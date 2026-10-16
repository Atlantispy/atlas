"""D1-B before/after on the authentic interval-1 state cells (read-only probe).

Usage: python -B measure_carried_start.py ARM OUT.json      ARM: before | after

- before: the pre-D1-B transform of _carried_start_cells (every row decoded and
  held in one dictionary);
- after: the D1-B transform (an index; each row exported when it is read).

Each arm runs the actual transformed function on the authentic IV1 state
cells (read from the original r9 store, read-only, through the census
binding, and appended through the live CellSink exactly as the capacity
harness's state overlap does) with a one-to-one identity start (child i keeps
parent i's lineage). It then replays the owner's reads at the next interval's
start:
- close_graph: starts, geometry volume errors and booked quadrature;
- transport: one lookup per graph cell with its exact values, and the
  measure-audit prior.

The decoded source record is released before the arm starts. Peaks come from
the budget and retained-scope statistics and the OS process peak working set.
No tracemalloc, so the timings are unperturbed.
"""
import gc
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
R = HERE.parents[2]
sys.path.insert(0, str(R/'compact-geometry-r1'))

import measure_live_capacity as CAP  # noqa: E402 - puts C, R and I on sys.path first

BEFORE_D1B = (
    ("previous = {row['cell_id']: row for row in state['cells']}",
     "previous = {row['cell_id']: row for row in _SV.rows(state['cells'])}"),
    ('carried[child] = dict(old, cell_id=child)', 'carried[child] = _SV.copy_row(old, cell_id=child)'),
)
PARTITION = 'p'*64


def carried_start(arm):
    import ast

    import exchange_record_patch as E
    import spatial_indexed_patch as X
    import spatial_transfer as S
    import spatial_validation_patch as V
    from atlas_tectonics import integration_spatial_owner as O
    source = E.holder_source(X.transform(S.spatial_owner_source(
        (CAP.I/'atlas_tectonics/integration_spatial_owner.py').read_text(encoding='utf8'))))
    source = (V.owner_source(source) if arm == 'after' else
              V._function(source, '_carried_start_cells', BEFORE_D1B))
    node = next(n for n in ast.parse(source).body
                if isinstance(n, ast.FunctionDef) and n.name == '_carried_start_cells')
    env = {**O.__dict__, '_SV': V}
    exec(compile(ast.Module(body=[node], type_ignores=[]), '<'+arm+'-carried-start>', 'exec'), env)  # noqa: S102
    return env['_carried_start_cells'], O


def main():
    arm, out = sys.argv[1], Path(sys.argv[2])
    CAP.require(arm in ('before', 'after'), 'arm must be before or after')
    import psutil

    import historical_admission as H
    import live_spatial_patch as L
    from atlas_tectonics.resources import WorkBudget
    from atlas_tectonics.storage import Compression, StoreLimits
    from content_cache import create_retained_scope
    from measure_live_mesh_capacity import _read_record
    function, O = carried_start(arm)
    census = CAP.read_census()['census']
    endpoint = census['endpoint']
    budget = WorkBudget(4 << 30)
    scope = create_retained_scope(budget, process_epoch='d1b-carried-start-probe')
    result = {'arm': arm, 'schema': 'atlas.step8.d1b-carried-start-probe.v1'}
    with H.open_original_readonly(limits=StoreLimits(**endpoint['store_limits']),
                                  compression=Compression(**endpoint['store_compression']),
                                  budget=budget) as source:
        held = _read_record(source, census['records']['spatial-record:state'], budget=budget,
                            check=lambda: None, evidence=[])
    rows = held.value['cells']
    names = sorted(rows[0]['exact'])
    sink = L.CellSink(scope, check=lambda: None)
    for row in rows:
        sink.append(row)
    cells = sink.finish()
    pairs = [(row['cell_id'], 'child:'+str(i), row['source_key']) for i, row in enumerate(rows)]
    fields = sorted(rows[0])
    del held, rows, row
    gc.collect()
    shape = {'physical_geometry_family': 'differential-plate-component-partition-v1',
             'parent_partition_id': PARTITION,
             'identity_start_cells': [{'parent_cell_id': p, 'cell_id': c} for p, c, _ in pairs],
             'cells': [{'cell_id': c, 'kind': 'exterior', 'source_key': k} for _, c, k in pairs]}
    state = {'cells': cells, 'thermal_mesh': {'partition_id': PARTITION}}
    keys = [c for _, c, _ in pairs]
    process = psutil.Process()
    base_reserved, base_retained = budget.reserved_bytes, scope.stats().retained_bytes
    result.update(rows=len(pairs), row_fields=fields, exact_fields=len(names),
                  base_reserved_bytes=base_reserved, base_retained_bytes=base_retained)
    peak = [0]

    def sample():
        peak[0] = max(peak[0], budget.reserved_bytes-base_reserved)

    timings, reads = {}, 0
    started = time.perf_counter()
    try:
        carried = function(state, shape)
    except Exception as error:  # noqa: BLE001 - a refusal is the before-arm measurement
        import traceback
        chain = CAP.exception_chain(error)
        result.update(refused=True, refusal={'type': type(error).__name__, 'message': str(error),
                      'first_raised': {'type': type(chain[-1]).__name__, 'message': str(chain[-1])}},
                      seconds_to_refusal=time.perf_counter()-started,
                      retained_at_refusal_bytes=scope.stats().retained_bytes-base_retained,
                      reserved_at_refusal_bytes=budget.reserved_bytes-base_reserved)
        for item in chain:
            traceback.clear_frames(item.__traceback__)
            item.__traceback__ = None
        chain = item = carried = None
    else:
        timings['carried_start'] = time.perf_counter()-started
        sample()
        result['refused'] = False
        result['held_after_start_bytes'] = budget.reserved_bytes-base_reserved
        mark = time.perf_counter()
        starts = {}
        for key, row in carried.items():
            sample()
            starts[key] = O._q(row['volume_m3'])
            reads += 1
        timings['close_graph_starts'] = time.perf_counter()-mark
        mark = time.perf_counter()
        errors = {}
        if 'geometry_volume_error_m3' in fields:
            for key, row in carried.items():
                sample()
                errors[key] = tuple(map(O._q, row['geometry_volume_error_m3']))
                reads += 1
        timings['close_graph_errors'] = time.perf_counter()-mark
        mark = time.perf_counter()
        booked = {}
        for key in keys:
            sample()
            booked[key] = O._q(carried[key]['exact'][names[0]]) if key in carried else 0
            reads += 1
        timings['close_graph_booked_quadrature'] = time.perf_counter()-mark
        mark = time.perf_counter()
        stocks = []
        for key in keys:
            before = carried.get(key)
            sample()
            stocks.append({k: O._q(v) for k, v in before['exact'].items()})
            reads += 1
        before = None
        timings['transport_values'] = time.perf_counter()-mark
        mark = time.perf_counter()
        prior = {key: O._q(carried[key]['volume_m3']) if key in carried else 0 for key in keys}
        reads += len(keys)
        timings['transport_measure_prior'] = time.perf_counter()-mark
        sample()
        result.update(row_reads=reads, starts=len(starts), errors=len(errors), booked=len(booked),
                      stocks=len(stocks), prior=len(prior))
        del starts, errors, booked, stocks, prior
    result.update(timings_seconds=timings, total_seconds=time.perf_counter()-started,
                  reserved_peak_delta_bytes=peak[0],
                  budget_peak_reserved_bytes=budget.statistics()['peak_reserved_bytes'],
                  retained_peak_bytes=scope.stats().peak_retained_bytes,
                  process_peak_working_set_bytes=process.memory_info().peak_wset,
                  process_rss_bytes=process.memory_info().rss)
    carried = None
    gc.collect()
    cells.close()
    sink._record.close()
    gc.collect()
    result['released_reserved_bytes'] = budget.reserved_bytes
    out.write_text(json.dumps(result, indent=1), encoding='utf8')
    print(json.dumps({k: result[k] for k in ('arm', 'refused', 'total_seconds', 'reserved_peak_delta_bytes')
                      if k in result}))


if __name__ == '__main__':
    main()
