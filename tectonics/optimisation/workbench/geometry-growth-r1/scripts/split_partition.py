"""Write a partition's supports as streamable JSONL.gz (header line + one support per line).

Sources: the IV2 rebuild output (--rebuild) or the saved IV1 capture (--capture).
The header carries support_ids, partition identity, and the production endpoint
width and leaf ceiling read from the IV1 closed graph in the store copy (the r4
proposal records the same 524288 ALE leaf limit). Read-only inputs; one new file.
"""
import argparse
import gzip
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rawstore import RawStore  # noqa: E402

IV1 = 'bc945eedff746d89992e474f4aa089eb333d03298e47a22f10ae6d54e0549bbc'

ap = argparse.ArgumentParser()
ap.add_argument('--store', required=True)
ap.add_argument('--rebuild')
ap.add_argument('--capture')
ap.add_argument('--output', required=True)
args = ap.parse_args()
out = Path(args.output)
if out.exists():
    raise SystemExit('output exists')
store = RawStore(args.store)
snaps = store.snapshots()
graph = store.record(snaps[IV1], snaps[IV1]['metadata']['exterior_advance']['record_blobs']['graph'])
width, leaves = graph['max_volume_error_m3'], graph['max_leaves']
del graph
store.close()
if args.rebuild:
    data = json.loads(gzip.decompress(Path(args.rebuild).read_bytes()))
    partition, supports = data['partition'], data['supports']
    label = 'iv2-rebuild'
else:
    data = json.loads(gzip.decompress(Path(args.capture).read_bytes()))
    partition, supports = data['partition'], data['supports']
    label = 'iv1-capture'
header = dict(label=label, support_ids=partition['support_ids'], interval_id=partition['interval_id'],
              max_volume_error_m3=width, max_leaves=leaves, supports=len(supports))
with gzip.open(out, 'xt', encoding='utf8') as f:
    f.write(json.dumps(header) + '\n')
    for s in supports:
        f.write(json.dumps(s, sort_keys=True, separators=(',', ':')) + '\n')
print(json.dumps(dict(output=str(out), supports=len(supports), width=width, max_leaves=leaves)))
