"""Refuter P1 scratch: wall_set direct vs transported (encode -> canonical chunks -> decode under a
fresh child ledger -> compute -> encode result -> parent decode/check), on a synthetic fixture with
exact and uncertain poses, physical planes, cones and several reservoirs. Type-exact comparison,
including refusals (type, message, notes). Also the serial original statement sequence (no _held).
Read-only on the candidate; writes only its own report next to this file.
"""
import json
import sys
from fractions import Fraction as Q
from pathlib import Path

T = Path('C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10')
sys.path.insert(0, str(T/'ps'/'scripts'))
import rc1_env  # noqa: E402
rc1_env.install('frozen:'+str(T/'ps'/'c'/'full'))

from atlas_tectonics import integration_pressure_walls as W  # noqa: E402
from atlas_tectonics import integration_volume as V  # noqa: E402
from atlas_tectonics import integration_differential_pressure as D  # noqa: E402
from atlas_tectonics import integration_spatial_pressure as P  # noqa: E402
from atlas_tectonics import integration_pressure_coupling as C  # noqa: E402
from atlas_tectonics.resources import WorkBudget  # noqa: E402
from atlas_tectonics.integration_parallel_binding import canonical  # noqa: E402

FAILS, NOTES = [], []


def same(x, y):
    if type(x) is not type(y):
        return False
    if type(x) in (tuple, list):
        return len(x) == len(y) and all(same(a, b) for a, b in zip(x, y))
    if type(x) is dict:
        return list(x) == list(y) and all(same(x[k], y[k]) for k in x)
    if type(x) is Q:
        return x.numerator == y.numerator and x.denominator == y.denominator
    if type(x) is float:
        return x.hex() == y.hex()
    if type(x) is V.CartesianCell:
        return all(same(getattr(x, n), getattr(y, n)) for n in ('lower_m', 'upper_m', 'origin_m', 'basis'))
    if type(x) is D._KernelPose:
        return (same(x._rotation, y._rotation) and same(x._error, y._error)
                and same(x._plane_history, y._plane_history) and same(x._history, y._history)
                and sorted(vars(x)) == sorted(vars(y)))
    return x == y


def check(name, ok):
    if not ok:
        FAILS.append(name)
        print('FAIL', name, flush=True)


def outcome(fn):
    try:
        return ('ok', fn())
    except Exception as error:  # noqa: BLE001
        return ('raise', type(error).__name__, str(error), tuple(getattr(error, '__notes__', ())))


def agree(a, b):
    if a[0] != b[0]:
        return False
    return same(a[1], b[1]) if a[0] == 'ok' else a[1:] == b[1:]


enc = V._encoded
IDENTITY = tuple(tuple(Q(int(i == j)) for j in range(3)) for i in range(3))
A, B = (Q(0), Q(0), Q(1)), (Q(1), Q(0), Q(1))
A2, B2 = (Q(0), Q(1), Q(1)), (Q(1), Q(1), Q(2))
OMEGA = (Q(0), Q(0), Q(1, 10**10))
PROFILE = ((Q(1), Q(5), Q(1), Q(0)),)


def vec(v):
    return [enc(Q(x)) for x in v]


def ray(direction):
    return dict(direction=vec(direction), angular_velocity_rad_s=vec(OMEGA), prior_rotations=[])


edge = dict(kind='moving-ray-edge', rays=[ray(A), ray(B)])
fixed = dict(kind='fixed-plane', normal=vec((1, 0, 0)), offset=enc(Q(9)))
snap = dict(kind='snapshot-rotated', constraint=edge, snapshot_offset_s=enc(Q(1, 2)), angular_velocity_rad_s=vec(OMEGA))


def fixture(budget):
    cells = [V.CartesianCell((1, 0, 0), (2, 1, 1), budget=budget),
             V.CartesianCell((0, -1, 2), (1, 1, 3), budget=budget),
             V.CartesianCell((Q(1, 3), 0, 1), (1, Q(1, 2), Q(5, 2)), budget=budget)]
    regions = [
        dict(cell=cells[0], cone=(), radial=(Q(1), Q(5)), density=Q(3, 2), plate_id=None),
        dict(cell=cells[1], cone=(), world_planes=((Q(1), Q(0), Q(0), Q(9)), (Q(0), Q(-1), Q(0), Q(1), Q(1, 100))),
             _physical_planes=((fixed, Q(1)), (edge, Q(1))), radial=(Q(1), Q(5)), density=Q(2), plate_id='plate:A'),
        dict(cell=cells[1], cone=(), world_planes=((Q(0), Q(0), Q(1), Q(0)),), _physical_planes=((snap, Q(1)),),
             radial=(Q(2), Q(4)), density=Q(5, 2), plate_id='plate:B'),
        dict(cell=cells[2], cone=((Q(1), Q(0), Q(0)), (Q(0), Q(1), Q(0)), (Q(0), Q(0), Q(1))),
             radial=(Q(1), Q(5)), density=Q(1), plate_id='plate:B'),
        dict(cell=cells[2], cone=(), radial=(Q(3, 2), Q(9, 2)), density=Q(7, 4), plate_id='plate:C'),
    ]
    exact = D._KernelPose(IDENTITY, Q(0))
    uncertain = D._KernelPose(IDENTITY, Q(1, 10**8), history=((OMEGA, Q(1)),))
    tilted = D._KernelPose(IDENTITY, Q(1, 10**6), history=(((Q(1), Q(0), Q(0)), Q(1, 3)), (OMEGA, Q(2))))
    walls = (('plate:A', 'plate:B', (A, B), exact, 'c0'), ('plate:A', 'plate:B', (A, B), uncertain, 'c1'),
             ('plate:B', 'plate:C', (A2, B2), uncertain, 'c2'), ('plate:C', 'plate:A', (B, A2), tilted, 'c3'),
             ('plate:A', 'plate:C', (A, B2), exact, 'c4'))
    native_box = V.CartesianCell((0, -1, 0), (2, 1, 3), budget=budget)
    reservoirs = (V.CartesianCell((1, 0, 0), (2, 1, 1), budget=budget),
                  V.CartesianCell((0, -1, 2), (1, 1, 3), budget=budget),
                  V.CartesianCell((0, 0, 0), (Q(1, 2), Q(1, 2), Q(1, 2)), budget=budget))
    return regions, walls, native_box, reservoirs


def original(rays, profiles, selected, native_box, reservoirs, pose, args):
    # The base loop's statements for one wall, without _held (serial original).
    force, removed, used = P.moving_wall_integrals(*rays, profiles, selected, native_box, pose, **args)
    cuts = []
    for box in reservoirs:
        _, cut, count = P.moving_wall_integrals(*rays, profiles, selected, box, pose, compute_density=False, **args)
        cuts.append((cut, count))
    return force, removed, used, cuts


def main():
    parent = WorkBudget(4 << 30, max_predicate_work_units=1 << 44)
    regions, walls, native_box, reservoirs = fixture(parent)
    profiles = (PROFILE, PROFILE)
    rows = []
    for width, leaves in ((Q(1), 256), (Q(64), 4096), (Q(1, 10**6), 16), (Q(8), 1024)):
        args = dict(gravity=Q(1), support_radius=Q(1), radius=Q(5), width=width, max_leaves=leaves, budget=parent)
        inputs, ids, size = W._shared_inputs(walls, regions, profiles, native_box, reservoirs, args)
        child = WorkBudget(512 << 20, max_predicate_work_units=1 << 34)
        shared = W._decode_shared(inputs, ids, child)
        check('regions roundtrip', same(shared['regions'], list(regions)))
        check('profiles roundtrip', same(shared['profiles'], profiles))
        check('native roundtrip', same(shared['native_box'], native_box))
        check('reservoirs roundtrip', same(shared['reservoirs'], reservoirs))
        check('walls roundtrip', same(shared['walls'], [(l, r, ra, po) for l, r, ra, po, _ in walls]))
        check('cells bound to child', all(r['cell']._resource is child for r in shared['regions']))
        for index, (left, right, rays, pose, _) in enumerate(walls):
            selected = W._selected(regions, left, right)
            base = outcome(lambda: original(rays, profiles, [dict(r) for r in selected], native_box, reservoirs, pose, args))
            direct = outcome(lambda: W.wall_set(rays, profiles, W._selected(regions, left, right), native_box,
                                                reservoirs, pose, args))
            worker = outcome(lambda: W._compute(shared, index, child))
            adopted = worker
            if worker[0] == 'ok':
                request = dict(schema=W.SCHEMA, wall=index, walls=len(walls), inputs=list(ids),
                               max_leaves=leaves, test=None)
                W.check_request(request)
                raw = canonical(dict(request, result=W._enc(worker[1])))
                record = json.loads(raw)
                adopted = outcome(lambda: W._check_result(W._dec(record['result'], parent, objects=False),
                                                         len(reservoirs)))
            name = 'w=%s L=%d wall=%d' % (width, leaves, index)
            check(name+' base==direct', agree(base, direct))
            check(name+' direct==worker', agree(direct, worker))
            check(name+' direct==adopted', agree(direct, adopted))
            rows.append(dict(case=name, outcome=direct[0], detail=None if direct[0] == 'ok' else direct[1:3],
                             leaves=direct[1][2] if direct[0] == 'ok' else None))
    # Encoding edge values
    edge_values = [-0.0, 0.0, 1e-310, float('inf'), -(1 << 4000), 1 << 70000, True, False, None, 1, 0,
                   'a\udc80\u20ac"\\', Q(-7, 3), (1, (2,), []), [(), [1.5]], {'b': 1, 'a': [True, 1]}, {}]
    for value in edge_values:
        back = W._dec(json.loads(canonical(W._enc(value))), parent)
        check('edge %r' % (value,) if not isinstance(value, int) or abs(value) < 10**20 else 'edge bigint', same(value, back))
    nan = W._dec(json.loads(canonical(W._enc(float('-nan')))), parent)
    NOTES.append('float -nan round trip gives hex %s (sign of NaN not kept)' % nan.hex())
    try:
        import pressure_indexed_patch as X
        owned = X._OwnedPlanes(((fixed, Q(1)),), None)
        W._enc(owned)
        check('_OwnedPlanes refused', False)
    except TypeError as error:
        NOTES.append('_OwnedPlanes: '+str(error))
    report = dict(fails=FAILS, notes=NOTES, rows=rows,
                  outcomes={k: sum(1 for r in rows if r['outcome'] == k) for k in ('ok', 'raise')})
    (Path(__file__).parent/'transport_equiv.json').write_text(json.dumps(report, indent=1, default=str))
    print('FAILS', len(FAILS), 'cases', len(rows), report['outcomes'])
    for note in NOTES:
        print('NOTE', note)


if __name__ == '__main__':
    main()
