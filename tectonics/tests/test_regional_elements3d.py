"""Analytical and variational checks for the bounded 3D Q2/Q1 operator.

SPDX-License-Identifier: AGPL-3.0-only
"""
from concurrent.futures import CancelledError
import threading
import unittest

import numpy as np

from atlas_tectonics.regional_elements3d import TaylorHoodBox


class RegionalElements3DTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.box = TaylorHoodBox((2, 3, 2), (2., 3., 4.))

    def test_partition_of_unity_geometry_and_continuous_connectivity(self):
        box = self.box
        self.assertEqual((box.nv, box.np, box.nc), (175, 36, 12))
        values = box.evaluate(np.tile([2., -3., 4.], (box.nv, 1)), np.full(box.np, 7.))
        np.testing.assert_allclose(values["velocity_q"], np.broadcast_to([2., -3., 4.], (12, 27, 3)), atol=3e-15)
        np.testing.assert_allclose(values["gradient_q"], 0., atol=3e-15)
        np.testing.assert_allclose(values["pressure_q"], 7., atol=3e-15)
        self.assertAlmostEqual(float(box.quadrature_weights.sum()*box.nc), 24., places=12)
        self.assertEqual(len(set(box.velocity_cells.ravel())), box.nv)
        self.assertEqual(len(set(box.pressure_cells.ravel())), box.np)
        # Two neighbouring z bricks share nine Q2 nodes and four Q1 nodes.
        self.assertEqual(len(set(box.velocity_cells[0]) & set(box.velocity_cells[1])), 9)
        self.assertEqual(len(set(box.pressure_cells[0]) & set(box.pressure_cells[1])), 4)

    def test_affine_velocity_gradient_and_trilinear_pressure_are_exact(self):
        box = self.box
        h = np.array([[.2, -.7, .3], [.4, -.1, -.8], [.9, .6, .5]])
        offset = np.array([1., -2., .5])
        p = box.pressure_coordinates
        pressure = (1+p[:, 0])*(2-p[:, 1])*(3+p[:, 2])
        values = box.evaluate(box.velocity_coordinates @ h.T+offset, pressure)
        q = box.quadrature_coordinates
        np.testing.assert_allclose(values["velocity_q"], q @ h.T+offset, atol=7e-15)
        np.testing.assert_allclose(values["gradient_q"], np.broadcast_to(h, (box.nc, 27, 3, 3)), atol=6e-15)
        np.testing.assert_allclose(values["pressure_q"], (1+q[..., 0])*(2-q[..., 1])*(3+q[..., 2]), atol=8e-15)

    def test_tensor_quadratic_velocity_and_derivative_exactness(self):
        box = self.box
        x, y, z = box.velocity_coordinates.T
        velocity = np.stack((x*x*y*z, x*y*y*z*z, x*x*y*y*z*z), axis=-1)
        result = box.evaluate(velocity, np.zeros(box.np))
        x, y, z = np.moveaxis(box.quadrature_coordinates, -1, 0)
        expected_v = np.stack((x*x*y*z, x*y*y*z*z, x*x*y*y*z*z), axis=-1)
        expected_g = np.stack((np.stack((2*x*y*z, x*x*z, x*x*y), axis=-1),
                               np.stack((y*y*z*z, 2*x*y*z*z, 2*x*y*y*z), axis=-1),
                               np.stack((2*x*y*y*z*z, 2*x*x*y*z*z, 2*x*x*y*y*z), axis=-1)), axis=-2)
        np.testing.assert_allclose(result["velocity_q"], expected_v, atol=3e-13, rtol=2e-15)
        np.testing.assert_allclose(result["gradient_q"], expected_g, atol=8e-13, rtol=5e-14)

    def test_affine_full_symmetric_stress_energy_bilinear_and_divergence_sign(self):
        box = self.box
        eta = 2.3
        a, b, weights, mass = box.assemble(np.full((box.nc, 27), eta))
        h = np.array([[.2, -.7, .3], [.4, -.1, -.8], [.9, .6, .5]])
        k = np.array([[-.4, .8, .1], [.6, .3, .7], [-.2, -.5, .9]])
        u = (box.velocity_coordinates @ h.T).ravel()
        v = (box.velocity_coordinates @ k.T).ravel()
        e, d = (h+h.T)/2, (k+k.T)/2
        self.assertAlmostEqual(float(u @ (a @ u)), 24.*2*eta*np.sum(e*e), delta=2e-11)
        self.assertAlmostEqual(float(v @ (a @ u)), 24.*2*eta*np.sum(e*d), delta=2e-11)
        np.testing.assert_allclose(b @ u, -np.trace(h)*weights, atol=3e-14)
        # Each Q1 node's squared basis integrates to cell volume/27.
        counts = np.bincount(box.pressure_cells.ravel(), minlength=box.np)
        np.testing.assert_allclose(weights, counts*2./8, atol=2e-15)
        np.testing.assert_allclose(mass, counts*2./(27*eta), atol=2e-16)
        rotation = np.array([[0., -3., 2.], [3., 0., -1.], [-2., 1., 0.]])
        rigid = (box.velocity_coordinates @ rotation.T + [2., 3., -1.]).ravel()
        np.testing.assert_allclose(a @ rigid, 0., atol=2e-13)

    def test_variable_viscosity_symmetry_and_quadrature_energy(self):
        box = self.box
        q = box.quadrature_coordinates
        eta = 1.1+q[..., 0]**2+.3*q[..., 1]+.2*np.sin(q[..., 2])
        a, _, _, _ = box.assemble(eta)
        difference = a-a.T
        self.assertLess(np.max(np.abs(difference.data), initial=0.), 1e-14)
        rng = np.random.default_rng(9081)
        velocity = rng.normal(size=(box.nv, 3))
        grad = box.evaluate(velocity, np.zeros(box.np))["gradient_q"]
        strain = .5*(grad+grad.swapaxes(-1, -2))
        expected = np.sum(2*eta*np.sum(strain*strain, axis=(-1, -2))*box.quadrature_weights)
        self.assertAlmostEqual(float(velocity.ravel() @ (a @ velocity.ravel())), expected, delta=2e-10)

    def test_inverse_viscosity_mass_with_linear_reciprocal(self):
        box = self.box
        q = box.quadrature_coordinates
        reciprocal = 1+.2*q[..., 0]+.3*q[..., 1]+.4*q[..., 2]
        _, _, _, mass = box.assemble(1/reciprocal)
        # Sum of local Q1 squares has even symmetry about each cell centre;
        # the affine reciprocal therefore integrates at its volume mean.
        centre = np.asarray(box.lengths)/2
        expected = (8/27)*24*(1+centre @ np.array([.2, .3, .4]))
        self.assertAlmostEqual(float(mass.sum()), expected, places=12)

    def test_body_and_extra_stress_work_and_skew_independence(self):
        box = self.box
        force = np.array([2., -.5, 1.3])
        stress = np.array([[2., .7, -.4], [.7, -1., .6], [-.4, .6, 3.]])
        h = np.array([[.2, -.7, .3], [.4, -.1, -.8], [.9, .6, .5]])
        offset = np.array([1., -.3, .8])
        u = box.velocity_coordinates @ h.T+offset
        forces = np.broadcast_to(force, (box.nc, 27, 3))
        stresses = np.broadcast_to(stress, (box.nc, 27, 3, 3))
        rhs = box.load(forces, stresses)
        expected = 24*(force @ (h @ (np.asarray(box.lengths)/2)+offset)-np.sum(((h+h.T)/2)*stress))
        self.assertAlmostEqual(float(u.ravel() @ rhs), expected, delta=3e-12)
        np.testing.assert_allclose(rhs.reshape(-1, 3).sum(axis=0), 24*force, atol=4e-14)
        skew = np.array([[0., 2., -.3], [-2., 0., 4.], [.3, -4., 0.]])
        np.testing.assert_allclose(box.load(forces, stresses+skew), rhs, atol=4e-15)

    def test_all_face_traction_resultants_and_affine_work(self):
        box = self.box
        traction = np.array([2., -.3, .7])
        h = np.array([[.2, -.7, .3], [.4, -.1, -.8], [.9, .6, .5]])
        offset = np.array([1., -.3, .8])
        u = box.velocity_coordinates @ h.T+offset
        for axis, label in enumerate("xyz"):
            area = np.prod([box.lengths[i] for i in range(3) if i != axis])
            for high in (0, 1):
                side = f"{label}{high}"
                with self.subTest(side=side):
                    coords = box.boundary_quadrature(side)
                    self.assertEqual(coords.shape, (box.nc//box.cells[axis], 9, 3))
                    np.testing.assert_allclose(coords[..., axis], high*box.lengths[axis], atol=1e-15)
                    rhs = box.integrate_boundary_traction(side, np.broadcast_to(traction, coords.shape))
                    np.testing.assert_allclose(rhs.reshape(-1, 3).sum(axis=0), area*traction, atol=1e-14)
                    centre = np.asarray(box.lengths)/2
                    centre[axis] = high*box.lengths[axis]
                    self.assertAlmostEqual(float(rhs @ u.ravel()), area*(traction @ (h @ centre+offset)), delta=2e-13)
                    off_face = box.velocity_coordinates[:, axis] != high*box.lengths[axis]
                    np.testing.assert_allclose(rhs.reshape(-1, 3)[off_face], 0., atol=0.)

    def test_surface_and_volume_stress_have_exact_weak_balance(self):
        box = self.box
        stress = np.array([[2., .7, -.4], [.7, -1., .6], [-.4, .6, 3.]])
        rhs = box.load(np.zeros((box.nc, 27, 3)), np.broadcast_to(stress, (box.nc, 27, 3, 3)))
        for axis, label in enumerate("xyz"):
            for high in (0, 1):
                side = f"{label}{high}"
                coords = box.boundary_quadrature(side)
                traction = (2*high-1)*stress[:, axis]
                rhs += box.integrate_boundary_traction(side, np.broadcast_to(traction, coords.shape))
        np.testing.assert_allclose(rhs, 0., atol=3e-15)

    def test_polynomial_surface_traction_and_virtual_work(self):
        box = self.box
        x, y, _ = np.moveaxis(box.boundary_quadrature("z1"), -1, 0)
        rhs = box.integrate_boundary_traction("z1", np.stack((x*x, y*y, x*y), axis=-1))
        lx, ly, _ = box.lengths
        expected_resultant = [lx**3*ly/3, lx*ly**3/3, lx**2*ly**2/4]
        np.testing.assert_allclose(rhs.reshape(-1, 3).sum(axis=0), expected_resultant, atol=2e-14)
        x, y, _ = box.velocity_coordinates.T
        virtual_velocity = np.stack((x*y, x*x, y), axis=-1)
        expected_work = lx**4*ly**2/8+lx**3*ly**3/9+lx**2*ly**3/6
        self.assertAlmostEqual(float(rhs @ virtual_velocity.ravel()), expected_work, delta=2e-13)

    def test_inputs_cancellation_and_immutable_reuse(self):
        box = self.box
        for cells in ((1, 2, 2), (25, 2, 2), (2., 2, 2), (True, 2, 2), (2, 2)):
            with self.subTest(cells=cells), self.assertRaises(ValueError):
                TaylorHoodBox(cells)
        for lengths in ((1., 0., 1.), (1., np.nan, 1.), (1., np.inf, 1.),
                        (1e-300,)*3, (1e103,)*3, (1e-200, 1e100, 1e100)):
            with self.subTest(lengths=lengths), self.assertRaises(ValueError):
                TaylorHoodBox(lengths=lengths)
        eta = np.ones((box.nc, 27))
        for bad in (eta[:, :1], eta*0, eta*np.nan, eta*-1, eta+1j):
            with self.assertRaises(ValueError):
                box.assemble(bad)
        event = threading.Event()
        event.set()
        with self.assertRaises(CancelledError):
            box.assemble(eta, cancel=event)
        calls = []
        def cancel_during_assembly():
            calls.append(True)
            return len(calls) == 4
        with self.assertRaises(CancelledError):
            box.assemble(eta, cancel=cancel_during_assembly)
        self.assertEqual(len(calls), 4)
        with self.assertRaises(ValueError):
            box.load(np.zeros((box.nc, 27, 3)), np.zeros((box.nc, 27, 3)))
        with self.assertRaises(ValueError):
            box.evaluate(np.zeros(3*box.nv), np.zeros(box.np))
        with self.assertRaises(ValueError):
            box.boundary_quadrature("left")
        with self.assertRaises(ValueError):
            box.integrate_boundary_traction("x0", np.zeros((1, 9, 3)))
        with self.assertRaises(ValueError):
            box.velocity_coordinates.setflags(write=True)
        _, b, weights, _ = box.assemble(eta)
        original = b.data.copy()
        b.data = np.zeros_like(b.data)
        weights[:] = 0
        _, fresh, fresh_weights, _ = box.assemble(eta)
        np.testing.assert_array_equal(fresh.data, original)
        self.assertGreater(float(fresh_weights.sum()), 0.)


if __name__ == "__main__":
    unittest.main()
