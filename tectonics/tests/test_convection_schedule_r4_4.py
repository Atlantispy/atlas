"""Cheap schedule checks must precede costly numerical execution."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import run_convection_r4_4 as runner


class ScheduleTests(unittest.TestCase):
    def config(self, case='tosi-1', **changes):
        result = dict(case=dict(name=case),dt=1e-5,maximum_steps=30000,sample_every=25,save_every=500)
        result.update(changes)
        return result

    def assess(self, config):
        return runner.schedule_feasibility(config,json.loads((ROOT/'cases/convection_r4_4.json').read_bytes()))

    def test_incompatible_final_sample_refused_before_output_or_solver(self):
        with tempfile.TemporaryDirectory() as folder:
            output=Path(folder)/'run'
            args=runner.parser().parse_args(['--output',str(output),'--max-steps','7',
                '--sample-every','2','--save-every','2'])
            with mock.patch.object(runner.atlas,'PreparedThermochemical2D') as solver:
                with self.assertRaisesRegex(ValueError,'maximum steps must be a multiple'):
                    runner.main(args)
                solver.assert_not_called()
            self.assertFalse(output.exists())

    def test_default_steady_schedule_has_no_known_blocker_not_acceptance(self):
        r=self.assess(self.config())
        self.assertEqual(r['known_blockers'],[])
        self.assertFalse(r['benchmark_accepted'])

    def test_short_runs_and_coarse_diagnostics_are_explicitly_inadequate(self):
        for change in (dict(maximum_steps=4,sample_every=1),dict(sample_every=1000,save_every=1000)):
            self.assertEqual(self.assess(self.config(**change))['status'],'INSUFFICIENT_FOR_MATURITY')

    def test_default_periodic_duration_and_saved_fields_are_inadequate(self):
        r=self.assess(self.config('tosi-5a'))
        self.assertEqual(len(r['known_blockers']),2)
        self.assertIn('Duration',r['known_blockers'][0])
        self.assertIn('Saved-field',r['known_blockers'][1])

    def test_resolved_periodic_schedule_is_not_declared_mature(self):
        r=self.assess(self.config('tosi-5a',maximum_steps=100000,save_every=50))
        self.assertEqual(r['known_blockers'],[])
        self.assertFalse(r['benchmark_accepted'])

    def test_case5b_period_is_not_invented(self):
        r=self.assess(self.config('tosi-5b'))
        self.assertTrue(any('regime and period' in text for text in r['unknowns']))
        self.assertFalse(r['benchmark_accepted'])

    def test_malformed_schedule_is_not_reported_feasible(self):
        for change in (dict(dt=float('nan')),dict(dt=-1),dict(sample_every=0),
                       dict(maximum_steps=True),dict(save_every=26),dict(case=dict(name='unknown'))):
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.assess(self.config(**change))


if __name__=='__main__':unittest.main()
