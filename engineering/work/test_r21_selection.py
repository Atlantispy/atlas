"""Two bounded exact selection checks; coefficients are synthetic oracles only."""
from copy import deepcopy
import unittest

from work.generator_upgrade_r21 import selection as s


def _plan(identity, plot, energy='0', uses=None, *, cultivated=True):
    return {'id': identity, 'plot_id': plot, 'cultivated': cultivated,
            'energy_kcal': energy, 'resource_use': {} if uses is None else uses}


def _problem(plots, plans, resources):
    fallow = [_plan('fallow-'+row['id'], row['id'], cultivated=False) for row in plots]
    return {'plots': plots, 'plans': plans+fallow, 'resources': resources,
            'limits': {'node_limit': 1000, 'time_limit_s': 10}}


class SelectionTests(unittest.TestCase):
    def test_daily_shared_competition_whole_plots_and_storage_prefixes(self):
        problem = _problem([{'id': 'a', 'area_m2': '2/3'}, {'id': 'b', 'area_m2': '4/3'}], [
            _plan('a-early', 'a', '10', {'pool:day0': '1/3'}),
            _plan('a-late', 'a', '6', {'pool:day1': '1/3'}),
            _plan('b-early', 'b', '9', {'pool:day0': '1/3'})],
            {'pool:day0': '1/3', 'pool:day1': '1/3'})
        original = deepcopy(problem)
        result = s.solve(problem); value = result['solution']
        self.assertEqual(problem, original)
        self.assertEqual(value['status'], 'MODELLED')
        self.assertEqual(value['selection'], {'a': 'a-late', 'b': 'b-early'})
        self.assertEqual(value['objective_kcal'], '15')
        self.assertEqual(value['objective_upper_bound_kcal'], '15')
        self.assertEqual(value['physical_area_m2'], '2')
        self.assertEqual(value['cultivated_area_m2'], '2')
        self.assertEqual(len(value['plot_ledger']), 2)  # competing a plans cannot both occupy a
        self.assertEqual({row['plot_id'] for row in value['plot_ledger']}, {'a', 'b'})
        for row in value['resource_ledger']:
            self.assertEqual(row['used'], '1/3')
            self.assertEqual(row['unused'], '0')
            self.assertEqual(row['residual'], '0')
        permuted = deepcopy(problem)
        permuted['plans'].reverse(); permuted['plots'].reverse()
        permuted['resources'] = dict(reversed(list(permuted['resources'].items())))
        self.assertEqual(s.solve(permuted)['solution'], value)

        # A daily delivery cap alone is not water: initially empty storage only
        # receives its finite four units on day1. The early plan cannot borrow it.
        storage = _problem([{'id': 'p', 'area_m2': '1'}], [
            _plan('early-high-energy', 'p', '100',
                  {'daily:0': '4', 'storage-prefix:0': '4', 'storage-prefix:1': '4'}),
            _plan('later', 'p', '5', {'daily:1': '4', 'storage-prefix:1': '4'})],
            {'daily:0': '4', 'daily:1': '4', 'storage-prefix:0': '0', 'storage-prefix:1': '4'})
        stored = s.solve(storage)
        self.assertEqual(stored['solution']['status'], 'MODELLED')
        self.assertEqual(stored['solution']['selection'], {'p': 'later'})
        self.assertEqual(stored['solution']['objective_kcal'], '5')
        self.assertIn('DO_NOT_SUM', stored['solution']['resource_rows'])
        type(self).results = {'shared_daily': result, 'storage_prefix': stored}

    def test_ties_rainfed_fallow_and_bounded_incomplete_search(self):
        problem = _problem([{'id': 'p', 'area_m2': '3'}], [
            _plan('rainfed-a', 'p', '7/3'), _plan('rainfed-b', 'p', '7/3')], {})
        result = s.solve(problem); value = result['solution']
        self.assertEqual(value['status'], 'ALLOCATION_UNRESOLVED')
        self.assertIsNone(value['selection'])
        self.assertIsNone(value['preferred_selection'])
        self.assertEqual(value['objective_kcal'], '7/3')
        self.assertEqual(value['objective_upper_bound_kcal'], '7/3')
        self.assertEqual({row['selection']['p'] for row in value['alternatives']}, {'rainfed-a', 'rainfed-b'})
        for row in value['alternatives']:
            self.assertEqual(row['cultivated_area_m2'], '3')
            self.assertEqual(row['resource_ledger'], [])
        self.assertIs(value['certificate']['search_complete'], True)
        limited = deepcopy(problem); limited['limits']['node_limit'] = 1
        incomplete = s.solve(limited)
        self.assertEqual(incomplete['solution']['status'], 'INCOMPLETE')
        self.assertIsNone(incomplete['solution']['selection'])
        self.assertNotIn('alternatives', incomplete['solution'])
        self.assertNotIn('certificate', incomplete['solution'])
        self.assertEqual(incomplete['diagnostics']['nodes'], 1)
        fallow = s.solve(_problem([{'id': 'p', 'area_m2': '3'}], [], {}))['solution']
        self.assertEqual(fallow['status'], 'MODELLED')
        self.assertEqual(fallow['cultivated_area_m2'], '0')
        self.assertEqual(fallow['physical_area_m2'], '3')
        self.assertEqual(fallow['objective_kcal'], '0')
        invalid = deepcopy(problem); invalid['plans'][0]['energy_kcal'] = '14/6'
        with self.assertRaises(ValueError):
            s.solve(invalid)
        invalid = deepcopy(problem); invalid['plans'][0]['resource_use'] = {'unknown-pool': '1'}
        with self.assertRaises(ValueError):
            s.solve(invalid)
        invalid = deepcopy(problem); invalid['plots'].append(deepcopy(invalid['plots'][0]))
        with self.assertRaises(ValueError):
            s.solve(invalid)
        invalid = deepcopy(problem); invalid['plans'] = invalid['plans'][:-1]
        with self.assertRaisesRegex(ValueError, 'fallow'):
            s.solve(invalid)
        type(self).tie_result = result
        type(self).incomplete_result = incomplete


if __name__ == '__main__':
    unittest.main()
