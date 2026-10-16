import sys, ctypes
T = 'C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10'
sys.path[:0] = ['C:/Users/LOCAL_USER/h13l1/runtime-src', T + '/ck/work/h3out']
import gmpy2 as G
import private_heat_compiled_dot_r1 as C
rng = lambda: (C.mpfr_get_emin(), C.mpfr_get_emax())
print('default', rng())
with G.context(emin=-100, emax=100):
    print('inside with narrow ctx', rng()); x = G.mpfr(2)**200; print(' op inside', x, rng())
G.set_context(G.context(emin=-100, emax=100)); print('after set_context narrow', rng())
try:
    G.mpfr(2)**300
except Exception as e:
    print(' op raised', type(e).__name__)
print('after op', rng())
# hash/rc/cache sanity of produced objects
G.set_context(G.context())
down, up = G.context(precision=320, round=G.RoundDown), G.context(precision=320, round=G.RoundUp)
a = (G.mpfr(1)/3, G.mpfr(2)/3)
out = C.pair_dots([[a, a]], [[a, a]], down, up)
lo, hi = out[0][0]
ref_lo = down.add(down.add(G.mpfr(0, 320), down.mul(a[0], a[0])), down.mul(a[0], a[0]))
print('hash equal', hash(lo) == hash(ref_lo), 'value equal', lo == ref_lo, 'rc', lo.rc, ref_lo.rc, 'prec', lo.precision)
del out, lo, hi
fresh = [G.mpfr(0, 320) for _ in range(20)]
print('fresh-from-cache all +0 rc0:', all(v == 0 and not v.is_signed() and v.rc == 0 and v.precision == 320 for v in fresh))
