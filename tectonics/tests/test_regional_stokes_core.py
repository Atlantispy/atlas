"""Focused W07 B00--B05 full-stress MAC checks; no geological defaults.

SPDX-License-Identifier: AGPL-3.0-only
"""
from __future__ import annotations

import unittest
from concurrent.futures import CancelledError

import numpy as np

from atlas_tectonics.regional_stokes import prepare_mac, boundary_coordinates
from w07_reference_fields import boundaries, dimensions, fields


def forces(plan, case):
    (xu, zu), (xw, zw) = plan.force_coordinates()
    return fields(case, xu, zu)[3], fields(case, xw, zw)[4]


def errors(plan, result, case):
    (xu, zu), (xw, zw) = plan.force_coordinates()
    xp, zp = np.meshgrid((np.arange(plan.nx)+.5)*plan.dx,
                         (np.arange(plan.nz)+.5)*plan.dz)
    ue, we, pe = fields(case, xu, zu)[0], fields(case, xw, zw)[1], fields(case, xp, zp)[2]
    qu, qw = np.ones_like(ue), np.ones_like(we)
    qu[:, [0, -1]] = .5
    qw[[0, -1]] = .5
    eu = np.sqrt(np.sum(qu*(result['u']-ue)**2)*plan.volume)
    ew = np.sqrt(np.sum(qw*(result['w']-we)**2)*plan.volume)
    ep = np.sqrt(np.sum((result['p']-pe)**2)*plan.volume)
    velnorm = np.sqrt((np.sum(qu*ue**2)+np.sum(qw*we**2))*plan.volume)
    pnorm = np.sqrt(np.sum(pe**2)*plan.volume)
    return eu, ew, ep, np.hypot(eu, ew)/velnorm if velnorm else 0., ep/pnorm if pnorm else 0.


class RegionalStokesCoreTests(unittest.TestCase):
    def assert_gates(self, result):
        d = result['diagnostics']
        self.assertLessEqual(d['momentum_residual'], 1e-9, d)
        self.assertLessEqual(d['divergence_residual'], 1e-10, d)
        self.assertLessEqual(d['pressure_gauge_residual'], 1e-12, d)
        self.assertLessEqual(d['normalised_work_residual'], 1e-9, d)
        self.assertTrue(d['gates_passed'], d)

    def test_b00_both_pressure_datums_and_boundary_reactions(self):
        for case in ('hydrostatic', 'hydrostatic_traction'):
            for n in (8, 16):
                with self.subTest(case=case, n=n):
                    width, height = dimensions(case)
                    with prepare_mac(n, n, width, height, 1., boundaries(case),
                                     pressure_mean=0. if case == 'hydrostatic' else None) as plan:
                        result = plan.solve(*forces(plan, case))
                        self.assert_gates(result)
                        self.assertLess(max(errors(plan, result, case)[:3]), 1e-9)
                        for side in ('left', 'right', 'bottom', 'top'):
                            comp = 'u' if side in ('left', 'right') else 'w'
                            x, z = boundary_coordinates(n, n, width, height, side, comp)
                            sign = -1. if side in ('left', 'bottom') else 1.
                            np.testing.assert_allclose(result['boundary_tractions'][side][comp],
                                                       -sign*fields(case, x, z)[2], atol=1e-9, rtol=0.)

    def test_b03_affine_extension_translation_and_boundary_work(self):
        for case in ('extension', 'translated_extension'):
            for nx, nz in ((8, 4), (16, 8)):
                with self.subTest(case=case, nx=nx):
                    with prepare_mac(nx, nz, 2., 1., 1., boundaries(case), pressure_mean=0.) as plan:
                        result = plan.solve(*forces(plan, case))
                        self.assert_gates(result)
                        self.assertLess(max(errors(plan, result, case)[:3]), 1e-9)
                        np.testing.assert_allclose(result['tau_xx'], 2., atol=1e-9, rtol=0.)
                        np.testing.assert_allclose(result['tau_zz'], -2., atol=1e-9, rtol=0.)
                        np.testing.assert_allclose(result['tau_xz'], 0., atol=1e-9, rtol=0.)
                        self.assertAlmostEqual(result['diagnostics']['dissipation'], 8., delta=1e-9)
                        self.assertAlmostEqual(result['diagnostics']['total_boundary_work'], 8., delta=1e-9)
                        self.assertLess(np.linalg.norm(result['diagnostics']['net_force']), 1e-9)
                        self.assertLess(abs(result['diagnostics']['net_torque']), 1e-9)

    def test_b04_full_top_traction_couette(self):
        for n in (8, 16, 32):
            with self.subTest(n=n), prepare_mac(n, n, 1., 1., 1., boundaries('couette')) as plan:
                result = plan.solve(*forces(plan, 'couette'))
                self.assert_gates(result)
                self.assertLess(max(errors(plan, result, 'couette')[:3]), 1e-9)
                np.testing.assert_allclose(result['tau_xz'], 1., atol=1e-9, rtol=0.)
                np.testing.assert_allclose(result['sigma_yy'], -2., atol=1e-9, rtol=0.)
                self.assertAlmostEqual(result['diagnostics']['dissipation'], 1., delta=1e-9)
                self.assertAlmostEqual(result['diagnostics']['total_boundary_work'], 1., delta=1e-9)

    def test_b01_retained_free_slip_convergence(self):
        collected = []
        for n in (8, 16, 32):
            with prepare_mac(n, n, 1., 1., 1., boundaries('free_slip'), pressure_mean=0.) as plan:
                result = plan.solve(*forces(plan, 'free_slip'))
                self.assert_gates(result)
                collected.append(errors(plan, result, 'free_slip')[:3])
        for coarse, fine in zip(collected[:-1], collected[1:]):
            for ratio in np.asarray(coarse)/fine:
                self.assertGreater(ratio, 3.7)
                self.assertLess(ratio, 4.6)
        self.assertLess(collected[-1][0], 8e-5)
        self.assertLess(collected[-1][1], 8e-5)
        self.assertLess(collected[-1][2], 5e-4)

    def test_b02_independent_polynomial_vortex_convergence(self):
        collected = []
        for n in (16, 32, 64):
            with prepare_mac(n, n, 1., 1., 1., boundaries('vortex'), pressure_mean=0.) as plan:
                result = plan.solve(*forces(plan, 'vortex'))
                self.assert_gates(result)
                collected.append(errors(plan, result, 'vortex')[3:])
                self.assertLess(plan.retained_nbytes, 128*1024**2)
        self.assertLess(collected[-1][0], .01)
        self.assertLess(collected[-1][1], .01)
        for coarse, fine in zip(collected[:-1], collected[1:]):
            self.assertGreaterEqual(coarse[0]/fine[0], 3.2)
            self.assertGreaterEqual(coarse[1]/fine[1], 3.2)

    def test_b01_rectangular_free_slip_convergence(self):
        def analytic(x, z):
            kx, kz, a, b = np.pi/3., np.pi, .05, .3
            u, w = a*kz*np.sin(kx*x)*np.cos(kz*z), -a*kx*np.cos(kx*x)*np.sin(kz*z)
            p = b*np.cos(2*kx*x)*np.cos(kz*z)
            return (u, w, p, (kx*kx+kz*kz)*u-2*kx*b*np.sin(2*kx*x)*np.cos(kz*z),
                    (kx*kx+kz*kz)*w-kz*b*np.cos(2*kx*x)*np.sin(kz*z))
        bc = {s: {'u': ('velocity', 0.) if s in ('left', 'right') else ('traction', 0.),
                  'w': ('traction', 0.) if s in ('left', 'right') else ('velocity', 0.)}
              for s in ('left', 'right', 'bottom', 'top')}
        collected = []
        for n in (8, 16, 32):
            with prepare_mac(2*n, n, 3., 1., 1., bc, pressure_mean=0.) as plan:
                (xu, zu), (xw, zw) = plan.force_coordinates()
                xp, zp = np.meshgrid((np.arange(2*n)+.5)*plan.dx, (np.arange(n)+.5)*plan.dz)
                result = plan.solve(analytic(xu, zu)[3], analytic(xw, zw)[4])
                self.assert_gates(result)
                collected.append([np.sqrt(np.mean((result[key]-target)**2)) for key, target in
                                  (('u', analytic(xu, zu)[0]), ('w', analytic(xw, zw)[1]), ('p', analytic(xp, zp)[2]))])
        for coarse, fine in zip(collected[:-1], collected[1:]):
            np.testing.assert_array_less(3.7, np.asarray(coarse)/fine)

    def test_b05_rigid_rotation_traction_null_modes_and_checkerboard(self):
        all_traction = {s: {'u': ('traction', 0.), 'w': ('traction', 0.)}
                        for s in ('left', 'right', 'bottom', 'top')}
        with self.assertRaisesRegex(ValueError, 'rigid'):
            prepare_mac(4, 4, 1., 1., 1., all_traction)
        for n in (4, 8):
            with prepare_mac(n, n, 1., 1., 1., all_traction,
                             rigid_constraints='zero-mean-translation-rotation') as plan:
                zero_u, zero_w = np.zeros((n, n+1)), np.zeros((n+1, n))
                self.assertEqual(plan.rigid_modes, 3)
                result = plan.solve(zero_u, zero_w)
                self.assert_gates(result)
                self.assertEqual(np.count_nonzero(result['velocity_vector']), 0)
                with self.assertRaisesRegex(ValueError, 'force/torque'):
                    plan.solve(zero_u+1., zero_w)
                torque = {s: dict(v) for s, v in all_traction.items()}
                torque['top']['u'], torque['bottom']['u'] = ('traction', 1.), ('traction', -1.)
                with self.assertRaisesRegex(ValueError, 'force/torque'):
                    plan.solve(zero_u, zero_w, boundaries=torque)
                strain = {s: dict(v) for s, v in all_traction.items()}
                strain['left']['u'], strain['right']['u'] = ('traction', -2.), ('traction', 2.)
                strain['bottom']['w'], strain['top']['w'] = ('traction', 2.), ('traction', -2.)
                strained = plan.solve(zero_u, zero_w, boundaries=strain)
                self.assert_gates(strained)
                (xu, zu), (xw, zw) = plan.force_coordinates()
                np.testing.assert_allclose(strained['u'], xu-.5, atol=1e-9, rtol=0.)
                np.testing.assert_allclose(strained['w'], -(zw-.5), atol=1e-9, rtol=0.)
                np.testing.assert_allclose(strained['p'], 0., atol=1e-9, rtol=0.)
                self.assertAlmostEqual(strained['diagnostics']['dissipation'], 4., delta=1e-9)
                checker = (-1.)**np.indices((n, n)).sum(axis=0)
                altered = plan.evaluate(result['velocity_vector'], checker, zero_u, zero_w)
                self.assertGreater(altered['diagnostics']['momentum_residual'], .1)
            with prepare_mac(n, n, 1., 1., 1., boundaries('rotation'), pressure_mean=0.) as plan:
                result = plan.solve(*forces(plan, 'rotation'))
                self.assert_gates(result)
                self.assertLess(max(np.max(np.abs(result[key])) for key in ('exx', 'ezz', 'exz')), 1e-9)
                self.assertLess(abs(result['diagnostics']['dissipation']), 1e-9)

    def test_reuse_direct_oracle_and_reevaluation(self):
        args = (8, 8, 1., 1., 1., boundaries('vortex'))
        with prepare_mac(*args, pressure_mean=0.) as iterative, prepare_mac(*args, pressure_mean=0., method='direct') as direct:
            loads = forces(iterative, 'vortex')
            a, b = iterative.solve(*loads), direct.solve(*loads)
            np.testing.assert_allclose(a['velocity_vector'], b['velocity_vector'], rtol=1e-9, atol=1e-11)
            np.testing.assert_allclose(a['p'], b['p'], rtol=1e-9, atol=1e-11)
            repeated = iterative.solve(*loads)
            np.testing.assert_array_equal(a['velocity_vector'], repeated['velocity_vector'])
            checked = iterative.evaluate(a['velocity_vector'], a['p'], *loads)
            np.testing.assert_array_equal(a['u'], checked['u'])
            self.assert_gates(checked)
            damaged = a['velocity_vector'].copy()
            damaged[iterative._iu[4, 4]] += .01
            self.assertFalse(iterative.evaluate(damaged, a['p'], *loads)['diagnostics']['gates_passed'])
            altered = {s: dict(v) for s, v in boundaries('vortex').items()}
            altered['top']['w'] = ('traction', 0.)
            with self.assertRaisesRegex(ValueError, 'type cannot change'):
                iterative.solve(*loads, boundaries=altered)

    def test_invalid_flux_corners_gauges_cancellation_and_close(self):
        bc = boundaries('extension')
        bc['right']['u'] = ('velocity', 2.)
        # Change neighbouring corner values too, so the failure is flux itself.
        for side in ('bottom', 'top'):
            bc[side]['u'] = ('velocity', lambda x, z: 1.5*x-1.)
        with self.assertRaisesRegex(ValueError, 'flux'):
            prepare_mac(8, 4, 2., 1., 1., bc, pressure_mean=0.)
        bc = boundaries('extension')
        bc['top']['u'] = ('velocity', 0.)
        with self.assertRaisesRegex(ValueError, 'corner'):
            prepare_mac(8, 4, 2., 1., 1., bc, pressure_mean=0.)
        with self.assertRaisesRegex(ValueError, 'explicit finite pressure mean'):
            prepare_mac(4, 4, 1., 1., 1., boundaries('vortex'))
        with self.assertRaisesRegex(ValueError, 'extra gauge'):
            prepare_mac(4, 4, 1., 1., 1., boundaries('couette'), pressure_mean=0.)
        with self.assertRaisesRegex(CancelledError, 'cancelled'):
            prepare_mac(4, 4, 1., 1., 1., boundaries('vortex'), pressure_mean=0., cancel=lambda: True)
        plan = prepare_mac(8, 8, 1., 1., 1., boundaries('vortex'), pressure_mean=0.)
        calls = 0
        def cancel_during_iteration():
            nonlocal calls
            calls += 1
            return calls >= 3
        with self.assertRaisesRegex(CancelledError, 'cancelled'):
            plan.solve(*forces(plan, 'vortex'), cancel=cancel_during_iteration)
        self.assert_gates(plan.solve(*forces(plan, 'vortex')))
        plan.close()
        with self.assertRaisesRegex(RuntimeError, 'closed'):
            plan.solve(np.zeros((8, 9)), np.zeros((9, 8)))


if __name__ == '__main__':
    unittest.main()
