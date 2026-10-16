"""Companion of workers_six.py: endpoint component sessions accept 1-6 workers.

Source transform of atlas_tectonics/integration_component_volume_parallel.py. The automatic
endpoint route (integration_component_volume_auto.py) opens ComponentParallelSession with the
SAME policy's (already resource-cut) worker count; RC1 refuses more than two there, which would
make a 4- or 6-worker policy fail the endpoint pass. Nothing else changes: transfer, adoption,
revocation and stop are the batch session's, which scale with the count.
"""
from hashlib import sha256

KNOWN_INPUT_SHA256 = {
    'fafc76fb866e37b5ea98b321bbd78a5e4ea75355e1aedef869401d936cf233df': 'RC1 composed-r1 runtime-src',
}
OLD = ("        if type(workers) is not int or not 1 <= workers <= 2:\n"
       "            raise ValueError('one or two component workers required')\n")
NEW = ("        if type(workers) is not int or not 1 <= workers <= 6:\n"
       "            raise ValueError('one to six component workers required')\n")


def transform(source, *, allow_unreviewed_input=False):
    if NEW in source:
        raise ValueError('endpoint workers-six transform already applied')
    if not allow_unreviewed_input and sha256(source.encode()).hexdigest() not in KNOWN_INPUT_SHA256:
        raise ValueError('component session input is not the reviewed module; pass allow_unreviewed_input and re-run parity')
    if source.count(OLD) != 1:
        raise ValueError('endpoint workers-six anchor must occur exactly once')
    return source.replace(OLD, NEW)
