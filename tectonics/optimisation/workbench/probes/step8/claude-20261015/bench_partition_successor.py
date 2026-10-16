"""Successor partition preparation with a native parent: detached charts or not.

Usage: python -B bench_partition_successor.py OUT.json COUNT REBOOK(0|1) [GROUP]
GROUP is how many consecutive parent supports share one chart (1 = every
support its own chart, the copying worst case; the authentic IV1 partition has
134 source regions for 2016 supports, about 15 per region).

Builds a native parent partition of COUNT supports from the measured deep
template (test_live_partition.measure: depth-16 charts, 48x prior rotations),
one support at a time through the native issuer, then runs the transformed
prepare_interval_partition up to the assembly boundary. Assembly itself is
captured (it is the same code on both settings): at its entry the capture
records the run-budget reservation and the process's private bytes, which is
where retained parent exports would overlap assembly. SHARED=0 gives every
parent support its own chart (one carried region and one deep copy per
support, the worst case for copying); SHARED=1 lets all supports share one
chart. live_partition_patch.DETACH_ALL_PARENTS is set before the transformed
module runs. The fixture's transient runtime copy lives in R/L.
"""
import gc
import json
import sys
import time
from copy import deepcopy
from pathlib import Path

HERE = Path(__file__).resolve().parent
R = HERE.parents[2]
C = R/'compact-geometry-r1'
I = R.parent/'runtime-integration-r1'/'runtime-src'


def main():
    out, count, rebook = Path(sys.argv[1]), int(sys.argv[2]), sys.argv[3] == '1'
    group = int(sys.argv[4]) if len(sys.argv) > 4 else 1
    sys.path[:0] = [str(C), str(R), str(I)]
    import psutil
    import test_partition_native_patch as F
    F.HERE = R/'L'/'p1'/'p2'/'p3'/'p4'/'p5'
    (R/'L').mkdir(exist_ok=True)
    import live_partition_patch as LP
    LP.REBOOK_CHARTS = rebook
    import test_live_partition as TLP
    TLP.setUpModule()
    try:
        result = run(TLP, LP, psutil, count, group)
    finally:
        TLP.tearDownModule()
    result.update(rebook_charts=rebook, supports_per_chart=group, count=count)
    out.write_text(json.dumps(result, indent=1, sort_keys=True), encoding='utf8')
    print(json.dumps({k: result[k] for k in ('rebook_charts', 'supports_per_chart', 'count', 'regions',
                      'elapsed_to_assembly', 'at_assembly_reserved_bytes', 'region_object_bytes',
                      'at_assembly_private_bytes', 'peak_reserved_bytes')}))


def run(TLP, LP, psutil, count, group):
    D, T, Rmod, F = TLP.D, TLP.T, TLP.R, TLP.F
    from content_cache import create_retained_scope  # noqa: F401  (same import order as the tests)
    process = psutil.Process()
    budget = T.WorkBudget(8 << 30)
    body, sample = T.tiny_partition(budget, count=1, depth=16)
    template = sample[0]
    constraint = template['constraints']['carried:edge']
    while constraint['kind'] == 'snapshot-rotated':
        constraint = constraint['constraint']
    constraint['rays'][0]['prior_rotations'] *= 48
    template['components'][0]['constraints'] = [['carried:edge', 1], ['normal', -1]]
    body['support_ids'] = []
    body['identity_start_cells'] = []
    body['native_contacts'][0]['contacts'] = []
    body['max_components'] = count+1
    operands = F.source_operands(body, budget)
    del sample
    supports = []
    for i in range(count):
        row = deepcopy(template)
        component = row['components'][0]
        component.update(logical_cell_id=T.ident('bench-cell'+str(i)), parent_cell_id=T.ident('bench-parent'+str(i)))
        row['voxel_index'] = [i, 0, 0]
        row['max_components'] = count+1
        row['source_chart_id'] = T.ident('bench-chart'+str(i // group))
        support = D._issue(D.DifferentialSupport, row, budget)
        supports.append(support)
        body['support_ids'].append(support.support_id)
        body['identity_start_cells'].append(dict(parent_cell_id=component['parent_cell_id'],
                                                 cell_id=component['logical_cell_id']))
        body['native_contacts'][0]['contacts'].append(dict(support_id=support.support_id,
            logical_cell_id=component['logical_cell_id'], voxel_index=row['voxel_index'], axis=0, end=0))
        del row, component, support
    parent = D._issue(D.DifferentialPartition, body, budget)
    object.__setattr__(parent, '_supports', tuple(supports))
    del supports
    step = dict(parent_network_id=body['endpoint_network_id'], prior_trajectory_id=body['trajectory_id'],
                start_time_s=body['end_time_s'], end_time_s=T.q(2), duration_s=T.q(1),
                plate_angular_velocity_rad_s={'plate:A': [T.q(0)]*3}, boundary_paths=[])
    interval = D._issue(D.DifferentialInterval, step, budget)
    finite = Rmod.PreparedFiniteStocks(T.ident('registry'), [dict(stock_id='sink', kind='sink',
        lineage={'fixture': 'successor benchmark'}, volume_m3=T.q(1), exact={'mass': T.q(1)})],
        field_names=('mass',), nonnegative_fields=('mass',), budget=budget)
    state = finite.initial()
    gc.collect()
    private_after_parent = process.memory_info().private
    observed = {}
    def capture(funding, sphere, geometry, collar, original, regions, **kwargs):
        observed.update(at_assembly_reserved_bytes=budget.reserved_bytes,
                        at_assembly_private_bytes=process.memory_info().private,
                        regions=len(regions), elapsed_to_assembly=time.perf_counter()-started,
                        region_canonical_width=sum(LP._width(region) for region in regions),
                        region_object_bytes=object_bytes(regions))
        result = D._issue(D.DifferentialPartition, dict(body), budget)
        object.__setattr__(result, '_supports', ())
        return result
    import unittest.mock
    peak_before = budget.statistics()['peak_reserved_bytes']
    with unittest.mock.patch.object(D, '_assemble_partition', capture):
        started = time.perf_counter()
        successor = D.prepare_interval_partition(parent, interval, operands[0], object(), operands[1],
            finite_stock_state=state, max_components=count+10, budget=budget)
        elapsed = time.perf_counter()-started
    statistics = budget.statistics()
    result = dict(successor_seconds=elapsed, private_after_parent_bytes=private_after_parent,
                  parent_json_bytes=len(parent._json)+sum(len(s._json) for s in parent.supports),
                  peak_reserved_bytes=statistics['peak_reserved_bytes'], peak_reserved_before=peak_before,
                  after_reserved_bytes=statistics['reserved_bytes'], **observed)
    del successor, parent, interval, state
    finite.close()
    return result


def object_bytes(value):
    """Distinct Python objects reachable from value (sys.getsizeof each once):
    what the carried regions really hold, shared subtrees counted once."""
    seen, pending, total = set(), [value], 0
    while pending:
        item = pending.pop()
        if id(item) in seen:
            continue
        seen.add(id(item))
        total += sys.getsizeof(item)
        if type(item) is dict:
            pending.extend(item.keys())
            pending.extend(item.values())
        elif type(item) in (list, tuple):
            pending.extend(item)
    return total


if __name__ == '__main__':
    main()
