"""Focused worker orchestration guards; native physics is exercised separately."""
from concurrent.futures import CancelledError
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tools'))
import w12_job_worker as worker


class FakeNative:
    """Small committed-store seam retaining owner and cancellation semantics."""

    def __init__(self):
        fixture = self
        self.events = []
        self.saved = {}
        self.fail_output = None
        self.fail_verify = None
        self.fail_graph = False
        self.graph_restored = False
        self.before_graph_return = lambda: None
        self.runtime = {'python': 'fake; orchestration test only'}
        self.np = SimpleNamespace(full=lambda n, value: [value]*n,
                                  zeros=lambda n: [0.]*n)

        class Budget:
            def __init__(self, maximum):
                self.maximum, self.reserved_bytes, self.peak = maximum, 0, 0
                fixture.budget = self

            def charge(self, amount):
                self.reserved_bytes += amount
                self.peak = max(self.peak, self.reserved_bytes)

            def statistics(self):
                return dict(max_bytes=self.maximum, reserved_bytes=self.reserved_bytes,
                            peak_reserved_bytes=self.peak)

        class Store:
            def __init__(self, path, *, limits, budget):
                self.path, self.budget = path, budget
                self.outputs = fixture.saved.setdefault(str(path), {})
                path.touch(exist_ok=True)
                fixture.limits = limits

            def __enter__(self):
                self.budget.charge(10)
                fixture.events.append('store_open')
                return self

            def __exit__(self, *args):
                fixture.events.append('store_close')
                self.budget.charge(-10)

            def statistics(self):
                return {'committed': len(self.outputs)}

        class Plan:
            def __init__(self, initial, surface, policy, schedule, **options):
                options['cancel'].check()
                self.store, self.budget = options['store'], options['budget']
                self.stats = dict(computed_outputs=0, restored_outputs=0)
                fixture.events.append(('plan_created', options['context']))

            def __enter__(self):
                self.budget.charge(20)
                fixture.events.append('plan_open')
                return self

            def __exit__(self, *args):
                fixture.events.append('plan_close')
                self.budget.charge(-20)

            def run(self, output_index=None, *, cancel=None):
                fixture.events.append(('run', output_index))
                target = 2 if output_index is None else output_index
                for index in range(target+1):
                    cancel.check()
                    if index == fixture.fail_output:
                        raise RuntimeError('native output failed')
                    if index in self.store.outputs:
                        self.stats['restored_outputs'] += 1
                    else:
                        self.store.outputs[index] = dict(product_id=str(index)*64, output_index=index)
                        self.stats['computed_outputs'] += 1
                cancel.check()
                return dict(self.store.outputs[target])

            def verify_product(self, product):
                index = product['output_index']
                if index == fixture.fail_verify:
                    raise ValueError('native commit verification failed')
                if product != self.store.outputs[index]:
                    raise ValueError('missing native commit')
                fixture.events.append(('verified', index))

            def statistics(self):
                return dict(self.stats)

        self.WorkBudget = Budget
        self.ArrayStore = Store
        self.PreparedColumnAssembly = Plan
        self.StoreLimits = lambda *args, **kwargs: (args, kwargs)

    def make_column_case(self, *, cells, budget):
        self.events.append(('case', cells))
        return dict(initial=None, initial_surface=None, support_policy=None, schedule=(1, 2),
            provenance=dict(source_id='synthetic-test', epoch={'id': 'epoch'},
                frame={'id': 'frame', 'depth_reference_id': 'datum'}))

    def run_graph(self, plan, *, graph_cache_root):
        if graph_cache_root.name != 'g':
            raise AssertionError('keep the Windows-compatible short cache leaf')
        self.events.append('graph')
        if self.graph_restored:
            product = dict(plan.store.outputs[2])
        else:
            product = plan.run(output_index=None)
        if self.fail_graph:
            raise ValueError('graph verification failed')
        self.before_graph_return()
        return {'product': product, 'execution': {'computed': not self.graph_restored}}


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)/'run'
        self.native = FakeNative()
        self.stop = False
        self.progress = []
        self.patch = patch.object(worker, '_native', return_value=self.native)
        self.loader = self.patch.start()
        self.addCleanup(self.patch.stop)

    def execute(self, **overrides):
        options = dict(cells=8, resume=False, cancelled=lambda: self.stop,
                       progress=self.progress.append)
        options.update(overrides)
        return worker.execute(self.directory, **options)

    def reports(self):
        return [json.loads(path.read_text()) for path in sorted(self.directory.glob('run-*.json'))]

    def assert_closed(self):
        self.assertEqual(self.native.events[-2:], ['plan_close', 'store_close'])
        self.assertEqual(self.native.budget.reserved_bytes, 0)

    def test_complete_outputs_have_immutable_reader_compatible_reports(self):
        result = self.execute()
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(result['completed_outputs'], 3)
        self.assertEqual(result['computed_outputs'], 3)
        self.assertEqual(result['restored_outputs'], 3)
        self.assertEqual(result['report'], 'run-00004.json')
        reports = self.reports()
        self.assertEqual([r['product']['output_index'] for r in reports], [0, 1, 2, 2])
        self.assertEqual([r['status'] for r in reports], ['PASS_SUPPORTED_NATIVE_PREFIX']*3+
                         ['PASS_SUPPORTED_SYNTHETIC_ASSEMBLY'])
        expected = {path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in (ROOT/'tools/run_tectonics.py', ROOT/'examples/w12_column_case.py')}
        self.assertEqual(reports[-1]['configuration']['example_sources'], expected)
        self.assertEqual(reports[-1]['released_resources']['reserved_bytes'], 0)
        self.assertEqual(self.native.budget.maximum, 128 << 20)
        self.assertEqual(self.native.limits[0][2], 32 << 20)
        self.assert_closed()

    def test_cancel_before_case_does_not_compute_or_report(self):
        self.stop = True
        result = self.execute()
        self.assertEqual(result['status'], 'cancelled')
        self.assertIsNone(result['report'])
        self.assertIsNone(result['product_id'])
        self.loader.assert_not_called()
        self.assertFalse((self.directory/'native.sqlite').exists())

    def test_cancel_after_commit_preserves_prefix_and_resume_only_computes_missing(self):
        def progress(value):
            self.progress.append(value)
            if value['phase'] == 'output_committed':
                self.stop = True
        first = self.execute(progress=progress)
        self.assertEqual(first['status'], 'cancelled')
        self.assertEqual(first['completed_outputs'], 1)
        self.assertEqual(first['report'], 'run-00001.json')
        original = (self.directory/first['report']).read_bytes()
        self.assert_closed()
        self.stop = False
        second = self.execute(resume=True)
        self.assertEqual(second['status'], 'completed')
        self.assertEqual(second['computed_outputs'], 2)
        self.assertEqual(second['restored_outputs'], 4)
        self.assertEqual((self.directory/first['report']).read_bytes(), original)
        self.assertEqual(len(self.reports()), 5)
        self.assert_closed()

    def test_failure_does_not_publish_half_output_or_swallow_error(self):
        self.native.fail_output = 1
        with self.assertRaisesRegex(RuntimeError, 'native output failed'):
            self.execute()
        self.assertEqual([r['product']['output_index'] for r in self.reports()], [0])
        self.assertNotIn('completed', [value['phase'] for value in self.progress])
        self.assert_closed()

    def test_unverified_commit_is_not_advertised(self):
        self.native.fail_verify = 0
        with self.assertRaisesRegex(ValueError, 'native commit verification failed'):
            self.execute()
        self.assertEqual(self.reports(), [])
        self.assertTrue(all(value['report'] is None for value in self.progress))
        self.assert_closed()

    def test_graph_failure_keeps_final_native_prefix_without_graph_success(self):
        self.native.fail_graph = True
        with self.assertRaisesRegex(ValueError, 'graph verification failed'):
            self.execute()
        self.assertEqual([r['product']['output_index'] for r in self.reports()], [0, 1, 2])
        self.assertEqual(self.progress[-1]['report'], 'run-00003.json')
        self.assert_closed()

    def test_completed_graph_wins_late_cancellation(self):
        self.native.before_graph_return = lambda: setattr(self, 'stop', True)
        result = self.execute()
        self.assertTrue(self.stop)
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(result['report'], 'run-00004.json')
        self.assert_closed()

    def test_graph_cache_restore_still_reports_verified_final_commit(self):
        self.execute()
        self.native.graph_restored = True
        result = self.execute(resume=True)
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(result['computed_outputs'], 0)
        self.assertEqual([r['product']['output_index'] for r in self.reports()], [0, 1, 2, 2]*2)
        self.assert_closed()

    def test_changed_source_or_cells_refuse_resume_without_repin(self):
        self.execute()
        with self.assertRaisesRegex(ValueError, 'binding differs'):
            self.execute(cells=9, resume=True)
        path = self.directory/'case.json'
        changed = json.loads(path.read_text())
        changed['example_sources']['tools/run_tectonics.py'] = '0'*64
        path.write_text(json.dumps(changed))
        before = path.read_bytes()
        with self.assertRaisesRegex(ValueError, 'binding differs'):
            self.execute(resume=True)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(len(self.reports()), 4)

    def test_invalid_cells_and_existing_fresh_directory_refuse(self):
        for value in (True, 4, 65, 8.0):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.execute(cells=value)
            self.assertFalse(self.directory.exists())
        self.directory.mkdir()
        with self.assertRaises(FileExistsError):
            self.execute()
        self.loader.assert_not_called()

    def test_progress_error_closes_native_owners(self):
        def progress(value):
            if value['phase'] == 'output_committed':
                raise OSError('status publication failed')
        with self.assertRaisesRegex(OSError, 'status publication failed'):
            self.execute(progress=progress)
        self.assertEqual(len(self.reports()), 1)
        self.assert_closed()

    def test_cancel_event_adapter_uses_native_contract(self):
        event = worker._Cancellation(lambda: True)
        self.assertTrue(event.is_set())
        with self.assertRaises(CancelledError):
            event.check()


if __name__ == '__main__':
    unittest.main()
