"""T/ps P1/P2: the wall loop of differential_pressure_forcing reads its walls from
integration_pressure_walls.wall_results (integration_differential_pressure.py).

wall_results yields, in the walls' order, each wall's (force, removed, used, cuts): the
unchanged moving_wall_integrals for the native box and then for each reservoir box,
computed in this process (serial, the default) or adopted from a source-bound batch worker
inside the driver's parallel() block. The merge below keeps the original statements in
the original order: leaves += used for the native box, then for each reservoir box
reservoir_wall = [C._add(a, b) ...] and leaves += used, then the plate updates. The
settings dict is built once instead of once per wall, with equal values.
Record identity: numbers byte-identical; the module source digest (execution identity) changes (D-b).
"""
from hashlib import sha256

KNOWN_INPUT_SHA256 = {
    '8d3d8f3dd11d632ce6a75380a17fdcd19b281fafa03b68401a2726d228c02a33': 'RC1 = composed-r2 = workers6-r6',
}
OLD = (
    '        certificates, leaves = [], 0\n'
    '        for left, right, rays, pose, certificate in walls:\n'
    '            selected = [dict(region, side=None if region[\'plate_id\'] is None else (0 if region[\'plate_id\'] == left else 1))\n'
    '                        for region in regions if region[\'plate_id\'] in (None, left, right)]\n'
    '            args = dict(gravity=Q(datum.gravity_m_s2), support_radius=rc, radius=radius,\n'
    '                        width=allowance, max_leaves=max_leaves, budget=budget)\n'
    '            force, removed, used = P.moving_wall_integrals(*rays, (profile, profile), selected, native_box, pose, **args)\n'
    '            leaves += used\n'
    '            reservoir_wall = [(Q(0), Q(0)) for _ in range(3)]\n'
    '            for box in reservoirs:\n'
    '                _, cut, used = P.moving_wall_integrals(*rays, (profile, profile), selected, box, pose,\n'
    '                                                     compute_density=False, **args)\n'
    '                reservoir_wall = [C._add(a, b) for a, b in zip(reservoir_wall, cut)]\n'
    '                leaves += used\n'
)
NEW = (
    '        certificates, leaves = [], 0\n'
    '        # T/ps P1/P2: each wall\'s integrals come from integration_pressure_walls in\n'
    '        # wall order (computed here unless the driver opened parallel walls); the\n'
    '        # merge keeps the original statements in the original order.\n'
    '        from .integration_pressure_walls import wall_results as _wall_results\n'
    '        args = dict(gravity=Q(datum.gravity_m_s2), support_radius=rc, radius=radius,\n'
    '                    width=allowance, max_leaves=max_leaves, budget=budget)\n'
    '        for (left, right, rays, pose, certificate), (force, removed, used, cuts) in zip(\n'
    '                walls, _wall_results(walls, regions, (profile, profile), native_box, reservoirs, args)):\n'
    '            leaves += used\n'
    '            reservoir_wall = [(Q(0), Q(0)) for _ in range(3)]\n'
    '            for cut, used in cuts:\n'
    '                reservoir_wall = [C._add(a, b) for a, b in zip(reservoir_wall, cut)]\n'
    '                leaves += used\n'
)


def transform(source, *, allow_unreviewed_input=False):
    if '_wall_results' in source:
        raise ValueError('P1 wall loop transform already applied')
    if not allow_unreviewed_input and sha256(source.encode()).hexdigest() not in KNOWN_INPUT_SHA256:
        raise ValueError('differential pressure input is not the reviewed module')
    if source.count(OLD) != 1:
        raise ValueError('P1 wall loop anchor must occur exactly once')
    return source.replace(OLD, NEW)
