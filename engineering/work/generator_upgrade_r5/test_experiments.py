"""Actual strict connected trial, explicit work-limit sensitivity and oracle."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import unittest

from . import binding, experiments

ORACLE = Path(__file__).resolve().parents[2] / 'outputs/generator-upgrade-r5/diagnosis-upstream-02/independent-oracle.json'
ORACLE_SHA = 'f9d76cccb581e3a11b6a5cc112f7c461c8c3144d0260e6f78e846118f272d3ea'


class StrictExperimentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bundle = binding.load()
        cls.recipes = [experiments.strict_recipe(cls.bundle, minimum_dt=minimum, max_steps=budget)
                       for minimum, budget in ((1e-4,1000), (1e-8,1000), (1e-8,10000))]
        cls.reports = [experiments.trial_report(cls.bundle, recipe) for recipe in cls.recipes]

    def test_original_minimum_is_temporal_not_nonlinear_failure(self):
        result = self.reports[0]
        self.assertEqual(result['status'], 'NUMERICAL_FAILURE')
        last = result['solver_calls'][-1]['diagnostics']['last_trial']
        self.assertEqual(last['gate'], 'temporal_accuracy')
        self.assertTrue(all(last['nonlinear_solutions_accepted'].values()))
        self.assertEqual(last['worst_component'], 'head_m')
        self.assertGreater(last['error_components']['head_m']['error_ratio'], 2000)
        self.assertIn('column lower; head_m at cell 0', result['failure'])
        self.assertIn('error/allowance=', result['failure'])
        self.assertNotIn('following_state', result)

    def test_finer_minimum_alone_honestly_exhausts_work_budget(self):
        result = self.reports[1]
        self.assertEqual(result['status'], 'NUMERICAL_FAILURE')
        self.assertIn('adaptive work budget exceeded', result['failure'])
        self.assertNotIn('following_state', result)

    def test_finer_minimum_and_explicit_larger_budget_solve_both_columns(self):
        result = self.reports[2]
        self.assertEqual(result['status'], 'MODELLED', result['failure'])
        self.assertEqual({r['column_id'] for r in result['solver_calls']}, {'lower','upper'})
        for row in result['solver_calls']:
            self.assertEqual(row['status'], 'MODELLED')
            self.assertLessEqual(abs(row['water_residual_m']), 1e-10)
            self.assertLessEqual(row['numerics']['maximum_error_ratio'], 1)
            self.assertGreater(row['numerics']['attempts'], 1000)
            self.assertLessEqual(row['numerics']['attempts'], 10000)

    def test_only_explicit_step_floor_and_work_budget_differ(self):
        normalised = []
        for recipe in self.recipes:
            value = deepcopy(recipe)
            controls = value['physical_recipe']['water_controls']
            del controls['min_dt_s']; del controls['max_steps']
            normalised.append(value)
        self.assertEqual(normalised[0], normalised[1])
        self.assertEqual(normalised[0], normalised[2])

    def test_supported_column_agrees_with_pinned_independent_time_integrator(self):
        raw = ORACLE.read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), ORACLE_SHA)
        oracle = json.loads(raw)
        self.assertLess(oracle['between_oracle_final_head_max_difference_m'], 1e-12)
        expected = oracle['independent_integrations'][-1]['final_head']
        observed = self.reports[2]['following_state']['members']['selected']['physical']['water']['lower']['state']['head_m']
        self.assertEqual(len(expected), len(observed))
        self.assertLess(max(abs(a-b) for a,b in zip(expected,observed)), 1e-8)

    def test_every_trial_preserves_input_and_strict_json_output(self):
        for report in self.reports:
            self.assertTrue(report['input_state_unchanged'])
            json.dumps(report, allow_nan=False)


if __name__ == '__main__':
    unittest.main()
