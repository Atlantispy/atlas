"""FALSE PASS: two A keys that land on one new key collapse silently; one value (any number) is dropped."""
from hashlib import sha256
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import parity as P  # noqa: E402

PRIV = 'atlas_tectonics/_private/'

# (a) non-injective key_map: the same helper exists in two old trees (composed helpers and heat-repair src)
a = {'cell_counts': {'C:\\w\\composed-r2\\helpers\\tree_r1.py': 236,
                     'C:\\w\\heat-repair\\src\\atlas_tectonics\\tree_r1.py': 999}}
m = dict(key_map={'C:\\w\\composed-r2\\helpers\\tree_r1.py': PRIV + 'tree_r1.py',
                  'C:\\w\\heat-repair\\src\\atlas_tectonics\\tree_r1.py': PRIV + 'tree_r1.py'},
         sha_map={}, bookings=[], external=[], self_ids=[], modules={})
b = {'cell_counts': {PRIV + 'tree_r1.py': 999}}           # the 236 entry is gone
print('(a) non-injective key_map, value 236 dropped ->', P.check_records(a, b, m)['status'])

# (b) injective key_map, but A already carries the new relative key in the same dict
a2 = {'path_cost': {'C:\\w\\composed-r2\\helpers\\tree_r1.py': 1.25, PRIV + 'tree_r1.py': 7.5}}
m2 = dict(m, key_map={'C:\\w\\composed-r2\\helpers\\tree_r1.py': PRIV + 'tree_r1.py'})
b2 = {'path_cost': {PRIV + 'tree_r1.py': 7.5}}             # the 1.25 entry is gone
print('(b) abs key collides with existing relative key, 1.25 dropped ->', P.check_records(a2, b2, m2)['status'])
