"""Item 11 planted mutants: each replaces fresh_interval_driver._commit_stages in memory only and
must make the item 11 wiring tests fail. Prints one line per mutant; exit 1 if any survives.
Usage: python -B item11_mutants.py   (nothing is written)
"""
import sys
import unittest
from pathlib import Path

R = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(R))

import test_fresh_interval_driver as T  # noqa: E402

F = T.F
ORIGINAL = F._commit_stages


def dropped_save(m):
    return [stage for stage in ORIGINAL(m) if stage[1] != 'heat-checkpoint-save']


def finish_after_publish(m):
    stages = ORIGINAL(m)
    return stages[:-2] + [stages[-1], stages[-2]]


def never_r3(m):
    return [stage for stage in ORIGINAL(m) if stage[1] != 'heat-checkpoint-r3-checks']


def renamed_publish(m):
    return ORIGINAL(m)[:-1] + [(m.Workflow._publish, 'endpoint-store-commit')]


TESTS = ('test_item11_the_projection_to_commit_window_is_split_in_call_order',
         'test_item11_without_the_r3_transform_only_its_stage_is_absent_and_recorded')


def survives(mutant):
    F._commit_stages = mutant
    try:
        suite = unittest.TestSuite(T.WiringTests(name) for name in TESTS)
        result = unittest.TextTestRunner(stream=open('nul' if sys.platform == 'win32' else '/dev/null', 'w'),
                                         verbosity=0).run(suite)
        return result.wasSuccessful()
    finally:
        F._commit_stages = ORIGINAL


def main():
    assert survives(ORIGINAL), 'the unmutated tests must pass'
    missed = [mutant.__name__ for mutant in (dropped_save, finish_after_publish, never_r3, renamed_publish)
              if survives(mutant)]
    for mutant in (dropped_save, finish_after_publish, never_r3, renamed_publish):
        print(mutant.__name__, 'SURVIVED' if mutant.__name__ in missed else 'caught')
    return 1 if missed else 0


if __name__ == '__main__':
    sys.exit(main())
