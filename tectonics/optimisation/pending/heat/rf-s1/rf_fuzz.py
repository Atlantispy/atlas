"""Differential fuzz r4 vs r5 over random closed systems. argv: seed count deadline_s"""
import random
import sys
import time
from fractions import Fraction as F
import rf_common as c

seed, count, deadline = int(sys.argv[1]), int(sys.argv[2]), float(sys.argv[3])
rnd = random.Random(seed)


def rq(lo, hi, den):
    return F(rnd.randint(lo*den, hi*den), den)


def gen():
    kind = rnd.choice(['rand', 'rand', 'rand', 'swap', 'lowold', 'bigden', 'single', 'tight'])
    if kind == 'single':
        cap = [rq(1, 5, 7)]
        t = [rq(250, 350, 3)]
        old = [cap[0]*t[0]]
        return kind, c.build(old, cap, [], [], [], [t[0]-1, t[0]+1])
    if kind == 'swap':
        cap = [rq(1, 4, 5)]*2
        a, b = rq(100, 400, 1), rq(100, 400, 1)
        old = [cap[0]*a, cap[1]*b]
        ql = rq(0, 1, 50)*(old[0]-old[1])/3
        qh = old[0]-old[1]  # candidate swaps the stocks exactly
        t = [a, b]
        return kind, c.build(old, cap, [(0, 1)], [ql], [qh], [min(a, b)-5, max(a, b)+5])
    n = rnd.randint(2, 7)
    den = 10**rnd.choice([0, 1, 3]) if kind != 'bigden' else 10**30+7
    caps = [rq(1, 6, 7)*rnd.choice([1, 1]) if kind != 'tight' else F(2) for _ in range(n)]
    temps = [rq(250, 350, den if den > 1 else 1) for _ in range(n)]
    old = [cc*t for cc, t in zip(caps, temps, strict=True)]
    pairs = [(i, i+1) for i in range(n-1)]
    for _ in range(rnd.randint(0, 3)):
        i, j = rnd.sample(range(n), 2)
        if (i, j) not in pairs and (j, i) not in pairs:
            pairs.append((i, j))
    k = rnd.choice([F(1, 4), F(1, 13), F(1, 3), F(2, 7)])
    low_q = [k*(temps[i]-temps[j]) for i, j in pairs]
    if kind == 'lowold':
        low_q = [F(0)]*len(pairs)
    scale = rnd.choice([F(-3), F(-1), F(0), F(1, 3), F(1), F(3, 2), F(2), F(7), F(40), F(1000), F(-1, 2)])
    if kind == 'lowold':
        high_q = [rq(-3, 3, 11) for _ in pairs]
    else:
        high_q = [scale*v for v in low_q]
    # bounds: hull of old temps widened by a random amount, sometimes tight against low
    lows = [e for e in old]
    delta = rnd.choice([F(0), F(1, 8), F(1), F(5), F(-1, 8)])
    if kind == 'tight':
        delta = rnd.choice([F(0), F(-1, 8), F(1, 16)])
    bounds = [min(temps)-delta, max(temps)+delta]
    return kind, c.build(old, caps, pairs, low_q, high_q, bounds)


stats = {}
mismatch = []
t0 = time.time()
done = 0
for idx in range(count):
    if time.time()-t0 > deadline:
        break
    kind, args = gen()
    o4, u4 = c.call(c.Q4, args)
    o5, u5 = c.call(c.Q5, args)
    # compare everything except the inventory (documented to change) for passed; full tuple for refusals/exceptions
    if o4[0] == 'passed' and o5[0] == 'passed':
        same = o4[1] == o5[1]
        cls = 'passed'
        th = dict(o4[1][1])['theta']
        cls += ':theta1' if th == ('q', 1, 1) else ':theta0' if th == ('q', 0, 1) else ':mid'
        route = repr(o4[1])
        if 'EXACT_ZERO_STRADDLING_FALLBACK' in route:
            cls += '+fallback'
    else:
        same = o4 == o5
        cls = o4[0]+':'+(o4[1] if o4[0] == 'exc' else '')
    stats[(kind, cls)] = stats.get((kind, cls), 0)+1
    if not same or u4 != 0 or u5 != 0:
        mismatch.append((idx, kind, cls, o4[0], o5[0], u4, u5))
    done += 1
print('seed', seed, 'cases', done, 'secs %.1f' % (time.time()-t0))
for k_, v in sorted(stats.items()):
    print(' ', k_, v)
print('MISMATCHES', len(mismatch))
for m in mismatch[:10]:
    print(' ', m)
