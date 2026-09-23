"""Bounded independent parcel-law controls, not sediment calibration."""
from concurrent.futures import CancelledError
from dataclasses import FrozenInstanceError, replace
from decimal import Decimal, localcontext
import math
import threading
import unittest
from unittest.mock import patch

import numpy as np
from numpy.testing import assert_allclose, assert_array_equal

from atlas_tectonics._validation import TectonicsError
from atlas_tectonics.compaction import CompactionParameters, compaction_response, compaction_work_bytes
from atlas_tectonics.resources import MemoryLimitError, WorkBudget


PARAMETERS = CompactionParameters("synthetic", "analytic test only", .1, .02, 1e5, 1e8, 0., .8)


class CompactionLawTests(unittest.TestCase):
    def test_loading_unloading_reloading_and_new_maximum(self):
        e0, s0, s1 = .8, 1e5, 9e5
        log_ratio = math.log(5.)
        loaded = compaction_response(e0, s0, s0, s1, PARAMETERS)
        assert_allclose(loaded, [e0-.1*log_ratio, s1], rtol=2e-15)
        unloaded = compaction_response(loaded[0], s1, loaded[1], s0, PARAMETERS)
        assert_allclose(unloaded, [e0-.08*log_ratio, s1], rtol=2e-15)
        reloaded = compaction_response(unloaded[0], s0, unloaded[1], s1, PARAMETERS)
        assert_allclose(reloaded, loaded, rtol=2e-15)
        further = compaction_response(reloaded[0], s1, reloaded[1], 1.9e6, PARAMETERS)
        assert_allclose(further, [loaded[0]-.1*math.log(2), 1.9e6], rtol=2e-15)

    def test_no_rebound_reversible_and_zero_slope_endpoints(self):
        for rebound in (0., .1):
            p = replace(PARAMETERS, rebound_slope_ln=rebound)
            a = compaction_response(.8, 0., 0., 9e5, p)
            b = compaction_response(a[0], 9e5, a[1], 0., p)
            assert_allclose(b[0], .8-(.1-rebound)*math.log(10), atol=2e-16)
        p = replace(PARAMETERS, compression_slope_ln=0., rebound_slope_ln=0.)
        assert_array_equal(compaction_response(.8, 1., 1., 99., p), [.8, 99.])

    def test_repeated_stress_is_exact_and_history_preserved(self):
        e = np.array([.01, .2, 1.])
        result = compaction_response(e, [1., 20., 300.], 1000., [1., 20., 300.], PARAMETERS)
        assert_array_equal(result[:, 0], e)
        assert_array_equal(result[:, 1], [1000.]*3)

    def test_broadcast_batches_and_immutable_detached_result(self):
        e = np.array([[.8], [.9]])
        stress = np.arange(1., 8.)*1e5
        actual = compaction_response(e, 0., 0., stress, PARAMETERS, batch_elements=3)
        expected_e = e-.1*np.log1p(stress/1e5)
        assert_allclose(actual[..., 0], expected_e, rtol=2e-15)
        assert_array_equal(actual[..., 1], np.broadcast_to(stress, (2, 7)))
        assert_array_equal(actual, compaction_response(e, 0., 0., stress, PARAMETERS))
        original = actual.copy(); e.fill(0); stress.fill(0)
        assert_array_equal(actual, original)
        with self.assertRaises(ValueError): actual.setflags(write=True)

    def test_explicit_parameter_bounds_and_frozen_record(self):
        for kwargs in ({"profile_id": " "}, {"provenance": ""}, {"compression_slope_ln": -1.},
                       {"rebound_slope_ln": .2}, {"reference_stress_pa": 0.},
                       {"max_effective_stress_pa": math.inf}, {"min_porosity": .9},
                       {"max_porosity": 1.}, {"compression_slope_ln": True}):
            with self.assertRaises(TectonicsError): replace(PARAMETERS, **kwargs)
        with self.assertRaises(FrozenInstanceError): PARAMETERS.reference_stress_pa = 1.

    def test_unknown_invalid_history_and_out_of_range_states_refuse(self):
        cases = ((-.1, 0., 0., 1.), (.8, -1., 0., 1.), (.8, 2., 1., 1.),
                 (.8, 0., 1e9, 1.), (.8, 0., 0., 1e9), (5., 0., 0., 1.),
                 (math.nan, 0., 0., 1.), (.8, 0., 0., math.inf),
                 (.01, 0., 0., 1e8))
        for args in cases:
            with self.assertRaises(TectonicsError): compaction_response(*args, PARAMETERS)
        with self.assertRaises(TectonicsError): compaction_response(.8, 0., 0., 1., None)
        with self.assertRaises(TectonicsError): compaction_response([.8]*2, [0.]*3, 0., 1., PARAMETERS)
        with self.assertRaises(TectonicsError): compaction_response(np.ma.array([.8], mask=[True]), 0., 0., 1., PARAMETERS)
        for batch in (0, -1, True, 1.5):
            with self.assertRaises(TectonicsError): compaction_response(.8, 0., 0., 1., PARAMETERS, batch_elements=batch)

    def test_admission_before_capture_and_release_on_failure(self):
        budget = WorkBudget(16)
        with patch("atlas_tectonics.compaction.read_array", side_effect=AssertionError("captured before admission")):
            with self.assertRaises(MemoryLimitError):
                compaction_response(.8, 0., 0., 1., PARAMETERS, budget=budget)
        self.assertEqual(budget.reserved_bytes, 0)
        admitted = WorkBudget(compaction_work_bytes((), (), (), (), batch_elements=1))
        with self.assertRaises(TectonicsError):
            compaction_response(.01, 0., 0., 1e8, PARAMETERS, budget=admitted, batch_elements=1)
        self.assertEqual(admitted.reserved_bytes, 0)

    def test_cancellation_before_capture_and_between_batches(self):
        flag = threading.Event(); flag.set()
        with patch("atlas_tectonics.compaction.read_array", side_effect=AssertionError("captured after cancel")):
            with self.assertRaises(CancelledError): compaction_response(.8, 0., 0., 1., PARAMETERS, cancel=flag)
        class AfterChecks:
            count = 0
            def is_set(self):
                self.count += 1
                return self.count >= 4
        budget = WorkBudget(1 << 20)
        with self.assertRaises(CancelledError):
            compaction_response([.8]*5, 0., 0., 1., PARAMETERS, batch_elements=1, budget=budget, cancel=AfterChecks())
        self.assertEqual(budget.reserved_bytes, 0)

    def test_large_shifted_stresses_and_tiny_weighted_ratio(self):
        p = replace(PARAMETERS, reference_stress_pa=1e308, max_effective_stress_pa=1.7e308)
        actual = compaction_response(.8, 1e308, 1e308, 1.5e308, p)
        assert_allclose(actual[0], .8-.1*math.log(1.25), rtol=2e-15)
        p = replace(PARAMETERS, compression_slope_ln=1e308, rebound_slope_ln=0.,
                    reference_stress_pa=1e308, max_effective_stress_pa=1.)
        tiny = compaction_response(.8, 0., 0., 1e-10, p)
        assert_allclose(tiny[0], .8-1e-10, rtol=0, atol=1e-16)
        # Decimal supplies an independent oracle for an adjacent-float load.
        old = 1e8; new = np.nextafter(old, math.inf)
        p = replace(PARAMETERS, max_effective_stress_pa=1e9)
        actual = compaction_response(1e-8, old, old, new, p)
        with localcontext() as context:
            context.prec = 70
            ratio = (Decimal.from_float(float(new))+Decimal(100000))/(Decimal.from_float(old)+Decimal(100000))
            expected = float(Decimal.from_float(1e-8)-Decimal.from_float(.1)*ratio.ln())
        assert_allclose(actual[0], expected, rtol=2e-15)

    def test_unrepresentable_nonzero_increment_refuses_false_zero(self):
        p = replace(PARAMETERS, compression_slope_ln=np.nextafter(0., 1.), rebound_slope_ln=0.)
        with self.assertRaisesRegex(TectonicsError, "numerical range"):
            compaction_response(.8, 0., 0., np.nextafter(0., 1.), p)


if __name__ == "__main__":
    unittest.main()
