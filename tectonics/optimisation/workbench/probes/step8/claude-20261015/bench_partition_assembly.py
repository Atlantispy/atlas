"""The actual transformed _assemble_partition at real row depth and scale.

Usage: python -B bench_partition_assembly.py OUT.json COUNT VARIANT MODE
VARIANT before = the takeover live_partition_patch.py (and partition_native_patch.py)
        from before-src, hash-checked; after = the current C files.
MODE    native (no compact scope) or compact (the caller's retained scope).

The per-support scientific step (partition_physical_support) is a controlled
operand returning the measured deep template row (test_live_partition.measure:
depth-16 charts, 48x prior rotations) for each voxel; everything else is the
real transformed assembly: row ownership, issuance, contact and identity
projections, the result dict and the final native issue or compact finish.
The grid gives COUNT non-native voxels around one native box. Records wall
time, run-budget peak, process private/peak working set, and the partition ID
(compared across variants as a scale exactness check). Writes stay in R.
"""
import gc
import hashlib
import json
import sys
import tempfile
import time
from copy import deepcopy
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
R = HERE.parents[2]
C = R/'compact-geometry-r1'
I = R.parent/'runtime-integration-r1'/'runtime-src'
BEFORE = ('live_partition_patch.py', 'partition_native_patch.py', 'partition_v2.py', 'partition_workflow_patch.py')


def main():
    out, count, variant, mode = Path(sys.argv[1]), int(sys.argv[2]), sys.argv[3], sys.argv[4]
    assert variant in ('before', 'after') and mode in ('native', 'compact', 'native-convert')
    (R/'L').mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='bench-', dir=R/'L') as directory:
        if variant == 'before':
            recorded = json.loads((HERE/'baseline-hashes-takeover.json').read_text(encoding='utf8'))
            for name in BEFORE:
                raw = (HERE/'before-src'/name).read_bytes()
                assert hashlib.sha256(raw).hexdigest() == recorded['compact-geometry-r1/'+name]['sha256'], name
                (Path(directory)/name).write_bytes(raw)
        sys.path[:0] = [directory, str(C), str(R), str(I)]
        import test_partition_native_patch as F
        F.HERE = R/'L'/'p1'/'p2'/'p3'/'p4'/'p5'
        import test_live_partition as TLP
        TLP.setUpModule()
        try:
            result = run(TLP, count, mode)
        finally:
            TLP.tearDownModule()
        result['loaded'] = {name: getattr(sys.modules.get(name[:-3]), '__file__', None) for name in BEFORE}
    result.update(variant=variant, mode=mode, count=count)
    out.write_text(json.dumps(result, indent=1, sort_keys=True), encoding='utf8')
    print(json.dumps({k: result.get(k) for k in ('variant', 'mode', 'count', 'supports', 'assemble_seconds',
                      'peak_reserved_bytes', 'private_delta_bytes', 'peak_wset_bytes', 'partition_id',
                      'convert_seconds', 'convert_peak_reserved_bytes', 'convert_private_delta_bytes',
                      'converted_identity')}))


def run(TLP, count, mode):
    import psutil
    from content_cache import create_retained_scope
    D, T, F, L = TLP.D, TLP.T, TLP.F, TLP.L
    process = psutil.Process()
    budget = T.WorkBudget(12 << 30)
    scope = create_retained_scope(budget, process_epoch='bench-partition-assembly') if mode == 'compact' else None
    body, sample = T.tiny_partition(budget, count=1, depth=16)
    template = sample[0]
    constraint = template['constraints']['carried:edge']
    while constraint['kind'] == 'snapshot-rotated':
        constraint = constraint['constraint']
    constraint['rays'][0]['prior_rotations'] *= 48
    template['components'][0].pop('parent_cell_id', None)
    template['components'][0].pop('start_identity', None)
    operands = F.source_operands(body, budget, initial=True)
    funding = operands[0]
    current = {'network_id': body['network_id'], 'start_time_s': T.q(0), 'end_time_s': T.q(0)}
    geometry = D._issue(D.CurrentGeometry, current, budget)
    box = D.V.CartesianCell((-1, -1, -1), (1, 1, 1), budget=budget)
    collar = SimpleNamespace(plan_id=body['collar_plan_id'], _budget=budget, cell_geometries=lambda: (box,))
    sphere = SimpleNamespace(network=SimpleNamespace(plate_ids=('plate:A',), sphere=SimpleNamespace(radius_m=10)))
    region = {'source_key': ['patch', 0], 'plate_id': 'plate:A', 'source_face_id': 'face', 'radial_band': 0,
              'chart': 0, 'radial_layer': template['radial_layer'], 'source_chart_id': T.ident('bench-region')}
    original = {'source': body['source'], 'volume_map_id': body['volume_map_id'],
                'component_keys': body['component_keys']}
    # x lines: COUNT/8 voxel columns either side of the native box; 3x3 in y, z.
    side = max(1, count//18)
    left = [Fraction(-10)+Fraction(9*i, side) for i in range(side)]
    right = [Fraction(1)+Fraction(9*i, side) for i in range(1, side+1)]
    grid = (tuple(left+[Fraction(-1), Fraction(1)]+right), (-10, -1, 1, 10), (-10, -1, 1, 10))
    def support_operand(interval, plate, layer, voxel, *, _owned_result=False, **kwargs):
        row = deepcopy(template)
        row.update(voxel=voxel.record(), current_geometry_id=interval.geometry_id,
                   interval_id=None, network_id=current['network_id'])
        if not _owned_result:
            return D._issue(D.DifferentialSupport, row, budget)
        return L.owned_support(row, budget)
    import unittest.mock
    gc.collect()
    before = process.memory_info()
    peak_before = budget.statistics()['peak_reserved_bytes']
    with unittest.mock.patch.object(D, 'partition_physical_support', support_operand):
        started = time.perf_counter()
        partition = D._assemble_partition(funding, sphere, geometry, collar, original, [region],
            grid_lines=grid, max_components=10*count+100, budget=budget,
            **({} if scope is None else {'compact_scope': scope}))
        elapsed = time.perf_counter()-started
    after = process.memory_info()
    statistics = budget.statistics()
    result = {'assemble_seconds': elapsed, 'supports': len(partition.supports), 'partition_id': partition.partition_id,
              'peak_reserved_bytes': statistics['peak_reserved_bytes'], 'peak_reserved_before': peak_before,
              'private_delta_bytes': after.private-before.private, 'private_after_bytes': after.private,
              'peak_wset_bytes': getattr(after, 'peak_wset', None)}
    if mode == 'compact':
        result['converted_identity'] = TLP.PN.compact_view(partition).identity().sha256
    if mode == 'native-convert':
        # The storage conversion every native partition takes before publication.
        import partition_workflow_patch as PW
        convert_scope = create_retained_scope(budget, process_epoch='bench-partition-convert')
        gc.collect()
        before = process.memory_info()
        budget_peak = budget.statistics()['peak_reserved_bytes']
        started = time.perf_counter()
        view = PW.convert_native(partition, budget, scope=convert_scope)
        result['convert_seconds'] = time.perf_counter()-started
        after = process.memory_info()
        result['convert_peak_reserved_bytes'] = budget.statistics()['peak_reserved_bytes']
        result['convert_peak_reserved_before'] = budget_peak
        result['convert_private_delta_bytes'] = after.private-before.private
        result['converted_identity'] = view.identity().sha256
        view.close()
        del view
        gc.collect()
        convert_scope.close()
    del partition
    gc.collect()
    if scope is not None:
        scope.close()
    return result


if __name__ == '__main__':
    main()
