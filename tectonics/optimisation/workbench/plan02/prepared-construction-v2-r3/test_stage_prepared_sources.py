"""Disposable standard-library controls. SOURCE ONLY until separately called.

No Atlas import, real plan/source access, construction or run queue invocation.
Every fixture lives in its own TemporaryDirectory; partial-output assertions run
before that test-owned fixture is cleaned by unittest. The stager never deletes.
"""
from dataclasses import replace
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('prepared_source_stager',
    Path(__file__).with_name('stage_prepared_sources.py'))
S = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = S
SPEC.loader.exec_module(S)


def encode(value):
    return (json.dumps(value, sort_keys=True, indent=2)+'\n').encode()


def digest(raw):
    return sha256(raw).hexdigest()


class Fixture:
    def __init__(self, base):
        self.base = base
        task = base/'task'
        self.box = task/'fidelity-integration-20261005/continuation-repair-20261013/optimisation-20261014/prepared-v2-r3'
        self.box.parent.mkdir(parents=True)
        self.sources = base/'source'
        self.sources.mkdir()
        self.handoff = base/'handoff'
        self.handoff.mkdir()
        self.raw = {'anchor.py': b'# source must never be imported\nraise RuntimeError("must not execute")\n',
                    'a.py': b'first-source\x00\xff\r\n', 'nested/b.bin': b'last-source\x00\x01\xff'}
        self.rows = {}
        for number, (name, raw) in enumerate(self.raw.items()):
            path = self.sources/(str(number)+'.txt')
            path.write_bytes(raw)
            self.rows[name] = {'source': str(path), 'sha256': digest(raw)}
        self.meta = []
        for role, path in (
                ('generation', base/'generation.json'),
                ('old_reviewed_inputs', base/'old.json'),
                ('I', self.box.parent/'runtime-integration-r1/manifest.json'),
                ('filtered', self.box.parent/'filtered-exact-r1/manifest.json'),
                ('heat', task/'fidelity-integration-20261005/heat-repair-20261007/continuation-preparation-r3.json')):
            path.parent.mkdir(parents=True, exist_ok=True)
            raw = encode({'fixture_metadata_only': role})
            path.write_bytes(raw)
            self.meta.append((role, path, digest(raw)))
        refs = {role: {'path': str(path), 'sha256': pin} for role, path, pin in self.meta}
        self.plan = dict(schema='atlas.private.prepared-source-copy-plan.v1',
            status='PREPARATION_ONLY_NO_COPY_OR_BUILD', route=S.ROUTE,
            future_box=str(self.box), target='composed-r1', files=self.rows,
            generation_predecessor=refs['generation'], retained_old_reviewed_inputs=refs['old_reviewed_inputs'],
            unavailable=['complete selected reviewed-inputs record', 'final generation'])
        self.selection = dict(route=S.ROUTE, layout={'future_box': str(self.box), 'target': 'composed-r1'},
                              files={'anchor.py': dict(self.rows['anchor.py'])})
        self.plan_path = base/'plan.json'
        self.refresh()
        self.policy = S.Policy(self.plan_path, self.plan_pin, self.box, task, self.handoff,
            self.index_pin, self.handoff_pin, self.preparer_pin, self.selection_pin,
            ((self.sources, 3),), tuple(self.meta), rows=3, selected=1,
            max_file_bytes=1024, max_source_bytes=4096, max_destination_path=384)

    def refresh(self):
        """Fixture-only explicit repin; production exposes no equivalent operation."""
        self.plan_path.write_bytes(encode(self.plan))
        self.plan_pin = digest(self.plan_path.read_bytes())
        contents = {'HANDOFF.md': b'DISPOSABLE FIXTURE, NO REVIEW ACCEPTANCE\n',
                    'prepare_generation.py': b'raise RuntimeError("must not import")\n',
                    'prepared-source-selection.json': encode(self.selection)}
        pins = {}
        for name, raw in contents.items():
            (self.handoff/name).write_bytes(raw)
            pins[name] = digest(raw)
        self.handoff_pin = pins['HANDOFF.md']
        self.preparer_pin = pins['prepare_generation.py']
        self.selection_pin = pins['prepared-source-selection.json']
        raw = encode({'schema': 'atlas.private.prepared-authoring-handoff-pins.v1', 'files': pins})
        (self.handoff/'HANDOFF-PINS.json').write_bytes(raw)
        self.index_pin = digest(raw)
        if hasattr(self, 'policy'):
            self.policy = replace(self.policy, plan_sha256=self.plan_pin, index_sha256=self.index_pin,
                                  selection_sha256=self.selection_pin)


class StagingControls(unittest.TestCase):
    def fixture(self):
        temp = tempfile.TemporaryDirectory(prefix='p02-stage-')
        self.addCleanup(temp.cleanup)
        return Fixture(Path(temp.name).resolve())

    def refused(self, fixture, reason, *, created=False, phase=None):
        with self.assertRaises(S.StageFailed) as caught:
            S.stage(fixture.policy)
        report = caught.exception.report
        # Full structured failures are retained by the caller's normal stdout log.
        print(json.dumps({'case': self.id(), 'expected_failure': report}, sort_keys=True))
        self.assertEqual(report['status'], 'PARTIAL_RETAINED' if created else 'REFUSED_NO_CREATE')
        self.assertEqual(report['destination_created'], created)
        self.assertFalse(report['post_copy_verified'])
        self.assertIn(reason, report['error']['message'])
        if phase:
            self.assertEqual(report['phase'], phase)
        if not created:
            self.assertFalse(fixture.box.exists())
        return report

    def test_exact_bytes_positive_and_existing_box_is_never_adopted(self):
        f = self.fixture()
        report = S.stage(f.policy)
        self.assertEqual(report['status'], 'STAGED_SOURCE_ONLY')
        self.assertEqual(report['copied_rows'], 3)
        self.assertTrue(report['post_copy_verified'])
        self.assertEqual({p.relative_to(f.box).as_posix() for p in f.box.rglob('*') if p.is_file()}, set(f.raw))
        for name, raw in f.raw.items():
            self.assertEqual((f.box/name).read_bytes(), raw)
            self.assertEqual(Path(f.rows[name]['source']).read_bytes(), raw)
        with self.assertRaises(S.StageFailed) as caught:
            S.stage(f.policy)
        self.assertEqual(caught.exception.report['status'], 'REFUSED_NO_CREATE')
        self.assertIn('exclusive absent', str(caught.exception))
        self.assertEqual((f.box/'a.py').read_bytes(), f.raw['a.py'])

    def test_plan_and_handoff_authentication_fail_before_creation(self):
        for victim in ('plan', 'HANDOFF.md', 'prepare_generation.py'):
            with self.subTest(victim=victim):
                f = self.fixture()
                path = f.plan_path if victim == 'plan' else f.handoff/victim
                path.write_bytes(path.read_bytes()+b'\nchanged')
                self.refused(f, 'SHA-256 mismatch')

    def test_late_source_drift_and_missing_metadata_refuse_before_creation(self):
        f = self.fixture()
        Path(f.rows['nested/b.bin']['source']).write_bytes(b'changed-last-source')
        report = self.refused(f, 'SHA-256 mismatch')
        self.assertEqual(report['attempted_files'], [])
        f = self.fixture()
        next(path for role, path, _ in f.meta if role == 'heat').unlink()
        self.refused(f, 'No such file' if sys.platform != 'win32' else 'cannot find')

    def test_exact_destination_source_roots_and_selected_row_membership(self):
        f = self.fixture()
        f.plan['future_box'] = str(f.box.parent/'other-box')
        f.refresh()
        self.refused(f, 'exact expected B')
        f = self.fixture()
        alien = f.base/'outside.txt'
        alien.write_bytes(f.raw['a.py'])
        f.rows['a.py']['source'] = str(alien)
        f.refresh()
        self.refused(f, 'outside exact allowed parent roots')
        f = self.fixture()
        f.rows['anchor.py']['sha256'] = '0'*64
        f.refresh()
        self.refused(f, 'selected input missing or altered')
        f = self.fixture()
        del f.rows['a.py']
        f.refresh()
        self.refused(f, 'exact selected row count')

    def test_names_prefix_case_alias_collisions_and_path_bounds(self):
        for names, reason in ((('../escape.py', 'b.bin'), 'noncanonical path component'),
                              (('a:stream', 'b.bin'), 'unsafe path component'),
                              (('CON.py', 'b.bin'), 'reserved path component'),
                              (('trailing.', 'b.bin'), 'noncanonical path component'),
                              (('Alpha', 'alpha'), 'destination collision'),
                              (('prefix', 'prefix/b.bin'), 'prefix collision')):
            with self.subTest(names=names):
                f = self.fixture()
                a, b = f.rows.pop('a.py'), f.rows.pop('nested/b.bin')
                f.rows[names[0]], f.rows[names[1]] = a, b
                f.refresh()
                self.refused(f, reason)
        f = self.fixture()
        f.rows['a.py'] = dict(f.rows['anchor.py'])
        f.refresh()
        self.refused(f, 'source alias/duplicate')
        f = self.fixture()
        f.policy = replace(f.policy, max_destination_path=len(str(f.box))+3)
        self.refused(f, 'path length')

    def test_source_reparse_ancestor_and_byte_caps(self):
        f = self.fixture()
        real_lstat = Path.lstat
        def reparse(path, *args, **kwargs):
            value = real_lstat(path, *args, **kwargs)
            if path == f.sources:
                values = {name: getattr(value, name) for name in
                          ('st_dev', 'st_ino', 'st_mode', 'st_size', 'st_mtime_ns', 'st_ctime_ns')}
                return SimpleNamespace(**values, st_file_attributes=0x400)
            return value
        with patch.object(Path, 'lstat', reparse):
            self.refused(f, 'symlink/reparse')
        for limit in ('max_file_bytes', 'max_source_bytes'):
            f = self.fixture()
            f.policy = replace(f.policy, **{limit: 5})
            self.refused(f, 'file byte cap')

    def test_copy_failure_keeps_partial_file_and_reports_no_success(self):
        f = self.fixture()
        def broken_write(path, raw):
            with path.open('xb') as stream:
                stream.write(raw[:3])
            raise OSError('injected disposable short-copy failure')
        with patch.object(S, '_write', broken_write):
            report = self.refused(f, 'injected disposable', created=True, phase='copy')
        self.assertEqual(report['copied_rows'], 0)
        self.assertEqual(len(report['attempted_files']), 1)
        self.assertEqual((f.box/report['attempted_files'][0]).read_bytes(), b'fir')
        for name, raw in f.raw.items():
            self.assertEqual(Path(f.rows[name]['source']).read_bytes(), raw)

    def test_post_copy_corruption_and_unexpected_entries_are_retained(self):
        for fault in ('corrupt_prior_copy', 'unexpected_entry'):
            with self.subTest(fault=fault):
                f = self.fixture()
                real_write = S._write
                seen = []
                def faulty_write(path, raw):
                    identity = real_write(path, raw)
                    seen.append(path)
                    if len(seen) == 3:
                        if fault == 'corrupt_prior_copy':
                            seen[0].write_bytes(b'CORRUPT')
                        else:
                            (f.box/'unexpected.txt').write_bytes(b'KEEP THIS FAILURE')
                    return identity
                with patch.object(S, '_write', faulty_write):
                    reason = 'SHA-256 mismatch' if fault == 'corrupt_prior_copy' else 'unexpected staged entry'
                    report = self.refused(f, reason, created=True, phase='post-copy-verification')
                self.assertEqual(report['copied_rows'], 3)
                self.assertTrue(f.box.exists())
                if fault == 'unexpected_entry':
                    self.assertEqual((f.box/'unexpected.txt').read_bytes(), b'KEEP THIS FAILURE')


class StatIdentityControls(unittest.TestCase):
    """Cross-API variability is allowed; within-API drift still refuses."""

    def fixture(self):
        temp = tempfile.TemporaryDirectory(prefix='p02-stat-')
        self.addCleanup(temp.cleanup)
        path = Path(temp.name).resolve()/'selected.bin'
        raw = b'bounded source snapshot\x00\xff\r\n'
        path.write_bytes(raw)
        return path, raw

    @staticmethod
    def view(value, **changes):
        fields = {name: getattr(value, name) for name in
                  ('st_dev', 'st_ino', 'st_mode', 'st_size', 'st_mtime_ns', 'st_ctime_ns')}
        fields['st_file_attributes'] = getattr(value, 'st_file_attributes', 0)
        fields.update(changes)
        return SimpleNamespace(**fields)

    def refusal(self, path, raw, reason, variant):
        with self.assertRaisesRegex(S.Refused, reason) as caught:
            S.pinned(path, digest(raw), len(raw))
        print(json.dumps({'case': self.id(), 'variant': variant,
                          'expected_failure': str(caught.exception)}, sort_keys=True))

    def test_stable_cross_api_ctime_and_attribute_difference_is_accepted(self):
        path, raw = self.fixture()
        pathname = path.lstat()
        real_fstat = S.os.fstat
        observed = []
        def different_api(fd):
            value = self.view(real_fstat(fd), st_ctime_ns=pathname.st_ctime_ns+100,
                              st_file_attributes=getattr(pathname, 'st_file_attributes', 0) ^ 0x20)
            observed.append(value)
            return value
        with patch.object(S.os, 'fstat', different_api):
            copied, identity = S.pinned(path, digest(raw), len(raw))
        self.assertEqual(copied, raw)
        self.assertEqual(len(observed), 2)
        self.assertNotEqual(observed[0].st_ctime_ns, pathname.st_ctime_ns)
        self.assertNotEqual(observed[0].st_file_attributes, getattr(pathname, 'st_file_attributes', 0))
        self.assertEqual(S.fingerprint(observed[0]), S.fingerprint(observed[1]))
        self.assertEqual(S.shared_fingerprint(observed[0]), S.shared_fingerprint(pathname))
        self.assertEqual(identity[1], S.fingerprint(path.lstat()))

    def test_changed_handle_fingerprint_during_read_refuses(self):
        for field in ('st_dev', 'st_ino', 'st_mode', 'st_size', 'st_mtime_ns',
                      'st_ctime_ns', 'st_file_attributes'):
            with self.subTest(field=field):
                path, raw = self.fixture()
                real_fstat = S.os.fstat
                calls = 0
                def changed_handle(fd):
                    nonlocal calls
                    calls += 1
                    value = self.view(real_fstat(fd))
                    if calls == 2:
                        setattr(value, field, getattr(value, field)+1)
                    return value
                with patch.object(S.os, 'fstat', changed_handle):
                    self.refusal(path, raw, 'source changed during read', field)
                self.assertEqual(calls, 2)

    def test_changed_path_and_same_bytes_replacement_refuse(self):
        for field in ('st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns', 'st_file_attributes'):
            with self.subTest(field=field):
                path, raw = self.fixture()
                real_ordinary = S.ordinary
                calls = 0
                def changed_path(candidate, kind):
                    nonlocal calls
                    chain, value = real_ordinary(candidate, kind)
                    if candidate == path:
                        calls += 1
                        if calls == 2:
                            value = self.view(value, **{field: getattr(value, field, 0)+1})
                    return chain, value
                with patch.object(S, 'ordinary', changed_path):
                    self.refusal(path, raw, 'source changed during read', field)
                self.assertEqual(path.read_bytes(), raw)
        path, raw = self.fixture()
        replacement = path.with_name('replacement.bin')
        replacement.write_bytes(raw)
        original_info = path.stat()
        S.os.utime(replacement, ns=(original_info.st_atime_ns, original_info.st_mtime_ns))
        real_ordinary = S.ordinary
        calls = 0
        def replace_before_postcheck(candidate, kind):
            nonlocal calls
            if candidate == path:
                calls += 1
                if calls == 2:
                    replacement.replace(path)
            return real_ordinary(candidate, kind)
        # The opened handle has closed before this ordinary() postcheck. The
        # real same-bytes replacement needs no Windows delete-sharing exception.
        with patch.object(S, 'ordinary', replace_before_postcheck):
            self.refusal(path, raw, 'source changed during read', 'real same-bytes replacement')
        self.assertEqual(path.read_bytes(), raw)
        self.assertFalse(replacement.exists())

    def test_opened_handle_must_match_path_and_be_ordinary(self):
        for field in ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_mode', 'reparse'):
            with self.subTest(field=field):
                path, raw = self.fixture()
                real_fstat = S.os.fstat
                def wrong_handle(fd):
                    value = self.view(real_fstat(fd))
                    if field == 'reparse':
                        value.st_file_attributes |= 0x400
                    else:
                        setattr(value, field, getattr(value, field)+1)
                    return value
                with patch.object(S.os, 'fstat', wrong_handle):
                    reason = 'not an ordinary file' if field == 'reparse' else 'source changed before open'
                    self.refusal(path, raw, reason, field)


if __name__ == '__main__':
    unittest.main(verbosity=2)
