"""Probes that HELD (expected outcome printed next to the actual one)."""
from hashlib import sha256
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import parity as P  # noqa: E402

K, N = 'C:\\w\\composed-r2\\helpers\\tree_r1.py', 'atlas_tectonics/_private/tree_r1.py'
OLD, NEW = sha256(b'old').hexdigest(), sha256(b'new').hexdigest()
M = dict(key_map={K: N}, sha_map={N: [OLD, NEW]}, bookings=[], external=[], self_ids=[], modules={})


def rec(a, b, m=M):
    try:
        return P.check_records(a, b, m)['status']
    except P.ParityError:
        return 'FAIL'
    except Exception as e:  # noqa: BLE001
        return 'CRASH ' + type(e).__name__


def ids(r):
    r['inner']['result_id'] = P.stream_hash({k: v for k, v in r['inner'].items() if k != 'result_id'})
    r['result_id'] = P.stream_hash({k: v for k, v in r.items() if k != 'result_id'})
    return r


rows = [
    ('pin under key absent from sha_map', rec({'s': {K: OLD}}, {'s': {N: NEW}}, dict(M, sha_map={})), 'FAIL'),
    ('B re-pins to a sha other than sha_map new', rec({'s': {K: OLD}}, {'s': {N: OLD}}), 'FAIL'),
    ('non-booking int -> bool', rec({'n': 1}, {'n': True}), 'FAIL'),
    ('0.0 -> -0.0', rec({'x': 0.0}, {'x': -0.0}), 'FAIL'),
    ('int 3 -> float 3.0', rec({'x': 3}, {'x': 3.0}), 'FAIL'),
    ('list order swapped', rec({'x': [1, 2]}, {'x': [2, 1]}), 'FAIL'),
    ('posix /home path key unmapped', rec({'s': {'/home/LOCAL_USER/x.py': 1}}, {'s': {'/home/LOCAL_USER/x.py': 1}}), 'FAIL'),
    ('C:/Users forward-slash leak in B', rec({'p': 'rel'}, {'p': 'C:/Users/LOCAL_USER/x'}), 'FAIL'),
    ('NaN only in B', rec({'x': 1.0}, {'x': float('nan')}), 'CRASH ValueError'),
    ('self_ids listed shallow-first (order)', rec(ids({'inner': {'m': K}}), ids({'inner': {'m': N}}),
                                                   dict(M, self_ids=[['result_id'], ['inner', 'result_id']])), 'PASS'),
    ('self-ID forged in B, others correct', rec(ids({'inner': {'m': K}}), dict(ids({'inner': {'m': N}}), result_id=NEW),
                                                dict(M, self_ids=[['inner', 'result_id'], ['result_id']])), 'FAIL'),
]
ast_rows = [
    ('import a.b -> import a.c', P.ast_equivalent('import a.b\n', 'import a.c\n'), False),
    ('import a.b -> import atlas_tectonics._private.a.b (bound name differs)',
     P.ast_equivalent('import a.b\n', 'import atlas_tectonics._private.a.b\n'), False),
    ('from m import * -> from atlas_tectonics._private.m2 import *',
     P.ast_equivalent('from m import *\n', 'from atlas_tectonics._private.m2 import *\n'), False),
    ('from m import * -> from atlas_tectonics._private.m import *',
     P.ast_equivalent('from m import *\n', 'from atlas_tectonics._private.m import *\n'), True),
    ('import X as K -> from atlas_tectonics._private import X as K',
     P.ast_equivalent('import X as K\n', 'from atlas_tectonics._private import X as K\n'), True),
    ('identity import replaces (not adds to) an import',
     P.ast_equivalent('import numpy as np\n', 'import atlas_tectonics._identity as np\n'), False),
    ('number edited inside a key call argument',
     P.ast_equivalent('from pathlib import Path\nk = str(Path(p[0]).resolve())\n',
                      'from pathlib import Path\nk = str(Path(p[1]).resolve())\n'), False),
    ('hex64 upper-case literal edited',
     P.ast_equivalent("X = '%s'\n" % OLD.upper(), "X = '%s'\n" % NEW.upper()), False),
]
for name, got, want in rows:
    print('%-6s %-44s got %s' % ('held' if got == want else 'BROKE', name, got))
for name, got, want in ast_rows:
    print('%-6s %-70s ast_equivalent=%s' % ('held' if got == want else 'BROKE', name, got))
