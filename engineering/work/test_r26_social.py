"""Focused native parity, partial reuse and coastal checkpoint safeguards."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import time
import unittest

from work.generator_upgrade_r26 import social


class SocialTests(unittest.TestCase):
    measurements = []

    @classmethod
    def setUpClass(cls):
        cls.inputs = social.fixtures()

    def test_complete_political_and_coupled_agriculture_cache_parity(self):
        parent = Path(__file__).resolve().parents[1]/'c26t'
        parent.mkdir(exist_ok=True)
        for operation in ('political_districts', 'agriculture'):
            with self.subTest(operation=operation), tempfile.TemporaryDirectory(prefix='s', dir=parent) as temp:
                root = Path(temp)
                arguments = self.inputs[operation]
                original = deepcopy(arguments)
                started = time.perf_counter()
                baseline = social.baseline(operation, arguments, cache=True, cache_root=root/'b')
                baseline_cold = time.perf_counter()-started
                started = time.perf_counter()
                baseline_warm = social.baseline(operation, arguments, cache=True, cache_root=root/'b')
                baseline_warm_s = time.perf_counter()-started
                started = time.perf_counter()
                adapter = social.Adapter(operation, cache=True, cache_root=root/'a')
                setup_s = time.perf_counter()-started
                started = time.perf_counter()
                actual = adapter.run(arguments, {})
                cold_s = time.perf_counter()-started
                cold_reporting = deepcopy(adapter.last_diagnostics)
                started = time.perf_counter()
                warm = adapter.run(arguments, {})
                warm_s = time.perf_counter()-started
                self.assertEqual(actual, baseline)
                self.assertEqual(warm, baseline_warm)
                self.assertEqual(baseline, baseline_warm)
                self.assertEqual(arguments, original)
                self.assertEqual(actual['scientific']['status'], 'MODELLED')
                cold_stages = [row for row in cold_reporting if 'hit' in row]
                warm_stages = [row for row in adapter.last_diagnostics if 'hit' in row]
                self.assertTrue(cold_stages)
                self.assertTrue(all(not row['hit'] for row in cold_stages))
                self.assertTrue(all(row['hit'] for row in warm_stages))
                self.assertTrue(all(not row['warnings'] for row in cold_stages+warm_stages))
                adapter.validate_result(warm, arguments, {})
                self.measurements.append({'operation': operation, 'baseline_cold_s': baseline_cold,
                    'baseline_warm_s': baseline_warm_s, 'adapter_setup_s': setup_s,
                    'adapter_cold_s': cold_s, 'adapter_warm_s': warm_s,
                    'cold_saved_s': baseline_cold-cold_s,
                    'cold_saved_percent': 100*(baseline_cold-cold_s)/baseline_cold,
                    'warm_saved_s': baseline_warm_s-warm_s,
                    'warm_saved_percent': 100*(baseline_warm_s-warm_s)/baseline_warm_s,
                    'equal_scientific_and_native_execution': True, 'stage_count': len(cold_stages)})
                if operation == 'agriculture':
                    changed = deepcopy(arguments)
                    changed['scenario']['food']['windows'][-1]['obligations'][0]['amount'] = '3000'
                    value = adapter.run(changed, {})
                    self.assertNotEqual(value['scientific_sha256'], actual['scientific_sha256'])
                    self.assertTrue(all(row['hit'] for row in adapter.last_diagnostics if row['stage'] != 'food'))
                    self.assertTrue(all(not row['hit'] for row in adapter.last_diagnostics if row['stage'] == 'food'))
                    self.assertEqual(value['scientific']['production'], actual['scientific']['production'])
                else:
                    changed = deepcopy(arguments)
                    changed['political']['atom_evidence']['atom-0']['A']['physical_compatibility_u'] += 1
                    adapter.run(changed, {})
                    stages = [row for row in adapter.last_diagnostics if 'hit' in row]
                    self.assertTrue(all(row['hit'] for row in stages if row.get('stage') != 'assignment'))
                    self.assertTrue(all(not row['hit'] for row in stages if row.get('stage') == 'assignment'))

    def test_native_coastal_continuation_and_private_checkpoint_store(self):
        arguments = self.inputs['coastal_advance']
        started = time.perf_counter()
        baseline = social.baseline('coastal_advance', arguments)
        baseline_s = time.perf_counter()-started
        parent = Path(__file__).resolve().parents[1]/'c26t'
        parent.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='c', dir=parent) as temp:
            started = time.perf_counter()
            adapter = social.Adapter('coastal_advance', cache=True, cache_root=Path(temp))
            setup_s = time.perf_counter()-started
            started = time.perf_counter()
            actual = adapter.run(arguments, {})
            run_s = time.perf_counter()-started
            self.assertEqual(actual, baseline)
            self.assertEqual(actual['scientific']['accounts']['water_residual_m3'], '0')
            adapter.validate_result(actual, arguments, {})
            cache = adapter._coastal_cache()()
            receipt = cache.save_checkpoint({'fixture': 'exact-r26-native-continuation'}, actual)
            self.assertIs(receipt['saved'], True)
            self.assertEqual(cache.load_checkpoint({'fixture': 'exact-r26-native-continuation'}), actual)
            broken = deepcopy(actual)
            broken['scientific']['time_s'] = '1'
            broken['scientific_sha256'] = adapter.p.sha(broken['scientific'])
            with self.assertRaises(ValueError):
                adapter.validate_result(broken, arguments, {})
            with self.assertRaisesRegex(ValueError, 'disjoint'):
                adapter.run(arguments, {'checkpoint': arguments['checkpoint']})
            self.measurements.append({'operation': 'coastal_advance', 'baseline_s': baseline_s,
                'adapter_setup_s': setup_s, 'adapter_run_s': run_s,
                'saved_s': baseline_s-run_s, 'saved_percent': 100*(baseline_s-run_s)/baseline_s,
                'equal_native_checkpoint': True, 'private_checkpoint_saved_and_restored': True})


if __name__ == '__main__':
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(SocialTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    print(json.dumps({'measurements': SocialTests.measurements}, sort_keys=True))
    raise SystemExit(not result.wasSuccessful())
