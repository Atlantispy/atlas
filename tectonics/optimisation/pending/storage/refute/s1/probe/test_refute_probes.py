"""S1 refuter probes: behaviour parity of completed_queries with/without the observer, and edge cases."""
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


def scenario(name, stages):
    """One owner-test scenario; returns everything observable to the run."""
    record, events = {}, []
    if stages is not None:
        record['stage'] = 'x'
    observer = F.QueryStages(record) if stages else None

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
    return dict(cq=record.get('completed_queries'), events=events, caught=caught,
                owner_events=getattr(owner, 'events', None)), record


class ParityProbes(unittest.TestCase):
    def test_observer_changes_nothing_the_run_sees(self):
        for name in ('ok', 'serial', 'flush-fails-during-failure', 'flush-fails-on-success', 'body-keyboard-interrupt'):
            with self.subTest(name):
                without, _ = scenario(name, None)
                withit, record = scenario(name, True)
                self.assertEqual(without, withit)
                rows = record['completed_queries_by_stage']['rows']
                self.assertEqual(record['completed_queries_by_stage'].get('status'), None)  # finish() not called here
                self.assertEqual(rows, [])  # current row not yet published

    def test_rows_sum_after_failure_in_body(self):
        run = TS.Run()
        run.phase('a')
        with self.assertRaises(ValueError):
            with run.queries() as owner:
                owner.hits, owner.held = 2, 3
                run.phase('b')
                owner.misses = 4
                raise ValueError('boom')
        run.stages.finish()
        stage = run.record['completed_queries_by_stage']
        totals = run.record['completed_queries']
        for name in F.QUERY_STAGE_FIELDS:
            self.assertEqual(sum(row[name] or 0 for row in stage['rows']), totals[name], name)
        self.assertEqual(stage['status'], 'COMPLETE')
        json.dumps(run.record, indent=2, sort_keys=True, allow_nan=False)

    def test_two_owners_sum_exceeds_last_record(self):
        run = TS.Run()
        run.phase('a')
        with run.queries() as first:
            first.hits = 5
        with run.queries() as second:
            second.hits = 1
        run.stages.finish()
        rows = run.record['completed_queries_by_stage']['rows']
        self.assertEqual(sum(row['hits'] or 0 for row in rows), 6)
        self.assertEqual(run.record['completed_queries']['hits'], 1)  # documented? only the last owner

    def test_stage_change_not_saved_before_finish(self):
        """guard.phase sets record['stage'] then _sync(); if _sync raises, save() is skipped."""
        run = TS.Run()
        run.phase('a')
        run.record['stage'] = 'b'  # set without save
        run.stages.finish()
        run.save()  # the final save after finish
        rows = run.record['completed_queries_by_stage']['rows']
        self.assertNotIn(None, rows, rows)

    def test_no_phase_ever(self):
        record = {}
        stages = F.QueryStages(record)
        stages.observe()
        stages.finish()
        self.assertEqual(record['completed_queries_by_stage']['status'], 'COMPLETE')
        self.assertEqual(len(record['completed_queries_by_stage']['rows']), 1)


if __name__ == '__main__':
    unittest.main()
