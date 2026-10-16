"""G-PY prototype: moving-face Decimal-80 jet product with per-coefficient interval classes.

Usage: python -B q2_jets_gpy.py <runtime root holding atlas_tectonics> [cases] [repeats]
Reference: integration_moving_face_moments._Jets.mul (fused route, plain _Jets, Decimal
_Intervals). Candidate: the SAME Decimal operations in the same order (point pairs, the
four-corner min/max for any zero endpoint, the sign-class corners, then lo.add/hi.add from
the zero start), but each coefficient's point flag and class are computed once per jet
instead of once per product, and _Intervals.mul/add are inlined. Any coefficient that is
not a 2-tuple of finite Decimals sends the whole product to the original route.
Identity: every endpoint's Decimal.as_tuple() (sign, digits, exponent). Timing: repeat
arms ABAB in one process (own fixture; no shared input).
"""
import random
import sys
import time
from decimal import Decimal
from fractions import Fraction

sys.path.insert(0, sys.argv[1])
from atlas_tectonics import integration_moving_face_moments as MF  # noqa: E402
from atlas_tectonics import integration_q2_directed as Q2  # noqa: E402

CASES = int(sys.argv[2]) if len(sys.argv) > 2 else 400
REPEATS = int(sys.argv[3]) if len(sys.argv) > 3 else 5
ORDER = MF.ORDER

# (low corner, high corner) per class pair; 3x3 is the two-candidate mixed case.
_CORNERS = {(1, 1): ((0, 0), (1, 1)), (1, 2): ((1, 0), (0, 1)), (1, 3): ((1, 0), (1, 1)),
            (2, 1): ((0, 1), (1, 0)), (2, 2): ((1, 1), (0, 0)), (2, 3): ((0, 1), (0, 0)),
            (3, 1): ((0, 1), (1, 1)), (3, 2): ((1, 0), (0, 0))}


def _classes(jet):
    """Per coefficient (live, point, class): class 0 = a zero endpoint, 1 > 0, 2 < 0, 3 mixed; None if not plain."""
    out = []
    zero = (Decimal(0), Decimal(0))
    for x in jet:
        if type(x) is not tuple or len(x) != 2 or type(x[0]) is not Decimal or type(x[1]) is not Decimal:
            return None
        x0, x1 = x
        if not (x0.is_finite() and x1.is_finite()):
            return None
        live = x != zero
        if x0.is_zero() or x1.is_zero():
            cls = 0
        elif x0 > 0:
            cls = 1
        elif x1 < 0:
            cls = 2
        else:
            cls = 3
        out.append((live, x0 == x1, cls))
    return out


def mul_classes(J, a, b):
    """J.mul(a, b) for a plain moving-face _Jets over plain Decimal _Intervals."""
    if a == J.z or b == J.z:
        return J.z
    if type(J) is not MF._Jets or type(J.I) is not Q2._Intervals or J.zero != (Decimal(0), Decimal(0)):
        return J.mul(a, b)
    ka, kb = _classes(a), _classes(b)
    if ka is None or kb is None or len(a) != ORDER+1 or len(b) != ORDER+1:
        return J.mul(a, b)
    lo, hi = J.I.lo, J.I.hi
    lm, hm, la, ha = lo.multiply, hi.multiply, lo.add, hi.add
    z0, z1 = J.zero
    result = []
    for k in range(ORDER+1):
        v0, v1 = z0, z1
        for i in range(k+1):
            x, y = a[i], b[k-i]
            live_x, point_x, cx = ka[i]
            live_y, point_y, cy = kb[k-i]
            if not (live_x and live_y):
                continue
            if point_x and point_y:
                p0 = lm(x[0], y[0])
                p1 = hm(x[0], y[0])
            elif cx == 0 or cy == 0:
                # builtin min/max over (x0y0, x0y1, x1y0, x1y1): all four products, then a
                # replacement only on a strict < (>), so the first of equal zeros is kept.
                x0, x1 = x
                y0, y1 = y
                p0 = lm(x0, y0)
                t = lm(x0, y1)
                if t < p0:
                    p0 = t
                t = lm(x1, y0)
                if t < p0:
                    p0 = t
                t = lm(x1, y1)
                if t < p0:
                    p0 = t
                p1 = hm(x0, y0)
                t = hm(x0, y1)
                if t > p1:
                    p1 = t
                t = hm(x1, y0)
                if t > p1:
                    p1 = t
                t = hm(x1, y1)
                if t > p1:
                    p1 = t
            elif cx == 3 and cy == 3:
                p0 = min(lm(x[0], y[1]), lm(x[1], y[0]))
                p1 = max(hm(x[0], y[0]), hm(x[1], y[1]))
            else:
                (li, lj), (hi_, hj) = _CORNERS[cx, cy]
                p0 = lm(x[li], y[lj])
                p1 = hm(x[hi_], y[hj])
            v0 = la(v0, p0)
            v1 = ha(v1, p1)
        result.append((v0, v1))
    return tuple(result)


def _class1(x, zero=(Decimal(0), Decimal(0))):
    if type(x) is not tuple or len(x) != 2 or type(x[0]) is not Decimal or type(x[1]) is not Decimal:
        return None
    x0, x1 = x
    if not (x0.is_finite() and x1.is_finite()):
        return None
    if x0.is_zero() or x1.is_zero():
        cls = 0
    elif x0 > 0:
        cls = 1
    elif x1 < 0:
        cls = 2
    else:
        cls = 3
    return (x != zero, x0 == x1, cls)


def _product(lm, hm, x, kx, y, ky):
    """_Intervals.mul(x, y) from precomputed (live, point, class)."""
    if kx[1] and ky[1]:
        return lm(x[0], y[0]), hm(x[0], y[0])
    cx, cy = kx[2], ky[2]
    if cx == 0 or cy == 0:
        x0, x1 = x
        y0, y1 = y
        p0 = lm(x0, y0)
        t = lm(x0, y1)
        if t < p0:
            p0 = t
        t = lm(x1, y0)
        if t < p0:
            p0 = t
        t = lm(x1, y1)
        if t < p0:
            p0 = t
        p1 = hm(x0, y0)
        t = hm(x0, y1)
        if t > p1:
            p1 = t
        t = hm(x1, y0)
        if t > p1:
            p1 = t
        t = hm(x1, y1)
        if t > p1:
            p1 = t
        return p0, p1
    if cx == 3 and cy == 3:
        return min(lm(x[0], y[1]), lm(x[1], y[0])), max(hm(x[0], y[0]), hm(x[1], y[1]))
    (li, lj), (hi_, hj) = _CORNERS[cx, cy]
    return lm(x[li], y[lj]), hm(x[hi_], y[hj])


def div_classes(J, a, b):
    """J.div(a, b): the same mul/add sequence per coefficient (no zero skipping), classes once each."""
    if type(J) is not MF._Jets or type(J.I) is not Q2._Intervals or J.zero != (Decimal(0), Decimal(0)):
        return J.div(a, b)
    kb = [_class1(y) for y in b]
    if None in kb or len(a) != ORDER+1 or len(b) != ORDER+1:
        return J.div(a, b)
    I = J.I
    lm, hm, la, ha = I.lo.multiply, I.hi.multiply, I.lo.add, I.hi.add
    z0, z1 = J.zero
    result, kr = [], []
    for k in range(ORDER+1):
        t0, t1 = z0, z1
        for i in range(1, k+1):
            p0, p1 = _product(lm, hm, b[i], kb[i], result[k-i], kr[k-i])
            t0 = la(t0, p0)
            t1 = ha(t1, p1)
        value = I.div(I.sub(a[k], (t0, t1)), b[0])
        known = _class1(value)
        if known is None:  # cannot happen for finite Decimal intervals; keep the original route
            return J.div(a, b)
        result.append(value)
        kr.append(known)
    return tuple(result)


def fixture(J, rng):
    I = J.I

    def coefficient():
        r = rng.random()
        if r < 0.15:
            return J.zero
        if r < 0.2:
            return (Decimal('-0'), Decimal(0))
        q = Fraction(rng.randint(-10**9, 10**9), rng.randint(1, 10**6))*Fraction(10)**rng.randint(-20, 20)
        if r < 0.3:
            return I.point(Fraction(rng.randint(-50, 50), 2**rng.randint(0, 6)))  # exact: a point
        if r < 0.38:
            return (Decimal(0), I.point(abs(q))[1])  # zero endpoint
        if r < 0.46:
            return (I.point(-abs(q))[0], Decimal('-0'))
        if r < 0.6:
            return (I.point(-abs(q))[0], I.point(abs(q)/3)[1])  # mixed
        return I.point(q)
    return tuple(coefficient() for _ in range(ORDER+1))


def same(x, y):
    return len(x) == len(y) and all(p[0].as_tuple() == q[0].as_tuple() and p[1].as_tuple() == q[1].as_tuple()
                                    for p, q in zip(x, y, strict=True))


def main():
    rng = random.Random(20261016)
    J = MF._Jets()
    pairs = []
    for _ in range(CASES):
        a, b = fixture(J, rng), fixture(J, rng)
        pairs.append((a, b))
        c = J.mul(a, b)  # products of products: varied exponents and lengths
        pairs.append((c, a))
    quotients = []
    for a, b in pairs[:len(pairs)//2]:
        lead = rng.choice((J.I.point(Fraction(rng.randint(1, 10**6), rng.randint(1, 999))),
                           (J.I.point(Fraction(-7, 3))[0], J.I.point(Fraction(-1, 9))[1]),
                           (Decimal(0), J.I.point(Fraction(1, 3))[1])))  # the last raises _Branch
        quotients.append((a, (lead,)+b[1:]))

    def outcome(fn, a, b):
        try:
            return fn(a, b), None
        except Exception as error:
            return None, type(error).__name__

    def agree(x, y):
        return x[1] == y[1] and (x[0] is None) == (y[0] is None) and (x[0] is None or same(x[0], y[0]))
    bad_mul = sum(not agree(outcome(J.mul, a, b), outcome(lambda p, q: mul_classes(J, p, q), a, b))
                  for a, b in pairs)
    bad_div = sum(not agree(outcome(J.div, a, b), outcome(lambda p, q: div_classes(J, p, q), a, b))
                  for a, b in quotients)
    branches = sum(outcome(J.div, a, b)[1] is not None for a, b in quotients)
    arms = {'mul': (pairs, J.mul, lambda a, b: mul_classes(J, a, b)),
            'div': ([q for q in quotients if outcome(J.div, *q)[1] is None], J.div, lambda a, b: div_classes(J, a, b))}
    report = dict(mul_products=len(pairs), mul_mismatches=bad_mul, div_cases=len(quotients),
                  div_branch_raises=branches, div_mismatches=bad_div)
    for name, (cases, reference, candidate) in arms.items():
        times = {'reference': [], 'candidate': []}
        for _ in range(REPEATS):
            for label, fn in (('reference', reference), ('candidate', candidate)):
                t = time.perf_counter()
                for a, b in cases:
                    fn(a, b)
                times[label].append(time.perf_counter()-t)
        best = {k: min(v) for k, v in times.items()}
        report[name] = dict(best_s={k: round(v, 4) for k, v in best.items()},
                            speedup=round(best['reference']/best['candidate'], 2),
                            spread={k: round(max(v)/min(v), 2) for k, v in times.items()})
    print(report)


main()
