"""W07 B08 dry C01 point and regional references; no localisation claim.
SPDX-License-Identifier: AGPL-3.0-only
"""
from concurrent.futures import CancelledError
from dataclasses import replace
import math
import threading
import unittest
from unittest import mock

import numpy as np

from atlas_tectonics._validation import TectonicsError
from atlas_tectonics.regional_execution import (PreparedRegionalStokes2D,
    RegionalMechanicsScales, RegionalReferencePressure)
from atlas_tectonics.regional_strength import (DryStrengthProfile, evaluate_dry_strength,
    solve_regional_strength, _vertices)
from atlas_tectonics.resources import WorkBudget, MemoryLimitError

MEASUREMENTS = []


def profile(**changes):
    p = DryStrengthProfile('B08 synthetic dry C01', 'frozen W07 C01/B08 analytical control',
        2., math.pi/6., 100., (1e-210, 1e210), 0., 0.)
    return replace(p, **changes)


def shear_problem(n=4, rate=1., pressure=10., traction=False, reference=None):
    pattern = {s: {'u': 'velocity', 'w': 'velocity'} for s in ('left', 'right', 'bottom', 'top')}
    if traction:
        pattern['top']['w'] = 'traction'
    plan = PreparedRegionalStokes2D(n, n, 1., 1., 100., pattern,
        scales=RegionalMechanicsScales(2., .25), frame_id='B08', vertical_datum='bottom zero',
        material_source='synthetic creep', physical_mean_pressure_pa=None if traction else pressure,
        reference_pressure=reference)
    boundary = {}
    for side in pattern:
        _, z = plan.coordinates((side, 'u'))
        boundary[side] = {'u': rate*z, 'w': -pressure if side == 'top' and traction else 0.}
    return plan, boundary


def solve(plan, boundary, **kwargs):
    d = plan.descriptor(); n = d['nx']
    request = dict(frame_id='B08', epoch_id='steady', time_s=0., material_source='explicit B08 dry strength',
                   force_source='zero body force', boundary_source='exact homogeneous shear')
    request.update(kwargs)
    result = solve_regional_strength(plan, profile(), np.zeros((n, n+1)), np.zeros((n+1, n)), boundary, **request)
    desc = result.descriptor()
    MEASUREMENTS.append({'n': n, 'iterations': desc['iterations'], 'last': desc['history'][-1],
                         'timings': desc['timings'], 'budget_peak': plan.statistics()['budget']['peak_reserved_bytes']})
    return result


class RegionalStrengthTests(unittest.TestCase):
    def test_b08_material_points_zero_creep_and_yield(self):
        rates = np.array([0., 1e-300, 1e-4, .02, .05, .5, 1e6])
        tau = math.sqrt(3.)+5.
        result = evaluate_dry_strength(profile(), 10., 0., 0., rates)
        expected = np.array([100. if e == 0 else min(100., tau/(2*e)) for e in rates])
        np.testing.assert_allclose(result['viscosity_pa_s'], expected, rtol=1e-13, atol=0.)
        np.testing.assert_allclose(result['yield_stress_pa'], tau, rtol=1e-14)
        np.testing.assert_allclose(result['stress_ii_pa'], 2*expected*rates, rtol=1e-13, atol=0.)
        self.assertEqual(result['viscosity_pa_s'][0], 100.)
        self.assertGreater(result['strain_rate_ii_s_1'][1], 0.)
        with self.assertRaises(TypeError):
            result['viscosity_pa_s'] = np.ones(7)
        with self.assertRaises(ValueError):
            result['viscosity_pa_s'].setflags(write=True)

    def test_full_plane_strain_invariant_and_principal_stress(self):
        result = evaluate_dry_strength(profile(), 10., .3, -.3, .4)
        self.assertAlmostEqual(float(result['strain_rate_ii_s_1']), .5, delta=1e-15)
        self.assertAlmostEqual(float(result['stress_ii_pa']), math.sqrt(3.)+5., delta=1e-13)
        self.assertAlmostEqual(float(result['largest_effective_principal_stress_pa']), math.sqrt(3.)-5., delta=1e-13)
        with self.assertRaisesRegex(TectonicsError, 'isochoric'):
            evaluate_dry_strength(profile(), 10., .3, -.3+1e-9, .4)
        evaluate_dry_strength(profile(), 10., .3, -.3+1e-9, .4, divergence_tolerance_s_1=1.1e-9)

    def test_pressure_tension_validity_and_parameter_refusals(self):
        with self.assertRaisesRegex(TectonicsError, 'negative effective pressure'):
            evaluate_dry_strength(profile(), -1e-20, 0., 0., 0.)
        with self.assertRaisesRegex(TectonicsError, 'tensile'):
            evaluate_dry_strength(profile(), 0., 0., 0., .5)
        allowed = evaluate_dry_strength(profile(tensile_strength_pa=2.), 0., 0., 0., .5)
        self.assertAlmostEqual(float(allowed['largest_effective_principal_stress_pa']), math.sqrt(3.), delta=1e-13)
        with self.assertRaisesRegex(TectonicsError, 'validity'):
            evaluate_dry_strength(profile(viscosity_validity_pa_s=(10., 100.)), 10., 0., 0., 1.)
        for changes in ({'cohesion_pa': 0.}, {'friction_angle_rad': -1.}, {'friction_angle_rad': math.pi/2},
                        {'pore_pressure_pa': 1.}, {'source': ''}, {'viscosity_validity_pa_s': (200., 300.)}):
            with self.subTest(changes=changes), self.assertRaises(TectonicsError):
                profile(**changes)

    def test_scale_safe_trial_stress_and_nonzero_tiny_rate(self):
        p = profile(creep_viscosity_pa_s=1e200)
        yielded = evaluate_dry_strength(p, 10., 0., 0., 1e200)
        self.assertAlmostEqual(float(yielded['stress_ii_pa']), math.sqrt(3.)+5., delta=1e-12)
        low = evaluate_dry_strength(p, 10., 0., 0., 1e-300)
        self.assertEqual(float(low['viscosity_pa_s']), 1e200)
        self.assertAlmostEqual(float(low['stress_ii_pa'])/2e-100, 1., delta=1e-13)

    def test_b08_homogeneous_shear_regional_current_law_and_datum_change(self):
        for n, rate, pressure in ((4, 0., 10.), (4, .001, 10.), (4, 1., 10.), (8, 1., 20.)):
            plan, boundary = shear_problem(n, rate, pressure)
            with plan:
                result = solve(plan, boundary)
                tau = math.sqrt(3.)+pressure/2.
                eta = 100. if rate == 0 else min(100., tau/abs(rate))
                np.testing.assert_allclose(result.mechanics.array('viscosity_center_pa_s'), eta, rtol=1e-10)
                np.testing.assert_allclose(result.mechanics.array('viscosity_vertex_pa_s'), eta, rtol=1e-10)
                np.testing.assert_allclose(result.mechanics.array('physical_pressure_pa'), pressure, atol=1e-9)
                np.testing.assert_allclose(result.mechanics.array('stress_xz_pa'), eta*rate, rtol=1e-10, atol=1e-10)
                self.assertTrue(result.descriptor()['current_law_diagnostics']['gates_passed'])
                self.assertLessEqual(result.descriptor()['viscosity_log_change'], 1e-8)
                self.assertIn('linear_solve_origin', result.mechanics.descriptor())
                self.assertFalse(result.descriptor()['localisation_claim'])
                with self.assertRaises(ValueError):
                    result.mechanics.array('strength_vertex_yield_stress_pa').setflags(write=True)

    def test_algebraic_pressure_offset_same_physical_datum_preserves_strength(self):
        outputs = []
        for background in (0., 3.):
            reference = RegionalReferencePressure(background, 0., 'declared pressure split')
            plan, boundary = shear_problem(4, 1., 10., traction=True, reference=reference)
            with plan:
                outputs.append(solve(plan, boundary))
        for name in ('physical_pressure_pa', 'viscosity_center_pa_s', 'viscosity_vertex_pa_s', 'stress_xz_pa'):
            np.testing.assert_allclose(outputs[0].mechanics.array(name), outputs[1].mechanics.array(name), rtol=1e-10, atol=1e-10)
        np.testing.assert_allclose(outputs[0].mechanics.array('dynamic_pressure_pa')-
                                   outputs[1].mechanics.array('dynamic_pressure_pa'), 3., atol=1e-10)

    def test_pressure_vertex_reconstruction_preserves_affine_fields(self):
        x, z = np.meshgrid((np.arange(4)+.5)/4, (np.arange(3)+.5)/3)
        xv, zv = np.meshgrid(np.arange(5)/4, np.arange(4)/3)
        np.testing.assert_allclose(_vertices(10+2*x-3*z), 10+2*xv-3*zv, atol=1e-14)

    def test_support_source_datum_cancellation_and_nonconvergence_refusals(self):
        oversized = np.broadcast_to(1., (16385,))
        with mock.patch('atlas_tectonics.regional_strength.read_array', side_effect=AssertionError('must not copy')):
            with self.assertRaisesRegex(TectonicsError, '16384'):
                evaluate_dry_strength(profile(), oversized, 0., 0., 0.)
        with self.assertRaises(MemoryLimitError):
            evaluate_dry_strength(profile(), np.full(10, 10.), 0., 0., .5, budget=WorkBudget(10))
        plan, boundary = shear_problem()
        with plan:
            bad = {s: dict(v) for s, v in boundary.items()}
            bad['left']['u'] = oversized
            with mock.patch('atlas_tectonics.regional_strength.read_array', side_effect=AssertionError('must not copy')):
                with self.assertRaisesRegex(TectonicsError, 'supports'):
                    solve(plan, bad)
            with self.assertRaisesRegex(TectonicsError, 'frame'):
                solve(plan, boundary, frame_id='other')
            event = threading.Event(); event.set()
            with self.assertRaises(CancelledError):
                solve(plan, boundary, cancel=event)
            with self.assertRaisesRegex(TectonicsError, 'did not converge'):
                solve(plan, boundary, max_iterations=1)
            solve(plan, boundary)
        pattern = {s: {'u': 'velocity', 'w': 'velocity'} for s in ('left', 'right', 'bottom', 'top')}
        with PreparedRegionalStokes2D(4, 4, 1., 1., 100., pattern, scales=RegionalMechanicsScales(1., 1.),
                frame_id='B08', vertical_datum='bottom', material_source='seed') as unbound:
            with self.assertRaisesRegex(TectonicsError, 'physical pressure'):
                solve(unbound, {s: {'u': 0., 'w': 0.} for s in pattern})


if __name__ == '__main__':
    unittest.main()
