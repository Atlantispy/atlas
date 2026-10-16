"""G-PY transform vs the unchanged moving-face module: Decimal-representation identity and timing.

Usage: python -B -I test_gpy_transform.py <runtime root (final-f2)> <transformed file> [cases] [repeats]
The transformed file is loaded as a sibling module of the runtime package (its relative imports
resolve to the same integration_q2_directed). Jets come from q2_jets_gpy's fixture plus jets made
from the module's own operations (products, quotients, sums), so exponents vary as in use.
Compared: every endpoint's Decimal.as_tuple(), and the exception type, for mul and div.
"""
import importlib.util
import random
import sys
import time
from decimal import Decimal
from fractions import Fraction

ROOT, FILE = sys.argv[1], sys.argv[2]
CASES = int(sys.argv[3]) if len(sys.argv) > 3 else 300
REPEATS = int(sys.argv[4]) if len(sys.argv) > 4 else 5
sys.path.insert(0, ROOT)
from atlas_tectonics import integration_moving_face_moments as MF  # noqa: E402

spec = importlib.util.spec_from_file_location('atlas_tectonics._gpy_moving_face', FILE)
NEW = importlib.util.module_from_spec(spec)
spec.loader.exec_module(NEW)
assert NEW._Jets is not MF._Jets and hasattr(NEW, '_gpy_mul')
ORDER = MF.ORDER


def jet(J, rng):
    I = J.I

    def coefficient():
        r = rng.random()
        if r < 0.15:
            return J.zero
        if r < 0.2:
            return (Decimal('-0'), Decimal(0))
        q = Fraction(rng.randint(-10**9, 10**9), rng.randint(1, 10**6))*Fraction(10)**rng.randint(-20, 20)
        if r < 0.3:
            return I.point(Fraction(rng.randint(-50, 50), 2**rng.randint(0, 6)))
        if r < 0.38:
            return (Decimal(0), I.point(abs(q))[1])
        if r < 0.46:
            return (I.point(-abs(q))[0], Decimal('-0'))
        if r < 0.6:
            return (I.point(-abs(q))[0], I.point(abs(q)/3)[1])
        return I.point(q)
    return tuple(coefficient() for _ in range(ORDER+1))


def same(x, y):
    return len(x) == len(y) and all(p[0].as_tuple() == q[0].as_tuple() and p[1].as_tuple() == q[1].as_tuple()
                                    for p, q in zip(x, y, strict=True))


def outcome(fn, a, b):
    try:
        return fn(a, b), None
    except Exception as error:
        return None, type(error).__name__


def main():
    rng = random.Random(20261016)
    old, new = MF._Jets(), NEW._Jets()
    muls, divs = [], []
    for _ in range(CASES):
        a, b = jet(old, rng), jet(old, rng)
        muls.append((a, b))
        c = old.mul(a, b)
        muls.append((c, old.add(a, c)))
        lead = rng.choice((old.I.point(Fraction(rng.randint(1, 10**6), rng.randint(1, 999))),
                           (old.I.point(Fraction(-7, 3))[0], old.I.point(Fraction(-1, 9))[1]),
                           (Decimal(0), old.I.point(Fraction(1, 3))[1])))
        divs.append((c, (lead,)+b[1:]))
    report = {}
    for name, cases, f_old, f_new in (('mul', muls, old.mul, new.mul), ('div', divs, old.div, new.div)):
        bad = raises = 0
        for a, b in cases:
            x, y = outcome(f_old, a, b), outcome(f_new, a, b)
            raises += x[1] is not None
            if not (x[1] == y[1] and (x[0] is None) == (y[0] is None) and (x[0] is None or same(x[0], y[0]))):
                bad += 1
        timed = [c for c in cases if outcome(f_old, *c)[1] is None]
        times = {'original': [], 'gpy': []}
        for _ in range(REPEATS):
            for label, fn in (('original', f_old), ('gpy', f_new)):
                t = time.perf_counter()
                for a, b in timed:
                    fn(a, b)
                times[label].append(time.perf_counter()-t)
        best = {k: min(v) for k, v in times.items()}
        report[name] = dict(cases=len(cases), raises=raises, mismatches=bad,
                            best_s={k: round(v, 4) for k, v in best.items()},
                            speedup=round(best['original']/best['gpy'], 2),
                            spread={k: round(max(v)/min(v), 2) for k, v in times.items()})
    print(report)


main()
