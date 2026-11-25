"""Shared binary64 input rules; no implicit units or physical defaults."""
from __future__ import annotations

import math
import threading
from numbers import Real
from typing import Any

import numpy as np
from numpy.typing import NDArray
from .resources import check_event_or_callable, elements

FloatArray = NDArray[np.float64]


class TectonicsError(ValueError):
    """Unsupported input, numerical range or mathematical configuration."""


def scalar(value: Any, name: str, *, positive: bool = False,
           nonnegative: bool = False) -> float:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real):
        raise TectonicsError(f"{name}: a real number, not bool/string, is required")
    try:
        result = float(value)
    except (OverflowError, ValueError) as exc:
        raise TectonicsError(f"{name}: not representable in binary64") from exc
    if not math.isfinite(result):
        raise TectonicsError(f"{name}: finite value required")
    if (positive and result <= 0) or (nonnegative and result < 0):
        raise TectonicsError(f"{name}: invalid sign")
    return result


def text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TectonicsError(f"{name}: nonblank text required")
    return value


def input_shape(value: Any, name: str = "input", _depth: int = 0) -> tuple[int, ...]:
    """Inspect supported inputs before conversion. Unknown masks never become data."""
    if _depth > 32:
        raise TectonicsError(f"{name}: nested/cyclic input exceeds supported depth")
    if np.ma.isMaskedArray(value) or value is np.ma.masked:
        raise TectonicsError(f"{name}: masked arrays require an explicit missing-data policy")
    if isinstance(value, np.ndarray):
        if value.dtype.kind not in "iuf":
            raise TectonicsError(f"{name}: real numeric data required")
        return tuple(int(n) for n in value.shape)
    if isinstance(value, (list, tuple)):
        if not value:
            raise TectonicsError(f"{name}: nonempty data required")
        first = input_shape(value[0], name, _depth + 1)
        for index in range(1, len(value)):
            if input_shape(value[index], name, _depth + 1) != first:
                raise TectonicsError(f"{name}: rectangular data required")
        return (len(value),) + first
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real):
        raise TectonicsError(f"{name}: real numeric data, not bool/string, required")
    return ()


def array(value: Any, name: str, *, ndim: int | None = None,
          nonnegative: bool = False) -> FloatArray:
    shape = input_shape(value, name)
    if ndim is not None and len(shape) != ndim:
        raise TectonicsError(f"{name}: expected {ndim} dimensions")
    if elements(shape) == 0:
        raise TectonicsError(f"{name}: nonempty data required")
    try:
        raw = np.asarray(value)
        if raw.dtype.kind not in "iuf":
            raise TectonicsError(f"{name}: real numeric data required")
        result = np.array(raw, dtype=np.float64, order="C", copy=True)
    except (TypeError, ValueError, OverflowError) as exc:
        raise TectonicsError(f"{name}: rectangular binary64 data required") from exc
    if ndim is not None and result.ndim != ndim:
        raise TectonicsError(f"{name}: expected {ndim} dimensions")
    if result.size == 0 or not np.isfinite(result).all():
        raise TectonicsError(f"{name}: nonempty finite data required")
    if nonnegative and np.any(result < 0):
        raise TectonicsError(f"{name}: nonnegative data required")
    return result


def _immutable_view(value: Any, *, compact: bool = False) -> FloatArray | None:
    """Borrow only a C-contiguous binary64 view with an immutable bytes owner.

    A read-only flag, memoryview, mmap or array subclass is insufficient. A fresh
    descriptor prevents caller edits to shape/dtype from changing our descriptor.
    The bytes owner, held through the base chain, keeps payload lifetime safe.
    """
    if (type(value) is not np.ndarray or value.dtype != np.dtype(np.float64)
            or not value.flags.c_contiguous or not value.flags.aligned):
        return None
    view = value.view()
    owner = view
    while type(owner) is np.ndarray:
        if owner.flags.writeable:
            return None
        owner = owner.base
    if type(owner) is not bytes or (compact and len(owner) != view.nbytes):
        return None
    return view


def read_array(value: Any, name: str, *, ndim: int | None = None,
               nonnegative: bool = False) -> FloatArray:
    """Private read input: borrow proven immutable bytes, otherwise detach once.

    Do not write into the result. Newly detached backing is owned by this call;
    kernels never expose it. Reusing public writable/read-only aliases is forbidden.
    Validation is still performed on every call; this is not an identity cache.
    """
    result = _immutable_view(value)
    if result is None:
        result = array(value, name, ndim=ndim, nonnegative=nonnegative)
        result.setflags(write=False)
        return result
    if ndim is not None and result.ndim != ndim:
        raise TectonicsError(f"{name}: expected {ndim} dimensions")
    if result.size == 0 or not np.isfinite(result).all():
        raise TectonicsError(f"{name}: nonempty finite data required")
    if nonnegative and np.any(result < 0):
        raise TectonicsError(f"{name}: nonnegative data required")
    return result


def snapshot(value: Any, name: str, *, nonnegative: bool = False) -> FloatArray:
    """Immutable validated input for hashing AND calculation; no second kernel copy.

    The caller must not mutate mutable input during capture, just as during array
    conversion. Once captured, the original may be mutated without affecting us.
    """
    result = _immutable_view(value, compact=True)
    if result is None:
        shape = input_shape(value, name)
        if elements(shape) == 0:
            raise TectonicsError(f"{name}: nonempty data required")
        try:
            raw = np.asarray(value, dtype=np.float64, order="C")
            result = np.frombuffer(raw.tobytes(order="C"), dtype=np.float64).reshape(raw.shape)
        except (TypeError, ValueError, OverflowError) as exc:
            raise TectonicsError(f"{name}: rectangular binary64 data required") from exc
    return read_array(result, name, nonnegative=nonnegative)


def _check_owner_thread(self, cancel=None):
    if self._closed or threading.get_ident() != self._owner:
        raise TectonicsError(self._thread_refusal)
    check_event_or_callable(cancel, 'constitutive work cancelled')
    self._context.verify()


def _stored_array(self, key):
    for name, shape, raw in self._arrays:
        if name == key:
            return np.frombuffer(raw, dtype='f8').reshape(shape)
    raise TectonicsError(self._missing_array)


def _coded_refusal(self, message, code, detail=None):
    if code not in self._allowed_codes:
        raise ValueError(self._unknown_code % code)
    TectonicsError.__init__(self, message)
    self.code, self.detail = code, detail


_PLANAR_ROUNDOFF = float(128*np.finfo(float).eps)
_PLANAR_MAP_ERROR = 1e-10


def unit_rows(a, error, message, finite_first=False):
    scale = np.max(np.abs(a), axis=-1, keepdims=True)
    if finite_first:
        invalid = not np.isfinite(scale).all() or np.any(scale == 0)
    else:
        invalid = np.any(scale == 0) or not np.isfinite(scale).all()
    if invalid:
        raise error(message)
    scaled = a / scale
    return scaled / np.sqrt(np.sum(scaled * scaled, axis=-1, keepdims=True))


def finite_array(value, name, error, suffix):
    if not np.isfinite(value).all():
        raise error(name + suffix)
    return value


def shaped_finite_array(value, shape, label, prefix, suffix):
    data = np.asarray(value, dtype=np.float64)
    if data.shape != shape or not np.isfinite(data).all():
        raise TectonicsError(prefix + label + suffix if prefix else label + suffix)
    return data


def bounded_record(value, label, encode, error, limit=None, limit_suffix=None):
    try:
        raw = encode(value)
    except TectonicsError as exc:
        raise error(label + ': finite JSON data required') from exc
    if limit is not None and len(raw) > limit:
        raise error(label + limit_suffix)
    return raw


def within_budget(candidate, owner, message):
    node = candidate
    while node is not None:
        if node is owner:
            return
        node = node._parent
    raise TectonicsError(message)


def banded_solvers(message):
    try:
        from scipy.linalg import cholesky_banded, cho_solve_banded
    except ImportError as exc:
        raise TectonicsError(message) from exc
    return cholesky_banded, cho_solve_banded


def frozen_contiguous(array, dtype):
    data = np.ascontiguousarray(array, dtype=dtype)
    return np.frombuffer(data.tobytes(), dtype=dtype).reshape(data.shape)


def frozen_asarray(value, dtype=None):
    data = np.asarray(value, dtype=dtype)
    return np.frombuffer(data.tobytes(), dtype=data.dtype).reshape(data.shape)


def frozen_c_order(value, dtype):
    data = np.asarray(value, dtype=dtype, order='C')
    return np.frombuffer(data.tobytes(order='C'), dtype=dtype).reshape(data.shape)


def frozen(value: Any) -> FloatArray:
    """Detached bytes-backed result: callers cannot re-enable write access."""
    input_shape(value, "result")
    # A published small slice must not pin a much larger otherwise-unused owner.
    reusable = _immutable_view(value, compact=True)
    data = reusable if reusable is not None else np.asarray(value, dtype=np.float64, order="C")
    if not np.isfinite(data).all():
        raise TectonicsError("numerical result is outside finite binary64 range")
    if reusable is not None:
        return reusable
    return np.frombuffer(data.tobytes(order="C"), dtype=np.float64).reshape(data.shape)


# A-15 (form (i)): ids name the science, not the work done to reach it. An id-maker hashes its record without the paths
# listed for it at that maker; the stored record keeps every field, so ceilings, budgets and readers of the figures read
# what they read before. A path is a tuple of keys; '*' matches every key of a dict or every item of a list. A path
# absent from a record leaves it as it is, so a record that holds no listed count hashes the same bytes as before.


def effort_paths(*specs):
    """Dotted specs ('field_errors', 'segments.*.leaves') as key tuples."""
    return tuple(tuple(spec.split('.')) for spec in specs)


def without_effort(record, listed):
    """A copy of record without the listed paths; parts no path reaches are shared, never copied or changed."""
    for path in listed:
        record = _drop_effort(record, path)
    return record


def _drop_effort(node, path):
    head, rest = path[0], path[1:]
    if type(node) is dict:
        keys = tuple(node) if head == '*' else (head,) if head in node else ()
        if not keys:
            return node
        node = dict(node)
        for key in keys:
            if rest:
                node[key] = _drop_effort(node[key], rest)
            else:
                del node[key]
        return node
    if type(node) in (list, tuple) and head == '*' and rest:
        return [_drop_effort(item, rest) for item in node]
    return node


def _float_quanta(value):
    """Exact 2^-1074 units of an already-rounded finite binary64 operand."""
    numerator, denominator = float(value).as_integer_ratio()
    return numerator << (1074 - (denominator.bit_length() - 1))


def _quanta_float(total):
    """Round one exact dyadic sum, without converting its numerator first."""
    return total / (1 << 1074)


def _replay_fsum(factory):
    """Sum validated finite words; replay only after fsum prefix overflow.

    The factory must make a fresh iterator over the same immutable rounded
    operands. Construct products/quotients before calling, not inside it.
    Callers own bounded scalar scratch and translate final projection overflow.
    """
    values = factory()
    try:
        return math.fsum(values)
    except OverflowError:
        total = 0
        for value in factory():
            total += _float_quanta(value)
        return _quanta_float(total)


def _arithmetic_sub(self, a, b):
    return self.add(a, self.neg(b))
