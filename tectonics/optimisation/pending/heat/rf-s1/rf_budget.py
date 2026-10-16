"""Budget sweep: minimum accepted WorkBudget for r4 and r5, plus outcome comparison in the band."""
import sys
import time
import rf_common as c
import rf_systems as S

kinds = sys.argv[1].split(',')
t0 = time.time()


def passes(mod, args, b):
    out, used = c.call(mod, args, budget_bytes=b)
    return out, used


for name in kinds:
    args = S.swap() if name == 'swap' else S.author(name)
    res = {}
    for label, mod in (('r4', c.Q4), ('r5', c.Q5)):
        lo, hi = 150_000, 1 << 34   # lo fails, hi passes
        o, u = passes(mod, args, hi)
        assert o[0] in ('passed', 'refused'), o
        full_outcome = o[0]
        while hi-lo > 64:
            mid = (lo+hi)//2
            o, u = passes(mod, args, mid)
            # "ok" means same class as unlimited-budget outcome
            if o[0] == full_outcome and not (o[0] == 'refused' and 'memory' in o[2].lower()):
                hi = mid
            else:
                lo = mid
        res[label] = hi
    print(name, 'unlimited-outcome', full_outcome, 'min accepted budget r4 %d r5 %d diff %d' % (res['r4'], res['r5'], res['r4']-res['r5']))
    # grid comparison from just below r5-min to just above r4-min
    lo_b, hi_b = res['r5']-4096, res['r4']+4096
    both = r4only = r5only = diff = 0
    pts = sorted(set([lo_b + (hi_b-lo_b)*i//40 for i in range(41)] + [res['r5']-1, res['r5'], res['r4']-1, res['r4']]))
    rows = []
    for b in pts:
        o4, u4 = c.call(c.Q4, args, budget_bytes=b)
        o5, u5 = c.call(c.Q5, args, budget_bytes=b)
        p4, p5 = o4[0] == full_outcome and 'memory' not in (o4[2] if len(o4) > 2 and isinstance(o4[2], str) else ''), \
            o5[0] == full_outcome and 'memory' not in (o5[2] if len(o5) > 2 and isinstance(o5[2], str) else '')
        if p4 and p5:
            both += 1
            if full_outcome == 'passed' and o4[1] != o5[1]:
                diff += 1
                print('  VALUE DIFF at', b)
        elif p4 and not p5:
            r4only += 1
            print('  R4 OK, R5 NOT at', b, o5[:3])
        elif p5 and not p4:
            r5only += 1
        if u4 or u5:
            print('  LEAK at', b, u4, u5)
        rows.append((b, o4[0], o4[1] if o4[0] == 'exc' else (o4[2][:60] if o4[0] == 'refused' else ''),
                     o5[0], o5[1] if o5[0] == 'exc' else (o5[2][:60] if o5[0] == 'refused' else '')))
    print('  grid', len(pts), 'both-ok', both, 'r4-only-ok', r4only, 'r5-only-ok', r5only, 'value-diff', diff)
    kinds_seen = sorted(set((r[1], r[2], r[3], r[4]) for r in rows))
    for k_ in kinds_seen:
        print('   ', k_)
print('secs %.1f' % (time.time()-t0))
