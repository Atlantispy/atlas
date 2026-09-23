"""Manufactured saddle equations; no subduction physics or mesh comparison."""
from concurrent.futures import CancelledError
from contextlib import ExitStack
import math
from threading import Event
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np
from scipy import sparse

from atlas_tectonics._validation import TectonicsError
from atlas_tectonics.resources import MemoryLimitError, WorkBudget
from atlas_tectonics.subduction_linear import solve_stokes, _bfbt


def system(gauge=False, contrast=1.):
    n = 24
    base = sparse.diags((-.15*np.ones(n-1), np.ones(n), -.15*np.ones(n-1)), (-1, 0, 1), format='csr')
    eta = np.geomspace(1., contrast, n)
    scale = sparse.diags(np.sqrt(eta), format='csr')
    stiffness = (scale@base@scale).tocsr()
    k = sparse.block_diag((stiffness, 1.3*stiffness), format='csr')
    difference = (sparse.eye(n, format='csr')-sparse.csr_matrix((np.ones(n), (np.arange(n), (np.arange(n)+1)%n)), shape=(n, n))).tocsr()
    g = sparse.vstack((difference if gauge else sparse.eye(n, format='csr'), .7*difference), format='csr')
    mass = (sparse.diags(1./np.sqrt(eta))@base@sparse.diags(1./np.sqrt(eta))).tocsr()
    weights = np.linspace(1., 3., n) if gauge else None
    v = np.sin(np.arange(2*n)*.41)+.1
    p = np.cos(np.arange(n)*.27)+.2
    if gauge:
        p -= weights@p/weights.sum()
    f, h = k@v+g@p, g.T@v
    return k, g, mass, f, h, v, p, weights


class SubductionLinearTests(unittest.TestCase):
    def solve_and_check(self, gauge, contrast, weighted=False):
        k, g, mass, f, h, expected_v, expected_p, weights = system(gauge, contrast)
        saved = [a.copy() for matrix in (k, g, mass) for a in (matrix.data, matrix.indices, matrix.indptr)]
        owner = WorkBudget(128*1024**2)
        c = np.sqrt(k.diagonal()) if weighted else None
        v, p, diagnostics = solve_stokes(k, g, f, h, pressure_mass=mass,
            pressure_mean_weights=weights, velocity_mass_sqrt_eta=c, budget=owner)
        scale = max(np.linalg.norm(np.r_[f, h]), np.finfo(float).tiny)
        self.assertLessEqual(np.linalg.norm(np.r_[k@v+g@p-f, g.T@v-h])/scale, 1e-10)
        self.assertLessEqual(diagnostics['linear_residual'], 1e-10)
        self.assertLessEqual(diagnostics['relative_residual'], 1e-10)
        self.assertLessEqual(diagnostics['iterations'], 1200)
        self.assertEqual(diagnostics['restart'], 60)
        np.testing.assert_allclose(v, expected_v, rtol=1e-8, atol=1e-8)
        np.testing.assert_allclose(p, expected_p, rtol=2e-7, atol=2e-7)
        if gauge:
            self.assertAlmostEqual(float(weights@p), 0., delta=1e-10)
            self.assertGreater(abs(float(expected_p.mean())), 1e-3)
            self.assertAlmostEqual(float(p.mean()), float(expected_p.mean()), delta=2e-7)
            self.assertAlmostEqual(diagnostics['gauge_multiplier'], 0., delta=1e-10)
        else:
            self.assertEqual(diagnostics['gauge_multiplier'], 0.)
        for actual, original in zip((a for matrix in (k, g, mass) for a in (matrix.data, matrix.indices, matrix.indptr)), saved):
            np.testing.assert_array_equal(actual, original)
        for a in (v, p):
            with self.assertRaises(ValueError):
                a.setflags(write=True)
        self.assertEqual(owner.reserved_bytes, 0)
        return diagnostics

    def test_manufactured_natural_pressure_and_heterogeneous_viscosity(self):
        for contrast in (1., 1e5):
            with self.subTest(contrast=contrast):
                self.solve_and_check(False, contrast)

    def test_weighted_pressure_gauge_and_five_order_viscosity_contrast(self):
        for contrast in (1., 1e5):
            with self.subTest(contrast=contrast):
                self.solve_and_check(True, contrast)

    def test_equilibrated_blocks_retain_original_physical_residual(self):
        for gauge in (False, True):
            with self.subTest(gauge=gauge):
                d = self.solve_and_check(gauge, 1e8)
                self.assertLess(d['iterations'], 1200)
                self.assertIn('componentwise_continuity_residual', d)

    def test_bfbt_supplied_weights_natural_and_gauged(self):
        for gauge in (False, True):
            with self.subTest(gauge=gauge):
                d = self.solve_and_check(gauge, 1e5, weighted=True)
                self.assertIn('supplied sqrt(eta)-weighted-mass BFBT', d['method'])

    def test_matrix_free_bfbt_matches_dense_reference_and_null_quotient(self):
        for gauge in (False, True):
            k, g, _, _, _, _, _, _ = system(gauge, 1e3)
            c = np.sqrt(k.diagonal()); dense_g = g.toarray(); a = dense_g/c[:, None]
            poisson = dense_g.T@a; middle = a.T@k@a
            inverse = np.linalg.pinv(poisson, rcond=1e-13) if gauge else np.linalg.inv(poisson)
            expected = inverse@middle@inverse
            owner = WorkBudget(128*1024**2)
            with ExitStack() as stack:
                apply, fill = _bfbt(k, g, c, gauge, owner, stack, None)
                actual = np.column_stack([apply(row) for row in np.eye(g.shape[1])])
                np.testing.assert_allclose(actual, expected, rtol=1e-9, atol=1e-8)
                self.assertLessEqual(fill['realised_accounted_bytes'], fill['admitted_bytes'])
            self.assertEqual(owner.reserved_bytes, 0)

    def test_zero_load_needs_no_factors_and_has_exact_zero_fields(self):
        for gauge in (False, True):
            k, g, mass, f, h, _, _, weights = system(gauge)
            with patch('atlas_tectonics.subduction_linear.splu', side_effect=AssertionError('factor not needed')):
                v, p, d = solve_stokes(k, g, f*0., h*0., pressure_mass=mass, pressure_mean_weights=weights)
            np.testing.assert_array_equal(v, np.zeros_like(f))
            np.testing.assert_array_equal(p, np.zeros_like(h))
            self.assertEqual(d['linear_residual'], 0.)
            self.assertEqual(d['iterations'], 0)

    def test_zero_pressure_with_nonzero_velocity_and_weighted_gauge(self):
        k, g, mass, _, _, _, _, weights = system(True)
        expected_v = np.ones(k.shape[0])
        f, h = k@expected_v, g.T@expected_v
        owner = WorkBudget(128*1024**2)
        v, p, d = solve_stokes(k, g, f, h, pressure_mass=mass,
            pressure_mean_weights=weights, budget=owner)
        np.testing.assert_allclose(v, expected_v, rtol=1e-10, atol=1e-10)
        np.testing.assert_allclose(p, 0., rtol=0., atol=1e-10)
        self.assertLessEqual(d['linear_residual'], 1e-10)
        self.assertLessEqual(d['relative_residual'], 1e-10)
        self.assertAlmostEqual(float(weights@p), 0., delta=1e-20)
        self.assertAlmostEqual(d['gauge_multiplier'], 0., delta=1e-10)
        self.assertEqual(owner.reserved_bytes, 0)

    def test_natural_global_continuity_correction_preserves_momentum(self):
        k = sparse.diags([2., 3., 4.], format='csr')
        g = sparse.csr_matrix([[1., 0.], [0., 1.], [1., 1.]])
        mass = sparse.eye(2, format='csr')
        expected_v = np.array([1., -.25, .125]); expected_p = np.array([.3, -.2])
        f = k@expected_v+g@expected_p; h = g.T@expected_v
        mode = (g@np.ones(2))/k.diagonal()
        dv, dp = mode*1e-12, -np.ones(2)*1e-12
        bias = np.r_[k@dv+g@dp, g.T@dv]
        scaling = np.r_[1/np.sqrt(k.diagonal()), np.ones(2)]
        def slightly_biased(operator, rhs, **kwargs):
            dense = np.column_stack([operator@row for row in np.eye(5)])
            return np.linalg.solve(dense, rhs+scaling*bias), 0
        with patch('atlas_tectonics.subduction_linear.gmres', side_effect=slightly_biased):
            v, p, d = solve_stokes(k, g, f, h, pressure_mass=mass)
        np.testing.assert_allclose(v, expected_v, rtol=0., atol=1e-14)
        np.testing.assert_allclose(p, expected_p, rtol=0., atol=1e-14)
        np.testing.assert_allclose(k@v+g@p, f, rtol=0., atol=1e-14)
        self.assertGreater(d['global_continuity_before_correction'], 1e-13)
        self.assertGreater(d['global_continuity_correction_velocity_inf'], 1e-13)
        self.assertLessEqual(abs(math.fsum(g.T@v-h)), 4*np.finfo(float).eps)
        self.assertLessEqual(d['linear_residual'], 1e-10)

    def test_true_equilibrated_defect_refines_once_and_stops_at_roundoff(self):
        k = sparse.diags([2., 3., 4.], format='csr')
        g = sparse.csr_matrix([[1., 0.], [0., 1.], [1., 1.]])
        mass = sparse.eye(2, format='csr')
        expected_v = np.array([1., -.25, .125]); expected_p = np.array([.3, -.2])
        f = k@expected_v+g@expected_p; h = g.T@expected_v
        dp = np.array([1., -1.])*1e-11; dv = -(g@dp)/k.diagonal()
        bias = np.r_[k@dv+g@dp, g.T@dv]
        scaling = np.r_[1/np.sqrt(k.diagonal()), np.ones(2)]
        calls = []
        def first_defect(operator, rhs, **kwargs):
            dense = np.column_stack([operator@row for row in np.eye(5)])
            answer = np.linalg.solve(dense, rhs+(scaling*bias if not calls else 0.))
            calls.append(None)
            return answer, 0
        owner = WorkBudget(128*1024**2)
        with patch('atlas_tectonics.subduction_linear.gmres', side_effect=first_defect):
            v, p, d = solve_stokes(k, g, f, h, pressure_mass=mass, budget=owner)
        self.assertEqual(len(calls), 2)
        self.assertEqual(d['corrections'], 1)
        self.assertTrue(d['refinement_at_roundoff'])
        self.assertIs(type(d['refinement_at_roundoff']), bool)
        self.assertIs(type(d['equilibrated_roundoff_scale']), float)
        self.assertLessEqual(d['equilibrated_residual'], d['equilibrated_roundoff_scale'])
        np.testing.assert_allclose(v, expected_v, rtol=0., atol=1e-14)
        np.testing.assert_allclose(p, expected_p, rtol=0., atol=1e-14)
        self.assertLessEqual(d['linear_residual'], 1e-10)
        self.assertEqual(owner.reserved_bytes, 0)

    def test_incompatible_flux_and_missing_or_spurious_gauge_refuse(self):
        owner = WorkBudget(128*1024**2)
        k, g, mass, f, h, _, _, weights = system(True)
        with self.assertRaises(TectonicsError):
            solve_stokes(k, g, f, h, pressure_mass=mass, budget=owner)
        with self.assertRaises(TectonicsError):
            solve_stokes(k, g, f, h+.1, pressure_mass=mass, pressure_mean_weights=weights, budget=owner)
        k, g, mass, f, h, _, _, _ = system(False)
        with self.assertRaises(TectonicsError):
            solve_stokes(k, g, f, h, pressure_mass=mass, pressure_mean_weights=weights, budget=owner)
        self.assertEqual(owner.reserved_bytes, 0)

    def test_nonconvergence_and_false_success_do_not_publish(self):
        k, g, mass, f, h, _, _, _ = system(False)
        owner = WorkBudget(128*1024**2)
        def false_success(operator, rhs, **kwargs):
            return np.zeros_like(rhs), 0
        with patch('atlas_tectonics.subduction_linear.gmres', side_effect=false_success) as mocked:
            with self.assertRaisesRegex(TectonicsError, 'original physical equations'):
                solve_stokes(k, g, f, h, pressure_mass=mass, budget=owner)
        self.assertEqual(mocked.call_count, 3)
        def exhausted(operator, rhs, **kwargs):
            self.assertEqual(kwargs['callback_type'], 'legacy')
            self.assertEqual(kwargs['maxiter'], 1200)
            for _ in range(kwargs['maxiter']):
                kwargs['callback'](1.)
            return np.zeros_like(rhs), 1200
        with patch('atlas_tectonics.subduction_linear.gmres', side_effect=exhausted) as mocked:
            with self.assertRaises(TectonicsError):
                solve_stokes(k, g, f, h, pressure_mass=mass, budget=owner)
        self.assertEqual(mocked.call_count, 1)
        self.assertEqual(owner.reserved_bytes, 0)

    def test_cancellation_and_budget_refusal_release_all_leases(self):
        k, g, mass, f, h, _, _, _ = system(False)
        owner = WorkBudget(128*1024**2); cancelled = Event(); cancelled.set()
        with self.assertRaises(CancelledError):
            solve_stokes(k, g, f, h, pressure_mass=mass, budget=owner, cancel=cancelled)
        cancelled.clear()
        def interrupted(operator, rhs, **kwargs):
            cancelled.set(); kwargs['callback'](1.)
        with patch('atlas_tectonics.subduction_linear.gmres', side_effect=interrupted):
            with self.assertRaises(CancelledError):
                solve_stokes(k, g, f, h, pressure_mass=mass, budget=owner, cancel=cancelled)
        self.assertEqual(owner.reserved_bytes, 0)
        tiny = WorkBudget(1024)
        with self.assertRaises(MemoryLimitError):
            solve_stokes(k, g, f, h, pressure_mass=mass, budget=tiny)
        self.assertEqual(tiny.reserved_bytes, 0)

    def test_factor_phases_and_both_realised_fill_guards(self):
        from atlas_tectonics import subduction_linear as linear
        k, g, mass, f, h, _, _, _ = system(False)
        owner = WorkBudget(128*1024**2)
        real_splu, real_gmres = linear.splu, linear.gmres
        phases = []
        def factor(*args, **kwargs):
            categories = owner.statistics()['categories']
            self.assertEqual(categories.get('subduction-gmres-basis', 0), 0)
            self.assertGreater(sum(v for name, v in categories.items() if name.endswith('-build')), 0)
            phases.append('factor')
            return real_splu(*args, **kwargs)
        def krylov(*args, **kwargs):
            categories = owner.statistics()['categories']
            self.assertEqual(sum(v for name, v in categories.items() if name.endswith('-build')), 0)
            self.assertEqual(categories['subduction-gmres-basis'], 8*60*(len(f)+len(h)))
            phases.append('gmres')
            return real_gmres(*args, **kwargs)
        with patch.object(linear, 'splu', side_effect=factor), patch.object(linear, 'gmres', side_effect=krylov):
            _, _, d = solve_stokes(k, g, f, h, pressure_mass=mass, budget=owner)
        self.assertEqual(phases[:2], ['factor', 'factor'])
        self.assertIn('gmres', phases)
        for key in ('velocity_factor', 'pressure_factor'):
            self.assertLessEqual(d[key]['retained_accounted_bytes'], d[key]['retained_admitted_bytes'])
            self.assertLessEqual(d[key]['realised_accounted_bytes'], d[key]['admitted_bytes'])
        self.assertEqual(owner.reserved_bytes, 0)
        tiny = sparse.eye(1, format='csr'); left = tiny.copy(); right = tiny.copy()
        fake = SimpleNamespace(L=left, U=right)
        # Include the RCM permutation/wrapper in both unchanged fill rules.
        allowance = 160+256+1024**2; retained_bound = (2*allowance+2)//3
        overhead = 2*tiny.indices.dtype.itemsize+4096
        cases = (((retained_bound-16-overhead)//2+1, 'retained footprint'),
                 ((allowance-20-overhead)//3+1, 'realised fill'))
        for factor_bytes, message in cases:
            def measured(matrix):
                return factor_bytes//2 if matrix is left else factor_bytes-factor_bytes//2 if matrix is right else 20
            with self.subTest(guard=message), ExitStack() as stack:
                with patch.object(linear, 'splu', return_value=fake), patch.object(linear, '_bytes', side_effect=measured):
                    with self.assertRaisesRegex(TectonicsError, message):
                        linear._factor(tiny, np.ones(1), True, owner, stack, None)
            self.assertEqual(owner.reserved_bytes, 0)

    def test_velocity_graph_ordering_unpermutes_and_accounts_storage(self):
        from atlas_tectonics import subduction_linear as linear
        k, _, _, _, _, _, _, _ = system(False, 1e3)
        original = k.copy(); scale = linear._positive_symmetric(k, 'velocity')
        rhs = np.column_stack((np.sin(np.arange(len(scale))), np.cos(np.arange(len(scale)))))
        scaled = linear._scaled_csc(k, scale)
        owner = WorkBudget(128*1024**2)
        with ExitStack() as stack:
            factor, d = linear._factor(k, scale, True, owner, stack, None)
            permutation = linear.reverse_cuthill_mckee(k, symmetric_mode=True)
            np.testing.assert_array_equal(factor.permutation, permutation)
            self.assertFalse(np.array_equal(permutation, np.arange(len(scale))))
            np.testing.assert_allclose(scaled@factor.solve(rhs), rhs, rtol=1e-13, atol=1e-13)
            np.testing.assert_allclose(factor.solve(rhs[:, 0]), factor.solve(rhs)[:, 0], rtol=0., atol=0.)
            self.assertEqual(d['ordering'], 'RCM-MMD_AT_PLUS_A')
            self.assertEqual(d['permutation_bytes'], permutation.nbytes)
            self.assertEqual(d['realised_accounted_bytes'],
                3*d['retained_factor_bytes']+linear._bytes(scaled)+2*permutation.nbytes+4096)
            self.assertEqual(d['retained_accounted_bytes'],
                2*d['retained_factor_bytes']+16*len(scale)+2*permutation.nbytes+4096)
            self.assertEqual(owner.reserved_bytes, d['retained_admitted_bytes'])
            self.assertLessEqual(d['ordering_workspace_bytes'], d['admitted_bytes'])
            self.assertEqual(len(d['permutation_sha256']), 64)
        self.assertEqual(owner.reserved_bytes, 0)
        np.testing.assert_array_equal(k.data, original.data)
        np.testing.assert_array_equal(k.indices, original.indices)
        np.testing.assert_array_equal(k.indptr, original.indptr)

    def test_velocity_envelope_uses_ancestor_headroom_without_waiving_fill(self):
        from atlas_tectonics import subduction_linear as linear
        matrix = sparse.eye(16, format='csr')
        parent = WorkBudget(128*1024**2); owner = WorkBudget(128*1024**2, parent=parent)
        with parent.reserve(parent.max_bytes-20000, category='retained-history'):
            with ExitStack() as stack:
                factor, d = linear._factor(matrix, np.ones(16), True, owner, stack, None)
                self.assertEqual(d['admitted_bytes'], 20000)
                self.assertEqual(parent.peak_reserved_bytes, parent.max_bytes)
                np.testing.assert_array_equal(factor.solve(np.arange(16.)), np.arange(16.))
            self.assertEqual(owner.reserved_bytes, 0)
        remaining = d['realised_accounted_bytes']-1
        self.assertGreater(remaining, d['ordering_workspace_bytes'])
        with parent.reserve(parent.max_bytes-remaining, category='retained-history'):
            with ExitStack() as stack, self.assertRaisesRegex(TectonicsError, 'realised fill'):
                linear._factor(matrix, np.ones(16), True, owner, stack, None)
            self.assertEqual(owner.reserved_bytes, 0)
        self.assertEqual(parent.reserved_bytes, 0)

    def test_invalid_sparse_blocks_and_rhs_refuse(self):
        k, g, mass, f, h, _, _, _ = system(False)
        owner = WorkBudget(128*1024**2)
        bad_mass = mass.copy(); bad_mass.data[0] = float('nan')
        asymmetric = k.copy(); asymmetric[0, 1] = 4.
        indefinite = k.copy(); indefinite[0, 0] = -1.
        cases = [(k.toarray(), g, mass, f, h), (k.tocsc(), g, mass, f, h),
            (k, g, bad_mass, f, h), (asymmetric, g, mass, f, h), (indefinite, g, mass, f, h),
            (k, g, mass[:-1, :-1].tocsr(), f, h), (k, g, mass, f[:-1], h),
            (k, g, mass, f*np.nan, h)]
        for args in cases:
            with self.subTest(shape=args[0].shape), self.assertRaises(TectonicsError):
                solve_stokes(args[0], args[1], args[3], args[4], pressure_mass=args[2], budget=owner)
        for c in (np.zeros(k.shape[0]), np.ones(k.shape[0]-1), np.full(k.shape[0], np.nan)):
            with self.assertRaises(TectonicsError):
                solve_stokes(k, g, f, h, pressure_mass=mass, velocity_mass_sqrt_eta=c, budget=owner)
        self.assertEqual(owner.reserved_bytes, 0)


if __name__ == '__main__':
    unittest.main()
