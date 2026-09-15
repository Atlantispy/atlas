import json
import math
import tempfile
import unittest
from copy import deepcopy
from fractions import Fraction as F
from pathlib import Path
from . import thermal as t, water as w


def fixture():
    spec=w.reference_spec([{'event_id':'one','duration_seconds':1,'inflows_m3':{'a':0,'b':0}}],{'a':0,'b':0})
    nodes={key:deepcopy(spec['network']['nodes'][key]) for key in ('a','b')}
    for key,node in nodes.items():
        node.update(datum_m=0,storage_area_m2=1,liquid_density_kg_m3=1,ice_density_kg_m3=1,capacity_m3=100)
        node['thermal'].update(solid_heat_capacity_j_k=10,liquid_heat_capacity_j_kg_k=2,ice_heat_capacity_j_kg_k=1,latent_heat_j_kg=100,freezing_temperature_k=10)
    network=dict(spec['network'],nodes=nodes,links=[{'link_id':'ab','left':'a','right':'b','conductance_m2_s':'1/10','liquid_fraction_exponent':1,'evidence':'Explicit analytical test'}])
    state=w.initial_state(network,{key:t.initial_cell(node['thermal'],10 if key=='a' else 0,20) for key,node in nodes.items()})
    event={'event_id':'one','duration_seconds':1,'inflows':[],'withdrawals':[],
        'heat_boundaries':{key:{'temperature_k':20,'conductance_w_k':0,'evidence':'Explicit insulated bath'} for key in nodes},
        'evidence':'Explicit test event','source_status':'SYNTHETIC TEST'}
    return {'network':network,'initial':state,'events':[event],'controls':{'max_dt_seconds':'1/10','stability_fraction':'1/4','max_substeps':1000,'energy_atol_j':'1/10000'}}


class WaterTests(unittest.TestCase):
    def run_case(self,spec=None,**kw):
        return w.run(**(fixture() if spec is None else spec),source_binding_sha256=kw.pop('source','a'*64),scenario_id='scenario',**kw)

    def test_actual_mass_heat_and_gross_link_ledgers(self):
        result=self.run_case(); self.assertEqual(result['status'],'MODELLED')
        row=result['events'][0]
        self.assertEqual(row['water_residual_kg'],'0'); self.assertEqual(row['energy_residual_j'],'0')
        self.assertGreater(F(row['gross_links']['ab']['left_to_right_kg']),0)
        for node in row['nodes'].values(): self.assertEqual(node['ledger']['energy_residual_j'],'0'); self.assertEqual(node['ledger']['water_residual_kg'],'0')

    def test_no_forcing_zero_conductance_identity(self):
        spec=fixture(); spec['network']['links'][0]['conductance_m2_s']=0; spec['initial']=w.initial_state(spec['network'],spec['initial']['nodes'])
        result=self.run_case(spec); self.assertEqual(result['final_state']['nodes'],spec['initial']['nodes'])

    def test_linear_two_reservoir_independent_refinement(self):
        errors=[]
        for n in (8,16,32):
            spec=fixture(); spec['controls']['max_dt_seconds']=str(F(1,n)); result=self.run_case(spec)
            mass=F(result['final_state']['nodes']['a']['water_mass_kg']); expected=5+5*math.exp(-.2)
            errors.append(abs(float(mass)-expected))
        self.assertTrue(1.9<errors[0]/errors[1]<2.1); self.assertTrue(1.9<errors[1]/errors[2]<2.1)

    def test_closed_network_total_stock_oracle(self):
        result=self.run_case(); self.assertEqual(sum(F(x['water_mass_kg']) for x in result['final_state']['nodes'].values()),10)

    def test_groundwater_head_reversal_real_direction(self):
        spec=fixture(); spec['network']['nodes']['a']['kind']='GROUNDWATER'; spec['network']['nodes']['b']['datum_m']=20
        spec['initial']=w.initial_state(spec['network'],{key:t.initial_cell(node['thermal'],10,20) for key,node in spec['network']['nodes'].items()})
        result=self.run_case(spec); flow=result['events'][0]['gross_links']['ab']
        self.assertGreater(F(flow['right_to_left_kg']),0); self.assertEqual(F(flow['left_to_right_kg']),0)

    def test_equal_mass_phase_expansion_cannot_create_head_difference(self):
        spec=fixture(); a=spec['network']['nodes']['a']; b=spec['network']['nodes']['b']
        a['ice_density_kg_m3']='1/2'; b['ice_density_kg_m3']='1/2'
        warm=w.node_snapshot(a,t.initial_cell(a['thermal'],10,20))
        icy=w.node_snapshot(b,t.initial_cell(b['thermal'],10,10,liquid_fraction_at_freezing='1/2'))
        self.assertEqual(warm['stage_m'],icy['stage_m']); self.assertGreater(F(icy['occupied_volume_m3']),F(warm['occupied_volume_m3']))

    def test_ice_bearing_groundwater_head_is_rejected_not_invented(self):
        spec=fixture(); node=spec['network']['nodes']['a']; node['kind']='GROUNDWATER'
        with self.assertRaises(ValueError): w.node_snapshot(node,t.initial_cell(node['thermal'],10,5))

    def test_ice_is_immobile_and_conductance_actually_changes(self):
        spec=fixture(); spec['initial']=w.initial_state(spec['network'],{key:t.initial_cell(node['thermal'],10 if key=='a' else 0,5) for key,node in spec['network']['nodes'].items()})
        frozen=self.run_case(spec)
        self.assertEqual(frozen['events'][0]['gross_links']['ab']['left_to_right_kg'],'0')
        self.assertGreater(F(self.run_case()['events'][0]['gross_links']['ab']['left_to_right_kg']),0)

    def test_boundary_thaw_releases_liquid_and_books_heat(self):
        spec=fixture(); spec['initial']=w.initial_state(spec['network'],{key:t.initial_cell(node['thermal'],10 if key=='a' else 0,5) for key,node in spec['network']['nodes'].items()})
        for row in spec['events'][0]['heat_boundaries'].values(): row.update(temperature_k=30,conductance_w_k=1000)
        result=self.run_case(spec); self.assertEqual(result['status'],'MODELLED')
        self.assertGreater(F(result['events'][0]['gross_links']['ab']['left_to_right_kg']),0)
        self.assertGreater(F(result['events'][0]['nodes']['a']['ledger']['boundary_heat_j']),0)

    def draw(self,key,volume,node='a',kind='ALLOCATION',latent=0):
        return {'allocation_id':key,'node_id':node,'sink_id':'human','volume_m3':volume,'kind':kind,'latent_heat_j_kg':latent,'evidence':'Explicit priority request'}

    def test_liquid_withdrawal_shortage_not_negative_storage(self):
        spec=fixture(); spec['events'][0]['withdrawals']=[self.draw('d',100)]
        result=self.run_case(spec); delivery=result['events'][0]['deliveries'][0]
        self.assertGreater(F(delivery['unmet_volume_m3']),0); self.assertGreaterEqual(F(result['final_state']['nodes']['a']['water_mass_kg']),0)

    def test_priority_order_and_once_only_delivery(self):
        spec=fixture(); spec['network']['links']=[]; spec['initial']=w.initial_state(spec['network'],spec['initial']['nodes']); spec['controls']['max_dt_seconds']=1
        spec['events'][0]['withdrawals']=[self.draw('first',8),self.draw('second',8)]
        rows=self.run_case(spec)['events'][0]['deliveries']; self.assertEqual([F(x['delivered_volume_m3']) for x in rows],[8,2])
        self.assertEqual(rows[0]['available_after_seconds'],'1'); self.assertEqual(len(rows[0]['source_input_sha256']),64)

    def test_evaporation_accounts_vaporisation_energy(self):
        spec=fixture(); spec['events'][0]['withdrawals']=[self.draw('evap','1/10',kind='EVAPORATION',latent=10)]
        row=self.run_case(spec)['events'][0]; self.assertEqual(F(row['deliveries'][0]['latent_energy_j']),1); self.assertEqual(row['energy_residual_j'],'0')

    def test_evaporation_cannot_reuse_energy_free_allocation(self):
        spec=fixture(); spec['events'][0]['withdrawals']=[self.draw('evap',1,kind='EVAPORATION',latent=0)]
        with self.assertRaises(ValueError): self.run_case(spec)

    def test_spill_debits_finite_storage(self):
        spec=fixture(); spec['network']['links']=[]; spec['network']['nodes']['a']['capacity_m3']=10; spec['initial']=w.initial_state(spec['network'],spec['initial']['nodes'])
        spec['events'][0]['inflows']=[{'allocation_id':'input','node_id':'a','volume_m3':5,'temperature_k':20,'evidence':'Test actual volume'}]
        result=self.run_case(spec); spills=result['events'][0]['deliveries']
        self.assertEqual(spills[0]['kind'],'SPILL'); self.assertEqual(F(spills[0]['delivered_volume_m3']),5); self.assertEqual(F(result['final_state']['nodes']['a']['water_mass_kg']),10)

    def test_ice_expansion_outside_geometry_not_clipped(self):
        spec=fixture(); spec['network']['nodes']['a']['ice_density_kg_m3']='1/2'; spec['network']['nodes']['b']['ice_density_kg_m3']='1/2'; spec['network']['nodes']['a']['capacity_m3']=10
        spec['initial']=w.initial_state(spec['network'],spec['initial']['nodes']); spec['events'][0]['heat_boundaries']['a'].update(temperature_k=1,conductance_w_k=1000000)
        result=self.run_case(spec); self.assertIsNone(result['final_state']); self.assertIn('ice volume',result['events'][0]['reason'])

    def test_unknown_causal_prefix_not_zero(self):
        spec=fixture(); spec['events']=[deepcopy(spec['events'][0]) for _ in range(3)]
        for i,row in enumerate(spec['events']): row['event_id']=str(i)
        spec['events'][1]['heat_boundaries']['a']['temperature_k']=None
        result=self.run_case(spec); self.assertEqual([x['status'] for x in result['events']],['MODELLED','UNKNOWN','NOT_ADVANCED_PRIOR_GAP']); self.assertEqual(result['completed_events'],1); self.assertIsNone(result['final_state'])

    def test_unknown_network_never_defaults(self):
        spec=fixture(); spec['network']['nodes']['a']['thermal']['latent_heat_j_kg']=None
        result=self.run_case(spec); self.assertEqual(result['status'],'UNKNOWN'); self.assertIsNone(result['final_state'])

    def test_unknown_thermal_provenance_still_requires_known_status(self):
        spec=fixture(); spec['network']['nodes']['a']['thermal'].update(latent_heat_j_kg=None,source_status='CLAIMED CANON')
        with self.assertRaises(ValueError): self.run_case(spec)

    def test_unknown_thermal_provenance_still_requires_evidence(self):
        spec=fixture(); spec['network']['nodes']['a']['thermal'].update(latent_heat_j_kg=None,evidence='')
        with self.assertRaises(ValueError): self.run_case(spec)

    def test_work_budget_failure_no_partial_event_commit(self):
        spec=fixture(); spec['controls']['max_substeps']=1
        result=self.run_case(spec); self.assertEqual(result['completed_events'],0); self.assertIsNone(result['final_state']); self.assertEqual(result['checkpoint']['state']['continuing_state'],spec['initial'])

    def test_exact_rational_event_clock(self):
        spec=fixture(); spec['events'][0]['duration_seconds']='1/3'
        row=self.run_case(spec)['events'][0]; self.assertEqual(sum(F(x['dt_seconds_exact']) for x in row['accepted_steps']),F(1,3)); self.assertEqual(F(row['end_seconds']),F(1,3))

    def test_actual_json_checkpoint_restart(self):
        spec=fixture(); two=deepcopy(spec['events'][0]); two['event_id']='two'; spec['events'].append(two)
        full=self.run_case(spec); stopped=self.run_case(spec,stop_after=1)
        with tempfile.TemporaryDirectory() as path:
            p=Path(path)/'checkpoint.json'; p.write_text(json.dumps(stopped['checkpoint']),encoding='utf-8'); saved=json.loads(p.read_text(encoding='utf-8'))
        resumed=self.run_case(spec,resume=saved); self.assertEqual(full,resumed)

    def test_rehashed_forged_checkpoint_rejected(self):
        spec=fixture(); stopped=self.run_case(spec,stop_after=1); cp=deepcopy(stopped['checkpoint']); cp['state']['continuing_state']['nodes']['a']['water_mass_kg']='1'; cp['state_sha256']=t.digest(cp['state'])
        with self.assertRaises(ValueError): self.run_case(spec,resume=cp)

    def test_changed_source_rejects_checkpoint(self):
        cp=self.run_case(stop_after=0)['checkpoint']
        with self.assertRaises(ValueError): self.run_case(source='b'*64,resume=cp)

    def test_changed_input_rejects_checkpoint(self):
        spec=fixture(); cp=self.run_case(spec,stop_after=0)['checkpoint']; spec['events'][0]['duration_seconds']=2
        with self.assertRaises(ValueError): self.run_case(spec,resume=cp)

    def test_duplicate_events_and_allocations_rejected(self):
        spec=fixture(); spec['events']*=2
        with self.assertRaises(ValueError): self.run_case(spec)
        spec=fixture(); spec['events'][0]['withdrawals']=[self.draw('same',1),self.draw('same',1)]
        with self.assertRaises(ValueError): self.run_case(spec)

    def test_consumed_initial_event_cannot_replay(self):
        spec=fixture(); spec['initial']['consumed_event_ids']=['one']
        with self.assertRaises(ValueError): self.run_case(spec)

    def test_mismatched_fluid_energy_reference_rejected(self):
        spec=fixture(); spec['network']['nodes']['a']['thermal']['latent_heat_j_kg']=101
        with self.assertRaises(ValueError): self.run_case(spec)

    def test_unknown_geometry_key_rejected(self):
        spec=fixture(); spec['network']['nodes']['a']['invented']=1
        with self.assertRaises(ValueError): self.run_case(spec)

    def test_booleans_negative_and_nonfinite_controls_rejected(self):
        for key,value in (('max_dt_seconds',True),('stability_fraction',1),('max_substeps',False),('energy_atol_j',float('nan'))):
            spec=fixture(); spec['controls'][key]=value
            with self.subTest(key=key),self.assertRaises(ValueError): self.run_case(spec)

    def test_internal_sink_cannot_duplicate_stock(self):
        spec=fixture(); spec['events'][0]['withdrawals']=[self.draw('bad',1)]; spec['events'][0]['withdrawals'][0]['sink_id']='b'
        with self.assertRaises(ValueError): self.run_case(spec)

    def test_full_twelve_window_reference_actual_freeze_and_ledgers(self):
        spec=w.reference_spec([{'event_id':str(i),'duration_seconds':2592000,'inflows_m3':{'lower':1,'upper':2}} for i in range(12)],{'lower':0,'upper':0})
        result=self.run_case({k:spec[k] for k in ('network','initial','events','controls')})
        self.assertEqual(result['status'],'MODELLED'); self.assertEqual(result['completed_events'],12)
        self.assertTrue(any(F(row['nodes']['lake']['end']['ice_water_kg'])>0 for row in result['events']))
        self.assertTrue(all(row['energy_residual_j']=='0' and row['water_residual_kg']=='0' for row in result['events']))
        WaterTests.actual_reference=result

    def test_source_cell_set_must_match_reference_inputs(self):
        with self.assertRaises(ValueError): w.reference_spec([{'event_id':'x','duration_seconds':1,'inflows_m3':{'wrong':1}}],{'right':1})

    def test_threshold_duration_uses_resolved_trajectory_not_month_end(self):
        spec=fixture(); spec['network']['links']=[]; spec['initial']=w.initial_state(spec['network'],spec['initial']['nodes'])
        spec['events'][0]['withdrawals']=[self.draw('decline',8)]; result=self.run_case(spec)
        diagnostic=w.duration_above_stage(result,'a',6)
        self.assertEqual(F(diagnostic['duration_above_seconds']),F(1,2)); self.assertFalse(diagnostic['observed_hydroperiod'])

    def test_missing_suffix_cannot_supply_full_hydroperiod(self):
        spec=fixture(); spec['events'][0]['source_status']='UNKNOWN'; result=self.run_case(spec)
        self.assertEqual(w.duration_above_stage(result,'a',1)['status'],'UNKNOWN_FULL_INTERVAL')

    def test_unknown_prefix_cannot_invent_threshold_support(self):
        spec=fixture(); spec['events'][0]['source_status']='UNKNOWN'; result=self.run_case(spec)
        with self.assertRaises(ValueError): w.duration_above_stage(result,'invented',1)

    def test_partial_ice_nonlinear_routing_against_independent_integral(self):
        # Donor fixed ice I=5; mobile x=m-I. dx/dt=-2G*x*x/(x+I).
        # Integrated: log(x)-I/x = log(5)-1-2G*t. Independent bisection.
        target=math.log(5)-1-.2; lo,hi=1.e-9,5.
        for _ in range(100):
            mid=(lo+hi)/2
            if math.log(mid)-5/mid>target: hi=mid
            else: lo=mid
        expected=5+(lo+hi)/2; errors=[]
        for n in (8,16,32):
            spec=fixture(); spec['controls']['max_dt_seconds']=str(F(1,n))
            spec['initial']=w.initial_state(spec['network'],{key:t.initial_cell(node['thermal'],10 if key=='a' else 0,10,liquid_fraction_at_freezing='1/2') for key,node in spec['network']['nodes'].items()})
            for row in spec['events'][0]['heat_boundaries'].values(): row['temperature_k']=10
            result=self.run_case(spec); self.assertEqual(result['status'],'MODELLED')
            errors.append(abs(float(F(result['final_state']['nodes']['a']['water_mass_kg']))-expected))
            self.assertEqual(result['events'][0]['water_residual_kg'],'0'); self.assertEqual(result['events'][0]['energy_residual_j'],'0')
        self.assertTrue(1.9<errors[0]/errors[1]<2.1); self.assertTrue(1.9<errors[1]/errors[2]<2.1)

    def test_coupled_freezing_case_temporal_refinement_retains_ledgers(self):
        values=[]
        for count in (32,64,128):
            spec=fixture(); spec['network']['links']=[]; spec['initial']=w.initial_state(spec['network'],spec['initial']['nodes']); spec['controls']['max_dt_seconds']=str(F(1,count))
            spec['events'][0]['heat_boundaries']['a'].update(temperature_k=5,conductance_w_k=100)
            result=self.run_case(spec); self.assertEqual(result['status'],'MODELLED')
            values.append(float(F(result['final_state']['nodes']['a']['energy_j'])))
            self.assertEqual(result['events'][0]['energy_residual_j'],'0')
        self.assertLess(abs(values[1]-values[2]),abs(values[0]-values[1]))


if __name__=='__main__': unittest.main()
