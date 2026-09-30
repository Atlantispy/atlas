"""Focused I02.4 checks: the real coupled column advanced only under one accepted clock of whole global steps.

Several requests with savepoints must follow the same numerical path as one uninterrupted run, bitwise, without
re-solving an accepted stage or rebuilding an operator; every commit spans whole steps at exactly the recorded times.
Fractional, over-limit and backward requests refuse before any work; the cumulative ceiling cannot be reset; an
unsupported event stops the clock before it; cancellation, retained refusals and expired budgets commit the accepted
whole steps and report the last accepted time; a competing writer makes a clock stale. Both commit sites share one
retry, so a failure the retry recovers from changes nothing and a propagating exception says whether its steps were
committed. A transfer declares its interval of whole steps, and that interval is committed with it or not at all.
SPDX-License-Identifier: AGPL-3.0-only
"""
from pathlib import Path
import sys
import tempfile
import time
import types
import unittest
from unittest import mock

import numpy as np
from threadpoolctl import threadpool_limits

from atlas_tectonics import _integration_heat as H, _integration_weakening as W
from atlas_tectonics import integration_clock as K, integration_evolution as E, integration_ledger as L
from atlas_tectonics import integration_state as I
from atlas_tectonics._validation import TectonicsError
from atlas_tectonics.storage import StoreError
from atlas_tectonics.timebase import advance_time

sys.path.insert(0, str(Path(__file__).resolve().parent))
import i02_workflow_fixtures as F

FIX = {}
STEPS = 16                                   # dt = 6.25e12 s over the retained 1e14 s horizon


def setUpModule():
    with threadpool_limits(limits=1, user_api='blas'):
        FIX['prepared'] = F.preparation()
        state = F.root(STEPS, prepared=FIX['prepared'])
        whole = I.Continuation(state)
        FIX['root'], FIX['whole'] = state, whole.advance(state, STEPS).state


def feed(start, end, label='feed', **changes):
    values = dict(label=label, producer='clock-check', donor='inflow', receiver='store-b',
                  component_mass_kg={'A': .5, 'B': .25}, enthalpy_j=-.75, basis=F.BASIS, start_step=start,
                  end_step=end)
    return L.Transfer(**dict(values, **changes))


def cancelled_after(steps):
    polls = []

    def cancel():
        polls.append(1)
        return len(polls) > steps
    return cancel


class Limited(unittest.TestCase):
    def setUp(self):
        lease = threadpool_limits(limits=1, user_api='blas')
        self.addCleanup(lease.restore_original_limits)
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.folder = Path(directory.name)
        self.store = F.store(self.folder/'ledger'/'ledger.sqlite')
        self.addCleanup(self.store.close)

    def ledger(self, state=None, **kwargs):
        return L.Ledger.create(self.store, FIX['root'] if state is None else state, **kwargs)


class ClockTests(Limited):
    def test_requests_and_savepoints_follow_the_uninterrupted_path_bitwise(self):
        ledger, root = self.ledger()
        clock = K.Clock(ledger)
        calls, original = [], E.stage

        def counted(*args, **kwargs):
            calls.append(args[3])
            return original(*args, **kwargs)
        refuse = dict(side_effect=AssertionError('a request rebuilt a prepared operator'))
        with mock.patch.object(E, 'stage', side_effect=counted), mock.patch.object(H, 'eigh', **refuse), \
                mock.patch.object(H, 'prepare_propagator', **refuse), \
                mock.patch.object(H, 'prepare_thermal', **refuse), mock.patch.object(W, 'prepare', **refuse):
            outcomes = [clock.advance(steps=3), clock.advance(steps=5, savepoint_steps=2),
                        clock.advance(until_s=clock.time_at(12)), clock.advance(steps=4, savepoint_steps=100)]
        self.assertEqual([o.status for o in outcomes], [K.COMPLETED]*3+[K.HISTORY_COMPLETE])
        self.assertEqual([o.accepted_steps for o in outcomes], [3, 5, 4, 4])
        self.assertEqual(len(calls), 1+2*STEPS)                  # the reference balance once, two stages per step
        commits = [c for o in outcomes for c in o.commits]
        self.assertEqual([c.interval[2:] for c in commits], [(0, 3), (3, 4), (4, 6), (6, 8), (8, 12), (12, 16)])
        for commit in commits:
            self.assertEqual(commit.interval[1], clock.time_at(commit.accepted_steps))
            self.assertEqual(commit.elapsed_s, commit.accepted_steps*FIX['root'].settings.step_s)
        head = ledger.head()
        self.assertEqual((head.key, head.sequence, head.accepted_steps), (commits[-1].key, 6, STEPS))
        final, whole = ledger.state(head), FIX['whole']
        self.assertEqual(final.column.column_state_id, whole.column.column_state_id)     # one numerical path
        for name in ('theta_k', 'kappa', 'yield_stage_counts'):
            self.assertEqual(getattr(final.column, name).tobytes(), getattr(whole.column, name).tobytes())
        self.assertEqual(final.column.accounts_j_m, whole.column.accounts_j_m)
        self.assertEqual((outcomes[-1].time_s, outcomes[-1].step), (whole.time_s, STEPS))

    def test_off_schedule_backward_and_over_limit_requests_refuse_before_work(self):
        ledger, root = self.ledger()
        clock = K.Clock(ledger)
        clock.advance(steps=2)
        half = (clock.time_at(3)+clock.time_at(4))/2
        refused = {
            'fractional end time': dict(until_s=half),
            'end time at the head': dict(until_s=clock.time_at(2)),
            'end time behind the head': dict(until_s=clock.time_at(1)),
            'zero steps': dict(steps=0),
            'boolean steps': dict(steps=True),
            'float steps': dict(steps=2.0),
            'both forms': dict(steps=1, until_s=clock.time_at(3)),
            'neither form': dict(),
            'beyond the remaining steps': dict(steps=STEPS-1),
            'beyond the schedule end': dict(until_s=clock.time_at(STEPS)+1e9),
            'zero savepoint interval': dict(steps=1, savepoint_steps=0),
            'untyped event': dict(steps=1, events=('savepoint',)),
            'fractional savepoint event': dict(steps=4, events=(K.Event(half, K.SAVEPOINT, 's'),)),
            'event behind the head': dict(steps=1, events=(K.Event(clock.time_at(1), 'rift', 'e'),)),
            'uncallable cancel': dict(steps=1, cancel=3),
        }
        for name, request in refused.items():
            with self.subTest(name), self.assertRaises(TectonicsError):
                clock.advance(**request)
        self.assertEqual(ledger.head().accepted_steps, 2)
        self.assertEqual(ledger.head().sequence, 1)

    def test_cumulative_limits_and_the_head_cannot_be_reset(self):
        ledger, root = self.ledger()
        clock = K.Clock(ledger)
        self.assertEqual(clock.advance(steps=STEPS).status, K.HISTORY_COMPLETE)
        with self.assertRaisesRegex(K.ClockError, 'never reset'):
            clock.advance(steps=1)
        with self.assertRaisesRegex(K.ClockError, 'never reset'):
            K.Clock(ledger).advance(steps=1)
        with self.assertRaisesRegex(K.ClockError, 'accepted head'):
            K.Clock(ledger, head=root)                               # no branch from an earlier commit
        with self.assertRaisesRegex(L.LedgerError, 'never reset'):
            L.Ledger.create(self.store, ledger.state(ledger.head()))  # an accepted state cannot pose as a root
        with self.assertRaises(TectonicsError):
            F.settings(257, F.DURATION)                               # the 256-step ceiling stays cumulative
        with self.assertRaises(TectonicsError):
            F.settings(STEPS, 2*F.DURATION)                           # the 1e14 s horizon stays the retained one

    def test_savepoint_events_commit_on_whole_steps(self):
        ledger, root = self.ledger()
        clock = K.Clock(ledger)
        outcome = clock.advance(steps=6, events=(K.Event(clock.time_at(2), K.SAVEPOINT, 'a'),
                                                 K.Event(clock.time_at(5), K.SAVEPOINT, 'b'),
                                                 K.Event(clock.time_at(9), K.SAVEPOINT, 'later')))
        self.assertEqual([c.accepted_steps for c in outcome.commits], [2, 5, 6])

    def test_an_unsupported_event_declared_with_the_ledger_stops_every_clock_before_it(self):
        settings = FIX['root'].settings
        at = lambda k: advance_time(FIX['root'].start_time_s, k*settings.step_s)
        rift = K.Event((at(5)+at(6))/2, 'rift-onset', 'declared-rift')
        ledger, root = self.ledger(calendar=(rift,))
        self.assertEqual(ledger.calendar, ((rift.time_s, 'rift-onset', 'declared-rift'),))
        clock = K.Clock(ledger)
        stopped = clock.advance(steps=10, savepoint_steps=2)
        self.assertEqual((stopped.status, stopped.accepted_steps, stopped.step), (K.REFUSED_UNSUPPORTED_EVENT, 5, 5))
        self.assertEqual((stopped.event, stopped.time_s), (rift, at(5)))
        self.assertIn('not supported', stopped.reason)
        self.assertEqual([c.accepted_steps for c in stopped.commits], [2, 4, 5])
        for again in (clock.advance(steps=1), K.Clock(ledger).advance(steps=3)):    # no re-declaration needed
            self.assertEqual((again.status, again.accepted_steps, again.step), (K.REFUSED_UNSUPPORTED_EVENT, 0, 5))
        piece = clock.continuation.advance(ledger.state(ledger.head()), 1).state
        with self.assertRaisesRegex(L.LedgerError, 'step past'):
            ledger.commit(ledger.head(), (piece,))                    # the ledger refuses it independently
        with self.assertRaisesRegex(K.ClockError, 'ledger calendar'):
            clock.advance(steps=1, events=(K.Event(at(7), 'rift-onset', 'request-only'),))
        on_step = K.Event(at(8), 'collision', 'declared-collision')
        other, _ = L.Ledger.create(self.store, FIX['root'], calendar=(on_step,))
        reached = K.Clock(other).advance(steps=STEPS)                 # up to the event time, never beyond it
        self.assertEqual((reached.status, reached.step), (K.REFUSED_UNSUPPORTED_EVENT, 8))
        self.assertEqual(K.Clock(other).advance(steps=1).accepted_steps, 0)
        half, late = (at(3)+at(4))/2, at(STEPS)+1e9
        for bad in (((at(1), 'rift onset', 'x'),), ((at(1), 'rift', 'caf\u00e9'),), ((-1., 'rift', 'x'),),
                    ((half, K.SAVEPOINT, 'half-step'),), ((late, K.SAVEPOINT, 'late'),), ((late, 'rift', 'late'),)):
            with self.subTest(bad=ascii(bad)), self.assertRaises(TectonicsError):
                L.Ledger.create(self.store, FIX['root'], calendar=bad)   # no entry can leave a clock unable to plan
        declared, _ = L.Ledger.create(self.store, FIX['root'], calendar=((at(3), K.SAVEPOINT, 'declared'),))
        self.assertEqual([c.accepted_steps for c in K.Clock(declared).advance(steps=5).commits], [3, 5])

    def test_an_exception_mid_request_keeps_the_accepted_steps_and_the_warm_path(self):
        ledger, root = self.ledger()
        clock = K.Clock(ledger)
        polls = []

        def interrupted():
            polls.append(1)
            if len(polls) == 4:
                raise KeyboardInterrupt
            return False
        with self.assertRaises(KeyboardInterrupt):
            clock.advance(steps=10, savepoint_steps=8, cancel=interrupted)
        self.assertEqual(ledger.head().accepted_steps, 3)                  # accepted whole steps were kept
        rest = clock.advance(steps=STEPS-3)
        self.assertEqual(rest.status, K.HISTORY_COMPLETE)
        self.assertEqual(ledger.state(ledger.head()).column.column_state_id, FIX['whole'].column.column_state_id)

    def test_an_interruption_while_an_exchange_commit_is_written_keeps_its_transfers(self):
        stocked = F.root(STEPS, prepared=FIX['prepared'], stocks=F.reservoirs(), basis=F.BASIS)
        ledger, root = self.ledger(stocked, exteriors=(('inflow', 'source'),))
        mix = L.Transfer(label='mix', producer='clock-check', donor='store-b', receiver='store-a',
                         component_mass_kg={'A': .5, 'B': 0.}, enthalpy_j=1.5, basis=F.BASIS, start_step=2,
                         end_step=4)
        apply, put = L._apply, self.store.put

        def once(original, error):
            calls = []

            def call(*args, **kwargs):
                calls.append(1)
                if len(calls) == 1:
                    raise error          # while the commit carrying the transfer is prepared or written
                return original(*args, **kwargs)
            return call
        with mock.patch.object(L, '_apply', once(apply, KeyboardInterrupt())), \
                self.assertRaises(KeyboardInterrupt) as caught:
            K.Clock(ledger).advance(steps=2, transfers=(feed(0, 2),))
        head = ledger.head()
        self.assertEqual((head.accepted_steps, len(head.transfer_ids)), (2, 1))           # steps and transfer together
        np.testing.assert_array_equal(ledger.exchange(head).inventory.component_mass_kg, [[5., 2.], [1.5, .75]])
        self.assertIn('committed as %s' % head.key, '\n'.join(caught.exception.__notes__))
        # An ordinary failure that the retry recovers from changes nothing: the request completes.
        with mock.patch.object(self.store, 'put', once(put, StoreError('storage transaction failed'))):
            outcome = K.Clock(ledger).advance(steps=2, transfers=(mix,))
        self.assertEqual((outcome.status, [c.accepted_steps for c in outcome.commits]), (K.COMPLETED, [4]))
        head = ledger.head()
        self.assertEqual((head.accepted_steps, len(head.transfer_ids)), (4, 1))
        np.testing.assert_array_equal(ledger.exchange(head).inventory.component_mass_kg, [[5.5, 2.], [1., .75]])
        self.assertEqual(K.Clock(ledger).advance(steps=1).accepted_steps, 1)             # the history continues

    def test_a_commit_that_fails_every_time_with_its_transfers_commits_neither_and_says_so(self):
        stocked = F.root(STEPS, prepared=FIX['prepared'], stocks=F.reservoirs(), basis=F.BASIS)
        ledger, root = self.ledger(stocked, exteriors=(('inflow', 'source'),))
        put = self.store.put

        def refusing(key, arrays, metadata, **kwargs):
            if metadata.get('transfers'):
                raise StoreError('metadata exceeds limit')       # the same failure on every attempt
            return put(key, arrays, metadata, **kwargs)
        with mock.patch.object(self.store, 'put', refusing), self.assertRaises(StoreError) as caught:
            K.Clock(ledger).advance(steps=3, transfers=(feed(0, 2),))
        head = ledger.head()
        self.assertEqual((head.accepted_steps, head.transfer_ids), (0, ()))   # the interval stands or falls whole
        self.assertIn('after global step 0 up to 2 were not committed', '\n'.join(caught.exception.__notes__))
        self.assertEqual(K.Clock(ledger).advance(steps=STEPS).status, K.HISTORY_COMPLETE)

    def test_a_retry_that_meets_its_own_published_record_adopts_it(self):
        stocked = F.root(STEPS, prepared=FIX['prepared'], stocks=F.reservoirs(), basis=F.BASIS)
        ledger, root = self.ledger(stocked, exteriors=(('inflow', 'source'),))
        put, calls = self.store.put, []

        def faulty(*args, **kwargs):
            calls.append(1)
            if len(calls) == 2:
                raise StoreError('the retry with the transfer fails at its write')
            result = put(*args, **kwargs)
            if len(calls) == 1:
                raise KeyboardInterrupt                  # published, then interrupted before the clock hears of it
            return result
        clock = K.Clock(ledger)
        with mock.patch.object(self.store, 'put', faulty), self.assertRaises(KeyboardInterrupt) as caught:
            clock.advance(steps=2, transfers=(feed(0, 1, label='due-1'),))
        head = ledger.head()
        self.assertEqual((head.accepted_steps, len(head.transfer_ids)), (1, 1))   # the published record, transfer too
        notes = '\n'.join(caught.exception.__notes__)
        self.assertIn('committed as %s' % head.key, notes)
        self.assertNotIn('not applied', notes)
        self.assertEqual(clock.advance(steps=1).accepted_steps, 1)                # adopted, not taken as overtaken

    def test_a_rival_record_of_the_same_state_with_other_transfer_content_is_refused_not_adopted(self):
        stocked = F.root(STEPS, prepared=FIX['prepared'], stocks=F.reservoirs(), basis=F.BASIS)
        ledger, root = self.ledger(stocked, exteriors=(('inflow', 'source'),))
        other = F.store(self.folder/'ledger'/'ledger.sqlite')          # a second connection to the same file
        self.addCleanup(other.close)
        rival = L.Ledger.open(other, ledger.ledger_id, source_id=F.SOURCE_ID, runtime_id=F.RUNTIME_ID)
        s1 = I.Continuation(stocked).advance(stocked, 1).state         # the same deterministic first step

        def move(kg):
            return L.Transfer(label='due-1', producer='clock-check', donor='inflow', receiver='store-b',
                              component_mass_kg={'A': kg, 'B': 0.}, enthalpy_j=0., basis=F.BASIS, start_step=0,
                              end_step=1)
        put, done = self.store.put, []

        def racing(*args, **kwargs):
            if not done:
                done.append(1)
                rival.commit(rival.root, (s1,), (move(2.),))           # same state and label, twice the mass
            return put(*args, **kwargs)
        with mock.patch.object(self.store, 'put', racing):
            outcome = K.Clock(ledger).advance(steps=1, transfers=(move(1.),))
        self.assertEqual(outcome.status, K.REFUSED_EXCHANGE)
        self.assertIn('other transfers', outcome.reason)
        self.assertEqual([c.key for c in outcome.commits], [ledger.head().key])      # the adopted rival record
        self.assertEqual(ledger.exchange(ledger.head()).inventory.component_mass_kg[1, 0], 3.)   # the rival's 2 kg

    def test_requests_reuse_the_checked_chain_while_only_this_ledger_writes(self):
        ledger, root = self.ledger()
        clock = K.Clock(ledger)
        reads, real = [], self.store.metadata

        def counted(key):
            reads.append(key)
            return real(key)
        per_request = []
        with mock.patch.object(self.store, 'metadata', side_effect=counted):
            for _ in range(8):
                before = len(reads)
                clock.advance(steps=1)
                per_request.append(len(reads)-before)
        self.assertEqual(len(set(per_request)), 1, per_request)     # flat: never a walk of the growing chain
        self.assertEqual(ledger.head().accepted_steps, 8)

    def test_unresolvable_schedules_and_malformed_controls_refuse(self):
        dense = F.root(STEPS, duration=1.6, start=2.**50-.125, prepared=FIX['prepared'])
        with self.assertRaisesRegex(L.LedgerError, 'not all distinct'):
            self.ledger(dense)                                         # refused before any history exists
        ledger, _ = self.ledger()
        clock = K.Clock(ledger)
        for request in (dict(cancel=types.SimpleNamespace(is_set=3)), dict(deadline='soon'),
                        dict(deadline=float('nan')), dict(deadline=True)):
            with self.subTest(request=repr(request)), self.assertRaises(K.ClockError):
                clock.advance(steps=1, **request)
        self.assertEqual(ledger.head().accepted_steps, 0)

    def test_cancellation_commits_accepted_steps_and_reports_the_last_time(self):
        ledger, root = self.ledger()
        clock = K.Clock(ledger)
        polls = []

        def cancel():
            polls.append(1)
            return len(polls) > 3
        outcome = clock.advance(steps=10, savepoint_steps=8, cancel=cancel)
        self.assertEqual((outcome.status, outcome.accepted_steps, outcome.step), (K.CANCELLED, 3, 3))
        self.assertEqual(outcome.time_s, clock.time_at(3))
        self.assertEqual(ledger.head().accepted_steps, 3)                 # usable accepted progress kept
        rest = clock.advance(steps=STEPS-3)
        self.assertEqual(rest.status, K.HISTORY_COMPLETE)
        self.assertEqual(ledger.state(ledger.head()).column.column_state_id, FIX['whole'].column.column_state_id)

    def test_retained_refusals_and_expired_budgets_keep_the_accepted_prefix(self):
        narrow = F.root(STEPS, prepared=FIX['prepared'], stretch_window=[.9, 1.05])
        ledger, root = self.ledger(narrow)
        clock = K.Clock(ledger)
        refused = clock.advance(steps=STEPS, savepoint_steps=4)
        self.assertEqual(refused.status, 'REFUSED_STRETCH_WINDOW')
        self.assertTrue(0 < refused.step < STEPS)
        self.assertEqual((ledger.head().accepted_steps, refused.time_s), (refused.step, clock.time_at(refused.step)))
        self.assertEqual(ledger.head().key, refused.commits[-1].key)
        self.assertTrue(1.05 >= ledger.state(ledger.head()).column.stretch)
        again = clock.advance(steps=1)                                    # the refusal is not reset by retrying
        self.assertEqual((again.status, again.accepted_steps, again.step), ('REFUSED_STRETCH_WINDOW', 0, refused.step))
        other, _ = self.ledger()
        expired = K.Clock(other).advance(steps=4, deadline=time.perf_counter()-1.)
        self.assertEqual((expired.status, expired.accepted_steps, expired.step), ('REFUSED_DEADLINE', 0, 0))

    def test_a_competing_writer_makes_the_clock_stale(self):
        ledger, root = self.ledger()
        first, second = K.Clock(ledger), K.Clock(ledger)
        first.advance(steps=2)
        stale = second.advance(steps=3)
        self.assertEqual((stale.status, stale.accepted_steps, stale.step), (K.REFUSED_STALE_PARENT, 0, 2))
        with self.assertRaisesRegex(K.ClockError, 'overtaken'):
            second.advance(steps=1)
        # Overtaken mid-request: the rival commits between two of this clock's steps; nothing of ours is published.
        other_store = F.store(self.folder/'ledger'/'ledger.sqlite')
        self.addCleanup(other_store.close)
        rival_ledger, _ = L.Ledger.create(other_store, FIX['root'])
        mine = K.Clock(ledger)
        rival = K.Clock(ledger)
        polls = []

        def interleave():
            polls.append(1)
            if len(polls) == 2:
                rival.advance(steps=1)
            return False
        raced = mine.advance(steps=4, cancel=interleave)
        self.assertEqual((raced.status, raced.accepted_steps), (K.REFUSED_STALE_PARENT, 0))
        self.assertEqual(raced.head.key, rival.head.key)
        self.assertEqual(rival_ledger.head().key, rival.head.key)
        self.assertEqual(rival.head.accepted_steps, 3)

    def test_attached_stocks_are_dated_with_every_commit(self):
        stocked = F.root(STEPS, prepared=FIX['prepared'], stocks=F.reservoirs(), basis=F.BASIS)
        ledger, root = self.ledger(stocked, exteriors=(('inflow', 'source'),))
        outcome = K.Clock(ledger).advance(steps=4, savepoint_steps=2)
        for commit in outcome.commits:
            exchange = ledger.exchange(commit)
            self.assertEqual(exchange.inventory.time_s, commit.time_s)
            np.testing.assert_array_equal(exchange.inventory.component_mass_kg, [[5., 2.], [1., .5]])
            closure = exchange.closure()
            self.assertEqual((closure['component_residual_kg'], closure['enthalpy_residual_j'],
                              closure['identity_exact']), ([0., 0.], 0., True))


class CommitRetryTests(Limited):
    """Correction round A1: the savepoint commit and the commit after an early stop share one retry. A failure the
    retry recovers from changes nothing, the stop decides the status, and an exception that still propagates says
    whether the steps were committed; a record an interrupted attempt published is adopted by the same clock."""

    def failing(self, fails, *, publish=False, error=None):
        """The first ``fails`` puts raise ``error`` (a StoreError by default), after writing when ``publish``."""
        put, calls = self.store.put, []

        def faulty(*args, **kwargs):
            calls.append(1)
            if len(calls) > fails:
                return put(*args, **kwargs)
            if publish:
                put(*args, **kwargs)
            raise error if error is not None else StoreError('storage transaction failed; no snapshot published')
        return mock.patch.object(self.store, 'put', faulty)

    def test_a_savepoint_commit_the_retry_recovers_changes_nothing(self):
        ledger, _ = self.ledger()
        with self.failing(1):
            outcome = K.Clock(ledger).advance(steps=4, savepoint_steps=2)
        self.assertEqual((outcome.status, [c.accepted_steps for c in outcome.commits]), (K.COMPLETED, [2, 4]))
        self.assertEqual(ledger.head().key, outcome.head.key)

    def test_a_cancelled_request_commits_through_a_transient_failure_and_stays_cancelled(self):
        ledger, _ = self.ledger()
        clock = K.Clock(ledger)
        with self.failing(1):
            outcome = clock.advance(steps=10, savepoint_steps=8, cancel=cancelled_after(3))
        self.assertEqual((outcome.status, outcome.accepted_steps, outcome.step), (K.CANCELLED, 3, 3))
        self.assertEqual([c.accepted_steps for c in outcome.commits], [3])
        self.assertEqual(ledger.head().key, outcome.head.key)
        self.assertEqual(clock.advance(steps=1).accepted_steps, 1)

    def test_a_retained_refusal_commits_through_a_transient_failure_and_keeps_its_status(self):
        narrow = F.root(STEPS, prepared=FIX['prepared'], stretch_window=[.9, 1.05])
        ledger, _ = self.ledger(narrow)
        with self.failing(1):
            refused = K.Clock(ledger).advance(steps=STEPS)
        self.assertEqual(refused.status, 'REFUSED_STRETCH_WINDOW')
        self.assertTrue(0 < refused.step < STEPS)
        self.assertEqual((ledger.head().accepted_steps, refused.accepted_steps), (refused.step, refused.step))
        self.assertEqual([c.accepted_steps for c in refused.commits], [refused.step])

    def test_a_commit_published_then_interrupted_after_a_cancel_is_adopted_by_the_same_clock(self):
        ledger, _ = self.ledger()
        clock = K.Clock(ledger)
        with self.failing(1, publish=True, error=KeyboardInterrupt()), self.assertRaises(KeyboardInterrupt) as caught:
            clock.advance(steps=10, savepoint_steps=8, cancel=cancelled_after(3))
        head = ledger.head()
        self.assertEqual((head.accepted_steps, clock.head.key), (3, head.key))
        self.assertIn('committed as %s' % head.key, '\n'.join(caught.exception.__notes__))
        rest = clock.advance(steps=STEPS-3)                          # its own record: not taken as overtaken
        self.assertEqual(rest.status, K.HISTORY_COMPLETE)
        self.assertEqual(ledger.state(ledger.head()).column.column_state_id, FIX['whole'].column.column_state_id)

    def test_a_commit_failing_twice_propagates_with_a_note_at_either_site(self):
        ledger, _ = self.ledger()
        for last, request in ((2, dict(steps=4, savepoint_steps=2)),
                              (3, dict(steps=10, savepoint_steps=8, cancel=cancelled_after(3)))):
            with self.subTest(last=last), self.failing(2), self.assertRaises(StoreError) as caught:
                K.Clock(ledger).advance(**request)
            self.assertIn('after global step 0 up to %d were not committed' % last,
                          '\n'.join(getattr(caught.exception, '__notes__', ())))
            self.assertEqual(ledger.head().accepted_steps, 0)
        self.assertEqual(K.Clock(ledger).advance(steps=1).accepted_steps, 1)

    def test_an_early_stop_overtaken_at_its_commit_keeps_its_stop_reason(self):
        ledger, _ = self.ledger()
        mine, rival = K.Clock(ledger), K.Clock(ledger)
        polls = []

        def cancel():
            polls.append(1)
            if len(polls) == 3:
                rival.advance(steps=1)
                return True
            return False
        outcome = mine.advance(steps=10, cancel=cancel)
        self.assertEqual((outcome.status, outcome.accepted_steps, outcome.head.key),
                         (K.REFUSED_STALE_PARENT, 0, rival.head.key))
        self.assertIn('cancelled between whole steps', outcome.reason)


class AdoptionTests(Limited):
    """Verification round r9: what a failed commit left is read from the accepted chain after the clock's own head, a
    commit whose outcome could not be read is settled by the next request, only a refused proposal is a refused
    exchange, and every propagating exception says what the request committed."""

    def stocked(self):
        state = F.root(STEPS, prepared=FIX['prepared'], stocks=F.reservoirs(), basis=F.BASIS)
        ledger, _ = self.ledger(state, exteriors=(('inflow', 'source'),))
        return state, ledger

    def rival(self, ledger):
        other = F.store(self.folder/'ledger'/'ledger.sqlite')          # a second connection to the same file
        self.addCleanup(other.close)
        return L.Ledger.open(other, ledger.ledger_id, source_id=F.SOURCE_ID, runtime_id=F.RUNTIME_ID)

    def test_a_record_continued_by_another_writer_before_the_retry_is_reported_as_committed(self):
        ledger, _ = self.ledger()
        rival, clock = self.rival(ledger), K.Clock(ledger)
        put, calls = self.store.put, []

        def faulty(*args, **kwargs):
            calls.append(1)
            if len(calls) == 1:
                put(*args, **kwargs)                    # step 1 is published ...
                raise KeyboardInterrupt                 # ... and the clock is interrupted before it hears of it
            head = rival.head()                         # another writer then continues from that record
            state = rival.state(head)
            rival.commit(head, (I.Continuation(state).advance(state, 1).state,))
            raise StoreError('the retry fails at its write')
        with mock.patch.object(self.store, 'put', faulty), self.assertRaises(KeyboardInterrupt) as caught:
            clock.advance(steps=1)
        chain = ledger.chain()
        self.assertEqual([c.accepted_steps for c in chain], [0, 1, 2])
        notes = '\n'.join(caught.exception.__notes__)
        self.assertIn('committed as %s' % chain[1].key, notes)
        self.assertIn('another writer has since continued the history', notes)
        self.assertNotIn('not committed', notes)
        with self.assertRaisesRegex(K.ClockError, 'overtaken'):
            clock.advance(steps=1)

    def test_a_commit_whose_outcome_could_not_be_read_is_settled_by_the_next_request(self):
        ledger, _ = self.ledger()
        clock = K.Clock(ledger)
        put, calls, chain, broken = self.store.put, [], L.Ledger.chain, []

        def faulty(*args, **kwargs):
            calls.append(1)
            if len(calls) == 1:
                put(*args, **kwargs)
                raise KeyboardInterrupt                 # published, then interrupted
            broken.append(1)                            # the retry fails, and so does the next read of the chain
            raise StoreError('the retry fails at its write')

        def unreadable(self_):
            if broken:
                broken.clear()
                raise StoreError('the chain could not be read')
            return chain(self_)
        with mock.patch.object(self.store, 'put', faulty), mock.patch.object(L.Ledger, 'chain', unreadable), \
                self.assertRaises(KeyboardInterrupt) as caught:
            clock.advance(steps=10, savepoint_steps=8, cancel=cancelled_after(3))
        self.assertIn('could not be read', '\n'.join(caught.exception.__notes__))
        self.assertEqual(ledger.head().accepted_steps, 3)           # it had been published
        rest = clock.advance(steps=STEPS-3)                          # settled: the clock adopts its own record
        self.assertEqual(rest.status, K.HISTORY_COMPLETE)
        self.assertEqual(ledger.state(ledger.head()).column.column_state_id, FIX['whole'].column.column_state_id)

    def test_an_early_stop_meeting_a_rival_record_with_other_transfers_keeps_its_status_and_says_so(self):
        stocked, ledger = self.stocked()
        rival, run = self.rival(ledger), I.Continuation(stocked)
        s1 = run.advance(stocked, 1).state
        s2 = run.advance(s1, 1).state
        put, done = self.store.put, []

        def racing(*args, **kwargs):
            if not done:
                done.append(1)
                rival.commit(rival.root, (s1, s2), (feed(0, 2),))    # the same two steps, with a transfer
            return put(*args, **kwargs)
        with mock.patch.object(self.store, 'put', racing):
            outcome = K.Clock(ledger).advance(steps=6, cancel=cancelled_after(2))
        self.assertEqual((outcome.status, outcome.accepted_steps), (K.CANCELLED, 2))
        self.assertIn('cancelled between whole steps', outcome.reason)
        self.assertIn('carries other transfers', outcome.reason)
        self.assertEqual([c.key for c in outcome.commits], [ledger.head().key])

    def test_a_failure_of_the_ledger_itself_is_not_reported_as_a_refused_exchange(self):
        _, ledger = self.stocked()
        clock = K.Clock(ledger)

        def damaged(exchange):
            raise L.LedgerError('exchange accounts changed after they were accepted')
        with mock.patch.object(L, '_intact', damaged), self.assertRaises(L.LedgerError) as caught:
            clock.advance(steps=2, transfers=(feed(0, 2),))
        self.assertNotIsInstance(caught.exception, L.ExchangeRefused)
        self.assertIn('after global step 0 up to 2 were not committed', '\n'.join(caught.exception.__notes__))
        self.assertEqual(ledger.head().accepted_steps, 0)

    def test_settling_an_unread_outcome_refuses_another_writers_record_with_other_transfers(self):
        stocked, ledger = self.stocked()
        rival, clock = self.rival(ledger), K.Clock(ledger)
        s1 = I.Continuation(stocked).advance(stocked, 1).state
        put, calls, chain, broken = self.store.put, [], L.Ledger.chain, []

        def faulty(*args, **kwargs):
            calls.append(1)
            if len(calls) == 1:                         # another writer commits the same step with another transfer
                rival.commit(rival.root, (s1,), (feed(0, 1, label='rival', component_mass_kg={'A': 2., 'B': 0.}),))
            else:
                broken.append(1)                        # the retry fails, and so does the next read of the chain
            raise StoreError('storage transaction failed; no snapshot published')

        def unreadable(self_):
            if broken:
                broken.clear()
                raise StoreError('the chain could not be read')
            return chain(self_)
        with mock.patch.object(self.store, 'put', faulty), mock.patch.object(L.Ledger, 'chain', unreadable), \
                self.assertRaises(StoreError) as caught:
            clock.advance(steps=1, transfers=(feed(0, 1, label='mine'),))
        self.assertIn('could not be read', '\n'.join(caught.exception.__notes__))
        with self.assertRaisesRegex(K.ClockError, 'another writer with other transfers'):
            clock.advance(steps=1)
        with self.assertRaisesRegex(K.ClockError, 'overtaken'):
            clock.check(steps=1)

    def test_every_refusal_caused_by_a_proposal_is_a_refused_exchange(self):
        _, ledger = self.stocked()
        emptied = feed(0, 1, label='empties', donor='store-b', receiver='store-a',
                       component_mass_kg={'A': 1., 'B': .5}, enthalpy_j=0.)          # leaves store-b its 4 J
        huge = tuple(feed(0, 1, label='big-%d' % i, component_mass_kg={'A': 2.**959, 'B': 0.}, enthalpy_j=0.)
                     for i in (1, 2))                                                  # together out of range
        for name, moves, message in (('emptied stock keeps enthalpy', (emptied,), 'empty stock'),
                                     ('stock out of range', huge, 'finite accounting range')):
            with self.subTest(name):
                outcome = K.Clock(ledger).advance(steps=1, transfers=moves)
                self.assertEqual((outcome.status, outcome.accepted_steps), (K.REFUSED_EXCHANGE, 0))
                self.assertIn(message, outcome.reason)
        self.assertEqual(ledger.head().accepted_steps, 0)

    def test_an_adopted_rival_record_that_was_then_overtaken_keeps_its_refusal(self):
        stocked, ledger = self.stocked()
        rival, run = self.rival(ledger), I.Continuation(stocked)
        s1 = run.advance(stocked, 1).state
        s2 = run.advance(s1, 1).state
        put, done = self.store.put, []

        def racing(*args, **kwargs):
            if not done:
                done.append(1)
                first = rival.commit(rival.root, (s1, s2), (feed(0, 2),))   # the same steps with a transfer ...
                state = rival.state(first)
                rival.commit(first, (I.Continuation(state).advance(state, 1).state,))      # ... then continued
            return put(*args, **kwargs)
        with mock.patch.object(self.store, 'put', racing):
            outcome = K.Clock(ledger).advance(steps=4, savepoint_steps=2)
        self.assertEqual((outcome.status, outcome.accepted_steps), (K.REFUSED_STALE_PARENT, 2))
        self.assertIn('carries other transfers', outcome.reason)
        self.assertIn('another candidate was accepted after this parent', outcome.reason)

    def test_an_unsupported_event_stop_keeps_its_status_when_a_rival_record_is_adopted_there(self):
        stocked = F.root(STEPS, prepared=FIX['prepared'], stocks=F.reservoirs(), basis=F.BASIS)
        at = lambda k: advance_time(stocked.start_time_s, k*stocked.settings.step_s)
        eruption = K.Event((at(2)+at(3))/2, 'eruption', 'declared-eruption')
        ledger, _ = self.ledger(stocked, exteriors=(('inflow', 'source'),), calendar=(eruption,))
        rival, run = self.rival(ledger), I.Continuation(stocked)
        s1 = run.advance(stocked, 1).state
        s2 = run.advance(s1, 1).state
        put, done = self.store.put, []

        def racing(*args, **kwargs):
            if not done:
                done.append(1)
                rival.commit(rival.root, (s1, s2), (feed(0, 2),))     # the same steps up to the event, with a transfer
            return put(*args, **kwargs)
        clock = K.Clock(ledger)
        with mock.patch.object(self.store, 'put', racing):
            outcome = clock.advance(steps=6)
        self.assertEqual((outcome.status, outcome.accepted_steps, outcome.event), (K.REFUSED_UNSUPPORTED_EVENT, 2,
                                                                                   eruption))
        self.assertIn('not supported', outcome.reason)
        self.assertIn('carries other transfers', outcome.reason)
        self.assertEqual([c.key for c in outcome.commits], [ledger.head().key])      # the adopted rival record
        self.assertEqual(len(ledger.head().transfer_ids), 1)                         # with the rival's transfer
        later = clock.advance(steps=6)                                               # the clock is not stale
        self.assertEqual((later.status, later.accepted_steps, later.event), (K.REFUSED_UNSUPPORTED_EVENT, 0, eruption))

    def test_an_exchange_refused_at_an_unsupported_event_stop_is_a_refused_exchange(self):
        stocked = F.root(STEPS, prepared=FIX['prepared'], stocks=F.reservoirs(), basis=F.BASIS)
        at = lambda k: advance_time(stocked.start_time_s, k*stocked.settings.step_s)
        eruption = K.Event((at(2)+at(3))/2, 'eruption', 'declared-eruption')
        ledger, _ = self.ledger(stocked, exteriors=(('inflow', 'source'),), calendar=(eruption,))
        huge = tuple(feed(1, 2, label='big-%d' % i, component_mass_kg={'A': 2.**959, 'B': 0.}, enthalpy_j=0.)
                     for i in (1, 2))                                   # together beyond the finite accounting range
        outcome = K.Clock(ledger).advance(steps=6, transfers=huge)
        self.assertEqual((outcome.status, outcome.accepted_steps, outcome.event), (K.REFUSED_EXCHANGE, 1, None))
        self.assertEqual((ledger.head().accepted_steps, len(ledger.head().transfer_ids)), (1, 0))   # interval start

    def test_an_interrupt_with_nothing_pending_says_what_the_request_committed(self):
        ledger, _ = self.ledger()
        polls = []

        def interrupted():
            polls.append(1)
            if len(polls) == 3:
                raise KeyboardInterrupt                 # just after the savepoint at step 2: nothing is pending
            return False
        with self.assertRaises(KeyboardInterrupt) as caught:
            K.Clock(ledger).advance(steps=6, savepoint_steps=2, cancel=interrupted)
        head = ledger.head()
        self.assertEqual(head.accepted_steps, 2)
        self.assertIn('committed as %s' % head.key, '\n'.join(caught.exception.__notes__))


class TransferIntervalTests(Limited):
    """Correction round A2: a transfer declares the interval of whole steps it was produced for. The clock makes both
    ends savepoints, commits the interval in one commit with it, and refuses an interval it cannot commit whole; the
    interval's steps are committed together with its exchange or not at all."""

    def setUp(self):
        super().setUp()
        self.stocked = F.root(STEPS, prepared=FIX['prepared'], stocks=F.reservoirs(), basis=F.BASIS)
        self.book, _ = self.ledger(self.stocked, exteriors=(('inflow', 'source'),))

    def at(self, step):
        return advance_time(self.stocked.start_time_s, step*self.stocked.settings.step_s)

    def test_interval_ends_become_savepoints_and_the_parent_is_the_commit_at_its_start(self):
        outcome = K.Clock(self.book).advance(steps=6, savepoint_steps=2, transfers=(feed(2, 5),))
        self.assertEqual([c.accepted_steps for c in outcome.commits], [2, 5, 6])      # 4 lies inside (2, 5]
        parent, carrying = outcome.commits[:2]
        record = carrying.metadata()['transfers'][0]
        self.assertEqual((record['parent_key'], record['interval']['start_step'], record['interval']['end_step']),
                         (parent.key, 2, 5))
        self.assertEqual((carrying.interval[2:], len(carrying.transfer_ids)), ((2, 5), 1))
        np.testing.assert_array_equal(self.book.exchange(carrying).inventory.component_mass_kg,
                                      [[5., 2.], [1.5, .75]])

    def test_a_refused_exchange_commits_none_of_its_interval(self):
        clock = K.Clock(self.book)
        greedy = feed(1, 3, label='greedy', donor='store-b', receiver='store-a',
                      component_mass_kg={'A': 99., 'B': 0.}, enthalpy_j=0.)
        outcome = clock.advance(steps=4, transfers=(greedy,))
        self.assertEqual((outcome.status, outcome.accepted_steps, outcome.step), (K.REFUSED_EXCHANGE, 1, 1))
        self.assertEqual([c.accepted_steps for c in outcome.commits], [1])
        self.assertIn('interval (1, 3] was refused, so its steps were not committed', outcome.reason)
        self.assertIn('finite availability', outcome.reason)
        self.assertEqual((self.book.head().accepted_steps, self.book.head().transfer_ids), (1, ()))
        again = clock.advance(steps=3)                              # the history continues from the interval's start
        self.assertEqual((again.status, again.step), (K.COMPLETED, 4))

    def test_a_stop_inside_an_interval_leaves_the_head_at_its_start(self):
        outcome = K.Clock(self.book).advance(steps=6, transfers=(feed(1, 4),), cancel=cancelled_after(3))
        self.assertEqual((outcome.status, outcome.accepted_steps, outcome.step), (K.CANCELLED, 1, 1))
        self.assertIn('after global step 1 lie inside the interval (1, 4]', outcome.reason)
        self.assertEqual([c.accepted_steps for c in outcome.commits], [1])
        polls = []

        def interrupted():
            polls.append(1)
            if len(polls) == 3:
                raise KeyboardInterrupt
            return False
        with self.assertRaises(KeyboardInterrupt) as caught:
            K.Clock(self.book).advance(steps=4, transfers=(feed(1, 4),), cancel=interrupted)
        self.assertIn('lie inside the interval (1, 4]', '\n'.join(caught.exception.__notes__))
        self.assertEqual((self.book.head().accepted_steps, self.book.head().transfer_ids), (1, ()))

    def test_intervals_the_clock_cannot_commit_whole_are_refused_before_work(self):
        calendar = ((self.at(3), K.SAVEPOINT, 'declared'), ((self.at(8)+self.at(9))/2, 'rift-onset', 'rift'))
        ledger, _ = self.ledger(self.stocked, exteriors=(('inflow', 'source'),), calendar=calendar)
        clock = K.Clock(ledger)
        clock.advance(steps=1)
        refused = {
            'starts before the accepted head': (dict(steps=3), (feed(0, 2),)),
            'ends after this request': (dict(steps=3), (feed(1, 5),)),
            'overlap': (dict(steps=6), (feed(4, 6), feed(5, 7, label='other'))),
            'savepoint splits the interval': (dict(steps=6), (feed(2, 4),)),                  # the ledger's step 3
            'savepoint splits the interval ': (dict(steps=6, events=(K.Event(self.at(5), K.SAVEPOINT, 'mine'),)),
                                               (feed(4, 6),)),                              # the request's step 5
            'before the end of the': (dict(steps=10), (feed(7, 10),)),                     # the rift after step 8
            'sequence of Transfer proposals': (dict(steps=3), {3: (feed(1, 3),)}),
        }
        for message, (request, transfers) in refused.items():
            with self.subTest(message.strip()), self.assertRaisesRegex(K.ClockError, message.strip()):
                clock.advance(transfers=transfers, **request)
        self.assertEqual(ledger.head().accepted_steps, 1)
        outcome = clock.advance(steps=5, transfers=(feed(1, 3), feed(3, 6, label='other')))    # adjacent: accepted
        self.assertEqual([c.accepted_steps for c in outcome.commits], [3, 6])


if __name__ == '__main__':
    unittest.main()
