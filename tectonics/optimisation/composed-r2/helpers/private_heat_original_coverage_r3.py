"""Pinned R2 coverage with the canonical shape helper, not a facade assumption.

The production resource facade deliberately exports only a subset of BASE.
R2 incorrectly asked it for pair_shape. This exact one-call derivative imports
that pure prospective shape function from its already pinned canonical module.
All checks, work inventories, ownership scopes and diagnostic contracts remain
unchanged. No resource API or scientific implementation is monkeypatched.
"""
from hashlib import sha256 as _repair_sha256
from pathlib import Path as _RepairPath

_REPAIR_ROOT = _RepairPath(__file__).resolve().parent
_REPAIR_SOURCE = _REPAIR_ROOT / 'private_heat_original_coverage_r2.py'
_REPAIR_SOURCE_SHA = '078a4a730d0cbac4c60b9e9e4f992859883af9ce282a089a9471125e214690c3'
_REPAIR_FACADE_SHA = '6517cc80b676a7a66a0ab573899d2e6e6beadf20af5fd7f9b6987962f35621cd'
_REPAIR_BYTES = _REPAIR_SOURCE.read_bytes()
if _repair_sha256(_REPAIR_BYTES).hexdigest() != _REPAIR_SOURCE_SHA:
    raise ValueError('Frozen sequential coverage R2 source changed')
_REPAIR_BEFORE = 'shape = resources.pair_shape(pair, hexadecimal=True)'
_REPAIR_AFTER = 'shape = _CANONICAL_SHAPES.pair_shape(pair, hexadecimal=True)'
_REPAIR_TEXT = _REPAIR_BYTES.decode('utf8')
if _REPAIR_TEXT.count(_REPAIR_BEFORE) != 1:
    raise ValueError('Canonical shape repair must match exactly one pinned call')
_REPAIR_DERIVED = _REPAIR_TEXT.replace(_REPAIR_BEFORE, _REPAIR_AFTER, 1)
exec(compile(_REPAIR_DERIVED, str(_REPAIR_SOURCE) + '[canonical-shape-r3]', 'exec'), globals())

import private_heat_issuer_resources_r1 as _CANONICAL_SHAPES

if _RepairPath(_CANONICAL_SHAPES.__file__).resolve() != _REPAIR_ROOT / 'private_heat_issuer_resources_r1.py':
    raise ValueError('Canonical shape module loaded from another source')
_PINS = globals()['_PINS']
_PINS.update({
    _REPAIR_SOURCE.name: _REPAIR_SOURCE_SHA,
    'private_heat_issuer_resources_r3.py': _REPAIR_FACADE_SHA,
})
source_bindings = globals()['source_bindings']
source_bindings()


def derivation():
    """Inspectable single-call delta; old sources and resource APIs are intact."""
    return dict(schema='atlas.private.original-coverage-canonical-shape.r3',
        source_sha256=_REPAIR_SOURCE_SHA,
        derived_text_sha256=_repair_sha256(_REPAIR_DERIVED.encode('utf8')).hexdigest(),
        changes=[dict(before=_REPAIR_BEFORE, after=_REPAIR_AFTER)],
        source_bindings=source_bindings(), scientific_changes=False,
        resource_api_monkeypatches=False, ownership_and_inventory_changes=False)
