"""Identity + speed check: ck_mpfr_dot.pair_dots vs the real r1 Arithmetic.dot.

Read-only on the runtime: imports composed-r1 helpers by path (run with -B -I).
Usage: python -B -I test_dot_identity.py <composed-r1 dir> <cases> <seed>
"""
import json
import os
import random
import sys
import time

COMPOSED = sys.argv[1]
CASES = int(sys.argv[2])
SEED = int(sys.argv[3])
sys.path[:0] = [os.path.join(COMPOSED, 'runtime-src'), os.path.join(COMPOSED, 'helpers'),
                os.path.dirname(os.path.abspath(__file__))]

import gmpy2 as G  # noqa: E402
import private_heat_certification_kernel_r1 as K  # noqa: E402

t0 = time.perf_counter()
import ck_mpfr_dot as C  # noqa: E402
t_import = time.perf_counter()-t0

rng = random.Random(SEED)


def rand_q():
    kind = rng.random()
    if kind < 0.08:
        return G.mpq(0)
    num = rng.getrandbits(rng.randint(1, 160)) * rng.choice((-1, 1))
    den = rng.getrandbits(rng.randint(1, 120)) or 1
    return G.mpq(num, den)


def rand_interval(ar):
    kind = rng.random()
    if kind < 0.5:
        return ar.point(rand_q())  # thin (point) enclosure, as in solve_enclosure
    if kind < 0.6:
        x = ar.point(rand_q())
        return ar.sub(x, x)  # contains zero; RD of exact cancellation gives -0
    lo, hi = sorted((rand_q(), rand_q()))
    return ar.point(lo)[0], ar.point(hi)[1]


def same(x, y):
    return (type(x) is type(y) is G.mpfr and x.precision == y.precision and x.rc == y.rc
            and G.to_binary(x) == G.to_binary(y) and (x == y or (G.is_nan(x) and G.is_nan(y)))
            and x.is_signed() == y.is_signed())


report = dict(cases=0, dots=0, mismatches=0, unavailable=0, import_s=round(t_import, 3))
first_call = None
for case in range(CASES):
    precision = rng.choice(K.PRECISIONS)
    ar = K.Arithmetic(precision)
    nx, ny, length = rng.randint(1, 6), rng.randint(1, 6), rng.randint(1, 12)
    xs = [[rand_interval(ar) for _ in range(length)] for _ in range(nx)]
    ys = [[rand_interval(ar) for _ in range(length)] for _ in range(ny)]
    ref = [[ar.dot(x, y) for y in ys] for x in xs]
    t0 = time.perf_counter()
    try:
        got, _, _ = C.pair_dots(xs, ys, precision)
    except C.Unavailable:
        report['unavailable'] += 1
        continue
    if first_call is None:
        first_call = time.perf_counter()-t0
    report['cases'] += 1
    for rr, gr in zip(ref, got, strict=True):
        for r, g in zip(rr, gr, strict=True):
            report['dots'] += 1
            if not (same(r[0], g[0]) and same(r[1], g[1])):
                report['mismatches'] += 1
                if report['mismatches'] <= 3:
                    print('MISMATCH', precision, r, g, r[0].rc, g[0].rc, r[1].rc, g[1].rc)
report['first_call_incl_compile_s'] = round(first_call or 0, 3)

# Speed: Gram-shaped batch (n columns x L observations), the solve_enclosure shape.
speed = {}
for precision in (320, 640):
    for n, length in ((20, 40), (30, 60)):
        ar = K.Arithmetic(precision)
        m = [[ar.point(rand_q()) for _ in range(n)] for _ in range(length)]
        columns = list(zip(*m, strict=True))
        best_py = best_ck = float('inf')
        for _ in range(3):
            t0 = time.perf_counter()
            ref = [[ar.dot(x, y) for y in columns] for x in columns]
            best_py = min(best_py, time.perf_counter()-t0)
            t0 = time.perf_counter()
            got, _, _ = C.pair_dots(columns, columns, precision)
            best_ck = min(best_ck, time.perf_counter()-t0)
        ok = all(same(r[0], g[0]) and same(r[1], g[1])
                 for rr, gr in zip(ref, got) for r, g in zip(rr, gr))
        speed[f'p{precision}_n{n}_L{length}'] = dict(python_ms=round(1e3*best_py, 2), compiled_ms=round(1e3*best_ck, 2),
                                                     speedup=round(best_py/best_ck, 1), identical=ok)
report['gram_speed_best_of_3'] = speed
report['assembly_sha256'] = C.compiled_assembly_sha256()
print(json.dumps(report, indent=1))
