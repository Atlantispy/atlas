from dataclasses import replace
from fractions import Fraction as F
import copy
import json
import unittest
from . import food_accounting as food
from .integration import food_delivery_snapshot
from .reference import inputs,food_reference,E


def run(**changes):
    upstream,bindings,kwargs=inputs(**changes)
    return food_delivery_snapshot(upstream['land_allocation']['food_budget'],bindings,**kwargs)


class IntegrationTests(unittest.TestCase):
    def test_actual_crop_allocator_budget_accounts_and_shared_route(self):
        r=run();self.assertEqual(r['status'],'ACCOUNTED_AND_TRANSPORT_SOLVED')
        self.assertEqual(sum(x['initial_kg'] for x in r['closure']),10)
        self.assertEqual(F(r['transport']['capacity_groups'][0]['used_kg']['exact']),4)
        self.assertEqual(sum(F(x['delivered_kg']['exact']) for x in r['transport']['commodity_totals']),F(18,5))

    def test_reserve_is_separate_from_consumption_and_old_debit(self):
        rows=run()['closure']
        self.assertEqual(sum(x['consumed_kg'] for x in rows),F(3,2))
        self.assertEqual(sum(x['reserved_kg'] for x in rows),F(3,4))
        self.assertEqual(sum(x['prior_debit_kg'] for x in rows),F(1,2))
        self.assertTrue(all(x['integrated_residual_kg']==0 for x in rows))

    def test_no_capacity_manufactures_no_delivery(self):
        r=run(capacity=0)
        self.assertEqual(sum(F(x['delivered_kg']['exact']) for x in r['transport']['commodity_totals']),0)
        self.assertGreater(sum(x['shortage_kg'] for x in r['obligation_fulfilment']),0)

    def test_loss_mass_is_accounted_not_consumed(self):
        r=run();totals=r['transport']['commodity_totals']
        self.assertEqual(sum(F(x['loss_kg']['exact']) for x in totals),F(2,5))
        for x in totals:self.assertEqual(F(x['dispatched_kg']['exact']),F(x['delivered_kg']['exact'])+F(x['loss_kg']['exact']))

    def test_lossless_variant_delivers_exact_capacity(self):
        r=run(loss=0)
        self.assertEqual(sum(F(x['delivered_kg']['exact']) for x in r['transport']['commodity_totals']),4)

    def test_person_years_are_converted_not_relabelled_kg(self):
        u,b,k=inputs();ob=list(k['obligations']);ob[2]=replace(ob[2],amount_unit='person_years',amount=1)
        k['obligations']=tuple(ob);r=food_delivery_snapshot(u['land_allocation']['food_budget'],b,**k)
        c=next(x for x in r['accounts']['conversions'] if x['obligation_id']=='town-eating')
        self.assertEqual(c['energy_kcal'],3000)
        self.assertEqual(c['commodity_kg'],{'beans':F(3,4),'grain':F(3,2)})

    def test_explicit_period_conversion_reaches_solver(self):
        r=run();self.assertEqual(r['period_seconds'],365*86400)

    def test_non_terrestrial_day_duration_is_not_overwritten(self):
        u,b,k=inputs();k['day_duration_seconds']=90000
        r=food_delivery_snapshot(u['land_allocation']['food_budget'],b,**k)
        self.assertEqual(r['period_seconds'],365*90000)
        self.assertEqual(F(r['transport']['period']['duration_seconds']['exact']),365*90000)

    def test_unknown_day_duration_does_not_default_to_earth(self):
        u,b,k=inputs();k['day_duration_seconds']=None
        r=food_delivery_snapshot(u['land_allocation']['food_budget'],b,**k)
        self.assertEqual(r['status'],'UNKNOWN');self.assertIsNone(r['transport'])

    def test_invalid_day_duration_rejected(self):
        u,b,k=inputs()
        for value in (False,0,-1,float('nan'),float('inf'),'86400'):
            k['day_duration_seconds']=value
            with self.assertRaises(ValueError):food_delivery_snapshot(u['land_allocation']['food_budget'],b,**k)

    def test_commodity_raw_mass_basis_rejected(self):
        u,b,k=inputs();k['commodities']=tuple(replace(x,mass_basis='raw_crop_kg') for x in k['commodities'])
        with self.assertRaises(ValueError):food_delivery_snapshot(u['land_allocation']['food_budget'],b,**k)

    def test_missing_objective_weight_is_not_default_priority(self):
        u,b,k=inputs();k['demand_weights'].pop(('town-eating','grain'))
        with self.assertRaises(ValueError):food_delivery_snapshot(u['land_allocation']['food_budget'],b,**k)

    def test_unknown_source_ledger_prevents_shipping(self):
        u,b,k=inputs();k['source_ledger_complete']=False
        r=food_delivery_snapshot(u['land_allocation']['food_budget'],b,**k)
        self.assertEqual(r['status'],'UNKNOWN');self.assertIsNone(r['transport'])

    def test_unknown_network_has_no_fabricated_closure(self):
        u,b,k=inputs();k['network_complete']=False
        r=food_delivery_snapshot(u['land_allocation']['food_budget'],b,**k)
        self.assertFalse(r['transport']['solved']);self.assertIsNone(r['closure'])

    def test_unknown_harvest_does_not_become_inventory(self):
        u,b,k=inputs();budget=copy.deepcopy(u['land_allocation']['food_budget'])
        removed=budget['rows'].pop();budget['unknown_parcel_ids'].append(removed['parcel_id'])
        r=food_delivery_snapshot(budget,b,**k)
        self.assertEqual(r['status'],'UNKNOWN');self.assertIsNone(r['transport'])

    def test_reusing_imported_source_cannot_duplicate_supply(self):
        u,b,k=inputs();imported=food.stocks_from_food_budget(u['land_allocation']['food_budget'],b,k['period'],source_id=k['source_id'],one_representative_harvest_in_period=True)
        k['inventory_stocks']=(replace(imported['stocks'][0],stock_id='renamed'),)
        with self.assertRaises(ValueError):food_delivery_snapshot(u['land_allocation']['food_budget'],b,**k)

    def test_delivered_remote_reserve_not_recurring_consumption(self):
        u,b,k=inputs();obs=list(k['obligations']);obs[2]=replace(obs[2],kind='one_off_reserve',recurrence='one_off')
        k['obligations']=tuple(obs);k['policies']=(k['policies'][0],food.LocalPolicy('town',('one_off_reserve',),('town-eating',),True,E))
        r=food_delivery_snapshot(u['land_allocation']['food_budget'],b,**k)
        self.assertTrue(all(x['disposition']=='reserved_stock' for x in r['obligation_fulfilment'] if x['node_id']=='town'))

    def test_new_increment_remains_distinct_commitment(self):
        u,b,k=inputs();obs=list(k['obligations']);obs[2]=replace(obs[2],kind='new_increment')
        k['obligations']=tuple(obs);k['policies']=(k['policies'][0],food.LocalPolicy('town',(),(),True,E))
        r=food_delivery_snapshot(u['land_allocation']['food_budget'],b,**k)
        self.assertTrue(all(x['disposition']=='delivered_commitment' for x in r['obligation_fulfilment'] if x['node_id']=='town'))
        self.assertEqual(sum(x['initial_kg'] for x in r['closure']),10)

    def test_snow_liquid_is_used_as_crop_forcing(self):
        u,_,_=inputs();self.assertEqual(u['crop_liquid_mm'],20)
        self.assertEqual(u['snow_liquid']['liquid_input_m3'],'1/5')

    def test_reference_json_is_deterministic_and_does_not_claim_completion(self):
        a=food_reference();b=food_reference();self.assertEqual(a,b)
        json.dumps(a,allow_nan=False)
        for field in ('production_installed','physical_acceptance','joint_crop_transport_optimum','population_capacity_claim'):
            self.assertFalse(a['delivery'][field])


if __name__=='__main__':unittest.main()
