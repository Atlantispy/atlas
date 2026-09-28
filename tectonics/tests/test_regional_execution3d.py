"""Bounded analytical, convergence and execution checks for regional 3D Stokes.

SPDX-License-Identifier: AGPL-3.0-only
"""
from concurrent.futures import CancelledError
import threading
import unittest
from unittest import mock

import numpy as np
from numpy.testing import assert_allclose, assert_array_equal

from atlas_tectonics import regional_elements3d, regional_execution3d
from atlas_tectonics._validation import TectonicsError
from atlas_tectonics.regional_execution import RegionalMechanicsScales
from atlas_tectonics.regional_execution3d import PreparedRegionalStokes3D, SIDES
from atlas_tectonics.resources import MemoryLimitError, WorkBudget


def pattern():
    return {side: ('velocity',)*3 for side in SIDES}


def quadrature(cells=(2, 2, 2), lengths=(1., 1., 1.)):
    """Sample the declared tensor Gauss rule without preparing a solver."""
    index = np.indices(cells).reshape(3, -1).T
    points, _ = np.polynomial.legendre.leggauss(3)
    reference = points[np.indices((3, 3, 3)).reshape(3, -1).T]
    spacing = np.asarray(lengths)/cells
    return (index[:, None, :]+(reference[None, :, :]+1)/2)*spacing


def prepare(*, cells=(2, 2, 2), lengths=(1., 1., 1.), eta=2., boundary=None, **kwargs):
    defaults = dict(scales=RegionalMechanicsScales(1., 1.), reference_viscosity_pa_s=2.,
                    frame_id='synthetic-Cartesian-right-handed', vertical_datum='box-bottom-z-zero',
                    material_source='analytical-test-material', physical_mean_pressure_pa=0.)
    defaults.update(kwargs)
    return PreparedRegionalStokes3D(cells, lengths, eta, pattern() if boundary is None else boundary, **defaults)


def request(**kwargs):
    values = dict(parent_state_id='analytical-parent', epoch_id='same-time', time_s=0.,
                  force_source='continuous-analytical-force', boundary_source='analytical-trace')
    values.update(kwargs)
    return values


def zeros():
    return {side: 0. for side in SIDES}


def solve(plan, force=0., velocity=0., tractions=None, **kwargs):
    return plan.solve(force, velocity, zeros() if tractions is None else tractions, **request(**kwargs))


def cross_shear(points):
    x, y, z = np.moveaxis(points, -1, 0)
    return np.stack((y*z, z*x, x*y), axis=-1)


class RegionalExecution3DTests(unittest.TestCase):
    def assert_gates(self, result):
        d = result.descriptor()
        self.assertLessEqual(d['linear_relative_residual'], 2e-9)
        self.assertLessEqual(d['work_relative_residual'], 5e-9)
        self.assertLess(d['weak_divergence_max'], 2e-8)
        self.assertFalse(d['scientific_acceptance'])

    def test_affine_extension_and_shear_with_physical_pressure(self):
        h = np.array([[.3, -.2, .7], [.4, -.1, -.6], [.8, .2, -.2]])
        strain = (h+h.T)/2
        with prepare(physical_mean_pressure_pa=11.) as plan:
            xyz = plan.coordinates('velocity')
            expected = xyz @ h.T+[.2, -.3, .1]
            result = solve(plan, velocity=expected)
        self.assert_gates(result)
        assert_allclose(result.array('velocity_m_s'), expected, atol=2e-9)
        assert_allclose(result.array('physical_pressure_pa'), 11., atol=3e-8)
        assert_allclose(result.array('velocity_gradient_s_inv'), np.broadcast_to(h, (8, 27, 3, 3)), atol=2e-8)
        assert_allclose(result.array('extra_plus_viscous_stress_pa'), np.broadcast_to(4*strain, (8, 27, 3, 3)), atol=8e-8)
        self.assertAlmostEqual(result.descriptor()['power_w']['viscous_dissipation'], 4*np.sum(strain*strain), delta=2e-8)

    def test_variable_viscosity_manufactured_polynomial(self):
        q = quadrature()
        eta = 1+q[..., 0]
        force = np.stack((np.ones(q.shape[:2]), 2-2*q[..., 2], -3-2*q[..., 1]), axis=-1)
        with prepare(eta=eta) as plan:
            xyz = plan.coordinates('velocity')
            pressure = plan.coordinates('pressure') @ np.array([1., 2., -3.])
            result = solve(plan, force=force, velocity=cross_shear(xyz))
        self.assert_gates(result)
        assert_allclose(result.array('velocity_m_s'), cross_shear(xyz), atol=2e-9)
        assert_allclose(result.array('physical_pressure_pa'), pressure, atol=3e-8)
        self.assertGreater(result.descriptor()['krylov_iterations'], 0)

    def test_hydrostatic_body_force_and_reaction(self):
        with prepare(physical_mean_pressure_pa=7.) as plan:
            q = plan.coordinates()
            force = np.broadcast_to([0., 0., -6.], q.shape)
            expected = 10.-6.*plan.coordinates('pressure')[:, 2]
            result = solve(plan, force=force)
        self.assert_gates(result)
        assert_allclose(result.array('velocity_m_s'), 0., atol=2e-10)
        assert_allclose(result.array('physical_pressure_pa'), expected, atol=2e-8)
        assert_allclose(result.array('velocity_constraint_reaction_n').sum(axis=0), [0., 0., 6.], atol=3e-9)

    def test_mixed_top_traction_defines_physical_pressure(self):
        boundary = pattern()
        boundary['z1'] = ('traction',)*3
        with prepare(boundary=boundary, physical_mean_pressure_pa=None) as plan:
            xyz = plan.coordinates('velocity')
            velocity = np.zeros_like(xyz)
            velocity[:, 0] = xyz[:, 2]
            traction = zeros()
            traction['z1'] = np.broadcast_to([2., 0., -7.], plan.coordinates('z1').shape)
            result = solve(plan, velocity=velocity, tractions=traction)
        self.assert_gates(result)
        assert_allclose(result.array('velocity_m_s'), velocity, atol=2e-9)
        assert_allclose(result.array('physical_pressure_pa'), 7., atol=3e-8)
        assert_allclose(result.array('natural_boundary_force_n').sum(axis=0), [2., 0., -7.], atol=1e-13)
        self.assertEqual(result.descriptor()['numerical_pressure_gauge'], 'natural traction')
        self.assertAlmostEqual(result.descriptor()['power_w']['viscous_dissipation'], 2., delta=2e-8)

    def test_piecewise_viscosity_preserves_interface_traction(self):
        q = quadrature()
        eta = np.where(q[..., 2] < .5, 1., 4.)
        with prepare(eta=eta) as plan:
            xyz = plan.coordinates('velocity')
            velocity = np.zeros_like(xyz)
            z = xyz[:, 2]
            velocity[:, 0] = np.where(z <= .5, 1.6*z, .8+.4*(z-.5))
            result = solve(plan, velocity=velocity)
        self.assert_gates(result)
        assert_allclose(result.array('velocity_m_s'), velocity, atol=2e-9)
        assert_allclose(result.array('physical_pressure_pa'), 0., atol=3e-8)
        stress = result.array('extra_plus_viscous_stress_pa')
        assert_allclose(stress[..., 0, 2], 1.6, atol=3e-8)
        assert_allclose(stress[..., 2, 0], 1.6, atol=3e-8)
        self.assertAlmostEqual(result.descriptor()['power_w']['viscous_dissipation'], 1.6, delta=2e-8)

    def test_deviatoric_extra_stress_is_preserved_in_equilibrium(self):
        with prepare() as plan:
            q = plan.coordinates()
            stress = np.zeros((*q.shape[:2], 3, 3))
            stress[..., 0, 1] = stress[..., 1, 0] = q[..., 0]
            result = solve(plan, force=np.broadcast_to([0., -1., 0.], q.shape),
                           extra_stress_pa=stress, stress_source='retained-deviatoric-test-state')
        self.assert_gates(result)
        assert_allclose(result.array('velocity_m_s'), 0., atol=2e-10)
        assert_allclose(result.array('physical_pressure_pa'), 0., atol=2e-8)
        assert_allclose(result.array('extra_plus_viscous_stress_pa'), stress, atol=2e-8)
        self.assertEqual(result.descriptor()['request']['stress_source'], 'retained-deviatoric-test-state')

    def test_rigid_rotation_has_no_viscous_energy(self):
        with prepare() as plan:
            xyz = plan.coordinates('velocity')
            velocity = np.cross([.3, -.7, .4], xyz)+[.2, .1, -.3]
            result = solve(plan, velocity=velocity)
        self.assert_gates(result)
        assert_allclose(result.array('velocity_m_s'), velocity, atol=1e-9)
        assert_allclose(result.array('extra_plus_viscous_stress_pa'), 0., atol=2e-8)
        self.assertLess(abs(result.descriptor()['power_w']['viscous_dissipation']), 1e-16)

    def test_si_rescaling_and_direct_gmres_agree(self):
        results = []
        for method, scales, reference in (
                ('gmres', RegionalMechanicsScales(1., 1.), 2.),
                ('direct', RegionalMechanicsScales(2.5, .125), 7.)):
            with self.subTest(method=method), prepare(method=method, scales=scales,
                    reference_viscosity_pa_s=reference, physical_mean_pressure_pa=4.) as plan:
                xyz = plan.coordinates('velocity')
                velocity = np.stack((xyz[:, 0]+.3*xyz[:, 2], -xyz[:, 1], np.zeros(len(xyz))), axis=-1)
                results.append(solve(plan, velocity=velocity))
        for result in results:
            self.assert_gates(result)
        for field in results[0].array_names:
            assert_allclose(results[0].array(field), results[1].array(field), atol=3e-8, rtol=3e-8)
        for name, value in results[0].descriptor()['power_w'].items():
            self.assertAlmostEqual(value, results[1].descriptor()['power_w'][name], delta=3e-8)

    def test_latest_cache_immutability_and_parent_invalidation(self):
        with prepare() as plan:
            a = solve(plan)
            b = solve(plan)
            c = solve(plan, parent_state_id='changed-parent')
            self.assertIs(a, b)
            self.assertNotEqual(a.result_id, c.result_id)
            self.assertEqual(plan.statistics()['solves'], 2)
            self.assertEqual(plan.statistics()['result_hits'], 1)
            for name in a.array_names:
                assert_array_equal(a.array(name), c.array(name))
                with self.assertRaises(ValueError):
                    a.array(name).setflags(write=True)
            with self.assertRaises(TectonicsError):
                a.result_id = 'changed'
            descriptor = a.descriptor()
            descriptor['request']['parent_state_id'] = 'edited'
            self.assertEqual(a.descriptor()['request']['parent_state_id'], 'analytical-parent')

    def test_force_coupling_responds_to_changed_regional_material(self):
        rates = []
        for eta, expected in ((2., .5), (4., 5/18)):
            with self.subTest(eta=eta), prepare(eta=eta) as plan:
                xyz = plan.coordinates('velocity')
                mode = np.stack((xyz[:, 0], -xyz[:, 1], np.zeros(len(xyz))), axis=-1)[None, ...]
                args = (0., 0., zeros(), mode, np.array([5.]), np.array([[2.]]))
                result = plan.solve_force_coupled(*args, coupling_source='explicit-test-driving', **request())
                repeated = plan.solve_force_coupled(*args, coupling_source='explicit-test-driving', **request())
                self.assertEqual(plan.statistics()['coupling_response_hits'], 1)
                self.assert_gates(result)
                rate = result.array('generalized_rates_s_inv')[0]
                rates.append(rate)
                self.assertAlmostEqual(rate, expected, delta=2e-9)
                assert_allclose(result.array('velocity_m_s'), expected*mode[0], atol=2e-9)
                assert_allclose(result.array('generalized_force_residual_j'), 0., atol=3e-8)
                assert_allclose(repeated.array('generalized_rates_s_inv'), [expected], atol=2e-9)
        self.assertGreater(rates[0], rates[1])

    def test_high_face_mask_uses_topology_not_float_endpoint_equality(self):
        with prepare(cells=(3, 2, 2), lengths=(.11050505050505051, 1., 1.)) as plan:
            mask = plan.velocity_mask().reshape(7, 5, 5, 3)
            self.assertTrue(np.all(mask[-1]), 'all high-x nodes require their prescribed velocity components')
            self.assertEqual(plan.descriptor()['pressure_gauge_required'], True)

    def test_nontrivial_3d_smooth_solution_converges(self):
        errors = []
        for n in (2, 4):
            def exact(points):
                x, y, z = np.moveaxis(np.pi*points, -1, 0)
                return np.stack((np.sin(x)*np.cos(y)*np.cos(z),
                                 -np.cos(x)*np.sin(y)*np.cos(z), np.zeros_like(x)), axis=-1)
            with prepare(cells=(n, n, n), eta=1.) as plan:
                q = plan.coordinates()
                x, y, z = np.moveaxis(np.pi*q, -1, 0)
                pressure_gradient = np.pi*np.stack((np.cos(x)*np.sin(y)*np.sin(z),
                        np.sin(x)*np.cos(y)*np.sin(z), np.sin(x)*np.sin(y)*np.cos(z)), axis=-1)
                force = 3*np.pi**2*exact(q)+pressure_gradient
                # Mean sin(pi*x)sin(pi*y)sin(pi*z) is 8/pi^3. The public datum
                # is zero here, so only velocity convergence is compared.
                result = solve(plan, force=force, velocity=exact(plan.coordinates('velocity')))
                self.assert_gates(result)
                points, weights = np.polynomial.legendre.leggauss(3)
                indices = np.indices((3, 3, 3)).reshape(3, -1).T
                w = np.prod(weights[indices], axis=1)/(8*n**3)
                difference = result.array('velocity_q_m_s')-exact(q)
                errors.append(float(np.sqrt(np.sum(np.sum(difference*difference, axis=-1)*w))))
        self.assertGreater(errors[0], 1e-4)
        self.assertLess(errors[1], errors[0]/3.)

    def test_cancellation_flux_source_and_budget_refusals(self):
        budget = WorkBudget(256*1024**2)
        event = threading.Event()
        event.set()
        with self.assertRaises(CancelledError):
            prepare(cancel=event, budget=budget)
        self.assertEqual(budget.reserved_bytes, 0)
        with self.assertRaises(MemoryLimitError):
            prepare(budget=WorkBudget(1024))
        with prepare(budget=budget) as plan:
            xyz = plan.coordinates('velocity')
            with self.assertRaisesRegex(TectonicsError, 'flux'):
                solve(plan, velocity=xyz)
            with self.assertRaises(CancelledError):
                solve(plan, cancel=event)
            with self.assertRaisesRegex(TectonicsError, 'force source'):
                solve(plan, force_source='')
            with mock.patch.object(regional_elements3d.TaylorHoodBox, 'evaluate', lambda *_: None):
                with self.assertRaisesRegex(TectonicsError, 'implementation changed'):
                    solve(plan)
        self.assertEqual(budget.reserved_bytes, 0)
        with mock.patch.object(regional_execution3d, '_LOADED_SOURCE_SHA256', '0'*64):
            with self.assertRaisesRegex(TectonicsError, 'source changed'):
                prepare(budget=budget)
        self.assertEqual(budget.reserved_bytes, 0)


if __name__ == '__main__':
    unittest.main()
