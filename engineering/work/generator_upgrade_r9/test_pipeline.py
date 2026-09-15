"""Stage joins, reporting and replay guards; actual parent created once."""
from copy import deepcopy
from fractions import Fraction as F
import math
from types import SimpleNamespace
import unittest
from . import binding, pipeline as p, upstream as u


class PipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bundle=binding.load(); cls.template=cls.bundle.reference.recipe(cls.bundle)
        cls.parent=cls.bundle.parent.run(cls.template['parent_recipe'])
        cls.env=u.project(cls.bundle,cls.parent,cls.template['seasons'])
        cls.scenario=next(iter(cls.env['scenarios']))
        # Unit-level replay tests deliberately reuse the actual parent result.
        # The release verifier separately executes fresh source-bound public runs.
        cls.cached=SimpleNamespace(storage=cls.bundle.storage,source_sha256=cls.bundle.source_sha256,
            parent=SimpleNamespace(source_sha256=cls.bundle.parent.source_sha256,run=lambda recipe:cls.parent))
        cls.full=p.run(cls.cached,cls.template)

    def setUp(self): self.recipe=deepcopy(self.template)

    def unit(self,organism='TEST-ANIMAL',season='warm',environment=None):
        return p.evaluate_unit(self.bundle,self.recipe,self.env if environment is None else environment,self.scenario,organism,season)

    def test_actual_reference_units_and_incomplete_real_roster(self):
        c=self.full['roster_coverage']
        self.assertEqual(c['completed_units'],684); self.assertTrue(c['all_units_executed'])
        self.assertFalse(c['all_required_products_complete'])
        self.assertTrue(c['organisms']['TEST-ANIMAL']['required_products_complete'])
        self.assertTrue(c['organisms']['TEST-PLANT']['required_products_complete'])
        self.assertEqual(sum(not v['required_products_complete'] for v in c['organisms'].values()),34)

    def test_exceptions_are_not_unknown_wild_density(self):
        self.assertIsNone(self.unit('HS14')['wild_expected_individuals'])
        self.assertEqual(self.unit('HS19')['wild_expected_individuals'],'0')
        self.assertEqual(self.unit('HS1')['status'],'INCOMPLETE_BIOLOGICAL_RULES')

    def test_duplicate_retained_taxon_rejected(self):
        self.recipe['organisms']['HS1-DUPLICATE']=deepcopy(self.recipe['organisms']['HS1'])
        with self.assertRaisesRegex(ValueError,'duplicate retained'): p.parse(self.bundle,self.recipe)

    def test_retained_identity_and_exception_not_relabelled(self):
        for field,value in (('name','new name'),('retained_hs',True),('applicability','SPATIAL')):
            recipe=deepcopy(self.recipe); recipe['organisms']['HS14'][field]=value
            with self.assertRaises(ValueError): p.parse(self.bundle,recipe)

    def test_no_anonymous_biological_defaults(self):
        self.recipe['organisms']['TEST-ANIMAL']['source_status']='WORKING NON-CANON'
        with self.assertRaisesRegex(ValueError,'bound source'): p.parse(self.bundle,self.recipe)

    def test_hs4_rooted_adult_cannot_acquire_walking_rule(self):
        taxon=self.recipe['organisms']['HS4']
        taxon['seasons']=deepcopy(self.recipe['organisms']['TEST-ANIMAL']['seasons'])
        for season in taxon['seasons'].values(): season['rule']['species_id']='HS4'
        with self.assertRaisesRegex(ValueError,'rooted adult'): p.parse(self.bundle,self.recipe)

    def test_missing_requested_season_not_silently_skipped(self):
        del self.recipe['organisms']['TEST-ANIMAL']['seasons']['cold']
        with self.assertRaises(ValueError): p.parse(self.bundle,self.recipe)

    def test_expected_count_independently_uses_occupied_area_not_support(self):
        row=self.unit(); case=row['range_endpoint_cases']['lower_habitat']
        for ident,cell in case['cells'].items():
            support=row['habitat'][ident]['interval'][0]
            probability=1/(1+math.exp(-(-1+3*support)))
            self.assertAlmostEqual(cell['occupancy_probability'],probability,places=14)
            area=F(2000000 if ident=='lower' else 1000000)
            expected=area*F(1,2)*F(1,2)*F(cell['occupancy_probability'])*F(1,10000)
            self.assertEqual(F(cell['expected_individuals']['exact']),expected)

    def test_seeded_snapshot_and_common_random_numbers(self):
        first=self.unit()['cells']; self.assertEqual(first,self.unit()['cells'])
        other=next(s for s in self.env['scenarios'] if s!=self.scenario)
        second=p.evaluate_unit(self.bundle,self.recipe,self.env,other,'TEST-ANIMAL','warm')['cells']
        for ident in first:
            self.assertEqual(first[ident]['draw_uniform_exact'],second[ident]['draw_uniform_exact'])
            self.assertIsNone(first[ident]['observed_presence'])
        self.recipe['placement_seed']='a new explicit seed'
        changed=self.unit()['cells']
        self.assertNotEqual(first['lower']['draw_uniform_exact'],changed['lower']['draw_uniform_exact'])

    def test_actual_occurrence_overlay_is_not_forcing(self):
        self.recipe['actual_occurrence_overlays']=[{'overlay_id':'test-observation','organism_id':'TEST-ANIMAL','cell_id':'lower','evidence':'test overlay only','source_status':'SYNTHETIC TEST'}]
        altered=p.run(self.cached,self.recipe)
        self.assertEqual(altered['state']['results'],self.full['state']['results'])
        self.assertFalse(altered['observations_used_as_forcing'])
        self.assertEqual(len(altered['actual_occurrence_overlays']),1)

    def test_edge_requires_actual_declared_physical_adjacency(self):
        self.recipe['organisms']['TEST-ANIMAL']['seasons']['warm']['edges'][0]['target']='elsewhere'
        with self.assertRaisesRegex(ValueError,'physical adjacency'): self.unit()

    def test_edge_uses_actual_parent_length(self):
        cs,edges,*rest=p.inputs(self.bundle,self.recipe,self.env,self.scenario,'TEST-ANIMAL','warm',0)
        self.assertEqual(edges[0].travel_cost,F(1000))

    def test_arrival_season_unsuitable_endpoint_blocks_transfer(self):
        cold=self.recipe['organisms']['TEST-ANIMAL']['seasons']['cold']
        cold['requirements']=[{'metric':'temperature_mean_c','unit':'degC','points':[[-100,0],[100,0]],'outside':'HOLD','evidence':'test winter exclusion'}]
        movement=self.unit()['movement_endpoint_cases']['lower_habitat']
        self.assertFalse(any(r.get('paths') for r in movement['requests']))

    def test_prescribed_total_conflict_blocks_movement(self):
        warm=self.recipe['organisms']['TEST-ANIMAL']['seasons']['warm']
        warm['prescribed_total']={'expected_individuals':0,'evidence':'test contradictory total','source_status':'SYNTHETIC TEST'}
        row=self.unit()
        self.assertEqual(row['status'],'UNKNOWN_OR_CONFLICT')
        self.assertEqual(row['movement_endpoint_cases']['lower_habitat']['status'],'UNKNOWN')
        self.assertFalse(row['movement_endpoint_cases']['lower_habitat']['requests'])

    def test_arrival_prescribed_total_conflict_blocks_movement(self):
        self.recipe['organisms']['TEST-ANIMAL']['seasons']['cold']['prescribed_total']={'expected_individuals':0,'evidence':'test arrival contradiction','source_status':'SYNTHETIC TEST'}
        movement=self.unit()['movement_endpoint_cases']['lower_habitat']
        self.assertEqual(movement['status'],'UNKNOWN'); self.assertFalse(movement['requests'])

    def test_prescribed_total_extra_fields_not_ignored(self):
        self.recipe['organisms']['TEST-ANIMAL']['seasons']['warm']['prescribed_total']={'expected_individuals':0,'evidence':'test','source_status':'SYNTHETIC TEST','rescale':True}
        with self.assertRaisesRegex(ValueError,'exact fields'): self.unit()

    def test_threshold_interval_does_not_claim_endpoint_envelope(self):
        env=deepcopy(self.env)
        for cell in env['scenarios'][self.scenario]['seasons']['warm']['cells'].values():
            cell['metrics']['pft.grass.seasonal_water_ratio']=u.metric(0.1,'1','test numerical bracket',[0.05,0.15])
        row=self.unit(environment=env)
        self.assertEqual(row['status'],'UNKNOWN_OR_CONFLICT')
        for cell in row['cells'].values():
            self.assertIsNone(cell['modelled_presence']); self.assertIsNone(cell['occupancy_probability_interval'])

    def test_unknown_origin_not_all_cells_accessible(self):
        self.recipe['organisms']['TEST-ANIMAL']['seasons']['warm']['origins']=None
        row=self.unit()
        self.assertTrue(all(c['modelled_presence'] is None for c in row['cells'].values()))

    def test_overlap_keeps_test_and_real_denominators_separate(self):
        product=self.full['overlap_products'][self.scenario]['warm']
        for cell in product['RETAINED']['cells'].values():
            self.assertEqual(cell['eligible_taxa'],34); self.assertEqual(cell['unknown_or_unexecuted_taxa'],34)
            self.assertEqual(cell['evaluated_presence_taxa'],0); self.assertIsNone(cell['observed_richness'])
        for cell in product['SYNTHETIC_TEST']['cells'].values():
            self.assertEqual(cell['eligible_taxa'],2); self.assertEqual(cell['evaluated_presence_taxa'],2)
            self.assertEqual(cell['modelled_present_taxa']+cell['modelled_absent_taxa'],2)

    def test_partial_coverage_never_completes_organism_early(self):
        partial=p.run(self.cached,self.recipe,stop_after=1)
        self.assertFalse(partial['roster_coverage']['all_units_executed'])
        self.assertFalse(any(v['required_products_complete'] for v in partial['roster_coverage']['organisms'].values()))

    def test_replay_equivalence_and_rechecksummed_forgery_rejection(self):
        part=p.run(self.cached,self.recipe,stop_after=17)
        cp={'schema':binding.CHECKPOINT_SCHEMA,'source_sha256':self.bundle.source_sha256,
            'recipe_sha256':part['recipe_sha256'],'state':part['state'],'state_sha256':u.digest(part['state'])}
        self.assertEqual(self.full,p.run(self.cached,self.recipe,resume=cp))
        forged=deepcopy(cp); forged['state']['environment_sha256']='0'*64; forged['state_sha256']=u.digest(forged['state'])
        with self.assertRaisesRegex(ValueError,'actual upstream/spatial replay'): p.run(self.cached,self.recipe,resume=forged)

    def test_whole_unit_cursor_not_boolean_or_fraction(self):
        for value in (True,-1,0.5,685):
            with self.assertRaises(ValueError): p.run(self.cached,self.recipe,stop_after=value)

    def test_parent_separate_preserves_original_storage_guard(self):
        self.assertNotIn('parent_result',self.full)
        self.assertEqual(self.full['parent_result_sha256'],u.digest(self.parent))
        self.assertLess(len(self.bundle.storage.encoded(self.full)),8*1024*1024)
        self.assertLess(len(self.bundle.storage.encoded(self.parent)),8*1024*1024)

    def test_rational_quantities_reject_boolean_and_unbounded_strings(self):
        for value in (True,False,{},'1'*257):
            with self.assertRaises(ValueError): p.quantity(value)


if __name__=='__main__': unittest.main()
