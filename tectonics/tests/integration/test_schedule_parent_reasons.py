"""R-11: the planner books each request the parent ran itself, with its seconds, under the reason that stood."""
import unittest

from atlas_shared.execution.schedule import Schedule


def _schedule():
    return Schedule(session=None, estimate=lambda label: None, beyond=lambda: 0, workers=2,
                    batch_seconds=1.0, batch_jobs=8, horizon=8, minimum_seconds=0.0, benefit_ratio=1.0,
                    timeout_seconds=60.0)


class _Busy:
    """A session whose every worker is busy: advance leaves its loop at once."""
    batches, log, seconds = [], [], {}

    def check(self):
        return True

    def running(self):
        return 2


class ParentReasons(unittest.TestCase):
    def test_never_offered_and_no_observations(self):
        schedule = _schedule()
        schedule.unlisted()
        schedule.ran(2.0)
        schedule.offer('job', 0.0, 'class')
        schedule.advance()
        schedule.reached()
        schedule.ran(1.5)
        report = schedule.report()
        self.assertEqual(report['parent_reasons'],
                         {'never offered': [1, 2.0], 'no compatible observations': [1, 1.5]})
        self.assertEqual(sum(seconds for _, seconds in report['parent_reasons'].values()), 3.5)
        self.assertEqual(report['reasons'], {'no compatible observations': 1})
        self.assertIsNone(report['stopped'])

    def test_every_worker_busy(self):
        schedule = _schedule()
        schedule.session = _Busy()
        schedule.offer('job', 0.0, 'class')
        schedule.advance()
        schedule.reached()
        schedule.ran(1.0)
        report = schedule.report()
        self.assertEqual(report['parent_reasons'], {'every worker busy': [1, 1.0]})
        self.assertIsNone(report['stopped'])


if __name__ == '__main__':
    unittest.main()
