"""Run r8 LG.capture() (receipt + sha check + json) on the three REAL r9 operands. Read-only."""
import importlib.util, json
from pathlib import Path
HERE = Path(__file__).resolve().parent
T = HERE.parents[3]
spec = importlib.util.spec_from_file_location('lg', T/'so/s2/r8/ledger_fresh_interval.py')
LG = importlib.util.module_from_spec(spec); spec.loader.exec_module(LG)
D = T/'fidelity-integration-20261005/continuation-repair-20261013/recovery-r9'
rec = json.loads((D/'heat-original-connected-20261013-r9.json').read_text(encoding='utf8'))
def find(o, out):
    if isinstance(o, dict):
        if 'raw_sha256' in o and 'path' in o: out.append(o)
        for v in o.values(): find(v, out)
    elif isinstance(o, list):
        for v in o: find(v, out)
rows = []; find(rec, rows)
seen = set()
for row in rows:
    if row['path'] in seen: continue
    seen.add(row['path'])
    got = LG.capture(D/'heat-original-connected-20261013-r9.artifacts', row)
    print(row['path'], row['raw_bytes'], row.get('gzip_bytes'), 'capture() OK; keys', sorted(got)[:3] if isinstance(got, dict) else type(got))
