"""N01: first-order conservative periodic thickness transport on a fixed 1D grid.

This is a binary64 reference field solver, NOT the historical integer mass ledger.
One shared face flux serves adjacent cells; varying velocity is conservative, not
pure pointwise translation. Constant density and no source/sink are assumed.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any

import numpy as np

from ._validation import FloatArray, TectonicsError, read_array as array, frozen, scalar, input_shape
from .parameters import PeriodicGrid1D
from .resources import elements, select_budget


@dataclass(frozen=True, slots=True)
class TransportResult:
    thickness_m: FloatArray
    face_flux_m2_s: FloatArray
    solid_volume_per_width_before_m2: float
    solid_volume_per_width_after_m2: float
    balance_residual_m2: float
    maximum_outflow_fraction: float
    backend: str = "reference"

    @property
    def numerical_method(self) -> str:
        return ("periodic-upwind-binary64-fsum-v2" if self.backend == "reference"
                else "periodic-upwind-binary64-exact-positive-sum-numba-v1")

    def __reduce__(self):
        return (_restore_result, (self.thickness_m, self.face_flux_m2_s,
                self.solid_volume_per_width_before_m2,
                self.solid_volume_per_width_after_m2, self.balance_residual_m2,
                self.maximum_outflow_fraction, self.backend))


def _restore_result(h, flux, before, after, residual, courant, backend="reference"):
    if backend not in ("reference", "numba"):
        raise TectonicsError("unsupported restored transport backend")
    return TransportResult(frozen(h), frozen(flux), scalar(before, "before"),
        scalar(after, "after"), scalar(residual, "residual"), scalar(courant, "courant"), backend)


def advect_thickness(thickness_m: Any, right_face_velocity_m_s: Any,
                     grid: PeriodicGrid1D, duration_s: float, *, budget=None,
                     backend: str = "numba") -> TransportResult:
    """One explicit upwind step for a single 1D periodic case.

    For variable velocities the positivity condition bounds the SUM of the two
    outward contributions per cell; max(abs(u))*dt/dx alone is insufficient.
    No automatic substepping or clipping conceals a rejected interval.
    The compiled numba backend is the default; reference is explicitly selectable.
    backend="numba" explicitly selects the optional compiled kernel and an exact
    nonnegative binary64 accumulator. First use compiles; no disk JIT cache,
    parallel reduction, fast-math or automatic backend switch is used.
    """
    if backend not in ("reference", "numba"):
        raise TectonicsError("backend must be reference or numba; no automatic fallback")
    if not isinstance(grid, PeriodicGrid1D):
        raise TectonicsError("explicit PeriodicGrid1D required")
    shape = input_shape(thickness_m, "thickness_m")
    if shape != (grid.cells,) or input_shape(right_face_velocity_m_s, "velocity") != shape:
        raise TectonicsError("one thickness and right-face velocity per cell required")
    with select_budget(budget).reserve(128 * elements(shape) + (1024 if backend == "numba" else 0)):
        h = array(thickness_m, "thickness_m", ndim=1, nonnegative=True)
        u = array(right_face_velocity_m_s, "right_face_velocity_m_s", ndim=1)
        if h.shape != (grid.cells,) or u.shape != h.shape:
            raise TectonicsError("one thickness and right-face velocity per cell required")
        dt = scalar(duration_s, "duration_s", nonnegative=True)
        if backend == "numba":
            try:
                from ._transport_native import advance
            except ImportError as exc:
                raise TectonicsError("numba backend unavailable; install the declared requirements or explicitly select backend='reference'") from exc
            try:
                updated, flux, sum_before, sum_after, maximum_outflow = advance(
                    h, u, dt / grid.spacing_m)
                before = scalar(sum_before * grid.spacing_m, "initial volume", nonnegative=True)
                after = scalar(sum_after * grid.spacing_m, "final volume", nonnegative=True)
            except (ValueError, OverflowError, FloatingPointError) as exc:
                raise TectonicsError(str(exc)) from exc
            del h, u
            return TransportResult(frozen(updated), frozen(flux), before, after,
                                   after - before, maximum_outflow, backend)
        try:
            with np.errstate(over="raise", invalid="raise", divide="raise"):
                ratio = dt / grid.spacing_m
                right_out = np.maximum(u, 0)
                right_out *= ratio
                left_out = np.empty_like(u)
                left_out[1:] = u[:-1]
                left_out[0] = u[-1]
                np.negative(left_out, out=left_out)
                np.maximum(left_out, 0, out=left_out)
                left_out *= ratio
                outflow = right_out + left_out
                if np.any(outflow > 1):
                    raise TectonicsError("outgoing Courant sum exceeds one; choose a smaller interval")
                maximum_outflow = float(outflow.max())
                flux = np.empty_like(h)
                flux[:-1] = h[1:]
                flux[-1] = h[0]
                np.copyto(flux, h, where=u >= 0)
                flux *= u
                updated = np.empty_like(h)
                np.subtract(1, outflow, out=updated)
                updated *= h
                # These private factors have no further readers. Reuse them as
                # donor buffers, preserving each cell's original addition order.
                right_out *= h
                left_out *= h
                updated[1:] += right_out[:-1]
                updated[0] += right_out[-1]
                updated[:-1] += left_out[1:]
                updated[-1] += left_out[0]
                del right_out, left_out, outflow, u
            before = scalar(math.fsum(h) * grid.spacing_m, "initial volume", nonnegative=True)
            after = scalar(math.fsum(updated) * grid.spacing_m, "final volume", nonnegative=True)
        except (FloatingPointError, OverflowError) as exc:
            raise TectonicsError("transport calculation exceeds numerical range") from exc
        del h
        return TransportResult(frozen(updated), frozen(flux), before, after,
                               after - before, maximum_outflow)


def native_build_info() -> dict:
    """Record compiler selection and generated machine-code digest, not a signature."""
    from ._transport_native import advance, positive_sum
    import numba
    import hashlib
    import llvmlite
    import platform
    compiled = [advance, positive_sum]
    assembly = "\n".join(fn.inspect_asm(sig) for fn in compiled for sig in fn.signatures)
    return {"method": "periodic-upwind-binary64-exact-positive-sum-numba-v1",
            "numba": numba.__version__, "llvmlite": llvmlite.__version__,
            "machine": platform.machine(), "fastmath": False, "parallel": False,
            "disk_jit_cache": False, "nogil": True,
            "generated_assembly_sha256": hashlib.sha256(assembly.encode()).hexdigest()}
