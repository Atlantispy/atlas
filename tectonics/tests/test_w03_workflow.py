"""Bounded stationary W01/W02/W03 assembly; no general transported stratigraphy."""
from concurrent.futures import CancelledError
from dataclasses import replace
from pathlib import Path
import tempfile
import threading
import unittest

import numpy as np
from numpy.testing import assert_allclose, assert_array_equal

from atlas_tectonics import (BoundaryRegion, CohortDescription, FeatureGeometry,
    FeaturePrecedence, GeologicalCase, GeologicalProvince, LayerComponent,
    MaterialCohort, RegionalGrid1D, SurfaceSelector, ThermalInitialProfile,
    ThermalParameters, PlateCoolingParameters, TectonicsError, build_boundary_network)
from atlas_tectonics.compaction import CompactionParameters
from atlas_tectonics.compaction_columns import DrainedCompactionConditions, compaction_geometry
from atlas_tectonics.regional_forcing import RegionalReduction
from atlas_tectonics.regional_workflow import PoreFluidCohort, PreparedRegionalWorkflow
from atlas_tectonics.regional_workflow_geometry import RegionalColumnSupport
from atlas_tectonics.resources import MemoryLimitError, WorkBudget
from atlas_tectonics.reuse import CachePolicy
from atlas_tectonics.storage import ArrayStore
from atlas_tectonics.w03_workflow import (initialise_w03_columns, advance_w03_columns,
    evolve_w03_columns, save_w03_columns, load_w03_columns)
from test_w01_geological_description import ROCK, WATER, SOURCE, column, layer
from test_w01_initial_sampling import initial
from test_w01_regional_forcing import box, definition, motion, planar, store_limits
from test_w03_thermal_support import MAT, SUPPORT


MODEL = CompactionParameters('w03-assembly', 'synthetic uncalibrated sediment',
                             .1, .02, 1e5, 1e8, 0., .8)
PLATE = PlateCoolingParameters(ThermalParameters('assembly-cooling', 'synthetic',
                                               300., 1300., 1e-6), 1e5, 3.3)
CONDITIONS = DrainedCompactionConditions('finite-water', 'saturated drained fixture',
                                        'water', 1000., 10.)
EDGES = np.array([0., 100., 1000., 10000., 100000.])
STEP = 1e12
SOLID_A = MaterialCohort('a', 'rock', 'solid-a', -100.)
SOLID_B = MaterialCohort('b', 'rock', 'solid-b', -50.)
FLUID = MaterialCohort('pore', 'water', 'shared-water', -100.)


def workflow_fixture(*, moving=False, mixed_units=False, distinct_fluids=False, cells=4,
                     length_m=4., width_m=2.):
    """Four 2 m2 planar columns, 69 m solid and 31 m pore equivalent thickness."""
    domain = box(x1=length_m, y1=width_m)
    net = build_boundary_network(domain, (BoundaryRegion('whole', 'A', domain),))
    sediments = (layer('upper', 'sediment', 40., .4, (LayerComponent('a', 1.),)),
                 layer('lower', 'sediment', 60., .25, (LayerComponent('b', 1.),)))
    layers = sediments + (layer('crust', 'crust', 29900., 0., (LayerComponent('a', 1.),)),
                         layer('mantle', 'lithospheric_mantle', 70000., 0., (LayerComponent('a', 1.),)))
    main = column('main', layers=layers, profile='initial', fluid_material_id='water')
    profile = ThermalInitialProfile('initial', 'synthetic', 'half_space',
        temperatures_k=(300., 1300.), diffusivity_m2_s=1e-6, cooling_start_time_s=0.)
    kwargs = dict(case_id='w03-assembly-fixture', topology=net, time_s=0., epoch_id='epoch',
        depth_reference_id='local-surface', source_id='synthetic', sources=(SOURCE,),
        materials=(replace(ROCK, density_kg_m3=2650.), WATER),
        cohorts=(CohortDescription(SOLID_A, 'synthetic'), CohortDescription(SOLID_B, 'synthetic')),
        thermal_profiles=(profile,), columns=(main,),
        provinces=(GeologicalProvince('background', 'main', SurfaceSelector('domain'), 'synthetic'),),
        precedence=FeaturePrecedence(('background',)))
    if mixed_units:
        # Identical amounts and thermal profile still do not authenticate parcel order.
        kwargs.update(columns=(main, replace(main, column_id='other')),
            geometries=(FeatureGeometry('right', box(x0=length_m/2, x1=length_m, y1=width_m), 'synthetic'),),
            provinces=kwargs['provinces']+(GeologicalProvince('other-province', 'other',
                SurfaceSelector('geometry', ('right',)), 'synthetic'),),
            precedence=FeaturePrecedence(('other-province', 'background')))
    source = initial(GeologicalCase(**kwargs))
    fluids = tuple(PoreFluidCohort(unit.unit_id,
        replace(FLUID, cohort_id='pore-'+str(i)) if distinct_fluids else FLUID, SOURCE)
        for i, unit in enumerate(source.units) if unit.layer.role == 'sediment')
    forcing = definition(net, (motion(translation=(1., 0., 0.) if moving else (0., 0., 0.)),),
                         duration_s=10*STEP)
    section = planar(origin_m=(0., width_m/2, 0.), length_m=length_m)
    reduction = RegionalReduction('planar-columns', 'frozen-at-start', SOURCE, width_m)
    support = RegionalColumnSupport('planar-strip', 0., 100., SOURCE)
    with PreparedRegionalWorkflow(source, forcing, section, reduction, RegionalGrid1D(cells, length_m),
            support, fluid_cohorts=fluids, backend='reference') as plan:
        return plan.initialise()


def initialise(workflow=None, **changes):
    kwargs = dict(subdivisions={'upper': 4, 'lower': 6},
        maximum_effective_stress_pa='normally-consolidated', top_effective_stress_pa=0.,
        conditions=CONDITIONS, reservoir_fluid_m3=100., cooling_model=PLATE,
        buoyancy_material=MAT, support_parameters=SUPPORT, depth_edges_m=EDGES,
        temperature_tolerance_k=1e-9)
    kwargs.update(changes)
    return initialise_w03_columns(workflow if workflow is not None else workflow_fixture(),
                                 'main', {'upper': MODEL, 'lower': MODEL}, **kwargs)


def cohort_row(state, cohort_id):
    i = next(i for i, cohort in enumerate(state.material.cohorts) if cohort.cohort_id == cohort_id)
    return state.material.thickness_m[i]


def pore_volume(state):
    return float(np.sum(state.compaction.grain_volume_m3*state.compaction.void_ratio))


class W03WorkflowTests(unittest.TestCase):
    def assert_accounts(self, state, total_water):
        measure = state.reference_width_m*state.material.grid.spacing_m
        assert_allclose(cohort_row(state, 'a'), np.full(4, 24.), rtol=0, atol=2e-13)
        assert_allclose(cohort_row(state, 'b'), np.full(4, 45.), rtol=0, atol=2e-13)
        assert_allclose(cohort_row(state, 'pore')*measure,
            np.sum(state.compaction.grain_volume_m3*state.compaction.void_ratio, axis=0),
            rtol=2e-14, atol=1e-12)
        self.assertAlmostEqual(state.reservoir_fluid_m3+pore_volume(state), total_water, places=10)
        self.assertEqual(state.material.time_s, state.compaction.time_s)
        self.assertEqual(state.time_s, state.material.time_s)
        assert_array_equal(state.compaction.area_m2, np.full(4, 2.))

    def test_initial_inventory_and_loaded_cooling_close_independent_accounts(self):
        original = initialise()
        assert_allclose(original.initial_bulk_thickness_m, 100., rtol=0, atol=1e-12)
        self.assertAlmostEqual(pore_volume(original), 248., places=10)
        self.assert_accounts(original, 348.)
        advanced = advance_w03_columns(original, time_s=STEP, top_effective_stress_pa=1e6)
        self.assert_accounts(advanced, 348.)
        self.assertGreater(advanced.reservoir_fluid_m3, original.reservoir_fluid_m3)
        assert_array_equal(advanced.compaction.grain_volume_m3, original.compaction.grain_volume_m3)
        diagnostic = advanced.thermal_diagnostics()
        T, heat, response = (diagnostic[k] for k in ('temperature_k', 'heat_j_m2', 'support_response'))
        self.assertEqual(T.shape, (4,)); self.assertEqual(heat.shape, (2,)); self.assertEqual(response.shape, (3,))
        self.assertTrue(np.all((T >= 300.) & (T <= 1300.)))
        self.assertLess(T[0], 1300.)
        deficit = float(np.dot(1300.-T, np.diff(EDGES)))
        assert_allclose(np.sum(heat), MAT.density_kg_m3*MAT.heat_capacity_j_kg_k*deficit,
                        rtol=3e-12, atol=1e-3)
        assert_allclose(diagnostic['net_heat_j_m2'], MAT.density_kg_m3*MAT.heat_capacity_j_kg_k*deficit,
                        rtol=3e-12, atol=1e-3)
        sheet = MAT.density_kg_m3*MAT.expansion_per_k*deficit
        assert_allclose(response, [sheet, 10*sheet, sheet/2300.], rtol=3e-12, atol=1e-9)
        before_id = advanced.state_id
        repeated = advanced.thermal_diagnostics()
        for key in diagnostic: assert_array_equal(repeated[key], diagnostic[key])
        self.assertEqual(advanced.state_id, before_id)

    def test_unload_reload_keep_peak_memory_and_irreversible_residual(self):
        initial_state = initialise()
        loaded = advance_w03_columns(initial_state, time_s=STEP, top_effective_stress_pa=1e6)
        unloaded = advance_w03_columns(loaded, time_s=2*STEP, top_effective_stress_pa=0.)
        reloaded = advance_w03_columns(unloaded, time_s=3*STEP, top_effective_stress_pa=1e6)
        for result in (loaded, unloaded, reloaded): self.assert_accounts(result, 348.)
        assert_array_equal(unloaded.compaction.maximum_effective_stress_pa,
                           loaded.compaction.maximum_effective_stress_pa)
        assert_allclose(reloaded.compaction.void_ratio, loaded.compaction.void_ratio, rtol=0, atol=3e-16)
        self.assertTrue(np.all(unloaded.compaction.void_ratio < initial_state.compaction.void_ratio))
        self.assertLess(unloaded.reservoir_fluid_m3, loaded.reservoir_fluid_m3)
        self.assertEqual(unloaded.compaction.parent_state_id, loaded.compaction.state_id)
        self.assertLess(float(np.sum(compaction_geometry(unloaded.compaction)['bulk_volume_m3'])), 800.)
        combined = evolve_w03_columns(initial_state, ((STEP, 1e6), (2*STEP, 0.), (3*STEP, 1e6)))
        self.assertEqual(combined.state_id, reloaded.state_id)
        with self.assertRaises(TectonicsError):
            evolve_w03_columns(initial_state, ((STEP, 1e6), (STEP, 0.)))

    def test_initial_thermal_boundary_model_and_support_mismatch_refuse(self):
        workflow = workflow_fixture()
        for changes in (
                {'cooling_model': replace(PLATE, thermal=replace(PLATE.thermal, surface_temperature_k=350.))},
                {'cooling_model': replace(PLATE, thermal=replace(PLATE.thermal, diffusivity_m2_s=2e-6))},
                {'cooling_model': replace(PLATE, thickness_m=2e5),
                 'depth_edges_m': [0., 100., 1000., 10000., 200000.]},
                {'temperature_tolerance_k': float('inf')},
                {'support_parameters': replace(SUPPORT, thermal_owner='flexure')},
                {'support_parameters': replace(SUPPORT, depth_reference_id='different-datum')},
                {'depth_edges_m': [0., 100., 1000.]}):
            with self.subTest(changes=changes), self.assertRaises(TectonicsError):
                initialise(workflow, **changes)

    def test_nonstationary_mixed_units_and_distinct_fluid_origins_refuse(self):
        for changes in ({'moving': True}, {'mixed_units': True}, {'distinct_fluids': True}):
            with self.subTest(changes=changes), self.assertRaises(TectonicsError):
                initialise(workflow_fixture(**changes))

    def test_insufficient_reservoir_and_invalid_clock_leave_parent_unchanged(self):
        original = initialise(top_effective_stress_pa=1e6, reservoir_fluid_m3=0.)
        material = original.material.thickness_m.copy()
        voids = original.compaction.void_ratio.copy(); original_id = original.state_id
        with self.assertRaisesRegex(TectonicsError, 'reservoir'):
            advance_w03_columns(original, time_s=STEP, top_effective_stress_pa=0.)
        for time in (0., -1.):
            with self.assertRaises(TectonicsError):
                advance_w03_columns(original, time_s=time, top_effective_stress_pa=1e6)
        assert_array_equal(original.material.thickness_m, material)
        assert_array_equal(original.compaction.void_ratio, voids)
        self.assertEqual(original.reservoir_fluid_m3, 0.)
        self.assertEqual(original.state_id, original_id)

    def test_budget_and_cancellation_refuse_without_partial_publication(self):
        workflow = workflow_fixture(); small = WorkBudget(16)
        with self.assertRaises(MemoryLimitError): initialise(workflow, budget=small)
        self.assertEqual(small.reserved_bytes, 0)
        flag = threading.Event(); flag.set()
        with self.assertRaises(CancelledError): initialise(workflow, cancel=flag)
        state = initialise(workflow); parent_id = state.state_id
        with self.assertRaises(MemoryLimitError):
            advance_w03_columns(state, time_s=STEP, top_effective_stress_pa=1e6, budget=small)
        with self.assertRaises(CancelledError):
            advance_w03_columns(state, time_s=STEP, top_effective_stress_pa=1e6, cancel=flag)
        self.assertEqual(state.state_id, parent_id)
        self.assertEqual(small.reserved_bytes, 0)

    def test_mixed_signed_exchange_retains_clock_and_both_material_receipts(self):
        original = initialise(top_effective_stress_pa=5e5)
        result = advance_w03_columns(original, time_s=STEP,
                                     top_effective_stress_pa=[1e6, 0., 1e6, 0.])
        self.assert_accounts(result, 348.)
        record = result.transition_record
        expected_out = np.sum(original.compaction.grain_volume_m3
                              *(original.compaction.void_ratio-result.compaction.void_ratio), axis=0)
        out = np.asarray(record['pore_fluid_out_m3'])
        assert_allclose(out, expected_out, rtol=2e-14, atol=1e-12)
        self.assertTrue(np.all(out[[0, 2]] > 0.))
        self.assertTrue(np.all(out[[1, 3]] < 0.))
        self.assertEqual(record['reservoir_before_m3'], original.reservoir_fluid_m3)
        self.assertEqual(record['reservoir_after_m3'], result.reservoir_fluid_m3)
        self.assertAlmostEqual(record['reservoir_after_m3']-record['reservoir_before_m3'],
                               float(np.sum(out)), places=11)
        receipts = record['material_receipts']
        self.assertEqual(len(receipts), 3)
        clock, removed, added = receipts
        self.assertEqual(clock['parent'], original.material.state_id)
        self.assertEqual(clock['duration_s'], STEP)
        self.assertEqual(clock['left']['mode'], 'closed')
        self.assertEqual(clock['right']['mode'], 'closed')
        self.assertEqual([r['event']['operation'] for r in (removed, added)], ['remove', 'add'])
        for r in (removed, added):
            self.assertEqual(r['operation'], 'material-transfer-v1')
            self.assertEqual(r['parent'], r['event']['parent_state_id'])
            self.assertEqual(r['event']['reservoir_id'], CONDITIONS.reservoir_id)
            self.assertEqual(r['event']['cohort']['cohort_id'], FLUID.cohort_id)
            self.assertEqual(r['event']['time_s'], STEP)
        self.assertNotEqual(removed['parent'], added['parent'])
        self.assertEqual(added['parent'], result.material.parent_state_id)
        self.assertAlmostEqual(removed['transfer_m2'], float(np.maximum(out, 0.).sum())/2., places=11)
        self.assertAlmostEqual(added['transfer_m2'], float(np.maximum(-out, 0.).sum())/2., places=11)

    def test_roundtrip_continuation_preserves_all_accounts_and_history(self):
        original = initialise()
        loaded = advance_w03_columns(original, time_s=STEP, top_effective_stress_pa=1e6)
        with tempfile.TemporaryDirectory() as directory:
            with ArrayStore(Path(directory)/'assembly.db', store_limits()) as store:
                save_w03_columns(loaded, store)
                self.assertTrue(store.contains(loaded.binding.workflow_id))
                restored = load_w03_columns(store, loaded.state_id)
                self.assertEqual(restored.state_id, loaded.state_id)
                self.assertEqual(restored.material.state_id, loaded.material.state_id)
                self.assertEqual(restored.compaction.state_id, loaded.compaction.state_id)
                self.assertEqual(restored.reservoir_fluid_m3, loaded.reservoir_fluid_m3)
                self.assertEqual(restored.transition_record, loaded.transition_record)
                assert_array_equal(restored.compaction.maximum_effective_stress_pa,
                                   loaded.compaction.maximum_effective_stress_pa)
                a = advance_w03_columns(loaded, time_s=2*STEP, top_effective_stress_pa=0.,
                    store=store, cache_policy=CachePolicy(mode='always'))
                b = advance_w03_columns(restored, time_s=2*STEP, top_effective_stress_pa=0.,
                    store=store, cache_policy=CachePolicy(mode='always'))
                self.assertEqual(a.state_id, b.state_id)
                self.assert_accounts(a, 348.); self.assert_accounts(b, 348.)
                assert_array_equal(a.material.thickness_m, b.material.thickness_m)
                assert_array_equal(a.compaction.void_ratio, b.compaction.void_ratio)
                for key, value in a.thermal_diagnostics().items():
                    assert_array_equal(value, b.thermal_diagnostics()[key])

    def test_selected_layer_and_grain_pore_contracts_are_explicit(self):
        workflow = workflow_fixture()
        for changes in ({'subdivisions': {'upper': 4}},
                        {'conditions': replace(CONDITIONS, pore_fluid_material_id='unknown-fluid')},
                        {'maximum_effective_stress_pa': np.zeros((10, 4))},
                        {'reservoir_fluid_m3': -1.}):
            with self.subTest(changes=changes), self.assertRaises(TectonicsError):
                initialise(workflow, **changes)


if __name__ == '__main__':
    unittest.main()
