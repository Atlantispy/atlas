"""Compiled batches of the heat certificate's directed interval dot (H3, WP24).

New private heat helper, used only by private_heat_certification_kernel_r1 after the H3
transform, which hashes this file and executes exactly the bytes it hashed. No new
software: numba 0.65.1 / llvmlite 0.47.0 are already pinned runtime dependencies
(atlas_tectonics.regional_multigrid3d), and the MPFR called here is the DLL gmpy2 2.3.2
itself loaded from gmpy2.libs (checked by module handle).

pair_dots(x_rows, y_rows, down, up) returns [[dot(x, y) for y in y_rows] for x in x_rows]
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
number); the caller then runs r1's own expression, which raises exactly as before. Only
contexts with Arithmetic's exact settings are accepted (precision >= 2: gmpy2 makes
precision-1 values at 64 bits; the five traps on, no inexact trap; default exponent
range, real precision and rounding), so no trap other than those flags can fire in r1.
The MPFR flag word is saved and restored around each batch. The gmpy2 contexts' sticky
flags are not updated (the heat helpers never read them).
Work runs in blocks of rows of at most BLOCK_PRODUCTS interval products (about 0.2 s);
check() is called between blocks, so cancellation is observed within one block. The
batch holds references to every input interval, so no input can be freed while the
compiled code (which releases the GIL) reads it.
Import fails with ImportError unless this is the reviewed build, the MPFR entry points
bind, and a compiled self-test reproduces r1's dot bit for bit; compilation happens
there, and no signature is compiled after it.
"""
import ctypes
import hashlib
import os
import time
from pathlib import Path

_STARTED = time.perf_counter()

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

_P, _I = ctypes.c_int64, ctypes.c_int  # Win64: a pointer travels in the same register as an int64
_MPFR_PATH = Path(G.__file__).resolve().parent.parent/'gmpy2.libs'/'libmpfr-6.dll'
try:
    _MPFR = ctypes.CDLL(str(_MPFR_PATH))
    _KERNEL32 = ctypes.WinDLL('kernel32')
    _KERNEL32.GetModuleHandleW.restype = ctypes.c_void_p
    _KERNEL32.GetModuleHandleW.argtypes = [ctypes.c_wchar_p]
    if _KERNEL32.GetModuleHandleW('libmpfr-6.dll') != _MPFR._handle:
        raise ImportError('the MPFR DLL is not the one gmpy2 loaded')

    def _bind(name, restype, argtypes):
        function = getattr(_MPFR, name)
        function.restype, function.argtypes = restype, argtypes
        return function

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
except (OSError, AttributeError) as error:
    raise ImportError('MPFR entry points unavailable: %s' % error) from error

RNDU, RNDD = 2, 3
FLAGS_ALL = 63
FLAGS_BAD = 1 | 2 | 4 | 16 | 32  # underflow, overflow, NaN, erange, divide-by-zero
MPFR_OFFSET = 16                 # MPFR_Object.f after PyObject_HEAD (gmpy2.h)
RC_FROM_MPFR = 32                # MPFR_Object.rc (offset 48) relative to the mpfr_t
EXP_BAND = 1 << 28
BLOCK_PRODUCTS = 1 << 20
_DEFAULT = G.context()
_TRAPS = dict(trap_underflow=True, trap_overflow=True, trap_invalid=True, trap_divzero=True, trap_erange=True)
_FIELDS = ('precision', 'real_prec', 'imag_prec', 'round', 'real_round', 'imag_round', 'emax', 'emin',
           'subnormalize', 'trap_underflow', 'trap_overflow', 'trap_inexact', 'trap_invalid',
           'trap_erange', 'trap_divzero', 'allow_complex', 'rational_division')
_SETTINGS = {}


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


def _settings(context):
    return tuple(getattr(context, name) for name in _FIELDS)


def contexts_ok(down, up):
    """Contexts with exactly the settings Arithmetic(precision) gives them (sticky flags aside)."""
    precision = down.precision
    if type(precision) is not int or precision < 2:
        return False
    if precision not in _SETTINGS:
        _SETTINGS[precision] = (_settings(G.context(precision=precision, round=G.RoundDown, **_TRAPS)),
                                _settings(G.context(precision=precision, round=G.RoundUp, **_TRAPS)))
    return (_settings(down), _settings(up)) == _SETTINGS[precision]


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
def _pair_dots(x_lo, x_hi, x_cls, x_free, y_lo, y_hi, y_cls, out_lo, out_hi, rcs_lo, rcs_hi, tmp,
               gram, start, stop):
    """Rows start..stop-1 of the batch; Gram copies read rows already finished."""
    length = x_lo.shape[1]
    ny = y_lo.shape[0]
    for i in range(start, stop):
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


_COMPILED = (_classes, _four, _product, _pair_dots)


def _addresses(rows, length, keep):
    """int64 mpfr_t addresses of (lo, hi) endpoints; refuse anything but 2-tuples of mpfr.

    Every interval tuple is appended to keep, so its endpoints outlive the batch even if
    another thread replaces it in a caller's container.
    """
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
            keep.append(pair)
            lo.append(id(a)+MPFR_OFFSET)
            hi.append(id(b)+MPFR_OFFSET)
    shape = (len(rows), length)
    return np.array(lo, dtype=np.int64).reshape(shape), np.array(hi, dtype=np.int64).reshape(shape)


def pair_dots(x_rows, y_rows, down, up, *, gram=False, check=None):
    """[[dot(x, y) for y in y_rows] for x in x_rows] for Arithmetic contexts down/up.

    gram=True requires y_rows to be x_rows. check() is called before every block after
    the first. Raises Unavailable instead of any number whenever the batch cannot be the
    original's result.
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
    keep = []
    x_lo, x_hi = _addresses(x_rows, length, keep)
    y_lo, y_hi = (x_lo, x_hi) if gram else _addresses(y_rows, length, keep)
    count = nx*ny
    lows = [G.mpfr(0, precision) for _ in range(count)]
    highs = [G.mpfr(0, precision) for _ in range(count)]
    scratch = [G.mpfr(0, precision) for _ in range(8)]
    if lows[0].precision != precision or highs[0].precision != precision or scratch[0].precision != precision:
        raise Unavailable('accumulators are not at the context precision')
    out_lo = np.array([id(v)+MPFR_OFFSET for v in lows], dtype=np.int64)
    out_hi = np.array([id(v)+MPFR_OFFSET for v in highs], dtype=np.int64)
    tmp = np.array([id(v)+MPFR_OFFSET for v in scratch], dtype=np.int64)
    rcs_lo = np.zeros(count, dtype=np.int32)
    rcs_hi = np.zeros(count, dtype=np.int32)
    step = max(1, BLOCK_PRODUCTS//(ny*length))
    flags = 0
    saved = mpfr_flags_save()
    mpfr_flags_clear(FLAGS_ALL)
    try:
        x_cls = _compiled(_classes, x_lo, x_hi)
        y_cls = x_cls if gram else _compiled(_classes, y_lo, y_hi)
        x_free = (x_cls != 0).all(axis=1)
        for start in range(0, nx, step):
            if start and check is not None:
                check()
            flags = _compiled(_pair_dots, x_lo, x_hi, x_cls, x_free, y_lo, y_hi, y_cls, out_lo, out_hi,
                              rcs_lo, rcs_hi, tmp, gram, start, min(nx, start+step))
            if flags & FLAGS_BAD:
                break
    finally:
        mpfr_flags_restore(saved, FLAGS_ALL)
    if flags & FLAGS_BAD:
        raise Unavailable('exceptional MPFR flag %d' % flags)
    return [list(zip(lows[i*ny:(i+1)*ny], highs[i*ny:(i+1)*ny], strict=True)) for i in range(nx)]


def _compiled(function, *args):
    try:
        return function(*args)
    except TypeError as error:  # no compiled signature matches (compilation is closed after import)
        raise Unavailable('no compiled signature: %s' % error) from error


def _r1_dot(x, y, down, up, zero):
    """private_heat_certification_kernel_r1.Arithmetic.dot without check(), for the self-test."""
    value = (zero, zero)
    for a, b in zip(x, y, strict=True):
        product = (min(down.mul(u, v) for u in a for v in b), max(up.mul(u, v) for u in a for v in b))
        value = (down.add(value[0], product[0]), up.add(value[1], product[1]))
    return value


def _samples(down, up, zero, negzero):
    """Positive, negative, mixed, zero-ended, signed-zero, point and inverted intervals."""
    def interval(p, q):
        return down.div(p, q), up.div(p, q)
    return [interval(1, 3), interval(-2, 7), (down.div(-1, 5), up.div(3, 11)), (zero, up.div(5, 9)),
            (down.div(-4, 13), negzero), (negzero, zero), (up.div(1, 3), up.div(1, 3)),
            (up.div(7, 3), down.div(2, 3)), interval(10**6, 7), interval(-1, 10**6)]


def _self_test():
    """Compile once and compare with r1's dot on every class, both zero signs and Gram copies."""
    for precision in (53, 200):
        down = G.context(precision=precision, round=G.RoundDown, **_TRAPS)
        up = G.context(precision=precision, round=G.RoundUp, **_TRAPS)
        near = G.context(precision=precision, round=G.RoundToNearest, **_TRAPS)
        with near:
            zero = G.mpfr(0)
        negzero = near.minus(zero)
        samples = _samples(down, up, zero, negzero)
        rows = [[samples[(3*i+t) % len(samples)] for t in range(7)] for i in range(5)]
        free = [[samples[(i+t) % 3] for t in range(7)] for i in range(4)]
        # Dots whose every product is a signed zero: the first-of-equals choice is the result.
        zeros = [[pair]*3 for pair in ((zero, zero), (negzero, negzero), (negzero, zero), (zero, negzero))]
        signed = [[pair]*3 for pair in samples[:6]]
        for x_rows, y_rows, gram in ((rows, rows, True), (free, free, True), (free+rows, rows[:3], False),
                                     (zeros, signed, False), (signed, zeros, False)):
            got = pair_dots(x_rows, y_rows, down, up, gram=gram)
            for i, x in enumerate(x_rows):
                for j, y in enumerate(y_rows):
                    for a, b in zip(got[i][j], _r1_dot(x, y, down, up, zero), strict=True):
                        if ((a.precision, a.rc, a.is_signed(), G.to_binary(a))
                                != (b.precision, b.rc, b.is_signed(), G.to_binary(b))):
                            return False
        # Exponents outside the band: only the skipped corner (-tiny)*tiny underflows, so the
        # batch must decline where r1 traps.
        tiny, one = down.mul_2exp(1, -600000000), down.div(1, 1)
        x, y = [(down.minus(tiny), one)], [(tiny, one)]
        if type(tiny) is not G.mpfr or type(one) is not G.mpfr:
            return False
        try:
            _r1_dot(x, y, down, up, zero)
        except G.UnderflowResultError:
            pass
        else:
            return False
        try:
            pair_dots([x], [y], down, up)
        except Unavailable as error:
            if 'exceptional MPFR flag' not in str(error):
                return False
        else:
            return False
    return True


try:
    _passed = _self_test()
except ImportError:
    raise
except Exception as error:
    raise ImportError('compiled interval dot could not be built: %s: %s' % (type(error).__name__, error)) from error
if not _passed:
    raise ImportError('compiled interval dot self-test differs from r1')
for _function in _COMPILED:
    _function.disable_compile()
_LOAD_SECONDS = time.perf_counter()-_STARTED  # bindings, compilation and self-test, once per process


def build_info():
    """Observed compiled-code identity (as regional_native_build_info), not a security seal."""
    import llvmlite
    assembly = '\n'.join(f.inspect_asm(sig) for f in _COMPILED for sig in f.signatures)
    return dict(module_sha256=_LOADED_SHA256, numba=numba.__version__, llvmlite=llvmlite.__version__,
                gmpy2=G.version(), mpfr=G.mpfr_version(), mpfr_dll=str(_MPFR_PATH),
                mpfr_dll_sha256=hashlib.sha256(_MPFR_PATH.read_bytes()).hexdigest(),
                fastmath=False, nogil=True, disk_jit_cache=False,
                signatures=sum(len(f.signatures) for f in _COMPILED),
                compiled_assembly_sha256=hashlib.sha256(assembly.encode()).hexdigest(),
                load_seconds=round(_LOAD_SECONDS, 3))
