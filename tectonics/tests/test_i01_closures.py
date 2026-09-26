"""Focused I01 control guards; no world generation or native package import.
SPDX-License-Identifier: AGPL-3.0-only
"""
from pathlib import Path
import sys
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"tools"))
import check_i01_closures as c


class TorqueTests(unittest.TestCase):
    def test_analytic_rotation_and_work(self):
        result = c.torque_control()
        self.assertLess(max(result["relative_errors"].values()), 1e-11)

    def test_bad_quadrature_and_negative_resistance(self):
        for weights, drag in (([-1, 1], 1.), ([1, 1], -1.), ([1], 1.)):
            with self.subTest(weights=weights, drag=drag), self.assertRaises(ValueError):
                c.drag_matrix([[1,0,0], [0,1,0]], weights, drag)

    def test_nullspace_and_nonfinite_refused(self):
        for matrix in (np.zeros((3,3)), np.diag([1., 1., 0.]), np.eye(3)*np.nan):
            with self.assertRaises(ValueError):
                c.solve_torque(matrix, np.ones(3))


class LocalisationTests(unittest.TestCase):
    def test_filter_preserves_constant_and_integral(self):
        f = c.length_factor(40, 100_000., 5000.)
        np.testing.assert_allclose(c.filtered(f, np.full(40, 2.)), 2., rtol=2e-14)
        raw = np.linspace(0., 4., 40)
        out = c.filtered(f, raw)
        self.assertAlmostEqual(float(out.mean()), float(raw.mean()), places=13)
        self.assertGreaterEqual(float(out.min()), 0.)

    def test_uniform_shear_independent_oracle(self):
        strength, imposed, ev, ep = 2e7, 1e-14, 1e23, 1e20
        stress, rate, plastic = c.shear_rate(np.full(20, strength), imposed, ev, ep)
        expected = (imposed+strength/ep)/(1/ev+1/ep)
        self.assertAlmostEqual(stress/expected, 1., places=13)
        np.testing.assert_allclose(rate, imposed, rtol=2e-13)
        self.assertTrue(np.all(plastic > 0))

    def test_subyield_does_not_invent_plasticity(self):
        stress, rate, plastic = c.shear_rate(np.full(10, 1e9), 1e-15, 1e23, 1e20)
        self.assertAlmostEqual(stress/1e8, 1., places=13)
        self.assertTrue(np.all(plastic == 0))

    def test_invalid_length_or_extent(self):
        for n, length, ell in ((2,1,1),(40,1,0),(40,-1,1),(40,1,float("nan"))):
            with self.assertRaises(ValueError):
                c.length_factor(n, length, ell)

    def test_softening_preserves_uniform_solution_without_roundoff_seeds(self):
        result = c.shear_case(40, 128, seed=False)
        self.assertEqual(float(np.ptp(result["_history"])), 0.)


class OceanTests(unittest.TestCase):
    def test_staged_birth_ages_not_current_distance(self):
        result = c.ocean_control()
        self.assertEqual(result["age_intervals_Myr"], [[3.,5.],[0.,3.]])
        self.assertEqual(result["inherited_age_at_endpoint_Myr"], 105.)
        self.assertAlmostEqual(result["rejected_current_distance_over_rate_age_Myr"], 4.2)
        self.assertLess(max(result["relative_errors"].values()), 1e-11)

    def test_finite_stock_failure_leaves_all_inputs_unchanged(self):
        stocks = np.array([10.,20.]); debits = np.array([5.,21.])
        with self.assertRaises(ValueError):
            c.reserve_balances(stocks, debits)
        np.testing.assert_array_equal(stocks, [10.,20.])
        np.testing.assert_array_equal(debits, [5.,21.])
        np.testing.assert_array_equal(c.reserve_balances(stocks,[5.,20.]), [5.,0.])

    def test_negative_or_nonfinite_debit_refused(self):
        for debit in (-1., float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                c.reserve_balances([10.], [debit])


class WaterTests(unittest.TestCase):
    def test_analytic_shoreline_crossing(self):
        one = c.sea_level([-2.,1.], [2.,1.], 6.)
        self.assertAlmostEqual(one["sea_level_m"], 1/11, places=13)
        np.testing.assert_allclose(one["depth_m"], [3.,0.], atol=1e-13)
        both = c.sea_level([-2.,1.], [2.,1.], 12.)
        self.assertAlmostEqual(both["sea_level_m"], 59/33, places=13)
        np.testing.assert_allclose(both["depth_m"], [125/23,26/23], atol=1e-13)

    def test_volume_datum_and_partition(self):
        self.assertLess(c.water_control()["errors"]["volume"], 1e-11)

    def test_zero_water_has_no_sea_level(self):
        result = c.sea_level([-2.,1.], [2.,1.], 0.)
        self.assertIsNone(result["sea_level_m"])
        np.testing.assert_array_equal(result["bed_m"], [-2.,1.])

    def test_invalid_volume_density_area_refused(self):
        for kwargs in (dict(volume_m3=-1), dict(volume_m3=float("nan")),
                       dict(volume_m3=1, rho_w=3300), dict(volume_m3=1, rho_m=0)):
            with self.assertRaises(ValueError):
                c.sea_level([-2.,1.], [2.,1.], **kwargs)
        with self.assertRaises(ValueError):
            c.sea_level([-2.,1.], [2.,-1.], 3.)


if __name__ == "__main__":
    unittest.main()
