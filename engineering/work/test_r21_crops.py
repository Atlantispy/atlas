"""Focused synthetic sequence, finite delivery and unchanged native water check."""
from copy import deepcopy
from fractions import Fraction as F
import unittest

from work.generator_upgrade_r21 import crops, _native_crop as agro


def fixture():
    evidence, status = 'explicit synthetic crop/covered-root fixture', 'SYNTHETIC TEST'
    source = {'evidence': evidence, 'source_status': status}
    crop = {**source, 'potential_yield_kg_m2': 1., 'yield_response_factor': 1., 'minimum_valid_et_ratio': 0.}
    conversion = {'mass_basis': 'EDIBLE_DRY_FOOD_KG', 'carbon_fraction_dry_matter': '1/2',
        'edible_fraction': '3/4', 'processing_loss_fraction': '1/5',
        'food_quality_evidence': evidence, 'evidence_id': evidence, 'source_status': status,
        'edible_energy_kcal_kg': '1000'}
    days = [{'precipitation_mm': 1., 'runoff_mm': 0., 'capillary_rise_mm': 0.,
             'net_irrigation_mm': 10. if i in (0, 3) else 0.,
             'potential_crop_et_mm': 0. if i == 2 else 10.} for i in range(5)]
    plan = {**source, 'plan_id': 'synthetic-plan', 'support_id': 'plot', 'irrigation_sink_id': 'inlet',
        'settlement_id': 'consumer', 'area_m2': '100', 'season_start_seconds': '0',
        'day_duration_seconds': '86400', 'regime': crops.REGIME, 'delivery_boundary': 'ROOT_ZONE_NET',
        'application_efficiency': '1/2', 'application_evidence': evidence,
        'initial_depletion_mm': 60., 'root_zone': {**source, 'field_capacity_m3_m3': .5,
            'wilting_point_m3_m3': .25, 'rooting_depth_m': .5, 'depletion_fraction': .2},
        'daily_forcing': days, 'segments': [
            {**source, 'segment_id': 'first', 'kind': 'CROP', 'start_day': 0, 'stop_day': 2,
             'crop_parameters': deepcopy(crop), 'conversion': deepcopy(conversion), 'commodity_id': 'grain'},
            {**source, 'segment_id': 'gap', 'kind': 'FALLOW', 'start_day': 2, 'stop_day': 3,
             'evaporation_model': 'ZERO_ET_REFERENCE'},
            {**source, 'segment_id': 'second', 'kind': 'CROP', 'start_day': 3, 'stop_day': 5,
             'crop_parameters': deepcopy(crop), 'conversion': deepcopy(conversion), 'commodity_id': 'grain'}]}
    deliveries = [{'allocation_id': f'allocation-{i}', 'delivery_id': f'delivery-{i}',
        'kind': 'ROUTED_WITHDRAWAL_DELIVERY', 'status': 'MODELLED', 'support_id': 'plot',
        'delivery_boundary': 'ROOT_ZONE_NET',
        'receiving_sink_id': 'inlet', 'day_index': i, 'available_after_seconds': str(i*86400),
        'source_input_sha256': 'a'*64, 'delivered_volume_m3': '2', 'application_efficiency': '1/2',
        'application_evidence': evidence, 'evidence_id': evidence, 'source_status': status} for i in (0, 3)]
    return plan, deliveries


class CropSequenceTests(unittest.TestCase):
    def test_continuous_daily_water_actual_deliveries_and_explicit_regimes(self):
        plan, deliveries = fixture()
        original = deepcopy((plan, deliveries))
        predicted, actual = crops.preview(plan), crops.execute(plan, deliveries)
        self.assertEqual((plan, deliveries), original)
        self.assertEqual(actual['status'], 'MODELLED')
        self.assertEqual(predicted['harvests'], [])
        self.assertEqual(predicted['quantity_role'], 'HYPOTHETICAL_NOT_DELIVERED')
        self.assertEqual(actual['total_edible_dry_kg'], predicted['total_edible_dry_kg'])
        self.assertEqual(len(actual['harvests']), 2)
        self.assertEqual(actual['irrigation_delivery_ids'], ['delivery-0', 'delivery-3'])
        self.assertEqual(actual['segments'][2]['initial_depletion_mm'], actual['segments'][1]['final_depletion_mm'])
        native = agro.water_balance(agro.RootZone(**plan['root_zone']),
            [agro.DayForcing(**day) for day in plan['daily_forcing']], initial_depletion_mm=60.)
        self.assertEqual(actual['final_depletion_mm'], native['final_depletion_mm'])
        self.assertEqual(actual['daily_water'], native['rows'])
        for harvest in actual['harvests']:
            self.assertEqual(F(harvest['edible_energy_kcal']), F(harvest['quantity_kg'])*1000)
        self.assertEqual(sum(F(row['gross_delivery_m3']) for row in actual['daily_demands']), 4)
        self.assertEqual(sum(F(row['net_root_zone_m3']) for row in actual['daily_demands']), 2)
        rationed_rows = [dict(row, delivered_volume_m3='1') for row in deliveries]
        rationed = crops.realise(plan, rationed_rows)
        self.assertEqual(rationed['status'], 'MODELLED')
        self.assertEqual((plan, deliveries), original)
        self.assertEqual(rationed['planted_area_m2'], '100')
        self.assertEqual(rationed['planted_segments'], plan['segments'])
        self.assertEqual(len(rationed['harvests']), 2)
        self.assertLess(F(rationed['total_edible_dry_kg']), F(actual['total_edible_dry_kg']))
        self.assertEqual(rationed['requested_daily_forcing'], plan['daily_forcing'])
        actual_plan = deepcopy(plan)
        actual_plan['daily_forcing'][0]['net_irrigation_mm'] = 5.
        actual_plan['daily_forcing'][3]['net_irrigation_mm'] = 5.
        direct = crops.execute(actual_plan, rationed_rows)
        self.assertEqual(rationed['daily_water'], direct['daily_water'])
        self.assertEqual(rationed['harvests'], direct['harvests'])
        self.assertEqual(rationed['irrigation_rationing_totals']['unmet_gross_delivery_m3'], '2')
        self.assertEqual(rationed['irrigation_rationing_totals']['actual_net_root_zone_m3'], '1')
        zero = crops.realise(plan, [])
        self.assertEqual(zero['status'], 'MODELLED')
        self.assertEqual(zero['planted_segments'], plan['segments'])
        self.assertEqual(zero['irrigation_rationing_totals']['unmet_gross_delivery_m3'], '4')
        with self.assertRaisesRegex(ValueError, 'exceeds'):
            crops.realise(plan, [dict(row, delivered_volume_m3='3') for row in deliveries])
        with self.assertRaisesRegex(ValueError, 'representable'):
            crops.realise(plan, [dict(row, delivered_volume_m3='1/3') for row in deliveries])
        surface = deepcopy(plan)
        surface['delivery_boundary'] = 'SURFACE_APPLICATION'
        self.assertEqual(crops.realise(surface, deliveries)['status'], 'OUTSIDE_REGIME')
        with self.assertRaisesRegex(ValueError, 'ROOT_ZONE_NET'):
            crops.realise(plan, [dict(row, delivery_boundary='SURFACE_APPLICATION') for row in deliveries])
        for mutate in ('missing', 'duplicate', 'late', 'volume', 'support', 'hypothetical'):
            bad = deepcopy(deliveries)
            if mutate == 'missing': bad.pop()
            elif mutate == 'duplicate': bad.append(dict(bad[0], allocation_id='another'))
            elif mutate == 'late': bad[0]['available_after_seconds'] = '1'
            elif mutate == 'volume': bad[0]['delivered_volume_m3'] = '1'
            elif mutate == 'support': bad[0]['support_id'] = 'other'
            else: bad[0]['hypothetical'] = True
            with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                crops.execute(plan, bad)
        unknown = deepcopy(plan)
        unknown['segments'][0]['crop_parameters']['yield_response_factor'] = None
        self.assertEqual(crops.preview(unknown)['status'], 'UNKNOWN')
        outside = deepcopy(plan)
        outside['segments'][1]['evaporation_model'] = 'BARE_SOIL_UNSPECIFIED'
        self.assertEqual(crops.preview(outside)['status'], 'OUTSIDE_REGIME')
        outside = deepcopy(plan)
        outside['daily_forcing'][2]['potential_crop_et_mm'] = 1.
        self.assertEqual(crops.preview(outside)['status'], 'OUTSIDE_REGIME')
        severe = deepcopy(plan)
        severe['segments'][0]['crop_parameters']['minimum_valid_et_ratio'] = 1.
        self.assertEqual(crops.preview(severe)['status'], 'OUTSIDE_REGIME')
        self.assertIsNone(crops.preview(severe)['total_edible_dry_kg'])


if __name__ == '__main__':
    unittest.main()
