"""S4 (item 20): a first session refused by the machine gates is looked for again later.

Fake session and clock only. What must hold: a LATER open neither stops the schedule nor
changes the parent's order; the retry waits for its interval; the retries are bounded; a
None open (refused session/funding) still stops at once; once open, batches launch as usual.
Run with SO_PKG naming the package root to test (candidate or base).
"""
import os
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [os.environ.get('SO_PKG', str(HERE/'pkg')), os.environ.get('SO_HELPERS', str(HERE/'helpers'))]

from atlas_tectonics import integration_parallel_rolling as RB  # noqa: E402


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class FakeSession:
    def __init__(self):
        self.batches, self.log, self.seconds = {}, [], {}
        self.stats = {'refused': 0}
        self.launched, self.retired, self.on_wait, self.last_error = [], [], None, None

    def running(self):
        return sum(1 for batch in self.batches.values() if not batch['done'])

    def check(self):
        return True

    def ended(self):
        return 'ended', None

    def active(self):
        return True

    def done(self, batch):
        return batch['done']

    def launch(self, jobs, timeout):
        index = len(self.launched)
        batch = self.batches[index] = dict(index=index, jobs=list(jobs), done=False)
        self.launched.append(batch)
        return batch

    def retire(self, batch):
        self.retired.append(batch['index'])
        self.batches.pop(batch['index'], None)


def schedule(opener, clock):
    return RB.Schedule(session=opener, estimate=lambda label: (2.0, 3.0), beyond=lambda: 0, workers=2,
                       batch_seconds=4.0, batch_jobs=8, horizon=64, minimum_seconds=1.0,
                       startup_seconds=0.1, transfer_seconds=0.01, contention=1.0, benefit_ratio=1.0,
                       timeout_seconds=60.0, clock=clock)


class RetryTests(unittest.TestCase):
    def run_pass(self, answers, requests=40, step=1.0):
        """Offer requests in order; the parent reaches each one and runs it for step seconds."""
        clock, opens = Clock(), []

        def opener():
            opens.append(clock.now)
            answer = answers[min(len(opens), len(answers))-1]
            return answer() if callable(answer) else answer
        plan = schedule(opener, clock)
        order = []
        for index in range(requests):
            while plan.hungry() and plan.offered < requests:
                plan.offer(('job', plan.offered), 0.0, 'class')
            plan.advance()
            kept = plan.reached()
            order.append((index, kept))
            if kept:
                plan.ran(step)
            clock.now += step
        plan.close()
        return plan, opens, order

    def test_later_defers_then_opens_and_launches(self):
        session = FakeSession()
        plan, opens, order = self.run_pass([RB.LATER, RB.LATER, lambda: session], requests=100)
        self.assertIsNone(plan.stopped)
        # Retries wait their intervals: 15 s, then 30 s after the second refusal.
        self.assertEqual(len(opens), 3)
        self.assertGreaterEqual(opens[1]-opens[0], RB.DEFER)
        self.assertGreaterEqual(opens[2]-opens[1], 2*RB.DEFER)
        self.assertIs(plan.session, session)
        self.assertTrue(session.launched)
        self.assertEqual(plan.reasons.get('session deferred'), 2)
        self.assertEqual(plan.report()['route'], 'parallel')
        # The parent's order is the offer order whatever was held.
        self.assertEqual([index for index, _ in order], list(range(100)))
        # Requests the parent reached before the late open were all its own.
        self.assertTrue(all(kept for index, kept in order if index < opens[2]))

    def test_retries_are_bounded(self):
        plan, opens, _ = self.run_pass([RB.LATER], requests=4000, step=1.0)
        self.assertEqual(len(opens), RB.DEFERRALS+1)
        self.assertEqual(plan.stopped, 'session not opened')
        self.assertEqual(plan.reasons.get('session deferred'), RB.DEFERRALS)
        gaps = [b-a for a, b in zip(opens, opens[1:], strict=False)]
        self.assertTrue(all(gap >= min(RB.DEFER_MAX, RB.DEFER*2**i) for i, gap in enumerate(gaps)))
        self.assertLessEqual(max(gaps), RB.DEFER_MAX+1.0)
        self.assertIn('all %d first opens' % (RB.DEFERRALS+1), plan.detail)

    def test_pass_ending_mid_deferral_reports_no_session(self):
        plan, opens, _ = self.run_pass([RB.LATER], requests=5)
        self.assertEqual(len(opens), 1)
        report = plan.report()
        self.assertEqual((report['route'], report['stopped']), ('serial', 'session not opened'))
        self.assertEqual(plan.reasons.get('session deferred'), 1)
        self.assertIn('1 machine-gate refusal', report['detail'])

    def test_none_still_stops_at_once(self):
        plan, opens, _ = self.run_pass([None])
        self.assertEqual(len(opens), 1)
        self.assertEqual(plan.stopped, 'session not opened')
        self.assertEqual(plan.report()['route'], 'serial')

    def test_no_planning_between_retries(self):
        clock = Clock()
        plan = schedule(lambda: RB.LATER, clock)
        for index in range(20):
            plan.offer(('job', index), 0.0, 'class')
        plan.advance()
        planned = plan.totals['plans']
        for _ in range(100):
            plan.advance()
        self.assertEqual(plan.totals['plans'], planned)
        clock.now = RB.DEFER
        plan.advance()
        self.assertEqual(plan.totals['plans'], planned+1)

    def test_open_answer_shapes_in_rolling_and_endpoints(self):
        from atlas_tectonics import integration_parallel_selection as S
        from atlas_tectonics import integration_component_volume_auto as A
        for cls in (S._Rolling, A.AutomaticEndpoints):
            owner = object.__new__(cls)
            owner.notes = []
            owner._machine = lambda: ('cpu', 'fewer free cores than the parent and its workers need')
            self.assertIs(owner._open(), RB.LATER, cls.__name__)
            self.assertEqual(owner.notes, ['cpu: fewer free cores than the parent and its workers need'])
            # The same gate again keeps one (latest) note; another gate adds one.
            owner._machine = lambda: ('cpu', 'still busy')
            self.assertIs(owner._open(), RB.LATER, cls.__name__)
            self.assertEqual(owner.notes, ['cpu: still busy'])
            owner._machine = lambda: ('memory', 'too little free memory')
            self.assertIs(owner._open(), RB.LATER, cls.__name__)
            self.assertEqual(owner.notes, ['cpu: still busy', 'memory: too little free memory'])
            # A gate no later look can pass stops the open as before.
            owner._machine = lambda: ('psutil', 'psutil is required to watch and stop a worker')
            self.assertIsNone(owner._open(), cls.__name__)


if __name__ == '__main__':
    unittest.main()
