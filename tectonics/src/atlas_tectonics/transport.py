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

from ._validation import FloatArray, TectonicsError, array, frozen, scalar
from .parameters import PeriodicGrid1D


@dataclass(frozen=True, slots=True)
class TransportResult:
    thickness_m: FloatArray
    face_flux_m2_s: FloatArray
    solid_volume_per_width_before_m2: float
    solid_volume_per_width_after_m2: float
    balance_residual_m2: float
    maximum_outflow_fraction: float


def advect_thickness(thickness_m: Any, right_face_velocity_m_s: Any,
                     grid: PeriodicGrid1D, duration_s: float) -> TransportResult:
    """One explicit upwind step for a single 1D periodic case.

    For variable velocities the positivity condition bounds the SUM of the two
    outward contributions per cell; max(abs(u))*dt/dx alone is insufficient.
    No automatic substepping or clipping conceals a rejected interval.
    """
    if not isinstance(grid, PeriodicGrid1D):
        raise TectonicsError("explicit PeriodicGrid1D required")
    h = array(thickness_m, "thickness_m", ndim=1, nonnegative=True)
    u = array(right_face_velocity_m_s, "right_face_velocity_m_s", ndim=1)
    if h.shape != (grid.cells,) or u.shape != h.shape:
        raise TectonicsError("one thickness and right-face velocity per cell required")
    dt = scalar(duration_s, "duration_s", nonnegative=True)
    try:
        with np.errstate(over="raise", invalid="raise", divide="raise"):
            right_out = np.maximum(u, 0) * (dt / grid.spacing_m)
            left_out = np.maximum(-np.roll(u, 1), 0) * (dt / grid.spacing_m)
            outflow = right_out + left_out
            if np.any(outflow > 1):
                raise TectonicsError("outgoing Courant sum exceeds one; choose a smaller interval")
            flux = u * np.where(u >= 0, h, np.roll(h, -1))
            # Algebraically the flux divergence; this form preserves positivity
            # without an after-the-fact mass-destroying negative-value clamp.
            updated = ((1 - outflow) * h + np.roll(right_out * h, 1)
                       + np.roll(left_out * h, -1))
        before = scalar(math.fsum(h) * grid.spacing_m, "initial volume", nonnegative=True)
        after = scalar(math.fsum(updated) * grid.spacing_m, "final volume", nonnegative=True)
    except (FloatingPointError, OverflowError) as exc:
        raise TectonicsError("transport calculation exceeds numerical range") from exc
    return TransportResult(frozen(updated), frozen(flux), before, after,
                           after - before, float(outflow.max()))
