"""Rebuild the exact IV2 interval and partition offline, under RC1. READ-ONLY inputs.

Inputs: a byte-identical COPY of the pinned IV1 store, the saved IV2 proposal
(r4 artifacts) and the saved capture. Steps:
1. restore IV1's DifferentialInterval and endpoint SphereNetwork from the store;
2. rebuild IV2's Motion from the proposal's rates (the runtime's own
   _motion_from_rates) and call prepare_differential_interval with IV1 as prior;
   check interval_id and motion_id against the proposal;
3. build IV2's carried regions exactly as prepare_interval_partition does and
   call RC1's own _assemble_partition; check partition_id against the proposal.
Writes the IV2 interval record and partition (with supports) to a NEW gzip file
for later replays; nothing else is written. No heat, transport or advance runs.
"""
import argparse
import gzip
import json
import math
import sys
import time
from fractions import Fraction as Q
from hashlib import sha256
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import rc1_env  # noqa: E402
from rawstore import RawStore  # noqa: E402

STORE_SHA = '3f70c26de17535a96b7ddd494aee72900decee272ae0f88edab3a42af1548899'
IV1 = 'bc945eedff746d89992e474f4aa089eb333d03298e47a22f10ae6d54e0549bbc'
PROPOSAL2_SHA = None  # recorded, not pinned upstream


class Funding:
    """Duck-typed stand-in exposing only what _assemble_partition reads."""
    def __init__(self, funding_id, original):
        self.funding_id = funding_id
        self._original = original

    def descriptor(self):
        return self._original


class Collar:
    def __init__(self, plan_id, cells):
        self.plan_id = plan_id
        self._cells = cells

    def cell_geometries(self):
        return self._cells


class Sphere:
    def __init__(self, network):
        self.network = network


class Parent:
    def __init__(self, partition_id):
        self.partition_id = partition_id


def file_sha(path):
    h = sha256()
    with open(path, 'rb') as f:
        while block := f.read(1 << 22):
            h.update(block)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--store', required=True)
    ap.add_argument('--proposal', required=True)
    ap.add_argument('--capture', required=True)
    ap.add_argument('--output', required=True)
    ap.add_argument('--interval-only', action='store_true')
    ap.add_argument('--max-components', type=int, default=65536)
    args = ap.parse_args()
    out = Path(args.output)
    if out.exists():
        raise SystemExit('output exists')
    t0 = time.perf_counter()
    if file_sha(args.store) != STORE_SHA:
        raise SystemExit('store copy sha differs')
    proposal_raw = Path(args.proposal).read_bytes()
    proposal = json.loads(proposal_raw)
    rc1_env.install()
    import numpy as np
    from atlas_tectonics import integration_differential_geometry as G
    from atlas_tectonics import integration_differential_coupling as C
    from atlas_tectonics import integration_sphere as S
    from atlas_tectonics import integration_volume as V
    from atlas_tectonics import integration_wall_measures as W
    from atlas_tectonics import integration_transfer as TR
    from atlas_tectonics.resources import WorkBudget

    store = RawStore(args.store)
    snaps = store.snapshots()
    manifest = snaps[IV1]
    meta = manifest['metadata']
    geometry_ref = meta['differential_geometry']['record_blob']
    raw = store.record_bytes(manifest, geometry_ref)
    record = json.loads(raw)
    from atlas_tectonics.storage import ArrayStore
    # The palette/run-length branches of the runtime decoder never read self.
    decode = lambda codec, payload, dt, count: ArrayStore._decode(None, codec, payload, dt, count)
    fields = {k.removeprefix('differential-network:'): store.numeric_array(manifest, k, decode)
              for k in manifest['arrays'] if k.startswith('differential-network:')}
    certification = store.record(manifest, meta['differential_certification']['record_blob'])
    state = store.record(manifest, meta['exterior_state']['record_blobs']['state'])
    store.close()
    budget = WorkBudget(8 << 30, max_predicate_work_units=1 << 44)
    network = S.restore_network(record['endpoint_network'], fields, budget=budget)
    iv1 = G.DifferentialInterval.restore(record['interval'], network, budget=budget)
    assert iv1.interval_id == 'f0f91a5f053637300e8cb27819e3dbed83aa88e83c76968daf2a1ba6aa728c73', iv1.interval_id
    iteration = certification['iteration']
    # The iteration's declared supplies/sinks, typed by the runtime's own
    # stored-motion reader (IV1's motion carries the same declarations).
    motion1 = TR._motion(record['interval']['motion'])
    if ([s.record() for s in motion1.supplies] != iteration['supplies'] or
            [s.record() for s in motion1.sinks] != iteration['sinks']):
        raise SystemExit('IV1 motion supplies/sinks differ from the iteration declarations')
    supplies, sinks = motion1.supplies, motion1.sinks
    rates = np.asarray(proposal['actual_plate_rates_rad_s'], dtype=float)
    duration = float(iteration['duration_s'])
    end_step = network.step + 1
    motion = C._motion_from_rates(network, end_step, duration, rates, supplies, sinks)
    timings = {}
    t = time.perf_counter()
    iv2 = G.prepare_differential_interval(network, motion, end_time_s=network.time_s + duration,
        angular_velocity_by_plate_rad_s={p: tuple(map(float, row)) for p, row in zip(network.plate_ids, rates)},
        max_leaves=iteration['max_orientation_leaves'], budget=budget, prior_interval=iv1)
    timings['prepare_differential_interval_s'] = time.perf_counter() - t
    checks = dict(motion_id=(motion.motion_id, proposal['proposal']['motion_id']),
                  interval_id=(iv2.interval_id, proposal['proposal']['interval_id']))
    print(json.dumps(dict(checks=checks, timings=timings)), flush=True)
    result = dict(schema='atlas.private.iv2-rebuild.r1', checks=checks, timings=timings,
                  proposal_sha256=sha256(proposal_raw).hexdigest(), store_copy_sha256=STORE_SHA,
                  interval=iv2.descriptor())
    if not args.interval_only and checks['interval_id'][0] == checks['interval_id'][1]:
        capture = json.loads(gzip.decompress(Path(args.capture).read_bytes()))
        parent = capture['partition']
        supports = capture['supports']
        step = iv2.record()
        old_time = W._decode(parent['end_time_s']) - W._decode(parent['start_time_s'])
        regions = {}
        parent_partition_id = proposal_parent_id = None
        parent_partition_id = 'ada1e1288643132f367db9b27388fc6d0b3ee8c1ede0291009543c50e0dee356'
        t = time.perf_counter()
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
        # Births: the actual IV1-end finite stock state (start of IV2).
        from atlas_tectonics import integration_material as M
        stocks = state['finite_stock_state']['stocks']
        source_regions = parent['source_regions']
        original_source = parent['source']
        for boundary in step['boundary_paths']:
            if boundary['kind'] != S.RIDGE:
                continue
            for side, supply in boundary['supplies'].items():
                plate = boundary[side + '_plate_id']
                selected = [row for row in stocks if row['kind'] == 'source' and
                            row['lineage'].get('kind') == 'declared-finite-shell-birth' and
                            row['lineage'].get('supply') == supply and row['lineage'].get('plate_id') == plate]
                if not selected:
                    raise ValueError('ridge side lacks finite birth declaration')
                for row in selected:
                    lineage = row['lineage']
                    context = lineage['source_context']
                    if (context['sphere_state_id'] != original_source['sphere_state_id'] or
                            context['network_id'] != original_source['network_id'] or
                            context['boundary_id'] != boundary['boundary_id'] or context['plate_id'] != plate):
                        raise ValueError('finite birth lineage mismatch')
                    column = M.BirthColumn.from_record(lineage['birth_column'])
                    layers = M.layer_geometry(column, tuple(s.thickness_m for s in column.sublayers), budget=budget)
                    layer = layers[lineage['sublayer']]
                    matching = {o['radial_band'] for o in source_regions
                                if o['plate_id'] == plate and o['radial_layer'] == layer.record()}
                    if len(matching) != 1:
                        raise ValueError('birth radial band')
                    key = W._hash(dict(birth_interval_id=iv2.interval_id, stock_id=row['stock_id']))
                    regions[key] = dict(source_chart_id=key, kind='birth',
                        source_key=[lineage['source_id'], lineage['sublayer']], plate_id=plate,
                        radial_band=next(iter(matching)), chart=key, radial_layer=layer.record(),
                        finite_stock_id=row['stock_id'], stock_lineage=lineage,
                        birth_boundary_id=boundary['boundary_id'], birth_side=side)
        timings['regions_s'] = time.perf_counter() - t
        original = dict(source=parent['source'], excluded_static_cells=parent['excluded_static_cells'],
                        volume_map_id=parent['volume_map_id'], component_keys=parent['component_keys'],
                        component_registry=parent['component_registry'], collar_plan_id=parent['collar_plan_id'])
        native = [V.CartesianCell.from_record(c, budget=budget) for c in parent['native_cells']]
        funding = Funding(parent['funding_id'], original)
        collar = Collar(parent['collar_plan_id'], native)
        sphere = Sphere(network)
        # r3 refused IV2 above 8192; r4 ran it with a 65536 allowance (WORKFLOW_DECISIONS,
        # 14 Oct diagnosis). The value is part of the partition record and identity.
        max_components = args.max_components
        t = time.perf_counter()
        part = G._assemble_partition(funding, sphere, iv2, collar, original,
            [regions[k] for k in sorted(regions)],
            grid_lines=tuple(tuple(map(W._decode, axis)) for axis in parent['grid_lines']),
            max_components=max_components, budget=budget, parent_partition=Parent(parent_partition_id))
        timings['assemble_partition_s'] = time.perf_counter() - t
        fss = state['finite_stock_state']
        r = part.record()
        r.update(finite_state_id=fss['state_id'], finite_owner_id=fss['owner_id'],
                 component_registry_id=fss['registry_id'] if 'registry_id' in fss else parent['component_registry_id'])
        legacy_id = sha256(G._encoded(r)).hexdigest() if hasattr(G, '_encoded') else None
        issued = G._issue(G.DifferentialPartition, r, budget)
        checks['partition_id'] = (issued.partition_id, proposal['proposal']['partition_id'])
        checks['partition_legacy_sha'] = (legacy_id, proposal['proposal']['partition_id'])
        result['partition'] = r
        result['supports'] = [s.record() for s in part.supports]
        result['counts'] = dict(regions=len(regions), supports=len(result['supports']),
            components=sum(len(s['components']) for s in result['supports']))
        print(json.dumps(dict(checks=checks, timings=timings, counts=result['counts'])), flush=True)
    result['rc1_package_digest'] = rc1_env.package_digest()
    result['rc1_loaded_sources'] = rc1_env.loaded_sources()
    result['total_seconds'] = time.perf_counter() - t0
    result['budget'] = budget.statistics()
    with gzip.open(out, 'xt', encoding='utf8') as f:
        json.dump(result, f, sort_keys=True, separators=(',', ':'))
    print(json.dumps(dict(output=str(out), total_seconds=result['total_seconds'],
                          peak_reserved=result['budget'].get('peak_reserved_bytes'))))


if __name__ == '__main__':
    main()
