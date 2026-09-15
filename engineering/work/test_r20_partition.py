"""One bounded multicut check; numerical evidence is a synthetic fixture only."""
from copy import deepcopy
import unittest
from unittest.mock import patch

from scipy.optimize import OptimizeResult

from work.generator_upgrade_r20 import partition as p


def problem(units, edges, *, join=(), cut=()):
    return {'unit_ids': list(units), 'edges': [
        {'left': a, 'right': b, 'length_m': 1, 'separation_u': separation,
         'continuity_u': continuity} for a, b, separation, continuity in edges],
        'must_join': [list(pair) for pair in join], 'must_cut': [list(pair) for pair in cut],
        'limits': {'max_cut_rounds': 32, 'node_limit': 10000, 'time_limit_s': 30}}


def blocks(solution):
    return sorted(sorted(row['members']) for row in solution['groups'])


class PartitionTests(unittest.TestCase):
    def test_connected_multicut_hard_facts_ambiguity_and_permutations(self):
        cases = {}
        line = problem('abc', [('a', 'b', 0, 9), ('b', 'c', 7, 0)])
        original = deepcopy(line)
        cases['unique_line'] = p.solve(line)
        solved = cases['unique_line']['solution']
        self.assertEqual(solved['status'], 'PASS')
        self.assertEqual(blocks(solved), [['a', 'b'], ['c']])
        self.assertEqual(solved['objective_u'], 0)
        self.assertEqual(solved['objective_bound_u'], 0)
        self.assertEqual(line, original)
        permuted = deepcopy(line)
        permuted['unit_ids'].reverse(); permuted['edges'].reverse()
        for row in permuted['edges']:
            row['left'], row['right'] = row['right'], row['left']
        self.assertEqual(p.solve(permuted)['solution'], solved)

        # Independent edge decisions would join ab/bc and cut ac: an invalid cycle.
        triangle = problem('abc', [('a', 'b', 0, 10), ('b', 'c', 0, 10), ('a', 'c', 6, 0)])
        cases['cycle'] = p.solve(triangle)
        self.assertEqual(cases['cycle']['solution']['status'], 'PASS')
        self.assertEqual(blocks(cases['cycle']['solution']), [['a', 'b', 'c']])
        self.assertEqual(cases['cycle']['solution']['objective_u'], 6)
        self.assertGreater(cases['cycle']['diagnostics']['cut_counts'].get('cycle', 0), 0)
        self.assertIs(cases['cycle']['diagnostics']['presolve'], False)

        nonlocal_join = problem('abc', [('a', 'b', 5, 0), ('b', 'c', 7, 0)], join=[('a', 'c')])
        cases['nonlocal_join'] = p.solve(nonlocal_join)
        self.assertEqual(cases['nonlocal_join']['solution']['status'], 'PASS')
        self.assertEqual(blocks(cases['nonlocal_join']['solution']), [['a', 'b', 'c']])
        self.assertEqual(cases['nonlocal_join']['solution']['objective_u'], 12)
        nonlocal_cut = problem('abc', [('a', 'b', 0, 2), ('b', 'c', 0, 9)], cut=[('a', 'c')])
        cases['nonlocal_cut'] = p.solve(nonlocal_cut)
        self.assertEqual(cases['nonlocal_cut']['solution']['status'], 'PASS')
        self.assertEqual(blocks(cases['nonlocal_cut']['solution']), [['a'], ['b', 'c']])
        self.assertEqual(cases['nonlocal_cut']['solution']['objective_u'], 2)

        equal = problem('ab', [('a', 'b', 4, 4)])
        cases['equal_optima'] = p.solve(equal)
        ambiguous = cases['equal_optima']['solution']
        self.assertEqual(ambiguous['status'], 'POLYCENTRIC_UNRESOLVED')
        self.assertEqual(ambiguous['objective_u'], 4)
        self.assertIsNone(ambiguous['preferred_partition'])
        self.assertNotIn('memberships', ambiguous)
        self.assertEqual(sorted(blocks(item) for item in ambiguous['alternatives']),
                         [[['a'], ['b']], [['a', 'b']]])
        self.assertEqual(ambiguous['diagnostic_envelope']['unit_ids'], ['a', 'b'])
        equal['unit_ids'].reverse()
        self.assertEqual(p.solve(equal)['solution'], ambiguous)

        impossible = problem('abc', [('a', 'b', 0, 1), ('b', 'c', 0, 1)],
                             join=[('a', 'c')], cut=[('a', 'b')])
        cases['infeasible'] = p.solve(impossible)
        self.assertEqual(cases['infeasible']['solution']['status'], 'FAILED')
        self.assertNotIn('memberships', cases['infeasible']['solution'])
        empty = p.solve(problem('ab', []))['solution']
        self.assertEqual(empty['status'], 'PASS')
        self.assertEqual(blocks(empty), [['a'], ['b']])
        malformed = deepcopy(line); malformed['edges'][0]['continuity_u'] = True
        with self.assertRaises(ValueError):
            p.solve(malformed)
        # A primary optimum alone is not success when its global node budget
        # leaves no capacity to perform the required alternative search.
        exhausted = OptimizeResult(status=0, message='synthetic budget oracle',
            x=[0.0, 1.0], fun=-7.0, mip_dual_bound=-7.0, mip_node_count=10000)
        with patch.object(p, 'milp', return_value=exhausted) as mocked:
            cases['budget_incomplete'] = p.solve(line)
            self.assertEqual(mocked.call_count, 1)
        self.assertEqual(cases['budget_incomplete']['solution']['status'], 'INCOMPLETE')
        self.assertNotIn('memberships', cases['budget_incomplete']['solution'])
        nonbinary = OptimizeResult(status=0, message='synthetic binary readback oracle',
            x=[1e-9, 1.0], fun=-7.0, mip_dual_bound=-7.0, mip_node_count=0)
        with patch.object(p, 'milp', return_value=nonbinary):
            rejected = p.solve(line)
        self.assertEqual(rejected['solution']['status'], 'INCOMPLETE')
        self.assertIn('exactly binary', rejected['solution']['reason'])
        type(self).results = cases


if __name__ == '__main__':
    unittest.main()
