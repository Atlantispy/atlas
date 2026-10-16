"""Refuter: solve_enclosure + physical_bounds through r1 and H3, incl. cancellation callables."""
import importlib.util, sys, random
T = 'C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10'
sys.path[:0] = ['C:/Users/LOCAL_USER/h13l1/runtime-src', T + '/ck/work/h3out']
def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m
K1 = load('k_r1', 'C:/Users/LOCAL_USER/h13l1/helpers/private_heat_certification_kernel_r1.py')
K3 = load('k_h3', T + '/ck/work/h3out/private_heat_certification_kernel_r1.py')
G = K1.G
rng = random.Random(3)
m, n = 5, 3
matrix = [[G.mpq(rng.randint(-9, 9), rng.randint(1, 7)) for _ in range(n)] for _ in range(m)]
rhs = [G.mpq(rng.randint(-9, 9), rng.randint(1, 5)) for _ in range(n)]
keys = [('cell', i) for i in range(m)]
base = (('cell', 0), ('wall', 1))
conv = [G.mpq(1, i+2) for i in range(m)]
tau = G.mpq(1, 3)

def same(x, y):
    if type(x) is not type(y): return False
    if type(x) is G.mpfr:
        return x.precision == y.precision and x.rc == y.rc and G.to_binary(x) == G.to_binary(y)
    if isinstance(x, (tuple, list)): return len(x) == len(y) and all(same(a, b) for a, b in zip(x, y))
    if isinstance(x, dict): return list(x) == list(y) and all(same(x[k], y[k]) for k in x)
    return x == y

def run(K, cancel_factory, where):
    ev = {}
    calls = [0]
    try:
        cancelled = cancel_factory(calls) if where == 'solve' else None
        dual, ar, proof = K.solve_enclosure(matrix, rhs, precision=320, cancelled=cancelled, evidence=ev)
        if where == 'physical':
            ar.cancelled = cancel_factory(calls)
        out = K.physical_bounds(matrix, dual, keys, base, tau, conv, ar)
        return ('ok', out, ev.get('phase'), calls[0])
    except Exception as e:
        return ('raise', (type(e).__name__, str(e)), ev.get('phase'), calls[0])

base1, base3 = run(K1, lambda c: None, 'none'), run(K3, lambda c: None, 'none')
print('plain: identical =', same(base1[1], base3[1]), base1[2], base3[2])
print('h3 status', K3.h3_status()['route'])

def one_shot(at):
    def factory(calls):
        def cancelled():
            calls[0] += 1
            return calls[0] == at
        return cancelled
    return factory

def sticky(at):
    def factory(calls):
        def cancelled():
            calls[0] += 1
            return calls[0] >= at
        return cancelled
    return factory

for at in (1, 2, n+1, n+2):
    r1, h3 = run(K1, one_shot(at), 'physical'), run(K3, one_shot(at), 'physical')
    print('one-shot cancel at check %d in physical_bounds:' % at)
    print('   r1:', r1[0], r1[1] if r1[0] == 'raise' else '', '| checks', r1[3])
    print('   h3:', h3[0], h3[1] if h3[0] == 'raise' else '', '| checks', h3[3])
for at in (1, n+1, n+2, m*n):
    r1, h3 = run(K1, sticky(at), 'physical'), run(K3, sticky(at), 'physical')
    print('sticky cancel from check %d: r1 %s | h3 %s' % (at, r1[1], h3[1]))
