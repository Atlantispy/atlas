"""Exact comparison of replay arms with each other and with r9's IV1 pre-closure bounds.

The r9 artifact preadvance-bounds.json.gz holds each IV1 cell's start/end volume
bounds as issued by the endpoint loop (before closure). Every replayed query's
exact lower/upper must equal it. Witness and leaves/work are compared between
arms only. Read-only; prints a JSON summary.
"""
import gzip
import json
import sys
from collections import Counter
from pathlib import Path


def load(path):
    rows, tail = {}, None
    for line in open(path, encoding='utf8'):
        r = json.loads(line)
        if r.get('done'):
            tail = r
            continue
        rows[(r['full_cell'], r['endpoint'])] = r
    return rows, tail


bounds_path, *arms = sys.argv[1:]
bounds = json.loads(gzip.decompress(Path(bounds_path).read_bytes()))
cells = {c['cell_id']: c for c in bounds['cells']}
summary = {}
loaded = {}
for path in arms:
    rows, tail = load(path)
    loaded[path] = rows
    same = diff = missing = 0
    for (cell, endpoint), r in rows.items():
        c = cells.get(cell)
        if c is None:
            missing += 1
            continue
        want = c['%s_volume_bounds_m3' % endpoint]
        if r['exact'][:2] == want:
            same += 1
        else:
            diff += 1
    summary[Path(path).name] = dict(queries=len(rows), seconds=round(tail['seconds'], 2) if tail else None,
        cpu_sum=round(sum(r['cpu_s'] for r in rows.values()), 2), equal_to_r9_bounds=same,
        different=diff, missing=missing, leaves=sum(r['leaves'] for r in rows.values()),
        work_units=sum(r.get('work_units', 0) for r in rows.values()),
        runtime=tail.get('runtime') if tail else None, route=tail.get('route') if tail else None)
names = list(loaded)
pairs = {}
for i, a in enumerate(names):
    for b in names[i + 1:]:
        ra, rb = loaded[a], loaded[b]
        common = set(ra) & set(rb)
        c = Counter()
        for k in common:
            c['exact_equal'] += ra[k]['exact'] == rb[k]['exact']
            c['measure_record_equal'] += ra[k].get('measure_sha') == rb[k].get('measure_sha')
            c['leaves_equal'] += ra[k]['leaves'] == rb[k]['leaves']
        pairs[Path(a).name + ' vs ' + Path(b).name] = dict(common=len(common), **c)
print(json.dumps(dict(arms=summary, pairs=pairs), indent=1))
