"""(b) projection: next charts of a REBUILT partition proved empty at its end instant.

For the IV2 -> IV3 transition no IV3 interval exists yet. The certificates used
here do not need it: C1 (opposite duplicate rigid planes; the shared next-interval
wrapper cancels from every identity comparison) and C4/C5 at the parent end
instant on the INNER (parent) constraints. An empty interior at that instant is
an empty chart for the whole next interval, whatever its rotation rate.
No parent end volumes exist for IV2, so there is no soundness cross-check here;
C5's soundness was cross-checked on IV1 -> IV2 (245/245, 0 violations).
Read-only; one JSONL evidence file per shard.
"""
import argparse
import gzip
import json
import sys
import time
from itertools import product
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import rc1_env  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--supports', required=True)
    ap.add_argument('--partition', required=True, help='rebuild output (partition header + interval)')
    ap.add_argument('--output', required=True)
    ap.add_argument('--shard', type=int, default=0)
    ap.add_argument('--shards', type=int, default=1)
    args = ap.parse_args()
    out = Path(args.output)
    if out.exists():
        raise SystemExit('output exists')
    rc1_env.install()
    from atlas_tectonics import integration_differential_geometry as G
    from atlas_tectonics import integration_volume as V
    from atlas_tectonics import integration_wall_measures as W
    from atlas_tectonics.resources import WorkBudget
    budget = WorkBudget(4 << 30, max_predicate_work_units=1 << 44)
    rebuild = json.loads(gzip.decompress(Path(args.partition).read_bytes()))
    parent, step = rebuild['partition'], rebuild['interval']
    old_time = W._decode(parent['end_time_s']) - W._decode(parent['start_time_s'])
    lines = tuple(tuple(map(W._decode, a)) for a in parent['grid_lines'])
    origin, basis = G._load_vec(parent['grid_origin_m']), tuple(map(G._load_vec, parent['grid_basis']))
    grid = [(at, V.CartesianCell(tuple(lines[j][at[j]] for j in range(3)), tuple(lines[j][at[j]+1] for j in range(3)),
                                 origin, basis, budget=budget))
            for at in product(*(range(len(a)-1) for a in lines))]
    charts = {}
    with gzip.open(args.supports, 'rt', encoding='utf8') as f:
        f.readline()
        for line in f:
            r = json.loads(line)
            omega = G._load_vec(step['plate_angular_velocity_rad_s'][r['plate_id']])  # placeholder wrapper rate
            for c in r['components']:
                key = W._hash(dict(parent_partition_id=parent['partition_id'] if 'partition_id' in parent else None,
                    parent_source_chart_id=r['source_chart_id'], parent_partition_path=c['partition_path'],
                    plate_id=r['plate_id'], radial_layer=r['radial_layer']))
                if key not in charts:
                    lits = tuple((n, s) for n, s in c['constraints'])
                    charts[key] = dict(literals=lits, inner={n: r['constraints'][n] for n, _ in lits},
                        wrapped={n: dict(kind='snapshot-rotated', constraint=r['constraints'][n],
                                         snapshot_offset_s=G._qtext(old_time), angular_velocity_rad_s=G._store_vec(omega))
                                 for n, _ in lits},
                        layer=r['radial_layer'], members=0)
                charts[key]['members'] += 1
    keys = sorted(charts)[args.shard::args.shards]
    t0 = time.perf_counter()
    with out.open('x', encoding='utf8') as sink:
        for key in keys:
            ch = charts[key]
            lits = ch['literals']
            found, tried = None, 0
            t = time.perf_counter()
            with G.B._Arena(budget) as arena:
                identities = {n: G._plane_identity(v) for n, v in ch['wrapped'].items()}
                if G._consistent_literals(lits, identities) is None:
                    found = 'C1-opposite-duplicate-rigid-plane'
                if found is None:
                    for level in (0, 24):
                        cert = G._common_ray_cone_zero_volume(lits, ch['inner'], old_time, old_time, level, arena)
                        if cert is not None:
                            found = 'C4-instant-L%d-%s' % (level, cert['kind'])
                            break
                if found is None:
                    layer = V.RadialLayer(*(W._decode(ch['layer'][k]) for k in ('radius_m', 'top_depth_m', 'bottom_depth_m')),
                                          budget=budget)
                    lower2, upper2 = layer.bottom_radius_m**2, layer.top_radius_m**2
                    ok = True
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
                            ok = False
                            break
                    if ok:
                        found = 'C5-every-voxel-instant-zero'
            sink.write(json.dumps(dict(chart=key[:16], members=ch['members'], literals=len(lits), proved=found,
                                       voxels_tried=tried, seconds=round(time.perf_counter() - t, 4))) + '\n')
            sink.flush()
        sink.write(json.dumps(dict(done=True, charts=len(keys), seconds=time.perf_counter() - t0,
                                   rc1_package_digest=rc1_env.package_digest())) + '\n')


if __name__ == '__main__':
    main()
