"""D2 (q14 profile, coordinator-approved 16 Oct 2026): _rotated converts each constant once.

Source transform of atlas_tectonics/integration_moving_face_moments.py. _rotated's Taylor loop
calls J.I.point(omega[...]) twice and J.I.point(Q(1, k)) once per (k, j): 9 conversions per order,
108 per call, for 3 distinct omega values and 12 distinct 1/k (q14: 8.6M conversions, 34 s, 3.1%).
The new loop converts the three omega components once and each 1/k once per k, then makes the same
mul/sub calls on the same values in the same order.

- Fast path only when J.I is exactly the q2 _Intervals or this module's _RationalIntervals and omega
  is a 3-tuple of Fractions. Both point() methods are pure functions of a Fraction: Q(q), then
  Decimal division in the instance's own contexts or nothing. Their results are immutable tuples
  of Decimals or Fractions, and mul/sub compare them only by value. Reusing one result is therefore
  the same as recomputing it, and with Fraction inputs no hoisted conversion can raise, so the
  exception order is unchanged too.
- Any other algebra (a subclass, a custom interval type, an instrumented one) or any other omega
  keeps the original loop, line for line.

No arena, work or budget call happens in the loop. G._rotation_boxes, before the loop, is untouched,
so its work charges are unchanged. Nothing reads the Decimal context flags.
Record identity: every jet is identical, so numbers are byte-identical. This module's source digest
(in wall temporal-integration records and, via the moving-interface digest, interface records)
changes; coordinator D-b allows that.
Stacks after jets_convolution (disjoint anchor). Exact kernels' G-PY is composed after this one.
"""
from hashlib import sha256

KNOWN_INPUT_SHA256 = {
    '42f2777f4f514b0c34036357aebc7a020aa431b46a43e7c23653897dcdd07dd3': 'RC1 composed-r1 runtime-src',
    'c5f2a1230f9e13633ad92f9a251ee01e08bac0b2905d9fed90c042402adb8075': 'RC1 + jets_convolution (cand-jets-r1)',
}
OLD = ('    columns = [[(J.I.point(lo)[0], J.I.point(hi)[1])] for lo, hi in posed]\n'
       '    for k in range(1, ORDER+1):\n'
       '        previous = [c[-1] for c in columns]\n'
       '        for j in range(3):\n'
       '            derivative = J.I.sub(J.I.mul(J.I.point(omega[(j+1) % 3]), previous[(j+2) % 3]),\n'
       '                                J.I.mul(J.I.point(omega[(j+2) % 3]), previous[(j+1) % 3]))\n'
       '            columns[j].append(J.I.mul(derivative, J.I.point(Q(1, k))))\n'
       '    return tuple(tuple(column) for column in columns)\n')
NEW = ('    columns = [[(J.I.point(lo)[0], J.I.point(hi)[1])] for lo, hi in posed]\n'
       '    if not ((type(J.I) is _Intervals or type(J.I) is _RationalIntervals)\n'
       '            and type(omega) is tuple and len(omega) == 3 and all(type(w) is Q for w in omega)):\n'
       '        for k in range(1, ORDER+1):\n'
       '            previous = [c[-1] for c in columns]\n'
       '            for j in range(3):\n'
       '                derivative = J.I.sub(J.I.mul(J.I.point(omega[(j+1) % 3]), previous[(j+2) % 3]),\n'
       '                                    J.I.mul(J.I.point(omega[(j+2) % 3]), previous[(j+1) % 3]))\n'
       '                columns[j].append(J.I.mul(derivative, J.I.point(Q(1, k))))\n'
       '        return tuple(tuple(column) for column in columns)\n'
       '    # D2 (16 Oct 2026): point() of these two algebras is a pure function of a Fraction,\n'
       '    # so each omega component and each 1/k is converted once; the same mul/sub calls follow.\n'
       '    point, mul, sub = J.I.point, J.I.mul, J.I.sub\n'
       '    rates = (point(omega[0]), point(omega[1]), point(omega[2]))\n'
       '    for k in range(1, ORDER+1):\n'
       '        previous = [c[-1] for c in columns]\n'
       '        inverse = point(Q(1, k))\n'
       '        for j in range(3):\n'
       '            derivative = sub(mul(rates[(j+1) % 3], previous[(j+2) % 3]),\n'
       '                             mul(rates[(j+2) % 3], previous[(j+1) % 3]))\n'
       '            columns[j].append(mul(derivative, inverse))\n'
       '    return tuple(tuple(column) for column in columns)\n')


def transform(source, *, allow_unreviewed_input=False):
    if 'rates = (point(omega[0]), point(omega[1]), point(omega[2]))' in source:
        raise ValueError('rotated hoist transform already applied')
    if not allow_unreviewed_input and sha256(source.encode()).hexdigest() not in KNOWN_INPUT_SHA256:
        raise ValueError('moving-face input is not a reviewed module; pass allow_unreviewed_input and re-run parity')
    if source.count(OLD) != 1:
        raise ValueError('_rotated loop anchor must occur exactly once')
    return source.replace(OLD, NEW)
