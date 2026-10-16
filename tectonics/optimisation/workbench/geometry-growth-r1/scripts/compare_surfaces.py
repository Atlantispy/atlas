"""Exact parity of wall/interface replays (baseline vs candidate, same input and harness).

Key: (kind, support index, cell, paired cell, constraint name or axis/end).
identical: both settled with byte-identical measure records (sha of the canonical
record, which includes bounds, leaves, met and work_units). Any settled pair that
differs is a VIOLATION. Capped-in-baseline queries settled by the candidate are
counted separately (they are compared later on a deeper run).
"""
import argparse
import glob
import json
import sys
from collections import Counter


def load(patterns):
    rows, cpu, tails = {}, 0.0, []
    for pattern in patterns:
        for path in sorted(glob.glob(pattern)):
            for line in open(path, encoding='utf8'):
                r = json.loads(line)
                if r.get('done'):
                    tails.append(r)
                    continue
                if 'job_counts' in r:
                    continue
                key = (r['kind'], None if NUMBERS else r['support_index'], r['cell'], r.get('other'),
                       r.get('constraint_name') or (r.get('axis'), r.get('end')))
                if key in rows:
                    raise SystemExit('duplicate key %r' % (key,))
                rows[key] = r
                cpu += r['cpu_s']
    return rows, cpu, tails


ap = argparse.ArgumentParser()
ap.add_argument('--baseline', nargs='+', required=True)
ap.add_argument('--candidate', nargs='+', required=True)
ap.add_argument('--numbers', action='store_true',
                help='supports re-identified (growth successor): match by cell and compare bounds, '
                     'met, leaves, work_units and rule instead of the record hash')
ap.add_argument('--dropped', help='JSON with dropped_cell_ids: baseline rows of dropped pieces are reported apart')
ap.add_argument('--except-digests', action='store_true',
                help='coordinator D-b: compare the record hash with every source_sha256 value blanked; '
                     'also count how many pairs differ in their full hash (digest-only changes)')
args = ap.parse_args()
NUMBERS = args.numbers
EXCEPT_DIGESTS = args.except_digests
DROPPED = set()
if args.dropped:
    DROPPED = {c[:16] for c in json.load(open(args.dropped))['dropped_cell_ids']}


def same(b, c):
    if EXCEPT_DIGESTS:
        if b.get('measure_sha_nodigest') is None:
            raise SystemExit('--except-digests needs rows with measure_sha_nodigest (rerun the replay)')
        return b.get('measure_sha_nodigest') == c.get('measure_sha_nodigest')
    if not NUMBERS:
        return b.get('measure_sha') == c.get('measure_sha')
    return all(b.get(k) == c.get(k) for k in ('inward', 'outward', 'leaves', 'work_units', 'rule'))
base, bcpu, _ = load(args.baseline)
cand, ccpu, _ = load(args.candidate)
tally, examples = Counter(), []
cpu = Counter()
for key, b in base.items():
    c = cand.get(key)
    kind = key[0]
    if c is None:
        if key[2] in DROPPED or (key[3] is not None and key[3] in DROPPED):
            tally['%s:dropped-by-(b) baseline=%s' % (kind, b['status'])] += 1
        else:
            tally['missing-in-candidate'] += 1
        continue
    if b['status'] == 'capped' or c['status'] == 'capped':
        tally['%s:capped baseline=%s candidate=%s' % (kind, b['status'], c['status'])] += 1
        continue
    if b['status'] != c['status'] or not same(b, c):
        tally['VIOLATION-' + kind] += 1
        if len(examples) < 5:
            examples.append((key, b.get('measure_sha'), c.get('measure_sha'), b['status'], c['status']))
        continue
    if EXCEPT_DIGESTS and b.get('measure_sha') != c.get('measure_sha'):
        tally[kind + ':identical-except-source-digests'] += 1
    else:
        tally[kind + ':identical'] += 1
    cpu[kind + ':baseline'] += b['cpu_s']
    cpu[kind + ':candidate'] += c['cpu_s']
tally['candidate-extra'] = len(set(cand) - set(base))
print(json.dumps(dict(baseline=len(base), candidate=len(cand), tally=dict(sorted(tally.items())),
                      cpu_all=dict(baseline=round(bcpu, 1), candidate=round(ccpu, 1)),
                      cpu_identical_pairs={k: round(v, 1) for k, v in cpu.items()}, violations=examples),
                 indent=1, default=str))
# A candidate row that is missing (and not a (b) drop) fails the comparison: an empty or partial
# candidate must never pass vacuously (16 Oct: a failed candidate rebuild left 40,968 rows missing).
sys.exit(1 if any(k.startswith('VIOLATION') for k in tally) or tally['missing-in-candidate'] else 0)
