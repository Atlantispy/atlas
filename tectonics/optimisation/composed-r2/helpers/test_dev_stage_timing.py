"""WP19 checkpoint controls and recorder/report integration; no physics."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import dev_stage_timing as D
import dev_stage_timing_report as REPORT


HERE = Path(__file__).resolve().parent
SCRATCH = HERE.parents[3]/'_t'/'wp19'
RESOURCE = HERE/'composed-r1/runtime-src/atlas_tectonics/resources.py'
spec = importlib.util.spec_from_file_location('_wp19_resources', RESOURCE)
resources = importlib.util.module_from_spec(spec)
spec.loader.exec_module(resources)


class Clock:
    wall = 0
    cpu = 0

    def advance(self, wall, cpu):
        self.wall += wall
        self.cpu += cpu


class Guard:
    def __init__(self, budget=None):
        self.budget = budget
        self.calls = []
        self.failure = None
        self.result = object()

    def check(self, force=False):
        self.calls.append(('check', force))
        if self.failure is not None:
            raise self.failure
        return False

    def phase(self, name):
        self.check(force=True)
        self.calls.append(('phase', name))
        return self.result


class Timing(unittest.TestCase):
    def setUp(self):
        SCRATCH.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=SCRATCH)
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.record = {}
        self.clock = Clock()

    def recorder(self, **kwargs):
        return D.Recorder(self.directory, self.record,
            clock=lambda: self.clock.wall, cpu=lambda: self.clock.cpu,
            memory=lambda: {'parent_rss_bytes': 10}, **kwargs)

    def events(self):
        return [json.loads(line) for line in (self.directory/D.FILENAME).read_bytes().splitlines()]

    def test_explicit_flag_and_strict_environment(self):
        for flag, env, expected in ((False, {}, False), (False, {D.ENV: '0'}, False),
                (False, {D.ENV: '1'}, True), (True, {}, True), (True, {D.ENV: '0'}, True)):
            self.assertEqual(D.enabled(flag, env), expected)
        for env in ('true', 'yes', ' 1', '2'):
            with self.assertRaises(ValueError):
                D.enabled(False, {D.ENV: env})
        with self.assertRaises(ValueError):
            D.enabled(1, {})

    def test_disabled_has_no_diagnostic_effects(self):
        guard = Guard()
        before = dict(guard.__dict__)
        with patch.object(D, 'Recorder', side_effect=AssertionError('must not construct')):
            with D.collect(guard, self.directory, enabled=False, record=self.record):
                self.assertFalse(guard.check(force=True))
        self.assertEqual(list(self.directory.iterdir()), [])
        self.assertEqual(self.record, {})
        self.assertEqual(set(guard.__dict__), set(before))

    def test_checkpoint_clocks_and_report_reconcile(self):
        recorder = self.recorder()
        self.clock.advance(10, 2)
        recorder.checkpoint('geometry')
        self.clock.advance(90, 21)
        recorder.checkpoint('finish')
        self.clock.advance(50, 11)
        recorder.close('ok')
        report = REPORT.build_report(self.directory/D.FILENAME)
        self.assertEqual(report['status'], 'COMPLETE')
        self.assertEqual(report['stages']['summed_wall_ns'], 150)
        self.assertEqual(report['stages']['summed_process_cpu_ns'], 34)
        self.assertEqual([(r['phase'], r['wall_ns']) for r in report['stages']['rows']],
                         [('geometry', 10), ('finish', 90), ('timing-finalisation', 50)])
        self.assertEqual([e['seq'] for e in self.events()], list(range(4)))

    def test_guard_methods_return_values_and_existing_hooks_preserved(self):
        guard = Guard(resources.WorkBudget(2*D.WORKSPACE_BYTES))
        trace, profile = sys.gettrace(), sys.getprofile()
        before = set(guard.__dict__)
        with D.collect(guard, self.directory, enabled=True, record=self.record):
            self.assertIs(guard.phase('geometry'), guard.result)
            D.checkpoint('geometry')
            self.assertFalse(guard.check(force=True))
            self.assertEqual(guard.budget.reserved_bytes, D.WORKSPACE_BYTES)
            self.assertEqual((sys.gettrace(), sys.getprofile()), (trace, profile))
        self.assertEqual(set(guard.__dict__), before)
        self.assertEqual(guard.budget.reserved_bytes, 0)
        self.assertEqual(self.record['dev_stage_timing']['status'], 'CLOSED')

    def test_guard_exception_identity_and_instance_method_restore(self):
        guard = Guard()
        marker = RuntimeError('guard cancelled workload')
        guard.failure = marker
        guard.check = guard.check
        original = guard.check
        with self.assertRaises(RuntimeError) as caught:
            with D.collect(guard, self.directory, enabled=True, record=self.record):
                guard.phase('geometry')
        self.assertIs(caught.exception, marker)
        self.assertIs(guard.check, original)
        self.assertNotIn('phase', guard.__dict__)
        self.assertEqual(self.events()[-1]['workload_status'], 'error')

    def test_workload_base_exception_preserved_and_closed(self):
        class Cancelled(BaseException):
            pass
        marker = Cancelled('cancelled')
        guard = Guard(resources.WorkBudget(2*D.WORKSPACE_BYTES))
        with self.assertRaises(Cancelled) as caught:
            with D.collect(guard, self.directory, enabled=True, record=self.record):
                raise marker
        self.assertIs(caught.exception, marker)
        self.assertEqual(guard.budget.reserved_bytes, 0)
        report = REPORT.build_report(self.directory/D.FILENAME)
        self.assertEqual(report['status'], 'COMPLETE')
        self.assertEqual(report['coverage']['workload_status'], 'error')

    def test_late_budget_binding_and_optional_refusal(self):
        holder = [None]
        recorder = self.recorder(budget=lambda: holder[0])
        budget = holder[0] = resources.WorkBudget(D.WORKSPACE_BYTES-1)
        recorder.checkpoint('geometry')
        self.assertFalse(recorder.active)
        self.assertEqual(budget.reserved_bytes, 0)
        self.assertEqual(budget.statistics()['refusals'], 0)
        self.assertEqual(self.record['dev_stage_timing']['status'], 'INCOMPLETE')
        recorder.close('ok')

    def test_io_failure_disables_recording_and_releases_budget(self):
        budget = resources.WorkBudget(2*D.WORKSPACE_BYTES)
        recorder = self.recorder(budget=lambda: budget)
        recorder.stream.close()
        recorder.checkpoint('geometry')
        self.assertFalse(recorder.active)
        self.assertEqual(budget.reserved_bytes, 0)
        recorder.close('ok')
        self.assertEqual(REPORT.build_report(self.directory/D.FILENAME)['status'], 'INCOMPLETE')

    def test_release_failure_is_visible_without_masking_workload(self):
        class BrokenLease:
            def __enter__(self):
                return True
            def __exit__(self, *args):
                raise RuntimeError('release failed')
        class BrokenBudget:
            reserved_bytes = 0
            def try_reserve(self, *args, **kwargs):
                return BrokenLease()
        guard = Guard(BrokenBudget())
        marker = RuntimeError('scientific failure')
        with self.assertRaises(RuntimeError) as caught:
            with D.collect(guard, self.directory, enabled=True, record=self.record):
                raise marker
        self.assertIs(caught.exception, marker)
        self.assertIn('release failed', self.record['dev_stage_timing']['release_error'])
        self.assertEqual(self.record['dev_stage_timing']['status'], 'INCOMPLETE')

    def test_existing_output_is_preserved_and_workload_continues(self):
        path = self.directory/D.FILENAME
        path.write_bytes(b'previous diagnostic')
        guard = Guard()
        with D.collect(guard, self.directory, enabled=True, record=self.record) as recorder:
            self.assertIsNone(recorder)
            self.assertFalse(guard.check())
        self.assertEqual(path.read_bytes(), b'previous diagnostic')
        self.assertEqual(self.record['dev_stage_timing']['status'], 'INCOMPLETE')

    def test_stream_cap_preserves_bounded_valid_prefix(self):
        recorder = self.recorder(max_bytes=D.MAX_LINE_BYTES)
        for _ in range(200):
            recorder.checkpoint('geometry')
        recorder.close('ok')
        self.assertLessEqual((self.directory/D.FILENAME).stat().st_size, D.MAX_LINE_BYTES)
        self.assertEqual(self.record['dev_stage_timing']['status'], 'INCOMPLETE')
        self.assertEqual(REPORT.build_report(self.directory/D.FILENAME)['status'], 'INCOMPLETE')

    def test_stage_limit_matches_report(self):
        recorder = self.recorder()
        with patch.object(D, 'MAX_NAMES', 2):
            recorder.checkpoint('geometry')
            recorder.checkpoint('finish')
        self.assertFalse(recorder.active)
        self.assertEqual(len(recorder.names), 1)
        recorder.close('ok')
        self.assertEqual(REPORT.build_report(self.directory/D.FILENAME)['status'], 'INCOMPLETE')

    def test_no_work_inside_stage_and_memory_only_at_checkpoints(self):
        guard = Guard(resources.WorkBudget(2*D.WORKSPACE_BYTES))
        original_check = guard.check
        calls = []
        with D.collect(guard, self.directory, enabled=True, record=self.record) as recorder:
            recorder.memory = lambda: calls.append(True) or {'parent_rss_bytes': 20}
            initial_size = recorder.bytes
            for _ in range(100):
                self.assertFalse(guard.check(force=True))
            self.assertEqual(guard.check, original_check)
            self.assertNotIn('check', guard.__dict__)
            self.assertEqual(recorder.bytes, initial_size)
            self.assertEqual(calls, [])
            guard.phase('geometry')
            self.assertEqual(len(calls), 0)
            D.checkpoint('geometry')
            self.assertEqual(len(calls), 1)
        self.assertEqual(len(calls), 2)
        self.assertEqual([e['event'] for e in self.events()], ['session_start', 'checkpoint', 'session_end'])
        self.assertFalse(hasattr(D, 'observe_query'))

    def test_memory_failure_does_not_stop_clocks(self):
        recorder = self.recorder()
        recorder.memory = lambda: (_ for _ in ()).throw(OSError('memory unavailable'))
        self.clock.advance(1_000_000_000, 10)
        recorder.checkpoint('geometry')
        recorder.close('ok')
        self.assertIn('memory unavailable', self.record['dev_stage_timing']['memory_error'])
        self.assertEqual(REPORT.build_report(self.directory/D.FILENAME)['status'], 'COMPLETE')

    def test_clock_regression_is_incomplete(self):
        recorder = self.recorder()
        self.clock.advance(-1, 0)
        recorder.checkpoint('geometry')
        recorder.close('ok')
        self.assertEqual(self.record['dev_stage_timing']['status'], 'INCOMPLETE')
        self.assertEqual(REPORT.build_report(self.directory/D.FILENAME)['status'], 'INCOMPLETE')

    def test_successor_composer_binds_only_helper(self):
        import assemble_resumable as assembler
        self.assertEqual(assembler.COPIED_HELPERS['dev_stage_timing.py'], 'dev_stage_timing.py')
        self.assertIn('dev_stage_timing.py', assembler.REVIEWED_FILES)
        self.assertFalse(any(name == 'stage_timing_patch' for name, _ in assembler.TRANSFORMERS))
        source = (HERE/'compact-geometry-r1/heat_payload_indexed_patch.py').read_text(encoding='utf8')
        self.assertNotIn('dev_stage_timing', assembler.literal(source, 'WORKER_RUNTIME_HELPERS'))


if __name__ == '__main__':
    unittest.main()
