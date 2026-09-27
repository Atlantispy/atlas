"""Focused guards for the I01 thermal/material-history prototype; no native import.
SPDX-License-Identifier: AGPL-3.0-only
"""
import copy
import math
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import numpy as np
from threadpoolctl import threadpool_limits

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"tools"))
import check_i01_thermal as c

SPEC = c.load_case()


class Base(unittest.TestCase):
    def setUp(self):
        self.lease = threadpool_limits(limits=1, user_api="blas")
        self.addCleanup(self.lease.restore_original_limits)
        mech = SPEC["mechanics"]
        self.grid = c.strength.PressurePlane(9, mech["domain_m"], mech["physical_length_m"])


class RepresentationTests(Base):
    def test_affine_eulerian_advection_refused_translation_exact(self):
        grid = c.strength.PressurePlane(17, 1e5, 5e3)
        field = np.cos(2*np.pi*(2*grid.x-grid.y)/grid.length)
        with self.assertRaisesRegex(ValueError, "not periodic"):
            c.eulerian_transport(grid, field, [[0., 1e-14], [0., 0.]], [0., 0.], 1.)
        shifted = c.observe_translated(grid, field, np.array([3., 1.])*grid.length/17)
        np.testing.assert_allclose(shifted, np.roll(field, shift=(1, 3), axis=(0, 1)), atol=2e-15, rtol=0)

    def test_spectral_resample_band_limited_oracle_and_refusals(self):
        coarse, fine = c.strength.PressurePlane(17, 1e5, 5e3), c.strength.PressurePlane(33, 1e5, 5e3)
        wave = lambda g: np.sin(2*np.pi*(3*g.x+2*g.y)/g.length)+.5*np.cos(2*np.pi*(5*g.y-g.x)/g.length)
        np.testing.assert_allclose(c.spectral_resample(wave(coarse), 33), wave(fine), atol=1e-13, rtol=0)
        for cells in (15, 32):
            with self.assertRaises(ValueError):
                c.spectral_resample(wave(coarse), cells)

    def test_displacement_gradient_norm(self):
        rotation = np.array([[0., -.03], [.03, 0.]])[:, :, None, None]*np.ones((1, 1, 2, 2))
        np.testing.assert_allclose(c.max_singular(rotation), .03, rtol=1e-14)
        stretch = np.array([[.02, 0.], [0., -.02]])[:, :, None, None]*np.ones((1, 1, 2, 2))
        np.testing.assert_allclose(c.max_singular(stretch), .02, rtol=1e-14)

    def test_strict_case_refuses_unadmitted_laws(self):
        for path, value in ((("history", "healing_per_s"), 1e-15), (("thermal", "plastic_heat_fraction"), -.1),
                            (("representation", "mean_spin_per_s"), 1e-15),
                            (("representation", "max_displacement_gradient"), .2)):
            bad = copy.deepcopy(SPEC); bad[path[0]][path[1]] = value
            with self.subTest(path=path), self.assertRaises(ValueError):
                c.validate_case(bad)
        extra = copy.deepcopy(SPEC); extra["pore_pressure_law"] = "drained"
        with self.assertRaises(ValueError):
            c.validate_case(extra)

    def test_declared_representation_and_nested_laws_are_enforced(self):
        for section, name, value in (("representation", "coordinates", "Eulerian"),
                                     ("representation", "affine_mean_velocity", "advect fields"),
                                     ("mechanics", "elastic_modulus_Pa", 1e11),
                                     ("mechanics", "pore_pressure_law", "drained")):
            bad = copy.deepcopy(SPEC); bad[section][name] = value
            with self.subTest(name=name), self.assertRaises(ValueError):
                c.validate_case(bad)

    def test_direct_evolution_validates_before_solving(self):
        t, h = np.full((9, 9), 1000.), np.full((9, 9), .03)
        for section, name, value in (("history", "healing_per_s", 1e-15),
                                     ("representation", "mean_spin_per_s", 1e-15),
                                     ("representation", "max_displacement_gradient", .2),
                                     ("thermal", "plastic_heat_fraction", 1.1)):
            bad = copy.deepcopy(SPEC); bad[section][name] = value
            with self.subTest(name=name), patch.object(
                    c, "evaluate", side_effect=AssertionError("unexpected mechanical solve")) as solve:
                with self.assertRaises(ValueError):
                    c.evolve(self.grid, bad, 1, .001, t, h)
                solve.assert_not_called()


class ThermalTests(Base):
    def test_phi_functions_continuous_and_exact_at_zero(self):
        phi1, phi2 = c.phi_functions(np.array([0., -1e-2*(1-1e-12), -1e-2, -1e-8, -3.]))
        self.assertEqual((phi1[0], phi2[0]), (1., .5))
        self.assertAlmostEqual(phi2[1]/phi2[2], 1., places=12)
        self.assertAlmostEqual(phi2[3], .5-1e-8/6, places=15)
        self.assertAlmostEqual(phi1[4], -math.expm1(-3.)/3, places=15)
        with self.assertRaises(ValueError):
            c.phi_functions(np.array([1e-9]))

    def test_exact_diffusion_and_trapezoidal_mean(self):
        grid = c.strength.PressurePlane(17, 1e5, 5e3)
        k2 = (2*np.pi/grid.length)**2*5
        field = 1000.+4*np.cos(2*np.pi*(2*grid.x+grid.y)/grid.length)
        stepper = c.ThermalStepper(grid, 1e-6, 1e12)
        zero = np.zeros_like(field)
        out = stepper.correct(stepper.predict(field, zero), zero, zero)
        exact = 1000.+4*np.exp(-1e-6*k2*1e12)*np.cos(2*np.pi*(2*grid.x+grid.y)/grid.length)
        np.testing.assert_allclose(out, exact, atol=1e-12, rtol=0)
        a, b = np.full_like(field, 1e-13), np.full_like(field, 3e-13)
        mean = stepper.correct(stepper.predict(field, a), a, b).mean()
        self.assertAlmostEqual(float(mean)-1000., .5e12*(1e-13+3e-13), places=12)


class CouplingTests(Base):
    def test_power_split_is_total_dissipation_once(self):
        t, h = np.full((9, 9), 1000.), np.full((9, 9), .03)
        full = c.evaluate(self.grid, t, h, SPEC, (1., 1.))
        half = c.evaluate(self.grid, t, h, SPEC, (1., .5))
        self.assertLess(full["split"], 1e-14)
        np.testing.assert_allclose(half["heat"]+half["stored"], full["heat"], rtol=1e-14)
        self.assertGreater(float(half["stored"].min()), 0.)
        self.assertAlmostEqual(float(full["heat"].mean())/full["macro_work"], 1., places=12)

    def test_filtered_history_never_written_back(self):
        grid = c.strength.PressurePlane(17, 1e5, 5e3)
        history = .06*np.exp(-(grid.x**2+grid.y**2)/7500.**2)
        before = history.copy()
        cohesion, smoothed = c.cohesion_from_history(grid, history, SPEC["mechanics"])
        np.testing.assert_array_equal(history, before)
        self.assertLess(float(smoothed.max()), float(history.max()))
        # The same physical seed is under-resolved on 9 cells: refused, not clipped.
        coarse = .06*np.exp(-(self.grid.x**2+self.grid.y**2)/7500.**2)
        with self.assertRaisesRegex(RuntimeError, "unresolved"):
            c.cohesion_from_history(self.grid, coarse, SPEC["mechanics"])

    def test_homogeneous_state_matches_independent_scalar_oracle(self):
        t, h = np.full((9, 9), 1000.), np.full((9, 9), .03)
        out = c.evolve(self.grid, SPEC, 8, .02, t, h)
        rise, gain = c.homogeneous_oracle(SPEC, 1000., .03, .02)
        self.assertLess(c.relative_change(out["mean_temperature_rise_K"], rise), 1e-6)
        self.assertLess(c.relative_change(out["mean_history_increment"], gain), 1e-6)
        self.assertLess(out["energy_balance_relative"], 1e-8)
        self.assertEqual(float(np.ptp(out["_history"])), 0.)

    def test_subyield_history_unchanged_and_viscous_heat_remains(self):
        spec = copy.deepcopy(SPEC); spec["mechanics"]["imposed_engineering_rate_scaled"] = [.1, 0.]
        t, h = np.full((9, 9), 1000.), np.full((9, 9), .03)
        out = c.evolve(self.grid, spec, 4, .01, t, h)
        np.testing.assert_array_equal(out["_history"], h)
        self.assertGreater(out["mean_temperature_rise_K"], 0.)

    def test_refusals_do_not_commit_or_accept_bad_input(self):
        grid = c.strength.PressurePlane(17, 1e5, 5e3)
        t, h = c.initial_fields(grid, SPEC)
        out = c.evolve(grid, SPEC, 16, .3, t, h)
        self.assertEqual(out["status"], "REFUSED_SMALL_STRAIN")
        self.assertLess(out["accepted_steps"], 16)
        self.assertLessEqual(out["max_displacement_gradient"], SPEC["representation"]["max_displacement_gradient"])
        self.assertLess(out["energy_balance_relative"], 1e-8)
        hot = c.evolve(grid, SPEC, 2, .3, t, h)
        self.assertEqual((hot["status"], hot["accepted_steps"]), ("REFUSED_TEMPERATURE_STEP", 0))
        self.assertEqual(hot["accounts"]["macro_work_J_m3"], 0.)
        for steps in (0, 257, 2.):
            with self.assertRaises(ValueError):
                c.evolve(grid, SPEC, steps, .01, t, h)
        with self.assertRaises(ValueError):
            c.evolve(grid, SPEC, 2, .01, t, -h)
        with self.assertRaises(ValueError):
            c.evolve(grid, SPEC, 2, .01, t[:, :3], h)


if __name__ == "__main__":
    unittest.main()
