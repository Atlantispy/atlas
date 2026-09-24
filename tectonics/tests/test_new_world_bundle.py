"""Synthetic portable lifecycle fixtures; no native physics or world generation.

The native loader/source/backend seams below are deliberately fake. Real native
completed/partial import and resume are covered by the owner's separate run.
"""
import copy
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock
import warnings
import zipfile

TOOLS = Path(__file__).resolve().parents[1] / 'tools'
sys.path.insert(0, str(TOOLS))
import new_world_bundle as bundle

job = bundle.job


def digest(value):
    return hashlib.sha256(job._encoded(value)).hexdigest()


class NewWorldBundleTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.world_path = self.root / 'original.atlas'
        self.write_zip(self.world_path, [('project.json', b'{"synthetic":true}'),
                                        ('arrays.sqlite', b'synthetic database, not native')])
        self.world_bytes = self.world_path.read_bytes()
        self.world = SimpleNamespace(manifest=dict(project_id='1' * 64,
            atlas_id='2' * 64, structure_id='3' * 64, motion_id='4' * 64,
            plan={'plan_id': '5' * 64}, title='Synthetic portable fixture'))
        self.sources = {'adapters': {'synthetic': '6' * 64},
                        'evolution': {'synthetic_runtime': '7' * 64}}
        self.backend = SimpleNamespace(OUTPUT_SCHEMA='synthetic-evolution-output.v1',
            METHOD='synthetic-no-physics', _digest=digest,
            check_initial=mock.Mock(side_effect=self.check_initial),
            prepare=mock.Mock(side_effect=AssertionError('must not sample or generate')),
            PreparedEvolution=mock.Mock(side_effect=AssertionError('must not restore physics owner')))
        self.loader = self.enterContext(mock.patch.object(bundle.projects, 'load_project',
                                                          side_effect=self.load_synthetic))
        self.enterContext(mock.patch.object(job, '_backend', return_value=self.backend))
        self.source_check = self.enterContext(mock.patch.object(job, '_sources',
                                             side_effect=lambda _: copy.deepcopy(self.sources)))
        self.jobs_root = self.root / 'jobs'
        self.jobs_root.mkdir()
        self.ident = 'a' * 32
        self.directory = self.make_job(self.ident, count=1, state='partial')
        self.archive = self.root / 'portable.atlas'

    @staticmethod
    def write_zip(path, entries, compression=zipfile.ZIP_STORED):
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', UserWarning)  # Intentional duplicate-member fixture.
            with zipfile.ZipFile(path, 'w', compression=compression) as archive:
                for name, body in entries:
                    archive.writestr(name, body)

    def load_synthetic(self, path):
        self.assertEqual(Path(path).read_bytes(), self.world_bytes)
        return self.world

    def check_initial(self, initial):
        body = {k: v for k, v in initial.items() if k != 'initial_id'}
        self.assertEqual(initial['initial_id'], digest(body))
        self.assertEqual(initial['source_binding'], self.sources['evolution'])

    def make_job(self, ident, *, count, state, error=None):
        directory = self.jobs_root / ident
        directory.mkdir()
        (directory / 'input.atlas').write_bytes(self.world_bytes)
        request = dict(schema=job.REQUEST_SCHEMA, producer_id=job.PRODUCER, job_id=ident,
            input=dict(sha256=hashlib.sha256(self.world_bytes).hexdigest(), size_bytes=len(self.world_bytes)),
            options={'synthetic': True}, schedule_s=[0., 1.], max_wall_seconds=30.,
            sources=copy.deepcopy(self.sources))
        request_body = job._encoded(request)
        (directory / 'request.json').write_bytes(request_body)
        initial = dict(schema='synthetic-initial.v1', max_elapsed_s=2.,
            source_binding=copy.deepcopy(self.sources['evolution']),
            **{k: self.world.manifest[k] for k in ('project_id', 'atlas_id', 'structure_id', 'motion_id')},
            plan_id=self.world.manifest['plan']['plan_id'],
            native_input=dict(epoch_time_s=10., frame_id='synthetic-frame',
                              epoch_id='synthetic-epoch', datum_id='synthetic-datum'))
        initial['initial_id'] = digest(initial)
        initial_body = job._encoded(initial)
        (directory / 'initial.json').write_bytes(initial_body)
        prefix = dict(schema=job.PREFIX_SCHEMA, job_id=ident,
            request_sha256=hashlib.sha256(request_body).hexdigest(),
            initial_sha256=hashlib.sha256(initial_body).hexdigest(), outputs=[])
        for index in range(count):
            result = dict(schema=self.backend.OUTPUT_SCHEMA, method=self.backend.METHOD,
                initial_id=initial['initial_id'], project_id=initial['project_id'],
                elapsed_s=float(index), time_s=10. + index, values=[index, index + 1],
                **{k: initial['native_input'][k] for k in ('frame_id', 'epoch_id', 'datum_id')})
            result['output_id'] = digest(result)
            result['accounted_workspace_peak_bytes'] = 0
            output = dict(schema=job.OUTPUT_SCHEMA, request_sha256=prefix['request_sha256'],
                initial_sha256=prefix['initial_sha256'], index=index,
                elapsed_s=float(index), result=result)
            body = job._encoded(output)
            name = f'output-{index:04d}.json'
            (directory / name).write_bytes(body)
            prefix['outputs'].append(dict(index=index, elapsed_s=float(index), file=name,
                size_bytes=len(body), sha256=hashlib.sha256(body).hexdigest(), output_id=result['output_id']))
        job._control(directory / 'prefix.json', prefix)
        job._control(directory / 'status.json', dict(schema=job.SCHEMA, producer_id=job.PRODUCER,
            job_id=ident, state=state, attempt=7, completed_outputs=count, total_outputs=2,
            computed_outputs=count, restored_outputs=0, error=error,
            timings=dict(prepare_s=.1, physics_s=.2, store_s=.3, restore_s=.4, elapsed_s=1.)))
        return directory

    def save(self, path=None, **kwargs):
        return bundle.save_bundle(path or self.archive, self.world_path, jobs_root=self.jobs_root,
                                  job_ids=kwargs.pop('job_ids', [self.ident]), **kwargs)

    def entries(self):
        with zipfile.ZipFile(self.archive) as archive:
            return [(entry.filename, archive.read(entry)) for entry in archive.infolist()]

    def rewrite(self, name, changes, *, recalculate=False):
        entries = dict(self.entries())
        changes(entries)
        if recalculate:
            manifest = json.loads(entries['bundle.json'])
            for entry in [manifest['world']] + [e for item in manifest['jobs'] for e in item['files']]:
                entry.update(size_bytes=len(entries[entry['file']]),
                             sha256=hashlib.sha256(entries[entry['file']]).hexdigest())
            manifest.pop('bundle_id')
            manifest['bundle_id'] = hashlib.sha256(job._encoded(manifest, bundle.MAX_MANIFEST)).hexdigest()
            entries['bundle.json'] = job._encoded(manifest, bundle.MAX_MANIFEST)
        path = self.root / name
        self.write_zip(path, list(entries.items()))
        return path

    def assert_refused(self, code, function, *args, **kwargs):
        with self.assertRaises(Exception) as caught:
            function(*args, **kwargs)
        self.assertEqual(getattr(caught.exception, 'code', None), code)

    def test_completed_and_cancelled_roundtrip_preserves_bytes_deduplicates_and_never_runs(self):
        completed = self.make_job('b' * 32, count=2, state='completed')
        cancelled = self.make_job('c' * 32, count=1, state='cancelled',
            error={'code': 'TIME_LIMIT', 'message': job.MESSAGES['TIME_LIMIT']})
        for directory in (completed, cancelled):
            (directory / 'cancel-0007.json').write_bytes(b'not portable process state')
            (directory / 'output-0255.json').write_bytes(b'uncommitted orphan')
            (directory / '.owned.tmp').write_bytes(b'incomplete temporary')
        result = self.save(job_ids=[cancelled.name, completed.name])
        self.assertEqual((result['stored_world_copies'], result['avoided_frozen_world_copies']), (1, 2))
        expected = {'bundle.json', 'world.atlas'}
        for directory, count in ((completed, 2), (cancelled, 1)):
            expected.update(f'jobs/{directory.name}/{name}' for name in
                (*bundle.FIXED, *(f'output-{i:04d}.json' for i in range(count))))
        with zipfile.ZipFile(self.archive) as archive:
            self.assertEqual(set(archive.namelist()), expected)
            self.assertTrue(all(info.compress_type == zipfile.ZIP_STORED for info in archive.infolist()))
            self.assertEqual(archive.read('world.atlas'), self.world_bytes)
        before = self.archive.read_bytes()
        inspected = bundle.inspect_bundle(self.archive)
        target = self.root / 'restored'
        loaded = bundle.load_bundle(self.archive, target)
        self.assertEqual(inspected, loaded)
        self.assertFalse(loaded['generated_on_open'])
        self.assertEqual(loaded['bundle_id'], result['bundle_id'])
        self.assertEqual(self.archive.read_bytes(), before)
        self.assertEqual((target / 'world.atlas').read_bytes(), self.world_bytes)
        self.assertEqual(json.loads((target / 'ready.json').read_bytes()), loaded)
        for source, count in ((completed, 2), (cancelled, 1)):
            restored = target / 'jobs' / source.name
            names = {'input.atlas', *bundle.FIXED, *(f'output-{i:04d}.json' for i in range(count))}
            self.assertEqual({p.name for p in restored.iterdir()}, names)
            for name in names:
                self.assertEqual((restored / name).read_bytes(), (source / name).read_bytes())
        self.assertEqual([item['attempt'] for item in loaded['jobs']], [7, 7])
        self.assertEqual(loaded['jobs'][1]['error']['code'], 'TIME_LIMIT')
        self.backend.prepare.assert_not_called()
        self.backend.PreparedEvolution.assert_not_called()
        self.assertGreater(self.backend.check_initial.call_count, 0)

    def test_prepared_partial_and_empty_prefix_restore_without_status_normalisation(self):
        empty = self.make_job('d' * 32, count=0, state='cancelled',
            error={'code': 'CANCELLED', 'message': job.MESSAGES['CANCELLED']})
        self.save(job_ids=[self.ident, empty.name])
        target = self.root / 'partial-restore'
        result = bundle.load_bundle(self.archive, target)
        self.assertEqual([(x['state'], x['completed_outputs']) for x in result['jobs']],
                         [('partial', 1), ('cancelled', 0)])
        for source in (self.directory, empty):
            for name in bundle.FIXED:
                self.assertEqual((target / 'jobs' / source.name / name).read_bytes(),
                                 (source / name).read_bytes())

    def test_legacy_and_initial_only_bundle_loading_do_not_need_evolution_sources(self):
        with mock.patch.object(job, '_backend', side_effect=AssertionError('no evolution for initial-only')):
            legacy = bundle.inspect_bundle(self.world_path)
            loaded = bundle.load_bundle(self.world_path, self.root / 'legacy')
            self.assertEqual(legacy, loaded)
            self.assertEqual(loaded['kind'], 'initial-only')
            self.assertEqual(loaded['jobs'], [])
            self.assertEqual((self.root / 'legacy' / 'world.atlas').read_bytes(), self.world_bytes)
            bundle.save_bundle(self.archive, self.world_path)
            self.assertEqual(bundle.inspect_bundle(self.archive)['kind'], 'combined')
        self.source_check.assert_not_called()

    def test_existing_file_and_directory_refuse_without_replacing_originals(self):
        self.save()
        original = self.archive.read_bytes()
        self.assert_refused('FILE_EXISTS', self.save)
        self.assertEqual(self.archive.read_bytes(), original)
        target = self.root / 'existing'
        target.mkdir()
        (target / 'keep').write_bytes(b'old world remains')
        self.assert_refused('FILE_EXISTS', bundle.load_bundle, self.archive, target)
        self.assertEqual({p.name for p in target.iterdir()}, {'keep'})
        self.assertEqual((target / 'keep').read_bytes(), b'old world remains')

    def test_malformed_duplicate_traversal_compressed_and_missing_members_refuse(self):
        self.save()
        entries = self.entries()
        cases = {
            'duplicate': (entries + [entries[0]], zipfile.ZIP_STORED),
            'traversal': (entries + [('../escaped', b'never extract')], zipfile.ZIP_STORED),
            'unexpected': (entries + [('extra.json', b'{}')], zipfile.ZIP_STORED),
            'compressed': (entries, zipfile.ZIP_DEFLATED),
            'missing': ([e for e in entries if not e[0].endswith('output-0000.json')], zipfile.ZIP_STORED),
        }
        for name, (members, compression) in cases.items():
            with self.subTest(case=name):
                source = self.root / f'{name}.atlas'
                self.write_zip(source, members, compression)
                destination = self.root / f'{name}-restore'
                self.assert_refused('INVALID_BUNDLE', bundle.load_bundle, source, destination)
                self.assertFalse(destination.exists())
        malformed = self.root / 'malformed.atlas'
        malformed.write_bytes(b'not a zip archive')
        self.assert_refused('BUNDLE_LIMIT', bundle.inspect_bundle, malformed)
        self.assertFalse((self.root / 'escaped').exists())

    def test_oversized_control_member_is_refused_before_native_load(self):
        self.save()
        name = f'jobs/{self.ident}/request.json'
        path = self.rewrite('oversized.atlas', lambda entries: entries.__setitem__(name, b'x' * 65537),
                            recalculate=True)
        self.loader.reset_mock()
        self.assert_refused('BUNDLE_LIMIT', bundle.inspect_bundle, path)
        self.loader.assert_not_called()

    def test_archive_integrity_and_scientific_output_identity_are_both_checked(self):
        self.save()
        name = f'jobs/{self.ident}/output-0000.json'
        def corrupt(entries):
            output = json.loads(entries[name])
            output['result']['values'][0] = 99
            entries[name] = job._encoded(output)
        bad_digest = self.rewrite('bad-digest.atlas', corrupt)
        self.assert_refused('INVALID_BUNDLE', bundle.inspect_bundle, bad_digest)
        def forged_transport(entries):
            corrupt(entries)
            prefix_name = f'jobs/{self.ident}/prefix.json'
            prefix = json.loads(entries[prefix_name])
            prefix['outputs'][0].update(size_bytes=len(entries[name]),
                                       sha256=hashlib.sha256(entries[name]).hexdigest())
            entries[prefix_name] = job._encoded(prefix) + b'\n'
        # Transport hashes alone cannot bless an altered scientific result.
        forged = self.rewrite('forged-output.atlas', forged_transport, recalculate=True)
        self.assert_refused('INVALID_BUNDLE', bundle.inspect_bundle, forged)

    def test_busy_checkpoint_refuses_without_cancellation_or_output(self):
        before = (self.directory / 'status.json').read_bytes()
        with job.jobs._lock(self.directory / 'worker.lock'):
            self.assert_refused('RUN_BUSY', self.save)
        self.assertFalse(self.archive.exists())
        self.assertEqual((self.directory / 'status.json').read_bytes(), before)
        self.assertEqual(list(self.directory.glob('cancel-*.json')), [])

    def test_wrong_world_current_source_and_archive_source_drift_refuse(self):
        self.save()
        original = self.archive.read_bytes()
        refused_path = self.root / 'refused.atlas'
        frozen = self.directory / 'input.atlas'
        frozen.write_bytes(b'a different frozen world')
        self.assert_refused('BUNDLE_WORLD_MISMATCH', self.save, refused_path)
        frozen.write_bytes(self.world_bytes)
        self.sources['adapters']['synthetic'] = 'f' * 64
        self.assert_refused('SOURCE_MISMATCH', self.save, refused_path)
        destination = self.root / 'incompatible'
        self.assert_refused('SOURCE_MISMATCH', bundle.load_bundle, self.archive, destination)
        self.assertFalse(destination.exists())
        self.assertEqual(self.archive.read_bytes(), original)

    def test_stale_active_inconsistent_counts_and_incomplete_preparation_refuse(self):
        status_path = self.directory / 'status.json'
        original = json.loads(status_path.read_bytes())
        changes = [('UNSTABLE_JOB', {'state': 'running'}),
                   ('INVALID_BUNDLE', {'completed_outputs': 0}),
                   ('INVALID_BUNDLE', {'state': 'completed'}),
                   ('UNSTABLE_JOB', {'computed_outputs': 0, 'restored_outputs': 0})]
        for code, patch in changes:
            with self.subTest(change=patch):
                job._control(status_path, dict(original, **patch))
                before = status_path.read_bytes()
                self.assert_refused(code, self.save)
                self.assertEqual(status_path.read_bytes(), before)
                self.assertFalse(self.archive.exists())
        job._control(status_path, original)
        (self.directory / 'initial.json').unlink()
        self.assert_refused('INITIAL_INCOMPLETE', self.save)

    def test_publication_failure_cleans_only_new_owned_files(self):
        self.save()
        original_publish = bundle._publish_copy
        target = self.root / 'failed-restore'
        def fail_after_world(source, destination, limit):
            if destination.name == 'request.json':
                raise OSError('synthetic publication failure')
            return original_publish(source, destination, limit)
        with mock.patch.object(bundle, '_publish_copy', side_effect=fail_after_world):
            with self.assertRaises(OSError):
                bundle.load_bundle(self.archive, target)
        self.assertFalse(target.exists())
        self.assertEqual(self.world_path.read_bytes(), self.world_bytes)

    def test_cli_strict_inputs_and_path_free_errors(self):
        answer, code = bundle.response(['save', '--file', str(self.archive), '--world',
            str(self.world_path), '--root', str(self.jobs_root)],
            io.BytesIO(json.dumps({'job_ids': [self.ident]}).encode()))
        self.assertEqual((answer['schema'], answer['status'], code), (bundle.RESPONSE_SCHEMA, 'ok', 0))
        for argv, body in [(['inspect', '--file', str(self.archive), '--file', str(self.archive)], b''),
                           (['save', '--file', str(self.archive), '--world', str(self.world_path)],
                            b'{"job_ids":[],"job_ids":[]}'),
                           (['save', '--file', str(self.archive), '--world', str(self.world_path)],
                            b'x' * 65537), (['unsupported'], b'')]:
            with self.subTest(argv=argv, body_size=len(body)):
                failure, exit_code = bundle.response(argv, io.BytesIO(body))
                self.assertEqual((failure['status'], exit_code), ('error', 2))
                self.assertNotIn(str(self.root), json.dumps(failure))
        with mock.patch.object(bundle.projects, 'load_project',
                side_effect=bundle.ContractError('SOURCE_MISMATCH', 'PRIVATE_PATH')):
            failure, code = bundle.response(['inspect', '--file', str(self.archive)], io.BytesIO())
        self.assertEqual((failure['error']['code'], code), ('SOURCE_MISMATCH', 2))
        self.assertNotIn('PRIVATE_PATH', json.dumps(failure))


if __name__ == '__main__':
    unittest.main()
