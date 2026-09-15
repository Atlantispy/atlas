"""One temporal-account check using two actual small native crop harvests."""
from copy import deepcopy
import unittest

from work.generator_upgrade_r21 import _native_crop as crop, _native_human as human, food

E = 'SYNTHETIC TEST: explicit crop and local food-account oracle, no geographic/freight claim'
S = 'SYNTHETIC TEST'


def harvest(identity, start, area):
    parameters = {'yield_mass_basis': 'DRY_HARVEST_KG', 'irrigation_deliveries': [],
        'day_duration_seconds': '1', 'season_start_seconds': str(start), 'irrigation_sink_id': 'field-inlet',
        'initial_depletion_mm': 0, 'potential_yield_kg_m2': 1, 'yield_response_factor': 1,
        'minimum_valid_et_ratio': .5, 'evidence': E, 'source_status': S}
    result = human.harvest_from_crop(crop,
        root_zone={'field_capacity_m3_m3': .3, 'wilting_point_m3_m3': .1, 'rooting_depth_m': 1,
                   'depletion_fraction': .5, 'evidence': E, 'source_status': S},
        daily_forcing=[{'precipitation_mm': 0, 'runoff_mm': 0, 'potential_crop_et_mm': 1,
                        'net_irrigation_mm': 0, 'capillary_rise_mm': 0}],
        crop_parameters=parameters, area_m2=str(area),
        conversion={'mass_basis': 'EDIBLE_DRY_FOOD_KG', 'carbon_fraction_dry_matter': '1/2',
            'edible_fraction': '1', 'processing_loss_fraction': '0', 'food_quality_evidence': E,
            'evidence_id': E, 'source_status': S}, harvest_id=identity, settlement_id='local',
        commodity_id='grain', support_id='plot-'+identity, event_id='event-'+identity,
        source_use_id='source-'+identity, available_at_seconds=str(start+1))
    if result['status'] != 'MODELLED':
        raise AssertionError('native crop fixture did not produce modelled harvest')
    return result['harvest']


def obligation(identity, amount, *, reserve=False):
    return {'obligation_id': identity, 'node_id': 'local', 'bundle_id': 'grain-diet',
        'kind': 'one_off_reserve' if reserve else 'recurring_consumption',
        'recurrence': 'one_off' if reserve else 'per_year', 'amount_unit': 'kcal',
        'amount': amount, 'component_claim_ids': ['claim-'+identity], 'evidence': E, 'source_status': S}


class FoodTests(unittest.TestCase):
    def test_native_harvest_timing_shortage_reserve_carry_and_duplicate_rejection(self):
        harvests = [harvest('early', 1, 2), harvest('late', 3, 3)]
        original = deepcopy(harvests)
        windows = []
        for identity, start, end, obligations in [
                ('w0', '0', '2', [obligation('early-demand', '1825')]),
                ('w1', '2', '4', [obligation('middle-demand', '1825'), obligation('reserve', '5', reserve=True)]),
                ('w2', '4', '5', [obligation('late-demand', '3650')])]:
            windows.append({'id': identity, 'start_seconds': start, 'end_seconds': end,
                'obligations': obligations, 'policies': [{'node_id': 'local',
                    'protected_order': ['recurring_consumption', 'one_off_reserve'],
                    'obligation_order': [row['obligation_id'] for row in obligations],
                    'block_export_on_shortfall': True, 'evidence': E}]})
        arguments = {'energy_by_harvest': {'early': '10', 'late': '10'}, 'windows': windows,
            'bundles': [{'bundle_id': 'grain-diet', 'components': [{'commodity_id': 'grain',
                'energy_share': '1', 'edible_energy_kcal_kg': '10', 'composition_evidence': E}],
                'energy_kcal_person_day': '10', 'diet_evidence': E, 'source_status': S}],
            'calendar': {'days_per_year': '365', 'day_duration_seconds': '1', 'evidence': E},
            'evidence': E, 'source_status': S}
        result = food.account(harvests, **arguments)
        self.assertEqual(harvests, original)
        self.assertEqual(result['status'], 'ACCOUNTED')
        self.assertEqual(result['windows'][0]['opening_harvest_ids'], [])
        self.assertEqual(result['windows'][0]['closing_arrivals'], ['early'])
        self.assertEqual(result['windows'][0]['shortages'][0]['quantity_kg'], '1')
        self.assertEqual(result['windows'][1]['opening_harvest_ids'], ['early'])
        self.assertEqual(result['windows'][1]['closing_arrivals'], ['late'])
        self.assertEqual(result['totals'], {'initial_admitted_edible_kg': '5', 'consumed_kg': '2',
            'reserved_carry_kg': '1/2', 'free_carry_kg': '5/2', 'residual_kg': '0'})
        self.assertTrue(all(row['residual_kg'] == '0' for row in result['final_stock_ledger']))
        self.assertIs(result['shortages_retroactively_fulfilled'], False)
        self.assertIs(result['transport_solved'], False)
        self.assertEqual(result['pending_harvest_ids'], [])
        self.assertEqual(len({row['use_id'] for row in result['debit_ledger']}), len(result['debit_ledger']))
        duplicated = deepcopy(harvests)
        extra = deepcopy(duplicated[0]); extra['harvest_id'] = 'renamed'
        duplicated.append(extra)
        bad_args = deepcopy(arguments); bad_args['energy_by_harvest']['renamed'] = '10'
        with self.assertRaisesRegex(ValueError, 'already imported'):
            food.account(duplicated, **bad_args)
        bad_args = deepcopy(arguments)
        bad_args['windows'][2]['obligations'][0]['component_claim_ids'] = ['claim-early-demand']
        with self.assertRaisesRegex(ValueError, 'already used'):
            food.account(harvests, **bad_args)
        type(self).result = result
        type(self).harvests = harvests


if __name__ == '__main__':
    unittest.main()
