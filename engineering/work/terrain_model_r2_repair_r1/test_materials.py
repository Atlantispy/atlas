"""Predeclared synthetic algebra/conservation fixtures, not field calibration.

Frozen before the first test run: mass atol1e-12kg/rtol5e-13;
volume atol1e-15m3/rtol5e-13; numerical scalar comparison uses the same rtol
and an explicitly unit-labelled absolute tolerance in each call. Analytical
limits and split-step equality are verification, not independent field holdout.
"""
from copy import deepcopy
from dataclasses import asdict, FrozenInstanceError, replace
import json
import math
import unittest

import materials as m


def soil_parameters(**changes):
    base = dict(bare_rate_m_per_year=.002, cover_scale_m=.4,
                rock_grain_density_kg_m3=2600, rock_porosity=0,
                regolith_grain_density_kg_m3=2600, regolith_porosity=.5,
                mobile_grain_density_kg_m3=2600, mobile_porosity=.5,
                dissolved_rock_fraction=0, mobile_fraction_of_retained_solids=1,
                evidence_id="SYNTHETIC_NUMERICAL_FIXTURE_NOT_DIADEM")
    return m.SoilProductionParameters(**{**base, **changes})


def dissolution_parameters(**changes):
    return m.DissolutionParameters(**{
        **dict(mineral="gypsum_linear_film", transfer_coefficient_m_per_year=.2,
               equilibrium_rock_equivalent_kg_m3=2., minimum_saturation=0.,
               maximum_saturation=.9, grain_density_kg_m3=2300.,
               evidence_id="SYNTHETIC_NUMERICAL_FIXTURE_NOT_GYPSUM_CALIBRATION"), **changes})


def organic_parameters(**changes):
    return m.OrganicParameters(**{
        **dict(input_dry_organic_kg_m2_per_year=.05, input_dry_mineral_kg_m2_per_year=0.,
               decay_per_year=.0001, organic_grain_density_kg_m3=1400.,
               mineral_grain_density_kg_m3=2600., evidence_id="SYNTHETIC_CATOTELM_SCENARIO"), **changes})


class MaterialTests(unittest.TestCase):
    def near(self, actual, expected, atol=1e-12):
        self.assertTrue(math.isfinite(actual))
        self.assertLessEqual(abs(actual-expected), atol + 5e-13*max(abs(actual), abs(expected)))

    def soil(self, p=None, **changes):
        return m.soil_production_step(**{**dict(area_m2=10., rock_available_kg=1e6,
            regolith_kg=0., mobile_kg=2600., duration_years=100.,
            parameters=p or soil_parameters()), **changes})

    def dissolve(self, p=None, **changes):
        return m.dissolution_step(**{**dict(rock_available_kg=1000., water_m3=10.,
            dissolved_rock_input_kg=0., reactive_area_m2=10., duration_years=.5,
            parameters=p or dissolution_parameters()), **changes})

    def organic(self, p=None, **changes):
        return m.organic_step(**{**dict(area_m2=10., organic_kg=100., mineral_kg=20.,
            void_ratio=4., external_water_m3=10., duration_years=100.,
            parameters=p or organic_parameters()), **changes})

    def compact(self, p=None, **changes):
        return m.compact_saturated_column(**{**dict(area_m2=10., solid_volume_m3=2.,
            void_ratio=4., effective_stress_before_pa=1000., effective_stress_after_pa=10000.,
            parameters=p or m.CompactionParameters(1., 1000., 100000., "SYNTHETIC_EOP")), **changes})

    def test_soil_closed_column_independent_integral(self):
        r = self.soil()
        h0 = .2
        # exp(h/L) grows linearly; independently solve final h then density ratio.
        h1 = .4*math.log(math.exp(h0/.4) + 2*.002*100/.4)
        expected_lowering = (h1-h0)/2
        self.near(r.bedrock_lowering_m, expected_lowering, 1e-14)
        self.near(r.rock_consumed_kg, expected_lowering*10*2600)
        self.near(r.surface_change_m, expected_lowering, 1e-14)
        self.assertFalse(r.limited_by_available_rock)

    def test_soil_density_porosity_and_partition_close(self):
        r = self.soil(soil_parameters(dissolved_rock_fraction=.25,
                                     mobile_fraction_of_retained_solids=.4))
        self.near(r.dissolved_rock_produced_kg, .25*r.rock_consumed_kg)
        self.near(r.mobile_produced_kg, .4*.75*r.rock_consumed_kg)
        self.near(r.regolith_produced_kg, .6*.75*r.rock_consumed_kg)
        self.near(r.rock_consumed_kg, r.regolith_produced_kg+r.mobile_produced_kg+r.dissolved_rock_produced_kg)
        self.near(r.mobile_bulk_added_m3, 2*r.mobile_solid_added_m3, 1e-15)
        self.near(r.rock_mass_residual_kg, 0.)

    def test_soil_available_rock_cap(self):
        r = self.soil(rock_available_kg=1.)
        self.assertEqual(r.rock_consumed_kg, 1.)
        self.assertEqual(r.rock_remaining_kg, 0.)
        self.assertTrue(r.limited_by_available_rock)

    def test_soil_zero_duration_zero_rate_zero_rock(self):
        for changes, p in (({"duration_years": 0}, None), ({"rock_available_kg": 0}, None),
                           ({}, soil_parameters(bare_rate_m_per_year=0))):
            with self.subTest(changes=changes):
                r = self.soil(p, **changes)
                self.assertEqual(r.rock_consumed_kg, 0)
                self.assertEqual(r.surface_change_m, 0)

    def test_soil_all_dissolved_limit(self):
        r = self.soil(soil_parameters(dissolved_rock_fraction=1))
        self.near(r.bedrock_lowering_m, .002*math.exp(-.2/.4)*100, 1e-14)
        self.assertEqual(r.regolith_produced_kg, 0)
        self.assertEqual(r.mobile_produced_kg, 0)
        self.near(r.surface_change_m, -r.bedrock_lowering_m, 1e-14)

    def test_soil_cover_and_supply_sensitivity(self):
        self.assertLess(self.soil(mobile_kg=5200).rock_consumed_kg, self.soil().rock_consumed_kg)
        self.assertGreater(self.soil(soil_parameters(bare_rate_m_per_year=.004)).rock_consumed_kg,
                           self.soil().rock_consumed_kg)
        immobile = self.soil(regolith_kg=2600, mobile_kg=0)
        self.near(immobile.rock_consumed_kg, self.soil().rock_consumed_kg)

    def test_soil_split_interval_semigroup(self):
        p = soil_parameters(dissolved_rock_fraction=.2, mobile_fraction_of_retained_solids=.6)
        whole = self.soil(p)
        first = self.soil(p, duration_years=40)
        second = self.soil(p, duration_years=60, rock_available_kg=first.rock_remaining_kg,
                           regolith_kg=first.regolith_after_kg, mobile_kg=first.mobile_after_kg)
        self.near(whole.rock_consumed_kg, first.rock_consumed_kg+second.rock_consumed_kg)
        self.near(whole.mobile_after_kg, second.mobile_after_kg)

    def test_dissolution_independent_half_deficit(self):
        r = self.dissolve(duration_years=math.log(2)/.2)
        self.near(r.rock_consumed_kg, 10.)
        self.near(r.concentration_after_kg_m3, 1.)
        self.assertEqual(r.carrier_water_input_m3, r.carrier_water_output_m3)
        self.near(r.rock_mass_residual_kg, 0.)

    def test_carbonate_and_gypsum_parameters_not_interchangeable(self):
        p = dissolution_parameters(mineral="calcite_linear_region_2", minimum_saturation=.36)
        r = self.dissolve(p, dissolved_rock_input_kg=10., duration_years=math.log(2)/.2)
        self.near(r.dissolved_rock_output_kg, 15.)
        with self.assertRaises(m.MaterialError):
            self.dissolve(p)  # Fresh water is outside this carbonate branch.
        with self.assertRaises(m.MaterialError):
            dissolution_parameters(mineral="halite")

    def test_dissolution_available_material_and_input_export(self):
        r = self.dissolve(rock_available_kg=.01, dissolved_rock_input_kg=2)
        self.assertEqual(r.rock_consumed_kg, .01)
        self.near(r.dissolved_rock_output_kg, 2.01)
        self.assertTrue(r.limited_by_available_rock)
        self.near(r.rock_solid_removed_m3, .01/2300, 1e-15)

    def test_dissolution_zero_water_contact_rate_or_duration(self):
        for changes in ({"water_m3": 0}, {"reactive_area_m2": 0}, {"duration_years": 0},
                        {"rock_available_kg": 0}):
            self.assertEqual(self.dissolve(**changes).rock_consumed_kg, 0)
        self.assertEqual(self.dissolve(dissolution_parameters(transfer_coefficient_m_per_year=0)).rock_consumed_kg, 0)
        with self.assertRaises(m.MaterialError):
            self.dissolve(water_m3=0, dissolved_rock_input_kg=1)

    def test_dissolution_regime_crossing_fails_not_clipped(self):
        for changes in ({"duration_years": 100}, {"dissolved_rock_input_kg": 20},
                        {"dissolved_rock_input_kg": 21}):
            with self.assertRaises(m.MaterialError):
                self.dissolve(**changes)

    def test_dissolution_surface_contact_and_chemistry_sensitivity(self):
        r = self.dissolve()
        self.assertGreater(self.dissolve(reactive_area_m2=20).rock_consumed_kg, r.rock_consumed_kg)
        self.assertLess(self.dissolve(dissolved_rock_input_kg=5).rock_consumed_kg, r.rock_consumed_kg)

    def test_dissolution_split_interval_exact_solution(self):
        whole = self.dissolve()
        first = self.dissolve(duration_years=.2)
        second = self.dissolve(duration_years=.3, rock_available_kg=first.rock_remaining_kg,
                               dissolved_rock_input_kg=first.dissolved_rock_output_kg)
        self.near(whole.dissolved_rock_output_kg, second.dissolved_rock_output_kg)

    def test_organic_independent_constant_input_solution(self):
        r = self.organic()
        equilibrium = .05*10/.0001
        expected = equilibrium + (100-equilibrium)*math.exp(-.0001*100)
        self.near(r.organic_after_kg, expected)
        self.near(100+50, r.organic_after_kg+r.decomposed_organic_origin_kg)
        self.near(r.pore_water_before_m3+10, r.pore_water_after_m3+r.water_output_m3, 1e-15)

    def test_organic_no_decay_zero_input_and_equilibrium(self):
        no_decay = self.organic(organic_parameters(decay_per_year=0))
        self.assertEqual(no_decay.organic_after_kg, 150)
        self.assertEqual(no_decay.decomposed_organic_origin_kg, 0)
        no_input = self.organic(organic_parameters(input_dry_organic_kg_m2_per_year=0))
        self.near(no_input.organic_after_kg, 100*math.exp(-.01))
        self.near(self.organic(organic_kg=5000).organic_after_kg, 5000)

    def test_organic_zero_duration_and_mineral_supply(self):
        r = self.organic(duration_years=0)
        self.assertEqual(r.organic_after_kg, 100)
        self.assertEqual(r.organic_input_kg, 0)
        r = self.organic(organic_parameters(input_dry_mineral_kg_m2_per_year=.1))
        self.assertEqual(r.mineral_after_kg, 120)
        self.near(r.mineral_mass_residual_kg, 0)

    def test_organic_split_interval_semigroup(self):
        first = self.organic(duration_years=40)
        second = self.organic(duration_years=60, organic_kg=first.organic_after_kg,
                              mineral_kg=first.mineral_after_kg)
        whole = self.organic()
        self.near(whole.organic_after_kg, second.organic_after_kg)
        self.near(whole.decomposed_organic_origin_kg,
                  first.decomposed_organic_origin_kg+second.decomposed_organic_origin_kg)

    def test_organic_requires_saturation_water_supply(self):
        with self.assertRaises(m.MaterialError):
            self.organic(external_water_m3=0)
        r = self.organic(organic_parameters(input_dry_organic_kg_m2_per_year=0), external_water_m3=0)
        self.assertGreater(r.water_output_m3, 0)

    def test_organic_decomposition_sensitivity(self):
        r = self.organic(organic_parameters(decay_per_year=.001))
        self.assertLess(r.organic_after_kg, self.organic().organic_after_kg)
        self.assertGreater(r.decomposed_organic_origin_kg, self.organic().decomposed_organic_origin_kg)

    def test_organic_short_interval_stable_mass(self):
        r = self.organic(duration_years=1e-9)
        self.assertGreater(r.decomposed_organic_origin_kg, 0)
        self.assertGreaterEqual(r.organic_after_kg, 0)
        self.near(r.organic_mass_residual_kg, 0)

    def test_compaction_independent_decade_loading(self):
        r = self.compact()
        self.assertEqual(r.void_ratio_after, 3)
        self.assertEqual(r.solid_volume_m3, 2)
        self.assertEqual(r.bulk_volume_before_m3, 10)
        self.assertEqual(r.bulk_volume_after_m3, 8)
        self.assertEqual(r.expelled_water_m3, 2)
        self.near(r.settlement_m, .2, 1e-15)

    def test_compaction_no_stress_change_and_no_solids(self):
        r = self.compact(effective_stress_after_pa=1000)
        self.assertEqual(r.settlement_m, 0)
        self.assertEqual(r.void_ratio_after, 4)
        self.assertEqual(self.compact(solid_volume_m3=0).expelled_water_m3, 0)

    def test_compaction_monotonic_and_split_load(self):
        r = self.compact(effective_stress_after_pa=100000)
        self.assertGreater(r.settlement_m, self.compact().settlement_m)
        first = self.compact()
        second = self.compact(void_ratio=first.void_ratio_after,
                              effective_stress_before_pa=10000, effective_stress_after_pa=100000)
        self.near(r.settlement_m, first.settlement_m+second.settlement_m, 1e-15)
        self.assertEqual(r.void_ratio_after, second.void_ratio_after)

    def test_compaction_unsupported_loading_fails(self):
        for changes in ({"effective_stress_after_pa": 500}, {"effective_stress_before_pa": 0},
                        {"effective_stress_after_pa": 200000}, {"void_ratio": .1}):
            with self.assertRaises(m.MaterialError):
                self.compact(**changes)

    def test_saturated_organic_then_compaction_water_ledger(self):
        grown = self.organic()
        compacted = self.compact(solid_volume_m3=grown.solid_volume_after_m3)
        self.near(grown.pore_water_before_m3+10,
                  compacted.pore_water_after_m3+grown.water_output_m3+compacted.expelled_water_m3, 1e-15)
        self.near(compacted.solid_volume_m3, grown.solid_volume_after_m3, 1e-15)

    def test_parameter_invalid_numbers_all_fields(self):
        all_parameters = (soil_parameters(), dissolution_parameters(), organic_parameters(),
                          m.CompactionParameters(1, 1000, 100000, "SYNTHETIC"))
        for p in all_parameters:
            for field, value in asdict(p).items():
                if isinstance(value, str):
                    with self.subTest(field=field), self.assertRaises(m.MaterialError):
                        replace(p, **{field: ""})
                    continue
                for invalid in (True, "1", -1, math.inf, math.nan, 10**1000):
                    with self.subTest(cls=type(p).__name__, field=field, invalid=str(invalid)[:20]), self.assertRaises(m.MaterialError):
                        replace(p, **{field: invalid})

    def test_fraction_density_and_regime_bounds(self):
        for changes in ({"rock_porosity": 1}, {"mobile_porosity": 1.1},
                        {"dissolved_rock_fraction": 1.01}, {"mobile_fraction_of_retained_solids": 2},
                        {"cover_scale_m": 0}, {"rock_grain_density_kg_m3": 0}):
            with self.assertRaises(m.MaterialError):
                soil_parameters(**changes)
        with self.assertRaises(m.MaterialError):
            dissolution_parameters(mineral="calcite_linear_region_2", minimum_saturation=.3)
        with self.assertRaises(m.MaterialError):
            dissolution_parameters(maximum_saturation=.95)

    def test_scalar_invalid_numbers_and_overflow(self):
        for method, field in ((self.soil, "rock_available_kg"), (self.dissolve, "water_m3"),
                              (self.organic, "organic_kg"), (self.compact, "solid_volume_m3")):
            for value in (True, -1, math.nan, math.inf, 10**1000):
                with self.subTest(field=field), self.assertRaises(m.MaterialError):
                    method(**{field: value})
        for method, changes in ((self.soil, {"area_m2": 1e308}),
                                (self.dissolve, {"reactive_area_m2": 1e308}),
                                (self.organic, {"area_m2": 1e308}),
                                (self.compact, {"solid_volume_m3": 1e308})):
            with self.subTest(method=method), self.assertRaises(m.MaterialError):
                method(**changes)

    def test_batch_parity_order_and_no_mutation(self):
        cells = [dict(area_m2=10., rock_available_kg=1e6, regolith_kg=0., mobile_kg=2600., duration_years=t)
                 for t in (0, 3, 10)]
        before = deepcopy(cells)
        p = soil_parameters()
        results = m.soil_production_batch(cells, p)
        self.assertEqual(results, tuple(m.soil_production_step(**cell, parameters=p) for cell in cells))
        self.assertEqual(cells, before)
        self.assertIsInstance(results, tuple)
        with self.assertRaises(FrozenInstanceError):
            results[0].rock_consumed_kg = 2

    def test_all_batches_empty_schema_and_cap(self):
        for function, p in ((m.soil_production_batch, soil_parameters()),
                            (m.dissolution_batch, dissolution_parameters()),
                            (m.organic_batch, organic_parameters()),
                            (m.compaction_batch, m.CompactionParameters(1, 1, 10, "TEST"))):
            self.assertEqual(function([], p), ())
            with self.assertRaises(m.MaterialError):
                function([], None)
            for bad in (({} for _ in range(1)), [{}]*(m.MAX_BATCH_CELLS+1), [None], [{"parameters": p}], [{"wrong": 1}]):
                with self.subTest(function=function), self.assertRaises(m.MaterialError):
                    function(bad, p)

    def test_underflow_and_result_volume_overflow_rejected(self):
        with self.assertRaises(m.MaterialError):
            self.organic(organic_parameters(input_dry_organic_kg_m2_per_year=1e-300), duration_years=1e-300)
        with self.assertRaises(m.MaterialError):
            self.dissolve(dissolution_parameters(grain_density_kg_m3=1e-310))
        with self.assertRaises(m.MaterialError):
            self.soil(mobile_kg=1e8)
        with self.assertRaises(m.MaterialError):
            self.organic(organic_kg=1e308, void_ratio=1e308)

    def test_compaction_close_stresses_keep_positive_settlement(self):
        after = math.nextafter(1000., math.inf)
        r = self.compact(effective_stress_after_pa=after, void_ratio=1e-5)
        expected = 2/10 * math.log1p((after-1000)/1000)/math.log(10)
        self.assertGreater(r.settlement_m, 0)
        self.assertLess(r.void_ratio_after, 1e-5)
        self.near(r.settlement_m, expected, 1e-30)
        with self.assertRaises(m.MaterialError):
            self.compact(effective_stress_after_pa=after)

    def test_result_finite_repeatable_and_no_physical_acceptance(self):
        for method in (self.soil, self.dissolve, self.organic, self.compact):
            a = json.dumps(asdict(method()), sort_keys=True, allow_nan=False)
            b = json.dumps(asdict(method()), sort_keys=True, allow_nan=False)
            self.assertEqual(a, b)
        self.assertEqual(m.STATUS, "BOUNDED_REDUCED_LAWS_NOT_PHYSICAL_ACCEPTANCE")


if __name__ == "__main__":
    unittest.main()
