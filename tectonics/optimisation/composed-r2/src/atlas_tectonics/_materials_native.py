"""Compiled sum-consistent cohort MUSCL transport, with joint RK stages.

Each row is an extensive material thickness, not an integer ID or an age field.
There is no separately advanced total to renormalise against. Fluxes are interval
means. No fast-math, changed precision, automatic order reduction or thread races.
"""
from __future__ import annotations
import math
import numpy as np
from numba import njit
from ._regional_native import admission, fluxes, _euler, upwind_span, _slope
from ._transport_native import _add_bits, _rounded_sum, positive_sum


@njit(nogil=True, fastmath=False, cache=False)
def cohort_fluxes(h, u, external_left, external_right, flux):
    """Positive partial traces sum to the scalar total trace at every donor.

    Project candidate MC slopes onto the prescribed total slope, then limit all
    composition deviations by ONE factor. Only reconstruction is limited; no
    flux, updated inventory or fraction is corrected after the fact.
    """
    c, n = h.shape
    total = column_totals(h)
    slopes = np.empty(c, dtype=np.float64)
    for k in range(c):
        flux[k, 0] = u[0]*external_left[k]
        flux[k, n] = u[n]*external_right[k]
    for i in range(n):
        total_slope = _slope(total, i)
        candidate_sum, correction = 0.0, 0.0
        for k in range(c):
            slopes[k] = _slope(h[k], i)
            value = candidate_sum + slopes[k]
            if abs(candidate_sum) >= abs(slopes[k]):
                correction += (candidate_sum-value)+slopes[k]
            else:
                correction += (slopes[k]-value)+candidate_sum
            candidate_sum = value
        candidate_sum += correction
        rate = total_slope/total[i] if total[i] else 0.0
        candidate_rate = candidate_sum/total[i] if total[i] else 0.0
        theta = 1.0
        for k in range(c):
            delta = slopes[k]-h[k, i]*candidate_rate
            if delta > 0.0:
                bound = h[k, i]*(2.0-rate)/delta
            elif delta < 0.0:
                bound = h[k, i]*(2.0+rate)/(-delta)
            else:
                continue
            # Round the common reconstruction factor inwards. One nextafter is
            # insufficient when base + theta*delta cancels at a trace bound.
            # This is arithmetic headroom, not a negative-value acceptance band.
            bound *= 1.0-8.0*np.finfo(np.float64).eps
            if bound < theta:
                theta = max(bound, 0.0)
        for k in range(c):
            slope = h[k, i]*rate + theta*(slopes[k]-h[k, i]*candidate_rate)
            lower, upper = h[k, i]-0.5*slope, h[k, i]+0.5*slope
            if lower < 0.0 or upper < 0.0:
                raise ValueError('cohort reconstruction outside nonnegative range')
            if u[i] <= 0.0:
                flux[k, i] = u[i]*lower
            if u[i+1] >= 0.0:
                flux[k, i+1] = u[i+1]*upper
    for k in range(c):
        for j in range(n+1):
            if not math.isfinite(flux[k, j]):
                raise ValueError('cohort face flux outside numerical range')


@njit(nogil=True, fastmath=False, cache=False)
def advance_cohorts(h, u, ratio, external_left, external_right, high):
    """Joint reconstruction at both SSP stages; unchanged upwind/single-row law."""
    maximum = admission(u, ratio, 0.5 if high else 1.0)
    c, n = h.shape
    updated = np.empty_like(h)
    flux = np.empty((c, n+1), dtype=np.float64)
    totals = np.empty((c, 2), dtype=np.float64)
    stage = np.empty((c, n) if high else (0, 0), dtype=np.float64)
    stage_flux = np.empty((c, n+1) if high else (0, 0), dtype=np.float64)
    moving = ratio != 0.0 and np.any(u)
    if high and c > 1:
        cohort_fluxes(h, u, external_left, external_right, flux)
    else:
        for k in range(c):
            fluxes(h[k], u, external_left[k], external_right[k], high, flux[k])
    if moving and high:
        for k in range(c):
            _euler(h[k], flux[k], ratio, stage[k])
        if c > 1:
            cohort_fluxes(stage, u, external_left, external_right, stage_flux)
        else:
            fluxes(stage[0], u, external_left[0], external_right[0], True, stage_flux[0])
    for k in range(c):
        if not moving:
            updated[k] = h[k]
            totals[k, 0] = positive_sum(h[k])
            totals[k, 1] = totals[k, 0]
        elif high:
            _euler(stage[k], stage_flux[k], ratio, updated[k])
            for i in range(n):
                updated[k, i] = h[k, i] + 0.5*(updated[k, i]-h[k, i])
            for j in range(n+1):
                flux[k, j] = flux[k, j] + 0.5*(stage_flux[k, j]-flux[k, j])
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
