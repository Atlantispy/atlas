"""Independent check of the pose width design r2 bounds (review environment: SymPy + mpmath only).

Usage: proof_quanta.py [BEFORE_JSON AFTER_JSON]
       (optional: the two per-runtime pose files written by route_parity.py; their exact errors are
       compared with the proven bound)

Nothing here imports the runtime or the transform modules. Every lemma is re-derived symbolically
(SymPy) or by exact rational arithmetic with this file's own helpers (a different floor_log2
algorithm from the transforms'), and every printed number is evaluated with mpmath at 50 digits.

  L1  round_up(x + q, q) - x lies in [q, 2q) for every rational x and q > 0          (both paths)
  L2  quanta: q = 2**(floor_log2(m) - G) satisfies 2**-(G+1) m < q <= 2**-G m          (both paths)
  L3  round to nearest moves an n-vector by <= sqrt(n)/2 q: n=3 (ray) <= q, n=4 (quaternion) = q
  L4  coaxial quaternion: products stay (w, s k); Q(w, s k)/|q|^2 is orthogonal and fixes k (and its
      transpose fixes k); rounding w to q and s to q_s = 2**(floor_log2 q - ceil_log2 |k|_1) moves
      the quaternion by <= q/sqrt(2)
  R1  ray radius: sum(delta_i + a_i) < (1 + 2**(1-G)) sum(delta_i), enclosure kept (move <= a_i)
  Q1  quaternion: e_k + 1 = (1+delta_k)(e_{k-1} + 1); by induction e~_k < (1 + 2**(1-G)) e_k, with the
      same delta_k (a segment's delta depends only on its rate, duration and goal)
  Q2  the placement check 4e <= operator_goal cannot flip for operator_goal <= 1/2
  P1  the share bound 2**(1-G) at G = 12 is < 0.049 %; a 1 % bar needs G >= 8
  C1  (c): total <= stored < total (1 + 2**-64), stored <= width
  D1  (optional) the real/synthetic pose errors: e_before <= e_after < (1 + 2**-11) e_before
"""
import json
import random
import sys
from fractions import Fraction as F

import mpmath
import sympy as sp

mpmath.mp.dps = 50
G = 12
DEV_BITS = 64
results = []


def record(name, ok, detail=''):
    results.append((name, bool(ok)))
    print('%-4s %-5s %s' % (name, 'PASS' if ok else 'FAIL', detail))


def floor_log2(x):
    """floor(log2 x) by repeated doubling/halving (independent of bit_length)."""
    x = F(x)
    assert x > 0
    k, p = 0, F(1)
    while p > x:
        k, p = k-1, p/2
    while p*2 <= x:
        k, p = k+1, p*2
    return k


def ceil_log2(x):
    k = floor_log2(x)
    return k if F(2)**k == F(x) else k+1


def round_up(x, q):
    return -((-x)//q)*q


def nearest(x, q):
    return round(x/q)*q


def rand_q(rng):
    num = rng.randint(1, 10**rng.randint(1, 40))
    den = rng.choice([rng.randint(1, 10**rng.randint(1, 40)), 2**rng.randint(0, 200)])
    return F(num, den)*rng.choice([1, -1])


def main():
    rng = random.Random(20261016)
    two = sp.Integer(2)

    # L1: symbolic: x = q*(n + f), n integer, 0 <= f < 1, so ceil((x+q)/q) = n + 1 + ceil(f) and
    # round_up(x+q, q) - x = q*(1 + ceil(f) - f): exactly q at f = 0; q*(2-f) for 0 < f < 1, whose
    # distances to the ends are q*(1-f) > 0 and q*f > 0.
    q, f, nn = sp.symbols('q f n', positive=True)
    added = sp.expand((nn+1+1)*q-q*(nn+f))
    ok = (sp.expand((nn+1+0)*q-q*nn) == q and sp.expand(added-q) == sp.expand(q*(1-f))
          and sp.expand(2*q-added) == sp.expand(q*f))
    bad = 0
    for _ in range(20000):
        x, qq = rand_q(rng), abs(rand_q(rng))
        a = round_up(x+qq, qq)-x
        bad += not (qq <= a < 2*qq)
    record('L1', ok and bad == 0,
           'round_up(x+q,q)-x in [q,2q): symbolic split f=0 / 0<f<1; 20,000 exact samples, %d bad' % bad)

    # L2: quanta bracket
    bad = 0
    for _ in range(20000):
        m = abs(rand_q(rng))
        qq = F(2)**(floor_log2(m)-G)
        bad += not (m/2**(G+1) < qq <= m/2**G)
    record('L2', bad == 0, '2^-(G+1) m < q <= 2^-G m on 20,000 exact samples, %d bad' % bad)

    # L3: componentwise move
    m3, m4 = sp.sqrt(3)/2, sp.sqrt(4)/2
    record('L3', m3 < 1 and m4 == 1, 'move <= sqrt(n)/2 q: n=3 %s q, n=4 %s q' % (mpmath.mpf(str(sp.N(m3, 30))), m4))

    # L4: coaxial algebra
    c1, c2, s1, s2, k1, k2, k3, w, s = sp.symbols('c1 c2 s1 s2 k1 k2 k3 w s', real=True)
    k = sp.Matrix([k1, k2, k3])

    def qmul(a, b):
        a0, av = a[0], sp.Matrix(a[1:])
        b0, bv = b[0], sp.Matrix(b[1:])
        return [a0*b0-av.dot(bv), *(a0*bv+b0*av+av.cross(bv))]

    prod = qmul([c1, *(s1*k)], [c2, *(s2*k)])
    want = [c1*c2-s1*s2*k.dot(k), *((c1*s2+c2*s1)*k)]
    product_ok = all(sp.expand(x-y) == 0 for x, y in zip(prod, want, strict=True))
    x_, y_, z_ = s*k1, s*k2, s*k3
    n2 = w**2+x_**2+y_**2+z_**2
    rot = sp.Matrix([[w**2+x_**2-y_**2-z_**2, 2*(x_*y_-w*z_), 2*(x_*z_+w*y_)],
                     [2*(x_*y_+w*z_), w**2-x_**2+y_**2-z_**2, 2*(y_*z_-w*x_)],
                     [2*(x_*z_-w*y_), 2*(y_*z_+w*x_), w**2-x_**2-y_**2+z_**2]])/n2
    fixes = sp.simplify(rot*k-k) == sp.zeros(3, 1) and sp.simplify(rot.T*k-k) == sp.zeros(3, 1)
    orth = sp.simplify(rot.T*rot-sp.eye(3)) == sp.zeros(3, 3)
    bad = 0
    for _ in range(5000):
        axis = [rand_q(rng) for _ in range(3)]
        if not any(axis):
            continue
        qq = F(2)**rng.randint(-120, 0)
        k1n = sum(map(abs, axis))
        qs = F(2)**(floor_log2(qq)-ceil_log2(k1n))
        ww, ss = rand_q(rng), rand_q(rng)
        dw, ds = nearest(ww, qq)-ww, nearest(ss, qs)-ss
        move2 = dw**2+ds**2*sum(a*a for a in axis)
        bad += not (qs*k1n <= qq and 2*move2 <= qq**2)
    record('L4', product_ok and fixes and orth and bad == 0,
           'coaxial product (w, s k) %s; Q(q)/|q|^2 fixes k and k^T %s; orthogonal %s; move <= q/sqrt2 on '
           '5,000 exact samples, %d bad' % (product_ok, fixes, orth, bad))

    # R1: ray radius
    c = two**(1-G)
    n = 8
    deltas = sp.symbols('d1:%d' % (n+1), positive=True)
    qs_ = sp.symbols('q1:%d' % (n+1), positive=True)
    radius_upper = sp.Add(*(d+2*qi for d, qi in zip(deltas, qs_, strict=True)))
    bound = sp.expand((1+c)*sp.Add(*deltas))
    slack = sp.expand(bound-radius_upper.subs({qi: d/two**G for qi, d in zip(qs_, deltas, strict=True)}))
    bad = 0
    for _ in range(2000):
        radius, total, ok_enclose = F(0), F(0), True
        for _ in range(rng.randint(1, 30)):
            d = abs(rand_q(rng)) or F(1)
            t = abs(rand_q(rng)) or F(1)
            qq = F(2)**(floor_log2(min(d, t))-G)
            move = qq*F(866026, 10**6)          # > sqrt(3)/2 q: a pessimistic rounding move
            before = radius+d
            radius = round_up(before+qq, qq)
            ok_enclose &= radius-before >= move
            total += d
        bad += not (ok_enclose and total <= radius < (1+F(2)**(1-G))*total)
    record('R1', slack == 0 and bad == 0,
           'sum(delta+a) < sum(delta+2q) <= (1+2^(1-G)) sum(delta) (symbolic, n=%d, equality at q=2^-G delta); '
           '2,000 exact radius chains, %d bad' % (n, bad))

    # Q1: quaternion recurrence and induction
    e0, d, cc = sp.symbols('e0 d c', nonnegative=True)
    closed = sp.expand(((1+d)*e0+d+1)-(1+d)*(e0+1)) == 0
    step = sp.expand((1+d)*(1+cc)*e0+d*(1+cc)-(1+cc)*((1+d)*e0+d)) == 0
    bad = 0
    for _ in range(2000):
        e_old, e_new, ok_chain = F(0), F(0), True
        for _ in range(rng.randint(1, 40)):
            dd = F(rng.randint(0, 10**6), 10**rng.randint(6, 30))
            e_old = (1+dd)*e_old+dd
            e_new = (1+dd)*e_new+dd
            if dd:
                qq = F(2)**(floor_log2(dd)-G)
                e_new = round_up(e_new+qq, qq)
            ok_chain &= e_old <= e_new <= (1+F(2)**(1-G))*e_old and (e_new < (1+F(2)**(1-G))*e_old or e_old == 0)
        bad += not ok_chain
    record('Q1', closed and step and bad == 0,
           'e_k+1 = (1+d)(e_{k-1}+1) %s; induction step identity %s; 2,000 exact chains (incl. delta=0 steps), '
           '%d bad' % (closed, step, bad))

    # Q2: placement check cannot flip (operator_goal g in (0, 1/2])
    x = sp.symbols('x', nonnegative=True)
    expbound = sp.diff(x*sp.exp(x)-(sp.exp(x)-1), x)          # = x e^x >= 0, and 0 at x = 0
    exp_ok = sp.simplify(expbound-x*sp.exp(x)) == 0
    g = mpmath.mpf(1)/2
    lhs = (1+mpmath.mpf(2)**(1-G))*mpmath.e**(g/8)            # 4e~ <= (1+c)(g/2)e^(g/8) < g  <=>  lhs < 2
    e_max = (1+mpmath.mpf(2)**(1-G))*(g/8)*mpmath.e**(g/8)
    record('Q2', exp_ok and lhs < 2 and e_max < 1,
           'e^x-1 <= x e^x (derivative x e^x) %s; (1+2^-11) e^(1/16) = %s < 2; e~ <= %s < 1'
           % (exp_ok, mpmath.nstr(lhs, 12), mpmath.nstr(e_max, 6)))

    # P1: precision numbers
    share = mpmath.mpf(2)**(1-G)
    need = next(gg for gg in range(1, 40) if mpmath.mpf(2)**(1-gg) <= mpmath.mpf(1)/100)
    record('P1', share*100 < mpmath.mpf('0.049') and need == 8,
           '2^(1-12) = %s %% (< 0.049 %%); 1 %% needs G >= %d (G=7 gives %s %%)'
           % (mpmath.nstr(share*100, 10), need, mpmath.nstr(mpmath.mpf(2)**-6*100, 6)))

    # C1: deviation storage
    bad = 0
    for _ in range(20000):
        total = abs(rand_q(rng))
        width = total*(1+F(rng.randint(0, 10**6), 10**rng.randint(6, 40)))
        quantum = F(2)**(floor_log2(total)-DEV_BITS)
        stored = min(round_up(total, quantum), width)
        bad += not (total <= stored <= width and stored-total < total/F(2)**DEV_BITS)
    record('C1', bad == 0, 'total <= stored <= width, stored-total < 2^-64 total = %s relative; 20,000 exact samples '
           '(incl. width at total), %d bad' % (mpmath.nstr(mpmath.mpf(2)**-64, 6), bad))

    # D1: the route-parity pose errors (exact)
    if len(sys.argv) == 3:
        before, after = (json.load(open(p, encoding='utf8'))['poses'] for p in sys.argv[1:3])
        worst, bad, count = F(0), 0, 0
        for key, row in before.items():
            ea = F(int(row['error'][0], 16), int(row['error'][1], 16))
            eb = F(int(after[key]['error'][0], 16), int(after[key]['error'][1], 16))
            if ea == 0:
                bad += eb != 0
                continue
            count += 1
            worst = max(worst, (eb-ea)/ea)
            bad += not (ea <= eb < (1+F(2)**(1-G))*ea)
        record('D1', bad == 0, '%d poses with an error: e_before <= e_after < (1+2^-11) e_before; worst added share '
               '%s %% (bound %s %%); zero-error poses stay 0; %d bad'
               % (count, mpmath.nstr(mpmath.mpf(worst.numerator)/worst.denominator*100, 6),
                  mpmath.nstr(share*100, 6), bad))
    failed = [name for name, ok in results if not ok]
    print('PROOF QUANTA %s (%d checks%s)' % ('PASS' if not failed else 'FAIL', len(results),
                                             ', failed %s' % failed if failed else ''))
    raise SystemExit(1 if failed else 0)


if __name__ == '__main__':
    main()
