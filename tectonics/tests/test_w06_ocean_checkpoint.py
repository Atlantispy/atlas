"""Lossless ocean-only codec checks; store/publication belong to workflow tests."""
from concurrent.futures import CancelledError
from contextlib import contextmanager
from dataclasses import replace
import sys
from threading import Event
import unittest

import numpy as np
from numpy.testing import assert_array_equal

from atlas_tectonics._validation import TectonicsError
from atlas_tectonics.resources import MemoryLimitError, WorkBudget
from atlas_tectonics.reuse import ExecutionContext
from atlas_tectonics.spreading_checkpoint import pack_ocean, restore_ocean
from atlas_tectonics.spreading_cooling import PreparedSpreadingCooling, _state as constant_state
from atlas_tectonics.spreading_history_cooling import PreparedHistoryCooling
from atlas_tectonics.spreading_integrals import spreading_thermal_means
from test_w06_spreading_cooling import cooling_fixture, cooling_parameters, YEAR
from test_w06_history_cooling import history_fixture


@contextmanager
def without_thermal_evaluation():
    """Observe calls without replacing a source-bound production callable."""
    forbidden = {spreading_thermal_means.__code__, PreparedSpreadingCooling._values.__code__,
        PreparedSpreadingCooling._evaluate.__code__, PreparedHistoryCooling._values.__code__,
        PreparedHistoryCooling._evaluate.__code__}
    def observe(frame, event, arg):
        if event == 'call' and frame.f_code in forbidden:
            raise AssertionError('checkpoint restore re-evaluated thermal fields')
    previous = sys.getprofile()
    try:
        sys.setprofile(observe)
        yield
    finally:
        sys.setprofile(previous)


def restore_arguments(state):
    return dict(time_s=state.time_s, intervals=state.motion.intervals,
        motion_parent_id=state.motion.parent_state_id, thermal_parent_id=state.parent_state_id)


class OceanCheckpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.context = ExecutionContext('reference')

    @classmethod
    def tearDownClass(cls):
        cls.context.close()

    def assert_roundtrip(self, plan, state):
        arrays, meta = pack_ocean(plan, state)
        self.assertNotIn('geometry', arrays)
        self.assertNotIn('ocean_fraction', arrays)
        self.assertNotIn('centre_valid', arrays)
        for array in arrays.values():
            with self.assertRaises(ValueError):
                array.setflags(write=True)
        with without_thermal_evaluation():
            actual = restore_ocean(plan, arrays, meta, **restore_arguments(state))
        self.assertIs(type(actual), type(state))
        self.assertEqual(actual.state_id, state.state_id)
        self.assertEqual(actual.motion.state_id, state.motion.state_id)
        self.assertEqual(actual.parent_state_id, state.parent_state_id)
        self.assertEqual(actual.motion.parent_state_id, state.motion.parent_state_id)
        self.assertEqual(actual.motion.strips, state.motion.strips)
        self.assertEqual(actual.exports, state.exports)
        for name in ('cell_values', 'centre_values', 'ocean_fraction', 'centre_valid',
                     'heat_accounts_j', 'water_accounts_m3'):
            assert_array_equal(getattr(actual, name), getattr(state, name))
        assert_array_equal(actual.motion.accounts_kg, state.motion.accounts_kg)
        return actual

    def test_constant_initial_exported_and_continued_exact_roundtrip(self):
        edges = np.linspace(-100000., 100000., 34)
        with cooling_fixture(context=self.context, edges=edges) as plan:
            self.assert_roundtrip(plan, plan.initial)
            first = plan.advance(plan.initial, time_s=5e6*YEAR)
            second = plan.advance(first, time_s=20e6*YEAR)
            recovered = self.assert_roundtrip(plan, second)
            self.assertEqual(recovered.motion.intervals, 2)
            self.assertTrue(all(e.width_m > 0 for e in recovered.exports))
            self.assertEqual(set(pack_ocean(plan, second)[0]),
                {'cell_values', 'centre_values', 'heat_accounts_j', 'water_accounts_m3'})

    def test_history_initial_switch_stop_and_first_exit_ownership_roundtrip(self):
        edges = np.linspace(-100000., 100000., 18)
        for scenario in ('motion_switch', 'stop', 'ownership_reassignment'):
            with self.subTest(scenario=scenario), history_fixture(context=self.context,
                    scenario=scenario, edges=edges) as plan:
                self.assert_roundtrip(plan, plan.initial)
                first = plan.advance(plan.initial, time_s=10e6*YEAR)
                final = plan.advance(first, time_s=20e6*YEAR)
                recovered = self.assert_roundtrip(plan, final)
                arrays, meta = pack_ocean(plan, final)
                self.assertEqual(arrays['export_accounts'].shape, (len(final.exports), 2))
                self.assertEqual(meta['export_count'], len(recovered.motion.exports))

    def test_payload_shape_dtype_finiteness_keys_and_identity_corruption(self):
        with cooling_fixture(context=self.context) as plan:
            state = plan.advance(plan.initial, time_s=5e6*YEAR)
            arrays, meta = pack_ocean(plan, state)
            variants = []
            variants.append(dict(arrays, extra=np.zeros(1)))
            variants.append({k: v for k, v in arrays.items() if k != 'heat_accounts_j'})
            variants.append(dict(arrays, cell_values=arrays['cell_values'].astype(np.float32)))
            variants.append(dict(arrays, cell_values=arrays['cell_values'][:-1]))
            altered = arrays['centre_values'].copy(); altered[0, 0] = np.nan
            variants.append(dict(arrays, centre_values=altered))
            altered = arrays['cell_values'].copy(); altered[0, 0] += 1.
            variants.append(dict(arrays, cell_values=altered))
            for index, corrupted in enumerate(variants):
                with self.subTest(variant=index), self.assertRaises(TectonicsError):
                    restore_ocean(plan, corrupted, meta, **restore_arguments(state))
            # Even a freshly recomputed state hash cannot legitimise a field
            # that breaks the declared support relation or finite reservoirs.
            corrupted = state.cell_values.copy()
            occupied = np.flatnonzero(state.ocean_fraction > 0.)[0]
            corrupted[occupied, len(plan.spreading.phases)+1] += 1.
            forged = constant_state(plan, state.motion, state.parent_state_id, state.exports,
                corrupted, state.centre_values, state.ocean_fraction, state.centre_valid,
                state.heat_accounts_j, state.water_accounts_m3)
            forged_arrays, forged_meta = pack_ocean(plan, forged)
            with self.assertRaisesRegex(TectonicsError, 'subsidence'):
                restore_ocean(plan, forged_arrays, forged_meta, **restore_arguments(state))

    def test_foreign_source_clock_count_parents_and_metadata_refuse(self):
        with cooling_fixture(context=self.context) as plan:
            state = plan.advance(plan.initial, time_s=5e6*YEAR)
            arrays, meta = pack_ocean(plan, state)
            for key, value in (('extra', 1), ('execution_id', '0'*64),
                    ('plan_id', '0'*64), ('motion_state_id', '0'*64), ('kind', 'history'),
                    ('time_s', True), ('intervals', True), ('motion_parent_id', None),
                    ('thermal_parent_id', '0'*64), ('export_count', 3)):
                with self.subTest(key=key), self.assertRaises(TectonicsError):
                    restore_ocean(plan, arrays, dict(meta, **{key: value}), **restore_arguments(state))
            with cooling_fixture(context=self.context,
                    parameters=replace(cooling_parameters(), water_source_id='foreign-water')) as other:
                with self.assertRaises(TectonicsError):
                    restore_ocean(other, arrays, meta, **restore_arguments(state))
            for changed in (dict(time_s=state.time_s+1.), dict(intervals=257),
                            dict(intervals=0), dict(motion_parent_id='0'*64)):
                with self.subTest(expected=changed), self.assertRaises(TectonicsError):
                    restore_ocean(plan, arrays, meta, **dict(restore_arguments(state), **changed))

    def test_budget_cancellation_and_history_export_corruption_are_errors(self):
        with history_fixture(context=self.context, edges=np.linspace(-100000., 100000., 18)) as plan:
            state = plan.advance(plan.initial, time_s=20e6*YEAR)
            arrays, meta = pack_ocean(plan, state)
            initial_bytes = plan._budget.reserved_bytes
            small = WorkBudget(1024, parent=plan._budget)
            with self.assertRaises(MemoryLimitError):
                pack_ocean(plan, state, budget=small)
            with self.assertRaises(MemoryLimitError):
                restore_ocean(plan, arrays, meta, budget=small, **restore_arguments(state))
            self.assertEqual(small.reserved_bytes, 0)
            self.assertEqual(plan._budget.reserved_bytes, initial_bytes)
            stop = Event(); stop.set()
            with self.assertRaises(CancelledError):
                pack_ocean(plan, state, cancel=stop)
            with self.assertRaises(CancelledError):
                restore_ocean(plan, arrays, meta, cancel=stop, **restore_arguments(state))
            self.assertEqual(plan._budget.reserved_bytes, initial_bytes)
            bad = arrays['export_accounts'].copy(); bad[0, 0] += 1e10
            with self.assertRaises(TectonicsError):
                restore_ocean(plan, dict(arrays, export_accounts=bad), meta, **restore_arguments(state))
            with self.assertRaises(TectonicsError):
                restore_ocean(plan, arrays, dict(meta, export_count=0), **restore_arguments(state))


if __name__ == '__main__':
    unittest.main()
