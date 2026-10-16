"""Read-only: field names of the IV1 closed graph and static partition rows (store copy)."""
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rawstore import RawStore  # noqa: E402

ROOT = '674ef5f3fcf41cb45e4b3e2ac2543e6ab0918b03f5a25dbc951363489a81bfad'
IV1 = 'bc945eedff746d89992e474f4aa089eb333d03298e47a22f10ae6d54e0549bbc'
store = RawStore(sys.argv[1])
snaps = store.snapshots()
graph = store.record(snaps[IV1], snaps[IV1]['metadata']['exterior_advance']['record_blobs']['graph'])
print('graph keys', {k: (type(v).__name__, len(v) if isinstance(v, (list, dict)) else v) for k, v in graph.items()
                     if not isinstance(v, str) or len(v) < 100})
for key in ('cells', 'inactive_zero_measure_cells'):
    rows = graph[key]
    print(key, len(rows), 'kinds', Counter(r['kind'] for r in rows))
    print('  sample', json.dumps(rows[0])[:1500])
    print('  fields', Counter(f for r in rows for f in r))
print('transfers', len(graph['transfers']), json.dumps(graph['transfers'][0])[:600])
print('selected', len(graph['selected_face_representatives']))
print('original faces', len(graph['original_face_intervals']), json.dumps(graph['original_face_intervals'][0])[:600])
del graph
static = store.record(snaps[ROOT], snaps[ROOT]['metadata']['differential_partition']['record_blobs']['partition'])
print('static partition keys', sorted(static))
print('static supports', len(static['supports']), 'components', sum(len(s['components']) for s in static['supports']))
print('static support sample keys', sorted(static['supports'][0]))
print('static partition record keys', sorted(static['partition']) if 'partition' in static else None)
store.close()
