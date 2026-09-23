"""Bounded W06.4 joins: changing kinematics, conserved origin and true cooling."""
from concurrent.futures import CancelledError
from contextlib import contextmanager
from dataclasses import replace
import hashlib
import json
import math
from pathlib import Path
import sys
from threading import Event
import unittest
from unittest import mock

import numpy as np

from atlas_tectonics import ColumnGrid1D, SpreadingPhase
from atlas_tectonics._validation import TectonicsError
from atlas_tectonics.resources import MemoryLimitError, WorkBudget
from atlas_tectonics.reuse import ExecutionContext
from atlas_tectonics.spreading_history import PlateReassignment, PreparedSpreadingHistory, RidgeHistoryEvent
from atlas_tectonics.spreading_history_cooling import PreparedHistoryCooling
from test_w06_spreading_cooling import (CASE as BIRTH, COOLING, YEAR, cooling_fixture,
                                        cooling_parameters, field_errors)
from w06_cooling_reference import CoolingReference
from w06_history_reference import PiecewiseHistoryReference, case_events


ROOT = Path(__file__).resolve().parents[1]
HISTORY = json.loads((ROOT/'cases/w06_history.json').read_text(encoding='utf-8'))


def typed_events(events):
    return tuple(RidgeHistoryEvent(**dict(event, reassignments=tuple(
        PlateReassignment(**item) for item in event['reassignments']))) for event in events)


def reference_history(scenario='motion_switch', *, bounds=None, events=None):
    return PiecewiseHistoryReference(case_events(HISTORY, scenario) if events is None else events,
        end_s=HISTORY['duration_years']*YEAR, bounds_m=HISTORY['domain_m'] if bounds is None else bounds,
        thermal_model_id=HISTORY['thermal_model_id'])


@contextmanager
def history_fixture(*, scenario='motion_switch', edges=None, events=None,
                    parameters=None, context=None, budget=None):
    owner = WorkBudget(HISTORY['work_budget_bytes']) if budget is None else budget
    if edges is None:
        edges = np.linspace(*HISTORY['domain_m'], 17)
    if events is None:
        events = case_events(HISTORY, scenario)
    grid = ColumnGrid1D(edges, frame_id=BIRTH['frame_id'], budget=owner)
    with PreparedSpreadingHistory(grid, typed_events(events), tuple(SpreadingPhase(**p) for p in BIRTH['phases']),
            time_s=BIRTH['time_s'], epoch_id=BIRTH['epoch_id'], width_m=BIRTH['width_m'],
            source_id=HISTORY['case_id'], context=context, budget=owner) as history:
        with PreparedHistoryCooling(history, parameters or cooling_parameters(), budget=owner) as cooling:
            yield cooling


class HistoryCoolingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.context = ExecutionContext('reference')
        cls.thermal = CoolingReference(COOLING, BIRTH['phases'])

    @classmethod
    def tearDownClass(cls):
        cls.context.close()

    def fixture(self, **kwargs):
        return history_fixture(context=self.context, **kwargs)

    def assert_fields(self, actual, expected):
        error = field_errors(actual, expected)
        contrast = COOLING['compensation_density_kg_m3']-COOLING['water_density_kg_m3']
        for name, gate in dict(temperature_k=COOLING['mean_temperature_error_k'],
                sheet_kg_m2=contrast*COOLING['support_error_m'], subsidence_m=COOLING['support_error_m'],
                depth_m=COOLING['support_error_m'], heat_j_m2=self.thermal.energy*COOLING['heat_relative_error']).items():
            self.assertLessEqual(error[name], gate, name)

    def assert_accounts(self, result, reference):
        heat, water = reference.thermal_accounts(result.motion.elapsed_s, self.thermal, width_m=BIRTH['width_m'])
        scale = max(heat[0], math.fsum(abs(v) for v in heat[[2, 4, 6, 7]]), 1.)
        np.testing.assert_allclose(result.heat_accounts_j[:9], heat[:9], rtol=0.,
                                   atol=scale*COOLING['heat_relative_error'])
        self.assertLessEqual(abs(heat[-1]), COOLING['reference_heat_relative_error'])
        self.assertLessEqual(abs(result.heat_accounts_j[-1]), COOLING['heat_relative_error'])
        np.testing.assert_allclose(result.water_accounts_m3[:5], water[:5], rtol=0.,
            atol=max(1.e-6, heat[0]/self.thermal.energy*COOLING['support_error_m']))
        expected_mass = reference.material_accounts(result.motion.elapsed_s, BIRTH['phases'], width_m=BIRTH['width_m'])
        np.testing.assert_allclose(result.motion.accounts_kg, expected_mass, rtol=0.,
                                   atol=128*np.finfo(float).eps*np.max(np.abs(expected_mass)))

    def test_frozen_history_geometry_material_and_first_exit_controls(self):
        self.assertEqual(HISTORY['frozen_design'], COOLING['frozen_design'])
        self.assertEqual(hashlib.sha256((ROOT/HISTORY['frozen_design']['path']).read_bytes()).hexdigest(),
                         HISTORY['frozen_design']['sha256'])
        for scenario in ('motion_switch', 'stop'):
            with self.subTest(scenario=scenario), self.fixture(scenario=scenario) as plan:
                result = plan.advance(plan.initial, time_s=20.e6*YEAR)
                expected = HISTORY['scenarios'][scenario]['expected_final']
                self.assertAlmostEqual(result.motion.ridge_position_m, expected['ridge_position_m'], delta=1.e-7)
                self.assertAlmostEqual(result.motion.created_width_m, expected['created_width_m'], delta=1.e-7)
                edges = min(s.left_m for s in result.motion.strips), max(s.right_m for s in result.motion.strips)
                np.testing.assert_allclose(edges, expected['oldest_edges_m'], atol=1.e-7, rtol=0.)
                np.testing.assert_allclose(result.motion.accounts_kg[:, 0], expected['created_phase_mass_kg'], rtol=1.e-14)
                self.assertAlmostEqual(result.heat_accounts_j[0]/expected['birth_enthalpy_j'], 1., delta=1.e-14)
                self.assert_accounts(result, reference_history(scenario))
                if scenario == 'motion_switch':
                    self.assertEqual(len(result.exports), 1)
                    export = result.exports[0].history
                    self.assertEqual(export.side, 'right')
                    self.assertAlmostEqual(export.exported_width_m, 50000., delta=1.e-7)
                    np.testing.assert_allclose([export.birth_offset_first_s, export.birth_offset_last_s],
                        np.asarray(expected['exported_birth_interval_years'])*YEAR, atol=1., rtol=0.)
                    np.testing.assert_allclose([export.exit_age_first_s, export.exit_age_last_s],
                        np.asarray(expected['right_exit_age_endpoints_years'])*YEAR, atol=1., rtol=0.)

    def test_true_crop_means_centres_and_ages_on_three_grids_switch_and_stop(self):
        for scenario in ('motion_switch', 'stop'):
            reference = reference_history(scenario)
            for spacing in HISTORY['grid_spacing_m']:
                edges = np.arange(HISTORY['domain_m'][0], HISTORY['domain_m'][1]+spacing, spacing, dtype=float)
                mask = (edges[:-1] >= HISTORY['crop_m'][0]) & (edges[1:] <= HISTORY['crop_m'][1])
                crop_edges = np.r_[edges[:-1][mask], edges[1:][mask][-1]]
                with self.fixture(scenario=scenario, edges=edges) as plan:
                    for years in (*HISTORY['output_years'], HISTORY['partial_cell_years']):
                        with self.subTest(scenario=scenario, spacing=spacing, years=years):
                            state = plan.advance(plan.initial, time_s=years*YEAR)
                            expected = reference.thermal_fields(crop_edges, years*YEAR, self.thermal)
                            np.testing.assert_allclose(state.ocean_fraction[mask], expected['ocean_fraction'], atol=1.e-12, rtol=0.)
                            np.testing.assert_array_equal(state.centre_valid[mask], expected['centre_valid'])
                            np.testing.assert_allclose(state.motion.centre_age_s[mask], expected['centre_age_s'], atol=1., rtol=0.)
                            self.assert_fields(state.cell_values[mask], expected['cell_values'])
                            self.assert_fields(state.centre_values[mask], expected['centre_values'])

    def test_old_crust_keeps_actual_age_not_current_distance_over_current_rate(self):
        edges = [-500000., 400000., 500000.]
        reference = reference_history()
        parcel = reference.parcel('right', 5.e6*YEAR, 20.e6*YEAR)
        self.assertAlmostEqual(parcel.position_m, 450000., delta=1.e-7)
        self.assertEqual(parcel.age_s, 15.e6*YEAR)
        wrong_age = (450000.-50000.)/(.035/YEAR-.005/YEAR)
        self.assertGreater(abs(wrong_age-parcel.age_s), 1.e6*YEAR)
        with self.fixture(edges=edges) as plan:
            state = plan.advance(plan.initial, time_s=20.e6*YEAR)
            self.assertAlmostEqual(state.motion.centre_age_s[1], parcel.age_s, delta=1.)
            self.assert_fields(state.centre_values[1:2], self.thermal.point(parcel.age_s)[None, :])
            self.assert_fields(state.cell_values, reference.thermal_fields(edges, state.time_s, self.thermal)['cell_values'])

    def test_single_event_reduces_to_step3_including_exact_ridge_centre(self):
        edges = np.linspace(*HISTORY['domain_m'], 34)  # Odd cell count: centre x=0.
        events = case_events(HISTORY)[:1]
        with self.fixture(edges=edges, events=events) as history, cooling_fixture(edges=edges, context=self.context) as constant:
            for years in (5.e6, 20.e6):
                actual = history.advance(history.initial, time_s=years*YEAR)
                expected = constant.advance(constant.initial, time_s=years*YEAR)
                self.assertTrue(actual.centre_valid[16])
                self.assertEqual(actual.motion.centre_age_s[16], 0.)
                self.assert_fields(actual.cell_values, expected.cell_values)
                self.assert_fields(actual.centre_values, expected.centre_values)
                np.testing.assert_allclose(actual.heat_accounts_j[:8], expected.heat_accounts_j[:8], rtol=1.e-12)

    def test_stop_creates_nothing_but_every_existing_age_and_cooling_continue(self):
        edges = np.linspace(*HISTORY['domain_m'], 34)
        with self.fixture(scenario='stop', edges=edges) as plan:
            before = plan.advance(plan.initial, time_s=10.e6*YEAR)
            after = plan.advance(before, time_s=20.e6*YEAR)
            np.testing.assert_array_equal(after.motion.accounts_kg, before.motion.accounts_kg)
            self.assertEqual(after.motion.strips, before.motion.strips)
            self.assertEqual(after.heat_accounts_j[0], before.heat_accounts_j[0])
            valid = before.centre_valid
            np.testing.assert_allclose(after.motion.centre_age_s[valid]-before.motion.centre_age_s[valid], 10.e6*YEAR, atol=1., rtol=0.)
            self.assertTrue(after.centre_valid[16])
            self.assertAlmostEqual(after.motion.centre_age_s[16], 10.e6*YEAR, delta=1.)
            self.assertGreater(after.heat_accounts_j[4], before.heat_accounts_j[4])
            self.assertGreater(after.water_accounts_m3[0], before.water_accounts_m3[0])
            self.assertTrue(np.all(after.centre_values[valid, 0] < before.centre_values[valid, 0]))

    def test_event_boundary_has_no_duplicate_birth_or_thermal_reset(self):
        reference = reference_history()
        with self.fixture(edges=np.linspace(*HISTORY['domain_m'], 9)) as plan:
            event = 10.e6*YEAR
            states = [plan.advance(plan.initial, time_s=time) for time in (event-1., event, event+1.)]
            self.assertEqual(len(states[1].motion.strips), 2)
            self.assertEqual(len(states[2].motion.strips), 4)
            self.assertAlmostEqual(states[1].motion.created_width_m, 400000., delta=1.e-7)
            self.assertAlmostEqual(states[2].motion.created_width_m-states[1].motion.created_width_m, .05/YEAR, delta=1.e-7)
            for state in states:
                self.assert_accounts(state, reference)
            old = [s for s in states[2].motion.strips if s.birth_event_id == BIRTH['motion']['event_id']]
            for strip in old:
                self.assertEqual(strip.cooling_offset_left_s, strip.birth_offset_left_s)
                self.assertEqual(strip.cooling_offset_right_s, strip.birth_offset_right_s)

    def test_stop_restart_retains_the_unfilled_birth_age_gap(self):
        first = case_events(HISTORY)[0]
        stopped = dict(first, offset_s=5.e6*YEAR, left_velocity_m_s=0., right_velocity_m_s=0.,
            ridge_velocity_m_s=0., event_id='stop-at-5myr', source_id='declared-welded-stop', active=False)
        restarted = dict(first, offset_s=10.e6*YEAR, event_id='restart-at-10myr', source_id='declared-ridge-restart')
        events = (first, stopped, restarted)
        edges = np.asarray([-500000., -225000., -175000., 0., 175000., 225000., 500000.])
        reference = reference_history(events=events)
        with self.fixture(events=events, edges=edges) as plan:
            stop = plan.advance(plan.initial, time_s=5.e6*YEAR)
            resume = plan.advance(stop, time_s=10.e6*YEAR)
            np.testing.assert_array_equal(stop.motion.accounts_kg, resume.motion.accounts_kg)
            result = plan.advance(resume, time_s=20.e6*YEAR)
            self.assertAlmostEqual(result.motion.created_width_m, 600000., delta=1.e-7)
            expected = reference.thermal_fields(edges, result.time_s, self.thermal)
            self.assert_fields(result.cell_values, expected['cell_values'])
            self.assert_fields(result.centre_values, expected['centre_values'])
            self.assert_accounts(result, reference)
            np.testing.assert_allclose(result.motion.centre_age_s, expected['centre_age_s'], atol=1., rtol=0.)
            for row in result.motion.intersections:
                young, old = row[-2:]/YEAR
                self.assertTrue(old <= 10.e6+1./YEAR or young >= 15.e6-1./YEAR)
            self.assertFalse(any(s.birth_event_id == stopped['event_id'] for s in result.motion.strips))
            for strip in result.motion.strips:
                if strip.birth_event_id == first['event_id']:
                    self.assertLessEqual(max(strip.birth_offset_left_s, strip.birth_offset_right_s), 5.e6*YEAR)

    def test_reassignment_preserves_origin_and_freezes_the_owner_at_first_exit(self):
        edges = np.linspace(*HISTORY['export_domain_m'], 17)
        reference = reference_history('ownership_reassignment', bounds=HISTORY['export_domain_m'])
        with self.fixture(scenario='ownership_reassignment', edges=edges) as plan:
            result = plan.advance(plan.initial, time_s=20.e6*YEAR)
            self.assert_accounts(result, reference)
            old = [s for s in result.motion.strips if s.birth_event_id == BIRTH['motion']['event_id']]
            self.assertEqual(len(old), 2)
            for strip in old:
                self.assertEqual(strip.birth_plate_id, 'synthetic-'+strip.side+'-plate')
                self.assertEqual(strip.plate_id, 'synthetic-reassigned-'+strip.side+'-plate')
                self.assertEqual(strip.birth_source_id, BIRTH['motion']['source_id'])
            expected = reference.first_exits(result.time_s)
            self.assertEqual(len(result.exports), len(expected))
            for thermal_export in result.exports:
                export = thermal_export.history
                candidates = [e for e in expected if e.side == export.side
                    and e.birth_event_id == export.birth_event_id and e.exit_event_id == export.exit_event_id]
                self.assertEqual(len(candidates), 1)
                independent = candidates[0]
                self.assertEqual(export.plate_id, independent.plate_id)
                self.assertEqual(export.birth_plate_id, independent.birth_plate_id)
                np.testing.assert_allclose([export.birth_offset_first_s, export.birth_offset_last_s,
                    export.exit_offset_first_s, export.exit_offset_last_s, export.exit_age_first_s, export.exit_age_last_s],
                    [independent.birth_first_s, independent.birth_last_s, independent.exit_first_s,
                     independent.exit_last_s, independent.age_first_s, independent.age_last_s], atol=1., rtol=0.)
                self.assertEqual(thermal_export.destination_id, export.side+'-thermal-export')
            self.assertTrue(any(e.history.plate_id == 'synthetic-right-plate' for e in result.exports))
            self.assertTrue(any(e.history.plate_id == 'synthetic-reassigned-right-plate' for e in result.exports))

    def test_clipped_and_enlarged_domains_keep_independent_accounts_and_common_crop(self):
        crop_edges = np.arange(-150000., 150001., 1000.)
        baseline = None
        for bounds in (HISTORY['domain_m'], HISTORY['enlarged_domain_m'], HISTORY['export_domain_m']):
            edges = np.arange(bounds[0], bounds[1]+1000., 1000.)
            with self.fixture(edges=edges) as plan:
                result = plan.advance(plan.initial, time_s=20.e6*YEAR)
                self.assert_accounts(result, reference_history(bounds=bounds))
                if bounds != HISTORY['export_domain_m']:
                    selected = (edges[:-1] >= crop_edges[0]) & (edges[1:] <= crop_edges[-1])
                    if baseline is None:
                        baseline = result.cell_values[selected].copy()
                    else:
                        error = field_errors(result.cell_values[selected], baseline)
                        self.assertLessEqual(error['subsidence_m'], HISTORY['enlarged_crop_support_error_m'])

    def test_64_128_partitions_and_direct_event_spanning_request_agree(self):
        with self.fixture(edges=np.linspace(*HISTORY['domain_m'], 5)) as plan:
            direct = plan.advance(plan.initial, time_s=20.e6*YEAR)
            for count in HISTORY['time_intervals']:
                state = plan.initial
                for time in np.linspace(0., 20.e6*YEAR, count+1)[1:]:
                    state = plan.advance(state, time_s=float(time))
                self.assertEqual(state.motion.intervals, count)
                self.assertEqual(state.motion.strips, direct.motion.strips)
                np.testing.assert_allclose(state.motion.centre_age_s, direct.motion.centre_age_s, atol=1., rtol=0.)
                self.assertLessEqual(field_errors(state.cell_values, direct.cell_values)['subsidence_m'], .01)
                np.testing.assert_array_equal(state.heat_accounts_j, direct.heat_accounts_j)
                np.testing.assert_array_equal(state.water_accounts_m3, direct.water_accounts_m3)

    def test_finite_thermal_stock_refusal_keeps_pre_event_state_and_reservations(self):
        owner = WorkBudget(HISTORY['work_budget_bytes'])
        parameters = replace(cooling_parameters(), birth_enthalpy_stock_j=3.e20)
        with self.fixture(parameters=parameters, budget=owner) as plan:
            state = plan.advance(plan.initial, time_s=10.e6*YEAR)
            identity, retained = state.state_id, owner.reserved_bytes
            with self.assertRaises(TectonicsError):
                plan.advance(state, time_s=20.e6*YEAR)
            self.assertEqual(state.state_id, identity)
            self.assertEqual(owner.reserved_bytes, retained)
            self.assertIs(plan.advance(state, time_s=state.time_s), state)
        self.assertEqual(owner.reserved_bytes, 0)

    def test_history_cancellation_budget_and_foreign_source_guards(self):
        owner = WorkBudget(HISTORY['work_budget_bytes'])
        event = Event()
        with self.fixture(budget=owner) as plan:
            accepted = plan.advance(plan.initial, time_s=10.e6*YEAR)
            retained = owner.reserved_bytes
            with self.assertRaises(MemoryLimitError):
                plan.advance(accepted, time_s=20.e6*YEAR, budget=WorkBudget(1, parent=owner))
            observed = []

            def cancel_at_thermal_work(frame, kind, arg):
                if (kind == 'call' and frame.f_code.co_name == '_values'
                        and frame.f_globals.get('__name__') == 'atlas_tectonics.spreading_history_cooling'):
                    observed.append(owner.reserved_bytes)
                    event.set()

            previous = sys.getprofile()
            try:
                sys.setprofile(cancel_at_thermal_work)
                with self.assertRaises(CancelledError):
                    plan.advance(accepted, time_s=20.e6*YEAR, cancel=event)
            finally:
                sys.setprofile(previous)
            self.assertTrue(observed)
            self.assertGreater(observed[0], retained)
            self.assertEqual(owner.reserved_bytes, retained)
            with self.fixture(parameters=replace(cooling_parameters(), water_source_id='other-history-water')) as other:
                with self.assertRaises(TectonicsError):
                    plan.advance(other.initial, time_s=YEAR)
            with mock.patch.object(PreparedHistoryCooling, '_values', lambda *args: None):
                with self.assertRaises(TectonicsError):
                    plan.advance(accepted, time_s=20.e6*YEAR)
        self.assertEqual(owner.reserved_bytes, 0)


if __name__ == '__main__':
    unittest.main()
