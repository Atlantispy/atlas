"""S1 r4 delta refuter probes: a second interrupt at every point of the failure branch; dis of the handlers."""
import dis
import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE)]

import test_run_fresh_interval as TR
import test_s1_query_stages as TS
from test_delta_r3_probes import interrupt_at, traced, staged_run, snapshot

F = TR.F
assert Path(F.__file__).resolve().parent == HERE, F.__file__
STOP_UPDATE = "self.value.update(status='INCOMPLETE', error=type(error).__name__+': '+str(error)[:256])"


class Second(KeyboardInterrupt):
    pass


class FirstInterrupt(KeyboardInterrupt):
    second_in_str = False

    def __str__(self):
        if self.second_in_str:
            raise Second('second in str()')
        return 'first'


class FirstFailure(RuntimeError):
    second_in_str = False

    def __str__(self):
        if self.second_in_str:
            raise Second('second in str()')
        return 'first'


class ArmedDict(dict):
    armed = False

    def update(self, *args, **kwargs):
        if self.armed:
            raise Second('second in update()')
        return super().update(*args, **kwargs)


class Failing(TR.FakeOwner):
    failure = None

    @property
    def unflushed(self):
        if self.failure is not None:
            raise self.failure
        return self.held


def failing_run():
    run = TS.Run()
    run.phase('a')
    with run.queries() as first:
        first.hits = 4
    owner = Failing('x', context=None, budget=None)
    run.stages.opened(owner)
    owner.hits = 3
    return run, owner


class DoubleInterruptProbes(unittest.TestCase):
    def assert_marked_and_frozen(self, run, owner):
        value = run.record['completed_queries_by_stage']
        self.assertEqual(value['status'], 'INCOMPLETE')
        before = snapshot(run)
        owner.failure = None
        owner.hits += 7
        run.save()
        run.phase('later')
        run.stages.opened(TR.FakeOwner('y', context=None, budget=None))
        run.stages.closed(owner)
        run.stages.finish()
        run.save()
        self.assertEqual(snapshot(run), before)
        rows = value['rows']
        self.assertFalse(any(rows[i] is rows[i+1] for i in range(len(rows)-1)))
        return value

    def second_points(self, run, first):
        stages = run.stages

        def at_entry(error):
            raise Second('second at _stop entry')

        def after_clear(error):
            stages.owner = stages.base = None
            raise Second('second after owner cleared')
        yield 'entry', lambda: setattr(stages, '_stop', at_entry)
        yield 'after-clear', lambda: setattr(stages, '_stop', after_clear)
        yield 'update-line', None  # traced: before the whole update line (str and update both pending)
        yield 'str', lambda: setattr(first, 'second_in_str', True)

        def arm_update():
            armed = ArmedDict(stages.value)
            stages.value = run.record['completed_queries_by_stage'] = armed
            armed.armed = True
        yield 'update', arm_update

    def test_second_interrupt_at_every_point_still_marks_the_rows(self):
        for first_type in (FirstInterrupt, FirstFailure):
            for where in ('entry', 'after-clear', 'update-line', 'str', 'update'):
                with self.subTest(first=first_type.__name__, where=where):
                    run, owner = failing_run()
                    first = first_type()
                    arm = dict(self.second_points(run, first))[where]
                    if arm is not None:
                        arm()
                    owner.failure = first
                    run.record['stage'] = 'b'
                    tracer = interrupt_at(F.QueryStages, '_stop', STOP_UPDATE, Second('second at update line')) \
                        if where == 'update-line' else None
                    with self.assertRaises(Second):
                        traced(tracer, run.save)
                    if isinstance(run.stages.value, ArmedDict):
                        run.stages.value.armed = False
                    vars(run.stages).pop('_stop', None)
                    first.second_in_str = False
                    self.assert_marked_and_frozen(run, owner)

    def test_single_interrupt_and_exception_paths_keep_r3_behaviour(self):
        run, owner = failing_run()
        owner.failure = FirstInterrupt()
        run.record['stage'] = 'b'
        with self.assertRaises(FirstInterrupt):
            run.save()
        value = self.assert_marked_and_frozen(run, owner)
        self.assertEqual(value['error'], 'FirstInterrupt: first')
        run, owner = failing_run()
        owner.failure = FirstFailure()
        run.record['stage'] = 'b'
        run.save()  # never raised
        value = self.assert_marked_and_frozen(run, owner)
        self.assertEqual(value['error'], 'FirstFailure: first')
        run, owner = failing_run()
        run.stages.closed(owner)
        run.stages.finish()
        self.assertEqual(run.record['completed_queries_by_stage']['status'], 'COMPLETE')

    def test_pre_existing_broken_str_escapes_save(self):
        """Outside the delta: an Exception whose __str__ fails escapes _stop, so save() raises (r1-r4)."""
        class Broken(RuntimeError):
            def __str__(self):
                raise ValueError('broken __str__')
        run, owner = failing_run()
        owner.failure = Broken()
        run.record['stage'] = 'b'
        try:
            run.save()
        except ValueError as error:
            print('\nBROKEN-STR escapes save():', repr(error), 'status',
                  run.record['completed_queries_by_stage'].get('status'), file=sys.stderr)
        else:
            print('\nBROKEN-STR contained', file=sys.stderr)

    def test_handlers_reach_the_status_store_without_a_call(self):
        code = F.QueryStages._safely.__code__
        instructions = list(dis.get_instructions(code))
        by_offset = {ins.offset: i for i, ins in enumerate(instructions)}
        # LOAD_ATTR self.value runs no Python code: a plain instance attribute holding a plain dict.
        self.assertNotIn('value', vars(F.QueryStages))
        self.assertNotIn('__getattribute__', vars(F.QueryStages))
        self.assertNotIn('__getattr__', vars(F.QueryStages))
        self.assertIs(type(F.QueryStages({}).value), dict)
        handlers = sorted({entry.target for entry in dis.Bytecode(code).exception_entries})
        risky = ('CALL', 'RESUME', 'JUMP_BACKWARD', 'SEND', 'YIELD_VALUE', 'INSTRUMENTED')
        paths = []
        for target in handlers:
            i, path = by_offset[target], []
            while i < len(instructions):
                ins = instructions[i]
                path.append(ins.opname+('' if ins.argrepr == '' else ' '+ins.argrepr))
                if ins.opname == 'STORE_SUBSCR' or ins.opname.startswith(('RERAISE', 'RETURN')):
                    break
                i += 1
            paths.append(path)
        print('\nHANDLER PATHS', file=sys.stderr)
        for path in paths:
            print('  ', ' | '.join(path), file=sys.stderr)
        stores = [path for path in paths if path[-1] == 'STORE_SUBSCR']
        self.assertTrue(stores, paths)
        for path in stores:
            self.assertFalse([op for op in path if op.startswith(risky)], path)
        # The BaseException branch: from its CHECK_EXC_MATCH to its store, along the fall-through path.
        text = [ins.opname+' '+ins.argrepr for ins in instructions]
        start = next(i for i, t in enumerate(text) if t.startswith('LOAD_GLOBAL') and 'BaseException' in t)
        end = next(i for i in range(start, len(text)) if text[i].startswith('STORE_SUBSCR'))
        branch = text[start:end+1]
        print('  BaseException branch:', ' | '.join(branch), file=sys.stderr)
        self.assertFalse([op for op in branch if op.startswith(risky)], branch)
        start = next(i for i, t in enumerate(text) if t.startswith('LOAD_GLOBAL') and t.endswith(' Exception'))
        end = next(i for i in range(start, len(text)) if text[i].startswith('STORE_SUBSCR'))
        branch = text[start:end+1]
        print('  Exception branch:', ' | '.join(branch), file=sys.stderr)
        self.assertFalse([op for op in branch if op.startswith(risky)], branch)


if __name__ == '__main__':
    unittest.main()
