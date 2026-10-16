"""S1 r3 delta refuter probes: interrupts (KeyboardInterrupt, SystemExit, GeneratorExit) against the r3 _safely/_stop."""
import json
import linecache
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE)]

import test_run_fresh_interval as TR
import test_s1_query_stages as TS

F = TR.F
assert Path(F.__file__).resolve().parent == HERE, F.__file__
LINES = Path(F.__file__).read_text(encoding='utf8').splitlines()


def code_of(owner_class, function, nested=None):
    code = getattr(owner_class, function).__code__
    if nested is not None:
        [code] = [c for c in code.co_consts if getattr(c, 'co_name', None) == nested]
    return code


def interrupt_at(owner_class, function, source, error=KeyboardInterrupt, nested=None):
    """A tracer raising ``error`` (as a Ctrl+C at an eval-breaker check would) just before ``source`` runs."""
    code = code_of(owner_class, function, nested)

    def local(frame, event, _arg):
        if event == 'line' and linecache.getline(frame.f_code.co_filename, frame.f_lineno).strip() == source:
            sys.settrace(None)
            raise error
        return local

    def tracer(frame, event, _arg):
        return local if frame.f_code is code else None
    return tracer


def traced(tracer, call):
    sys.settrace(tracer)
    try:
        call()
    finally:
        sys.settrace(None)


def snapshot(run):
    return json.dumps(run.record['completed_queries_by_stage'], sort_keys=True)


def staged_run():
    """phase a with a closed owner (hits 4), then an open owner in phase a (hits 3 so far)."""
    run = TS.Run()
    run.phase('a')
    with run.queries() as first:
        first.hits = 4
    owner = TR.FakeOwner('x', context=None, budget=None)
    run.stages.opened(owner)
    owner.hits = 3
    return run, owner


OBSERVE_LINES = ("stage = self.record.get('stage')", 'if stage != self.stage:', 'self._accumulate()',
                 "self.value['rows'].append(self.row)", 'self.stage = stage', 'self.row = self._new_row()')
ACCUMULATE_LINES = ('if self.owner is not None:', "now, unflushed = self._counts(self.owner), getattr(self.owner, 'unflushed', 0)",
                    'sums = {name: (self.row[name] or 0)+now[name]-self.base[name] for name in QUERY_STAGE_FIELDS}',
                    'self.row.update(sums, unflushed=unflushed)', 'self.base = now')
FINISH_LINES = ('self._observe()', 'self._accumulate()', 'self.owner = self.base = None',
                "self.value['rows'].append(self.row)", 'self.row = None', "self.value['status'] = 'COMPLETE'")


class InterruptProbes(unittest.TestCase):
    def assert_stopped_and_frozen(self, run, owner, error_name='KeyboardInterrupt'):
        value = run.record['completed_queries_by_stage']
        self.assertEqual(value['status'], 'INCOMPLETE')
        self.assertTrue(value['error'].startswith(error_name), value['error'])
        before = snapshot(run)
        owner.hits += 7
        run.save()
        run.phase('later')
        run.stages.opened(TR.FakeOwner('y', context=None, budget=None))
        run.stages.closed(owner)
        run.stages.finish()
        run.save()
        self.assertEqual(snapshot(run), before)  # nothing after _stop mutates the rows

    def test_every_line_of_a_stage_change_interrupt_is_marked_and_frozen(self):
        for function, lines in (('_observe', OBSERVE_LINES), ('_accumulate', ACCUMULATE_LINES)):
            for source in lines:
                with self.subTest(function=function, source=source):
                    self.assertTrue(any(line.strip() == source for line in LINES), source)
                    run, owner = staged_run()
                    run.record['stage'] = 'b'
                    with self.assertRaises(KeyboardInterrupt):
                        traced(interrupt_at(F.QueryStages, function, source), run.save)
                    self.assert_stopped_and_frozen(run, owner)

    def test_every_line_of_finish_interrupt_is_marked_and_frozen(self):
        for source in FINISH_LINES:
            with self.subTest(source=source):
                run, owner = staged_run()
                run.record['stage'] = 'b'  # a skipped save, so finish() closes a stage too
                with self.assertRaises(KeyboardInterrupt):
                    traced(interrupt_at(F.QueryStages, 'finish', source, nested='step'), run.stages.finish)
                self.assert_stopped_and_frozen(run, owner)

    def test_interrupt_in_phase_before_and_after_save(self):
        # Before save: the stage is set but never observed; the next save closes it (no row was mid-update).
        run, owner = staged_run()
        with self.assertRaises(KeyboardInterrupt):
            traced(interrupt_at(TS.Run, 'phase', 'self.save()'), lambda: run.phase('b'))
        run.save()
        run.stages.closed(owner)
        run.stages.finish()
        value = run.record['completed_queries_by_stage']
        self.assertEqual(value['status'], 'COMPLETE')
        self.assertEqual(sum(row['hits'] or 0 for row in value['rows']), 7)
        self.assertEqual([row['stage'] for row in value['rows']], [None, 'a', 'b'])
        # After save (the interrupt lands in the caller once phase returned): rows already consistent.
        run, owner = staged_run()
        run.phase('b')
        run.stages.closed(owner)
        run.stages.finish()
        self.assertEqual(run.record['completed_queries_by_stage']['status'], 'COMPLETE')

    def test_the_interrupt_propagates_unchanged(self):
        for error in (KeyboardInterrupt(), SystemExit(3), GeneratorExit()):
            with self.subTest(error=type(error).__name__):
                run, owner = staged_run()
                run.record['stage'] = 'b'
                original = error
                try:
                    traced(interrupt_at(F.QueryStages, '_observe', 'self.stage = stage', error), run.save)
                except BaseException as caught:  # noqa: BLE001
                    self.assertIs(caught, original)
                    self.assertEqual(getattr(caught, '__notes__', None), None)
                    self.assertIsNone(caught.__cause__)
                else:
                    self.fail('not raised')
                self.assert_stopped_and_frozen(run, owner, type(error).__name__)

    def test_second_interrupt_at_stop_entry(self):
        """A second Ctrl+C pending when _stop is called fires at _stop's entry, before the status is set."""
        run, owner = staged_run()
        run.record['stage'] = 'b'

        def interrupted(error):
            raise KeyboardInterrupt('second')
        run.stages._stop = interrupted
        with self.assertRaises(KeyboardInterrupt) as raised:
            traced(interrupt_at(F.QueryStages, '_observe', 'self.stage = stage'), run.save)
        self.assertEqual(str(raised.exception), 'second')
        del run.stages._stop
        value = run.record['completed_queries_by_stage']
        status_after_double = value.get('status')
        run.save()  # _workload's except path
        run.stages.closed(owner)
        run.stages.finish()
        rows = value['rows']
        self.result = dict(status_after_double=status_after_double, final=value.get('status'),
                           hits=sum(row['hits'] or 0 for row in rows), duplicated=any(
                               rows[i] is rows[i+1] for i in range(len(rows)-1)))
        print('\nDOUBLE-INTERRUPT', self.result, file=sys.stderr)

    def test_second_interrupt_inside_stop_before_status(self):
        run, owner = staged_run()
        run.record['stage'] = 'b'
        stages = run.stages

        def interrupted(error):
            stages.owner = stages.base = None
            raise KeyboardInterrupt('second')
        stages._stop = interrupted
        with self.assertRaises(KeyboardInterrupt):
            traced(interrupt_at(F.QueryStages, '_observe', 'self.stage = stage'), run.save)
        del stages._stop
        value = run.record['completed_queries_by_stage']
        status_after_double = value.get('status')
        run.save()
        run.stages.closed(owner)
        run.stages.finish()
        rows = value['rows']
        print('\nDOUBLE-INTERRUPT-MID-STOP', dict(status_after_double=status_after_double, final=value.get('status'),
              hits=sum(row['hits'] or 0 for row in rows), duplicated=any(
                  rows[i] is rows[i+1] for i in range(len(rows)-1))), file=sys.stderr)

    def test_generator_exit_in_completed_queries(self):
        def scenario(observed):
            record, events = {}, []
            stages = F.QueryStages(record) if observed else None

            def save():
                if stages is not None:
                    stages.observe()
                events.append('save')

            def body():
                with F.completed_queries(TR.FakeOwner, Path('queries'), declared='columnar',
                                         arguments=F.query_store_arguments(TR.FakeOwner, 'columnar'), execution='e',
                                         budget='b', cancel='c', limits={'max_store_bytes': 7, 'max_entries': 5},
                                         record=record, save=save, query_stages=stages) as owner:
                    owner.written, owner.held, owner.hits = 5, 3, 1
                    yield owner
                    owner.hits = 99  # never reached
            generator = body()
            owner = next(generator)
            generator.close()  # GeneratorExit at the yield inside the with
            if stages is not None:
                stages.finish()
            return dict(cq=record.get('completed_queries'), events=events, owner_events=owner.events), record
        without, _ = scenario(False)
        withit, record = scenario(True)
        self.assertEqual(without, withit)
        value = record['completed_queries_by_stage']
        self.assertEqual(value['status'], 'COMPLETE')
        for name in F.QUERY_STAGE_FIELDS:
            self.assertEqual(sum(row[name] or 0 for row in value['rows']), record['completed_queries'][name], name)

    def test_observation_exception_still_never_raised(self):
        run, owner = staged_run()
        run.record['stage'] = 'b'
        run.stages._counts = lambda _owner: 1/0
        run.save()  # no raise
        value = run.record['completed_queries_by_stage']
        self.assertEqual(value['status'], 'INCOMPLETE')
        self.assertTrue(value['error'].startswith('ZeroDivisionError'))


if __name__ == '__main__':
    unittest.main()
