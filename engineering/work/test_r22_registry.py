"""One public graph connection, authenticated reuse and targeted invalidation."""
from copy import deepcopy
import tempfile
import unittest
from work.test_r22_placement import fixture
from work.generator_upgrade_r22 import registry
from work.generator_upgrade_r21 import _native_human as human, _snapshot_contract as snapshot
from work.generator_upgrade_r22 import provenance as p


def recipe():
    population, sites, geography, policy = fixture()
    port = {'quantity': 'BOUND_COMPONENT_RECEIPT', 'unit': '1', 'support_id': 'test-supports', 'temporal_support': 'test-window'}
    template = human.reference_inputs()
    for event in template['events']:
        for name in ('water_demands','water_demand_order','food_demands','food_demand_order'): event[name] = []
    rates = {'source_status': 'SYNTHETIC TEST', 'evidence_id': 'explicit graph test',
        'unit_basis': 'PER_HUMAN_INDIVIDUAL_PER_SECOND', 'water_m3': '1/100',
        'food_kg': {'synthetic-food': '1/100'}, 'food_weight_per_kg': {'synthetic-food': '1'}}
    def stage(identity, operation, category, inputs, dependencies):
        return {'stage_id': identity, 'category': category, 'producer_id': operation,
            'producer_sha256': registry.registration(operation, port)['sha256'], 'inputs': inputs,
            'dependencies': dependencies, 'outputs': {'result': port}, 'missing_inputs': [],
            'mode': 'GENERATED', 'acceptance': {'status': 'PENDING', 'evidence': 'Numerical wiring only, no domain acceptance'}}
    context = dict(geography['context'], calendar_id='explicit-test-calendar')
    return {'schema': 'diadem.snapshot-graph-recipe.r11', 'context': context,
        'required_categories': ['populations', 'infrastructure_connectivity'], 'evidence': 'two-stage integration fixture',
        'stages': [stage('place', 'population_scenario', 'populations',
            dict(population=population,candidates=sites,geography=geography,policy=policy), {}),
            stage('serve', 'human_service', 'infrastructure_connectivity',
                dict(human_inputs=template, rates=rates, geography_sha256=p.sha(geography)),
                {'placement': {'stage_id': 'place', 'output': 'result', 'port': port}})]}


class RegistryTests(unittest.TestCase):
    def test_connected_graph_cache_checkpoint_and_changed_demand(self):
        graph = recipe()
        with tempfile.TemporaryDirectory(prefix='r22-registry-') as root:
            cold = registry.run(graph, cache_root=root)
            warm = registry.run(graph, cache_root=root)
            self.assertEqual(cold['graph'], warm['graph'])
            self.assertEqual(warm['execution']['computed_stage_ids'], [])
            self.assertEqual(warm['execution']['reused_stage_ids'], ['place','serve'])
            saved = cold['elapsed_seconds']-warm['elapsed_seconds']
            print({'r22_public_graph_cold_seconds': cold['elapsed_seconds'],
                   'warm_seconds': warm['elapsed_seconds'], 'saved_seconds': saved,
                   'saved_percent': 100*saved/cold['elapsed_seconds'],
                   'scope': 'two-stage synthetic placement-to-finite-freight graph, not whole-world performance'})
            self.assertEqual(cold['graph']['state']['rows']['serve']['product']['values']['result']['status'], 'COMPLETE')
            resumed = registry.run(graph, cache_root=root, resume=snapshot.checkpoint(cold['graph']))
            self.assertEqual(resumed['graph'], cold['graph'])
            changed = deepcopy(graph)
            changed['stages'][1]['inputs']['rates']['water_m3'] = '1/200'
            rerun = registry.run(changed, cache_root=root)
            self.assertEqual(rerun['execution']['computed_stage_ids'], ['serve'])
            self.assertEqual(rerun['execution']['reused_stage_ids'], ['place'])
            self.assertFalse(rerun['whole_diadem_year_verified'])


if __name__ == '__main__': unittest.main()
