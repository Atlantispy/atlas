"""Independent mechanical oracles for I01 D2 pressure/temperature snapshots.
SPDX-License-Identifier: AGPL-3.0-only
"""
import json
import math
from pathlib import Path
import sys
import unittest

import numpy as np
from threadpoolctl import threadpool_limits

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"tools"))
import check_i01_strength as c

SPEC = json.loads(c.CASE.read_text(encoding="utf-8"))
PARAMS, POLICY = SPEC["parameters"], SPEC["policy"]


class StrengthTests(unittest.TestCase):
    def setUp(self):
        self.grid = c.PressurePlane(17, PARAMS["domain_m"], PARAMS["physical_length_m"])
        self.ones = np.ones((17, 17))
        self.lease = threadpool_limits(limits=1, user_api="blas")
        self.addCleanup(self.lease.restore_original_limits)

    def test_pressure_projector_sign_and_full_momentum(self):
        grid = self.grid
        mx, my = 2, 3
        # Integer periodic phase avoids cancellation in large physical coordinates.
        index = np.arange(grid.n)-(grid.n-1)//2
        phase = (mx*index[None, :]+my*index[:, None]) % grid.n
        wave = np.cos(2*np.pi*phase/grid.n)
        b = np.array([mx*mx-my*my, 2*mx*my])/(mx*mx+my*my)
        a = np.array([-2*mx*my, mx*mx-my*my])/(mx*mx+my*my)
        stress = b[:, None, None]*wave
        np.testing.assert_allclose(grid.pressure(stress), wave, atol=2e-15, rtol=0)
        self.assertLess(c.rms(grid.momentum(stress, wave)), 1e-18)
        self.assertGreater(c.rms(grid.momentum(stress, -wave)), 1e-4)
        np.testing.assert_allclose(grid.pressure(a[:, None, None]*wave), 0, atol=1e-15)
        self.assertGreater(c.rms(grid.momentum(a[:, None, None]*wave, self.ones*0)), 1e-5)

    def test_arrhenius_reference_and_units(self):
        t = np.array([900., 1000., 1100.])
        actual = c.viscosity(t, 10., 1000., 120000.)
        expected = 10*np.exp(120000/8.31446261815324*(1/t-1/1000))
        np.testing.assert_array_equal(actual, expected)
        self.assertEqual(actual[1], 10.)
        self.assertTrue(actual[0] > actual[1] > actual[2])
        np.testing.assert_array_equal(c.viscosity(t, 10., 1000., 0.), 10.)

    def test_effective_pressure_pore_clamp_and_reference(self):
        phi = math.pi/6
        p = np.array([-10., 0., 2.])
        y = c.yield_strength(1., 3., p, 1., phi)
        np.testing.assert_allclose(y, math.cos(phi)+np.array([0., 2., 4.])*math.sin(phi))
        self.assertGreater(c.yield_strength(1., 4., 0., 1., phi), y[1])
        self.assertLess(c.yield_strength(1., 3., 0., 2., phi), y[1])

    def test_homogeneous_yielded_subyield_and_zero_rate(self):
        y = math.cos(math.pi/6)+1.
        for q in (0., .01, 1.):
            out = c.solve(self.grid, self.ones, self.ones*1000., [q, 0.], PARAMS, POLICY)
            exact = 10*q if 10*q <= y else (10*q+10*y)/11
            np.testing.assert_allclose(out["stress"][0], exact, atol=2e-14, rtol=0)
            np.testing.assert_allclose(out["pressure"], 0., atol=2e-14, rtol=0)
            np.testing.assert_allclose(out["g"][0], q, atol=2e-14, rtol=0)
            self.assertAlmostEqual(out["work"], exact*q, places=13)

    def test_manufactured_temperature_pressure_solution(self):
        self.assertTrue(c.manufactured(self.grid, PARAMS, POLICY)["passed"])

    def test_returned_stress_uses_returned_pressure(self):
        temperature, cohesion = c.fixture(self.grid, PARAMS)
        out = c.solve(self.grid, cohesion, temperature, [1., 0.], PARAMS, POLICY)
        y = c.yield_strength(cohesion, 3., out["pressure"], 1., math.pi/6)
        eta = c.viscosity(temperature, 10., 1000., 120000.)
        t = c.base.constitutive(out["g"], y, eta, 1.)[0]
        np.testing.assert_array_equal(out["strength"], y)
        np.testing.assert_array_equal(out["stress"], t)
        self.assertGreater(c.rms(out["pressure"]), .001)
        self.assertGreater(float(np.ptp(out["g"], axis=1).max()), .01)
        self.assertGreater(float(np.ptp(out["g"], axis=2).max()), .01)
        self.assertLess(out["momentum_residual"], POLICY["momentum_relative"])
        self.assertLess(out["work_residual"], POLICY["work_relative"])

    def test_no_friction_matches_original_mechanics(self):
        temperature, cohesion = c.fixture(self.grid, PARAMS)
        params = dict(PARAMS, friction_degrees=0., activation_energy_J_per_mol=0.)
        old_policy = dict(POLICY, projected_force_relative=POLICY["momentum_relative"])
        old = c.base.equilibrium(self.grid, cohesion, [1., 0.], 10., 1., old_policy)
        new = c.solve(self.grid, cohesion, temperature, [1., 0.], params, POLICY)
        np.testing.assert_allclose(new["stress"], old["stress"], atol=2e-10, rtol=0)
        np.testing.assert_allclose(new["g"], old["g"], atol=2e-10, rtol=0)

    def test_warm_initial_is_not_mutated_or_trusted(self):
        temperature, cohesion = c.fixture(self.grid, PARAMS)
        initial = dict(chi=.01*np.cos(self.grid.x/self.grid.length*2*np.pi), pressure=np.zeros_like(cohesion))
        before = {k:v.copy() for k, v in initial.items()}
        out = c.solve(self.grid, cohesion, temperature, [1., 0.], PARAMS, POLICY, initial=initial)
        for key in before:
            np.testing.assert_array_equal(initial[key], before[key])
        self.assertGreater(out["pressure_iterations"], 1)
        initial["pressure"] += 1
        with self.assertRaisesRegex(ValueError, "zero mean"):
            c.solve(self.grid, cohesion, temperature, [1., 0.], PARAMS, POLICY, initial=initial)

    def test_budget_and_small_damping_do_not_fake_convergence(self):
        temperature, cohesion = c.fixture(self.grid, PARAMS)
        with self.assertRaisesRegex(RuntimeError, "budget"):
            c.solve(self.grid, cohesion, temperature, [1., 0.], PARAMS, POLICY, deadline=0.)
        policy = dict(POLICY, max_pressure_iterations=2, pressure_relaxation=1e-15)
        with self.assertRaisesRegex(RuntimeError, "pressure feedback unresolved"):
            c.solve(self.grid, cohesion, temperature, [1., 0.], PARAMS, policy)

    def test_invalid_material_fields_and_policy_refused(self):
        for temp in (0., -273., float("nan"), 1e-300):
            with self.assertRaises(ValueError):
                c.viscosity(temp, 10., 1000., 120000.)
        for phi in (-.1, math.pi/2, float("nan")):
            with self.assertRaises(ValueError):
                c.yield_strength(1., 3., 0., 1., phi)
        for params in (dict(PARAMS, pore_pressure_scaled=-1.), dict(PARAMS, plastic_viscosity_scaled=0.),
                       dict(PARAMS, reference_pressure_scaled=self.ones*3)):
            with self.assertRaises(ValueError):
                c.solve(self.grid, self.ones, self.ones*1000., [1., 0.], params, POLICY)
        with self.assertRaises(ValueError):
            c.solve(self.grid, self.ones[:, :2], self.ones*1000., [1., 0.], PARAMS, POLICY)
        with self.assertRaises(ValueError):
            c.solve(self.grid, self.ones, self.ones*1000., [1., 0.], PARAMS, dict(POLICY, pressure_relaxation=0.))


if __name__ == "__main__":
    unittest.main()
