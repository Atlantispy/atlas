"""Isolated recipe/recovery regressions; no production or frozen-source writes."""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import sys
import unittest
from unittest.mock import patch

import shoreline_workflow as w


def recipe():
    return {'schema':'diadem.terrain.shoreline.recipe.r6','purpose':'SYNTHETIC_ENGINEERING_ONLY',
        'scenario_id':'native_two_cell_basin','source_label':'SYNTHETIC workflow verification',
        'state':{'shape':[1,2],'cell_area_m2':[1.,1.],'bedrock_m':[0.,2.],
                 'bed_solid_m3':[0.,0.],'liquid_m3':[0.,0.],'suspended_solid_m3':[0.,0.]},
        'forcing':{'steps':3,'dt_years':.125,'dx_m':1.,'dy_m':1.,'external_outlets':[],
                   'connectivity':4,'runoff_m_year':[1.,0.],'sediment_k_per_year':[0.,0.],
                   'rock_k_per_year':[0.,0.],'cover_scale_m':1.,'settling_m_year':0.,
                   'basin_settling_m_year':0.,'diffusivity_m2_year':[0.,0.],
                   'incoming_liquid_m3_year':[0.,0.],'incoming_solid_m3_year':[0.,0.],
                   'critical_gradient':None,'erosion_reference_runoff_m_year':None},
        'limits':{'wall_seconds':120,'max_product_bytes':8*1024*1024},'constraints':[],
        'physical_acceptance':False,'production_authorised':False}


def endpoint_recipe():
    r=recipe();r['scenario_id']='forced_exact_half_year_endpoint'
    r['state'].update(shape=[1,3],cell_area_m2=[1.]*3,bedrock_m=[.984375,0.,1.],
        bed_solid_m3=[0.]*3,liquid_m3=[.01171875,.75,0.],suspended_solid_m3=[.00390625,.25,0.])
    r['forcing'].update(steps=1,dt_years=.5,external_outlets=[2],basin_settling_m_year=.125)
    for name in w.VECTOR_FIELDS:r['forcing'][name]=[0.]*3
    r['forcing'].update(incoming_liquid_m3_year=[.328125,0.,0.],incoming_solid_m3_year=[.171875,0.,0.])
    return r


class RecipeTests(unittest.TestCase):
    def test_general_native_recipe_is_valid_without_execution_or_mutation(self):
        r=recipe();before=deepcopy(r)
        with patch.object(w.driver,'advance',side_effect=AssertionError('validation must not generate')):
            state=w.validate(r)
        self.assertEqual(state.size,2);self.assertEqual(r,before)

    def test_missing_extra_or_promoted_authority_fields_reject(self):
        for key in recipe():
            r=recipe();r.pop(key)
            with self.subTest(key=key),self.assertRaises(ValueError):w.validate(r)
        for key,value in (('schema','diadem.terrain.capture.recipe.r4'),('purpose','PRODUCTION'),
                          ('physical_acceptance',0),('production_authorised',True),('source_label','UNKNOWN')):
            r=recipe();r[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):w.validate(r)
        r=recipe();r['forcing']['override']=True
        with self.assertRaises(ValueError):w.validate(r)

    def test_invalid_forcing_and_envelopes_reject(self):
        for key,value in (('steps',True),('steps',129),('dt_years',0),('dt_years',float('inf')),
                          ('dx_m',False),('dy_m',2.),('connectivity',True),('connectivity',6),
                          ('external_outlets',[0,0]),('external_outlets',[True]),
                          ('incoming_solid_m3_year',[.1,0.]),('runoff_m_year',[1.]),
                          ('rock_k_per_year',[0.,-1.]),('cover_scale_m',0.)):
            r=recipe();r['forcing'][key]=value
            with self.subTest(key=key,value=value),self.assertRaises(ValueError):w.validate(r)
        for key,value in (('wall_seconds',121),('wall_seconds',True),('max_product_bytes',0),
                          ('max_product_bytes',w.MAX_BYTES+1)):
            r=recipe();r['limits'][key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):w.validate(r)

    def test_state_status_controls_and_unrepresentable_time_reject(self):
        for key,value in (('source_status','CANON'),('frame','diadem'),('unknown',0),('time_years',1e30)):
            r=recipe();r['state'][key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):w.validate(r)
        r=recipe();r['constraints']=[{'id':'bed','cell':0,'minimum_m':1.,'maximum_m':2.,
            'source_status':'WORKING NON-CANON SYNTHETIC','source_label':'SYNTHETIC conflict'}]
        with self.assertRaisesRegex(ValueError,'CONFLICT'):w.validate(r)

    def test_private_graph_does_not_execute_foreign_same_named_modules(self):
        spec=importlib.util.spec_from_file_location('_shoreline_namespace_test',w.__file__)
        module=importlib.util.module_from_spec(spec)
        foreign=SimpleNamespace(__file__=str(w.HERE/'shoreline_driver.py'),advance=lambda *a,**k:None)
        with patch.dict(sys.modules,{'shoreline_driver':foreign,'capture':foreign}):spec.loader.exec_module(module)
        self.assertIsNot(module.driver,foreign)
        self.assertEqual(Path(module.driver.__file__),w.HERE/'shoreline_driver.py')
        self.assertIs(module.driver.capture,module.capture)


class PersistenceTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory(prefix='r6-shoreline-workflow-')
        self.addCleanup(temporary.cleanup);self.root=Path(temporary.name)
        self.allowed=self.root/'outputs'/'terrain-model-r6-shoreline'
        self.addCleanup(patch.stopall);patch.object(w,'OUTPUT_ROOT',self.allowed).start()
        self.input=self.root/'recipe.json';self.write_recipe(recipe())

    def write_recipe(self,r):self.input.write_bytes(w.io.canonical(r))
    def output(self,name='candidate'):return self.allowed/name
    def read(self,path):return w.io.parse_json(w._read(path))
    def tree(self,path):return {p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in path.iterdir()}
    def pending(self,name='candidate'):
        paths=list(self.allowed.glob(name+'.pending-*'));self.assertEqual(len(paths),1);return paths[0]
    def interrupt(self,step=1,at=None,name='candidate'):
        with self.assertRaisesRegex(RuntimeError,'injected interruption'):
            w.run(self.input,self.output(name),interrupt_after_step=None if at else step,interrupt_at=at)
        self.assertFalse(self.output(name).exists());return self.pending(name)

    def test_commit_uses_shoreline_driver_and_records_exact_per_step_counts(self):
        real=w.driver.advance
        with patch.object(w.capture,'advance',side_effect=AssertionError('must not use capture integrator')), \
                patch.object(w.driver,'advance',wraps=real) as called:
            result=w.run(self.input,self.output())
        self.assertEqual(called.call_count,3)
        self.assertTrue(all(c.kwargs['steps']==1 for c in called.call_args_list))
        self.assertEqual(result['status'],'COMMITTED_SHORELINE_REFERENCE')
        product=self.read(self.output()/'RESULT.json');self.assertEqual(product['state']['liquid_m3'],[.375,0.])
        for key in w.COUNT_FIELDS:self.assertEqual(product['counts'][key],sum(row[key] for row in product['step_counts']))
        self.assertIs(product['physical_acceptance'],False);self.assertIs(product['production_authorised'],False)
        self.assertEqual(len(product['checkpoints']),3)

    def test_uninterrupted_driver_and_workflow_match_original_absolute_targets(self):
        r=recipe();r['forcing'].update(steps=7,dt_years=.1);r['state']['time_years']=.2
        self.write_recipe(r);initial=w.validate(r)
        expected,_=w.driver.advance(initial,**r['forcing'])
        w.run(self.input,self.output());actual=self.read(self.output()/'RESULT.json')['state']
        self.assertEqual(w.io.canonical(actual),w.io.canonical(expected.as_dict()))

    def test_checkpoint_restart_matches_clean_products_exactly(self):
        pending=self.interrupt(2);before=self.tree(pending)
        w.run(self.input,self.output(),resume=True);w.run(self.input,self.output('clean'))
        self.assertEqual(self.tree(self.output()),self.tree(self.output('clean')))
        for name,sha in before.items():self.assertEqual(self.tree(self.output())[name],sha)

    def test_after_products_and_receipt_interruptions_are_recoverable(self):
        for at in ('after_products','after_receipt'):
            self.interrupt(at=at,name=at);w.run(self.input,self.output(at),resume=True)
        self.assertEqual(self.tree(self.output('after_products')),self.tree(self.output('after_receipt')))

    def test_committed_reuse_replays_and_preserves_exact_bytes(self):
        w.run(self.input,self.output());before=self.tree(self.output());real=w.driver.advance
        with patch.object(w.driver,'advance',wraps=real) as called:result=w.run(self.input,self.output(),resume=True)
        self.assertEqual(called.call_count,3);self.assertEqual(result['status'],'VERIFIED_SHORELINE_REUSE')
        self.assertEqual(before,self.tree(self.output()))

    def test_no_overwrite_or_implicit_resume(self):
        pending=self.interrupt();before=self.tree(pending)
        with self.assertRaises(FileExistsError):w.run(self.input,self.output())
        self.assertEqual(before,self.tree(pending))
        w.run(self.input,self.output(),resume=True);before=self.tree(self.output())
        with self.assertRaises(FileExistsError):w.run(self.input,self.output())
        self.assertEqual(before,self.tree(self.output()))
        with self.assertRaises(FileNotFoundError):w.run(self.input,self.output('missing'),resume=True)

    def test_corrupt_checkpoint_and_resealed_committed_checkpoint_reject(self):
        pending=self.interrupt();p=pending/'CHECKPOINT-000001.json';record=self.read(p)
        record['state']['liquid_m3'][0]+=1.;p.write_bytes(w.io.canonical(record));before=self.tree(pending)
        with self.assertRaisesRegex(ValueError,'replayed'):w.run(self.input,self.output(),resume=True)
        self.assertEqual(before,self.tree(pending))
        target=self.output('committed');w.run(self.input,target);p=target/'CHECKPOINT-000003.json'
        record=self.read(p);record['state']['liquid_m3'][0]+=.1;p.write_bytes(w.io.canonical(record))
        receipt=self.read(target/'RECEIPT.json');receipt['products'][p.name]={'sha256':w._sha(p.read_bytes()),'bytes':p.stat().st_size}
        (target/'RECEIPT.json').write_bytes(w.io.canonical(receipt));before=self.tree(target)
        with self.assertRaisesRegex(ValueError,'replayed'):w.run(self.input,target,resume=True)
        self.assertEqual(before,self.tree(target))

    def test_changed_counts_chain_identity_and_target_time_reject(self):
        for key,value in (('step_counts',{}),('generation_id','0'*64),('previous_state_sha256','1'*64),
                          ('completed_steps',True),('target_time_years',9.)):
            name=key;pending=self.interrupt(name=name);p=pending/'CHECKPOINT-000001.json'
            record=self.read(p);record[key]=value;p.write_bytes(w.io.canonical(record))
            with self.subTest(key=key),self.assertRaises(ValueError):w.run(self.input,self.output(name),resume=True)

    def test_noncontiguous_foreign_or_terminal_partial_inventory_reject(self):
        for mode in ('gap','foreign','premature-result'):
            pending=self.interrupt(name=mode)
            if mode=='gap':(pending/'CHECKPOINT-000001.json').rename(pending/'CHECKPOINT-000003.json')
            elif mode=='foreign':(pending/'foreign.txt').write_text('keep',encoding='utf8')
            else:(pending/'RESULT.json').write_bytes(b'{}')
            before=self.tree(pending)
            with self.subTest(mode=mode),self.assertRaises(ValueError):w.run(self.input,self.output(mode),resume=True)
            self.assertEqual(before,self.tree(pending))

    def test_recipe_and_source_drift_block_commit_and_reuse(self):
        real=w.driver.advance
        for source in (False,True):
            name='source' if source else 'recipe';before=self.input.read_bytes()
            pins=w.source_pins();changed=[False]
            def run(*a,**k):
                result=real(*a,**k);changed[0]=True
                if not source:self.input.write_bytes(before+b'\n')
                return result
            def sources():return pins+[{'name':'injected drift'}] if changed[0] and source else pins
            with patch.object(w.driver,'advance',side_effect=run),patch.object(w,'source_pins',side_effect=sources):
                with self.assertRaisesRegex(ValueError,'drift'):w.run(self.input,self.output(name))
            self.assertFalse(self.output(name).exists());self.input.write_bytes(before)
        self.interrupt(name='newidentity');self.input.write_bytes(self.input.read_bytes()+b'\n')
        with self.assertRaisesRegex(ValueError,'another recipe/source'):w.run(self.input,self.output('newidentity'),resume=True)

    def test_foreign_receipt_or_noncanonical_json_reject(self):
        w.run(self.input,self.output());p=self.output()/'RECEIPT.json';r=self.read(p)
        r['production_authorised']=0;p.write_bytes(w.io.canonical(r))
        with self.assertRaises(ValueError):w.run(self.input,self.output(),resume=True)
        for raw in (b'{"x":1,"x":2}',b'{"x":NaN}',b'{bad'):
            self.input.write_bytes(raw)
            with self.assertRaises(ValueError):w.run(self.input,self.output('invalid'))

    def test_root_escapes_recipe_inside_output_and_links_reject(self):
        for target in (self.allowed,self.allowed/'..'/'escape',self.root/'foreign'):
            with self.subTest(target=str(target)),self.assertRaises(ValueError):w.run(self.input,target)
        target=self.output('inside');target.mkdir(parents=True);p=target/'recipe.json';p.write_bytes(self.input.read_bytes())
        with self.assertRaises(ValueError):w.run(p,target)
        link=self.root/'linked.json';os_module=w.os
        os_module.link(self.input,link)
        with self.assertRaisesRegex(ValueError,'hardlinked'):w.run(link,self.output('linked'))
        link.unlink()

    def test_storage_and_whole_workflow_wall_limits_fail_closed(self):
        r=recipe();r['limits']['max_product_bytes']=1;self.write_recipe(r)
        with self.assertRaisesRegex(ValueError,'storage'):w.run(self.input,self.output('tiny'))
        self.assertFalse(self.output('tiny').exists());self.write_recipe(recipe())
        real=w.driver.advance;clock=[0.]
        def slow(*a,**k):
            result=real(*a,**k);clock[0]=121.;return result
        with patch.object(w.time,'monotonic',side_effect=lambda:clock[0]),patch.object(w.driver,'advance',side_effect=slow):
            with self.assertRaisesRegex(ValueError,'wall-time'):w.run(self.input,self.output('slow'))
        self.assertFalse(self.output('slow').exists())
        self.assertNotIn('CHECKPOINT-000001.json',self.tree(self.pending('slow')))

    def test_atomic_write_failure_never_leaves_truncated_checkpoint(self):
        real=w._move_new
        def fail(source,target):
            if Path(target).name=='CHECKPOINT-000001.json':raise OSError('injected atomic rename failure')
            return real(source,target)
        with patch.object(w,'_move_new',side_effect=fail),self.assertRaises(OSError):w.run(self.input,self.output())
        self.assertEqual(set(self.tree(self.pending())),{'RECIPE.json'})
        w.run(self.input,self.output(),resume=True)

    def test_writer_lock_rejects_concurrent_invocation_and_releases_after_error(self):
        self.allowed.mkdir(parents=True)
        with w._writer_lock(self.output().with_name('.candidate.writer.lock')):
            with self.assertRaisesRegex(ValueError,'writer lock'):w.run(self.input,self.output())
        w.run(self.input,self.output())

    def test_blocked_driver_preserves_verified_checkpoint_and_native_counts(self):
        real=w.driver.advance;calls=[0]
        def blocked(*a,**k):
            calls[0]+=1
            if calls[0]==2:
                error=w.driver.CouplingError('BLOCKED_UNRESOLVED_HYDRAULIC_CLOSURE')
                error.coupling_counts={'scalar_rhs_evaluations':7};raise error
            return real(*a,**k)
        with patch.object(w.driver,'advance',side_effect=blocked),self.assertRaisesRegex(ValueError,'BLOCKED_') as caught:
            w.run(self.input,self.output())
        info=caught.exception.shoreline_workflow_failure
        self.assertEqual(info['completed_replayed_steps'],1);self.assertEqual(info['driver_counts'],{'scalar_rhs_evaluations':7})
        self.assertFalse(info['output_committed']);self.assertEqual(set(self.tree(self.pending())),{'RECIPE.json','CHECKPOINT-000001.json'})

    def test_bad_driver_counts_do_not_create_checkpoint(self):
        real=w.driver.advance
        def invalid(*a,**k):
            state,report=real(*a,**k);report['counts']['trial_calls']=True;return state,report
        with patch.object(w.driver,'advance',side_effect=invalid),self.assertRaisesRegex(ValueError,'work counts'):
            w.run(self.input,self.output())
        self.assertNotIn('CHECKPOINT-000001.json',self.tree(self.pending()))

    def test_exact_forced_endpoint_is_a_durable_recoverable_snapshot(self):
        self.write_recipe(endpoint_recipe());self.interrupt()
        checkpoint=self.read(self.pending()/'CHECKPOINT-000001.json')
        self.assertEqual(checkpoint['state']['liquid_m3'],[0.,189/256,0.])
        self.assertEqual(checkpoint['state']['suspended_solid_m3'],[0.,63/256,0.])
        self.assertEqual(checkpoint['state']['bed_solid_m3'],[1/64,1/64,0.])
        self.assertEqual(checkpoint['step_counts']['scalar_rhs_evaluations'],24)
        self.assertFalse(checkpoint['driver_diagnostics']['events'][0]['post_event_hydraulics_solved'])
        w.run(self.input,self.output(),resume=True);w.run(self.input,self.output('clean'))
        self.assertEqual(self.tree(self.output()),self.tree(self.output('clean')))

    def test_forced_endpoint_two_quarter_steps_match_half_year_state(self):
        r=endpoint_recipe();self.write_recipe(r);w.run(self.input,self.output('half'))
        r['forcing'].update(steps=2,dt_years=.25);self.write_recipe(r);self.interrupt()
        w.run(self.input,self.output(),resume=True)
        self.assertEqual(self.read(self.output()/'RESULT.json')['state'],self.read(self.output('half')/'RESULT.json')['state'])

    def test_beyond_endpoint_hydraulic_blocker_cannot_become_success(self):
        r=endpoint_recipe();r['forcing']['dt_years']=1.;self.write_recipe(r)
        with self.assertRaisesRegex(ValueError,'BLOCKED_UNCERTIFIED_DRYING_EVENT') as caught:
            w.run(self.input,self.output())
        self.assertFalse(self.output().exists());self.assertEqual(set(self.tree(self.pending())),{'RECIPE.json'})
        self.assertEqual(caught.exception.shoreline_workflow_failure['completed_replayed_steps'],0)
        self.assertGreater(caught.exception.shoreline_workflow_failure['driver_counts']['scalar_rhs_evaluations'],0)

    def test_aggregate_work_cap_reports_uncommitted_attempt_and_preserves_prefix(self):
        real=w.driver.advance;calls=[0]
        def counted(*a,**k):
            result,report=real(*a,**k);calls[0]+=1
            report['counts']['trial_cell_evaluations']=w.driver.MAX_CELL_TRIALS if calls[0]==2 else 1
            return result,report
        with patch.object(w.driver,'advance',side_effect=counted),self.assertRaisesRegex(ValueError,'aggregate') as caught:
            w.run(self.input,self.output())
        info=caught.exception.shoreline_workflow_failure
        self.assertEqual(info['completed_driver_counts']['trial_cell_evaluations'],1)
        self.assertEqual(info['driver_counts']['trial_cell_evaluations'],w.driver.MAX_CELL_TRIALS)
        self.assertEqual(set(self.tree(self.pending())),{'RECIPE.json','CHECKPOINT-000001.json'})


if __name__=='__main__':unittest.main()
