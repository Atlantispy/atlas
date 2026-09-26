"""Tests of the read-only current-evidence checker, not tests of Atlas's generator."""
from __future__ import annotations

import contextlib
from copy import deepcopy
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from tools import check_current_evidence as evidence

TOOL = b'print("tool")\n'
ADAPTER = b'VALUE = 1\n'


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def encode(value) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + '\n').encode()


class CurrentEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'repo'
        self.write('pkg/tools/tool.py', TOOL)
        self.write('pkg/tools/adapter.py', ADAPTER)
        self.receipt = {
            'tool_sha256': sha(TOOL),
            'sources': {'adapters': {'adapter.py': sha(ADAPTER)}, 'native_execution_id': 'f' * 64},
            'output_ids': ['e' * 64],
            'job_id': '7' * 32,
        }
        self.write('pkg/evidence/current.json', encode(self.receipt))
        self.write('pkg/evidence/old.json', encode({'tool_sha256': 'a' * 64}))
        self.write('pkg/evidence/replaced.json', b'{"status": "PASS"}\n')
        self.write('pkg/evidence/wrong.json', b'{"status": "FAIL"}\n')
        self.register = {'schema': evidence.SCHEMA, 'scope': 'synthetic fixture', 'records': [
            dict(id='current', path='pkg/evidence/current.json', status='current', note='fixture',
                 bindings=[{'pointer': '/tool_sha256', 'file': 'pkg/tools/tool.py'},
                           {'pointer': '/sources/adapters/{key}', 'file': 'pkg/tools/{key}'}],
                 not_checked=[{'pointer': '/sources/native_execution_id', 'kind': 'runtime',
                               'reason': 'native identity'},
                              {'pointer': '/output_ids/*', 'kind': 'artefact', 'reason': 'not in repository'}],
                 limits=['synthetic only']),
            dict(id='old', path='pkg/evidence/old.json', status='historical', note='older code'),
            dict(id='replaced', path='pkg/evidence/replaced.json', status='superseded',
                 superseded_by='current', note='replaced'),
            dict(id='wrong', path='pkg/evidence/wrong.json', status='invalid', note='faulty harness'),
        ]}
        self.pin()

    def write(self, relative, data):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def pin(self):
        # Stands in for an explicit, reviewed register update; the checker never does this.
        for record in self.register['records']:
            record['sha256'] = sha((self.root / record['path']).read_bytes())

    def record(self, rid):
        return next(record for record in self.register['records'] if record['id'] == rid)

    def rewrite_receipt(self, change):
        change(self.receipt)
        self.write('pkg/evidence/current.json', encode(self.receipt))
        self.pin()

    def check(self):
        return evidence.check(self.root, self.register)

    def assertFails(self, *fragments):
        failures = self.check()[0]
        self.assertTrue(any(all(f in failure for f in fragments) for failure in failures), failures)

    def assertRefused(self, change):
        changed = deepcopy(self.register)
        change(changed)
        with self.assertRaises(evidence.RegisterError):
            evidence.check(self.root, changed)

    def test_unchanged_inputs_pass_and_every_current_record_is_visited(self):
        self.write('pkg/evidence/second.json', encode(self.receipt))
        self.register['records'].append(dict(deepcopy(self.record('current')), id='second',
                                             path='pkg/evidence/second.json'))
        self.pin()
        original = deepcopy(self.register)
        failures, visited = self.check()
        self.assertEqual(failures, [])
        self.assertEqual(self.register, original)
        self.assertEqual(set(visited), {record['id'] for record in self.register['records']})
        self.assertTrue(all(summary['ok'] for summary in visited.values()))
        for rid in ('current', 'second'):
            self.assertEqual((visited[rid]['bindings'], visited[rid]['files']), (2, 2))
            self.assertEqual(visited[rid]['not_checked'], {'runtime': 1, 'artefact': 1})

    def test_changed_source_fails_with_file_level_diagnostic(self):
        self.write('pkg/tools/tool.py', TOOL + b'# edited\n')
        failures, visited = self.check()
        self.assertEqual(len(failures), 1, failures)
        for fragment in ('current: pkg/tools/tool.py changed', 'pkg/evidence/current.json',
                         '/tool_sha256', sha(TOOL), 'successor receipt', 'reclassify'):
            self.assertIn(fragment, failures[0])
        self.assertFalse(visited['current']['ok'])
        # Historical, superseded and invalid records do not fail because code moved on.
        self.assertTrue(all(visited[rid]['ok'] for rid in ('old', 'replaced', 'wrong')))

    def test_missing_source_fails(self):
        (self.root / 'pkg/tools/adapter.py').unlink()
        self.assertFails('current: pkg/tools/adapter.py: missing file', '/sources/adapters/adapter.py')

    def test_missing_registered_records_fail(self):
        for record in self.register['records']:
            with self.subTest(record=record['id']):
                path = self.root / record['path']
                original = path.read_bytes()
                path.unlink()
                try:
                    self.assertFails(f"{record['id']}: {record['path']}: missing file")
                finally:
                    path.write_bytes(original)
        self.assertRefused(lambda changed: changed['records'][2].update(superseded_by='absent'))

    def test_malformed_digests_fail(self):
        for bad in ('A' * 64, 'a' * 63, 'g' * 64, 42, None, ['a' * 64]):
            with self.subTest(value=bad):
                self.rewrite_receipt(lambda receipt: receipt.update(tool_sha256=bad))
                self.assertFails('/tool_sha256 holds a malformed digest')
        self.rewrite_receipt(lambda receipt: receipt.update(tool_sha256=sha(TOOL)))
        self.rewrite_receipt(lambda receipt: receipt['sources'].update(native_execution_id='runtime-7'))
        self.assertFails('/sources/native_execution_id holds a malformed digest')
        for bad in ('A' * 64, 'a' * 63, None):
            with self.subTest(register_sha256=bad):
                self.assertRefused(lambda changed: changed['records'][1].update(sha256=bad))

    def test_undeclared_digest_fields_are_never_silently_omitted(self):
        for field, value in (('extra_sha256', sha(TOOL)), ('extra', 'b' * 64), ('extra_sha256', 'short')):
            with self.subTest(field=field, value=value):
                self.rewrite_receipt(lambda receipt: receipt.update({field: value}))
                self.assertFails(f'/{field} is an unclassified digest-bearing field')
                self.rewrite_receipt(lambda receipt: receipt.pop(field))

    def test_native_execution_id_is_never_checked_as_a_file_hash(self):
        # Even a value equal to a file digest cannot turn an execution identity into a binding.
        self.rewrite_receipt(lambda receipt: receipt['sources'].update(native_execution_id=sha(TOOL)))
        current = self.record('current')
        current['not_checked'].pop(0)
        current['bindings'].append({'pointer': '/sources/native_execution_id', 'file': 'pkg/tools/tool.py'})
        with self.assertRaises(evidence.RegisterError):
            self.check()
        current['bindings'][-1] = {'pointer': '/sources/{key}', 'file': 'pkg/tools/{key}'}
        failures, visited = self.check()
        self.assertTrue(any('/sources/native_execution_id is an identity' in f for f in failures), failures)
        self.assertFalse(visited['current']['ok'])

    def test_path_escape_and_non_portable_references_are_refused(self):
        (self.root.parent / 'outside.py').write_bytes(TOOL)
        for path in ('../outside.py', '/outside.py', 'C:/outside.py', 'pkg\\tools\\tool.py',
                     'pkg/../outside.py', './pkg/tools/tool.py', 'pkg//tools/tool.py', '',
                     'pkg/tools/tool.py.', 'pkg/tools/NUL', 'pkg/tools/tool.py:stream', 'pkg/ tools/tool.py'):
            with self.subTest(path=path):
                self.assertRefused(lambda changed: changed['records'][1].update(path=path))
                self.assertRefused(lambda changed: changed['records'][0]['bindings'][0].update(file=path))
        for key in ('../../outside.py', 'NUL', 'tool.py.'):
            with self.subTest(receipt_key=key):
                self.rewrite_receipt(lambda receipt: receipt['sources']['adapters'].update({key: sha(TOOL)}))
                self.assertFails('refused repository-relative path')
                self.rewrite_receipt(lambda receipt: receipt['sources']['adapters'].pop(key))

    def test_directory_link_or_junction_is_refused(self):
        alias = self.root / 'pkg/linked'
        try:
            if os.name == 'nt':
                subprocess.run(['cmd', '/c', 'mklink', '/J', str(alias), str(self.root / 'pkg/tools')],
                               capture_output=True, check=True)
            else:
                alias.symlink_to(self.root / 'pkg/tools', target_is_directory=True)
        except (OSError, subprocess.CalledProcessError) as exc:
            self.skipTest(f'OS cannot create a directory alias: {exc}')
        self.record('current')['bindings'][0]['file'] = 'pkg/linked/tool.py'
        self.assertFails('pkg/linked/tool.py: symlink or reparse point refused')

    def test_file_symlink_is_refused(self):
        link = self.root / 'pkg/tools/alias.py'
        try:
            link.symlink_to(self.root / 'pkg/tools/tool.py')
        except (NotImplementedError, OSError):
            self.skipTest('this environment cannot create a test symlink')
        self.record('current')['bindings'][0]['file'] = 'pkg/tools/alias.py'
        self.assertFails('pkg/tools/alias.py: symlink or reparse point refused')

    def test_historical_evidence_survives_code_change_but_not_rewriting(self):
        self.write('pkg/tools/tool.py', b'print("moved on")\n')
        failures, visited = self.check()
        self.assertTrue(failures and all(f.startswith('current: ') for f in failures), failures)
        self.assertTrue(all(visited[rid]['ok'] for rid in ('old', 'replaced', 'wrong')))
        path = self.root / 'pkg/evidence/old.json'
        path.write_bytes(path.read_bytes().replace(b'"a', b'"b'))
        self.assertFails('old: pkg/evidence/old.json is not the classified version',
                         'must not be rewritten silently')

    def test_statuses_and_supersession_are_enforced(self):
        changes = {
            'unknown status': lambda r: r['records'][1].update(status='Current'),
            'missing successor': lambda r: r['records'][2].pop('superseded_by'),
            'self successor': lambda r: r['records'][2].update(superseded_by='replaced'),
            'invalid successor': lambda r: r['records'][2].update(superseded_by='wrong'),
            'historical successor field': lambda r: r['records'][1].update(superseded_by='current'),
            'cycle': lambda r: (r['records'][1].update(status='superseded', superseded_by='replaced'),
                                r['records'][2].update(superseded_by='old')),
            'current without limits': lambda r: r['records'][0].pop('limits'),
            'current without bindings': lambda r: r['records'][0].update(bindings=[]),
            'unknown kind': lambda r: r['records'][0]['not_checked'][0].update(kind='trusted'),
            'empty reason': lambda r: r['records'][0]['not_checked'][0].update(reason=' '),
            'capture mismatch': lambda r: r['records'][0]['bindings'][1].update(file='pkg/tools/x.py'),
            'duplicate id': lambda r: r['records'][3].update(id='old'),
            'duplicate path': lambda r: r['records'][3].update(path='pkg/evidence/old.json'),
            'unknown field': lambda r: r.update(repin=True),
            'wrong schema': lambda r: r.update(schema='other'),
            'no records': lambda r: r.update(records=[]),
        }
        for name, change in changes.items():
            with self.subTest(name):
                self.assertRefused(change)

    def test_current_claims_cannot_rest_on_invalid_or_superseded_evidence(self):
        for rid, relative, status in (('wrong', 'pkg/evidence/wrong.json', 'invalid'),
                                      ('replaced', 'pkg/evidence/replaced.json', 'superseded')):
            with self.subTest(rid):
                digest = sha((self.root / relative).read_bytes())
                self.rewrite_receipt(lambda receipt: receipt.update(report_sha256=digest))
                self.record('current')['bindings'].append({'pointer': '/report_sha256', 'file': relative})
                self.assertFails(f'relies on {status} evidence {relative} ({rid})')
                self.record('current')['bindings'].pop()
                self.rewrite_receipt(lambda receipt: receipt.pop('report_sha256'))

    def test_stale_or_overlapping_rules_fail(self):
        self.record('current')['bindings'].append({'pointer': '/absent_sha256', 'file': 'pkg/tools/tool.py'})
        self.assertFails('bindings /absent_sha256 matches nothing')
        self.record('current')['bindings'].pop()
        self.record('current')['not_checked'].append(
            {'pointer': '/tool_sha256', 'kind': 'artefact', 'reason': 'overlap'})
        self.assertFails('/tool_sha256 is classified by both')

    def test_strict_json_is_required(self):
        for body in (b'{"tool_sha256": "x", "tool_sha256": "y"}', b'{"value": NaN}',
                     b'{"value": 1e999}', b'{"nested": [-1e999]}',
                     b'\xef\xbb\xbf{}', b'{', b'\xff'):
            with self.subTest(body=body):
                self.write('pkg/evidence/current.json', body)
                self.pin()
                self.assertFails('invalid strict JSON')
        self.write('register.json', b'{"schema": 1, "schema": 2}')
        with self.assertRaises(evidence.RegisterError):
            evidence.load_register(self.root, 'register.json')

    def test_crlf_only_difference_is_explained_but_still_fails(self):
        self.write('pkg/tools/tool.py', TOOL.replace(b'\n', b'\r\n'))
        self.assertFails('pkg/tools/tool.py changed', 'Only CRLF line endings differ')

    def test_oversized_file_is_refused(self):
        with patch.object(evidence, 'MAX_FILE_BYTES', 8):
            self.assertFails('exceeds the 8-byte check limit')

    def test_cli_is_read_only_and_states_its_limits(self):
        self.write('pkg/evidence/register.json', encode(self.register))
        arguments = ['--root', str(self.root), '--register', 'pkg/evidence/register.json']

        def snapshot():
            return {p.relative_to(self.root): p.read_bytes() if p.is_file() else None
                    for p in self.root.rglob('*')}

        before = snapshot()
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(evidence.main(arguments), 0)
        self.assertEqual(snapshot(), before)
        for fragment in ('not checked: 1 artefact, 1 runtime', 'limit: synthetic only',
                         'no runtime, native-execution, platform or scientific verification'):
            self.assertIn(fragment, output.getvalue())
        self.write('pkg/tools/tool.py', b'changed\n')
        before = snapshot()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()) as errors:
            self.assertEqual(evidence.main(arguments), 1)
            self.assertEqual(evidence.main(['--root', str(self.root / 'absent')]), 1)
            self.assertEqual(evidence.main(['--root', str(self.root)]), 1)
        self.assertEqual(snapshot(), before)
        self.assertIn('No receipt, register or source file was modified', errors.getvalue())

    def test_checked_in_register_passes_and_visits_every_current_record(self):
        repository = Path(__file__).resolve().parents[1]
        register = evidence.load_register(repository)
        failures, visited = evidence.check(repository, register)
        self.assertEqual(failures, [])
        current = [record for record in register['records'] if record['status'] == 'current']
        self.assertTrue(current)
        self.assertEqual({rid for rid, s in visited.items() if s['status'] == 'current'},
                         {record['id'] for record in current})
        self.assertLessEqual({'new-world-s7-r2', 'new-world-bundle-r2'}, set(visited))
        # Fixed historical runs cannot become current by checking only unchanged
        # adapter files while their native/integration dependencies have moved on.
        for rid in ('new-world-s7-r2', 'new-world-bundle-r2', 'new-world-motion-frame-r2'):
            self.assertEqual(visited[rid]['status'], 'historical')
        for record in current:
            self.assertGreater(visited[record['id']]['bindings'], 0)
            # Native execution identities stay explicitly unverified, never file-checked.
            for rule in record['not_checked']:
                if rule['pointer'].endswith('native_execution_id'):
                    self.assertEqual(rule['kind'], 'runtime')
            self.assertFalse(any(rule['pointer'].endswith('_id') for rule in record['bindings']))


if __name__ == '__main__':
    unittest.main()
