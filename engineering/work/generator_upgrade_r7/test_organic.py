"""Independent equations and conservation for the actual R7 organic producer."""
from dataclasses import asdict, replace
from fractions import Fraction as F
import math
import unittest
from unittest.mock import patch

import numpy as np

from . import organic as o

E = 'SYNTHETIC DIMENSIONAL TEST, NOT DIADEM SOIL COEFFICIENTS'
S = 'SYNTHETIC TEST'


def law(**changes):
    values = dict(fast_rate_per_s=.2, slow_rate_per_s=.05, fast_to_slow_fraction=F(3,10),
                  carbon_fraction_dry_matter=F(2,5), reference_temperature_k=300.,
                  fast_activation_energy_j_mol=0., slow_activation_energy_j_mol=0.,
                  gas_constant_j_mol_k=8.314, minimum_temperature_k=270., maximum_temperature_k=330.,
                  moisture_curve=((0.,0.), (.5,1.), (1.,1.)),
                  redox_factors=(('OXIC',1.,1.), ('ANOXIC',.1,.2)),
                  regimes=('AERATED_MINERAL','WATERLOGGED_MINERAL','ORGANIC_DOMINATED'),
                  evidence=E, source_status=S)
    values.update(changes)
    return o.OrganicLaw(**values)


def forcing(**changes):
    values = dict(duration_seconds=F(4), fast_litter_carbon_kg_m2_s=F(1,20),
                  slow_litter_carbon_kg_m2_s=F(1,100), soil_temperature_k=300.,
                  water_filled_pore_fraction=.5, redox='OXIC', regime='AERATED_MINERAL',
                  climate_state_id='synthetic-climate', water_state_id='synthetic-water',
                  temperature_evidence='Supplied actual soil temperature for synthetic oracle',
                  litter_evidence=E, evidence=E, source_status=S)
    values.update(changes)
    return o.OrganicForcing(**values)


def state(fast=F(2), slow=F(3)):
    return o.initial_state('layer-a', 'one-horizontal-square-metre', fast, slow, evidence=E, source_status=S)


def analytical(old, segment, a, b, fraction):
    """Independent scalar closed form; no matrix exponential or producer helper."""
    duration = float(segment.duration_seconds)
    fast0, slow0 = float(old.fast_carbon_kg_m2), float(old.slow_carbon_kg_m2)
    u, v = float(segment.fast_litter_carbon_kg_m2_s), float(segment.slow_litter_carbon_kg_m2_s)
    A, B = math.exp(-a*duration), math.exp(-b*duration)
    L_a = -math.expm1(-a*duration)/a if a else duration
    L_b = -math.expm1(-b*duration)/b if b else duration
    K = duration*A if a == b else (A-B)/(b-a)
    fast = fast0*A+u*L_a
    slow = slow0*B+v*L_b
    if a:
        slow += fraction*(a*fast0*K+u*(L_b-K))
    exported = fast0+slow0+(u+v)*duration-fast-slow
    return fast, slow, exported


class OrganicTests(unittest.TestCase):
    def modelled(self, value):
        self.assertEqual(value['status'], 'MODELLED', value.get('reason'))
        ledger = value['carbon']
        self.assertEqual(ledger['initial_kg_m2']+ledger['input_kg_m2'],
                         ledger['final_kg_m2']+ledger['exported_atmospheric_carbon_kg_m2'])
        self.assertEqual(ledger['residual_kg_m2'], 0)
        self.assertGreaterEqual(value['state'].fast_carbon_kg_m2, 0)
        self.assertGreaterEqual(value['state'].slow_carbon_kg_m2, 0)

    def test_unequal_rate_two_pool_and_continuous_inputs_match_closed_form(self):
        initial, segment, parameters = state(), forcing(), law()
        result = o.advance_layer(initial, (segment,), parameters); self.modelled(result)
        expected = analytical(initial, segment, .2, .05, .3)
        for actual, wanted in zip((result['state'].fast_carbon_kg_m2, result['state'].slow_carbon_kg_m2,
                                   result['carbon']['exported_atmospheric_carbon_kg_m2']), expected):
            self.assertAlmostEqual(float(actual), wanted, delta=2e-13)

    def test_equal_rate_limit_matches_independent_closed_form(self):
        initial, segment = state(), forcing()
        result = o.advance_layer(initial, (segment,), law(slow_rate_per_s=.2)); self.modelled(result)
        wanted = analytical(initial, segment, .2, .2, .3)
        self.assertAlmostEqual(float(result['state'].slow_carbon_kg_m2), wanted[1], delta=2e-13)

    def test_single_pool_exponential_decay_is_exact_to_numeric_precision(self):
        segment = forcing(fast_litter_carbon_kg_m2_s=0, slow_litter_carbon_kg_m2_s=0)
        result = o.advance_layer(state(fast=2, slow=0), (segment,), law(fast_to_slow_fraction=0))
        self.modelled(result)
        self.assertAlmostEqual(float(result['final_organic_carbon_kg_m2']), 2*math.exp(-.8), delta=2e-14)

    def test_zero_rates_preserve_stocks_and_add_litter_exactly(self):
        result = o.advance_layer(state(), (forcing(),), law(fast_rate_per_s=0, slow_rate_per_s=0))
        self.modelled(result)
        self.assertEqual(result['state'].fast_carbon_kg_m2, F(11,5))
        self.assertEqual(result['state'].slow_carbon_kg_m2, F(76,25))
        self.assertEqual(result['carbon']['exported_atmospheric_carbon_kg_m2'], 0)

    def test_zero_exposure_does_not_form_organic_stock_or_consume_litter(self):
        result = o.advance_layer(state(), (forcing(duration_seconds=0),), law())
        self.modelled(result)
        self.assertEqual(result['state'].fast_carbon_kg_m2, 2)
        self.assertEqual(result['state'].slow_carbon_kg_m2, 3)
        self.assertEqual(result['state'].elapsed_seconds, 0)
        self.assertEqual(result['carbon']['input_kg_m2'], 0)
        self.assertEqual(result['carbon']['exported_atmospheric_carbon_kg_m2'], 0)

    def test_zero_fast_rate_does_not_transfer_to_slow(self):
        result = o.advance_layer(state(), (forcing(),), law(fast_rate_per_s=0))
        self.modelled(result)
        wanted = analytical(state(), forcing(), 0, .05, .3)
        self.assertAlmostEqual(float(result['state'].slow_carbon_kg_m2), wanted[1], delta=2e-13)

    def test_zero_slow_rate_retains_all_transferred_carbon(self):
        segment = forcing(fast_litter_carbon_kg_m2_s=0, slow_litter_carbon_kg_m2_s=0)
        result = o.advance_layer(state(), (segment,), law(slow_rate_per_s=0, fast_to_slow_fraction=1))
        self.modelled(result)
        self.assertEqual(result['carbon']['exported_atmospheric_carbon_kg_m2'], 0)
        self.assertEqual(result['final_organic_carbon_kg_m2'], 5)

    def test_continuous_litter_not_all_present_at_interval_start(self):
        segment = forcing(fast_litter_carbon_kg_m2_s=0, slow_litter_carbon_kg_m2_s=3)
        result = o.advance_layer(state(fast=0,slow=0), (segment,), law(slow_rate_per_s=2))
        self.modelled(result)
        self.assertAlmostEqual(float(result['state'].slow_carbon_kg_m2), 1.5*(1-math.exp(-8)), delta=2e-13)
        self.assertGreater(float(result['state'].slow_carbon_kg_m2), 12*math.exp(-8))

    def test_exact_dry_matter_ledger_uses_only_supplied_carbon_fraction(self):
        result = o.advance_layer(state(), (forcing(),), law()); self.modelled(result)
        carbon, dry = result['carbon'], result['organic_dry_matter']
        for field in ('initial_kg_m2','input_kg_m2','final_kg_m2'):
            self.assertEqual(dry[field], carbon[field]*F(5,2))
        self.assertEqual(dry['initial_kg_m2']+dry['input_kg_m2'], dry['final_kg_m2']+dry['decomposed_dry_matter_origin_kg_m2'])
        self.assertIsNone(result['nitrogen_release']['value'])
        self.assertIsNone(result['gas_speciation']['co2_kg_m2'])
        self.assertIsNone(result['gas_speciation']['ch4_kg_m2'])

    def test_actual_temperature_changes_rate_by_supplied_arrhenius_law(self):
        parameters = law(fast_activation_energy_j_mol=50000, slow_activation_energy_j_mol=30000)
        segment = forcing(soil_temperature_k=310.)
        result = o.advance_layer(state(), (segment,), parameters); self.modelled(result)
        a = .2*math.exp(50000/8.314*(1/300-1/310))
        b = .05*math.exp(30000/8.314*(1/300-1/310))
        self.assertAlmostEqual(result['segments'][0]['fast_rate_per_s'], a, delta=1e-14)
        self.assertAlmostEqual(float(result['state'].slow_carbon_kg_m2), analytical(state(),segment,a,b,.3)[1], delta=2e-13)

    def test_actual_wfps_interpolates_explicit_curve_without_rainfall_proxy(self):
        segment = forcing(water_filled_pore_fraction=.25)
        result = o.advance_layer(state(), (segment,), law()); self.modelled(result)
        self.assertAlmostEqual(result['segments'][0]['moisture_multiplier'], .5)
        self.assertAlmostEqual(float(result['state'].fast_carbon_kg_m2), analytical(state(),segment,.1,.025,.3)[0], delta=2e-13)

    def test_declared_anoxic_response_is_separate_from_saturation(self):
        wet = forcing(water_filled_pore_fraction=1., regime='WATERLOGGED_MINERAL', redox='ANOXIC')
        oxic = replace(wet, redox='OXIC')
        a, b = [o.advance_layer(state(), (segment,), law()) for segment in (wet,oxic)]
        self.modelled(a); self.modelled(b)
        self.assertAlmostEqual(a['segments'][0]['fast_rate_per_s'], .02, delta=1e-15)
        self.assertAlmostEqual(b['segments'][0]['fast_rate_per_s'], .2, delta=1e-15)
        self.assertGreater(a['final_organic_carbon_kg_m2'], b['final_organic_carbon_kg_m2'])

    def test_organic_dominated_requires_explicit_admitted_law(self):
        segment = forcing(regime='ORGANIC_DOMINATED', redox='ANOXIC')
        admitted = o.advance_layer(state(), (segment,), law()); self.modelled(admitted)
        refused = o.advance_layer(state(), (segment,), law(regimes=('AERATED_MINERAL',)))
        self.assertEqual(refused['status'], 'OUTSIDE_REGIME'); self.assertIsNone(refused['state'])

    def test_missing_drivers_return_unknown_not_zero_or_partial_stock(self):
        for key,value in (('soil_temperature_k',None),('water_filled_pore_fraction',None),
                          ('redox','UNKNOWN'),('fast_litter_carbon_kg_m2_s',None)):
            with self.subTest(key=key):
                result = o.advance_layer(state(), (forcing(),forcing(**{key:value})), law())
                self.assertEqual(result['status'], 'UNKNOWN'); self.assertIsNone(result['state'])
                self.assertIsNone(result['carbon']); self.assertEqual(result['segments'], [])

    def test_missing_carbon_fraction_or_source_status_remains_unknown(self):
        for parameters in (law(carbon_fraction_dry_matter=None), law(source_status='CONFLICT')):
            result = o.advance_layer(state(), (forcing(),), parameters)
            self.assertEqual(result['status'], 'UNKNOWN'); self.assertIsNone(result['organic_dry_matter'])

    def test_temperature_applicability_exceeded_does_not_extrapolate(self):
        result = o.advance_layer(state(), (forcing(soil_temperature_k=350),), law())
        self.assertEqual(result['status'], 'OUTSIDE_REGIME'); self.assertIsNone(result['state'])

    def test_same_forcing_split_intervals_agree_with_single_exposure(self):
        full = o.advance_layer(state(), (forcing(),), law())
        split = o.advance_layer(state(), (forcing(duration_seconds=2),)*2, law())
        self.modelled(full); self.modelled(split)
        for key in ('final_organic_carbon_kg_m2','final_organic_dry_mass_kg_m2'):
            self.assertAlmostEqual(float(full[key]), float(split[key]), delta=3e-13)

    def test_exact_state_restart_replays_identical_continuation(self):
        first = o.advance_layer(state(), (forcing(),), law()); self.modelled(first)
        restored = o.state_from_record(o.state_to_record(first['state']))
        self.assertEqual(restored, first['state'])
        continued = o.advance_layer(first['state'], (forcing(),), law())
        replayed = o.advance_layer(restored, (forcing(),), law())
        self.modelled(continued); self.assertEqual(continued,replayed)
        self.assertEqual(continued['state'].elapsed_seconds, 8)

    def test_exposure_is_explicit_seconds_not_an_implicit_year_or_event(self):
        result = o.advance_layer(state(), (forcing(duration_seconds=F(7,3)),), law())
        self.modelled(result)
        self.assertEqual(result['state'].elapsed_seconds, F(7,3))
        self.assertEqual(result['carbon']['input_kg_m2'], F(7,50))
        self.assertEqual(result['layer_id'], 'layer-a'); self.assertEqual(result['support_id'], state().support_id)

    def test_inputs_unchanged_and_evidence_retained(self):
        initial, segment, parameters = state(), forcing(), law()
        before = tuple(asdict(v) for v in (initial,segment,parameters))
        result = o.advance_layer(initial,(segment,),parameters); self.modelled(result)
        self.assertEqual(before,tuple(asdict(v) for v in (initial,segment,parameters)))
        self.assertEqual(result['segments'][0]['forcing']['water_state_id'], segment.water_state_id)
        self.assertEqual(result['segments'][0]['forcing']['temperature_evidence'], segment.temperature_evidence)

    def test_negative_nonfinite_boolean_and_out_of_range_values_reject(self):
        for bad in (True, -1., float('nan'), float('inf')):
            with self.subTest(value=bad), self.assertRaises(ValueError): law(fast_rate_per_s=bad)
            with self.subTest(value=bad), self.assertRaises(ValueError): state(fast=bad)
        for bad in (-.1, 1.1, True):
            with self.subTest(value=bad), self.assertRaises(ValueError): forcing(water_filled_pore_fraction=bad)
        with self.assertRaises(ValueError): law(carbon_fraction_dry_matter=0)
        with self.assertRaises(ValueError): law(fast_to_slow_fraction=1.1)
        with self.assertRaises(ValueError): forcing(duration_seconds=-1)

    def test_invalid_curve_redox_and_empty_or_mutable_segments_reject(self):
        for curve in (((.1,1.),(1.,1.)), ((0.,0.),(.5,1.),(.5,2.),(1.,1.))):
            with self.assertRaises(ValueError): law(moisture_curve=curve)
        with self.assertRaises(ValueError): law(redox_factors=(('OXIC',1,1),('OXIC',0,0)))
        with self.assertRaises(ValueError): forcing(redox='SATURATED')
        for segments in ((), [forcing()]):
            with self.assertRaises(ValueError): o.advance_layer(state(), segments, law())

    def test_unrepresentable_numerical_exposure_fails_without_partial_output(self):
        result = o.advance_layer(state(),(forcing(),forcing(duration_seconds=10**8)),law())
        self.assertEqual(result['status'],'NUMERICAL_FAILURE')
        self.assertIsNone(result['state']); self.assertIsNone(result['carbon']); self.assertEqual(result['segments'],[])

    def test_bad_matrix_exponential_never_clips_or_renormalises_large_defect(self):
        for changed in ('negative','mass','nonfinite'):
            matrix = np.eye(6); matrix[:3,3:] = np.eye(3)
            if changed == 'negative': matrix[2,0] = -1e-16
            if changed == 'mass': matrix[0,0] = 1.001
            if changed == 'nonfinite': matrix[0,0] = np.nan
            with self.subTest(changed=changed), patch.object(o,'expm',return_value=matrix):
                result = o.advance_layer(state(),(forcing(),),law())
                self.assertEqual(result['status'],'NUMERICAL_FAILURE'); self.assertIsNone(result['state'])

    def test_small_probability_roundoff_is_disclosed_and_exactly_reconciled(self):
        matrix = np.eye(6); matrix[:3,3:] = np.eye(3); matrix[0,0] += 1e-13
        with patch.object(o,'expm',return_value=matrix):
            result = o.advance_layer(state(),(forcing(),),law())
        self.modelled(result)
        self.assertGreater(result['segments'][0]['transition_column_sum_defect'],0)
        self.assertGreater(result['segments'][0]['roundoff_reconciliation_bound_kg_m2'],0)

    def test_finite_long_exposure_matches_equilibrium_supply_limits(self):
        segment = forcing(duration_seconds=10**5)
        result = o.advance_layer(state(),(segment,),law()); self.modelled(result)
        self.assertAlmostEqual(float(result['state'].fast_carbon_kg_m2), .05/.2, delta=2e-10)
        self.assertAlmostEqual(float(result['state'].slow_carbon_kg_m2), (.01+.3*.05)/.05, delta=2e-10)

    def test_malformed_restart_does_not_create_stock(self):
        record = o.state_to_record(state())
        for value in ([1,0],[True,1],[1,-1],0):
            with self.subTest(value=value), self.assertRaises(ValueError):
                o.state_from_record({**record,'fast_carbon_kg_m2':value})
        with self.assertRaises(ValueError): o.state_from_record({**record,'extra':0})


if __name__ == '__main__':
    unittest.main()
