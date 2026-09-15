"""One finite replacement/contact/account check; no geological model run."""
from copy import deepcopy
from fractions import Fraction as F
import unittest

from work.generator_upgrade_r18 import replacement


def inventory(layers):
    result = {}
    for layer in layers:
        for unit, weight in layer['weights'].items():
            result[unit] = result.get(unit, F())+F(layer['thickness_m'])*F(weight)
    return result


class ReplacementTests(unittest.TestCase):
    def test_partial_sequential_protected_exact_finite_replacement_and_rejections(self):
        layers = [dict(compartment_id='root', thickness_m='6', weights={'A': '1/2', 'GT': '1/2'}),
                  dict(compartment_id='cover', thickness_m='4', weights={'C': '1'})]
        original = deepcopy(layers)
        first, transfers = replacement.replace(layers, 3, {'X': '1/2', 'Y': '1/2'})
        self.assertEqual(layers, original)
        self.assertEqual([row['thickness_m'] for row in first], ['6', '1', '3'])
        self.assertEqual(len({row['compartment_id'] for row in first}), 3)
        self.assertEqual(first[-1]['weights'], {'C': '1/4', 'X': '3/8', 'Y': '3/8'})
        self.assertEqual(transfers[0]['coverage'], '3/4')
        self.assertEqual(transfers[0]['depth_start_m'], '0')
        self.assertEqual(transfers[0]['depth_stop_m'], '3')
        self.assertEqual(transfers[0]['removed_bulk_thickness_m'], {'C': '9/4'})
        self.assertEqual(transfers[0]['introduced_bulk_thickness_m'], {'X': '9/8', 'Y': '9/8'})
        self.assertEqual(replacement.replace(layers, 3, {'Y': '1/2', 'X': '1/2'}), (first, transfers))
        second, exchanged = replacement.replace(first, 20, {'Z': 1},
            eligible_units=('A', 'C', 'GT'), protected_units=('GT',), coverage=1)
        stocks = inventory(second)
        self.assertEqual(stocks, {'GT': F(3), 'Z': F(19, 4), 'X': F(9, 8), 'Y': F(9, 8)})
        self.assertEqual(sum(F(row['thickness_m']) for row in second), 10)
        self.assertEqual(sum(F(value) for row in exchanged for value in row['removed_bulk_thickness_m'].values()), F(19, 4))
        self.assertEqual(sum(F(value) for row in exchanged for value in row['introduced_bulk_thickness_m'].values()), F(19, 4))
        third, again = replacement.replace(second, 20, {'Z': 1}, eligible_units=('A', 'C'), protected_units=('GT',))
        self.assertEqual(third, second); self.assertEqual(again, [])
        clipped, exchanged = replacement.replace(layers, 100, {'D': 1}, protected_units=('GT',))
        self.assertEqual(inventory(clipped), {'D': F(7), 'GT': F(3)})
        self.assertEqual(max(F(row['depth_stop_m']) for row in exchanged), 10)
        for depth, candidates, coverage in [(0, {'D': 1}, None), (100, {'D': 0}, None), (100, {'D': 1}, 0)]:
            result, changed = replacement.replace(layers, depth, candidates, coverage=coverage)
            self.assertEqual(result, original); self.assertEqual(changed, [])
            result[0]['weights']['A'] = '0'
            self.assertEqual(layers, original)
        self.assertEqual(replacement.replace([], 100, {'D': 1}), ([], []))
        for depth, candidates, coverage in [(-1, {'D': 1}, None), (True, {'D': 1}, None),
                (1, {'D': True}, None), (1, {'D': '-1/2'}, None), (1, {'D': 2}, None),
                (1, {'D': float('nan')}, None), (1, {'D': 0}, '1/2'), (1, {'D': 1}, 2)]:
            with self.subTest(depth=depth, candidates=candidates, coverage=coverage), self.assertRaises(ValueError):
                replacement.replace(layers, depth, candidates, coverage=coverage)
        bad = deepcopy(layers); bad[0]['weights']['A'] = '1/3'
        with self.assertRaisesRegex(ValueError, 'sum exactly'):
            replacement.replace(bad, 1, {'D': 1})
        with self.assertRaisesRegex(ValueError, 'duplicate compartment'):
            replacement.replace(layers+layers, 1, {'D': 1})


if __name__ == '__main__':
    unittest.main()
