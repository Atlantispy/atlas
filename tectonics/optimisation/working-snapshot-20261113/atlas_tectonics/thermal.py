"""E04 half-space cooling; bounded broadcast work, not an evolving thermal PDE."""
from __future__ import annotations

import math
from typing import Any

import numpy as np

from ._validation import FloatArray, TectonicsError, read_array as array, frozen, input_shape
from .parameters import ThermalParameters
from .resources import elements, select_budget


# Execution granularity, not a physical length, timestep or accuracy control.
DEFAULT_COOLING_BATCH_ELEMENTS = 8_192


def _batch_count(value: int) -> int:
    if type(value) is not int or value <= 0:
        raise TectonicsError("batch_elements must be a positive integer")
    return value


def cooling_work_bytes(depth_shape, age_shape, batch_elements=DEFAULT_COOLING_BATCH_ELEMENTS):
    """Conservative array-work estimate; caller-held/native allocations are separate."""
    size = _batch_count(batch_elements)
    shape = np.broadcast_shapes(depth_shape, age_shape)
    total = elements(shape)
    if not total:
        raise TectonicsError("cooling inputs must be nonempty")
    # Input conversion, age-length field, output and immutable publication; bounded
    # iterator/filter buffers. This intentionally does not assume zero-copy inputs.
    return (24 * (elements(depth_shape) + elements(age_shape))
            + 24 * total + 48 * min(total, size) + 8192)


def half_space_temperature(depth_m: Any, age_s: Any,
                           parameters: ThermalParameters, *, backend: str = "scipy",
                           budget=None, batch_elements: int = DEFAULT_COOLING_BATCH_ELEMENTS) -> FloatArray:
    """T=Ts+(Tm-Ts)*erf(z/(2*sqrt(kappa*t))); depth is positive downwards.

    SciPy bulk erf is the default; backend="reference" explicitly uses math.erf.
    Age-dependent lengths are evaluated before broadcasting, once per supplied age,
    rather than once per output sample. Remaining independent arithmetic is batched.
    The returned full array still needs admission; batching does not shrink output.
    batch_elements changes execution granularity, never sampling or physical time.
    No worker pool, approximate erf or automatic dependency fallback is used.
    """
    if not isinstance(parameters, ThermalParameters):
        raise TectonicsError("explicit ThermalParameters required")
    if backend not in ("reference", "scipy"):
        raise TectonicsError("backend must be reference or scipy; no automatic fallback")
    batch_elements = _batch_count(batch_elements)
    ds, ts = input_shape(depth_m, "depth_m"), input_shape(age_s, "age_s")
    try:
        shape = np.broadcast_shapes(ds, ts)
        required = cooling_work_bytes(ds, ts, batch_elements)
    except ValueError as exc:
        raise TectonicsError("depth and age cannot be broadcast or are empty") from exc
    with select_budget(budget).reserve(required):
        # Refuse absent selected dependencies before preparing bulk data.
        if backend == "scipy":
            try:
                from scipy.special import erf as bulk_erf
            except ImportError as exc:
                raise TectonicsError("scipy backend unavailable; install the declared requirements or explicitly select backend='reference'") from exc
        depth = array(depth_m, "depth_m", nonnegative=True)
        age = array(age_s, "age_s", nonnegative=True)
        if depth.shape != ds or age.shape != ts:
            raise TectonicsError("input shape changed during capture")
        with np.errstate(over="ignore", under="ignore", divide="ignore", invalid="ignore"):
            length = np.sqrt(age)
            length *= 2 * math.sqrt(parameters.diffusivity_m2_s)
        positive = age > 0
        if np.any(~np.isfinite(length)) or np.any(positive & (length <= 0)):
            raise TectonicsError("thermal diffusion length outside numerical range")
        del positive, age
        output = np.empty(shape, dtype=np.float64)
        # Buffered C-order iteration preserves broadcasting/strides without making
        # a repeated full-sized depth or length array. Each chunk is independent.
        with np.nditer([depth, length, output], flags=["external_loop", "buffered"],
                       op_flags=[["readonly"], ["readonly"], ["writeonly", "no_broadcast"]],
                       order="C", buffersize=min(batch_elements, elements(shape))) as iterator:
            for d, scale, target in iterator:
                target.fill(0)
                active = scale > 0
                with np.errstate(over="ignore", under="ignore", divide="ignore", invalid="ignore"):
                    np.divide(d, scale, out=target, where=active)
                # At t=0 the interior is mantle temperature; z=0 stays surface.
                np.copyto(target, np.inf, where=(~active) & (d > 0))
                if backend == "scipy":
                    bulk_erf(target, out=target)
                else:
                    target[:] = np.fromiter((math.erf(float(x)) for x in target),
                                            dtype=np.float64, count=target.size)
                np.multiply(target, parameters.mantle_temperature_k - parameters.surface_temperature_k, out=target)
                np.add(target, parameters.surface_temperature_k, out=target)
        del depth, length, d, scale, target, active, iterator
        return frozen(output)
