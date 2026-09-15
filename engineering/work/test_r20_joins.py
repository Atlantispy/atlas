"""One focused unchanged-site/generation/legal-access integration check."""
from copy import deepcopy
import unittest
from shapely.geometry import box, mapping
from work.generator_upgrade_r20 import geometry, joins


class JoinTests(unittest.TestCase):
    def test_exact_sites_generation_and_separate_access(self):
        prepared = geometry.prepare([
            {'id': 'u0', 'geometry': mapping(box(0, 0, 1, 1))},
            {'id': 'u1', 'geometry': mapping(box(1, 0, 2, 1))}], mapping(box(0, 0, 2, 1)))
        hierarchy = {'u0': {'surface_fill': 'forest', 'haus': ['canopy', 'floor']},
                     'u1': {'surface_fill': 'neutral', 'haus': []}}
        for ident, value in hierarchy.items():
            value.update(barony_id=ident+'-b', county_id=ident+'-c', duchy_id=ident+'-d')
        rows = [{'id': ident, 'xy_m': xy, 'source_status': 'SYNTHETIC TEST'}
                for ident, xy in [('a', [.5, .5]), ('b', [1.5, .5]), ('edge', [1., .5]), ('outside', [3., .5])]]
        before = deepcopy(rows)
        context = {'world_id': 'fixture', 'snapshot_id': 'date', 'calendar_id': 'calendar',
                   'spatial_frame_id': 'frame', 'vertical_reference': 'unused', 'scenario_id': 'scenario'}
        binding = {'generation': 'g', 'expected_generation': 'g',
                   'context': context, 'expected_context': deepcopy(context)}
        out = joins.sites(rows, prepared, hierarchy, **binding)
        by_id = {row['id']: row for row in out}
        self.assertEqual(rows, before)
        self.assertEqual(by_id['a']['political_binding']['haus'], ['canopy', 'floor'])
        self.assertEqual(by_id['b']['political_binding']['haus'], [])
        self.assertEqual(by_id['edge']['status'], 'BOUNDARY_AMBIGUOUS')
        self.assertEqual(by_id['outside']['status'], 'OUTSIDE_DOMAIN')
        with self.assertRaises(ValueError):
            joins.sites(rows, prepared, hierarchy, **dict(binding, expected_generation='stale'))
        with self.assertRaises(ValueError):
            joins.sites(rows, prepared, hierarchy, **dict(binding, expected_context={'world_id': 'other'}))
        with self.assertRaises(ValueError):
            joins.sites(rows, prepared, dict(hierarchy, u0=None), **binding)
        route = {'id': 'r', 'from_site': 'a', 'to_site': 'b', 'physical_travel_seconds': 30,
                 'permission': 'UNKNOWN', 'mode': 'walk', 'season': 'summer',
                 'evidence': 'explicit fixture', 'source_status': 'SYNTHETIC TEST'}
        unknown = joins.access([route], out, **binding)[0]
        self.assertEqual(unknown['physical_travel_seconds'], 30)
        self.assertIsNone(unknown['permitted_travel_seconds'])
        self.assertFalse(unknown['sovereignty_transfer'])
        allowed = joins.access([dict(route, permission='ALLOWED')], out, **binding)[0]
        self.assertEqual(allowed['permitted_travel_seconds'], 30)
        other = dict(context, world_id='other')
        with self.assertRaises(ValueError):
            joins.access([route], out, **dict(binding, context=other, expected_context=other))
        conditional = joins.access([dict(route, permission='CONDITIONAL')], out, **binding)[0]
        self.assertIsNone(conditional['permitted_travel_seconds'])
        with self.assertRaises(ValueError):
            joins.access([dict(route, physical_travel_seconds=float('nan'))], out, **binding)


if __name__ == '__main__':
    unittest.main()
