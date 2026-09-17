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

from ._validation import FloatArray, TectonicsError, array, frozen, scalar, input_shape
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

    def __reduce__(self):
        return (_restore_result, (self.thickness_m, self.face_flux_m2_s,
                self.solid_volume_per_width_before_m2,
                self.solid_volume_per_width_after_m2, self.balance_residual_m2,
                self.maximum_outflow_fraction))


def _restore_result(h, flux, before, after, residual, courant):
    return TransportResult(frozen(h), frozen(flux), scalar(before, "before"),
        scalar(after, "after"), scalar(residual, "residual"), scalar(courant, "courant"))


def advect_thickness(thickness_m: Any, right_face_velocity_m_s: Any,
                     grid: PeriodicGrid1D, duration_s: float, *, budget=None) -> TransportResult:
    """One explicit upwind step for a single 1D periodic case.

    For variable velocities the positivity condition bounds the SUM of the two
    outward contributions per cell; max(abs(u))*dt/dx alone is insufficient.
    No automatic substepping or clipping conceals a rejected interval.
    """
    if not isinstance(grid, PeriodicGrid1D):
        raise TectonicsError("explicit PeriodicGrid1D required")
    shape = input_shape(thickness_m, "thickness_m")
    if shape != (grid.cells,) or input_shape(right_face_velocity_m_s, "velocity") != shape:
        raise TectonicsError("one thickness and right-face velocity per cell required")
    with select_budget(budget).reserve(128 * elements(shape)):
        h = array(thickness_m, "thickness_m", ndim=1, nonnegative=True)
        u = array(right_face_velocity_m_s, "right_face_velocity_m_s", ndim=1)
        if h.shape != (grid.cells,) or u.shape != h.shape:
            raise TectonicsError("one thickness and right-face velocity per cell required")
        dt = scalar(duration_s, "duration_s", nonnegative=True)
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
