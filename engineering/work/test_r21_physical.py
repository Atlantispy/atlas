"""Focused tiny actual R13 irrigation/season/harvest seam; no full-year run."""
from copy import deepcopy
from fractions import Fraction as F
import unittest

from work.generator_upgrade_r21 import physical as p, food


class PhysicalTests(unittest.TestCase):
    def test_actual_coupled_surface_irrigation_and_temporal_harvest(self):
        plan, deliveries = p.reference_plan()
        native_globals = dict(p.soil.advance.__globals__)
        saved, calls = {}, []
        def cache(name, invocation, producer):
            key = p.human.digest(invocation)
            if key not in saved:
                saved[key] = producer(); calls.append(name)
            return deepcopy(saved[key])
        wet = p.run(plan, deliveries, cache_step=cache)
        self.assertEqual(wet['status'], 'MODELLED', wet.get('reason', wet.get('crops')))
        self.assertEqual(len(calls), 2)
        self.assertEqual(p.run(plan, deliveries, cache_step=cache), wet)
        self.assertEqual(len(calls), 2)
        self.assertEqual(dict(p.soil.advance.__globals__), native_globals)
        self.assertEqual(wet['events'][1]['result']['initial_state'], wet['events'][0]['result']['final_state'])
        self.assertEqual(wet['final_state']['elapsed_seconds'], 200)
        first = wet['events'][0]
        self.assertEqual(F(first['surface_input']['soil_boundary_irrigation_m3']), F(1, 100000))
        self.assertFalse(first['surface_input']['application_efficiency_applied_here'])
        self.assertEqual(first['native_event']['surface_water_temperature_k'], 281)
        for event in wet['events']:
            native = event['result']; ledger = native['ledger']
            self.assertLessEqual(abs(ledger['water_residual_m']), plan['controls']['water_atol_m'])
            self.assertLessEqual(abs(ledger['energy_residual_j_m2']), plan['controls']['energy_atol_j_m2'])
            self.assertGreater(native['r21_trajectory']['successful_trial_endpoints'], 0)
            self.assertFalse(event['actual_exports']['return_flow_credited'])
        crop = wet['crops'][0]
        self.assertGreater(F(crop['actual_root_transpiration_m']), 0)
        self.assertLess(F(crop['actual_root_transpiration_m']), F(crop['potential_root_transpiration_m']))
        harvest = wet['harvests'][0]
        self.assertEqual(harvest['available_at_seconds'], '200')
        self.assertEqual(harvest['conversion']['producer_kind'], p.PRODUCER_KIND)
        self.assertEqual(F(harvest['conversion']['dry_mass_residual_kg']), 0)
        admitted = food._harvests(wet['harvests'], {harvest['harvest_id']: '3000'})
        self.assertEqual(len(admitted), 1)
        dry = p.run(plan, [], cache_step=cache)
        self.assertEqual(dry['status'], 'MODELLED', dry.get('reason', dry.get('crops')))
        self.assertLess(F(dry['total_edible_dry_kg']), F(wet['total_edible_dry_kg']))
        # Yield-only compatibility changes reuse identical physical events; no
        # second bucket is executed to obtain UNKNOWN or an alternate Ky.
        unknown = deepcopy(plan)
        unknown['crops'][0]['et_compatibility']['source_status'] = 'UNKNOWN'
        call_count = len(calls)
        missing = p.run(unknown, deliveries, cache_step=cache)
        self.assertEqual(len(calls), call_count)
        self.assertEqual(missing['status'], 'UNKNOWN')
        self.assertEqual(missing['final_state'], wet['final_state'])
        self.assertEqual(missing['harvests'], [])
        self.assertIsNone(missing['total_edible_dry_kg'])
        self.__class__.results = {'irrigated': wet, 'dry': dry, 'unknown_compatibility': missing}

    def test_exact_support_time_roots_and_surface_enthalpy_guards(self):
        plan, deliveries = p.reference_plan()
        repeated = deepcopy(deliveries)+deepcopy(deliveries)
        with self.assertRaisesRegex(ValueError, 'reused'):
            p._validate(plan, repeated)
        wrong = deepcopy(deliveries); wrong[0]['delivery_boundary'] = 'ROOT_ZONE_NET'
        with self.assertRaisesRegex(ValueError, 'boundary'):
            p._validate(plan, wrong)
        late = deepcopy(deliveries); late[0]['start_seconds'] = '100'
        with self.assertRaisesRegex(ValueError, 'time mismatch'):
            p._validate(plan, late)
        roots = deepcopy(plan); roots['crops'][0]['root_support']['rooted_thickness_by_layer_m']['test-soil'] = '1'
        with self.assertRaisesRegex(ValueError, 'root depth'):
            p._validate(roots, deliveries)
        overlapping = deepcopy(plan); extra = deepcopy(overlapping['crops'][0]); extra['crop_id'] = 'competing-crop'
        overlapping['crops'].append(extra)
        with self.assertRaisesRegex(ValueError, 'overlap'):
            p._validate(overlapping, deliveries)
        event = deepcopy(plan['events'][0]['soil_event'])
        event['surface_water_flux_m_s'] = 1e-7
        mixed, receipt = p._surface(plan['model'], event, deliveries, F(1), plan['controls'])
        self.assertGreater(mixed['surface_water_temperature_k'], 280)
        self.assertLess(mixed['surface_water_temperature_k'], 281)
        self.assertEqual(F(receipt['requested_surface_volume_m3']),
                         F(event['surface_water_flux_m_s'])*100+F(1, 100000))
        self.assertLessEqual(abs(F(receipt['energy_representation_residual_j'])), F(plan['controls']['energy_atol_j_m2']))


if __name__ == '__main__':
    unittest.main()
