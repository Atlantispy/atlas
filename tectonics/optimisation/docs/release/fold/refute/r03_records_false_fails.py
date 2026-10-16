"""FALSE FAIL / crash cases in check_records for legitimate folds."""
from hashlib import sha256
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import parity as P  # noqa: E402

K, N = 'C:\\w\\composed-r2\\helpers\\tree_r1.py', 'atlas_tectonics/_private/tree_r1.py'
OLD, NEW = sha256(b'old').hexdigest(), sha256(b'new').hexdigest()
DIGEST = sha256(b'output field bytes').hexdigest()
base = dict(key_map={K: N}, sha_map={N: [OLD, NEW]}, bookings=[], external=[], self_ids=[], modules={})


def st(a, b, m):
    try:
        return P.check_records(a, b, m)['status']
    except P.ParityError as e:
        return 'FAIL ParityError: %s' % str(e)[:70]
    except Exception as e:  # noqa: BLE001
        return 'CRASH %s: %s' % (type(e).__name__, str(e)[:60])


# 1. same path key holds a source pin in one dict and an (unchanged) output digest in another
a = {'sources': {K: OLD}, 'output_digest': {K: DIGEST}}
b = {'sources': {N: NEW}, 'output_digest': {N: DIGEST}}
print('1 hex64 data digest under a path key  ->', st(a, b, base))

# 2. booking keyed by path (per-file path bytes)
a = {'path_bytes': {K: 412}}
b = {'path_bytes': {N: 371}}
print('2 booking path goes through a path key ->', st(a, b, dict(base, bookings=[['path_bytes', K]])))

# 3. float booking (e.g. GiB) that shrinks
a = {'ram_gib': 4.0}
b = {'ram_gib': 3.5}
print('3 float booking that shrinks           ->', st(a, b, dict(base, bookings=[['ram_gib']])))

# 4. NaN carried unchanged (json.loads accepts NaN) in an un-hashed field
a = {'probe': float('nan')}
print('4 NaN unchanged in A and B             ->', st(a, dict(a), base))

# 5. a data string starting with "/" (unit / separator) is treated as an absolute path
a = {'unit': '/s', 'sep': '/'}
print('5 data string starting with "/"         ->', st(a, dict(a), base))

# 6. self-ID sitting in a dict under a path key
inner = {'cells': 3}
inner['result_id'] = P.stream_hash(inner)
a = {'by_file': {K: inner}}
b = {'by_file': {N: dict(inner)}}
print('6 self-ID path through a path key       ->', st(a, b, dict(base, self_ids=[['by_file', K, 'result_id']])))
