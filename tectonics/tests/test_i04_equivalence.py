"""I04 Part A: package reproductions of the retained I01 helpers equal the tools (R4-8, no tool moved).

The tools stay byte-unchanged and are imported here only, as other I01 tests do; production code never imports
them. Equal inputs must give bitwise-equal outputs and the same refusals.
"""
from pathlib import Path
import math
import sys
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
import check_i01_closures as closures                       # noqa: E402
import check_i01_gpe as gpe                                 # noqa: E402

from atlas_tectonics import integration_driving as D       # noqa: E402


CASE_DATUM = dict(pressure_pa=6474600000., compensation_elevation_m=-200000., mantle_density_kg_m3=3300.,
                  gravity_m_s2=9.81, reference_temperature_k=293.15)   # cases/i01_gpe_v1.json datum


def both(fields=CASE_DATUM):
    return gpe.Datum(**fields), D.Datum(**fields)


class ColumnParity(unittest.TestCase):
    def assert_same(self, *inputs, fields=CASE_DATUM):
        tool, package = both(fields)
        expected = gpe.columns(tool, *inputs)
        actual = D.columns(package, *inputs)
        self.assertEqual(set(expected), set(actual))
        for name in expected:
            self.assertTrue(np.array_equal(expected[name], actual[name]), name)

    def test_retained_control_columns(self):
        # The retained exact control's own column field at order 4 (tools/check_i01_gpe.py sphere_control).
        n, _ = gpe._quadrature(4)
        stencil = gpe.SphericalStencil(n, math.pi/32)
        x = stencil.sample_directions.reshape(-1, 3)[:, 0]
        h = np.sqrt(35000.**2+4e8*x)[:, None]
        self.assert_same(h, 2800., 0., 1000., 1000.)

    def test_layered_thermal_columns(self):
        rng = np.random.default_rng(20261003)
        h = rng.uniform(1e3, 2.5e4, size=(257, 7))  # at most 175 km: positive mantle fill
        rho = rng.uniform(2600., 3300., size=h.shape)
        alpha = rng.uniform(0., 3.5e-5, size=h.shape)
        tb = rng.uniform(300., 1600., size=h.shape)
        tt = rng.uniform(280., 1500., size=h.shape)
        self.assert_same(h, rho, alpha, tb, tt)

    def test_broadcast_and_translated_datum(self):
        h = np.broadcast_to(np.array([60e3, 20e3, 15e3]), (64, 3)).copy()
        self.assert_same(h, [3250., 2900., 2700.], 3e-5, [1400., 900., 600.], [900., 600., 293.15],
                         fields=dict(CASE_DATUM, compensation_elevation_m=-150000.))

    def test_same_refusals(self):
        tool, package = both()
        good = np.full((2, 2), 1e4)
        cases = [(np.zeros((2, 2)), 2800., 0., 1000., 1000.),
                 (good, 2800., 1e-3, 1000., 1000.),                  # anomaly beyond 0.1
                 (np.full((1, 1), 3e5), 3300., 0., 1000., 1000.),   # negative fill
                 (good, True, 0., 1000., 1000.),
                 (good, np.nan, 0., 1000., 1000.),
                 (good, np.ones((3, 3)), 0., 1000., 1000.),
                 (good, -1., 0., 1000., 1000.)]
        for inputs in cases:
            with self.subTest(inputs=str(inputs[0].shape)):
                with self.assertRaises(ValueError) as expected:
                    gpe.columns(tool, *inputs)
                with self.assertRaises(ValueError) as actual:
                    D.columns(package, *inputs)
                if inputs[1] is not None and np.shape(inputs[1]) == (3, 3):
                    # Recorded deviation: a broadcast mismatch is a named refusal, not numpy's own message.
                    self.assertIn('broadcast', str(actual.exception))
                else:
                    self.assertEqual(str(actual.exception), str(expected.exception))
        for bad in (dict(CASE_DATUM, pressure_pa=0.), dict(CASE_DATUM, gravity_m_s2=float('nan')),
                    dict(CASE_DATUM, mantle_density_kg_m3=True)):
            with self.assertRaises(ValueError) as expected:
                gpe.Datum(**bad)
            with self.assertRaises(ValueError) as actual:
                D.Datum(**bad)
            self.assertEqual(str(actual.exception), str(expected.exception))


class SolveParity(unittest.TestCase):
    def control_matrix(self):
        radius, drag, edge_drag = 6_371_000.0, 6.25e14, 1e21
        north = radius / math.sqrt(3) * np.array([[a, b, 1.0] for a in (-1., 1.) for b in (-1., 1.)])
        basal = closures.drag_matrix(north, np.full(4, 2 * math.pi * radius**2 / 4), drag)
        angle = np.arange(8) * 2 * math.pi / 8
        equator = radius * np.column_stack((np.cos(angle), np.sin(angle), np.zeros(8)))
        edge = closures.drag_matrix(equator, np.full(8, 2 * math.pi * radius / 8), edge_drag)
        return np.block([[basal + edge, -edge], [-edge, basal + edge]])

    def test_bitwise_omega(self):
        rng = np.random.default_rng(41)
        systems = [(self.control_matrix(), np.r_[[1e25, -2e25, 3e25], [-1e25, 2e25, -3e25]])]
        for n in (3, 6, 12, 36):
            a = rng.normal(size=(n, n))
            systems.append((a @ a.T + n*np.eye(n), rng.normal(size=n)))
        for matrix, torque in systems:
            expected = closures.solve_torque(matrix, torque)
            actual, residual = D.solve_torque(matrix, torque)
            self.assertTrue(np.array_equal(expected, actual))
            self.assertLessEqual(residual, 1e-11)
        zero, residual = D.solve_torque(systems[0][0], np.zeros(6))
        self.assertTrue(np.all(zero == 0))
        self.assertEqual(residual, 0.)

    def test_same_refusals(self):
        for matrix in (np.zeros((3, 3)), np.diag([1., 1., 0.]), np.eye(3)*np.nan, np.diag([1., 1., 1e-13]),
                       np.array([[1., 1e-3, 0.], [0., 1., 0.], [0., 0., 1.]]), np.eye(2)):
            with self.subTest(matrix=str(matrix.tolist())):
                with self.assertRaises(ValueError) as expected:
                    closures.solve_torque(matrix, np.ones(3))
                with self.assertRaises(ValueError) as actual:
                    D.solve_torque(matrix, np.ones(3))
                self.assertEqual(str(actual.exception), str(expected.exception))


if __name__ == '__main__':
    unittest.main()
