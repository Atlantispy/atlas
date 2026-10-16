"""Attribute RC1-versus-r7 endpoint differences on IV1 to named RC1 changes (single-factor ablation).

Inputs: r7 (reference), RC1, and RC1 with each change switched off (cube, item15,
item11) plus all three off. For each query that differs between RC1 and r7, record
which ablations restore the r7 result exactly. Prints JSON; read-only.
"""
import json
import sys
from collections import Counter


def load(path):
    rows, tail = {}, None
    for line in open(path, encoding='utf8'):
        r = json.loads(line)
        if r.get('done'):
            tail = r
            continue
        rows[(r['support_index'], r['cell'], r['endpoint'])] = r
    return rows, tail


names = ['r7', 'rc1', 'nocube', 'item15off', 'item11off', 'alloff']
data = {n: load(p) for n, p in zip(names, sys.argv[1:7])}
ref = data['r7'][0]
summary = {}
for n in names[1:]:
    rows = data[n][0]
    summary[n] = dict(equal_to_r7=sum(rows[k]['exact'] == r['exact'] for k, r in ref.items()),
                      queries=len(rows), seconds=round(data[n][1]['seconds'], 2),
                      leaves=sum(r['leaves'] for r in rows.values()),
                      work_units=sum(r.get('work_units', 0) for r in rows.values()))
summary['r7'] = dict(queries=len(ref), seconds=round(data['r7'][1]['seconds'], 2),
                     leaves=sum(r['leaves'] for r in ref.values()),
                     work_units=sum(r.get('work_units', 0) for r in ref.values()))
causes = Counter()
for k, r in ref.items():
    if data['rc1'][0][k]['exact'] == r['exact']:
        continue
    restored = tuple(n for n in ('nocube', 'item15off', 'item11off') if data[n][0][k]['exact'] == r['exact'])
    causes['restored by ' + ('+'.join(restored) if restored else 'no single switch') +
           ('; all-off restores' if data['alloff'][0][k]['exact'] == r['exact'] else '; ALL-OFF DOES NOT RESTORE')] += 1
# Changes each switch makes relative to RC1 (what the item alters on its own).
own = {}
for n in ('nocube', 'item15off', 'item11off'):
    rows = data[n][0]
    own[n] = dict(results_changed_vs_rc1=sum(rows[k]['exact'] != data['rc1'][0][k]['exact'] for k in ref),
                  met_changed=sum(rows[k]['status'] != data['rc1'][0][k]['status'] for k in ref))
print(json.dumps(dict(arms=summary, rc1_vs_r7_differences=sum(causes.values()), attribution=dict(causes),
                      each_switch_vs_rc1=own), indent=1))
