"""T/ps P2: one region preparation per pressure wall (integration_spatial_pressure.py).

moving_wall_integrals prepares every region of a wall (face-on-wall proofs, back boxes,
wall polygons, cone and plane clipping) before it integrates the density anomaly and
the owned pressure. That preparation reads only the wall's rays, regions, profiles (a
region whose density equals a profile row is skipped), pose and outer radius. It never
reads owned_box or compute_density. differential_pressure_forcing calls the kernel
1 + len(reservoirs) times per wall with the same rays, regions list, profiles, pose and
radius, so the same preparation was repeated. A caller may now pass one private _held dict
for those calls. The first call fills it with the prepared regions, and later calls for
the same wall reuse them. They are only read after preparation. A held preparation used
with another regions list, profiles object, pose, wall or radius, or after a region was
changed, is refused (r2: the P2 refuter found profiles missing from this check, 16 Oct).
Without _held nothing changes. Reused calls skip only identical temporary V._work
reservations; values, leaves, notes and refusals are unchanged.
Record identity: numbers byte-identical; the module source digest (execution identity) changes (D-b).
"""
from hashlib import sha256

KNOWN_INPUT_SHA256 = {
    '8bbcdd81cae3f7496ad08fb5ecb0f218b085a97e47584f513ac28fdfde7ca83b': 'RC1 = composed-r2 = workers6-r6',
}
ANCHORS = (
    ('                         gravity, support_radius, radius, width, max_leaves, budget, compute_density=True):\n',
     '                         gravity, support_radius, radius, width, max_leaves, budget, compute_density=True,\n'
     '                         _held=None):\n'),
    ('    invariant_wall = axis is not None and not any(O._cross(normal, axis))\n'
     '    for original in regions:\n',
     '    invariant_wall = axis is not None and not any(O._cross(normal, axis))\n'
     '    # T/ps P2: the regions prepared below depend only on this wall\'s rays,\n'
     '    # regions, profiles, pose and outer radius, never on owned_box or compute_density.\n'
     '    # A caller that evaluates one wall for several boxes passes one _held\n'
     '    # dict: the first call fills it, later calls for the same wall reuse it.\n'
     '    # Prepared regions are only read after this loop.\n'
     '    reused = None\n'
     '    if _held is not None and \'active\' in _held:\n'
     '        if not (_held[\'regions\'] is regions and _held[\'profiles\'] is profiles\n'
     '                and _held[\'pose\'] is pose and _held[\'wall\'] == (a, b, outer)\n'
     '                and len(_held[\'items\']) == len(regions)\n'
     '                and all(held == region for held, region in zip(_held[\'items\'], regions))):\n'
     '            raise C.PressureCouplingRefused(\'a held wall preparation belongs to another wall\')\n'
     '        reused = _held[\'active\']\n'
     '    for original in (regions if reused is None else ()):\n'),
    ('    back_owned = _back_box(owned_box, pose, outer, budget, axis=axis)\n',
     '    if reused is not None:\n'
     '        active = reused\n'
     '    elif _held is not None:\n'
     '        _held.update(regions=regions, profiles=profiles, pose=pose, wall=(a, b, outer),\n'
     '                     items=tuple(dict(region) for region in regions), active=active)\n'
     '    back_owned = _back_box(owned_box, pose, outer, budget, axis=axis)\n'),
)


def transform(source, *, allow_unreviewed_input=False):
    if '_held=None' in source:
        raise ValueError('P2 wall preparation transform already applied')
    if not allow_unreviewed_input and sha256(source.encode()).hexdigest() not in KNOWN_INPUT_SHA256:
        raise ValueError('spatial pressure input is not the reviewed module')
    for old, new in ANCHORS:
        if source.count(old) != 1:
            raise ValueError('P2 anchor must occur exactly once: '+old.strip()[:60])
        source = source.replace(old, new)
    return source
