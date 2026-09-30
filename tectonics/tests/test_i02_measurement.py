"""I02 timing acceptance: every measured mode must agree before comparison timings are published.

SPDX-License-Identifier: AGPL-3.0-only
"""
import copy
import json
from pathlib import Path
import sys
import unittest
from unittest import mock

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
import measure_i02_workflow as harness
from atlas_tectonics import integration_evolution as E


class ComparisonTests(unittest.TestCase):
    def setUp(self):
        self.reference = dict(identity={'source_id': 'same', 'start_time_s': 2.5e6}, time_s=1e14,
                              scalars={'stretch': 1.1, 'accepted_steps': 16},
                              theta=np.array([1., -2.]), kappa=np.array([.1, .2]),
                              initial_theta=np.array([.5, -.5]), initial_kappa=np.array([.1, .1]),
                              yield_stage_counts=np.array([0, 33], dtype=np.int64), stages=33,
                              restress_mismatches=0, accounts={'heat_j_m': 1e12, 'stored_j_m': 0.})

    def child(self):
        # The actual process boundary serialises arrays to lists.
        state = json.loads(json.dumps(self.reference, default=lambda value: value.tolist()))
        return dict(status='HISTORY_COMPLETE', state=state)

    def test_restart_accepts_retained_parity_and_exact_counts(self):
        child = self.child()
        child['state']['theta'][0] += 1e-9
        child['state']['accounts']['heat_j_m'] *= 1+1e-9
        self.assertTrue(harness._reopened_matches(child, self.reference, 1e-8))

    def test_missing_extra_nonfinite_and_wrong_shape_results_are_refused(self):
        mutations = {
            'missing state': lambda c: c.pop('state'),
            'missing account': lambda c: c['state']['accounts'].pop('stored_j_m'),
            'foreign account': lambda c: c['state']['accounts'].update(foreign=1.),
            'account nan': lambda c: c['state']['accounts'].update(heat_j_m=float('nan')),
            'account infinity': lambda c: c['state']['accounts'].update(heat_j_m=float('inf')),
            'field nan': lambda c: c['state']['theta'].__setitem__(0, float('nan')),
            'broadcast field': lambda c: c['state'].update(theta=[[1., -2.]]),
            'short field': lambda c: c['state'].update(theta=[1.]),
            'empty field': lambda c: c['state'].update(theta=[]),
            'string field': lambda c: c['state'].update(theta=['1.', '-2.']),
            'changed geometry': lambda c: c['state']['scalars'].update(stretch=1.2),
            'changed stages': lambda c: c['state'].update(stages=34),
            'fractional count': lambda c: c['state'].update(stages=33.),
            'changed yield counts': lambda c: c['state']['yield_stage_counts'].__setitem__(1, 32),
            'changed initial field': lambda c: c['state']['initial_theta'].__setitem__(0, .5+1e-10),
            'changed identity': lambda c: c['state']['identity'].update(source_id='different'),
            'incomplete history': lambda c: c.update(status='COMPLETED'),
        }
        for name, change in mutations.items():
            with self.subTest(name=name):
                child = self.child()
                change(child)
                self.assertFalse(harness._reopened_matches(child, self.reference, 1e-8))

    def test_bare_comparison_checks_all_fields_and_accounts_exactly(self):
        reference = dict(theta=np.array([1., 2.]), accounts={'heat_j_m': 10.}, accepted_steps=16)
        self.assertTrue(harness._matches(copy.deepcopy(reference), reference))
        for altered in (dict(reference, theta=np.array([1., 2.])+100.),
                        dict(reference, accounts={'heat_j_m': 11.}),
                        dict(reference, theta=np.array([[1., 2.]])),
                        dict(reference, theta=np.array([1., float('nan')]))):
            with self.subTest(altered=altered):
                self.assertFalse(harness._matches(altered, reference))


class MeasurementRegressionTests(unittest.TestCase):
    def test_source_drift_withholds_all_times(self):
        bindings = harness._bindings()
        changed = dict(bindings, **{'tools/measure_i02_workflow.py': '0'*64})
        with mock.patch.object(harness, '_bindings', side_effect=[bindings, changed]):
            record = harness.measure(2, 4)
        self.assertFalse(record['checks']['sources_unchanged'])
        self.assertEqual(record['source_sha256'], bindings)
        self.assertEqual((record['status'], record['results'], record['growth'], record['derived']),
                         ('FAILED_EQUALITY', None, None, None))

    def test_review_probe_with_cold_temperature_and_reopen_account_drift_withholds_times(self):
        evolve, subprocess_run = E.evolve, harness.subprocess.run
        changed = []

        def drift_cold(*args, **kwargs):
            result = evolve(*args, **kwargs)
            if kwargs.get('modes') is None:
                changed.append(1)
                return dict(result, theta=result['theta']+100.)
            return result

        def drift_accounts(*args, **kwargs):
            done = subprocess_run(*args, **kwargs)
            self.assertEqual(done.returncode, 0, done.stderr)
            output = json.loads(done.stdout.strip().splitlines()[-1])
            output['state']['accounts'] = {'deliberately_incorrect_account': 1e99}
            done.stdout = json.dumps(output)+'\n'
            return done

        with mock.patch.object(E, 'evolve', drift_cold), mock.patch.object(harness.subprocess, 'run', drift_accounts):
            record = harness.measure(2, 4)
        self.assertEqual(changed, [1, 1])
        self.assertFalse(record['checks']['bare_cold_equals_continuation'])
        self.assertTrue(record['checks']['bare_warm_equals_continuation'])
        self.assertFalse(record['checks']['bare_equals_continuation'])
        self.assertFalse(record['checks']['reopened_within_parity'])
        self.assertTrue(record['checks']['workflow_equals_continuation'])
        self.assertEqual((record['status'], record['results'], record['growth'], record['derived']),
                         ('FAILED_EQUALITY', None, None, None))


if __name__ == '__main__':
    unittest.main()
