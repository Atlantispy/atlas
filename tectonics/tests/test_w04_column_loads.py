"""Independent finite-column mass balances; no flexure or field calibration."""
from concurrent.futures import CancelledError
from dataclasses import FrozenInstanceError, replace
from decimal import Decimal, localcontext
import math
import threading
import unittest

import numpy as np
from numpy.testing import assert_allclose, assert_array_equal

from atlas_tectonics._validation import TectonicsError
from atlas_tectonics.column_loads import (
    LoadSupport, LoadPhase, ColumnLoadState, column_load_change,
)
from atlas_tectonics.constitutive import BoussinesqMaterial
from atlas_tectonics.resources import WorkBudget, MemoryLimitError


SOURCE = 'authored analytic fixture; arbitrary SI values, not Earth defaults'
GRAIN = LoadPhase('grain', 'sediment-grain', 8., SOURCE)
WATER = LoadPhase('pore', 'pore-water', 2., SOURCE)
MATERIAL = BoussinesqMaterial('load-fixture', SOURCE, 8., 3., 2., .001,
    100., 0., 0., (50., 150.), .1)
THERMAL = LoadPhase('thermal-rock', 'rock', 8., SOURCE, MATERIAL,
    'fixed homogeneous coverage, independently declared')


def support(areas=(5.,), heights=(2.,), **kwargs):
    defaults = dict(geometry_source='fixed-footprint-fixture', frame_id='frame',
                    datum_id='datum')
    defaults.update(kwargs)
    return LoadSupport(tuple('column-'+str(i) for i in range(len(areas))),
        areas, heights, **defaults)


def state(domain, volumes, fill=(2.,), phases=(GRAIN, WATER), **kwargs):
    defaults = dict(source_id='snapshot-fixture', epoch_id='epoch')
    defaults.update(kwargs)
    return ColumnLoadState(domain, phases, volumes, fill, **defaults)


class ColumnLoadBalanceTests(unittest.TestCase):
    def test_compaction_replaced_by_same_water_has_no_load(self):
        domain = support()
        reference = state(domain, [[3., 3.]])
        compacted = state(domain, [[3., 1.]])
        # Four kg of pore water leave; four kg occupy the newly opened gap.
        assert_allclose(column_load_change(reference, compacted, 2.),
            [[-.8, .8, 0., 0.]], rtol=0., atol=1e-15)

    def test_compaction_with_air_replacement_unloads(self):
        domain = support()
        reference = state(domain, [[3., 3.]], fill=(0.,))
        compacted = state(domain, [[3., 1.]], fill=(0.,))
        assert_allclose(column_load_change(reference, compacted, 2.),
            [[-.8, 0., 0., -1.6]], rtol=0., atol=1e-15)

    def test_deposition_erosion_and_explicit_absent_phase(self):
        domain = support()
        reference = state(domain, [[0., 0.]])
        deposited = state(domain, [[1., 0.]])
        expected = [[1.6, -.4, 0., 2.4]]
        assert_allclose(column_load_change(reference, deposited, 2.), expected,
            rtol=0., atol=1e-15)
        assert_allclose(column_load_change(deposited, reference, 2.),
            -np.asarray(expected), rtol=0., atol=1e-15)

    def test_fill_density_change_uses_finite_unoccupied_volume(self):
        domain = support()
        reference = state(domain, [[3., 3.]], fill=(2.,))
        changed = state(domain, [[3., 3.]], fill=(4.,))
        # Support volume 10, occupied 6: only the four-unit gap changes density.
        assert_allclose(column_load_change(reference, changed, 2.),
            [[0., 1.6, 0., 3.2]], rtol=0., atol=1e-15)
        full = state(domain, [[5., 5.]], fill=(2.,))
        full_changed = state(domain, [[5., 5.]], fill=(40.,))
        assert_array_equal(column_load_change(full, full_changed, 2.), [[0.]*4])

    def test_simultaneous_volume_and_fill_change_matches_total_mass_balance(self):
        domain = support((2., 4., 3.), (5., 3., 4.))
        old_v = np.array([[2., 1.], [5., 2.], [0., 2.]])
        new_v = np.array([[3., 2.], [1., 6.], [2., 0.]])
        old_f = np.array([1., 2., 3.]); new_f = np.array([4., 1., 0.])
        reference = state(domain, old_v, old_f)
        current = state(domain, new_v, new_f)
        expected = []
        # Independently sum absolute supported masses, rather than reproduce the
        # implementation's contrast/delta-volume arithmetic.
        for area, height, ov, nv, of, nf in zip(domain.area_m2, domain.height_m,
                old_v, new_v, old_f, new_f):
            old_mass = math.fsum((8.*ov[0], 2.*ov[1]))
            new_mass = math.fsum((8.*nv[0], 2.*nv[1]))
            old_fill = of*(area*height-math.fsum(ov))
            new_fill = nf*(area*height-math.fsum(nv))
            expected.append([(new_mass-old_mass)/area, (new_fill-old_fill)/area,
                0., 2.*((new_mass+new_fill)-(old_mass+old_fill))/area])
        assert_allclose(column_load_change(reference, current, 2., batch_columns=1),
            expected, rtol=2e-15, atol=2e-15)

    def test_self_reference_additivity_and_reversal(self):
        domain = support()
        a = state(domain, [[1., 3.]], fill=(1.,))
        b = state(domain, [[3., 2.]], fill=(4.,))
        c = state(domain, [[2., 5.]], fill=(2.,))
        ab = column_load_change(a, b, 2.)
        bc = column_load_change(b, c, 2.)
        ac = column_load_change(a, c, 2.)
        assert_array_equal(column_load_change(a, a, 2.), [[0.]*4])
        assert_allclose(ab+bc, ac, rtol=2e-15, atol=2e-15)
        assert_allclose(column_load_change(c, a, 2.), -ac, rtol=2e-15, atol=2e-15)

    def test_fixed_support_horizontal_and_phase_subdivision(self):
        whole = support((4.,), (3.,))
        reference = state(whole, [[2., 2.]])
        current = state(whole, [[4., 0.]])
        expected = column_load_change(reference, current, 2.)
        split = support((2., 2.), (3., 3.))
        a = state(split, [[1., 1.], [1., 1.]], fill=(2., 2.))
        b = state(split, [[2., 0.], [2., 0.]], fill=(2., 2.))
        actual = column_load_change(a, b, 2., batch_columns=1)
        assert_allclose(actual, np.repeat(expected, 2, axis=0), rtol=0., atol=0.)
        self.assertEqual(float(actual[:, 3]@split.area_m2),
            float(expected[:, 3]@whole.area_m2))
        phases = (replace(GRAIN, phase_id='grain-a'),
                  replace(GRAIN, phase_id='grain-b'), WATER)
        a = state(whole, [[1., 1., 2.]], phases=phases)
        b = state(whole, [[2., 2., 0.]], phases=phases)
        assert_array_equal(column_load_change(a, b, 2.), expected)

    def test_compensated_opposing_phase_loads_preserve_small_result(self):
        domain = support((1.,), (2e16,))
        phases = tuple(LoadPhase(label, 'other', 1., SOURCE)
                       for label in ('positive-large', 'small', 'negative-large'))
        a = state(domain, [[0., 0., 1e16]], fill=(0.,), phases=phases)
        b = state(domain, [[1e16, 1., 0.]], fill=(0.,), phases=phases)
        assert_array_equal(column_load_change(a, b, 2.), [[1., 0., 0., 2.]])


class ColumnLoadThermalTests(unittest.TestCase):
    def test_cooling_warming_and_no_inventory_update(self):
        domain = support((5.,), (4.,))
        a = state(domain, [[15.]], phases=(THERMAL,), temperature_k=[[100.]])
        b = state(domain, [[15.]], phases=(THERMAL,), temperature_k=[[95.]])
        before = (a.state_id, b.state_id, a.volume_m3.copy(), b.volume_m3.copy())
        actual = column_load_change(a, b, 2.)
        # rho0*alpha*5 K*3 m = .12 kg/m2; conserved mass remains unchanged.
        assert_allclose(actual, [[0., 0., .12, .24]], rtol=2e-15, atol=0.)
        assert_allclose(column_load_change(b, a, 2.), -actual, rtol=2e-15, atol=0.)
        assert_array_equal(column_load_change(a, a, 2.), [[0.]*4])
        self.assertEqual((a.state_id, b.state_id), before[:2])
        assert_array_equal(a.volume_m3, before[2]); assert_array_equal(b.volume_m3, before[3])

    def test_thermal_volume_means_and_phase_catalogue_order(self):
        domain = support((2.,), (4.,))
        second = replace(THERMAL, phase_id='thermal-two',
            thermal_coverage_source='second disjoint fixed region')
        phases = (THERMAL, WATER, second)
        a = state(domain, [[2., 1., 4.]], phases=phases, temperature_k=[[100., 100.]])
        b = state(domain, [[2., 1., 4.]], phases=phases, temperature_k=[[90., 105.]])
        # Equal/opposite integrated anomalies, despite unequal phase volumes.
        assert_array_equal(column_load_change(a, b, 2.), [[0.]*4])

    def test_thermal_range_anomaly_envelope_and_fixed_coverage_refuse(self):
        domain = support((5.,), (4.,))
        a = state(domain, [[15.]], phases=(THERMAL,), temperature_k=[[100.]])
        for temperature in (49., 151., math.nan):
            with self.subTest(temperature=temperature), self.assertRaises(TectonicsError):
                state(domain, [[15.]], phases=(THERMAL,), temperature_k=[[temperature]])
        tight = replace(THERMAL, thermal_material=replace(MATERIAL,
            max_relative_density_anomaly=.001))
        with self.assertRaises(TectonicsError):
            state(domain, [[15.]], phases=(tight,), temperature_k=[[95.]])
        moved = state(domain, [[14.]], phases=(THERMAL,), temperature_k=[[95.]])
        with self.assertRaisesRegex(TectonicsError, 'coverage'):
            column_load_change(a, moved, 2.)

    def test_thermal_density_basis_composition_and_unknown_coverage_refuse(self):
        for kwargs in (dict(density_kg_m3=7.),
                dict(thermal_material=replace(MATERIAL, composition_density_contrast_kg_m3=1.)),
                dict(thermal_coverage_source=None), dict(thermal_coverage_source='')):
            with self.subTest(kwargs=kwargs), self.assertRaises(TectonicsError):
                replace(THERMAL, **kwargs)
        with self.assertRaises(TectonicsError):
            replace(GRAIN, thermal_coverage_source='coverage-without-law')


class ColumnLoadContractTests(unittest.TestCase):
    def test_catalogue_frame_datum_and_coverage_mismatch_refuse(self):
        domain = support(); a = state(domain, [[3., 3.]])
        alternatives = [state(support(frame_id='different'), [[3., 3.]]),
            state(support(datum_id='different'), [[3., 3.]]),
            state(support(geometry_source='different-footprint'), [[3., 3.]]),
            state(support((4.,), (2.,)), [[3., 3.]]),
            state(domain, [[3., 3.]], phases=(replace(GRAIN, density_kg_m3=9.), WATER)),
            state(domain, [[3., 3.]], phases=(WATER, GRAIN))]
        for b in alternatives:
            with self.subTest(state=b.state_id), self.assertRaises(TectonicsError):
                column_load_change(a, b, 2.)

    def test_different_snapshot_epoch_labels_need_no_inferred_time_arithmetic(self):
        domain = support()
        a = state(domain, [[3., 3.]], epoch_id='reference-instant')
        b = state(domain, [[3., 3.]], epoch_id='current-instant')
        self.assertNotEqual(a.state_id, b.state_id)
        assert_array_equal(column_load_change(a, b, 2.), [[0.]*4])

    def test_capacity_shapes_nonfinite_negative_and_missing_temperature_refuse(self):
        domain = support()
        bad_states = [dict(volumes=[[6., 5.]]), dict(volumes=[3., 3.]),
            dict(volumes=[[3.], [3.]]), dict(volumes=[[-1., 3.]]),
            dict(volumes=[[math.nan, 3.]]), dict(volumes=np.ma.array([[3., 3.]])),
            dict(volumes=[[3., 3.]], fill=2.), dict(volumes=[[3., 3.]], fill=(-1.,)),
            dict(volumes=[[3., 3.]], fill=(math.inf,)),
            dict(volumes=[[3., 3.]], temperature_k=[[100.]]),
            dict(volumes=[[3.]], phases=(THERMAL,)),
            dict(volumes=[[3.]], phases=(THERMAL,), temperature_k=[100.]),
            dict(volumes=[[3., 3.]], phases=(GRAIN, GRAIN))]
        for kwargs in bad_states:
            with self.subTest(kwargs=kwargs), self.assertRaises(TectonicsError):
                state(domain, **kwargs)
        for areas, heights in (((0.,), (2.,)), ((5.,), (-1.,)),
                ((5.,), (math.inf,)), ((5.,), (2., 3.))):
            with self.subTest(areas=areas, heights=heights), self.assertRaises(TectonicsError):
                support(areas, heights)

    def test_inputs_snapshots_output_and_array_descriptors_are_independent(self):
        areas = np.array([5.]); heights = np.array([4.])
        domain = support(areas, heights)
        volumes = np.array([[15.]]); fills = np.array([2.]); temperatures = np.array([[100.]])
        a = state(domain, volumes, fills, phases=(THERMAL,), temperature_k=temperatures)
        identity = (domain.support_id, a.state_id)
        areas[:] = 99.; heights[:] = 99.; volumes[:] = 1.; fills[:] = 99.; temperatures[:] = 95.
        assert_array_equal(domain.area_m2, [5.]); assert_array_equal(domain.height_m, [4.])
        assert_array_equal(a.volume_m3, [[15.]]); assert_array_equal(a.fill_density_kg_m3, [2.])
        assert_array_equal(a.temperature_k, [[100.]])
        for array in (domain.area_m2, domain.height_m, a.volume_m3,
                a.fill_density_kg_m3, a.temperature_k, column_load_change(a, a, 2.)):
            with self.assertRaises(ValueError): array.setflags(write=True)
            with self.assertRaises(ValueError): array.flat[0] = 1.
            array.shape = (array.size,)
            array.dtype = np.uint8
        self.assertEqual(a.volume_m3.shape, (1, 1))
        self.assertEqual(a.temperature_k.dtype, np.dtype('float64'))
        self.assertEqual((domain.support_id, a.state_id), identity)
        with self.assertRaises(FrozenInstanceError): a.source_id = 'altered'
        with self.assertRaises(FrozenInstanceError): domain.frame_id = 'altered'

    def test_budget_admission_release_and_cancellation(self):
        tiny = WorkBudget(1)
        with self.assertRaises(MemoryLimitError): support(budget=tiny)
        domain = support((5., 5., 5.), (2., 2., 2.))
        with self.assertRaises(MemoryLimitError):
            state(domain, [[3., 3.]]*3, fill=(2.,)*3, budget=tiny)
        a = state(domain, [[3., 3.]]*3, fill=(2.,)*3)
        with self.assertRaises(MemoryLimitError): column_load_change(a, a, 2., budget=tiny)
        self.assertEqual(tiny.reserved_bytes, 0)
        budget = WorkBudget(1<<20)
        column_load_change(a, a, 2., budget=budget, batch_columns=1)
        self.assertEqual(budget.reserved_bytes, 0)
        event = threading.Event(); event.set()
        with self.assertRaises(CancelledError): column_load_change(a, a, 2., cancel=event, budget=budget)
        with self.assertRaises(CancelledError):
            state(domain, [[3., 3.]]*3, fill=(2.,)*3, cancel=event, budget=budget)

        class CancelDuringBatch:
            calls = 0
            def is_set(self):
                self.calls += 1
                return self.calls >= 3

        with self.assertRaises(CancelledError):
            column_load_change(a, a, 2., cancel=CancelDuringBatch(), budget=budget, batch_columns=1)
        self.assertEqual(budget.reserved_bytes, 0)
        assert_array_equal(a.volume_m3, [[3., 3.]]*3)

    def test_invalid_gravity_batch_and_arithmetic_overflow_refuse(self):
        domain = support(); a = state(domain, [[3., 3.]])
        for gravity in (0., -1., math.nan, math.inf):
            with self.subTest(gravity=gravity), self.assertRaises(TectonicsError):
                column_load_change(a, a, gravity)
        for batch in (0, -1, True, 1.5):
            with self.subTest(batch=batch), self.assertRaises(TectonicsError):
                column_load_change(a, a, 2., batch_columns=batch)
        enormous = LoadPhase('enormous', 'other', 1e308, SOURCE)
        a = state(domain, [[0.]], phases=(enormous,), fill=(0.,))
        b = state(domain, [[10.]], phases=(enormous,), fill=(0.,))
        with self.assertRaises(TectonicsError): column_load_change(a, b, 2.)

    def test_extreme_scaling_never_silently_erases_representable_load(self):
        # An explicit refusal is valid outside the numerical envelope. A zero
        # result is not: Decimal confirms the final physical sheet is nonzero.
        tiny = float(np.nextafter(0., 1.))
        enormous = LoadPhase('dense', 'other', 1e300, SOURCE)
        domain = support((2.,), (1.,))
        a = state(domain, [[0.]], phases=(enormous,), fill=(0.,))
        b = state(domain, [[tiny]], phases=(enormous,), fill=(0.,))
        with localcontext() as context:
            context.prec = 90
            expected = float(Decimal.from_float(tiny)*Decimal.from_float(1e300)/Decimal(2))
        try:
            result = column_load_change(a, b, 1.)
        except TectonicsError:
            pass
        else:
            assert_allclose(result[0, [0, 3]], [expected, expected], rtol=2e-14, atol=0.)
        temperature = 1e-308; next_temperature = float(np.nextafter(temperature, math.inf))
        material = replace(MATERIAL, density_kg_m3=1e300, expansion_per_k=1.,
            reference_temperature_k=temperature, temperature_range_k=(temperature, next_temperature))
        phase = replace(THERMAL, density_kg_m3=1e300, thermal_material=material)
        domain = support((1.,), (1.,))
        a = state(domain, [[.5]], phases=(phase,), temperature_k=[[next_temperature]], fill=(0.,))
        b = state(domain, [[.5]], phases=(phase,), temperature_k=[[temperature]], fill=(0.,))
        with localcontext() as context:
            context.prec = 90
            delta = Decimal.from_float(next_temperature)-Decimal.from_float(temperature)
            expected = float(delta*Decimal.from_float(1e300)/Decimal(2))
        try:
            result = column_load_change(a, b, 1.)
        except TectonicsError:
            pass
        else:
            assert_allclose(result[0, [2, 3]], [expected, expected], rtol=2e-14, atol=0.)


if __name__ == '__main__':
    unittest.main()
