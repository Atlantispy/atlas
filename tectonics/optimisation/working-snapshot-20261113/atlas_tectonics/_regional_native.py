"""W02 regional finite volumes; compiled loops, no hidden mesh or state engine.

Face j separates cells j-1 and j. Positive velocity/flux points towards +x.
Boundary scalars are validated upstream. Each face flux is computed once per
stage, then read with opposite signs by its neighbours. MUSCL uses MC-limited
spatial reconstruction and SSP-RK2 with frozen forcing during the interval.
No fast-math, parallel reduction, or automatic clipping/substepping.
"""
from __future__ import annotations
import math
import numpy as np
from numba import njit
from ._transport_native import _add_bits, _rounded_sum, positive_sum


@njit(nogil=True, fastmath=False, cache=False)
def admission(u, ratio, cap):
    """No O(N) allocation: refuse an inadmissible interval before candidate work."""
    if not math.isfinite(ratio) or ratio < 0:
        raise ValueError("transport interval/spacing outside numerical range")
    maximum = 0.0
    for i in range(u.size - 1):
        outgoing = max(u[i+1], 0.0)*ratio + max(-u[i], 0.0)*ratio
        if not math.isfinite(outgoing):
            raise ValueError("outgoing fraction outside numerical range")
        if outgoing > cap:
            raise ValueError("outgoing Courant sum exceeds scheme limit; reduce interval explicitly")
        maximum = max(maximum, outgoing)
    return maximum


@njit(nogil=True, fastmath=False, cache=False)
def duration_limit(u, dx, cap):
    """Scale speeds before adding; infinity here means no finite binary64 cap."""
    best, cell = math.inf, -1
    for i in range(u.size - 1):
        a, b = max(u[i+1], 0.0), max(-u[i], 0.0)
        scale = max(a, b)
        if scale > 0:
            # Avoid overflow of a+b. Overflow of dx/scale means a very loose cap;
            # the public wrapper tests/refuses any actual requested interval.
            dm, de = math.frexp(dx)
            sm, se = math.frexp(scale)
            mantissa, exponent = math.frexp((dm/sm)*(cap/(a/scale+b/scale)))
            value = math.ldexp(mantissa, exponent+de-se)
            if value < best:
                best, cell = value, i
    return best, cell


@njit(inline="always", fastmath=False, cache=False)
def _slope(h, i):
    n = h.size
    if n == 1:
        return 0.0
    if i == 0 or i == n-1:
        # One-sided limited reconstruction, using INTERNAL data only. External
        # thickness is a face boundary value, not a fictitious cell-centre value.
        if n == 2:
            slope = h[1]-h[0]
        else:
            d1 = h[1]-h[0] if i == 0 else h[n-1]-h[n-2]
            d2 = h[2]-h[1] if i == 0 else h[n-2]-h[n-3]
            central = 1.5*d1-0.5*d2
            if d1 > 0 and d2 > 0 and central > 0:
                slope = min(2.0*d1, central, 2.0*d2)
            elif d1 < 0 and d2 < 0 and central < 0:
                slope = -min(-2.0*d1, -central, -2.0*d2)
            else:
                slope = 0.0
        # Positivity limiter on the RECONSTRUCTION, not post-update clipping.
        return math.copysign(min(abs(slope), 2.0*h[i]), slope)
    dl, dr = h[i]-h[i-1], h[i+1]-h[i]
    if dl > 0.0 and dr > 0.0:
        return min(2.0*dl, 0.5*dl+0.5*dr, 2.0*dr)
    if dl < 0.0 and dr < 0.0:
        return -min(-2.0*dl, -0.5*dl-0.5*dr, -2.0*dr)
    return 0.0


@njit(nogil=True, fastmath=False, cache=False)
def fluxes(h, u, external_left, external_right, high_order, flux):
    """Fill the necessary face array, with no full slope or padded-field array."""
    n = h.size
    hl = h[0] - (0.5*_slope(h, 0) if high_order else 0.0)
    hr = h[n-1] + (0.5*_slope(h, n-1) if high_order else 0.0)
    flux[0] = u[0] * (external_left if u[0] > 0.0 else hl)
    flux[n] = u[n] * (external_right if u[n] < 0.0 else hr)
    for j in range(1, n):
        donor = j-1 if u[j] >= 0.0 else j
        value = h[donor]
        if high_order:
            value += (0.5 if u[j] >= 0.0 else -0.5) * _slope(h, donor)
        flux[j] = u[j]*value
    for j in range(n+1):
        if not math.isfinite(flux[j]):
            raise ValueError("regional face flux outside numerical range")


@njit(nogil=True, fastmath=False, cache=False)
def upwind_span(h, u, ratio, left, right, start, stop, updated, before, after):
    """Disjoint output span; private exact accumulators permit a tested split.

    A donor-weight form avoids subtracting nearly equal fluxes from a tiny cell.
    It is algebraically the face-flux balance, with documented binary64 rounding.
    Neighbours are always read from h, never from partially updated output.
    """
    bits_in, bits_out = h.view(np.uint64), updated.view(np.uint64)
    n = h.size
    for i in range(start, stop):
        outgoing_right = max(u[i+1], 0.0)*ratio
        outgoing_left = max(-u[i], 0.0)*ratio
        incoming_left = max(u[i], 0.0)*ratio
        incoming_right = max(-u[i+1], 0.0)*ratio
        hl = left if i == 0 else h[i-1]
        hr = right if i == n-1 else h[i+1]
        value = (1.0-(outgoing_right+outgoing_left))*h[i]
        value = value + incoming_left*hl
        value = value + incoming_right*hr
        if not math.isfinite(value) or value < 0.0:
            raise ValueError("regional thickness outside finite nonnegative range")
        updated[i] = value
        _add_bits(before, bits_in[i])
        _add_bits(after, bits_out[i])


@njit(nogil=True, fastmath=False, cache=False)
def _euler(h, flux, ratio, updated):
    for i in range(h.size):
        value = h[i] + ratio*flux[i] - ratio*flux[i+1]
        if not math.isfinite(value) or value < 0.0:
            raise ValueError("MUSCL stage outside nonnegative range; no clipping is permitted")
        updated[i] = value


@njit(nogil=True, fastmath=False, cache=False)
def advance_regional(h, u, ratio, left, right, high_order):
    cap = 0.5 if high_order else 1.0
    maximum = admission(u, ratio, cap)
    n = h.size
    flux = np.empty(n+1, dtype=np.float64)
    fluxes(h, u, left, right, high_order, flux)
    updated = np.empty(n, dtype=np.float64)
    if ratio == 0.0 or not np.any(u):
        updated[:] = h
        total = positive_sum(h)
        return updated, flux, total, total, maximum
    if not high_order:
        before, after = np.zeros(34, dtype=np.uint64), np.zeros(34, dtype=np.uint64)
        upwind_span(h, u, ratio, left, right, 0, n, updated, before, after)
        return updated, flux, _rounded_sum(before), _rounded_sum(after), maximum
    # Two SSP stages, not an arbitrary longer explicit step. The flux returned
    # is the interval-mean flux used by the RK2 conservation account.
    stage = np.empty(n, dtype=np.float64)
    _euler(h, flux, ratio, stage)
    stage_flux = np.empty(n+1, dtype=np.float64)
    fluxes(stage, u, left, right, True, stage_flux)
    _euler(stage, stage_flux, ratio, updated)
    for i in range(n):
        updated[i] = h[i] + 0.5*(updated[i]-h[i])
    for j in range(n+1):
        flux[j] = flux[j] + 0.5*(stage_flux[j]-flux[j])
    return updated, flux, positive_sum(h), positive_sum(updated), maximum
