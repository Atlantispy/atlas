"""Structural parity of a growth-successor partition against its RC1 baseline (read-only).

Checks, for every kept support (matched by source chart, voxel, plate and layer):
  - every field identical except 'constraints';
  - candidate constraints == baseline constraints restricted to the names that
    component literals use ((a): nothing else removed, nothing changed);
  - components identical (logical ids, paths, literals, owner rays, parent ids,
    start identities).
Baseline supports with no kept counterpart must belong to charts (b) dropped, and
every component in them must be listed (for the endpoint-zero check).
Partition records: identical except support_ids, native_contacts' support_id
references (and contacts of dropped components), source_regions of dropped charts
and identity_start_cells of dropped pieces.
"""
import gzip
import json
import sys
from collections import Counter
from pathlib import Path


def load(path):
    return json.loads(gzip.decompress(Path(path).read_bytes()))


def key(s):
    return (s['source_chart_id'], tuple(s['voxel_index']), s['plate_id'], json.dumps(s['radial_layer'], sort_keys=True))


base, cand = load(sys.argv[1]), load(sys.argv[2])
bs = {key(s): s for s in base['supports']}
cs = {key(s): s for s in cand['supports']}
tally = Counter()
problems = []
kept_charts = {r['source_chart_id'] for r in cand['partition']['source_regions']}
dropped_cells = []
for k, b in bs.items():
    c = cs.get(k)
    if c is None:
        if b['source_chart_id'] in kept_charts:
            tally['PROBLEM-kept-chart-support-missing'] += 1
            problems.append(('missing', k[:2]))
        else:
            tally['support-of-dropped-chart'] += 1
            dropped_cells.extend(p['logical_cell_id'] for p in b['components'])
        continue
    if {f: v for f, v in b.items() if f != 'constraints'} != {f: v for f, v in c.items() if f != 'constraints'}:
        tally['PROBLEM-non-constraint-field-differs'] += 1
        problems.append(('fields', k[:2], sorted(f for f in b if b.get(f) != c.get(f))))
        continue
    used = {n for p in b['components'] for n, _ in p['constraints']}
    if c['constraints'] != {n: v for n, v in b['constraints'].items() if n in used}:
        tally['PROBLEM-constraints-not-exact-restriction'] += 1
        problems.append(('constraints', k[:2]))
        continue
    tally['support-identical-except-unreferenced-constraints'] += 1
    tally['constraints-removed'] += len(b['constraints']) - len(c['constraints'])
tally['candidate-supports-without-baseline'] = len(set(cs) - set(bs))
bp, cp = base['partition'], cand['partition']
fields = sorted(set(bp) | set(cp))
differing = [f for f in fields if bp.get(f) != cp.get(f)]
expected = {'support_ids', 'native_contacts', 'source_regions', 'identity_start_cells'}
result = dict(baseline_partition=base.get('partition_id', (base.get('checks') or {}).get('partition_id')), candidate_partition=cand.get('partition_id'),
              dropped_charts=cand.get('dropped_charts'), tally=dict(tally),
              partition_fields_differing=differing,
              unexpected_partition_field_differences=sorted(set(differing) - expected),
              dropped_components=len(dropped_cells), problems=problems[:10])
if 'identity_start_cells' in differing:
    bi = {json.dumps(r, sort_keys=True) for r in bp['identity_start_cells']}
    ci = {json.dumps(r, sort_keys=True) for r in cp['identity_start_cells']}
    removed = bi - ci
    dropped = set(dropped_cells)
    result['identity_start_cells'] = dict(removed=len(removed), added=len(ci - bi),
        removed_all_dropped=all(json.loads(r)['cell_id'] in dropped for r in removed))
Path(sys.argv[3]).write_text(json.dumps(dict(result, dropped_cell_ids=dropped_cells)), encoding='utf8') if len(sys.argv) > 3 else None
print(json.dumps(result, indent=1))
sys.exit(1 if any(k.startswith('PROBLEM') for k in tally) or result['unexpected_partition_field_differences'] else 0)
