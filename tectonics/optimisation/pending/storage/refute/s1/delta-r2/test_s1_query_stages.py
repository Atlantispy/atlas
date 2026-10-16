"""S1: completed-query counters per guard stage (WP17 instrumentation; observation only)."""
import ast
import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE)]

import test_run_fresh_interval as TR  # the relocated owner test: F from this folder, owner tree read-only

F = TR.F


class Run:
    """A guard stand-in that, like ContinuationGuard.phase, sets record['stage'] and then calls save()."""

    def __init__(self):
        self.record, self.saves = {'phases': []}, 0
        self.stages = F.QueryStages(self.record)

    def save(self):
        self.stages.observe()
        self.saves += 1

    def phase(self, name):
        self.record['phases'].append(dict(name=name))
        self.record['stage'] = name
        self.save()

    def queries(self, owner_type=TR.FakeOwner, declared='columnar'):
        return F.completed_queries(owner_type, Path('queries'), declared=declared,
            arguments=F.query_store_arguments(owner_type, declared), execution='execution', budget='budget',
            cancel='cancel', limits={'max_store_bytes': 7, 'max_entries': 5}, record=self.record, save=self.save,
            query_stages=self.stages)

    def rows(self):
        return [(row['stage'], row['opens'], row['hits'], row['misses'], row['written'], row['incomplete'],
                 row['unflushed']) for row in self.record['completed_queries_by_stage']['rows']]


class QueryStageTests(unittest.TestCase):
    def test_rows_follow_stage_changes_with_exact_deltas_and_nulls_outside_the_owner(self):
        run = Run()
        run.phase('admission')
        with run.queries() as owner:
            owner.hits, owner.misses = 2, 1
            run.phase('prepare')
            owner.hits, owner.held, owner.incomplete = 3, 4, 1
            run.phase('advance')
            owner.written = 2
        run.phase('seal')
        run.stages.finish()
        self.assertEqual(run.rows(), [
            (None, 0, None, None, None, None, None),
            ('admission', 1, 2, 1, 0, 0, 0),
            ('prepare', 0, 1, 0, 0, 1, 4),
            # The exit flush commits the 4 held entries in this stage (written 2 -> 6).
            ('advance', 0, 0, 0, 6, 0, 0),
            ('seal', 0, None, None, None, None, None)])
        stage = run.record['completed_queries_by_stage']
        self.assertEqual(stage['status'], 'COMPLETE')
        self.assertEqual(stage['opened_with'], [dict(stage='admission', hits=0, misses=0, written=0, incomplete=0)])
        totals = run.record['completed_queries']
        for name in F.QUERY_STAGE_FIELDS:
            self.assertEqual(sum(row[name] or 0 for row in stage['rows']), totals[name], name)
        json.dumps(run.record)  # run.json stays plain JSON

    def test_guard_phases_and_stage_are_untouched(self):
        run = Run()
        for name in ('a', 'b', 'c'):
            run.phase(name)
        with run.queries():
            run.phase('d')
        self.assertEqual([row['name'] for row in run.record['phases']], ['a', 'b', 'c', 'd'])
        self.assertEqual(run.record['stage'], 'd')

    def test_reopens_are_counted_in_their_stage(self):
        run = Run()
        run.phase('one')
        with run.queries() as first:
            first.hits = 5
        with run.queries() as second:
            second.hits = 1
            run.phase('two')
            second.misses = 2
        with run.queries():
            pass
        run.stages.finish()
        self.assertEqual(run.rows()[1:], [('one', 2, 6, 0, 0, 0, 0), ('two', 1, 0, 2, 0, 0, 0)])
        self.assertEqual([row['stage'] for row in run.record['completed_queries_by_stage']['opened_with']],
                         ['one', 'one', 'two'])

    def test_serial_owner_without_unflushed_reads_zero(self):
        run = Run()
        run.phase('s')
        with run.queries(owner_type=TR.SerialOwner, declared='files') as owner:
            owner.written = 3
        run.stages.finish()
        self.assertEqual(run.rows()[1], ('s', 1, 0, 0, 3, 0, 0))

    def test_flush_failure_still_closes_the_row(self):
        run = Run()
        run.phase('s')
        with self.assertRaises(RuntimeError):
            with run.queries() as owner:
                owner.hits, owner.held = 1, 2
                owner.flush_error = RuntimeError('flush')
        run.stages.finish()
        self.assertEqual(run.rows()[1], ('s', 1, 1, 0, 0, 0, 2))
        self.assertEqual(run.record['completed_queries']['hits'], 1)

    def test_an_observation_failure_is_recorded_and_never_raised(self):
        run = Run()
        run.phase('s')
        run.stages.opened(TR.FakeOwner('x', context=None, budget=None))  # an owner that never closes
        with run.queries() as owner:  # the second open refuses inside the observer only
            owner.hits = 1
        run.phase('t')
        run.stages.finish()
        stage = run.record['completed_queries_by_stage']
        self.assertEqual(stage['status'], 'INCOMPLETE')
        self.assertIn('one completed-query owner at a time', stage['error'])
        self.assertEqual(run.record['completed_queries']['hits'], 1)  # the owner's own record is unchanged

    def test_no_owner_and_no_observer_keep_the_old_record(self):
        record, events = {}, []
        with F.completed_queries(TR.FakeOwner, Path('queries'), declared='columnar',
                arguments=F.query_store_arguments(TR.FakeOwner, 'columnar'), execution='e', budget='b', cancel='c',
                limits={'max_store_bytes': 7, 'max_entries': 5}, record=record,
                save=lambda: events.append('save')) as owner:
            owner.hits = 2
        self.assertEqual(set(record), {'completed_queries'})
        self.assertEqual(events, ['save'])

    # r2: the refuter's P3 gaps (mutant names from T/so/refute/s1/refute-r1.log).
    def test_finish_closes_a_stage_whose_save_was_skipped_and_then_stops(self):
        # guard.phase sets record['stage'] then _sync(); if _sync raises, its save() is skipped (refuter probe).
        run = Run()
        run.phase('a')
        run.record['stage'] = 'b'
        run.stages.finish()
        closed = [(None, 0, None, None, None, None, None), ('a', 0, None, None, None, None, None),
                  ('b', 0, None, None, None, None, None)]
        self.assertEqual(run.rows(), closed)
        run.save()  # the runner's final save, after finish(): adds nothing
        run.phase('late')  # nor does any later stage change
        self.assertEqual(run.rows(), closed)
        self.assertEqual(run.record['completed_queries_by_stage']['status'], 'COMPLETE')

    def test_finish_counts_an_owner_still_open(self):  # m11
        run = Run()
        run.phase('s')
        owner = TR.FakeOwner('x', context=None, budget=None)
        run.stages.opened(owner)
        owner.hits, owner.held = 3, 1
        run.stages.finish()
        self.assertEqual(run.rows()[1], ('s', 1, 3, 0, 0, 0, 1))
        self.assertEqual(run.record['completed_queries_by_stage']['status'], 'COMPLETE')

    def test_an_open_observes_a_stage_change_first(self):  # m13
        run = Run()
        run.phase('a')
        run.record['stage'] = 'b'  # this stage's save() was skipped
        with run.queries() as owner:
            owner.hits = 1
        run.stages.finish()
        self.assertEqual(run.rows()[1:], [('a', 0, None, None, None, None, None), ('b', 1, 1, 0, 0, 0, 0)])
        self.assertEqual([row['stage'] for row in run.record['completed_queries_by_stage']['opened_with']], ['b'])

    def test_a_record_without_a_stage_stays_complete(self):  # m17
        record = {}
        stages = F.QueryStages(record)
        stages.observe()
        stages.finish()
        value = record['completed_queries_by_stage']
        self.assertEqual((value['status'], len(value['rows'])), ('COMPLETE', 1))
        self.assertNotIn('error', value)

    def test_a_refused_store_counts_no_open(self):  # m18
        class Columnar(TR.FakeOwner):
            def __init__(self, *args, storage='files', **kwargs):
                super().__init__(*args, storage='columnar', **kwargs)
        run = Run()
        run.phase('s')
        with self.assertRaisesRegex(F.FreshRefused, 'differs from the declared store'), \
                run.queries(owner_type=Columnar, declared='files'):
            pass
        with run.queries() as owner:  # the next open is counted normally
            owner.hits = 1
        run.stages.finish()
        stage = run.record['completed_queries_by_stage']
        self.assertEqual(stage['status'], 'COMPLETE')
        self.assertEqual(run.rows()[1], ('s', 1, 1, 0, 0, 0, 0))
        self.assertEqual(len(stage['opened_with']), 1)

    def test_a_base_exception_is_never_caught(self):  # m10
        class Interrupting(TR.FakeOwner):
            @property
            def hits(self):
                raise KeyboardInterrupt

            @hits.setter
            def hits(self, value):
                pass
        run = Run()
        run.phase('s')
        with self.assertRaises(KeyboardInterrupt):
            run.stages.opened(Interrupting('x', context=None, budget=None))
        self.assertNotIn('status', run.record['completed_queries_by_stage'])


class WiringTests(unittest.TestCase):
    tree = ast.parse(Path(F.__file__).read_text(encoding='utf8'))

    def function(self, name, within=None):
        scope = self.tree if within is None else self.function(within)
        return next(n for n in ast.walk(scope) if isinstance(n, ast.FunctionDef) and n.name == name)

    def keyword_calls(self, function, callee):
        return [node for node in ast.walk(function) if isinstance(node, ast.Call) and
                (getattr(node.func, 'id', None) == callee or getattr(node.func, 'attr', None) == callee)]

    def test_the_observer_reaches_the_query_owner(self):
        for scope, callee in (('_workload', 'run_fresh_interval'), ('run_fresh_interval', '_advance'),
                              ('_advance', 'completed_queries')):
            calls = self.keyword_calls(self.function(scope), callee)
            self.assertEqual(len(calls), 1, scope)
            self.assertEqual([ast.unparse(k.value) for k in calls[0].keywords if k.arg == 'query_stages'],
                             ['query_stages'], scope)

    def test_save_observes_before_writing_and_finish_precedes_the_final_status(self):
        save = self.function('save', within='_workload')
        self.assertEqual([ast.unparse(node.value) for node in save.body],
                         ['query_stages.observe()', 'G._write(output, record)'])
        workload = ast.unparse(self.function('_workload'))
        self.assertLess(workload.index('query_stages.finish()'),
                        workload.index("record['status'] = final_status(record['errors'], mode, record)"))
        self.assertLess(workload.index('query_stages = QueryStages(record)'),
                        workload.index('G.ContinuationGuard(output, record, save)'))


if __name__ == '__main__':
    unittest.main()
