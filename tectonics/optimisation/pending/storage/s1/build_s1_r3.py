"""S1 revision 3: the r2 delta re-check's residual P3s (T/so/refute/s1/delta-r2/delta-r2.log); writes s1/r3/.

Source r2 (8581f597). Only QueryStages changes, plus one blank line:
- an interrupt (KeyboardInterrupt, SystemExit) inside an observation can land between two updates of a row
  (rows.append before self.stage; row.update before self.base), so a later save or finish() would count that
  row or delta twice. It is now recorded (status INCOMPLETE, error) and re-raised: observation stops, finish()
  no longer marks the rows COMPLETE, and the interrupt itself still propagates (never swallowed);
- two blank lines before @contextmanager (E302).
The r2 S1 tests are carried over with the m10 test updated (an interrupt now leaves INCOMPLETE) and one new test.
"""
import hashlib
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

DOC_OLD = '''    An Exception here is recorded (status INCOMPLETE, error) and stops only this
    observation; the rows keep the stages closed before it (recording failures stay
    diagnostic, as in dev_stage_timing). A BaseException (KeyboardInterrupt, SystemExit)
    is never caught. finish() closes the last row and sets status COMPLETE; observation
    stops there.'''
DOC_NEW = '''    An Exception here is recorded (status INCOMPLETE, error) and stops only this
    observation; the rows keep the stages closed before it (recording failures stay
    diagnostic, as in dev_stage_timing). A BaseException (KeyboardInterrupt, SystemExit)
    is never swallowed: it may land between two updates of a row, so it is recorded the
    same way (the rows are then not trusted as COMPLETE) and re-raised. finish() closes
    the last row and sets status COMPLETE; observation stops there.'''

SAFELY_OLD = '''    def _safely(self, step):
        if 'status' in self.value:  # finished (COMPLETE) or failed (INCOMPLETE): observation has stopped
            return
        try:
            step()
        except Exception as error:  # noqa: BLE001 - instrumentation never fails the run
            self.owner = self.base = None
            self.value.update(status='INCOMPLETE', error=type(error).__name__+': '+str(error)[:256])
'''
SAFELY_NEW = '''    def _stop(self, error):
        self.owner = self.base = None
        self.value.update(status='INCOMPLETE', error=type(error).__name__+': '+str(error)[:256])

    def _safely(self, step):
        if 'status' in self.value:  # finished (COMPLETE) or failed (INCOMPLETE): observation has stopped
            return
        try:
            step()
        except Exception as error:  # noqa: BLE001 - instrumentation never fails the run
            self._stop(error)
        except BaseException as error:
            # An interrupt may have landed between two updates of a row: mark the rows, stop, re-raise.
            self._stop(error)
            raise
'''
GAP_OLD = '        self._safely(step)\n\n@contextmanager\ndef completed_queries('
GAP_NEW = '        self._safely(step)\n\n\n@contextmanager\ndef completed_queries('

TEST_OLD = '''    def test_a_base_exception_is_never_caught(self):  # m10
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
'''
TEST_NEW = '''    def test_a_base_exception_is_never_caught(self):  # m10, m22
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
        value = run.record['completed_queries_by_stage']
        self.assertEqual((value['status'], value['error']), ('INCOMPLETE', 'KeyboardInterrupt: '))

    def test_an_interrupt_mid_row_marks_the_rows_and_stops(self):  # m21
        # The interrupt lands inside a stage change's accumulate (after the row's reads began); whatever was
        # half applied, no later save or finish() adds to the rows or calls them COMPLETE.
        class Owner(TR.FakeOwner):
            interrupt = False

            @property
            def unflushed(self):
                if self.interrupt:
                    raise KeyboardInterrupt
                return 0
        run = Run()
        run.phase('s')
        owner = Owner('x', context=None, budget=None)
        run.stages.opened(owner)
        owner.hits += 2
        owner.interrupt = True
        with self.assertRaises(KeyboardInterrupt):
            run.phase('t')
        owner.interrupt = False
        before = json.dumps(run.record['completed_queries_by_stage'], sort_keys=True)
        owner.hits += 5
        run.phase('u')
        run.stages.closed(owner)
        run.stages.finish()
        value = run.record['completed_queries_by_stage']
        self.assertEqual(json.dumps(value, sort_keys=True), before)
        self.assertEqual(value['status'], 'INCOMPLETE')
        self.assertTrue(value['error'].startswith('KeyboardInterrupt'))
'''


def replace_once(text, old, new, label):
    if text.count(old) != 1:
        raise SystemExit('%s: seam found %d times' % (label, text.count(old)))
    return text.replace(old, new)


def main():
    source = (HERE/'r2'/'run_fresh_interval.py').read_bytes()
    if hashlib.sha256(source).hexdigest()[:8] != '8581f597':
        raise SystemExit('r2 candidate is not 8581f597: refusing')
    test = (HERE/'r2'/'test_s1_query_stages.py').read_bytes()
    if hashlib.sha256(test).hexdigest()[:8] != '0c84ac49':
        raise SystemExit('r2 S1 tests are not 0c84ac49: refusing')
    s = source.decode('utf8')
    for label, old, new in (('docstring', DOC_OLD, DOC_NEW), ('_safely', SAFELY_OLD, SAFELY_NEW),
                            ('E302 gap', GAP_OLD, GAP_NEW)):
        s = replace_once(s, old, new, label)
    owner_test = (HERE/'r2'/'test_run_fresh_interval.py').read_bytes()
    if hashlib.sha256(owner_test).hexdigest()[:8] != '543e5608':
        raise SystemExit('relocated owner test is not 543e5608: refusing')
    t = replace_once(test.decode('utf8'), TEST_OLD, TEST_NEW, 'm10 test')
    compile(s, 'run_fresh_interval.py', 'exec')
    compile(t, 'test_s1_query_stages.py', 'exec')
    target = HERE/'r3'
    target.mkdir(exist_ok=False)
    for name, data in (('run_fresh_interval.py', s.encode('utf8')), ('test_s1_query_stages.py', t.encode('utf8')),
                       ('test_run_fresh_interval.py', owner_test)):
        (target/name).write_bytes(data)
        print('wrote', target/name, hashlib.sha256(data).hexdigest())


if __name__ == '__main__':
    sys.exit(main())
