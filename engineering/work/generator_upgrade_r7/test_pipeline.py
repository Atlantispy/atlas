import copy
from fractions import Fraction as F
import tempfile
from pathlib import Path
import unittest

from . import binding


class PipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bundle=binding.load(); cls.p=cls.bundle.pipeline; cls.recipe=cls.bundle.reference.recipe(cls.bundle)
        cls.full=cls.bundle.run(cls.recipe); cls.stop=cls.bundle.run(cls.recipe,stop_after=1)
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'checkpoint.json'
            cls.bundle.storage.write_json(path,cls.bundle.checkpoint(cls.stop))
            cls.saved=cls.bundle.storage.read_json(path)
            cls.restarted=cls.bundle.run(cls.recipe,resume=cls.saved)
        cls.scenario=sorted(cls.full['state']['members'])[0]
        cls.cell=cls.full['state']['members'][cls.scenario]['upper']
        cls.support=cls.full['actual_exposure']['members'][cls.scenario]['upper']

    def changed(self): return copy.deepcopy(self.recipe)

    def test_actual_three_coequal_members(self):
        expected={row.scenario_id for row in self.bundle.parent.pipeline.hm.snow_scenarios()}
        self.assertEqual(set(self.full['state']['members']),expected)
        self.assertEqual(self.full['snow_family'],'THREE_COEQUAL_SENSITIVITIES_NO_PREFERRED_MEMBER')

    def test_actual_parent_source_binding(self):
        parent=self.full['parent_result']
        self.assertEqual(parent['source_sha256'],self.bundle.parent.source_sha256)
        self.assertEqual(self.full['state']['parent_result_sha256'],self.bundle.storage.sha(self.bundle.storage.encoded(parent)))

    def test_source_climate_not_soil_age(self):
        self.assertEqual(F(self.support['climate_duration_seconds']),240)
        self.assertEqual(F(self.cell['formation_state']['elapsed_seconds']),63072000)
        self.assertIn('NOT_INFERRED',self.full['soil_age_status'])

    def test_extracted_temperature_is_actual_weighted_history(self):
        history=self.full['parent_result']['state']['members'][self.scenario]['joint_history']
        weighted=sum(F(r['duration_seconds'])*F(r['cells']['upper']['temperature_c']) for r in history)/sum(F(r['duration_seconds']) for r in history)
        self.assertEqual(self.support['climate_air_temperature_c'],float(weighted))

    def test_final_layer_moisture_not_fabricated_history_mean(self):
        for row in self.support['layers']:
            self.assertEqual(row['moisture_support'],'FINAL_ACTUAL_LAYER_STATE_HELD_FIXED_NOT_TEMPORAL_MEAN')
            self.assertAlmostEqual(row['wfps'],float(F(row['theta'])/F(row['theta_s'])))

    def test_existing_cohorts_use_their_actual_layer_water(self):
        source={row['layer_id']:row for row in self.support['layers']}
        for layer_id,row in self.cell['exposure_history'][0]['organic_results'].items():
            if layer_id in source:
                forcing=row['segments'][0]['forcing']
                self.assertEqual(forcing['water_filled_pore_fraction'],source[layer_id]['wfps'])
                self.assertEqual(forcing['water_state_id'],source[layer_id]['water_state_id'])

    def test_surface_mantle_moisture_has_explicit_hypothesis(self):
        self.assertEqual(self.recipe['organic']['surface_moisture_hypothesis'],'PARENT_COLUMN_FINAL_WFPS_HELD_HOMOGENISATION')
        forcing=self.cell['surface_organic']['segments'][0]['forcing']
        self.assertEqual(forcing['water_filled_pore_fraction'],self.support['profile_wfps'])
        self.assertIn('HELD_HOMOGENISATION',forcing['evidence'])

    def test_nonzero_separate_initial_organic_inventory_counted_once(self):
        recipe=self.changed(); recipe['organic']['initial_carbon_per_kg_mineral']=[0.00001,0.00002]
        recipe['organic']['surface_initial_carbon_kg_m2']=[0.001,0.002]
        row=self.p._simulate_cell(self.bundle,recipe,self.support,self.full['state']['parent_result_sha256'],0)
        mineral=sum((l.mineral_mass_kg_m2 for l in row['formation_state'].layers if l.phase!='bedrock'),F())
        # Kernel state fields are typed here; verify the independent supplied stock.
        expected=(mineral*(F(0.00001)+F(0.00002))+F(0.001)+F(0.002))/F(recipe['organic']['law']['carbon_fraction_dry_matter'])
        self.assertEqual(F(row['total_dry_mass_accounting']['initial_separate_organic_kg_m2']),expected)
        self.assertEqual(F(row['total_dry_mass_accounting']['final_organic_kg_m2']),expected)
        self.assertEqual(sum(F(g['organic_dry_mass_kg_m2']) for g in row['geometry']),expected)

    def test_physical_material_mass_conserved(self):
        budget=self.cell['total_dry_mass_accounting']
        self.assertEqual(F(budget['initial_mineral_kg_m2']),F(budget['final_mineral_kg_m2']))
        for step in self.cell['exposure_history']:
            for row in step['production']['mineral_balances']: self.assertEqual(F(row['residual_kg_m2']),0)

    def test_complete_organic_dry_origin_budget(self):
        b=self.cell['total_dry_mass_accounting']
        self.assertEqual(F(b['initial_separate_organic_kg_m2']),0)
        self.assertEqual(F(b['initial_separate_organic_kg_m2'])+F(b['natural_organic_input_kg_m2'])-F(b['organic_decomposition_origin_kg_m2']),F(b['final_organic_kg_m2']))
        self.assertEqual(F(b['final_combined_dry_kg_m2']),sum(F(row['total_dry_mass_kg_m2']) for row in self.cell['geometry']))

    def test_new_litter_changes_real_geometry(self):
        self.assertGreater(F(self.cell['total_dry_mass_accounting']['final_organic_kg_m2']),0)
        for row in self.cell['geometry']:
            self.assertEqual(F(row['total_dry_mass_kg_m2']),F(row['mineral_mass_kg_m2'])+F(row['organic_dry_mass_kg_m2']))
            self.assertEqual(F(row['thickness_m']),F(row['total_dry_mass_kg_m2'])/F(row['grain_density_kg_m3'])/(1-F(row['porosity'])))

    def test_actual_carbon_ledgers_close(self):
        for step in self.cell['exposure_history']:
            for row in (*step['organic_results'].values(),step['surface_organic_result']):
                b=row['carbon']
                self.assertEqual(F(b['initial_kg_m2'])+F(b['input_kg_m2'])-F(b['final_kg_m2'])-F(b['exported_atmospheric_carbon_kg_m2']),0)

    def test_new_rock_cohorts_have_zero_birth_age(self):
        latest=self.cell['exposure_history'][-1]
        for transfer in latest['production']['transfers']:
            row=self.cell['organic_by_layer'][transfer['product_layer_id']]
            self.assertEqual(F(row['state']['elapsed_seconds']),0)
            self.assertEqual(F(row['final_organic_carbon_kg_m2']),0)

    def test_prior_formed_cohort_has_only_subsequent_exposure(self):
        transfer=self.cell['exposure_history'][0]['production']['transfers'][0]
        row=self.cell['organic_by_layer'][transfer['product_layer_id']]
        self.assertEqual(F(row['state']['elapsed_seconds']),31536000)

    def test_original_material_layers_are_not_flattened(self):
        final={l['layer_id'] for l in self.cell['formation_state']['layers']}
        self.assertTrue(set(self.cell['source_parent_layer_ids'])<=final)
        self.assertGreater(len(final),len(self.cell['source_parent_layer_ids']))

    def test_particle_size_change_is_actual_and_mass_conserved(self):
        row=self.cell['exposure_history'][0]['particle_alteration'][0]
        self.assertGreater(row['dose'],0)
        self.assertEqual(F(row['mineral_mass_residual_kg_m2']),0)
        self.assertIn('NOT_PREDICTED',row['clay_mineralogy'])

    def test_horizon_profile_has_actual_a_o_c_r(self):
        values={v for r in self.cell['horizons']['horizons'] for v in r['candidates']}
        self.assertTrue({'A','O','C','R'}<=values)
        self.assertEqual(self.cell['horizons']['solum_status'],'MODELLED')
        self.assertGreater(F(self.cell['horizons']['mineral_pedogenic_solum_depth_m']),0)

    def test_solum_excludes_o_and_c_r(self):
        expected=F()
        for row in self.cell['horizons']['horizons']:
            if row['candidates']==['O']: continue
            if set(row['candidates'])<= {'C','R'}: break
            expected+=F(row['bottom_depth_m'])-F(row['top_depth_m'])
        self.assertEqual(F(self.cell['horizons']['mineral_pedogenic_solum_depth_m']),expected)

    def test_o_uses_organic_dominated_regime(self):
        self.assertEqual(self.cell['surface_organic']['segments'][0]['forcing']['regime'],'ORGANIC_DOMINATED')

    def test_fresh_consumer_actually_solves_new_geometry(self):
        probe=self.cell['formed_soil_water']; old=self.full['parent_result']['state']['members'][self.scenario]['physical']['water']['upper']
        self.assertEqual(probe['status'],'MODELLED_NEW_GEOMETRY_WATER_PROBE')
        self.assertNotEqual(probe['result']['state']['column_sha256'],old['state']['column_sha256'])
        self.assertIn('NOT_BORROWED',probe['initial_head_status'])

    def test_new_pressure_is_computed_from_solved_head(self):
        probe=self.cell['formed_soil_water']
        for row in probe['result']['layers']:
            self.assertEqual(row['signed_pore_pressure_pa'],probe['inputs']['water_density_kg_m3']*probe['inputs']['gravity_m_s2']*row['head_m'])

    def test_complete_water_surface_reservoir_budget(self):
        b=self.cell['formed_soil_water']['water_accounting']
        residual=sum(F(b[k]) for k in ('parent_porewater_m','parent_surface_water_m','reservoir_initial_m','external_liquid_m','bottom_in_m'))-sum(F(b[k]) for k in ('formed_final_porewater_m','surface_final_m','reservoir_final_m','bottom_out_m','actual_et_m'))
        self.assertEqual(residual,F(b['physical_numerical_residual_m']))
        self.assertLess(abs(float(residual)),1e-8)
        self.assertGreaterEqual(F(b['reservoir_final_m']),0)

    def test_fertility_uses_actual_formed_water(self):
        actual=self.bundle.storage.sha(self.bundle.storage.encoded(self.cell['formed_soil_water']))
        self.assertEqual(self.cell['fertility']['assay_support']['actual_formed_water_sha256'],actual)
        self.assertNotEqual(actual,self.support['water_state_id'])

    def test_fertility_has_explicit_organic_elemental_inputs(self):
        row=self.cell['fertility']
        self.assertIn('EXPLICIT_CURRENT',row['assay_support']['organic_nitrogen'])
        self.assertGreater(row['index_0_1'],0); self.assertLess(row['index_0_1'],1)

    def test_full_saved_restart_exact_parity(self):
        self.assertEqual(self.full,self.restarted)
        self.assertEqual(self.bundle.checkpoint(self.full),self.bundle.checkpoint(self.restarted))

    def test_restart_does_not_double_apply_exposure(self):
        self.assertEqual(self.restarted['state']['completed_exposures'],2)
        self.assertEqual(len(self.cell['exposure_history']),2)

    def test_rechecksummed_forged_state_rejected_by_replay(self):
        cp=copy.deepcopy(self.saved)
        cp['state']['members'][self.scenario]['upper']['total_dry_mass_accounting']['final_organic_kg_m2']='999'
        cp['state_sha256']=self.bundle.storage.sha(self.bundle.storage.encoded(cp['state']))
        with self.assertRaisesRegex(ValueError,'replay'): self.bundle.run(self.recipe,resume=cp)

    def test_changed_recipe_restart_rejected(self):
        recipe=self.changed(); recipe['soil_exposures'][0]['duration_seconds']+=1
        with self.assertRaisesRegex(ValueError,'binding differs'): self.bundle.run(recipe,resume=self.saved)

    def test_old_checkpoint_schema_rejected(self):
        cp=copy.deepcopy(self.saved); cp['schema']='diadem.strict-soil-water-checkpoint.r6'
        with self.assertRaises(ValueError): self.bundle.run(self.recipe,resume=cp)

    def test_duplicate_exposure_refused(self):
        recipe=self.changed(); recipe['soil_exposures'][1]['exposure_id']=recipe['soil_exposures'][0]['exposure_id']
        with self.assertRaises(ValueError): self.p.parse(self.bundle,recipe)

    def test_no_implicit_age(self):
        recipe=self.changed(); del recipe['soil_exposures'][0]['duration_seconds']
        with self.assertRaises(ValueError): self.p.parse(self.bundle,recipe)

    def test_boolean_duration_refused(self):
        recipe=self.changed(); recipe['soil_exposures'][0]['duration_seconds']=True
        with self.assertRaises(ValueError): self.p.parse(self.bundle,recipe)

    def test_parent_mass_interpretation_required(self):
        recipe=self.changed(); recipe['parent_mass_interpretation']='UNKNOWN'
        with self.assertRaises(ValueError): self.p.parse(self.bundle,recipe)

    def test_particle_fraction_nonclosure_refused(self):
        recipe=self.changed(); recipe['materials']['mineral|immobile_regolith']['particle_mass_fractions']=[1,1,1,1]
        with self.assertRaises(ValueError): self.p.parse(self.bundle,recipe)

    def test_boolean_particle_fraction_refused(self):
        recipe=self.changed(); recipe['materials']['mineral|immobile_regolith']['particle_mass_fractions']=[True,0,0,0]
        with self.assertRaises(ValueError): self.p.parse(self.bundle,recipe)

    def test_initial_organic_pair_has_exact_inventory(self):
        recipe=self.changed(); recipe['organic']['initial_carbon_per_kg_mineral']=[0,0,1]
        with self.assertRaises(ValueError): self.p.parse(self.bundle,recipe)

    def test_checkpoint_state_shape_is_explicit(self):
        cp=copy.deepcopy(self.saved); cp['state']=[]; cp['state_sha256']=self.bundle.storage.sha(self.bundle.storage.encoded([]))
        with self.assertRaisesRegex(ValueError,'soil state'): self.bundle.run(self.recipe,resume=cp)

    def test_mineral_elemental_stock_overmass_refused(self):
        recipe=self.changed(); recipe['materials']['mineral|immobile_regolith']['reserve_mass_fractions']={'N':0.5,'P':0.5,'K':0.5}
        with self.assertRaises(ValueError): self.p.parse(self.bundle,recipe)

    def test_organic_carbon_and_element_overmass_refused(self):
        recipe=self.changed(); recipe['fertility']['organic_reserve_mass_fractions']={'N':0.3,'P':0.3,'K':0.3}
        with self.assertRaises(ValueError): self.p.parse(self.bundle,recipe)

    def test_unknown_organic_elements_not_zero(self):
        recipe=self.changed(); recipe['fertility']['organic_reserve_mass_fractions']['N']=None
        with self.assertRaises(ValueError): self.p.parse(self.bundle,recipe)

    def test_uncoupled_dissolution_refused(self):
        recipe=self.changed(); recipe['formation']['laws'][0]['dissolved_mass_fraction']=0.1
        with self.assertRaises(ValueError): self.p.parse(self.bundle,recipe)

    def test_missing_new_hydraulic_law_refused(self):
        options=copy.deepcopy(self.recipe['water_consumer']); del options['laws']['organic|organic_mantle']
        with self.assertRaisesRegex(ValueError,'explicit joint hydraulic law'):
            self.p.postformation_water(self.bundle,self.cell['geometry'],self.support,options)

    def test_packing_hydraulic_mismatch_refused(self):
        options=copy.deepcopy(self.recipe['water_consumer']); options['laws']['organic|organic_mantle']['porosity']=0.8
        with self.assertRaisesRegex(ValueError,'packing/density'):
            self.p.postformation_water(self.bundle,self.cell['geometry'],self.support,options)

    def test_insufficient_explicit_water_refused(self):
        options=copy.deepcopy(self.recipe['water_consumer']); options['reservoir_water_m']=0
        support=copy.deepcopy(self.support); support['parent_porewater_m']='0'; support['parent_surface_water_m']='0'
        with self.assertRaisesRegex(ValueError,'reservoir insufficient'):
            self.p.postformation_water(self.bundle,self.cell['geometry'],support,options)

    def test_saturated_initial_pressure_not_inferred(self):
        options=copy.deepcopy(self.recipe['water_consumer']); options['initial_pore_saturation']=1
        with self.assertRaisesRegex(ValueError,'saturated pressure'):
            self.p.postformation_water(self.bundle,self.cell['geometry'],self.support,options)

    def test_missing_probe_is_explicit_unknown_fertility(self):
        recipe=self.changed(); recipe['water_consumer']=None
        row=self.p._simulate_cell(self.bundle,recipe,self.support,self.full['state']['parent_result_sha256'],1)
        self.assertEqual(row['formed_soil_water']['status'],'REQUIRES_WATER_RECOMPUTATION')
        self.assertEqual(row['fertility']['status'],'UNKNOWN'); self.assertIsNone(row['fertility']['index_0_1'])

    def test_no_production_canon_or_optimisation_claim(self):
        for key in ('production_installed','canon_changed','optimisation_performed'): self.assertIs(self.full[key],False)
        self.assertIn('PRE_FORMATION_REFERENCE_NOT_CURRENT',self.full['product_inventory']['parent_result'])

    def test_actual_changed_climate_changes_organic_and_fertility(self):
        recipe=self.changed()
        for event in recipe['parent_recipe']['retained_recipe']['events']: event['atmosphere']['reference_temperature_c']+=3
        changed=self.bundle.run(recipe)['state']['members'][self.scenario]['upper']
        self.assertNotEqual(changed['total_dry_mass_accounting']['final_organic_kg_m2'],self.cell['total_dry_mass_accounting']['final_organic_kg_m2'])
        self.assertNotEqual(changed['fertility']['index_0_1'],self.cell['fertility']['index_0_1'])


if __name__=='__main__': unittest.main()
