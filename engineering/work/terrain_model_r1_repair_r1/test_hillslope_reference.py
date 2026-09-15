"""Independent arithmetic and safety tests; no source/terrain writes."""

from dataclasses import FrozenInstanceError, replace
from decimal import Decimal, localcontext
import hashlib
import math
import unittest
from unittest import mock

import hillslope_reference as reference


def decimal_elevation(x, parameters, length, toe=0.0):
    """60-digit independent closed-form oracle, not producer bisection."""
    with localcontext() as context:
        context.prec = 60
        d = lambda value: Decimal(str(value))
        a = d(parameters.density_ratio) * d(parameters.Co_m_per_yr) / d(parameters.K_m2_per_yr)
        critical = d(parameters.critical_gradient)
        if a == 0:
            return d(toe)
        c = 2 * a / critical

        def primitive(position):
            t = (1 + (c * d(position)) ** 2).sqrt()
            return critical / c * (t - ((1 + t) / 2).ln())

        return d(toe) + primitive(length) - primitive(x)


class HillslopeReferenceTests(unittest.TestCase):
    def setUp(self):
        self.p = reference.HillslopeParameters(0.003, 0.000075, 2.0, 1.2)

    def test_contract_frozen_before_execution(self):
        data = reference.CONTRACT_PATH.read_bytes()
        self.assertEqual(hashlib.sha256(data).hexdigest(),
                         "3f5e42aecef8e008b6472ca791088eeadf1d84e567d7797c2417054dc68d2f93")
        contract = reference.read_contract()
        self.assertEqual(contract["source"]["parameter_location"], "Figure 2 caption, printed page 855")
        self.assertEqual(contract["reference_case"]["grid_spacings_m"], [0.5, 0.25, 0.125])
        self.assertEqual(contract["method"]["time_step"], "NOT_APPLICABLE_STATIC_STEADY_RECONSTRUCTION")

    def test_changed_contract_rejected_without_execution(self):
        with mock.patch.object(reference.Path, "read_bytes", return_value=b"{}"):
            with self.assertRaises(reference.ReferenceError):
                reference.run_benchmark()

    def test_loosened_code_tolerance_rejected(self):
        for name in ("FLUX_ATOL", "FLUX_RTOL", "MAX_CELLS", "MAX_BISECTION_ITERATIONS"):
            with self.subTest(name=name), mock.patch.object(reference, name, 123):
                with self.assertRaisesRegex(reference.ReferenceError, "constants differ"):
                    reference.run_benchmark()

    def test_parameter_rejections(self):
        for name in ("K_m2_per_yr", "Co_m_per_yr", "density_ratio", "critical_gradient"):
            for bad in (True, "0.1", math.inf, math.nan, -1.0):
                with self.subTest(name=name, bad=bad), self.assertRaises(reference.ReferenceError):
                    replace(self.p, **{name: bad})
        for name in ("K_m2_per_yr", "density_ratio", "critical_gradient"):
            with self.assertRaises(reference.ReferenceError):
                replace(self.p, **{name: 0})

    def test_extreme_derived_parameters_rejected(self):
        with self.assertRaises(reference.ReferenceError):
            reference.HillslopeParameters(1e-300, 1e300, 2.0, 1.2)
        with self.assertRaises(reference.ReferenceError):
            reference.HillslopeParameters(1.0, 5e-324, 0.1, 1.2)
        with self.assertRaises(reference.ReferenceError):
            replace(self.p, K_m2_per_yr=10**1000)

    def test_positive_toe_flux_underflow_rejected(self):
        with self.assertRaises(reference.ReferenceError):
            reference.reconstruct_half_hillslope(self.p, half_length_m=5e-324,
                                                 spacing_m=5e-324)

    def test_implementation_drift_rejected(self):
        original_read = reference.Path.read_bytes
        reads = 0

        def read(path):
            nonlocal reads
            data = original_read(path)
            if path == reference.Path(reference.__file__):
                reads += 1
                if reads == 2:
                    return data + b"\n# injected drift"
            return data

        with mock.patch.object(reference.Path, "read_bytes", read):
            with self.assertRaisesRegex(reference.ReferenceError, "changed during"):
                reference.run_benchmark()

    def test_parameters_and_results_immutable(self):
        profile = reference.reconstruct_half_hillslope(self.p, half_length_m=4, spacing_m=0.5)
        with self.assertRaises(FrozenInstanceError):
            self.p.critical_gradient = 1.5
        with self.assertRaises(FrozenInstanceError):
            profile.spacing_m = 2.0
        self.assertIsInstance(profile.elevation_m, tuple)

    def test_zero_supply_flat_exact_and_fixed_datum(self):
        p = replace(self.p, Co_m_per_yr=0.0)
        profile = reference.reconstruct_half_hillslope(p, half_length_m=40, spacing_m=0.5,
                                                       toe_elevation_m=-19.0)
        self.assertEqual(profile.elevation_m, (-19.0,) * 81)
        self.assertEqual(profile.midpoint_slope, (0.0,) * 80)
        self.assertEqual(profile.toe_flux_m2_per_yr, 0.0)
        self.assertEqual(reference.slope_for_flux(0, p), 0.0)
        self.assertEqual(reference.analytic_elevation(4, p, half_length_m=40, toe_elevation_m=-19), -19)

    def test_critical_and_negative_slopes_rejected_not_clamped(self):
        for slope in (-1e-9, self.p.critical_gradient, self.p.critical_gradient + 1, math.nan):
            with self.subTest(slope=slope), self.assertRaises(reference.ReferenceError):
                reference.sediment_flux(slope, self.p)
        with self.assertRaises(reference.ReferenceError):
            reference.slope_for_flux(-1.0, self.p)
        with self.assertRaises(reference.ReferenceError):
            reference.slope_for_flux(1e30, self.p)

    def test_bisection_against_independent_quadratic_root(self):
        for flux in (0, 1e-15, 1e-8, 0.0001, 0.001, 0.006, 0.1, 10):
            with self.subTest(flux=flux):
                slope = reference.slope_for_flux(flux, self.p)
                p = self.p
                exact = 2.0 * flux / (p.K_m2_per_yr +
                    math.hypot(p.K_m2_per_yr, 2.0 * flux / p.critical_gradient))
                self.assertAlmostEqual(slope, exact, delta=2e-15)
                residual = abs(reference.sediment_flux(slope, p) - flux)
                self.assertLessEqual(residual, reference.FLUX_ATOL + reference.FLUX_RTOL * flux)

    def test_reconstruction_does_not_call_analytic_oracle(self):
        with mock.patch.object(reference, "analytic_elevation", side_effect=AssertionError("oracle used")):
            profile = reference.reconstruct_half_hillslope(self.p, half_length_m=40, spacing_m=0.5)
        self.assertGreater(profile.elevation_m[0], 0.0)

    def test_units_bulk_density_supply_and_profile_order(self):
        profile = reference.reconstruct_half_hillslope(self.p, half_length_m=40, spacing_m=0.5,
                                                       toe_elevation_m=3.0)
        self.assertAlmostEqual(profile.toe_flux_m2_per_yr, 0.006, delta=2e-18)
        self.assertEqual(profile.x_m[0], 0.0)
        self.assertEqual(profile.x_m[-1], 40.0)
        self.assertEqual(profile.elevation_m[-1], 3.0)
        self.assertTrue(all(a > b for a, b in zip(profile.elevation_m, profile.elevation_m[1:])))
        self.assertTrue(all(a < b for a, b in zip(profile.midpoint_slope, profile.midpoint_slope[1:])))
        self.assertTrue(all(0 < slope < 1.2 for slope in profile.midpoint_slope))
        for x, flux in zip(profile.midpoint_x_m, profile.midpoint_flux_m2_per_yr):
            self.assertAlmostEqual(flux, 0.00015 * x, delta=2e-18)

    def test_doubling_density_ratio_equals_doubling_rock_lowering(self):
        args = dict(half_length_m=40, spacing_m=0.25)
        a = reference.reconstruct_half_hillslope(replace(self.p, density_ratio=4), **args)
        b = reference.reconstruct_half_hillslope(replace(self.p, Co_m_per_yr=0.00015), **args)
        self.assertEqual(reference.profile_bytes(a), reference.profile_bytes(b))

    def test_low_gradient_linear_limit(self):
        p = replace(self.p, Co_m_per_yr=1e-9)
        a = p.supply_m_per_yr / p.K_m2_per_yr
        length = 10.0
        nonlinear = reference.analytic_elevation(0, p, half_length_m=length)
        linear = 0.5 * a * length * length
        self.assertAlmostEqual(nonlinear / linear, 1.0, delta=1e-8)
        self.assertAlmostEqual(reference.slope_for_flux(p.supply_m_per_yr * length, p)
                               / (a * length), 1.0, delta=1e-8)

    def test_grid_and_extent_rejections(self):
        for options in ({"half_length_m": 40, "spacing_m": 0.3},
                        {"half_length_m": 0, "spacing_m": 1},
                        {"half_length_m": 1, "spacing_m": 2},
                        {"half_length_m": 40, "spacing_m": -1},
                        {"half_length_m": 1e6, "spacing_m": 1},
                        {"half_length_m": math.nan, "spacing_m": 1}):
            with self.subTest(options=options), self.assertRaises(reference.ReferenceError):
                reference.reconstruct_half_hillslope(self.p, **options)
        with self.assertRaises(reference.ReferenceError):
            reference.analytic_elevation(41, self.p, half_length_m=40)

    def test_oracle_against_sixty_digit_decimal(self):
        cases = [reference.read_contract()["reference_case"],
                 *reference.read_contract()["held_out_numerical_stress_cases"]]
        for case in cases:
            p = reference.HillslopeParameters(*(case[k] for k in
                ("K_m2_per_yr", "Co_m_per_yr", "density_ratio", "critical_gradient")))
            length, toe = case["half_length_m"], case["toe_elevation_m"]
            for x in (0, length / 10, length / 2, length - 0.125, length):
                with self.subTest(case=case["id"], x=x):
                    expected = float(decimal_elevation(x, p, length, toe))
                    observed = reference.analytic_elevation(x, p, half_length_m=length,
                                                           toe_elevation_m=toe)
                    self.assertAlmostEqual(observed, expected, delta=3e-13)

    def test_midpoint_derivative_bound(self):
        a = self.p.supply_m_per_yr / self.p.K_m2_per_yr
        bound = 8 * a * a / self.p.critical_gradient
        for i in range(1001):
            r = i / 1001
            magnitude = (2 * a * a / self.p.critical_gradient) * r * (3 + r*r) * (1-r*r)**3 / (1+r*r)**3
            self.assertLessEqual(magnitude, bound)
        fine = reference.height_error_bound(self.p, half_length_m=40, spacing_m=0.125)
        self.assertAlmostEqual(fine["quadrature_m"], 0.00043402777777777775, delta=1e-18)

    def test_all_profile_points_inside_independent_analytic_bound(self):
        for spacing in (0.5, 0.25, 0.125):
            profile = reference.reconstruct_half_hillslope(self.p, half_length_m=40, spacing_m=spacing)
            bound = reference.height_error_bound(self.p, half_length_m=40, spacing_m=spacing)["total_m"]
            for x, elevation in zip(profile.x_m, profile.elevation_m):
                self.assertLessEqual(abs(elevation - float(decimal_elevation(x, self.p, 40))), bound)

    def test_byte_exact_repeat_including_signed_zero(self):
        args = dict(half_length_m=40, spacing_m=0.125, toe_elevation_m=-0.0)
        a = reference.reconstruct_half_hillslope(self.p, **args)
        b = reference.reconstruct_half_hillslope(self.p, **args)
        self.assertEqual(reference.profile_bytes(a), reference.profile_bytes(b))
        c = replace(a, elevation_m=a.elevation_m[:-1] + (0.0,))
        self.assertNotEqual(reference.profile_bytes(a), reference.profile_bytes(c))

    def test_full_frozen_benchmark_and_no_completion_claim(self):
        report = reference.run_benchmark()
        self.assertEqual(report["status"], "PASS_NUMERICAL_REFERENCE_ONLY")
        self.assertEqual(len(report["cases"]), 3)
        self.assertTrue(all(len(case["grids"]) == 3 for case in report["cases"]))
        for key in ("physical_validation_passed", "diadem_parameters_established",
                    "production_authorized", "complete_T03_CF04_L02", "optimisation_measured"):
            self.assertIs(report[key], False)


if __name__ == "__main__":
    unittest.main()
