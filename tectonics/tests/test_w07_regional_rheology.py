"""Focused retained-law regional integration references; no time evolution.
SPDX-License-Identifier: AGPL-3.0-only
"""
from concurrent.futures import CancelledError
from dataclasses import replace
import math
import threading
import unittest

import numpy as np

from atlas_tectonics._validation import TectonicsError
from atlas_tectonics.constitutive import DiffusiveScales, RheologyProfile, reference_rheology
from atlas_tectonics.regional_execution import PreparedRegionalStokes2D, RegionalMechanicsScales
from atlas_tectonics.regional_rheology import solve_regional_rheology, _invariant_sites, _same_state


def scales():
    return DiffusiveScales('explicit SI test', 2., 2., 3., 300., 1000., 1.)


def plan_for_shear(n=8, shear=1., velocity=None):
    pattern = {s: {'u': 'velocity', 'w': 'velocity'} for s in ('left', 'right', 'bottom', 'top')}
    pattern['top']['w'] = 'traction'
    plan = PreparedRegionalStokes2D(n, n, 1., 1., 3., pattern,
        scales=RegionalMechanicsScales(2., .25), frame_id='test', vertical_datum='bottom', material_source='seed')
    values = {}
    for side in pattern:
        _, z = plan.coordinates((side, 'u'))
        values[side] = {'u': shear*z if velocity is None else velocity(z), 'w': -2. if side == 'top' else 0.}
    return plan, values


def request(plan, profile, boundary, temperature=.6, *, n=8, sc=None, **kwargs):
    tc = np.full((n, n), 300.+1000.*temperature)
    tv = np.full((n+1, n+1), 300.+1000.*temperature)
    return solve_regional_rheology(plan, profile, scales() if sc is None else sc, tc, tv,
        np.zeros((n, n+1)), np.zeros((n+1, n)), boundary,
        frame_id='test', epoch_id='steady', time_s=0., thermal_source='explicit stress-site samples',
        material_source='retained-law control', force_source='zero analytic force',
        boundary_source='exact shear trace', **kwargs)


class RegionalRheologyTests(unittest.TestCase):
    def test_current_law_checker_rejects_same_velocity_under_changed_shear_stress(self):
        plan, boundary = plan_for_shear()
        with plan:
            old = plan.solve(np.zeros((8, 9)), np.zeros((9, 8)), boundary,
                frame_id='test', epoch_id='steady', time_s=0., force_source='zero', boundary_source='shear')
            eta_vertex = np.broadcast_to(3.*(1+np.arange(9)[:, None]/8), (9, 9)).copy()
            plan.update_viscosity(np.full((8, 8), 3.), eta_vertex,
                material_source='changed explicit eta', material_sampling='exact point samples')
            published, checked = _same_state(plan, old, None)
            self.assertIsNone(published)
            self.assertFalse(checked['gates_passed'])
            self.assertGreater(checked['momentum_residual'], .01)

    def test_current_law_checker_preserves_reference_pressure_split(self):
        from test_regional_execution import prepare, inputs
        from atlas_tectonics.regional_execution import RegionalReferencePressure
        reference = RegionalReferencePressure(2., 7., 'constant density hydrostatics')
        with prepare('hydrostatic_traction', n=4, reference_pressure=reference) as plan:
            fu, fw, boundary = inputs('hydrostatic_traction', plan)
            law_scales = DiffusiveScales('hydrostatic scales', 3., 3., 1., 300., 1000., 3.)
            result = solve_regional_rheology(plan, reference_rheology('constant'), law_scales,
                np.full((4, 4), 600.), np.full((5, 5), 600.), fu, fw, boundary,
                frame_id='synthetic-x-right-z-up', epoch_id='steady', time_s=0., thermal_source='constant temperature',
                material_source='unit law', force_source='hydrostatic gravity', boundary_source='hydrostatic pressure')
            expected = np.broadcast_to((2+7*(3-(np.arange(4)+.5)*3/4))[:, None], (4, 4))
            np.testing.assert_allclose(result.mechanics.array('physical_pressure_pa'), expected, atol=1e-10)
            np.testing.assert_allclose(result.mechanics.array('u_m_s'), 0., atol=1e-10)
            np.testing.assert_allclose(result.mechanics.array('stress_xx_pa'), -expected, atol=1e-10)

    def test_tosi_homogeneous_shear_preserves_original_norm_scales_and_factor_two(self):
        profile = reference_rheology('tosi-2')
        for shear in (0., 1.):
            plan, boundary = plan_for_shear(shear=shear)
            with plan:
                result = request(plan, profile, boundary)
                # eII=|du/dz|/2 in SI; dimensional rate multiplies t0=2.
                q = math.sqrt(2.)*abs(shear)/2.*scales().time_s
                linear = 1e5**(-.6)
                expected = 3.*2.*linear/(1.+linear*q/(.001*q+1.))
                np.testing.assert_allclose(result.mechanics.array('viscosity_center_pa_s'), expected, rtol=1e-10)
                np.testing.assert_allclose(result.mechanics.array('viscosity_vertex_pa_s'), expected, rtol=1e-10)
                np.testing.assert_allclose(result.mechanics.array('stress_xz_pa'), expected*shear, atol=1e-10)
                np.testing.assert_allclose(result.mechanics.array('physical_pressure_pa'), 2., atol=1e-10)
                self.assertLessEqual(result.descriptor()['viscosity_log_change'], 1e-8)
                self.assertTrue(result.descriptor()['current_law_diagnostics']['gates_passed'])
                self.assertIn('linear_solve_origin', result.mechanics.descriptor())
                self.assertNotIn('linear_residual', result.mechanics.descriptor()['diagnostics'])
                with self.assertRaises(ValueError):
                    result.mechanics.array('viscosity_center_pa_s').setflags(write=True)

    def test_smooth_temperature_shear_matches_integrated_continuum_reference(self):
        profile = RheologyProfile('temperature-shear-exp-v1', 'tosi-linear', 'analytic exponential shear control',
                                   (('contrast_T', math.e), ('contrast_z', 1.)))
        errors = []
        for n in (16, 32):
            exact = lambda z: np.expm1(z)/np.expm1(1.)
            plan, boundary = plan_for_shear(n, velocity=exact)
            with plan:
                tc = np.broadcast_to(300.+1000.*(np.arange(n)[:, None]+.5)/n, (n, n)).copy()
                tv = np.broadcast_to(300.+1000.*np.arange(n+1)[:, None]/n, (n+1, n+1)).copy()
                result = solve_regional_rheology(plan, profile, scales(), tc, tv,
                    np.zeros((n, n+1)), np.zeros((n+1, n)), boundary,
                    frame_id='test', epoch_id='steady', time_s=0., thermal_source='T=z exact Kelvin samples',
                    material_source='analytic exponential law', force_source='zero', boundary_source='exact integrated shear')
                expected = np.broadcast_to(exact((np.arange(n)[:, None]+.5)/n), (n, n+1))
                errors.append(np.linalg.norm(result.mechanics.array('u_m_s')-expected)/np.linalg.norm(expected))
                np.testing.assert_allclose(result.mechanics.array('viscosity_vertex_pa_s'),
                                           3.*np.exp(-(tv-300.)/1000.), rtol=1e-13)
                self.assertEqual(result.descriptor()['iterations'], 1)
        self.assertLess(errors[-1], .01)
        self.assertLess(errors[-1], errors[0])

    def test_bf_fixed_damage_yield_and_no_history_evolution(self):
        profile = RheologyProfile('BF homogeneous explicit variant', 'bf23-memory',
            '10.1029/2023GC011179; disclosed homogeneous test parameters',
            (('E', 2.), ('eta0', 10.), ('a', 2.), ('b', 0.), ('dcrit', 10.),
             ('weakening', .5), ('B', 0.), ('Ed', 0.)))
        damage_c, damage_v = np.full((8, 8), 6.), np.full((9, 9), 6.)
        plan, boundary = plan_for_shear()
        with plan:
            result = request(plan, profile, boundary, temperature=1., damage_center=damage_c, damage_vertex=damage_v)
            # strength=2*(1-.5*6/10)=1.4; rate II=.5*t0=1; eta=1.4/(2*1).
            np.testing.assert_allclose(result.mechanics.array('viscosity_vertex_pa_s'), 3.*.7, atol=1e-10)
            np.testing.assert_allclose(result.mechanics.array('stress_xz_pa'), 2.1, atol=1e-10)
            self.assertFalse(result.descriptor()['damage_evolved'])
            self.assertFalse(result.descriptor()['time_advanced'])
            np.testing.assert_array_equal(damage_c, 6.)
            np.testing.assert_array_equal(damage_v, 6.)

    def test_tensor_reconstruction_is_exact_for_affine_components_including_boundaries(self):
        n = 4
        xc, zc = np.meshgrid((np.arange(n)+.5)/n, (np.arange(n)+.5)/n)
        xv, zv = np.meshgrid(np.arange(n+1)/n, np.arange(n+1)/n)
        exx, ezz, exz = 1+xc+2*zc, 3-2*xc+zc, 2+xv-zv
        c, v = _invariant_sites(exx, ezz, exz)
        np.testing.assert_allclose(c, np.sqrt((exx**2+ezz**2)/2+(2+xc-zc)**2), atol=1e-14)
        np.testing.assert_allclose(v, np.sqrt(((1+xv+2*zv)**2+(3-2*xv+zv)**2)/2+exz**2), atol=1e-14)

    def test_small_spatially_varying_nonlinear_field_passes_current_law_balances(self):
        n = 8
        pattern = {s: {'u': 'velocity' if s in ('left', 'right') else 'traction',
                       'w': 'traction' if s in ('left', 'right') else 'velocity'}
                   for s in ('left', 'right', 'bottom', 'top')}
        with PreparedRegionalStokes2D(n, n, 1., 1., 3., pattern, scales=RegionalMechanicsScales(1., 1.),
                frame_id='test', vertical_datum='bottom', material_source='seed') as plan:
            xc, zc = np.meshgrid((np.arange(n)+.5)/n, (np.arange(n)+.5)/n)
            xv, zv = np.meshgrid(np.arange(n+1)/n, np.arange(n+1)/n)
            xw, zw = np.meshgrid((np.arange(n)+.5)/n, np.arange(n+1)/n)
            thermal = lambda x, z: 300.+1000.*(.6+.1*np.cos(np.pi*x)*np.sin(np.pi*z))
            result = solve_regional_rheology(plan, reference_rheology('tosi-2'), scales(),
                thermal(xc, zc), thermal(xv, zv), np.zeros((n, n+1)), .01*np.sin(np.pi*xw)*np.cos(np.pi*zw),
                {s: {'u': 0., 'w': 0.} for s in pattern}, frame_id='test', epoch_id='steady', time_s=0.,
                thermal_source='explicit smooth temperature', material_source='Tosi2 test',
                force_source='analytic sine body force', boundary_source='free slip')
            self.assertGreater(result.descriptor()['iterations'], 1)
            self.assertTrue(result.descriptor()['current_law_diagnostics']['gates_passed'])
            self.assertGreater(np.max(np.abs(result.mechanics.array('u_m_s'))), 0.)

    def test_refuses_clipping_missing_damage_extrapolation_cancel_and_nonconvergence(self):
        plan, boundary = plan_for_shear()
        with plan:
            with self.assertRaisesRegex(TectonicsError, 'clipping'):
                request(plan, replace(reference_rheology('tosi-2'), viscosity_bounds=(.001, 1.)), boundary)
            with self.assertRaises(TectonicsError):
                request(plan, reference_rheology('bf23-memory'), boundary)
            with self.assertRaisesRegex(TectonicsError, 'extrapolation'):
                request(plan, reference_rheology('tosi-2'), boundary, temperature=1.1)
            event = threading.Event(); event.set()
            with self.assertRaises(CancelledError):
                request(plan, reference_rheology('tosi-2'), boundary, cancel=event)
            with self.assertRaisesRegex(TectonicsError, 'did not converge'):
                request(plan, reference_rheology('tosi-2'), boundary, max_iterations=1)
            self.assertEqual(request(plan, reference_rheology('tosi-2'), boundary).descriptor()['iterations'], 2)


if __name__ == '__main__':
    unittest.main()
