"""Fixed-temperature wall transport: exact fluxes and preserved scalar bounds.

SPDX-License-Identifier: AGPL-3.0-only
These local checks do not establish the cause of the mature Tosi discrepancy.
"""
import math
import unittest
import numpy as np
from numpy.testing import assert_array_equal

from atlas_tectonics import PreparedThermochemical2D, ThermochemicalPolicy, CourantLimitError
from atlas_tectonics import _thermochemical_native as native
from atlas_tectonics.thermochemical import _reference_transfers, _Diffusion2D
from atlas_tectonics.thermochemical_execution import _courant_arrays
from thermochemical_fixtures import problem, initial, circulation


def transfers(kernel, q, cx, cz, walls=None):
    fields, nz, nx = q.shape
    fx = np.empty((fields, nz, nx+1))
    fz = np.empty((fields, nz+1, nx))
    kernel(q, cx, cz, fx, fz, walls)
    return fx, fz


class FixedWallTransfers(unittest.TestCase):
    def test_linear_temperature_exact_at_both_wall_adjacent_faces(self):
        for n in (2, 8):
            # Both velocity signs exercise both possible donors, including each
            # boundary row. Cell averages of this linear field equal its centres.
            theta = 2.-(np.arange(n)+.5)/n
            q = np.stack((np.broadcast_to(theta[:, None], (n, 4)),
                          np.broadcast_to(theta[:, None]-1., (n, 4))))
            cx = np.zeros((n, 5)); cz = np.zeros((n+1, 4))
            cz[1:-1] = np.array([.125, -.125, .125, -.125])
            expected = cz[1:-1]*(2.-np.arange(1, n)[:, None]/n)
            legacy = transfers(native.face_transfers, q, cx, cz)
            for kernel in (native.face_transfers, _reference_transfers):
                with self.subTest(n=n, kernel=kernel.__name__):
                    fx, fz = transfers(kernel, q, cx, cz, (2., 1.))
                    assert_array_equal(fz[0, 1:-1], expected)
                    assert_array_equal(fz[1], legacy[1][1])
                    assert_array_equal(fx, legacy[0])
                    assert_array_equal(fz[:, [0, -1]], 0.)
            self.assertNotEqual(legacy[1][0, 1, 0], expected[0, 0])
            self.assertNotEqual(legacy[1][0, -2, 1], expected[-1, 1])

    def test_reflected_ghost_cannot_break_half_courant_bound(self):
        # Unrestricted MC with a reflected ghost would reconstruct .3 from a
        # .1 donor here, invalidating the existing factor-two outgoing bound.
        q = np.array([[[.1, .1], [1., 1.], [.1, .1]],
                      [[.1, .1], [1., 1.], [.1, .1]]])
        cx = np.zeros((3, 3)); cz = np.zeros((4, 2))
        cz[1] = .125; cz[2] = -.125
        for kernel in (native.face_transfers, _reference_transfers):
            with self.subTest(kernel=kernel.__name__):
                _, fz = transfers(kernel, q, cx, cz, (0., 0.))
                assert_array_equal(fz[0, 1], .025)
                assert_array_equal(fz[0, 2], -.025)
                assert_array_equal(fz[1, 1], .0125)
                assert_array_equal(fz[1, 2], -.0125)

    def test_nonlinear_profiles_remain_bounded_conservative_and_match_reference(self):
        p = problem(9); v = circulation(p, .3)
        u, w = v.array('u_m_s'), v.array('w_m_s')
        outgoing = (np.maximum(u[:, 1:], 0.)+np.maximum(-u[:, :-1], 0.)+
                    np.maximum(w[1:], 0.)+np.maximum(-w[:-1], 0.))*9
        dt = .499/float(outgoing.max())
        cx, cz, _, _ = _courant_arrays(p.box, u, w, dt, ThermochemicalPolicy(outgoing_courant=.5))
        rng = np.random.default_rng(731)
        base = rng.random((2, 9, 9))**3
        base[:, 0, ::2] = 0.; base[:, -1, 1::2] = 1.
        for walls in ((0., 1.), (1., 0.), (.2, .8)):
            q = base.copy()
            totals = [math.fsum(field.flat) for field in q]
            for _ in range(20):
                f, g = transfers(native.face_transfers, q, cx, cz, walls)
                a, b = transfers(_reference_transfers, q, cx, cz, walls)
                assert_array_equal(f, a); assert_array_equal(g, b)
                out = np.empty_like(q); native.euler_update(q, f, g, out)
                self.assertGreaterEqual(float(out.min()), -2e-15)
                self.assertLessEqual(float(out.max()), 1.+2e-15)
                q = out
            for field, total in zip(q, totals):
                self.assertLess(abs(math.fsum(field.flat)-total), 2e-14)

    def test_none_preserves_existing_insulated_transport(self):
        q = np.random.default_rng(54).random((2, 5, 4))
        cx = np.full((5, 5), .01); cz = np.full((6, 4), -.02)
        f = np.empty((2, 5, 5)); g = np.empty((2, 6, 4))
        native.face_transfers(q, cx, cz, f, g)
        for kernel in (native.face_transfers, _reference_transfers):
            a, b = transfers(kernel, q, cx, cz, None)
            assert_array_equal(a, f); assert_array_equal(b, g)


class FixedWallStep(unittest.TestCase):
    def test_courant_refusal_identifies_stage_and_actual_limit_without_mutating_state(self):
        p = problem(8); s = initial(p); before = s.array('temperature_k').copy()
        with PreparedThermochemical2D(p) as plan:
            with self.assertRaises(CourantLimitError) as failure:
                plan.advance(s, 5., source='explicit oversized interval', velocity=circulation(p, 1.))
        message = str(failure.exception)
        for text in ('advection RK stage 0', 'outgoing Courant sum', 'dt_s=5',
                     'same-velocity timestep ceiling', 'advisory only', 'no auto-substepping'):
            self.assertIn(text, message)
        assert_array_equal(s.array('temperature_k'), before)

    def test_both_rk_stages_use_fixed_walls_and_return_balanced_native_reference_steps(self):
        p = problem(8); s = initial(p); v = circulation(p, .1); dt = .025
        T, C = s.array('temperature_k'), s.array('composition')
        diffusion = _Diffusion2D(p); source = diffusion.transform(np.zeros_like(T))
        td, _ = diffusion.advance(T, source, dt*.5, None)
        q0 = np.stack((td, C))
        cx, cz, _, _ = _courant_arrays(p.box, v.array('u_m_s'), v.array('w_m_s'), dt, ThermochemicalPolicy())
        f0, g0 = transfers(_reference_transfers, q0, cx, cz, (310., 300.))
        q1 = q0+(f0[:, :, :-1]-f0[:, :, 1:])+(g0[:, :-1]-g0[:, 1:])
        f1, g1 = transfers(_reference_transfers, q1, cx, cz, (310., 300.))
        results = []
        for backend in ('numba', 'reference'):
            with PreparedThermochemical2D(p, backend=backend) as plan:
                result = plan.advance(s, dt, source='fixed-wall reconstruction check', velocity=v)
            assert_array_equal(result.array('flux_x_increment'), .5*f0+.5*f1)
            assert_array_equal(result.array('flux_z_increment'), .5*g0+.5*g1)
            self.assertLess(result.descriptor()['record']['balances']['heat_relative_residual'], 1e-12)
            results.append(result)
        for name in ('temperature_k', 'composition'):
            assert_array_equal(results[0].state.array(name), results[1].state.array(name))


if __name__ == '__main__':
    unittest.main()
