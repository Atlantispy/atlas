"""Read-only: bounded structural description of selected raw records (store copy)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rawstore import RawStore  # noqa: E402

ROOT = '674ef5f3fcf41cb45e4b3e2ac2543e6ab0918b03f5a25dbc951363489a81bfad'
IV1 = 'bc945eedff746d89992e474f4aa089eb333d03298e47a22f10ae6d54e0549bbc'


def describe(value, depth=0, name='root', limit=3, width=40):
    pad = '  ' * depth
    if isinstance(value, dict):
        print(f'{pad}{name}: dict[{len(value)}]')
        if depth < limit:
            for k, v in list(value.items())[:width]:
                describe(v, depth + 1, k, limit, width)
    elif isinstance(value, list):
        print(f'{pad}{name}: list[{len(value)}]')
        if depth < limit and value:
            describe(value[0], depth + 1, name + '[0]', limit, width)
    else:
        print(f'{pad}{name}: {repr(value)[:120]}')


store = RawStore(sys.argv[1])
snaps = store.snapshots()
wanted = [(ROOT, ('differential_partition', 'record_blobs', 'current')),
          (IV1, ('differential_geometry', 'record_blob')),
          (IV1, ('differential_certification', 'record_blob')),
          (IV1, ('exterior_state', 'record_blobs', 'state'))]
for snap, path in wanted:
    ref = snaps[snap]['metadata']
    for p in path:
        ref = ref[p]
    rec = store.record(snaps[snap], ref)
    print('=====', snap[:8], '.'.join(path), ref['bytes'])
    describe(rec, limit=3)
for snap in (ROOT, IV1):
    meta = snaps[snap]['metadata']
    print('=====', snap[:8], 'metadata (non-blob)')
    for k, v in meta.items():
        print('  ', k, json.dumps(v)[:600])
store.close()
