"""Diagnostic: compare two --trace-work replay rows call by call (first divergence + totals by caller)."""
import json
import sys
from collections import Counter


def rows(path):
    return [json.loads(line) for line in open(path, encoding='utf8') if line.strip()]


def main():
    a, b = rows(sys.argv[1]), rows(sys.argv[2])
    for ra, rb in zip(a, b):
        ta, tb = ra['trace'], rb['trace']
        print('query', ra['cell'], ra.get('other'), ra.get('constraint_name'), 'work', ra.get('work_units'), rb.get('work_units'),
              'calls', len(ta), len(tb), 'sum', sum(c for c, _, _ in ta), sum(c for c, _, _ in tb))
        arenas_a = {x for _, _, x in ta}
        arenas_b = {x for _, _, x in tb}
        print('  arenas', len(arenas_a), len(arenas_b))
        ca, cb = Counter(), Counter()
        for c, who, _ in ta:
            ca[who.split('<')[0] + '<' + who.split('<')[1] if '<' in who else who] += c
        for c, who, _ in tb:
            cb[who.split('<')[0] + '<' + who.split('<')[1] if '<' in who else who] += c
        for k in sorted(set(ca) | set(cb)):
            if ca[k] != cb[k]:
                print('  caller', k, ca[k], cb[k], cb[k] - ca[k])
        counts_a = [c for c, _, _ in ta]
        counts_b = [c for c, _, _ in tb]
        i = next((i for i, (x, y) in enumerate(zip(counts_a, counts_b)) if x != y), min(len(ta), len(tb)))
        print('  first divergence at call', i)
        for j in range(max(0, i - 3), min(i + 6, max(len(ta), len(tb)))):
            print('   ', j, ta[j][:2] if j < len(ta) else None, '|', tb[j][:2] if j < len(tb) else None)


if __name__ == '__main__':
    main()
