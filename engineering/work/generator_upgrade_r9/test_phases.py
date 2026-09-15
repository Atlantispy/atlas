"""Explicit-stock flow and actual-parent same-cohort conservation checks."""
from copy import deepcopy
from dataclasses import replace
from fractions import Fraction as F
import unittest
from . import binding, pipeline, upstream, spatial as s, phases

E='SYNTHETIC TEST: finite named cohort'; K='SYNTHETIC TEST'


class ExplicitStockTests(unittest.TestCase):
    def setUp(self):
        self.cells=tuple(s.Cell(k,F(100),1.,F(1),True,E,K) for k in ('a','b'))
        self.edges=(s.Edge('ab','a','b',F(1),True,F(20),E,K),)
        self.rule=s.SpeciesRule('test',.1,None,None,None,None,F(10),'m','SEASONAL_MOVEMENT',E,K)
        self.origins=(s.Origin('a',E,K),)
        self.stock=s.ExplicitStock('test','test animal','same-cohort','explicit domain','source-snapshot','warm',(('a',F(8)),('b',F(2))),E,K)

    def run_transfer(self,**kw):
        return s.route_movements(self.cells,self.edges,self.origins,self.rule,(s.MovementRequest('move','a','b',F(5),0,E,K),),
            season_id='warm',receiving_capacity={'a':F(20),'b':F(20)},evidence=E,source_status=K,
            declared_departure_stock=kw.pop('declared_departure_stock',self.stock),**kw)

    def test_declared_stock_does_not_need_or_invent_density(self):
        result=self.run_transfer()
        self.assertEqual(result['status'],'MODELLED_FEASIBLE_ALLOCATION')
        self.assertEqual(F(result['cells']['a']['final_expected_individuals']['exact']),3)
        self.assertEqual(F(result['cells']['b']['final_expected_individuals']['exact']),7)
        self.assertIn('no density',result['stock_basis'])

    def test_phase_and_organism_identity_are_not_interchangeable(self):
        for key,value in (('phase_id','cold'),('species_id','different')):
            with self.assertRaises(ValueError): self.run_transfer(declared_departure_stock=replace(self.stock,**{key:value}))

    def test_mutable_duplicate_or_boolean_counts_rejected(self):
        for counts in ([('a',F(1))],(('a',1),('a',2)),(('a',True),)):
            with self.assertRaises(ValueError): replace(self.stock,counts=counts)

    def test_complete_source_cells_required(self):
        with self.assertRaises(ValueError): self.run_transfer(declared_departure_stock=replace(self.stock,counts=(('a',F(10)),)))

    def test_cannot_mix_density_and_explicit_stock_modes(self):
        self.rule=replace(self.rule,density_per_occupied_m2=F(1))
        with self.assertRaisesRegex(ValueError,'density-free'): self.run_transfer()

    def test_explicit_stock_cannot_overrule_failed_source_habitat(self):
        self.cells=(replace(self.cells[0],habitat_support=0.),self.cells[1])
        row=self.run_transfer(); self.assertEqual(row['status'],'UNKNOWN'); self.assertFalse(row['paths'])

    def test_explicit_stock_cannot_overrule_unknown_provenance(self):
        row=self.run_transfer(declared_departure_stock=replace(self.stock,source_status='UNKNOWN'))
        self.assertEqual(row['status'],'UNKNOWN'); self.assertFalse(row['paths'])

    def test_movement_hash_binds_stock_and_counting_unit(self):
        first=self.run_transfer()
        second=self.run_transfer(declared_departure_stock=replace(self.stock,counting_unit='different defined unit'))
        self.assertNotEqual(first['movement_inputs_sha256'],second['movement_inputs_sha256'])

    def test_unresolved_cell_stock_not_zero(self):
        result=self.run_transfer(declared_departure_stock=replace(self.stock,counts=(('a',None),('b',F(2)))))
        self.assertEqual(result['status'],'UNKNOWN')
        self.assertIsNone(result['cells']['a']['initial_expected_individuals'])

    def test_residents_left_in_failed_arrival_habitat_are_not_complete(self):
        destination=(replace(self.cells[0],habitat_support=0.),self.cells[1])
        result=self.run_transfer(destination_cells=destination,destination_edges=self.edges,destination_origins=self.origins,
            destination_rule=self.rule,destination_season_id='cold')
        self.assertEqual(result['status'],'CONFLICT')
        self.assertEqual(result['cells']['a']['arrival_persistence_status'],'CONFLICT')
        self.assertEqual(F(result['cells']['a']['final_expected_individuals']['exact']),3)
        self.assertEqual(sum(F(v['final_expected_individuals']['exact']) for v in result['cells'].values()),10)

    def test_unknown_resident_arrival_persistence_stays_unknown(self):
        destination=(replace(self.cells[0],habitat_support=None),self.cells[1])
        result=self.run_transfer(destination_cells=destination,destination_edges=self.edges,destination_origins=self.origins,
            destination_rule=self.rule,destination_season_id='cold')
        self.assertEqual(result['status'],'UNKNOWN')
        self.assertEqual(result['cells']['a']['arrival_persistence_status'],'UNKNOWN')


class ConnectedPhaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bundle=binding.load(); cls.recipe=cls.bundle.reference.recipe(cls.bundle)
        cls.parent=cls.bundle.parent.run(cls.recipe['parent_recipe'])
        cls.env=upstream.project(cls.bundle,cls.parent,cls.recipe['seasons'])
        cls.results={}
        for scenario in cls.env['scenarios']:
            cls.results[scenario]={'TEST-ANIMAL':{season:pipeline.evaluate_unit(cls.bundle,cls.recipe,cls.env,scenario,'TEST-ANIMAL',season) for season in ('warm','cold')}}
        cls.abundance=pipeline.abundance_products(cls.recipe,cls.env,cls.results)
        cls.chains=phases.run(cls.bundle,cls.recipe,cls.env,cls.abundance,pipeline.inputs)

    def test_two_actual_seasonal_phases_conserve_same_32_animals(self):
        chain=self.chains['TEST-ANIMAL-SAME-COHORT']
        self.assertEqual(len(chain['scenarios']),9)
        for endpoints in chain['scenarios'].values():
            for row in endpoints.values():
                self.assertEqual(row['status'],'MODELLED_CONSERVED_COHORT')
                self.assertEqual(F(row['total_expected_entities']['exact']),32)
                self.assertEqual(row['completed_phase_count'],2)
                self.assertEqual(F(row['phases'][0]['result']['cells']['lower']['final_expected_individuals']['exact']),11)
                self.assertEqual(F(row['phases'][0]['result']['cells']['upper']['final_expected_individuals']['exact']),21)
                self.assertEqual(row['initial_counts'],row['final_committed_counts'])
                self.assertEqual(F(row['conservation_residual_expected_entities']['exact']),0)

    def test_actual_arrival_counts_become_next_departure_not_new_density(self):
        for endpoints in self.chains['TEST-ANIMAL-SAME-COHORT']['scenarios'].values():
            for row in endpoints.values():
                first,second=[p['result'] for p in row['phases']]
                for ident in ('lower','upper'):
                    self.assertEqual(first['cells'][ident]['final_expected_individuals'],second['cells'][ident]['initial_expected_individuals'])
                self.assertEqual(second['declared_departure_stock']['cohort_id'],'TEST-ANIMAL-SAME-COHORT')

    def test_same_allocation_cannot_be_renamed_as_another_organism(self):
        recipe=deepcopy(self.recipe); recipe['cohort_chains'][0]['organism_id']='TEST-PLANT'
        with self.assertRaises(ValueError): phases.run(self.bundle,recipe,self.env,self.abundance,pipeline.inputs)

    def test_declared_transition_cannot_change_silently(self):
        recipe=deepcopy(self.recipe); recipe['organisms']['TEST-ANIMAL']['seasons']['warm']['movement']['destination_season_id']='warm'
        with self.assertRaises(ValueError): phases.run(self.bundle,recipe,self.env,self.abundance,pipeline.inputs)

    def test_cap_remainder_stays_unplaced_across_all_phases(self):
        recipe=deepcopy(self.recipe)
        recipe['abundance_scenarios'][1]['model']['cells'][0]['capacity_expected_entities']=10
        abundance=pipeline.abundance_products(recipe,self.env,self.results)
        result=phases.run(self.bundle,recipe,self.env,abundance,pipeline.inputs)
        for endpoints in result['TEST-ANIMAL-SAME-COHORT']['scenarios'].values():
            for row in endpoints.values():
                self.assertEqual(F(row['unplaced_expected_entities']['exact']),6)
                self.assertEqual(F(row['total_expected_entities']['exact']),32)
                self.assertEqual(row['status'],'INCOMPLETE_UNPLACED')

    def test_missing_footprint_does_not_create_phase_stock(self):
        recipe=deepcopy(self.recipe); recipe['abundance_scenarios'][1]['model']['cells']=None
        abundance=pipeline.abundance_products(recipe,self.env,self.results)
        result=phases.run(self.bundle,recipe,self.env,abundance,pipeline.inputs)
        for endpoints in result['TEST-ANIMAL-SAME-COHORT']['scenarios'].values():
            for row in endpoints.values(): self.assertEqual(row['status'],'UNKNOWN'); self.assertFalse(row['phases'])

    def test_real_scope_stock_is_unplaced_and_bonds_separate(self):
        record=self.abundance['owner_stock_register']
        self.assertEqual(F(record['HS13']['allocation']['unplaced_expected_entities']['exact']),500)
        self.assertEqual(record['HS13']['source_population_reference']['active_bonds_reference'],350)
        self.assertEqual(F(record['HS19']['allocation']['unplaced_expected_entities']['exact']),1)
        self.assertTrue(record['HS19']['not_wild_generation'])
        self.assertIsNone(record['bannerhaus_slope_pines']['allocation']['total_expected_entities'])

    def test_abundance_cannot_bypass_unknown_actual_biology(self):
        recipe=deepcopy(self.recipe); recipe['organisms']['TEST-ANIMAL']['seasons']['warm']=None
        results=deepcopy(self.results)
        for scenario in results: results[scenario]['TEST-ANIMAL']['warm']=pipeline.evaluate_unit(self.bundle,recipe,self.env,scenario,'TEST-ANIMAL','warm')
        abundance=pipeline.abundance_products(recipe,self.env,results)
        for value in abundance['alternative_scenarios']['PRESCRIBED_STOCK']['physical_scenarios'].values():
            self.assertEqual(value['model']['status'],'UNKNOWN')
            self.assertEqual(F(value['model']['unplaced_expected_entities']['exact']),32)

    def test_phase_cannot_complete_with_residents_in_failed_arrival_habitat(self):
        environment=deepcopy(self.env)
        for scenario in environment['scenarios'].values():
            scenario['seasons']['cold']['cells']['lower']['metrics']['mineral_solum_m']=upstream.metric(0,'m','explicit arrival exclusion')
        result=phases.run(self.bundle,self.recipe,environment,self.abundance,pipeline.inputs)
        for endpoints in result['TEST-ANIMAL-SAME-COHORT']['scenarios'].values():
            for row in endpoints.values():
                self.assertEqual(row['status'],'UNKNOWN'); self.assertEqual(row['completed_phase_count'],0)
                self.assertEqual(F(row['conservation_residual_expected_entities']['exact']),0)
                self.assertEqual(sum(F(v['exact']) for v in row['final_committed_counts'].values()),32)


if __name__=='__main__': unittest.main()
