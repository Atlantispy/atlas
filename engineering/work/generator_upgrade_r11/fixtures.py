"""Sealed R10 output is a regression input, never fresh parent-generation proof."""
from . import provenance

PATH = provenance.TASK/'outputs/generator-upgrade-r10/seasonal-reference-01/n-worker-reference/full-result.json'
SHA256 = 'f191389d93c411f81e7003e5edf96551b53dc945e359dc705d83d00c64a0930e'
SIZE = 5409421


def parent(bundle):
    raw = provenance.checked(PATH, SHA256)
    if len(raw) != SIZE:
        raise ValueError('exact sealed R10 fixture size required')
    return bundle.storage.decoded(raw)
