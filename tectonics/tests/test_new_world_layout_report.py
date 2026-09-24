"""Focused final report guard; no native work or campaign replay."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from check_new_world_layout import summarise_series


class LayoutReportTests(unittest.TestCase):
    def series(self):
        cases = []
        for first in (.5, .6, .7):
            cases.append(dict(generation=dict(atlas_id='a'*64), assessment=dict(
                geometry=dict(status='PASS'), outline_geometry=dict(status='PASS'),
                global_rotation=dict(status='PASS', cut_rotation=dict(status='PASS')),
                layout_metrics=dict(ranked_area_fractions=[first, 1-first]))))
        cases.append(dict(generation=dict(atlas_id=None, status='REJECTED'), assessment=None))
        return dict(cases=cases, requested_cases=4, attempted_cases=4, unattempted_case_indices=[])

    def test_expected_refusal_does_not_erase_successful_cases(self):
        result = summarise_series(self.series())
        self.assertTrue(result['numerical_geometry_pass'])
        self.assertTrue(result['three_seed_rotation_invariant_diversity'])

    def test_missing_failed_or_unattempted_diagnostics_never_pass(self):
        source = self.series()
        for key in ('geometry','outline_geometry','global_rotation'):
            for value in ({}, dict(status='FAIL')):
                series = deepcopy(source)
                series['cases'][0]['assessment'][key] = value
                self.assertFalse(summarise_series(series)['numerical_geometry_pass'])
        series = deepcopy(source)
        series['cases'][0]['assessment'] = None
        series['cases'][0]['assessment_error'] = dict(status='REFUSED')
        self.assertFalse(summarise_series(series)['numerical_geometry_pass'])
        series = deepcopy(source)
        series['cases'][-1]['generation'] = None
        self.assertFalse(summarise_series(series)['numerical_geometry_pass'])
        series = deepcopy(source)
        series['unattempted_case_indices'] = [4]
        series['requested_cases'] = 5
        self.assertFalse(summarise_series(series)['numerical_geometry_pass'])

    def test_diversity_uses_first_three_not_a_replacement_resolution(self):
        series = self.series()
        series['cases'][0]['assessment'] = None
        self.assertFalse(summarise_series(series)['three_seed_rotation_invariant_diversity'])


if __name__ == '__main__':
    unittest.main()
