"""Add timeout/failure retention around the unchanged frozen C14 child cases.

The reviewed original source, derivation, package and five scientific cases are
immutable. This parent-only successor records partial streams and finality on
failure, returns nonzero, and never retries a case. Explicit queue GO is separate.
"""
import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import traceback
import types

HERE = Path(__file__).resolve().parent
W = Path('C:/Users/LOCAL_USER/Documents/Codex/agentchattr/workspace')
T = Path('C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10')
ORIGINAL = W / 'work/plan13/c14-r1/qualify_heat.py'
ORIGINAL_SHA = 'ca57b86c67efd3b588e5aa0a3ae430fe6a3cf1c0fdb1c6c02316deef138d8fdf'
DERIVATION = T / 'ac/p13c14-run-r1/derivation.json'
DERIVATION_SHA = 'c333a6442c402f72322bb2969b81cce6ca853b4aeb241fc3b8fab1a827d9ba1e'
COMPOSITION = T / 'ac/p13c14-r1/composition.json'
COMPOSITION_SHA = '646916ba3264257e5d67ae95b1fd66f9d300c92fa614e93f32035d7bb0ebaf70'
CASES = ('identities', 'compiled-identity', 'eight-cell', 'compact-reopen', 'mutation')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def checked(path, expected):
    raw = path.read_bytes()
    require(sha256(raw).hexdigest() == expected, 'Source identity differs: ' + str(path))
    return raw


def bytes_value(value):
    if value is None:
        return b''
    return value if isinstance(value, bytes) else value.encode('utf8')


def finality(module, bindings):
    checks = []
    for name, pin in bindings.items():
        try:
            checked(Path(name), pin)
            checks.append(dict(path=name, sha256=pin, status='PASS'))
        except Exception as error:
            checks.append(dict(path=name, sha256=pin, status='FAIL', failure=repr(error)))
    try:
        module.source_inputs()
        declared = dict(status='PASS', scope='Unchanged original source_inputs closure')
    except Exception as error:
        declared = dict(status='FAIL', scope='Unchanged original source_inputs closure', failure=repr(error))
    return dict(passed=declared['status'] == 'PASS' and all(row['status'] == 'PASS' for row in checks),
                checks=checks, original_declared_source_closure=declared)


def run_cases(module, output, bindings, runtime_environment, selection_pin, *, run_process=subprocess.run):
    """Drive original child entry points; always save a result after admission."""
    require(not output.exists(), 'Preserve previous qualification output')
    output.mkdir(parents=True)
    records, failure = [], None
    began = time.perf_counter()
    env = {key: value for key, value in os.environ.items()
           if not key.upper().startswith(('PYTHON', 'PYDEVD', 'COVERAGE'))}
    env.update(PYTHONHASHSEED='0', PYTHONDONTWRITEBYTECODE='1',
               OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1')
    try:
        module.source_inputs()
        require(tuple(module.CASES) == CASES, 'Original five scientific cases changed')
        for case in module.CASES:
            with tempfile.TemporaryDirectory(prefix='heat-' + case + '-', dir=output) as temporary:
                command = [sys.executable, '-B', '-s', '-P', str(module.__file__),
                    '--derivation-sha256', module.DERIVATION_SHA, '--case', case, '--scratch', temporary]
                start = time.perf_counter()
                stdout = stderr = b''
                returncode = None
                timed_out = False
                process_failure = None
                try:
                    done = run_process(command, capture_output=True, cwd=module.ROOT, env=env,
                                       timeout=180, check=False)
                    stdout, stderr, returncode = bytes_value(done.stdout), bytes_value(done.stderr), done.returncode
                except subprocess.TimeoutExpired as error:
                    # subprocess.run kills and waits for its timed-out child.
                    # TimeoutExpired may contain bytes even when text=True;
                    # retain the actual returned bytes without loss or retry.
                    stdout, stderr = bytes_value(error.stdout), bytes_value(error.stderr)
                    timed_out, process_failure = True, repr(error)
                except Exception as error:
                    stdout = bytes_value(getattr(error, 'stdout', None))
                    stderr = bytes_value(getattr(error, 'stderr', None))
                    process_failure = repr(error)
                (output / (case + '.stdout.txt')).write_bytes(stdout)
                (output / (case + '.stderr.txt')).write_bytes(stderr)
                try:
                    assertion = json.loads(stdout)
                    assertions_pass = assertion.get('case') == case and assertion.get('status') == 'PASS'
                except (ValueError, TypeError, AttributeError):
                    assertions_pass = False
                passed = returncode == 0 and assertions_pass and not timed_out and process_failure is None
                row = dict(case=case, status='PASS' if passed else ('TIMEOUT' if timed_out else 'FAIL'),
                    returncode=returncode, timed_out=timed_out, timeout_seconds=180,
                    assertions_pass=assertions_pass, seconds=time.perf_counter()-start,
                    stdout_sha256=sha256(stdout).hexdigest(), stderr_sha256=sha256(stderr).hexdigest(),
                    command=command)
                if process_failure is not None:
                    row['failure'] = process_failure
                records.append(row)
                print(json.dumps(row), flush=True)
                if not passed:
                    failure = dict(case=case, status=row['status'], failure=process_failure)
                    break
    except Exception as error:
        failure = dict(status='ERROR', failure=repr(error))
    finally:
        source_finality = finality(module, bindings)
        passed = failure is None and len(records) == len(CASES) and all(
            row['status'] == 'PASS' for row in records) and source_finality['passed']
        report = dict(schema='plan13-c14.focused-heat-qualification.r2', status='PASS' if passed else 'FAIL',
            seconds=time.perf_counter()-began, cases=records, failure=failure, source_finality=source_finality,
            source_pins=bindings, selection_sha256=selection_pin, runtime_environment=runtime_environment,
            child_source=dict(path=str(module.__file__), sha256=ORIGINAL_SHA),
            composition_sha256=module.COMPOSITION_SHA, profile_sha256=module.PROFILE_SHA,
            derivation_sha256=module.DERIVATION_SHA, delta_sha256=module.DELTA_SHA,
            H3_enabled=False, candidate_only=True, retries=0,
            scientific_case_policy='Five frozen original --case entry points and assertions unchanged',
            excludes=['full workflow lineage/cold recovery', 'historical migration',
                      'native production acceptance', 'scientific acceptance', 'performance'])
        with (output / 'result.json').open('x', encoding='utf8', newline='\n') as stream:
            json.dump(report, stream, indent=2)
            stream.write('\n')
    return 0 if passed else 1


def load_selection(path, pin):
    selection = json.loads(checked(path, pin))
    require(selection['schema'] == 'plan13-c14.qualification-driver-selection.r2', 'Exact r2 selection required')
    for name, target, expected in (('original_child', ORIGINAL, ORIGINAL_SHA),
            ('derivation', DERIVATION, DERIVATION_SHA), ('composition', COMPOSITION, COMPOSITION_SHA)):
        require(selection[name] == dict(path=str(target), sha256=expected), 'Selected original identity differs: ' + name)
        checked(target, expected)
    driver = Path(__file__).resolve()
    require(selection['driver']['path'] == str(driver), 'Exact successor driver path required')
    checked(driver, selection['driver']['sha256'])
    require(selection['scientific_cases'] == list(CASES) and selection['run_authority'] == 'SEPARATE_EXPLICIT_GO_REQUIRED',
            'Frozen cases and separate run authority required')
    return selection


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--selection', type=Path, required=True)
    parser.add_argument('--selection-sha256', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    selection = load_selection(args.selection, args.selection_sha256)
    module = types.ModuleType('_frozen_C14_qualification_children')
    module.__file__ = str(ORIGINAL)
    exec(compile(checked(ORIGINAL, ORIGINAL_SHA), str(ORIGINAL), 'exec'), module.__dict__)
    runtime_environment = module.validate_runtime()
    module.configure(DERIVATION_SHA)
    require(module.COMPOSITION_SHA == COMPOSITION_SHA, 'Exact original composition required')
    bindings = {str(args.selection.resolve()): args.selection_sha256,
        str(Path(__file__).resolve()): selection['driver']['sha256'], str(ORIGINAL): ORIGINAL_SHA,
        str(DERIVATION): DERIVATION_SHA, str(COMPOSITION): COMPOSITION_SHA,
        str(module.PROFILE): module.PROFILE_SHA, str(HERE.parent / 'c14-r1/integration-map.json'): module.DELTA_SHA,
        str(T / 'ac/p13c14-run-r1/manifest.json'): module.DERIVED['manifest_sha256'],
        str(module.FIXTURE): module.FIXTURE_SHA, str(module.STORE_FIXTURE): module.STORE_FIXTURE_SHA}
    for name, pin in bindings.items():
        checked(Path(name), pin)
    return run_cases(module, args.output, bindings, runtime_environment, args.selection_sha256)


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception:
        traceback.print_exc()
        raise SystemExit(1)
