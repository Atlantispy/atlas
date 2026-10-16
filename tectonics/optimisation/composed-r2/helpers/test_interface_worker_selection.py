"""Interface worker ceiling from interval 2: default 4, 6 only if it fits, clamped to the policy."""
import sys
import unittest
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import interface_worker_selection as S

GIB = 1 << 30


def policy(maximum):
    @dataclass(frozen=True)
    class Policy:
        """Stands in for InterfaceParallelPolicy: RC1's envelopes, refusing more than ``maximum`` workers."""
        workers: int = 2
        child_bytes: int = 512 << 20
        ram_reserve_bytes: int = 2 << 30
        budget_fraction: float = 0.5

        def __post_init__(self):
            if not 1 <= self.workers <= maximum:
                raise ValueError('worker count refused')
    return Policy


def choose(maximum=6, *, cores=8, load=0.0, available=24*GIB, real=2*GIB, logical=3*GIB, budget=16*GIB):
    return S.select(policy_type=policy(maximum), child_baseline_bytes=256 << 20, parent_storage_bytes=64 << 20,
                    raw_result_bytes=1 << 20, parent={'real_peak_bytes': real, 'logical_peak_bytes': logical},
                    machine={'physical_cores': cores, 'logical_cpus': 2*cores, 'load_percent': load,
                             'available_bytes': available}, logical_budget_bytes=budget)


class SelectionTests(unittest.TestCase):
    def test_six_when_the_measured_footprint_fits(self):
        record = choose()
        self.assertEqual((record['selected'], record['chosen'], record['policy_maximum']), (6, 6, 6))
        self.assertEqual(record['per_worker_booked_bytes'], 768 << 20)
        self.assertTrue(all(record['checks']['six'].values()))
        self.assertEqual(record['schema'], S.SCHEMA)

    def test_default_four_when_six_do_not_fit_and_the_reason_names_the_cut(self):
        cases = (('cores', {'cores': 6}), ('memory', {'available': 8*GIB}), ('budget', {'logical': 12*GIB}))
        for name, change in cases:
            with self.subTest(limit=name):
                record = choose(**change)
                self.assertEqual(record['selected'], 4)
                self.assertFalse(record['checks']['six'][name])
                self.assertIn('six do not fit: '+name, record['reason'])

    def test_clamped_to_the_policy_maximum_until_the_cap_is_lifted(self):
        record = choose(maximum=2)
        self.assertEqual((record['selected'], record['chosen'], record['policy_maximum']), (6, 2, 2))
        self.assertIn('clamped to 2 by the policy', record['reason'])
        self.assertEqual(choose(maximum=2, cores=6)['chosen'], 2)
        self.assertEqual(choose(maximum=4)['chosen'], 4)

    def test_measured_inputs_are_required(self):
        with self.assertRaisesRegex(ValueError, 'measured parent footprint required'):
            S.select(policy_type=policy(6), child_baseline_bytes=0, parent_storage_bytes=0, raw_result_bytes=0,
                     parent={'real_peak_bytes': 1}, machine={}, logical_budget_bytes=GIB)
        with self.assertRaisesRegex(ValueError, 'measured CPU load'):
            S.select(policy_type=policy(6), child_baseline_bytes=0, parent_storage_bytes=0, raw_result_bytes=0,
                     parent={'real_peak_bytes': 1, 'logical_peak_bytes': 1},
                     machine={'physical_cores': 8, 'logical_cpus': 16, 'available_bytes': GIB},
                     logical_budget_bytes=GIB)
        with self.assertRaisesRegex(ValueError, 'accepts no worker count'):
            S.policy_maximum(policy(0))


if __name__ == '__main__':
    unittest.main()
