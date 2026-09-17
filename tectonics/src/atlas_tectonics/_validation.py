"""Shared binary64 input rules; no implicit units or physical defaults."""
from __future__ import annotations

import math
from numbers import Real
from typing import Any

import numpy as np
from numpy.typing import NDArray
from .resources import elements

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
