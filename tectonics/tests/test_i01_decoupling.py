"""Focused tests for the bounded nonlinear admission certificate.

SPDX-License-Identifier: AGPL-3.0-only
"""
from fractions import Fraction as Q
import importlib.util
import math
from pathlib import Path
import sys
import unittest

PATH = Path(__file__).resolve().parents[1]/"tools/check_i01_decoupling.py"
SPEC = importlib.util.spec_from_file_location("i01_decoupling_control", PATH)
m = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = m
SPEC.loader.exec_module(m)


class AdmissionTests(unittest.TestCase):
    def test_linear_oracle_and_exact_threshold(self):
        p = m.PreparedBalance(m.Balance(1, 1, Q(1, 4), Q(1, 2), 1))
        self.assertTrue(p.admits(Q(1, 2)))
        self.assertFalse(p.admits(math.nextafter(0.5, 0)))
        self.assertTrue(p.admits(math.nextafter(0.5, 1)))
        lo, hi = p.bracket()
        self.assertLessEqual(lo, Q(1, 2))
        self.assertGreaterEqual(hi, Q(1, 2))

    def test_zero_derivative_does_not_mean_decoupled(self):
        p = m.PreparedBalance(m.Balance(1, 1, Q(9, 10), 0, 1))
        self.assertFalse(p.admits(Q(1, 100)))
        lo, hi = p.bracket()
        self.assertLessEqual(lo, Q(1, 10))
        self.assertGreaterEqual(hi, Q(1, 10))

    def test_nonlinear_oracle(self):
        p = m.PreparedBalance(m.Balance(1, 1, 0, 1, 2))
        lo, hi = p.bracket()
        exact = (3-math.sqrt(5))/2
        self.assertLess(abs(float((lo+hi)/2)-exact), 1e-12)
        self.assertFalse(p.admits(0.61))
        self.assertTrue(p.admits(0.62))

    def test_static_and_free_limits(self):
        for y in (1, 2):
            p = m.PreparedBalance(m.Balance(1, 1, y, 1, 2))
            self.assertEqual(p.bracket(), (0, 0))
            self.assertFalse(p.admits(0.99))
        p = m.PreparedBalance(m.Balance(1, 1, 0, 0, 8))
        self.assertEqual(p.bracket(), (1, 1))
        self.assertTrue(p.admits(0))

    def test_polynomial_equivalence_all_supported_exponents(self):
        # Construct a rational exact speed x=(1/2)^n; its nth root is 1/2.
        for n in range(1, 9):
            x = Q(1, 2)**n
            a = 2*(1-x-Q(1, 4))
            p = m.PreparedBalance(m.Balance(1, 1, Q(1, 4), a, n))
            self.assertTrue(p.at_least(x))
            self.assertFalse(p.at_least(x+Q(1, 2**60)))
            lo, hi = p.bracket(64)
            self.assertLessEqual(lo, x)
            self.assertGreaterEqual(hi, x)

    def test_force_and_speed_unit_scaling(self):
        base = m.PreparedBalance(m.Balance(1, 1, Q(1, 4), Q(1, 2), 2))
        # Force scale 100, speed scale 4: a multiplies by 100/sqrt(4).
        scaled = m.PreparedBalance(m.Balance(100, 25, 25, 25, 2))
        self.assertEqual(base.bracket(), scaled.bracket())
        self.assertEqual(scaled.v0, 4*base.v0)

    def test_nonfinite_negative_and_unsupported_inputs(self):
        for value in (float("nan"), float("inf"), -1, True, "1"):
            with self.assertRaises(ValueError):
                m.Balance(1, 1, value, 1, 2)
        for n in (0, 9, 1.5, True):
            with self.assertRaises(ValueError):
                m.Balance(1, 1, 0, 1, n)
        with self.assertRaises(ValueError):
            m.Balance(1, 0, 0, 1, 1)
        with self.assertRaises(ValueError):
            m.Balance(1, 1, 0, 1 << 4097, 1)
        p = m.PreparedBalance(m.Balance(1, 1, 0, 1, 1))
        for eps in (-1, 1, float("nan")):
            with self.assertRaises(ValueError):
                p.admits(eps)
        with self.assertRaises(ValueError):
            p.bracket(129)


class WindowTests(unittest.TestCase):
    def setUp(self):
        self.current = m.Balance(1, 1, 0, 0, 2)
        self.kwargs = dict(duration_s=10, relative_tolerance=0.01, displacement_limit_m=0.1)

    def test_missing_window_is_not_inferred_from_snapshot(self):
        result = m.window_admission(self.current, None, **self.kwargs)
        self.assertTrue(result["snapshot_passed"])
        self.assertFalse(result["numerical_admissible"])

    def test_between_endpoint_strengthening_refused(self):
        pulse = m.Balance(1, 1, 1, 0, 2)
        result = m.window_admission(self.current, pulse, **self.kwargs)
        self.assertTrue(result["snapshot_passed"])
        self.assertFalse(result["numerical_admissible"])

    def test_whole_window_motion_displacement_and_work(self):
        bound = m.Balance(1, 1, Q(1, 1000), Q(2, 1000), 2)
        result = m.window_admission(self.current, bound, **self.kwargs)
        self.assertTrue(result["numerical_admissible"])
        self.assertFalse(result["generated_separation_authorised"])
        self.assertLessEqual(result["displacement_error_bound_m"], math.nextafter(0.1, math.inf))
        self.assertEqual(result["displacement_error_bound_m"], result["driving_work_error_bound_J_m"])
        tighter = dict(self.kwargs, displacement_limit_m=0.001)
        self.assertFalse(m.window_admission(self.current, bound, **tighter)["numerical_admissible"])

    def test_invalid_or_incompatible_envelopes(self):
        for bound in (m.Balance(2, 1, 0, 0, 2), m.Balance(1, 2, 0, 0, 2),
                      m.Balance(1, 1, 0, 0, 3)):
            with self.assertRaises(ValueError):
                m.window_admission(self.current, bound, **self.kwargs)
        current = m.Balance(1, 1, 0.1, 0.1, 2)
        with self.assertRaises(ValueError):
            m.window_admission(current, self.current, **self.kwargs)
        with self.assertRaises(ValueError):
            m.window_admission(self.current, self.current, **dict(self.kwargs, duration_s=0))

    def test_display_bounds_round_outward(self):
        for value in (Q(1, 10), Q(1, 3), Q(1, 2**1100), Q(0)):
            self.assertGreaterEqual(Q(m.upper_float(value)), value)
        with self.assertRaises(ValueError):
            m.upper_float(Q(10**400))


if __name__ == "__main__":
    unittest.main()
