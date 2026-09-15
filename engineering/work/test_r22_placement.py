"""Focused reference placement, source replacement and actual finite freight."""
from copy import deepcopy
from fractions import Fraction as F
import tempfile
import unittest

from work.generator_upgrade_r21 import _native_human as human
from work.generator_upgrade_r22 import placement as m, provenance as p

SOURCE = {'source_status': 'SYNTHETIC TEST', 'evidence_id': 'explicit numerical connection fixture, not Diadem placement'}


def fixture(total=20):
    geography = {'context': {'world_id': 'test', 'snapshot_id': 'seed', 'spatial_frame_id': 'local',
        'vertical_reference': 'test-z', 'scenario_id': 'SYNTHETIC_HUMAN_REFERENCE'},
        'supports': {'upper': {'xy_m': [0, 0]}, 'lower': {'xy_m': [100, 0]}},
        'state_sha256': 'a'*64, 'seed_scientific_sha256': 'b'*64,
        'source_status': 'SYNTHETIC TEST', 'role': 'SYNTHETIC TEST'}
    gh = p.sha(geography)
    population = dict(SOURCE, population_id='humans', counting_unit='HUMAN_INDIVIDUAL',
                      scope_id='test', count=total, geography_sha256=gh)
    candidates = [dict(SOURCE, settlement_id=s, support_id=s, weight='1', max_population=total,
                       eligible=True, geography_sha256=gh) for s in ('upper', 'lower')]
    policy = dict(SOURCE, allocation='CAPPED_WEIGHTED_LARGEST_REMAINDER', tie_break='SETTLEMENT_ID_ASCENDING')
    return population, candidates, geography, policy


class PlacementTests(unittest.TestCase):
    def test_capped_exact_and_replacement(self):
        pop, sites, geo, policy = fixture(23)
        sites[0]['max_population'] = 3
        sites[1]['max_population'] = 17
        result = m.place(pop, sites, geography=geo, policy=policy, cache=False)
        self.assertEqual((result['placed'], result['unplaced']), (20, 3))
        self.assertEqual([r['population'] for r in result['settlements']], [3, 17])
        changed = deepcopy(geo); changed['state_sha256'] = 'c'*64
        with self.assertRaisesRegex(ValueError, 'different geography'):
            m.place(pop, sites, geography=changed, policy=policy, cache=False)

    def test_unknown_is_not_zero_and_working_is_usable(self):
        pop, sites, geo, policy = fixture(21)
        sites[0]['source_status'] = 'Provisional'
        result = m.place(pop, sites, geography=geo, policy=policy, cache=False)
        self.assertEqual(result['status'], 'MODELLED')
        self.assertEqual(result['settlements'][0]['source_status'], 'Provisional')
        sites[1]['weight'] = None
        result = m.place(pop, sites, geography=geo, policy=policy, cache=False)
        self.assertEqual((result['status'], result['unplaced']), ('UNKNOWN', 21))

    def test_reference_join_never_redistributes(self):
        pop, _, geo, _ = fixture(20)
        gh = p.sha(geo)
        assignments = [dict(SOURCE, pool_id=k, count=n, count_basis='DISJOINT_HUMAN_IDENTITIES',
                            service_class='LIVING_HUMANS') for k,n in [('known', 7), ('missing', 8)]]
        crosswalk = {'known': dict(SOURCE, settlement_id='upper', support_id='upper', usable=True, geography_sha256=gh)}
        result = m.assign_reference(pop, assignments, crosswalk, geography=geo, cache=False)
        self.assertEqual((result['placed'], result['unplaced'], result['unresolved_reference_remainder']), (7, 13, 5))
        self.assertEqual(result['settlements'][0]['population'], 7)
        with self.assertRaisesRegex(ValueError, 'one count per disjoint'):
            m.assign_reference(pop, assignments+assignments[:1], crosswalk, geography=geo, cache=False)

    def test_actual_population_demand_freight_and_cached_unknown(self):
        pop, sites, geo, policy = fixture()
        placed = m.place(pop, sites, geography=geo, policy=policy, cache=False)
        template = human.reference_inputs()
        for row in template['events']:
            for key in ('water_demands','water_demand_order','food_demands','food_demand_order'):
                row[key] = []
        rates = dict(SOURCE, unit_basis='PER_HUMAN_INDIVIDUAL_PER_SECOND', water_m3='1/100',
                     food_kg={'synthetic-food':'1/100'}, food_weight_per_kg={'synthetic-food':'1'})
        with tempfile.TemporaryDirectory(prefix='r22-placement-') as root:
            result = m.connect_human(placed, template, rates, geography_sha256=p.sha(geo), cache_root=root)
            self.assertEqual(result['status'], 'COMPLETE')
            self.assertEqual(result['human']['accepted_events'], 2)
            self.assertEqual(result['native_inputs']['network'], template['network'])
            demands = result['native_inputs']['events'][0]['food_demands']
            self.assertEqual(sum(F(r['required_kg']) for r in demands), F(2))
            self.assertEqual(result, m.connect_human(placed, template, rates, geography_sha256=p.sha(geo), cache_root=root))
            template['initial_state']['water_m3']['upper'] = None
            unknown = m.connect_human(placed, template, rates, geography_sha256=p.sha(geo), cache_root=root)
            self.assertEqual(unknown['status'], 'UNKNOWN')
            self.assertEqual(unknown, m.connect_human(placed, template, rates, geography_sha256=p.sha(geo), cache_root=root))


if __name__ == '__main__':
    unittest.main()
