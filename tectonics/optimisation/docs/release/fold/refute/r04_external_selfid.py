"""External preimage that contains one of the record's own self-IDs (or any ID that the fold re-derives).
The checker maps paths in the preimage but leaves the embedded old self-ID, so:
FALSE PASS: B whose external ID still references the pre-fold result passes.
FALSE FAIL: B whose external ID references the folded result is rejected."""
import copy
from hashlib import sha256
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import parity as P  # noqa: E402

K, N = 'C:\\w\\composed-r2\\helpers\\tree_r1.py', 'atlas_tectonics/_private/tree_r1.py'


def ids(r):
    r['inner']['result_id'] = P.stream_hash({k: v for k, v in r['inner'].items() if k != 'result_id'})
    return r


a = ids({'inner': {'module': K, 'cells': 236}})
pre_a = {'label': 'consumer', 'result': a['inner']['result_id']}
a['consumer'] = P.stream_hash(pre_a)

b = ids({'inner': {'module': N, 'cells': 236}})
b_right = dict(copy.deepcopy(b), consumer=P.stream_hash({'label': 'consumer', 'result': b['inner']['result_id']}))
b_stale = dict(copy.deepcopy(b), consumer=a['consumer'])
m = dict(key_map={K: N}, sha_map={}, bookings=[], self_ids=[['inner', 'result_id']], modules={},
         external=[dict(path=['consumer'], preimage_a=pre_a)])
for label, bb in (('stale consumer (old result_id)', b_stale), ('consumer re-derived from new result_id', b_right)):
    try:
        print('%-40s -> %s' % (label, P.check_records(a, bb, m)['status']))
    except P.ParityError as e:
        print('%-40s -> FAIL %s' % (label, str(e)[:70]))
