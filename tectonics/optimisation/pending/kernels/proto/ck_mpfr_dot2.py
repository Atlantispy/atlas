"""H3 prototype v2: v1 (ck_mpfr_dot) plus two exact work reductions.

1. Sign classes. For an interval with no zero endpoint and lo <= hi, the sign of each
   endpoint fixes which corner holds the exact minimum (maximum) product. Directed
   rounding is monotone, so RD(that product) equals the minimum of the four RD corner
   products, and every corner product equal to it is the same nonzero MPFR number at
   the same precision (identical bits). Only that corner is computed (both corners for
   mixed x mixed). Any interval with a zero endpoint, NaN/Inf or lo > hi takes v1's
   four-corner route, which keeps Python's first-of-equals choice between -0 and +0.
2. Gram symmetry. When X is Y and rows i and j are both zero-free, dot(X[j], X[i]) is
   the same chain of additions of the same values as dot(X[i], X[j]); the result is
   copied with mpfr_set (exact at equal precision) and the same ternary value. Rows
   with a zero endpoint are always computed in their own order.

Exceptional MPFR flags still make the caller discard the batch and run the original
Python route. Context sticky flags are not updated (no reader exists; see notes).
"""
import ctypes

import gmpy2 as G
import numpy as np
from numba import njit

import ck_mpfr_dot as V1
from ck_mpfr_dot import (Unavailable, _store_i32, mpfr_add, mpfr_mul, mpfr_less_p,
                         mpfr_greater_p, mpfr_flags_save, mpfr_flags_clear, mpfr_flags_restore,
                         RNDU, RNDD, FLAGS_ALL, FLAGS_BAD, MPFR_OFFSET, RC_FROM_MPFR, _addresses)

_P, _I = ctypes.c_int64, ctypes.c_int
mpfr_sgn = V1._bind('mpfr_sgn', _I, [_P])
mpfr_lessequal_p = V1._bind('mpfr_lessequal_p', _I, [_P, _P])
mpfr_regular_p = V1._bind('mpfr_regular_p', _I, [_P])
mpfr_set = V1._bind('mpfr_set', _I, [_P, _P, _I])
mpfr_get_exp = V1._bind('mpfr_get_exp', ctypes.c_long, [_P])

# Sign classes: 0 = four-corner route; 1 = positive; 2 = negative; 3 = mixed (lo < 0 < hi)
# A shortcut skips corner products, so it is taken only where NO corner product could
# overflow or underflow (the Python route would trap on any of the four): every endpoint
# exponent lies within +-2**28, so every product exponent lies within +-(2**29+1), far
# inside the reviewed range +-(2**30-1) checked at import.
EXP_BAND = 1 << 28


@njit(nogil=True, fastmath=False, cache=False)
def _classes(lo, hi):
    n, length = lo.shape
    out = np.zeros((n, length), dtype=np.int8)
    for i in range(n):
        for t in range(length):
            a0 = lo[i, t]
            a1 = hi[i, t]
            if mpfr_regular_p(a0) == 0 or mpfr_regular_p(a1) == 0:
                continue  # zero, NaN or Inf endpoint
            e0 = mpfr_get_exp(a0)
            e1 = mpfr_get_exp(a1)
            if e0 >= EXP_BAND or e0 <= -EXP_BAND or e1 >= EXP_BAND or e1 <= -EXP_BAND:
                continue
            if mpfr_lessequal_p(a0, a1) == 0:
                continue
            s0 = mpfr_sgn(a0)
            s1 = mpfr_sgn(a1)
            if s0 > 0:
                out[i, t] = 1
            elif s1 < 0:
                out[i, t] = 2
            else:
                out[i, t] = 3
    return out


@njit(nogil=True, fastmath=False, cache=False)
def _four(tmp, a0, a1, b0, b1):
    """v1 four-corner product; returns (low address, high address)."""
    mpfr_mul(tmp[0], a0, b0, RNDD)
    mpfr_mul(tmp[1], a0, b1, RNDD)
    mpfr_mul(tmp[2], a1, b0, RNDD)
    mpfr_mul(tmp[3], a1, b1, RNDD)
    m = tmp[0]
    if mpfr_less_p(tmp[1], m) != 0:
        m = tmp[1]
    if mpfr_less_p(tmp[2], m) != 0:
        m = tmp[2]
    if mpfr_less_p(tmp[3], m) != 0:
        m = tmp[3]
    mpfr_mul(tmp[4], a0, b0, RNDU)
    mpfr_mul(tmp[5], a0, b1, RNDU)
    mpfr_mul(tmp[6], a1, b0, RNDU)
    mpfr_mul(tmp[7], a1, b1, RNDU)
    M = tmp[4]
    if mpfr_greater_p(tmp[5], M) != 0:
        M = tmp[5]
    if mpfr_greater_p(tmp[6], M) != 0:
        M = tmp[6]
    if mpfr_greater_p(tmp[7], M) != 0:
        M = tmp[7]
    return m, M


@njit(nogil=True, fastmath=False, cache=False)
def _product(tmp, ca, cb, a0, a1, b0, b1):
    if ca == 0 or cb == 0:
        return _four(tmp, a0, a1, b0, b1)
    if ca == 1:
        if cb == 1:
            lx, ly, hx, hy = a0, b0, a1, b1
        elif cb == 2:
            lx, ly, hx, hy = a1, b0, a0, b1
        else:
            lx, ly, hx, hy = a1, b0, a1, b1
    elif ca == 2:
        if cb == 1:
            lx, ly, hx, hy = a0, b1, a1, b0
        elif cb == 2:
            lx, ly, hx, hy = a1, b1, a0, b0
        else:
            lx, ly, hx, hy = a0, b1, a0, b0
    else:
        if cb == 1:
            lx, ly, hx, hy = a0, b1, a1, b1
        elif cb == 2:
            lx, ly, hx, hy = a1, b0, a0, b0
        else:
            # mixed x mixed: min(a0*b1, a1*b0), max(a0*b0, a1*b1); both nonzero, so equal
            # values are identical numbers and the first-of-equals choice cannot matter.
            mpfr_mul(tmp[0], a0, b1, RNDD)
            mpfr_mul(tmp[1], a1, b0, RNDD)
            m = tmp[0]
            if mpfr_less_p(tmp[1], m) != 0:
                m = tmp[1]
            mpfr_mul(tmp[4], a0, b0, RNDU)
            mpfr_mul(tmp[5], a1, b1, RNDU)
            M = tmp[4]
            if mpfr_greater_p(tmp[5], M) != 0:
                M = tmp[5]
            return m, M
    mpfr_mul(tmp[0], lx, ly, RNDD)
    mpfr_mul(tmp[4], hx, hy, RNDU)
    return tmp[0], tmp[4]


@njit(nogil=True, fastmath=False, cache=False)
def _pair_dots2(x_lo, x_hi, x_cls, y_lo, y_hi, y_cls, out_lo, out_hi, tmp, gram):
    nx, length = x_lo.shape
    ny = y_lo.shape[0]
    x_free = np.ones(nx, dtype=np.bool_)
    for i in range(nx):
        for t in range(length):
            if x_cls[i, t] == 0:
                x_free[i] = False
                break
    rcs_lo = np.zeros(nx*ny, dtype=np.int32)
    rcs_hi = np.zeros(nx*ny, dtype=np.int32)
    for i in range(nx):
        for j in range(ny):
            k = i*ny+j
            acc_lo = out_lo[k]
            acc_hi = out_hi[k]
            if gram and j < i and x_free[i] and x_free[j]:
                src = j*ny+i
                mpfr_set(acc_lo, out_lo[src], RNDD)
                mpfr_set(acc_hi, out_hi[src], RNDU)
                rcs_lo[k] = rcs_lo[src]
                rcs_hi[k] = rcs_hi[src]
            else:
                rl = np.int32(0)
                rh = np.int32(0)
                for t in range(length):
                    m, M = _product(tmp, x_cls[i, t], y_cls[j, t], x_lo[i, t], x_hi[i, t],
                                    y_lo[j, t], y_hi[j, t])
                    rl = np.int32(mpfr_add(acc_lo, acc_lo, m, RNDD))
                    rh = np.int32(mpfr_add(acc_hi, acc_hi, M, RNDU))
                rcs_lo[k] = rl
                rcs_hi[k] = rh
            _store_i32(acc_lo+RC_FROM_MPFR, rcs_lo[k])
            _store_i32(acc_hi+RC_FROM_MPFR, rcs_hi[k])
    return mpfr_flags_save()


def _check_rows(rows, length):
    for row in rows:
        if len(row) != length:
            raise Unavailable('ragged rows')
        for pair in row:
            if type(pair[0]) is not G.mpfr or type(pair[1]) is not G.mpfr:
                raise Unavailable('non-mpfr operand')


def pair_dots(x_rows, y_rows, precision, *, gram=False):
    """[[dot(x, y) for y in y_rows] for x in x_rows], Arithmetic(precision) semantics.

    gram=True asserts y_rows is x_rows (checked) and enables exact symmetric reuse.
    """
    nx, ny = len(x_rows), len(y_rows)
    length = len(x_rows[0]) if nx else 0
    if not nx or not ny or not length:
        raise Unavailable('empty batch')
    if gram and y_rows is not x_rows:
        raise Unavailable('gram requires the same rows')
    _check_rows(x_rows, length)
    if not gram:
        _check_rows(y_rows, length)
    x_lo, x_hi = _addresses(x_rows, 0), _addresses(x_rows, 1)
    if gram:
        y_lo, y_hi = x_lo, x_hi
    else:
        y_lo, y_hi = _addresses(y_rows, 0), _addresses(y_rows, 1)
    count = nx*ny
    lows = [G.mpfr(0, precision) for _ in range(count)]
    highs = [G.mpfr(0, precision) for _ in range(count)]
    scratch = [G.mpfr(0, precision) for _ in range(8)]
    out_lo = np.fromiter((id(v)+MPFR_OFFSET for v in lows), dtype=np.int64, count=count)
    out_hi = np.fromiter((id(v)+MPFR_OFFSET for v in highs), dtype=np.int64, count=count)
    tmp = np.fromiter((id(v)+MPFR_OFFSET for v in scratch), dtype=np.int64, count=8)
    saved = mpfr_flags_save()
    mpfr_flags_clear(FLAGS_ALL)
    try:
        x_cls = _classes(x_lo, x_hi)
        y_cls = x_cls if gram else _classes(y_lo, y_hi)
        flags = _pair_dots2(x_lo, x_hi, x_cls, y_lo, y_hi, y_cls, out_lo, out_hi, tmp, gram)
    finally:
        mpfr_flags_restore(saved, FLAGS_ALL)
    if flags & FLAGS_BAD:
        raise Unavailable('exceptional MPFR flag %d' % flags)
    return [list(zip(lows[i*ny:(i+1)*ny], highs[i*ny:(i+1)*ny])) for i in range(nx)]


def compiled_assembly_sha256():
    import hashlib
    parts = []
    for f in (_classes, _four, _product, _pair_dots2):
        parts.extend(f.inspect_asm(sig) for sig in f.signatures)
    return hashlib.sha256('\n'.join(parts).encode()).hexdigest()
