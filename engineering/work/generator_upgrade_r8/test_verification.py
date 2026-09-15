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
        retained=self.bundle.identity['retained_source_identity']
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
        records={label:{'work.generator_upgrade_r8.binding':{'path':path,'sha256':digest}} for label in ('r8','r7','r6')}
        with self.assertRaisesRegex(ValueError,'private/actual'):
            v.validate_private_executions(records,{},self.bundle,self.helper)

    def test_private_graph_chain_cannot_be_omitted(self):
        with self.assertRaises(ValueError): v.validate_private_executions({}, {},self.bundle,self.helper)

    def test_private_graph_cannot_mislabel_an_observed_source(self):
        records={}; executed={}
        for label,graph in (('r8',self.bundle.graph),('r7',self.bundle.parent.graph),('r6',self.bundle.parent.parent.graph)):
            logical=next(iter(graph.nodes)); path,digest=graph.nodes[logical]
            records[label]={logical:{'path':str(path),'sha256':digest}}; executed[str(path)]=digest
        v.validate_private_executions(records,executed,self.bundle,self.helper)
        records['r8']['work.generator_upgrade_r8.undeclared']=records['r8'].pop(next(iter(records['r8'])))
        with self.assertRaisesRegex(ValueError,'private/actual'):
            v.validate_private_executions(records,executed,self.bundle,self.helper)

    def fixture(self):
        recipe={'schema':'synthetic-verifier-recipe-not-scientific','input':1}
        soil={'schema':'diadem.soil-formation-result.r7','source_sha256':self.bundle.parent.source_sha256,
            'state':{'members':{'SYNTHETIC':{'a':{},'b':{}}}}}
        seasonal={'status':'SYNTHETIC_VERIFIER_ENVELOPE_ONLY'}
        row={'schema':v.RESULT_SCHEMA,'source_sha256':self.bundle.source_sha256,
            'recipe_sha256':v.sha(self.bundle.storage.encoded(recipe)), 'soil_result':soil,'seasonal':seasonal,
            'state':{'completed_cells':2,'soil_result_sha256':v.sha(self.bundle.storage.encoded(soil)),
                'seasonal_sha256':v.sha(self.bundle.storage.encoded(seasonal)),
                'members':{'SYNTHETIC':{'a':{},'b':{}}}}}
        return recipe,row

    def test_envelope_complete_and_stop_cursor(self):
        recipe,row=self.fixture()
        self.assertEqual(v.validate_envelope(row,recipe,self.bundle,complete=True),2)
        row['state']['completed_cells']=1; del row['state']['members']['SYNTHETIC']['b']
        self.assertEqual(v.validate_envelope(row,recipe,self.bundle,complete=False),2)

    def test_envelope_boolean_cursor_rejected(self):
        recipe,row=self.fixture(); row['state']['completed_cells']=True
        with self.assertRaises(ValueError): v.validate_envelope(row,recipe,self.bundle,complete=False)

    def test_envelope_source_recipe_and_parent_join_rejected(self):
        for key in ('source_sha256','recipe_sha256'):
            recipe,row=self.fixture(); row[key]='0'*64
            with self.subTest(key=key),self.assertRaises(ValueError): v.validate_envelope(row,recipe,self.bundle,complete=True)
        for key in ('soil_result_sha256','seasonal_sha256'):
            recipe,row=self.fixture(); row['state'][key]='0'*64
            with self.subTest(key=key),self.assertRaises(ValueError): v.validate_envelope(row,recipe,self.bundle,complete=True)

    def test_envelope_unknown_cell_rejected(self):
        recipe,row=self.fixture(); row['state']['members']['SYNTHETIC']['c']=row['state']['members']['SYNTHETIC'].pop('b')
        with self.assertRaises(ValueError): v.validate_envelope(row,recipe,self.bundle,complete=True)

    def test_envelope_extra_state_rejected(self):
        recipe,row=self.fixture(); row['state']['pretend_water']={}
        with self.assertRaises(ValueError): v.validate_envelope(row,recipe,self.bundle,complete=True)

    def test_envelope_extra_empty_scenario_rejected(self):
        recipe,row=self.fixture(); row['state']['members']['invented']={}
        with self.assertRaisesRegex(ValueError,'scenario inventory'):
            v.validate_envelope(row,recipe,self.bundle,complete=True)

    def saved_fixture(self,root):
        recipe,full=self.fixture(); stop=copy.deepcopy(full)
        stop['state']['completed_cells']=1; del stop['state']['members']['SYNTHETIC']['b']
        values={'recipe.json':recipe,'full-result.json':full,'restart-result.json':full,'stop-result.json':stop,
            'full-checkpoint.json':self.bundle.checkpoint(full),'restart-checkpoint.json':self.bundle.checkpoint(full),
            'stop-checkpoint.json':self.bundle.checkpoint(stop)}
        for name,value in values.items(): self.bundle.storage.write_json(root/name,value)
        return {'path':str(root),'files':{name:v.sha((root/name).read_bytes()) for name in values},
            'reference_sha256':v.sha(self.bundle.storage.encoded(full)),'scientific_checks':{'fixture':'NOT_SCIENTIFIC'}},values

    def test_seven_saved_artifacts_exact_readback(self):
        with tempfile.TemporaryDirectory() as directory,patch.object(v,'validate_products',return_value={'fixture':'NOT_SCIENTIFIC'}):
            record,values=self.saved_fixture(Path(directory))
            self.assertEqual(v.validate_artifacts(record,self.bundle),values['full-result.json'])

    def test_forged_checkpoint_rechecksum_does_not_match_result(self):
        with tempfile.TemporaryDirectory() as directory,patch.object(v,'validate_products',return_value={'fixture':'NOT_SCIENTIFIC'}):
            root=Path(directory); record,values=self.saved_fixture(root)
            forged=copy.deepcopy(values['stop-checkpoint.json']); forged['state']['completed_cells']=99
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
            with self.assertRaisesRegex(ValueError,'pending'): v.validate_products(row,self.bundle)


class ScientificVerificationTests(unittest.TestCase):
    """Mutate genuine successful products; reuse the connected suite fixture."""
    @classmethod
    def setUpClass(cls):
        from . import test_pipeline
        owner=test_pipeline.ConnectedTests
        if not hasattr(owner,'full'): owner.setUpClass()
        cls.bundle=owner.b; cls.recipe=owner.r; cls.full=owner.full
        cls.member=owner.member; cls.cell_id=owner.cell_id; cls.row=owner.cell
        cls.soil=owner.soil['state']['members'][cls.member][cls.cell_id]
        cls.cycle=owner.exposure['members'][cls.member]['cells'][cls.cell_id]
        cls.family=sorted(cls.row['pft_results'])[0]; cls.ident=sorted(cls.recipe['pfts'])[0]
        cls.proof=v.validate_products(cls.full,cls.bundle,cls.recipe)

    def capacity_check(self,capacity):
        return v.validate_capacity(capacity,self.soil,self.recipe['pfts'][self.ident]['rooting'],self.row['soil_support_id'])

    def snow_check(self,cycle):
        return v.validate_snow(cycle,self.recipe['seasonal']['calendar'],self.member,self.cell_id,
            self.full['seasonal']['binding_sha256'],atol=self.recipe['seasonal']['snow_atol_m'])

    def pft_check(self,result):
        return v.validate_pft_water(result,self.row['capacities'][self.ident],self.cycle,self.recipe['pfts'][self.ident],
            self.recipe['family_demand_multipliers'][self.family],self.recipe['seasonal']['calendar'],
            self.row['soil_support_id'],self.family)

    def test_actual_complete_physical_reference(self):
        self.assertEqual((self.proof['cell_count'],self.proof['pft_experiment_count'],self.proof['actual_climate_calls']),(6,108,72))

    def test_unknown_capacity_is_not_zero(self):
        unknown={'status':'UNKNOWN','capacity_m':None,'rooted_depth_m':None}
        self.assertFalse(self.capacity_check(unknown))
        unknown['capacity_m']=0
        with self.assertRaises(ValueError): self.capacity_check(unknown)

    def test_forged_layer_available_water_rejected(self):
        altered=copy.deepcopy(self.row['capacities'][self.ident]); altered['layers'][0]['available_water_m']='123'
        with self.assertRaises(ValueError): self.capacity_check(altered)

    def test_forged_rooted_geometry_rejected(self):
        altered=copy.deepcopy(self.row['capacities'][self.ident]); altered['geometry_sha256']='0'*64
        with self.assertRaises(ValueError): self.capacity_check(altered)

    def test_unknown_snow_cannot_supply_events(self):
        self.assertIsNone(self.snow_check({'status':'UNKNOWN','events':None}))
        with self.assertRaises(ValueError): self.snow_check({'status':'UNKNOWN','events':[]})

    def test_forged_snow_stock_rejected(self):
        altered=copy.deepcopy(self.cycle); altered['months'][0]['snow']['ledger']['final_swe_m']='999'
        with self.assertRaises(ValueError): self.snow_check(altered)

    def test_repeated_snow_time_rejected(self):
        altered=copy.deepcopy(self.cycle); altered['months'][1]['snow']['forcing']['start_seconds']='0'
        with self.assertRaises(ValueError): self.snow_check(altered)

    def test_dropped_melt_event_rejected(self):
        altered=copy.deepcopy(self.cycle); altered['events'].pop(0)
        with self.assertRaises(ValueError): self.snow_check(altered)

    def test_wrong_pft_water_source_rejected(self):
        altered=copy.deepcopy(self.row['pft_results'][self.family][self.ident])
        altered['source_binding']['seasonal_cycle_sha256']='0'*64
        with self.assertRaises(ValueError): self.pft_check(altered)

    def test_double_counted_melt_input_rejected(self):
        altered=copy.deepcopy(self.row['pft_results'][self.family][self.ident])
        altered['inputs']['events'][0]['liquid_input_m_s']+=1
        with self.assertRaises(ValueError): self.pft_check(altered)

    def test_forged_actual_uptake_rejected(self):
        altered=copy.deepcopy(self.row['pft_results'][self.family][self.ident])
        altered['water']['lower']['events'][0]['actual_transpiration_m']+=1
        with self.assertRaises(ValueError): self.pft_check(altered)

    def test_forged_periodic_metric_rejected(self):
        altered=copy.deepcopy(self.row['pft_results'][self.family][self.ident])
        altered['metrics']['active_actual_to_potential_transpiration_ratio']=100
        with self.assertRaises(ValueError): self.pft_check(altered)

    def test_classifier_cannot_replace_actual_pft_metric(self):
        altered=copy.deepcopy(self.row)
        record=next(p for family in altered['classification']['family_records'] for p in family['pfts'].values() if p['status']=='ADMISSIBLE')
        record['actual_value']+=0.1
        with self.assertRaises(ValueError): v.validate_classification(altered,self.recipe,self.bundle.pipeline.biomes)

    def test_classifier_geometric_consensus_not_arbitrary_score(self):
        altered=copy.deepcopy(self.row); altered['classification']['broad_consensus_support']['1']=999
        with self.assertRaises(ValueError): v.validate_classification(altered,self.recipe,self.bundle.pipeline.biomes)

    def test_classification_must_retain_structural_uncertainty(self):
        altered=copy.deepcopy(self.row); altered['classification']['uncertainty']=[]
        with self.assertRaises(ValueError): v.validate_classification(altered,self.recipe,self.bundle.pipeline.biomes)


if __name__=='__main__': unittest.main()
