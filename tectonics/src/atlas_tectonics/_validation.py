"""Shared binary64 input rules; no implicit units or physical defaults."""
from __future__ import annotations

import math
from numbers import Real
from typing import Any

import numpy as np
from numpy.typing import NDArray

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


def _reject_bools(value: Any) -> None:
    # np.asarray([True, 1.0]) would otherwise conceal the Boolean.
    if isinstance(value, (bool, np.bool_)):
        raise TectonicsError("Boolean values are not physical quantities")
    if isinstance(value, (list, tuple)):
        for item in value:
            _reject_bools(item)


def array(value: Any, name: str, *, ndim: int | None = None,
          nonnegative: bool = False) -> FloatArray:
    _reject_bools(value)
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


def frozen(value: Any) -> FloatArray:
    """Detached bytes-backed result: callers cannot re-enable write access."""
    data = np.asarray(value, dtype=np.float64, order="C")
    if not np.isfinite(data).all():
        raise TectonicsError("numerical result is outside finite binary64 range")
    return np.frombuffer(data.tobytes(order="C"), dtype=np.float64).reshape(data.shape)
