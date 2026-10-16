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
import start_gate as SG
from types import SimpleNamespace

BOOKING = 4 << 30
GATE = {'booking_bytes': BOOKING, 'booking_basis': 'test booking'}


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
        return L.preflight(self.profile_path, self.pin, stage=stage, environ={}, **{**GATE, **kwargs})


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
            ('start gate refused', lambda: self.with_memory(6 << 30)),
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
        return L.preflight(self.profile_path, self.pin, stage='root', environ=environ, **GATE)

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

    def test_a_review_producer_exits_one_and_nothing_else_does(self):
        review_receipt = {'errors': [{'type': 'PresealSealedForReview'}], 'review_only': {'state': F.REVIEW_STATUS}}
        cleanup = {'cleanup': {'remaining': [3], 'action_errors': []}}
        cases = ((1, True, {}, []), (0, True, {}, ['guard_exit']), (2, True, {}, ['guard_exit']),
                 (True, True, {}, ['guard_exit']), (1.0, True, {}, ['guard_exit']), (1, False, {}, ['guard_exit']),
                 (1, True, cleanup, ['guard_cleanup']))
        for index, (exit_code, review, change, expected) in enumerate(cases):
            with self.subTest(exit=exit_code, review=review, change=change):
                p = {k: (v.parent/('r%d-' % index+v.name) if isinstance(v, Path) else v)
                     for k, v in L.paths(self.row, 'root')['run'].items()}
                p['out'] = self.attempt/f'review-out-{index}'
                for name_ in ('receipt', 'guard', 'control', 'abort', 'cancel'):
                    p[name_] = p['out']/L.paths(self.row, 'root')['run'][name_].name
                status = F.REVIEW_STATUS if review else F.SEALED_STATUS['root']
                self.write(p, status=status, guard={'workload_exit_code': exit_code, **change},
                           receipt=review_receipt if review else {})
                with mock.patch.object(LM, '_alive', return_value=False):
                    failures, _, _ = L.guard_postcheck(p, receipt_status=status, review=review)
                self.assertEqual(failures, expected)


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
                mock.patch.object(RF, 'command', return_value=['reader']) as self.reader_command, \
                mock.patch.object(L, '_tool', side_effect=lambda *a: next(tools)), \
                mock.patch.object(RUN, '_tree', return_value={'files': 2, 'bytes': 9}):
            code = L.run_stage(self.profile_path, self.pin, stage=stage, environ={}, emit=lines.append, **GATE)
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

        # The real guard returns 2 for its workload's exit 1; that pair is clean review evidence.
        for wrapper, postcheck_failures, recorded in ((2, [], []), (1, [], ['guard_wrapper_exit']),
                                                      (0, [], ['guard_wrapper_exit']),
                                                      (2, ['guard_exit'], ['guard_exit'])):
            with self.subTest(wrapper=wrapper, failures=postcheck_failures):
                (self.attempt/'stage-root.json').unlink(missing_ok=True)
                for name in ('run-root', 'run-root.tracking.json', 'run-root.log'):
                    if (self.attempt/name).is_dir():
                        for item in (self.attempt/name).iterdir():
                            item.unlink()
                        (self.attempt/name).rmdir()
                    else:
                        (self.attempt/name).unlink(missing_ok=True)

                def guarded(argv, env, p, emit, wrapper=wrapper):
                    p['out'].mkdir()
                    p['receipt'].write_text(json.dumps({'status': F.REVIEW_STATUS, 'review_only': review}),
                                            encoding='utf8')
                    return wrapper, 12.0
                with mock.patch.object(L, '_pinned_sources', return_value={}), \
                        mock.patch.object(L, '_guarded', side_effect=guarded), \
                        mock.patch.object(L, 'guard_postcheck', return_value=(postcheck_failures, [], {})) as postcheck, \
                        mock.patch.object(L, '_tool', side_effect=lambda *a: tools.append(a)):
                    code = L.run_stage(self.profile_path, self.pin, stage='root', environ={}, emit=lines.append, **GATE)
                record = json.loads((self.attempt/'stage-root.json').read_text(encoding='utf8'))
                self.assertEqual((code, record['status'], record['failed_step']), (1, F.REVIEW_STATUS, 'preseal'))
                self.assertEqual(record['review']['sealed_file'], review['sealed_file'])
                self.assertEqual(record['review']['adoption'], F.REVIEW_ADOPTION)
                self.assertEqual(record['review']['guard_failures'], recorded)
                self.assertEqual([(s['name'], s['exit'], s['failures']) for s in record['steps']],
                                 [('runner', wrapper, recorded)])
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
                               emit=lambda line: None, **GATE)
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


class CompositionRootTests(unittest.TestCase):
    """A published composition launches only from its permanent root (coordinator, 16 Oct 2026)."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='lfr-', dir=HERE)
        self.workspace = Path(self.temp.name)
        self.root = self.workspace/'composed'
        (self.root/'helpers').mkdir(parents=True)
        inputs = self.workspace/'reviewed-inputs.json'
        inputs.write_text(json.dumps({'target_root': str(self.root)}), encoding='utf8')
        self.record = {'root': str(self.root), 'reviewed_inputs': 'reviewed-inputs.json',
                       'reviewed_inputs_sha256': LM.file_hash(inputs)}
        self.row = {'workspace': str(self.workspace)}

    def tearDown(self):
        self.temp.cleanup()

    def check(self, here, manifest=None, record=None):
        if record is not None:
            (self.root/'composition.json').write_text(json.dumps(record), encoding='utf8')
        with mock.patch.object(L, 'HERE', here):
            return L._composition_root(self.row, manifest or {'files': {}})

    def test_inside_its_own_root_passes(self):
        found = self.check(self.root/'helpers', record=self.record)
        self.assertEqual(found['root'], str(self.root))
        self.assertEqual(found['reviewed_inputs_sha256'], self.record['reviewed_inputs_sha256'])

    def test_a_copied_composition_refuses(self):
        copy = self.workspace/'copied'
        (copy/'helpers').mkdir(parents=True)
        (copy/'composition.json').write_text(json.dumps(self.record), encoding='utf8')
        with self.assertRaisesRegex(L.StageRefused, 'runs only from'):
            self.check(copy/'helpers')

    def test_changed_reviewed_inputs_refuse(self):
        with self.assertRaisesRegex(L.StageRefused, 'reviewed inputs differ'):
            self.check(self.root/'helpers', record=dict(self.record, reviewed_inputs_sha256=key('other')))

    def test_a_helpers_folder_without_its_record_refuses(self):
        with self.assertRaisesRegex(L.StageRefused, 'requires its composition.json'):
            self.check(self.root/'helpers')

    def test_a_development_launch_refuses_a_frozen_profile_only(self):
        self.assertEqual(self.check(self.workspace)['root'], None)
        self.assertEqual(self.check(self.workspace, {'files': {}, 'composition': {'test_only': True}})['root'], None)
        for name in ('frozen', 'published'):
            with self.assertRaisesRegex(L.StageRefused, 'only from its published composition root'):
                self.check(self.workspace, {'files': {}, 'composition': {name: 'x'}})


class MeasurementReuseTests(StageFixture):
    """Item 7: the seed comes from the adopted root stage and run A's receipt; the store is never hashed here."""

    def adopted_root(self, *, stored=None, **change):
        """Run A's adopted root stage: its stage record, its receipt and the adoption record, bound by SHA-256."""
        store = self.folder/'store'
        store.mkdir(exist_ok=True)
        adopted = RF.adopted_path(store, 0)
        if not adopted.exists():
            F.write_durable(adopted, {'schema': RF.ADOPTED_SCHEMA, 'status': RF.ADOPTED_STATUS})
        root = L.paths(self.row, 'root')
        root['run']['out'].mkdir(exist_ok=True)
        stored = {'filename': F.MEASUREMENT_STORE, 'sha256': key('store')} if stored is None else stored
        root['run']['receipt'].write_text(json.dumps({'status': F.SEALED_STATUS['root'],
                                                      'initial_measurement_store': stored}), encoding='utf8')
        steps = [{'name': name, 'ok': True} for name in L.ROOT_STEPS]
        steps[0]['receipt_sha256'] = LM.file_hash(root['run']['receipt'])
        steps[3]['adopted_sha256'] = LM.file_hash(adopted)
        record = {'schema': L.STAGE_SCHEMA, 'stage': 'root', 'status': L.ADOPTED, 'steps': steps, **change}
        L._save(root['record'], record)
        return {'receipt_sha256': steps[0]['receipt_sha256'], 'store_sha256': key('store')}

    def test_the_seed_is_the_adopted_root_receipt_and_the_store_pin_it_recorded(self):
        seed = self.adopted_root()
        with mock.patch.object(LM, 'file_hash', wraps=LM.file_hash) as hashed:
            self.assertEqual(L.initial_measurement_seed(self.row), seed)
        self.assertEqual(sorted(Path(call.args[0]).name for call in hashed.call_args_list),
                         sorted(['run.json', RF.adopted_path('s', 0).name]))
        self.assertFalse((self.folder/'store'/F.MEASUREMENT_STORE).exists())

    def test_anything_but_a_cleanly_adopted_root_stage_refuses(self):
        with self.assertRaisesRegex(L.StageRefused, 'requires the root stage adopted'):
            L.initial_measurement_seed(self.row)
        good = [{'name': name, 'ok': True} for name in L.ROOT_STEPS]
        for change in ({'status': 'FAILED'}, {'stage': 'interval'}, {'schema': 'other'}, {'steps': good[:3]},
                       {'steps': [good[1], good[0], *good[2:]]}, {'steps': [*good[:3], {'name': 'adopt', 'ok': 1}]},
                       {'steps': [*good[:3], 'adopt']}, {'steps': None}):
            with self.subTest(change=change):
                self.adopted_root(**change)
                with self.assertRaisesRegex(L.StageRefused, 'requires the root stage adopted'):
                    L.initial_measurement_seed(self.row)

    def test_changed_records_or_an_unnamed_store_refuse(self):
        root = L.paths(self.row, 'root')
        self.adopted_root()
        with open(root['run']['receipt'], 'a', encoding='utf8') as stream:
            stream.write(' ')
        with self.assertRaisesRegex(L.StageRefused, 'run A receipt differs from the root stage record'):
            L.initial_measurement_seed(self.row)
        self.adopted_root()
        adopted = RF.adopted_path(self.folder/'store', 0)
        adopted.write_bytes(adopted.read_bytes()+b' ')
        with self.assertRaisesRegex(L.StageRefused, 'adoption record differs from the root stage record'):
            L.initial_measurement_seed(self.row)
        for stored, message in (({}, 'names no closed initial measurement store'),
                                ({'filename': 'other.sqlite', 'sha256': key('s')}, 'names no closed'),
                                ({'filename': F.MEASUREMENT_STORE, 'sha256': key('s').upper()}, 'lowercase SHA-256')):
            with self.subTest(stored=stored):
                self.adopted_root(stored=stored)
                with self.assertRaisesRegex(ValueError, message):
                    L.initial_measurement_seed(self.row)

    def test_reuse_is_an_interval_stage_flag_only(self):
        for stage, value in (('root', True), ('interval', 1)):
            with self.subTest(stage=stage, value=value), \
                    self.assertRaisesRegex(L.StageRefused, 'measurement reuse applies to the interval stage only'):
                L.preflight(self.profile_path, self.pin, stage=stage, environ={}, reuse_initial_measurements=value)
        lines = []
        with mock.patch('builtins.print', side_effect=lambda line, **kwargs: lines.append(line)):
            code = L.main(['--profile', str(self.profile_path), '--profile-sha256', self.pin, '--stage', 'root',
                           '--preflight-only', '--reuse-initial-measurements'])
        self.assertEqual(code, 2)
        self.assertIn('measurement reuse applies to the interval stage only', lines[-1])
        self.assertEqual(list(self.attempt.iterdir()), [])

    def seeded_stage(self, reused):
        """The interval stage with --reuse-initial-measurements; the runner records ``reused``."""
        seed = self.adopted_root()
        argv = [*self.runner_argv()[:5], str(self.attempt/'run-interval'/'run.json'), *self.runner_argv()[6:]]
        launched, lines = [], []
        finalise = (0, {'status': F.READER_PASS['interval'], 'verdict_sha256': key('v'), 'width_gate_passed': True},
                    1.0, '')
        tools = iter([finalise, (0, {'status': RF.ADOPTED_STATUS, 'sha256': key('a')}, 1.0, '')])

        def guarded(argv, env, p, emit):
            p['out'].mkdir()
            receipt = {'status': RF.WORKLOAD_STATUS['interval']}
            if p['receipt'].name == 'run.json':
                receipt = {'status': F.SEALED_STATUS['interval']}
                if reused is not None:
                    receipt['reused_initial_cache'] = reused(seed)
            p['receipt'].write_text(json.dumps(receipt), encoding='utf8')
            launched.append(p['receipt'].name)
            return 0, 5.0
        with mock.patch.object(F, 'command', return_value=argv) as command, \
                mock.patch.object(L, '_pinned_sources', return_value={}), \
                mock.patch.object(L, '_guarded', side_effect=guarded), \
                mock.patch.object(L, 'guard_postcheck', return_value=([], [], {})), \
                mock.patch.object(RF, 'command', return_value=['reader']), \
                mock.patch.object(L, '_tool', side_effect=lambda *a: next(tools)), \
                mock.patch.object(RUN, '_tree', return_value={'files': 2, 'bytes': 9}):
            code = L.run_stage(self.profile_path, self.pin, stage='interval', environ={},
                               reuse_initial_measurements=True, emit=lines.append, **GATE)
        record = json.loads((self.attempt/'stage-interval.json').read_text(encoding='utf8'))
        self.assertEqual(command.call_args.kwargs['seed'], seed)
        self.assertEqual(record['initial_measurement_seed'], seed)
        return code, record, lines, launched, seed

    @staticmethod
    def reuse(seed, **change):
        return {'pinned_sha256': seed['store_sha256'], 'receipt': {'sha256': seed['receipt_sha256']},
                'status': 'FULL_REUSE', 'hits': 7, 'misses': 0, 'full_reuse': True, 'counts_agree_with_bytes': True,
                'copy_seconds': 0.25, 'after_sha256': seed['store_sha256'], **change}

    def test_a_seeded_stage_passes_the_pins_and_reports_the_reuse(self):
        code, record, lines, launched, seed = self.seeded_stage(lambda seed: self.reuse(seed))
        expected = {'status': 'FULL_REUSE', 'hits': 7, 'misses': 0, 'full_reuse': True,
                    'counts_agree_with_bytes': True, 'copy_seconds': 0.25}
        self.assertEqual((code, record['status'], launched), (0, L.ADOPTED, ['run.json', 'reopen.json']))
        self.assertEqual(record['steps'][0]['reused_initial_cache'], expected)
        milestones = [json.loads(line) for line in lines if '"MILESTONE"' in line]
        self.assertEqual(milestones, [{'status': 'MILESTONE', 'stage': 'interval', 'reused_initial_cache': expected}])

    def test_a_runner_record_without_reuse_for_these_pins_stops_before_the_reader(self):
        for name, reused in (('missing', None), ('store pin', lambda seed: self.reuse(seed, pinned_sha256=key('x'))),
                             ('receipt pin', lambda seed: self.reuse(seed, receipt={'sha256': key('x')})),
                             ('refused', lambda seed: {'status': 'REFUSED_BEFORE_ADMISSION', 'requested': seed})):
            with self.subTest(case=name):
                for path in (*self.attempt.iterdir(), *(self.folder/'store').glob('*')):
                    if path.is_dir():
                        for item in path.iterdir():
                            item.unlink()
                        path.rmdir()
                    else:
                        path.unlink()
                code, record, lines, launched, _ = self.seeded_stage(reused)
                self.assertEqual((code, record['status'], record['failed_step'], launched),
                                 (1, 'FAILED', 'runner', ['run.json']))
                self.assertIn('no measurement reuse for these pins', record['reason'])
                self.assertFalse([line for line in lines if '"MILESTONE"' in line])

    def test_the_milestone_names_only_matching_pins(self):
        seed = {'receipt_sha256': key('r'), 'store_sha256': key('s')}
        self.assertIsNone(L.reuse_milestone(None, seed))
        self.assertIsNone(L.reuse_milestone({'reused_initial_cache': []}, seed))
        self.assertEqual(set(L.reuse_milestone({'reused_initial_cache': self.reuse(seed)}, seed)), set(L.REUSE_FIELDS))


class StartGateTests(StageFixture):
    """The by-need gate (start_gate.py) at the launcher: decided, admitted and handed to both children."""

    def argv(self, *extra):
        return ['--profile', str(self.profile_path), '--profile-sha256', self.pin, '--stage', 'root', *extra]

    def main(self, *extra):
        lines = []
        with mock.patch('builtins.print', side_effect=lambda line, **kwargs: lines.append(line)):
            code = L.main(self.argv(*extra))
        return code, lines

    def test_no_record_and_no_booking_refuses_before_any_output(self):
        with self.assertRaisesRegex(SG.StartGateRefused, 'no completed PASS record'):
            L.preflight(self.profile_path, self.pin, stage='root', environ={})
        for extra in ((), ('--preflight-only',)):
            with self.subTest(extra=extra):
                code, lines = self.main(*extra)
                self.assertEqual(code, 2)
                self.assertIn('no completed PASS record', lines[-1])
        self.assertEqual(list(self.attempt.iterdir()), [])

    def test_a_measured_record_beats_a_lower_booking(self):
        record = {'schema': L.STAGE_SCHEMA, 'status': L.ADOPTED, 'stage': 'root', 'interval': 0,
                  'steps': [{'name': name, 'ok': True, **({'resources': {'sampled_peak_bytes': {
                      SG.TREE_PEAK: 5 << 30}}} if name in SG.GUARDED_STEPS else {})} for name in L.ROOT_STEPS]}
        path = self.folder/'earlier-stage-root.json'
        path.write_text(json.dumps(record), encoding='utf8')
        plan = self.preflight(peak_records=[path])
        memory, gate = plan['record']['memory'], plan['record']['start_gate']
        self.assertEqual(memory['hard_gate_bytes'], SG.gate_bytes(5 << 30))
        self.assertEqual((gate['basis'], gate['predicted_peak_bytes'], gate['booking']['used']),
                         (SG.MEASURED, 5 << 30, False))
        self.assertEqual(gate['available_bytes'], 12 << 30)

    def test_a_gate_above_free_memory_leaves_no_record_and_no_run(self):
        with mock.patch.object(LM, '_available_bytes', return_value=SG.gate_bytes(BOOKING) - 1), \
                mock.patch.object(L, '_guarded') as guarded, \
                self.assertRaisesRegex(SG.StartGateRefused, 'start gate refused'):
            L.run_stage(self.profile_path, self.pin, stage='root', environ={}, emit=lambda line: None, **GATE)
        guarded.assert_not_called()
        self.assertEqual(list(self.attempt.iterdir()), [])

    def test_a_random_seed_refuses(self):
        flags = SimpleNamespace(flags=SimpleNamespace(hash_randomization=1))
        with mock.patch.object(SG, 'sys', flags), self.assertRaisesRegex(SG.StartGateRefused, 'seed 0'):
            self.preflight()
        self.assertEqual(list(self.attempt.iterdir()), [])

    def test_both_children_get_the_launchers_decision(self):
        flow = StageFlowTests('test_adopted_root_records_every_step_in_order')
        flow.setUp()
        self.addCleanup(flow.doCleanups)
        self.addCleanup(flow.tearDown)
        code, record, _ = flow.run_stage()
        gate = SG.stage_decision(SG.stage_key('root', 0), booking_bytes=BOOKING, booking_basis='test booking')
        self.assertEqual(code, 0)
        runner = F.command
        assert isinstance(runner, mock.Mock)
        self.assertEqual(runner.call_args.kwargs['start_gate'], gate)
        self.assertEqual(flow.reader_command.call_args.kwargs['start_gate'], gate)
        self.assertEqual(record['start_gate'], dict(gate, available_bytes=12 << 30, hash_randomization=0))

    def test_the_gate_reads_the_launchers_own_stage_records(self):
        self.assertEqual(SG.STAGE_SCHEMA, L.STAGE_SCHEMA)
        self.assertEqual(SG.STAGE_PASS, (L.ADOPTED, L.GATE_STOP))
        self.assertEqual(list(SG.STAGE_STEPS), L.ROOT_STEPS)
        self.assertEqual(SG.stage_key('interval', F.INTERVALS['interval'])['interval'], 1)


class IntervalNStageTests(StageFixture):
    """Item 21: stage interval N >= 2 starts from adopted(N-1) exactly as its own stage recorded it."""

    def adopted_parent(self, number=1, **change):
        store = self.folder/'store'
        store.mkdir(exist_ok=True)
        adopted = RF.adopted_path(store, number)
        if not adopted.exists():
            F.write_durable(adopted, {'schema': RF.ADOPTED_SCHEMA, 'status': RF.ADOPTED_STATUS, 'interval': number,
                                      'verdict_sha256': key('verdict')})
        steps = self.good_steps()
        steps[3]['adopted_sha256'] = LM.file_hash(adopted)
        record = {'schema': L.STAGE_SCHEMA, 'stage': 'interval', 'interval': number, 'status': L.ADOPTED,
                  'steps': steps, **change}
        path = L.paths(self.row, 'interval', None if number == 1 else number)['record']
        path.unlink(missing_ok=True)
        L._save(path, record)
        return LM.file_hash(adopted)

    @staticmethod
    def good_steps():
        steps = [{'name': name, 'ok': True} for name in L.ROOT_STEPS]
        steps[2].update(verdict_sha256=key('verdict'), width_gate_passed=True)
        return steps

    def argv(self, number):
        name = 'run-interval' if number == 1 else f'run-interval-{number:04d}'
        return [*self.runner_argv()[:5], str(self.attempt/name/'run.json'),
                *self.runner_argv()[6:]]

    def reviewed_parent(self, number=1, *, stage_change=(), review_change=(), adopted_change=(), verdict_change=()):
        """Interval ``number`` sealed for review by its own stage, then adopted by the approval route."""
        store = self.folder/'store'
        store.mkdir(exist_ok=True)
        for path in (F.verdict_path(store, number), RF.adopted_path(store, number)):
            if path.exists():
                path.chmod(0o644)
                path.unlink()
        entry = {'interval': number, 'filename': f'interval-{number:04d}.sqlite', 'file_sha256': key('file'),
                 'logical_seal': key('seal')}
        gate = ({'schema': F.WIDTH_GATE_V1, 'passed': True} if number == 1 else
                {'schema': F.WIDTH_GATE_V2, 'interval': number, 'next_interval': number+1, 'passed': True})
        verdict = {'schema': F.VERDICT_SCHEMA, 'interval': number, 'review_only': True, 'width_gate': gate,
                   'producer_receipt_sha256': key('review receipt'), **dict(verdict_change)}
        verdict_sha = F.write_durable(F.verdict_path(store, number), verdict)
        adopted = {'schema': RF.ADOPTED_SCHEMA, 'status': RF.ADOPTED_STATUS, 'interval': number, 'entry': entry,
                   'verdict_sha256': verdict_sha, 'review_approval_sha256': key('approval')}
        adopted = adopted_change(adopted) if callable(adopted_change) else {**adopted, **dict(adopted_change)}
        pin = F.write_durable(RF.adopted_path(store, number), adopted)
        review = {'cause': {'type': 'PresealRefused', 'message': 'checker defect'},
                  'sealed_file': {k: entry[k] for k in ('filename', 'file_sha256', 'logical_seal')},
                  'adoption': F.REVIEW_ADOPTION, 'receipt_sha256': key('review receipt'), 'guard_failures': [],
                  'next': 'reopen_fresh_restart --launch --review', **dict(review_change)}
        record = {'schema': L.STAGE_SCHEMA, 'stage': 'interval', 'interval': number, 'status': F.REVIEW_STATUS,
                  'failed_step': 'preseal', 'steps': [{'name': 'runner', 'ok': False, 'exit': 2, 'failures': []}],
                  'review': review, **dict(stage_change)}
        path = L.paths(self.row, 'interval', None if number == 1 else number)['record']
        path.unlink(missing_ok=True)
        L._save(path, record)
        return pin

    def test_a_review_adopted_parent_starts_interval_n_from_its_explicit_pin(self):
        for number in (2, 3):
            with self.subTest(number=number):
                pin = self.reviewed_parent(number-1)
                parent = L.paths(self.row, 'interval', None if number == 2 else number-1)['record']
                before = parent.read_bytes()
                with mock.patch.object(F, 'command', return_value=self.argv(number)) as command:
                    plan = self.preflight('interval', interval=number, parent_adopted_sha256=pin)
                self.assertEqual(command.call_args.kwargs['parent_adopted_sha256'], pin)
                self.assertEqual(plan['record']['parent'], {'stage_record': str(parent), 'adopted_sha256': pin,
                                                            'route': 'review-adopted',
                                                            'review_approval_sha256': key('approval')})
                self.assertEqual(parent.read_bytes(), before, 'the old review stage is never relabelled')

    def test_a_review_adopted_parent_refuses_unless_its_evidence_names_that_adoption(self):
        evidence, differs = 'no clean review evidence', 'adopted interval N-1 differs from its review stage record'
        approved, gate = 'no review-approved adoption of interval N-1', 'read with its width gate passed'
        runner = lambda **new: {'steps': [{'name': 'runner', 'ok': False, 'exit': 2, 'failures': [], **new}]}
        sealed = lambda **new: {'sealed_file': {'filename': 'interval-0001.sqlite', 'file_sha256': key('file'),
                                                'logical_seal': key('seal'), **new}}
        cases = (
            ('needs its explicit adoption pin', {}, None),
            ('lowercase SHA-256', {}, 'ABC'),
            ('differs from the explicit pin', {}, key('another adoption')),
            (evidence, {'stage_change': {'failed_step': 'runner'}}, 'PIN'),
            (evidence, {'stage_change': {'interval': 2}}, 'PIN'),
            (evidence, {'stage_change': {'stage': 'root'}}, 'PIN'),
            (evidence, {'stage_change': {'schema': 'other'}}, 'PIN'),
            (evidence, {'stage_change': runner(exit=1)}, 'PIN'),
            (evidence, {'stage_change': runner(exit=True)}, 'PIN'),
            (evidence, {'stage_change': runner(exit=2.0)}, 'PIN'),
            (evidence, {'stage_change': runner(name='reader')}, 'PIN'),
            (evidence, {'stage_change': {'steps': [*runner()['steps'], {'name': 'reader', 'ok': True}]}}, 'PIN'),
            (evidence, {'stage_change': {'review': None}}, 'PIN'),
            (evidence, {'review_change': {'guard_failures': ['guard_exit']}}, 'PIN'),
            (evidence, {'review_change': {'guard_failures': ['guard_wrapper_exit']}}, 'PIN'),
            (evidence, {'review_change': {'guard_failures': None}}, 'PIN'),
            (differs, {'review_change': {'receipt_sha256': key('another receipt')}}, 'PIN'),
            (differs, {'review_change': sealed(file_sha256=key('another file'))}, 'PIN'),
            (differs, {'review_change': sealed(logical_seal=key('another seal'))}, 'PIN'),
            (differs, {'review_change': sealed(filename='interval-0002.sqlite')}, 'PIN'),
            (differs, {'review_change': sealed(extra=1)}, 'PIN'),
            (approved, {'adopted_change': {'review_approval_sha256': None}}, 'PIN'),
            (approved, {'adopted_change': {'status': 'QUARANTINED'}}, 'PIN'),
            (approved, {'adopted_change': {'interval': 2}}, 'PIN'),
            (approved, {'adopted_change': {'entry': None}}, 'PIN'),
            ('recorded SHA-256', {'adopted_change': {'verdict_sha256': key('another verdict')}}, 'PIN'),
            (gate, {'verdict_change': {'review_only': None}}, 'PIN'),
            (gate, {'verdict_change': {'width_gate': {'schema': F.WIDTH_GATE_V1, 'passed': False}}}, 'PIN'),
            (gate, {'verdict_change': {'width_gate': {'schema': F.WIDTH_GATE_V2, 'interval': 1, 'next_interval': 2,
                                                      'passed': True}}}, 'PIN'),
            (gate, {'verdict_change': {'width_gate': None}}, 'PIN'),
        )
        for index, (message, change, pin) in enumerate(cases):
            with self.subTest(index=index, message=message), \
                    mock.patch.object(F, 'command', return_value=self.argv(2)), \
                    self.assertRaisesRegex(ValueError, message):
                actual = self.reviewed_parent(**change)
                self.preflight('interval', interval=2, parent_adopted_sha256=actual if pin == 'PIN' else pin)
        with mock.patch.object(F, 'command', return_value=self.argv(2)):
            pin = self.adopted_parent()
            with self.assertRaisesRegex(ValueError, 'for a review-adopted parent only'):
                self.preflight('interval', interval=2, parent_adopted_sha256=pin)
            with self.assertRaisesRegex(ValueError, 'adoption pin is for interval N >= 2'):
                self.preflight('interval', parent_adopted_sha256=pin)
            self.adopted_parent(status=L.GATE_STOP)
            with self.assertRaisesRegex(ValueError, 'for a review-adopted parent only'):
                self.preflight('interval', interval=2, parent_adopted_sha256=pin)

    def test_a_review_adopted_parents_verdict_is_read_only_at_its_full_pin(self):
        with mock.patch.object(F, 'command', return_value=self.argv(2)):
            pin = self.reviewed_parent()
            self.assertEqual(self.preflight('interval', interval=2, parent_adopted_sha256=pin)['record']['parent']
                             ['route'], 'review-adopted')
            for change in (lambda a: {k: v for k, v in a.items() if k != 'verdict_sha256'},
                           {'verdict_sha256': None}, {'verdict_sha256': ''}, {'verdict_sha256': 'ABC'},
                           {'verdict_sha256': 1}, {'verdict_sha256': [key('x')]},
                           lambda a: {**a, 'verdict_sha256': a['verdict_sha256'].upper()},
                           lambda a: {**a, 'verdict_sha256': a['verdict_sha256'][:63]}):
                with self.subTest(change=change):
                    pin = self.reviewed_parent(adopted_change=change)
                    with self.assertRaisesRegex(ValueError, 'exact lowercase SHA-256 required'):
                        self.preflight('interval', interval=2, parent_adopted_sha256=pin)

    def test_interval_n_paths_are_its_own(self):
        p = L.paths(self.row, 'interval', 2)
        self.assertEqual((p['record'], p['run']['out'], p['reader']['out']),
                         (self.attempt/'stage-interval-0002.json', self.attempt/'run-interval-0002',
                          self.attempt/'reader-interval-0002'))
        self.assertEqual((p['run']['tracking'].name, p['reader']['log'].name),
                         ('run-interval-0002.tracking.json', 'reader-interval-0002.log'))
        self.assertEqual(L.paths(self.row, 'interval', 1), L.paths(self.row, 'interval'))
        self.assertEqual(L.paths(self.row, 'interval')['record'], self.attempt/'stage-interval.json')

    def test_preflight_passes_the_parent_stages_adoption_pin(self):
        for number in (2, 3):
            with self.subTest(number=number):
                pin = self.adopted_parent(number-1)
                with mock.patch.object(F, 'command', return_value=self.argv(number)) as command:
                    plan = self.preflight('interval', interval=number)
                self.assertEqual((command.call_args.kwargs['interval'],
                                  command.call_args.kwargs['parent_adopted_sha256']), (number, pin))
                parent = L.paths(self.row, 'interval', None if number == 2 else number-1)['record']
                self.assertEqual(plan['record']['parent'], {'stage_record': str(parent), 'adopted_sha256': pin})
                self.assertEqual(plan['record']['interval'], number)
                self.assertEqual(plan['gate'], SG.stage_decision(SG.stage_key('interval', number), **GATE))
                self.assertEqual(list(self.attempt.glob(f'stage-interval-{number:04d}*')), [])
        L.paths(self.row, 'interval')['record'].unlink()
        F.write_durable(RF.adopted_path(self.folder/'store', 0), {'schema': RF.ADOPTED_SCHEMA,
                                                                  'status': RF.ADOPTED_STATUS})
        with mock.patch.object(F, 'command', return_value=self.argv(1)) as command:
            plan = self.preflight('interval')
        self.assertEqual((command.call_args.kwargs['interval'], command.call_args.kwargs['parent_adopted_sha256'],
                          'parent' in plan['record']), (None, None, False))

    def test_interval_n_preflight_refusals(self):
        message = 'interval N requires interval N-1 adopted by its own stage with its width gate passed'
        good = self.good_steps()
        finalise = lambda **new: [*good[:2], {**good[2], **new}, good[3]]
        cases = ((message, {'status': L.GATE_STOP}), (message, {'status': 'FAILED'}), (message, {'interval': 2}),
                 (message, {'steps': finalise(width_gate_passed=False)}),
                 (message, {'steps': finalise(width_gate_passed=None)}),
                 (message, {'stage': 'root'}), (message, {'schema': 'other'}), (message, {'steps': good[:3]}),
                 ('adopted interval N-1 differs from its stage record',
                  {'steps': [*good[:3], {'name': 'adopt', 'ok': True, 'adopted_sha256': key('x')}]}),
                 ('lowercase SHA-256', {'steps': [*good[:3], {'name': 'adopt', 'ok': True}]}))
        for text, change in cases:
            with self.subTest(change=change), mock.patch.object(F, 'command', return_value=self.argv(2)), \
                    self.assertRaisesRegex(ValueError, text):
                self.adopted_parent(**change)
                self.preflight('interval', interval=2)
        with mock.patch.object(F, 'command', return_value=self.argv(2)):
            self.adopted_parent()
            with self.assertRaisesRegex(ValueError, message):
                self.preflight('interval', interval=3)
            adopted = RF.adopted_path(self.folder/'store', 1)
            steps = self.good_steps()
            steps[2]['verdict_sha256'], steps[3]['adopted_sha256'] = key('x'), LM.file_hash(adopted)
            self.adopted_parent(steps=steps)
            with self.assertRaisesRegex(L.StageRefused, 'adopted interval N-1 differs from its stage record'):
                self.preflight('interval', interval=2)
            self.adopted_parent()
            raw = adopted.read_bytes()
            adopted.chmod(0o644)
            adopted.write_bytes(raw+b' ')
            with self.assertRaisesRegex(L.StageRefused, 'adopted interval N-1 differs from its stage record'):
                self.preflight('interval', interval=2)
            adopted.write_bytes(raw)
            F.write_durable(F.runner_record_path(self.folder/'store', 2), {'x': 1})
            with self.assertRaisesRegex(L.StageRefused, 'no earlier interval-N record'):
                self.preflight('interval', interval=2)
            for kwargs, text in (({'stage': 'root', 'interval': 2}, 'N >= 1 of the interval mode'),
                                 ({'interval': 2, 'stop_before_advance': True}, 'runs no smoke')):
                with self.subTest(kwargs=kwargs), self.assertRaisesRegex(ValueError, text):
                    self.preflight(**{'stage': 'interval', **kwargs})
        self.assertEqual(sorted(path.name for path in self.attempt.iterdir()), ['stage-interval.json'])

    def test_an_interval_n_stage_hands_its_interval_to_every_step(self):
        pin = self.adopted_parent()
        tools = []
        finalise = (0, {'status': F.READER_PASS['interval'], 'verdict_sha256': key('v'), 'width_gate_passed': False},
                    1.0, '')
        results = iter([finalise, (0, {'status': RF.ADOPTED_STATUS, 'sha256': key('a')}, 1.0, '')])
        guarded = iter([(0, 10.0), (0, 20.0)])
        with mock.patch.object(F, 'command', return_value=self.argv(2)) as command, \
                mock.patch.object(L, '_pinned_sources', return_value={}), \
                mock.patch.object(L, '_guarded', side_effect=lambda *a: next(guarded)), \
                mock.patch.object(L, 'guard_postcheck', return_value=([], [], {})), \
                mock.patch.object(RF, 'command', return_value=['reader']) as reader, \
                mock.patch.object(L, '_tool', side_effect=lambda *a: tools.append(a) or next(results)),                 mock.patch.object(LM, 'file_hash', side_effect=lambda path, real=LM.file_hash:
                                  real(path) if Path(path).exists() else key(str(path))), \
                mock.patch.object(RUN, '_tree', return_value={'files': 2, 'bytes': 9}):
            code = L.run_stage(self.profile_path, self.pin, stage='interval', interval=2, environ={},
                               emit=lambda line: None, **GATE)
        record = json.loads((self.attempt/'stage-interval-0002.json').read_text(encoding='utf8'))
        self.assertEqual((code, record['status'], record['interval']), (0, L.GATE_STOP, 2))
        self.assertEqual(command.call_args.kwargs['parent_adopted_sha256'], pin)
        self.assertEqual(reader.call_args.kwargs['interval'], 2)
        for arguments in tools:
            self.assertEqual(arguments[arguments.index('--interval')+1], '2')

    def test_run_stage_passes_the_explicit_pin_to_preflight(self):
        with mock.patch.object(L, 'preflight', side_effect=RuntimeError('preflight reached')) as preflight,                 self.assertRaisesRegex(RuntimeError, 'preflight reached'):
            L.run_stage(self.profile_path, self.pin, stage='interval', interval=2, environ={},
                        emit=lambda line: None, parent_adopted_sha256=key('a'), **GATE)
        self.assertEqual(preflight.call_args.kwargs['parent_adopted_sha256'], key('a'))

    def test_main_passes_the_interval(self):
        base = ['--profile', str(self.profile_path), '--profile-sha256', self.pin, '--stage', 'interval',
                '--interval', '2']
        with mock.patch.object(L, 'run_stage', return_value=0) as stage:
            self.assertEqual(L.main(base), 0)
        self.assertEqual((stage.call_args.kwargs['interval'], stage.call_args.kwargs['parent_adopted_sha256']),
                         (2, None))
        with mock.patch.object(L, 'run_stage', return_value=0) as stage:
            self.assertEqual(L.main([*base, '--parent-adopted-sha256', key('a')]), 0)
        self.assertEqual(stage.call_args.kwargs['parent_adopted_sha256'], key('a'))
        plan = {'argv': [], 'record': {'memory': {}, 'start_gate': {}, 'disk': {}}, 'seed': None}
        with mock.patch.object(L, 'preflight', return_value=plan) as preflight, \
                mock.patch('builtins.print'):
            self.assertEqual(L.main([*base, '--preflight-only', '--parent-adopted-sha256', key('a')]), 0)
        self.assertEqual((preflight.call_args.kwargs['interval'], preflight.call_args.kwargs['parent_adopted_sha256']),
                         (2, key('a')))


if __name__ == '__main__':
    unittest.main()
