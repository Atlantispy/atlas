"""Bounded analytical, convergence and execution checks for regional 3D Stokes.

SPDX-License-Identifier: AGPL-3.0-only
"""
from concurrent.futures import CancelledError
import gc
import json
import os
from pathlib import Path
import subprocess
import sys
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


class _RegionalExecutionAssertions:
    def assert_gates(self, result):
        d = result.descriptor()
        self.assertLessEqual(d['linear_relative_residual'], 2e-9)
        self.assertLessEqual(d['work_relative_residual'], 5e-9)
        self.assertLess(d['weak_divergence_max'], 2e-8)
        self.assertFalse(d['scientific_acceptance'])


class RegionalExecution3DTests(_RegionalExecutionAssertions, unittest.TestCase):
    """Default-method contracts also exercised with multigrid."""

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

    def test_small_magnitude_solves_match_the_direct_oracle(self):
        # R1: GMRES used an absolute atol and gates floored at max(1, ...), so a
        # small dimensionless load returned zero velocity with residual ~1e-14.
        boundary = pattern()
        boundary['z1'] = ('traction',)*3
        q = quadrature(cells=(3, 3, 3))
        eta = np.exp(3*np.sin(3*q[..., 0])*np.cos(2*q[..., 1])+q[..., 2])
        force = np.stack((np.sin(4*q[..., 2]), np.cos(3*q[..., 0]), np.sin(5*q[..., 1])*q[..., 0]), -1)
        with prepare(cells=(3, 3, 3), eta=eta, boundary=boundary, method='direct',
                     reference_viscosity_pa_s=1., physical_mean_pressure_pa=None) as plan:
            oracle = solve(plan, force=force).array('velocity_m_s')
        with prepare(cells=(3, 3, 3), eta=eta, boundary=boundary,
                     reference_viscosity_pa_s=1., physical_mean_pressure_pa=None) as plan:
            for amplitude in (1., 1e-9, 1e-12, 1e-14):
                with self.subTest(amplitude=amplitude):
                    result = solve(plan, force=amplitude*force)
                    self.assert_gates(result)
                    self.assertGreater(result.descriptor()['krylov_iterations'], 0)
                    scaled = result.array('velocity_m_s')/amplitude
                    self.assertLess(np.max(np.abs(scaled-oracle))/np.max(np.abs(oracle)), 1e-9)

    def test_closed_box_net_inflow_is_refused_at_every_scale(self):
        # A 5% net inflow into a closed incompressible box was accepted with unit
        # scales because the flux tolerance was floored at max(1, |d|).
        length, speed = 1e5, 1e-9
        for scales in (RegionalMechanicsScales(1., 1.), RegionalMechanicsScales(length, speed)):
            for method in ('direct', 'gmres'):
                with self.subTest(scales=scales, method=method), prepare(
                        lengths=(length,)*3, eta=1e21, scales=scales, method=method,
                        reference_viscosity_pa_s=1e21) as plan:
                    xyz = plan.coordinates('velocity')
                    profile = np.sin(np.pi*xyz[:, 1]/length)*np.sin(np.pi*xyz[:, 2]/length)
                    velocity = np.zeros_like(xyz)
                    velocity[xyz[:, 0] == 0, 0] = speed*profile[xyz[:, 0] == 0]
                    high = xyz[:, 0] == np.max(xyz[:, 0])
                    velocity[high, 0] = .95*speed*profile[high]
                    with self.assertRaisesRegex(TectonicsError, 'net flux'):
                        solve(plan, velocity=velocity)
                    # Balanced through-flow of the same size remains admissible.
                    velocity[high, 0] = speed*profile[high]
                    self.assert_gates(solve(plan, velocity=velocity))
        with prepare(eta=1., reference_viscosity_pa_s=1.) as plan:
            xyz = plan.coordinates('velocity')
            inflow = np.zeros_like(xyz)
            low = xyz[:, 0] == 0
            inflow[low, 0] = 1e-12*np.sin(np.pi*xyz[low, 1])*np.sin(np.pi*xyz[low, 2])
            with self.assertRaisesRegex(TectonicsError, 'net flux'):
                solve(plan, velocity=inflow)

    def test_small_traction_box_is_not_mistaken_for_a_closed_box(self):
        # The gauge test was floored at max(1, |B|); small dimensionless boxes
        # have tiny B entries, so an open (traction) box acquired a pressure gauge.
        boundary = pattern()
        boundary['z1'] = ('traction',)*3
        scales = RegionalMechanicsScales(1e6, 1.)
        with prepare(boundary=boundary, scales=scales, physical_mean_pressure_pa=None) as plan:
            self.assertFalse(plan.descriptor()['pressure_gauge_required'])
            q = plan.coordinates()
            result = solve(plan, force=np.broadcast_to([0., 0., -6.], q.shape))
            d = result.descriptor()
            self.assertLessEqual(d['linear_relative_residual'], 2e-9)
            self.assertLessEqual(d['work_relative_residual'], 5e-9)
            self.assertTrue(d['physical_pressure_defined'])
            # Hydrostatic: velocity is zero relative to its scale f L^2/eta = 3 m/s.
            assert_allclose(result.array('velocity_m_s'), 0., atol=3e-9)
            assert_allclose(result.array('physical_pressure_pa'),
                            6.*(1.-plan.coordinates('pressure')[:, 2]), atol=1e-8)
        with self.assertRaisesRegex(TectonicsError, 'second datum'):
            prepare(boundary=boundary, scales=scales, physical_mean_pressure_pa=0.)
        with prepare(scales=scales) as plan:
            self.assertTrue(plan.descriptor()['pressure_gauge_required'])

    def test_unrepresentable_load_is_refused_and_exact_zero_is_exact(self):
        with prepare() as plan:
            q = plan.coordinates()
            with self.assertRaisesRegex(TectonicsError, 'binary64 relative precision'):
                solve(plan, force=np.broadcast_to([1e-300, 2e-300, -1e-300], q.shape))
            quiet = solve(plan, force_source='explicit-zero-force')
            self.assert_gates(quiet)
            assert_array_equal(quiet.array('velocity_m_s'), 0.)
            self.assertEqual(quiet.descriptor()['linear_relative_residual'], 0.)

    def test_rigid_translation_through_an_open_top_passes_the_work_gate(self):
        # Every power is round-off here; the work floor is the attributable
        # residual and operand round-off, not an absolute max(1, ...).
        boundary = pattern()
        boundary['z1'] = ('traction',)*3
        with prepare(boundary=boundary, physical_mean_pressure_pa=None) as plan:
            velocity = np.zeros((len(plan.coordinates('velocity')), 3))
            velocity[:, 0] = 5.
            result = solve(plan, velocity=velocity)
        self.assert_gates(result)
        assert_allclose(result.array('velocity_m_s'), velocity, atol=1e-9)

    def test_underflowing_forcing_and_power_are_refused_not_zeroed(self):
        # A force of 1e-100 N/m3 in a 1e-90 m box underflowed in assembly and was
        # returned as exact zero velocity; powers below binary64 were published
        # as 0 W. Both now refuse and name the scale choice.
        with prepare(lengths=(1e-90,)*3, eta=1e-20, reference_viscosity_pa_s=1e-20) as plan:
            q = plan.coordinates()
            with self.assertRaisesRegex(TectonicsError, 'underflows to zero in assembly'):
                solve(plan, force=np.broadcast_to([0., 0., -1e-100], q.shape))
        with prepare(scales=RegionalMechanicsScales(1., 1e100), eta=1., reference_viscosity_pa_s=1.) as plan:
            xyz = plan.coordinates('velocity')
            velocity = np.zeros_like(xyz)
            velocity[:, 0] = 1e-70*xyz[:, 2]
            with self.assertRaisesRegex(TectonicsError, 'mechanical work'):
                solve(plan, velocity=velocity)

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


class DirectGmresRegionalExecution3DTests(_RegionalExecutionAssertions, unittest.TestCase):
    """Explicit direct/GMRES controls; changing the default cannot exercise multigrid."""

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

    def test_same_si_problem_under_any_scales_matches_or_refuses(self):
        # A 1 km box, 1e21 Pa s and a 300 N/m3 anomaly with unit scales used to
        # give a GMRES velocity 2.6e-4 away from the direct answer, accepted.
        boundary = pattern()
        boundary['z1'] = ('traction',)*3
        length = 1000.
        def run(scales, method):
            with prepare(cells=(3, 3, 3), lengths=(length,)*3, eta=1e21, boundary=boundary, method=method,
                         scales=scales, reference_viscosity_pa_s=1e21, physical_mean_pressure_pa=None) as plan:
                q = plan.coordinates()
                force = np.zeros(q.shape)
                force[..., 2] = -300.*np.cos(np.pi*q[..., 0]/length)
                return solve(plan, force=force)
        oracle = run(RegionalMechanicsScales(length, 1e-14), 'direct').array('velocity_m_s')
        for scales in (RegionalMechanicsScales(1., 1.), RegionalMechanicsScales(1e5, 1e-9),
                       RegionalMechanicsScales(1e-3, 1e3)):
            for method in ('gmres', 'direct'):
                with self.subTest(scales=scales, method=method):
                    try:
                        result = run(scales, method)
                    except TectonicsError:
                        continue
                    self.assert_gates(result)
                    velocity = result.array('velocity_m_s')
                    self.assertLess(np.max(np.abs(velocity-oracle))/np.max(np.abs(oracle)), 1e-9)

    def test_mis_scaled_solves_never_publish_a_wrong_field(self):
        # Adversarial verification: a combined residual norm let the momentum
        # block go unchecked when continuity dominated, and a residual-absorbing
        # work floor then accepted rigid fields with 225-8210% error.
        closed = pattern()
        length = 1e5
        cases = ((1e-3, 1e-15, 1e30), (1., 1e-9, 1e34), (length, 1e-9, 1e21))
        for kind in ('translation', 'rotation', 'shear'):
            for ls, vs, eta0 in cases:
                with self.subTest(kind=kind, scales=(ls, vs, eta0)), prepare(
                        cells=(3, 3, 3), lengths=(length, 1.3*length, .7*length), eta=1e21, boundary=closed,
                        method='direct', scales=RegionalMechanicsScales(ls, vs), reference_viscosity_pa_s=eta0,
                        physical_mean_pressure_pa=None) as plan:
                    xyz = plan.coordinates('velocity')
                    if kind == 'translation':
                        exact = np.broadcast_to([1e-9, -2e-9, .5e-9], xyz.shape).copy()
                    elif kind == 'rotation':
                        exact = np.cross([1e-14, -2e-14, 3e-14], xyz-[.3*length, .2*length, .1*length])
                    else:
                        exact = np.zeros_like(xyz)
                        exact[:, 0] = 1e-9*xyz[:, 2]/(.7*length)
                    try:
                        result = solve(plan, velocity=exact)
                    except TectonicsError:
                        continue
                    error = np.max(np.abs(result.array('velocity_m_s')-exact))/np.max(np.abs(exact))
                    self.assertLess(error, 1e-8)
                    d = result.descriptor()
                    self.assertLessEqual(max(d['momentum_backward_error'], d['continuity_backward_error']), 2e-9)

    def test_load_dominated_state_resolves_the_small_driving_velocity(self):
        # Verification finding: with rho0*g balanced by pressure, a relative stop
        # on the whole right-hand side left the anomaly-driven velocity inaccurate
        # while every normwise backward error was tiny. Refinement, and a momentum
        # gate against |A||u| plus only the round-off of the balanced terms, now
        # resolve it (rho0 = 3300 and rho0 = 0 give one velocity in exact arithmetic).
        length, gravity = 1e5, 10.
        for name, boundary in (('closed', pattern()), ('open-top', dict(pattern(), z1=('traction',)*3))):
            def run(rho0, method):
                with prepare(cells=(3, 3, 3), lengths=(length,)*3, eta=1e21, boundary=boundary, method=method,
                             scales=RegionalMechanicsScales(length, 1e-9), reference_viscosity_pa_s=1e21,
                             physical_mean_pressure_pa=None) as plan:
                    q = plan.coordinates()
                    force = np.zeros(q.shape)
                    force[..., 2] = -gravity*(rho0+.01*np.cos(np.pi*q[..., 0]/length)*np.cos(np.pi*q[..., 2]/length))
                    return solve(plan, force=force)
            reference = run(0., 'direct').array('velocity_m_s')
            for method in ('gmres', 'direct'):
                with self.subTest(boundary=name, method=method):
                    velocity = run(3300., method).array('velocity_m_s')
                    self.assertLess(np.max(np.abs(velocity-reference))/np.max(np.abs(reference)), 1e-8)

    def _layered_shear(self, contrast, eta0, factor=None):
        """Closed-box shear over a weak layer (1e21 above z = 2/3, 1e21/contrast below)."""
        length, speed, cells = 1e5, 1e-9, (4, 4, 4)
        q = quadrature(cells, (length,)*3)
        eta = np.where(q[..., 2]/length > 2/3, 1e21, 1e21/contrast)*np.ones(27)
        with prepare(cells=cells, lengths=(length,)*3, eta=eta, method='direct',
                     scales=RegionalMechanicsScales(length, speed), reference_viscosity_pa_s=eta0,
                     physical_mean_pressure_pa=None) as plan:
            xyz = plan.coordinates('velocity')
            velocity = np.zeros_like(xyz)
            velocity[:, 0] = speed*xyz[:, 2]/length
            velocity[:, 1] = speed*np.sin(np.pi*xyz[:, 0]/length)*xyz[:, 2]/length
            if factor is not None:
                plan._factor = factor(plan, plan._factor, xyz[plan._free//3, 2] < 2/3*length)
            return solve(plan, velocity=velocity).array('velocity_m_s')

    def test_weak_region_rows_are_judged_by_their_own_magnitudes(self):
        # Verification finding: block errors normalised by the largest row accepted
        # a velocity error whose residual sits on weak-layer momentum rows (2e-5
        # at contrast 1e4, 1e-4 at 1e6). Rows are now judged componentwise: with
        # the refinement correction unavailable a 1e-6 error of that kind is
        # refused (the combined residual, about 1e-10, would pass), and with the
        # correction available it is repaired.
        class Perturbed:
            def __init__(self, plan, real, weak, size, refine):
                self.real, self.weak, self.size, self.refine, self.calls = real, weak, size, refine, 0
                self.free = len(plan._free)
            def solve(self, vector):
                self.calls += 1
                y = self.real.solve(vector)
                if self.calls == 1:
                    # K^-1 e for e = +-1 on the weak layer's momentum rows only.
                    e = np.zeros_like(vector)
                    e[:self.free] = np.where(np.arange(self.free) % 2, 1., -1.)*self.weak
                    d = self.real.solve(e)
                    d /= float(np.max(np.abs(d[:self.free])))
                    return y+self.size*float(np.max(np.abs(y[:self.free])))*d
                if not self.refine:
                    raise TectonicsError('simulated: no refinement correction available')
                return y
        reference = self._layered_shear(1e4, 1e21)
        def error(size, refine):
            u = self._layered_shear(1e4, 1e21, lambda plan, real, weak: Perturbed(plan, real, weak, size, refine))
            return np.max(np.abs(u-reference))/np.max(np.abs(reference))
        self.assertLess(error(0., False), 1e-12)
        with self.assertRaisesRegex(TectonicsError, 'block residual exceeds'):
            error(1e-6, False)
        self.assertLess(error(1e-6, True), 1e-8)

    def test_badly_scaled_contrast_is_refined_not_refused(self):
        # A reference viscosity at the weak end of a 1e5-1e6 contrast gave an
        # accurate direct solution that failed the block gates by round-off; one
        # working-precision refinement step now makes it pass the same gates.
        for contrast in (1e5, 1e6):
            with self.subTest(contrast=contrast):
                reference = self._layered_shear(contrast, 1e21)
                u = self._layered_shear(contrast, 1e21/contrast)
                self.assertLess(np.max(np.abs(u-reference))/np.max(np.abs(reference)), 1e-8)

    def test_unconverged_refinement_correction_is_judged_not_discarded(self):
        # Verification finding: a buoyant weak inclusion (contrast 1e4) in an
        # open-top box was solved by GMRES to rtol but failed the componentwise
        # continuity gate; the refinement correction reached the iteration limit
        # and was thrown away, so a well-scaled problem was refused although the
        # correction passed every gate. It is now kept when it lowers the worst
        # gate ratio, and the published solution still faces every gate.
        length, cells = 1e5, (5, 5, 5)
        q = quadrature(cells, (length,)*3)
        inside = np.sum((q/length-[.5, .5, .4])**2, axis=-1) < .06
        eta = np.where(inside, 1e17, 1e21)
        force = np.zeros(q.shape)
        force[..., 2] = -10.*(3300.-30.*inside)
        def run(method):
            with prepare(cells=cells, lengths=(length,)*3, eta=eta, method=method,
                         boundary=dict(pattern(), z1=('traction',)*3),
                         scales=RegionalMechanicsScales(length, 1e-9), reference_viscosity_pa_s=1e21,
                         physical_mean_pressure_pa=None, budget=WorkBudget(512*1024**2)) as plan:
                return solve(plan, force=force)
        reference = run('direct').array('velocity_m_s')
        result = run('gmres')
        velocity = result.array('velocity_m_s')
        self.assertLess(np.max(np.abs(velocity-reference))/np.max(np.abs(reference)), 1e-8)
        self.assertGreater(result.descriptor()['linear_refinements'], 0)

    def test_declared_mean_pressure_changes_pressure_not_velocity(self):
        # A 3 GPa datum inside the right-hand side dominated every relative
        # target: GMRES velocity moved by 2.5e-7 (1.7e-6 at 10 GPa), accepted.
        length, speed, eta = 1e5, 3e-10, 1e19
        def run(datum, method):
            with prepare(cells=(4, 4, 3), lengths=(length, length, .6*length), eta=eta, method=method,
                         scales=RegionalMechanicsScales(length, speed), reference_viscosity_pa_s=eta,
                         physical_mean_pressure_pa=datum) as plan:
                xyz = plan.coordinates('velocity')
                velocity = np.zeros_like(xyz)
                velocity[:, 0] = speed*xyz[:, 2]/(.6*length)
                velocity[:, 1] = speed*np.sin(np.pi*xyz[:, 0]/length)*xyz[:, 2]/(.6*length)
                return solve(plan, velocity=velocity)
        reference = run(None, 'direct')
        u0 = reference.array('velocity_m_s')
        for datum in (3e9, 1e10):
            for method in ('gmres', 'direct'):
                with self.subTest(datum=datum, method=method):
                    result = run(datum, method)
                    self.assertLess(np.max(np.abs(result.array('velocity_m_s')-u0))/np.max(np.abs(u0)), 1e-9)
                    shift = result.array('physical_pressure_pa')-reference.array('relative_pressure_pa')
                    assert_allclose(shift, datum, rtol=1e-9)


def _process_memory():
    """Operating-system process memory from the benchmark harness (Windows: private commit)."""
    tools = str(Path(__file__).resolve().parents[1]/'tools')
    if tools not in sys.path:
        sys.path.append(tools)
    from benchmark_regional3d_solvers import process_memory
    return process_memory()


_DIRECT_PEAK = '''
import gc, json, sys
sys.path.append(sys.argv[1])
from benchmark_regional3d_solvers import process_memory
from atlas_tectonics.regional_execution import RegionalMechanicsScales
from atlas_tectonics.regional_execution3d import PreparedRegionalStokes3D, SIDES
from atlas_tectonics.resources import WorkBudget
def run(cells, budget):
    with PreparedRegionalStokes3D(cells, (1., 1., 1.), 2., {s: ('velocity',)*3 for s in SIDES},
            scales=RegionalMechanicsScales(1., 1.), reference_viscosity_pa_s=2., frame_id='f', vertical_datum='d',
            material_source='m', physical_mean_pressure_pa=0., method='direct', budget=budget) as plan:
        plan.solve(1., 0., {s: 0. for s in SIDES}, parent_state_id='p', epoch_id='e', time_s=0.,
                   force_source='f', boundary_source='b')
run((2, 2, 2), WorkBudget(2**34))
gc.collect()
before = process_memory()['private_bytes']
budget = WorkBudget(2**34)
run((4, 4, 4), budget)
print(json.dumps([process_memory()['peak_private_bytes']-before, budget.peak_reserved_bytes]))
'''


class FactorAccountingTests(unittest.TestCase):
    """Admitted factor bytes against the storage SuperLU actually commits (1 October 2026)."""
    @unittest.skipUnless(sys.platform == 'win32', 'reads the Windows process private commit')
    def test_ilu_allowance_covers_superlu_working_storage(self):
        # SuperLU commits fill_factor*nnz entries in each of two float64 and two
        # int32 arrays before factoring, 192 bytes per entry of A_f: 157.9 MB at
        # 6^3 free-slip, against the former 160-byte allowance of 137.6 MB. That
        # term is the whole derived bound apart from 1,024 bytes per unknown for
        # SuperLU's O(n) arrays (measured about 60), 5.7 MB here. The commit minus
        # the fill term measured -0.5 to +1.3 MB (heap growth varies by run), so the
        # headroom is 4.4-6.2 MB, 2.7-3.8% of the allowance. The same per-unknown
        # term bounds the commit from below, so the check also establishes the fill
        # term, and the failure message separates the two parts.
        free_slip = {side: tuple('velocity' if axis == 'xyz'.index(side[0]) else 'traction' for axis in range(3))
                     for side in SIDES}
        prepare(method='gmres').close()             # the first factorisation commits one-off process state
        original, seen = regional_execution3d.spilu, {}

        def measured(matrix, **kwargs):
            gc.collect()
            before = _process_memory()['private_bytes']
            factor = original(matrix, **kwargs)
            seen.update(committed=_process_memory()['private_bytes']-before,
                        allowance=regional_execution3d._ilu_allowance(matrix.nnz, matrix.shape[0]),
                        fill=int(24*kwargs['fill_factor']*matrix.nnz), n=matrix.shape[0])
            return factor
        with mock.patch.object(regional_execution3d, 'spilu', measured):
            prepare(cells=(6, 6, 6), boundary=free_slip, method='gmres', budget=WorkBudget(2**31)).close()
        rest = seen['committed']-seen['fill']
        report = 'committed %d B = fill term %d B %+d B; allowance %d B, n %d' % (
            seen['committed'], seen['fill'], rest, seen['allowance'], seen['n'])
        self.assertLessEqual(seen['committed'], seen['allowance'], report)
        self.assertGreaterEqual(rest, seen['fill']-seen['allowance'], report)     # the fill term was observed

    @unittest.skipUnless(sys.platform == 'win32', 'reads the Windows process private commit')
    def test_direct_accounting_covers_its_measured_peak(self):
        # One fresh process, as the benchmark harness measures: peak private commit
        # after a warm-up plan, minus the level before the plan. SuperLU's complete
        # factor commits 720 bytes per entry of K: at 4^3 the plan peaked at 116 MiB
        # against 62 MiB accounted when the allowance was 16 n^2 alone.
        source = Path(regional_execution3d.__file__).resolve().parents[1]
        environment = dict(os.environ, PYTHONPATH=os.pathsep.join((str(source), str(Path(__file__).resolve().parent))))
        done = subprocess.run([sys.executable, '-B', '-c', _DIRECT_PEAK, str(Path(__file__).resolve().parents[1]/'tools')],
                              env=environment, capture_output=True, text=True, timeout=600, check=True)
        measured, accounted = json.loads(done.stdout.strip().splitlines()[-1])
        self.assertLessEqual(measured, accounted)
        self.assertGreater(measured, accounted//4)

    def test_realised_factor_is_checked_without_retained_copies(self):
        # factor.L/U build CSC copies that SciPy keeps with the factor (458 MB at
        # 12^3 lithosphere, never admitted). SuperLU's stored-entry count gives the
        # same after-the-fact check, which still refuses an exceeded allowance.
        class Counted:
            def __init__(self, factor):
                self.nnz, self.shape, self.solve = factor.nnz, factor.shape, factor.solve

            @property
            def L(self):
                raise AssertionError('a factor copy was built')
            U = L
        for method, name, allowance in (('gmres', 'spilu', '_ilu_allowance'), ('direct', 'splu', '_lu_allowance')):
            original = getattr(regional_execution3d, name)
            with self.subTest(method=method), \
                    mock.patch.object(regional_execution3d, name, lambda *a, **k: Counted(original(*a, **k))):
                with prepare(cells=(3, 3, 3), method=method) as plan:
                    self.assertLessEqual(solve(plan, force=1.).descriptor()['linear_relative_residual'], 2e-9)
                budget = WorkBudget(2**30)
                with mock.patch.object(regional_execution3d, allowance, lambda nnz, n: 1024), \
                        self.assertRaisesRegex(MemoryLimitError, 'realised factor exceeded'):
                    prepare(cells=(3, 3, 3), method=method, budget=budget)
                self.assertEqual(budget.reserved_bytes, 0)


    def test_default_budget_refuses_known_overshoot_before_factorisation(self):
        # A 5-cube direct open-top solve previously admitted about 179.5 MiB
        # while committing about 311 MiB on the measured Windows runtime.
        # Refuse before allocating its factor; do not raise the default budget.
        boundary = dict(pattern(), z1=('traction',)*3)
        with mock.patch.object(regional_execution3d, 'splu',
                               side_effect=AssertionError('unadmitted factor was allocated')):
            with self.assertRaises(MemoryLimitError):
                prepare(cells=(5, 5, 5), boundary=boundary, method='direct',
                        physical_mean_pressure_pa=None)
            budget = WorkBudget(256*1024**2)
            with self.assertRaises(MemoryLimitError):
                prepare(cells=(5, 5, 5), boundary=boundary, method='direct',
                        physical_mean_pressure_pa=None, budget=budget)
            self.assertEqual(budget.reserved_bytes, 0)


if __name__ == '__main__':
    unittest.main()
