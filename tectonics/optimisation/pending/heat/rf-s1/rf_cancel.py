"""Cancellation sweep: cancel callback fires from tick K on. Compare r4/r5 outcomes, leaks, totals."""
import sys
import time
import rf_common as c
import rf_systems as S

t0 = time.time()
DEADLINE = float(sys.argv[2])


class Tick:
    def __init__(self, k):
        self.n, self.k = 0, k

    def __call__(self):
        self.n += 1
        return self.n >= self.k


for name in sys.argv[1].split(','):
    args = S.swap() if name == 'swap' else S.author(name)
    tot = {}
    for label, mod in (('r4', c.Q4), ('r5', c.Q5)):
        t = Tick(10**12)
        o, u = c.call(mod, args, cancelled=t)
        assert o[0] == 'passed'
        tot[label] = t.n
    print(name, 'total cancel-callback ticks r4', tot['r4'], 'r5', tot['r5'])
    ks = sorted(set([1, 2, 5, 17, tot['r5']-2, tot['r5']-1, tot['r5'], tot['r5']+1, tot['r5']+2, tot['r4']-1, tot['r4'], tot['r4']+1] +
                    [tot['r4']*i//24 for i in range(1, 24)]))
    odd = []
    for k in ks:
        if time.time()-t0 > DEADLINE:
            print('  deadline hit at k', k)
            break
        res = {}
        for label, mod in (('r4', c.Q4), ('r5', c.Q5)):
            o, u = c.call(mod, args, cancelled=Tick(k))
            res[label] = (o[0] if o[0] != 'exc' else o[1], u, o)
        done4, done5 = res['r4'][0] == 'passed', res['r5'][0] == 'passed'
        if res['r4'][1] or res['r5'][1]:
            odd.append(('LEAK', k, res['r4'][:2], res['r5'][:2]))
        if done4 and done5 and res['r4'][2][1] != res['r5'][2][1]:
            odd.append(('VALUEDIFF', k))
        if done4 and not done5:
            odd.append(('R4 DONE, R5 CANCELLED/FAILED', k, res['r5'][0]))
        if done5 and not done4:
            odd.append(('r5 completes, r4 cancelled', k, res['r4'][0]))
        for lab in ('r4', 'r5'):
            if res[lab][0] not in ('passed', 'CancelledError'):
                odd.append(('OTHER', k, lab, res[lab][0], res[lab][2][:3]))
    print('  K tested', len(ks))
    summary = {}
    for o in odd:
        summary[o[0]] = summary.get(o[0], 0)+1
    print('  anomalies', summary)
    for o in odd[:6]:
        print('   ', o)
print('secs %.1f' % (time.time()-t0))
