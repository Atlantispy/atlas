"""Exact parity of a candidate replay against the RC1 baseline (same input, same harness).

Per query (support index, logical cell, endpoint):
  identical            same status and byte-identical measure record (sha)
  same-numbers         same exact lower/upper/witness and met; record differs (leaves/work only)
  settled-from-capped  baseline hit the CPU cap (unresolved); candidate result recorded
  VIOLATION            any difference in exact numbers or met outcome between two settled results
Prints JSON; exit status 1 on any violation.
"""
import argparse
import glob
import json
import sys
from collections import Counter


def load(patterns):
    rows, tails = {}, []
    for pattern in patterns:
        for path in sorted(glob.glob(pattern)):
            for line in open(path, encoding='utf8'):
                r = json.loads(line)
                if r.get('done'):
                    tails.append(r)
                    continue
                key = ((r['cell'], r['endpoint']) if BY_CELL else
                       (r['support_index'], r['cell'], r['endpoint']))   # 16-hex cell prefix in every row
                if key in rows:
                    raise SystemExit('duplicate query key: %r' % (key,))
                rows[key] = r
    return rows, tails


ap = argparse.ArgumentParser()
ap.add_argument('--baseline', nargs='+', required=True)
ap.add_argument('--candidate', nargs='+', required=True)
ap.add_argument('--by-cell', action='store_true', help='match by (cell, endpoint) only (supports re-identified)')
ap.add_argument('--dropped', help='JSON with dropped_cell_ids: baseline queries of dropped pieces must be exact zero')
args = ap.parse_args()
BY_CELL = args.by_cell
base, bt = load(args.baseline)
cand, ct = load(args.candidate)
dropped = set()
if args.dropped:
    dropped = {c[:16] for c in json.load(open(args.dropped))['dropped_cell_ids']}
tally, examples = Counter(), []
settled = Counter()
for key, b in base.items():
    c = cand.get(key)
    cell = key[0] if BY_CELL else key[1]
    if c is None:
        if cell in dropped:
            tally['dropped-by-(b)-baseline-exact-zero' if b.get('upper_zero') else
                  'dropped-by-(b)-baseline-capped' if b['status'] == 'capped' else 'VIOLATION-dropped-positive'] += 1
        else:
            tally['VIOLATION-missing-in-candidate'] += 1
        continue
    if b['status'] == 'capped':
        tally['settled-from-capped' if c['status'] == 'met' else 'still-' + c['status']] += 1
        if c['status'] == 'met':
            settled['exact-zero' if c.get('upper_zero') else 'positive']
        continue
    if c['status'] != b['status']:
        tally['VIOLATION-status'] += 1
        examples.append((key, b['status'], c['status']))
        continue
    if b.get('exact') != c.get('exact'):
        tally['VIOLATION-numbers'] += 1
        examples.append((key, b.get('exact'), c.get('exact')))
        continue
    if b.get('measure_sha') == c.get('measure_sha'):
        tally['identical'] += 1
    else:
        tally['same-numbers-record-differs'] += 1
tally['candidate-extra'] = len(set(cand) - set(base))
result = dict(baseline_queries=len(base), candidate_queries=len(cand), tally=dict(tally),
              baseline_cpu=round(sum(r['cpu_s'] for r in base.values()), 2),
              candidate_cpu=round(sum(r['cpu_s'] for r in cand.values()), 2),
              baseline_seconds=[round(t['seconds'], 1) for t in bt], candidate_seconds=[round(t['seconds'], 1) for t in ct],
              violations=examples[:10])
print(json.dumps(result, indent=1, default=str))
sys.exit(1 if any(k.startswith('VIOLATION') for k in tally) else 0)
