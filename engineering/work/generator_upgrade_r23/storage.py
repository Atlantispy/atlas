"""Faster bounded canonical JSON, retaining the R12 authenticated store bodies.

The C encoder is used only after native strict validation and a conservative
UTF-8 byte bound proves the complete result fits the unchanged record limit.
Values outside that bound use the unchanged streaming native encoder. No
native module globals or predecessor code are changed.
"""

import json
from types import FunctionType

from work.generator_runtime_r12 import store as native


def _remaining(value, budget):
    """Subtract an upper bound without allocating any encoded fragments.

    Called only after native._check_json. A string code point needs at most six
    JSON UTF-8 bytes (a control escape); other valid Unicode needs at most four.
    An integer's decimal digits are bounded using 30103/100000 > log10(2), with
    room for zero and a minus sign. Finite binary64 JSON spelling fits 32 bytes.
    Returning a negative budget means fallback, not rejection of the value.
    """
    kind = type(value)
    if kind is str:
        return budget - 6 * len(value) - 2
    if kind is int:
        return budget - (value.bit_length() * 30103 // 100000 + 2)
    if kind is float:
        return budget - 32
    if value is None or kind is bool:
        return budget - 5
    budget -= 2 + max(0, len(value) - 1)
    if budget < 0:
        return -1
    if kind is dict:
        for key, item in value.items():
            budget -= 6 * len(key) + 3  # Key quotes and colon.
            if budget < 0:
                return -1
            budget = _remaining(item, budget)
            if budget < 0:
                return -1
    else:
        for item in value:
            budget = _remaining(item, budget)
            if budget < 0:
                return -1
    return budget


def _encode(value, limit=native.MAX_RECORD_BYTES):
    native._check_json(value)
    if _remaining(value, limit) < 0:
        return native._encode(value, limit)
    try:
        return json.dumps(value, ensure_ascii=False, allow_nan=False,
                          sort_keys=True, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, OverflowError, RecursionError) as exc:
        raise native.CacheError("Invalid JSON value") from exc


def _with_encoder(function):
    # Keep the native code objects and every authentication/path/lock helper;
    # only these two methods' private global dictionaries receive the encoder.
    result = FunctionType(function.__code__,
                          dict(function.__globals__, _encode=_encode),
                          function.__name__, function.__defaults__,
                          function.__closure__)
    result.__kwdefaults__ = function.__kwdefaults__
    result.__annotations__ = function.__annotations__
    result.__qualname__ = function.__qualname__
    return result


class Store(native.Store):
    """The native R12 store with a bounded canonical-encoding fast path."""

    _read = _with_encoder(native.Store._read)
    put = _with_encoder(native.Store.put)
