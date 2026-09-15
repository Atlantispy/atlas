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
        self.assertNotIn('_r10_exact_verification_utilities',sys.modules)

    def test_nested_map_retains_r7_external_validation_sources(self):
        mapping=v.source_map(self.bundle.identity,self.helper)
        retained=self.bundle.identity['retained_source_identity']['retained_source_identity']['retained_source_identity']
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
        records={label:{'work.generator_upgrade_r10.binding':{'path':path,'sha256':digest}} for label in ('r10','r9','r8','r7','r6')}
        with self.assertRaisesRegex(ValueError,'private/actual'):
            v.validate_private_executions(records,{},self.bundle,self.helper)

    def test_private_graph_chain_cannot_be_omitted(self):
        with self.assertRaises(ValueError): v.validate_private_executions({}, {},self.bundle,self.helper)

    def test_private_graph_cannot_mislabel_an_observed_source(self):
        records={}; executed={}
        for label,graph in (('r10',self.bundle.graph),('r9',self.bundle.parent.graph),('r8',self.bundle.parent.parent.graph),('r7',self.bundle.parent.parent.parent.graph),('r6',self.bundle.parent.parent.parent.parent.graph)):
            logical=next(iter(graph.nodes)); path,digest=graph.nodes[logical]
            records[label]={logical:{'path':str(path),'sha256':digest}}; executed[str(path)]=digest
        v.validate_private_executions(records,executed,self.bundle,self.helper)
        records['r10']['work.generator_upgrade_r10.undeclared']=records['r10'].pop(next(iter(records['r10'])))
        with self.assertRaisesRegex(ValueError,'private/actual'):
            v.validate_private_executions(records,executed,self.bundle,self.helper)

    def fixture(self):
        recipe={'schema':'synthetic-verifier-recipe-not-scientific',
            'parent_recipe':{'schema':'synthetic-R9-recipe','parent_recipe':{'input':1}},
            'hydraulic_hypotheses':{'TEST_H':{}}}
        physical={'schema':'diadem.biomes-vegetation-result.r8','source_sha256':self.bundle.parent.parent.source_sha256,
            'recipe_sha256':v.sha(self.bundle.storage.encoded(recipe['parent_recipe']['parent_recipe'])),
            'state':{'members':{'SYNTHETIC':{'a':{},'b':{}}}}}
        physical_sha=v.sha(self.bundle.storage.encoded(physical))
        parent={'schema':'diadem.species-spatial-result.r9','source_sha256':self.bundle.parent.source_sha256,
            'recipe_sha256':v.sha(self.bundle.storage.encoded(recipe['parent_recipe'])),
            'parent_result_sha256':physical_sha}
        parent_sha=v.sha(self.bundle.storage.encoded(parent))
        row={'schema':v.RESULT_SCHEMA,'source_sha256':self.bundle.source_sha256,
            'recipe_sha256':v.sha(self.bundle.storage.encoded(recipe)),
            'parent_result_sha256':parent_sha,'physical_parent_result_sha256':physical_sha,
            'state':{'completed_units':2,'parent_result_sha256':parent_sha,'physical_parent_result_sha256':physical_sha,
                'results':{'SYNTHETIC/TEST_H/a':{},'SYNTHETIC/TEST_H/b':{}}}}
        self.parent_fixture=parent; self.physical_fixture=physical
        return recipe,row

    def test_envelope_complete_and_stop_cursor(self):
        recipe,row=self.fixture()
        self.assertEqual(len(v.validate_envelope(row,recipe,self.bundle,self.parent_fixture,self.physical_fixture,complete=True)),2)
        row['state']['completed_units']=1; del row['state']['results']['SYNTHETIC/TEST_H/b']
        self.assertEqual(len(v.validate_envelope(row,recipe,self.bundle,self.parent_fixture,self.physical_fixture,complete=False)),1)

    def test_envelope_boolean_cursor_rejected(self):
        recipe,row=self.fixture(); row['state']['completed_units']=True
        with self.assertRaises(ValueError): v.validate_envelope(row,recipe,self.bundle,self.parent_fixture,self.physical_fixture,complete=False)

    def test_envelope_source_recipe_and_parent_join_rejected(self):
        for key in ('source_sha256','recipe_sha256'):
            recipe,row=self.fixture(); row[key]='0'*64
            with self.subTest(key=key),self.assertRaises(ValueError): v.validate_envelope(row,recipe,self.bundle,self.parent_fixture,self.physical_fixture,complete=True)
        for key in ('parent_result_sha256','physical_parent_result_sha256'):
            recipe,row=self.fixture(); row['state'][key]='0'*64
            with self.subTest(key=key),self.assertRaises(ValueError): v.validate_envelope(row,recipe,self.bundle,self.parent_fixture,self.physical_fixture,complete=True)

    def test_envelope_malformed_organism_map_rejected(self):
        recipe,row=self.fixture(); row['state']['results']=[]
        with self.assertRaises(ValueError): v.validate_envelope(row,recipe,self.bundle,self.parent_fixture,self.physical_fixture,complete=True)

    def test_envelope_extra_state_rejected(self):
        recipe,row=self.fixture(); row['state']['pretend_water']={}
        with self.assertRaises(ValueError): v.validate_envelope(row,recipe,self.bundle,self.parent_fixture,self.physical_fixture,complete=True)

    def test_separate_parent_result_hash_rejected(self):
        recipe,row=self.fixture(); row['parent_result_sha256']='0'*64
        with self.assertRaises(ValueError): v.validate_envelope(row,recipe,self.bundle,self.parent_fixture,self.physical_fixture,complete=True)

    def test_separate_physical_parent_is_not_a_different_source(self):
        recipe,row=self.fixture(); self.physical_fixture['source_sha256']='0'*64
        with self.assertRaises(ValueError): v.validate_envelope(row,recipe,self.bundle,self.parent_fixture,self.physical_fixture,complete=True)

    def test_rechecksummed_physical_parent_still_must_match_r9(self):
        recipe,row=self.fixture(); self.physical_fixture['state']['members']['SYNTHETIC']['a']['forged']=True
        digest=v.sha(self.bundle.storage.encoded(self.physical_fixture))
        row['physical_parent_result_sha256']=digest; row['state']['physical_parent_result_sha256']=digest
        with self.assertRaises(ValueError): v.validate_envelope(row,recipe,self.bundle,self.parent_fixture,self.physical_fixture,complete=True)

    def test_whole_year_units_cannot_alias_hydraulic_hypotheses(self):
        recipe,row=self.fixture(); state=row['state']['results']
        state['SYNTHETIC/OTHER_H/b']=state.pop('SYNTHETIC/TEST_H/b')
        with self.assertRaises(ValueError): v.validate_envelope(row,recipe,self.bundle,self.parent_fixture,self.physical_fixture,complete=True)

    def saved_fixture(self,root):
        recipe,full=self.fixture(); stop=copy.deepcopy(full)
        stop['state']['completed_units']=1; del stop['state']['results']['SYNTHETIC/TEST_H/b']
        values={'recipe.json':recipe,'parent-result.json':self.parent_fixture,'physical-parent-result.json':self.physical_fixture,'full-result.json':full,'restart-result.json':full,'stop-result.json':stop,
            'full-checkpoint.json':self.bundle.checkpoint(full),'restart-checkpoint.json':self.bundle.checkpoint(full),
            'stop-checkpoint.json':self.bundle.checkpoint(stop)}
        for name,value in values.items(): self.bundle.storage.write_json(root/name,value)
        return {'path':str(root),'files':{name:v.sha((root/name).read_bytes()) for name in values},
            'reference_sha256':v.sha(self.bundle.storage.encoded(full)),
            'parent_result_sha256':v.sha(self.bundle.storage.encoded(self.parent_fixture)),
            'physical_parent_result_sha256':v.sha(self.bundle.storage.encoded(self.physical_fixture)),'scientific_checks':{'fixture':'NOT_SCIENTIFIC'}},values

    def test_nine_saved_artifacts_exact_readback(self):
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

    def test_failed_scientific_full_is_saved_before_any_restart_attempt(self):
        # Synthetic envelope tests only the failure-preservation workflow.
        recipe,full=self.fixture(); calls=[]
        def run(value,**kw): calls.append((value,kw)); return full
        fake=types.SimpleNamespace(storage=self.bundle.storage,run=run,checkpoint=self.bundle.checkpoint,
            reference=types.SimpleNamespace(recipe=lambda _:recipe),
            parent=types.SimpleNamespace(run=lambda _:self.parent_fixture,
                parent=types.SimpleNamespace(run=lambda _:self.physical_fixture)))
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)/'failed-attempt'
            with patch.object(v,'validate_products',side_effect=ValueError('incomplete hydraulic year')):
                with self.assertRaisesRegex(ValueError,'incomplete hydraulic year'): v.artifacts(fake,root)
            self.assertEqual(calls,[(recipe,{})])
            self.assertEqual({p.name for p in root.iterdir()},
                {'recipe.json','parent-result.json','physical-parent-result.json','full-result.json','full-checkpoint.json'})
            self.assertEqual(self.bundle.storage.read_json(root/'full-result.json'),full)

    def test_pending_science_never_certifies_synthetic_envelope(self):
        _,row=self.fixture()
        with patch.object(v,'PRODUCT_CONTRACT_READY',False):
            with self.assertRaisesRegex(ValueError,'pending'): v.validate_products(row,self.bundle,{},self.parent_fixture,self.physical_fixture)


class HydraulicProductVerificationTests(unittest.TestCase):
    """Mutations of actual R6 seasonal integration results, not synthetic PASS dictionaries."""
    @classmethod
    def setUpClass(cls):
        from . import test_hydraulics as cases
        cls.product=cases.run(ev=cases.events(demand=cases.F(1,1000000),root=cases.uptake()))

    def test_actual_twelve_interval_water_accounting(self):
        report=v.validate_hydraulic_year(self.product)
        self.assertEqual(report['events'],12); self.assertEqual(report['months'],12)
        self.assertFalse(report['periodic_hydraulic_state_claim']); self.assertFalse(report['soil_freezing_modelled'])

    def test_retained_fixture_explicitly_identifies_original_numerical_execution(self):
        record=v.validate_numerical_binding(self.product)
        self.assertEqual(record['implementation'],'R6_RETAINED_NUMERICAL_EXECUTION')
        self.assertIsNone(record['adapter'])

    def test_shared_result_schema_cannot_supply_missing_numerical_identity(self):
        row=copy.deepcopy(self.product); row['inputs'].pop('numerical_binding')
        with self.assertRaisesRegex(ValueError,'numerical implementation binding'):
            v.validate_numerical_binding(row)

    def test_original_fixture_cannot_certify_successor_numerical_execution(self):
        row=copy.deepcopy(self.product['inputs']['numerical_binding'])
        row['implementation']='R10_SATURATION_BRANCH_RESOLUTION'
        with self.assertRaisesRegex(ValueError,'source-bound successor'):
            v.validate_numerical_binding(self.product,row)

    def test_retained_event_cannot_be_relabelled_as_successor(self):
        row=copy.deepcopy(self.product)
        row['events'][0]['solver_result']['numerical_implementation']='R10_SATURATION_BRANCH_RESOLUTION'
        with self.assertRaisesRegex(ValueError,'relabelled'):
            v.validate_numerical_binding(row)

    def test_numerical_kernel_binding_must_match_expected_source(self):
        row=copy.deepcopy(self.product); expected=copy.deepcopy(row['inputs']['numerical_binding'])
        row['inputs']['numerical_binding']['retained_hydraulic_kernel']['sha256']='0'*64
        with self.assertRaisesRegex(ValueError,'source-bound successor'):
            v.validate_numerical_binding(row,expected)

    def test_successor_labels_without_actual_per_event_identity_rejected(self):
        # An adversarial metadata mutation, never a claim that this R6 fixture ran R10.
        row=copy.deepcopy(self.product); record=row['inputs']['numerical_binding']
        record.update(implementation='R10_SATURATION_BRANCH_RESOLUTION',
            adapter={'path':str(v.HERE/'richards_numerics.py'),'sha256':'a'*64})
        with self.assertRaisesRegex(ValueError,'event numerical execution'):
            v.validate_numerical_binding(row)

    def test_event_calendar_duration_cannot_be_relabelled(self):
        row=copy.deepcopy(self.product); row['events'][1]['duration_seconds']='2'
        with self.assertRaises(ValueError): v.validate_hydraulic_year(row)

    def test_cumulative_calendar_cannot_reset(self):
        row=copy.deepcopy(self.product); row['events'][1]['solver_result']['state']['elapsed_seconds']=1.
        with self.assertRaises(ValueError): v.validate_hydraulic_year(row)

    def test_actual_layer_water_content_not_a_score(self):
        row=copy.deepcopy(self.product); row['events'][0]['solver_result']['layers'][0]['theta_m3_m3']+=0.01
        with self.assertRaises(ValueError): v.validate_hydraulic_year(row)

    def test_signed_pore_pressure_retains_suction(self):
        row=copy.deepcopy(self.product); layer=row['events'][0]['solver_result']['layers'][0]
        layer['signed_pore_pressure_pa']=abs(layer['signed_pore_pressure_pa'])
        with self.assertRaises(ValueError): v.validate_hydraulic_year(row)

    def test_root_gross_flux_must_use_actual_physical_face(self):
        row=copy.deepcopy(self.product); row['events'][0]['solver_result']['ledger']['root_zone_upward_capillary_m']=1.
        with self.assertRaises(ValueError): v.validate_hydraulic_year(row)

    def test_monthly_flux_is_not_last_event_or_annual_flux(self):
        row=copy.deepcopy(self.product); row['months']['1']['ledger_m']['actual_et_m']=row['annual']['ledger_m']['actual_et_m']
        with self.assertRaises(ValueError): v.validate_hydraulic_year(row)

    def test_month_end_layers_cannot_include_last_event_uptake_as_state(self):
        row=copy.deepcopy(self.product); row['months']['1']['end_layers'][0]['et_m']=0.
        with self.assertRaises(ValueError): v.validate_hydraulic_year(row)

    def test_accumulated_annual_stock_ledger_cannot_create_water(self):
        row=copy.deepcopy(self.product); row['annual']['ledger_m']['final_storage_m']='1'
        with self.assertRaises(ValueError): v.validate_hydraulic_year(row)

    def test_unknown_year_cannot_keep_a_final_state(self):
        row=copy.deepcopy(self.product); row.update(status='UNKNOWN',partial_results_only=True)
        with self.assertRaises(ValueError): v.validate_hydraulic_year(row)


class InternalClockVerificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from . import test_hydraulics as cases, richards_numerics as numerical
        cls.product=cases.run(numerical_solver=numerical.Adapter(cases.w))

    def changed(self):
        return copy.deepcopy(self.product['events'][0]['solver_result'])

    def test_actual_adapter_partitions_every_short_forcing_interval_exactly(self):
        checks=v.validate_hydraulic_year(self.product)['internal_clock_checks']
        self.assertEqual(checks['exactly_partitioned_complete_events'],12)
        self.assertEqual(checks['retained_r6_events_without_exact_internal_receipts'],0)
        self.assertGreater(checks['accepted_steps_in_exact_partitions'],12)

    def test_step_exact_duration_is_binary64_value_not_a_relabelled_decimal(self):
        row=self.changed(); row['numerics']['accepted_steps_detail'][0]['dt_seconds_exact']='1/10'
        with self.assertRaisesRegex(ValueError,'binary64 duration'): v.validate_internal_clock(row)

    def test_exact_cumulative_step_endpoint_cannot_reset(self):
        row=self.changed(); steps=row['numerics']['accepted_steps_detail']
        steps[1]['end_seconds_exact']=steps[0]['end_seconds_exact']
        with self.assertRaisesRegex(ValueError,'exact internal clock'): v.validate_internal_clock(row)

    def test_exact_final_forcing_support_cannot_be_shortened(self):
        row=self.changed(); n=row['numerics']; n['accepted_steps_detail'].pop(); n['accepted_steps']-=1
        n['elapsed_seconds_exact']=n['accepted_steps_detail'][-1]['end_seconds_exact']
        with self.assertRaisesRegex(ValueError,'exactly fill'): v.validate_internal_clock(row)

    def test_internally_consistent_last_step_still_cannot_overrun_forcing(self):
        row=self.changed(); step=row['numerics']['accepted_steps_detail'][-1]
        step['dt_seconds']+=1.; step['dt_seconds_exact']=str(v.F(step['dt_seconds']))
        step['end_seconds']+=1.; step['end_seconds_exact']=str(v.F(step['end_seconds_exact'])+1)
        with self.assertRaisesRegex(ValueError,'overrun'): v.validate_internal_clock(row)

    def test_rounded_endpoint_must_match_its_exact_sum(self):
        row=self.changed(); row['numerics']['accepted_steps_detail'][0]['end_seconds']+=.1
        with self.assertRaisesRegex(ValueError,'display mismatch'): v.validate_internal_clock(row)

    def test_forcing_exact_receipt_cannot_change_actual_forcing(self):
        row=self.changed(); row['numerics']['forcing_duration_seconds_exact']='2'
        with self.assertRaisesRegex(ValueError,'supplied binary64 interval'): v.validate_internal_clock(row)

    def test_elapsed_receipt_must_equal_actual_step_sum(self):
        row=self.changed(); row['numerics']['elapsed_seconds_exact']='0'
        with self.assertRaisesRegex(ValueError,'exactly fill'): v.validate_internal_clock(row)

    def test_repeated_rounded_endpoints_do_not_erase_sub_ulp_exact_steps(self):
        # A clock-only partition oracle, not a fabricated physical solver result.
        steps=[]; clock=v.F()
        for dt in (1.,2.**-54,2.**-54,1.-2.**-53):
            clock+=v.F(dt)
            steps.append({'dt_seconds':dt,'dt_seconds_exact':str(v.F(dt)),
                'end_seconds':float(clock),'end_seconds_exact':str(clock)})
        row={'numerical_implementation':'R10_SATURATION_BRANCH_RESOLUTION','status':'MODELLED',
            'forcing':{'duration_seconds':2.},'numerics':{'accepted_steps':4,'accepted_steps_detail':steps,
                'elapsed_seconds_exact':'2','forcing_duration_seconds_exact':'2'}}
        self.assertEqual(steps[0]['end_seconds'],steps[1]['end_seconds'])
        self.assertNotEqual(steps[0]['end_seconds_exact'],steps[1]['end_seconds_exact'])
        self.assertEqual(v.validate_internal_clock(row)['accepted_steps'],4)

    def test_boolean_accepted_step_count_is_not_an_exact_inventory(self):
        row=self.changed(); row['numerics']['accepted_steps']=True
        with self.assertRaisesRegex(ValueError,'inventory'): v.validate_internal_clock(row)

    def test_unknown_numerical_label_cannot_fall_back_to_retained_clock_semantics(self):
        row=self.changed(); row['numerical_implementation']='UNREVIEWED_SOLVER'
        with self.assertRaisesRegex(ValueError,'unknown numerical implementation'): v.validate_internal_clock(row)


class ClimateProductVerificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from . import climate
        cls.bundle=binding.load(); parent=cls.bundle.parent.parent
        cls.physical=parent.run(parent.reference.recipe(parent))
        cls.product=climate.project(cls.physical,parent.source_sha256)

    def changed(self):
        row=copy.deepcopy(self.product); member=next(iter(row['members'].values()))
        return row,next(iter(member['cells'].values()))

    def test_actual_representative_climate_and_liquid_chronology(self):
        report=v.validate_climate(self.product,self.physical)
        self.assertEqual(report['actual_months'],72)
        self.assertEqual(report['duration_seconds'],str(sum((v.F(self.product['calendar']['day_seconds'])*d for d in self.product['calendar']['month_days']),v.F())))

    def test_month_count_is_not_duration_weighting(self):
        row,cell=self.changed(); annual=cell['annual']
        self.assertNotEqual(annual['duration_weighted_temperature_c'],annual['arithmetic_mean_of_monthly_means_temperature_c'])
        annual['duration_weighted_temperature_c']=annual['arithmetic_mean_of_monthly_means_temperature_c']
        with self.assertRaises(ValueError): v.validate_climate(row,self.physical)

    def test_wind_direction_must_follow_actual_vector(self):
        row,cell=self.changed(); air=cell['months'][0]['air']; air['wind_from_degrees']=(air['wind_from_degrees']+90)%360
        with self.assertRaises(ValueError): v.validate_climate(row,self.physical)

    def test_monthly_rain_snow_precipitation_cannot_create_water(self):
        row,cell=self.changed(); quantity=cell['months'][0]['precipitation_m']; value=v.quantity(quantity)+1
        quantity.update(exact=str(value),value=float(value))
        with self.assertRaises(ValueError): v.validate_climate(row,self.physical)

    def test_snow_liquid_cannot_be_counted_twice(self):
        row,cell=self.changed(); quantity=cell['events'][0]['exact_snow_liquid_m']; value=v.quantity(quantity)+1
        quantity.update(exact=str(value),value=float(value))
        with self.assertRaises(ValueError): v.validate_climate(row,self.physical)

    def test_air_temperature_does_not_supply_soil_freeze_state(self):
        row,cell=self.changed(); cell['months'][0]['soil_freeze_fraction']=0.
        with self.assertRaises(ValueError): v.validate_climate(row,self.physical)

    def test_circular_monthly_drought_length_recomputed(self):
        row,cell=self.changed(); cell['monthly_climatic_support']['longest_circular_strongly_dry_run_months']+=1
        with self.assertRaises(ValueError): v.validate_climate(row,self.physical)


class PlantProductVerificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from . import test_plants as cases
        cases.PlantTests.setUpClass(); cls.cases=cases.PlantTests()
        cls.actual=cls.cases.actual(active=[True]+[False]*10+[True],split=True,ecological_fail=True)
        cls.product=cls.cases.project(cls.actual)
        cls.roster=cls.cases.bundle.parent.graph.load('work.generator_upgrade_r9.owner_inputs').biological_roster()
        cls.species=cases.p.species_phenology(cls.roster)

    def check(self,row):
        return v.validate_plant_activity(row,self.actual,'actual-test-R8-PFT')

    def test_actual_conditional_activity_does_not_override_ecological_failure(self):
        report=self.check(self.product)
        self.assertEqual(report['ecological_admissibility'],'FAIL')
        self.assertEqual(report['active_duration_seconds'],'62')

    def test_pft_source_payload_cannot_be_relabelled(self):
        row=copy.deepcopy(self.product); row['source']['pft_payload_sha256']='0'*64
        with self.assertRaises(ValueError): self.check(row)

    def test_activity_is_duration_not_unconditional_growth(self):
        row=copy.deepcopy(self.product); row['months'][1]['physiological_active_fraction']=1.
        with self.assertRaises(ValueError): self.check(row)

    def test_available_water_stock_bracket_must_match_actual_trajectory(self):
        row=copy.deepcopy(self.product); row['months'][0]['available_water']['final_storage_m']['upper']+=1.
        with self.assertRaises(ValueError): self.check(row)

    def test_month_flux_cannot_be_copied_from_another_month(self):
        row=copy.deepcopy(self.product); row['months'][1]['available_water']['actual_transpiration_m']={'lower':1.,'upper':1.}
        with self.assertRaises(ValueError): self.check(row)

    def test_cyclic_wrap_drought_is_retained_not_reconstructed_from_month_flags(self):
        row=copy.deepcopy(self.product); row['cyclic_drought']['longest_cyclic_dry_active_spell_s']['lower']=31.
        with self.assertRaises(ValueError): self.check(row)

    def test_species_phenology_remains_unknown_for_seventeen_source_bound_plants(self):
        self.assertEqual(v.validate_species_phenology(self.species,self.roster)['owner_bound_plants'],17)

    def test_unknown_owner_flowering_cannot_be_fabricated_as_zero(self):
        row=copy.deepcopy(self.species); next(iter(row['plants'].values()))['flowering_windows']=[]
        with self.assertRaises(ValueError): v.validate_species_phenology(row,self.roster)


class CarbonProductVerificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from . import test_seasonal_carbon as cases
        cases.SeasonalCarbonTests.setUpClass(); cls.cases=cases.SeasonalCarbonTests()
        cls.product=cls.cases.run_case()

    def test_actual_retained_pools_carbon_and_dry_origin_close(self):
        result=v.validate_carbon_year(self.product)
        self.assertEqual(result['completed_months'],12)
        self.assertEqual(result['geometry_feedback'],'NOT_APPLIED_DIAGNOSTIC_ONLY')

    def test_litter_input_cannot_be_replaced_by_dry_matter(self):
        row=copy.deepcopy(self.product); row['events'][0]['producer_result']['carbon']['input_kg_m2']='1'
        with self.assertRaises(ValueError): v.validate_carbon_year(row)

    def test_dry_origin_export_must_use_explicit_carbon_fraction(self):
        row=copy.deepcopy(self.product); row['events'][0]['producer_result']['organic_dry_matter']['decomposed_dry_matter_origin_kg_m2']='0'
        with self.assertRaises(ValueError): v.validate_carbon_year(row)

    def test_event_carbon_stocks_cannot_reset(self):
        row=copy.deepcopy(self.product); row['events'][1]['initial_state']=row['events'][0]['initial_state']
        with self.assertRaises(ValueError): v.validate_carbon_year(row)

    def test_annual_carbon_export_is_sum_not_final_event_only(self):
        row=copy.deepcopy(self.product); row['annual']['carbon_kg_m2']['exported_carbon_origin']=row['events'][-1]['producer_result']['carbon']['exported_atmospheric_carbon_kg_m2']
        with self.assertRaises(ValueError): v.validate_carbon_year(row)

    def test_carbon_checkpoint_prefix_must_match_actual_events(self):
        row=copy.deepcopy(self.product); cp=row['checkpoint']; cp['accepted_prefix_sha256']='0'*64
        cp['checkpoint_sha256']=v.sha(v.encoded({k:x for k,x in cp.items() if k!='checkpoint_sha256'}))
        with self.assertRaises(ValueError): v.validate_carbon_year(row)

    def test_partial_carbon_preserves_prefix_without_annual_state(self):
        row=self.cases.run_case(stop_after=5)
        self.assertEqual(v.validate_carbon_year(row)['status'],'STOPPED')

    def test_missing_soil_temperature_remains_unknown_not_air_substitution(self):
        row=self.cases.run_case(events=self.cases.events(soil_temperature_k=None))
        self.assertEqual(v.validate_carbon_year(row)['status'],'UNKNOWN')


if __name__=='__main__': unittest.main()
