"""Read-only layout probe: gmpy2 MPFR object offsets, loaded MPFR DLL, exponent range.

Run with .r44-env python -B -I. Writes nothing.
"""
import ctypes
import os
import sys

import gmpy2 as G

libs = os.path.abspath(os.path.join(os.path.dirname(G.__file__), os.pardir, "gmpy2.libs"))
mpfr_path = os.path.join(libs, "libmpfr-6.dll")
k32 = ctypes.WinDLL("kernel32", use_last_error=True)
k32.GetModuleHandleW.restype = ctypes.c_void_p
k32.GetModuleHandleW.argtypes = [ctypes.c_wchar_p]
before = k32.GetModuleHandleW("libmpfr-6.dll")
lib = ctypes.CDLL(mpfr_path)
print("mpfr handle already loaded by gmpy2:", hex(before or 0), "ctypes handle:", hex(lib._handle), "same:", before == lib._handle)

lib.mpfr_get_version.restype = ctypes.c_char_p
print("mpfr_get_version:", lib.mpfr_get_version().decode(), "gmpy2 says", G.mpfr_version())
for name in ("mpfr_get_emin", "mpfr_get_emax", "mpfr_get_emin_min", "mpfr_get_emax_max"):
    f = getattr(lib, name)
    f.restype = ctypes.c_long
    print(name, f())
ctx = G.context()
print("gmpy2 default context emin/emax:", ctx.emin, ctx.emax, "subnormalize", ctx.subnormalize)
print("sizeof(long)", ctypes.sizeof(ctypes.c_long))

# Locate the mpfr_t inside the object: precision field at id+16 (PyObject_HEAD = 16 bytes).
for prec in (320, 640, 1280, 2560):
    with G.context(precision=prec, round=G.RoundDown) as c:
        x = G.mpfr(1) / 3
        y = G.mpfr(2) / 3
    addr = id(x)
    p_read = ctypes.c_long.from_address(addr + 16).value
    sign_read = ctypes.c_int.from_address(addr + 20).value
    exp_read = ctypes.c_long.from_address(addr + 24).value
    # mpfr_get_prec through the DLL on the struct pointer
    lib.mpfr_get_prec.restype = ctypes.c_long
    lib.mpfr_get_prec.argtypes = [ctypes.c_int64]
    print(f"prec={prec} read={p_read} via_dll={lib.mpfr_get_prec(addr + 16)} sign={sign_read} exp={exp_read} x.rc={x.rc} y.rc={y.rc}")

# rc offset: find int field equal to rc for objects with rc=-1 and rc=+1
with G.context(precision=320, round=G.RoundDown):
    a = G.mpfr(1) / 3  # rc -1
with G.context(precision=320, round=G.RoundUp):
    b = G.mpfr(1) / 3  # rc +1
with G.context(precision=320):
    c0 = G.mpfr(1) / 2  # exact, rc 0
print("rc values", a.rc, b.rc, c0.rc)
for off in range(16, 64, 4):
    va = ctypes.c_int.from_address(id(a) + off).value
    vb = ctypes.c_int.from_address(id(b) + off).value
    vc = ctypes.c_int.from_address(id(c0) + off).value
    if (va, vb, vc) == (a.rc, b.rc, c0.rc):
        print("rc offset candidate", off)
# hash_cache: -1 for unhashed object, then hash(x)
d = G.mpfr("0.1", 320)
for off in range(16, 64, 8):
    v = ctypes.c_int64.from_address(id(d) + off).value
    if v == -1:
        h = hash(d)
        print("hash_cache candidate", off, "after hash:", ctypes.c_int64.from_address(id(d) + off).value == h)
print("sys.getsizeof(mpfr 320)", sys.getsizeof(d), "basicsize", type(d).__basicsize__)
# Uniqueness of fresh zeros
z1, z2 = G.mpfr(0, 320), G.mpfr(0, 320)
print("fresh zeros distinct objects:", z1 is not z2, "precision", z1.precision)
