"""Solid-coordinate controls, not field-calibrated sediment acceptance."""
from concurrent.futures import CancelledError
from dataclasses import replace
import math
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

import numpy as np
from numpy.testing import assert_allclose, assert_array_equal

from atlas_tectonics import (CompactionParameters, GrainComponent, CompactionParcel,
    DrainedCompactionConditions, CompactionState, compaction_geometry, advance_compaction,
    compaction_from_geological_column, save_compaction_state, load_compaction_state,
    MaterialCohort, TectonicsError, MaterialVolumeBasis, GeologicalCase)
from atlas_tectonics.reuse import cached_compaction_response, ReuseController, CachePolicy
from atlas_tectonics.resources import WorkBudget, MemoryLimitError
from atlas_tectonics.storage import ArrayStore, StoreLimits
from test_w01_initial_sampling import initial
from test_w01_geological_description import ingredients, column, layer, ROCK, WATER


MODEL = CompactionParameters('test', 'synthetic, not Earth calibration', .1, .02, 1e5, 1e8, 0., .8)
GRAIN = GrainComponent(MaterialCohort('grain', 'quartz-test', 'origin', None), 1., 2650., 'synthetic')
CONDITIONS = DrainedCompactionConditions('reservoir', 'known saturated drained limit', 'water', 1000., 10.)


def state(count=16, columns=1, model=MODEL, **changes):
    args = dict(area_m2=1., top_effective_stress_pa=0., conditions=CONDITIONS,
                time_s=0., epoch_id='test', depth_reference_id='sediment-top', source_state_id='analytic')
    args.update(changes)
    parcels = tuple(CompactionParcel(str(i), 'synthetic', (GRAIN,), model) for i in range(count))
    return CompactionState(parcels, np.full((count, columns), 100./count), np.full((count, columns), .8),
                           'normally-consolidated', **args)


def advance(s, area, time, **changes):
    args = dict(area_m2=area, top_effective_stress_pa=0., time_s=time, epoch_id=s.epoch_id,
                available_reservoir_fluid_m3=100.)
    args.update(changes)
    return advance_compaction(s, **args)


def mean_log(area):
    # Independent analytic antiderivative in the continuous solid coordinate.
    a = 1e5; b = (2650.-1000.)*10.*100./area
    return (1+a/b)*math.log1p(b/a)-1.


class CompactionColumnsTests(unittest.TestCase):
    def test_conservation_area_cycle_and_fluid_mass_account(self):
        s = state(32); before = compaction_geometry(s)
        result = advance(s, .5, 1.); after = compaction_geometry(result.state)
        assert_array_equal(s.grain_volume_m3, result.state.grain_volume_m3)
        assert_array_equal(before['grain_mass_kg'], after['grain_mass_kg'])
        self.assertIs(s._grain, result.state._grain)
        self.assertTrue(np.all(result.state.void_ratio < s.void_ratio))
        self.assertTrue(np.all(result.pore_fluid_out_m3 > 0))
        assert_allclose(np.sum(before['pore_volume_m3']-after['pore_volume_m3'], axis=0), result.pore_fluid_out_m3, atol=1e-13)
        assert_allclose(result.pore_fluid_out_kg, result.pore_fluid_out_m3*1000, rtol=2e-15)
        assert_allclose(after['bulk_volume_m3'], s.grain_volume_m3+after['pore_volume_m3'], rtol=2e-15)
        assert_allclose(after['bulk_thickness_m']*.5, after['bulk_volume_m3'], rtol=2e-15)
        un = advance(result.state, 1., 2.); geometry = compaction_geometry(un.state)
        self.assertLess(float(np.sum(geometry['bulk_thickness_m'])), 180.)
        self.assertLess(float(un.pore_fluid_out_m3[0]), 0.)
        assert_array_equal(un.state.maximum_effective_stress_pa, result.state.maximum_effective_stress_pa)
        reloaded = advance(un.state, .5, 3.)
        assert_allclose(reloaded.state.void_ratio, result.state.void_ratio, rtol=0, atol=2e-16)
        self.assertEqual(un.state.parent_state_id, result.state.state_id)

    def test_midpoint_refinement_against_continuous_integral(self):
        expected = 200.*(1.8-.1*(mean_log(.5)-mean_log(1.)))
        returned = 100.*(1.8-.08*(mean_log(.5)-mean_log(1.)))
        self.assertAlmostEqual(expected, 348.0489533306557, places=10)
        errors = []
        for n in (32, 64, 128):
            compacted = advance(state(n), .5, 1.)
            value = float(np.sum(compaction_geometry(compacted.state)['bulk_thickness_m']))
            errors.append(abs(value-expected))
        for old, new in zip(errors, errors[1:]):
            self.assertGreater(old/new, 3.5)
            self.assertLess(old/new, 4.1)
        unloaded = advance(compacted.state, 1., 2.)
        self.assertLess(abs(float(np.sum(compaction_geometry(unloaded.state)['bulk_thickness_m']))-returned), .002)

    def test_zero_compaction_and_multiple_column_area_account(self):
        model = replace(MODEL, compression_slope_ln=0., rebound_slope_ln=0.)
        s = state(4, columns=3, model=model)
        result = advance(s, [.5, 1., 2.], 1.)
        assert_array_equal(result.state.void_ratio, s.void_ratio)
        assert_array_equal(result.pore_fluid_out_m3, [0., 0., 0.])
        assert_allclose(np.sum(compaction_geometry(result.state)['bulk_thickness_m'], axis=0), [360., 180., 90.])
        # Array descriptor mutation cannot mutate the owning state.
        view = result.state.void_ratio; view.shape = (12,)
        self.assertEqual(result.state.void_ratio.shape, (4, 3))
        with self.assertRaises(ValueError): result.state.void_ratio.setflags(write=True)

    def test_explicit_grain_mixture_keeps_cohort_inventories(self):
        other = GrainComponent(MaterialCohort('second', 'dense', 'origin2', -1.), .75, 3000., 'synthetic')
        mixture = (replace(GRAIN, solid_volume_fraction=.25), other)
        parcel = CompactionParcel('mixture', 'synthetic', mixture, MODEL)
        s = CompactionState((parcel,), [[50.]], [[.8]], 'normally-consolidated', area_m2=2.,
            top_effective_stress_pa=100., conditions=CONDITIONS, time_s=0., epoch_id='test',
            depth_reference_id='top', source_state_id='authored')
        result = advance(s, 1., 1.)
        self.assertEqual(result.state.parcels[0].components, mixture)
        self.assertEqual(parcel.grain_density_kg_m3, .25*2650+.75*3000)
        assert_array_equal(compaction_geometry(s)['grain_mass_kg'], compaction_geometry(result.state)['grain_mass_kg'])

    def test_water_history_frame_budget_and_cancellation_refuse(self):
        s = state(); compacted = advance(s, .5, 1.).state
        with self.assertRaisesRegex(TectonicsError, 'reservoir fluid'):
            advance(compacted, 1., 2., available_reservoir_fluid_m3=0.)
        for changes in ({'epoch_id': 'wrong'}, {'time_s': 0.}, {'area_m2': 0.}, {'top_effective_stress_pa': -1.}):
            with self.assertRaises(TectonicsError): advance(s, 1., 1., **changes)
        budget = WorkBudget(16)
        with self.assertRaises(MemoryLimitError): advance(s, 1., 1., budget=budget)
        self.assertEqual(budget.reserved_bytes, 0)
        flag = threading.Event(); flag.set()
        with self.assertRaises(CancelledError): advance(s, 1., 1., cancel=flag)
        with self.assertRaises(TectonicsError):
            CompactionState(s.parcels, s.grain_volume_m3, s.void_ratio, np.zeros(s.shape),
                area_m2=1., top_effective_stress_pa=0., conditions=CONDITIONS, time_s=0., epoch_id='test',
                depth_reference_id='top', source_state_id='bad')

    def test_cache_hits_parameter_and_history_invalidation(self):
        with tempfile.TemporaryDirectory() as folder:
            with ArrayStore(Path(folder)/'cache.db', StoreLimits(1024, 1<<20, 8<<20, 4096)) as store:
                control = ReuseController()
                cached_compaction_response(.8, 0., 0., 1e6, MODEL, store=store, controller=control)
                self.assertEqual(store.statistics()['snapshots'], 0)
                kw = dict(store=store, controller=control, cache_policy=CachePolicy(mode='always'))
                a = cached_compaction_response(.8, 0., 0., 1e6, MODEL, **kw)
                b = cached_compaction_response(.8, 0., 0., 1e6, MODEL, **kw)
                assert_array_equal(a, b)
                self.assertEqual(control.statistics()['hits'], 1)
                self.assertEqual(control.statistics()['writes'], 1)
                history = cached_compaction_response(.8, 0., 2e6, 1e6, MODEL, **kw)
                self.assertGreater(history[0], a[0])
                law = cached_compaction_response(.8, 0., 0., 1e6, replace(MODEL, compression_slope_ln=.05), **kw)
                self.assertGreater(law[0], a[0])
                with patch('atlas_tectonics.compaction.compaction_response', side_effect=AssertionError('changed code')):
                    with self.assertRaises((TectonicsError, AssertionError)):
                        cached_compaction_response(.8, 0., 0., 1e6, MODEL, **kw)

    def test_history_roundtrip_then_same_continuation(self):
        s = advance(state(4), .5, 1.).state
        with tempfile.TemporaryDirectory() as folder:
            with ArrayStore(Path(folder)/'state.db', StoreLimits(1024, 1<<20, 8<<20, 65536)) as store:
                save_compaction_state(s, store)
                loaded = load_compaction_state(store, s.state_id)
                self.assertEqual(loaded.state_id, s.state_id)
                assert_array_equal(loaded.maximum_effective_stress_pa, s.maximum_effective_stress_pa)
                a = advance(s, 1., 2.); b = advance(loaded, 1., 2.)
                self.assertEqual(a.state.state_id, b.state.state_id)
                assert_array_equal(a.pore_fluid_out_m3, b.pore_fluid_out_m3)

    def test_reservoir_is_one_shared_stock_not_broadcast_stock(self):
        compacted = advance(state(8, columns=2), .5, 1.).state
        demand = -advance(compacted, 1., 2.).pore_fluid_out_m3
        # Enough for either column alone, but insufficient for both together.
        with self.assertRaisesRegex(TectonicsError, 'reservoir fluid'):
            advance(compacted, 1., 2., available_reservoir_fluid_m3=float(1.5*demand[0]))
        complete = advance(compacted, 1., 2., available_reservoir_fluid_m3=float(2.1*demand[0]))
        self.assertTrue(np.all(complete.pore_fluid_out_m3 < 0))

    def test_shapes_and_metadata_are_admitted_before_copy(self):
        s = state(1)
        huge = np.broadcast_to(1., (1000000,))
        args = dict(area_m2=1., top_effective_stress_pa=0., conditions=CONDITIONS,
            time_s=0., epoch_id='test', depth_reference_id='top', source_state_id='synthetic')
        with patch('atlas_tectonics.compaction_columns.snapshot', side_effect=AssertionError('copied too early')):
            with self.assertRaises(TectonicsError):
                CompactionState(s.parcels, [[1.]], huge, 'normally-consolidated', **args)
            with self.assertRaises(TectonicsError):
                CompactionState(s.parcels, [[1.]], [[.8]], huge, **args)
            with self.assertRaises(TectonicsError):
                CompactionState(s.parcels, [[1.]], [[.8]], 'normally-consolidated', **{**args, 'area_m2': huge})
            parcel = replace(s.parcels[0], source_id='x'*100000)
            with self.assertRaises(MemoryLimitError):
                CompactionState((parcel,), [[1.]], [[.8]], 'normally-consolidated', budget=WorkBudget(1<<20), **args)


class GeologicalCompactionImportTests(unittest.TestCase):
    def source(self, phi=.4):
        args = ingredients()
        args.update(materials=(ROCK, WATER), columns=(column(layers=(layer('sediment', 'sediment', 10., phi),
            layer()), fluid_material_id='water'),))
        return initial(GeologicalCase(**args))

    def test_source_bound_sediment_grain_water_and_history(self):
        source = self.source()
        result = compaction_from_geological_column(source, 'continental', {'sediment': MODEL},
            subdivisions={'sediment': 4}, area_m2=2., top_effective_stress_pa=0.,
            maximum_effective_stress_pa='normally-consolidated', conditions=CONDITIONS)
        self.assertEqual(result.source_state_id, source.state_id)
        self.assertEqual(result.epoch_id, source.case.epoch_id)
        assert_allclose(np.sum(result.grain_volume_m3), 12.)
        assert_allclose(np.sum(compaction_geometry(result)['pore_volume_m3']), 8.)
        self.assertEqual(result.parcels[0].components[0].cohort.cohort_id, 'old')
        self.assertEqual(source.case.column('continental').layers[0].bulk_thickness_m, 10.)

    def test_unknown_porosity_bulk_reference_and_wrong_fluid_refuse(self):
        kwargs = dict(subdivisions={'sediment': 2}, area_m2=1., top_effective_stress_pa=0.,
            maximum_effective_stress_pa='normally-consolidated', conditions=CONDITIONS)
        with self.assertRaisesRegex(TectonicsError, 'unknown porosity'):
            compaction_from_geological_column(self.source(None), 'continental', {'sediment': MODEL}, **kwargs)
        source = self.source(0.)
        bound = initial(source.case, material_bases=(MaterialVolumeBasis('rock', 'bulk_reference', 'synthetic'),
                                                   MaterialVolumeBasis('water', 'fluid', 'synthetic')))
        with self.assertRaisesRegex(TectonicsError, 'true grain'):
            compaction_from_geological_column(bound, 'continental', {'sediment': MODEL}, **kwargs)
        kwargs['conditions'] = replace(CONDITIONS, pore_fluid_density_kg_m3=1030.)
        with self.assertRaisesRegex(TectonicsError, 'fluid density'):
            compaction_from_geological_column(source, 'continental', {'sediment': MODEL}, **kwargs)


if __name__ == '__main__':
    unittest.main()
