"""Summarise a replay JSONL; optionally compare IV1 results with the IV1 graph (store copy)."""
import argparse
import json
import sys
from collections import Counter, defaultdict
from fractions import Fraction as Q
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

IV1 = 'bc945eedff746d89992e474f4aa089eb333d03298e47a22f10ae6d54e0549bbc'


def dq(p):
    return Q(int(p[0], 16), int(p[1], 16))


ap = argparse.ArgumentParser()
ap.add_argument('replay', nargs='+')
ap.add_argument('--store')
ap.add_argument('--top', type=int, default=15)
args = ap.parse_args()
rows, tails = [], []
for path in args.replay:
    for line in open(path, encoding='utf8'):
        r = json.loads(line)
        (tails if r.get('done') else rows).append(r)
print('files', len(args.replay), 'queries', len(rows), 'tails', [dict(q=t['queries'], s=round(t['seconds'], 1)) for t in tails])
status = Counter(r['status'] for r in rows)
print('status', dict(status))
cpu = sum(r['cpu_s'] for r in rows)
wall = sum(r['wall_s'] for r in rows)
print('sum cpu %.1f s, sum wall %.1f s' % (cpu, wall))
by_ep = defaultdict(lambda: [0, 0.0])
for r in rows:
    k = (r['endpoint'], 'parent' if r['parent'] else 'sibling', r['status'])
    by_ep[k][0] += 1
    by_ep[k][1] += r['cpu_s']
for k, (n, s) in sorted(by_ep.items()):
    print('  ', k, n, 'queries', round(s, 1), 's')
zero = sum(1 for r in rows if r.get('upper_zero'))
print('results with exact zero upper', zero)
hist = Counter()
for r in rows:
    c = r['cpu_s']
    hist['<0.05' if c < .05 else '<0.2' if c < .2 else '<1' if c < 1 else '<5' if c < 5 else '<30' if c < 30 else '>=30'] += 1
print('cpu histogram', dict(hist))
leaves = Counter()
for r in rows:
    n = r['leaves']
    leaves['1' if n <= 1 else '<=8' if n <= 8 else '<=64' if n <= 64 else '<=1024' if n <= 1024 else '>1024'] += 1
print('leaf histogram', dict(leaves))
print('top cpu queries:')
for r in sorted(rows, key=lambda r: -r['cpu_s'])[:args.top]:
    print('   %.2fs %s ep=%s parent=%s lits=%d depth=%d leaves=%d lvl=%d zero/wit/und=%d/%d/%d up0=%s root=%s chart=%s path=%s' % (
        r['cpu_s'], r['status'], r['endpoint'], r['parent'], r['literals'], r['max_snapshot_depth'], r['leaves'],
        r['max_level'], r['zero_leaves'], r['witnessed_leaves'], r['undecided_leaves'], r.get('upper_zero'),
        r.get('root'), r['chart'], r['path']))
if args.store:
    from rawstore import RawStore
    store = RawStore(args.store)
    snaps = store.snapshots()
    graph = store.record(snaps[IV1], snaps[IV1]['metadata']['exterior_advance']['record_blobs']['graph'])
    store.close()
    cells = {c['cell_id'][:16]: c for c in graph['cells'] + graph['inactive_zero_measure_cells']}
    same = diff = missing = 0
    examples = []
    for r in rows:
        c = cells.get(r['cell'])
        if c is None or r.get('lower') is None:
            missing += 1
            continue
        key = 'true_%s_volume_bounds_m3' % r['endpoint']
        lo, hi = (float(dq(p)) for p in c[key])
        if (lo, hi) == (r['lower'], r['upper']) and (dq(c[key][1]) == 0) == r['upper_zero']:
            same += 1
        else:
            diff += 1
            if len(examples) < 5:
                examples.append((r['cell'], r['endpoint'], (lo, hi), (r['lower'], r['upper'])))
    print('IV1 graph comparison (float view + exact zero flag): same', same, 'different', diff, 'missing', missing)
    for e in examples:
        print('   ', e)
