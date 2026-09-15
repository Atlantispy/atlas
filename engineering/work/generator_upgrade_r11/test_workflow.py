"""Isolated graph dispatch/status oracles; not a substitute for real-producer QA.

The tiny explicit module doubles below prove orchestration without pretending
their integer records are climate/water/biology calculations. Final verification
also executes the same graph against the actual captured source graph.
"""
from copy import deepcopy
from types import SimpleNamespace as N
import base64
import json
import unittest
from unittest.mock import patch
from . import snapshot as s, workflow as w

H='a'*64


class Codec:
    @staticmethod
    def pack(value):
        raw=s.encoded(value)
        return {'sha256':s.sha(value),'byte_length':len(raw),'bytes':base64.b64encode(raw).decode('ascii')}

    @staticmethod
    def unpack(record):
        raw=base64.b64decode(record['bytes'],validate=True); out=json.loads(raw)
        if len(raw)!=record['byte_length'] or s.sha(out)!=record['sha256']:
            raise ValueError('packed checksum differs')
        return out


def fixture(*, supplied=False, water_status='MODELLED', missing_carbon=False):
    calls=[]
    r8_recipe={'seasonal':{'calendar':{'calendar_id':'explicit-year'}},'cell_context':{'cell':{}},'edges':[],
        'soil_recipe':{'organic':{'grain_density_kg_m3':1500}}}
    r9_recipe={'parent_recipe':r8_recipe}
    r10_recipe={'parent_recipe':r9_recipe,'hydraulic_hypotheses':{'held':{}}}
    recipe={'parent_recipe':r10_recipe,'scope':'SYNTHETIC DISPATCH TEST ONLY'}
    physical={'schema':'diadem.biomes-vegetation-result.r8','source_sha256':H,'recipe_sha256':s.sha(r8_recipe),
        'soil_result':{'state':{'members':{'snow':{'cell':{'height':'1'}}}},'parent_result':{'sediment':'0'}}}
    biology={'schema':'diadem.species-spatial-result.r9','parent_result_sha256':s.sha(physical)}
    parent={'schema':'diadem.seasonal-result.r10','parent_result_sha256':s.sha(biology),
        'physical_parent_result_sha256':s.sha(physical),'climate':{'members':{'snow':{'value':1}}}}
    unit={'snow_id':'snow','carbon':{'layers':{'cell-mineral':{'diagnostic':{'status':
        'UNKNOWN' if missing_carbon else 'MODELLED_SEASONAL_CARBON_DIAGNOSTIC'}}}}}
    def invoke(name,value):
        def run(*args,**kwargs):
            calls.append(name); return deepcopy(value)
        return run
    codec=Codec()
    r8=N(run=invoke('R8',physical),source_sha256=H,
        parent=N(parent=N(solver=N(),pipeline=N(hm=N(snow_scenarios=lambda:[N(scenario_id='snow')])))))
    r9=N(parent=r8,run=invoke('R9',biology))
    r10=N(parent=r9,run=invoke('R10',parent),graph=N(load=lambda name:N(Adapter=lambda sw:sw) if name.endswith('richards_numerics') else codec))
    geo={'contract':{'schema':'diadem.geo.r11-input-contract.v1','world_input_completeness':'INCOMPLETE','unresolved':[
        {'field':'seelenwacht_secondary_route','status':'CONFLICT','owner':'exact-owner'},
        {'field':'compatible_political_parent_and_policy','status':'PENDING_OWNER_RETURN','owner':'political-owner'}]},
        'source_bindings':{'explicit-contract':H}}
    pipeline=N(parse=lambda *a:None,parent_units=lambda *a:{'snow/held':{'cell':deepcopy(unit)}},
        water_inputs=lambda *a:({'network':{},'initial':{},'events':[],'controls':{}},{'actual':'water-input-join'}),
        ecosystem_products=invoke('ecosystem',({'cell':{'status':'MODELLED_SEASONAL_ECOSYSTEM'}},{'actual':'eco-input-join'})),
        human_inputs=lambda *a:{'scenario_id':'snow/held'})
    modules={'pipeline':pipeline,'owner_inputs':N(geography=lambda *a:deepcopy(geo),species=lambda *a:{'owner':'actual-bound-in-real-graph'}),
        'world_inputs':N(declared_frames=invoke('world-frames',{'schema':'diadem.r11.owner-declared-world-frames.v1','vertical_datum':None})),
        'biology':N(build_overlay=invoke('owner-bio',{'schema':'diadem.biological-overlay-test','status':'PRESERVED_FACTS'})),
        'soil_feedback':N(reference_continuation=invoke('feedback',{'schema':'diadem.actual-soil-structure-continuation.r11','status':'MODELLED_STRUCTURE_AND_WATER_CONTINUATION'})),
        'water':N(run=invoke('water',{'status':water_status})),
        'human':N(run_year=invoke('human',{'status':'COMPLETE','events':[],'fixed_settlements':[]}))}
    bundle=N(parent=r10,source_sha256=H,module=lambda key:modules[key],transport=N(),
        graph=N(verify=lambda:None),verify=lambda:None)
    return bundle,recipe,calls,parent if supplied else None,modules


class WorkflowTests(unittest.TestCase):
    def run_fixture(self,**kw):
        b,r,c,parent,_=fixture(**kw)
        return b,r,c,w.run(b,r,supplied_parent=parent)

    def test_assemble_does_no_science(self):
        b,r,c,p,_=fixture(); built=w.assemble(b,r)
        self.assertEqual(c,[])
        self.assertEqual(set(built['recipe']['required_categories']),set(s.CATEGORIES))
        s.parse(built['recipe'],built['registry'])

    def test_actual_registered_call_order_dispatch(self):
        _,_,calls,out=self.run_fixture()
        self.assertEqual([c for c in calls if c in ('R8','R9','R10')],['R8','R9','R10'])
        self.assertEqual(calls.count('water'),1)
        self.assertEqual(calls.count('ecosystem'),1)
        self.assertGreater(calls.index('human'),calls.index('water'))
        self.assertGreater(calls.index('human'),calls.index('ecosystem'))
        self.assertEqual(out['status'],'INCOMPLETE')
        self.assertFalse(out['whole_generator_complete'])

    def test_supplied_parent_explicit_and_not_regenerated(self):
        _,_,calls,out=self.run_fixture(supplied=True)
        self.assertNotIn('R10',calls); self.assertIn('R8',calls); self.assertIn('R9',calls)
        self.assertEqual(out['graph_artifact']['state']['rows']['parent-r10']['product']['status'],'SUPPLIED_CONSTRAINT')

    def test_fresh_parent_declared_generated(self):
        _,_,_,out=self.run_fixture()
        self.assertEqual(out['graph_artifact']['state']['rows']['parent-r10']['product']['status'],'MODELLED')

    def test_exact_lineage_mismatch_rejects(self):
        b,r,c,p,_=fixture(supplied=True); p['physical_parent_result_sha256']='b'*64
        with self.assertRaisesRegex(ValueError,'dependency artifacts'):
            w.run(b,r,supplied_parent=p)

    def test_r9_lineage_mismatch_rejects(self):
        b,r,c,_,_=fixture(); b.parent.parent.run=lambda recipe:{'parent_result_sha256':'b'*64}
        with self.assertRaisesRegex(ValueError,'R8 dependency'):
            w.run(b,r)

    def test_missing_water_does_not_zero_or_block_independent_ecology(self):
        b,r,c,out=self.run_fixture(water_status='UNKNOWN')
        self.assertIn('ecosystem',c); self.assertNotIn('human',c)
        refs=out['scenario_product_refs']['snow/held']
        self.assertIsNone(refs['water']); self.assertIsNone(refs['human']); self.assertIsNotNone(refs['ecosystem'])
        self.assertIn('water--snow--held',out['diagnostic_artifact_refs'])

    def test_unknown_carbon_is_causal_not_zero(self):
        _,_,c,out=self.run_fixture(missing_carbon=True)
        self.assertIn('water',c); self.assertNotIn('ecosystem',c); self.assertNotIn('human',c)
        self.assertIsNone(out['scenario_product_refs']['snow/held']['ecosystem'])

    def test_projections_never_relabel_as_regeneration(self):
        _,_,_,out=self.run_fixture()
        for name in ('precipitation-parent','topography-parent','formed-soil-parent','erosion-parent','populations--snow--held'):
            self.assertEqual(out['graph_artifact']['state']['rows'][name]['product']['status'],'SUPPLIED_CONSTRAINT')

    def test_raw_owner_states_and_ids_preserved(self):
        b,r,c,out=self.run_fixture()
        self.assertEqual(out['owner_field_statuses'][0],{'field':'seelenwacht_secondary_route','status':'CONFLICT','owner':'exact-owner'})
        contract=w.resolve(b,out,out['owner_input_contract_ref'])
        self.assertEqual(contract['contract']['unresolved'],out['owner_field_statuses'])
        closure=out['graph_artifact']['category_closure']
        self.assertFalse(closure['political_borders']['execution_complete'])

    def test_new_owner_field_cannot_be_silently_omitted(self):
        b,r,_,_,modules=fixture()
        modules['owner_inputs'].geography=lambda *a:{'contract':{'schema':'diadem.geo.r11-input-contract.v1','unresolved':[
            {'field':'new-physical-input','status':'UNKNOWN','owner':'owner'}]},'source_bindings':{'p':H}}
        with self.assertRaisesRegex(ValueError,'explicit category mapping'):
            w.assemble(b,r)

    def test_population_gate_not_false_missing_total(self):
        b,r,_,_,_=fixture(); built=w.assemble(b,r)
        row=next(x for x in built['recipe']['stages'] if x['stage_id']=='required-parent--populations')
        self.assertIn('15,964,359',row['missing_inputs'][0])
        self.assertIn('mapping',row['missing_inputs'][0])

    def test_each_artifact_resolves_and_is_stored_once(self):
        b,_,_,out=self.run_fixture()
        self.assertEqual(len(out['packed_artifacts']),len(set(out['packed_artifacts'])))
        for row in out['graph_artifact']['state']['rows'].values():
            ref=row['product']['values']['product']
            if ref is not None:
                self.assertIsInstance(w.resolve(b,out,ref),dict)
        self.assertLess(len(s.encoded(out['graph_artifact'])),s.MAX_BYTES)

    def test_modified_artifact_fails_checksum(self):
        b,_,_,out=self.run_fixture(); ref=out['parent_ref']
        out['packed_artifacts'][ref['artifact_id']]['bytes']=base64.b64encode(b'{}').decode('ascii')
        with self.assertRaisesRegex(ValueError,'checksum'):
            w.resolve(b,out,ref)

    def test_modified_reference_size_rejects(self):
        b,_,_,out=self.run_fixture(); ref=deepcopy(out['parent_ref']); ref['byte_length']+=1
        with self.assertRaisesRegex(ValueError,'size'):
            w.resolve(b,out,ref)

    def test_modified_source_binding_rejects(self):
        b,_,_,out=self.run_fixture(); out['source_sha256']='b'*64
        with self.assertRaisesRegex(ValueError,'source binding'):
            w.resolve(b,out,out['parent_ref'])

    def test_zero_cursor_executes_nothing(self):
        b,r,c,p,_=fixture(); out=w.run(b,r,stop_after=0)
        self.assertEqual(c,[]); self.assertIsNone(out['parent_ref'])

    def test_restart_exact_at_graph_boundary(self):
        b,r,c,p,_=fixture(); stop=w.run(b,r,stop_after=3)
        self.assertEqual(w.run(b,r),w.run(b,r,resume=stop['graph_checkpoint']))

    def test_rehashed_checkpoint_forgery_still_rejects(self):
        b,r,_,_,_=fixture(); out=w.run(b,r,stop_after=3); cp=deepcopy(out['graph_checkpoint'])
        first=next(iter(cp['state']['rows'].values())); first['product']['evidence']='forged'
        cp['state_sha256']=s.sha(cp['state'])
        with self.assertRaisesRegex(ValueError,'semantic'):
            w.run(b,r,resume=cp)

    def test_registered_input_mutation_rejects_before_science(self):
        b,r,c,_,_=fixture(); built=w.assemble(b,r)
        built['recipe']['stages'][0]['inputs']['scope']='changed'
        with self.assertRaisesRegex(ValueError,'input binding'):
            s.run(built['recipe'],built['registry'])
        self.assertNotIn('R8',c)

    def test_soil_continuation_is_actual_registered_downstream_call(self):
        b,r,c,out=self.run_fixture()
        self.assertGreater(c.index('feedback'),c.index('ecosystem'))
        ref=out['scenario_product_refs']['snow/held']['soil_feedback']['cell']
        self.assertEqual(w.resolve(b,out,ref)['status'],'MODELLED_STRUCTURE_AND_WATER_CONTINUATION')

    def test_materialisation_never_reruns_science(self):
        b,r,c,out=self.run_fixture(); before=list(c)
        result=w.materialise_consequences(b,r,out)
        self.assertEqual(c,before); self.assertTrue(result['materialised_without_scientific_reruns'])
        self.assertEqual(result['status'],'COMPLETE_BOUNDED_CONSEQUENCES')
        self.assertEqual(result['graph_status'],'INCOMPLETE')
        row=Codec.unpack(result['state']['results']['snow/held'])
        self.assertEqual(row['human']['status'],'COMPLETE')
        self.assertEqual(row['water_joins'],{'actual':'water-input-join'})

    def test_materialisation_wrong_ref_cannot_select_another_product(self):
        b,r,c,out=self.run_fixture()
        out['scenario_product_refs']['snow/held']['water']=out['scenario_product_refs']['snow/held']['human']
        with self.assertRaisesRegex(ValueError,'reference differs'):
            w.materialise_consequences(b,r,out)

    def test_materialisation_unknown_remains_incomplete(self):
        b,r,c,out=self.run_fixture(missing_carbon=True)
        result=w.materialise_consequences(b,r,out)
        self.assertEqual(result['status'],'INCOMPLETE')
        self.assertEqual(result['state']['completed_scenarios'],len(result['state']['results']))
        self.assertEqual(Codec.unpack(result['state']['results']['snow/held'])['status'],'INCOMPLETE')

    def test_effective_owner_delta_preserves_original(self):
        b,r,c,_,modules=fixture(); original=modules['owner_inputs'].geography(b)
        updated=deepcopy(original); updated['effective_unresolved']=deepcopy(updated['contract']['unresolved'])
        updated['effective_unresolved'][1]['status']='INCOMPLETE'; updated['requested_owner_returns_complete']=True
        modules['owner_inputs'].geography=lambda *a:deepcopy(updated)
        out=w.run(b,r)
        self.assertEqual(out['owner_field_statuses'][1]['status'],'INCOMPLETE')
        geo=w.resolve(b,out,out['owner_input_contract_ref'])
        self.assertEqual(geo['contract']['unresolved'][1]['status'],'PENDING_OWNER_RETURN')
        self.assertTrue(geo['requested_owner_returns_complete'])
        summary=w.materialise_consequences(b,r,out)['geo_input_contract']
        self.assertEqual(summary['unresolved'][1]['status'],'INCOMPLETE')
        self.assertEqual(summary['original_unresolved'][1]['status'],'PENDING_OWNER_RETURN')

    def test_meaningful_cursor_after_first_human(self):
        b,r,c,_,_=fixture(); cursor=w.graph_stop_after_first_human(b,r)
        self.assertEqual(c,[])
        out=w.run(b,r,stop_after=cursor)
        self.assertEqual(c.count('human'),1)
        self.assertIsNotNone(out['scenario_product_refs']['snow/held']['human'])

    def test_declared_frame_not_promoted_to_map_or_known_datum(self):
        b,r,c,out=self.run_fixture()
        self.assertIn('world-frames',c)
        row=out['graph_artifact']['state']['rows']['world-owner-frames']['product']
        self.assertEqual(row['status'],'SUPPLIED_CONSTRAINT')
        self.assertIsNone(w.resolve(b,out,out['declared_world_frames_ref'])['vertical_datum'])

    def test_missing_actual_soil_recipe_rejects_before_dispatch(self):
        b,r,c,_,_=fixture()
        physical=r['parent_recipe']['parent_recipe']['parent_recipe']
        physical['parent_recipe']=physical.pop('soil_recipe')
        with self.assertRaisesRegex(ValueError,'actual R8 soil_recipe'):
            w.assemble(b,r)
        self.assertEqual(c,[])

    def test_invalid_organic_density_rejects_before_dispatch(self):
        for value in (None,True,False,0,-1,'0','-1','NaN','Infinity',float('nan'),float('inf')):
            with self.subTest(value=value):
                b,r,c,_,_=fixture()
                r['parent_recipe']['parent_recipe']['parent_recipe']['soil_recipe']['organic']['grain_density_kg_m3']=value
                with self.assertRaisesRegex(ValueError,'density'):
                    w.assemble(b,r)
                self.assertEqual(c,[])

    def test_registered_feedback_receives_exact_retained_density(self):
        b,r,c,_,modules=fixture(); observed=[]
        retained=modules['soil_feedback'].reference_continuation
        def capture(*args,**kwargs):
            observed.append(kwargs['organic_grain_density_kg_m3'])
            return retained(*args,**kwargs)
        modules['soil_feedback'].reference_continuation=capture
        w.run(b,r)
        self.assertEqual(observed,[1500])


class ActualWorkflowRecipeTests(unittest.TestCase):
    """Real source-bound recipe contract, without running any science producer."""
    @classmethod
    def setUpClass(cls):
        from . import binding
        cls.bundle=binding.load()
        cls.recipe=cls.bundle.reference.recipe(cls.bundle)

    def test_actual_ancestor_recipe_contracts_and_packing_input(self):
        r10=self.bundle.parent; r9=r10.parent; r8=r9.parent; r7=r8.parent
        a=self.recipe['parent_recipe']; b=a['parent_recipe']; c=b['parent_recipe']; d=c['soil_recipe']
        self.assertNotIn('parent_recipe',c)
        r10.graph.load('work.generator_upgrade_r10.pipeline').parse(r10,a)
        r9.graph.load('work.generator_upgrade_r9.pipeline').parse(r9,b)
        r8.pipeline.parse(r8,c)
        r7.pipeline.parse(r7,d)
        self.assertEqual(w.retained_organic_density(c),d['organic']['grain_density_kg_m3'])

    def test_actual_assembly_all_groups_and_soil_callbacks_without_science(self):
        r10=self.bundle.parent; r9=r10.parent; r8=r9.parent
        with patch.object(r10,'run',side_effect=AssertionError('unexpected R10 run')), \
             patch.object(r9,'run',side_effect=AssertionError('unexpected R9 run')), \
             patch.object(r8,'run',side_effect=AssertionError('unexpected R8 run')):
            built=w.assemble(self.bundle,self.recipe)
        self.assertEqual(len(built['stage_ids']['human']),9)
        self.assertEqual(sum(map(len,built['stage_ids']['soil_feedback'].values())),18)
        self.assertEqual(len(built['recipe']['required_categories']),18)
        _,order=s.parse(built['recipe'],built['registry'])
        self.assertEqual(len(order),len(built['recipe']['stages']))

    def test_actual_invalid_soil_recipe_fails_before_any_producer(self):
        recipe=deepcopy(self.recipe)
        physical=recipe['parent_recipe']['parent_recipe']['parent_recipe']
        physical['parent_recipe']=physical.pop('soil_recipe')
        with self.assertRaisesRegex(ValueError,'actual R8 soil_recipe'):
            w.assemble(self.bundle,recipe)


if __name__=='__main__':
    unittest.main()
