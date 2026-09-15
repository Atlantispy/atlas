"""Focused whole-plot exclusion/permission geometry oracle; no crop or world run."""
from copy import deepcopy
import unittest

from shapely.geometry import box, mapping, MultiPolygon
from work.generator_upgrade_r21 import land


class LandTests(unittest.TestCase):
    def test_whole_plots_exclusions_uncertainty_and_no_clearance_promotion(self):
        def plot(ident, geometry, **changes):
            return dict({'id': ident, 'geometry': mapping(geometry), 'crop_ids': ['test-crop'],
                'management_permission': 'ALLOWED', 'evidence': 'explicit synthetic productive-plot hypothesis',
                'source_status': 'SYNTHETIC TEST', 'source_role': 'EXPLICIT_PLOT_HYPOTHESIS'}, **changes)
        plots = [plot('free', box(0, 0, 2, 2)), plot('blocked', box(2, 0, 4, 2)),
                 plot('multi', MultiPolygon([box(0, 3, 1, 4), box(2, 3, 3, 4)])),
                 plot('proxy', box(4, 0, 5, 1), source_role='ROOTREACH_NO_CLEARANCE_PROXY')]
        declared = mapping(box(-1, -1, 6, 6))
        layers = [{'id': 'protected', 'geometries': [mapping(box(2, 0, 3, 1))],
                   'rule': 'PROTECTED_FOOTPRINT', 'evidence': 'explicit synthetic exclusion',
                   'source_status': 'SYNTHETIC TEST'}]
        admission = {'scenario_id': 'whole-plot-synthetic', 'source_status': 'SYNTHETIC TEST',
            'evidence': 'explicit complete toy masks; no actual-world admission',
            'land_complete': True, 'exclusions_complete': True,
            'required_exclusion_rules': ['PROTECTED_FOOTPRINT'], 'forbidden_source_roles': []}
        before = deepcopy((plots, declared, layers, admission))
        result = land.prepare(plots, declared, layers, admission=admission)
        self.assertEqual((plots, declared, layers, admission), before)
        self.assertEqual(result['status'], 'PREPARED')
        rows = {row['id']: row for row in result['plots']}
        self.assertEqual(rows['free']['allowed_crop_ids'], ['FALLOW', 'test-crop'])
        self.assertEqual(rows['free']['exclusion_ids'], [])  # Shared edge is not excluded area.
        self.assertEqual(rows['blocked']['allowed_crop_ids'], ['FALLOW'])
        self.assertEqual(rows['blocked']['crop_ids'], ['test-crop'])
        self.assertEqual(rows['proxy']['allowed_crop_ids'], ['FALLOW'])
        self.assertEqual(rows['multi']['area_m2_exact'], '2')
        for row in plots:
            self.assertEqual(rows[row['id']]['geometry'], row['geometry'])
        self.assertEqual(result['ledger']['candidate_area_sum_m2_exact'], '11')
        self.assertEqual(result['ledger']['candidate_union_area_m2_exact'], '11')
        self.assertEqual(result['ledger']['double_count_area_m2_exact'], '0')
        self.assertEqual(result['ledger']['classification_residual_m2_exact'], '0')
        unknown = deepcopy(plots); unknown[0]['management_permission'] = 'UNKNOWN'
        uncertain = land.prepare(unknown, declared, layers, admission=admission)
        self.assertEqual(uncertain['status'], 'INPUT_INCOMPLETE')
        self.assertIsNone(next(row for row in uncertain['plots'] if row['id'] == 'free')['allowed_crop_ids'])
        missing = deepcopy(admission); missing['exclusions_complete'] = None
        self.assertEqual(land.prepare(plots, declared, [], admission=missing)['status'], 'INPUT_INCOMPLETE')
        status_proxy = deepcopy(plots); status_proxy[0]['source_status'] = 'INCOMPLETE_MODELLED_NO_CLEARANCE_PROXY'
        promoted = land.prepare(status_proxy, declared, layers, admission=admission)
        self.assertEqual(next(row for row in promoted['plots'] if row['id'] == 'free')['allowed_crop_ids'], ['FALLOW'])
        overlapping = [plot('one', box(0, 0, 2, 2)), plot('two', box(1, 0, 3, 2))]
        with self.assertRaises(ValueError):
            land.prepare(overlapping, declared, layers, admission=admission)


if __name__ == '__main__':
    unittest.main()
