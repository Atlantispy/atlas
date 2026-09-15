"""Actual retained physical products cross the seasonal stage interfaces."""
from copy import deepcopy
from fractions import Fraction as F
import unittest
from . import binding, fixtures


class SeasonalIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.b=binding.load();cls.p=cls.b.pipeline;cls.r=cls.b.reference.recipe(cls.b);cls.a=fixtures.physical()
        cls.key=('LOW_DDF3_SIGMA2','TEMPERATE_R8_B','lower')
        cls.w=cls.p.hydraulic_product(cls.b,cls.r,cls.a,*cls.key)
        cls.c=cls.p.carbon_product(cls.b,cls.r,cls.a,cls.w,*cls.key)
        cls.bridge=cls.b.graph.load('work.generator_upgrade_r10.carbon_bridge')
    def test_reference_all_three_families_remain_counterfactual(self):
        self.assertEqual({v['family_id'] for v in self.r['hydraulic_hypotheses'].values()},{'R8_A','R8_B','R8_C'})
    def test_recipe_rejects_extra_fields(self):
        r=deepcopy(self.r);r['pretend_field']=1
        with self.assertRaises(ValueError):self.p.parse(self.b,r)
    def test_recipe_requires_bound_source(self):
        r=deepcopy(self.r);r['source_sha256']='0'*64
        with self.assertRaises(ValueError):self.p.parse(self.b,r)
    def test_hypothesis_cannot_alias_unit_path(self):
        r=deepcopy(self.r);r['hydraulic_hypotheses']['a/b']=r['hydraulic_hypotheses'].pop('TEMPERATE_R8_A')
        with self.assertRaises(ValueError):self.p.parse(self.b,r)
    def test_every_physical_cell_needs_explicit_hypothesis(self):
        r=deepcopy(self.r);del r['hydraulic_hypotheses']['TEMPERATE_R8_B']['columns']['lower']
        with self.assertRaises(ValueError):self.p.parse(self.b,r)
    def test_new_soil_temperature_model_not_invented(self):
        r=deepcopy(self.r);r['hydraulic_hypotheses']['TEMPERATE_R8_B']['columns']['lower']['soil_thermal_regime']='AIR_IS_SOIL'
        with self.assertRaises(ValueError):self.p.parse(self.b,r)
    def test_full_calendar_carries_probe_clock(self):
        self.assertEqual(self.w['status'],'MODELLED_SEASONAL_HYDRAULICS')
        self.assertEqual(self.w['completed_months'],12)
        self.assertEqual(self.w['final_state']['elapsed_seconds'],31536030.)
        self.assertEqual(F(self.w['calendar_start_elapsed_seconds']),30)
    def test_root_face_excludes_bedrock(self):
        c=self.w['column'];self.assertEqual(c['root_boundary_index'],len(c['layers'])-1)
        self.assertEqual(c['layers'][-1]['layer_id'],'lower-substrate')
        self.assertLess(float(F(self.w['root_boundary_depth_m'])),1.2)
    def test_no_positive_root_weight_below_face(self):
        r=deepcopy(self.r);s=r['hydraulic_hypotheses']['TEMPERATE_R8_B']['columns']['lower'];s['root_weights_by_layer']={'lower-substrate':1}
        with self.assertRaises(ValueError):self.p.hydraulic_inputs(self.b,r,self.a,*self.key)
    def test_unknown_root_layer_refused(self):
        r=deepcopy(self.r);r['hydraulic_hypotheses']['TEMPERATE_R8_B']['columns']['lower']['root_weights_by_layer']={'invented':1}
        with self.assertRaises(ValueError):self.p.hydraulic_inputs(self.b,r,self.a,*self.key)
    def test_root_face_cannot_exceed_pft_depth(self):
        r=deepcopy(self.r);r['hydraulic_hypotheses']['TEMPERATE_R8_B']['pft_id']='grass'
        with self.assertRaises(ValueError):self.p.hydraulic_inputs(self.b,r,self.a,*self.key)
    def test_changed_retained_head_binding_refused(self):
        a=deepcopy(self.a);a['soil_result']['state']['members'][self.key[0]]['lower']['formed_soil_water']['result']['state']['column_sha256']='0'*64
        with self.assertRaises(ValueError):self.p.hydraulic_inputs(self.b,self.r,a,*self.key)
    def test_three_family_demands_exact_parent_pft_arithmetic(self):
        source=self.a['seasonal']['members'][self.key[0]]['cells']['lower']['events']
        for family,multiplier in (('R8_A',.9),('R8_B',1.),('R8_C',1.1)):
            values=self.p.hydraulic_inputs(self.b,self.r,self.a,self.key[0],'TEMPERATE_'+family,'lower')[4]
            for e,actual in zip(source,values):
                self.assertEqual(actual.potential_root_demand_m_s,F(e['potential_evaporation_m_s']*.8*multiplier if e['temperature_c']>5 else 0))
    def test_rain_and_snow_melt_not_added_twice(self):
        source=self.a['seasonal']['members'][self.key[0]]['cells']['lower']['events']
        values=self.p.hydraulic_inputs(self.b,self.r,self.a,*self.key)[4]
        self.assertEqual([e.liquid_input_m_s for e in values],[F(e['liquid_input_m_s']) for e in source])
    def test_soil_state_does_not_reset_in_january_or_december(self):
        self.assertNotEqual(self.w['final_state']['head_m'],self.w['initial_state']['head_m'])
        self.assertNotEqual(self.w['months']['1']['end_state']['head_m'],self.w['months']['12']['end_state']['head_m'])
    def test_water_whole_year_balance(self):
        l=self.w['annual']['ledger_m']
        residual=F(l['initial_storage_m'])+F(l['supplied_liquid_input_m'])+F(l['bottom_upward_m'])-F(l['final_storage_m'])-F(l['bottom_downward_m'])-F(l['surface_runoff_m'])-F(l['actual_et_m'])
        self.assertLess(abs(residual),F(self.r['budget_atol_m']))
    def test_local_export_area_converted_once(self):
        out=self.p.downstream(self.w,F(2000000))
        self.assertEqual(len(out['local_water_supply']),12)
        for mid,row in out['local_water_supply'].items():
            a=self.w['months'][mid];expected=F(a['ledger_m']['surface_runoff_m'])*2000000
            self.assertEqual(F(row['local_surface_export_m3']['exact']),expected)
            self.assertEqual(F(row['local_mean_export_supply_m3_s']['exact']),expected/F(a['duration_seconds']))
    def test_unmodelled_consumers_remain_null(self):
        out=self.p.downstream(self.w,F(2000000))
        for key in ('river_flow_m3_s','lake_level_m','soil_ice_fraction','crop_yield_kg','food_supply_kg','route_passability','seasonal_population_growth','political_boundary_change'):
            self.assertIsNone(out[key])
    def test_actual_field_carbon_not_confused_with_experiment(self):
        self.assertEqual(self.c['actual_field_prediction']['status'],'UNKNOWN')
        self.assertEqual(self.c['geometry_feedback'],'NOT_APPLIED_DIAGNOSTIC_ONLY')
        self.assertTrue(self.c['selected_layers_not_whole_soil_inventory'])
    def test_both_selected_carbon_layers_advance_retained_pools(self):
        self.assertEqual(set(self.c['layers']),{'lower-mineral','lower-organic-mantle'})
        for item in self.c['layers'].values():
            c=item['diagnostic'];self.assertEqual(c['status'],'MODELLED_SEASONAL_CARBON_DIAGNOSTIC');self.assertEqual(c['completed_months'],12)
            self.assertEqual(F(c['calendar_start_pool_age_seconds']),63072000)
            self.assertEqual(F(*c['final_state']['elapsed_seconds']),94608000)
    def test_carbon_and_water_have_different_retained_ages(self):
        c=self.c['layers']['lower-mineral']['diagnostic']
        self.assertNotEqual(F(c['calendar_start_pool_age_seconds']),F(self.w['calendar_start_elapsed_seconds']))
        self.assertEqual(F(c['events'][0]['water_sample_seconds_in_year']),0)
    def test_carbon_water_start_is_actual_layer_wfps(self):
        args=self.bridge.inputs(self.b,self.r,self.a,self.w,*self.key,'lower-mineral');event=args[4][0]
        solver=self.b.parent.parent.parent.parent.solver;layer=next(l for l in self.w['column']['layers'] if l['layer_id']=='lower-mineral');index=[l['layer_id'] for l in self.w['column']['layers']].index('lower-mineral')
        expected=solver.hydraulic_properties(solver.HydraulicLayer(**layer),self.w['initial_state']['head_m'][index])[0]/layer['theta_s']
        self.assertEqual(event.forcing.water_filled_pore_fraction,expected)
        self.assertEqual(event.moisture_hold,'EVENT_START_SAMPLE_HELD')
    def test_missing_soil_temperature_blocks_carbon_not_water(self):
        r=deepcopy(self.r);r['carbon']['soil_temperature_k_by_month'][3]=None
        out=self.bridge.layer_product(self.b,r,self.a,self.w,*self.key,'lower-mineral')
        self.assertEqual(out['status'],'UNKNOWN');self.assertEqual(out['completed_months'],3);self.assertIsNone(out['annual']);self.assertIsNone(out['final_state'])
    def test_missing_litter_is_not_zero(self):
        r=deepcopy(self.r);r['carbon']['fast_litter_carbon_kg_m2_s_by_month'][0]=None
        out=self.bridge.layer_product(self.b,r,self.a,self.w,*self.key,'lower-mineral')
        self.assertEqual(out['status'],'UNKNOWN');self.assertEqual(out['completed_events'],0)
    def test_unknown_thermal_branch_keeps_causal_water_gap(self):
        r=deepcopy(self.r);r['hydraulic_hypotheses']['TEMPERATE_R8_B']['columns']['lower']['soil_thermal_regime']='UNKNOWN'
        out=self.p.hydraulic_product(self.b,r,self.a,*self.key)
        self.assertEqual(out['status'],'UNKNOWN');self.assertEqual(out['completed_events'],0);self.assertIsNone(out['annual'])
    def test_actual_carbon_full_restart_exact(self):
        stop=self.bridge.layer_product(self.b,self.r,self.a,self.w,*self.key,'lower-mineral',stop_after=2)
        resumed=self.bridge.layer_product(self.b,self.r,self.a,self.w,*self.key,'lower-mineral',resume=stop['checkpoint'])
        self.assertEqual(resumed,self.c['layers']['lower-mineral']['diagnostic'])
    def test_actual_water_full_restart_after_snow_depletion_exact(self):
        stop=self.p.hydraulic_product(self.b,self.r,self.a,*self.key,stop_after=2)
        resumed=self.p.hydraulic_product(self.b,self.r,self.a,*self.key,resume=stop['checkpoint'])
        self.assertEqual(resumed,self.w)
    def test_source_physical_geometry_not_mutated(self):
        self.assertEqual(self.a,fixtures.physical())
    def test_carbon_rejects_wrong_hydraulic_scenario(self):
        w=deepcopy(self.w);w['scenario_id']='wrong'
        with self.assertRaises(ValueError):self.bridge.inputs(self.b,self.r,self.a,w,*self.key,'lower-mineral')
    def test_carbon_rejects_duplicate_water_events(self):
        w=deepcopy(self.w);w['events'].append(deepcopy(w['events'][0]))
        with self.assertRaises(ValueError):self.bridge.inputs(self.b,self.r,self.a,w,*self.key,'lower-mineral')
    def test_carbon_rejects_changed_water_duration(self):
        w=deepcopy(self.w);w['events'][0]['duration_seconds']='1'
        with self.assertRaises(ValueError):self.bridge.inputs(self.b,self.r,self.a,w,*self.key,'lower-mineral')
    def test_carbon_rejects_changed_water_column(self):
        w=deepcopy(self.w);w['column']['layers'][0]['thickness_m']*=2
        with self.assertRaises(ValueError):self.bridge.inputs(self.b,self.r,self.a,w,*self.key,'lower-mineral')
    def test_carbon_rejects_wrong_retained_pool_identity(self):
        a=deepcopy(self.a);a['soil_result']['state']['members'][self.key[0]]['lower']['organic_by_layer']['lower-mineral']['state']['layer_id']='other-layer'
        with self.assertRaises(ValueError):self.bridge.inputs(self.b,self.r,a,self.w,*self.key,'lower-mineral')


if __name__=='__main__':unittest.main()
