"""D1: contains() forms only the leading incidence coefficient read by the runtime.

Source transform of integration_moving_interface_moments.py. The original contains()
reads coefficient 0 of J.sub(J.mul(a[0],b[1]),J.mul(a[1],b[0])). The guarded helper
forms that coefficient with the same interval operations, operands and order,
including each add of zero, and otherwise evaluates the original expression.
The existing guards require exact T._Jets and T._Intervals classes, no convolution
budget, nonzero leading operands and nonzero leading products. The runtime's
contains() constructs its own unbudgeted algebra; no runtime module or selected
transform patches its algebra methods. No arena, work or budget charge is removed.

K1: this is not universal exception equivalence for arbitrary hand-built jets.
Coefficients 1..12 are skipped. A bad value or exceptional magnitude there can
make the original full expression raise Overflow or TypeError while this helper
returns coefficient 0. The reviewed runtime builds these coefficients through its
finite prec-80 Decimal interval operations within the stated magnitude domain.
The retained focused proof covers its declared runtime/corpus scope, not every
possible externally constructed coefficient or exception.

K2: exact-type guards reject subclasses but do not detect method replacements on
an exact-class instance or class. Such instrumentation may still take the fast
path; its call log must not be claimed equivalent to the original full loop.
The unchanged fallback is for inputs rejected by the actual guards, not for all
forms of instrumented algebra. See D1-D2-KNOWN.md for the retained refutation and
runtime-route evidence. The emitted HELPER and transform logic are unchanged.

Within the reviewed runtime scope, contains() returns the same boolean and the
records preserve numerical/representation/work-unit parity. Only this module's
source digest changes under the approved D-b translation. Source presence is not
q23/q24 acceptance. This r2 successor narrows documentation only; old transform
and frozen composition identities remain preserved.
"""
from hashlib import sha256

KNOWN_INPUT_SHA256 = {
    '23fb1565e2d1d11e9d29835ad99e4ca63a24af53843149f47dd01f8357906c9b':
        'RC1 composed-r1 runtime-src (no other transform touches this module)',
}
CALL_OLD = '                        determinant = J.sub(J.mul(a[0],b[1]),J.mul(a[1],b[0]))[0]\n'
CALL_NEW = '                        determinant = _incidence_constant(a, b, J)\n'
HELPER_ANCHOR = '\n\ndef _ray(ray, bounds, J, arena):\n'
HELPER = '''

def _incidence_constant(a, b, J):
    """Coefficient 0 of J.sub(J.mul(a[0],b[1]),J.mul(a[1],b[0])), the only one contains() reads.

    D1 (16 Oct 2026): for this module's own jets (T._Jets, no convolution budget, q2 intervals)
    with the four leading coefficients and both leading products nonzero, J.mul and J.sub take
    their elementwise routes, so coefficient 0 is these same interval operations on the same
    operands in the same order. Anything else evaluates the full expression.
    """
    if type(J) is T._Jets and J._convolution_budget is None and type(J.I) is T._Intervals:
        I, zero = J.I, J.zero
        p, q, r, s = a[0][0], b[1][0], a[1][0], b[0][0]
        if p != zero and q != zero and r != zero and s != zero:
            left = I.add(zero, I.mul(p, q))
            right = I.add(zero, I.mul(r, s))
            if left != zero and right != zero:
                return I.add(left, I.neg(right))
    return J.sub(J.mul(a[0],b[1]),J.mul(a[1],b[0]))[0]
'''


def transform(source, *, allow_unreviewed_input=False):
    if 'def _incidence_constant(' in source:
        raise ValueError('incidence constant transform already applied')
    if not allow_unreviewed_input and sha256(source.encode()).hexdigest() not in KNOWN_INPUT_SHA256:
        raise ValueError('moving-interface input is not the reviewed module; pass allow_unreviewed_input and re-run parity')
    if source.count(CALL_OLD) != 1:
        raise ValueError('incidence determinant anchor must occur exactly once')
    if source.count(HELPER_ANCHOR) != 1:
        raise ValueError('helper anchor (def _ray) must occur exactly once')
    return source.replace(CALL_OLD, CALL_NEW).replace(HELPER_ANCHOR, HELPER + HELPER_ANCHOR)
