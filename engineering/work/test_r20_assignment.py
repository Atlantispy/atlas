"""One focused synthetic assignment/contiguity/ambiguity regression; no owner policy."""
from copy import deepcopy
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from work.generator_upgrade_r20.assignment import solve


class WholeUnitAssignmentTests(unittest.TestCase):
    def test_lexicographic_connectivity_ambiguity_and_hard_adjacency(self):
        def problem(units, edges, scores):
            return {'unit_ids': units, 'owners': ['A', 'B'],
                'eligible': {unit: ['A', 'B'] for unit in units}, 'scores': scores,
                'edges': [{'left': a, 'right': b, 'length_m': 1, 'boundary_score': weight}
                          for a, b, weight in edges],
                'required_owners': ['A', 'B'], 'connected_owners': ['A', 'B'],
                'required_adjacency': [], 'prohibited_adjacency': [],
                'limits': {'max_cut_rounds': 32, 'node_limit': 10000, 'time_limit_s': 10}}

        line = problem(['a', 'b', 'c'], [('a', 'b', 1), ('b', 'c', 3)],
            {'a': {'A': 10, 'B': 0}, 'b': {'A': 0, 'B': 0}, 'c': {'A': 0, 'B': 10}})
        untouched = deepcopy(line)
        result = solve(line)
        self.assertEqual(line, untouched)
        self.assertEqual(result['solution']['status'], 'MODELLED')
        self.assertEqual(result['solution']['assignment'], {'a': 'A', 'b': 'A', 'c': 'B'})
        self.assertEqual(result['solution']['objectives'], {'evidence': 20, 'frontier_support': 3})
        self.assertNotIn('wall_seconds', result['solution'])
        self.assertEqual(result['solution']['alternatives'], [])
        self.assertFalse(result['solution']['alternatives_exhaustive'])

        presence = deepcopy(line)
        presence['required_presence'] = [{'owner': 'B', 'unit_ids': ['b']}]
        constrained = solve(presence)['solution']
        self.assertEqual(constrained['status'], 'MODELLED')
        self.assertEqual(constrained['assignment'], {'a': 'A', 'b': 'B', 'c': 'B'})
        self.assertEqual(constrained['objectives'], {'evidence': 20, 'frontier_support': 1})

        # A high-scoring disconnected A fringe must lose to a connected feasible
        # ownership. Zero frontier evidence remains a real physical connection.
        branch = problem(['a', 'b', 'c', 'd'], [('b', 'a', 0), ('b', 'c', 0), ('b', 'd', 0)],
            {'a': {'A': 20, 'B': 0}, 'b': {'A': 0, 'B': 10},
             'c': {'A': 5, 'B': 0}, 'd': {'A': 0, 'B': 30}})
        connected = solve(branch)
        self.assertEqual(connected['solution']['status'], 'MODELLED')
        self.assertEqual(connected['solution']['assignment'], {'a': 'A', 'b': 'B', 'c': 'B', 'd': 'B'})
        self.assertEqual(connected['solution']['objectives'], {'evidence': 60, 'frontier_support': 0})
        self.assertGreater(connected['diagnostics']['cut_rounds'], 0)
        self.assertFalse(connected['diagnostics']['presolve'])

        tied = deepcopy(line)
        tied['edges'][1]['boundary_score'] = 1
        unresolved = solve(tied)['solution']
        self.assertEqual(unresolved['status'], 'POLYCENTRIC_UNRESOLVED')
        self.assertIsNone(unresolved['assignment'])
        self.assertEqual(unresolved['objectives'], {'evidence': 20, 'frontier_support': 1})
        self.assertEqual(unresolved['alternatives'], [
            {'a': 'A', 'b': 'A', 'c': 'B'}, {'a': 'A', 'b': 'B', 'c': 'B'}])
        self.assertFalse(unresolved['alternatives_exhaustive'])

        # Absent solver node receipts are not reported as zero work, and finite
        # incumbent/dual bounds remain visible even for an uncertain outcome.
        for solver_status, expected in ((2, 'FAILED'), (1, 'INCOMPLETE')):
            receipt = SimpleNamespace(status=solver_status, success=False,
                message='synthetic budget receipt', mip_node_count=None,
                fun=-20., mip_dual_bound=-21.)
            with patch('work.generator_upgrade_r20.assignment.milp', return_value=receipt):
                bounded = solve(line)
            self.assertEqual(bounded['solution']['status'], expected)
            self.assertIsNone(bounded['solution']['assignment'])
            self.assertEqual(bounded['solution']['alternatives'], [])
            call = bounded['diagnostics']['solver_calls'][0]
            self.assertIsNone(call['reported_nodes'])
            self.assertEqual(call['charged_nodes'], line['limits']['node_limit'])
            self.assertEqual(bounded['diagnostics']['nodes_used'], line['limits']['node_limit'])
            self.assertEqual((call['fun'], call['mip_dual_bound']), (-20., -21.))

        fixed = problem(['a', 'b'], [('a', 'b', 0)],
                        {'a': {'A': 1}, 'b': {'B': 1}})
        fixed['eligible'] = {'a': ['A'], 'b': ['B']}
        fixed['required_adjacency'] = [['A', 'B']]
        self.assertEqual(solve(fixed)['solution']['status'], 'MODELLED')
        impossible_presence = deepcopy(fixed)
        impossible_presence['required_presence'] = [{'owner': 'A', 'unit_ids': ['b']}]
        self.assertEqual(solve(impossible_presence)['solution']['status'], 'FAILED')
        forbidden = deepcopy(fixed)
        forbidden['required_adjacency'] = []
        forbidden['prohibited_adjacency'] = [['B', 'A']]
        self.assertEqual(solve(forbidden)['solution']['status'], 'FAILED')
        isolated = deepcopy(fixed)
        isolated['edges'] = []
        self.assertEqual(solve(isolated)['solution']['status'], 'FAILED')

        # OR adjacency is physical, not evidence-weighted, and does not require
        # every listed other owner to be present. D is an unused alternative.
        neighbour = problem(['a', 'b', 'c'], [('a', 'b', 0), ('b', 'c', 0)],
            {'a': {'A': 0}, 'b': {'B': 10, 'C': 0}, 'c': {'B': 0, 'C': 10}})
        neighbour['owners'] = ['A', 'B', 'C', 'D']
        neighbour['eligible'] = {'a': ['A'], 'b': ['B', 'C'], 'c': ['B', 'C']}
        neighbour['required_owners'] = ['A', 'B', 'C']
        neighbour['connected_owners'] = ['A', 'B', 'C', 'D']
        self.assertEqual(solve(neighbour)['solution']['assignment'], {'a': 'A', 'b': 'B', 'c': 'C'})
        neighbour['required_any_adjacency'] = [{'owner': 'A', 'other_owners': ['D', 'C']}]
        any_result = solve(neighbour)['solution']
        self.assertEqual(any_result['status'], 'MODELLED')
        self.assertEqual(any_result['assignment'], {'a': 'A', 'b': 'C', 'c': 'B'})
        self.assertEqual(any_result['objectives'], {'evidence': 0, 'frontier_support': 0})
        neighbour['prohibited_adjacency'] = [['A', 'C']]
        self.assertEqual(solve(neighbour)['solution']['status'], 'FAILED')

        no_cuts = deepcopy(branch)
        no_cuts['limits']['max_cut_rounds'] = 0
        limited = solve(no_cuts)['solution']
        self.assertEqual(limited['status'], 'INCOMPLETE')
        self.assertIsNone(limited['assignment'])
        with self.assertRaises(ValueError):
            bad = deepcopy(line)
            bad['edges'].append(deepcopy(bad['edges'][0]))
            solve(bad)
        for invalid in ([{'owner': 'unknown', 'unit_ids': ['a']}],
                        [{'owner': 'A', 'unit_ids': ['unknown']}],
                        [{'owner': 'A', 'unit_ids': ['a', 'a']}],
                        [{'owner': 'A', 'unit_ids': []}],
                        [{'owner': 'A', 'unit_ids': ['a'], 'extra': 1}],
                        [{'owner': 'A', 'unit_ids': ['a']}] * 2):
            with self.subTest(required_presence=invalid), self.assertRaises(ValueError):
                bad = deepcopy(line)
                bad['required_presence'] = invalid
                solve(bad)
        for invalid in ([{'owner': 'unknown', 'other_owners': ['B']}],
                        [{'owner': 'A', 'other_owners': ['unknown']}],
                        [{'owner': 'A', 'other_owners': ['A']}],
                        [{'owner': 'A', 'other_owners': ['B', 'B']}],
                        [{'owner': 'A', 'other_owners': []}],
                        [{'owner': 'A', 'other_owners': ['B'], 'extra': 1}],
                        [{'owner': 'A', 'other_owners': ['B']}] * 2):
            with self.subTest(required_any_adjacency=invalid), self.assertRaises(ValueError):
                bad = deepcopy(line)
                bad['required_any_adjacency'] = invalid
                solve(bad)


if __name__ == '__main__':
    unittest.main()
