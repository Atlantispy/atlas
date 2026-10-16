"""T/ps P3: the pressure interval/jet arithmetic without Fraction construction and dispatch overhead
(integration_pressure_coupling.py).

The small-case profile of the pressure stage spends 46% of its time in fractions.py.
That breaks down as 29.6M Fraction constructions and 48M ABC instance checks, the latter
from Fraction comparisons and from Fraction-by-int products. Each edit below performs
exactly the operation Fraction itself performs, on the same integers, so every value
and every type is unchanged:

1. Literal constants (Q(0), Q(1), Q(1, 2), Q(1, 3), Q(1, 4), Q(-1, 4), (Q(0), Q(0)), and
   the jets _jet_constant(Q(0)) and _jet_constant(Q(1))) are built once at import. Fractions
   and tuples are immutable, and nothing here tests them by identity. Mutable lists stay
   per call: only their immutable members are shared.
2. _dyadic_outward's exact floor/ceiling numerators over a positive power-of-two
   denominator become Fractions by the gcd reduction Fraction.__new__ applies
   (math.gcd, then Fraction._from_coprime_ints), without a second dispatch. Any other
   operand types or a non-positive denominator (never passed: both callers use 1 << k)
   take Fraction's constructor itself (r2, after the P3 refuter, 16 Oct).
3. _mul's fast path tests order and sign with Fraction's own comparisons:
   x <= y is x.n*y.d <= x.d*y.n, and x >= 0 is x.n >= 0 (denominators are positive).
   The mixed-sign min/max keep min()/max()'s choice of the first of two equals.
4. _scale multiplies by Fraction(q) when q is an int and every factor is a Fraction,
   which is what Fraction's operator does. min/max of two Fractions use the same
   integer comparison.
5. _jet_is_constant compares two Fractions by numerator and denominator, as
   Fraction.__eq__ does.
Record identity: numbers byte-identical; the module source digest (execution identity) changes (D-b).
"""
from hashlib import sha256

KNOWN_INPUT_SHA256 = {
    '91b5a6e18f3e730fa3655d1e5cae6d7eaf79a36404e7979e3e1414368bf72087': 'RC1 = composed-r2 = workers6-r6',
}
EDITS = (
    # 2. _dyadic_outward
    ('        return Q(floor, denominator), Q(ceiling, denominator)\n',
     '        return _over(floor, denominator), _over(ceiling, denominator)\n'),
    # 3. _mul
    ('            and type(b[0]) is Q and type(b[1]) is Q\n'
     '            and a[0] <= a[1] and b[0] <= b[1]):\n'
     '        lo, hi = a\n'
     '        low, high = b\n'
     '        if lo >= 0:\n'
     '            if low >= 0:\n'
     '                return lo*low, hi*high\n'
     '            if high <= 0:\n'
     '                return hi*low, lo*high\n'
     '            return hi*low, hi*high\n'
     '        if hi <= 0:\n'
     '            if low >= 0:\n'
     '                return lo*high, hi*low\n'
     '            if high <= 0:\n'
     '                return hi*high, lo*low\n'
     '            return lo*high, lo*low\n'
     '        if low >= 0:\n'
     '            return lo*high, hi*high\n'
     '        if high <= 0:\n'
     '            return hi*low, lo*low\n'
     '        return min(lo*high, hi*low), max(lo*low, hi*high)\n',
     '            and type(b[0]) is Q and type(b[1]) is Q):\n'
     '        lo, hi = a\n'
     '        low, high = b\n'
     '        # T/ps P3: Fraction\'s own integer comparisons without its dispatch:\n'
     '        # x <= y is x.n*y.d <= x.d*y.n and x >= 0 is x.n >= 0 (positive denominators).\n'
     '        if (lo._numerator*hi._denominator <= lo._denominator*hi._numerator\n'
     '                and low._numerator*high._denominator <= low._denominator*high._numerator):\n'
     '            if lo._numerator >= 0:\n'
     '                if low._numerator >= 0:\n'
     '                    return lo*low, hi*high\n'
     '                if high._numerator <= 0:\n'
     '                    return hi*low, lo*high\n'
     '                return hi*low, hi*high\n'
     '            if hi._numerator <= 0:\n'
     '                if low._numerator >= 0:\n'
     '                    return lo*high, hi*low\n'
     '                if high._numerator <= 0:\n'
     '                    return hi*high, lo*low\n'
     '                return lo*high, lo*low\n'
     '            if low._numerator >= 0:\n'
     '                return lo*high, hi*high\n'
     '            if high._numerator <= 0:\n'
     '                return hi*low, lo*low\n'
     '            first, second = lo*high, hi*low\n'
     '            third, fourth = lo*low, hi*high\n'
     '            # min() keeps the first unless the second is smaller; max() unless it is larger.\n'
     '            return (second if second._numerator*first._denominator < first._numerator*second._denominator else first,\n'
     '                    fourth if fourth._numerator*third._denominator > third._numerator*fourth._denominator else third)\n'),
    # 4. _scale
    ('def _scale(a, q):\n'
     '    values = tuple(x*q for x in a)\n'
     '    return min(values), max(values)\n',
     'def _scale(a, q):\n'
     '    if type(q) is int and type(a) is tuple and all(type(x) is Q for x in a):\n'
     '        # T/ps P3: a Fraction times an int is the Fraction times Fraction(q).\n'
     '        q = Q(q)\n'
     '    values = tuple(x*q for x in a)\n'
     '    if len(values) == 2 and type(values[0]) is Q and type(values[1]) is Q:\n'
     '        first, second = values\n'
     '        # min() and max() of two Fractions by Fraction\'s own integer comparison.\n'
     '        return (second if second._numerator*first._denominator < first._numerator*second._denominator else first,\n'
     '                second if second._numerator*first._denominator > first._numerator*second._denominator else first)\n'
     '    return min(values), max(values)\n'),
    # 5. _jet_is_constant
    ('def _jet_is_constant(a):\n'
     '    return a[0][0] == a[0][1] and a[1] == (0, 0) and a[2] == (0, 0)\n',
     'def _jet_is_constant(a):\n'
     '    x, y = a[0][0], a[0][1]\n'
     '    if type(x) is Q and type(y) is Q:\n'
     '        # T/ps P3: Fraction == Fraction compares numerators and denominators.\n'
     '        same = x._numerator == y._numerator and x._denominator == y._denominator\n'
     '    else:\n'
     '        same = x == y\n'
     '    return same and a[1] == (0, 0) and a[2] == (0, 0)\n'),
)
# 1. Literal constants, replaced in this order with these exact counts.
LITERALS = (
    ('_jet_constant(Q(0))', '_JET_ZERO', 9),
    ('_jet_constant(Q(1))', '_JET_ONE', 1),
    ('(Q(0), Q(0))', '_ZERO_PAIR', 26),
    ('Q(1, 2)', '_HALF', 4),
    ('Q(1, 3)', '_THIRD', 2),
    ('Q(1, 4)', '_QUARTER', 1),
    ('Q(-1, 4)', '_MINUS_QUARTER', 2),
    ('Q(1)', '_ONE', 7),
    ('Q(0)', '_ZERO', 20),
)
PRECISION = "_JET_PRECISION = ContextVar('radial_pressure_interval_precision', default=128)\n"
CONSTANTS = (
    PRECISION +
    '# T/ps P3: exact constants built once. Fractions and tuples are immutable, so\n'
    '# each use is the value its literal built before, without a construction.\n'
    '_ZERO, _ONE, _HALF, _THIRD, _QUARTER, _MINUS_QUARTER = Q(0), Q(1), Q(1, 2), Q(1, 3), Q(1, 4), Q(-1, 4)\n'
    '_ZERO_PAIR = (_ZERO, _ZERO)\n'
    '\n'
    '\n'
    'def _over(numerator, denominator):\n'
    '    """Q(numerator, denominator); for two ints with denominator > 0, Fraction.__new__\'s own\n'
    '    gcd reduction without its dispatch. Anything else takes the constructor itself."""\n'
    '    if type(numerator) is int and type(denominator) is int and denominator > 0:\n'
    '        g = math.gcd(numerator, denominator)\n'
    '        return Q._from_coprime_ints(numerator//g, denominator//g)\n'
    '    return Q(numerator, denominator)\n'
    '\n'
    '\n'
    'if not hasattr(Q, \'_from_coprime_ints\'):    # before Python 3.12: the plain constructor\n'
    '    _over = Q\n')
JET = ('def _jet_constant(value):\n'
       '    return (value, value), _ZERO_PAIR, _ZERO_PAIR\n')
JET_CONSTANTS = JET + '\n\n_JET_ZERO, _JET_ONE = _jet_constant(_ZERO), _jet_constant(_ONE)\n'


def transform(source, *, allow_unreviewed_input=False):
    if '_ZERO_PAIR' in source:
        raise ValueError('P3 coupling transform already applied')
    if not allow_unreviewed_input and sha256(source.encode()).hexdigest() not in KNOWN_INPUT_SHA256:
        raise ValueError('pressure coupling input is not the reviewed module')
    for old, new in EDITS:
        if source.count(old) != 1:
            raise ValueError('P3 anchor must occur exactly once: '+old.strip()[:60])
        source = source.replace(old, new)
    for old, new, count in LITERALS:
        if source.count(old) != count:
            raise ValueError('P3 literal %s occurs %d times, expected %d' % (old, source.count(old), count))
        source = source.replace(old, new)
    for old, new in ((PRECISION, CONSTANTS), (JET, JET_CONSTANTS)):
        if source.count(old) != 1:
            raise ValueError('P3 definition anchor must occur exactly once: '+old.strip()[:60])
        source = source.replace(old, new)
    if 'Q(0)' in source.replace(CONSTANTS, ''):
        raise ValueError('P3 left a literal behind')
    return source
