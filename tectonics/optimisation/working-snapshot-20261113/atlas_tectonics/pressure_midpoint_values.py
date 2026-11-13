"""G1 receiving midpoint values; no runtime AST extraction or monkeypatching.

Custody is issued only by the selected pressure-wall batch worker around its
serial _compute on the freshly minted isolated root ledger. Arbitrary library
callers remain unsupported; queue exclusivity is not an ownership proof.
Copied arithmetic is bound to selected coupling 7c2c3b99 and overlap 96f3921c;
full identities and build-time provenance are recorded in this candidate's README.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from fractions import Fraction as Q
import math
import sys
import threading

from . import integration_volume_overlap as O
from .resources import WorkBudget

_ZERO, _ONE, _HALF, _THIRD, _QUARTER, _MINUS_QUARTER = Q(0), Q(1), Q(1, 2), Q(1, 3), Q(1, 4), Q(-1, 4)
_ZERO_PAIR = (_ZERO, _ZERO)
# Static zero derivative witnesses require no derivative arithmetic or owner.
_JET_ZERO = (_ZERO_PAIR, _ZERO_PAIR, _ZERO_PAIR)
_JET_ONE = ((_ONE, _ONE), _ZERO_PAIR, _ZERO_PAIR)
_JET_PRECISION = ContextVar('pressure_midpoint_value_precision', default=128)
_OWNER = ContextVar('pressure_midpoint_value_owner', default=None)
_REFUSAL = ContextVar('pressure_midpoint_refusal_class', default=None)
_SCRATCH_BYTES = 262144
_SCAFFOLD_BYTES = 8192


class UnknownConstant(Exception):
    """Private unsupported predicate; never a numerical success or refusal."""


class _Capacity(Exception):
    """Private retained-capacity miss, eligible for original fallback."""


class _Custody:
    """Private capability for the selected batch worker's serial compute epoch."""
    __slots__ = ('budget', 'thread', 'active')

    def __init__(self, budget):
        self.budget = budget
        self.thread = threading.get_ident()
        self.active = True


_CUSTODY = ContextVar('pressure_worker_custody', default=None)


def _isolated_root(budget):
    if (sys.implementation.name != 'cpython' or type(budget) is not WorkBudget
            or budget._parent is not None or budget._scope is not None
            or budget._revoker is not None):
        return False
    # Predicate units are a separate ledger, not RAM and not scratch funding.
    work = budget._predicate_work
    return work is None or (type(work) is WorkBudget and work._parent is None
        and work._scope is None and work._revoker is None)


def _eligible(budget, custody):
    return (type(custody) is _Custody and custody is _CUSTODY.get()
        and custody.active and custody.budget is budget
        and custody.thread == threading.get_ident() and _isolated_root(budget))


@contextmanager
def worker_custody(budget):
    """PW batch_worker _answer only: ledger is fresh, private and serially used.

    Structural checks cannot establish ownership for arbitrary callers. The
    sole production call site is part of this contract; this is not a public
    library opt-in. Nested issuance declines, retaining the outer epoch.
    """
    if _CUSTODY.get() is not None or not _isolated_root(budget):
        yield None
        return
    custody = _Custody(budget)
    token = _CUSTODY.set(custody)
    try:
        yield custody
    finally:
        custody.active = False
        custody.budget = None
        _CUSTODY.reset(token)


def current_custody(budget):
    custody = _CUSTODY.get()
    return custody if _eligible(budget, custody) else None


def _retained_size(value, depth=0):
    """Bound shallow immutable payload; aliases deliberately counted repeatedly."""
    if depth > 8:
        raise _Capacity('unsupported retained depth')
    if type(value) is Q:
        return sys.getsizeof(value)+sys.getsizeof(value.numerator)+sys.getsizeof(value.denominator)
    if type(value) in (int, bool) or value is None:
        return sys.getsizeof(value)
    if type(value) is str and len(value) <= 32:
        return sys.getsizeof(value)
    if type(value) is tuple and len(value) <= 8:
        return sys.getsizeof(value)+sum(_retained_size(v, depth+1) for v in value)
    raise _Capacity('unsupported retained representation')


class _Scratch:
    __slots__ = ('used', 'objects')

    def __init__(self):
        self.used = _SCAFFOLD_BYTES
        self.objects = []

    def make(self, cls, pair, constant, expression=None):
        # Header sizes include an extra 64 bytes per wrapper. Sixteen bytes per
        # registry slot plus the scaffold overbounds CPython list growth; payload
        # and aliases are counted cumulatively, with no reclaimed capacity credit.
        size = (_VALUE_HEADER if cls is Value else _RADIAL_HEADER)
        size += _retained_size(pair)+_retained_size(constant)+_retained_size(expression)+16
        if size > _SCRATCH_BYTES-self.used:
            raise _Capacity('midpoint retained scratch exhausted')
        self.used += size
        value = object.__new__(cls)
        # Register only an empty wrapper: an append allocation failure must not
        # strand an unregistered payload in the propagated traceback.
        value.value = value.constant = None
        if cls is ValueRadial:
            value.expression = None
        self.objects.append(value)
        value.value, value.constant = pair, constant
        if cls is ValueRadial:
            value.expression = expression
        return value

    def clear(self):
        # Clear payload even when a propagated exception retains evaluator frames.
        for value in self.objects:
            value.value = None
            value.constant = None
            if type(value) is ValueRadial:
                value.expression = None
        self.objects.clear()
        self.used = 0


class Value:
    __slots__ = ('value', 'constant')

    def __new__(cls, value, constant=None):
        flag = False if value[0] != value[1] else constant
        return _OWNER.get().make(cls, value, flag)

    def __init__(self, value, constant=None):
        pass

    def __getitem__(self, index):
        if index != 0:
            raise AssertionError('value path requested a derivative')
        return self.value


class ValueRadial(Value):
    __slots__ = ('expression',)

    def __new__(cls, jet, expression):
        return _OWNER.get().make(cls, jet[0], classify(jet, resolve=False), expression)

    def __init__(self, jet, expression):
        pass


_VALUE_HEADER = sys.getsizeof(object.__new__(Value))+64
_RADIAL_HEADER = sys.getsizeof(object.__new__(ValueRadial))+64
_RadialJet = ValueRadial


def classify(jet, resolve=True):
    if isinstance(jet, Value):
        flag = jet.constant
        if flag is None and resolve:
            raise UnknownConstant('singleton value has no derivative witness')
        return flag
    return jet[0][0] == jet[0][1] and jet[1] == (0, 0) and jet[2] == (0, 0)


def _refused(message):
    # The actual receiving C exception class is supplied by the attempt owner.
    return _REFUSAL.get()(message)


def _over(numerator, denominator):
    """Q(numerator, denominator); for two ints with denominator > 0, Fraction.__new__'s own
    gcd reduction without its dispatch. Anything else takes the constructor itself."""
    if type(numerator) is int and type(denominator) is int and (denominator > 0):
        g = math.gcd(numerator, denominator)
        return Q._from_coprime_ints(numerator // g, denominator // g)
    return Q(numerator, denominator)


def _dyadic_outward(pair, denominator):
    lo, hi = pair
    if type(lo) in (int, Q) and type(hi) in (int, Q):
        floor = lo.numerator * denominator // lo.denominator
        ceiling = -(-hi.numerator * denominator // hi.denominator)
        return (_over(floor, denominator), _over(ceiling, denominator))
    return (Q((lo * denominator).__floor__(), denominator), Q((hi * denominator).__ceil__(), denominator))


def _add(a, b):
    return (a[0] + b[0], a[1] + b[1])


def _mul(a, b):
    if type(a) is tuple and type(b) is tuple and (len(a) == len(b) == 2) and (type(a[0]) is Q) and (type(a[1]) is Q) and (type(b[0]) is Q) and (type(b[1]) is Q):
        lo, hi = a
        low, high = b
        if lo._numerator * hi._denominator <= lo._denominator * hi._numerator and low._numerator * high._denominator <= low._denominator * high._numerator:
            if lo._numerator >= 0:
                if low._numerator >= 0:
                    return (lo * low, hi * high)
                if high._numerator <= 0:
                    return (hi * low, lo * high)
                return (hi * low, hi * high)
            if hi._numerator <= 0:
                if low._numerator >= 0:
                    return (lo * high, hi * low)
                if high._numerator <= 0:
                    return (hi * high, lo * low)
                return (lo * high, lo * low)
            if low._numerator >= 0:
                return (lo * high, hi * high)
            if high._numerator <= 0:
                return (hi * low, lo * low)
            first, second = (lo * high, hi * low)
            third, fourth = (lo * low, hi * high)
            return (second if second._numerator * first._denominator < first._numerator * second._denominator else first, fourth if fourth._numerator * third._denominator > third._numerator * fourth._denominator else third)
    values = tuple((x * y for x in a for y in b))
    return (min(values), max(values))


def _scale(a, q):
    if type(q) is int and type(a) is tuple and all((type(x) is Q for x in a)):
        q = Q(q)
    values = tuple((x * q for x in a))
    if len(values) == 2 and type(values[0]) is Q and (type(values[1]) is Q):
        first, second = values
        return (second if second._numerator * first._denominator < first._numerator * second._denominator else first, second if second._numerator * first._denominator > first._numerator * second._denominator else first)
    return (min(values), max(values))


def _divide(q, interval):
    if interval[0] <= 0 <= interval[1]:
        raise _refused('interval division crosses zero')
    values = (q / interval[0], q / interval[1])
    return (min(values), max(values))


def _sqrt(q, bits=72):
    """Outward rational square-root bounds, with no floating predicate."""
    if q < 0:
        raise _refused('negative squared radius')
    exponent = (q.numerator.bit_length() - q.denominator.bit_length()) // 2 if q else 0
    denominator = 1 << max(0, bits - exponent)
    n = math.isqrt(q.numerator * denominator ** 2 // q.denominator)
    lo = Q(n, denominator)
    return (lo, lo if lo * lo == q else Q(n + 1, denominator))


def _minus(a, b):
    return tuple((x - y for x, y in zip(a, b)))


def _same_radial(a, b):
    if _jet_is_constant(a) and _jet_is_constant(b):
        return a[0][0] == b[0][0]
    return isinstance(a, _RadialJet) and isinstance(b, _RadialJet) and (a.expression == b.expression)


def _radial_interval_jets(s_jet, left, right, entry, exit_, bottom, top):

    def radial_edge(edge):
        if edge is None:
            return _JET_ZERO
        c, x, y = edge
        if c == 0:
            return _JET_ZERO
        values = (x + y * left, x + y * right)
        coefficient = ((min(values), max(values)), (y, y), _ZERO_PAIR)
        result = _jet_mul(s_jet, _jet_scale(_jet_reciprocal(coefficient), c))
        if isinstance(s_jet, _RadialJet):
            result = _RadialJet(result, ('radial-edge', s_jet.expression, x / c, y / c))
        return result
    lower_edge, upper_edge = (radial_edge(entry), radial_edge(exit_))
    fixed = True
    if lower_edge[0][1] <= bottom:
        lower = _jet_constant(bottom)
    elif lower_edge[0][0] >= bottom:
        lower = lower_edge
    else:
        lower = ((bottom, max(bottom, lower_edge[0][1])), _ZERO_PAIR, _ZERO_PAIR)
        fixed = False
    if upper_edge[0][0] >= top:
        upper = _jet_constant(top)
    elif upper_edge[0][1] <= top:
        upper = upper_edge
    else:
        upper = ((min(top, upper_edge[0][0]), top), _ZERO_PAIR, _ZERO_PAIR)
        fixed = False
    if _same_radial(lower, upper) or upper[0][1] <= lower[0][0]:
        return (lower, upper, True, False)
    if upper[0][0] < lower[0][1]:
        fixed = False
    return (lower, upper, fixed, True)


def _jet_power(a, exponent):
    if _jet_is_constant(a):
        return _jet_constant(a[0][0] ** exponent)
    result = _JET_ONE
    for _ in range(exponent):
        result = _jet_mul(result, a)
    return result


def _jet_extreme(a, b, *, maximum):
    if _same_radial(a, b):
        return (a, True)
    if a[0][0] >= b[0][1] if maximum else a[0][1] <= b[0][0]:
        return (a, True)
    if b[0][0] >= a[0][1] if maximum else b[0][1] <= a[0][0]:
        return (b, True)
    op = max if maximum else min
    return (((op(a[0][0], b[0][0]), op(a[0][1], b[0][1])), _ZERO_PAIR, _ZERO_PAIR), False)


def _positive_interval_primitive(lower, upper, primitive):
    """Integrate only an ordered radial interval; uncertain order includes0."""
    if _same_radial(lower, upper) or upper[0][1] <= lower[0][0]:
        return (_JET_ZERO, True)
    result = _jet_add(primitive(upper), _jet_scale(primitive(lower), -1))
    fixed = upper[0][0] >= lower[0][1]
    if not fixed:
        result = (_mul(result[0], (_ZERO, _ONE)), _ZERO_PAIR, _ZERO_PAIR)
    return (result, fixed)


def _donor_radial_pressure(receiver_low, receiver_high, donor_low, donor_high):
    """J=integral r^2*max(0,b-max(a,r)) dr, using true donor endpoints a,b."""
    below_high, first_fixed = _jet_extreme(receiver_high, donor_low, maximum=False)
    below, order_fixed = _positive_interval_primitive(receiver_low, below_high, lambda r: _jet_scale(_jet_power(r, 3), _THIRD))
    below = _jet_mul(below, _jet_add(donor_high, _jet_scale(donor_low, -1)))
    middle_low, low_fixed = _jet_extreme(receiver_low, donor_low, maximum=True)
    middle_high, high_fixed = _jet_extreme(receiver_high, donor_high, maximum=False)
    middle, mid_order_fixed = _positive_interval_primitive(middle_low, middle_high, lambda r: _jet_add(_jet_scale(_jet_mul(donor_high, _jet_power(r, 3)), _THIRD), _jet_scale(_jet_power(r, 4), _MINUS_QUARTER)))
    return (_jet_add(below, middle), all((first_fixed, order_fixed, low_fixed, high_fixed, mid_order_fixed)))


if not hasattr(Q, "_from_coprime_ints"):
    _over = Q


def _jet_constant(value):
    return Value((value, value), True)


def _jet_is_constant(a):
    result = classify(a)
    return result


def _is_zero(a):
    return a[0] == (0, 0) and classify(a)


def _rounded(pair):
    return Value(_dyadic_outward(pair, 1 << _JET_PRECISION.get()))


def _jet_add(a, b):
    if _is_zero(a):
        return b
    if _is_zero(b):
        return a
    if _jet_is_constant(a) and _jet_is_constant(b):
        return _jet_constant(a[0][0] + b[0][0])
    return _rounded(_add(a[0], b[0]))


def _jet_scale(a, q):
    if q == 0:
        return _JET_ZERO
    if q == 1:
        return a
    if _jet_is_constant(a):
        return _jet_constant(a[0][0] * q)
    return _rounded(_scale(a[0], q))


def _jet_mul(a, b):
    if _jet_is_constant(a):
        return _jet_scale(b, a[0][0])
    if _jet_is_constant(b):
        return _jet_scale(a, b[0][0])
    return _rounded(_mul(a[0], b[0]))


def _jet_reciprocal(a):
    if _jet_is_constant(a) and a[0][0] != 0:
        return _jet_constant(1 / a[0][0])
    return _rounded(_divide(_ONE, a[0]))


def _radial_chart_jets(a, b, normal, left, right, bits):
    direction = _minus(b, a)
    dd, ad = (O._dot(direction, direction), O._dot(a, direction))
    closest = max(left, min(right, -ad / dd)) if dd else left

    def radius2(t):
        point = tuple((x + t * y for x, y in zip(a, direction, strict=False)))
        return O._dot(point, point)
    square = (radius2(closest), max(radius2(left), radius2(right)))
    if square[0] <= 0:
        raise _refused('radial angular chart reaches the origin')
    s = (_sqrt(square[0], bits)[0], _sqrt(square[1], bits)[1])
    s_jet = ValueRadial(Value(s), ('sqrt-quadratic', O._dot(a, a), 2 * ad, dd))
    inverse = _jet_reciprocal(s_jet)
    factor = _jet_mul(_jet_mul(inverse, inverse), inverse)
    centre_moment, derivative_moment = (O._cross(normal, a), O._cross(normal, direction))
    result = []
    for x, y in zip(centre_moment, derivative_moment, strict=False):
        values = (x + y * left, x + y * right)
        linear = ((min(values), max(values)), (y, y), _ZERO_PAIR)
        result.append(_jet_mul(linear, factor))
    return (s_jet, tuple(result))


def _evaluate_pressure(left, right, data, bits, *, a, b, normal, profiles, rc, outer, gravity):
    edges, rows = data
    s, factors = _radial_chart_jets(a, b, normal, left, right, bits)
    low, high, fixed, possible = _radial_interval_jets(s, left, right, *edges, rc, outer)
    if not possible:
        return ((_JET_ZERO,) * 3, True)
    total = _JET_ZERO
    for bottom, top, rho, ptop, weight in profiles:
        x, y, selected, exists = _radial_interval_jets(s, left, right, *edges, bottom, top)
        if not exists:
            continue
        value, ordered = _positive_interval_primitive(x, y, lambda r: _jet_add(_jet_scale(_jet_power(r, 3), (ptop + gravity * rho * top) / 3), _jet_scale(_jet_power(r, 4), -gravity * rho / 4)))
        total = _jet_add(total, _jet_scale(value, weight))
        fixed &= selected and ordered
    for entry, exit_, bottom, top, coefficient in rows:
        x, y, selected, exists = _radial_interval_jets(s, left, right, entry, exit_, bottom, top)
        if not exists:
            continue
        value, ordered = _donor_radial_pressure(low, high, x, y)
        if not selected:
            value = (_mul(value[0], (_ZERO, _ONE)), _ZERO_PAIR, _ZERO_PAIR)
        total = _jet_add(total, _jet_scale(value, coefficient))
        fixed &= selected and ordered
    return (tuple((_jet_mul(factor, total) for factor in factors)), fixed)


def _run_attempt(left, right, data, bits, *, a, b, normal, profiles, rc, outer, gravity, refused, scratch):
    owner_token = _OWNER.set(scratch)
    precision_token = _JET_PRECISION.set(bits)
    refusal_token = _REFUSAL.set(refused)
    try:
        jets, fixed = _evaluate_pressure(left, right, data, bits, a=a, b=b, normal=normal,
                                        profiles=profiles, rc=rc, outer=outer, gravity=gravity)
        # Export only original value-result payloads, no tags, owner or wrapper.
        return True, (tuple(jet[0] for jet in jets), fixed)
    except (UnknownConstant, _Capacity):
        return False, None
    finally:
        scratch.clear()
        _REFUSAL.reset(refusal_token)
        _JET_PRECISION.reset(precision_token)
        _OWNER.reset(owner_token)


def attempt_pressure_midpoint(left, right, data, bits, *, a, b, normal, profiles, rc, outer, gravity,
                              refused, budget, custody=None):
    if left != right or not _eligible(budget, custody):
        return False, None
    # Optional shortfall is a miss, never a caught mandatory resource refusal.
    with budget.try_reserve(_SCRATCH_BYTES, category='pressure-midpoint-values') as admitted:
        if not admitted:
            return False, None
        scratch = _Scratch()
        return _run_attempt(left, right, data, bits, a=a, b=b, normal=normal, profiles=profiles,
                            rc=rc, outer=outer, gravity=gravity, refused=refused, scratch=scratch)
