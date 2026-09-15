"""Focused native parity and retained ancestry validation checks."""
from copy import deepcopy
from dataclasses import replace
from fractions import Fraction as F
import unittest
from unittest.mock import patch

from work.native_terrain_r1 import domain
from work.native_terrain_r2 import evolve as numerical
from work.native_terrain_r2.test_evolve import ContinuingStateTests as Fixture
from . import trials


class TrialTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Fixture.setUpClass()
        cls.addClassCleanup(Fixture.doClassCleanups)

    def args(self):
        body = Fixture.migrated['body']
        return (numerical._native(body), body['palette'], body['lineage'],
                body['exported_origin_mass_kg'], F(1), 'mapping-test',
                F(body['surface_water_exported_m3']))

    def test_exact_full_accepted_body_and_input_preservation(self):
        executor = trials.from_executor(Fixture.executor)
        before = deepcopy(Fixture.migrated)
        actual = executor.advance(Fixture.migrated, F(1), Fixture.acceptance,
                                  operation_id='successor-once')
        self.assertEqual(actual, Fixture.first)
        self.assertEqual(Fixture.migrated, before)

    def test_one_mapping_per_substep_replaces_two_without_global_mutation(self):
        actual_mapping = domain.channel_layer_sources
        outer_mapping = numerical.channel_layer_sources
        with patch.object(domain, 'channel_layer_sources', wraps=actual_mapping) as inside:
            with patch.object(numerical, 'channel_layer_sources', wraps=outer_mapping) as outside:
                expected = Fixture.executor._substep(*self.args())
                self.assertEqual((inside.call_count, outside.call_count), (1, 1))
                inside.reset_mock()
                outside.reset_mock()
                actual = trials.substep(Fixture.executor, *self.args())
                self.assertEqual((inside.call_count, outside.call_count), (1, 0))
        self.assertEqual(actual, expected)
        self.assertIs(domain.channel_layer_sources, actual_mapping)
        self.assertIs(numerical.channel_layer_sources, outer_mapping)

    def test_corrupt_erosion_ancestry_keeps_original_failure_and_input(self):
        actual_mapping = domain.channel_layer_sources

        def corrupt(before, trial):
            event, *tail = trial.erosion_events
            changed = dict(event, remaining_mass_kg=event['remaining_mass_kg'] + F(1))
            return actual_mapping(before, replace(trial, erosion_events=(changed, *tail)))

        args = self.args()
        before = deepcopy(args)
        failures = []
        with patch.object(domain, 'channel_layer_sources', side_effect=corrupt):
            for step in (Fixture.executor._substep,
                         lambda *values: trials.substep(Fixture.executor, *values)):
                with self.assertRaises(ValueError) as failure:
                    step(*args)
                failures.append(str(failure.exception))
        self.assertEqual(failures, ['channel erosion source identity or finite split differs'] * 2)
        self.assertEqual(args, before)

    def test_rejection_keeps_original_failure_and_input(self):
        acceptance = replace(Fixture.acceptance, max_surface_error_m=F(),
                             max_material_bulk_l1_error_m3=F(), max_halvings=0)
        before = deepcopy(Fixture.migrated)
        failures = []
        for executor in (Fixture.executor, trials.from_executor(Fixture.executor)):
            with self.assertRaises(ValueError) as failure:
                executor.advance(Fixture.migrated, F(1), acceptance, operation_id='reject')
            failures.append(str(failure.exception))
        self.assertEqual(failures[0], failures[1])
        self.assertEqual(Fixture.migrated, before)


if __name__ == '__main__':
    unittest.main()
