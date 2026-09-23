"""Independent bounded checks of W03 whole-column thermal age changes."""
from concurrent.futures import CancelledError
from dataclasses import replace
import math
import threading
import unittest
from unittest.mock import patch

import numpy as np
from numpy.testing import assert_allclose, assert_array_equal

from atlas_tectonics._validation import TectonicsError
from atlas_tectonics.parameters import PlateCoolingParameters, ThermalParameters
from atlas_tectonics.plate_cooling import finite_plate_temperature
from atlas_tectonics.plate_integrals import plate_cooling_deficit_change
from atlas_tectonics.resources import MemoryLimitError, WorkBudget


P = PlateCoolingParameters(ThermalParameters('integral-test', 'synthetic analytic',
                                             0., 1., 1.), 1., 1.)


def long_mode_deficit(age):
    if age == 0:
        return 0.
    return .5-math.fsum(4/(n*n*math.pi**2)*math.exp(-n*n*math.pi**2*age)
                       for n in range(1, 1000, 2))


class PlateIntegralTests(unittest.TestCase):
    def test_independent_long_modes_and_branch_switch(self):
        ages = np.array([1e-4, .003, .0625, np.nextafter(.0625, 1.), .2, 1., 10.])
        refs = np.array([0., .001, .0625])
        expected = [[long_mode_deficit(a)-long_mode_deficit(b) for b in refs] for a in ages]
        assert_allclose(plate_cooling_deficit_change(ages[:, None], refs, P),
                        expected, rtol=0, atol=4e-16)

    def test_whole_column_matches_true_cell_means_and_refinement(self):
        ages = np.array([0., 1e-5, .03, .0625, .063, .7, 30.])
        reference = .012
        for edges in (np.array([0., 1.]), np.array([0., .001, .08, .3, .9, 1.]),
                      np.linspace(0., 1., 102)):
            now = finite_plate_temperature(edges[:-1], ages[:, None], P,
                                            cell_bottom_m=edges[1:])
            before = finite_plate_temperature(edges[:-1], reference, P,
                                               cell_bottom_m=edges[1:])
            expected = np.sum((before-now)*np.diff(edges), axis=1)
            assert_allclose(plate_cooling_deficit_change(ages, reference, P),
                            expected, rtol=0, atol=5e-16)

    def test_initial_young_and_old_limits(self):
        assert_array_equal(plate_cooling_deficit_change([0., 1e300], 0., P), [0., .5])
        young = np.array([1e-300, 1e-30, 1e-8])
        assert_allclose(plate_cooling_deficit_change(young, 0., P),
                        2*np.sqrt(young/math.pi), rtol=3e-15, atol=0)
        # Temperature offsets cancel; only the prescribed boundary contrast enters.
        shifted = replace(P, thermal=replace(P.thermal, surface_temperature_k=273.,
                                             mantle_temperature_k=1573.))
        assert_allclose(plate_cooling_deficit_change([.01, .5], .002, shifted),
                        1300*plate_cooling_deficit_change([.01, .5], .002, P), rtol=3e-15)

    def test_mature_tiny_increment_does_not_subtract_steady_limits(self):
        reference = 10.
        age = np.nextafter(reference, math.inf)
        value = float(plate_cooling_deficit_change(age, reference, P))
        # Independent derivative limit: correction over one ulp is <1e-13 relative.
        expected = 4*math.exp(-math.pi**2*reference)*(age-reference)
        self.assertGreater(value, 0.)
        assert_allclose(value, expected, rtol=3e-14, atol=0)
        self.assertEqual(long_mode_deficit(age), long_mode_deficit(reference))

    def test_si_scale_and_adjacent_input_ages(self):
        p = replace(P, thickness_m=1e150,
                    thermal=replace(P.thermal, diffusivity_m2_s=1e150),
                    conductivity_w_m_k=1e150)
        assert_allclose(plate_cooling_deficit_change([1e148, 1e150], 2e148, p),
                        plate_cooling_deficit_change([.01, 1.], .02, P), rtol=4e-15, atol=1e-16)
        p = replace(P, thickness_m=3.)
        ref = 90.; age = np.nextafter(ref, math.inf)
        expected = 4*math.exp(-math.pi**2*(ref/9))*((age-ref)/9)
        assert_allclose(plate_cooling_deficit_change(age, ref, p), expected, rtol=4e-14, atol=0)

    def test_symmetry_equal_ages_isothermal_and_batching(self):
        age = np.array([0., .001, .0625, .2, 10.])[:, None]
        ref = np.array([0., .003, .07, .9])[::2]
        expected = plate_cooling_deficit_change(age, ref, P)
        assert_array_equal(plate_cooling_deficit_change(ref, age, P), -expected)
        assert_array_equal(plate_cooling_deficit_change(age, ref, P, batch_elements=3), expected)
        assert_array_equal(plate_cooling_deficit_change(age, age, P), np.zeros_like(age))
        equal = replace(P, thermal=replace(P.thermal, surface_temperature_k=300.,
                                           mantle_temperature_k=300.))
        assert_array_equal(plate_cooling_deficit_change([0., 1e300], [1e300, 0.], equal), [0., 0.])

    def test_detached_immutable_result(self):
        age = np.array([.01, .2]); reference = np.array([.002, .02])
        result = plate_cooling_deficit_change(age, reference, P)
        expected = result.copy()
        age[:] = 0.; reference[:] = 0.
        assert_array_equal(result, expected)
        with self.assertRaises(ValueError):
            result.setflags(write=True)
        self.assertFalse(np.shares_memory(result, age))

    def test_invalid_inputs_ranges_and_unrepresentable_transient(self):
        for age, ref in ((-1., 0.), (0., -1.), (math.inf, 0.), (0., math.nan),
                         (True, 0.), ('1', 0.), (np.ma.array([1.]), 0.),
                         (np.empty(0), 0.), ([1., 2.], [1., 2., 3.])):
            with self.subTest(age=age, reference=ref):
                with self.assertRaises(TectonicsError):
                    plate_cooling_deficit_change(age, ref, P)
        with self.assertRaises(TectonicsError):
            plate_cooling_deficit_change(1., 0., P.thermal)
        for count in (True, 0, -1, 2.5):
            with self.assertRaises(TectonicsError):
                plate_cooling_deficit_change(1., 0., P, batch_elements=count)
        for length in (1e-300, 1e300):
            with self.assertRaises(TectonicsError):
                plate_cooling_deficit_change(1., 0., replace(P, thickness_m=length))
        with self.assertRaisesRegex(TectonicsError, 'leading transient'):
            plate_cooling_deficit_change(101., 100., P)

    def test_admission_precedes_capture_and_releases_on_failure(self):
        budget = WorkBudget(16)
        with patch('atlas_tectonics.plate_integrals.read_array', side_effect=AssertionError('capture')):
            with self.assertRaises(MemoryLimitError):
                plate_cooling_deficit_change([.1, .2], 0., P, budget=budget)
        self.assertEqual(budget.reserved_bytes, 0)
        budget = WorkBudget(1<<20)
        with self.assertRaises(TectonicsError):
            plate_cooling_deficit_change(-1., 0., P, budget=budget)
        self.assertEqual(budget.reserved_bytes, 0)

    def test_cancellation_before_and_during_batches(self):
        flag = threading.Event(); flag.set()
        with self.assertRaises(CancelledError):
            plate_cooling_deficit_change(.1, 0., P, cancel=flag)
        class CancelAfterFirstBatch:
            checks = 0
            def is_set(self):
                self.checks += 1
                return self.checks >= 3
        budget = WorkBudget(1<<20)
        with self.assertRaises(CancelledError):
            plate_cooling_deficit_change([.01, .02, .03], 0., P, batch_elements=1,
                                         budget=budget, cancel=CancelAfterFirstBatch())
        self.assertEqual(budget.reserved_bytes, 0)


if __name__ == '__main__':
    unittest.main()
