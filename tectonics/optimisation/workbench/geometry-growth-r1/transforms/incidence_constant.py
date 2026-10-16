"""D1 (q14 profile, coordinator-approved 16 Oct 2026): contains() forms only the coefficient it reads.

Source transform of atlas_tectonics/integration_moving_interface_moments.py. In evaluate()'s
contains(), the homogeneous-line incidence test reads only coefficient 0 of

    J.sub(J.mul(a[0],b[1]),J.mul(a[1],b[0]))

but computes two full 13-coefficient jet products (q14: 148 of 1,087 CPU-s, 13.6%). The new
module function _incidence_constant forms coefficient 0 alone when that is provably the same value,
and otherwise evaluates the original expression:

- Fast path only for this module's jets: type(J) is T._Jets, no convolution budget (so J.mul takes
  its plain route, never the budgeted exact one) and J.I a q2 _Intervals (Decimal contexts, no hooks).
  contains() always gets J = T._Jets(), which is exactly that.
- With the four leading coefficients a[0][0], b[1][0], a[1][0], b[0][0] all nonzero: J.mul's leading
  `== J.z` test cannot fire, and its coefficient 0 is I.add(zero, I.mul(x[0], y[0])) on every route
  (the generic generator, the jets_convolution loop). If both of those are nonzero, both products and
  the negated second product are jets other than J.z, so J.sub = J.add(P, J.neg(Q)) takes its
  elementwise route and its coefficient 0 is I.add(P0, I.neg(Q0)). The fast path runs those same
  interval operations on the same operands in the same order.
- Anything else (a zero leading coefficient, either product zero, another algebra) evaluates the
  original expression unchanged.

What is skipped: the 12 higher coefficients of each product and of the difference, which nothing
reads. They are pure Decimal context operations on finite operands. Nothing in these modules reads
context flags, and with prec 80 and Emax 999999 they cannot trap unless a coefficient exceeds 10^499999.
No arena, work or budget call happens inside J.mul, J.sub or the interval algebra, so work units,
reservations and the budget are unchanged (the enclosing evaluate() charges are untouched).
Record identity: contains() returns the same boolean, so every number is byte-identical. This
module's source digest (written into interface records) changes; coordinator D-b allows that.
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
