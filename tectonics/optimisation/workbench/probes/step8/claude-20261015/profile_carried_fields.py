"""Backlog item 12 (D1-B lazy per-field rows): per-pass cost of whole-row against per-field exports.

Usage: python -B profile_carried_fields.py OUT_JSON

The authentic IV1 parent state (spatial-record:state, read query-only from the reviewed ORIGINAL
through historical_admission.open_original_readonly) is streamed into the Step 8 CellSink exactly
as the capacity state overlap does. Over the D1-B carried mapping (identity carry), it times:
- the carried start: spatial_validation_patch.start_rows plus carried_rows/carry;
- 'whole': today's read, carried.values() then row['volume_m3'] (one whole-row export per row);
- one field export per row for each field close_graph and transport read: volume_m3,
  geometry_volume_error_m3, exact, and exact[material_quadrature_m3].
Every per-field value is compared with the same value of the whole-row export (the lazy rows'
exactness condition). Nothing is written except OUT_JSON.
"""
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
R = HERE.parents[2]
C = R/'compact-geometry-r1'
I = R.parent/'runtime-integration-r1'/'runtime-src'
B_NAME = 'material_quadrature_m3'
FIELDS = ('volume_m3', 'geometry_volume_error_m3', 'exact')


def main():
    sys.path[:0] = [str(C), str(R), str(I)]
    import historical_admission as H
    import live_spatial_patch as L
    import measure_live_capacity as CAP
    import spatial_validation_patch as V
    from atlas_tectonics.resources import WorkBudget
    from atlas_tectonics.storage import Compression, StoreLimits
    from content_cache import create_retained_scope
    from measure_live_mesh_capacity import _read_record
    census = CAP.read_census()['census']
    endpoint = census['endpoint']
    budget = WorkBudget(8 << 30)
    scope = create_retained_scope(budget, process_epoch='d1b-field-profile')
    result = {'schema': 'atlas.private.d1b-field-profile.v1', 'source': 'spatial-record:state (ORIGINAL, query-only)'}
    started = time.perf_counter()
    with H.open_original_readonly(limits=StoreLimits(**endpoint['store_limits']),
                                  compression=Compression(**endpoint['store_compression']), budget=budget) as source:
        held = _read_record(source, census['records']['spatial-record:state'], budget=budget,
                            check=lambda: None, evidence=[])
        sink = L.CellSink(scope, check=lambda: None)
        for cell in held.value['cells']:
            sink.append(cell)
        cells = sink.finish()
        del held, cell
    result['decode_and_sink_seconds'] = round(time.perf_counter()-started, 3)
    n = cells.size
    t = time.perf_counter()
    start = V.start_rows(cells)
    carried = V.carried_rows(start)
    for key in start:
        V.carry(carried, key, key, None)
    result['carried_start_seconds'] = round(time.perf_counter()-t, 4)
    t = time.perf_counter()
    whole = {}
    for key, row in carried.items():
        _ = row['volume_m3']
        whole[key] = {name: row[name] for name in FIELDS}
        row = None
    result['whole_row_pass_seconds'] = round(time.perf_counter()-t, 4)
    keys = list(start)

    def field_pass(path):
        values, t0 = {}, time.perf_counter()
        for key in keys:
            at = start._index[key]
            with cells.at(at) as row:
                ref = row
                for name in path:
                    ref = ref.field(name)
                with ref:
                    values[key] = V._key_value(ref) if ref.kind == 'scalar' else _export(ref, V)
        return values, round(time.perf_counter()-t0, 4)

    passes = {}
    for path in (('volume_m3',), ('geometry_volume_error_m3',), ('exact',), ('exact', B_NAME)):
        values, seconds = field_pass(path)
        expected = {key: (whole[key][path[0]] if len(path) == 1 else whole[key][path[0]][path[1]]) for key in keys}
        passes['.'.join(path)] = {'seconds': seconds, 'equal_to_whole_row_values': values == expected}
    result.update(rows=n, field_passes=passes,
                  per_row_ms={'whole_row': round(1000*result['whole_row_pass_seconds']/n, 3),
                              **{k: round(1000*v['seconds']/n, 3) for k, v in passes.items()}})
    del start, carried, whole, cells
    sink._record.close()
    scope.close()
    Path(sys.argv[1]).write_text(json.dumps(result, indent=1), encoding='utf8')
    print(json.dumps(result, indent=1))


def _export(ref, V):
    with ref.export(max_logical_bytes=V.ROW_BYTES, max_owned_bytes=V.ROW_BYTES) as owned:
        return owned.value


if __name__ == '__main__':
    main()
