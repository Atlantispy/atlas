"""Bounded connected reference/cache and final-owner acceptance comparisons.

Run in a fresh Python process after R20 source freeze. Normal R20 imports use
its actual source-capturing loader; no source pins/modules are reset or mocked.
"""
from copy import deepcopy
from pathlib import Path
import tempfile
import time
import unittest

from work.generator_upgrade_r20 import assignment, geometry, hierarchy, owner
from work.generator_upgrade_r20 import output, partition, pipeline, provenance as p, reference


def _blocks(value):
    return sorted(sorted(row['members']) for row in value['groups'])


def _stages(result):
    stages = {}
    for row in result['reporting']:
        name = row.get('stage', row.get('level'))
        if name is not None:
            if name in stages:
                raise AssertionError('duplicate stage receipt: '+name)
            stages[name] = row
    return stages


def _rectangle(left, right):
    return {'type': 'Polygon', 'coordinates': [
        [[left, 0], [right, 0], [right, 1], [left, 1], [left, 0]]]}


class PipelineTests(unittest.TestCase):
    def test_connected_hierarchy_whole_ownership_and_selective_cache(self):
        execution = p.identity()
        physical = reference.physical()
        unchanged_physical = deepcopy(physical)
        packets, reads = [], []

        def loader(frozen, *, revised=False):
            self.assertEqual(frozen['status'], 'PASS')
            self.assertTrue(frozen['assignment_allowed'])
            value = reference.political()
            if revised:
                value['atom_evidence']['atom-4']['A']['physical_compatibility_u'] = 12
            packets.append(deepcopy(value)); reads.append(revised)
            return value

        with tempfile.TemporaryDirectory(prefix='r20-') as directory:
            cache_root = Path(directory)
            started = time.perf_counter()
            cold = pipeline.run(physical, loader, cache_root=cache_root)
            cold_seconds = time.perf_counter()-started
            started = time.perf_counter()
            warm = pipeline.run(physical, loader, cache_root=cache_root)
            warm_seconds = time.perf_counter()-started
            revised = pipeline.run(physical, lambda frozen: loader(frozen, revised=True), cache_root=cache_root)
            exported = output.product(warm, expected_context=physical['context'])
            self.assertEqual(exported['status'], 'MODELLED')
            self.assertEqual(exported['values']['political_districts'], warm['scientific'])
            saved = output.save(cache_root/'out', 'product', exported)
            self.assertEqual(p.checked(saved), p.encoded(exported))
            self.assertEqual(saved, output.save(cache_root/'out', 'product', exported))
        self.assertEqual(reads, [False, False, True])
        self.assertEqual(physical, unchanged_physical)
        self.assertEqual(cold['scientific'], warm['scientific'])
        self.assertEqual(p.encoded(cold['scientific']), p.encoded(warm['scientific']))
        self.assertEqual(cold['execution'], execution)
        self.assertEqual(warm['execution'], execution)
        self.assertEqual(revised['execution'], execution)
        for result in (cold, warm, revised):
            self.assertEqual(result['scientific']['status'], 'MODELLED')
            self.assertEqual(result['scientific']['source_status'], 'SYNTHETIC TEST')
            self.assertIs(result['scientific']['actual_diadem_map_accepted'], False)

        stage_names = ['geometry', 'L1', 'L2', 'L3', 'assignment']
        receipt = [_stages(result) for result in (cold, warm, revised)]
        for rows in receipt:
            self.assertEqual(set(rows), set(stage_names))
            self.assertFalse(any(row['warnings'] for row in rows.values()))
        self.assertEqual([receipt[0][key]['hit'] for key in stage_names], [False]*5)
        self.assertEqual([receipt[1][key]['hit'] for key in stage_names], [True]*5)
        self.assertEqual([receipt[2][key]['hit'] for key in stage_names], [True]*4+[False])
        for key in stage_names[:-1]:
            self.assertEqual(receipt[0][key]['stats']['namespace'], receipt[2][key]['stats']['namespace'])
        self.assertNotEqual(receipt[0]['assignment']['stats']['namespace'],
                            receipt[2]['assignment']['stats']['namespace'])

        science = cold['scientific']; formed = science['formation']
        ids = {'atom-'+str(i) for i in range(12)}
        self.assertEqual(set(formed['atom_to_assignment_unit']), ids)
        self.assertEqual(set(formed['leaf_hierarchy']), ids)
        self.assertEqual([len(set(formed['leaf_hierarchy'][atom][i] for atom in ids))
                          for i in range(3)], [6, 4, 3])
        self.assertEqual([row['solution']['status'] for row in formed['levels']], ['PASS']*3)
        for i in range(3):
            blocks = {}
            for atom in ids:
                blocks.setdefault(formed['leaf_hierarchy'][atom][i], set()).add(atom)
            self.assertEqual(set().union(*blocks.values()), ids)
            self.assertEqual(sum(map(len, blocks.values())), len(ids))
            if i:
                lower_parents = {}
                for atom in ids:
                    child = formed['leaf_hierarchy'][atom][i-1]
                    lower_parents.setdefault(child, set()).add(formed['leaf_hierarchy'][atom][i])
                self.assertTrue(all(len(parents) == 1 for parents in lower_parents.values()))
            # The reference's persistent physical separator survives every ancestor.
            self.assertNotEqual(formed['leaf_hierarchy']['atom-3'][i],
                                formed['leaf_hierarchy']['atom-4'][i])
        self.assertEqual(len(formed['assignment_prepared']['supports']), 3)
        self.assertEqual(formed['assignment_prepared']['covered_area_m2'], 12000000)
        self.assertEqual(science['physical_freeze_sha256'], p.sha(formed))
        self.assertEqual(science['assignment']['objectives'], {'evidence': 9, 'frontier_support': 1})
        self.assertEqual(set(science['assignment']['assignment']), set(formed['atom_to_assignment_unit'].values()))
        for atom in ids:
            expected = 'A' if int(atom.split('-')[1]) < 4 else 'B'
            self.assertEqual(science['hierarchy'][atom]['surface_fill'], expected)
        self.assertEqual(science['borders']['disconnected_groups'], [])
        self.assertEqual(science['borders']['covered_area_m2'], 12000000)

        original_sites = {row['id']: row for row in packets[0]['sites']}
        for row in science['sites']:
            self.assertEqual(row['status'], 'ASSIGNED')
            self.assertEqual(row['xy_m'], original_sites[row['id']]['xy_m'])
            self.assertEqual(row['source_status'], original_sites[row['id']]['source_status'])
            self.assertEqual(row['context'], physical['context'])
            self.assertEqual(row['political_generation'], science['political_generation'])
        self.assertEqual(len(science['sites']), len(original_sites))
        self.assertEqual(len(science['access']), 1)
        route = science['access'][0]
        self.assertEqual(route['physical_travel_seconds'], 7200)
        self.assertEqual(route['legal_status'], 'UNKNOWN')
        self.assertEqual(route['permission'], 'UNKNOWN')
        self.assertIsNone(route['permitted_travel_seconds'])
        self.assertIs(route['sovereignty_transfer'], False)

        changed = revised['scientific']
        self.assertEqual(changed['formation'], formed)
        self.assertEqual(changed['physical_freeze_sha256'], science['physical_freeze_sha256'])
        self.assertNotEqual(changed['political_input_sha256'], science['political_input_sha256'])
        self.assertNotEqual(changed['political_generation'], science['political_generation'])
        self.assertEqual(changed['assignment']['objectives'], {'evidence': 12, 'frontier_support': 1})
        for atom in ids:
            self.assertEqual(changed['hierarchy'][atom]['surface_fill'],
                             'A' if int(atom.split('-')[1]) < 8 else 'B')
        p.verify(execution)
        type(self).results = {'cold': cold, 'warm': warm, 'political_revision': revised}
        type(self).timing = {'cold_seconds': cold_seconds, 'warm_seconds': warm_seconds,
            'saved_seconds': cold_seconds-warm_seconds,
            'saved_percent': 100*(cold_seconds-warm_seconds)/cold_seconds,
            'scope': 'One matched twelve-atom connected workflow pair including source checks and validation; not whole-Diadem performance'}

    def test_pinned_owner_transitivity_hard_ancestor_and_boundary_accounting(self):
        execution = p.identity()
        cases = owner.read_cases()
        formation = {row['id']: row for row in cases['formation_cases']}
        results = {}
        for ident in ('F03-frustrated-triangle', 'F05-hard-contradiction', 'F13-persistent-cut-at-ancestor'):
            case = formation[ident]
            problem = {'unit_ids': case['nodes'], 'edges': [
                {'left': a, 'right': b, 'length_m': 1, 'separation_u': separation,
                 'continuity_u': continuity} for a, b, separation, continuity in case['edges']],
                'must_join': case.get('must_join', []), 'must_cut': case.get('must_cut', []),
                'limits': dict(reference.LIMITS)}
            solved = partition.solve(problem); results[ident] = solved
            value = solved['solution']
            if case.get('expected_status') == 'INFEASIBLE':
                self.assertEqual(value['status'], 'FAILED')
                self.assertNotIn('memberships', value)
                continue
            self.assertEqual(value['objective_u'], case['expected_min'])
            self.assertEqual(value['objective_bound_u'], case['expected_min'])
            expected = sorted(sorted(sorted(block) for block in candidate) for candidate in case['expected_optima'])
            if len(expected) == 1:
                self.assertEqual(value['status'], 'PASS')
                self.assertEqual(_blocks(value), expected[0])
            else:
                self.assertEqual(value['status'], 'POLYCENTRIC_UNRESOLVED')
                self.assertEqual(sorted(_blocks(candidate) for candidate in value['alternatives']), expected)
                self.assertIsNone(value['preferred_partition'])
                self.assertIs(value['diagnostic_envelope']['is_candidate_partition'], False)
                self.assertGreater(case['envelope_cost'], value['objective_u'])

        assignment_cases = {row['id']: row for row in cases['assignment_cases']}
        for ident in ('A03-material-alternatives', 'A06-all-active-owners-nonempty'):
            case = assignment_cases[ident]
            problem = {'unit_ids': case['units'], 'owners': case['owners'],
                'eligible': {unit: [case['locks'][unit]] if unit in case.get('locks', {}) else list(case['owners'])
                             for unit in case['units']}, 'scores': case['scores'],
                'edges': [{'left': a, 'right': b, 'length_m': 1, 'boundary_score': score}
                          for a, b, score in case['edges']],
                'required_owners': case['owners'], 'connected_owners': case['owners'],
                'required_adjacency': [], 'prohibited_adjacency': [], 'limits': dict(reference.LIMITS)}
            solved = assignment.solve(problem); results[ident] = solved
            value = solved['solution']
            self.assertEqual(value['status'], 'FAILED' if case['expected_status'] == 'INFEASIBLE' else 'POLYCENTRIC_UNRESOLVED')
            self.assertIsNone(value['assignment'])
            if 'expected_score' in case:
                self.assertEqual([value['objectives']['evidence'], value['objectives']['frontier_support']], case['expected_score'])

        prepared = geometry.prepare([{'id': 'a', 'geometry': _rectangle(0, 1)},
            {'id': 'b', 'geometry': _rectangle(1, 2)}], _rectangle(0, 2))
        projected = []
        for ident in ('F08-unsplit-boundary', 'F09-equivalent-subsegments'):
            case = formation[ident]
            level = {'id': 'L1', 'alias': hierarchy.ALIASES[0], 'edge_costs': [
                dict(zip(('left', 'right', 'separation_u', 'continuity_u'), row)) for row in case['edges']],
                'must_join': [], 'must_cut': []}
            projected.append(hierarchy.project(prepared, {'a': 'a', 'b': 'b'}, level))
        self.assertEqual(projected[0], projected[1])
        self.assertEqual(projected[0][0]['edges'][0]['separation_u'], 3)
        self.assertEqual(projected[0][0]['edges'][0]['continuity_u'], 5)
        self.assertEqual(projected[0][1], 0)

        case = formation['F13-persistent-cut-at-ancestor']
        level = {'id': 'L3', 'alias': hierarchy.ALIASES[2], 'edge_costs': [
            {'left': 'a', 'right': 'b', 'separation_u': case['edges'][0][2],
             'continuity_u': case['edges'][0][3]}], 'must_join': [], 'must_cut': [['a', 'b']]}
        quotient, fixed = hierarchy.project(prepared, {'a': 'c1', 'b': 'c2'}, level)
        self.assertEqual(quotient['must_cut'], case['must_cut'])
        self.assertEqual(quotient['edges'][0]['continuity_u'], case['expected_min'])
        self.assertEqual(fixed, 0)
        with self.assertRaisesRegex(ValueError, 'split a frozen child'):
            hierarchy.project(prepared, {'a': 'c1', 'b': 'c1'}, level)
        physical = reference.physical()
        hierarchy.scoped_facts(physical['levels'], physical['hard_facts'])
        omitted = deepcopy(physical['levels'])
        omitted[1]['must_cut'] = []
        with self.assertRaisesRegex(ValueError, 'active_levels'):
            hierarchy.scoped_facts(omitted, physical['hard_facts'])
        p.verify(execution)
        type(self).owner_results = results
        type(self).projection_results = {'segmentation_equivalence': projected, 'persistent_ancestor_cut': quotient}


if __name__ == '__main__':
    unittest.main()
