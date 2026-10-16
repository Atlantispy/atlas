"""Coordinator decision D1 (16 Oct): RC1 integrated items 11 and 15 OFF for Step 10.

Source transform of atlas_tectonics/integration_differential_geometry.py. Restores
the r4/r9 (native-composed-r7) behaviour of exactly two RC1 optimisations:

  item 11  aspect-aware subdivision axis -> the original cyclic axis, k = depth % 3
           (the single call site in _component_volume_bounds_decoded);
  item 15  padded whole-cell containment for INEXACT poses -> not attempted
           (the single call site in _component_volume_certificate; exact-pose
           containment, which r7 already had, is unchanged).

Evidence (R/geometry-growth-r1/evidence/): with the cube stop, item 11 and item 15 all
off, RC1 reproduces r7 exactly on all 7,181 IV1 endpoint queries
(attribution-iv1-r1.json). Deterministic cost: item 11 saves 2.2% of leaves / 0.6%
of work on IV1 and 0.6% / 0.26% on IV2 while changing 91 + 133 results; item 15
saves no leaves, adds 0.1-0.2% work, and changes 1 + 2 results. Timing differences
are inside the measured +/-10% machine noise. Every result stays a certified,
overlapping enclosure either way; met never changes. With both off, the interval-1
difference ledger against pinned IV1 is cube-stop only.

The helper functions stay defined (unused) so no other source changes. Anchors are
checked exactly; only the reviewed RC1 input is accepted unless a composer stacks
this on other transforms and re-runs parity.
"""
from hashlib import sha256

KNOWN_INPUT_SHA256 = {
    'fc9dd85e002fe54db6e409ebe89083996f62611c40d958a5a1e60184f3424253': 'RC1 composed-r1 runtime-src',
}
ITEM11_OLD = '                k = _component_longest_side(parent, arena, depth=depth, _query=arena._component_ray_cache)\n'
ITEM11_NEW = '                k = depth % 3  # D1: item 11 off (r7 cyclic axis)\n'
ITEM15_OLD = ('        if error:\n'
              '            if _padded_box_contained(cell, normal, error, offset, sign, clipping):\n'
              '                mask |= 1 << index\n'
              '            continue\n')
ITEM15_NEW = ('        if error:\n'
              '            continue  # D1: item 15 off (no padded containment for inexact poses, as r7)\n')


def _once(source, old, new):
    if source.count(old) != 1:
        raise ValueError('items 11/15 anchor must occur exactly once: ' + old[:70])
    return source.replace(old, new)


def transform(source, *, allow_unreviewed_input=False):
    if not allow_unreviewed_input and sha256(source.encode()).hexdigest() not in KNOWN_INPUT_SHA256:
        raise ValueError('items 11/15 transform input is not the reviewed geometry; pass allow_unreviewed_input and re-run parity')
    source = _once(source, ITEM11_OLD, ITEM11_NEW)
    source = _once(source, ITEM15_OLD, ITEM15_NEW)
    return source
