"""Rebuild a next-interval partition offline (static->IV1 or IV1->IV2) under a chosen runtime.

Same route as rebuild_iv2.py (which first established the exact IV2 rebuild):
prepare_interval_partition's carried-region build, its birth declarations, and the
runtime's own _assemble_partition. With --growth the runtime must be a test
composition containing the growth-successor transform; its own
_growth_drop_empty_charts is then applied at the same point as the composed hook.
Baseline runs check the partition_id against the saved one; candidate runs record
their (new) identity. Read-only inputs; writes one gzip JSON.
"""
import argparse
import gzip
import json
import sys
import time
from fractions import Fraction as Q
from hashlib import sha256
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import rc1_env  # noqa: E402
from rawstore import RawStore  # noqa: E402
from rebuild_iv2 import Funding, Collar, Sphere, file_sha, STORE_SHA, IV1  # noqa: E402

ROOT = '674ef5f3fcf41cb45e4b3e2ac2543e6ab0918b03f5a25dbc951363489a81bfad'
SAVED = dict(iv1='ada1e1288643132f367db9b27388fc6d0b3ee8c1ede0291009543c50e0dee356',
             iv2='c241d4f5f15eef0dae658609f3b2ba829c4a5b3f8235eab3ef5cd4394527cbaa')


def issued_parent(parent, partition_id, budget):
    """The parent partition as the runtime itself issues one (G._issue), checked against its id.

    RC1's builder reads only parent_partition.partition_id, so an id stand-in sufficed. The Step 8
    live-partition stage (live_partition_patch.resolve_scope) requires an actual issued
    DifferentialPartition, as production's prepare_interval_partition does. Its supports are not
    needed by the builder and are left empty.
    """
    from atlas_tectonics import integration_differential_geometry as G
    body = {k: v for k, v in parent.items() if k not in ('partition_id', 'supports')}
    issued = G._issue(G.DifferentialPartition, body, budget)
    object.__setattr__(issued, '_supports', ())
    if issued.partition_id != partition_id:
        raise SystemExit('issued parent partition id %s differs from the saved %s' % (issued.partition_id, partition_id))
    return issued


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--transition', choices=('iv1', 'iv2'), required=True)
    ap.add_argument('--store', required=True)
    ap.add_argument('--capture', required=True)
    ap.add_argument('--iv2-interval', help='rebuild output holding the exact IV2 interval (for iv2)')
    ap.add_argument('--proposal', help='r4 proposal-02 (for iv2)')
    ap.add_argument('--runtime', default='rc1')
    ap.add_argument('--growth', action='store_true')
    ap.add_argument('--output', required=True)
    args = ap.parse_args()
    out = Path(args.output)
    if out.exists():
        raise SystemExit('output exists')
    t0 = time.perf_counter()
    if file_sha(args.store) != STORE_SHA:
        raise SystemExit('store copy sha differs')
    rc1_env.install(args.runtime)
    import numpy as np
    from atlas_tectonics import integration_differential_geometry as G
    from atlas_tectonics import integration_differential_coupling as C
    from atlas_tectonics import integration_sphere as S
    from atlas_tectonics import integration_volume as V
    from atlas_tectonics import integration_wall_measures as W
    from atlas_tectonics import integration_transfer as TR
    from atlas_tectonics import integration_material as M
    from atlas_tectonics.resources import WorkBudget
    from atlas_tectonics.storage import ArrayStore
    if args.growth and not hasattr(G, '_growth_drop_empty_charts'):
        raise SystemExit('runtime lacks the growth-successor transform')
    store = RawStore(args.store)
    snaps = store.snapshots()
    meta = snaps[IV1]['metadata']
    record = store.record(snaps[IV1], meta['differential_geometry']['record_blob'])
    decode = lambda codec, payload, dt, count: ArrayStore._decode(None, codec, payload, dt, count)
    fields = {k.removeprefix('differential-network:'): store.numeric_array(snaps[IV1], k, decode)
              for k in snaps[IV1]['arrays'] if k.startswith('differential-network:')}
    budget = WorkBudget(8 << 30, max_predicate_work_units=1 << 44)
    network = S.restore_network(record['endpoint_network'], fields, budget=budget)
    iv1 = G.DifferentialInterval.restore(record['interval'], network, budget=budget)
    capture = json.loads(gzip.decompress(Path(args.capture).read_bytes()))
    if args.transition == 'iv1':
        parent = store.record(snaps[ROOT], snaps[ROOT]['metadata']['differential_partition']['record_blobs']['partition'])
        supports = parent.pop('supports')
        parent_partition_id = parent.pop('partition_id')
        start_state = store.record(snaps[ROOT], snaps[ROOT]['metadata']['exterior_state']['record_blobs']['state'])
        interval, step = iv1, iv1.record()
        old_time = (W._decode(parent['end_time_s'])-W._decode(parent['start_time_s'])
                    if parent['scope'] != 'initial-current' else Q(0))
        max_components = capture['partition']['max_components']
    else:
        parent = dict(capture['partition'])
        supports = capture['supports']
        parent_partition_id = SAVED['iv1']
        start_state = store.record(snaps[IV1], meta['exterior_state']['record_blobs']['state'])
        rebuilt = json.loads(gzip.decompress(Path(args.iv2_interval).read_bytes()))
        proposal = json.loads(Path(args.proposal).read_bytes())
        certification = store.record(snaps[IV1], meta['differential_certification']['record_blob'])
        iteration = certification['iteration']
        motion1 = TR._motion(record['interval']['motion'])
        rates = np.asarray(proposal['actual_plate_rates_rad_s'], dtype=float)
        duration = float(iteration['duration_s'])
        motion = C._motion_from_rates(network, network.step+1, duration, rates, motion1.supplies, motion1.sinks)
        interval = G.prepare_differential_interval(network, motion, end_time_s=network.time_s+duration,
            angular_velocity_by_plate_rad_s={p: tuple(map(float, row)) for p, row in zip(network.plate_ids, rates)},
            max_leaves=iteration['max_orientation_leaves'], budget=budget, prior_interval=iv1)
        if interval.interval_id != rebuilt['interval']['interval_id']:
            raise SystemExit('IV2 interval differs from the exact rebuild')
        step = interval.record()
        old_time = W._decode(parent['end_time_s'])-W._decode(parent['start_time_s'])
        max_components = 65536
    store.close()
    timings = {}
    t = time.perf_counter()
    regions = {}
    for r in supports:
        omega = G._load_vec(step['plate_angular_velocity_rad_s'][r['plate_id']])
        for component in r['components']:
            identity = dict(parent_partition_id=parent_partition_id,
                parent_source_chart_id=r['source_chart_id'], parent_partition_path=component['partition_path'],
                plate_id=r['plate_id'], radial_layer=r['radial_layer'])
            key = W._hash(identity)
            if key not in regions:
                constraints, literals = {}, []
                for name, sign in component['constraints']:
                    value = r['constraints'][name]
                    if value['kind'] == 'fixed-plane':
                        raise ValueError('fixed exclusion in carried material')
                    constraints[name] = dict(kind='snapshot-rotated', constraint=value,
                        snapshot_offset_s=G._qtext(old_time), angular_velocity_rad_s=G._store_vec(omega))
                    literals.append((name, sign))
                regions[key] = dict(source_chart_id=key, kind='inherited', source_key=r['source_key'],
                    plate_id=r['plate_id'], radial_band=r['radial_band'], chart=key,
                    radial_layer=r['radial_layer'], source_constraint_chart=dict(constraints=constraints, literals=literals),
                    parent_owner_ray_ids=component['owner_ray_ids'], parent_cells={}, parent_chart=identity)
            cells = regions[key]['parent_cells']
            at = ','.join(map(str, r['voxel_index']))
            if at in cells:
                raise ValueError('duplicate carried slot')
            cells[at] = component['logical_cell_id']
    timings['regions_s'] = time.perf_counter()-t
    native = [V.CartesianCell.from_record(c, budget=budget) for c in parent['native_cells']]
    collar = Collar(parent['collar_plan_id'], native)
    dropped = 0
    if args.growth:
        t = time.perf_counter()
        before = len(regions)
        regions = G._growth_drop_empty_charts(regions, step, old_time, parent['grid_lines'], collar, budget)
        dropped = before-len(regions)
        timings['growth_b_s'] = time.perf_counter()-t
    stocks = start_state['finite_stock_state']['stocks']
    source_regions, original_source = parent['source_regions'], parent['source']
    for boundary in step['boundary_paths']:
        if boundary['kind'] != S.RIDGE:
            continue
        for side, supply in boundary['supplies'].items():
            plate = boundary[side+'_plate_id']
            selected = [row for row in stocks if row['kind'] == 'source' and
                        row['lineage'].get('kind') == 'declared-finite-shell-birth' and
                        row['lineage'].get('supply') == supply and row['lineage'].get('plate_id') == plate]
            if not selected:
                raise ValueError('ridge side lacks finite birth declaration')
            for row in selected:
                lineage = row['lineage']
                column = M.BirthColumn.from_record(lineage['birth_column'])
                layers = M.layer_geometry(column, tuple(s.thickness_m for s in column.sublayers), budget=budget)
                layer = layers[lineage['sublayer']]
                matching = {o['radial_band'] for o in source_regions
                            if o['plate_id'] == plate and o['radial_layer'] == layer.record()}
                if len(matching) != 1:
                    raise ValueError('birth radial band')
                key = W._hash(dict(birth_interval_id=interval.interval_id, stock_id=row['stock_id']))
                regions[key] = dict(source_chart_id=key, kind='birth',
                    source_key=[lineage['source_id'], lineage['sublayer']], plate_id=plate,
                    radial_band=next(iter(matching)), chart=key, radial_layer=layer.record(),
                    finite_stock_id=row['stock_id'], stock_lineage=lineage,
                    birth_boundary_id=boundary['boundary_id'], birth_side=side)
    original = dict(source=parent['source'], excluded_static_cells=parent['excluded_static_cells'],
                    volume_map_id=parent['volume_map_id'], component_keys=parent['component_keys'],
                    component_registry=parent['component_registry'], collar_plan_id=parent['collar_plan_id'])
    t = time.perf_counter()
    part = G._assemble_partition(Funding(parent['funding_id'], original), Sphere(network), interval, collar, original,
        [regions[k] for k in sorted(regions)], grid_lines=tuple(tuple(map(W._decode, a)) for a in parent['grid_lines']),
        max_components=max_components, budget=budget, parent_partition=issued_parent(parent, parent_partition_id, budget))
    timings['assemble_partition_s'] = time.perf_counter()-t
    fss = start_state['finite_stock_state']
    r = part.record()
    r.update(finite_state_id=fss['state_id'], finite_owner_id=fss['owner_id'],
             component_registry_id=fss['registry_id'] if 'registry_id' in fss else parent.get('component_registry_id',
                                                                                              capture['partition']['component_registry_id']))
    partition_id = sha256(G._encoded(r)).hexdigest()
    supports_out = [s.record() for s in part.supports]
    result = dict(schema='atlas.private.next-partition-rebuild.r1', transition=args.transition, runtime=args.runtime,
                  growth=args.growth, partition_id=partition_id, saved_partition_id=SAVED[args.transition],
                  identical_to_saved=partition_id == SAVED[args.transition], dropped_charts=dropped,
                  counts=dict(regions=len(regions), supports=len(supports_out),
                              components=sum(len(s['components']) for s in supports_out),
                              stored_constraints=sum(len(s['constraints']) for s in supports_out),
                              support_record_bytes=sum(len(G._encoded(s)) for s in supports_out)),
                  timings=timings, total_seconds=time.perf_counter()-t0, budget=budget.statistics(),
                  package_digest=rc1_env.package_digest(), partition=r, supports=supports_out)
    with gzip.open(out, 'xt', encoding='utf8') as f:
        json.dump(result, f, sort_keys=True, separators=(',', ':'))
    try:  # diagnostic: this process's lifetime peaks (Windows)
        import psutil
        info = psutil.Process().memory_info()
        result['process_memory'] = dict(peak_working_set_bytes=getattr(info, 'peak_wset', None),
                                        peak_commit_bytes=getattr(info, 'peak_pagefile', None))
    except Exception as exc:
        result['process_memory'] = dict(error=repr(exc))
    print(json.dumps({k: v for k, v in result.items() if k not in ('partition', 'supports', 'budget')}, indent=1))


if __name__ == '__main__':
    main()
