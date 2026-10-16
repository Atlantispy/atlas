"""G, part 2: exact counts on the rebuilt IV2 partition (read-only).

(a) stored vs referenced constraints on IV2 supports; IV3 chart groups that IV2
pieces would seed (prepare_interval_partition's key) with their literal counts
and carried depths. Uses the same census functions as growth_count.py.
"""
import gzip
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from growth_count import constraint_census, depth, enc  # noqa: E402

supports_path, out_path = sys.argv[1], Path(sys.argv[2])
if out_path.exists():
    raise SystemExit('output exists')
supports = []
with gzip.open(supports_path, 'rt', encoding='utf8') as f:
    header = json.loads(f.readline())
    for line in f:
        supports.append(json.loads(line))
census = constraint_census(supports)
groups = {}
kinds = Counter()
parents = Counter()
for s in supports:
    layer = enc(s['radial_layer'])
    for c in s['components']:
        key = (s['source_chart_id'], tuple(map(str, c['partition_path'])), s['plate_id'], layer)
        if key not in groups:
            groups[key] = dict(literals=len(c['constraints']),
                               depth=Counter(depth(s['constraints'][n]) + 1 for n, _ in c['constraints']),
                               members=0)
        groups[key]['members'] += 1
        kinds[s['kind']] += 1
        parents['identity child' if c.get('parent_cell_id') else 'sibling/birth'] += 1
lit_depth = Counter()
for g in groups.values():
    lit_depth.update(g['depth'])
result = dict(schema='atlas.private.geometry-growth-count-iv2.r1', interval_id=header['interval_id'],
              supports=len(supports), components=census['components'], component_kinds=dict(kinds),
              start_identity=dict(parents), a_iv2_supports=census,
              iv3_chart_groups=len(groups), iv3_chart_literals=sum(g['literals'] for g in groups.values()),
              iv3_literal_depths=dict(sorted(lit_depth.items())))
with out_path.open('x', encoding='utf8') as f:
    json.dump(result, f, indent=1, sort_keys=True)
print(json.dumps(result, indent=1, sort_keys=True))
