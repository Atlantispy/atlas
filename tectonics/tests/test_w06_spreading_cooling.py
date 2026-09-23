"""Focused assembled W06.3 ocean checks, not the full W03 thermal suite."""
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

from atlas_tectonics import ColumnGrid1D, PreparedRidgeSpreading, RidgeMotion, SpreadingPhase
from atlas_tectonics._validation import TectonicsError
from atlas_tectonics.constitutive import BoussinesqMaterial
from atlas_tectonics.parameters import PlateCoolingParameters, ThermalParameters
from atlas_tectonics.resources import MemoryLimitError, WorkBudget
from atlas_tectonics.reuse import ExecutionContext
from atlas_tectonics.spreading_cooling import OceanCoolingParameters, PreparedSpreadingCooling
from atlas_tectonics.thermal_support import ThermalSupportParameters
from w06_cooling_reference import CoolingReference


ROOT = Path(__file__).resolve().parents[1]
COOLING = json.loads((ROOT/'cases/w06_cooling.json').read_text(encoding='utf-8'))
CASE = json.loads((ROOT/'cases'/COOLING['spreading_case']).read_text(encoding='utf-8'))
YEAR = CASE['seconds_per_year']


def motion_arguments():
    values = dict(CASE['motion'])
    for side in ('left', 'right', 'ridge'):
        values[side+'_velocity_m_s'] = values.pop(side+'_velocity_m_per_year')/YEAR
    return values


def reference_motion(motion):
    return {name: getattr(motion, name) for name in (
        'ridge_position_m', 'left_velocity_m_s', 'right_velocity_m_s', 'ridge_velocity_m_s')}


def cooling_parameters(case=COOLING):
    plate = PlateCoolingParameters(ThermalParameters(case['case_id'], 'W06 frozen synthetic hot birth',
        case['surface_temperature_k'], case['base_temperature_k'], case['diffusivity_m2_s']),
        case['plate_thickness_m'], case['conductivity_w_m_k'])
    materials = tuple(BoussinesqMaterial(row['phase_id'], row['source_id'], row['density_kg_m3'],
        plate.volumetric_heat_capacity_j_m3_k/row['density_kg_m3'], case['conductivity_w_m_k'],
        alpha, case['base_temperature_k'], 0., 0.,
        (case['surface_temperature_k'], case['base_temperature_k']), case['max_relative_density_anomaly'])
        for row, alpha in zip(CASE['phases'], case['phase_expansion_per_k']))
    support = ThermalSupportParameters('w06-hot-birth-column', 'W06 selected column isostasy',
        'w06-fixed-water-level', 'column-isostasy', case['compensation_density_kg_m3'],
        case['water_density_kg_m3'], case['gravity_m_s2'], case['max_relative_deflection'])
    return OceanCoolingParameters(plate, materials, support, case['axial_depth_m'],
        case['birth_enthalpy_stock_j'], case['basal_heat_stock_j'], case['water_stock_m3'],
        case['case_id'], 'finite-hot-birth-enthalpy', 'finite-basal-heat-allowance',
        'finite-fixed-level-water', 'left-thermal-export', 'right-thermal-export')


@contextmanager
def cooling_fixture(*, edges=None, motion=None, parameters=None, context=None, budget=None):
    if edges is None:
        edges = np.linspace(*CASE['domain_m'], 17)
    owner = WorkBudget(CASE['work_budget_bytes']) if budget is None else budget
    grid = ColumnGrid1D(edges, frame_id=CASE['frame_id'], budget=owner)
    with PreparedRidgeSpreading(grid, motion or RidgeMotion(**motion_arguments()),
            tuple(SpreadingPhase(**p) for p in CASE['phases']), time_s=CASE['time_s'],
            epoch_id=CASE['epoch_id'], width_m=CASE['width_m'], source_id=CASE['case_id'],
            context=context, budget=owner) as spreading:
        with PreparedSpreadingCooling(spreading, parameters or cooling_parameters(), budget=owner) as cooling:
            yield cooling


def field_errors(actual, expected, phases=2):
    errors = np.abs(actual-expected)
    return dict(temperature_k=float(np.max(errors[:, :phases], initial=0.)),
                sheet_kg_m2=float(np.max(errors[:, phases], initial=0.)),
                subsidence_m=float(np.max(errors[:, phases+1], initial=0.)),
                depth_m=float(np.max(errors[:, phases+2], initial=0.)),
                heat_j_m2=float(np.max(errors[:, phases+3:], initial=0.)))


class SpreadingCoolingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.context = ExecutionContext('reference')
        cls.reference = CoolingReference(COOLING, CASE['phases'])

    @classmethod
    def tearDownClass(cls):
        cls.context.close()

    def fixture(self, **kwargs):
        return cooling_fixture(context=self.context, **kwargs)

    def assert_fields(self, actual, expected):
        error = field_errors(actual, expected)
        self.assertLessEqual(error['temperature_k'], COOLING['mean_temperature_error_k'])
        contrast = COOLING['compensation_density_kg_m3']-COOLING['water_density_kg_m3']
        self.assertLessEqual(error['sheet_kg_m2'], contrast*COOLING['support_error_m'])
        self.assertLessEqual(error['subsidence_m'], COOLING['support_error_m'])
        self.assertLessEqual(error['depth_m'], COOLING['support_error_m'])
        self.assertLessEqual(error['heat_j_m2'], self.reference.energy*COOLING['heat_relative_error'])

    def assert_accounts(self, result, plan):
        heat, water = self.reference.accounts(plan.spreading.grid.edges_m[[0, -1]],
            result.motion.elapsed_s, width_m=CASE['width_m'], **reference_motion(plan.spreading.motion))
        scale = max(heat[0], math.fsum(abs(v) for v in heat[[2, 4, 6, 7]]), 1.)
        np.testing.assert_allclose(result.heat_accounts_j[:9], heat[:9], rtol=0.,
                                   atol=COOLING['heat_relative_error']*scale)
        self.assertLessEqual(abs(heat[-1]), COOLING['reference_heat_relative_error'])
        self.assertLessEqual(abs(result.heat_accounts_j[-1]), COOLING['heat_relative_error'])
        created_area = heat[0]/self.reference.energy
        np.testing.assert_allclose(result.water_accounts_m3[:5], water[:5], rtol=0.,
                                   atol=max(1.e-6, created_area*COOLING['support_error_m']))
        self.assertLessEqual(abs(result.water_accounts_m3[-1]), 128*np.finfo(float).eps*max(water[0], 1.))

    def test_frozen_inputs_and_independent_quadrature_uncertainty(self):
        self.assertEqual(COOLING['frozen_design'], CASE['frozen_design'])
        design = ROOT/COOLING['frozen_design']['path']
        self.assertEqual(hashlib.sha256(design.read_bytes()).hexdigest(), COOLING['frozen_design']['sha256'])
        self.assertEqual(self.reference.energy*CASE['final_created_width_m'], 3.432e20)
        tighter = CoolingReference(COOLING, CASE['phases'], tolerance=5.e-14)
        for low, high in ((0., 20.e6*YEAR), (0., YEAR), (4.e6*YEAR, 20.e6*YEAR),
                          (100.e6*YEAR, 200.e6*YEAR)):
            error = field_errors(self.reference.mean(low, high)[None, :], tighter.mean(low, high)[None, :])
            self.assertLess(error['temperature_k'], COOLING['reference_temperature_error_k'])
            self.assertLess(error['subsidence_m'], COOLING['reference_support_error_m'])
            self.assertLess(error['heat_j_m2']/self.reference.energy, COOLING['reference_heat_relative_error'])
        for years, expected in ((1.e6, 218.116170), (5.e6, 508.646061),
                                 (10.e6, 729.091665), (20.e6, 1038.028468)):
            self.assertAlmostEqual(self.reference.point(years*YEAR)[3], expected, delta=.001)

    def test_all_occupied_crop_cells_and_centres_on_three_grids_and_outputs(self):
        for spacing in CASE['grid_spacing_m']:
            edges = np.arange(CASE['domain_m'][0], CASE['domain_m'][1]+spacing, spacing, dtype=float)
            crop = (edges[:-1] >= CASE['crop_m'][0]) & (edges[1:] <= CASE['crop_m'][1])
            cropped_edges = np.r_[edges[:-1][crop], edges[1:][crop][-1]]
            with self.fixture(edges=edges) as plan:
                state = plan.initial
                for years in (*CASE['output_years'], CASE['partial_cell_years']):
                    with self.subTest(spacing=spacing, years=years):
                        # Partial-cell control is a separate immutable branch.
                        start = plan.initial if years == CASE['partial_cell_years'] else state
                        result = plan.advance(start, time_s=years*YEAR)
                        if years != CASE['partial_cell_years']:
                            state = result
                        expected = self.reference.fields(cropped_edges, years*YEAR,
                                                         **reference_motion(plan.spreading.motion))
                        np.testing.assert_allclose(result.ocean_fraction[crop], expected['ocean_fraction'], atol=1.e-12, rtol=0.)
                        np.testing.assert_array_equal(result.centre_valid[crop], expected['centre_valid'])
                        self.assert_fields(result.cell_values[crop], expected['cell_values'])
                        self.assert_fields(result.centre_values[crop], expected['centre_values'])
                        empty = result.ocean_fraction == 0.
                        self.assertTrue(np.all(result.cell_values[empty] == 0.))
                        self.assertTrue(np.all(result.centre_values[~result.centre_valid] == 0.))

    def test_all_output_heat_and_water_accounts_are_independent_birth_integrals(self):
        with self.fixture(edges=np.linspace(*CASE['domain_m'], 33)) as plan:
            state = plan.initial
            for years in CASE['output_years']:
                state = plan.advance(state, time_s=years*YEAR)
                self.assert_accounts(state, plan)
            self.assertEqual(state.heat_accounts_j[0], 3.432e20)
            self.assertGreater(state.heat_accounts_j[2], 0.)
            self.assertGreater(state.water_accounts_m3[0], 2600.*800000.)
            self.assertEqual(state.water_accounts_m3[3], 0.)
            self.assertEqual(state.water_accounts_m3[4], 0.)

    def test_clipped_exports_freeze_enthalpy_and_water_at_boundary_exit(self):
        with self.fixture(edges=np.linspace(*CASE['export_domain_m'], 9)) as plan:
            result = plan.advance(plan.initial, time_s=20.e6*YEAR)
            self.assert_accounts(result, plan)
            exit_values = self.reference.point(5.e6*YEAR)
            hot_above_surface = sum((exit_values[i]-COOLING['surface_temperature_k'])*p['thickness_m']
                                    for i, p in enumerate(CASE['phases']))*self.reference.capacity
            for index, export in enumerate(result.exports):
                self.assertEqual(export.width_m, 300000.)
                self.assertAlmostEqual(export.first_exit_age_s/YEAR, 5.e6, delta=1.e-8)
                self.assertAlmostEqual(export.last_exit_age_s/YEAR, 5.e6, delta=1.e-8)
                self.assertAlmostEqual(result.heat_accounts_j[6+index]/300000., hot_above_surface,
                                       delta=self.reference.energy*COOLING['heat_relative_error'])
                self.assertAlmostEqual(result.water_accounts_m3[3+index]/300000., exit_values[4], delta=.1)
            # Continuing to cool the exported births outside the window gives a
            # measurably different answer; this guard detects that tempting bug.
            wrong_depth = self.reference.mean(5.e6*YEAR, 20.e6*YEAR)[4]
            self.assertGreater(wrong_depth-exit_values[4], 200.)

    def test_constant_migrating_ridge_accounts_and_mixed_ridge_cell(self):
        motion = RidgeMotion(**dict(motion_arguments(), ridge_velocity_m_s=.002/YEAR))
        edges = np.array([-100000., -75000., -12000., 45000., 70000., 100000.])
        with self.fixture(edges=edges, motion=motion) as plan:
            result = plan.advance(plan.initial, time_s=20.e6*YEAR)
            expected = self.reference.fields(edges, result.motion.elapsed_s, **reference_motion(motion))
            self.assert_fields(result.cell_values, expected['cell_values'])
            self.assert_fields(result.centre_values, expected['centre_values'])
            self.assert_accounts(result, plan)
            self.assertTrue(np.any(np.all(result.motion.cell_geometry[:, :, 0] > 0, axis=0)))
            self.assertNotEqual(result.heat_accounts_j[6], result.heat_accounts_j[7])
            self.assertNotEqual(result.exports[0].first_exit_age_s, result.exports[0].last_exit_age_s)

    def test_partition_32_64_128_preserves_final_fields_accounts_and_birth_history(self):
        finals = []
        with self.fixture(edges=np.linspace(*CASE['domain_m'], 5)) as plan:
            for intervals in CASE['time_intervals']:
                state = plan.initial
                for time in np.linspace(0., CASE['duration_years']*YEAR, intervals+1)[1:]:
                    state = plan.advance(state, time_s=float(time))
                finals.append(state)
                self.assertEqual(state.motion.intervals, intervals)
            for final in finals[1:]:
                for name in ('cell_values', 'centre_values', 'heat_accounts_j', 'water_accounts_m3'):
                    np.testing.assert_array_equal(getattr(final, name), getattr(finals[0], name))
                self.assertEqual(final.motion.strips, finals[0].motion.strips)
                self.assertNotEqual(final.state_id, finals[0].state_id)

    def test_initial_repeated_output_immutability_and_nonowning_close(self):
        owner = WorkBudget(CASE['work_budget_bytes'])
        with self.fixture(budget=owner) as plan:
            zero = plan.initial
            self.assertEqual(zero.time_s, 0.)
            self.assertFalse(np.any(zero.ocean_fraction))
            self.assertFalse(np.any(zero.centre_valid))
            np.testing.assert_array_equal(zero.heat_accounts_j[[0, 2, 4, 5, 6, 7, 8, 9]], 0.)
            self.assertEqual(zero.heat_accounts_j[1], COOLING['birth_enthalpy_stock_j'])
            self.assertEqual(zero.heat_accounts_j[3], COOLING['basal_heat_stock_j'])
            self.assertEqual(zero.water_accounts_m3[1], COOLING['water_stock_m3'])
            self.assertIs(plan.advance(zero, time_s=0.), zero)
            state = plan.advance(zero, time_s=5.e6*YEAR)
            self.assertIs(plan.advance(state, time_s=state.time_s), state)
            self.assertEqual(state.parent_state_id, zero.state_id)
            for values in (state.cell_values, state.centre_values, state.ocean_fraction,
                           state.centre_valid, state.heat_accounts_j, state.water_accounts_m3):
                with self.assertRaises(ValueError):
                    values.setflags(write=True)
            plan.close()
            self.assertIs(plan.spreading.advance(state.motion, time_s=state.time_s), state.motion)
            with self.assertRaises(TectonicsError):
                plan.advance(state, time_s=state.time_s)
        self.assertEqual(owner.reserved_bytes, 0)

    def test_heat_and_water_exhaustion_refuse_whole_candidate_without_spending(self):
        heat, water = self.reference.accounts(CASE['domain_m'], 20.e6*YEAR, width_m=1.,
            **reference_motion(RidgeMotion(**motion_arguments())))
        caps = dict(birth_enthalpy_stock_j=.9*heat[0], basal_heat_stock_j=.9*heat[2], water_stock_m3=.9*water[0])
        for name, cap in caps.items():
            owner = WorkBudget(CASE['work_budget_bytes'])
            with self.subTest(reservoir=name), self.fixture(parameters=replace(cooling_parameters(), **{name: cap}), budget=owner) as plan:
                accepted = plan.advance(plan.initial, time_s=5.e6*YEAR)
                before = accepted.state_id, accepted.heat_accounts_j.tobytes(), accepted.water_accounts_m3.tobytes()
                retained = owner.reserved_bytes
                with self.assertRaises(TectonicsError):
                    plan.advance(accepted, time_s=20.e6*YEAR)
                self.assertEqual(owner.reserved_bytes, retained)
                self.assertEqual(before, (accepted.state_id, accepted.heat_accounts_j.tobytes(), accepted.water_accounts_m3.tobytes()))
                self.assertIs(plan.advance(accepted, time_s=accepted.time_s), accepted)
            self.assertEqual(owner.reserved_bytes, 0)

    def test_owner_material_capacity_and_phase_partition_must_match(self):
        parameters = cooling_parameters()
        for owner in ('flexure', 'mechanical-buoyancy', 'empirical-age-depth'):
            with self.assertRaises(TectonicsError):
                replace(parameters, support=replace(parameters.support, thermal_owner=owner))
        material = parameters.phase_materials[0]
        for changed in (replace(material, reference_temperature_k=1500.),
                        replace(material, heat_capacity_j_kg_k=100.),
                        replace(material, internal_heating_w_m3=1.e-6),
                        replace(material, max_relative_density_anomaly=.01)):
            with self.assertRaises(TectonicsError):
                replace(parameters, phase_materials=(changed, parameters.phase_materials[1]))
        for changed in (replace(parameters, phase_materials=parameters.phase_materials[::-1]),
                        replace(parameters, phase_materials=parameters.phase_materials[:1]),
                        replace(parameters, plate=replace(parameters.plate, thickness_m=100001.))):
            with self.assertRaises(TectonicsError), self.fixture(parameters=changed):
                pass
        with self.assertRaises(TectonicsError):
            replace(parameters, water_source_id=parameters.birth_heat_source_id)

    def test_subsidence_envelope_checks_oldest_parcel_not_only_cold_cell_mean(self):
        parameters = cooling_parameters()
        limited = replace(parameters, support=replace(parameters.support, max_relative_deflection=.01))
        with self.fixture(edges=[-500000., 0., 500000.], parameters=limited) as plan:
            state = plan.advance(plan.initial, time_s=5.e6*YEAR)
            self.assertLess(self.reference.mean(0., 20.e6*YEAR)[3], 1000.)
            self.assertGreater(self.reference.point(20.e6*YEAR)[3], 1000.)
            with self.assertRaises(TectonicsError):
                plan.advance(state, time_s=20.e6*YEAR)

    def test_cancellation_and_admission_release_temporary_work_and_preserve_state(self):
        owner = WorkBudget(CASE['work_budget_bytes'])
        event = Event()
        with self.fixture(budget=owner) as plan:
            state = plan.advance(plan.initial, time_s=5.e6*YEAR)
            retained, identity = owner.reserved_bytes, state.state_id
            with self.assertRaises(MemoryLimitError):
                plan.advance(state, time_s=10.e6*YEAR, budget=WorkBudget(1, parent=owner))
            observed = []

            def cancel_inside(frame, kind, arg):
                if (kind == 'call' and frame.f_code.co_name == '_values'
                        and frame.f_globals.get('__name__') == 'atlas_tectonics.spreading_cooling'):
                    observed.append(owner.reserved_bytes)
                    event.set()

            previous = sys.getprofile()
            try:
                sys.setprofile(cancel_inside)
                with self.assertRaises(CancelledError):
                    plan.advance(state, time_s=10.e6*YEAR, cancel=event)
            finally:
                sys.setprofile(previous)
            self.assertTrue(observed)
            self.assertGreater(observed[0], retained)
            self.assertEqual(owner.reserved_bytes, retained)
            self.assertEqual(state.state_id, identity)
            event.clear()
            self.assertEqual(plan.advance(state, time_s=10.e6*YEAR).time_s, 10.e6*YEAR)
            event.set()
            with self.assertRaises(CancelledError):
                PreparedSpreadingCooling(plan.spreading, cooling_parameters(), budget=owner, cancel=event)
            self.assertEqual(owner.reserved_bytes, retained)
        self.assertEqual(owner.reserved_bytes, 0)

    def test_source_provenance_foreign_plan_and_live_execution_binding(self):
        import atlas_tectonics.spreading_cooling as module
        parameters = cooling_parameters()
        changed = replace(parameters, water_source_id='different-finite-water-source')
        with self.fixture() as plan, self.fixture(parameters=changed) as other:
            self.assertNotEqual(plan.plan_id, other.plan_id)
            with self.assertRaises(TectonicsError):
                plan.advance(other.initial, time_s=YEAR)
            with mock.patch.object(module, 'spreading_thermal_means', lambda *args, **kwargs: None):
                with self.assertRaises(TectonicsError):
                    plan.advance(plan.initial, time_s=YEAR)
            self.assertIs(plan.advance(plan.initial, time_s=0.), plan.initial)
            state = plan.advance(plan.initial, time_s=YEAR)
            self.assertEqual(state.motion.strips[0].event_id, CASE['motion']['event_id'])
            self.assertEqual(state.exports[0].destination_id, parameters.left_export_id)
            self.assertEqual(state.exports[1].destination_id, parameters.right_export_id)


if __name__ == '__main__':
    unittest.main()
