"""Pins not stored as a bare hex64 directly under an absolute key are never re-pinned, although sha_map lists them.
FALSE PASS: B that leaves the old (pre-fold) sha passes.  FALSE FAIL: the correctly re-pinned B is rejected."""
from hashlib import sha256
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import parity as P  # noqa: E402

OLDK, NEWK = 'C:\\w\\heat-repair\\src\\atlas_tectonics\\integration_spatial_transport.py', \
    'atlas_tectonics/integration_spatial_transport.py'
OLD, NEW = sha256(b'heat-repair copy').hexdigest(), sha256(b'composed copy').hexdigest()
m = dict(key_map={OLDK: NEWK}, sha_map={NEWK: [OLD, NEW]}, bookings=[], external=[], self_ids=[], modules={})


def run(label, a, b_stale, b_right):
    def st(b):
        try:
            return P.check_records(a, b, m)['status']
        except P.ParityError as e:
            return 'FAIL (%s)' % str(e)[:60]
    print('%-34s stale old sha -> %-5s | correct new sha -> %s' % (label, st(b_stale), st(b_right)))


run('dict value {sha256, bytes}', {'src': {OLDK: {'sha256': OLD, 'bytes': 9}}},
    {'src': {NEWK: {'sha256': OLD, 'bytes': 9}}}, {'src': {NEWK: {'sha256': NEW, 'bytes': 9}}})
run('prefixed "sha256:<hex>"', {'src': {OLDK: 'sha256:' + OLD}},
    {'src': {NEWK: 'sha256:' + OLD}}, {'src': {NEWK: 'sha256:' + NEW}})
run('list of [path, sha] pairs', {'src': [[OLDK, OLD]]}, {'src': [[NEWK, OLD]]}, {'src': [[NEWK, NEW]]})
run('pin under {"path":..,"sha":..}', {'src': [{'path': OLDK, 'sha': OLD}]},
    {'src': [{'path': NEWK, 'sha': OLD}]}, {'src': [{'path': NEWK, 'sha': NEW}]})
