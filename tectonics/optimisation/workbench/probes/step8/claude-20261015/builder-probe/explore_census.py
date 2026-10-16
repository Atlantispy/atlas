"""Read-only: print the census entry for spatial-record:graph (fields, counts)."""
from hashlib import sha256
import json
from pathlib import Path

R = Path(__file__).resolve().parents[4]
CENSUS = R/'probes/structure-census-r3/structure-census.json'
raw = CENSUS.read_bytes()
print('census sha256', sha256(raw).hexdigest())
census = json.loads(raw)
rec = census['census']['records']['spatial-record:graph']
print({k: (v if not isinstance(v, (list, dict)) else type(v).__name__) for k, v in rec.items()})
print('counts', rec.get('counts'))
print('max_depth', rec.get('max_depth'))
for f in rec['fields'][:80]:
    print(f['path'], f['kind'], f['items'], f['bytes'])
print('nfields', len(rec['fields']))
