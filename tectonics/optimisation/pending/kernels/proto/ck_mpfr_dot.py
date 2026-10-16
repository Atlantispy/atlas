"""H3 prototype: compiled directed-rounding interval dot products on gmpy2's own MPFR.

No new software. Uses numba 0.65.1 / llvmlite 0.47.0 (already pinned runtime
dependencies, see atlas_tectonics.regional_multigrid3d) and the MPFR DLL that
gmpy2 2.3.2 has already loaded from gmpy2.libs.

Semantics reproduced exactly, operation for operation, from
private_heat_certification_kernel_r1.Arithmetic:
  mul(a, b) = (min(RD(x*y) for x in a for y in b), max(RU(x*y) for x in a for y in b))
              where min/max keep the FIRST of equal values (Python builtins);
  dot(a, b) = fold of add over mul, starting from (+0, +0), RD for low, RU for high.
Every MPFR call is the same correctly rounded function at the same precision on the
same operands, so values, zero signs and ternary values (rc) are identical. Any
underflow, overflow, NaN, erange or divide-by-zero flag makes the caller discard
the batch and rerun the original Python route, which raises exactly as before.
The MPFR global flag word is saved and restored around every batch.
"""
import ctypes
import os

import gmpy2 as G
import numba
import numpy as np
from llvmlite import ir
from numba import njit, types
from numba.extending import intrinsic

REVIEWED = dict(gmpy2='2.3.2', mpfr='MPFR 4.2.2', numba='0.65.1', limbsize=64)
if (G.version(), G.mpfr_version(), numba.__version__, G.mp_limbsize()) != tuple(REVIEWED.values()):
    raise ImportError('compiled interval dot is reviewed only for ' + repr(REVIEWED))
if numba.config.DISABLE_JIT:
    raise ImportError('compiled interval dot requires enabled numba JIT')

_LIBS = os.path.abspath(os.path.join(os.path.dirname(G.__file__), os.pardir, 'gmpy2.libs'))
_MPFR = ctypes.CDLL(os.path.join(_LIBS, 'libmpfr-6.dll'))
_k32 = ctypes.WinDLL('kernel32')
_k32.GetModuleHandleW.restype = ctypes.c_void_p
_k32.GetModuleHandleW.argtypes = [ctypes.c_wchar_p]
if _k32.GetModuleHandleW('libmpfr-6.dll') != _MPFR._handle:
    raise ImportError('MPFR DLL is not the one gmpy2 loaded')


def _bind(name, restype, argtypes):
    f = getattr(_MPFR, name)
    f.restype, f.argtypes = restype, argtypes
    return f


_P, _I = ctypes.c_int64, ctypes.c_int  # Win64: a pointer travels in the same register as int64
mpfr_mul = _bind('mpfr_mul', _I, [_P, _P, _P, _I])
mpfr_add = _bind('mpfr_add', _I, [_P, _P, _P, _I])
mpfr_less_p = _bind('mpfr_less_p', _I, [_P, _P])
mpfr_greater_p = _bind('mpfr_greater_p', _I, [_P, _P])
mpfr_flags_save = _bind('mpfr_flags_save', ctypes.c_uint, [])
mpfr_flags_clear = _bind('mpfr_flags_clear', None, [ctypes.c_uint])
mpfr_flags_restore = _bind('mpfr_flags_restore', None, [ctypes.c_uint, ctypes.c_uint])
mpfr_get_emin = _bind('mpfr_get_emin', ctypes.c_long, [])
mpfr_get_emax = _bind('mpfr_get_emax', ctypes.c_long, [])

RNDU, RNDD = 2, 3
FLAGS_ALL = 63
FLAGS_BAD = 1 | 2 | 4 | 16 | 32  # underflow, overflow, NaN, erange, divide-by-zero
MPFR_OFFSET = 16  # PyObject_HEAD on 64-bit CPython
RC_FROM_MPFR = 32  # MPFR_Object.rc (offset 48) relative to the mpfr_t (offset 16)


def _layout_ok():
    """Refuse unless the object layout and MPFR exponent range are the reviewed ones."""
    with G.context(precision=320, round=G.RoundDown):
        a = G.mpfr(1)/3
    with G.context(precision=640, round=G.RoundUp):
        b = G.mpfr(1)/3
    for x, rc in ((a, -1), (b, 1)):
        if ctypes.c_long.from_address(id(x)+MPFR_OFFSET).value != x.precision:
            return False
        if ctypes.c_int.from_address(id(x)+MPFR_OFFSET+RC_FROM_MPFR).value != rc or x.rc != rc:
            return False
    c = G.context()
    return (mpfr_get_emin(), mpfr_get_emax()) == (c.emin, c.emax) and not c.subnormalize


if not _layout_ok():
    raise ImportError('gmpy2 object layout or MPFR exponent range differs from the reviewed one')


@intrinsic
def _store_i32(typingctx, address, value):
    sig = types.void(types.int64, types.int32)

    def codegen(context, builder, signature, args):
        pointer = builder.inttoptr(args[0], ir.IntType(32).as_pointer())
        builder.store(args[1], pointer)
        return context.get_dummy_value()
    return sig, codegen


@njit(nogil=True, fastmath=False, cache=False)
def _pair_dots(x_lo, x_hi, y_lo, y_hi, out_lo, out_hi, tmp):
    """out[i*ny+j] = dot(X[i], Y[j]) exactly as Arithmetic.dot; returns (flags, inexact_dn, inexact_up)."""
    nx, length = x_lo.shape
    ny = y_lo.shape[0]
    inexact_dn = 0
    inexact_up = 0
    k = 0
    for i in range(nx):
        for j in range(ny):
            acc_lo = out_lo[k]
            acc_hi = out_hi[k]
            rl = np.int32(0)
            rh = np.int32(0)
            for t in range(length):
                a0 = x_lo[i, t]
                a1 = x_hi[i, t]
                b0 = y_lo[j, t]
                b1 = y_hi[j, t]
                # Lower bound: four RD corner products, Python min keeps the first minimum.
                r0 = mpfr_mul(tmp[0], a0, b0, RNDD)
                r1 = mpfr_mul(tmp[1], a0, b1, RNDD)
                r2 = mpfr_mul(tmp[2], a1, b0, RNDD)
                r3 = mpfr_mul(tmp[3], a1, b1, RNDD)
                if r0 != 0 or r1 != 0 or r2 != 0 or r3 != 0:
                    inexact_dn = 1
                m = tmp[0]
                if mpfr_less_p(tmp[1], m) != 0:
                    m = tmp[1]
                if mpfr_less_p(tmp[2], m) != 0:
                    m = tmp[2]
                if mpfr_less_p(tmp[3], m) != 0:
                    m = tmp[3]
                # Upper bound: four RU corner products, Python max keeps the first maximum.
                r0 = mpfr_mul(tmp[4], a0, b0, RNDU)
                r1 = mpfr_mul(tmp[5], a0, b1, RNDU)
                r2 = mpfr_mul(tmp[6], a1, b0, RNDU)
                r3 = mpfr_mul(tmp[7], a1, b1, RNDU)
                if r0 != 0 or r1 != 0 or r2 != 0 or r3 != 0:
                    inexact_up = 1
                M = tmp[4]
                if mpfr_greater_p(tmp[5], M) != 0:
                    M = tmp[5]
                if mpfr_greater_p(tmp[6], M) != 0:
                    M = tmp[6]
                if mpfr_greater_p(tmp[7], M) != 0:
                    M = tmp[7]
                rl = np.int32(mpfr_add(acc_lo, acc_lo, m, RNDD))
                rh = np.int32(mpfr_add(acc_hi, acc_hi, M, RNDU))
                if rl != 0:
                    inexact_dn = 1
                if rh != 0:
                    inexact_up = 1
            _store_i32(acc_lo+RC_FROM_MPFR, rl)
            _store_i32(acc_hi+RC_FROM_MPFR, rh)
            k += 1
    return mpfr_flags_save(), inexact_dn, inexact_up


def _addresses(rows, side):
    """int64[n, L] mpfr_t addresses of interval endpoint `side` (0 lo, 1 hi)."""
    n = len(rows)
    length = len(rows[0]) if n else 0
    out = np.fromiter((id(pair[side])+MPFR_OFFSET for row in rows for pair in row),
                      dtype=np.int64, count=n*length)
    return out.reshape(n, length)


class Unavailable(Exception):
    """The compiled batch declined; the caller must run the original Python route."""


def pair_dots(x_rows, y_rows, precision):
    """[[dot(x, y) for y in y_rows] for x in x_rows] with Arithmetic(precision) semantics.

    Rows are sequences of (lo, hi) gmpy2.mpfr pairs, all of one length >= 1.
    Raises Unavailable (never a numerical result) if any exceptional flag is raised.
    """
    nx, ny = len(x_rows), len(y_rows)
    length = len(x_rows[0]) if nx else 0
    if not nx or not ny or not length:
        raise Unavailable('empty batch')
    for row in x_rows:
        if len(row) != length:
            raise Unavailable('ragged rows')
    for row in y_rows:
        if len(row) != length:
            raise Unavailable('ragged rows')
    for rows in (x_rows, y_rows):
        for row in rows:
            for pair in row:
                if type(pair[0]) is not G.mpfr or type(pair[1]) is not G.mpfr:
                    raise Unavailable('non-mpfr operand')
    x_lo, x_hi = _addresses(x_rows, 0), _addresses(x_rows, 1)
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
        flags, inexact_dn, inexact_up = _pair_dots(x_lo, x_hi, y_lo, y_hi, out_lo, out_hi, tmp)
    finally:
        mpfr_flags_restore(saved, FLAGS_ALL)
    if flags & FLAGS_BAD:
        raise Unavailable('exceptional MPFR flag %d' % flags)
    result = [list(zip(lows[i*ny:(i+1)*ny], highs[i*ny:(i+1)*ny])) for i in range(nx)]
    return result, bool(inexact_dn), bool(inexact_up)


def compiled_assembly_sha256():
    import hashlib
    asm = '\n'.join(_pair_dots.inspect_asm(sig) for sig in _pair_dots.signatures)
    return hashlib.sha256(asm.encode()).hexdigest()
