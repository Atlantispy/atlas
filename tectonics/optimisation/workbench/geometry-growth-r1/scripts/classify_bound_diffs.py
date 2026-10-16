"""Classify exact bound differences between two replay arms (read-only)."""
import json
import sys
from collections import Counter
from fractions import Fraction as Q


def dq(p):
    return Q(int(p[0], 16), int(p[1], 16))


def load(path):
    out = {}
    for line in open(path, encoding='utf8'):
        r = json.loads(line)
        if not r.get('done'):
            out[(r['full_cell'], r['endpoint'])] = r
    return out


a, b = load(sys.argv[1]), load(sys.argv[2])   # a = baseline (r7), b = candidate (rc1)
kinds = Counter()
width = Counter()
examples = []
for k, ra in a.items():
    rb = b[k]
    if ra['exact'] == rb['exact']:
        continue
    la, ua, wa = map(dq, ra['exact'])
    lb, ub, wb = map(dq, rb['exact'])
    lower = 'same' if la == lb else 'looser' if lb < la else 'tighter'
    upper = 'same' if ua == ub else 'looser' if ub > ua else 'tighter'
    overlap = max(la, lb) <= min(ua, ub)
    kinds[(lower, upper, 'overlap' if overlap else 'DISJOINT', k[1], 'witness-same' if wa == wb else 'witness-diff')] += 1
    width['candidate wider' if ub - lb > ua - la else 'candidate narrower' if ub - lb < ua - la else 'same width'] += 1
    if len(examples) < 6:
        examples.append(dict(cell=k[0][:16], endpoint=k[1], base=[float(la), float(ua), float(wa)],
                             cand=[float(lb), float(ub), float(wb)], base_leaves=ra['leaves'], cand_leaves=rb['leaves']))
print(json.dumps(dict(differences=sum(kinds.values()), kinds={'|'.join(k): v for k, v in kinds.items()},
                      width=dict(width), examples=examples), indent=1))
