"""Read-only scan: which replayed interface jobs carry a COMPLEMENTARY cut pair?

Two clip literals are complementary when their constraint records name the same
physical plane with opposite orientation and the same sign (or the same record
with opposite signs): the cells then meet the face only on that plane. Detection
is syntactic on the stored records only:
  moving-ray-edge      identity = the ray pair up to order; orientation +1/-1;
  snapshot-rotated     identity = (wrapper fields, inner identity); orientation inner's;
  anything else        identity = the encoded record; orientation +1.
Joins the replay rows (status, cpu) of a surfaces replay by job key and tallies.
Usage: scan_complementary.py --supports S --replay 'glob' [--every 10]
"""
import argparse
import glob
import gzip
import json
from collections import Counter


def enc(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'))


def canon(record):
    kind = record.get('kind')
    if kind == 'moving-ray-edge' and len(record.get('rays', ())) == 2:
        forward, reverse = enc(record['rays']), enc(list(reversed(record['rays'])))
        return ('edge', min(forward, reverse)), (1 if forward <= reverse else -1)
    if kind == 'snapshot-rotated':
        inner = canon(record['constraint'])
        wrapper = enc({k: v for k, v in record.items() if k != 'constraint'})
        return ('snap', wrapper, inner[0]), inner[1]
    return ('record', enc(record)), 1


def complementary(literals, constraints):
    seen = {}
    pairs = []
    for name, sign in literals:
        identity, orientation = canon(constraints[name])
        side = sign * orientation
        for other_name, other_side in seen.get(identity, ()):
            if other_side == -side:
                pairs.append((other_name, name))
        seen.setdefault(identity, []).append((name, side))
    return pairs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--supports', required=True)
    ap.add_argument('--replay', required=True, help='glob of replay_surfaces JSONL rows')
    ap.add_argument('--list-capped', default=None, help='write the capped jobs (with the flag) to this JSONL')
    args = ap.parse_args()
    by_support, capped_rows = Counter(), []
    rows = {}
    for path in sorted(glob.glob(args.replay)):
        for line in open(path, encoding='utf8'):
            r = json.loads(line)
            if r.get('kind') == 'interface':
                rows.setdefault(r['support_index'], []).append(r)
    tally, cpu, examples = Counter(), Counter(), []
    with gzip.open(args.supports, 'rt', encoding='utf8') as f:
        f.readline()
        for index, line in enumerate(f):
            if index not in rows:
                continue
            record = json.loads(line)
            parts = {p['logical_cell_id'][:16]: p for p in record['components']}
            constraints = record['constraints']
            for r in rows[index]:
                part = parts[r['cell']]
                name = r['constraint_name']
                literals = [(n, s) for n, s in part['constraints'] if n != name]
                merged = dict(constraints)
                if r.get('other'):
                    other = parts[r['other']]
                    identity = canon(constraints[name])[0]
                    for n, s in other['constraints']:
                        if canon(constraints[n])[0] == identity:
                            continue          # the matched opposite interface itself
                        merged['neighbour:' + n] = constraints[n]
                        literals.append(('neighbour:' + n, s))
                pairs = complementary(literals, merged)
                key = ('paired' if r.get('other') else 'single', 'complementary' if pairs else 'none', r['status'])
                tally[key] += 1
                cpu[key] += r['cpu_s']
                if r['status'] == 'capped':
                    by_support[(index, key[1])] += 1
                    if args.list_capped:
                        capped_rows.append(dict(support_index=index, cell=r['cell'], other=r.get('other'),
                                                constraint_name=name, complementary=bool(pairs)))
                if pairs and r['status'] == 'met' and len(examples) < 8:
                    examples.append(dict(support_index=index, cell=r['cell'], other=r.get('other'), name=name,
                                         cpu_s=r['cpu_s'], leaves=r.get('leaves'), pairs=pairs[:2],
                                         inward=r.get('inward'), outward=r.get('outward')))
    if args.list_capped:
        with open(args.list_capped, 'x', encoding='utf8', newline='\n') as sink:
            for row in capped_rows:
                sink.write(json.dumps(row) + '\n')
    print(json.dumps(dict(tally={' / '.join(k): v for k, v in sorted(tally.items())},
                          cpu_s={' / '.join(k): round(v, 1) for k, v in sorted(cpu.items())},
                          capped_by_support=[[s, c, n] for (s, c), n in by_support.most_common(20)],
                          met_with_complementary_examples=examples[:2]), indent=1))


if __name__ == '__main__':
    main()
