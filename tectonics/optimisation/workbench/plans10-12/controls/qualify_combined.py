"""Tracked, bounded qualification of the changed integration seams only."""
import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
W = HERE.parents[1]
T = Path('C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10')
PYTHON = T / '.r44-env/Scripts/python.exe'
ROOT = T / 'ac/p1012-r1'
COMPOSITION = ROOT / 'composition.json'
COMP_SHA = 'cb71df92d0ab2f3ab175c43a669d5b8ffc1d4d350cbdc49b68fd6f2cabfb74d5'
BOOT = HERE / 'bootstrap_native.py'
BOOT_SHA = '9df3df452bc39509ff7364ca0ef37ed8218228c5adca39b87a08869fc1b2c59c'
P10 = W / 'work/plan10/review-integration-r1/run_measurement_reuse_controls.py'
P10_SHA = '97af4a15f5d12ad44a284f2ee7939365f2dbe13291165284db025382d79a24a1'
P11 = W / 'work/plan11/review-integration-r1/run_successor_bootstrap_controls.py'
P11_SHA = '00c917717a1d80babf6404de1fb89ba5c1f4002a004b56d64645db5addf6f867'


def check(path, pin):
    if sha256(path.read_bytes()).hexdigest() != pin:
        raise ValueError('Source identity differs: ' + str(path))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--phase', choices=('orchestration', 'heat'), required=True)
    parser.add_argument('--heat-sha256')
    args = parser.parse_args()
    evidence = HERE / ('e-' + args.phase + '-r1')
    if evidence.exists():
        raise FileExistsError('Evidence already exists; preserve original attempt')
    pins = {COMPOSITION: COMP_SHA, BOOT: BOOT_SHA, Path(__file__).resolve(): sha256(Path(__file__).read_bytes()).hexdigest()}
    native = [str(PYTHON), '-B', '-s', '-P', str(BOOT), '--composition', str(COMPOSITION)]
    if args.phase == 'orchestration':
        pins.update({P10: P10_SHA, P11: P11_SHA})
        stages = [
            ('reuse-ten', [str(PYTHON), '-B', '-s', '-P', str(P10), '--composition-sha256', COMP_SHA], 0, '"tests_run": 10'),
            ('bootstrap-seventeen', [str(PYTHON), '-B', '-I', str(P11), '--bootstrap-sha256', BOOT_SHA, '--helper-count', '390'], 0, '"tests_run": 17'),
            ('native-help', native + ['--composition-sha256', COMP_SHA, '--', '--help'], 0, 'usage:'),
            ('bad-composition-pin', native + ['--composition-sha256', '0' * 64, '--', '--help'], 1, 'source digest differs'),
            ('bad-native-argument', native + ['--composition-sha256', COMP_SHA, '--', '--stage', 'unknown-review-stage'], 2, 'invalid choice'),
        ]
    else:
        heat = W / 'work/plan12/review-integration-r1/run_combined_heat_controls.py'
        if not args.heat_sha256:
            raise ValueError('explicit reviewed heat runner pin required')
        pins[heat] = args.heat_sha256
        stages = [('heat-eight-cell', [str(PYTHON), '-B', '-s', '-P', str(heat), '--composition-sha256', COMP_SHA], 0, '"passed": true')]
    for p, pin in pins.items():
        check(p, pin)
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith('PYTHON') and
           k.upper() not in {'COVERAGE_PROCESS_START', 'COVERAGE_RCFILE', 'PYDEVD_LOAD_VALUES_ASYNC', 'PYDEVD_USE_FRAME_EVAL'}}
    env.update(PYTHONHASHSEED='0', PYTHONDONTWRITEBYTECODE='1', OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1')
    evidence.mkdir()
    result = dict(passed=False, phase=args.phase, source_pins={str(p): s for p, s in pins.items()}, stages=[],
                  full_interval_run=False, holds_released=False, scientific_acceptance=False)
    began = time.perf_counter()
    try:
        for name, command, expected_exit, marker in stages:
            start = time.perf_counter()
            completed = subprocess.run(command, cwd=T, env=env, capture_output=True, timeout=180)
            out, err = evidence / (name + '.stdout.txt'), evidence / (name + '.stderr.txt')
            out.write_bytes(completed.stdout)
            err.write_bytes(completed.stderr)
            text = (completed.stdout + completed.stderr).decode('utf8', errors='replace')
            passed = completed.returncode == expected_exit and marker in text
            row = dict(name=name, passed=passed, command=command, exit=completed.returncode,
                       expected_exit=expected_exit, expected_marker=marker, seconds=time.perf_counter()-start,
                       stdout_sha256=sha256(completed.stdout).hexdigest(), stderr_sha256=sha256(completed.stderr).hexdigest())
            result['stages'].append(row)
            print(json.dumps(row), flush=True)
            if not passed:
                raise RuntimeError('Qualification failed: ' + name + '; see retained stdout/stderr')
        for p, pin in pins.items():
            check(p, pin)
        result.update(passed=True, source_finality=True)
    except BaseException as error:
        result['failure'] = repr(error)
        raise
    finally:
        result['seconds'] = time.perf_counter() - began
        (evidence / 'result.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf8')
    print(json.dumps(dict(passed=True, evidence=str(evidence), stages=len(result['stages']), seconds=result['seconds'])), flush=True)


if __name__ == '__main__':
    main()
