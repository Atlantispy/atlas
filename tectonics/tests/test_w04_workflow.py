"""Independent W03-to-W04 controls on an eight-cell synthetic periodic strip."""
from concurrent.futures import CancelledError
import copy
from dataclasses import FrozenInstanceError, replace
import math
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

import numpy as np
from numpy.testing import assert_allclose, assert_array_equal

from atlas_tectonics._validation import TectonicsError
from atlas_tectonics.parameters import FlexureParameters
from atlas_tectonics.resources import WorkBudget, MemoryLimitError
from atlas_tectonics.reuse import CachePolicy
from atlas_tectonics.storage import ArrayStore
from atlas_tectonics.w03_workflow import (advance_w03_columns,
    save_w03_columns, load_w03_columns)
from atlas_tectonics.w04_workflow import (W04SurfaceInputs, W04SupportPolicy,
    PreparedW04Support, project_w04_support)
from test_w03_workflow import initialise, workflow_fixture, STEP
from test_w01_regional_forcing import store_limits


SOURCE = 'authored synthetic W04 coupling control, not a physical calibration'
ELASTIC = FlexureParameters('w04-analytic', SOURCE, 12., 1., 0., 3300., 10.)
POLICY = W04SupportPolicy(SOURCE, 'periodic-repetition', 'flexure', 0.,
    100., .1, .01, ELASTIC)


def cell_ids(state):
    return tuple(cell['cell_id'] for cell in
        state.source_workflow.initial_samples.descriptor()['cells'])


def surface(state, volumes=None, pressure=None, *, source=SOURCE):
    n = state.material.grid.cells
    if volumes is None:
        volumes = np.full(n, state.reservoir_fluid_m3/n)
    if pressure is None:
        pressure = np.zeros(n)
    return W04SurfaceInputs(state, cell_ids(state), volumes, pressure, source_id=source)


class W04WorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.reference = initialise(workflow_fixture(cells=8))
        cls.reference_surface = surface(cls.reference)
        cls.cooling = advance_w03_columns(cls.reference, time_s=STEP,
            top_effective_stress_pa=0.)
        cls.cooling_surface = surface(cls.cooling)
        cls.compacted = advance_w03_columns(cls.reference, time_s=STEP,
            top_effective_stress_pa=1e6)
        cls.prepared = PreparedW04Support(cls.reference, cls.reference_surface, POLICY)

    @classmethod
    def tearDownClass(cls):
        cls.prepared.close()

    def test_reference_zero_and_explicit_additional_pressure(self):
        zero = self.prepared.solve(self.reference, self.reference_surface)
        assert_array_equal(zero.values, np.zeros((8, 8)))
        applied = surface(self.reference, pressure=np.full(8, 100.))
        result = self.prepared.solve(self.reference, applied)
        assert_array_equal(result.values[:, :3], np.zeros((8, 3)))
        assert_array_equal(result.values[:, 3:5], np.full((8, 2), 100.))
        expected = 100./(3300.*10.)
        assert_allclose(result.values[:, 5], expected, rtol=2e-15, atol=0.)
        assert_allclose(result.values[:, 6:], -expected, rtol=2e-15, atol=0.)

    def test_closed_reservoir_redistribution_is_zero_mean_sinusoidal_load(self):
        phase = 2*np.pi*np.arange(8)/8
        volumes = self.reference_surface.reservoir_volume_m3+.01*np.cos(phase)
        inputs = surface(self.reference, volumes)
        result = self.prepared.solve(self.reference, inputs)
        area = self.reference.compaction.area_m2
        pressure_amplitude = 1000.*10.*.01/area[0]
        dx = self.reference.material.grid.spacing_m
        # E=12, Te=1, nu=0 give D=1. This is the discrete operator eigenvalue,
        # not the continuum k**4 approximation.
        denominator = 3300.*10.+(2*math.sin(math.pi/8)/dx)**4
        expected_w = pressure_amplitude*np.cos(phase)/denominator
        assert_allclose(result.downward_load_pa, pressure_amplitude*np.cos(phase),
            rtol=3e-12, atol=2e-10)
        assert_allclose(result.values[:, 5], expected_w, rtol=3e-12, atol=1e-14)
        self.assertAlmostEqual(float(result.downward_load_pa@area), 0., delta=1e-9)
        self.assertGreater(float(np.ptp(result.values[:, 5])), .001)
        assert_allclose(np.mean(result.values[:, 5]),
            np.mean(result.downward_load_pa)/(3300.*10.), rtol=0., atol=2e-17)
        assert_array_equal(result.values[:, 1:4], np.zeros((8, 3)))
        shifted = self.prepared.solve(self.reference, surface(self.reference, np.roll(volumes, 2)))
        assert_allclose(shifted.values, np.roll(result.values, 2, axis=0),
            rtol=3e-12, atol=2e-10)
        expected_water = -result.values[:, 5]+(volumes-self.reference_surface.reservoir_volume_m3)/area
        assert_allclose(result.reservoir_surface_change_m, expected_water, rtol=2e-14, atol=1e-14)

    def test_thermal_counted_once_against_independent_cell_mean_integral(self):
        reference_diagnostic = self.reference.thermal_diagnostics()
        diagnostic = self.cooling.thermal_diagnostics()
        widths = np.diff(self.reference.binding.depth_edges_m)
        delta_integral = math.fsum(map(float,
            (reference_diagnostic['temperature_k']-diagnostic['temperature_k'])*widths))
        material = self.reference.binding.buoyancy_material
        expected_q = material.density_kg_m3*material.expansion_per_k*10.*delta_integral
        result = self.prepared.solve(self.cooling, self.cooling_surface)
        assert_allclose(result.values[:, 2], expected_q, rtol=3e-12, atol=1e-6)
        assert_allclose(result.values[:, 4], expected_q, rtol=3e-12, atol=1e-6)
        assert_allclose(result.values[:, 5], expected_q/(3300.*10.), rtol=3e-12, atol=1e-10)
        assert_allclose(result.values[:, [0, 1, 3]], 0., rtol=0., atol=1e-8)
        self.assertNotAlmostEqual(result.values[0, 5], float(diagnostic['support_response'][2]), places=6)
        metadata = result.descriptor()
        self.assertEqual(metadata['thermal_owner'], 'flexure')
        self.assertEqual(metadata['w03_local_displacement'], 'diagnostic-only-excluded')
        self.assertFalse(metadata['feedback_applied'])

    def test_compaction_pore_exchange_is_loaded_once_at_its_explicit_destination(self):
        old_pores = np.sum(self.reference.compaction.grain_volume_m3*self.reference.compaction.void_ratio, axis=0)
        new_pores = np.sum(self.compacted.compaction.grain_volume_m3*self.compacted.compaction.void_ratio, axis=0)
        # Retain all expelled water directly above its original cell. Total local
        # material mass is unchanged, although the sediment surface subsides.
        local_water = self.reference_surface.reservoir_volume_m3+old_pores-new_pores
        result = self.prepared.solve(self.compacted, surface(self.compacted, local_water))
        cooling_only = self.prepared.solve(self.cooling, self.cooling_surface)
        assert_allclose(result.values[:, 0:2], 0., rtol=0., atol=2e-8)
        assert_array_equal(result.values[:, 3], np.zeros(8))
        assert_allclose(result.values[:, 4:6], cooling_only.values[:, 4:6], rtol=2e-14, atol=1e-8)
        sediment_change = (np.sum(self.compacted.material.thickness_m, axis=0)
                           -np.sum(self.reference.material.thickness_m, axis=0))
        assert_allclose(result.sediment_surface_change_m,
            sediment_change-result.values[:, 5], rtol=3e-14, atol=1e-11)
        assert_allclose(result.reservoir_surface_change_m, -result.values[:, 5],
            rtol=3e-14, atol=1e-11)

    def test_total_reference_is_idempotent_not_accumulated_and_matches_one_shot(self):
        before = (self.reference.state_id, self.cooling.state_id,
            self.cooling.material.thickness_m.copy(), self.cooling.compaction.void_ratio.copy())
        first = self.prepared.solve(self.cooling, self.cooling_surface)
        second = self.prepared.solve(self.cooling, self.cooling_surface)
        assert_array_equal(first.values, second.values)
        self.assertEqual(first.result_id, second.result_id)
        one_shot = project_w04_support(self.reference, self.cooling,
            self.reference_surface, self.cooling_surface, POLICY)
        assert_array_equal(first.values, one_shot.values)
        self.assertEqual(first.result_id, one_shot.result_id)
        self.assertTrue(first.descriptor()['total_reference_result'])
        self.assertEqual((self.reference.state_id, self.cooling.state_id), before[:2])
        assert_array_equal(self.cooling.material.thickness_m, before[2])
        assert_array_equal(self.cooling.compaction.void_ratio, before[3])

    def test_a_later_fixed_reference_uses_its_own_thermal_interval(self):
        later = advance_w03_columns(self.cooling, time_s=2*STEP, top_effective_stress_pa=0.)
        later_surface = surface(later)
        from_initial = self.prepared.solve(later, later_surface)
        to_middle = self.prepared.solve(self.cooling, self.cooling_surface)
        with PreparedW04Support(self.cooling, self.cooling_surface, POLICY) as shifted:
            second_interval = shifted.solve(later, later_surface)
        assert_allclose(from_initial.values[:, :6],
            to_middle.values[:, :6]+second_interval.values[:, :6], rtol=3e-13, atol=1e-7)
        self.assertEqual(second_interval.descriptor()['reference_state'], self.cooling.state_id)

    def test_surface_requires_correct_cells_complete_water_and_explicit_shapes(self):
        volumes = self.reference_surface.reservoir_volume_m3.copy()
        for ids, water, pressure in ((tuple(reversed(cell_ids(self.reference))), volumes, np.zeros(8)),
                (cell_ids(self.reference), volumes*2, np.zeros(8)),
                (cell_ids(self.reference), -volumes, np.zeros(8)),
                (cell_ids(self.reference), volumes, 0.),
                (cell_ids(self.reference), volumes[:-1], np.zeros(8)),
                (cell_ids(self.reference), volumes, np.full(8, math.nan))):
            with self.subTest(ids=ids, water=water, pressure=pressure), self.assertRaises(TectonicsError):
                W04SurfaceInputs(self.reference, ids, water, pressure, source_id=SOURCE)
        with self.assertRaisesRegex(TectonicsError, 'another W03 state'):
            self.prepared.solve(self.cooling, self.reference_surface)

    def test_policy_ownership_periodic_scope_and_old_water_bath_stiffness_refuse(self):
        for change in (dict(boundary='closed'), dict(thermal_owner='column-isostasy'),
                dict(thermal_owner='mechanical-buoyancy')):
            with self.subTest(change=change), self.assertRaises(TectonicsError):
                replace(POLICY, **change)
        for policy in (replace(POLICY, elastic=replace(ELASTIC, density_contrast_kg_m3=2300.)),
                replace(POLICY, elastic=replace(ELASTIC, gravity_m_s2=9.)),
                replace(POLICY, void_density_kg_m3=1000.,
                    elastic=replace(ELASTIC, density_contrast_kg_m3=2300.))):
            with self.subTest(policy=policy), self.assertRaises(TectonicsError):
                with PreparedW04Support(self.reference, self.reference_surface, policy):
                    pass

    def test_finite_capacity_and_linear_validity_limits_refuse(self):
        with self.assertRaisesRegex(TectonicsError, 'finite support'):
            with PreparedW04Support(self.reference, self.reference_surface,
                    replace(POLICY, headroom_m=1.)):
                pass
        concentrated = np.zeros(8); concentrated[0] = self.reference.reservoir_fluid_m3
        with PreparedW04Support(self.reference, self.reference_surface,
                replace(POLICY, headroom_m=20.)) as plan:
            with self.assertRaisesRegex(TectonicsError, 'finite support'):
                plan.solve(self.reference, surface(self.reference, concentrated))
        pressure = 1e5*np.cos(2*np.pi*np.arange(8)/8)
        with self.assertRaisesRegex(TectonicsError, 'validity envelope'):
            self.prepared.solve(self.reference, surface(self.reference, pressure=pressure))

    def test_changed_source_datum_and_loaded_callable_refuse(self):
        # Deliberately inconsistent synthetic copies exercise the adapter's source
        # guards. The genuine immutable W03 fixtures are never modified.
        changed = copy.copy(self.cooling)
        object.__setattr__(changed, 'execution_id', 'unbound-runtime')
        with self.assertRaisesRegex(TectonicsError, 'incompatible'):
            self.prepared.solve(changed, self.cooling_surface)
        changed = copy.copy(self.cooling)
        binding = replace(changed.binding, depth_reference_id='other-datum',
            support_parameters=replace(changed.binding.support_parameters, depth_reference_id='other-datum'))
        object.__setattr__(changed, 'binding', binding)
        with self.assertRaisesRegex(TectonicsError, 'incompatible'):
            self.prepared.solve(changed, self.cooling_surface)
        with patch('atlas_tectonics.w04_workflow.plate_cooling_deficit_change',
                side_effect=AssertionError('changed executable must not run')):
            with self.assertRaises(TectonicsError):
                self.prepared.solve(self.cooling, self.cooling_surface)

    def test_surface_snapshots_readonly_results_and_dry_water_masks(self):
        old_water = np.full(8, (100.-.001)/6); old_water[:2] = [0., .001]
        new_water = old_water.copy(); new_water[:2] = [.001, 0.]
        pressure = np.zeros(8)
        old = surface(self.reference, old_water, pressure)
        new = surface(self.reference, new_water, pressure)
        old_water[:] = 99.; new_water[:] = 99.; pressure[:] = 99.
        with PreparedW04Support(self.reference, old, POLICY) as plan:
            result = plan.solve(self.reference, new)
        assert_array_equal(result.reservoir_surface_known, [False, False]+[True]*6)
        assert_array_equal(result.values[:2, 7], [0., 0.])
        with self.assertRaisesRegex(TectonicsError, 'undefined'):
            _ = result.reservoir_surface_change_m
        metadata = result.descriptor(); metadata['policy']['thermal_owner'] = 'altered'
        self.assertEqual(result.descriptor()['policy']['thermal_owner'], 'flexure')
        for array in (old.reservoir_volume_m3, new.external_downward_pressure_pa,
                result.values, result.reservoir_surface_known):
            with self.assertRaises(ValueError): array.setflags(write=True)
            with self.assertRaises(ValueError): array.flat[0] = 1
            array.shape = (array.size,)
        self.assertEqual(result.values.shape, (8, 8))
        self.assertEqual(old.reservoir_volume_m3[0], 0.)
        self.assertEqual(new.reservoir_volume_m3[0], .001)
        with self.assertRaises(FrozenInstanceError): result.result_id = 'altered'
        with self.assertRaises(AttributeError): self.prepared.policy = POLICY

    def test_budget_close_and_cancellation_leave_source_unchanged(self):
        tiny = WorkBudget(1)
        with self.assertRaises(MemoryLimitError):
            PreparedW04Support(self.reference, self.reference_surface, POLICY, budget=tiny)
        self.assertEqual(tiny.reserved_bytes, 0)
        budget = WorkBudget(16<<20)
        plan = PreparedW04Support(self.reference, self.reference_surface, POLICY, budget=budget)
        self.assertGreater(budget.reserved_bytes, 0)
        reserved = budget.reserved_bytes
        event = threading.Event(); event.set()
        with self.assertRaises(CancelledError): plan.solve(self.cooling, self.cooling_surface, cancel=event)
        self.assertEqual(budget.reserved_bytes, reserved)
        before = self.cooling.state_id
        plan.solve(self.cooling, self.cooling_surface)
        self.assertEqual(budget.reserved_bytes, reserved)
        self.assertEqual(self.cooling.state_id, before)
        plan.close(); plan.close()
        self.assertEqual(budget.reserved_bytes, 0)
        with self.assertRaisesRegex(TectonicsError, 'closed'):
            plan.solve(self.cooling, self.cooling_surface)
        failed_entry = PreparedW04Support(self.reference,self.reference_surface,POLICY,budget=budget)
        with patch.object(PreparedW04Support,'_live',side_effect=TectonicsError('changed on entry')):
            # Close also verifies the source and can report the changed loaded
            # callable instead; either refusal must release the reservation.
            with self.assertRaisesRegex(TectonicsError,'changed'):
                with failed_entry:
                    self.fail('entry should refuse')
        self.assertEqual(budget.reserved_bytes,0)

    def test_repeated_projection_reuses_stored_load_and_flexure(self):
        with tempfile.TemporaryDirectory() as directory:
            with ArrayStore(Path(directory)/'w04.db', store_limits()) as store:
                with PreparedW04Support(self.reference, self.reference_surface, POLICY) as plan:
                    kwargs = dict(store=store, cache_policy=CachePolicy(mode='always'))
                    first = plan.solve(self.cooling, self.cooling_surface, **kwargs)
                    count = store.statistics()['snapshots']
                    second = plan.solve(self.cooling, self.cooling_surface, **kwargs)
                    self.assertGreaterEqual(count, 2)
                    self.assertEqual(store.statistics()['snapshots'], count)
                    self.assertGreaterEqual(plan._controller.statistics()['hits'], 2)
                    assert_array_equal(first.values, second.values)
                    self.assertEqual(first.result_id, second.result_id)
                    save_w03_columns(self.cooling, store)
                    restored = load_w03_columns(store, self.cooling.state_id)
                    self.assertEqual(restored.state_id, self.cooling.state_id)
                    restored_surface = surface(restored,
                        self.cooling_surface.reservoir_volume_m3,
                        self.cooling_surface.external_downward_pressure_pa)
                    self.assertEqual(restored_surface.input_id, self.cooling_surface.input_id)
                    recovered = plan.solve(restored, restored_surface, **kwargs)
                    assert_array_equal(recovered.values, first.values)
                    self.assertEqual(recovered.result_id, first.result_id)


if __name__ == '__main__':
    unittest.main()
