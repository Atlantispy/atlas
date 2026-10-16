"""Replay captured W4 certification inputs through several kernel files, bitwise, timed.

Usage: python -B -I replay_kernels.py <runtime-src> <out json> <capture dir> label=kernel.py ...
The first label is the reference. Each kernel file is loaded under its own module name with
its folder first on sys.path (so a kernel finds the helper beside it). Per payload, every
arm runs back to back: solve_enclosure, then physical_bounds on that arm's own dual/ar
when the capture holds the matching physical call. Compared: every returned mpfr
(value, zero sign, precision, rc, gmpy2.to_binary), proof dict, exception type and text,
and the evidence dict (phase) after the call.
"""
import glob
import hashlib
import importlib.util
import json
import os
import pickle
import sys
import time

RUNTIME, OUT, CAPTURE = sys.argv[1], sys.argv[2], sys.argv[3]
ARMS = [arg.split('=', 1) for arg in sys.argv[4:]]
sys.path.insert(0, RUNTIME)
import gmpy2 as G  # noqa: E402

kernels = {}
for label, path in ARMS:
    folder = os.path.dirname(os.path.abspath(path))
    sys.path.insert(0, folder)
    spec = importlib.util.spec_from_file_location('kernel_' + label, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # the folder stays on sys.path: a kernel imports its helpers lazily
    kernels[label] = module


def same(x, y):
    if type(x) is not type(y):
        return False
    if type(x) is G.mpfr:
        return (x.precision == y.precision and x.rc == y.rc and G.to_binary(x) == G.to_binary(y)
                and x.is_signed() == y.is_signed())
    if isinstance(x, (tuple, list)):
        return len(x) == len(y) and all(same(a, b) for a, b in zip(x, y))
    if isinstance(x, dict):
        return list(x) == list(y) and all(same(x[k], y[k]) for k in x)
    return x == y


def run(fn, *args, **kw):
    t = time.perf_counter()
    try:
        value, error = fn(*args, **kw), None
    except Exception as exc:
        value, error = None, (type(exc).__name__, str(exc))
    return value, error, time.perf_counter()-t


def outcome(kernel, payload, physical):
    """One arm on one solve payload (+ its physical call). Returns (record, seconds)."""
    _, matrix, rhs, precision = payload
    evidence = {}
    solved, error, seconds = run(kernel.solve_enclosure, matrix, rhs, precision=precision, evidence=evidence)
    record = dict(error=error, evidence=dict(evidence),
                  bounds=None if solved is None else solved[0], proof=None if solved is None else solved[2])
    if physical is not None and solved is not None:
        _, pmatrix, keys, base_keys, tau, conversion = physical
        bounds, perror, pseconds = run(kernel.physical_bounds, pmatrix, solved[0], keys, base_keys, tau,
                                       conversion, solved[1])
        seconds += pseconds
        record.update(physical=bounds, physical_error=perror, phase_after_physical=evidence.get('phase'))
    return record, seconds


files = sorted(glob.glob(os.path.join(CAPTURE, '*.pkl')))
by_pid = {}
for path in files:
    pid, number = os.path.basename(path)[:-4].split('-')
    by_pid.setdefault(pid, []).append(path)
pairs = []  # (solve payload path, following physical payload path or None)
for pid, paths in by_pid.items():
    paths.sort()
    for i, path in enumerate(paths):
        with open(path, 'rb') as fh:
            kind = pickle.load(fh)[0]
        if kind == 'solve':
            nxt = paths[i+1] if i+1 < len(paths) else None
            if nxt is not None:
                with open(nxt, 'rb') as fh:
                    if pickle.load(fh)[0] != 'physical':
                        nxt = None
            pairs.append((path, nxt))

labels = [label for label, _ in ARMS]
reference = labels[0]
report = dict(kernels={label: hashlib.sha256(open(path, 'rb').read()).hexdigest() for label, path in ARMS},
              solves=len(pairs), with_physical=sum(p is not None for _, p in pairs),
              seconds={label: 0.0 for label in labels}, mismatches={label: [] for label in labels[1:]},
              errors=0, precisions={})
# Warm-up (first-call compilation) outside the timings.
with open(pairs[0][0], 'rb') as fh:
    warm = pickle.load(fh)
for label in labels:
    outcome(kernels[label], warm, None)
for solve_path, physical_path in pairs:
    with open(solve_path, 'rb') as fh:
        payload = pickle.load(fh)
    physical = None
    if physical_path:
        with open(physical_path, 'rb') as fh:
            physical = pickle.load(fh)
    report['precisions'][payload[3]] = report['precisions'].get(payload[3], 0)+1
    records = {}
    for label in labels:
        records[label], seconds = outcome(kernels[label], payload, physical)
        report['seconds'][label] += seconds
    report['errors'] += records[reference]['error'] is not None
    for label in labels[1:]:
        if not same(records[reference], records[label]):
            report['mismatches'][label].append(os.path.basename(solve_path))
report['seconds'] = {k: round(v, 3) for k, v in report['seconds'].items()}
report['speedup_vs_reference'] = {k: round(report['seconds'][reference]/v, 2) for k, v in report['seconds'].items()}
report['mismatch_counts'] = {k: len(v) for k, v in report['mismatches'].items()}
for label in labels:
    status = getattr(kernels[label], 'h3_status', None)
    if status:
        report['h3_status_' + label] = status()
with open(OUT, 'w', encoding='utf8') as fh:
    json.dump(report, fh, indent=1, default=str)
print(json.dumps({k: report[k] for k in ('solves', 'with_physical', 'errors', 'precisions', 'seconds',
                                        'speedup_vs_reference', 'mismatch_counts')}))
