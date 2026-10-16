"""Read-only: how the saved capture's IV1 supports differ from the store's IV1 partition."""
from collections import Counter
from hashlib import sha256
import gzip
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rawstore import RawStore  # noqa: E402

IV1 = 'bc945eedff746d89992e474f4aa089eb333d03298e47a22f10ae6d54e0549bbc'
capture, store_path = sys.argv[1:3]
data = json.loads(gzip.decompress(open(capture, 'rb').read()))
store = RawStore(store_path)
snaps = store.snapshots()
rec = store.record(snaps[IV1], snaps[IV1]['metadata']['differential_partition']['record_blobs']['partition'])
store.close()
a, b = data['supports'], rec['supports']
print('counts', len(a), len(b), 'store partition_id', rec.get('partition_id'))
print('partition non-support keys equal:', {k: v for k, v in rec.items() if k not in ('supports', 'partition_id')} == data['partition'])
ka = Counter(sha256(json.dumps(s, sort_keys=True).encode()).hexdigest() for s in a)
kb = Counter(sha256(json.dumps(s, sort_keys=True).encode()).hexdigest() for s in b)
print('same multiset of supports:', ka == kb, 'same order:', a == b)
if ka != kb:
    s, t = a[0], b[0]
    print('field sets', sorted(set(s) ^ set(t)))
    for k in sorted(set(s) | set(t)):
        if s.get(k) != t.get(k):
            print('  differs', k, json.dumps(s.get(k))[:300], '|', json.dumps(t.get(k))[:300])
print('support_ids order matches store list:', [x for x in rec['support_ids']] == data['partition']['support_ids'])
