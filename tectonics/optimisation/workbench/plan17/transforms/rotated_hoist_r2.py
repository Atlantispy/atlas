"""D2: _rotated converts each accepted constant once, preserving interval arithmetic order.

Source transform of integration_moving_face_moments.py. The original Taylor loop
converts omega components twice per (k,j) and 1/k once per (k,j). The accepted
fast path converts three components once and each reciprocal once per order,
then makes the same interval mul/sub calls on the same values in the same order.
It accepts exact q2 _Intervals or this module's exact _RationalIntervals and an
exact 3-tuple of Fractions. Their unpatched point methods are pure functions of
a Fraction, returning immutable interval tuples. No arena, work or budget call
is removed; the preceding rotation-box work charges remain intact. Current
runtime routes do not read the Decimal context flags or patch algebra methods.

K2: exact-type checks reject subclasses/custom interval classes, but do not
detect patches on an exact-class instance or class. An instrumented exact-class
algebra may therefore still take the fast path and make fewer point calls.
Do not claim that every instrumented algebra takes the original loop or has an
identical conversion-call log. The unchanged original loop applies exactly when
the actual class/omega guards reject the input. See D1-D2-KNOWN.md for the
retained refutation and scope evidence; K1's skipped-coefficient exception limit
belongs to D1 and is not asserted as a new D2 behaviour.

The existing source anchors, NEW loop, fallback and transform logic are unchanged.
The reviewed runtime records preserve numerical/representation/work-unit parity;
only the moving-face source digest changes under the approved D-b translation.
D2 follows jets_convolution and precedes G-PY r4. Source presence and focused
proof are not q24 completion. This r2 successor changes module documentation
only; historical transform and frozen composition identities remain preserved.
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
