"""Replay captured W4 certification inputs: r1 vs compiled-batch arms, bitwise, timed.

Usage: python -B -I replay_w4.py <layout dir> <capture dir> <out json> [arms=v1,v2] [limit]
Reads only. Every payload runs r1 and each arm back to back in this process.
"""
import glob
import hashlib
import json
import os
import pickle
import sys
import time

LAYOUT, CAPTURE, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
ARMS = (sys.argv[4] if len(sys.argv) > 4 else 'v1,v2').split(',')
LIMIT = int(sys.argv[5]) if len(sys.argv) > 5 else 0
sys.path[:0] = [os.path.join(LAYOUT, 'runtime-src'), os.path.join(LAYOUT, 'helpers'),
                os.path.dirname(os.path.abspath(__file__))]

import gmpy2 as G  # noqa: E402
import private_heat_certification_kernel_r1 as K  # noqa: E402
import ck_solve as S  # noqa: E402

DOTS = {}
if 'v1' in ARMS:
    import ck_mpfr_dot as D1  # noqa: E402
    DOTS['v1'] = D1
if 'v2' in ARMS:
    import ck_mpfr_dot2 as D2  # noqa: E402
    DOTS['v2'] = D2


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
        value = fn(*args, **kw)
        error = None
    except Exception as exc:  # compared, never swallowed silently
        value, error = None, (type(exc).__name__, str(exc))
    return value, error, time.perf_counter()-t


files = sorted(glob.glob(os.path.join(CAPTURE, '*.pkl')),
               key=lambda p: (os.path.basename(p).split('-')[0], os.path.basename(p)))
if LIMIT:
    files = files[:LIMIT]
report = dict(kernel_sha256=hashlib.sha256(open(K.__file__, 'rb').read()).hexdigest(),
              files=len(files), solve=0, physical=0, mismatches=[], errors_r1=0,
              seconds={'r1': 0.0, **{arm: 0.0 for arm in DOTS}},
              precision_counts={}, shapes=[])
# Warm-up compile outside the timings.
with open(files[0], 'rb') as fh:
    warm = pickle.load(fh)
for arm, dots in DOTS.items():
    if warm[0] == 'solve':
        run(S.solve_enclosure, K, dots, warm[1], warm[2], precision=warm[3])
last_solve = {}
for path in files:
    with open(path, 'rb') as fh:
        payload = pickle.load(fh)
    pid = os.path.basename(path).split('-')[0]
    if payload[0] == 'solve':
        _, matrix, rhs, precision = payload
        report['solve'] += 1
        report['precision_counts'][precision] = report['precision_counts'].get(precision, 0)+1
        if len(report['shapes']) < 2000:
            report['shapes'].append((len(matrix), len(rhs), precision))
        ev_ref = {}
        ref, err, dt = run(K.solve_enclosure, matrix, rhs, precision=precision, evidence=ev_ref)
        report['seconds']['r1'] += dt
        report['errors_r1'] += err is not None
        last_solve[pid] = (ref, matrix)
        for arm, dots in DOTS.items():
            ev = {}
            got, gerr, dt = run(S.solve_enclosure, K, dots, matrix, rhs, precision=precision, evidence=ev)
            report['seconds'][arm] += dt
            ok = (err == gerr and ev == ev_ref and
                  (ref is None or (same(ref[0], got[0]) and same(ref[2], got[2]))))
            if not ok:
                report['mismatches'].append((arm, os.path.basename(path), err, gerr))
    else:
        _, matrix, keys, base_keys, signed_tau, conversion = payload
        report['physical'] += 1
        ref_solve = last_solve.get(pid)
        if not ref_solve or ref_solve[0] is None or ref_solve[1] is not matrix and ref_solve[1] != matrix:
            report['mismatches'].append(('pairing', os.path.basename(path), None, None))
            continue
        dual, ar = ref_solve[0][0], ref_solve[0][1]
        ref, err, dt = run(K.physical_bounds, matrix, dual, keys, base_keys, signed_tau, conversion, ar)
        report['seconds']['r1'] += dt
        for arm, dots in DOTS.items():
            got, gerr, dt = run(S.physical_bounds, K, dots, matrix, dual, keys, base_keys, signed_tau,
                                conversion, ar)
            report['seconds'][arm] += dt
            if not (err == gerr and (ref is None or same(ref, got))):
                report['mismatches'].append((arm, os.path.basename(path), err, gerr))
report['seconds'] = {k: round(v, 3) for k, v in report['seconds'].items()}
report['speedup'] = {arm: round(report['seconds']['r1']/report['seconds'][arm], 2) for arm in DOTS}
report['mismatch_count'] = len(report['mismatches'])
report['mismatches'] = report['mismatches'][:20]
shapes = report.pop('shapes')
report['shape_summary'] = dict(rows_max=max(s[0] for s in shapes), cols_max=max(s[1] for s in shapes),
                               rows_mean=round(sum(s[0] for s in shapes)/len(shapes), 1),
                               cols_mean=round(sum(s[1] for s in shapes)/len(shapes), 1)) if shapes else {}
with open(OUT, 'w', encoding='utf8') as fh:
    json.dump(report, fh, indent=1)
print(json.dumps({k: report[k] for k in ('files', 'solve', 'physical', 'errors_r1', 'mismatch_count',
                                        'seconds', 'speedup', 'precision_counts', 'shape_summary')}))
