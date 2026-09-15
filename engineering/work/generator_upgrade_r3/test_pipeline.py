import copy
from dataclasses import replace
from fractions import Fraction as F
import unittest
from unittest.mock import patch
from . import pipeline as p, storage, soil_inputs as si
from .reference import recipe


class ConnectedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.recipe=recipe();cls.result=p.run(cls.recipe);cls.state=cls.result['state']

    def test_actual_complete_feedback(self):
        s=self.state
        self.assertEqual(s['completed_events'],2)
        self.assertEqual(F(s['elapsed']),240)
        self.assertGreater(len(s['history']),1)
        for k,initial in self.recipe['cells'].items():
            before=si.HydraulicProfile.from_dict(initial['profile']);after=si.HydraulicProfile.from_dict(s['profiles'][k])
            self.assertNotEqual(before.column.surface_m,after.column.surface_m)
            self.assertGreater(len(after.bindings),len(before.bindings))
            self.assertTrue(any(r['wet_deposition'] for r in s['history']))

    def test_whole_water_budget_independent(self):
        r=self.result;h=self.state['history']
        expected=F(r['initial_total_water_m3'])+sum((F(x['liquid_input_m3'])+F(x['bottom_in_m3'])-F(x['bottom_out_m3'])-
            F(x['actual_et_m3'])-F(x['runoff_export_m3'])-F(x['sediment_porewater_export_m3']) for x in h),F())
        self.assertEqual(expected-F(r['final_total_water_m3']),F(r['water_residual_m3']))
        self.assertLess(abs(float(F(r['water_residual_m3']))),1e-7)

    def test_material_budget_independent(self):
        initial=[si.HydraulicProfile.from_dict(r['profile']) for r in self.recipe['cells'].values()]
        final=[si.HydraulicProfile.from_dict(r) for r in self.state['profiles'].values()]
        for material in ('mineral','substrate'):
            start=sum((l.mass_kg for pr in initial for l in pr.column.layers if l.material_id==material),F())
            end=sum((l.mass_kg for pr in final for l in pr.column.layers if l.material_id==material),F())
            export=sum((F(b['exported_mass_kg']) for h in self.state['history'] for b in h['terrain']['material_balances'] if b['material_id']==material),F())
            self.assertEqual(start,end+export)

    def test_sediment_water_export_separate(self):
        h=self.state['history']
        self.assertGreater(sum(F(r['sediment_porewater_export_m3']) for r in h),0)
        self.assertGreater(sum(F(r['runoff_export_m3']) for r in h),0)

    def test_surface_stock_not_exported_twice(self):
        self.assertGreater(sum(F(v) for v in self.state['surface'].values()),0)
        self.assertTrue(all(F(r['runoff_export_m3'])<F(r['initial_water_m3']) for r in self.state['history']))

    def test_exact_actual_water_geometry_and_pressure(self):
        model=p.parse(self.recipe)
        for k,raw in self.state['profiles'].items():
            profile=si.HydraulicProfile.from_dict(raw);column,_=p.water_column(model,k,profile)
            water=self.state['water'][k]
            self.assertEqual(water['state']['column_sha256'],p.sw.column_digest(column))
            self.assertEqual(water['state']['elapsed_seconds'],240)
            for layer,w in zip(column.layers,water['layers']):
                theta,_=p.sw.hydraulic_properties(layer,w['head_m'])
                self.assertEqual(theta,w['theta_m3_m3'])
                self.assertEqual(w['signed_pore_pressure_pa'],1000*9.81*w['head_m'])

    def test_actual_pressure_used_in_stability(self):
        for k,product in self.result['soil_products'].items():
            fs=product['stability'];self.assertEqual(fs['mask'],'VALID')
            w=next(r for r in self.state['water'][k]['layers'] if r['layer_id']==k+'-mineral')
            self.assertEqual(fs['inputs']['pore_pressure_pa']['lower'],w['signed_pore_pressure_pa'])
            self.assertEqual(fs['inputs']['vertical_failure_depth_m']['lower'],w['centre_depth_m'])

    def test_gross_reversal_remains_separate(self):
        h=self.state['history']
        self.assertGreater(sum(F(r['bottom_in_m3']) for r in h),0)
        self.assertGreater(sum(F(r['bottom_out_m3']) for r in h),0)
        for r in h:
            for flux in r['root_flux_m3'].values():self.assertTrue(all(v>=0 for v in flux.values()))

    def test_no_pedogenic_or_canon_promotion(self):
        self.assertFalse(self.result['canon_changed']);self.assertFalse(self.result['production_installed'])
        self.assertTrue(all(r['pedogenic_horizons']=='NOT_INFERRED' for r in self.result['soil_products'].values()))

    def test_each_interval_coupled_gate(self):
        gates=[r['coupled_acceptance'] for r in self.state['history'] if 'coupled_acceptance' in r]
        self.assertEqual(len(gates),2)
        self.assertTrue(all(c['error_ratio']<=1 for g in gates for c in g['accepted_intervals']))
        self.assertTrue(all(any('flux/' in k for k in c['components']) for g in gates for c in g['accepted_intervals']))

    def test_restart_exact(self):
        first=p.run(self.recipe,stop_after=1)
        cp=storage.checkpoint(first['state'],recipe_sha256=storage.sha(storage.encoded(self.recipe)),source_sha256='a'*64)
        self.assertEqual(p.run(self.recipe,resume=cp,source_sha256='a'*64),self.result)

    def test_completed_restart_no_double_deposition(self):
        cp=storage.checkpoint(self.state,recipe_sha256=storage.sha(storage.encoded(self.recipe)),source_sha256='a'*64)
        self.assertEqual(p.run(self.recipe,resume=cp,source_sha256='a'*64),self.result)

    def test_forged_checksum_not_physical_authority(self):
        bad=copy.deepcopy(self.state);bad['surface']['upper']='100'
        cp=storage.checkpoint(bad,recipe_sha256=storage.sha(storage.encoded(self.recipe)),source_sha256='a'*64)
        with self.assertRaisesRegex(ValueError,'reproducible physical'):p.run(self.recipe,resume=cp,source_sha256='a'*64)

    def test_changed_forcing_restart_rejected(self):
        cp=storage.checkpoint(self.state,recipe_sha256=storage.sha(storage.encoded(self.recipe)),source_sha256='a'*64)
        r=recipe();r['events'][0]['cells']['upper']['liquid_input_m_s']*=2
        with self.assertRaisesRegex(ValueError,'different recipe'):p.run(r,resume=cp,source_sha256='a'*64)

    def test_changed_source_restart_rejected(self):
        cp=storage.checkpoint(self.state,recipe_sha256=storage.sha(storage.encoded(self.recipe)),source_sha256='a'*64)
        with self.assertRaisesRegex(ValueError,'different recipe'):p.run(self.recipe,resume=cp,source_sha256='b'*64)

    def test_no_implicit_model_year(self):
        r=recipe();del r['seconds_per_year']
        with self.assertRaises(ValueError):p.parse(r)

    def test_explicit_mechanical_roots_required(self):
        r=recipe();del r['cells']['upper']['stability_roots']
        with self.assertRaises(ValueError):p.parse(r)

    def test_rock_is_not_shallow_soil(self):
        r=recipe();r['cells']['upper']['stability_layer_id']='upper-substrate'
        result=p.run(r)
        self.assertEqual(result['soil_products']['upper']['stability']['mask'],'INAPPLICABLE')

    def test_pet_requires_uptake_before_morphology(self):
        r=recipe();r['events'][0]['cells']['upper']['potential_et_m_s']=1e-8
        with patch.object(p.tt,'terrain_trial',side_effect=AssertionError('must validate first')):
            with self.assertRaisesRegex(ValueError,'ET requires'):p.run(r)

    def test_unknown_head_requires_input_before_morphology(self):
        r=recipe();r['events'][0]['cells']['upper']['boundary']['head_m']=None
        with patch.object(p.tt,'terrain_trial',side_effect=AssertionError('must validate first')):
            with self.assertRaisesRegex(ValueError,'lower boundary'):p.run(r)

    def test_absent_roots_cannot_supply_positive_uptake(self):
        r=recipe();f=r['events'][0]['cells']['upper'];f['potential_et_m_s']=1e-8
        f['uptake']={'by_layer_id':{'upper-mineral':1},'dry_zero_head_m':-100,'dry_full_head_m':-10,
            'wet_full_head_m':-0.2,'wet_zero_head_m':-0.1,'evidence':r['evidence'],'source_status':'SYNTHETIC TEST'}
        with self.assertRaisesRegex(ValueError,'absent roots'):p.parse(r)

    def test_ordinal_hydraulic_property_rejected(self):
        r=recipe();r['cells']['upper']['profile']['bindings'][0]['properties']['ksat_vertical_m_s']='high'
        with self.assertRaises(ValueError):p.parse(r)

    def test_nonfinite_input_rejected(self):
        r=recipe();r['gravity_m_s2']=float('nan')
        with self.assertRaises(ValueError):p.parse(r)

    def test_material_packing_mismatch_rejected(self):
        r=recipe();r['sediment'][0]['deposited_porosity']=0.3
        with self.assertRaises(ValueError):p.parse(r)

    def test_missing_forcing_cell_rejected(self):
        r=recipe();del r['events'][0]['cells']['upper']
        with self.assertRaises(ValueError):p.parse(r)

    def test_no_silent_canon_recipe(self):
        r=recipe();r['source_status']='CANON'
        with self.assertRaises(ValueError):p.parse(r)

    def test_unsupported_closed_pit_rejected(self):
        r=recipe();r['connectors']=[]
        with self.assertRaises(p.tt.TerrainRegimeError):p.parse(r)

    def test_original_recipe_unmutated(self):
        self.assertEqual(self.recipe,recipe())

    def test_exhausted_root_support_not_relocated(self):
        model=p.parse(self.recipe);pr=model.profiles['upper']
        stripped=si.strip_surface(pr,pr.column.layers[-1].mass_kg).profile
        with self.assertRaisesRegex(ValueError,'root support'):p.water_column(model,'upper',stripped)

    def test_solver_failure_cannot_be_partial_pass(self):
        with patch.object(p.sw,'advance',return_value={'status':'NUMERICAL_FAILURE','reason':'deliberate test'}):
            with self.assertRaises(p.CoupledStepFailure):p.run(self.recipe)

    def test_rejected_trials_leave_initial_state_unchanged(self):
        model=p.parse(self.recipe);s=p.initial(model);before=p.serialise(s)
        p.trial(model,s,self.recipe['events'][0],F(60))
        self.assertEqual(p.serialise(s),before)

    def test_endpoint_cancellation_does_not_hide_flux_difference(self):
        model=p.parse(self.recipe);s=p.initial(model)
        a=p.trial(model,s,self.recipe['events'][0],F(60));b=copy.deepcopy(a)
        b['history'][-1]['bottom_in_m3']=str(F(b['history'][-1]['bottom_in_m3'])+1)
        b['history'][-1]['bottom_out_m3']=str(F(b['history'][-1]['bottom_out_m3'])+1)
        error,_=p.compare(model,a,b,s);self.assertGreater(error,1)

    def test_actual_coupled_root_uptake_and_unsaturated_stability_mask(self):
        r=recipe();r['events']=r['events'][:1]
        for law in r['erosion']:law['k_per_year']=0.0
        for key,cell in r['cells'].items():
            profile=si.HydraulicProfile.from_dict(cell['profile'])
            profile,_=si.replace_porewater(profile,tuple(l.bulk_volume_m3/F(8) for l in profile.column.layers),evidence=r['evidence'])
            cell['profile']=profile.as_dict();cell['surface_water_m3']='0'
            cell['stability_roots'].update(mode='BASAL',maximum_active_depth_m=0.5)
            f=r['events'][0]['cells'][key];f.update(liquid_input_m_s=0,potential_et_m_s=1e-7)
            f['boundary'].update(kind='free_drainage',head_m=None)
            f['uptake']={'by_layer_id':{key+'-mineral':1},'dry_zero_head_m':-100,'dry_full_head_m':-10,
                'wet_full_head_m':-0.2,'wet_zero_head_m':-0.1,'evidence':r['evidence'],'source_status':'SYNTHETIC TEST'}
        result=p.run(r)
        self.assertGreater(sum(F(h['actual_et_m3']) for h in result['state']['history']),0)
        self.assertTrue(all(x['stability']['mask']=='INAPPLICABLE' for x in result['soil_products'].values()))
        self.assertTrue(all(x['stability']['inputs']['pore_pressure_pa']['lower']<0 for x in result['soil_products'].values()))

    def test_nonbinary_capacity_cannot_be_silently_overfilled(self):
        profile=p.parse(self.recipe).profiles['upper']
        layers=tuple(replace(l,porosity=F(1,10)) for l in profile.column.layers)
        column=replace(profile.column,layers=layers)
        props=tuple(replace(b.properties,porosity=F(1,10)) for b in profile.bindings)
        profile=si.bind_column(column,props,tuple(b.layer_id for b in profile.bindings),
            tuple(l.bulk_volume_m3/F(10) for l in layers),profile_id='upper',evidence=self.recipe['evidence'])
        with self.assertRaisesRegex(ValueError,'outside'):
            si.replace_porewater(profile,tuple(F(0.1)*l.bulk_volume_m3 for l in layers),evidence=self.recipe['evidence'])


if __name__=='__main__':unittest.main()
