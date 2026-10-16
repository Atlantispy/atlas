"""(b) census: which next-interval charts an exact voxel-free whole-interval certificate proves empty.

Builds each IV2 chart exactly as prepare_interval_partition does (snapshot-rotated
wrappers at the IV2 plate rate, offset = IV1 duration) from the saved capture and
the rebuilt IV2 interval, then tries, under RC1:
  C1 _consistent_literals(...) is None   (exact opposite duplicate rigid planes)
  C2 _common_ray_cone_zero_volume(literals, constraints, 0, T, 0, arena)  (cell=None)
  C3 exact Gordan test on every co-rotating rigid group (rational normals, one
     shared proper rotation): 0 in conv{s_i n_i} => empty interior for all time.
Soundness check built in: a chart holding any IV1 piece with a positive true
volume bound at the IV1 end must NOT be proved empty (its IV2 start region
contains that piece). Read-only; writes one JSON evidence file.
"""
import argparse
import gzip
import json
import sys
import time
from collections import Counter
from fractions import Fraction as Q
from hashlib import sha256
from itertools import combinations
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import rc1_env  # noqa: E402
from rawstore import RawStore  # noqa: E402

IV1 = 'bc945eedff746d89992e474f4aa089eb333d03298e47a22f10ae6d54e0549bbc'


def solve3(rows, rhs):
    """Exact solve of a 3x3 (or fewer) rational system by Gaussian elimination; None if singular."""
    n = len(rows)
    m = [list(r) + [b] for r, b in zip(rows, rhs)]
    for c in range(n):
        p = next((r for r in range(c, n) if m[r][c] != 0), None)
        if p is None:
            return None
        m[c], m[p] = m[p], m[c]
        for r in range(n):
            if r != c and m[r][c] != 0:
                f = m[r][c] / m[c][c]
                m[r] = [a - f * b for a, b in zip(m[r], m[c])]
    return [m[r][n] / m[r][r] for r in range(n)]


def zero_in_hull(vectors):
    """Exact: is 0 a convex combination of the given rational 3-vectors? (Caratheodory, <=4 points.)

    Returns positive weights over a subset, or None. 0 in conv{a_i} with a_i != 0
    is Gordan's alternative to {x: a_i.x > 0 for all i} being nonempty.
    """
    vs = [v for v in vectors if any(v)]
    for k in range(2, min(4, len(vs)) + 1):
        for subset in combinations(range(len(vs)), k):
            pts = [vs[i] for i in subset]
            # weights w >= 0, sum w = 1, sum w_i p_i = 0: (k unknowns, 4 equations).
            # Solve using k of the 4 equations, check the rest exactly.
            eqs = [[p[j] for p in pts] for j in range(3)] + [[Q(1)] * k]
            rhs = [Q(0), Q(0), Q(0), Q(1)]
            for rows in combinations(range(4), k):
                if 3 not in rows:
                    continue
                w = solve3([eqs[r] for r in rows], [rhs[r] for r in rows])
                if w is None or any(x < 0 for x in w):
                    continue
                if all(sum(e * x for e, x in zip(eqs[r], w)) == rhs[r] for r in range(4)):
                    return [subset[i] for i in range(k)], w
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--capture', required=True)
    ap.add_argument('--interval', required=True, help='rebuild output holding the IV2 interval record')
    ap.add_argument('--store', required=True)
    ap.add_argument('--output', required=True)
    ap.add_argument('--instant', action='store_true', help='also try C4 at the parent end instant')
    ap.add_argument('--voxels', action='store_true', help='also try C5 over every grid voxel at that instant')
    args = ap.parse_args()
    out = Path(args.output)
    if out.exists():
        raise SystemExit('output exists')
    rc1_env.install()
    from atlas_tectonics import integration_differential_geometry as G
    from atlas_tectonics import integration_wall_measures as W
    from atlas_tectonics.resources import WorkBudget
    budget = WorkBudget(4 << 30, max_predicate_work_units=1 << 44)
    capture = json.loads(gzip.decompress(Path(args.capture).read_bytes()))
    step = json.loads(gzip.decompress(Path(args.interval).read_bytes()))['interval']
    if step['interval_id'] != 'bac70685048803dc4f307e9080f81b2d7359205dc373e919f945ca6ed713f48c':
        raise SystemExit('not the IV2 interval')
    store = RawStore(args.store)
    snaps = store.snapshots()
    graph = store.record(snaps[IV1], snaps[IV1]['metadata']['exterior_advance']['record_blobs']['graph'])
    store.close()
    cells = {c['cell_id']: c for c in graph['cells'] + graph['inactive_zero_measure_cells']}
    del graph
    parent = capture['partition']
    old_time = W._decode(parent['end_time_s']) - W._decode(parent['start_time_s'])
    duration = W._decode(step['duration_s'])
    from atlas_tectonics import integration_volume as V
    from itertools import product
    lines = tuple(tuple(map(W._decode, a)) for a in parent['grid_lines'])
    origin, basis = G._load_vec(parent['grid_origin_m']), tuple(map(G._load_vec, parent['grid_basis']))
    grid = [(at, V.CartesianCell(tuple(lines[j][at[j]] for j in range(3)), tuple(lines[j][at[j]+1] for j in range(3)),
                                 origin, basis, budget=budget))
            for at in product(*(range(len(a)-1) for a in lines))]
    charts = {}
    for r in capture['supports']:
        omega = G._load_vec(step['plate_angular_velocity_rad_s'][r['plate_id']])
        for c in r['components']:
            identity = dict(parent_partition_id='ada1e1288643132f367db9b27388fc6d0b3ee8c1ede0291009543c50e0dee356',
                parent_source_chart_id=r['source_chart_id'], parent_partition_path=c['partition_path'],
                plate_id=r['plate_id'], radial_layer=r['radial_layer'])
            key = W._hash(identity)
            if key not in charts:
                constraints, literals = {}, []
                for name, sign in c['constraints']:
                    constraints[name] = dict(kind='snapshot-rotated', constraint=r['constraints'][name],
                        snapshot_offset_s=G._qtext(old_time), angular_velocity_rad_s=G._store_vec(omega))
                    literals.append((name, sign))
                charts[key] = dict(constraints=constraints, literals=tuple(literals), members=[], omega=omega,
                                   inner={n: r['constraints'][n] for n, _ in literals}, layer=r['radial_layer'])
            charts[key]['members'].append(c['logical_cell_id'])
    rows = []
    t0 = time.perf_counter()
    for key, ch in sorted(charts.items()):
        cons, lits = ch['constraints'], ch['literals']
        end_upper = [Q(int(cells[m]['true_end_volume_bounds_m3'][1][0], 16), int(cells[m]['true_end_volume_bounds_m3'][1][1], 16))
                     for m in ch['members']]
        all_zero_end = all(u == 0 for u in end_upper)
        inactive_all = all(m in cells and not Q(int(cells[m]['end_volume_m3'][0], 16)) for m in ch['members'])
        found, detail = None, None
        t = time.perf_counter()
        with G.B._Arena(budget) as arena:
            identities = {n: G._plane_identity(v) for n, v in cons.items()}
            if G._consistent_literals(lits, identities) is None:
                found = 'C1-opposite-duplicate-rigid-plane'
            if found is None:
                cert = G._common_ray_cone_zero_volume(lits, cons, Q(0), duration, 0, arena)
                if cert is not None:
                    found, detail = 'C2-' + cert['kind'], cert['kind']
            if found is None:
                groups = {}
                for name, sign in lits:
                    path = G._rigid_plane_path(cons[name])
                    if path is None:
                        continue
                    normal, theta, w = path
                    groups.setdefault((theta, w), []).append(tuple(sign * q for q in normal))
                for (theta, w), normals in groups.items():
                    if len(normals) < 2:
                        continue
                    hit = zero_in_hull(normals)
                    if hit is not None:
                        found = 'C3-gordan-corotating'
                        detail = dict(group_size=len(normals), weights=[str(x) for x in hit[1]])
                        break
            # C4: the same proof on the INNER constraints at the single instant
            # where the parent interval ends. Every next-interval literal is that
            # inner plane rigidly rotated by one shared R(s), so an empty interior
            # at that instant is an empty chart for the whole next interval.
            if found is None and args.instant:
                for level in (0, 24, 48):
                    cert = G._common_ray_cone_zero_volume(lits, ch['inner'], old_time, old_time, level, arena)
                    if cert is not None:
                        found = 'C4-instant-L%d-%s' % (level, cert['kind'])
                        break
            # C5: zero volume at the parent end instant in EVERY grid voxel
            # (regular, native and excluded alike). The grid covers the whole
            # funded radial domain, so the chart is empty for the next interval.
            if found is None and args.voxels:
                layer = V.RadialLayer(*(W._decode(ch['layer'][k]) for k in ('radius_m', 'top_depth_m', 'bottom_depth_m')),
                                      budget=budget)
                lower2, upper2 = layer.bottom_radius_m**2, layer.top_radius_m**2
                failed = None
                tried = 0
                for at, box in grid:
                    low, high = box._radial_bounds()
                    if low >= upper2 or high <= lower2:
                        continue
                    tried += 1
                    zero = False
                    for level in (0, 16, 32):
                        detail = {}
                        bounds, _, _, _ = G._component_volume_certificate(layer, box, lits, ch['inner'],
                            old_time, level, arena, detail=detail)
                        if bounds[1] == 0:
                            zero = True
                            break
                        if not detail.get('angular_inner_empty'):
                            break
                    if not zero:
                        failed = at
                        break
                if failed is None:
                    found = 'C5-every-voxel-instant-zero(%d voxels)' % tried
                else:
                    detail = dict(first_unproved_voxel=list(failed))
        rows.append(dict(chart=key[:16], members=len(ch['members']), literals=len(lits),
                         all_zero_end=all_zero_end, inactive_all=inactive_all, proved=found,
                         seconds=round(time.perf_counter() - t, 4)))
        if found and not all_zero_end:
            print('SOUNDNESS VIOLATION', key, found, flush=True)
    summary = Counter()
    for r in rows:
        summary[('proved' if r['proved'] else 'not-proved', 'all-zero-end' if r['all_zero_end'] else 'has-positive')] += 1
    by_kind = Counter(r['proved'] for r in rows if r['proved'])
    proved_rows = [r for r in rows if r['proved']]
    result = dict(schema='atlas.private.chart-emptiness-census.r1', charts=len(rows),
        summary={'|'.join(k): v for k, v in summary.items()}, by_certificate=dict(by_kind),
        proved_members=sum(r['members'] for r in proved_rows), proved_literals=sum(r['literals'] for r in proved_rows),
        soundness_violations=sum(1 for r in rows if r['proved'] and not r['all_zero_end']),
        seconds=round(time.perf_counter() - t0, 3), rows=rows,
        rc1_package_digest=rc1_env.package_digest())
    with out.open('x', encoding='utf8') as f:
        json.dump(result, f, indent=1)
    print(json.dumps({k: v for k, v in result.items() if k != 'rows'}, indent=1))


if __name__ == '__main__':
    main()
