"""Refuter: H3 batch (with r1 fallback) vs r1 Arithmetic.dot on adversarial intervals."""
import importlib.util, sys, random, time
T = 'C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10'
sys.path[:0] = ['C:/Users/LOCAL_USER/h13l1/runtime-src', T + '/ck/work/h3out-r2']

def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m

K1 = load('k_r1', 'C:/Users/LOCAL_USER/h13l1/helpers/private_heat_certification_kernel_r1.py')
K3 = load('k_h3', T + '/ck/work/h3out-r2/private_heat_certification_kernel_r1.py')
G = K1.G

def same(x, y):
    if type(x) is not type(y):
        return False
    if type(x) is G.mpfr:
        return (x.precision == y.precision and x.rc == y.rc and G.to_binary(x) == G.to_binary(y)
                and x.is_signed() == y.is_signed())
    if isinstance(x, (tuple, list)):
        return len(x) == len(y) and all(same(a, b) for a, b in zip(x, y))
    return x == y

def ref(prec, xs, ys):
    ar = K1.Arithmetic(prec, evidence={})
    try:
        return [[ar.dot(x, y) for y in ys] for x in xs], None, ar.evidence.get('phase')
    except Exception as e:
        return None, (type(e).__name__, str(e)), ar.evidence.get('phase')

stats = dict(batch=0, declined=0)
def h3(prec, xs, ys, gram=False):
    ar = K3.Arithmetic(prec, evidence={})
    try:
        a = K3._h3_batch(ar, xs, ys, gram=gram)
        if a is None:
            stats['declined'] += 1
            a = [[ar.dot(x, y) for y in ys] for x in xs]
        else:
            stats['batch'] += 1
            ar.check('interval-add')
        return a, None, ar.evidence.get('phase')
    except Exception as e:
        return None, (type(e).__name__, str(e)), ar.evidence.get('phase')

def mk(v, p, rnd=G.RoundToNearest):
    with G.context(precision=p, round=rnd, emin=G.context().emin, emax=G.context().emax):
        return G.mpfr(v) if not isinstance(v, tuple) else G.mul_2exp(G.mpfr(v[0]), v[1])

B = 1 << 28
rng = random.Random(7)
def special_value(p):
    k = rng.random()
    if k < 0.10: return mk(0, p) if rng.random() < 0.5 else -mk(0, p)
    if k < 0.13: return mk('inf', p) * rng.choice((1, -1))
    if k < 0.15: return mk('nan', p)
    if k < 0.40:  # near the exponent band and near emin/emax
        e = rng.choice((B-2, B-1, B, B+1, -B, -B+1, -B+2, -B-1, (1 << 29), -(1 << 29), (1 << 29)+5,
                        -(1 << 29)-5, 1073741800, -1073741800, 3, -3, 0))
        return mk((rng.choice((1, -1, 3, -3, 0.75, -0.75)), e), rng.choice((p, 53, 2*p+7, 2)))
    if k < 0.70:  # small integers -> many equal products, exact cancellations
        return mk(rng.choice((1, -1, 2, -2, 3, -3, 0.5, -0.5)), rng.choice((p, 53, 2)))
    return mk(rng.uniform(-4, 4), rng.choice((p, 53, 4*p+3)))

def interval(p):
    a, b = special_value(p), special_value(p)
    k = rng.random()
    if k < 0.15: return (a, a)          # equal endpoints (same object)
    if k < 0.25: return (b, a)          # possibly lo > hi
    return (a, b) if (G.is_nan(a) or G.is_nan(b) or a <= b) else (b, a)

mism = []
t0 = time.perf_counter()
cases = 0
for case in range(1500):
    p = rng.choice((320, 640, 2, 3, 53))
    nx, ny, L = rng.randint(1, 3), rng.randint(1, 3), rng.randint(1, 4)
    xs = [[interval(p) for _ in range(L)] for _ in range(nx)]
    ys = [[interval(p) for _ in range(L)] for _ in range(ny)]
    gram = rng.random() < 0.3
    if gram:
        ys = xs
    r = ref(p, xs, ys)
    h = h3(p, xs, ys, gram=gram)
    cases += 1
    if not (same(r[0], h[0]) and r[1] == h[1] and r[2] == h[2]):
        mism.append((p, gram, xs, ys, r, h))
print('cases', cases, stats, 'mismatches', len(mism), 'seconds', round(time.perf_counter()-t0, 1))
for p, gram, xs, ys, r, h in mism[:4]:
    print('---- p', p, 'gram', gram)
    print(' xs', xs); print(' ys', ys)
    print(' r1', r[1], r[2], r[0] and [[(v[0], v[0].rc, v[1], v[1].rc, v[0].precision) for v in row] for row in r[0]])
    print(' h3', h[1], h[2], h[0] and [[(v[0], v[0].rc, v[1], v[1].rc, v[0].precision) for v in row] for row in h[0]])

# precision 1 (accepted by gmpy2 context and by solve_enclosure; G.mpfr(0, 1) is 64-bit)
xs = [[(mk(3, 2), mk(3, 2)), (mk(5, 3), mk(7, 3))]]
ys = [[(mk(5, 3), mk(5, 3)), (mk(3, 2), mk(3, 2))]]
r, h = ref(1, xs, ys), h3(1, xs, ys)
print('precision-1 r1', r[0], [v.precision for v in r[0][0][0]] if r[0] else r[1])
print('precision-1 h3', h[0], [v.precision for v in h[0][0][0]] if h[0] else h[1], 'same', same(r[0], h[0]))
