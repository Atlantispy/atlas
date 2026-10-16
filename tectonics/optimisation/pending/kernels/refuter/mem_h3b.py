import sys, runpy
T = 'C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10'
import psutil
p = psutil.Process()
def dlls(): return {m.path.lower() for m in p.memory_maps()}
sys.argv = ['x']
before_mods = set(sys.modules)
g = {}
src = open(T + '/ck/refuter/mem_h3.py').read()
cut = src.index("t = time.perf_counter()\nC.pair_dots")
exec(compile(src[:cut], 'pre', 'exec'), g)
d0, m0 = dlls(), set(sys.modules)
exec(compile(src[cut:], 'post', 'exec'), g)
d1, m1 = dlls(), set(sys.modules)
print('new DLLs/maps after first batch:', sorted(d1-d0)[:20])
print('new modules after first batch (count %d):' % len(m1-m0), sorted(m for m in m1-m0 if '.' not in m)[:30])
