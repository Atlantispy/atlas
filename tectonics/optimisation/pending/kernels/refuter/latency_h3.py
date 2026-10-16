import sys, time, random, threading
T = 'C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10'
sys.path[:0] = ['C:/Users/LOCAL_USER/h13l1/runtime-src', T + '/ck/work/h3out']
import gmpy2 as G
import private_heat_compiled_dot_r1 as C
rng = random.Random(1)
for p in (320, 2560):
    down, up = G.context(precision=p, round=G.RoundDown), G.context(precision=p, round=G.RoundUp)
    n, m = 40, 200
    def iv():
        x = G.mpfr(rng.uniform(-3, 3), p)
        return (down.sub(x, G.mpfr(1e-30)), up.add(x, G.mpfr(1e-30)))
    cols = [[iv() for _ in range(m)] for _ in range(n)]
    w = cols[:1]; C.pair_dots(w, w, down, up, gram=True)
    t = time.perf_counter(); C.pair_dots(cols, cols, down, up, gram=True); dt = time.perf_counter()-t
    print('p', p, 'gram n=%d m=%d: %.3f s, %.0f ns per interval product (computed half)' % (n, m, dt, dt/(n*(n+1)/2*m)*1e9))
# overflow detection inside a worker thread (MPFR TLS flags) while main thread does gmpy2 work
down, up = G.context(precision=320, round=G.RoundDown), G.context(precision=320, round=G.RoundUp)
big = G.mul_2exp(G.mpfr(1), 1073741000)
res = {}
def worker():
    try:
        C.pair_dots([[(big, big)]], [[(big, big)]], down, up); res['w'] = 'number'
    except C.Unavailable as e:
        res['w'] = 'Unavailable: %s' % e
th = threading.Thread(target=worker); th.start()
for _ in range(20000):
    G.mpfr(1)/3
th.join(); print('thread overflow ->', res['w'])
