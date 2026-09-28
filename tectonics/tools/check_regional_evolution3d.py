"""Bounded connected tests and matched preparation-reuse measurement.

SPDX-License-Identifier: AGPL-3.0-only
"""
from __future__ import annotations
import argparse
import hashlib
import io
import json
from pathlib import Path
import platform
import statistics
import sys
from time import perf_counter
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
sys.path.insert(0, str(ROOT/'tests'))
import numpy as np
import scipy
from test_regional_evolution3d import prepare, initial, advance


def bindings():
    names = ['tools/check_regional_evolution3d.py', 'docs/REGIONAL_EVOLUTION_3D.md',
        'tests/test_regional_evolution3d.py', 'tests/test_regional_transport3d.py',
        'tests/test_regional_heat3d.py']
    names += [p.relative_to(ROOT).as_posix() for p in sorted((ROOT/'src/atlas_tectonics').glob('*.py'))]
    return {n: hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in names}


def controls():
    stream = io.StringIO()
    suite = unittest.defaultTestLoader.loadTestsFromName('test_regional_evolution3d')
    begin = perf_counter()
    outcome = unittest.TextTestRunner(stream=stream, verbosity=0).run(suite)
    tests = dict(count=outcome.testsRun, errors=len(outcome.errors),
        failures=len(outcome.failures), skips=len(outcome.skipped),
        elapsed_seconds=perf_counter()-begin,
        failed_tests=[str(t) for t, _ in outcome.errors+outcome.failures])
    if not outcome.wasSuccessful() or outcome.skipped:
        return dict(passed=False, joined_tests=tests)
    samples = dict(rebuild=[], prepared=[])
    checks = dict(bitwise_output_parity=True)
    with prepare(cells=(3, 3, 3)) as warm:
        base = initial(warm)
        reference = advance(warm, base)
        for i in range(3):
            for mode in (('rebuild', 'prepared') if i % 2 == 0 else ('prepared', 'rebuild')):
                begin = perf_counter()
                if mode == 'rebuild':
                    with prepare(cells=(3, 3, 3)) as cold:
                        result = advance(cold, initial(cold))
                else:
                    result = advance(warm, initial(warm))
                samples[mode].append(perf_counter()-begin)
                checks['bitwise_output_parity'] &= all(np.array_equal(reference.state.array(k),
                    result.state.array(k)) for k in reference.state.array_names)
                checks['bitwise_output_parity'] &= all(np.array_equal(reference.mechanics.array(k),
                    result.mechanics.array(k)) for k in reference.mechanics.array_names)
        stats = warm.statistics()
        identity = warm.descriptor()['execution']
        checks['one_mechanical_preparation'] = stats['mechanical_preparations'] == 1
        checks['one_heat_factor'] = stats['heat']['factorizations'] == 1
        checks['one_transport_factor'] = stats['transport']['factorizations'] == 1
    med = {k: statistics.median(v) for k, v in samples.items()}
    return dict(passed=all(checks.values()), joined_tests=tests, checks=checks,
        benchmark=dict(cells=[3, 3, 3], samples_seconds=samples, median_seconds=med,
            saved_seconds=med['rebuild']-med['prepared'], saved_percent=100*(1-med['prepared']/med['rebuild']),
            scope='3x3x3 quiescent connected fixture; imports excluded; three interleaved samples; not world runtime',
            prepared_statistics=stats), execution_identity=identity)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    with args.output.open('x', encoding='utf-8', newline='\n') as target:
        begin = perf_counter()
        report = dict(schema='atlas.regional-evolution3d-controls.v1', status='INCOMPLETE',
            scientific_acceptance=False, whole_planet_acceptance=False,
            runtime=dict(python=platform.python_version(), system=platform.system(),
                         numpy=np.__version__, scipy=scipy.__version__))
        try:
            report['source_sha256'] = bindings()
            report.update(controls())
            report['source_unchanged'] = report['source_sha256'] == bindings()
            report['status'] = 'PASS_BOUNDED_CONTROLS_ONLY' if report['passed'] and report['source_unchanged'] else 'FAIL'
        except Exception as exc:
            report.update(status='FAIL', error_type=type(exc).__name__)
        report['elapsed_seconds'] = perf_counter()-begin
        json.dump(report, target, indent=2, allow_nan=False); target.write('\n')
    print(json.dumps({k: report[k] for k in ('status', 'elapsed_seconds')}))
    return 0 if report['status'] == 'PASS_BOUNDED_CONTROLS_ONLY' else 1


if __name__ == '__main__':
    raise SystemExit(main())
