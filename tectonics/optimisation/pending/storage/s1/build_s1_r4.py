"""S1 revision 4: the r3 delta re-check's P3s (T/so/refute/s1/delta-r3/delta-r3.log); writes s1/r4/.

Source r3 (66a5000f). Only QueryStages._safely and the class docstring change:
- a second interrupt landing inside _stop (on entry, or at its str() or update() calls) left no status, so a later
  save counted the half-updated row again and finish() could report COMPLETE. Both failure branches now store
  status INCOMPLETE first, as a plain dict store with no call before it (CPython delivers a pending interrupt only at
  a call or a backward jump), and then call _stop;
- the docstring's one 140-character line is rewrapped.
The r3 S1 tests are carried over with one new test (a second interrupt while stopping, after an interrupt or an
ordinary failure mid-row).
"""
import hashlib
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

DOC_OLD = '''    same way (the rows are then not trusted as COMPLETE) and re-raised. finish() closes
    the last row and sets status COMPLETE; observation stops there. A run killed hard never reaches finish(): its run.json keeps the rows of
    the stages closed by its last save(), with no status and no in-progress row.
'''
DOC_NEW = '''    same way (the rows are then not trusted as COMPLETE) and re-raised. Either way the
    status is stored first, by a plain dict store with no call before it, so a second
    interrupt arriving while the failure is recorded cannot leave the rows unmarked.
    finish() closes the last row and sets status COMPLETE; observation stops there. A run
    killed hard never reaches finish(): its run.json keeps the rows of the stages closed
    by its last save(), with no status and no in-progress row.
'''
MARK = "            self.value['status'] = 'INCOMPLETE'  # first, with no call before it: see the class docstring\n"
SAFELY_OLD = '''        except Exception as error:  # noqa: BLE001 - instrumentation never fails the run
            self._stop(error)
        except BaseException as error:
            # An interrupt may have landed between two updates of a row: mark the rows, stop, re-raise.
            self._stop(error)
            raise
'''
SAFELY_NEW = '''        except Exception as error:  # noqa: BLE001 - instrumentation never fails the run
''' + MARK + '''            self._stop(error)
        except BaseException as error:
            # An interrupt may have landed between two updates of a row: mark the rows, stop, re-raise.
''' + MARK + '''            self._stop(error)
            raise
'''

TEST_OLD = '''        self.assertTrue(value['error'].startswith('KeyboardInterrupt'))


class WiringTests'''
TEST_NEW = '''        self.assertTrue(value['error'].startswith('KeyboardInterrupt'))

    def test_a_second_interrupt_while_stopping_still_marks_the_rows(self):  # m23, m24
        # A failure mid-row, then a second interrupt inside _stop before it stores anything: the status is
        # already INCOMPLETE, so no later save or finish() adds to the rows or calls them COMPLETE.
        class Owner(TR.FakeOwner):
            failure = None

            @property
            def unflushed(self):
                if self.failure is not None:
                    raise self.failure
                return 0

        def second(error):
            raise KeyboardInterrupt('second')
        for first in (KeyboardInterrupt('first'), RuntimeError('first')):
            with self.subTest(first=type(first).__name__):
                run = Run()
                run.phase('s')
                owner = Owner('x', context=None, budget=None)
                run.stages.opened(owner)
                owner.hits += 2
                owner.failure = first
                run.stages._stop = second
                with self.assertRaisesRegex(KeyboardInterrupt, 'second'):
                    run.phase('t')
                owner.failure = None
                before = json.dumps(run.record['completed_queries_by_stage'], sort_keys=True)
                owner.hits += 5
                run.phase('u')
                run.stages.closed(owner)
                run.stages.finish()
                value = run.record['completed_queries_by_stage']
                self.assertEqual(json.dumps(value, sort_keys=True), before)
                self.assertEqual(value['status'], 'INCOMPLETE')


class WiringTests'''


def replace_once(text, old, new, label):
    if text.count(old) != 1:
        raise SystemExit('%s: seam found %d times' % (label, text.count(old)))
    return text.replace(old, new)


def checked(path, short):
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest()[:8] != short:
        raise SystemExit('%s is not %s: refusing' % (path, short))
    return data


def main():
    s = checked(HERE/'r3'/'run_fresh_interval.py', '66a5000f').decode('utf8')
    t = checked(HERE/'r3'/'test_s1_query_stages.py', 'b1c3c051').decode('utf8')
    checked(HERE/'r3'/'test_run_fresh_interval.py', '543e5608')
    for label, old, new in (('docstring', DOC_OLD, DOC_NEW), ('_safely', SAFELY_OLD, SAFELY_NEW)):
        s = replace_once(s, old, new, label)
    t = replace_once(t, TEST_OLD, TEST_NEW, 'new test')
    compile(s, 'run_fresh_interval.py', 'exec')
    compile(t, 'test_s1_query_stages.py', 'exec')
    target = HERE/'r4'
    target.mkdir(exist_ok=False)
    for name, text in (('run_fresh_interval.py', s), ('test_s1_query_stages.py', t)):
        (target/name).write_bytes(text.encode('utf8'))
    shutil.copyfile(HERE/'r3'/'test_run_fresh_interval.py', target/'test_run_fresh_interval.py')
    for name in ('run_fresh_interval.py', 'test_s1_query_stages.py', 'test_run_fresh_interval.py'):
        print('wrote', target/name, hashlib.sha256((target/name).read_bytes()).hexdigest())


if __name__ == '__main__':
    sys.exit(main())
