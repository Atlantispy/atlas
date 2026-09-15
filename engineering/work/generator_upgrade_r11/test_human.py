"""Small analytical/state/provenance tests against fresh-bound actual R2/R1 code."""
from copy import deepcopy
from fractions import Fraction as F
import hashlib
import json
from pathlib import Path
import unittest
from . import binding


def test_data_bindings():
    path = Path(__file__).resolve().parents[2]/'outputs/generator-upgrade-r10/seasonal-reference-01/n-worker-reference/full-result.json'
    return {str(path): 'f191389d93c411f81e7003e5edf96551b53dc945e359dc705d83d00c64a0930e'}


class HumanTests(unittest.TestCase):
    reference_product = None
    actual_ecosystem_harvest_product = None
    actual_water_delivery_product = None

    @classmethod
    def setUpClass(cls):
        cls.bundle = binding.load()
        cls.h = cls.bundle.module('human')
        cls.t = cls.bundle.transport
        cls.a = cls.bundle.agroclimate
        cls.reference_product = cls.h.run_year(cls.t, **cls.h.reference_inputs(source_binding_sha256=cls.bundle.source_sha256,commodity_id='grain'))

    def inputs(self):
        return self.h.reference_inputs(source_binding_sha256=self.bundle.source_sha256,commodity_id='grain')

    def run_case(self, args=None, **kw):
        return self.h.run_year(self.t, **(args or self.inputs()), **kw)

    def harvest(self, event='window-1', at='10', amount='10', ident='harvest-1'):
        return {'harvest_id': ident, 'settlement_id': 'upper', 'commodity_id': 'grain', 'support_id': 'upper',
            'quantity_kg': amount, 'mass_basis': 'EDIBLE_DRY_FOOD_KG', 'available_at_seconds': at,
            'source_event_id': event, 'source_input_sha256': 'a'*64, 'source_use_id': ident+'-source',
            'evidence_id': 'synthetic harvested-food material evidence', 'source_status': 'SYNTHETIC TEST'}

    def delivery(self, event='window-1', at='10', amount='10', ident='allocation-1'):
        return {'allocation_id': ident, 'delivery_id': ident+'-delivery', 'receiving_sink_id': 'water-sink-lower',
            'settlement_id': 'lower', 'delivered_volume_m3': amount, 'available_at_seconds': at,
            'available_after_seconds': at,
            'source_event_id': event, 'source_input_sha256': 'a'*64,
            'evidence_id': 'actual predebited synthetic terminal', 'source_status': 'SYNTHETIC TEST'}

    def rule(self):
        return {'metric_id': 'road-snow', 'support_id': 'pass', 'unit': 'm', 'full_service_at': '0',
            'zero_service_at': '1', 'evidence_id': 'synthetic pass response', 'whole_window_scenario': True}

    def obs(self, event='window-1', value='1/2'):
        return {'road-snow': {'kind': 'SNOW_WATER_EQUIVALENT', 'event_id': event, 'support_id': 'pass', 'unit': 'm',
            'value': value, 'temporal_support': 'INTERVAL_HELD', 'source_input_sha256': 'a'*64,
            'evidence_id': 'synthetic exact snow', 'source_status': 'SYNTHETIC TEST'}}

    def test_actual_retained_transport_executes(self):
        out = self.reference_product
        self.assertEqual(out['status'], 'COMPLETE')
        self.assertEqual(out['events'][0]['transport']['schema'], 'diadem.multicommodity-transport.r2')
        self.assertEqual(out['events'][0]['transport']['certificate']['arithmetic'], 'EXACT_RATIONAL_REPRESENTED_FLOWS')

    def test_independent_capacity_loss_cut(self):
        out = self.reference_product['events'][0]
        # 10 s minus conservative 2 s travel margin: 8 kg shared dispatch,
        # 10% loss leaves 7.2 kg, so 12 kg demand has 4.8 kg shortage.
        self.assertEqual(out['dispatch_horizon_seconds'], '8')
        self.assertEqual(F(out['food_service'][0]['delivered_kg']), F(36,5))
        self.assertEqual(F(out['food_service'][0]['shortage_kg']), F(24,5))
        self.assertEqual(F(out['food_totals'][0]['transport_loss_kg']), F(4,5))

    def test_independent_all_stock_ledgers(self):
        for event in self.reference_product['events']:
            for row in event['water']:
                self.assertEqual(F(row['opening_m3'])+F(row['opening_delivery_m3'])+F(row['closing_delivery_m3']),
                    sum(F(row[k]) for k in ('opening_spill_m3','closing_spill_m3','loss_m3','consumed_service_m3','closing_m3')))
            for row in event['food_totals']:
                self.assertEqual(F(row['opening_kg'])+F(row['harvest_kg']),
                    sum(F(row[k]) for k in ('closing_kg','consumed_service_kg','transport_loss_kg','storage_loss_and_discard_kg')))

    def test_food_and_water_carried_not_reset(self):
        state = self.reference_product['state']
        self.assertEqual(state['food_kg']['upper']['grain'], '14')
        self.assertEqual(state['water_m3'], {'upper':'0','lower':'0'})
        self.assertEqual(self.reference_product['events'][1]['water_service'][0]['delivered_m3'], '2')

    def test_end_harvest_not_available_early(self):
        args = self.inputs(); args['initial_state']['food_kg']['upper']['grain'] = '0'
        args['events'][0]['harvests'] = [self.harvest()]
        out = self.run_case(args)
        self.assertEqual(out['events'][0]['food_service'][0]['delivered_kg'], '0')
        self.assertEqual(F(out['events'][1]['food_service'][0]['delivered_kg']), F(36,5))

    def test_opening_harvest_available(self):
        args = self.inputs(); args['initial_state']['food_kg']['upper']['grain'] = '0'
        args['events'][0]['harvests'] = [self.harvest(at='0')]
        self.assertEqual(F(self.run_case(args)['events'][0]['food_service'][0]['delivered_kg']), F(36,5))

    def test_end_water_delivery_is_next_window_stock(self):
        args = self.inputs(); args['events'][0]['water_deliveries'] = [self.delivery()]
        out = self.run_case(args)
        self.assertEqual(out['events'][0]['water_service'][1]['delivered_m3'], '2')
        self.assertEqual(out['events'][1]['water_service'][1]['delivered_m3'], '4')
        self.assertEqual(out['state']['water_m3']['lower'], '6')

    def test_finite_storage_spill_and_attrition(self):
        args = self.inputs(); args['events'][0]['water_deliveries'] = [self.delivery(at='0', amount='30')]
        args['events'][0]['water_loss_fraction']['lower'] = '1/10'
        row = self.run_case(args)['events'][0]['water'][1]
        self.assertEqual((row['opening_spill_m3'],row['loss_m3'],row['closing_m3']), ('12','2','14'))

    def test_food_storage_discards_do_not_become_exports(self):
        args = self.inputs(); args['settlements'][0]['food_capacity_kg']['grain'] = '30'
        args['events'][0]['harvests'] = [self.harvest(at='0', amount='50')]
        args['events'][0]['food_loss_fraction']['upper']['grain'] = '1/2'
        row = self.run_case(args)['events'][0]['food'][0]
        self.assertEqual((row['opening_storage_discard_kg'],row['storage_loss_kg']), ('50','15'))

    def test_local_service_and_reserves_precede_export(self):
        args = self.inputs(); event = args['events'][0]
        local = deepcopy(event['food_demands'][0]); local.update(demand_id='local',settlement_id='upper',required_kg='25')
        event['food_demands'].append(local); event['food_demand_order'].append('local')
        event['protected_food_reserve_kg']['upper']['grain'] = '3'
        out = self.run_case(args)['events'][0]
        self.assertEqual(next(r for r in out['food_service'] if r['demand_id']=='local')['delivered_kg'], '25')
        self.assertEqual(F(next(r for r in out['food_service'] if r['settlement_id']=='lower')['delivered_kg']), F(9,5))
        self.assertEqual(out['food'][0]['closing_kg'], '3')

    def test_water_priority_is_explicit_not_id_sort(self):
        args=self.inputs(); e=args['events'][0]
        second=deepcopy(e['water_demands'][0]); second.update(demand_id='zzz',required_m3='5')
        e['water_demands'].append(second); e['water_demand_order'].insert(0,'zzz')
        rows=self.run_case(args)['events'][0]['water_service']
        self.assertEqual((rows[0]['demand_id'],rows[0]['delivered_m3'],rows[1]['delivered_m3']),('zzz','5','1'))

    def test_shared_bidirectional_multicommodity_capacity(self):
        args=self.inputs(); args['commodities'].append({**args['commodities'][0], 'commodity_id':'beans'})
        for s in args['settlements']:
            s['food_capacity_kg']['beans']='100'
        args['initial_state']['food_kg']['upper']['beans']='0'; args['initial_state']['food_kg']['lower']['beans']='30'
        for link in args['network']['links']:
            rule=deepcopy(link['rules'][0]); rule['commodity_id']='beans'; link['rules'].append(rule)
        for e in args['events']:
            for s in ('upper','lower'):
                e['food_loss_fraction'][s]['beans']='0'; e['protected_food_reserve_kg'][s]['beans']='0'
            demand=deepcopy(e['food_demands'][0]); demand.update(demand_id=e['event_id']+'-beans',settlement_id='upper',commodity_id='beans')
            e['food_demands'].append(demand); e['food_demand_order'].append(demand['demand_id'])
        out=self.run_case(args)['events'][0]
        self.assertEqual(F(out['transport']['capacity_groups'][0]['used_kg']['exact']),8)
        self.assertEqual(sum(F(r['delivered_kg']) for r in out['food_service']),F(36,5))
        self.assertEqual([r['residual_kg'] for r in out['food_totals']],['0','0'])

    def test_closed_weather_group_known_shortage_not_unknown(self):
        args=self.inputs(); args['network']['capacity_groups'][0]['hazard_rules']=[self.rule()]
        for e in args['events']: e['hazard_observations']=self.obs(e['event_id'], '1')
        out=self.run_case(args)
        self.assertEqual(out['status'],'COMPLETE')
        self.assertEqual(out['events'][0]['food_service'][0]['status'],'SHORTAGE')
        self.assertEqual(out['events'][0]['food_service'][0]['delivered_kg'],'0')

    def test_partial_weather_derating_exact(self):
        args=self.inputs(); args['network']['capacity_groups'][0]['hazard_rules']=[self.rule()]
        for e in args['events']: e['hazard_observations']=self.obs(e['event_id'])
        out=self.run_case(args)['events'][0]
        self.assertEqual(F(out['food_service'][0]['delivered_kg']),F(18,5))
        self.assertEqual(out['capacity_responses'][0]['capacity_kg'],'4')

    def test_missing_transport_hazard_invalidates_causal_suffix(self):
        args=self.inputs(); args['network']['capacity_groups'][0]['hazard_rules']=[self.rule()]
        args['events'][0]['hazard_observations']=self.obs()
        out=self.run_case(args)
        self.assertEqual((out['status'],out['accepted_events']),('UNKNOWN',1))
        self.assertEqual(out['state']['elapsed_seconds'],'10')
        self.assertEqual(out['events'][1]['status'],'UNKNOWN')

    def test_exposure_is_not_probability_or_casualties(self):
        args=self.inputs(); args['settlements'][0]['exposure_rules']=[self.rule()]
        for e in args['events']: e['hazard_observations']=self.obs(e['event_id'])
        row=self.run_case(args)['events'][0]['hazard_exposure'][0]
        self.assertEqual(row['exposed_fixed_population'],10)
        self.assertIsNone(row['probability']); self.assertIsNone(row['expected_casualties'])

    def test_instantaneous_hazard_does_not_close_whole_month(self):
        obs=self.obs(); obs['road-snow']['temporal_support']='AT_INSTANT'
        with self.assertRaisesRegex(ValueError,'instantaneous'):
            self.h.hazard_response(self.rule(),obs,event_id='window-1')

    def test_hazard_units_support_and_calendar_guard(self):
        for field,value in [('unit','mm'),('support_id','other'),('event_id','other')]:
            obs=self.obs(); obs['road-snow'][field]=value
            with self.assertRaisesRegex(ValueError,'mismatch'):
                self.h.hazard_response(self.rule(),obs,event_id='window-1')

    def test_stability_response_reverse_direction(self):
        rule=self.rule(); rule.update(unit='1',full_service_at='2',zero_service_at='1')
        obs=self.obs(value='3/2'); obs['road-snow'].update(kind='FACTOR_OF_SAFETY',unit='1')
        self.assertEqual(self.h.hazard_response(rule,obs,event_id='window-1')['service_fraction'],'1/2')

    def test_missing_network_not_false_disconnection(self):
        args=self.inputs(); args['network']['network_complete']=False
        out=self.run_case(args)
        self.assertEqual((out['status'],out['accepted_events']),('UNKNOWN',0))

    def test_no_path_is_distinct_from_known_zero_stock(self):
        args=self.inputs(); args['network']['links']=[]
        out=self.run_case(args)
        self.assertEqual(out['events'][0]['food_service'][0]['status'],'NO_PATH_FROM_KNOWN_STOCK')
        args['initial_state']['food_kg']['upper']['grain']='0'
        self.assertEqual(self.run_case(args)['events'][0]['food_service'][0]['status'],'SHORTAGE')

    def test_unknown_initial_stock_is_not_zero(self):
        args=self.inputs(); args['initial_state']['food_kg']['upper']['grain']=None
        out=self.run_case(args)
        self.assertEqual(out['status'],'UNKNOWN'); self.assertIsNone(out['state'])

    def test_duplicate_water_source_cannot_reenter(self):
        args=self.inputs(); args['events'][0]['water_deliveries']=[self.delivery()]
        args['events'][1]['water_deliveries']=[self.delivery(event='window-2',at='20')]
        with self.assertRaisesRegex(ValueError,'reused'): self.run_case(args)

    def test_duplicate_harvest_source_cannot_reenter_under_new_name(self):
        args=self.inputs(); a=self.harvest(); b=self.harvest(event='window-2',at='20',ident='new')
        b['source_use_id']=a['source_use_id']; args['events'][0]['harvests']=[a]; args['events'][1]['harvests']=[b]
        with self.assertRaisesRegex(ValueError,'reused'): self.run_case(args)

    def test_calendar_duration_and_coverage(self):
        args=self.inputs(); args['calendar'][1]['start_seconds']='11'
        with self.assertRaisesRegex(ValueError,'contiguous'): self.run_case(args)
        args=self.inputs(); args['events'].reverse()
        with self.assertRaisesRegex(ValueError,'ordered'): self.run_case(args)

    def test_midwindow_harvest_not_backdated(self):
        args=self.inputs(); args['events'][0]['harvests']=[self.harvest(at='5')]
        with self.assertRaisesRegex(ValueError,'boundary'): self.run_case(args)

    def test_distinct_producer_event_name_preserves_exact_interval_join(self):
        args=self.inputs(); row=self.harvest(event='actual-eco-event-12')
        args['events'][0]['harvests']=[row]
        with self.assertRaisesRegex(ValueError,'interval-end join'): self.run_case(args)
        row['source_interval']={'event_id':'actual-eco-event-12','start_seconds':'4','end_seconds':'10','binding':'actual source time verified'}
        out=self.run_case(args)
        self.assertEqual(out['status'],'COMPLETE')
        self.assertEqual(out['events'][0]['food'][0]['closing_harvest_kg'],'10')

    def test_travel_envelope_guard(self):
        args=self.inputs(); args['network']['links'][0]['travel_time_s']='11'
        with self.assertRaisesRegex(ValueError,'travel bound'): self.run_case(args)

    def test_constructive_uniform_dispatch_arrival_and_capacity(self):
        row=self.reference_product['events'][0]; horizon=F(row['dispatch_horizon_seconds']); duration=F(row['duration_seconds'])
        links={r['link_id']:r for r in self.inputs()['network']['links']}
        rate=F(0)
        for route in row['transport']['routes']:
            if F(route['dispatched_kg']['exact'])==0: continue
            path_time=sum(F(links[l]['travel_time_s']) for l in route['link_ids'])
            self.assertLessEqual(horizon+path_time,duration)
            rate += sum(F(g['load_kg']['exact'])/horizon for g in route['capacity_loads'])
        self.assertLessEqual(rate,1)

    def test_checkpoint_full_replay_and_stop_zero(self):
        args=self.inputs(); full=self.run_case(args); partial=self.run_case(args,stop_after=1)
        self.assertEqual(full,self.run_case(args,resume=partial['checkpoint']))
        zero=self.run_case(args,stop_after=0)
        self.assertEqual(full,self.run_case(args,resume=zero['checkpoint']))

    def test_checkpoint_forged_stock_or_prefix_rejected(self):
        args=self.inputs(); cp=self.run_case(args,stop_after=1)['checkpoint']
        cp['state']['food_kg']['upper']['grain']='999'
        with self.assertRaisesRegex(ValueError,'replay'): self.run_case(args,resume=cp)
        cp=self.run_case(args,stop_after=1)['checkpoint']; cp['prefix_sha256']='f'*64
        with self.assertRaisesRegex(ValueError,'replay'): self.run_case(args,resume=cp)

    def test_checkpoint_source_scenario_or_inputs_changed(self):
        args=self.inputs(); cp=self.run_case(args,stop_after=1)['checkpoint']
        for key in ('scenario_id','source_binding_sha256'):
            changed=deepcopy(args); changed[key]='f'*64
            with self.assertRaisesRegex(ValueError,'mismatch'): self.run_case(changed,resume=cp)

    def test_inputs_unchanged_and_strict_json(self):
        args=self.inputs(); before=deepcopy(args); out=self.run_case(args)
        self.assertEqual(args,before); json.dumps(out,allow_nan=False)
        self.assertEqual(out['fixed_settlements'],args['settlements'])

    def test_unknown_stock_no_partial_event_commit(self):
        args=self.inputs(); args['events'][0]['water_deliveries']=[self.delivery(at='0')]
        args['events'][0]['food_demands'][0]['required_kg']=None
        out=self.run_case(args)
        self.assertEqual(out['accepted_events'],0)
        self.assertEqual(out['state']['water_m3']['lower'],'2')
        self.assertEqual(out['state']['used_water_allocation_ids'],[])

    def test_harvest_carbon_conversion_exact_not_biomass_equals_food(self):
        record={'status':'MODELLED','event_id':'window-1','support_id':'upper','harvested_carbon_kg_m2':'2',
            'available_after_seconds':'10',
            'source_input_sha256':'a'*64,'source_use_id':'plot-1','evidence_id':'synthetic biomass','source_status':'SYNTHETIC TEST'}
        conversion={'carbon_fraction_dry_matter':'2/5','edible_fraction':'1/2','processing_loss_fraction':'1/10',
            'mass_basis':'EDIBLE_DRY_FOOD_KG','food_quality_evidence':'explicit hypothetical food assay',
            'evidence_id':'synthetic processing','source_status':'SYNTHETIC TEST'}
        out=self.h.harvest_from_ecosystem(record,harvest_id='h',settlement_id='upper',commodity_id='grain',
            support_id='upper',area_m2='10',conversion=conversion,available_at_seconds='10')
        self.assertEqual(F(out['quantity_kg']),F(45,2))
        self.assertEqual(out['conversion']['dry_mass_residual_kg'],'0')
        conversion['edible_fraction']=None
        with self.assertRaises(self.h.MissingEvidence):
            self.h.harvest_from_ecosystem(record,harvest_id='h',settlement_id='upper',commodity_id='grain',
                support_id='upper',area_m2='10',conversion=conversion,available_at_seconds='10')

    def test_water_helper_rejects_raw_runoff(self):
        record={'kind':'RAW_RUNOFF','status':'MODELLED','receiving_sink_id':'sink','evidence_id':'e','source_status':'SYNTHETIC TEST'}
        with self.assertRaises(self.h.MissingEvidence):
            self.h.water_delivery(record,settlement_id='upper',receiving_sink_id='sink',available_at_seconds='10')

    def test_actual_water_delivery_cannot_be_backdated(self):
        record={'kind':'ROUTED_WITHDRAWAL_DELIVERY','status':'MODELLED','receiving_sink_id':'sink',
            'allocation_id':'a','delivery_id':'d','event_id':'window-1','delivered_volume_m3':'2',
            'source_input_sha256':'a'*64,'available_after_seconds':'10','evidence_id':'e','source_status':'SYNTHETIC TEST'}
        with self.assertRaisesRegex(ValueError,'before'):
            self.h.water_delivery(record,settlement_id='upper',receiving_sink_id='sink',available_at_seconds='0')
        self.assertEqual(self.h.water_delivery(record,settlement_id='upper',receiving_sink_id='sink',available_at_seconds='10')['available_after_seconds'],'10')

    def test_public_event_also_rejects_water_backdate(self):
        args=self.inputs(); row=self.delivery(at='0'); row['available_after_seconds']='10'
        args['events'][0]['water_deliveries']=[row]
        with self.assertRaisesRegex(ValueError,'before'): self.run_case(args)

    def test_positive_crop_irrigation_needs_exact_real_debit(self):
        root=dict(field_capacity_m3_m3=.3,wilting_point_m3_m3=.1,rooting_depth_m=1.,depletion_fraction=.5,evidence='test',source_status='SYNTHETIC TEST')
        forcing=[dict(precipitation_mm=0.,runoff_mm=0.,net_irrigation_mm=1.,capillary_rise_mm=0.,potential_crop_et_mm=1.)]
        row=dict(allocation_id='irrigation-one',delivery_id='irrigation-delivery-one',kind='ROUTED_WITHDRAWAL_DELIVERY',status='MODELLED',support_id='upper',
            receiving_sink_id='plot',source_input_sha256='b'*64,day_index=0,available_after_seconds='0',
            delivered_volume_m3='2',application_efficiency='1/2',application_evidence='supplied',evidence_id='test',source_status='SYNTHETIC TEST')
        parameters=dict(initial_depletion_mm=0.,potential_yield_kg_m2=2.,yield_response_factor=1.,minimum_valid_et_ratio=.1,
            evidence='test',source_status='SYNTHETIC TEST',yield_mass_basis='DRY_HARVEST_KG',irrigation_deliveries=[row],
            day_duration_seconds='10',season_start_seconds='0',irrigation_sink_id='plot')
        conversion=dict(carbon_fraction_dry_matter='1/2',edible_fraction='1/2',processing_loss_fraction='0',mass_basis='EDIBLE_DRY_FOOD_KG',
            food_quality_evidence='explicit synthetic crop',evidence_id='test',source_status='SYNTHETIC TEST')
        args=dict(root_zone=root,daily_forcing=forcing,crop_parameters=parameters,area_m2='1000',conversion=conversion,
            harvest_id='h',settlement_id='upper',commodity_id='grain',support_id='upper',event_id='window-1',source_use_id='crop1',available_at_seconds='10')
        out=self.h.harvest_from_crop(self.a,**args)
        ledger=out['harvest']['conversion']['irrigation_debits'][0]
        self.assertEqual((ledger['gross_delivery_m3'],ledger['net_root_zone_m3'],ledger['application_loss_m3']),('2','1','1'))
        parameters['irrigation_deliveries'][0]['delivered_volume_m3']='1'
        with self.assertRaisesRegex(ValueError,'do not match'): self.h.harvest_from_crop(self.a,**args)
        parameters['irrigation_deliveries'][0]['delivered_volume_m3']='2'
        parameters['irrigation_deliveries'][0]['available_after_seconds']='1'
        with self.assertRaisesRegex(ValueError,'before'): self.h.harvest_from_crop(self.a,**args)

    def test_crop_allocation_cannot_also_supply_reservoir(self):
        args=self.inputs(); crop=self.harvest(); crop['conversion']={'irrigation_allocation_ids':['allocation-1'],'irrigation_delivery_ids':['allocation-1-delivery']}
        args['events'][0]['harvests']=[crop]; args['events'][0]['water_deliveries']=[self.delivery()]
        with self.assertRaisesRegex(ValueError,'also used'): self.run_case(args)

    def test_same_crop_terminal_cannot_be_relabelled_as_new_allocation(self):
        args=self.inputs(); crop=self.harvest(); crop['conversion']={
            'irrigation_allocation_ids':['crop-allocation'], 'irrigation_delivery_ids':['allocation-1-delivery']}
        args['events'][0]['harvests']=[crop]; args['events'][0]['water_deliveries']=[self.delivery()]
        with self.assertRaisesRegex(ValueError,'terminal delivery reused'): self.run_case(args)

    def test_full_ecosystem_bridge_preserves_law_clock_and_source(self):
        initial={'live_carbon_kg_m2':'4','organic_state':{'fast_carbon_kg_m2':[0,1],'slow_carbon_kg_m2':[0,1]}}
        inputs={'plant_law':{'carbon_fraction_dry_matter':'2/5','evidence':'test','source_status':'SYNTHETIC TEST'},
            'initial_state':initial,'events':[{'event_id':'window-1','support_id':'upper','layer_id':'L','month_id':1,
                'harvest_fraction':'1/2','organic_forcing':{'duration_seconds':'10','fast_litter_carbon_kg_m2_s':'0','slow_litter_carbon_kg_m2_s':'0'}}]}
        result={'schema':'diadem.seasonal-ecosystem.r11','source_binding_sha256':'b'*64,'geometry_sha256':'c'*64,
            'scenario_id':'eco','inputs':inputs,'inputs_sha256':self.h.digest(inputs),'events':[{
                'event_id':'window-1','status':'MODELLED','support_id':'upper','layer_id':'L','harvested_carbon_kg_m2':'2',
                'harvested_dry_matter_kg_m2':'5','start_seconds_in_year':'0','duration_seconds':'10','month_id':1,
                'initial_state':initial,'end_state':{**initial,'live_carbon_kg_m2':'2'},
                'net_production_kg_c_m2':'0','potential_net_production_kg_c_m2':'0','litter_carbon_kg_m2':'0',
                'organic_producer':{'carbon':{'exported_atmospheric_carbon_kg_m2':'0'}},
                'budgets_kg_m2':{'C':{'initial':'4','final':'2','net_atmospheric_input':'0','external_litter_input':'0',
                    'heterotrophic_export':'0','harvest_export':'2','numerical_residual':'0'}}}]}
        conversion=dict(carbon_fraction_dry_matter='2/5',edible_fraction='1/2',processing_loss_fraction='0',mass_basis='EDIBLE_DRY_FOOD_KG',
            food_quality_evidence='explicit synthetic biomass',evidence_id='test',source_status='SYNTHETIC TEST')
        args=dict(event_id='window-1',settlement_id='upper',commodity_id='grain',support_id='upper',area_m2='10',
            conversion=conversion,source_binding_sha256='b'*64,geometry_sha256='c'*64,scenario_id='eco')
        out=self.h.harvest_from_ecosystem_result(result,**args)
        self.assertEqual((out['quantity_kg'],out['available_at_seconds']),('25','10'))
        self.assertEqual(out['source_input_sha256'],self.h.digest(result))
        forged=deepcopy(result); forged['events'][0]['harvested_carbon_kg_m2']='4'; forged['events'][0]['harvested_dry_matter_kg_m2']='10'
        with self.assertRaisesRegex(ValueError,'harvest-fraction'): self.h.harvest_from_ecosystem_result(forged,**args)
        conversion['carbon_fraction_dry_matter']='1/2'
        with self.assertRaisesRegex(ValueError,'retain actual'): self.h.harvest_from_ecosystem_result(result,**args)
        conversion['carbon_fraction_dry_matter']='2/5'; result['inputs_sha256']='f'*64
        with self.assertRaisesRegex(ValueError,'digest'): self.h.harvest_from_ecosystem_result(result,**args)

    def test_actual_crop_helper_no_monthly_disaggregation(self):
        root=dict(field_capacity_m3_m3=.3,wilting_point_m3_m3=.1,rooting_depth_m=1.,depletion_fraction=.5,evidence='test',source_status='SYNTHETIC TEST')
        forcing=[dict(precipitation_mm=0.,runoff_mm=0.,net_irrigation_mm=0.,capillary_rise_mm=0.,potential_crop_et_mm=1.)]*3
        parameters=dict(initial_depletion_mm=0.,potential_yield_kg_m2=2.,yield_response_factor=1.,minimum_valid_et_ratio=.1,
            evidence='test',source_status='SYNTHETIC TEST',yield_mass_basis='DRY_HARVEST_KG',irrigation_deliveries=[],
            day_duration_seconds='1',season_start_seconds='0')
        conversion=dict(carbon_fraction_dry_matter='1/2',edible_fraction='1/2',processing_loss_fraction='0',mass_basis='EDIBLE_DRY_FOOD_KG',
            food_quality_evidence='synthetic explicit crop food law',evidence_id='test',source_status='SYNTHETIC TEST')
        out=self.h.harvest_from_crop(self.a,root_zone=root,daily_forcing=forcing,crop_parameters=parameters,area_m2='10',
            conversion=conversion,harvest_id='h',settlement_id='upper',commodity_id='grain',support_id='upper',event_id='window-1',
            source_use_id='crop-one-season',available_at_seconds='10')
        self.assertEqual(out['crop']['schema'],'diadem.crop-water-yield.r1')
        self.assertEqual(out['crop']['status'],'MODELLED'); self.assertEqual(out['harvest']['quantity_kg'],'10')
        self.assertEqual(len(out['crop']['water']['rows']),3)

    def test_actual_saved_parent_to_ecosystem_to_food(self):
        path, expected = next(iter(test_data_bindings().items()))
        raw = Path(path).read_bytes(); self.assertEqual(hashlib.sha256(raw).hexdigest(),expected)
        parent=json.loads(raw)
        codec=self.bundle.parent.graph.load('work.generator_upgrade_r10.payloads')
        unit=codec.unpack(next(iter(parent['state']['results'].values())))
        eco=self.bundle.module('ecosystem')
        spec=eco.reference_spec(self.bundle.organic,self.bundle.fertility,unit); spec.pop('reference_join')
        result=eco.run_year(self.bundle.organic,self.bundle.fertility,**spec,
            source_binding_sha256=self.bundle.source_sha256,scenario_id='actual-parent-join',evidence='actual test join',source_status='SYNTHETIC TEST')
        self.assertEqual(result['status'],'MODELLED_SEASONAL_ECOSYSTEM')
        last=result['events'][-1]
        conversion={'carbon_fraction_dry_matter':'2/5','edible_fraction':'1/2','processing_loss_fraction':'1/10',
            'mass_basis':'EDIBLE_DRY_FOOD_KG','food_quality_evidence':'SYNTHETIC TEST: not a claim that a temperate stand is an edible crop',
            'evidence_id':'test artificial food conversion','source_status':'SYNTHETIC TEST'}
        args=dict(event_id=last['event_id'],settlement_id=unit['cell_id'],commodity_id='synthetic-food',support_id=last['support_id'],
            area_m2='10',conversion=conversion,source_binding_sha256=self.bundle.source_sha256,
            geometry_sha256=result['geometry_sha256'],scenario_id='actual-parent-join')
        product=self.h.harvest_from_ecosystem_result(result,**args)
        self.assertGreater(F(product['quantity_kg']),0)
        self.assertEqual(F(product['quantity_kg']),F(last['harvested_dry_matter_kg_m2'])*10*F(1,2)*F(9,10))
        self.assertEqual(F(product['available_after_seconds']),sum(F(e['duration_seconds']) for e in result['events']))
        self.assertGreater(len(product['conversion']['producer']['evidence_id']),256)
        forged=deepcopy(result); forged['events'][-1]['harvested_carbon_kg_m2']=str(2*F(last['harvested_carbon_kg_m2']))
        forged['events'][-1]['harvested_dry_matter_kg_m2']=str(2*F(last['harvested_dry_matter_kg_m2']))
        with self.assertRaisesRegex(ValueError,'harvest-fraction'):
            self.h.harvest_from_ecosystem_result(forged,**args)
        self.__class__.actual_ecosystem_harvest_product=product

    def test_actual_finite_water_to_settlement_bridge(self):
        water=self.bundle.module('water')
        spec=water.reference_spec([{'event_id':'window-1','duration_seconds':'10','inflows_m3':{'upper':'2','lower':'1'}}],
                                  {'upper':'1','lower':'1'})
        result=water.run(spec['network'],spec['initial'],spec['events'],controls=spec['controls'],
            source_binding_sha256=self.bundle.source_sha256,scenario_id='water-join')
        rows=self.h.water_deliveries_from_result(result,event_id='window-1',settlement_by_sink={'human-reservoir':'lower'},
            source_binding_sha256=self.bundle.source_sha256,scenario_id='water-join')
        self.assertEqual(len(rows),1); self.assertEqual(rows[0]['available_after_seconds'],'10')
        self.assertEqual(rows[0]['actual_routed_delivery']['kind'],'ALLOCATION')
        args=self.inputs(); args['settlements'][1]['receiving_sink_id']='human-reservoir'; args['events'][0]['water_deliveries']=rows
        product=self.run_case(args)
        self.assertEqual(product['events'][0]['water_service'][1]['delivered_m3'],'2')
        self.assertEqual(F(product['events'][0]['water'][1]['closing_m3']),F(rows[0]['delivered_volume_m3']))
        self.__class__.actual_water_delivery_product=rows
        args=dict(event_id='window-1',settlement_by_sink={'human-reservoir':'lower'},
            source_binding_sha256=self.bundle.source_sha256,scenario_id='water-join')
        forged=deepcopy(result); forged['events'][0]['deliveries'][0]['available_after_seconds']='0'
        with self.assertRaisesRegex(ValueError,'availability'): self.h.water_deliveries_from_result(forged,**args)
        forged=deepcopy(result); d=forged['events'][0]['deliveries'][0]
        d['delivered_volume_m3']=str(2*F(d['delivered_volume_m3'])); d['delivered_mass_kg']=str(2*F(d['delivered_mass_kg']))
        with self.assertRaisesRegex(ValueError,'withdrawal|ledger'): self.h.water_deliveries_from_result(forged,**args)

    def test_invalid_boolean_negative_and_population(self):
        for value in (True,-1,float('inf')):
            args=self.inputs(); args['initial_state']['water_m3']['upper']=value
            with self.assertRaises(ValueError): self.run_case(args)
        args=self.inputs(); args['settlements'][0]['population']=1.5
        with self.assertRaises(ValueError): self.run_case(args)

    def test_capacity_exact_if_representable(self):
        row=self.h.capacity_representation('13/17',self.inputs()['network']['capacity_representation'])
        self.assertEqual(row['method'],'EXACT'); self.assertEqual(row['reduction_kg'],'0')

    def test_capacity_independent_downward_oracle(self):
        exact=F(7,2)+F(1,2**200)
        row=self.h.capacity_representation(exact,self.inputs()['network']['capacity_representation'])
        self.assertEqual(F(row['represented_capacity_kg']),F(7,2))
        self.assertEqual(F(row['reduction_kg']),F(1,2**200))
        self.assertFalse(row['original_capacity_optimum_certified'])
        self.assertLessEqual(F(row['represented_capacity_kg']),exact)

    def test_capacity_no_implicit_rounding(self):
        args=self.inputs(); args['network'].pop('capacity_representation')
        args['network']['capacity_groups'][0]['capacity_rate_kg_s']=str(F(1)+F(1,2**200))
        out=self.run_case(args)
        self.assertEqual(out['status'],'OUTSIDE_REGIME')
        self.assertIn('rational envelope',out['events'][0]['reason'])

    def test_capacity_positive_underflow_rejected(self):
        law=self.inputs()['network']['capacity_representation']
        with self.assertRaisesRegex(ValueError,'cannot disappear'):
            self.h.capacity_representation(F(1,2**200),law)

    def test_capacity_declared_error_allowance_not_bypassed(self):
        law=self.inputs()['network']['capacity_representation']; law['max_absolute_loss_kg']='0'
        with self.assertRaisesRegex(ValueError,'allowance'):
            self.h.capacity_representation(F(1)+F(1,2**200),law)

    def test_capacity_malformed_numerical_law_rejected(self):
        law=self.inputs()['network']['capacity_representation']
        for quantum in ('1/3','0',True,'1/'+str(2**200)):
            bad=deepcopy(law); bad['quantum_kg']=quantum
            with self.assertRaises(ValueError): self.h.capacity_representation(1,bad)

    def test_actual_all_snow_monthly_capacity_inputs(self):
        path,expected=next(iter(test_data_bindings().items())); raw=Path(path).read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(),expected); parent=json.loads(raw)
        p=self.bundle.module('pipeline'); recipe=self.bundle.reference.recipe(self.bundle)
        groups=p.parent_units(self.bundle,recipe,parent); evidence=[]
        for snow in parent['climate']['members']:
            key=next(k for k in sorted(groups) if k.startswith(snow+'/')); group=groups[key]
            water=self.bundle.module('water'); spec,_=p.water_inputs(self.bundle,recipe,group,parent['climate']['members'][snow])
            routed=water.run(spec['network'],spec['initial'],spec['events'],controls=spec['controls'],
                source_binding_sha256=self.bundle.source_sha256,scenario_id=key)
            args=p.human_inputs(self.bundle,recipe,parent,key,group,routed,{})
            out=self.run_case(args); self.assertEqual(out['status'],'COMPLETE')
            self.assertEqual(len(out['events']),12)
            rows=[r for e in out['events'] for r in e['capacity_responses']]
            for row in rows:
                rep=row['numerical_representation']; exact=F(row['base_capacity_kg'])*F(row['service_fraction'])
                self.assertEqual(F(row['capacity_kg']),exact)
                self.assertEqual(F(rep['exact_capacity_kg']),exact)
                self.assertEqual(F(rep['represented_capacity_kg'])+F(rep['reduction_kg']),exact)
                self.assertLessEqual(F(rep['reduction_kg']),F(args['network']['capacity_representation']['max_absolute_loss_kg']))
            if snow=='LOW_DDF3_SIGMA2':
                self.assertTrue(any(r['numerical_representation']['method']=='EXPLICIT_DYADIC_INNER' for r in rows))
                args['network'].pop('capacity_representation'); old=self.run_case(args)
                self.assertEqual(old['status'],'OUTSIDE_REGIME')
                self.assertEqual(old['accepted_events'],3)
                self.assertIn('capacity:shared-road',old['events'][3]['reason'])
            evidence.append({'scenario_id':key,'accepted_events':len(out['events']),
                'capacity_rows':rows,'source_parent_sha256':expected})
        self.__class__.actual_capacity_products=evidence


if __name__ == '__main__':
    unittest.main()
