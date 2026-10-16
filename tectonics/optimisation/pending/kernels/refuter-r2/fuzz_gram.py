import sys, random
T = 'C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10'
sys.argv = ['x']
src = open(T + '/ck/refuter-r2/fuzz_h3.py').read()
exec(compile(src[:src.index('mism = []')], 'fuzz_h3', 'exec'))
rng2 = random.Random(11)
def free_iv(p):
    def v():
        k = rng2.random()
        s = rng2.choice((1, -1))
        if k < 0.3: return mk((s*rng2.choice((1, 3, 5, 0.75)), rng2.choice((B-1, -B+1, 0, 1, -1, B//2))), rng2.choice((p, 2, 53, 3*p)))
        return mk(s*rng2.choice((1, 2, 3, 0.5)), rng2.choice((p, 2)))
    a, b = v(), v()
    return (a, b) if a <= b else (b, a)
def nonfree_iv(p):
    return rng2.choice(((mk(0, p), mk(1, p)), (-mk(0, p), mk(2, p)), (mk(-1, p), -mk(0, p)), (mk(-2, p), mk(0, p)), (mk(3, p), mk(1, p))))
bad = 0; total = 0
for case in range(400):
    p = rng2.choice((320, 640, 2, 53))
    n, L = rng2.randint(2, 6), rng2.randint(1, 6)
    rows = [[(nonfree_iv(p) if rng2.random() < 0.08 else free_iv(p)) for _ in range(L)] for _ in range(n)]
    r, h = ref(p, rows, rows), h3(p, rows, rows, gram=True)
    total += 1
    if not (same(r[0], h[0]) and r[1] == h[1] and r[2] == h[2]):
        bad += 1
        if bad <= 2: print('MISMATCH p', p, rows, r[1], h[1])
print('gram cases', total, 'mismatches', bad, stats)
