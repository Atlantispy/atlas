"""Run only the affected synthetic Windows receiver checks in a materialised source.

Requires the compatible Atlas interpreter and a new scratch directory. No real
interval data, timing campaign or default selection is used.
SPDX-License-Identifier: AGPL-3.0-only
"""
import argparse
import hashlib
import importlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

GUARDED_E2 = frozenset({
    'test_seal_inventory_failure_gets_its_closing_identity_check',
    'test_failed_batch_body_refuses_only_if_identity_changed',
    'test_verified_read_fallback_without_read_batch_checks_on_failure',
})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', required=True, type=Path)
    parser.add_argument('--scratch', required=True, type=Path)
    args = parser.parse_args()
    source, scratch = args.source_root.resolve(strict=True), args.scratch.absolute()
    if os.name != 'nt':
        parser.error('The native receiver check requires Windows; no skipped pass is reported')
    scratch.mkdir(parents=True, exist_ok=False)
    (scratch / '_t').mkdir()
    tempfile.tempdir = str(scratch / '_t')
    os.environ['TEMP'] = os.environ['TMP'] = tempfile.tempdir
    sys.path[:0] = [str(source / 'helpers'), str(source / 'src')]
    fixture = importlib.import_module('test_segment_store')
    fixture.TASK = scratch
    native = importlib.import_module('test_s1a_guarded_read')
    fresh = importlib.import_module('test_s1_sealed_read')
    guard = importlib.import_module('sealed_guard_set')
    suite = unittest.TestSuite((unittest.defaultTestLoader.loadTestsFromModule(native),
                               unittest.defaultTestLoader.loadTestsFromTestCase(fresh.S1RefuterFreshnessTests)))
    if suite.countTestCases() != 36:
        raise ValueError('Expected the original 26 guard cases plus ten freshness cases')
    guard_observations = {}

    class Result(unittest.TextTestResult):
        def startTest(self, test):
            self.guarded_before = guard.STATS['guarded']
            super().startTest(test)

        def stopTest(self, test):
            if test._testMethodName in GUARDED_E2:
                guard_observations[test._testMethodName] = guard.STATS['guarded'] - self.guarded_before
            super().stopTest(test)

    result = unittest.TextTestRunner(verbosity=2, resultclass=Result).run(suite)
    sources = {}
    for name in ('sealed_guard_set', 'interval_store_set', 'interval_catalog',
                 'test_s1a_guarded_read', 'test_s1_sealed_read', 'atlas_tectonics.reuse'):
        path = Path(sys.modules[name].__file__).resolve()
        sources[name] = dict(member=path.relative_to(source).as_posix(),
                             sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    passed = (result.wasSuccessful() and result.testsRun == 36 and not result.skipped
              and set(guard_observations) == GUARDED_E2 and all(v > 0 for v in guard_observations.values()))
    record = dict(passed=passed, tests=result.testsRun, failures=len(result.failures), errors=len(result.errors),
        skipped=[(str(test), reason) for test, reason in result.skipped],
        guard_observations=guard_observations, sources=sources,
        bad=[(str(test), trace) for test, trace in result.failures + result.errors],
        scope='Synthetic receiver checks only; no performance, IV data or scientific acceptance')
    (scratch / 'result.json').write_text(json.dumps(record, indent=2) + '\n', encoding='utf-8', newline='\n')
    print(json.dumps({key: record[key] for key in ('passed', 'tests', 'failures', 'errors', 'skipped', 'guard_observations')}))
    raise SystemExit(0 if passed else 1)


if __name__ == '__main__':
    main()
