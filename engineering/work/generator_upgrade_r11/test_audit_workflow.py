"""Saved graph tampering tests using explicit orchestration doubles.

These tests do not claim scientific validation of the toy producer records.
The real workflow verification calls the real saved-account auditors; here their
invocation is observed, while all scientific reruns are prohibited after setup.
"""
from copy import deepcopy
from types import SimpleNamespace as N
import unittest
from . import audit_workflow as a, workflow as w, snapshot as s
from .test_workflow import fixture as dispatch_fixture, Codec, H
from .ecosystem import plain as ecosystem_plain


SCIENCE = {'R8','R9','R10','water','ecosystem','human','feedback'}


def fixture(*, supplied=False, water_status='MODELLED', missing_carbon=False):
    b, r, calls, _, modules = dispatch_fixture(water_status=water_status, missing_carbon=missing_carbon)
    r['parameters'] = {'plant_absorbed_light_multiplier':'1'}
    r10=b.parent; r9=r10.parent; r8=r9.parent
    expected=[]
    for bound, recipe, schema in ((r8,r['parent_recipe']['parent_recipe']['parent_recipe'],'diadem.biomes-vegetation-result.r8'),
            (r9,r['parent_recipe']['parent_recipe'],'diadem.species-spatial-result.r9'),
            (r10,r['parent_recipe'],'diadem.seasonal-world-result.r10')):
        value=bound.run(recipe)
        value.update(schema=schema, source_sha256=H, recipe_sha256=s.sha(recipe), source_status='WORKING NON-CANON',
            production_installed=False, canon_changed=False, optimisation_performed=False)
        if expected:
            value['parent_result_sha256']=s.sha(expected[-1])
        if len(expected)==2:
            value['physical_parent_result_sha256']=s.sha(expected[0])
        expected.append(value); bound.source_sha256=H

    def invoke(name, value):
        def call(*args, **kwargs):
            calls.append(name); return deepcopy(value)
        return call
    for bound,name,value in zip((r8,r9,r10),('R8','R9','R10'),expected):
        bound.run=invoke(name,value)
    p=modules['pipeline']; p.E='explicit metadata test evidence'
    spec={'initial_state':{},'plant_law':{},'organic_law':{},'nutrient_context':{},'calendar':{},
        'events':[],'numerics':{},'geometry_sha256':'c'*64}
    eco_inputs=deepcopy(spec)
    eco_inputs.update(source_binding_sha256=H, scenario_id='snow/held/cell', evidence=p.E, source_status='SYNTHETIC TEST')
    join={'actual':'eco-input-join'}
    modules['ecosystem']=N(reference_spec=lambda *args:{**deepcopy(spec),'reference_join':deepcopy(join)},
        state_to_record=lambda organic, value:value, plain=ecosystem_plain)
    eco={'status':'MODELLED_SEASONAL_ECOSYSTEM','source_status':'WORKING NON-CANON',
        'source_binding_sha256':H,'scenario_id':'snow/held/cell','inputs':eco_inputs}
    p.ecosystem_products=invoke('ecosystem',({'cell':eco},{'cell':join}))
    modules['water'].run=invoke('water',{'status':water_status,'source_binding_sha256':H,'scenario_id':'snow/held',
        'inputs':{'network':{},'initial':{},'events':[],'controls':{}},'production_ready':False,'canon_adopted':False})
    modules['human'].run_year=invoke('human',{'status':'COMPLETE','source_status':'WORKING NON-CANON',
        'source_binding_sha256':H,'scenario_id':'snow/held','events':[],'fixed_settlements':[]})
    modules['workflow']=w; b.organic=N(); b.fertility=N()
    audit_calls=[]
    def audit(name):
        def inspect(*args):
            audit_calls.append(name); return {'status':'TOY_AUDITOR_CALLED_NOT_SCIENTIFIC_EVIDENCE'}
        return inspect
    modules['audit']=N(group=audit('group'),water=audit('water'),ecosystem=audit('ecosystem'))
    modules['audit_soil']=N(continuation=audit('soil'))
    calls.clear()
    return b,r,calls,deepcopy(expected[-1]) if supplied else None,modules,audit_calls


def rehash(out):
    """Rehash a forged saved graph without running a scientific producer."""
    nodes={row['stage_id']:row for row in out['graph_recipe']['stages']}
    rows=out['graph_artifact']['state']['rows']
    # Rows were inserted in accepted topological order by the graph executor.
    for ident,row in rows.items():
        stage=nodes[ident]
        deps={name:rows[dep['stage_id']]['product_sha256'] for name,dep in sorted(stage['dependencies'].items())}
        row['invocation_sha256']=s.sha({'context':out['graph_recipe']['context'],'stage':stage,'dependency_products':deps})
        row['product_sha256']=s.sha(row['product'])
    out['graph_checkpoint']=s.checkpoint(out['graph_artifact'])


def change_artifact(out, ref, change):
    """Replace a payload and direct graph/named references with honest new hashes.

    This deliberately does not rewrite scientific source claims, projections or
    embedded references: the independent semantic validator must check those.
    """
    old=ref['artifact_id']; value=Codec.unpack(out['packed_artifacts'][old]); change(value)
    record=Codec.pack(value); new=record['sha256']
    def rewrite(value):
        if isinstance(value,dict):
            if value.get('artifact_id')==old:
                return {**value,'artifact_id':new,'sha256':new,'byte_length':record['byte_length'],
                    'schema':Codec.unpack(record).get('schema','explicit-object')}
            return {k:rewrite(v) for k,v in value.items()}
        if isinstance(value,list):
            return [rewrite(v) for v in value]
        return value
    for key in list(out):
        if key!='packed_artifacts': out[key]=rewrite(out[key])
    del out['packed_artifacts'][old]; out['packed_artifacts'][new]=record
    rehash(out)


class AuditWorkflowTests(unittest.TestCase):
    def setup_result(self, *, stop_after=None, **kwargs):
        self.b,self.r,self.calls,self.parent,self.modules,self.audit_calls=fixture(**kwargs)
        self.out=w.run(self.b,self.r,supplied_parent=self.parent,stop_after=stop_after)
        self.before=[c for c in self.calls if c in SCIENCE]
        return self.out

    def audit(self, *, complete=True):
        result=a.result(self.b,self.r,self.out,supplied_parent=self.parent,complete=complete)
        self.assertEqual([c for c in self.calls if c in SCIENCE],self.before)
        return result

    def reject(self, pattern, *, complete=True):
        with self.assertRaisesRegex(ValueError,pattern): self.audit(complete=complete)
        self.assertEqual([c for c in self.calls if c in SCIENCE],self.before)

    def test_complete_delegates_saved_ledgers_without_science(self):
        self.setup_result(); result=self.audit()
        self.assertEqual(result['status'],'PASS'); self.assertEqual(result['scientific_producer_reruns'],0)
        self.assertEqual(result['complete_scenario_count'],1); self.assertEqual(result['soil_continuation_count'],1)
        self.assertEqual(self.audit_calls,['group','soil']); self.assertEqual(result['graph_status'],'INCOMPLETE')

    def test_supplied_parent_is_bound_not_regenerated(self):
        self.setup_result(supplied=True); self.audit(); self.assertNotIn('R10',self.before)

    def test_zero_prefix_requires_no_science(self):
        self.setup_result(stop_after=0); result=self.audit(complete=False)
        self.assertEqual(result['completed_stages'],0); self.assertEqual(self.before,[])
        self.assertEqual(self.audit_calls,[]); self.assertEqual(result['graph_status'],'STOPPED')

    def test_every_accepted_prefix_passes_without_scientific_replay(self):
        b,r,_,p,_,_=fixture(); built=w.assemble(b,r,supplied_parent=p)
        for cursor in range(len(built['recipe']['stages'])+1):
            with self.subTest(cursor=cursor):
                self.setup_result(stop_after=cursor); self.audit(complete=False)

    def test_prefix_not_complete(self):
        self.setup_result(stop_after=0); self.reject('all graph stages')

    def test_complete_mode_requires_boolean(self):
        self.setup_result(); self.reject('explicit complete',complete=1)

    def test_failed_water_allowed_only_prefix_audit(self):
        self.setup_result(water_status='UNKNOWN'); result=self.audit(complete=False)
        self.assertEqual(result['complete_scenario_count'],0); self.assertIn('ecosystem',self.audit_calls)
        self.reject('complete bounded scenario')

    def test_missing_carbon_keeps_actual_water_partial(self):
        self.setup_result(missing_carbon=True); self.audit(complete=False)
        self.assertEqual(self.audit_calls,['water']); self.reject('complete bounded scenario')

    def test_source_mutation(self):
        self.setup_result(); self.out['source_sha256']='b'*64; self.reject('recipe/source/schema')

    def test_recipe_context_mutation(self):
        self.setup_result(); self.out['graph_recipe']['context']['calendar_id']='another-year'; self.reject('stage/inputs/port/source')

    def test_stage_registration_mutation(self):
        self.setup_result(); self.out['graph_recipe']['stages'][0]['source_sha256']='b'*64; self.reject('stage/inputs/port/source')

    def test_checkpoint_mutation(self):
        self.setup_result(); self.out['graph_checkpoint']['state_sha256']='b'*64; self.reject('checkpoint/state')

    def test_missing_stage_despite_rehashed_checkpoint(self):
        self.setup_result(); self.out['graph_artifact']['state']['rows'].pop('parent-r10')
        self.out['graph_checkpoint']=s.checkpoint(self.out['graph_artifact']); self.reject('prefix omits')

    def test_invocation_forgery(self):
        self.setup_result(); self.out['graph_artifact']['state']['rows']['parent-r10']['invocation_sha256']='b'*64
        self.out['graph_checkpoint']=s.checkpoint(self.out['graph_artifact']); self.reject('invocation/dependency')

    def test_evidence_forgery_survives_hashes_not_semantics(self):
        self.setup_result(); self.out['graph_artifact']['state']['rows']['parent-r10']['product']['evidence']='forged'; rehash(self.out)
        self.reject('evidence differs')

    def test_false_generated_parent_projection(self):
        self.setup_result(); self.out['graph_artifact']['state']['rows']['topography-parent']['product']['status']='MODELLED'; rehash(self.out)
        self.reject('supplied/generated/source-status')

    def test_known_parent_source_status_promotion(self):
        self.setup_result(); self.out['graph_artifact']['state']['rows']['physical-r8']['product']['source_status']='CANON'; rehash(self.out)
        self.reject('supplied/generated/source-status')

    def test_missing_gate_is_not_executed(self):
        self.setup_result(); rows=self.out['graph_artifact']['state']['rows']
        row=next(row for row in rows.values() if row['producer_executed'] is False)
        row['producer_executed']=True; rehash(self.out); self.reject('non-executed UNKNOWN')

    def test_missing_gate_reason_cannot_be_relabelled(self):
        self.setup_result(); rows=self.out['graph_artifact']['state']['rows']
        row=next(row for row in rows.values() if row['producer_executed'] is False)
        row['product']['unresolved']=['invented replacement']; rehash(self.out); self.reject('non-executed UNKNOWN')

    def test_output_units_are_exact(self):
        self.setup_result(); self.out['graph_artifact']['state']['rows']['physical-r8']['product']['ports']['product']['unit']='metres'
        rehash(self.out); self.reject('port|support')

    def test_category_closure_cannot_be_promoted(self):
        self.setup_result(); self.out['graph_artifact']['category_closure']['plate_tectonics']['execution_complete']=True
        self.out['graph_checkpoint']=s.checkpoint(self.out['graph_artifact']); self.reject('closure inflated')

    def test_status_cannot_be_promoted(self):
        self.setup_result(); self.out['status']='EXECUTED'; self.reject('completion status')

    def test_world_completion_cannot_be_promoted(self):
        self.setup_result(); self.out['whole_generator_complete']=True; self.reject('not a completed world')

    def test_canon_flag_cannot_be_promoted(self):
        self.setup_result(); self.out['graph_artifact']['canon_changed']=True; self.reject('canon/production authority')

    def test_artifact_byte_mutation(self):
        self.setup_result(); key=self.out['parent_ref']['artifact_id']; self.out['packed_artifacts'][key]['byte_length']+=1
        self.reject('checksum')

    def test_orphan_artifact_rejected(self):
        self.setup_result(); extra=Codec.pack({'orphan':1}); self.out['packed_artifacts'][extra['sha256']]=extra
        self.reject('unreferenced/missing')

    def test_named_parent_reference_cannot_select_other_stage(self):
        self.setup_result(); self.out['parent_ref']=self.out['biology_parent_ref']; self.reject('named stage reference')

    def test_scenario_reference_cannot_select_other_product(self):
        self.setup_result(); refs=self.out['scenario_product_refs']['snow/held']; refs['water']=refs['human']; self.reject('component reference')

    def test_soil_support_cannot_be_dropped(self):
        self.setup_result(); self.out['scenario_product_refs']['snow/held']['soil_feedback']={}; self.reject('soil continuation reference inventory')

    def test_owner_field_status_cannot_be_silently_resolved(self):
        self.setup_result(); self.out['owner_field_statuses'][0]['status']='COMPLETE'; self.reject('GEO field/status')

    def test_rehashed_biology_owner_overlay_rejected(self):
        self.setup_result(); change_artifact(self.out,self.out['biological_owner_overlay_ref'],lambda row:row.update(status='SELECTED_WITHOUT_OWNER'))
        self.reject('delivered biology overlay')

    def test_rehashed_frame_unknown_datum_not_zero(self):
        self.setup_result(); change_artifact(self.out,self.out['declared_world_frames_ref'],lambda row:row.update(vertical_datum=0))
        self.reject('declared native world frame')

    def test_rehashed_parent_wrong_source_rejected(self):
        self.setup_result(); change_artifact(self.out,self.out['parent_ref'],lambda row:row.update(source_sha256='b'*64)); self.reject('R8/R9/R10 source')

    def test_rehashed_parent_wrong_lineage_rejected(self):
        self.setup_result(); change_artifact(self.out,self.out['parent_ref'],lambda row:row.update(parent_result_sha256='b'*64)); self.reject('R10-to-R9/R8')

    def test_rehashed_parent_authority_promotion_rejected(self):
        self.setup_result(); change_artifact(self.out,self.out['parent_ref'],lambda row:row.update(canon_changed=True)); self.reject('parent applicability/authority')

    def test_rehashed_projection_value_rejected(self):
        self.setup_result(); ref=self.out['graph_artifact']['state']['rows']['precipitation-parent']['product']['values']['product']
        change_artifact(self.out,ref,lambda row:row.update(selected_value_sha256='b'*64)); self.reject('projection content/meaning')

    def test_rehashed_ecosystem_law_input_rejected(self):
        self.setup_result(); ref=self.out['scenario_product_refs']['snow/held']['ecosystem']
        change_artifact(self.out,ref,lambda row:row['models']['cell']['inputs'].update(plant_law={'invented':'law'})); self.reject('native ecosystem stock/driver/law')

    def test_rehashed_ecosystem_source_join_rejected(self):
        self.setup_result(); ref=self.out['scenario_product_refs']['snow/held']['ecosystem']
        change_artifact(self.out,ref,lambda row:row.update(source_joins={'cell':{'wrong':'parent'}})); self.reject('ecosystem source joins')

    def test_rehashed_partial_water_input_rejected(self):
        self.setup_result(missing_carbon=True); ref=self.out['scenario_product_refs']['snow/held']['water']
        change_artifact(self.out,ref,lambda row:row['model']['inputs'].update(controls={'invented':1})); self.reject('water parent/input joins',complete=False)

    def test_rehashed_wrapper_scenario_rejected(self):
        self.setup_result(); ref=self.out['scenario_product_refs']['snow/held']['ecosystem']
        change_artifact(self.out,ref,lambda row:row.update(scenario_id='wrong/scenario')); self.reject('wrapper group/schema')

    def test_diagnostics_cannot_attach_to_success(self):
        self.setup_result(); self.out['diagnostic_artifact_refs']['parent-r10']=self.out['parent_ref']; self.reject('nonfailed/unexecuted')


if __name__=='__main__':
    unittest.main()
