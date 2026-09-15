"""Focused policy tests; no physical model or whole-case execution."""
from copy import deepcopy
from dataclasses import dataclass, replace
from fractions import Fraction as F
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from . import scheduling as s


@dataclass(frozen=True)
class Acceptance:
    max_surface_error_m: F = F(1)
    max_material_bulk_l1_error_m3: F = F(1)
    max_allocation_error_m3: F = F(100)
    max_halvings: int = 8
    evidence: str = 'unchanged fixture tolerances'


def diagnostics(duration, error=F(1, 32)):
    return {'duration_years': str(duration), 'surface_error_m': str(error),
            'material_bulk_l1_error_m3': str(error), 'cumulative_allocation_error_m3': '0',
            'topology_equal': True, 'within_operator_topology_change': False}


def row(*, start=F(10), requested=F(5), duration=F(5, 8), error=F(1, 32), acceptance=None):
    acceptance = acceptance or Acceptance()
    rejected, trial = [], requested
    while trial > duration:
        rejected.append(diagnostics(trial, F(2)))
        trial /= 2
    if trial != duration:
        raise ValueError('fixture requires an exact halving chain')
    return {'operation_id': 'accepted-' + str(start), 'start_year': str(start),
            'requested_duration_years': str(requested), 'duration_years': str(duration),
            'accepted_method': 'TWO_HALF_STEPS_FULL_TRIAL_DISCARDED',
            'acceptance': {key: str(value) if type(value) is F else value for key, value in vars(acceptance).items()},
            'diagnostics': diagnostics(duration, error), 'rejected_trials': rejected,
            'parent_state_sha256': '0' * 64, 'state_sha256': '1' * 64,
            'substeps': [{'hillslope': {'duration_years': str(duration / 2), 'total_bulk_allocation_error_m3': '0'},
                         'surface_runoff_m3': '0', 'surface_water_exported_m3': '0',
                         'numeric_compaction': {'total_l1_units': 0}} for _ in range(2)]}


def propose(latest, *, remaining=F(100), previous_count=0):
    elapsed = F(latest['start_year']) + F(latest['duration_years'])
    return s.propose_duration([latest], remaining, Acceptance(), elapsed_years=elapsed,
                              previous_count=previous_count)


class SchedulingTests(unittest.TestCase):
    def test_first_step_and_target_limit(self):
        for remaining, expected in ((F(100), F(5)), (F(3, 7), F(3, 7))):
            result = s.propose_duration([], remaining, Acceptance(), elapsed_years=F(0))
            self.assertEqual(result.duration_years, expected)
            self.assertEqual(result.remaining_halvings, 8)

    def test_rejected_chain_reuses_duration_and_preserves_absolute_floor(self):
        result = propose(row())
        self.assertEqual(result.duration_years, F(5, 8))
        self.assertEqual(result.skipped_halvings, 3)
        self.assertEqual(result.remaining_halvings, 5)
        self.assertEqual(result.duration_years / 2 ** result.remaining_halvings, F(5) / 2 ** 8)
        self.assertEqual(result.evidence['previous_rejected_durations_years'], ['5', '5/2', '5/4'])

    def test_target_clamp_and_changed_remaining_halving_grid(self):
        self.assertEqual(propose(row(duration=F(5)), remaining=F(1, 4)).duration_years, F(1, 4))
        result = propose(row(duration=F(5, 2)), remaining=F(3))
        self.assertEqual(result.duration_years, F(3, 2))
        self.assertEqual(result.duration_years / 2 ** result.remaining_halvings, F(3) / 2 ** 8)

    def test_invalid_history_and_stale_time_are_refused(self):
        invalid = []
        for key, value in (('duration_years', '0'), ('requested_duration_years', '3'),
                           ('accepted_method', 'unchecked'), ('start_year', '-1')):
            candidate = row()
            candidate[key] = value
            invalid.append(candidate)
        candidate = row()
        candidate['rejected_trials'][1]['duration_years'] = '2'
        invalid.append(candidate)
        candidate = row()
        candidate['diagnostics']['within_operator_topology_change'] = True
        invalid.append(candidate)
        candidate = row()
        candidate['acceptance']['max_surface_error_m'] = '2'
        invalid.append(candidate)
        candidate = row()
        candidate['rejected_trials'][0]['surface_error_m'] = '0'
        candidate['rejected_trials'][0]['material_bulk_l1_error_m3'] = '0'
        invalid.append(candidate)
        for candidate in invalid:
            with self.subTest(candidate=candidate), self.assertRaises(ValueError):
                propose(candidate)
        with self.assertRaises(ValueError):
            s.propose_duration([row()], F(100), Acceptance(), elapsed_years=F(12))

    def test_periodic_recovery_needs_clean_low_error_and_obeys_maximum(self):
        latest = row(requested=F(5, 8), acceptance=replace(Acceptance(), max_halvings=5))
        self.assertEqual(propose(latest, previous_count=1).duration_years, F(5, 8))
        result = propose(latest, previous_count=2)
        self.assertEqual(result.duration_years, F(5, 4))
        self.assertEqual(result.evidence['reason'], 'PERIODIC_LOW_ERROR_RECOVERY_PROBE')
        latest['diagnostics']['surface_error_m'] = '1/4'
        self.assertEqual(propose(latest, previous_count=2).duration_years, F(5, 8))
        self.assertEqual(propose(row(), previous_count=2).duration_years, F(5, 8))
        maximum = row(requested=F(5), duration=F(5))
        self.assertEqual(propose(maximum, previous_count=2).duration_years, F(5))

    def test_new_rejection_reduces_next_proposal_without_new_floor(self):
        latest = row(requested=F(5, 8), duration=F(5, 16),
                     acceptance=replace(Acceptance(), max_halvings=5))
        result = propose(latest, previous_count=2)
        self.assertEqual(result.duration_years, F(5, 16))
        self.assertEqual(result.remaining_halvings, 4)

    def test_size_guard_rejections_supported_and_unknown_kinds_refused(self):
        latest = row()
        latest['rejected_trials'][0] = {'duration_years': '5', 'kind': 'TerrainStepTooLarge', 'reason': 'guard'}
        self.assertEqual(propose(latest).duration_years, F(5, 8))
        latest['rejected_trials'][0]['kind'] = 'ArbitraryError'
        with self.assertRaises(ValueError):
            propose(latest)

    def test_deterministic_after_json_restart_and_input_unchanged(self):
        latest = row(requested=F(5, 8), acceptance=replace(Acceptance(), max_halvings=5))
        before = deepcopy(latest)
        self.assertEqual(propose(latest, previous_count=2), propose(json.loads(json.dumps(latest)), previous_count=2))
        self.assertEqual(latest, before)
        self.assertFalse(propose(latest).evidence['complete_scientific_body_identity_expected'])

    def test_resource_and_exact_input_bounds(self):
        for remaining in (F(0), F(-1), 0.5, True, 'NaN'):
            with self.subTest(remaining=remaining), self.assertRaises(ValueError):
                s.propose_duration([], remaining, Acceptance(), elapsed_years=F())
        with self.assertRaises(ValueError):
            propose(row(), previous_count=255)
        with self.assertRaises(ValueError):
            s.propose_duration([], F(5), Acceptance(), elapsed_years=F(), previous_count=True)

    def test_archive_reads_only_newest_authenticated_row_and_detects_tamper(self):
        from work.native_terrain_r3 import history as h
        with tempfile.TemporaryDirectory(prefix='native-r4-schedule-') as folder:
            archived = h.History.from_rows(folder, [row(start=F(5)), row()])
            with patch.object(h.History, '_raw', autospec=True, side_effect=h.History._raw) as reader:
                latest = s.latest_accepted_row(archived)
                self.assertEqual(latest, row())
                self.assertEqual(reader.call_count, 1)
                self.assertTrue(reader.call_args.kwargs['authenticate_summary'])
            restored = h.History.from_refs(folder, archived.refs)
            self.assertEqual(s.latest_accepted_row(restored), latest)
            path = Path(folder) / archived.refs[-1]['path']
            raw = path.read_bytes()
            path.write_bytes(bytes([raw[0] ^ 1]) + raw[1:])
            with self.assertRaises(ValueError):
                s.latest_accepted_row(archived)


if __name__ == '__main__':
    unittest.main()
