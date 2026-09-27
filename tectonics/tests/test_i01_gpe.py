"""Focused dry-column/GPE connection controls.
SPDX-License-Identifier: AGPL-3.0-only
"""
from dataclasses import replace
import json
from pathlib import Path
import sys
import unittest
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"tools"))
import check_i01_gpe as g


class ColumnTests(unittest.TestCase):
    def setUp(self):
        self.d = g.Datum(3300*9.81*200e3, -200e3)

    def test_airy_surface_gpe_pressure_and_separate_material(self):
        h = np.array([[30e3], [40e3]])
        r = g.columns(self.d, h, 2800., 0., 1000., 1000.)
        np.testing.assert_allclose(r["surface_elevation_m"], (1-2800/3300)*h[:, 0], rtol=1e-13)
        np.testing.assert_allclose(r["gpe_anomaly_j_m2"], .5*9.81*2800*(1-2800/3300)*h[:, 0]**2, rtol=1e-13)
        np.testing.assert_allclose(r["pressure_residual_pa"], 0., atol=1e-6)
        np.testing.assert_array_equal(r["reference_rock_mass_kg_m2"], 2800*h[:, 0])

    def test_linear_density_moment_matches_independent_quadrature(self):
        h, rho, alpha, tb, tt = 40e3, 2900., 3e-5, 1500., 300.
        r = g.columns(self.d, [[h]], rho, alpha, tb, tt)
        x, w = np.polynomial.legendre.leggauss(4)
        z = (x+1)*h/2
        density = rho*(1-alpha*(tb+(tt-tb)*z/h-self.d.reference_temperature_k))
        mass = np.sum(w*density)*h/2
        moment = np.sum(w*z*density)*h/2
        expected = 9.81*(moment-mass*mass/(2*3300))
        self.assertAlmostEqual(r["gpe_anomaly_j_m2"][0]/expected, 1., places=13)

    def test_layer_split_and_order(self):
        whole = g.columns(self.d, [[40e3]], 2900., 3e-5, 1500., 300.)
        split = g.columns(self.d, [[20e3, 20e3]], 2900., 3e-5, [[1500., 900.]], [[900., 300.]])
        for key in whole:
            np.testing.assert_allclose(split[key], whole[key], rtol=2e-14, atol=1e-6)
        inverted = g.columns(self.d, [[40e3]], 2900., 3e-5, 300., 1500.)
        self.assertNotEqual(whole["gpe_anomaly_j_m2"][0], inverted["gpe_anomaly_j_m2"][0])

    def test_datum_translation_and_deeper_common_mantle(self):
        args = ([[30e3], [40e3]], 2800., 0., 1000., 1000.)
        r = g.columns(self.d, *args)
        translated = g.columns(replace(self.d, compensation_elevation_m=-199900.), *args)
        deeper = g.columns(replace(self.d, pressure_pa=self.d.pressure_pa+3300*9.81*1e5,
                                  compensation_elevation_m=-300000.), *args)
        np.testing.assert_allclose(translated["surface_elevation_m"], r["surface_elevation_m"]+100.)
        np.testing.assert_allclose(deeper["surface_elevation_m"], r["surface_elevation_m"])
        for other in (translated, deeper):
            np.testing.assert_array_equal(other["gpe_anomaly_j_m2"], r["gpe_anomaly_j_m2"])

    def test_heating_changes_support_not_reference_material_inventory(self):
        cold = g.columns(self.d, [[40e3]], 2900., 3e-5, 1000., 300.)
        hot = g.columns(self.d, [[40e3]], 2900., 3e-5, 1100., 400.)
        self.assertGreater(hot["surface_elevation_m"][0], cold["surface_elevation_m"][0])
        self.assertGreater(hot["gpe_anomaly_j_m2"][0], cold["gpe_anomaly_j_m2"][0])
        np.testing.assert_array_equal(hot["reference_rock_mass_kg_m2"], cold["reference_rock_mass_kg_m2"])
        self.assertLess(hot["effective_rock_load_kg_m2"][0], cold["effective_rock_load_kg_m2"][0])

    def test_invalid_and_unsupported_columns(self):
        for h, rho, alpha, tb, tt in (([[0]], 2800, 0, 1, 1), ([[1]], -1, 0, 1, 1),
            ([[1]], 2800, -1, 1, 1), ([[1]], 2800, 1, 1000, 1),
            ([[1]], 2800, 0, 0, 1), ([[1]], True, 0, 1, 1),
            ([[1]], 2800, 0, np.nan, 1), ([[300e3]], 2800, 0, 1, 1),
            ([[1, 1]], [2800, 2800, 2800], 0, 1, 1)):
            with self.subTest(h=h, rho=rho, tb=tb), self.assertRaises(ValueError):
                g.columns(self.d, h, rho, alpha, tb, tt)
        for kwargs in (dict(pressure_pa=True), dict(gravity_m_s2=-1), dict(compensation_elevation_m=np.inf)):
            with self.assertRaises(ValueError):
                replace(self.d, **kwargs)


class SphericalTests(unittest.TestCase):
    def test_constant_gpe_zero_force_and_immutable_setup(self):
        n = np.eye(3)
        s = g.SphericalStencil(n, .05)
        n[:] = 0
        np.testing.assert_array_equal(s.directions, np.eye(3))
        np.testing.assert_array_equal(s.traction(np.full((3, 2, 2), 1e12), radius_m=6e6, reduction=1.), np.zeros((3, 3)))
        with self.assertRaises(ValueError):
            s.sample_directions.setflags(write=True)

    def test_gradient_sign_poles_and_rotation_covariance(self):
        n = np.vstack((np.eye(3), -np.eye(3)))
        a = np.array([1., 2., 3.])
        s = g.SphericalStencil(n, .04)
        sample = s.sample_directions@a*1e12
        t = s.traction(sample, radius_m=6e6, reduction=.7)
        expected = -.7e12/6e6*(a-(n@a)[:, None]*n)*np.sin(.04)/.04
        np.testing.assert_allclose(t, expected, rtol=2e-13, atol=1e-8)
        q, _ = np.linalg.qr(np.array([[1., 2., 3.], [2., -1., .3], [1., .1, .9]]))
        rotated = g.SphericalStencil(n@q.T, .04)
        rt = rotated.traction(rotated.sample_directions@(q@a)*1e12, radius_m=6e6, reduction=.7)
        np.testing.assert_allclose(rt, t@q.T, rtol=2e-13, atol=1e-8)

    def test_invalid_stencil_and_traction(self):
        for n, step in (([[0., 0., 0.]], .01), (np.eye(3), 0.), (np.eye(3), .2), (np.eye(3), True)):
            with self.assertRaises(ValueError):
                g.SphericalStencil(n, step)
        s = g.SphericalStencil(np.eye(3), .01)
        for values, radius, gamma in ((np.zeros((3, 2)), 1., 1.), (np.full((3, 2, 2), np.nan), 1., 1.),
                                      (np.zeros((3, 2, 2)), -1., 1.), (np.zeros((3, 2, 2)), 1., True)):
            with self.assertRaises(ValueError):
                s.traction(values, radius_m=radius, reduction=gamma)

    def test_actual_column_to_retained_torque_connection(self):
        spec = json.loads((g.ROOT/"cases/i01_gpe_v1.json").read_text())
        r = g.sphere_control(spec, 4)
        self.assertAlmostEqual(r["relative_rotation_error"], r["expected_central_difference_error"], places=12)
        self.assertLess(r["work_relative"], 1e-12)
        self.assertLess(r["global_torque_cancellation_relative"], 1e-12)


if __name__ == "__main__":
    unittest.main()
