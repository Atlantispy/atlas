"""WP20 probe: the exact Gordan certificate on every saved query, joined with the triage.

Soundness check: a query whose RC1 result has a positive witness (true volume > 0)
must never be proved zero. Coverage: which capped (stalled) queries it settles,
and how many already-zero queries it would also prove. Read-only; prints JSON.
"""
import gzip
import json
import sys
import time
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import rc1_env  # noqa: E402
import gordan  # noqa: E402

supports_path, out_path, *triage = sys.argv[1:]
out = Path(out_path)
if out.exists():
    raise SystemExit('output exists')
rc1_env.install()
from atlas_tectonics import integration_differential_geometry as G  # noqa: E402

results = {}
for path in triage:
    for line in open(path, encoding='utf8'):
        r = json.loads(line)
        if not r.get('done'):
            results[(r['support_index'], r['cell'], r['endpoint'])] = r
tally = Counter()
proved_rows = []
t0 = time.perf_counter()
cert_time = 0.0
with gzip.open(supports_path, 'rt', encoding='utf8') as f:
    f.readline()
    for index, line in enumerate(f):
        s = json.loads(line)
        for c in s['components']:
            t = time.perf_counter()
            cert = gordan.certificate(c['constraints'], s['constraints'], G._rigid_plane_path)
            cert_time += time.perf_counter() - t
            for endpoint in ('start', 'end'):
                r = results.get((index, c['logical_cell_id'][:16], endpoint))
                if r is None:
                    continue
                status = r['status']
                positive = (r.get('witness') or 0) > 0
                zero = bool(r.get('upper_zero'))
                key = ('proved' if cert else 'not-proved', status,
                       'witness>0' if positive else 'zero' if zero else 'undecided')
                tally[key] += 1
                if cert and positive:
                    tally['SOUNDNESS_VIOLATION'] += 1
                if cert and status == 'capped':
                    proved_rows.append(dict(support_index=index, cell=c['logical_cell_id'][:16], endpoint=endpoint,
                                            certificate=cert))
summary = dict(schema='atlas.private.wp20-gordan-probe.r1', tally={'|'.join(k) if isinstance(k, tuple) else k: v
                                                                    for k, v in sorted(tally.items())},
               capped_proved=len(proved_rows), certificate_seconds=round(cert_time, 3),
               seconds=round(time.perf_counter() - t0, 3), capped_examples=proved_rows[:3])
with out.open('x', encoding='utf8') as fo:
    json.dump(dict(summary, capped_proved_rows=proved_rows), fo, indent=1)
print(json.dumps(summary, indent=1)[:6000])
