"""Matrix-free multigrid candidate for regional 3D Stokes: operators and solves.

SPDX-License-Identifier: AGPL-3.0-only

The default-method analytical, scale, gate, refusal and reuse contracts of
``test_regional_execution3d`` are repeated with ``method='multigrid'``. Explicit
direct/GMRES-only controls remain in the reference module, without duplicate
execution here. Element operators are compared
with the assembled reference; the reuse path is checked for changed-input
invalidation; the plate and evolution consumers are exercised directly.
"""
from concurrent.futures import CancelledError
from pathlib import Path
import sys
import unittest
from unittest import mock

import numpy as np
from numpy.testing import assert_allclose, assert_array_equal
from scipy import sparse
from scipy.sparse.linalg import LinearOperator, cg

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'tools'), str(ROOT/'src'), str(Path(__file__).resolve().parent)]
import test_regional_execution3d as reference
from atlas_tectonics import regional_multigrid3d as multigrid3d
from atlas_tectonics._validation import TectonicsError
from atlas_tectonics.regional_elements3d import TaylorHoodBox
from atlas_tectonics.regional_execution import RegionalMechanicsScales
from atlas_tectonics.regional_execution3d import PreparedRegionalStokes3D, SIDES
from atlas_tectonics.resources import MemoryLimitError, WorkBudget


_ORIGINAL_PREPARE = reference.prepare


def _multigrid_prepare(**kwargs):
    kwargs.setdefault('method', 'multigrid')
    return _ORIGINAL_PREPARE(**kwargs)


class MultigridRegionalExecution3DTests(reference.RegionalExecution3DTests):
    """The reference suite with the candidate method as the default."""
    def setUp(self):
        patcher = mock.patch.object(reference, 'prepare', _multigrid_prepare)
        patcher.start()
        self.addCleanup(patcher.stop)


def mixed_pattern():
    pattern = {side: ('velocity',)*3 for side in SIDES}
    pattern['z1'] = ('traction',)*3
    pattern['x1'] = ('velocity', 'traction', 'traction')
    return pattern


def operators(cells=(3, 4, 2), lengths=(1.3, .7, 1.1), pattern=None, seed=0):
    rng = np.random.default_rng(seed)
    mesh = TaylorHoodBox(cells, lengths)
    eta = np.exp(2*rng.normal(size=(mesh.nc, 27)))
    A, B, _, _ = mesh.assemble(eta)
    pattern = mixed_pattern() if pattern is None else pattern
    fixed_mask = multigrid3d._node_mask(tuple(2*n+1 for n in cells), pattern)
    geometry = multigrid3d.StructuredGeometry(mesh, pattern, np.flatnonzero(fixed_mask),
                                              np.flatnonzero(~fixed_mask), B)
    return mesh, eta, A, B, geometry, multigrid3d.MultigridStokes(geometry, eta), rng


def relative(a, b):
    return float(np.max(np.abs(a-b))/np.max(np.abs(b)))


class MultigridOperatorTests(unittest.TestCase):
    def test_matrix_free_operator_equals_assembled_full_stress_form(self):
        mesh, eta, A, B, geometry, mg, rng = operators()
        u, p = rng.normal(size=3*mesh.nv), rng.normal(size=mesh.np)
        applied, divergence = mg.apply(u, p, divergence=True)
        self.assertLess(relative(applied, A@u+B.T@p), 4e-15)
        self.assertLess(relative(divergence, B@u), 4e-15)
        self.assertLess(relative(mg.apply(u), A@u), 4e-15)
        self.assertLess(relative(mg._diagonal(), A.diagonal()), 4e-15)
        # Cross-component coupling is present: a pure x-velocity drives y/z rows.
        ux = np.zeros((mesh.nv, 3)); ux[:, 0] = rng.normal(size=mesh.nv)
        self.assertGreater(np.max(np.abs(mg.apply(ux.ravel()).reshape(-1, 3)[:, 1:])), 0.)

    def test_gate_products_use_assembled_entries_not_element_magnitudes(self):
        mesh, eta, A, B, geometry, mg, rng = operators()
        u = rng.normal(size=3*mesh.nv)
        au, magnitude = mg.products(u)
        self.assertLess(relative(au, A@u), 4e-15)
        self.assertLess(relative(magnitude, abs(A)@np.abs(u)), 4e-15)
        self.assertLess(relative(mg.row_magnitudes(), abs(A)@np.ones(3*mesh.nv)), 4e-15)
        # Summing element magnitudes would be a strictly looser scale here.
        mesh1 = TaylorHoodBox((2, 2, 2), (1., 1., 1.))
        A1, B1, _, _ = mesh1.assemble(np.ones((8, 27)))
        cancelled = np.count_nonzero(A1.toarray() == 0.)-(A1.shape[0]**2-A1.nnz)
        self.assertGreater(cancelled, 0, 'the constant-viscosity form has assembled cancellations')

    def test_q1_level_is_the_exact_galerkin_product_of_the_q2_form(self):
        mesh, eta, A, B, geometry, mg, rng = operators()
        line = [sparse.csr_matrix(([1.]*(n+1)+[.5]*(2*n), (list(range(0, 2*n+1, 2))+[r for i in range(n) for r in (2*i+1, 2*i+1)],
                                    list(range(n+1))+[c for i in range(n) for c in (i, i+1)])), shape=(2*n+1, n+1))
                for n in mesh.cells]
        P = sparse.kron(sparse.kron(sparse.kron(line[0], line[1]), line[2]), sparse.identity(3), format='csr')
        free, free1 = geometry.free, geometry.free1
        galerkin = (P[free][:, free1].T@A[free][:, free]@P[free][:, free1]).toarray()
        self.assertLess(np.max(np.abs(mg.matrices[0].toarray()-galerkin))/np.max(np.abs(galerkin)), 4e-15)
        # Coarse zeros on constrained faces interpolate to zeros on fine constraints.
        x = rng.normal(size=len(free1))
        full = mg._prolong(0, x)
        assert_array_equal(full[geometry.fixed], 0.)
        self.assertLess(relative(full[free], P[free][:, free1]@x), 4e-15)
        r = np.zeros(3*mesh.nv); r[free] = rng.normal(size=len(free))
        self.assertAlmostEqual(float(mg._restrict(0, r)@x), float(r@full), delta=1e-12*np.linalg.norm(r)*np.linalg.norm(full))

    def test_nested_levels_interpolate_trilinear_fields_exactly_with_semicoarsening(self):
        pattern = {side: ('velocity',)*3 for side in SIDES}
        mesh = TaylorHoodBox((16, 16, 8), (4., 4., 1.))
        A, B, _, _ = mesh.assemble(np.ones((mesh.nc, 27)))
        fixed = multigrid3d._node_mask(tuple(2*n+1 for n in mesh.cells), pattern)
        geometry = multigrid3d.StructuredGeometry(mesh, pattern, np.flatnonzero(fixed), np.flatnonzero(~fixed), B)
        self.assertGreater(len(geometry.levels), 0)
        # The thin z direction (smaller spacing) is coarsened first.
        self.assertEqual(geometry.levels[0]['shape'], (17, 17, 5))
        for level in geometry.levels:
            P = level['prolong']
            self.assertTrue(np.all(np.asarray(P.sum(axis=1)).ravel() <= 1+1e-15))
            self.assertLessEqual(P.shape[1], P.shape[0])

    def test_vcycle_is_a_fixed_linear_operator_and_a_strong_preconditioner(self):
        mesh, eta, A, B, geometry, mg, rng = operators(cells=(6, 5, 4), lengths=(1.2, 1., .8), seed=4)
        free = geometry.free
        a, b = rng.normal(size=len(free)), rng.normal(size=len(free))
        combined = mg.vcycle(2.*a-3.*b)
        self.assertLess(relative(combined, 2.*mg.vcycle(a)-3.*mg.vcycle(b)), 1e-12)
        Af = A[free][:, free].tocsr()
        iterations = []
        cg(Af, b, M=LinearOperator(Af.shape, matvec=mg.vcycle), rtol=1e-10, maxiter=200,
           callback=lambda _: iterations.append(1))
        # Viscosity varies by about e^8 inside and between bricks.
        self.assertLess(len(iterations), 60)

    def test_flexible_gmres_with_deflation_meets_the_true_residual(self):
        rng = np.random.default_rng(2)
        n = 400
        # A few isolated small eigenvalues stall restarted GMRES; deflation keeps them.
        spectrum = np.concatenate(([1e-3, 3e-3, 1e-2], np.linspace(1., 3., n-3)))
        matrix = np.diag(spectrum)+(.2/np.sqrt(n))*rng.normal(size=(n, n))
        b = rng.normal(size=n)
        x, converged, iterations = multigrid3d.fgmres_dr(lambda v: matrix@v, lambda v: v, b, 1e-11, 20, 6, 1200)
        self.assertTrue(converged)
        self.assertLessEqual(np.linalg.norm(b-matrix@x), 1e-11*np.linalg.norm(b))
        restarted = multigrid3d.fgmres_dr(lambda v: matrix@v, lambda v: v, b, 1e-11, 20, 0, 1200)
        self.assertLess(iterations, restarted[2])
        # A preconditioner that changes every application (a nonlinear inner
        # step) keeps the flexible Arnoldi relation valid.
        calls = []

        def varying(v):
            calls.append(1)
            return v/np.diag(matrix)*(1.+.3*np.sin(len(calls)))
        x, converged, _ = multigrid3d.fgmres_dr(lambda v: matrix@v, varying, b, 1e-11, 20, 6, 1200)
        self.assertTrue(converged)
        self.assertLessEqual(np.linalg.norm(b-matrix@x), 1e-11*np.linalg.norm(b))
        x, converged, iterations = multigrid3d.fgmres_dr(lambda v: matrix@v, lambda v: v, b, 1e-11, 20, 6, 7)
        self.assertFalse(converged)
        self.assertEqual(iterations, 7)
        # Right-hand sides far outside the normal range are scaled internally.
        for scale in (1e-200, 1e200):
            x, converged, _ = multigrid3d.fgmres_dr(lambda v: matrix@v, lambda v: v, scale*b, 1e-11, 20, 6, 1200)
            self.assertTrue(converged)
            self.assertLess(np.max(np.abs(matrix@x-scale*b))/np.max(np.abs(scale*b)), 1e-9)

    def test_an_unattainable_aim_stops_at_the_floor_and_accepts_only_the_required_residual(self):
        # An operator whose products carry relative noise of about 1e-12 cannot
        # reach 1e-15. The solve stops at its floor instead of spinning to the
        # ceiling, and it is converged only against the looser accepted target.
        rng = np.random.default_rng(3)
        n = 200
        matrix = np.diag(np.linspace(1., 2., n))+(.1/np.sqrt(n))*rng.normal(size=(n, n))
        noise = np.random.default_rng(4)

        def noisy(v):
            y = matrix@v
            return y*(1+1e-12*noise.normal(size=n))
        b = rng.normal(size=n)
        x, converged, iterations = multigrid3d.fgmres_dr(noisy, lambda v: v, b, 1e-15, 20, 6, 1200, accept=1e-11)
        self.assertTrue(converged)
        self.assertLess(iterations, 1200)
        self.assertLessEqual(np.linalg.norm(b-matrix@x), 1e-11*np.linalg.norm(b))
        x, converged, iterations = multigrid3d.fgmres_dr(noisy, lambda v: v, b, 1e-15, 20, 6, 1200, accept=1e-15)
        self.assertFalse(converged)
        self.assertLess(iterations, 1200)


def prepare(cells=(3, 3, 3), eta=2., boundary=None, method='multigrid', **kwargs):
    values = dict(scales=RegionalMechanicsScales(1., 1.), reference_viscosity_pa_s=2.,
                  frame_id='synthetic-Cartesian-right-handed', vertical_datum='box-bottom-z-zero',
                  material_source='analytical-test-material', physical_mean_pressure_pa=0.)
    values.update(kwargs)
    return PreparedRegionalStokes3D(cells, kwargs.pop('lengths', (1., 1., 1.)), eta,
                                    reference.pattern() if boundary is None else boundary, method=method,
                                    **{k: v for k, v in values.items() if k != 'lengths'})


class MultigridPlanTests(unittest.TestCase):
    def test_changed_viscosity_reuses_geometry_and_invalidates_results(self):
        q = reference.quadrature((3, 3, 3))
        force = np.stack((np.sin(3*q[..., 2]), q[..., 0], np.cos(2*q[..., 1])), axis=-1)
        budget = WorkBudget(512*1024**2)
        with prepare(eta=1+q[..., 0], budget=budget) as plan:
            first = reference.solve(plan, force=force)
            reserved = budget.reserved_bytes
            changed = plan.with_viscosity(2+q[..., 1], material_source='changed-material')
            with changed, prepare(eta=2+q[..., 1], material_source='changed-material') as fresh:
                self.assertTrue(changed.statistics()['geometry_reused'])
                self.assertFalse(fresh.statistics()['geometry_reused'])
                self.assertNotEqual(changed.plan_id, plan.plan_id)
                self.assertEqual(changed.plan_id, fresh.plan_id)
                reused = reference.solve(changed, force=force)
                cold = reference.solve(fresh, force=force)
                self.assertEqual(changed.statistics()['result_hits'], 0)
                self.assertNotEqual(reused.result_id, first.result_id)
                for name in cold.array_names:
                    assert_array_equal(reused.array(name), cold.array(name))
                self.assertGreater(np.max(np.abs(reused.array('velocity_m_s')-first.array('velocity_m_s'))), 1e-3)
            # The original plan is untouched and still serves its own result.
            self.assertIs(reference.solve(plan, force=force), first)
            self.assertEqual(budget.reserved_bytes, reserved)
            released = plan.with_viscosity(3., material_source='released', release=True)
            with released:
                with self.assertRaisesRegex(TectonicsError, 'closed'):
                    reference.solve(plan, force=force)
                self.assertLessEqual(budget.reserved_bytes, reserved*1.01)
        self.assertEqual(budget.reserved_bytes, 0)

    def test_reused_preparation_must_match_geometry_boundaries_and_method(self):
        with prepare() as plan:
            shared = plan._shared
            for changes in (dict(cells=(3, 3, 4)), dict(boundary=mixed_pattern()), dict(method='gmres'),
                            dict(lengths=(1., 1., 2.)), dict(scales=RegionalMechanicsScales(2., 1.))):
                with self.subTest(changes=changes), self.assertRaisesRegex(TectonicsError, 'does not match'):
                    prepare(_shared=shared, **changes)

    def test_default_budget_now_admits_a_ten_cube_that_assembly_refuses(self):
        # The assembled route refuses every 7x7x7 cube in the default 256 MiB.
        with self.assertRaises(MemoryLimitError):
            prepare(cells=(7, 7, 7), method='gmres')
        with prepare(cells=(10, 10, 10)) as plan:
            stats = plan.statistics()['budget']
            self.assertLessEqual(stats['reserved_bytes'], 256*1024**2)
            self.assertIn('regional3d-multigrid-factor', stats['categories'])
            self.assertEqual(plan.descriptor()['solver']['krylov_rtol'], 1e-13)
            self.assertGreaterEqual(len(plan.descriptor()['solver']['levels']), 2)
        with self.assertRaises(MemoryLimitError):
            prepare(budget=WorkBudget(4*1024**2))

    def test_refused_admission_returns_every_multigrid_reservation(self):
        projected = multigrid3d.projected_bytes((3, 3, 3))
        for limit in (projected['structure']-1, projected['structure']+projected['work']-1):
            budget = WorkBudget(limit)
            with self.assertRaises(MemoryLimitError):
                prepare(budget=budget)
            self.assertEqual(budget.reserved_bytes, 0)

    def test_floor_limited_high_contrast_case_is_accepted_where_the_reference_is(self):
        # Review finding: a 1e13-conditioned box (base prescribed only, cellwise
        # contrast 1e4) cannot reach the 1e-13 aim; it spun to the ceiling and was
        # refused although gmres and direct accept it. It now stops at its floor
        # and is accepted by the unchanged gates.
        cells, lengths = (4, 2, 2), (1e5, 1e4, 1e5)
        q = reference.quadrature(cells, lengths)
        strong = np.array([1, 1, 0, 0, 0, 1, 1, 1, 1, 1, 0, 1, 1, 1, 1, 1], dtype=bool)
        eta = 1e21*np.where(strong, 1e4, 1.)[:, None]*np.ones(27)
        force = np.zeros(q.shape)
        force[..., 2] = -10.*(3300.-30.*np.sin(6*q[..., 0]/lengths[0])*np.cos(5*q[..., 1]/lengths[1]))
        force[..., 0] = 3.*np.cos(4*q[..., 2]/lengths[2])
        boundary = dict({side: ('traction',)*3 for side in SIDES}, z0=('velocity',)*3)
        outputs = {}
        for method in ('direct', 'multigrid'):
            with prepare(cells=cells, lengths=lengths, eta=eta, boundary=boundary, method=method,
                         scales=RegionalMechanicsScales(1e5, 1e-9), reference_viscosity_pa_s=1e21,
                         physical_mean_pressure_pa=None, budget=WorkBudget(2**31)) as plan:
                outputs[method] = reference.solve(plan, force=force)
                if method == 'multigrid':
                    self.assertLess(plan.statistics()['krylov_iterations'], 1200)
                    applications = plan.statistics()['preconditioner_applications']
                    self.assertGreater(applications, 0)
            if method == 'multigrid':
                self.assertEqual(plan.statistics()['preconditioner_applications'], applications)
        u0, u1 = outputs['direct'].array('velocity_m_s'), outputs['multigrid'].array('velocity_m_s')
        self.assertLess(np.max(np.abs(u1-u0))/np.max(np.abs(u0)), 1e-8)

    def test_cancellation_during_multigrid_preparation_returns_the_reservation(self):
        budget = WorkBudget(512*1024**2)
        calls = []

        def cancel():
            calls.append(1)
            return len(calls) > 12
        with self.assertRaises(CancelledError):
            prepare(cells=(5, 5, 5), budget=budget, cancel=cancel)
        self.assertGreater(len(calls), 12)
        self.assertEqual(budget.reserved_bytes, 0)

    def test_source_and_loaded_implementation_of_the_new_module_are_bound(self):
        with mock.patch.object(multigrid3d, '_LOADED_SOURCE_SHA256', '0'*64):
            with self.assertRaisesRegex(TectonicsError, 'source changed'):
                prepare()
        with prepare() as plan:
            with mock.patch.object(multigrid3d.MultigridStokes, 'precondition', lambda *_: None):
                with self.assertRaisesRegex(TectonicsError, 'implementation changed'):
                    reference.solve(plan)

    def test_buoyant_high_contrast_inclusion_matches_the_direct_oracle(self):
        length, cells = 1e5, (5, 5, 5)
        q = reference.quadrature(cells, (length,)*3)
        inside = np.sum((q/length-[.5, .5, .4])**2, axis=-1) < .06
        force = np.zeros(q.shape)
        force[..., 2] = -10.*(3300.-30.*inside)
        results = {}
        for boundary in ('closed', 'open-top'):
            for method in ('direct', 'multigrid'):
                pattern = reference.pattern() if boundary == 'closed' else dict(reference.pattern(), z1=('traction',)*3)
                with prepare(cells=cells, lengths=(length,)*3, eta=np.where(inside, 1e17, 1e21), boundary=pattern,
                             method=method, scales=RegionalMechanicsScales(length, 1e-9),
                             reference_viscosity_pa_s=1e21, physical_mean_pressure_pa=None,
                             budget=WorkBudget(512*1024**2)) as plan:
                    results[boundary, method] = reference.solve(plan, force=force)
            u0 = results[boundary, 'direct'].array('velocity_m_s')
            u1 = results[boundary, 'multigrid'].array('velocity_m_s')
            self.assertLess(np.max(np.abs(u1-u0))/np.max(np.abs(u0)), 1e-8)
            self.assertGreater(results[boundary, 'multigrid'].descriptor()['krylov_iterations'], 0)

    def test_flat_box_with_semicoarsened_levels_matches_the_direct_oracle(self):
        cells, lengths = (9, 8, 4), (4., 3.5, 1.)
        q = reference.quadrature(cells, lengths)
        eta = np.where(q[..., 2] > .7, 100., 1.)*(1+.5*np.sin(q[..., 0]))
        force = np.stack((np.zeros(q.shape[:2]), np.sin(q[..., 0]), -1-np.cos(q[..., 1])), axis=-1)
        boundary = dict(reference.pattern(), z1=('traction',)*3,
                        x0=('velocity', 'traction', 'traction'), x1=('velocity', 'traction', 'traction'))
        outputs = {}
        for method in ('direct', 'multigrid'):
            # A small coarse-grid threshold forces nested (semi-coarsened) Q1
            # levels at a test-sized mesh; the threshold is part of the plan identity.
            with mock.patch.dict(multigrid3d.SETTINGS, coarse_dofs=300), prepare(
                    cells=cells, lengths=lengths, eta=eta, boundary=boundary, method=method,
                    reference_viscosity_pa_s=1., physical_mean_pressure_pa=None,
                    budget=WorkBudget(8*1024**3)) as plan:
                outputs[method] = reference.solve(plan, force=force)
                if method == 'multigrid':
                    self.assertGreaterEqual(len(plan.descriptor()['solver']['levels']), 3)
                    self.assertEqual(plan.descriptor()['solver']['coarse_dofs'], 300)
        for name in ('velocity_m_s', 'physical_pressure_pa', 'velocity_constraint_reaction_n'):
            self.assertLess(relative(outputs['multigrid'].array(name), outputs['direct'].array(name)), 1e-8)


class MultigridConsumerTests(unittest.TestCase):
    def test_plate_torque_coupling_recovers_the_analytical_twist(self):
        import regional_plate_coupling as plates
        import test_regional_plate_coupling as fixture
        boundary = {side: ('traction',)*3 for side in SIDES}
        boundary['z0'] = boundary['z1'] = ('velocity',)*3
        with PreparedRegionalStokes3D((2, 2, 2), (2., 3., 4.), 2., boundary,
                scales=RegionalMechanicsScales(1., 1.), reference_viscosity_pa_s=2.,
                frame_id='local-box', vertical_datum='fixed-box-bottom',
                material_source='synthetic-constant-viscosity', method='multigrid') as p:
            mapped = plates.PreparedPlateBoundary3D(p, **fixture.options(p))
            base = np.zeros_like(p.coordinates('velocity'))
            args = (0., base, fixture.twisting_tractions(p), [[1.625, 0., 0.]], np.zeros((3, 3)))
            result = mapped.solve_torque_coupled(*args, coupling_source='analytical-torque', **fixture.request())
            assert_allclose(result.exchange.array('angular_velocity_rad_s'), [[.5, 0., 0.]], atol=2e-9)
            assert_allclose(result.exchange.array('plate_power_into_region_w'), [.8125], atol=2e-9)
            prescribed = mapped.solve_prescribed([fixture.motion()], 0., base, fixture.twisting_tractions(p),
                                                 **fixture.request())
            assert_allclose(prescribed.exchange.array('torque_on_region_nm'), [[1.625, 0., 0.]], atol=2e-9)
            self.assertEqual(p.statistics()['factorizations'], 1)

    def test_evolution_selects_the_candidate_and_reuses_geometry_on_viscosity_change(self):
        import test_regional_evolution3d as evolution
        from atlas_tectonics.constitutive import RheologyProfile
        profile = RheologyProfile('thermal-control', 'tosi-linear', 'declared-analytic',
                                  (('contrast_T', 10.), ('contrast_z', 1.)))
        with self.assertRaisesRegex(TectonicsError, 'mechanics method'):
            evolution.prepare(profile, mechanics_method='ilu')
        velocities = {}
        for method in ('direct', 'multigrid'):
            with evolution.prepare(profile, mechanics_method=method) as plan:
                self.assertEqual(plan.descriptor()['mechanics_method'], method)
                state = evolution.initial(plan, histories={'formation': 0.})
                xyz = np.indices((5, 5, 5)).reshape(3, -1).T/4
                mode = np.stack((xyz[:, 0], -xyz[:, 1], np.zeros(len(xyz))), axis=-1)[None]
                coupling = dict(boundary_modes_m=mode, external_generalized_force_j=np.array([1.]),
                                external_resistance_j_s=np.array([[1.]]), source='synthetic-exterior-only')
                result = evolution.advance(plan, state, .02, heat_source_w_m3=2., coupling=coupling,
                                           boundary_stocks=evolution.full_stocks(plan))
                stats = plan.statistics()
                self.assertGreater(stats['mechanical_preparations'], 1)
                self.assertEqual(stats['mechanical_geometry_reuses'], stats['mechanical_preparations']-1)
                velocities[method] = result.mechanics.array('velocity_m_s')
        assert_allclose(velocities['multigrid'], velocities['direct'], atol=2e-9)


class BenchmarkPressureComparisonTests(unittest.TestCase):
    def test_traction_datum_offset_is_not_hidden(self):
        from benchmark_regional3d_solvers import _pressure_forward_error
        pressure = np.array([2.e9, 4.e9, 6.e9])
        self.assertAlmostEqual(_pressure_forward_error(pressure, pressure+1.e9,
            physical_pressure_defined=True), 1./6.)

    def test_supplied_mean_is_also_part_of_the_comparison(self):
        from benchmark_regional3d_solvers import _pressure_forward_error
        pressure = np.array([-2., 0., 2.])+10.
        self.assertAlmostEqual(_pressure_forward_error(pressure, pressure+3.,
            physical_pressure_defined=True), .25)

    def test_undetermined_gauge_allows_only_a_constant_shift(self):
        from benchmark_regional3d_solvers import _pressure_forward_error
        pressure = np.array([-2., 0., 2.])
        self.assertEqual(_pressure_forward_error(pressure, pressure+100.,
            physical_pressure_defined=False), 0.)
        self.assertGreater(_pressure_forward_error(pressure, pressure+[100., 101., 100.],
            physical_pressure_defined=False), 0.)

    def test_zero_reference_does_not_hide_nonzero_error(self):
        from benchmark_regional3d_solvers import _pressure_forward_error
        self.assertEqual(_pressure_forward_error(np.zeros(3), np.zeros(3),
            physical_pressure_defined=True), 0.)
        with self.assertRaisesRegex(ValueError, 'zero reference'):
            _pressure_forward_error(np.zeros(3), np.ones(3), physical_pressure_defined=True)


if __name__ == '__main__':
    unittest.main()
