"""Step-4 geometry/history checks against independent scalar parcel paths."""
from concurrent.futures import CancelledError
from dataclasses import asdict, replace
import json
from pathlib import Path
from threading import Event
import unittest
from unittest.mock import patch

import numpy as np
from numpy.testing import assert_allclose, assert_array_equal

from atlas_tectonics._validation import TectonicsError
from atlas_tectonics.mesh import ColumnGrid1D
from atlas_tectonics.resources import MemoryLimitError, WorkBudget
from atlas_tectonics.reuse import ExecutionContext
from atlas_tectonics.spreading import SpreadingPhase
from atlas_tectonics.spreading_history import (PlateReassignment, RidgeHistoryEvent,
                                               PreparedSpreadingHistory)
from w06_history_reference import PiecewiseHistoryReference, case_events


ROOT = Path(__file__).resolve().parents[1]
CASE = json.loads((ROOT/'cases/w06_history.json').read_text(encoding='utf-8'))
BIRTH = json.loads((ROOT/'cases/w06_spreading.json').read_text(encoding='utf-8'))
YEAR = CASE['seconds_per_year']
MYR = 1e6*YEAR


def events(scenario='motion_switch'):
    result = []
    for row in case_events(CASE, scenario):
        row = dict(row)
        row['reassignments'] = tuple(PlateReassignment(**r) for r in row['reassignments'])
        result.append(RidgeHistoryEvent(**row))
    return tuple(result)


def ordered(rows):
    return rows[np.lexsort((rows[:, 1], rows[:, 0]))]


class HistoryGeometryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.context = ExecutionContext('reference')

    @classmethod
    def tearDownClass(cls):
        cls.context.close()

    def fixture(self, *, scenario='motion_switch', history=None, edges=None, phases=None, **kwargs):
        if edges is None:
            edges = np.linspace(*CASE['domain_m'], 2001)
        return PreparedSpreadingHistory(ColumnGrid1D(edges, frame_id=BIRTH['frame_id']),
            events(scenario) if history is None else history,
            tuple(SpreadingPhase(**row) for row in BIRTH['phases']) if phases is None else phases,
            time_s=0., epoch_id=BIRTH['epoch_id'], width_m=BIRTH['width_m'],
            source_id=CASE['case_id'], context=self.context, **kwargs)

    def reference(self, history, bounds):
        return PiecewiseHistoryReference(tuple(asdict(e) for e in history), end_s=20*MYR,
            bounds_m=bounds, thermal_model_id=CASE['thermal_model_id'])

    def test_switch_all_intersections_centres_accounts_and_first_exit(self):
        with self.fixture() as plan:
            reference = self.reference(plan.events, CASE['domain_m'])
            for age in (5*MYR, 10*MYR, CASE['partial_cell_years']*YEAR, 20*MYR):
                with self.subTest(age=age):
                    state = plan.advance(plan.initial, time_s=age)
                    expected = reference.project(plan.grid.edges_m, age)
                    a, b = ordered(state.intersections), ordered(expected['intersections'])
                    assert_array_equal(a[:, :2], b[:, :2])
                    assert_allclose(a[:, 2], b[:, 2], rtol=0., atol=CASE['position_error_m'])
                    assert_allclose(a[:, 3:], b[:, 3:], rtol=0., atol=CASE['age_error_s'])
                    assert_array_equal(state.centre_valid, expected['centre_valid'])
                    assert_allclose(state.centre_age_s, expected['centre_age_s'], rtol=0., atol=1.)
                    mass = reference.material_accounts(age, BIRTH['phases'], width_m=BIRTH['width_m'])
                    assert_allclose(state.accounts_kg[:, :5], mass[:, :5], rtol=3e-14, atol=.1)
                    self.assertLessEqual(len(a), plan.grid.cells+2*len(plan.events))
            self.assertAlmostEqual(state.ridge_position_m, 50000., delta=1e-7)
            self.assertAlmostEqual(state.created_width_m, 900000., delta=1e-7)
            assert_allclose((state.strips[0].left_m, state.strips[-1].right_m),
                            (-350000., 550000.), rtol=0., atol=1e-7)
            self.assertEqual(len(state.exports), 1)
            export = state.exports[0]
            self.assertEqual(export.side, 'right')
            assert_allclose(export.exported_width_m, 50000., rtol=0., atol=1e-7)
            assert_allclose((export.birth_offset_first_s, export.birth_offset_last_s),
                            (0., 2.5*MYR), rtol=0., atol=1.)
            assert_allclose((export.exit_offset_first_s, export.exit_offset_last_s),
                            ((10+300000/.035/1e6)*MYR, 20*MYR), rtol=0., atol=1.)
            assert_allclose((export.exit_age_first_s, export.exit_age_last_s),
                            ((10+300000/.035/1e6)*MYR, 17.5*MYR), rtol=0., atol=1.)
            self.assertGreater(export.exit_age_first_s, export.exit_age_last_s)

    def test_stop_preserves_births_and_samples_older_ridge(self):
        # Odd cell count places an actual sample at x=0, including its point age.
        edges = np.arange(-500250., 500251., 500.)
        for scenario in ('motion_switch', 'stop'):
            with self.subTest(scenario=scenario), self.fixture(scenario=scenario, edges=edges) as plan:
                at_five = plan.advance(plan.initial, time_s=5*MYR)
                self.assertTrue(at_five.centre_valid[1000])
                self.assertEqual(at_five.centre_age_s[1000], 0.)
                at_ten = plan.advance(at_five, time_s=10*MYR)
                self.assertEqual(len(at_ten.strips), 2)
                self.assertEqual(at_ten.created_width_m, 400000.)
                if scenario == 'stop':
                    stopped = plan.advance(at_ten, time_s=20*MYR)
                    self.assertTrue(stopped.centre_valid[1000])
                    self.assertEqual(stopped.centre_age_s[1000], 10*MYR)
                    self.assertEqual(stopped.created_width_m, at_ten.created_width_m)
                    self.assertEqual(stopped.strips, at_ten.strips)
                    assert_allclose(stopped.intersections[:, 3:]-at_ten.intersections[:, 3:],
                                    10*MYR, rtol=0., atol=1.)
                    self.assertFalse(stopped.exports)

    def test_reassignment_retains_original_birth_and_first_exit_owner(self):
        with self.fixture(scenario='ownership_reassignment', edges=np.linspace(-100000., 100000., 401)) as plan:
            state = plan.advance(plan.initial, time_s=20*MYR)
            reference = self.reference(plan.events, (-100000., 100000.))
            for strip in state.strips:
                self.assertEqual(strip.plate_id, getattr(plan.events[-1], strip.side+'_plate_id'))
                self.assertEqual(strip.cooling_offset_left_s, strip.birth_offset_left_s)
                self.assertEqual(strip.cooling_offset_right_s, strip.birth_offset_right_s)
                if strip.birth_event_id == plan.events[0].event_id:
                    self.assertEqual(strip.birth_plate_id, getattr(plan.events[0], strip.side+'_plate_id'))
                    self.assertNotEqual(strip.birth_plate_id, strip.plate_id)
            expected = reference.first_exits(20*MYR)
            key = lambda e: (e.birth_event_id, e.side, e.exit_event_id)
            actual = {key(e): e for e in state.exports}
            self.assertEqual(set(actual), {key(e) for e in expected})
            for row in expected:
                export = actual[key(row)]
                self.assertEqual(export.plate_id, row.plate_id)
                assert_allclose(export.exported_width_m, row.width_m, rtol=0., atol=1e-7)
                assert_allclose((export.exit_age_first_s, export.exit_age_last_s),
                                (row.age_first_s, row.age_last_s), rtol=0., atol=1.)
            earlier = [e for e in state.exports if e.exit_event_id == plan.events[0].event_id]
            self.assertTrue(earlier)
            self.assertTrue(all(e.plate_id == getattr(plan.events[0], e.side+'_plate_id') for e in earlier))

    def test_outputs_do_not_create_histories_and_partial_cell_projection(self):
        with self.fixture(edges=[-500000., -166667., 22222., 500000.]) as plan:
            direct = plan.advance(plan.initial, time_s=20*MYR)
            state = plan.initial
            for time in (1*MYR, 10*MYR, 15.00625*MYR, 20*MYR):
                state = plan.advance(state, time_s=time)
            self.assertEqual(state.strips, direct.strips)
            self.assertEqual(state.exports, direct.exports)
            assert_array_equal(state.intersections, direct.intersections)
            assert_array_equal(state.accounts_kg, direct.accounts_kg)
            self.assertNotEqual(state.state_id, direct.state_id)
            self.assertIs(plan.advance(state, time_s=state.time_s), state)
            initial = plan.initial
            self.assertEqual(initial.intersections.shape, (0, 5))
            self.assertFalse(initial.centre_valid.any())
            assert_array_equal(initial.accounts_kg[:, 0], 0.)
            thickness = plan.phase_thickness(state)
            self.assertEqual(thickness.shape, (2, 3))
            for array in (state.intersections, state.accounts_kg, state.centre_age_s,
                          state.centre_valid, state.centre_strip_index, thickness):
                with self.assertRaises(ValueError):
                    array.setflags(write=True)

    def test_invalid_events_positions_and_ownership_fail_visibly(self):
        base = events()
        bad = ((replace(base[0], offset_s=1.),),
               (base[0], replace(base[1], offset_s=0.)),
               (base[0], replace(base[1], event_id=base[0].event_id)),
               (base[0], replace(base[1], ridge_position_m=1.)),
               (base[0], replace(base[1], ridge_id='different')),
               (base[0], replace(base[1], left_plate_id='unaccounted')),
               (base[0], replace(base[1], ridge_position_m=600000.)))
        for history in bad:
            with self.subTest(history=history), self.assertRaises(TectonicsError):
                self.fixture(history=history)
        for changes in (dict(active=False), dict(left_velocity_m_s=1.),
                        dict(ridge_velocity_m_s=base[0].right_velocity_m_s)):
            with self.assertRaises(TectonicsError):
                replace(base[0], **changes)
        with self.fixture() as plan, self.assertRaises(TectonicsError):
            plan.advance(plan.initial, time_s=120*MYR)

    def test_feeds_budgets_cancel_content_and_source_guards(self):
        phases = tuple(replace(SpreadingPhase(**row), stock_kg=1.) for row in BIRTH['phases'])
        with self.fixture(phases=phases) as plan:
            before = plan.initial.state_id
            with self.assertRaisesRegex(TectonicsError, 'feed exhausted'):
                plan.advance(plan.initial, time_s=MYR)
            self.assertEqual(plan.initial.state_id, before)
        with self.assertRaises(MemoryLimitError):
            self.fixture(budget=WorkBudget(1024))
        stop = Event(); stop.set()
        with self.assertRaises(CancelledError):
            self.fixture(cancel=stop)
        with self.fixture() as plan:
            with self.assertRaises(CancelledError):
                plan.advance(plan.initial, time_s=MYR, cancel=stop)
            with patch.object(ExecutionContext, 'verify', side_effect=TectonicsError('source changed')):
                with self.assertRaisesRegex(TectonicsError, 'source changed'):
                    plan.advance(plan.initial, time_s=MYR)
            object.__setattr__(plan.initial, 'created_width_m', 1.)
            with self.assertRaisesRegex(TectonicsError, 'identity'):
                plan.advance(plan.initial, time_s=MYR)

    def test_semantic_and_requested_interval_caps(self):
        first = events()[0]
        too_many = tuple(replace(first, offset_s=float(i), event_id='event-'+str(i)) for i in range(257))
        with self.assertRaisesRegex(TectonicsError, '256'):
            self.fixture(history=too_many)
        with self.fixture(history=(first,), edges=[-1., 0., 1.]) as plan:
            state = plan.initial
            for i in range(1, 257):
                state = plan.advance(state, time_s=float(i))
            self.assertEqual(state.intervals, 256)
            with self.assertRaisesRegex(TectonicsError, '256'):
                plan.advance(state, time_s=257.)

    def test_many_events_without_exports_avoid_quadratic_admission(self):
        first = events()[0]
        history = tuple(replace(first, offset_s=float(i), event_id='event-'+str(i)) for i in range(256))
        budget = WorkBudget(128*1024*1024)
        with self.fixture(history=history, edges=[-1., 0., 1.], budget=budget) as plan:
            state = plan.advance(plan.initial, time_s=256.)
            self.assertEqual(len(state.strips), 512)
            self.assertFalse(state.exports)
            expected = 2*.02/YEAR*256
            assert_allclose(state.created_width_m, expected, rtol=3e-15)
            assert_allclose(state.intersections[:, 2].sum(), expected, rtol=3e-14)
            self.assertLess(budget.peak_reserved_bytes, budget.max_bytes)


if __name__ == '__main__':
    unittest.main()
