"""Run unittest names from C with a stack-dump watchdog (no timing claims).

Usage: python -B run_test_watchdog.py SECONDS test.name [test.name ...]
After SECONDS without finishing, every thread's stack is dumped and the
process exits, so a spinning test shows where it loops instead of hanging.
"""
import faulthandler
import os
import sys
import unittest

R = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..'))
C = os.path.join(R, 'compact-geometry-r1')


def main():
    seconds = float(sys.argv[1])
    os.chdir(C)
    sys.path.insert(0, C)
    # Appended last, so C and each test's own inserts still win: a few storage
    # suites import atlas_tectonics and R siblings without adding them.
    sys.path.extend([os.path.join(os.path.dirname(R), 'runtime-integration-r1', 'runtime-src'), R])
    faulthandler.dump_traceback_later(seconds, exit=True)
    suite = unittest.defaultTestLoader.loadTestsFromNames(sys.argv[2:])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    faulthandler.cancel_dump_traceback_later()
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
