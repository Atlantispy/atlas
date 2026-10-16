import sys, ctypes
sys.path[:0] = ['C:/Users/LOCAL_USER/h13l1/runtime-src']
from concurrent.futures import CancelledError
print('python', sys.version)
print('CancelledError mro', [c.__name__ for c in CancelledError.__mro__])
from atlas_tectonics.exact_arithmetic import library
G = library()
print('G is gmpy2', G.__name__, G.version(), G.mpfr_version())
from pathlib import Path
dll = ctypes.CDLL(str(Path(G.__file__).resolve().parent.parent/'gmpy2.libs'/'libmpfr-6.dll'))
for name in ('mpfr_buildopt_tls_p', 'mpfr_buildopt_sharedcache_p'):
    f = getattr(dll, name); f.restype = ctypes.c_int; print(name, f())
dll.mpfr_get_emin.restype = ctypes.c_long; dll.mpfr_get_emax.restype = ctypes.c_long
print('mpfr emin/emax', dll.mpfr_get_emin(), dll.mpfr_get_emax(), 'ctx', G.context().emin, G.context().emax)
f = dll.mpfr_get_emin_min; f.restype = ctypes.c_long; print('emin_min', f())
for p in (1, 2, 3, 64):
    try:
        c = G.context(precision=p)
        print('p', p, 'context ok; mpfr(0,p).precision =', G.mpfr(0, p).precision, 'ctx mpfr(0).precision', G.mpfr(0, 0).precision)
    except Exception as e:
        print('p', p, type(e).__name__, e)
