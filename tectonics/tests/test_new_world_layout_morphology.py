"""Focused synthetic guards for the descriptive new-world assessment tool."""
from concurrent.futures import CancelledError
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import threading
import unittest
from unittest import mock

import numpy as np

from atlas_tectonics import SphericalFrame, PlateLayoutSettings, generate_plate_layout, layout_metrics
from atlas_tectonics.plate_reference import AREA_ROWS
from atlas_tectonics.plate_reference_dataset import EARTH_REFERENCE_RADIUS_M
from atlas_tectonics.plate_reference_use import ReferenceUsePlan, reference_use_policy
from atlas_tectonics.resources import WorkBudget, MemoryLimitError


TOOL = Path(__file__).resolve().parents[1] / 'tools/assess_plate_layout_morphology.py'
spec = importlib.util.spec_from_file_location('layout_morphology_under_test', TOOL)
assessment = importlib.util.module_from_spec(spec)
spec.loader.exec_module(assessment)


class MorphologyAssessmentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.atlas = generate_plate_layout(
            SphericalFrame(EARTH_REFERENCE_RADIUS_M, 'synthetic-morphology-test'),
            PlateLayoutSettings(6, 41, 96))
        cls.budget = WorkBudget(128 << 20)
        cls.report = assessment.assess_layout(cls.atlas, run_id='synthetic-geometry', budget=cls.budget)

    def test_existing_geometry_invariants_and_seams(self):
        geometry = self.report['geometry']
        self.assertEqual(geometry['status'], 'PASS')
        self.assertEqual(geometry['euler_characteristic'], 2)
        self.assertEqual(geometry['directed_edge_uses'], 2 * self.atlas.edge_count)
        self.assertEqual(geometry['connected_components'], [1] * 6)
        self.assertTrue(geometry['longitude_seam_representations_agree'])
        self.assertEqual(len(geometry['pole_and_seam_owner_sets']), 8)
        self.assertTrue(all(geometry['pole_and_seam_owner_sets']))
        self.assertEqual(sum(geometry['junction_owner_count_histogram'].values()), self.atlas.vertex_count)
        self.assertEqual(geometry['vertices_and_edge_midpoints_checked'],
                         self.atlas.vertex_count + self.atlas.edge_count)

    def test_global_rotation_preserves_realised_geometry(self):
        rotation = self.report['global_rotation']
        self.assertEqual(rotation['status'], 'PASS')
        self.assertFalse(rotation['ownership_discrepancies'])
        for metric, error in rotation['maximum_absolute_differences'].items():
            self.assertLessEqual(error, rotation['existing_numerical_bounds'][metric])

    def test_report_never_promotes_science_or_hides_outline_coverage(self):
        self.assertFalse(self.report['scientific_acceptance'])
        self.assertEqual(self.report['reference_status'], 'NOT_SELECTED')
        self.assertEqual(len(self.report['outline_measurements']), 6)
        self.assertEqual({r['plate_id'] for r in self.report['outline_measurements']}, set(self.atlas.plate_ids))
        self.assertFalse(self.report['layout_metrics']['morphology_validated'])
        self.assertEqual(self.report['outline_geometry']['plates_attempted'], 6)
        self.assertEqual(self.report['outline_geometry']['status'], 'PASS')
        json.dumps(self.report, allow_nan=False)
        self.assertEqual(self.budget.reserved_bytes, 0)

    def test_owner_query_gap_cannot_pass_geometry(self):
        metrics = layout_metrics(self.atlas)
        native = assessment._owners
        def missing(*args, **kwargs):
            rows = native(*args, **kwargs)
            rows[0] = set()
            return rows
        with mock.patch.object(assessment, '_owners', side_effect=missing):
            row, _, _ = assessment._geometry(self.atlas, metrics, bounds=assessment._bounds(),
                                              budget=self.budget, cancel=None)
        self.assertEqual(row['status'], 'FAIL')
        self.assertIn(0, row['point_ownership_discrepancies'])
        self.assertEqual(self.budget.reserved_bytes, 0)

    def test_cancellation_and_memory_refusal_release(self):
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(CancelledError):
            assessment.assess_layout(self.atlas, run_id='cancelled', cancel=cancel)
        budget = WorkBudget(100)
        with self.assertRaises(MemoryLimitError):
            assessment.assess_layout(self.atlas, run_id='no-budget', budget=budget)
        self.assertEqual(budget.reserved_bytes, 0)

    def test_unresolved_outline_is_reported_not_filtered(self):
        with mock.patch.object(assessment, 'plate_outline_cycles', side_effect=assessment.GeometryError('pinched owner')):
            rows = assessment._shapes(self.atlas, budget=self.budget, cancel=None)
        self.assertEqual(len(rows), 6)
        self.assertTrue(all(row['status'] == 'UNRESOLVED_OUTLINE' for row in rows))
        values, unresolved = assessment._phase_population(rows, 0, 0, 'compactness')
        self.assertEqual(values, [])
        self.assertEqual(unresolved, 6)
        self.assertEqual(assessment._outline_geometry(self.report['layout_metrics'], rows,
                         assessment._bounds())['status'], 'FAIL_OR_INCOMPLETE')

    def _synthetic_reference(self, include_withheld):
        measured = next(row for row in self.report['outline_measurements'] if row['status'] == 'MEASURED')
        # A deliberately synthetic plan exercises the REAL immutable-use methods
        # and current reviewed exclusions without replaying reference verification.
        # It is never supplied as evidence of authentic PB2002 numerical checks.
        rows = [dict(plate_id=pid, table_area_sr=area, multiscale=measured['measures'])
                for pid, area in AREA_ROWS]
        report = dict(plates=rows, dataset={'synthetic': True},
            connectivity=dict(neighbours={pid: ['synthetic-neighbour'] for pid, _ in AREA_ROWS},
                              incidence_discrepancies=[]),
            status='SYNTHETIC_TEST_ONLY', unavailable_gates=['all authentic source verification'])
        plan = object.__new__(ReferenceUsePlan)
        values = dict(_report=report, _policy=reference_use_policy(),
            _plate_rows={row['plate_id']: row for row in rows},
            _scope_ids={split: tuple(row['plate_id'] for row in rows
                if (assessment.record_role(observable='outline', plate_id=row['plate_id'])
                    == 'WITHHELD_WITHIN_MODEL') == (split == 'withheld'))
                for split in ('development', 'withheld')},
            dataset_id='a' * 64, policy_id=reference_use_policy()['policy_id'], report_id='b' * 64)
        for key, value in values.items():
            object.__setattr__(plan, key, value)
        return assessment.prepare_reference(plan, include_withheld=include_withheld,
                                            run_id='synthetic-audited-selection')

    def test_common_scales_and_explicit_within_model_holdout(self):
        reference = self._synthetic_reference(True)
        rows = assessment._comparisons(self.atlas, self.report['layout_metrics'],
            self.report['outline_measurements'], reference, run_id='synthetic-comparison',
            budget=self.budget, cancel=None)
        area = next(row for row in rows if row['metric'] == 'area_fraction')
        self.assertEqual(area['split'], 'development')
        self.assertEqual(area['reference_count'], 52)
        withheld = [row for row in rows if row['split'] == 'withheld']
        self.assertTrue(withheld)
        self.assertTrue(all(row.get('geological_model_accepted', False) is False for row in rows))
        self.assertTrue(all(row['scientific_threshold'] is None for row in rows))
        shapes = [row for row in rows if row['metric'] == 'compactness']
        self.assertEqual({row['observation_scale_m'] for row in shapes}, set(assessment.OBSERVATION_SCALES_M))
        self.assertEqual({row['sampling_phase'] for row in shapes}, {0., .5})
        self.assertEqual(next(row for row in withheld if row['metric'] == 'neighbour_count')['independent_evidence_families'], 1)

    def test_withheld_not_selected_is_not_evaluated(self):
        rows = assessment._comparisons(self.atlas, self.report['layout_metrics'],
            self.report['outline_measurements'], self._synthetic_reference(False),
            run_id='development-only', budget=self.budget, cancel=None)
        self.assertFalse(any(row['split'] == 'withheld' for row in rows))

    def test_reference_preparation_honours_reviewed_use_and_holdout(self):
        reference = self._synthetic_reference(False)
        rows = {row['plate_id']: row for row in reference['shapes']}
        self.assertEqual(rows['PS']['status'], 'NOT_SELECTED_WITHHELD')
        self.assertEqual(rows['MS']['status'], 'EXCLUDED_BY_REFERENCE_USE_POLICY')
        self.assertFalse(rows['MS']['use_eligibility']['ordinary_surface_morphology']['eligible'])
        self.assertFalse(any(row['split'] == 'withheld' for row in reference['observations']))
        for row in reference['observations']:
            if row['metric'] not in ('area_fraction',):
                self.assertIn('MS', [item['plate_id'] for item in row['excluded']])
                self.assertEqual(row['policy_id'], reference['reference_use']['policy_id'])
        self.assertEqual(next(row for row in reference['observations']
                              if row['metric'] == 'area_fraction')['included_count'], 52)

    def test_adjacency_source_exclusions_stay_separate_from_unresolved(self):
        reference = self._synthetic_reference(True)
        records = assessment._comparisons(self.atlas, self.report['layout_metrics'],
            self.report['outline_measurements'], reference, run_id='restricted-neighbours',
            budget=self.budget, cancel=None)
        degree = next(row for row in records
                      if row['metric'] == 'neighbour_count' and row['split'] == 'development')
        excluded = {row['plate_id'] for row in degree['reference_selection']['excluded']}
        self.assertIn('MS', excluded)
        self.assertGreater(degree['excluded_reference'], 0)
        self.assertEqual(degree['unresolved_reference'], 0)
        self.assertNotIn('MS', degree['reference_selection']['plate_ids'])
        self.assertEqual(sum(len(row['reference_selection']['plate_ids']) for row in records
                             if row['metric'] == 'neighbour_count'), 43)
        json.dumps(reference, allow_nan=False)

    def test_rejected_cases_retained_and_not_retried(self):
        rejection = {'status': 'REJECTED_SEED', 'seed': 8, 'error': 'unresolved small plate'}
        accepted = {'status': 'GENERATED_NOT_ACCEPTED', 'seed': 7}
        callback = mock.Mock(side_effect=[SimpleNamespace(atlas=self.atlas, report=accepted),
                                         SimpleNamespace(atlas=None, report=rejection)])
        with mock.patch.object(assessment, 'assess_layout', return_value=self.report):
            report = assessment.assess_cases(['plan-a', 'plan-b'], generate=callback,
                run_id='retained-refusal', resolution_pairs=((0, 1),))
        self.assertEqual(callback.call_args_list, [mock.call('plan-a'), mock.call('plan-b')])
        self.assertEqual(report['attempted_cases'], 2)
        self.assertEqual(report['generated_cases'], 1)
        self.assertEqual(report['cases'][1]['generation'], rejection)
        self.assertIsNone(report['cases'][1]['assessment'])
        self.assertEqual(report['resolution_sensitivity'][0]['status'], 'UNRESOLVED_REFUSED_CASE')

    def test_resolution_differences_have_no_acceptance_threshold(self):
        changed = dict(self.report, candidate_id='b' * 64,
                       layout_metrics=dict(self.report['layout_metrics']))
        changed['layout_metrics']['area_fractions'] = [v + .01 for v in changed['layout_metrics']['area_fractions']]
        candidate = SimpleNamespace(atlas=self.atlas, report={'status': 'SYNTHETIC'})
        with mock.patch.object(assessment, 'assess_layout', side_effect=[self.report, changed]):
            series = assessment.assess_cases([0, 1], generate=lambda _: candidate,
                run_id='resolution-synthetic', resolution_pairs=((0, 1),))
        row = series['resolution_sensitivity'][0]
        self.assertEqual(row['status'], 'DESCRIPTIVE_GENERATING_SUPPORT_SENSITIVITY')
        self.assertIsNone(row['scientific_threshold'])
        np.testing.assert_allclose(row['metric_differences']['area_fractions'], .01)

    def test_assessment_refusal_preserves_generation_and_completed_prefix(self):
        candidate = SimpleNamespace(atlas=self.atlas, report={'status': 'SYNTHETIC_GENERATED'})
        with mock.patch.object(assessment, 'assess_layout',
                               side_effect=[self.report, assessment.GeometryError('unresolved diagnostic')]):
            series = assessment.assess_cases([0, 1], generate=lambda _: candidate, run_id='refused-assessment')
        self.assertIs(series['cases'][0]['assessment'], self.report)
        self.assertEqual(series['cases'][1]['generation'], candidate.report)
        self.assertIsNone(series['cases'][1]['assessment'])
        self.assertEqual(series['cases'][1]['assessment_error']['status'], 'REFUSED')
        self.assertEqual(series['generated_cases'], 2)
        self.assertEqual(series['assessed_cases'], 1)

    def test_cancellation_retains_prefix_and_does_not_start_another_case(self):
        candidate = SimpleNamespace(atlas=self.atlas, report={'status': 'SYNTHETIC_GENERATED'})
        callback = mock.Mock(return_value=candidate)
        with mock.patch.object(assessment, 'assess_layout', side_effect=[self.report, CancelledError('deadline')]):
            series = assessment.assess_cases([0, 1, 2], generate=callback,
                run_id='cancel-series', resolution_pairs=((0, 2),))
        self.assertEqual(callback.call_count, 2)
        self.assertEqual(series['cases'][1]['generation'], candidate.report)
        self.assertEqual(series['cases'][1]['assessment_error']['status'], 'CANCELLED')
        self.assertEqual(series['unattempted_case_indices'], [2])
        self.assertEqual(series['resolution_sensitivity'][0]['status'], 'UNRESOLVED_UNATTEMPTED_CASE')


if __name__ == '__main__':
    unittest.main()
