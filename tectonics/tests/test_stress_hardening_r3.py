"""Extreme-range stress/heat regressions against direct Decimal contractions.

SPDX-License-Identifier: AGPL-3.0-only
No new physical model: these checks enforce tau=2*eta*e and Q=tau:e over the
helper's accepted binary64 range. Decimal is a test oracle, never a hot path.
"""
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal, localcontext
import math
import unittest
from unittest import mock
import warnings

import numpy as np
from numpy.testing import assert_allclose, assert_array_equal, assert_array_max_ulp

from atlas_tectonics import stress_and_dissipation, TectonicsError
from atlas_tectonics.resources import WorkBudget, MemoryLimitError


def oracle(eta, tensor):
    """Direct products of exact input floats, independently of exponent scaling."""
    a = np.asarray(tensor, dtype=float)
    with localcontext() as c:
        c.prec = 4000  # enough for exact products of three binary64 inputs
        v = Decimal.from_float(float(eta))
        stress = np.empty_like(a)
        heat = Decimal(0)
        for ij in np.ndindex(a.shape):
            e = Decimal.from_float(float(a[ij]))
            s = 2*v*e
            stress[ij] = float(s)
            heat += s*e
        return stress, float(heat)


class StressRangeTests(unittest.TestCase):
    def check_oracle(self, eta, tensor):
        expected_stress, expected_heat = oracle(eta, tensor)
        with warnings.catch_warnings(record=True) as caught, np.errstate(all='raise'):
            actual = stress_and_dissipation(eta, tensor)
        self.assertEqual(caught, [])
        assert_array_max_ulp(actual['deviatoric_stress'], expected_stress, maxulp=2)
        assert_array_max_ulp(actual['viscous_dissipation'], np.asarray(expected_heat), maxulp=4)
        self.assertGreater(float(actual['viscous_dissipation']), 0)
        return actual

    def test_reported_square_underflow(self):
        r = self.check_oracle(1e100, np.diag([1e-170, -1e-170]))
        assert_allclose(r['viscous_dissipation'], 4e-240, rtol=4e-16, atol=0)

    def test_square_overflow_but_final_outputs_finite(self):
        self.check_oracle(1e-300, np.diag([1e200, -1e200]))

    def test_twice_viscosity_overflows_but_outputs_finite(self):
        self.check_oracle(1e308, np.diag([1e-300, -1e-300]))

    def test_smallest_positive_viscosity_large_rate(self):
        self.check_oracle(float(np.nextafter(0., 1.)), np.diag([1e308, -1e308]))

    def test_unrepresentable_invariant_not_needed_for_finite_stress_and_heat(self):
        r = 1e308
        a = np.full((3, 3), r); np.fill_diagonal(a, [r, -r, 0])
        self.check_oracle(float(np.nextafter(0., 1.)), a)

    def test_subnormal_strain_is_not_rejected_when_outputs_representable(self):
        self.check_oracle(1e308, np.diag([1e-310, -1e-310]))

    def test_nonzero_subnormal_stress_is_preserved(self):
        r = self.check_oracle(1e-310, np.diag([1., -1.]))
        self.assertLess(r['deviatoric_stress'][0, 0], np.finfo(float).tiny)

    def test_heat_terms_sum_before_subnormal_rounding(self):
        tiny = float(np.nextafter(0., 1.))
        rate = math.ldexp(1., -537)
        result = self.check_oracle(.25, np.diag([rate, -rate]))
        self.assertEqual(float(result['viscous_dissipation']), tiny)

    def test_zero_strain_at_both_viscosity_extremes(self):
        for eta in (float(np.nextafter(0., 1.)), np.finfo(float).max):
            with self.subTest(eta=eta), np.errstate(all='raise'):
                r = stress_and_dissipation(eta, np.zeros((3, 3)))
                assert_array_equal(r['deviatoric_stress'], np.zeros((3, 3)))
                self.assertEqual(float(r['viscous_dissipation']), 0)

    def test_true_heat_underflow_is_explicit(self):
        with self.assertRaisesRegex(TectonicsError, 'dissipation underflows'):
            stress_and_dissipation(1., np.diag([1e-300, -1e-300]))

    def test_true_stress_underflow_is_explicit(self):
        with self.assertRaisesRegex(TectonicsError, 'stress underflows'):
            stress_and_dissipation(1e-300, np.diag([1e-300, -1e-300]))

    def test_tiny_offdiagonal_not_hidden_by_other_large_components(self):
        with self.assertRaisesRegex(TectonicsError, 'stress underflows'):
            stress_and_dissipation(1e-100, [[1e100, 1e-300], [1e-300, -1e100]])

    def test_true_stress_overflow_is_explicit(self):
        with self.assertRaises(TectonicsError):
            stress_and_dissipation(1e308, np.diag([2., -2.]))

    def test_true_heat_overflow_is_explicit(self):
        with self.assertRaises(TectonicsError):
            stress_and_dissipation(1., np.diag([1e200, -1e200]))

    def test_broadcast_strided_inputs(self):
        rates = np.array([1e-170, 1., 1e50, 1e100])[::2]
        a = rates[:, None, None, None] * np.diag([1., -1.])[None, None, :, :]
        eta = np.array([1e100, 1e101, 1e102])[None, :]
        r = stress_and_dissipation(eta, a)
        self.assertEqual(r['deviatoric_stress'].shape, (2, 3, 2, 2))
        for i, j in np.ndindex(2, 3):
            s, q = oracle(eta[0, j], a[i, 0])
            assert_array_max_ulp(r['deviatoric_stress'][i, j], s, maxulp=2)
            assert_array_max_ulp(r['viscous_dissipation'][i, j], np.asarray(q), maxulp=4)

    def test_extensive_exponent_sweep_against_decimal(self):
        pairs = [(-1073, 1023), (-1000, 800), (-600, 500), (-100, 300),
                 (0, -537), (0, 0), (400, -500), (800, -800), (1023, -1000)]
        for p, r in pairs:
            eta, rate = math.ldexp(.75, p), math.ldexp(.875, r)
            with self.subTest(eta_exponent=p, rate_exponent=r):
                self.check_oracle(eta, np.diag([rate, -rate]))

    def test_full_3d_tensor_against_decimal(self):
        a = np.array([[1., 2, 3], [2, -1, 4], [3, 4, 0]])
        for eta, rate in ((3., 1.), (1e100, 1e-170), (1e-300, 1e200)):
            with self.subTest(eta=eta, rate=rate):
                self.check_oracle(eta, rate*a)

    def test_ordinary_stress_contraction_agrees(self):
        a = 1e-15*np.array([[1., 2, 3], [2, -1, 4], [3, 4, 0]])
        r = stress_and_dissipation(1e21, a)
        assert_allclose(r['viscous_dissipation'], np.sum(r['deviatoric_stress']*a), rtol=4e-16, atol=0)

    def test_rotation_invariant_heat(self):
        a = np.array([[1., 2, 3], [2, -1, 4], [3, 4, 0]])*1e-170
        q, _ = np.linalg.qr(np.random.default_rng(41).normal(size=(3, 3)))
        before = stress_and_dissipation(1e100, a)
        after = stress_and_dissipation(1e100, q@a@q.T)
        assert_allclose(before['viscous_dissipation'], after['viscous_dissipation'], rtol=4e-15, atol=0)

    def test_nonsymmetric_tensor_rejected_without_overflow_warning(self):
        with warnings.catch_warnings(record=True) as caught, np.errstate(all='raise'):
            with self.assertRaisesRegex(TectonicsError, 'not symmetric'):
                stress_and_dissipation(1e-300, [[0., 1e308], [-1e308, 0.]])
        self.assertEqual(caught, [])

    def test_nontraceless_tensor_still_rejected(self):
        for scale in (1e-300, 1., 1e300):
            with self.subTest(scale=scale), self.assertRaisesRegex(TectonicsError, 'traceless'):
                stress_and_dissipation(1., np.eye(3)*scale)

    def test_before_allocation_budget_refusal(self):
        budget = WorkBudget(1)
        with mock.patch('atlas_tectonics.constitutive.read_array', side_effect=AssertionError('early capture')):
            with self.assertRaises(MemoryLimitError):
                stress_and_dissipation(1., np.zeros((2, 2)), budget=budget)
        self.assertEqual(budget.reserved_bytes, 0)

    def test_budget_released_on_success_and_all_range_failures(self):
        budget = WorkBudget(1<<20)
        stress_and_dissipation(1e100, np.diag([1e-170, -1e-170]), budget=budget)
        for eta, rate in ((1., 1e-300), (1e-300, 1e-300), (1e308, 1e300)):
            with self.assertRaises(TectonicsError):
                stress_and_dissipation(eta, np.diag([rate, -rate]), budget=budget)
        self.assertEqual(budget.reserved_bytes, 0)

    def test_immutable_detached_outputs(self):
        a = np.diag([1e-170, -1e-170]); eta = np.array(1e100)
        r = stress_and_dissipation(eta, a); a[:] = 0; eta[...] = 1
        for out in r.values():
            with self.assertRaises(ValueError): out.setflags(write=True)
        self.assertNotEqual(float(r['viscous_dissipation']), 0)

    def test_threaded_independent_calls_agree(self):
        a = np.diag([1e-170, -1e-170])
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: stress_and_dissipation(1e100, a), range(4)))
        for r in results[1:]:
            for name in r: assert_array_equal(r[name], results[0][name])

    def test_invalid_viscosity_and_nonfinite_tensor_remain_rejected(self):
        for eta in (0, -1, float('nan'), float('inf'), True):
            with self.subTest(eta=eta), self.assertRaises(TectonicsError):
                stress_and_dissipation(eta, np.zeros((2, 2)))
        with self.assertRaises(TectonicsError):
            stress_and_dissipation(1., [[float('inf'), 0], [0, -1]])

    def test_unbroadcastable_shapes_still_rejected(self):
        with self.assertRaises(TectonicsError):
            stress_and_dissipation(np.ones(3), np.zeros((4, 2, 2)))

    def test_point_limit_checked_before_capture(self):
        a = np.broadcast_to(np.eye(2), (2097153, 2, 2))
        with mock.patch('atlas_tectonics.constitutive.read_array', side_effect=AssertionError('early capture')):
            with self.assertRaisesRegex(TectonicsError, 'envelope'):
                stress_and_dissipation(1., a)


if __name__ == '__main__':
    unittest.main()
