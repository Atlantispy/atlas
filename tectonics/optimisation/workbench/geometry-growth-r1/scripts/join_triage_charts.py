"""Join IV2 triage rows with the IV1->IV2 chart-emptiness census (read-only).

Reports how many IV2 queries, CPU seconds and capped (stall) queries belong to
next charts that (b) proves empty, i.e. would not exist with (b).
"""
import json
import sys
from collections import Counter, defaultdict

census_path, *triage = sys.argv[1:]
census = json.load(open(census_path))['rows']
proved = {r['chart'] for r in census if r['proved']}
all_charts = {r['chart'] for r in census}
rows = []
for path in triage:
    for line in open(path, encoding='utf8'):
        r = json.loads(line)
        if not r.get('done'):
            rows.append(r)
tally = defaultdict(Counter)
for r in rows:
    group = ('removed by (b)' if r['chart'] in proved else
             'kept (inherited)' if r['chart'] in all_charts else 'birth/new chart')
    t = tally[group]
    t['queries'] += 1
    t['cpu_s'] += r['cpu_s']
    t['capped'] += r['status'] == 'capped'
    t['components_end'] += r['endpoint'] == 'end'
    t['exact_zero_results'] += bool(r.get('upper_zero'))
out = {k: {kk: (round(vv, 2) if isinstance(vv, float) else vv) for kk, vv in v.items()} for k, v in tally.items()}
capped = [r for r in rows if r['status'] == 'capped']
out['capped_charts'] = Counter('removed' if r['chart'] in proved else 'kept' if r['chart'] in all_charts else 'birth'
                               for r in capped)
print(json.dumps(out, indent=1))
