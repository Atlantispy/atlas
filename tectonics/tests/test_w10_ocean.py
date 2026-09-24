"""Small independent mathematical, source and reporting checks for W10 heat flow."""
import copy
import importlib.util
import json
import math
from pathlib import Path
import unittest

import numpy as np
from numpy.testing import assert_allclose

from atlas_tectonics.resources import WorkBudget

SPEC = importlib.util.spec_from_file_location('w10_ocean', Path(__file__).resolve().parents[1]/'tools/w10_ocean.py')
w10 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(w10)


class W10OceanTests(unittest.TestCase):
    def test_surface_derivative_against_independent_constant_plate_series(self):
        case, _ = w10.load_case()
        parameters = w10.baseline_parameters(case)
        ages = np.array([40., 60., 100., 165.])
        clock = case['model']['seconds_per_year']
        th = parameters.thermal
        scale = parameters.conductivity_w_m_k*(th.mantle_temperature_k-th.surface_temperature_k)/parameters.thickness_m
        expected = [scale*(1+2*math.fsum(math.exp(-th.diffusivity_m2_s*n*n*math.pi**2*
                    age*1e6*clock/parameters.thickness_m**2) for n in range(1, 101))) for age in ages]
        actual, refinement = w10._evaluate(ages, parameters, clock, WorkBudget(1024*1024))
        assert_allclose(actual, expected, rtol=0, atol=1e-9)
        self.assertTrue(refinement['passed'])

    def test_dispersion_statistic_and_fixed_selection(self):
        case, _ = w10.load_case()
        data = w10.validate_case(case)
        self.assertEqual(data.shape, (50, 7))
        sigma = (data[:, 5]-data[:, 4])/1.349
        result = w10.comparison(data, data[:, 3]+2*sigma)
        self.assertAlmostEqual(result['rms_scaled_residual'], 2.)
        self.assertEqual(result['dispersion_verdict'], 'NOT_CONSISTENT_WITH_OBSERVED_DISPERSION')
        self.assertEqual(w10.comparison(data, data[:, 3])['rms_scaled_residual'], 0.)

    def test_malformed_observations_screen_and_source_changes_refuse(self):
        original, _ = w10.load_case()
        for change in ('missing_bin', 'duplicate_age', 'nan', 'quartiles', 'boolean', 'threshold'):
            case = copy.deepcopy(original)
            if change == 'missing_bin': case['observations'].pop()
            elif change == 'duplicate_age': case['observations'][1][0] = case['observations'][0][0]
            elif change == 'nan': case['observations'][0][2] = math.nan
            elif change == 'quartiles': case['observations'][0][4] = case['observations'][0][5]
            elif change == 'boolean': case['observations'][0][1] = True
            else: case['screen']['maximum_rms_scaled_residual'] = 2.
            with self.subTest(change=change), self.assertRaises(ValueError):
                w10.validate_case(case)
        case = copy.deepcopy(original)
        case['model']['case_sha256'] = '0'*64
        with self.assertRaisesRegex(ValueError, 'source bytes changed'):
            w10.baseline_parameters(case)
        case = copy.deepcopy(original)
        case['model']['constants']['conductivity_w_m_k'] = 4.
        with self.assertRaisesRegex(ValueError, 'no calibration'):
            w10.baseline_parameters(case)
        params = w10.baseline_parameters(original)
        with self.assertRaises(ValueError):
            w10.surface_flux([0.], params, 31557600., 2.5, WorkBudget(1024*1024))

    def test_complete_run_retains_baseline_and_explicit_claim_boundaries(self):
        before = w10.CASE_PATH.read_bytes()
        result = w10.run_challenge()
        self.assertEqual(before, w10.CASE_PATH.read_bytes())
        self.assertEqual(len(result['observations']), 50)
        self.assertEqual(len(result['sensitivity']['cases']), 8)
        self.assertEqual(len(result['age_bin_edges']['cases']), 2)
        self.assertTrue(result['all_numerical_checks_passed'])
        self.assertEqual(result['status'], result['baseline']['dispersion_verdict'])
        self.assertFalse(result['calibration_performed'])
        self.assertFalse(result['calibrated_confidence'])
        self.assertFalse(result['whole_tectonics_acceptance'])
        self.assertIsNone(result['selected_sensitivity_model'])
        self.assertEqual(result['model_input']['constants']['conductivity_w_m_k'], 3.3)
        self.assertEqual(result['resources']['accounted_kernel_budget']['reserved_bytes'], 0)
        json.dumps(result, allow_nan=False)


if __name__ == '__main__':
    unittest.main()
