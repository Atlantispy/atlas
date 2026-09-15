import json
import math
import tempfile
import unittest
from copy import deepcopy
from fractions import Fraction as F
from pathlib import Path
from . import thermal as t


def cell(key='a'):
    return {'cell_id':key,'solid_heat_capacity_j_k':10,'liquid_heat_capacity_j_kg_k':2,
        'ice_heat_capacity_j_kg_k':1,'latent_heat_j_kg':100,'freezing_temperature_k':10,
        'evidence':'Fictional dimensioned analytical test, not natural constants.','source_status':'SYNTHETIC TEST'}


class ThermalTests(unittest.TestCase):
    def test_sensible_liquid_oracle(self):
        c=cell(); state=t.initial_cell(c,5,20)
        self.assertEqual(F(state['energy_j']),700); self.assertEqual(t.phase(c,**state)['temperature_k'],20)

    def test_sensible_frozen_oracle(self):
        c=cell(); state=t.initial_cell(c,5,5)
        self.assertEqual(F(state['energy_j']),-75); self.assertEqual(t.phase(c,**state)['ice_water_kg'],'5')

    def test_latent_plateau_is_not_temperature_partition(self):
        with self.assertRaises(ValueError): t.initial_cell(cell(),5,10)
        result=t.phase(cell(),5,125)
        self.assertEqual(result['temperature_k'],10); self.assertEqual(F(result['liquid_water_kg']),F(5,4))

    def test_explicit_fraction_initialises_plateau(self):
        self.assertEqual(t.initial_cell(cell(),5,10,liquid_fraction_at_freezing='1/4')['energy_j'],'125')

    def test_off_plateau_fraction_rejected(self):
        with self.assertRaises(ValueError): t.initial_cell(cell(),1,11,liquid_fraction_at_freezing=1)

    def test_negative_temperature_rejected(self):
        with self.assertRaises(ValueError): t.phase(cell(),1,-1000)

    def test_explicit_unknown_is_not_default(self):
        c=cell(); c['latent_heat_j_kg']=None
        with self.assertRaises(ValueError): t.phase(c,1,1)

    def test_boolean_nonfinite_and_large_guard(self):
        for value in (True,float('nan'),float('inf'),'1'+'0'*5000):
            with self.subTest(value=str(value)[:20]), self.assertRaises(ValueError): t.number(value,'test')

    def test_positive_transfer_underflow_rejected(self):
        with self.assertRaises(ValueError): t.represented('1/'+str(10**400),'tiny positive heat')

    def test_cell_schema_rejects_unknown_field(self):
        c=cell(); c['guessed']=0
        with self.assertRaises(ValueError): t.phase(c,1,0)

    def test_liquid_addition_books_advected_heat(self):
        c=cell(); before=t.initial_cell(c,2,20); after,energy=t.add_liquid(c,before,3,20)
        self.assertEqual(energy,360); self.assertEqual(F(after['energy_j'])-F(before['energy_j']),energy)
        self.assertEqual(t.phase(c,**after)['temperature_k'],20)

    def test_cold_support_can_freeze_incoming_liquid(self):
        c=cell(); before=t.initial_cell(c,0,1); after,_=t.add_liquid(c,before,1,10)
        self.assertEqual(F(t.phase(c,**after)['ice_water_kg']),F(9,10))

    def test_supercooled_inflow_not_silently_admitted(self):
        with self.assertRaises(ValueError): t.add_liquid(cell(),t.initial_cell(cell(),0,10,liquid_fraction_at_freezing=0),1,9)

    def test_liquid_removal_preserves_temperature(self):
        c=cell(); before=t.initial_cell(c,5,20); after,energy=t.remove_liquid(c,before,2)
        self.assertEqual(energy,240); self.assertEqual(t.phase(c,**after)['temperature_k'],20)

    def test_ice_cannot_be_withdrawn_as_liquid(self):
        with self.assertRaises(ValueError): t.remove_liquid(cell(),t.initial_cell(cell(),5,5),1)

    def test_zero_transfer_on_frozen_store_is_noop_not_supercooled_flow(self):
        c=cell(); state=t.initial_cell(c,1,5)
        self.assertEqual(t.remove_liquid(c,state,0),(state,F()))
        self.assertEqual(t.add_liquid(c,state,0,5),(state,F()))
        with self.assertRaises(ValueError): t.add_liquid(c,state,1,5)

    def test_forged_negative_initial_stock_cannot_be_repaired_by_inflow(self):
        with self.assertRaises(ValueError): t.add_liquid(cell(),{'water_mass_kg':'-1','energy_j':'100'},2,20)

    def test_pair_implicit_sensible_equation_independent(self):
        a,b=cell('a'),cell('b'); sa=t.initial_cell(a,0,20); sb=t.initial_cell(b,0,10,liquid_fraction_at_freezing=0)
        aa,bb,receipt=t.exchange_heat(a,sa,b,sb,2,1,energy_atol_j='1/1000000')
        # C=10 each, backward-Euler Q=2*(20-10)/(1+2/10+2/10).
        self.assertAlmostEqual(float(F(receipt['energy_left_to_right_j'])),100/7)
        self.assertEqual(F(aa['energy_j'])+F(bb['energy_j']),F(sa['energy_j'])+F(sb['energy_j']))

    def test_pair_heat_crosses_phase_conservatively(self):
        a,b=cell('a'),cell('b'); sa=t.initial_cell(a,2,20); sb=t.initial_cell(b,2,5)
        aa,bb,_=t.exchange_heat(a,sa,b,sb,100,10,energy_atol_j='1/1000')
        self.assertEqual(F(aa['energy_j'])+F(bb['energy_j']),F(sa['energy_j'])+F(sb['energy_j']))
        self.assertGreater(F(t.phase(b,**bb)['liquid_water_kg']),0)

    def test_boundary_heat_exact_ledger(self):
        c=cell(); before=t.initial_cell(c,1,5); after,receipt=t.boundary_heat(c,before,20,10,10,energy_atol_j='1/1000')
        self.assertEqual(F(after['energy_j'])-F(before['energy_j']),F(receipt['energy_into_cell_j']))

    def test_zero_conductance_no_thermal_change(self):
        c=cell(); before=t.initial_cell(c,1,5); after,_=t.boundary_heat(c,before,20,0,10,energy_atol_j=1)
        self.assertEqual(after,before)

    def test_advective_representation_allowance_enforced(self):
        c=cell(); before={'water_mass_kg':'1','energy_j':'301/3'}
        with self.assertRaises(ValueError): t.remove_liquid(c,before,'1/3',energy_atol_j='1/1000000000000000000000000000000')

    def fixture(self):
        cells={'a':cell()}; state=t.initial_column(cells,{'a':t.initial_cell(cell(),0,20)},source_binding_sha256='a'*64)
        return cells,state,[],{'a':{'temperature_k':10,'conductance_w_k':1,'evidence':'Explicit bath'}}

    def advance(self,args,**kw):
        return t.advance_column(*args,event_id=kw.get('event_id','one'),duration_seconds=kw.get('duration',1),
            max_dt_seconds=kw.get('dt',1),max_substeps=1000,energy_atol_j='1/10000')

    def test_column_exact_energy_and_water(self):
        result=self.advance(self.fixture()); self.assertEqual(result['energy_ledger_j']['residual'],'0'); self.assertFalse(result['water_mass_changed'])
        self.assertEqual(result['hydraulic_feedback'],'NOT_FROZEN_RICHARDS')

    def test_column_temporal_refinement_analytical(self):
        errors=[]
        for n in (8,16,32):
            result=self.advance(self.fixture(),duration=10,dt=F(10,n)); temp=result['accepted_steps'][-1]['end_layers']['a']['temperature_k']
            errors.append(abs(temp-(10+10*math.exp(-1))))
        self.assertTrue(1.8<errors[0]/errors[1]<2.1); self.assertTrue(1.8<errors[1]/errors[2]<2.1)

    def test_column_saved_file_continuation(self):
        args=self.fixture(); one=self.advance(args)
        with tempfile.TemporaryDirectory() as path:
            p=Path(path)/'state.json'; p.write_text(json.dumps(one['final_state']),encoding='utf-8'); saved=json.loads(p.read_text(encoding='utf-8'))
        resumed=self.advance((args[0],saved,args[2],args[3]),event_id='two')
        full=self.advance(args,duration=2)
        self.assertEqual(resumed['final_state']['cells'],full['final_state']['cells'])

    def test_column_duplicate_event_rejected(self):
        args=self.fixture(); result=self.advance(args)
        with self.assertRaises(ValueError): self.advance((args[0],result['final_state'],args[2],args[3]))

    def test_unknown_boundary_no_air_temperature_guess(self):
        args=self.fixture(); args[3]['a']['temperature_k']=None; result=self.advance(args)
        self.assertEqual(result['status'],'UNKNOWN'); self.assertIsNone(result['final_state'])

    def test_changed_thermal_law_rejects_state(self):
        args=self.fixture(); args[0]['a']['solid_heat_capacity_j_k']=11
        with self.assertRaises(ValueError): self.advance(args)


if __name__=='__main__': unittest.main()
