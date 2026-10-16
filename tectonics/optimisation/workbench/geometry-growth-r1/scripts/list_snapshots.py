"""Read-only: list each snapshot's metadata record references (store copy)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rawstore import RawStore, refs  # noqa: E402

store = RawStore(sys.argv[1])
for key, manifest in store.snapshots().items():
    meta = manifest.get('metadata', {})
    print('SNAPSHOT', key, 'top keys', sorted(manifest), 'metadata keys', sorted(meta)[:80])
    print('   arrays', len(manifest.get('arrays', {})))
    for path, ref in refs(meta):
        print('   REF', path, ref['bytes'])
    scalars = {k: v for k, v in meta.items() if not isinstance(v, (dict, list))}
    print('   scalars', json.dumps(scalars)[:1500])
store.close()
