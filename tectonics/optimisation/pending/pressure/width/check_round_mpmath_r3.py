"""Independent enclosure check of pose probe r3 (T/ps/width, 16 Oct). Review env only (mpmath, SymPy).

Usage: <review-env python> check_round_mpmath_r3.py PROBE_R3_JSON

No atlas code. For each case the true pose is composed step by step at 400 decimal digits:
  ray        v <- R(w_i, duration) v by Rodrigues, for i = 1..n (pattern cycled)
  quaternion Q <- (cos|h_i|, sin|h_i| h_i/|h_i|) * Q, h_i = w_i*duration/2 (the runtime's product order)
Checks, per row:
  ray (levels 0, 24)   |rounded - true|_2 <= its recorded radius
  sweep (levels 0, 24) the swept current step [0, duration] after n-1 priors: |mid - true(t)|_2 <= radius
                       at t = 0, d/4, d/2, 3d/4, d (necessary samples of the interval enclosure)
  quaternion           |rounded - true|_2 <= recorded error/4 (the unit-quaternion distance the code bounds)
  coaxial rows         the rounded quaternion's vector part is EXACTLY parallel to the first rate (Fractions)
  shares               the added share of the actual certified error is < 2**(1-guard) (the design's bound)
and with SymPy the rounding lemmas: round-to-nearest on k <= 4 components moves a vector by at most
sqrt(k)/2*q <= q; the coaxial (w, s*k) rounding with q_s*|k|_1 <= q moves it by at most q/sqrt(2) <= q;
round_up(e+q, q) - e lies in [q, 2q).
Exit 0 only if every check holds.
"""
import json
import sys
from fractions import Fraction

import mpmath as mp
import sympy as sp

mp.mp.dps = 400


def rational(text):
    num, den = text.split('/')
    return mp.mpf(int(num, 16))/mp.mpf(int(den, 16))


def exact(text):
    num, den = text.split('/')
    return Fraction(int(num, 16), int(den, 16))


def lemma():
    q = sp.symbols('q', positive=True)
    ok = all(sp.simplify(sp.sqrt(kk)/2*q - q) <= 0 for kk in (1, 2, 3, 4))
    ok = ok and sp.simplify(sp.sqrt((q/2)**2 + (q/2)**2) - q) < 0
    e = sp.Rational(7, 3)
    for quantum in (sp.Rational(1, 2**10), sp.Rational(3, 7), sp.Integer(1)):
        raised = sp.ceiling((e+quantum)/quantum)*quantum
        ok = ok and quantum <= raised-e < 2*quantum
    return bool(ok)


def rodrigues(v, w, t):
    speed = mp.sqrt(sum(x*x for x in w))
    if speed == 0:
        return list(v)
    k = [x/speed for x in w]
    c, s = mp.cos(speed*t), mp.sin(speed*t)
    kv = sum(a*b for a, b in zip(k, v))
    cross = [k[1]*v[2]-k[2]*v[1], k[2]*v[0]-k[0]*v[2], k[0]*v[1]-k[1]*v[0]]
    return [v[j]*c+cross[j]*s+k[j]*kv*(1-c) for j in range(3)]


def qmul(a, b):
    w, x, y, z = a
    v, p, q, r = b
    return [w*v-x*p-y*q-z*r, w*p+x*v+y*r-z*q, w*q-x*r+y*v+z*p, w*r+x*q-y*p+z*v]


def dist(a, b):
    return mp.sqrt(sum((x-y)**2 for x, y in zip(a, b)))


def main():
    data = json.load(open(sys.argv[1], encoding='utf8'))
    duration = rational(data['duration'])
    ray = [rational(t) for t in data['ray']]
    limits = dict(ray=mp.mpf(2)**(1-data['guard_ray']), quat=mp.mpf(2)**(1-data['guard_quat']))
    bad, worst = [], {}
    ok = lemma()
    print('rounding lemmas (SymPy):', ok)
    if not ok:
        bad.append('lemma')
    if data['failures'] or not data['delta_rule']:
        bad.append(('probe', data['failures'], data['delta_rule']))

    def check(label, distance, radius):
        good = distance <= radius
        slack = radius/distance if distance else mp.inf
        key = label.split()[0]
        if slack < worst.get(key, (mp.inf, ''))[0]:
            worst[key] = (slack, label)
        if not good:
            bad.append(label)
            print('FAIL', label, mp.nstr(distance, 5), mp.nstr(radius, 5))

    for case in data['cases']:
        pattern = [[rational(t) for t in w] for w in case['pattern']]
        first = [exact(t) for t in case['pattern'][0]]
        for row in case['rows']:
            n = row['steps']
            rates = [pattern[i % len(pattern)] for i in range(n)]
            before, vector, quaternion = None, list(ray), [mp.mpf(1), mp.mpf(0), mp.mpf(0), mp.mpf(0)]
            for w in rates:
                before = vector
                vector = rodrigues(vector, w, duration)
                h = [x*duration/2 for x in w]
                hn = mp.sqrt(sum(x*x for x in h))
                quaternion = qmul([mp.cos(hn)]+[mp.sin(hn)*x/hn for x in h], quaternion)
            tag = '%s n=%d' % (case['name'], n)
            for level in (0, 24):
                check('ray%d %s' % (level, tag), dist([rational(t) for t in row['ray%d' % level]], vector),
                      rational(row['ray%d_error_exact' % level]))
                mid = [rational(t) for t in row['sweep%d' % level]]
                radius = rational(row['sweep%d_error_exact' % level])
                for f in (0, 1, 2, 3, 4):
                    check('sweep%d %s t=%d/4' % (level, tag, f), dist(mid, rodrigues(before, rates[-1], duration*f/4)),
                          radius)
                share = row['ray%d_added_share' % level]
                if not share < limits['ray']*(1+mp.mpf(10)**-9):
                    bad.append(('ray share', level, tag, share))
            check('quat %s' % tag, dist([rational(t) for t in row['quat']], quaternion),
                  rational(row['quat_error_exact'])/4)
            if not row['quat_added_share'] < limits['quat']*(1+mp.mpf(10)**-9):
                bad.append(('quat share', tag, row['quat_added_share']))
            if case['kind'] == 'coaxial':
                vec = [exact(t) for t in row['quat'][1:]]
                cross = (vec[1]*first[2]-vec[2]*first[1], vec[2]*first[0]-vec[0]*first[2],
                         vec[0]*first[1]-vec[1]*first[0])
                if any(cross):
                    bad.append(('axis not exact', tag))
            print('%-12s ray0/24 share %.3g/%.3g  quat share %.3g  bits ray24 %d quat %d  axis %s  mutant axis %s' % (
                tag, row['ray0_added_share'], row['ray24_added_share'], row['quat_added_share'], row['ray24_bits'],
                row['quat_bits'], row['quat_axis_kept'], row['mutant_componentwise_axis_kept']), flush=True)
    print('smallest slack (bound/actual):', {k: (mp.nstr(v, 12), at) for k, (v, at) in worst.items()})
    print('ENCLOSURE PASS' if not bad else 'ENCLOSURE FAIL %r' % bad)
    raise SystemExit(1 if bad else 0)


if __name__ == '__main__':
    main()
