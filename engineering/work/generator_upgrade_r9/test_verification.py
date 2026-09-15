"""Adversarial verifier guards using labelled synthetic envelope fixtures.

These tests do not stand in for the actual scientific reference acceptance run.
"""
import copy
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from . import binding, verify as v


class VerificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bundle=binding.load()
        cls.helper,cls.utility_path,cls.utility_sha=v.utility()

    def pins(self):
        return patch.multiple(v,EXPECTED_COUNT=2,INVENTORY_SHA256=v.inventory_digest(['alpha','beta']))

    def test_inventory_pending_blocks_release(self):
        with patch.multiple(v,EXPECTED_COUNT=None,INVENTORY_SHA256=None):
            with self.assertRaisesRegex(ValueError,'pending'): v.require_inventory(['alpha'])

    def test_science_pending_blocks_seal_even_with_pins(self):
        with self.pins(),patch.object(v,'PRODUCT_CONTRACT_READY',False):
            with self.assertRaisesRegex(ValueError,'scientific product contract pending'):
                v.require_release_ready(['alpha','beta'])

    def test_inventory_exact_accepts(self):
        with self.pins(): v.require_inventory(['alpha','beta'])

    def test_inventory_reordered_rejected(self):
        with self.pins(),self.assertRaises(ValueError): v.require_inventory(['beta','alpha'])

    def test_inventory_duplicate_rejected(self):
        with self.pins(),self.assertRaises(ValueError): v.require_inventory(['alpha','alpha'])

    def test_inventory_bool_count_rejected(self):
        with patch.multiple(v,EXPECTED_COUNT=True,INVENTORY_SHA256='a'*64):
            with self.assertRaises(ValueError): v.require_inventory(['alpha'])

    def test_inventory_nonlist_rejected(self):
        with self.pins(),self.assertRaises(ValueError): v.require_inventory(('alpha','beta'))

    def test_inventory_different_ids_same_count_rejected(self):
        with self.pins(),self.assertRaises(ValueError): v.require_inventory(['alpha','gamma'])

    def test_record_all_actual_identity_lists_required(self):
        row=self.record_fixture()
        with self.pins():
            v.validate_tests(row)
            for key in ('started','stopped','passed'):
                changed=copy.deepcopy(row); changed[key]=['beta','alpha']
                with self.subTest(key=key),self.assertRaises(ValueError): v.validate_tests(changed)

    def test_skip_failure_expected_failure_not_accepted(self):
        with self.pins():
            for key in ('failures','errors','skips','expected_failures','unexpected_successes'):
                row=self.record_fixture(); row[key]=1
                with self.subTest(key=key),self.assertRaises(ValueError): v.validate_tests(row)

    def test_boolean_success_count_not_accepted(self):
        with self.pins():
            row=self.record_fixture(); row['failures']=False
            with self.assertRaises(ValueError): v.validate_tests(row)

    def test_false_pass_status_not_accepted(self):
        with self.pins():
            row=self.record_fixture(); row['status']='FAIL'
            with self.assertRaises(ValueError): v.validate_tests(row)

    @staticmethod
    def record_fixture():
        ids=['alpha','beta']
        return {'status':'PASS','tests':2,'test_ids':ids,'inventory_sha256':v.inventory_digest(ids),
            'started':ids[:],'stopped':ids[:],'passed':ids[:],'failures':0,'errors':0,
            'skips':0,'expected_failures':0,'unexpected_successes':0}

    def test_child_environment_clears_parent_optimisation(self):
        with patch.dict(os.environ,{'PYTHONOPTIMIZE':'2'}):
            environment=self.helper.child_environment()
            self.assertNotIn('PYTHONOPTIMIZE',environment)
            self.assertEqual(environment['PYTHONDONTWRITEBYTECODE'],'1')
            self.assertEqual(os.environ['PYTHONOPTIMIZE'],'2')

    def test_actual_child_modes_ignore_parent_optimisation_two(self):
        with patch.dict(os.environ,{'PYTHONOPTIMIZE':'2'}):
            for mode,flags in ((0,[]),(2,['-OO'])):
                result=subprocess.run([sys.executable,'-B',*flags,'-c','import sys; print(sys.flags.optimize)'],
                    env=self.helper.child_environment(),capture_output=True,text=True,check=True,timeout=20)
                self.assertEqual(result.stdout.strip(),str(mode))

    def test_missing_test_file_inventory_rejected_before_loading(self):
        with patch.object(Path,'glob',return_value=[]):
            with self.assertRaisesRegex(ValueError,'test file inventory'):
                v.discover(self.helper)

    def test_reported_worker_flag_must_be_actual_integer(self):
        row=self.worker_header()
        for value in (True,'0',2,1):
            row['optimisation_flag']=value
            with self.subTest(value=value),self.assertRaises(ValueError):
                v.validate_worker_header(row,self.bundle,0)

    def test_worker_modes_only_zero_or_two(self):
        row=self.worker_header()
        for mode in (False,1,3,'0'):
            with self.subTest(mode=mode),self.assertRaises(ValueError): v.validate_worker_header(row,self.bundle,mode)
        v.validate_worker_header(row,self.bundle,0)
        row['optimisation_flag']=2; v.validate_worker_header(row,self.bundle,2)

    def test_worker_source_identity_not_only_digest(self):
        row=self.worker_header(); row['source_identity']={}
        with self.assertRaises(ValueError): v.validate_worker_header(row,self.bundle,0)

    def worker_header(self):
        return {'status':'PASS','optimisation_flag':0,'source_identity':self.bundle.identity,
            'source_sha256':self.bundle.source_sha256}

    def test_canonical_import_cannot_install_standalone_capture(self):
        with patch.object(v,'ENTRY_SOURCE_SHA256','0'*64):
            with self.assertRaisesRegex(ValueError,'fresh source-compiled'): v.install()

    def test_missing_fresh_entry_proof_refused(self):
        with patch.object(v,'ENTRY_SOURCE_SHA256',None):
            with self.assertRaises(ValueError): v.install()

    def test_utility_is_actual_fixed_retained_bytes(self):
        self.assertEqual(v.sha(self.utility_path.read_bytes()),self.utility_sha)
        self.assertEqual(Path(self.helper.__file__),self.utility_path)
        self.assertNotIn('_r8_exact_verification_utilities',sys.modules)

    def test_nested_map_retains_r7_external_validation_sources(self):
        mapping=v.source_map(self.bundle.identity,self.helper)
        retained=self.bundle.identity['retained_source_identity']['retained_source_identity']
        for path,digest in retained['external_test_reference_sources'].items():
            self.assertEqual(mapping[self.helper.canonical(path)],digest)
        self.assertGreaterEqual(len(mapping),161)

    def test_conflicting_external_binding_rejected(self):
        altered=copy.deepcopy(self.bundle.identity)
        altered['external_reference_sources']={str(v.HERE/'binding.py'):'0'*64}
        with self.assertRaisesRegex(ValueError,'conflicting'): v.source_map(altered,self.helper)

    def test_external_path_and_digest_strict(self):
        for rows in ({'relative.py':'0'*64},{str(v.HERE/'binding.py'):'bad'},[] ):
            with self.subTest(rows=rows),self.assertRaises(ValueError):
                v.external_sources({'external_reference_sources':rows})

    def test_actual_executed_bytes_validated_live(self):
        path=str(v.HERE/'binding.py'); digest=v.sha(Path(path).read_bytes())
        with patch.object(v,'required_sources',return_value=[Path(path)]):
            v.validate_execution({path:digest},self.bundle.identity,self.helper)
            with self.assertRaises(ValueError): v.validate_execution({path:'0'*64},self.bundle.identity,self.helper)

    def test_live_source_differs_even_if_receipt_digest_matches_identity(self):
        path=str(v.HERE/'binding.py'); digest=v.sha(Path(path).read_bytes())
        with patch.object(v,'required_sources',return_value=[]),patch.object(Path,'read_bytes',return_value=b'changed'):
            with self.assertRaisesRegex(ValueError,'byte identity'):
                v.validate_execution({path:digest},self.bundle.identity,self.helper)

    def test_missing_required_actual_execution_rejected(self):
        path=str(v.HERE/'binding.py'); digest=v.sha(Path(path).read_bytes())
        with patch.object(v,'required_sources',return_value=[v.HERE/'verify.py']):
            with self.assertRaisesRegex(ValueError,'was not executed'):
                v.validate_execution({path:digest},self.bundle.identity,self.helper)

    def test_execution_without_fresh_compile_rejected(self):
        capture=self.helper.ExecutionCapture()
        code=compile('pass','<synthetic-capture-test>','exec').replace(co_filename=str(v.HERE/'binding.py'))
        with self.assertRaisesRegex(ValueError,'freshly captured'): capture.observe('exec',(code,))

    def test_private_graph_requires_observed_execution(self):
        path=str(v.HERE/'binding.py'); digest=v.sha(Path(path).read_bytes())
        records={label:{'work.generator_upgrade_r9.binding':{'path':path,'sha256':digest}} for label in ('r9','r8','r7','r6')}
        with self.assertRaisesRegex(ValueError,'private/actual'):
            v.validate_private_executions(records,{},self.bundle,self.helper)

    def test_private_graph_chain_cannot_be_omitted(self):
        with self.assertRaises(ValueError): v.validate_private_executions({}, {},self.bundle,self.helper)

    def test_private_graph_cannot_mislabel_an_observed_source(self):
        records={}; executed={}
        for label,graph in (('r9',self.bundle.graph),('r8',self.bundle.parent.graph),('r7',self.bundle.parent.parent.graph),('r6',self.bundle.parent.parent.parent.graph)):
            logical=next(iter(graph.nodes)); path,digest=graph.nodes[logical]
            records[label]={logical:{'path':str(path),'sha256':digest}}; executed[str(path)]=digest
        v.validate_private_executions(records,executed,self.bundle,self.helper)
        records['r9']['work.generator_upgrade_r9.undeclared']=records['r9'].pop(next(iter(records['r9'])))
        with self.assertRaisesRegex(ValueError,'private/actual'):
            v.validate_private_executions(records,executed,self.bundle,self.helper)

    def fixture(self):
        recipe={'schema':'synthetic-verifier-recipe-not-scientific','parent_recipe':{'input':1},
            'organisms':{'annual':{}},'seasons':[{'season_id':'a'},{'season_id':'b'}]}
        parent={'schema':'diadem.biomes-vegetation-result.r8','source_sha256':self.bundle.parent.source_sha256,
            'recipe_sha256':v.sha(self.bundle.storage.encoded(recipe['parent_recipe']))}
        environment={'status':'SYNTHETIC_VERIFIER_ENVELOPE_ONLY','scenarios':{'SYNTHETIC':{}}}
        parent_sha=v.sha(self.bundle.storage.encoded(parent))
        row={'schema':v.RESULT_SCHEMA,'source_sha256':self.bundle.source_sha256,
            'recipe_sha256':v.sha(self.bundle.storage.encoded(recipe)), 'parent_result_sha256':parent_sha,'environment':environment,
            'state':{'completed_units':2,'parent_result_sha256':parent_sha,
                'environment_sha256':v.sha(self.bundle.storage.encoded(environment)),
                'results':{'SYNTHETIC':{'annual':{'a':{},'b':{}}}}}}
        self.parent_fixture=parent
        return recipe,row

    def test_envelope_complete_and_stop_cursor(self):
        recipe,row=self.fixture()
        self.assertEqual(len(v.validate_envelope(row,recipe,self.bundle,self.parent_fixture,complete=True)),2)
        row['state']['completed_units']=1; del row['state']['results']['SYNTHETIC']['annual']['b']
        self.assertEqual(len(v.validate_envelope(row,recipe,self.bundle,self.parent_fixture,complete=False)),1)

    def test_envelope_boolean_cursor_rejected(self):
        recipe,row=self.fixture(); row['state']['completed_units']=True
        with self.assertRaises(ValueError): v.validate_envelope(row,recipe,self.bundle,self.parent_fixture,complete=False)

    def test_envelope_source_recipe_and_parent_join_rejected(self):
        for key in ('source_sha256','recipe_sha256'):
            recipe,row=self.fixture(); row[key]='0'*64
            with self.subTest(key=key),self.assertRaises(ValueError): v.validate_envelope(row,recipe,self.bundle,self.parent_fixture,complete=True)
        for key in ('parent_result_sha256','environment_sha256'):
            recipe,row=self.fixture(); row['state'][key]='0'*64
            with self.subTest(key=key),self.assertRaises(ValueError): v.validate_envelope(row,recipe,self.bundle,self.parent_fixture,complete=True)

    def test_envelope_malformed_organism_map_rejected(self):
        recipe,row=self.fixture(); row['state']['results']['SYNTHETIC']['annual']=[]
        with self.assertRaises(ValueError): v.validate_envelope(row,recipe,self.bundle,self.parent_fixture,complete=True)

    def test_envelope_extra_state_rejected(self):
        recipe,row=self.fixture(); row['state']['pretend_water']={}
        with self.assertRaises(ValueError): v.validate_envelope(row,recipe,self.bundle,self.parent_fixture,complete=True)

    def test_separate_parent_result_hash_rejected(self):
        recipe,row=self.fixture(); row['parent_result_sha256']='0'*64
        with self.assertRaises(ValueError): v.validate_envelope(row,recipe,self.bundle,self.parent_fixture,complete=True)

    def saved_fixture(self,root):
        recipe,full=self.fixture(); stop=copy.deepcopy(full)
        stop['state']['completed_units']=1; del stop['state']['results']['SYNTHETIC']['annual']['b']
        values={'recipe.json':recipe,'parent-result.json':self.parent_fixture,'full-result.json':full,'restart-result.json':full,'stop-result.json':stop,
            'full-checkpoint.json':self.bundle.checkpoint(full),'restart-checkpoint.json':self.bundle.checkpoint(full),
            'stop-checkpoint.json':self.bundle.checkpoint(stop)}
        for name,value in values.items(): self.bundle.storage.write_json(root/name,value)
        return {'path':str(root),'files':{name:v.sha((root/name).read_bytes()) for name in values},
            'reference_sha256':v.sha(self.bundle.storage.encoded(full)),
            'parent_result_sha256':v.sha(self.bundle.storage.encoded(self.parent_fixture)),'scientific_checks':{'fixture':'NOT_SCIENTIFIC'}},values

    def test_eight_saved_artifacts_exact_readback(self):
        with tempfile.TemporaryDirectory() as directory,patch.object(v,'validate_products',return_value={'fixture':'NOT_SCIENTIFIC'}):
            record,values=self.saved_fixture(Path(directory))
            self.assertEqual(v.validate_artifacts(record,self.bundle),values['full-result.json'])

    def test_forged_checkpoint_rechecksum_does_not_match_result(self):
        with tempfile.TemporaryDirectory() as directory,patch.object(v,'validate_products',return_value={'fixture':'NOT_SCIENTIFIC'}):
            root=Path(directory); record,values=self.saved_fixture(root)
            forged=copy.deepcopy(values['stop-checkpoint.json']); forged['state']['completed_units']=99
            forged['state_sha256']=v.sha(self.bundle.storage.encoded(forged['state']))
            # Redirect readback without editing an existing artifact or predecessor.
            original=self.bundle.storage.read_json
            def read(path): return forged if Path(path).name=='stop-checkpoint.json' else original(path)
            with patch.object(self.bundle.storage,'read_json',side_effect=read):
                with self.assertRaisesRegex(ValueError,'checkpoint identity'): v.validate_artifacts(record,self.bundle)

    def test_extra_artifact_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); record,_=self.saved_fixture(root)
            self.bundle.storage.write_json(root/'unexpected.json',{})
            with self.assertRaisesRegex(ValueError,'inventory'): v.validate_artifacts(record,self.bundle)

    def test_artifact_hash_mismatch_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            record,_=self.saved_fixture(Path(directory)); record['files']['recipe.json']='0'*64
            with self.assertRaisesRegex(ValueError,'hash'): v.validate_artifacts(record,self.bundle)

    def test_saved_files_never_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); self.saved_fixture(root)
            with self.assertRaises(FileExistsError): self.bundle.storage.write_json(root/'recipe.json',{})

    def test_pending_science_never_certifies_synthetic_envelope(self):
        _,row=self.fixture()
        with patch.object(v,'PRODUCT_CONTRACT_READY',False):
            with self.assertRaisesRegex(ValueError,'pending'): v.validate_products(row,self.bundle,{},self.parent_fixture)


class ProductVerificationTests(unittest.TestCase):
    """Mutations of an actual generated parent and spatial product, not toy PASS rows."""
    @classmethod
    def setUpClass(cls):
        cls.bundle=binding.load(); cls.recipe=cls.bundle.reference.recipe(cls.bundle)
        cls.parent=cls.bundle.parent.run(cls.recipe['parent_recipe'])
        # The parent is genuinely generated once here. The final acceptance worker
        # separately calls the source-bound public full, stop and saved restart API.
        cached=types.SimpleNamespace(storage=cls.bundle.storage,source_sha256=cls.bundle.source_sha256,
            parent=types.SimpleNamespace(source_sha256=cls.bundle.parent.source_sha256,run=lambda recipe:cls.parent))
        cls.full=cls.bundle.pipeline.run(cached,cls.recipe)
        cls.scenario=next(iter(cls.full['environment']['scenarios']))
        cls.unit=cls.full['state']['results'][cls.scenario]['TEST-ANIMAL']['warm']
        cls.spec=cls.recipe['organisms']['TEST-ANIMAL']['seasons']['warm']
        cls.physical=cls.full['environment']['scenarios'][cls.scenario]['seasons']['warm']['cells']

    def test_actual_connected_scientific_gate(self):
        report=v.validate_products(self.full,self.bundle,self.recipe,self.parent)
        self.assertEqual(report['status'],v.VERIFIED_STATUS)
        self.assertFalse(report['all_required_products_complete'])
        self.assertEqual(report['complete_synthetic_engine_organisms'],2)

    def test_actual_seasonal_metrics_recalculated_from_parent(self):
        for name in ('temperature_mean_c','precipitation_m','liquid_water_m'):
            environment=copy.deepcopy(self.full['environment'])
            cell=next(iter(environment['scenarios'][self.scenario]['seasons']['warm']['cells'].values()))
            cell['metrics'][name]['value']+=0.1
            with self.subTest(metric=name),self.assertRaises(ValueError): v.validate_environment(environment,self.parent,self.recipe)

    def test_actual_unknown_physical_metric_is_not_zero(self):
        environment=copy.deepcopy(self.full['environment']); found=False
        for scenario in environment['scenarios'].values():
            for season in scenario['seasons'].values():
                for cell in season['cells'].values():
                    for metric in cell['metrics'].values():
                        if metric['status']=='UNKNOWN':
                            metric.update(status='MODELLED',value=0.,interval=[0.,0.]); found=True; break
                    if found: break
                if found: break
            if found: break
        self.assertTrue(found)
        with self.assertRaises(ValueError): v.validate_environment(environment,self.parent,self.recipe)

    def test_actual_habitat_cannot_substitute_physical_support(self):
        ident=next(iter(self.unit['habitat'])); habitat=copy.deepcopy(self.unit['habitat'][ident])
        habitat['factors'][0]['actual']['value']+=1
        with self.assertRaises(ValueError): v.validate_habitat(habitat,self.physical[ident],self.spec)

    def test_actual_spatial_area_rechecksum_cannot_change_parent_support(self):
        row=copy.deepcopy(self.unit['range_endpoint_cases']['lower_habitat'])
        row['inputs']['cells'][0]['area_m2']=str(v.F(row['inputs']['cells'][0]['area_m2'])+1)
        row['inputs_sha256']=v.sha(v.encoded(row['inputs']))
        with self.assertRaises(ValueError): v.validate_spatial_join(row,self.unit['habitat'],self.physical,self.spec,self.recipe,0)

    def test_actual_logistic_probability_recomputed(self):
        row=copy.deepcopy(self.unit['range_endpoint_cases']['lower_habitat'])
        cell=next(c for c in row['cells'].values() if c['occupancy_probability'] not in (None,0))
        cell['occupancy_probability']+=0.01
        with self.assertRaises(ValueError): v.validate_range(row)

    def test_actual_area_and_abundance_ledgers_recomputed(self):
        for field in ('expected_occupied_area_m2','expected_individuals'):
            row=copy.deepcopy(self.unit['range_endpoint_cases']['lower_habitat'])
            cell=next(c for c in row['cells'].values() if c[field] is not None)
            value=v.amount(cell[field])+1; cell[field]={'exact':str(value),'value':float(value)}
            with self.subTest(field=field),self.assertRaises(ValueError): v.validate_range(row)

    def test_actual_seeded_draw_and_observation_separation(self):
        for key,value in (('draw_uniform_exact','0'),('observed_presence',True)):
            unit=copy.deepcopy(self.unit); next(iter(unit['cells'].values()))[key]=value
            with self.subTest(field=key),self.assertRaises(ValueError): v.validate_draws(unit,self.recipe,'TEST-ANIMAL','warm')

    def movement_fixture(self):
        departure=self.unit['range_endpoint_cases']['lower_habitat']
        arrival=self.full['state']['results'][self.scenario]['TEST-ANIMAL'][self.spec['movement']['destination_season_id']]['range_endpoint_cases']['lower_habitat']
        return copy.deepcopy(self.unit['movement_endpoint_cases']['lower_habitat']),departure,arrival

    def test_actual_movement_stock_cannot_be_created(self):
        row,departure,arrival=self.movement_fixture(); cell=next(iter(row['cells'].values()))
        value=v.amount(cell['final_expected_individuals'])+1
        cell['final_expected_individuals']={'exact':str(value),'value':float(value)}
        with self.assertRaises(ValueError): v.validate_movement(row,departure,arrival,self.spec)

    def test_actual_shared_corridor_capacity_accounting(self):
        row,departure,arrival=self.movement_fixture(); edge=next(iter(row['edges'].values()))
        value=v.amount(edge['used_expected_individuals'])+1
        edge['used_expected_individuals']={'exact':str(value),'value':float(value)}
        with self.assertRaises(ValueError): v.validate_movement(row,departure,arrival,self.spec)

    def test_actual_movement_arrival_context_required(self):
        row,departure,arrival=self.movement_fixture(); row['destination_range_inputs_sha256']=departure['inputs_sha256']
        with self.assertRaises(ValueError): v.validate_movement(row,departure,arrival,self.spec)

    def test_actual_overlap_unknown_denominator_not_absence(self):
        full=copy.deepcopy(self.full)
        cell=next(iter(full['overlap_products'][self.scenario]['warm']['RETAINED']['cells'].values()))
        cell['modelled_absent_taxa']=cell['unknown_or_unexecuted_taxa']; cell['unknown_or_unexecuted_taxa']=0
        with self.assertRaises(ValueError): v.validate_overlap(full,self.recipe)

    def test_actual_synthetic_taxa_excluded_from_real_overlap(self):
        full=copy.deepcopy(self.full)
        full['overlap_products'][self.scenario]['warm']['RETAINED']['eligible_organism_ids'].append('TEST-ANIMAL')
        with self.assertRaises(ValueError): v.validate_overlap(full,self.recipe)

    def test_actual_engine_success_not_full_roster_success(self):
        full=copy.deepcopy(self.full); full['roster_coverage']['all_required_products_complete']=True
        with self.assertRaises(ValueError): v.validate_products(full,self.bundle,self.recipe,self.parent)

    def test_actual_dimensional_density_count_recomputed(self):
        full=copy.deepcopy(self.full)
        model=full['abundance_models']['alternative_scenarios']['DECLARED_DENSITY']['physical_scenarios'][self.scenario]['model']
        row=next(iter(model['cells'].values())); value=v.amount(row['expected_entities'])+1
        row['expected_entities']={'exact':str(value),'value':float(value)}
        with self.assertRaises(ValueError): v.validate_abundance(full,self.recipe,full['biological_owner_contracts'])

    def test_actual_stock_unplaced_not_redistributed(self):
        full=copy.deepcopy(self.full)
        model=full['abundance_models']['alternative_scenarios']['PRESCRIBED_STOCK']['physical_scenarios'][self.scenario]['model']
        model['unplaced_expected_entities']={'exact':'1','value':1.}
        with self.assertRaises(ValueError): v.validate_abundance(full,self.recipe,full['biological_owner_contracts'])

    def test_actual_owner_stock_not_forced_onto_new_terrain(self):
        full=copy.deepcopy(self.full)
        allocation=full['abundance_models']['owner_stock_register']['HS1']['allocation']
        allocation['placed_expected_entities']={'exact':'1','value':1.}
        with self.assertRaises(ValueError): v.validate_abundance(full,self.recipe,full['biological_owner_contracts'])

    def test_actual_cohort_cannot_restart_counts_each_season(self):
        full=copy.deepcopy(self.full)
        endpoint=next(iter(full['seasonal_cohort_chains'].values()))['scenarios'][self.scenario]['lower_habitat']
        endpoint['phases'][1]['result']['declared_departure_stock']['counts'][0][1]='16'
        with self.assertRaises(ValueError): v.validate_cohorts(full,self.recipe)

    def test_actual_cohort_total_not_sum_of_season_maps(self):
        full=copy.deepcopy(self.full)
        endpoint=next(iter(full['seasonal_cohort_chains'].values()))['scenarios'][self.scenario]['lower_habitat']
        endpoint['total_expected_entities']={'exact':'96','value':96.}
        with self.assertRaises(ValueError): v.validate_cohorts(full,self.recipe)

    def test_actual_cohort_resident_arrival_support_not_only_transfer_target(self):
        full=copy.deepcopy(self.full)
        # Warm-to-cold transfer targets upper; eleven residents remain in lower.
        # Conservation alone cannot certify persistence in an excluded arrival cell.
        row=full['state']['results'][self.scenario]['TEST-ANIMAL']['cold']['range_endpoint_cases']['lower_habitat']['cells']['lower']
        row['habitat_status']='FAIL'
        with self.assertRaisesRegex(ValueError,'arrival persistence'): v.validate_cohorts(full,self.recipe)


if __name__=='__main__': unittest.main()
