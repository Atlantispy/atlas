"""Conservative binary64 filters; None always means use the exact operation.

No rounded coordinate leaves this module. Exact rational inputs remain the
authority. Each scalar is enclosed from its integer limbs, not by assuming
that float(Fraction/mpq) has any particular conversion rounding policy.
Requires IEEE binary64 and gradual underflow, checked before using a filter.
Temporary work is constant-sized; production callers own FILTER_BYTES before
entry and preserve that owner if an escaping traceback retains the work.
"""
from fractions import Fraction
import math
import struct
import sys

from atlas_tectonics import exact_arithmetic as _backend

_library = _backend.library()
_RATIONAL_TYPES = (int, Fraction) if _library is None else (
    int, Fraction, _library.mpq, _library.mpz)
_INTEGER_TYPES = (int,) if _library is None else (int, _library.mpz)
FILTER_BYTES = 32768
_INF = float('inf')
_TINY = math.ulp(0.0)
_BIG_SCALE = 2.0**1022
_SMALL_SCALE = 2.0**-52
_IEEE = (sys.float_info.radix == 2 and sys.float_info.mant_dig == 53
         and sys.float_info.max_exp == 1024 and _TINY > 0.0)


def _available():
    # Do not silently rely on a process changing FTZ/DAZ or the rounding mode.
    # The bounds themselves tolerate any IEEE rounding direction. Gradual
    # underflow is required; an unsupported environment simply uses exact GMP.
    # Compare a NORMAL result to detect denormal-input flushing, and inspect
    # the output bits to detect denormal-output flushing. Comparing two tiny
    # floats would itself silently compare two zeros with DAZ enabled.
    return (_IEEE and _TINY*_BIG_SCALE == _SMALL_SCALE
            and struct.pack('>d', sys.float_info.min*0.5) == b'\x00\x08\x00\x00\x00\x00\x00\x00')


def _scaled(value, exponent, direction):
    try:
        result = math.ldexp(value, exponent)
    except OverflowError:
        return None
    if not math.isfinite(result):
        return None
    result = math.nextafter(result, direction)
    return result if math.isfinite(result) else None


def ratio_bounds(numerator, denominator):
    """Enclose an exact integer ratio using at most 53 leading bits per limb.

    For shifts ns, ds, nh <= abs(n)/2**ns <= nh+1, and similarly
    dh <= d/2**ds <= dh+1. Endpoints are tight when no bits are shifted.
    Positive division is monotone. Pad division AND power-of-two scaling
    independently outwards; this also covers subnormal rounding/underflow.
    """
    if type(numerator) not in _INTEGER_TYPES or type(denominator) not in _INTEGER_TYPES:
        raise TypeError('exact integer numerator and denominator required')
    if denominator <= 0:
        raise ValueError('positive exact denominator required')
    if not _available():
        return None
    if numerator == 0:
        return (0.0, 0.0)
    negative = numerator < 0
    n = -numerator if negative else numerator
    if denominator == 1 and n.bit_length() <= 53:
        exact = float(numerator)
        return (exact, exact)
    ns = max(0, n.bit_length()-53)
    ds = max(0, denominator.bit_length()-53)
    nh = float(n >> ns)
    dh = float(denominator >> ds)
    # These additions are exact: heads are at most 2**53-1.
    nhigh = nh+1.0 if ns else nh
    dhigh = dh+1.0 if ds else dh
    low = math.nextafter(nh/dhigh, -_INF)
    high = math.nextafter(nhigh/dh, _INF)
    low = _scaled(low, ns-ds, -_INF)
    high = _scaled(high, ns-ds, _INF)
    if low is None or high is None:
        return None
    return (-high, -low) if negative else (low, high)


def rational_bounds(value):
    if type(value) not in _RATIONAL_TYPES:
        raise TypeError('exact int, Fraction or selected GMP rational required')
    return ratio_bounds(value.numerator, value.denominator)


def _add(a, b):
    low, high = a[0]+b[0], a[1]+b[1]
    if not math.isfinite(low) or not math.isfinite(high):
        return None
    low, high = math.nextafter(low, -_INF), math.nextafter(high, _INF)
    return (low, high) if math.isfinite(low) and math.isfinite(high) else None


def _sub(a, b):
    return _add(a, (-b[1], -b[0]))


def _mul(a, b):
    # Multiplication by a certified singleton has just two extrema.
    if b[0] == b[1]:
        scalar = b[0]
        if scalar == 0.0:
            return (0.0, 0.0)
        if scalar == 1.0:
            return a
        if scalar == -1.0:
            return (-a[1], -a[0])
        products = (a[0]*scalar, a[1]*scalar)
    else:
        products = (a[0]*b[0], a[0]*b[1], a[1]*b[0], a[1]*b[1])
    if not all(map(math.isfinite, products)):
        return None
    low = math.nextafter(min(products), -_INF)
    high = math.nextafter(max(products), _INF)
    return (low, high) if math.isfinite(low) and math.isfinite(high) else None


def _sign(value):
    if value is None:
        return None
    if value[0] > 0.0:
        return 1
    if value[1] < 0.0:
        return -1
    return None


def plane_bounds(coefficients):
    if len(coefficients) != 4:
        raise ValueError('four exact plane coefficients required')
    result = tuple(map(rational_bounds, coefficients))
    return None if any(value is None for value in result) else result


def plane_side_from_bounds(coefficients, point):
    if len(point) != 3:
        raise ValueError('three exact point coordinates required')
    if coefficients is None:
        return None
    total = (-coefficients[3][1], -coefficients[3][0])
    for coefficient, coordinate in zip(coefficients[:3], point, strict=True):
        bound = rational_bounds(coordinate)
        if bound is None:
            return None
        term = _mul(coefficient, bound)
        if term is None:
            return None
        total = _add(total, term)
        if total is None:
            return None
    return _sign(total)


def plane_side(coefficients, point):
    return plane_side_from_bounds(plane_bounds(coefficients), point)


def orientation2d(p, q, r):
    if any(len(point) != 2 for point in (p, q, r)):
        raise ValueError('three exact 2-D points required')
    values = tuple(rational_bounds(value) for point in (p, q, r) for value in point)
    if any(value is None for value in values):
        return None
    px, py, qx, qy, rx, ry = values
    ax, ay, bx, by = _sub(qx, px), _sub(qy, py), _sub(rx, px), _sub(ry, py)
    if any(value is None for value in (ax, ay, bx, by)):
        return None
    first, second = _mul(ax, by), _mul(ay, bx)
    if first is None or second is None:
        return None
    return _sign(_sub(first, second))
