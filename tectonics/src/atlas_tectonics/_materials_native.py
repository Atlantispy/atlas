"""Compiled cohort transport: same regional MUSCL law, O(N) shared scratch.

Each row is an extensive material thickness, not an integer ID or an age field.
There is no separately advanced total to renormalise against. Fluxes are interval
means. No fast-math, changed precision, automatic order reduction or thread races.
"""
from __future__ import annotations
import math
import numpy as np
from numba import njit
from ._regional_native import admission, fluxes, _euler, upwind_span
from ._transport_native import _add_bits, _rounded_sum, positive_sum


@njit(nogil=True, fastmath=False, cache=False)
def advance_cohorts(h, u, ratio, external_left, external_right, high):
    """Reuse the two RK scratch vectors across rows, not C copies of each stage."""
    maximum = admission(u, ratio, 0.5 if high else 1.0)
    c, n = h.shape
    updated = np.empty_like(h)
    flux = np.empty((c, n+1), dtype=np.float64)
    totals = np.empty((c, 2), dtype=np.float64)
    stage = np.empty(n if high else 0, dtype=np.float64)
    stage_flux = np.empty(n+1 if high else 0, dtype=np.float64)
    moving = ratio != 0.0 and np.any(u)
    for k in range(c):
        fluxes(h[k], u, external_left[k], external_right[k], high, flux[k])
        if not moving:
            updated[k] = h[k]
            totals[k, 0] = positive_sum(h[k])
            totals[k, 1] = totals[k, 0]
        elif high:
            _euler(h[k], flux[k], ratio, stage)
            fluxes(stage, u, external_left[k], external_right[k], True, stage_flux)
            _euler(stage, stage_flux, ratio, updated[k])
            for i in range(n):
                updated[k, i] = h[k, i] + 0.5*(updated[k, i]-h[k, i])
            for j in range(n+1):
                flux[k, j] = flux[k, j] + 0.5*(stage_flux[j]-flux[k, j])
            totals[k, 0] = positive_sum(h[k])
            totals[k, 1] = positive_sum(updated[k])
        else:
            before = np.zeros(34, dtype=np.uint64)
            after = np.zeros(34, dtype=np.uint64)
            upwind_span(h[k], u, ratio, external_left[k], external_right[k],
                        0, n, updated[k], before, after)
            totals[k, 0], totals[k, 1] = _rounded_sum(before), _rounded_sum(after)
    return updated, flux, totals, maximum


@njit(nogil=True, fastmath=False, cache=False)
def column_totals(h):
    """Exact positive accumulation per column; round once, no O(C*N) scratch."""
    c, n = h.shape
    out = np.empty(n, dtype=np.float64)
    bits = h.view(np.uint64)
    limbs = np.zeros(34, dtype=np.uint64)
    for i in range(n):
        limbs[:] = 0
        for k in range(c):
            _add_bits(limbs, bits[k, i])
        out[i] = _rounded_sum(limbs)
        if not math.isfinite(out[i]):
            raise ValueError('total thickness exceeds numerical range')
    return out
