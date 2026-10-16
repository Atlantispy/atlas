"""Route (1) stage launcher controls: preflight, guard postcheck, step order and stage statuses.

Stand-in processes only; the real stages are the synthetic run and the smoke.
"""
import json
import os
import sys
import tempfile
import unittest
from hashlib import sha256
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE)]

import launch_fresh_interval as L
import launch_monitored_interval as LM
import reopen_fresh_restart as RF
import run_fresh_interval as F
import run_prepared_restart as RUN


def key(text):
    return sha256(text.encode()).hexdigest()


def encoded(row):
    return json.dumps(row, sort_keys=True, separators=(',', ':')).encode()


class StageFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='lf-', dir=HERE)
        self.folder = Path(self.temp.name)
        native = self.folder/'src'/'atlas_tectonics'
        native.mkdir(parents=True)
        (native/'__init__.py').write_text('# synthetic\n', encoding='utf8')
        helper = self.folder/'fixture_stage_helper.py'
        helper.write_text('VALUE = 1\n', encoding='utf8')
        self.attempt = self.folder/'attempt'
        self.attempt.mkdir()
        pinned = {HERE/name for name in L.PINNED} | {helper, native/'__init__.py'}
        manifest = self.folder/'manifest.json'
        relative = lambda path: Path(path).relative_to(HERE).as_posix()
        manifest.write_bytes(encoded({'files': {relative(p): RUN.file_hash(p) for p in pinned},
                                      'source_hashes': {'atlas_tectonics/__init__.py': RUN.file_hash(native/'__init__.py')},
                                      'data_only': {}, F.QUERY_STORE_FLAG: 'files'}))
        row = {'schema': F.PROFILE_SCHEMA, 'workspace': str(HERE),
               'source_manifest': {'path': relative(manifest), 'sha256': RUN.file_hash(manifest)},
               'native_root': relative(self.folder/'src'), 'import_roots': [relative(self.folder), '.'],
               'modules': {name: relative(helper) for name in F.FRESH_MODULES},
               'advance_driver': {'module': F.DRIVER, 'path': relative(helper), 'sha256': RUN.file_hash(helper)},
               'output_directory': str(self.attempt), 'store_directory': str(self.folder/'store'),
               'completed_query_directory': relative(self.folder/'queries'),
               'completed_query_limits': {'max_entries': 10, 'max_store_bytes': 1 << 20}}
        self.profile_path = self.folder/'profile.json'
        self.profile_path.write_bytes(encoded(row))
        self.pin = RUN.file_hash(self.profile_path)
        self.row = row
        patches = (mock.patch.object(LM, '_available_bytes', return_value=12 << 30),
                   mock.patch.object(LM, '_pending_reboot', return_value=[]),
                   mock.patch.object(LM, '_matching_processes', return_value=[]),
                   mock.patch.object(F, 'command', return_value=self.runner_argv()))
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def tearDown(self):
        self.temp.cleanup()

    def runner_argv(self):
        python = str(LM._ordinary(sys.executable))
        return [python, '-B', 'guard.py', '--launch', '--output', str(self.attempt/'run-root'/'run.json'), '--',
                python, '-B', 'run_fresh_interval.py', '--workload']

    def preflight(self, stage='root', **kwargs):
        return L.preflight(self.profile_path, self.pin, stage=stage, environ={}, **kwargs)


class PreflightTests(StageFixture):
    def test_root_preflight_writes_nothing_and_binds_the_orchestration(self):
        plan = self.preflight()
        self.assertEqual(plan['record']['status'], 'PREFLIGHT_PASSED')
        self.assertEqual(set(plan['record']['pinned_sources']), set(L.PINNED))
        self.assertEqual(plan['env']['PYTHONHASHSEED'], '0')
        self.assertEqual(list(self.attempt.iterdir()), [])

    def test_refusals_before_any_output(self):
        cases = (
            ('instrumentation', lambda: self.preflight_env({'PYTHONPATH': 'x'})),
            ('PYTHONHASHSEED', lambda: self.preflight_env({'PYTHONHASHSEED': '1'})),
            ('10 GiB available', lambda: self.with_memory(9 << 30)),
            ('fresh stage outputs', lambda: (self.attempt/'run-root').mkdir() or self.preflight()),
            ('new store directory', lambda: (self.folder/'store').mkdir() or self.preflight()),
        )
        for message, attempt in cases:
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                attempt()
            for item in ('run-root', 'store'):
                for base in (self.attempt, self.folder):
                    if (base/item).is_dir():
                        (base/item).rmdir()

    def test_interval_requires_run_a_adopted(self):
        with self.assertRaises(FileNotFoundError):
            self.preflight('interval')

    def preflight_env(self, environ):
        return L.preflight(self.profile_path, self.pin, stage='root', environ=environ)

    def with_memory(self, available):
        with mock.patch.object(LM, '_available_bytes', return_value=available):
            return self.preflight()


class PostcheckTests(StageFixture):
    def write(self, p, *, status, **change):
        p['out'].mkdir()
        parent = {'pid': 41, 'created_ticks': 1}
        guard = {'schema': LM.GUARD_SCHEMA, 'status': 'STOPPED', 'reason': None, 'workload_exit_confirmed': True,
                 'workload_exit_code': 0, 'cleanup': LM.CLEAN, 'parent': parent, 'nonce': 'n',
                 'guardian': {'pid': 40}, 'limits': {'rss_bytes': RUN.RSS_BYTES, 'free_floor_bytes': RUN.FREE_BYTES},
                 'sampled_peak_bytes': {'process_tree_rss_bytes': 5}, 'elapsed_seconds': 3.0}
        control = {'parent': parent, 'nonce': 'n', 'close_requested': True}
        receipt = {'pid': 41, 'status': status, 'errors': [], 'final_reserved_bytes': 0,
                   'production_acceptance': False, 'supervisor': {'pid': 40},
                   'logical_budget_final': {'peak_reserved_bytes': 7}}
        tracking = {'guardian': {'pid': 40, 'create_time': 1.0}, 'parent': parent}
        for name, value in (('guard', guard), ('control', control), ('receipt', receipt), ('tracking', tracking)):
            value.update(change.get(name, {}))
            p[name].write_text(json.dumps(value), encoding='utf8')

    def test_clean_guard_passes_and_reports_real_and_booked_peaks(self):
        p = L.paths(self.row, 'root')['run']
        self.write(p, status=F.SEALED_STATUS['root'])
        with mock.patch.object(LM, '_alive', return_value=False):
            failures, _, resources = L.guard_postcheck(p, receipt_status=F.SEALED_STATUS['root'])
        self.assertEqual(failures, [])
        self.assertEqual((resources['sampled_peak_bytes'], resources['booked_peak_reserved_bytes']),
                         ({'process_tree_rss_bytes': 5}, 7))

    def test_each_failure_is_named(self):
        cases = (('guard_exit', {'guard': {'workload_exit_code': 1}}),
                 ('guard_cleanup', {'guard': {'cleanup': {'remaining': [3], 'action_errors': []}}}),
                 ('guard_parent', {'receipt': {'pid': 42}}),
                 ('guard_supervisor', {'receipt': {'supervisor': {'pid': 9}}}),
                 ('receipt', {'receipt': {'errors': [{'type': 'X'}]}}),
                 ('tracking', {'tracking': {'guardian': {'pid': 1, 'create_time': 1.0}}}))
        for index, (name, change) in enumerate(cases):
            with self.subTest(check=name):
                p = {k: (v.parent/(str(index)+'-'+v.name) if isinstance(v, Path) else v)
                     for k, v in L.paths(self.row, 'root')['run'].items()}
                p['out'] = self.attempt/f'out-{index}'
                for name_ in ('receipt', 'guard', 'control', 'abort', 'cancel'):
                    p[name_] = p['out']/L.paths(self.row, 'root')['run'][name_].name
                self.write(p, status=F.SEALED_STATUS['root'], **change)
                with mock.patch.object(LM, '_alive', return_value=False):
                    failures, _, _ = L.guard_postcheck(p, receipt_status=F.SEALED_STATUS['root'])
                self.assertIn(name, failures)


class StageFlowTests(StageFixture):
    def run_stage(self, *, stage='root', runner=(0, []), reader=(0, []), finalise=None, adopt=None):
        finalise = finalise or (0, {'status': F.READER_PASS[stage], 'verdict_sha256': key('verdict'),
                                    'width_gate_passed': None if stage == 'root' else True}, 1.0, '')
        adopt = adopt or (0, {'status': RF.ADOPTED_STATUS, 'sha256': key('adopted')}, 1.0, '')
        guarded = iter([(runner[0], 10.0), (reader[0], 20.0)])
        checks = iter([(runner[1], [], {'booked_peak_reserved_bytes': 1}), (reader[1], [], {})])
        tools = iter([finalise, adopt])
        lines = []
        # Receipt hashes are stand-ins here; the real source pins are PreflightTests' subject.
        with mock.patch.object(L, '_pinned_sources', return_value={}), \
                mock.patch.object(L, '_guarded', side_effect=lambda *a: next(guarded)), \
                mock.patch.object(L, 'guard_postcheck', side_effect=lambda *a, **k: next(checks)), \
                mock.patch.object(LM, 'file_hash', side_effect=lambda path: key(str(path))), \
                mock.patch.object(RF, 'command', return_value=['reader']), \
                mock.patch.object(L, '_tool', side_effect=lambda *a: next(tools)), \
                mock.patch.object(RUN, '_tree', return_value={'files': 2, 'bytes': 9}):
            code = L.run_stage(self.profile_path, self.pin, stage=stage, environ={}, emit=lines.append)
        record = json.loads((self.attempt/f'stage-{stage}.json').read_text(encoding='utf8'))
        return code, record, lines

    def test_adopted_root_records_every_step_in_order(self):
        code, record, _ = self.run_stage()
        self.assertEqual(code, 0)
        self.assertEqual(record['status'], L.ADOPTED)
        self.assertEqual([step['name'] for step in record['steps']], ['runner', 'reader', 'finalise', 'adopt'])
        self.assertEqual(record['steps'][0]['wall_seconds'], 10.0)
        self.assertFalse((self.attempt/'stage-root.json.partial').exists())

    def test_a_failed_step_stops_the_stage_before_adoption(self):
        for name, change in (('runner', {'runner': (1, [])}), ('reader', {'reader': (0, ['guard_exit'])}),
                             ('finalise', {'finalise': (1, {'status': 'FAILED'}, 1.0, 'err')}),
                             ('adopt', {'adopt': (1, None, 1.0, 'uncertain')})):
            with self.subTest(step=name):
                (self.attempt/'stage-root.json').unlink(missing_ok=True)
                code, record, lines = self.run_stage(**change)
                self.assertEqual((code, record['status'], record['failed_step']), (1, 'FAILED', name))
                self.assertNotIn('adopt', [s['name'] for s in record['steps'] if s.get('ok')])
                self.assertIn('"FAILED"', lines[-1])

    def test_failed_width_gate_adopts_and_stops_before_interval_2(self):
        store = self.folder/'store'
        store.mkdir()
        F.write_durable(RF.adopted_path(store, 0), {'schema': RF.ADOPTED_SCHEMA, 'status': RF.ADOPTED_STATUS})
        with mock.patch.object(F, 'command', return_value=[*self.runner_argv()[:5],
                                                           str(self.attempt/'run-interval'/'run.json'),
                                                           *self.runner_argv()[6:]]):
            code, record, _ = self.run_stage(stage='interval', finalise=(0, {'status': F.READER_PASS['interval'],
                                             'verdict_sha256': key('v'), 'width_gate_passed': False}, 1.0, ''))
        self.assertEqual((code, record['status'], record['width_gate_passed']), (0, L.GATE_STOP, False))

    def test_review_state_stops_before_the_reader_and_is_reported_plainly(self):
        review = {'state': F.REVIEW_STATUS, 'cause': {'type': 'PresealRefused', 'message': 'binding differs'},
                  'sealed_file': {'filename': 'interval-0001.sqlite', 'file_sha256': key('file'), 'logical_seal': key('s')}}
        lines, tools = [], []

        def guarded(argv, env, p, emit):
            p['out'].mkdir()
            p['receipt'].write_text(json.dumps({'status': F.REVIEW_STATUS, 'review_only': review}), encoding='utf8')
            return 1, 12.0
        with mock.patch.object(L, '_pinned_sources', return_value={}), \
                mock.patch.object(L, '_guarded', side_effect=guarded), \
                mock.patch.object(L, 'guard_postcheck', return_value=([], [], {})) as postcheck, \
                mock.patch.object(L, '_tool', side_effect=lambda *a: tools.append(a)):
            code = L.run_stage(self.profile_path, self.pin, stage='root', environ={}, emit=lines.append)
        record = json.loads((self.attempt/'stage-root.json').read_text(encoding='utf8'))
        self.assertEqual((code, record['status'], record['failed_step']), (1, F.REVIEW_STATUS, 'preseal'))
        self.assertEqual(record['review']['sealed_file'], review['sealed_file'])
        self.assertEqual(record['review']['adoption'], F.REVIEW_ADOPTION)
        self.assertEqual(postcheck.call_args.kwargs, {'receipt_status': F.REVIEW_STATUS, 'review': True})
        self.assertEqual(tools, [])
        self.assertIn(F.REVIEW_STATUS, lines[-1])

    def test_stop_before_advance_runs_the_runner_only(self):
        store = self.folder/'store'
        store.mkdir()
        F.write_durable(RF.adopted_path(store, 0), {'schema': RF.ADOPTED_SCHEMA, 'status': RF.ADOPTED_STATUS})
        argv = [*self.runner_argv()[:5], str(self.attempt/'run-interval'/'run.json'), *self.runner_argv()[6:]]
        tools, statuses = [], []

        def postcheck(p, *, receipt_status, review=False):
            statuses.append(receipt_status)
            return [], [], {}
        with mock.patch.object(F, 'command', return_value=argv) as command, \
                mock.patch.object(L, '_pinned_sources', return_value={}), \
                mock.patch.object(L, '_guarded', return_value=(0, 5.0)), \
                mock.patch.object(L, 'guard_postcheck', side_effect=postcheck), \
                mock.patch.object(LM, 'file_hash', side_effect=lambda path: key(str(path))), \
                mock.patch.object(L, '_tool', side_effect=lambda *a: tools.append(a)):
            code = L.run_stage(self.profile_path, self.pin, stage='interval', environ={}, stop_before_advance=True,
                               emit=lambda line: None)
        record = json.loads((self.attempt/'stage-interval.json').read_text(encoding='utf8'))
        self.assertEqual((code, record['status'], statuses, tools), (0, F.STOPPED_STATUS, [F.STOPPED_STATUS], []))
        self.assertTrue(command.call_args.kwargs['stop_before_advance'])
        with self.assertRaisesRegex(ValueError, 'interval stage only'):
            L.preflight(self.profile_path, self.pin, stage='root', environ={}, stop_before_advance=True)

    def test_stage_record_is_replaced_atomically(self):
        path = self.attempt/'record.json'
        path.write_text('{}', encoding='utf8')
        L._save(path, {'a': 1})
        self.assertEqual(json.loads(path.read_text(encoding='utf8')), {'a': 1})
        self.assertEqual(sorted(os.listdir(self.attempt)), ['record.json'])


if __name__ == '__main__':
    unittest.main()
