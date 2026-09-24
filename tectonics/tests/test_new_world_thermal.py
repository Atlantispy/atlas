"""Focused independent analytic checks for bounded initial temperature tables."""
from dataclasses import FrozenInstanceError
import importlib.util
import math
from pathlib import Path
import sys
import unittest
from unittest import mock

import numpy as np

from atlas_tectonics.resources import MemoryLimitError, WorkBudget


TOOL = Path(__file__).resolve().parents[1] / 'tools/new_world_thermal.py'
spec = importlib.util.spec_from_file_location('new_world_thermal_under_test', TOOL)
thermal = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = thermal
spec.loader.exec_module(thermal)


def independent_ocean(depths, age_s, length=125000.0, surface=273.15, base=1573.15):
    """64 Fourier modes; at the tested >=10 Ma, omitted terms are <1e-350."""
    x = np.asarray(depths) / length
    terms = [x]
    for mode in range(1, 65):
        decay = math.exp(-mode * mode * math.pi ** 2 * 1.0e-6 * age_s / length ** 2)
        terms.append(2.0 / (mode * math.pi) * np.sin(mode * math.pi * x) * decay)
    return surface + (base - surface) * np.sum(terms, axis=0)


class NewWorldThermalTests(unittest.TestCase):
    def test_homogeneous_conduction_matches_independent_quadratic(self):
        length, k, heat, surface, base = 100000.0, 3.0, 1.0e-6, 300.0, 1300.0
        result = thermal.continental_profile([0.0, length], [k], [heat], surface, base)
        z = np.asarray(result.depths_m)
        expected = surface + (base - surface) * z / length + heat * z * (length - z) / (2.0 * k)
        np.testing.assert_allclose(result.temperatures_k, expected, rtol=0.0, atol=5e-12)
        midpoints = 0.5 * (z[1:] + z[:-1])
        exact = surface + (base - surface) * midpoints / length + heat * midpoints * (length - midpoints) / (2.0 * k)
        error = np.max(np.abs(np.interp(midpoints, z, result.temperatures_k) - exact))
        self.assertLessEqual(error, result.max_error_bound_k + 5e-12)
        self.assertLessEqual(result.max_error_bound_k, 0.05)

    def test_layer_interfaces_flux_continuity_and_heat_balance(self):
        boundaries = (0.0, 10000.0, 40000.0, 120000.0)
        conductivity = (3.0, 2.5, 3.3)
        heating = (1.5e-6, 0.5e-6, 0.0)
        result = thermal.continental_profile(boundaries, conductivity, heating)
        z = np.asarray(result.depths_m)
        temperature = np.asarray(result.temperatures_k)
        recovered_fluxes = []
        for index, (k, heat) in enumerate(zip(conductivity, heating)):
            first = result.depths_m.index(boundaries[index])
            last = result.depths_m.index(boundaries[index + 1])
            # On a quadratic, secant gradient is the exact midpoint derivative.
            top_flux = k * (temperature[first + 1] - temperature[first]) / (z[first + 1] - z[first]) + heat * (z[first + 1] - z[first]) / 2.0
            base_flux = k * (temperature[last] - temperature[last - 1]) / (z[last] - z[last - 1]) - heat * (z[last] - z[last - 1]) / 2.0
            recovered_fluxes.append((top_flux, base_flux))
        for left, right in zip(recovered_fluxes, recovered_fluxes[1:]):
            self.assertAlmostEqual(left[1], right[0], places=12)
        total_heat = sum(heat * (b - a) for heat, a, b in zip(heating, boundaries, boundaries[1:]))
        self.assertAlmostEqual(recovered_fluxes[0][0] - recovered_fluxes[-1][1], total_heat, places=12)
        descriptor = result.descriptor()
        self.assertAlmostEqual(descriptor['upward_interface_heat_flux_w_m2'][0], recovered_fluxes[0][0], places=12)
        self.assertLess(abs(descriptor['computed_base_temperature_residual_k']), 1e-10)
        # No-heating layered solution is linear in accumulated thermal resistance.
        linear = thermal.continental_profile(boundaries, conductivity, (0.0, 0.0, 0.0))
        self.assertEqual(linear.depths_m, boundaries)
        resistance = np.r_[0.0, np.cumsum(np.diff(boundaries) / conductivity)]
        np.testing.assert_allclose(linear.temperatures_k, 273.15 + 1300.0 * resistance / resistance[-1], atol=1e-12)

    def test_ocean_endpoints_and_error_against_independent_fourier_solution(self):
        for age_ma in (10.0, 120.0):
            with self.subTest(age_ma=age_ma):
                age = age_ma * thermal.SECONDS_PER_MA
                result = thermal.ocean_profile(age)
                self.assertEqual((result.depths_m[0], result.depths_m[-1]), (0.0, 125000.0))
                self.assertEqual((result.temperatures_k[0], result.temperatures_k[-1]), (273.15, 1573.15))
                np.testing.assert_allclose(result.temperatures_k, independent_ocean(result.depths_m, age), atol=2e-12, rtol=0.0)
                midpoints = 0.5 * (np.asarray(result.depths_m[1:]) + result.depths_m[:-1])
                samples = np.r_[np.linspace(0.0, 125000.0, 2001), midpoints]
                error = np.max(np.abs(np.interp(samples, result.depths_m, result.temperatures_k) - independent_ocean(samples, age)))
                self.assertLessEqual(error, result.max_error_bound_k + 2e-12)
                self.assertLessEqual(result.max_error_bound_k, 0.05)
                self.assertLessEqual(len(result.depths_m), thermal.MAX_NODES)

    def test_ocean_cools_with_elapsed_thermal_age(self):
        values = []
        for age_ma in (10.0, 60.0, 120.0):
            result = thermal.ocean_profile(age_ma * thermal.SECONDS_PER_MA)
            values.append(np.interp([10000.0, 30000.0, 80000.0], result.depths_m, result.temperatures_k))
        self.assertTrue(np.all(np.diff(values, axis=0) < 0.0))
        self.assertFalse(result.descriptor()['formation_age_inferred'])
        self.assertFalse(result.descriptor()['spherical_volume_mean'])

    def test_returned_profile_is_immutable_and_descriptor_detached(self):
        result = thermal.ocean_profile(thermal.OCEAN_MIN_AGE_S, surface_k=1000.0, base_k=1000.0)
        self.assertEqual(result.depths_m, (0.0, 125000.0))
        self.assertEqual(result.temperatures_k, (1000.0, 1000.0))
        self.assertEqual(result.max_error_bound_k, 0.0)
        with self.assertRaises(FrozenInstanceError):
            result.max_error_bound_k = 1.0
        descriptor = result.descriptor()
        descriptor['sources'].clear()
        self.assertTrue(result.descriptor()['sources'])
        self.assertEqual(len(thermal.source_hash()), 64)
        with mock.patch.object(thermal, '_SOURCE_SHA256', 'changed'), self.assertRaisesRegex(ValueError, 'SOURCE_MISMATCH'):
            thermal.source_hash()
        with mock.patch.object(thermal, '_SOURCE_PATH') as path:
            path.read_bytes.side_effect = OSError('unavailable')
            with self.assertRaisesRegex(ValueError, 'SOURCE_MISMATCH'):
                thermal.source_hash()

    def test_invalid_inputs_and_node_limit_refuse_without_relaxing_bound(self):
        for age in (True, '10', float('nan'), float('inf'), 0.0,
                    9.0 * thermal.SECONDS_PER_MA, 121.0 * thermal.SECONDS_PER_MA):
            with self.subTest(age=age), self.assertRaises(ValueError):
                thermal.ocean_profile(age)
        for kwargs in ({'thickness_m': 0.0}, {'thickness_m': float('inf')},
                       {'surface_k': -1.0}, {'base_k': 200.0}, {'base_k': True},
                       {'thickness_m': 1e12}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                thermal.ocean_profile(thermal.OCEAN_MIN_AGE_S, **kwargs)
        for boundaries, conductivity, heating in (
                ([1.0, 2.0], [3.0], [0.0]), ([0.0, 0.0], [3.0], [0.0]),
                ([0.0, 1.0], [0.0], [0.0]), ([0.0, 1.0], [3.0], [-1.0]),
                ([0.0, 1.0], [3.0, 4.0], [0.0]), ([0.0, 1.0], [True], [0.0]),
                ([0.0, float('nan')], [3.0], [0.0]),
                ([0.0, 1e5], [3.0], [1e3]), ([0.0, 1.0], [float('inf')], [0.0])):
            with self.subTest(inputs=(boundaries, conductivity, heating)), self.assertRaises(ValueError):
                thermal.continental_profile(boundaries, conductivity, heating)
        with self.assertRaises(ValueError):
            thermal.continental_profile((x for x in [0.0, 1.0]), [3.0], [0.0])
        with self.assertRaises(MemoryLimitError):
            thermal.ocean_profile(thermal.OCEAN_MIN_AGE_S, budget=WorkBudget(128))


if __name__ == '__main__':
    unittest.main()
