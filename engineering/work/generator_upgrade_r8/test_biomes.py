"""Small independent classification, physical joins and uncertainty checks."""
import ast
import copy
import hashlib
import itertools
import json
import math
from pathlib import Path
import unittest

from . import biomes as b
from . import vegetation as v

E='SYNTHETIC ecological response for dimensional/semantic test, not Diadem adoption'
S='SYNTHETIC TEST'
METRIC='active_actual_to_potential_transpiration_ratio'
CONTROL={'low_support_threshold':.25,'broad_margin':.04,'formation_margin':.04,'tie_tolerance':1e-7}
DOMAIN={'kind':'LAND','source_status':S,'evidence':E}


def pft_record(key,value=1.,status='PASS',interval=None):
    """Explicit result-contract fixture; actual producer join tested separately."""
    return {'schema':'diadem.pft-seasonal-admissibility.r8','pft_id':key,'status':status,
        'metrics':{METRIC:value},'metric_units':{METRIC:'1'},'metric_intervals':{METRIC:[value,value] if interval is None else interval},
        'fixture_evidence':E}


def climate(value=1.,unit='1',status=S):return {'value':value,'unit':unit,'source_status':status,'evidence':E}


def response(metric='annual_precipitation_to_reference_pet_ratio',value=1.,required=True,unit='1'):
    return {'metric':metric,'unit':unit,'points':[[0.,value],[1.,value]],'outside':'HOLD','required':required,'evidence':E}


def inputs(best=7):
    guilds={name:{'guild':name,'evidence':E} for name in sorted(b.GUILDS)}
    pfts={name:pft_record(name) for name in guilds}
    source={1:[],2:['COLD_HERB'],3:['COLD_SHRUB','COLD_CONIFER'],4:['COLD_CONIFER'],
        5:['COLD_CONIFER','TEMPERATE_TREE'],6:['MACROFOREST_TREE'],7:['TEMPERATE_TREE'],
        8:['TEMPERATE_TREE','GRASS'],9:['GRASS'],10:['DRY_SHRUB']}
    rules=[]
    for code in b.FORMATION_NAMES:
        responses=[response(value=.9 if code==best else .1)]
        if code==1:responses += [dict(response('snow_persistence_fraction'),points=[[0.,0.],[1.,1.]]),response('warmest_month_temperature_c',unit='degC')]
        rules.append({'code':code,'pft_ids':source[code],'pft_operator':'NONVEGETATED' if code==1 else 'ALL' if code in (5,8) else 'ANY',
            'responses':responses,'factor_operator':'MINIMUM','evidence':E})
    families=[{'family_id':name,'evidence':E,'pft_score_rules':{key:{'metric':METRIC,'unit':'1','points':[[0.,0.],[1.,1.]],'evidence':E} for key in pfts},
        'formations':copy.deepcopy(rules)} for name in ('climate-structure','limiting-factor','integrated-water')]
    return {'cell_id':'cell-a','domain':copy.deepcopy(DOMAIN),'families':families,
        'pft_results':{family['family_id']:copy.deepcopy(pfts) for family in families},
        'climate_metrics':{'annual_precipitation_to_reference_pet_ratio':climate(), 'snow_persistence_fraction':climate(0.),'warmest_month_temperature_c':climate(15.,'degC')},
        'pft_guilds':guilds,'controls':copy.deepcopy(CONTROL)}


def classify(**changes):
    args=inputs();args.update(changes);return b.classify_cell(**args)


def source_fixture_bindings():return {row['path']:row['sha256'] for row in b.source_bindings()}


class BiomeTests(unittest.TestCase):
    def test_exact_retained_legend_and_compatibility_source_read(self):
        records=b.source_bindings()
        for row in records:self.assertEqual(hashlib.sha256(Path(row['path']).read_bytes()).hexdigest(),row['sha256'])
        builder=next(row for row in records if row['path'].endswith('bm1r2_builder/build_bm1r2_1km.py'))
        tree=ast.parse(Path(builder['path']).read_bytes())
        literals={n.targets[0].id:ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign)
            and isinstance(n.targets[0],ast.Name) and n.targets[0].id in ('BROAD_NAMES','FORMATION_NAMES')}
        self.assertEqual(literals['BROAD_NAMES'],b.BROAD_NAMES);self.assertEqual(literals['FORMATION_NAMES'],b.FORMATION_NAMES)
        core=next(row for row in records if row['path'].endswith('bm1r2_core.py'))
        node=next(n for n in ast.parse(Path(core['path']).read_bytes()).body if isinstance(n,ast.Assign)
            and isinstance(n.targets[0],ast.Name) and n.targets[0].id=='FORMATION_COMPATIBILITY')
        matrix=ast.literal_eval(node.value.args[0])
        self.assertEqual({i+1:tuple(j+1 for j,value in enumerate(row) if value) for i,row in enumerate(matrix)},b.COMPATIBILITY)

    def test_primary_formation_compatible_and_not_actual_cover(self):
        result=classify()
        self.assertEqual(result['status'],'MODELLED_POTENTIAL')
        self.assertEqual(result['broad']['primary_code'],3);self.assertEqual(result['formation']['primary_code'],7)
        self.assertIn('COMPETITION_AND_DISTURBANCE_UNRESOLVED',result['uncertainty'])
        self.assertFalse(result['actual_vegetation_used_as_forcing'])

    def test_all_ten_formations_reachable_without_changing_legend(self):
        for code in range(1,11):
            args=inputs(best=code)
            if code==1:args['climate_metrics']['snow_persistence_fraction']['value']=1.
            result=b.classify_cell(**args)
            self.assertEqual(result['formation']['primary_code'],code)
            self.assertIn(code,b.COMPATIBILITY[result['broad']['primary_code']])

    def test_positive_geometric_broad_and_median_formation_independent_oracle(self):
        args=inputs()
        for family,score in zip(args['families'],(.3,.7,.9)):family['formations'][6]['responses'][0]['points']=[[0.,score],[1.,score]]
        result=b.classify_cell(**args)
        expected=(.3*.7*.9)**(1/3)
        self.assertAlmostEqual(result['broad_consensus_support'][3],expected,delta=2e-16)
        self.assertEqual(result['formation_median_support'][7],.7)

    def test_all_family_permutations_produce_identical_result(self):
        args=inputs();reference=b.classify_cell(**args)
        for order in itertools.permutations(args['families']):
            other=dict(args,families=list(order));self.assertEqual(b.classify_cell(**other),reference)

    def test_formation_input_order_has_no_preference(self):
        args=inputs();first=b.classify_cell(**args)
        for family in args['families']:family['formations'].reverse()
        self.assertEqual(b.classify_cell(**args),first)

    def test_equal_scores_keep_ties_and_all_compatible_alternatives(self):
        args=inputs()
        for family in args['families']:
            for rule in family['formations']:rule['responses'][0]['points']=[[0.,.5],[1.,.5]]
        result=b.classify_cell(**args)
        self.assertEqual(result['broad']['tied_codes'],[1,2,3,4])
        self.assertEqual(result['broad']['primary_code'],1)
        self.assertEqual(result['all_plausible_formation_codes'],list(range(2,11)))
        self.assertIn('DISPLAY_TIE_WITHIN_DECLARED_TOLERANCE',result['uncertainty'])
        self.assertNotIn('NUMERICAL_BRACKET_OVERLAP',result['uncertainty'])

    def test_nearby_alternative_across_broad_boundary_retained(self):
        args=inputs()
        for family in args['families']:family['formations'][8]['responses'][0]['points']=[[0.,.88],[1.,.88]]
        result=b.classify_cell(**args)
        self.assertEqual(result['broad']['plausible_codes'],[3,4]);self.assertIn(9,result['all_plausible_formation_codes'])

    def test_physical_zero_never_floored_into_default_biome(self):
        args=inputs()
        for family in args['families']:
            for rule in family['formations']:rule['responses'][0]['points']=[[0.,0.],[1.,0.]]
        result=b.classify_cell(**args)
        self.assertEqual(result['status'],'NO_ADMISSIBLE_CANDIDATE')
        self.assertIsNone(result['broad']['primary_code']);self.assertIsNone(result['formation']['primary_code'])
        self.assertEqual(set(result['broad_consensus_support'].values()),{0.})

    def test_disjoint_family_physical_support_is_conflict_not_false_global_absence(self):
        args=inputs()
        for family,chosen in zip(args['families'],(2,4,10)):
            for rule in family['formations']:rule['responses'][0]['points']=[[0.,1. if rule['code']==chosen else 0.],[1.,1. if rule['code']==chosen else 0.]]
        result=b.classify_cell(**args)
        self.assertEqual(result['status'],'NO_COMMON_FAMILY_SUPPORT')
        self.assertEqual(result['broad']['plausible_codes'],[1,2,4])
        self.assertIn('FAMILY_STRUCTURAL_CONFLICT',result['uncertainty'])

    def test_same_broad_through_disjoint_formations_is_not_false_unique_formation(self):
        args=inputs()
        for family,chosen in zip(args['families'],(5,6,7)):
            for rule in family['formations']:rule['responses'][0]['points']=[[0.,1. if rule['code']==chosen else 0.],[1.,1. if rule['code']==chosen else 0.]]
        result=b.classify_cell(**args)
        self.assertEqual(result['status'],'NO_MEDIAN_FORMATION_SUPPORT')
        self.assertEqual(result['broad']['primary_code'],3)
        self.assertIsNone(result['formation']['primary_code'])
        self.assertEqual(result['all_plausible_formation_codes'],[5,6,7])
        self.assertIn('FAMILY_STRUCTURAL_CONFLICT',result['uncertainty'])

    def test_required_missing_climate_stays_unknown_not_zero_or_outside(self):
        args=inputs();args['climate_metrics'].pop('annual_precipitation_to_reference_pet_ratio');result=b.classify_cell(**args)
        self.assertEqual(result['status'],'UNKNOWN');self.assertIsNone(result['formation']['primary_code'])

    def test_optional_missing_is_neutral_with_explicit_uncertainty(self):
        args=inputs()
        for family in args['families']:family['formations'][6]['responses'].append(response('coldest_month_temperature_c',required=False,unit='degC'))
        result=b.classify_cell(**args)
        self.assertEqual(result['formation']['primary_code'],7)
        self.assertIn('OPTIONAL_PHYSICAL_CONTEXT_UNKNOWN_NEUTRAL',result['uncertainty'])
        for family in result['family_records']:self.assertEqual(family['optional_missing_metrics'],['coldest_month_temperature_c'])

    def test_unknown_required_pft_evaluation_propagates(self):
        args=inputs();args['pft_results'][args['families'][0]['family_id']]['TEMPERATE_TREE']['status']='UNKNOWN'
        result=b.classify_cell(**args);self.assertEqual(result['status'],'UNKNOWN')
        self.assertIsNone(result['formation']['primary_code'])

    def test_failed_pft_is_structural_zero_not_missing(self):
        args=inputs()
        for results in args['pft_results'].values():results['TEMPERATE_TREE']['status']='FAIL'
        result=b.classify_cell(**args)
        self.assertEqual(result['formation_median_support'][7],0.)
        self.assertEqual(result['formation_median_support'][8],0.)
        self.assertNotEqual(result['status'],'UNKNOWN')

    def test_numerical_failure_cannot_be_ecological_pass(self):
        args=inputs();args['pft_results'][args['families'][0]['family_id']]['TEMPERATE_TREE']['status']='NUMERICAL_FAILURE'
        self.assertEqual(b.classify_cell(**args)['status'],'UNKNOWN')

    def test_pft_unknown_score_metric_even_when_other_constraints_pass(self):
        args=inputs()
        for rows in args['pft_results'].values():rows['TEMPERATE_TREE']['metrics'][METRIC]=None
        self.assertEqual(b.classify_cell(**args)['status'],'UNKNOWN')

    def test_nonterrestrial_zero_and_unknown_null_are_distinct(self):
        for kind in ('SEA','CONFIRMED_OPEN_WATER','OUTSIDE'):
            result=classify(domain=dict(DOMAIN,kind=kind));self.assertEqual(result['formation']['primary_code'],0)
            self.assertEqual(result['status'],'NONTERRESTRIAL')
        result=classify(domain=dict(DOMAIN,source_status='UNKNOWN'))
        self.assertEqual(result['status'],'UNKNOWN_DOMAIN');self.assertIsNone(result['formation'])

    def test_f6_requires_independent_macroforest_guild(self):
        args=inputs();args['pft_guilds']['MACROFOREST_TREE']['guild']='TEMPERATE_TREE'
        with self.assertRaisesRegex(ValueError,'F6'):b.classify_cell(**args)

    def test_formation_names_cannot_relabel_incompatible_plant_guilds(self):
        for code,replacement in ((2,['TEMPERATE_TREE']),(3,['GRASS']),(4,['GRASS']),
                (5,['COLD_CONIFER']),(7,['GRASS']),(9,['COLD_CONIFER']),(10,['TEMPERATE_TREE'])):
            args=inputs();args['families'][0]['formations'][code-1]['pft_ids']=replacement
            with self.assertRaisesRegex(ValueError,'F'+str(code)):b.classify_cell(**args)
        args=inputs();args['families'][0]['formations'][4]['pft_operator']='ANY'
        with self.assertRaisesRegex(ValueError,'F5'):b.classify_cell(**args)

    def test_f6_any_cannot_bypass_failed_macroforest_via_ordinary_tree(self):
        args=inputs(best=6)
        for family in args['families']:family['formations'][5]['pft_ids'].append('TEMPERATE_TREE')
        for rows in args['pft_results'].values():rows['MACROFOREST_TREE']['status']='FAIL'
        with self.assertRaisesRegex(ValueError,'F6'):b.classify_cell(**args)
        for family in args['families']:family['formations'][5]['pft_operator']='ALL'
        self.assertEqual(b.classify_cell(**args)['formation_median_support'][6],0.)

    def test_f8_requires_both_tree_and_grass_and_disclaims_realised_mosaic(self):
        args=inputs(best=8);result=b.classify_cell(**args)
        self.assertIn('neither realised mosaic',result['formation_specific_limit'])
        args['families'][0]['formations'][7]['pft_operator']='ANY'
        with self.assertRaisesRegex(ValueError,'F8'):b.classify_cell(**args)

    def test_f1_requires_thermal_and_actual_snow_hypothesis(self):
        args=inputs();args['families'][0]['formations'][0]['responses'].pop()
        with self.assertRaisesRegex(ValueError,'F1'):b.classify_cell(**args)

    def test_f1_nonvegetated_endpoint_does_not_require_successful_plants(self):
        args=inputs(best=1);args['climate_metrics']['snow_persistence_fraction']['value']=1.
        for rows in args['pft_results'].values():
            for value in rows.values():value['status']='FAIL'
        result=b.classify_cell(**args);self.assertEqual(result['formation']['primary_code'],1)

    def test_actual_pft_producer_seasonal_stress_changes_formation_support(self):
        months=(31,28,31,30,31,30,31,31,30,31,30,31)
        calendar=v.Calendar('explicit-365-day',tuple(x*86400 for x in months),86400,E)
        parameters=v.PFTConstraints('TEMPERATE_TREE',5.,.5,(v.Limit('warmest_month_temperature_c',5.,30.,E,S),),(),E,S)
        actual=[]
        for ratio in (.2,1.):
            events=tuple(v.Event(str(i),i,days*86400,15.,ratio*1e-7,1e-7,True,E,S) for i,days in enumerate(months,1))
            result=v.evaluate(v.WaterCapacity(.1,1.,'physical-rooted-column',E,S),calendar,events,parameters,{})
            self.assertEqual(result['status'],'PASS',result)
            args=inputs()
            for rows in args['pft_results'].values():rows['TEMPERATE_TREE']=result
            classified=b.classify_cell(**args);actual.append(classified['formation_median_support'][7])
        self.assertLess(actual[0],actual[1]);self.assertAlmostEqual(actual[0],.2,delta=2e-8)

    def test_pft_metric_unit_and_identity_not_silently_relabelled(self):
        for change in ({'pft_id':'other'},{'schema':'old-proximity-score'},{'metric_units':{METRIC:'kg'}}):
            args=inputs();args['pft_results'][args['families'][0]['family_id']]['TEMPERATE_TREE'].update(change)
            with self.assertRaises(ValueError):b.classify_cell(**args)

    def test_pft_numerical_bracket_maps_interior_response_extremum(self):
        spec={'metric':METRIC,'unit':'1','points':[[0.,0.],[.5,1.],[1.,0.]],'evidence':E}
        score,record=b._score_pft('test',spec,pft_record('test',.5,interval=[.25,.75]))
        self.assertEqual(score,1.);self.assertEqual(record['support_interval'],[.5,1.])

    def test_pft_bracket_can_preserve_alternative_above_midpoint_margin(self):
        scores={1:.5,2:.4};intervals={1:[.45,.55],2:[.3,.6]}
        selected=b._selection(scores,.01,1e-7,.25,intervals)
        self.assertEqual(selected['plausible_codes'],[1,2]);self.assertFalse(selected['numerically_distinct_primary'])

    def test_zero_midpoint_with_positive_interval_is_unresolved_not_absence(self):
        selected=b._selection({1:0.,2:0.},.01,1e-7,.25,{1:[0.,.2],2:[0.,0.]})
        self.assertEqual(selected['status'],'NUMERICAL_SUPPORT_UNRESOLVED');self.assertEqual(selected['plausible_codes'],[1])

    def test_bad_metric_brackets_reject(self):
        args=inputs();args['pft_results'][args['families'][0]['family_id']]['TEMPERATE_TREE']['metric_intervals'][METRIC]=[.9,.8]
        with self.assertRaisesRegex(ValueError,'bracket'):b.classify_cell(**args)

    def test_physical_metric_units_unknown_conflict_and_nan(self):
        for status in ('UNKNOWN','CONFLICT','INCOMPLETE'):
            args=inputs();args['climate_metrics']['annual_precipitation_to_reference_pet_ratio']['source_status']=status
            self.assertEqual(b.classify_cell(**args)['status'],'UNKNOWN')
        for replacement in (climate(float('nan')),climate(unit='kg'),climate(True)):
            args=inputs();args['climate_metrics']['annual_precipitation_to_reference_pet_ratio']=replacement
            with self.assertRaises(ValueError):b.classify_cell(**args)

    def test_physical_names_and_ranges_cannot_be_political_or_impossible(self):
        for name,value,unit in (('political_identity',1.,'1'),('snow_persistence_fraction',1.1,'1'),
                ('annual_precipitation_to_reference_pet_ratio',-1.,'1'),('warmest_month_temperature_c',-273.15,'degC')):
            args=inputs();args['climate_metrics'][name]=climate(value,unit)
            with self.assertRaises(ValueError):b.classify_cell(**args)
        args=inputs();args['families'][0]['formations'][6]['responses'][0]['metric']='agriculture_capacity'
        with self.assertRaises(ValueError):b.classify_cell(**args)
        args=inputs();args['families'][0]['pft_score_rules']['TEMPERATE_TREE']['metric']='political_identity'
        with self.assertRaises(ValueError):b.classify_cell(**args)

    def test_metric_unit_contract_matches_actual_producer(self):
        self.assertEqual(b.PFT_METRIC_UNITS,v.METRIC_UNITS)

    def test_actual_annual_water_and_formed_solum_fields_permitted(self):
        args=inputs()
        for name in ('annual_precipitation_m','annual_reference_pet_m','mineral_solum_depth_m'):
            args['climate_metrics'][name]=climate(.5,'m')
        self.assertEqual(b.classify_cell(**args)['status'],'MODELLED_POTENTIAL')
        for name in ('annual_precipitation_m','annual_reference_pet_m','mineral_solum_depth_m'):
            broken=copy.deepcopy(args);broken['climate_metrics'][name]['value']=-1.
            with self.assertRaises(ValueError):b.classify_cell(**broken)

    def test_strict_family_count_rule_inventory_and_input_whitelist(self):
        args=inputs();args['families'].pop()
        with self.assertRaises(ValueError):b.classify_cell(**args)
        args=inputs();args['families'][0]['formations'].pop()
        with self.assertRaises(ValueError):b.classify_cell(**args)
        args=inputs();args['families'][0]['political_mask']='not allowed'
        with self.assertRaises(ValueError):b.classify_cell(**args)

    def test_bad_response_configuration_and_bool_controls(self):
        for points in ([[0.,0.],[0.,1.]],[[0.,0.],[1.,2.]],[[False,0.],[1.,1.]]):
            with self.assertRaises(ValueError):b.response(.5,points,'HOLD')
        with self.assertRaises(ValueError):classify(controls=dict(CONTROL,tie_tolerance=True))
        with self.assertRaises(ValueError):classify(controls=dict(CONTROL,tie_tolerance=.1))

    def test_affine_response_endpoints_and_exterior_policy(self):
        points=[[-10.,0.],[20.,1.]]
        self.assertEqual(b.response(-10.,points,'HOLD'),0.);self.assertEqual(b.response(20.,points,'HOLD'),1.)
        self.assertEqual(b.response(5.,points,'HOLD'),.5)
        self.assertEqual(b.response(30.,points,'ZERO'),0.);self.assertEqual(b.response(30.,points,'HOLD'),1.)
        self.assertEqual(b.response(0.,[[-1e308,0.],[1e308,1.]],'HOLD'),.5)

    def test_output_strict_json_contains_no_nodata_nan(self):
        for result in (classify(),classify(domain=dict(DOMAIN,kind='SEA')),classify(domain=dict(DOMAIN,kind='UNKNOWN'))):
            json.loads(json.dumps(result,allow_nan=False))

    def test_local_adjacency_reports_real_difference_without_mutating(self):
        left=b.classify_cell(**inputs(7));args=inputs(10);args['cell_id']='cell-b';right=b.classify_cell(**args)
        before=copy.deepcopy([left,right]);edge={'a':'cell-a','b':'cell-b','length_m':1000.,'evidence':E}
        result=b.transition_diagnostics([left,right],[edge])
        self.assertTrue(result['edges'][0]['different_primary_formation']);self.assertFalse(result['classes_modified'])
        self.assertEqual([left,right],before)

    def test_spatial_permutation_and_partition_do_not_change_cells(self):
        recipes=[dict(inputs(code),cell_id='cell-'+str(code)) for code in (2,7,10)]
        def run(rows):return {row['cell_id']:b.classify_cell(**row) for row in rows}
        whole=run(recipes)
        for order in itertools.permutations(recipes):self.assertEqual(run(order),whole)
        for cut in (1,2):self.assertEqual(run(recipes[:cut])|run(recipes[cut:]),whole)

    def test_declared_spatial_edges_are_order_independent_without_wrap_or_smoothing(self):
        cells=[b.classify_cell(**dict(inputs(code),cell_id='cell-'+str(code))) for code in (2,7,10)]
        edges=[{'a':'cell-2','b':'cell-7','length_m':100.,'evidence':E},
               {'a':'cell-7','b':'cell-10','length_m':200.,'evidence':E}]
        expected=b.transition_diagnostics(cells,edges)
        actual=b.transition_diagnostics(list(reversed(cells)),list(reversed(edges)))
        self.assertEqual(list(reversed(actual['edges'])),expected['edges'])
        self.assertEqual(len(actual['edges']),2)
        self.assertEqual([row['formation']['primary_code'] for row in cells],[2,7,10])

    def test_unknown_neighbour_not_zero_class_or_spurious_boundary(self):
        left=classify();right=classify(cell_id='other',domain=dict(DOMAIN,kind='UNKNOWN'))
        result=b.transition_diagnostics([left,right],[{'a':'cell-a','b':'other','length_m':1.,'evidence':E}])
        self.assertIsNone(result['edges'][0]['different_primary_formation'])

    def test_duplicate_self_missing_and_nonpositive_adjacency_reject(self):
        left=classify();right=classify(cell_id='other');edge={'a':'cell-a','b':'other','length_m':1.,'evidence':E}
        for edges in ([edge,edge],[dict(edge,b='cell-a')],[dict(edge,b='missing')],[dict(edge,length_m=0)]):
            with self.assertRaises(ValueError):b.transition_diagnostics([left,right],edges)


if __name__=='__main__':unittest.main()
