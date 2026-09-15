"""Focused crop-stage, root-demand and true surface evaporation integration."""
from copy import deepcopy
from fractions import Fraction as F
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np

from work.generator_upgrade_r21 import physical
from work.generator_upgrade_r22 import crop_development as crop, evaporation as evap


SOURCE = {'source_status': 'SYNTHETIC TEST', 'evidence': 'Explicit manufactured R22 fixture; no Diadem crop calibration'}


def profile_fixture():
    def stage(identity, kt, ke, depth, end=None):
        row = {'stage_id': identity, 'transpiration_coefficient': kt,
            'potential_soil_evaporation_coefficient': ke, 'maximum_total_coefficient': '6/5',
            'root_depth_m': depth, **SOURCE}
        if end is not None:
            row['end_thermal_time_cd'] = end
        return row
    profile = {'profile_id': 'manufactured', 'crop_id': 'test-crop',
        'thermal_method': 'FAO_AQUACROP_GDD_METHOD_1', 'thermal_day_seconds': '86400',
        'base_temperature_c': '0', 'upper_temperature_c': '30',
        'forcing_interpretation': 'SUPPLIED_DAILY_EXTREMA_CONSTANT_THERMAL_RATE_WITHIN_INTERVAL',
        'coefficient_interpretation': 'DISJOINT_PURE_TRANSPIRATION_AND_EXPOSED_SOIL_EVAPORATION',
        'root_distribution': 'UNIFORM_DENSITY_OVER_ACCESSIBLE_ROOTED_LENGTH',
        'stages': [stage('early', '1/2', '1/5', '1/10', '10'), stage('late', '1', '1/10', '3/20', '20')],
        'post_maturity': stage('mature', '0', '3/10', '0'), **SOURCE}
    forcing = {'event_id': 'weather', 'start_seconds': '0', 'end_seconds': '172800',
        'minimum_temperature_c': '10', 'maximum_temperature_c': '30', 'reference_et_m': '1/50', **SOURCE}
    layers = [{'layer_id': key, 'thickness_m': '1/10', 'root_accessibility': 'ACCESSIBLE', **SOURCE} for key in ('a', 'b')]
    return profile, forcing, layers


def evaporation_fixture():
    plan, _ = physical.reference_plan()
    event = deepcopy(plan['events'][0]['soil_event'])
    event['bottom_water'] = {'kind': 'noflow', **SOURCE}
    event['potential_root_demand_m_s'] = 0.
    event['surface_evaporation'] = {'kind': 'SUPPLIED_POTENTIAL_LIQUID_SURFACE',
        'potential_m_s': 1e-8, 'dry_zero_head_m': -100., 'dry_full_head_m': -2.,
        'latent_heat_vaporisation_j_kg': 2450000.,
        'heat_boundary_basis': 'BEFORE_EVAPORATIVE_LATENT_COOLING',
        'applicability': {'kind': 'EXPOSED_UNFROZEN_NONSALINE_SOIL',
            'donor_layer_id': plan['model']['layers'][0]['layer_id'], 'exposed_fraction': 1.,
            'wetted_fraction': 1., 'exposed_wetted_fraction': 1.,
            'demand_area_basis': 'COLUMN_MEAN_AFTER_EXPOSED_WETTED_FRACTION', **SOURCE}, **SOURCE}
    return plan['model'], plan['initial_state'], event, plan['controls']


class CropDevelopmentTests(unittest.TestCase):
    def test_stage_crossings_exact_water_demands_roots_and_restart(self):
        profile, forcing, layers = profile_fixture()
        state = crop.initial_state(profile, elapsed_seconds='0', thermal_time_cd='0')
        result = crop.advance(profile, state, forcing, layers)
        self.assertEqual(result['status'], 'MODELLED')
        self.assertEqual([row['end_seconds'] for row in result['segments']], ['43200', '86400', '172800'])
        self.assertEqual(result['segments'][1]['root_support']['weights'], ['2/3', '1/3'])
        self.assertEqual(F(result['potential_transpiration_m']), F(3, 400))
        self.assertEqual(F(result['potential_soil_evaporation_m']), F(9, 2000))
        self.assertEqual(result['soil_water_consumed_here_m'], '0')
        first = deepcopy(forcing); first.update(end_seconds='86400', reference_et_m='1/100')
        second = deepcopy(forcing); second.update(start_seconds='86400', reference_et_m='1/100')
        a = crop.advance(profile, state, first, layers)
        b = crop.advance(profile, a['final_state'], second, layers)
        self.assertEqual(b['final_state'], result['final_state'])
        self.assertEqual(F(a['potential_transpiration_m'])+F(b['potential_transpiration_m']), F(result['potential_transpiration_m']))
        self.assertTrue(result['maturity_reached'])

    def test_cold_hot_unknown_and_no_implicit_crop_calibration(self):
        profile, forcing, layers = profile_fixture()
        state = crop.initial_state(profile, elapsed_seconds='0', thermal_time_cd='0')
        cold = deepcopy(forcing); cold.update(minimum_temperature_c='-10', maximum_temperature_c='0')
        self.assertEqual(crop.advance(profile, state, cold, layers)['final_state']['thermal_time_cd'], '0')
        hot = deepcopy(forcing); hot.update(minimum_temperature_c='40', maximum_temperature_c='50')
        self.assertEqual(crop.advance(profile, state, hot, layers)['final_state']['thermal_time_cd'], '60')
        unknown = deepcopy(profile); unknown['stages'][0]['root_depth_m'] = None
        missing = crop.advance(unknown, crop.initial_state(unknown, elapsed_seconds='0', thermal_time_cd='0'), forcing, layers)
        self.assertEqual(missing['status'], 'UNKNOWN'); self.assertIsNone(missing['final_state'])
        bad = deepcopy(profile); bad['coefficient_interpretation'] = 'KCB_IS_ALWAYS_PURE_TRANSPIRATION'
        with self.assertRaisesRegex(ValueError, 'pure transpiration'):
            crop.validate_profile(bad)
        bad = deepcopy(profile); bad['stages'][0]['potential_soil_evaporation_coefficient'] = '1'
        with self.assertRaisesRegex(ValueError, 'total energy'):
            crop.validate_profile(bad)
        with self.assertRaisesRegex(ValueError, 'beyond'):
            crop.root_support(layers, '1')

    def test_crop_segment_executes_on_the_actual_common_soil(self):
        profile, forcing, layers = profile_fixture()
        model, state, event, controls = evaporation_fixture()
        layers = [{'layer_id': model['layers'][0]['layer_id'], 'thickness_m': str(F(model['layers'][0]['thickness_m'])),
                   'root_accessibility': 'ACCESSIBLE', **SOURCE}]
        forcing.update(end_seconds='100', reference_et_m='1/100000')
        output = crop.advance(profile, crop.initial_state(profile, elapsed_seconds='0', thermal_time_cd='0'), forcing, layers)
        bound = crop.bind_soil_event(output['segments'][0], event, model, controls)
        result = evap.advance(model, state, bound['event'], controls)
        self.assertEqual(result['status'], 'MODELLED', result.get('reason'))
        evap.audit_event(model, bound['event'], result, controls)
        self.assertGreater(result['ledger']['root_withdrawal_m'], 0.)
        self.assertGreater(result['ledger']['surface_evaporation_m'], 0.)
        self.assertEqual(bound['mapping']['soil_water_consumed_here_m'], '0')
        second = deepcopy(forcing); second.update(event_id='second-weather', start_seconds='100', end_seconds='200')
        windows = [{'forcing': forcing, 'soil_event': event}, {'forcing': second, 'soil_event': event}]
        initial = crop.initial_state(profile, elapsed_seconds='0', thermal_time_cd='0')
        with TemporaryDirectory() as directory:
            cold = crop.run(profile, initial, windows, layers, model, state, controls, cache_root=Path(directory))
            warm = crop.run(profile, initial, windows, layers, model, state, controls, cache_root=Path(directory))
        self.assertEqual(cold['status'], 'MODELLED')
        self.assertEqual(cold['events'][1]['result']['initial_state'], cold['events'][0]['result']['final_state'])
        self.assertEqual(cold['final_soil_state']['elapsed_seconds'], 200.)
        self.assertTrue(all(row['cache_hit'] for row in warm['execution']['events']))
        self.assertEqual(warm['execution']['stats']['writes'], 0)
        cold.pop('execution'); warm.pop('execution')
        self.assertEqual(cold, warm)


class EvaporationTests(unittest.TestCase):
    def test_actual_surface_water_liquid_enthalpy_and_latent_cooling(self):
        model, state, event, controls = evaporation_fixture()
        globals_before = dict(evap.soil.__dict__)
        result = evap.advance(model, state, event, controls)
        self.assertEqual(result['status'], 'MODELLED', result.get('reason'))
        self.assertEqual(evap.soil.__dict__, globals_before)
        audit = evap.audit_event(model, event, result, controls)
        ledger = result['ledger']
        self.assertGreater(audit['surface_evaporation_m'], 0.)
        self.assertEqual(ledger['root_withdrawal_m'], 0.)
        self.assertEqual(ledger['surface_runoff_m'], 0.)
        self.assertLess(result['final_state']['temperature_k'][0], state['temperature_k'][0])
        self.assertAlmostEqual(ledger['storage_change_m'], -ledger['surface_evaporation_m'], delta=controls['water_atol_m'])
        self.assertAlmostEqual(ledger['enthalpy_change_j_m2'],
            -ledger['surface_evaporation_enthalpy_j_m2']-ledger['surface_evaporation_latent_heat_j_m2'], delta=controls['energy_atol_j_m2'])
        self.assertGreater(result['final_state']['liquid_water'][0], model['layers'][0]['theta_r'])
        corrupt = deepcopy(result); corrupt['ledger']['surface_runoff_m'] += ledger['surface_evaporation_m']
        with self.assertRaises(ValueError):
            evap.audit_event(model, event, corrupt, controls)

    def test_simultaneous_rain_roots_evaporation_is_one_stock_and_zero_parity(self):
        model, state, event, controls = evaporation_fixture()
        event['surface_water_flux_m_s'] = 1e-7
        event['potential_root_demand_m_s'] = 1e-7
        result = evap.advance(model, state, event, controls)
        self.assertEqual(result['status'], 'MODELLED', result.get('reason'))
        evap.audit_event(model, event, result, controls)
        ledger = result['ledger']
        # Rain exceeds the supplied dry-soil infiltration capacity. Its real
        # bypass is a separate liquid export, not evaporated water or a loss
        # that may be omitted from the common finite-stock balance.
        self.assertGreater(ledger['rain_excess_runoff_m'], 0.)
        self.assertEqual(ledger['surface_runoff_m'], ledger['rain_excess_runoff_m'])
        self.assertEqual(ledger['surface_exfiltration_m'], 0.)
        self.assertGreater(ledger['root_withdrawal_m'], 0.)
        self.assertGreater(ledger['surface_evaporation_m'], 0.)
        self.assertAlmostEqual(ledger['storage_change_m'], ledger['surface_input_m']-ledger['surface_runoff_m']-
            ledger['root_withdrawal_m']-ledger['surface_evaporation_m'], delta=controls['water_atol_m'])
        zero = deepcopy(event); zero['surface_evaporation']['potential_m_s'] = 0.
        legacy = deepcopy(zero); del legacy['surface_evaporation']
        native = evap.soil.advance(model, state, legacy, controls)
        successor = evap.advance(model, state, zero, controls)
        self.assertEqual(successor['final_state'], native['final_state'])
        self.assertEqual(successor['ledger']['root_withdrawal_m'], native['ledger']['root_withdrawal_m'])

    def test_boundary_jacobian_and_unknown_guards(self):
        model, state, event, controls = evaporation_fixture()
        head, temperature, offsets = evap.soil._read_state(model, state)
        props = evap.soil._properties(model, head, temperature, temperature_offset=offsets)
        rates = evap._rates(model, props, temperature, event, temperature_offset=offsets)
        x = np.r_[head, offsets]
        for column in range(2):
            epsilon = 1e-5
            sides = []
            for sign in (-1, 1):
                probe = x.copy(); probe[column] += sign*epsilon
                p = evap.soil._properties(model, probe[:1], probe[1:]+model['constants']['melting_temperature_k'], temperature_offset=probe[1:])
                sides.append(evap._rates(model, p, probe[1:]+model['constants']['melting_temperature_k'], event, temperature_offset=probe[1:]))
            for key in ('water', 'advection', 'heat'):
                observed = (sides[1][key][0]-sides[0][key][0])/(2*epsilon)
                self.assertAlmostEqual(rates[key+'_jac'][0, column], observed, delta=max(1e-9, abs(observed)*1e-5))
        unknown = deepcopy(event); unknown['surface_evaporation']['latent_heat_vaporisation_j_kg'] = None
        result = evap.advance(model, state, unknown, controls)
        self.assertEqual(result['status'], 'UNKNOWN'); self.assertIsNone(result['final_state'])
        absent = deepcopy(event); absent['surface_evaporation'] = None
        self.assertEqual(evap.advance(model, state, absent, controls)['status'], 'UNKNOWN')
        bad = deepcopy(event); bad['surface_evaporation']['heat_boundary_basis'] = 'ALREADY_NET_OF_EVAPORATION'
        with self.assertRaisesRegex(ValueError, 'exclude'):
            evap.advance(model, state, bad, controls)
        buried = deepcopy(event); buried['surface_evaporation']['applicability']['donor_layer_id'] = 'old-buried-material'
        with self.assertRaisesRegex(ValueError, 'donor differs'):
            evap.advance(model, state, buried, controls)
        covered = deepcopy(event); covered['surface_evaporation']['applicability'].update(exposed_fraction=0., exposed_wetted_fraction=0.)
        with self.assertRaisesRegex(ValueError, 'exposed and wetted'):
            evap.advance(model, state, covered, controls)
        frozen = evap.soil.initial_state(model, [-3.], [270.])
        self.assertEqual(evap.advance(model, frozen, event, controls)['status'], 'OUTSIDE_REGIME')

    def test_dry_cutoff_and_real_rain_bypass_remain_separate(self):
        model, state, event, controls = evaporation_fixture()
        dry = evap.soil.initial_state(model, [-101.], state['temperature_k'])
        result = evap.advance(model, dry, event, controls)
        self.assertEqual(result['status'], 'MODELLED', result.get('reason'))
        self.assertEqual(result['ledger']['surface_evaporation_m'], 0.)
        self.assertEqual(result['final_state']['total_water'], dry['total_water'])
        wet = deepcopy(event); wet['surface_water_flux_m_s'] = 1e-4
        result = evap.advance(model, state, wet, controls)
        self.assertEqual(result['status'], 'MODELLED', result.get('reason'))
        evap.audit_event(model, wet, result, controls)
        self.assertGreater(result['ledger']['rain_excess_runoff_m'], 0.)
        self.assertGreater(result['ledger']['surface_evaporation_m'], 0.)


if __name__ == '__main__':
    unittest.main()
