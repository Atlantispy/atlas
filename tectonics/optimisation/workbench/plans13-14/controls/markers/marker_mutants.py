"""Apply the five stipulated FD faults to disposable files and require their detection."""
import argparse
import importlib.util
import io
from hashlib import sha256
import json
import os
from pathlib import Path
import sys
import time
import unittest

HERE = Path(__file__).resolve().parent
T = Path('C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10')
ROOT = T / 'ac/p1012-r1'
SOURCE = HERE / 'candidate/helpers/fresh_interval_driver.py'
TEST = HERE / 'checks-r3/test_fresh_interval_driver.py'
CASES = ('WiringTests.test_item11m_heat_counters_follow_the_r9_three',
         'WiringTests.test_item11m_a_scan_without_one_direct_nested_function_refuses_before_the_admission',
         'WiringTests.test_item11_the_projection_to_commit_window_is_split_in_call_order',
         'WiringTests.test_item11_without_the_r3_transform_only_its_stage_is_absent_and_recorded',
         'WiringTests.test_item11m_the_successor_refuses_a_scan_without_one_nested_function_before_the_admission',
         'ClosureContractTests.test_returns_the_unique_direct_code_object_without_executing_the_guard',
         'ClosureContractTests.test_missing_and_duplicate_closures_raise')


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    output = parser.parse_args().output.resolve()
    if sys.flags.hash_randomization != 0 or os.environ.get('PYTHONHASHSEED') != '0':
        raise ValueError('Start the exact interpreter with PYTHONHASHSEED=0')
    output.mkdir(exist_ok=False)
    began = time.perf_counter()
    sys.path[:0] = [str(SOURCE.parent), str(ROOT / 'helpers'), str(ROOT / 'src')]
    os.environ.update(P14_COMPOSITION=str(ROOT), P14_DRIVER_ROOT=str(SOURCE.parent))
    tests = load('_plan14_focused_marker_tests', TEST)
    raw = SOURCE.read_bytes()
    text = raw.decode('utf8')
    pins = {str(p): sha256(p.read_bytes()).hexdigest() for p in (SOURCE, TEST, ROOT / 'composition.json')}
    faults = {
        'drop-stage': (", (F.C.correct, 'heat-finish-correction')", ''),
        'reorder-stages': ("(F.Q.closed_guard, 'heat-finish-closed-guard'), (F.I.issue, 'heat-finish-issue')",
                           "(F.I.issue, 'heat-finish-issue'), (F.Q.closed_guard, 'heat-finish-closed-guard')"),
        'accept-zero': ("    _require(len(found) == 1,", "    if not found:\n        return None\n    _require(len(found) == 1,"),
        'accept-multiple': ("_require(len(found) == 1,", "_require(len(found) >= 1,"),
        'wrong-tick-code': ("__code__=_closure(guard, 'certificate')", "__code__=_closure(guard, 'admissible')"),
    }
    rows = []
    for name, fault in [('baseline', None), *faults.items()]:
        changed = text
        if fault is not None:
            before, after = fault
            if text.count(before) != 1:
                raise ValueError('Mutant not uniquely applicable: ' + name)
            changed = text.replace(before, after)
            if changed == text:
                raise ValueError('Unapplied mutant: ' + name)
        path = output / name / 'fresh_interval_driver.py'
        path.parent.mkdir()
        path.write_text(changed, encoding='utf8', newline='\n')
        tests.F = load('_plan14_' + name.replace('-', '_'), path)
        suite = unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromName(case, tests) for case in CASES)
        stream = io.StringIO()
        result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
        (path.parent / 'checks.log').write_text(stream.getvalue(), encoding='utf8')
        row = dict(name=name, applied=fault is not None, sha256=sha256(path.read_bytes()).hexdigest(),
                   tests=result.testsRun, passed=result.wasSuccessful(), caught=not result.wasSuccessful(),
                   failures=[test.id() for test, _ in result.failures], errors=[test.id() for test, _ in result.errors])
        rows.append(row)
        print(json.dumps(row), flush=True)
        if name == 'baseline' and not result.wasSuccessful():
            raise AssertionError('Clean baseline must pass before applying any mutant')
    finality = all(sha256(Path(p).read_bytes()).hexdigest() == pin for p, pin in pins.items())
    passed = rows[0]['passed'] and all(row['applied'] and row['caught'] for row in rows[1:]) and finality
    report = dict(passed=passed, baseline_pass=rows[0]['passed'], applied=5, caught=sum(r['caught'] for r in rows[1:]),
                  survived=sum(r['passed'] for r in rows[1:]), unapplied=0, rows=rows,
                  source_pins=pins, source_finality=finality, seconds=time.perf_counter()-began)
    (output / 'result.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf8')
    return 0 if passed else 1


if __name__ == '__main__':
    sys.exit(main())
