"""Focused independent oracles for the I01 2D prototype.
SPDX-License-Identifier: AGPL-3.0-only
"""
import json
from pathlib import Path
import sys
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"tools"))
import check_i01_fault2d as c

SPEC = json.loads(c.CASE.read_text(encoding="utf-8"))


class PlaneTests(unittest.TestCase):
    def test_helmholtz_constant_and_oblique_mode(self):
        grid = c.PeriodicPlane(33, 1., .05)
        raw = 2+np.cos(2*np.pi*(2*grid.x+3*grid.y))
        expected = 2+(raw-2)/(1+.05**2*(2*np.pi)**2*13)
        np.testing.assert_allclose(grid.smooth(raw), expected, atol=2e-15, rtol=0)
        np.testing.assert_array_equal(grid.smooth(np.full((33, 33), 2.)), 2.)
        self.assertAlmostEqual(float(grid.smooth(raw).mean()), float(raw.mean()), places=14)

    def test_projection_inverse_and_adjoint(self):
        grid = c.PeriodicPlane(17, 1., .05)
        rng = np.random.default_rng(19)
        chi = rng.normal(size=(17, 17)); chi -= chi.mean()
        tensor = rng.normal(size=(2, 17, 17))
        np.testing.assert_allclose(grid.adjoint(grid.project(chi)), chi, atol=3e-15, rtol=0)
        self.assertAlmostEqual(float(np.sum(grid.project(chi)*tensor)),
                               float(np.sum(chi*grid.adjoint(tensor))), places=12)

    def test_analytic_laminates_at_four_angles(self):
        self.assertTrue(c.laminate_control(SPEC)["passed"])

    def test_subyield_uniform_zero_history(self):
        grid = c.PeriodicPlane(17, 1., .05)
        out = c.equilibrium(grid, np.full((17, 17), 20.), [1., 0.], 10., .1, SPEC["policy"])
        np.testing.assert_array_equal(out["stress"][0], 10.)
        np.testing.assert_array_equal(out["plastic"], 0.)
        self.assertEqual(out["work"], 10.)

    def test_constitutive_gradient_and_tangent(self):
        g = np.array([[[.01, 1.]], [[.02, .4]]])
        y = np.ones((1, 2)); dg = np.array([[[.2, -.3]], [[.4, .2]]])
        stress, _, a, b, direction, _ = c.constitutive(g, y, 10., .1)
        h = 1e-6
        plus = c.constitutive(g+h*dg, y, 10., .1)
        minus = c.constitutive(g-h*dg, y, 10., .1)
        np.testing.assert_allclose((plus[-1]-minus[-1])/(2*h), np.sum(stress*dg, axis=0), atol=2e-10)
        exact = b*dg+(a-b)*direction*np.sum(direction*dg, axis=0)
        np.testing.assert_allclose((plus[0]-minus[0])/(2*h), exact, atol=2e-10)

    def test_invalid_support_and_fields(self):
        for n, length, ell in ((16, 1., .1), (257+2, 1., .1), (17, 0., .1), (17, 1., float("nan"))):
            with self.assertRaises(ValueError):
                c.PeriodicPlane(n, length, ell)
        grid = c.PeriodicPlane(17, 1., .05)
        for bad in (-1., float("nan")):
            with self.assertRaises(ValueError):
                c.equilibrium(grid, np.full((17, 17), bad), [1., 0.], 10., .1, SPEC["policy"])
        with self.assertRaises(ValueError):
            c.evolve(17, 257, SPEC)

    def test_deadline_is_a_refusal(self):
        grid = c.PeriodicPlane(17, 1., .05)
        with self.assertRaisesRegex(RuntimeError, "budget"):
            c.equilibrium(grid, np.ones((17, 17)), [1., 0.], 10., .1, SPEC["policy"], deadline=0.)

    def test_seeded_2d_changes_both_fields_and_preserves_inputs(self):
        before = json.dumps(SPEC, sort_keys=True)
        row, field = c.evolve(17, 8, SPEC)
        self.assertGreater(float(np.ptp(field, axis=0).max()), .01)
        self.assertGreater(float(np.ptp(field, axis=1).max()), .01)
        self.assertGreater(row["peak_to_mean"], 1.)
        self.assertLess(row["max_work_residual"], SPEC["policy"]["work_relative"])
        self.assertEqual(json.dumps(SPEC, sort_keys=True), before)


if __name__ == "__main__":
    unittest.main()
