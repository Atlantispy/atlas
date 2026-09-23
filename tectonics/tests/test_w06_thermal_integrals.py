"""Independent age/depth controls for W06's thermal distribution adapter."""
from concurrent.futures import CancelledError
from dataclasses import replace
import math
import threading
import unittest
from unittest.mock import patch

import numpy as np
from numpy.testing import assert_allclose, assert_array_equal
from scipy.integrate import quad

from atlas_tectonics._validation import TectonicsError
from atlas_tectonics.parameters import PlateCoolingParameters, ThermalParameters
from atlas_tectonics.plate_cooling import finite_plate_temperature, plate_cooling_heat
from atlas_tectonics.resources import MemoryLimitError, WorkBudget
from atlas_tectonics.spreading_integrals import spreading_thermal_means


MYR = 1e6*31557600.
PLATE = PlateCoolingParameters(
    ThermalParameters('w06-test', 'synthetic frozen W06 inputs', 273.15, 1573.15, 1e-6),
    100000., 3.3)
EDGES = np.array([0., 7000., 100000.])
UNIT = PlateCoolingParameters(ThermalParameters('unit', 'analytic control', 0., 1., 1.), 1., 1.)


def scalar_deficit(z, age):
    """Separate scalar PDE solution; no production strip or thermal helper."""
    if age == 0:
        return 0.
    if age < .07:
        scale = 2*math.sqrt(age)
        return math.erfc(z/scale)+math.fsum(
            math.erfc((2*n+z)/scale)-math.erfc((2*n-z)/scale) for n in range(1, 7))
    return 1-z-math.fsum(2/(n*math.pi)*math.sin(n*math.pi*z)
                        *math.exp(-n*n*math.pi**2*age) for n in range(1, 101))


def reference_phase_mean(a, b, z0, z1):
    """Independent adaptive age AND depth integration, with tracked uncertainty."""
    largest_depth_error = 0.
    def depth(age):
        nonlocal largest_depth_error
        root = math.sqrt(age)
        points = [(root-z0)/(z1-z0), (4*root-z0)/(z1-z0)]
        value, error = quad(lambda u: scalar_deficit(z0+(z1-z0)*u, age), 0., 1.,
            points=[v for v in points if 0 < v < 1], epsabs=3e-13, epsrel=3e-13, limit=120)
        largest_depth_error = max(largest_depth_error, error)
        return value
    if a == b:
        value = depth(a)
        return value, largest_depth_error
    start = math.sqrt(a); stop = math.sqrt(b); span = (b-a)/(start+stop)
    # QUADPACK can otherwise accept the long panel after a very shallow
    # transition while missing its small tail. Resolve that tail on geometric
    # depth-diffusion scales independently of the production Gauss refinement.
    cuts = []
    for edge in (z0, z1):
        scale = .5*edge
        while scale > 0. and scale < stop:
            cuts.append((scale-start)/span)
            scale *= 2
    switch = (math.sqrt(.07)-start)/span
    value, error = quad(lambda q: depth((start+span*q)**2)*2*(start+span*q)/(start+stop),
        0., 1., points=sorted(set(v for v in (*cuts, switch) if 0 < v < 1)),
        epsabs=3e-13, epsrel=3e-13, limit=120)
    return value, error+largest_depth_error


def scalar_heat(age, side):
    if age == 0:
        return 0.
    if age < .07:
        root = math.sqrt(age)
        def primitive(distance):
            q = distance/root
            return root/math.sqrt(math.pi)*math.exp(-q*q)-distance*math.erfc(q)
        if side == 0:
            return 2*root/math.sqrt(math.pi)+4*math.fsum(primitive(n) for n in range(1, 7))
        return -4*math.fsum(primitive(n+.5) for n in range(6))
    transient = math.fsum(((-1)**n if side else -1)*2/(n*n*math.pi**2)
                         *math.exp(-n*n*math.pi**2*age) for n in range(1, 101))
    return (age+1/3 if side == 0 else -age+1/6)+transient


class W06ThermalIntegralTests(unittest.TestCase):
    def test_zero_equal_ages_and_immutable_broadcast(self):
        age = np.array([0., .001*MYR, 20*MYR, 100*MYR, 200*MYR])[:, None]
        deficit, heat = spreading_thermal_means(age, np.broadcast_to(age, (5, 2)), EDGES, PLATE)
        self.assertEqual(deficit.shape, (5, 2, 2)); self.assertEqual(heat.shape, (5, 2, 2))
        assert_array_equal(deficit[0], 0.); assert_array_equal(heat[0], 0.)
        temperatures = finite_plate_temperature(EDGES[:-1], age, PLATE, cell_bottom_m=EDGES[1:])
        expected = (PLATE.thermal.mantle_temperature_k-temperatures)*np.diff(EDGES)
        assert_allclose(deficit[:, 0], expected, rtol=0., atol=5e-8)
        assert_allclose(heat[:, 0], plate_cooling_heat(age[:, 0], PLATE), rtol=3e-15, atol=.01)
        for array in (deficit, heat):
            with self.assertRaises(ValueError):
                array.setflags(write=True)
        age[:] = 0.
        self.assertGreater(deficit[-1, 0, 0], 0.)

    def test_half_space_uniform_birth_distribution_and_tiny_signal(self):
        # Whole-column young limit is 2*sqrt(kappa/pi)*E[sqrt(age)].
        for lo, hi in ((0., 1e-300), (0., 1e-8), (1e-10, 1e-8)):
            deficit, heat = spreading_thermal_means(lo, hi, [0., .07, 1.], UNIT)
            a = math.sqrt(lo); b = math.sqrt(hi)
            mean_root = (2/3)*(b*b+a*b+a*a)/(a+b)
            expected = 2*mean_root/math.sqrt(math.pi)
            self.assertGreater(deficit[0], 0.)
            assert_allclose(deficit.sum(), expected, rtol=3e-13, atol=0.)
            assert_allclose(heat[0], expected, rtol=3e-13, atol=0.)
            self.assertEqual(heat[1], 0.)
        mean, _ = spreading_thermal_means(0., 1e-4, [0., 1.], UNIT)
        midpoint, _ = spreading_thermal_means(5e-5, 5e-5, [0., 1.], UNIT)
        self.assertGreater(abs(mean[0]-midpoint[0]), 1e-4)

    def test_independent_age_and_depth_quadrature_each_phase_and_heat(self):
        # Includes the W03 method switch and mature 100/200 Myr controls.
        pairs = [(0., .001), (.0001, .02), (0., .063), (.02, .08),
                 (100*MYR*1e-16, 200*MYR*1e-16)]
        edges = [0., .07, 1.]
        for a, b in pairs:
            with self.subTest(interval=(a, b)):
                deficit, heat = spreading_thermal_means(a, b, edges, UNIT)
                for j, (z0, z1) in enumerate(zip(edges[:-1], edges[1:])):
                    expected, error = reference_phase_mean(a, b, z0, z1)
                    self.assertLess(error, 1e-11)
                    assert_allclose(deficit[j]/(z1-z0), expected, rtol=0., atol=2e-11)
                for side in (0, 1):
                    r0 = math.sqrt(a); r1 = math.sqrt(b)
                    expected, error = quad(lambda q: scalar_heat((r0+(r1-r0)*q)**2, side)
                        *2*(r0+(r1-r0)*q)/(r0+r1), 0., 1.,
                        epsabs=2e-13, epsrel=2e-13, limit=120)
                    self.assertLess(error, 1e-11)
                    assert_allclose(heat[side], expected, rtol=0., atol=2e-12)
                assert_allclose(deficit.sum(), heat.sum(), rtol=0., atol=2e-13)

    def test_near_coincident_intervals_and_split_additivity(self):
        for age in (1e-12, .0625, .1, 1.):
            upper = np.nextafter(age, math.inf)
            point = spreading_thermal_means(age, age, [0., .07, 1.], UNIT)
            interval = spreading_thermal_means(age, upper, [0., .07, 1.], UNIT)
            for actual, expected in zip(interval, point):
                assert_allclose(actual, expected, rtol=3e-14, atol=1e-15)
        a, mid, b = 0., .041, .2
        whole = spreading_thermal_means(a, b, [0., .07, 1.], UNIT)
        left = spreading_thermal_means(a, mid, [0., .07, 1.], UNIT)
        right = spreading_thermal_means(mid, b, [0., .07, 1.], UNIT)
        for total, first, second in zip(whole, left, right):
            assert_allclose(total, (first*(mid-a)+second*(b-mid))/(b-a), rtol=2e-12, atol=1e-10)

    def test_shallow_phase_transition_is_resolved(self):
        edges = [0., 2e-5, 1.]
        deficit, heat = spreading_thermal_means(0., .0625, edges, UNIT)
        expected, uncertainty = reference_phase_mean(0., .0625, 0., edges[1])
        self.assertLess(uncertainty, 1e-11)
        assert_allclose(deficit[0]/edges[1], expected, rtol=0., atol=2e-11)
        assert_allclose(deficit.sum(), heat.sum(), rtol=0., atol=2e-13)

    def test_refusals_cancellation_budget_and_error_failure(self):
        for a, b, edges in ((-1., 2., EDGES), (2., 1., EDGES), (0., math.inf, EDGES),
                            (0., 1., [1., 100000.]), (0., 1., [0., 7000., 7000., 100000.]),
                            (0., 1., np.linspace(0., 100000., 18))):
            with self.subTest(inputs=(a, b, edges)), self.assertRaises(TectonicsError):
                spreading_thermal_means(a, b, edges, PLATE)
        budget = WorkBudget(1024)
        with self.assertRaises(MemoryLimitError):
            spreading_thermal_means(0., MYR, EDGES, PLATE, budget=budget)
        self.assertEqual(budget.reserved_bytes, 0)
        stop = threading.Event(); stop.set()
        with self.assertRaises(CancelledError):
            spreading_thermal_means(0., MYR, EDGES, PLATE, cancel=stop)
        with patch('atlas_tectonics.spreading_integrals._MAX_DEPTH', 0), \
                patch('atlas_tectonics.spreading_integrals._NORMALISED_TOLERANCE', 1e-30):
            with self.assertRaisesRegex(TectonicsError, 'error bound'):
                spreading_thermal_means(0., .01, [0., .07, 1.], UNIT)
        equal = replace(PLATE, thermal=replace(PLATE.thermal, mantle_temperature_k=273.15))
        deficit, heat = spreading_thermal_means(0., MYR, EDGES, equal)
        assert_array_equal(deficit, 0.); assert_array_equal(heat, 0.)


if __name__ == '__main__':
    unittest.main()
