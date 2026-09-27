"""Focused coupled water/plate tests. SPDX-License-Identifier: AGPL-3.0-only"""
from concurrent.futures import CancelledError
from dataclasses import FrozenInstanceError
import importlib.util
import math
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import patch
import numpy as np

SPEC = importlib.util.spec_from_file_location("i01_water_flexure", Path(__file__).resolve().parents[1]/"tools/check_i01_water_flexure.py")
m = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = m
SPEC.loader.exec_module(m)


class WaterFlexureTests(unittest.TestCase):
    def plate(self, thickness=15000., shape=(16, 16)):
        return m.Plate(shape, 600000., 400000., thickness)

    def test_finite_fill_exact_and_cache_invalidated(self):
        bed = np.array([0., 1., 4., 8.])
        level, d, wet, hit = m._fill(bed, 1.)
        self.assertEqual(level, 2.5)
        np.testing.assert_array_equal(d, [2.5, 1.5, 0., 0.])
        self.assertFalse(hit)
        self.assertTrue(m._fill(bed, 1.1, wet)[3])
        self.assertFalse(m._fill(bed, 4., wet)[3])

    def test_zero_water_undefined_level(self):
        p = self.plate()
        bed = np.arange(256.).reshape(p.shape)
        r = p.equilibrium(bed, 0., **m.ARGS, initial_displacement_m=np.ones(p.shape))
        self.assertIsNone(r["sea_level_m"])
        np.testing.assert_array_equal(r["displacement_m"], 0.)
        np.testing.assert_array_equal(r["bed_m"], bed)

    def test_flat_finite_water_not_double_loaded(self):
        p = self.plate()
        h = 100.
        r = p.equilibrium(np.zeros(p.shape), h*p.length_x_m*p.length_y_m, **m.ARGS)
        np.testing.assert_allclose(r["depth_m"], h, rtol=0, atol=1e-10)
        np.testing.assert_allclose(r["displacement_m"], p.density_ratio*h, rtol=0, atol=1e-7)
        self.assertAlmostEqual(r["sea_level_m"], (1-p.density_ratio)*h, places=7)

    def test_airy_limit_partial_wet_analytical(self):
        p = self.plate(0., (4, 4))
        bed = np.tile([-1000., 0., 2000., 3000.], (4, 1))
        h, beta = 500., 1-p.density_ratio
        s = (4*beta*h-1000.)/2  # first two cells wet
        expected_d = np.maximum(s-bed, 0)/beta
        r = p.equilibrium(bed, h*p.length_x_m*p.length_y_m, **m.ARGS)
        self.assertAlmostEqual(r["sea_level_m"], s, places=5)
        np.testing.assert_allclose(r["depth_m"], expected_d, atol=2e-6, rtol=0)
        np.testing.assert_allclose(r["displacement_m"], p.density_ratio*expected_d, atol=2e-6, rtol=0)

    def test_fully_wet_oblique_2d_mode(self):
        p = self.plate()
        y, x = np.indices(p.shape)
        mode = np.cos(2*np.pi*(2*x/p.shape[1]+y/p.shape[0]))
        bed, h = 10.*mode, 1000.
        k2 = (4*np.pi/p.length_x_m)**2+(2*np.pi/p.length_y_m)**2
        lam = p.rigidity_n_m*k2*k2+p.dry_k
        c = p.rho_w_kg_m3*p.gravity_m_s2
        expected = p.density_ratio*h-10.*c/(lam-c)*mode
        r = p.equilibrium(bed, h*p.length_x_m*p.length_y_m, **m.ARGS)
        error = float(np.sqrt(np.mean((r["displacement_m"]-expected)**2)))
        self.assertLessEqual(error, r["rms_iteration_error_estimate_m"]+1e-10)
        np.testing.assert_allclose(r["displacement_m"], expected, atol=2e-6, rtol=0)

    def test_datum_shift_transpose_volume_and_work(self):
        p = self.plate()
        y, x = np.indices(p.shape)
        bed = 400*np.cos(2*np.pi*x/16)+300*np.cos(2*np.pi*y/16)
        volume = 200*p.length_x_m*p.length_y_m
        r = p.equilibrium(bed, volume, **m.ARGS)
        shifted = p.equilibrium(bed+100000., volume, **m.ARGS)
        np.testing.assert_allclose(shifted["depth_m"], r["depth_m"], atol=1e-8, rtol=0)
        self.assertAlmostEqual(shifted["sea_level_m"]-r["sea_level_m"], 100000., places=7)
        swapped = m.Plate((16, 16), p.length_y_m, p.length_x_m, p.elastic_thickness_m)
        transposed = swapped.equilibrium(bed.T, volume, **m.ARGS)
        np.testing.assert_allclose(transposed["displacement_m"].T, r["displacement_m"], atol=1e-8, rtol=0)
        self.assertLess(r["volume_relative_residual"], 1e-11)
        self.assertLess(r["force_relative_residual"], 1e-7)
        self.assertLess(r["virtual_work_relative_residual"], 1e-7)
        self.assertLess(r["mean_subsidence_relative_residual"], 1e-11)
        self.assertAlmostEqual(float(np.mean(r["displacement_m"])), p.density_ratio*200, places=8)

    def test_warm_start_idempotent_and_volume_change(self):
        p = self.plate()
        bed = np.tile(np.linspace(-200., 200., 16), (16, 1))
        v = 100*p.length_x_m*p.length_y_m
        cold = p.equilibrium(bed, v, **m.ARGS)
        warm = p.equilibrium(bed, v, **m.ARGS, initial_displacement_m=cold["displacement_m"])
        np.testing.assert_allclose(cold["displacement_m"], warm["displacement_m"], atol=2e-6, rtol=0)
        changed = p.equilibrium(bed, 2*v, **m.ARGS, initial_displacement_m=cold["displacement_m"])
        fresh = self.plate().equilibrium(bed, 2*v, **m.ARGS)
        np.testing.assert_allclose(changed["displacement_m"], fresh["displacement_m"], atol=2e-6, rtol=0)
        self.assertGreater(changed["sea_level_m"], cold["sea_level_m"])
        with self.assertRaises(FrozenInstanceError):
            p.elastic_thickness_m = 0.
        with self.assertRaises(ValueError):
            p._stiffness.setflags(write=True)

    def test_forebulge_is_not_clipped(self):
        p = self.plate(shape=(64, 64))
        bed = np.full(p.shape, 10000.)
        bed[30:34, 30:34] = -10000.
        r = p.equilibrium(bed, p.length_x_m*p.length_y_m, **m.ARGS)
        self.assertLess(r["displacement_m"].min(), 0.)

    def test_invalid_contract_shape_and_parameters(self):
        p = self.plate()
        for changes in ({"geometry": "sphere"}, {"connectivity": "isolated_lakes"}, {"reuse_wet_set": "yes"}):
            with self.assertRaises(ValueError):
                p.equilibrium(np.zeros(p.shape), 1., **(m.ARGS | changes))
        for value in (True, "1", float("nan"), -1.):
            with self.assertRaises(ValueError):
                p.equilibrium(np.zeros(p.shape), value, **m.ARGS)
        for shape in ((2, 2), (129, 4), (True, 16)):
            with self.assertRaises(ValueError):
                self.plate(shape=shape)
        with self.assertRaises(ValueError):
            p.equilibrium(np.ones((4, 4)), 1., **m.ARGS)
        with self.assertRaises(ValueError):
            m.Plate((4, 4), 1., 1., 1., rho_w_kg_m3=3300.)

    def test_cancellation_and_iteration_refusal(self):
        p = self.plate()
        event = threading.Event()
        event.set()
        with self.assertRaises(CancelledError):
            p.equilibrium(np.zeros(p.shape), 1., **m.ARGS, cancel=event)
        with patch.dict(m.POLICY, {"max_iterations": 1}):
            with self.assertRaises(ValueError):
                p.equilibrium(np.zeros(p.shape), 1e12, **m.ARGS)


if __name__ == "__main__":
    unittest.main()
