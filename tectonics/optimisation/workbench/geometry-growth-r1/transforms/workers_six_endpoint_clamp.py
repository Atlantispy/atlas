"""Companion of workers_six.py: the automatic ENDPOINT route keeps RC1's bound of two workers.

Source transform of atlas_tectonics/integration_component_volume_auto.py. With workers_six a
policy may ask for up to six workers; the endpoint route opens ComponentParallelSession with the
policy's (resource-cut) count, and RC1's session refuses more than two, which would fail the
endpoint pass. Rather than widen the endpoint session (no endpoint parity at >2 yet; endpoint
batching is deferred work, WP18 part 1), the endpoint route clamps its cut count to 2 right after
its machine gates. ComponentParallelSession itself is unchanged (1..2), so direct constructors keep
RC1's cap. Wall and interface batches use the full count.
Supersedes workers_six_endpoints.py (16 Oct refuter: no endpoint parity; direct constructors).
"""
from hashlib import sha256

KNOWN_INPUT_SHA256 = {
    '72cb051ecc3a3be369891add19922e3c62f57f0367995c8dffedd2770e12c3b9': 'RC1 composed-r1 runtime-src',
}
OLD = ("    def _open(self):\n"
       "        refusal = self._machine()\n"
       "        if refusal is not None:\n"
       "            self.notes.append('%s: %s' % refusal)\n"
       "            return None\n"
       "        policy = self.policy\n")
NEW = ("    def _open(self):\n"
       "        refusal = self._machine()\n"
       "        if refusal is not None:\n"
       "            self.notes.append('%s: %s' % refusal)\n"
       "            return None\n"
       "        # Endpoint sessions keep RC1's bound of two workers (ComponentParallelSession is\n"
       "        # 1..2); a larger policy count serves the wall and interface batches only.\n"
       "        self.workers = min(self.workers, 2)\n"
       "        policy = self.policy\n")


def transform(source, *, allow_unreviewed_input=False):
    if 'self.workers = min(self.workers, 2)' in source:
        raise ValueError('endpoint clamp already applied')
    if not allow_unreviewed_input and sha256(source.encode()).hexdigest() not in KNOWN_INPUT_SHA256:
        raise ValueError('endpoint auto input is not the reviewed module; pass allow_unreviewed_input and re-run parity')
    if source.count(OLD) != 1:
        raise ValueError('endpoint clamp anchor must occur exactly once')
    return source.replace(OLD, NEW)
