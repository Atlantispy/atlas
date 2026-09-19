#!/usr/bin/env python3
"""Bounded R3 stress arithmetic evidence; no simulation or general benchmark.

SPDX-License-Identifier: AGPL-3.0-only
The optional --baseline is a complete source-only package for a before/after
comparison, never substituted for the selected target. Worker processes isolate
imports. Each full-call timing includes capture, checks and immutable outputs.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import time
import warnings

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True


def run_one(root):
    sys.path[:0] = [str(root/'src'), str(root)]
    from verify import source_inventory
    from atlas_tectonics import stress_and_dissipation
    from atlas_tectonics.resources import WorkBudget
    import atlas_tectonics
    if Path(atlas_tectonics.__file__).resolve() != root/'src/atlas_tectonics/__init__.py':
        raise ValueError('wrong package imported')
    before = source_inventory(root)
    cases = []
    for label, eta, rate in (
        ('reported-square-underflow', 1e100, 1e-170),
        ('square-overflow-finite-result', 1e-300, 1e200),
        ('twice-viscosity-overflow-finite-result', 1e308, 1e-300),
        ('ordinary-mantle-scale-control', 1e21, 1e-15),
        ('true-final-underflow', 1., 1e-300),
    ):
        with warnings.catch_warnings(record=True) as caught:
            try:
                r = stress_and_dissipation(eta, np.diag([rate, -rate]))
                data = {'stress': r['deviatoric_stress'].tolist(), 'heat': float(r['viscous_dissipation'])}
            except ValueError as exc:
                data = {'refused': type(exc).__name__, 'message': str(exc)}
        cases.append({'name': label, 'viscosity': eta, 'strain_diagonal': [rate, -rate],
                      'result': data, 'warnings': [str(w.message) for w in caught]})
    rate_axis = np.logspace(-180, -130, 201)
    tensor = rate_axis[:, None, None] * np.diag([1., -1.])
    curve = stress_and_dissipation(1e100, tensor)['viscous_dissipation']
    timings = []
    for n in (8192, 65536):
        tensor = np.linspace(.5e-15, 1.5e-15, n)[:, None, None] * np.array([[1., 2.], [2., -1.]])
        budget = WorkBudget(128<<20)
        calls = []; hashes = []
        for _ in range(6):
            start = time.perf_counter()
            r = stress_and_dissipation(1e21, tensor, budget=budget)
            calls.append(time.perf_counter() - start)
            hashes.append({k: hashlib.sha256(a.tobytes()).hexdigest() for k, a in r.items()})
        if any(h != hashes[0] for h in hashes):
            raise ValueError('repeated same-input results changed')
        if budget.reserved_bytes:
            raise ValueError('stress budget leaked')
        qref = 20.*1e21*np.linspace(.5e-15, 1.5e-15, n)**2
        error = float(np.max(np.abs(r['viscous_dissipation'] - qref)/qref))
        timings.append({'points': n, 'first_complete_seconds': calls[0], 'repeated_seconds': calls[1:],
                        'median_repeated_seconds': statistics.median(calls[1:]),
                        'analytic_relative_error': error, 'result_sha256': hashes[0],
                        'budget': budget.statistics()})
    after = source_inventory(root)
    if after != before:
        raise ValueError('source changed during measurements')
    return {'source_inventory': before, 'source_unchanged': True, 'cases': cases,
            'curve': {'viscosity': 1e100, 'rate': rate_axis.tolist(), 'dissipation': curve.tolist()},
            'timings': timings, 'runtime': {'python': platform.python_version(), 'numpy': np.__version__,
                                          'system': platform.system(), 'executable_is_symlink': Path(sys.executable).is_symlink()}}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--baseline', type=Path, help='optional complete, unchanged prior tectonics directory')
    p.add_argument('--worker', type=Path, help=argparse.SUPPRESS)
    args = p.parse_args()
    if args.worker is not None:
        print(json.dumps(run_one(args.worker.absolute()), allow_nan=False))
        return
    def child(root):
        run = subprocess.run([sys.executable, '-I', '-B', str(Path(__file__).absolute()), '--worker', str(root)],
                             capture_output=True, text=True, timeout=45)
        if run.returncode:
            raise ValueError(run.stderr)
        return json.loads(run.stdout)
    previous = child(args.baseline.absolute()) if args.baseline is not None else None
    current = child(ROOT)
    # Direct Decimal products validate the plotted log-range independently.
    sys.path[:0] = [str(ROOT/'tests'), str(ROOT/'src')]
    from test_stress_hardening_r3 import oracle
    expected = np.array([oracle(1e100, np.diag([r, -r]))[1] for r in current['curve']['rate']])
    observed = np.array(current['curve']['dissipation'])
    max_error = float(np.max(abs(observed-expected)/expected))
    if max_error > 8*np.finfo(float).eps or np.any(observed <= 0):
        raise ValueError('stress arithmetic curve disagrees with independent Decimal oracle')
    if not current['cases'][-1]['result'].get('refused'):
        raise ValueError('true final underflow was not refused')
    report = {'schema': 'atlas.r3-stress-hardening-evidence.v1',
              'status': 'PASS_BOUNDED_STRESS_ARITHMETIC',
              'scope': 'same local stress/heating equations; before/after regression probes and 8192/65536-point full-call timings',
              'previous': previous, 'current': current, 'curve_decimal_reference': expected.tolist(),
              'curve_max_relative_error': max_error,
              'claims': {'full_solver': False, 'physical_validation': False, 'universal_speedup': False,
                         'RSS_cap': False, 'R4_started': False, 'dependency_installation': False}}
    print(json.dumps(report, indent=2, allow_nan=False))


if __name__ == '__main__':
    main()
