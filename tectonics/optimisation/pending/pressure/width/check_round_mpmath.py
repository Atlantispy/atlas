"""Independent enclosure check of the rounded pose probe (T/ps/width, 16 Oct). Review env only (mpmath, SymPy).

Usage: <review-env python> check_round_mpmath.py PROBE_JSON

For n identical coaxial steps the true pose is closed-form, so no atlas code is used here:
  ray        R(phi) v by Rodrigues, phi = n*|omega|*duration, axis omega/|omega|
  quaternion (cos(n|h|), sin(n|h|) h/|h|), h = omega*duration/2
at 400 decimal digits. Checks, per row and level:
  ray:        |rounded - true|_2 <= its recorded error radius (Euclidean, so componentwise as well)
  quaternion: |rounded - true|_2 <= recorded error/4 (the unit-quaternion distance the code bounds)
and with SymPy the rounding lemma used in DESIGN.md: round-to-nearest on k <= 4 components moves a
vector by at most sqrt(k)/2 * q <= q in the 2-norm, and round_up(e+q, q) - e lies in [q, 2q).
Prints the slack (bound / actual) per check; exit 0 only if every check holds.
"""
import json
import sys

import mpmath as mp
import sympy as sp

mp.mp.dps = 400


def rational(text):
    num, den = text.split('/')
    return mp.mpf(int(num, 16))/mp.mpf(int(den, 16))


def lemma():
    q, k = sp.symbols('q k', positive=True)
    ok = all(sp.simplify(sp.sqrt(kk)/2*q - q) <= 0 for kk in (1, 2, 3, 4))
    e = sp.Rational(7, 3)
    for quantum in (sp.Rational(1, 2**10), sp.Rational(3, 7), sp.Integer(1)):
        raised = sp.ceiling((e+quantum)/quantum)*quantum
        ok = ok and quantum <= raised-e < 2*quantum
    return ok


def main():
    data = json.load(open(sys.argv[1], encoding='utf8'))
    omega = [rational(t) for t in data['omega']]
    duration = rational(data['duration'])
    ray = [rational(t) for t in data['ray']]
    speed = mp.sqrt(sum(w*w for w in omega))
    axis = [w/speed for w in omega]
    bad = []
    print('rounding lemma (SymPy):', lemma())
    if not lemma():
        bad.append('lemma')
    for row in data['rows']:
        n = row['steps']
        phi = n*speed*duration
        c, s = mp.cos(phi), mp.sin(phi)
        kv = sum(a*b for a, b in zip(axis, ray))
        cross = [axis[1]*ray[2]-axis[2]*ray[1], axis[2]*ray[0]-axis[0]*ray[2], axis[0]*ray[1]-axis[1]*ray[0]]
        true = [ray[j]*c+cross[j]*s+axis[j]*kv*(1-c) for j in range(3)]
        for level in (0, 24):
            got = [rational(t) for t in row['ray%d_rounded' % level]]
            radius = rational(row['ray%d_rounded_error_exact' % level])
            dist = mp.sqrt(sum((g-t)**2 for g, t in zip(got, true)))
            ok = dist <= radius
            print('n=%-5d ray level %-2d  dist %s  radius %s  slack %s  %s' % (
                n, level, mp.nstr(dist, 4), mp.nstr(radius, 4), mp.nstr(radius/dist, 4) if dist else 'inf',
                'OK' if ok else 'FAIL'))
            if not ok:
                bad.append((n, 'ray', level))
        half = [w*duration/2 for w in omega]
        hn = mp.sqrt(sum(h*h for h in half))
        qtrue = [mp.cos(n*hn)]+[mp.sin(n*hn)*h/hn for h in half]
        got = [rational(t) for t in row['quat_rounded']]
        radius = rational(row['quat_rounded_error_exact'])/4
        dist = mp.sqrt(sum((g-t)**2 for g, t in zip(got, qtrue)))
        ok = dist <= radius
        print('n=%-5d quaternion      dist %s  radius %s  slack %s  %s' % (
            n, mp.nstr(dist, 4), mp.nstr(radius, 4), mp.nstr(radius/dist, 4) if dist else 'inf',
            'OK' if ok else 'FAIL'))
        if not ok:
            bad.append((n, 'quaternion'))
    print('ENCLOSURE PASS' if not bad else 'ENCLOSURE FAIL %r' % bad)
    raise SystemExit(1 if bad else 0)


if __name__ == '__main__':
    main()
