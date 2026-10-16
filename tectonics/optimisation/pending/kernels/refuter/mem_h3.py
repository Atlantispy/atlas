"""Refuter: process memory/time added by the H3 route (numba import + first-batch JIT)."""
import ctypes, sys, time
from ctypes import wintypes
T = 'C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10'
sys.path[:0] = ['C:/Users/LOCAL_USER/h13l1/runtime-src', T + '/ck/work/h3out']
class PMC(ctypes.Structure):
    _fields_ = [('cb', wintypes.DWORD), ('PageFaultCount', wintypes.DWORD), ('PeakWorkingSetSize', ctypes.c_size_t),
                ('WorkingSetSize', ctypes.c_size_t), ('QuotaPeakPagedPoolUsage', ctypes.c_size_t),
                ('QuotaPagedPoolUsage', ctypes.c_size_t), ('QuotaPeakNonPagedPoolUsage', ctypes.c_size_t),
                ('QuotaNonPagedPoolUsage', ctypes.c_size_t), ('PagefileUsage', ctypes.c_size_t),
                ('PeakPagefileUsage', ctypes.c_size_t), ('PrivateUsage', ctypes.c_size_t)]
k32 = ctypes.WinDLL('kernel32'); k32.GetCurrentProcess.restype = wintypes.HANDLE
psapi = ctypes.WinDLL("psapi"); psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD]
def mem():
    c = PMC(); c.cb = ctypes.sizeof(c)
    psapi.GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(c), c.cb)
    return dict(private_MiB=round(c.PrivateUsage/2**20, 1), peak_private_MiB=round(c.PeakPagefileUsage/2**20, 1),
                ws_MiB=round(c.WorkingSetSize/2**20, 1), peak_ws_MiB=round(c.PeakWorkingSetSize/2**20, 1))
import gmpy2 as G
import numpy
print('base (gmpy2+numpy)', mem())
t = time.perf_counter()
import private_heat_compiled_dot_r1 as C
print('after import compiled helper (numba) %.2fs' % (time.perf_counter()-t), mem())
with G.context(precision=320, round=G.RoundDown, trap_underflow=True, trap_overflow=True, trap_invalid=True, trap_divzero=True, trap_erange=True) as d:
    pass
down = G.context(precision=320, round=G.RoundDown); up = G.context(precision=320, round=G.RoundUp)
rows = [[(G.mpfr(1), G.mpfr(2)), (G.mpfr(-3), G.mpfr(0))]]
t = time.perf_counter()
C.pair_dots(rows, rows, down, up, gram=True)
print('after first batch (JIT compile) %.2fs' % (time.perf_counter()-t), mem())
import psutil
