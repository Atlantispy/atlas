"""S4 (Small optimisations, backlog 20, 16 Oct 2026): retry a machine-gate-refused first open later.

Source transform of atlas_tectonics/integration_component_volume_auto.py, generated from Small optimisations' reviewed
candidate (T/so/s4, INTEGRATION.md 13:43) by Geometry's make_s4_transforms.py: the hunks of
base fa0cbcaf... -> candidate 092dca7c..., applied in order, reproduce the candidate byte
for byte. A first worker session that only the machine and ledger gates refused (free cores,
memory, budget or predicate units at that moment) is looked for again at 15 s doubling to
120 s, at most 24 times, while the parent goes on serially; psutil missing still stops at once.
Records and the parent's adoption order cannot change (a late session is an ordinary first
session opened later in the pass). Owner review: G/reviews/s4-retry-review.md.
"""
from hashlib import sha256

KNOWN_INPUT_SHA256 = {
    'fa0cbcaf55eb0845e824fa8a2a8417dd1c0b1936c899a8b049d0ba88a1a1cdfe':
        'gg/workers6-r6 (composed-r1 + workers_six_endpoint_clamp); stacks after wp18 by its _open anchor',
}
CANDIDATE_SHA256 = '092dca7ca6d1d443eab31a631d7a1ed24651b80adbbe32d7c77feb1217ff8c9d'   # T/so/s4/integration_component_volume_auto.py

EDITS = (
    ('        if refusal is not None:\n'
     "            self.notes.append('%s: %s' % refusal)\n"
     '            return None\n'
     "        # Endpoint sessions keep RC1's bound of two workers (ComponentParallelSession is\n",
     '        if refusal is not None:\n'
     '            # A momentary machine refusal defers the open (see _Rolling._refused).\n'
     '            return self._refused(refusal)\n'
     "        # Endpoint sessions keep RC1's bound of two workers (ComponentParallelSession is\n"),
)


def transform(source, *, allow_unreviewed_input=False):
    if 'return self._refused(refusal)' in source:
        raise ValueError('S4 retry already applied')
    if not allow_unreviewed_input and sha256(source.encode()).hexdigest() not in KNOWN_INPUT_SHA256:
        raise ValueError('integration_component_volume_auto.py input is not the reviewed module; pass allow_unreviewed_input and re-run parity')
    for old, new in EDITS:
        if source.count(old) != 1:
            raise ValueError('S4 anchor must occur exactly once: %r' % old[:60])
        source = source.replace(old, new)
    return source
