"""Compiled batches of the heat certificate's directed interval dot (H3, WP24).

New private heat helper, used only by private_heat_certification_kernel_r1 after the H3
transform. No new software: numba 0.65.1 / llvmlite 0.47.0 are already pinned runtime
dependencies (atlas_tectonics.regional_multigrid3d), and the MPFR called here is the DLL
gmpy2 2.3.2 itself loaded from gmpy2.libs (checked by module handle).

pair_dots(x_rows, y_rows, precision) returns [[dot(x, y) for y in y_rows] for x in x_rows]
with the values of private_heat_certification_kernel_r1.Arithmetic(precision).dot:
  mul(a, b) = (min(RD(x*y) for x in a for y in b), max(RU(x*y) for x in a for y in b)),
              min/max keeping the FIRST of equal values (Python builtins);
  dot(a, b) = add() fold of mul() from (+0, +0): RD for the low, RU for the high bound.
Each result is a new gmpy2.mpfr at `precision` whose value, zero sign and ternary value
(rc) are those of the corresponding r1 object. Two exact work reductions:
1. Sign classes. For an interval with no zero endpoint, lo <= hi and both exponents
   within +-2**28, the endpoint signs fix which corner holds the exact minimum
   (maximum) product. Directed rounding is monotone, so RD of that corner equals the
   minimum of the four RD corner products, and any equal corner is the same nonzero
   number at the same precision. Only that corner is computed (both candidates for
   mixed x mixed). The exponent band guarantees that no skipped corner could have
   overflowed or underflowed (r1 traps on any of the four). Every other interval takes
   the four-corner route in r1's order with r1's first-of-equals choice, which decides
   between -0 and +0.
2. Gram symmetry (gram=True, x_rows is y_rows). When rows i and j are both
   shortcut-eligible, dot(X[j], X[i]) adds the same values in the same order as
   dot(X[i], X[j]); the result is copied exactly (mpfr_set, equal precision) with the
   same ternary value. Rows with any four-corner interval are always computed.
Any underflow, overflow, NaN, erange or divide-by-zero flag raises Unavailable (never a
number); the caller then runs r1's own expression, which raises exactly as before. The
MPFR flag word is saved and restored around each batch. The gmpy2 contexts' sticky
flags are not updated (the heat helpers never read them).
"""
import ctypes
import hashlib
import os
from pathlib import Path

import gmpy2 as G
import numba
import numpy as np
from llvmlite import ir
from numba import njit, types
from numba.extending import intrinsic

_LOADED_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
REVIEWED = (('gmpy2', '2.3.2'), ('mpfr', 'MPFR 4.2.2'), ('numba', '0.65.1'), ('limbsize', 64))
if (G.version(), G.mpfr_version(), numba.__version__, G.mp_limbsize()) != tuple(v for _, v in REVIEWED):
    raise ImportError('compiled interval dot is reviewed only for %r' % (REVIEWED,))
if numba.config.DISABLE_JIT or os.name != 'nt' or ctypes.sizeof(ctypes.c_void_p) != 8:
    raise ImportError('compiled interval dot requires enabled numba JIT on 64-bit Windows')

_MPFR = ctypes.CDLL(str(Path(G.__file__).resolve().parent.parent/'gmpy2.libs'/'libmpfr-6.dll'))
_KERNEL32 = ctypes.WinDLL('kernel32')
_KERNEL32.GetModuleHandleW.restype = ctypes.c_void_p
_KERNEL32.GetModuleHandleW.argtypes = [ctypes.c_wchar_p]
if _KERNEL32.GetModuleHandleW('libmpfr-6.dll') != _MPFR._handle:
    raise ImportError('the MPFR DLL is not the one gmpy2 loaded')


def _bind(name, restype, argtypes):
    function = getattr(_MPFR, name)
    function.restype, function.argtypes = restype, argtypes
    return function


_P, _I = ctypes.c_int64, ctypes.c_int  # Win64: a pointer travels in the same register as an int64
mpfr_mul = _bind('mpfr_mul', _I, [_P, _P, _P, _I])
mpfr_add = _bind('mpfr_add', _I, [_P, _P, _P, _I])
mpfr_set = _bind('mpfr_set', _I, [_P, _P, _I])
mpfr_less_p = _bind('mpfr_less_p', _I, [_P, _P])
mpfr_greater_p = _bind('mpfr_greater_p', _I, [_P, _P])
mpfr_lessequal_p = _bind('mpfr_lessequal_p', _I, [_P, _P])
mpfr_regular_p = _bind('mpfr_regular_p', _I, [_P])
mpfr_sgn = _bind('mpfr_sgn', _I, [_P])
mpfr_get_exp = _bind('mpfr_get_exp', ctypes.c_long, [_P])
mpfr_flags_save = _bind('mpfr_flags_save', ctypes.c_uint, [])
mpfr_flags_clear = _bind('mpfr_flags_clear', None, [ctypes.c_uint])
mpfr_flags_restore = _bind('mpfr_flags_restore', None, [ctypes.c_uint, ctypes.c_uint])
mpfr_get_emin = _bind('mpfr_get_emin', ctypes.c_long, [])
mpfr_get_emax = _bind('mpfr_get_emax', ctypes.c_long, [])

RNDU, RNDD = 2, 3
FLAGS_ALL = 63
FLAGS_BAD = 1 | 2 | 4 | 16 | 32  # underflow, overflow, NaN, erange, divide-by-zero
MPFR_OFFSET = 16                 # MPFR_Object.f after PyObject_HEAD (gmpy2.h)
RC_FROM_MPFR = 32                # MPFR_Object.rc (offset 48) relative to the mpfr_t
EXP_BAND = 1 << 28
_DEFAULT = G.context()


def _layout_ok():
    """The reviewed object layout and exponent range, read back from gmpy2-made values."""
    with G.context(precision=320, round=G.RoundDown):
        a = G.mpfr(1)/3
    with G.context(precision=640, round=G.RoundUp):
        b = G.mpfr(1)/3
    for x, rc in ((a, -1), (b, 1)):
        if ctypes.c_long.from_address(id(x)+MPFR_OFFSET).value != x.precision:
            return False
        if ctypes.c_int.from_address(id(x)+MPFR_OFFSET+RC_FROM_MPFR).value != rc or x.rc != rc:
            return False
    return ((mpfr_get_emin(), mpfr_get_emax()) == (_DEFAULT.emin, _DEFAULT.emax)
            and not _DEFAULT.subnormalize and G.mpfr(0, 320) is not G.mpfr(0, 320))


if not _layout_ok():
    raise ImportError('gmpy2 object layout or MPFR exponent range differs from the reviewed one')


class Unavailable(Exception):
    """The batch declined; the caller must run its original Python expression."""


def contexts_ok(down, up):
    """Contexts as Arithmetic builds them: directed, equal precision, default exponent range."""
    return (down.round == G.RoundDown and up.round == G.RoundUp and down.precision == up.precision
            and not down.subnormalize and not up.subnormalize
            and down.emin == up.emin == _DEFAULT.emin and down.emax == up.emax == _DEFAULT.emax)


@intrinsic
def _store_i32(typingctx, address, value):
    sig = types.void(types.int64, types.int32)

    def codegen(context, builder, signature, args):
        builder.store(args[1], builder.inttoptr(args[0], ir.IntType(32).as_pointer()))
        return context.get_dummy_value()
    return sig, codegen


@njit(nogil=True, fastmath=False, cache=False)
def _classes(lo, hi):
    """0 = four-corner route; 1 = positive; 2 = negative; 3 = mixed (lo < 0 < hi)."""
    n, length = lo.shape
    out = np.zeros((n, length), dtype=np.int8)
    for i in range(n):
        for t in range(length):
            a0 = lo[i, t]
            a1 = hi[i, t]
            if mpfr_regular_p(a0) == 0 or mpfr_regular_p(a1) == 0:
                continue
            e0 = mpfr_get_exp(a0)
            e1 = mpfr_get_exp(a1)
            if e0 >= EXP_BAND or e0 <= -EXP_BAND or e1 >= EXP_BAND or e1 <= -EXP_BAND:
                continue
            if mpfr_lessequal_p(a0, a1) == 0:
                continue
            if mpfr_sgn(a0) > 0:
                out[i, t] = 1
            elif mpfr_sgn(a1) < 0:
                out[i, t] = 2
            else:
                out[i, t] = 3
    return out


@njit(nogil=True, fastmath=False, cache=False)
def _four(tmp, a0, a1, b0, b1):
    """r1's mul: four RD then four RU corner products, first of equals kept."""
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
def _pair_dots(x_lo, x_hi, x_cls, y_lo, y_hi, y_cls, out_lo, out_hi, tmp, gram):
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
                source = j*ny+i
                mpfr_set(acc_lo, out_lo[source], RNDD)
                mpfr_set(acc_hi, out_hi[source], RNDU)
                rcs_lo[k] = rcs_lo[source]
                rcs_hi[k] = rcs_hi[source]
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


def _addresses(rows, length):
    """int64 mpfr_t addresses of (lo, hi) endpoints; refuse anything but 2-tuples of mpfr."""
    lo, hi = [], []
    for row in rows:
        if len(row) != length:
            raise Unavailable('rows of unequal length')
        for pair in row:
            if type(pair) is not tuple or len(pair) != 2:
                raise Unavailable('interval is not a 2-tuple')
            a, b = pair
            if type(a) is not G.mpfr or type(b) is not G.mpfr:
                raise Unavailable('interval endpoint is not an mpfr')
            lo.append(id(a)+MPFR_OFFSET)
            hi.append(id(b)+MPFR_OFFSET)
    shape = (len(rows), length)
    return np.array(lo, dtype=np.int64).reshape(shape), np.array(hi, dtype=np.int64).reshape(shape)


def pair_dots(x_rows, y_rows, down, up, *, gram=False):
    """[[dot(x, y) for y in y_rows] for x in x_rows] for Arithmetic contexts down/up.

    gram=True requires y_rows to be x_rows. Raises Unavailable instead of any number
    whenever the batch cannot be the original's result.
    """
    if not contexts_ok(down, up):
        raise Unavailable('contexts are not the reviewed directed pair')
    precision = down.precision
    nx, ny = len(x_rows), len(y_rows)
    length = len(x_rows[0]) if nx else 0
    if not nx or not ny or not length:
        raise Unavailable('empty batch')
    if gram and y_rows is not x_rows:
        raise Unavailable('gram requires the same rows')
    x_lo, x_hi = _addresses(x_rows, length)
    y_lo, y_hi = (x_lo, x_hi) if gram else _addresses(y_rows, length)
    count = nx*ny
    lows = [G.mpfr(0, precision) for _ in range(count)]
    highs = [G.mpfr(0, precision) for _ in range(count)]
    scratch = [G.mpfr(0, precision) for _ in range(8)]
    out_lo = np.array([id(v)+MPFR_OFFSET for v in lows], dtype=np.int64)
    out_hi = np.array([id(v)+MPFR_OFFSET for v in highs], dtype=np.int64)
    tmp = np.array([id(v)+MPFR_OFFSET for v in scratch], dtype=np.int64)
    saved = mpfr_flags_save()
    mpfr_flags_clear(FLAGS_ALL)
    try:
        x_cls = _classes(x_lo, x_hi)
        y_cls = x_cls if gram else _classes(y_lo, y_hi)
        flags = _pair_dots(x_lo, x_hi, x_cls, y_lo, y_hi, y_cls, out_lo, out_hi, tmp, gram)
    finally:
        mpfr_flags_restore(saved, FLAGS_ALL)
    if flags & FLAGS_BAD:
        raise Unavailable('exceptional MPFR flag %d' % flags)
    return [list(zip(lows[i*ny:(i+1)*ny], highs[i*ny:(i+1)*ny], strict=True)) for i in range(nx)]


def build_info():
    """Observed compiled-code identity (as regional_native_build_info), not a security seal.

    Compilation is lazy (first batch); before it, compiled is False and no digest exists.
    """
    functions = (_classes, _four, _product, _pair_dots)
    compiled = all(f.signatures for f in functions)
    assembly = '\n'.join(f.inspect_asm(sig) for f in functions for sig in f.signatures) if compiled else None
    import llvmlite
    return dict(module_sha256=_LOADED_SHA256, numba=numba.__version__, llvmlite=llvmlite.__version__,
                fastmath=False, nogil=True, disk_jit_cache=False, compiled=compiled,
                compiled_assembly_sha256=None if assembly is None else hashlib.sha256(assembly.encode()).hexdigest())
