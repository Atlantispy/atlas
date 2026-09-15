"""One focused neutral polygon-support test; no district assignment policy."""
from copy import deepcopy
import unittest

from shapely.geometry import shape
from work.generator_upgrade_r20 import geometry as g


def rectangle(x0, y0, x1, y1):
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]


def polygon(ring, holes=()):
    return {'type': 'Polygon', 'coordinates': [ring, *holes]}


class GeometryTests(unittest.TestCase):
    def test_holes_positive_borders_islands_and_rejected_partitions(self):
        hole = rectangle(1, 1, 2, 2)
        domain = {'type': 'MultiPolygon', 'coordinates': [
            [rectangle(0, 0, 4, 3), hole], [rectangle(4, 3, 5, 4)],
            [rectangle(6, 0, 7, 1)], [rectangle(8, 0, 9, 1)]]}
        supports = [
            {'id': 'B', 'geometry': polygon(rectangle(3, 0, 4, 3))},
            {'id': 'A', 'geometry': polygon(rectangle(0, 0, 3, 3), [hole])},
            {'id': 'islands', 'geometry': {'type': 'MultiPolygon', 'coordinates': [
                [rectangle(8, 0, 9, 1)], [rectangle(6, 0, 7, 1)]]}},
            {'id': 'corner', 'geometry': polygon(rectangle(4, 3, 5, 4))}]
        untouched = deepcopy(supports)
        prepared = g.prepare(supports, domain)
        type(self).prepared = prepared
        self.assertEqual(supports, untouched)
        self.assertEqual([row['id'] for row in prepared['supports']], ['A', 'B', 'corner', 'islands'])
        self.assertEqual(prepared['domain_area_m2'], 14)
        self.assertEqual(prepared['covered_area_m2'], 14)
        self.assertEqual(prepared['support_area_sum_m2'], 14)
        self.assertEqual([(row['left'], row['right'], row['length_m']) for row in prepared['edges']], [('A', 'B', 3)])
        self.assertEqual(shape(prepared['edges'][0]['geometry']).length, 3)
        self.assertEqual(prepared, g.prepare(list(reversed(supports)), domain))
        separated = g.dissolve(prepared, {'A': 'left', 'B': 'right', 'corner': 'corner', 'islands': 'archipelago'})
        self.assertEqual([(row['left'], row['right'], row['length_m']) for row in separated['edges']], [('left', 'right', 3)])
        archipelago = next(row for row in separated['groups'] if row['id'] == 'archipelago')
        self.assertEqual(archipelago['positive_edge_components'], [['islands']])
        self.assertEqual(archipelago['polygon_component_count'], 2)
        self.assertIs(archipelago['connected'], False)
        self.assertEqual(separated['disconnected_groups'], ['archipelago'])
        joined = g.dissolve(prepared, {'A': 'mainland', 'B': 'mainland', 'corner': 'corner', 'islands': 'archipelago'})
        type(self).dissolved = joined
        mainland = next(row for row in joined['groups'] if row['id'] == 'mainland')
        self.assertEqual(mainland['area_m2'], 11)
        self.assertEqual(len(mainland['geometry']['coordinates']), 2)  # hole retained
        self.assertIs(mainland['connected'], True)
        self.assertEqual(joined['edges'], [])  # corner touch is never adjacency
        self.assertEqual(joined['boundary_ledger']['absorbed_internal_length_m'], 3)
        self.assertEqual(joined['boundary_ledger']['perimeter_reporting_residual_m'], 0)
        self.assertIs(joined['coverage']['gap_empty'], True)
        self.assertIs(joined['coverage']['outside_empty'], True)
        with self.assertRaises(ValueError):
            g.dissolve(prepared, {'A': 'incomplete'})
        changed = deepcopy(prepared)
        changed['edges'][0]['length_m'] = 4
        with self.assertRaises(ValueError):
            g.dissolve(changed, {row['id']: 'all' for row in supports})

        box = polygon(rectangle(0, 0, 4, 1))
        bad_partitions = {
            'overlap': [polygon(rectangle(0, 0, 3, 1)), polygon(rectangle(2, 0, 4, 1))],
            'gap': [polygon(rectangle(0, 0, 1, 1)), polygon(rectangle(2, 0, 4, 1))],
            'outside': [polygon(rectangle(0, 0, 5, 1))],
            'invalid': [polygon([[0, 0], [4, 1], [0, 1], [4, 0], [0, 0]])],
            'nonfinite': [polygon(rectangle(0, 0, float('nan'), 1))],
            'unclosed': [polygon([[0, 0], [4, 0], [4, 1], [0, 1]])],
            'line': [{'type': 'LineString', 'coordinates': [[0, 0], [4, 1]]}],
            'point': [{'type': 'Point', 'coordinates': [0, 0]}]}
        for name, items in bad_partitions.items():
            with self.subTest(rejected=name), self.assertRaises(ValueError):
                g.prepare([{'id': str(index), 'geometry': item} for index, item in enumerate(items)], box)
        with self.assertRaises(ValueError):
            g.prepare([{'id': 'duplicate', 'geometry': box}, {'id': 'duplicate', 'geometry': box}], box)


if __name__ == '__main__':
    unittest.main()
