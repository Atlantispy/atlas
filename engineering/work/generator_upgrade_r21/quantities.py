"""Small explicit exact accounts; no rounding of conserved quantities."""
from fractions import Fraction as F
import math


def q(value, label='quantity', *, positive=False):
    if type(value) not in (str, int, float, F) or isinstance(value, bool):
        raise ValueError('explicit rational '+label+' required')
    try:
        result = F(value)
    except (ValueError, ZeroDivisionError, OverflowError) as exc:
        raise ValueError('finite rational '+label+' required') from exc
    if result < 0 or (positive and not result) or max(result.numerator.bit_length(), result.denominator.bit_length()) > 8192:
        raise ValueError('bounded nonnegative '+label+' required')
    return result


def exact(value, fields, label):
    if type(value) is not dict or set(value) != set(fields):
        raise ValueError('exact '+label+' fields required')


def ident(value, label='identity'):
    if type(value) is not str or not value.strip() or len(value) > 4096:
        raise ValueError('bounded nonblank '+label+' required')
    return value


def native(value, label='quantity'):
    exact_value = q(value, label)
    converted = float(exact_value)
    if not math.isfinite(converted) or F(converted) != exact_value:
        raise ValueError(label+' not exactly represented by native binary64; no rounding')
    return converted


def plain(value):
    if isinstance(value, F):
        return str(value)
    if isinstance(value, dict):
        return {key: plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(item) for item in value]
    return value
