"""S1 r2 delta refuter probes: parity with/without the observer, failure paths, and the async windows."""
import json
import sys
import unittest
from concurrent.futures import CancelledError
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE)]

import test_run_fresh_interval as TR
import test_s1_query_stages as TS

F = TR.F
assert Path(F.__file__).resolve().parent == HERE, F.__file__


def scenario(name, observed, break_observer=False):
    """One owner-test scenario; returns everything observable to the run."""
    record, events = {}, []
    observer = F.QueryStages(record) if observed else None
    if break_observer:
        def broken(_owner):
            raise ValueError('observer read failed')
        observer._counts = broken

    def save():
        if observer is not None:
            observer.observe()
        events.append('save')
    owner_type = TR.SerialOwner if name == 'serial' else TR.FakeOwner
    declared = 'files' if name == 'serial' else 'columnar'
    caught, owner = None, None
    try:
        with F.completed_queries(owner_type, Path('queries'), declared=declared,
                                 arguments=F.query_store_arguments(owner_type, declared), execution='e', budget='b',
                                 cancel='c', limits={'max_store_bytes': 7, 'max_entries': 5}, record=record,
                                 save=save, query_stages=observer) as owner:
            record['stage'] = 'mid'  # a stage change inside the owner's life
            if name == 'serial':
                owner.written = 2
            else:
                owner.written, owner.held, owner.hits = 5, 3, 1
            if name == 'flush-fails-during-failure':
                owner.flush_error = CancelledError('guard abort')
                raise ValueError('advance failed')
            if name == 'flush-fails-on-success':
                owner.flush_error = CancelledError('late abort')
            if name == 'body-keyboard-interrupt':
                raise KeyboardInterrupt
    except BaseException as error:  # noqa: BLE001
        caught = (type(error).__name__, str(error), tuple(getattr(error, '__notes__', ())))
    if observer is not None:
        observer.finish()
    return dict(cq=record.get('completed_queries'), events=events, caught=caught,
                owner_events=getattr(owner, 'events', None)), record


NAMES = ('ok', 'serial', 'flush-fails-during-failure', 'flush-fails-on-success', 'body-keyboard-interrupt')


class DeltaProbes(unittest.TestCase):
    def test_observer_changes_nothing_the_run_sees(self):
        for name in NAMES:
            for broken in (False, True):
                with self.subTest(name=name, broken=broken):
                    without, _ = scenario(name, False)
                    withit, record = scenario(name, True, broken)
                    self.assertEqual(without, withit)
                    value = record['completed_queries_by_stage']
                    self.assertEqual(value['status'], 'INCOMPLETE' if broken else 'COMPLETE')
                    json.dumps(record, indent=2, sort_keys=True, allow_nan=False)
                    if not broken:
                        totals = record['completed_queries']
                        for field in F.QUERY_STAGE_FIELDS:
                            self.assertEqual(sum(row[field] or 0 for row in value['rows']), totals[field], field)

    def test_a_failed_read_mid_accumulate_leaves_the_row_and_stops(self):
        class Flaky(TR.FakeOwner):
            fail = False

            @property
            def unflushed(self):  # r1 read this AFTER writing the counts into the row
                if self.fail:
                    raise ValueError('late read failed')
                return self.held
        run = TS.Run()
        run.phase('a')
        owner = Flaky('x', context=None, budget=None)
        run.stages.opened(owner)
        owner.hits = 2
        before = dict(run.stages.row)
        owner.fail = True
        run.phase('b')  # _accumulate: counts read and summed, then unflushed fails before any update
        value = run.record['completed_queries_by_stage']
        self.assertEqual(value['status'], 'INCOMPLETE')
        self.assertEqual(run.stages.row, before)  # nothing half-written
        self.assertEqual([row['stage'] for row in value['rows']], [None])  # 'a' never published
        run.stages.closed(owner)
        run.stages.finish()
        run.save()
        self.assertEqual(value['status'], 'INCOMPLETE')
        self.assertEqual([row['stage'] for row in value['rows']], [None])

    def test_skipped_save_then_finish_has_no_null_row(self):
        run = TS.Run()
        run.phase('a')
        run.record['stage'] = 'b'
        run.stages.finish()
        run.save()
        rows = run.record['completed_queries_by_stage']['rows']
        self.assertNotIn(None, rows)
        self.assertEqual([row['stage'] for row in rows], [None, 'a', 'b'])

    def test_two_owners_sum_and_scope_says_so(self):
        run = TS.Run()
        run.phase('a')
        with run.queries() as first:
            first.hits = 5
        with run.queries() as second:
            second.hits = 1
        run.stages.finish()
        value = run.record['completed_queries_by_stage']
        self.assertEqual(sum(row['hits'] or 0 for row in value['rows']), 6)
        self.assertEqual(run.record['completed_queries']['hits'], 1)
        self.assertIn('last owner', value['scope'])

    def _interrupt_at(self, function, source):
        """Raise KeyboardInterrupt (as a Ctrl+C would) just before ``source`` runs in QueryStages.<function>."""
        code = getattr(F.QueryStages, function).__code__
        lines = Path(F.__file__).read_text(encoding='utf8').splitlines()

        def local(frame, event, _arg):
            if event == 'line' and lines[frame.f_lineno-1].strip() == source:
                sys.settrace(None)
                raise KeyboardInterrupt
            return local

        def tracer(frame, event, _arg):
            return local if frame.f_code is code else None
        return tracer

    def test_async_interrupt_between_append_and_stage_duplicates_a_row(self):
        """Residual r1 P3 (4): a Ctrl+C after rows.append and before self.stage = stage."""
        run = TS.Run()
        run.phase('a')
        with run.queries() as owner:
            owner.hits = 4
        sys.settrace(self._interrupt_at('_observe', 'self.stage = stage'))
        try:
            with self.assertRaises(KeyboardInterrupt):
                run.phase('b')
        finally:
            sys.settrace(None)
        run.save()  # _workload's except path saves
        run.stages.finish()
        rows = run.record['completed_queries_by_stage']['rows']
        hits = sum(row['hits'] or 0 for row in rows)
        self.assertEqual((hits, run.record['completed_queries']['hits']), (8, 4))  # the 'a' row is in twice
        self.assertIs(rows[1], rows[2])

    def test_async_interrupt_between_update_and_base_double_counts(self):
        """Residual: a Ctrl+C after row.update and before self.base = now in _accumulate."""
        run = TS.Run()
        run.phase('a')
        owner = TR.FakeOwner('x', context=None, budget=None)
        run.stages.opened(owner)
        owner.hits = 3
        sys.settrace(self._interrupt_at('_accumulate', 'self.base = now'))
        try:
            with self.assertRaises(KeyboardInterrupt):
                run.phase('b')
        finally:
            sys.settrace(None)
        run.stages.closed(owner)
        run.stages.finish()
        rows = run.record['completed_queries_by_stage']['rows']
        self.assertEqual(sum(row['hits'] or 0 for row in rows), 6)  # owner.hits is 3


if __name__ == '__main__':
    unittest.main()
