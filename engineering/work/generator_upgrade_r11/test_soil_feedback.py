import hashlib
import json
import tempfile
import unittest
from copy import deepcopy
from dataclasses import asdict
from fractions import Fraction as F
from pathlib import Path
from . import binding, soil_feedback as s, thermal as t

FIXTURE=Path(__file__).resolve().parents[2]/'outputs/generator-upgrade-r10/seasonal-reference-01/n-worker-reference/full-result.json'
FIXTURE_SHA='f191389d93c411f81e7003e5edf96551b53dc945e359dc705d83d00c64a0930e'
PHYSICAL_FIXTURE=FIXTURE.with_name('physical-parent-result.json')
PHYSICAL_SHA='19a0975d09d1571e68ed510421b085675753b64ddfba316c8e8e2d68662cb000'


def test_data_bindings(): return {str(FIXTURE):FIXTURE_SHA,str(PHYSICAL_FIXTURE):PHYSICAL_SHA}


class SoilFeedbackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bundle=binding.load(); cls.sw=cls.bundle.parent.parent.parent.parent.parent.solver
        cls.adapter=cls.bundle.parent.graph.load('work.generator_upgrade_r10.richards_numerics').Adapter(cls.sw)
        raw=FIXTURE.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=FIXTURE_SHA: raise ValueError('changed retained test fixture')
        parent=json.loads(raw); cls.unit=cls.bundle.parent.graph.load('work.generator_upgrade_r10.payloads').unpack(next(iter(parent['state']['results'].values())))
        cls.spec=s.thermal_reference_spec(cls.sw,cls.unit)
        cls.thermal_result=s.thermal_year(cls.spec,source_binding_sha256='a'*64,scenario_id='actual-held-thermal')
        raw=PHYSICAL_FIXTURE.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=PHYSICAL_SHA: raise ValueError('changed actual material test fixture')
        physical=json.loads(raw); cls.formed=physical['soil_result']['state']['members'][cls.unit['snow_id']][cls.unit['cell_id']]
        eco=cls.bundle.module('ecosystem'); es=eco.reference_spec(cls.bundle.organic,cls.bundle.fertility,cls.unit); es.pop('reference_join')
        cls.ecosystem=eco.run_year(cls.bundle.organic,cls.bundle.fertility,**es,source_binding_sha256=cls.bundle.source_sha256,
            scenario_id=cls.unit['snow_id']+'/'+cls.unit['hydraulic_hypothesis_id']+'/'+cls.unit['cell_id'],evidence='Explicit test on actual formed support',source_status='SYNTHETIC TEST')

    def fixture(self):
        w=self.sw; layers=tuple(w.HydraulicLayer(k,1,.02,.25,2,2,.5,1e-6,'Explicit synthetic native law','SYNTHETIC TEST') for k in ('a','b'))
        column=w.Column('profile',layers,2,'Explicit profile','SYNTHETIC TEST'); state=w.initial_state(column,(-2,-2),elapsed_seconds=123)
        material={k:{'constituents':[{'constituent_id':k+'-mineral','kind':'MINERAL','old_mass_kg_m2':1500,'new_mass_kg_m2':1500,'grain_density_kg_m3':2000,'evidence':'Explicit dry mineral inventory'}],
            'new_porosity':.25,'hydraulic_law':{'theta_r':.02,'alpha_per_m':2,'n':2,'mualem_l':.5,'ksat_m_s':1e-6,'evidence':'Explicit joint hydraulic law','source_status':'SYNTHETIC TEST'},
            'evidence':'Explicit one-to-one material packing','source_status':'SYNTHETIC TEST'} for k in ('a','b')}
        return column,state,material

    def remap(self,fixture=None,**kw):
        col,state,material=self.fixture() if fixture is None else fixture
        return s.rebind_unfrozen(self.sw,col,state,material,ice_water_m_by_layer=kw.pop('ice',{'a':0,'b':0}),
            water_atol_m=kw.pop('water_atol','1/10000000000'),geometry_atol_m='1/10000000000',source_binding_sha256='a'*64,evidence='Explicit unfrozen instantaneous synthetic isothermal rebind',**kw)

    def test_native_identity_remap_conserves_extensive_stock(self):
        result=self.remap(); self.assertEqual(result['status'],'MODELLED_ONE_TO_ONE_WATER_REBIND')
        self.assertLess(abs(F(result['total_water_representation_residual_m'])),F(1,10**10))
        self.assertEqual(result['external_water_input_m'],'0'); self.assertEqual(result['external_water_output_m'],'0')

    def test_expansion_uses_new_inverse_not_old_head(self):
        fixture=self.fixture(); fixture[2]['a']['new_porosity']=.5
        result=self.remap(fixture); row=result['layer_ledgers'][0]
        self.assertEqual(F(row['new_thickness_m_exact']),F(3,2)); self.assertNotEqual(row['new_head_m'],-2)
        self.assertLess(abs(F(row['new_water_m'])-F(row['old_water_m'])),F(1,10**10))

    def test_contraction_is_conservative_when_still_unsaturated(self):
        fixture=self.fixture(); fixture[2]['a']['new_porosity']=.125
        result=self.remap(fixture); self.assertEqual(F(result['layer_ledgers'][0]['new_thickness_m_exact']),F(6,7))

    def test_no_phantom_time_or_rainfall_advance(self):
        result=self.remap(); self.assertEqual(result['elapsed_seconds_before'],123); self.assertEqual(result['elapsed_seconds_after'],123); self.assertEqual(result['forcing_events_consumed'],[])

    def test_changed_layer_inventory_rejected(self):
        fixture=self.fixture(); fixture[2]['new']=fixture[2].pop('a')
        with self.assertRaises(ValueError): self.remap(fixture)

    def test_reordered_layer_material_rejected(self):
        col,state,material=self.fixture()
        with self.assertRaises(ValueError): self.remap((col,state,{k:material[k] for k in ('b','a')}))

    def test_old_material_volume_must_close(self):
        fixture=self.fixture(); fixture[2]['a']['constituents'][0]['old_mass_kg_m2']=1400; fixture[2]['a']['constituents'][0]['new_mass_kg_m2']=1400
        with self.assertRaises(ValueError): self.remap(fixture)

    def test_mineral_mass_creation_forbidden(self):
        fixture=self.fixture(); fixture[2]['a']['constituents'][0]['new_mass_kg_m2']=1501
        with self.assertRaises(ValueError): self.remap(fixture)

    def test_organic_change_needs_actual_producer(self):
        fixture=self.fixture(); fixture[2]['a']['constituents'][0].update(kind='ORGANIC',new_mass_kg_m2=1501)
        with self.assertRaises(ValueError): self.remap(fixture)

    def test_frozen_water_rejected(self):
        with self.assertRaises(ValueError): self.remap(ice={'a':'1/1000','b':0})

    def test_unknown_ice_is_not_unfrozen(self):
        with self.assertRaises(ValueError): self.remap(ice={'a':None,'b':0})

    def test_saturated_target_has_no_inferred_pressure(self):
        col,state,material=self.fixture(); state=self.sw.initial_state(col,(0,0),elapsed_seconds=123)
        material['a']['hydraulic_law']['alpha_per_m']=3
        with self.assertRaisesRegex(ValueError,'saturated'): self.remap((col,state,material))

    def test_unchanged_saturated_support_keeps_only_actual_initial_guess(self):
        col,state,material=self.fixture(); state=self.sw.initial_state(col,(1,2),elapsed_seconds=123)
        for layer in col.layers: material[layer.layer_id]['hydraulic_law']['evidence']=layer.evidence
        result=self.remap((col,state,material)); self.assertEqual(result['new_state']['head_m'],[1,2])
        self.assertTrue(all('NUMERICAL_INITIAL' in x['head_status'] for x in result['layer_ledgers']))
        self.assertEqual(result['current_pressure_status'],'UNVERIFIED_UNTIL_NEXT_ACTUAL_WATER_STEP')

    def test_overflow_not_clipped_or_moved_to_surface(self):
        fixture=self.fixture(); fixture[2]['a']['new_porosity']=.025
        with self.assertRaisesRegex(ValueError,'overflow'): self.remap(fixture)

    def test_residual_target_not_artificially_wetted(self):
        fixture=self.fixture(); fixture[2]['a']['new_porosity']=.99; fixture[2]['a']['hydraulic_law']['theta_r']=.1
        with self.assertRaisesRegex(ValueError,'residual'): self.remap(fixture)

    def test_unknown_hydraulic_law_rejected(self):
        fixture=self.fixture(); fixture[2]['a']['hydraulic_law']['ksat_m_s']=None
        with self.assertRaises(ValueError): self.remap(fixture)

    def test_state_geometry_digest_rejects_mismatch(self):
        col,state,material=self.fixture(); bad=self.sw.State(state.head_m,state.elapsed_seconds,'0'*64)
        with self.assertRaises(ValueError): self.remap((col,bad,material))

    def test_actual_native_next_step_on_rebound_geometry(self):
        fixture=self.fixture(); fixture[2]['a']['new_porosity']=.5; rebound=self.remap(fixture)
        column=s.native_column(self.sw,rebound['new_column']); state=s.native_state(self.sw,column,rebound['new_state'])
        forcing=self.sw.Forcing(1,0,0,None,'New physical interval, no repeated rain','SYNTHETIC TEST')
        boundary=self.sw.Boundary('no_flow',None,'Closed basal support','SYNTHETIC TEST')
        controls=self.sw.Controls(.1,1e-8,1,1e-5,1e-3,1e-7,1e-3,1e-9,1e-7,-1e8,1e4,10000,100,'SDIRK2')
        result=self.adapter.advance(column,state,forcing,boundary,controls,water_density_kg_m3=1000,gravity_m_s2=9.8)
        self.assertEqual(result['status'],'MODELLED'); self.assertEqual(result['state'].column_sha256,self.sw.column_digest(column)); self.assertEqual(result['state'].elapsed_seconds,124)
        SoilFeedbackTests.actual_rebound_next_step={'rebind':rebound,'water_step':t.plain({key:(asdict(value) if key=='state' else value) for key,value in result.items()})}

    def test_saved_rebound_state_next_step_input_parity(self):
        result=self.remap()
        with tempfile.TemporaryDirectory() as path:
            file=Path(path)/'rebind.json'; file.write_text(json.dumps(result),encoding='utf-8'); saved=json.loads(file.read_text(encoding='utf-8'))
        col=s.native_column(self.sw,saved['new_column']); state=s.native_state(self.sw,col,saved['new_state'])
        self.assertEqual(self.sw.column_digest(col),result['new_column_sha256']); self.assertEqual(list(state.head_m),result['new_state']['head_m'])

    def test_actual_all_layer_thermal_support_and_mass(self):
        result=self.thermal_result; self.assertEqual(result['status'],'MODELLED_HOLD_INITIAL_WATER_DIAGNOSTIC')
        self.assertEqual(set(result['final_state']['cells']),{x['layer_id'] for x in self.unit['hydrology']['column']['layers']})
        for key,state in result['final_state']['cells'].items(): self.assertEqual(state['water_mass_kg'],self.spec['initial_cells'][key]['water_mass_kg'])
        self.assertEqual(result['water_support'],'HOLD_INITIAL_WATER_DIAGNOSTIC'); self.assertFalse(result['frozen_richards_implemented'])

    def test_actual_thermal_exact_energy_every_event(self):
        self.assertTrue(all(row['thermal_result']['energy_ledger_j']['residual']=='0' for row in self.thermal_result['events']))

    def test_actual_thermal_exact_calendar(self):
        self.assertEqual([r['event_id'] for r in self.thermal_result['events']],[r['event_id'] for r in self.unit['hydrology']['events']])
        self.assertEqual(sum((F(row['duration_seconds']) for row in self.thermal_result['events']),F()),sum((F(row['duration_seconds']) for row in self.unit['hydrology']['events']),F()))

    def test_actual_thermal_saved_checkpoint_replay(self):
        stopped=s.thermal_year(self.spec,source_binding_sha256='a'*64,scenario_id='actual-held-thermal',stop_after=2)
        with tempfile.TemporaryDirectory() as path:
            file=Path(path)/'thermal.json'; file.write_text(json.dumps(stopped['checkpoint']),encoding='utf-8'); cp=json.loads(file.read_text(encoding='utf-8'))
        resumed=s.thermal_year(self.spec,source_binding_sha256='a'*64,scenario_id='actual-held-thermal',resume=cp)
        self.assertEqual(resumed,self.thermal_result)

    def test_rehashed_thermal_checkpoint_rejected(self):
        stopped=s.thermal_year(self.spec,source_binding_sha256='a'*64,scenario_id='actual-held-thermal',stop_after=1); cp=deepcopy(stopped['checkpoint'])
        key=next(iter(cp['state']['continuing_state']['cells'])); cp['state']['continuing_state']['cells'][key]['energy_j']='0'; cp['state_sha256']=t.digest(cp['state'])
        with self.assertRaises(ValueError): s.thermal_year(self.spec,source_binding_sha256='a'*64,scenario_id='actual-held-thermal',resume=cp)

    def test_unknown_thermal_boundary_preserves_prefix_only(self):
        spec=deepcopy(self.spec); key=next(iter(spec['cells'])); spec['events'][1]['boundaries'][key]['temperature_k']=None
        result=s.thermal_year(spec,source_binding_sha256='a'*64,scenario_id='unknown')
        self.assertEqual(result['status'],'UNKNOWN'); self.assertEqual(result['completed_events'],1); self.assertIsNone(result['final_state'])

    def test_changed_calendar_rejected(self):
        spec=deepcopy(self.spec); spec['events'][1]['start_seconds_in_year']='0'
        with self.assertRaises(ValueError): s.thermal_year(spec,source_binding_sha256='a'*64,scenario_id='test')

    def actual_material(self,unit=None,formed=None,eco=None):
        return s.material_spec_from_formed(self.sw,self.unit if unit is None else unit,self.formed if formed is None else formed,
            self.ecosystem if eco is None else eco,organic_grain_density_kg_m3=1500,evidence='Explicit retained R7 organic grain density1500 kg/m3, actual selected ecosystem change',source_binding_sha256=self.bundle.source_sha256)

    def test_actual_formed_organic_geometry_and_water_rebind(self):
        material=self.actual_material(); column=s.native_column(self.sw,self.unit['hydrology']['column']); state=s.native_state(self.sw,column,self.unit['hydrology']['final_state'])
        result=s.rebind_unfrozen(self.sw,column,state,material,ice_water_m_by_layer={x.layer_id:0 for x in column.layers},water_atol_m=1e-9,geometry_atol_m=1e-9,
            source_binding_sha256=self.bundle.source_sha256,evidence='Explicit instantaneous isothermal unfrozen selected-cohort structure update after actual representative year',ecosystem_result=self.ecosystem,ecosystem_scenario_id=self.ecosystem['scenario_id'])
        changed=[row for row in result['layer_ledgers'] if F(row['new_thickness_m_exact'])!=F(row['old_thickness_m']) and abs(F(row['new_thickness_m_exact'])-F(row['old_thickness_m']))>F(1,10**12)]
        self.assertEqual([row['layer_id'] for row in changed],[self.unit['cell_id']+'-mineral'])
        self.assertLess(abs(F(result['total_water_representation_residual_m'])),F(1,10**9))
        SoilFeedbackTests.actual_material_rebind=result

    def test_forged_formed_mass_hash_rejected(self):
        formed=deepcopy(self.formed); formed['geometry'][0]['organic_dry_mass_kg_m2']='100'
        with self.assertRaises(ValueError): self.actual_material(formed=formed)

    def test_forged_organic_final_stock_rejected(self):
        eco=deepcopy(self.ecosystem); eco['final_state']['organic_state']['fast_carbon_kg_m2']='999'
        with self.assertRaises(ValueError): self.actual_material(eco=eco)

    def test_joint_forged_organic_stock_and_change_ledger_rejected(self):
        eco=deepcopy(self.ecosystem); pair=eco['final_state']['organic_state']['fast_carbon_kg_m2']; extra=F(1,100)
        value=F(*pair)+extra; eco['final_state']['organic_state']['fast_carbon_kg_m2']=[value.numerator,value.denominator]
        cf=F(eco['inputs']['organic_law']['carbon_fraction_dry_matter']); row=eco['events'][-1]['soil_material_change']
        row['organic_dry_mass_change_kg_m2']=str(F(row['organic_dry_mass_change_kg_m2'])+extra/cf)
        with self.assertRaises(ValueError): self.actual_material(eco=eco)

    def test_changed_ecosystem_source_and_scenario_rejected(self):
        for key,value in (('source_binding_sha256','b'*64),('scenario_id','unrelated')):
            eco=deepcopy(self.ecosystem); eco[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError): self.actual_material(eco=eco)
        for key,value in (('source_binding_sha256','b'*64),('scenario_id','unrelated'),('geometry_sha256','b'*64)):
            eco=deepcopy(self.ecosystem); eco['inputs'][key]=value; eco['inputs_sha256']=t.digest(eco['inputs'])
            with self.subTest(inner_key=key),self.assertRaises(ValueError): self.actual_material(eco=eco)

    def test_actual_organic_change_cannot_be_omitted(self):
        material=self.actual_material()
        for row in material.values():
            for constituent in row['constituents']: constituent['new_mass_kg_m2']=constituent['old_mass_kg_m2']
        column=s.native_column(self.sw,self.unit['hydrology']['column']); state=s.native_state(self.sw,column,self.unit['hydrology']['final_state'])
        with self.assertRaises(ValueError): s.rebind_unfrozen(self.sw,column,state,material,ice_water_m_by_layer={x.layer_id:0 for x in column.layers},water_atol_m=1e-9,geometry_atol_m=1e-9,
            source_binding_sha256=self.bundle.source_sha256,evidence='Explicit test',ecosystem_result=self.ecosystem,ecosystem_scenario_id=self.ecosystem['scenario_id'])

    def test_actual_formed_remap_and_new_solver_produced_pressure(self):
        result=s.reference_continuation(self.adapter,self.unit,self.formed,self.ecosystem,organic_grain_density_kg_m3=1500,
            source_binding_sha256=self.bundle.source_sha256,evidence='Actual-layer explicit short unfrozen numerical continuation')
        self.assertEqual(result['status'],'MODELLED_STRUCTURE_AND_WATER_CONTINUATION')
        self.assertEqual(result['pressure_status'],'ACTUAL_NEW_GEOMETRY_SOLVER_PRODUCED')
        self.assertEqual(F(result['actual_water_step']['state']['elapsed_seconds']),F(self.unit['hydrology']['final_state']['elapsed_seconds'])+1)
        self.assertTrue(any('SATURATED' in row['head_status'] for row in result['rebind']['layer_ledgers']))
        SoilFeedbackTests.actual_material_continuation=result


if __name__=='__main__': unittest.main()
