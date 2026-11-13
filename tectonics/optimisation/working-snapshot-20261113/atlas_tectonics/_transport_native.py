"""Default compiled upwind update and exact sums of NONNEGATIVE binary64 data.

An original fixed-limb accumulator stores each value as an integer multiple of
2**-1074. Thirty-four uint64 limbs cover every finite positive binary64 times any
array length addressable with signed 64-bit indices. Addition is exact; the final
sum is rounded once, nearest/ties-to-even. This is not a general signed fsum and
not the historical mass ledger. Reference comparison uses math.fsum and Fractions.

No fast-math/reassociation, parallel reduction, disk compilation cache or Python
object access in the compiled loops. Private buffers belong to one invocation.
"""
from __future__ import annotations

import math

import numpy as np
import numba
from numba import njit

if numba.__version__ != "0.65.1":
    raise ImportError("transport backend requires the reviewed Numba 0.65.1 build family")
if numba.config.DISABLE_JIT:
    raise ImportError("numba backend requires JIT; NUMBA_DISABLE_JIT is enabled")


@njit(inline="always", fastmath=False, cache=False)
def _add_limb(limbs, index, value):
    while value != 0:
        if index >= 34:
            raise OverflowError("exact-sum accumulator capacity exceeded")
        old = limbs[index]
        new = old + value
        limbs[index] = new
        value = np.uint64(1) if new < old else np.uint64(0)
        index += 1


@njit(inline="always", fastmath=False, cache=False)
def _add_bits(limbs, bits):
    # The caller validates nonnegative finite data. Negative zero has value zero.
    exponent = int((bits >> np.uint64(52)) & np.uint64(2047))
    mantissa = bits & np.uint64(0x000fffffffffffff)
    shift = 0
    if exponent != 0:
        mantissa |= np.uint64(1) << np.uint64(52)
        shift = exponent - 1
    index, offset = shift // 64, shift % 64
    _add_limb(limbs, index, mantissa << np.uint64(offset))
    if offset != 0:
        _add_limb(limbs, index + 1, mantissa >> np.uint64(64 - offset))


@njit(fastmath=False, cache=False)
def _rounded_sum(limbs):
    index = 33
    while index >= 0 and limbs[index] == 0:
        index -= 1
    if index < 0:
        return 0.0
    word = limbs[index]
    top = index * 64
    while word > 1:
        word >>= np.uint64(1)
        top += 1
    out = np.empty(1, dtype=np.uint64)
    if top < 52:  # Exact subnormal; no bits need discarding.
        out[0] = limbs[0]
        return out.view(np.float64)[0]
    shift = top - 52
    i, offset = shift // 64, shift % 64
    significand = limbs[i] >> np.uint64(offset)
    if offset != 0 and i + 1 < 34:
        significand |= limbs[i + 1] << np.uint64(64 - offset)
    significand &= np.uint64(0x001fffffffffffff)
    if shift > 0:
        j, bit = (shift - 1) // 64, (shift - 1) % 64
        halfway = ((limbs[j] >> np.uint64(bit)) & np.uint64(1)) != 0
        sticky = (limbs[j] & ((np.uint64(1) << np.uint64(bit)) - np.uint64(1))) != 0
        for k in range(j):
            if limbs[k] != 0:
                sticky = True
        if halfway and (sticky or (significand & np.uint64(1)) != 0):
            significand += np.uint64(1)
            if significand == np.uint64(0x0020000000000000):
                significand >>= np.uint64(1)
                top += 1
    exponent = top - 51
    if exponent >= 2047:
        raise OverflowError("exact transport sum exceeds finite binary64 range")
    out[0] = (np.uint64(exponent) << np.uint64(52)) | (significand & np.uint64(0x000fffffffffffff))
    return out.view(np.float64)[0]


@njit(nogil=True, fastmath=False, cache=False)
def positive_sum(values):
    """Independent entry point for verifying the accumulator; no negative values."""
    bits = values.view(np.uint64)
    limbs = np.zeros(34, dtype=np.uint64)
    for i in range(values.size):
        if not math.isfinite(values[i]) or values[i] < 0:
            raise ValueError("exact positive sum requires finite nonnegative values")
        _add_bits(limbs, bits[i])
    return _rounded_sum(limbs)


@njit(nogil=True, fastmath=False, cache=False)
def advance(h, u, ratio):
    """Validated contiguous 1D arrays in; private candidates and scalar sums out."""
    if not math.isfinite(ratio) or ratio < 0:
        raise ValueError("transport calculation exceeds numerical range")
    n = h.size
    if n < 5 or u.size != n:
        raise ValueError("matching arrays with at least five cells required")
    # Admission pass preserves all timestep refusals before returning candidates.
    maximum = 0.0 * ratio  # preserve an explicitly supplied negative-zero interval
    for i in range(n):
        previous = n - 1 if i == 0 else i - 1
        right = (u[i] if u[i] > 0 else 0.0) * ratio
        left = (-u[previous] if u[previous] < 0 else 0.0) * ratio
        outgoing = right + left
        if not math.isfinite(outgoing):
            raise ValueError("transport calculation exceeds numerical range")
        if outgoing > 1:
            raise ValueError("outgoing Courant sum exceeds one; choose a smaller interval")
        if outgoing > maximum:
            maximum = outgoing
    updated = np.empty(n, dtype=np.float64)
    flux = np.empty(n, dtype=np.float64)
    before = np.zeros(34, dtype=np.uint64)
    after = np.zeros(34, dtype=np.uint64)
    old_bits, new_bits = h.view(np.uint64), updated.view(np.uint64)
    for i in range(n):
        previous = n - 1 if i == 0 else i - 1
        following = 0 if i == n - 1 else i + 1
        right = (u[i] if u[i] > 0 else 0.0) * ratio
        left = (-u[previous] if u[previous] < 0 else 0.0) * ratio
        incoming_left = (u[previous] if u[previous] > 0 else 0.0) * ratio
        incoming_right = (-u[i] if u[i] < 0 else 0.0) * ratio
        # Preserve the reference's multiplication and left-then-right additions.
        value = (1.0 - (right + left)) * h[i]
        value = value + incoming_left * h[previous]
        value = value + incoming_right * h[following]
        face = u[i] * (h[i] if u[i] >= 0 else h[following])
        if not math.isfinite(value) or not math.isfinite(face) or value < 0:
            raise ValueError("transport calculation exceeds numerical range")
        updated[i], flux[i] = value, face
        _add_bits(before, old_bits[i])
        _add_bits(after, new_bits[i])
    return updated, flux, _rounded_sum(before), _rounded_sum(after), maximum
