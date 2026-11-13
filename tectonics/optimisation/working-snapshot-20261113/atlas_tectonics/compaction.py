"""W03 drained parcel compaction with explicitly supplied loading/rebound history.

Separate e--log(stress) slopes are motivated by consolidation hysteresis (Fowler
and Yang, 2002, doi:10.1029/2001JB000389, section 1). The positive stress offset
below is an explicit Atlas regularisation, not that paper's nonlinear EOS, an
Athy depth law, or a transient Darcy/consolidation solution. No upstream code is
copied. Parameter calibration and the drained assumption remain caller inputs.
"""
from __future__ import annotations

from concurrent.futures import CancelledError
from dataclasses import dataclass
from typing import Any

import numpy as np

from ._validation import FloatArray, TectonicsError, frozen, input_shape, read_array, scalar, text
from .resources import elements, select_budget


@dataclass(frozen=True, slots=True)
class CompactionParameters:
    """SI stress bounds and dimensionless natural-log slopes; no physical defaults.

    A conventional base-10 compression index is divided by ln(10) to obtain a
    natural-log slope. Zero rebound means irreversible/no-rebound unloading;
    equal slopes give the explicitly selected reversible limiting case.
    """
    profile_id: str
    provenance: str
    compression_slope_ln: float
    rebound_slope_ln: float
    reference_stress_pa: float
    max_effective_stress_pa: float
    min_porosity: float
    max_porosity: float

    def __post_init__(self):
        text(self.profile_id, "profile_id")
        text(self.provenance, "provenance")
        for name in ("compression_slope_ln", "rebound_slope_ln", "min_porosity", "max_porosity"):
            object.__setattr__(self, name, scalar(getattr(self, name), name, nonnegative=True))
        for name in ("reference_stress_pa", "max_effective_stress_pa"):
            object.__setattr__(self, name, scalar(getattr(self, name), name, positive=True))
        if self.rebound_slope_ln > self.compression_slope_ln:
            raise TectonicsError("rebound slope must not exceed compression slope")
        if not self.min_porosity <= self.max_porosity < 1:
            raise TectonicsError("require 0 <= min_porosity <= max_porosity < 1")


def _cancel(cancel):
    if cancel is not None and cancel.is_set():
        raise CancelledError("compaction cancelled; no candidate published")


def compaction_work_bytes(*shapes, batch_elements=8192):
    """Conservative accounted array work, excluding caller buffers/native baseline."""
    if type(batch_elements) is not int or batch_elements <= 0:
        raise TectonicsError("batch_elements must be a positive integer")
    try:
        shape = np.broadcast_shapes(*shapes)
    except ValueError as exc:
        raise TectonicsError("compaction inputs cannot be broadcast") from exc
    count = elements(shape)
    if not count:
        raise TectonicsError("compaction inputs must be nonempty")
    # Four captures, two-channel work/publication, and conservative bounded
    # iterator, masked arithmetic and logarithm temporaries. No broadcast copies.
    return 24 * sum(elements(s) for s in shapes) + 40 * count + 1024 * min(count, batch_elements) + 8192


def _weighted_log_ratio(a, b, offset, slope):
    """slope*ln((offset+a)/(offset+b)), without overflowing shifted stresses.

    Symmetric nonnegative differences avoid cancellation on near-equal stresses.
    Small ratios multiply via binary exponents before scaling: an underflowing
    bare ratio must not destroy an otherwise representable weighted increment.
    """
    result = np.zeros(a.shape, dtype=np.float64)
    if slope == 0:
        return result
    different = a != b
    if not np.any(different):
        return result
    av, bv = a[different], b[different]
    low, high = np.minimum(av, bv), np.maximum(av, bv)
    difference = high - low
    scale = np.maximum(low, offset)
    with np.errstate(over="ignore", under="ignore", divide="ignore", invalid="ignore"):
        denominator = low / scale + offset / scale
        ratio = (difference / scale) / denominator
        increment = np.empty(ratio.shape, dtype=np.float64)
        small = ratio < 1e-8
        if np.any(small):
            numerator_m, numerator_e = np.frexp(difference[small])
            scale_m, scale_e = np.frexp(scale[small])
            slope_m, slope_e = np.frexp(slope)
            weighted = np.ldexp((numerator_m * slope_m / scale_m) / denominator[small],
                                numerator_e + slope_e - scale_e)
            x = ratio[small]
            # log1p(x)/x = 1 - x/2 + x^2/3 ...; omitted relative term < 4e-25.
            increment[small] = weighted * (1 - x / 2 + x * x / 3)
        regular = (~small) & np.isfinite(ratio)
        increment[regular] = slope * np.log1p(ratio[regular])
        large = ~np.isfinite(ratio)
        if np.any(large):
            increment[large] = slope * (np.log(difference[large]) - np.log(scale[large])
                                        - np.log(denominator[large]))
    if np.any(~np.isfinite(increment)) or np.any(increment <= 0):
        raise TectonicsError("compaction increment outside numerical range")
    result[different] = np.where(av > bv, increment, -increment)
    return result


def compaction_response(void_ratio: Any, effective_stress_pa: Any,
                        maximum_effective_stress_pa: Any, new_effective_stress_pa: Any,
                        parameters: CompactionParameters, *, budget=None,
                        batch_elements=8192, cancel=None) -> FloatArray:
    """Return immutable broadcast-shape+(2,) [new void ratio, new peak stress].

    Compressive effective stress is nonnegative in Pa; e=porosity/(1-porosity).
    The anchored update is de=-(Cc-Cr)*ln((peak_new+s0)/(peak_old+s0))
    -Cr*ln((stress_new+s0)/(stress_old+s0)). Peak history is never inferred from
    porosity and is never erased by unloading. This local constitutive function
    assumes effective stresses have already been established by a column model.
    All range failures refuse the entire result; there is no clipping.
    """
    _cancel(cancel)
    if type(parameters) is not CompactionParameters:
        raise TectonicsError("explicit CompactionParameters required")
    names = ("void_ratio", "effective_stress_pa", "maximum_effective_stress_pa", "new_effective_stress_pa")
    values = (void_ratio, effective_stress_pa, maximum_effective_stress_pa, new_effective_stress_pa)
    shapes = tuple(input_shape(value, name) for value, name in zip(values, names))
    required = compaction_work_bytes(*shapes, batch_elements=batch_elements)
    shape = np.broadcast_shapes(*shapes)
    with select_budget(budget).reserve(required, category="compaction-law"):
        captures = tuple(read_array(value, name, nonnegative=True) for value, name in zip(values, names))
        if any(value.shape != expected for value, expected in zip(captures, shapes)):
            raise TectonicsError("input shape changed during capture")
        _cancel(cancel)
        output = np.empty(shape + (2,), dtype=np.float64)
        p = parameters
        lower = p.min_porosity / (1 - p.min_porosity)
        upper = p.max_porosity / (1 - p.max_porosity)
        operands = [*captures, output[..., 0], output[..., 1]]
        flags = [["readonly"]] * 4 + [["writeonly", "no_broadcast"]] * 2
        with np.nditer(operands, flags=["external_loop", "buffered"], op_flags=flags,
                       order="C", buffersize=min(batch_elements, elements(shape))) as iterator:
            for old_e, old_s, peak, new_s, target_e, target_peak in iterator:
                _cancel(cancel)
                if (np.any(old_e < lower) or np.any(old_e > upper)
                        or np.any(peak < old_s) or np.any(peak > p.max_effective_stress_pa)
                        or np.any(new_s > p.max_effective_stress_pa)):
                    raise TectonicsError("compaction state outside supplied porosity/stress/history bounds")
                np.maximum(peak, new_s, out=target_peak)
                plastic = _weighted_log_ratio(target_peak, peak, p.reference_stress_pa,
                                              p.compression_slope_ln - p.rebound_slope_ln)
                elastic = _weighted_log_ratio(new_s, old_s, p.reference_stress_pa, p.rebound_slope_ln)
                with np.errstate(over="ignore", under="ignore", invalid="ignore"):
                    increment = plastic + elastic
                    np.subtract(old_e, increment, out=target_e)
                if (np.any(~np.isfinite(target_e)) or np.any(target_e < lower)
                        or np.any(target_e > upper)):
                    raise TectonicsError("updated compaction porosity outside supplied range")
        _cancel(cancel)
        return frozen(output)
