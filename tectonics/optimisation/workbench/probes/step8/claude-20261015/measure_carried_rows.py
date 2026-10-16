"""Real against booked memory for the carried parent cell rows (authentic IV1).

Usage: python -B measure_carried_rows.py OUT.json
Decodes the authentic IV1 spatial state record once (query-only original),
then for every cell row: canonical length; the small-row export charge that
record_views._export_ref books today (65536 + 192 * length for rows up to
32,768 logical bytes); and the real bytes a held decoded row keeps, measured
with tracemalloc as the growth from json.loads of the row's canonical bytes
while every earlier row is still held (the carried dict holds them all).
Untimed; writes only OUT.json.
"""
import gc
import json
import sys
import tracemalloc
from pathlib import Path

HERE = Path(__file__).resolve().parent
R = HERE.parents[2]
C = R/'compact-geometry-r1'
I = R.parent/'runtime-integration-r1'/'runtime-src'


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                      allow_nan=False).encode('utf8')


def main():
    out = Path(sys.argv[1]).resolve()
    if out.parent != HERE:
        raise SystemExit('output must be directly inside the evidence folder')
    sys.path[:0] = [str(C), str(R), str(I)]
    import historical_admission as H
    import measure_live_capacity as CAP
    from atlas_tectonics.resources import WorkBudget
    from atlas_tectonics.storage import Compression, StoreLimits
    from measure_live_mesh_capacity import _read_record
    census = CAP.read_census()['census']
    endpoint = census['endpoint']
    budget = WorkBudget(16 << 30)
    with H.open_original_readonly(limits=StoreLimits(**endpoint['store_limits']),
                                  compression=Compression(**endpoint['store_compression']), budget=budget) as source:
        held = _read_record(source, census['records']['spatial-record:state'], budget=budget,
                            check=lambda: None, evidence=[])
        rows = [canonical(row) for row in held.value['cells']]
        del held
    gc.collect()
    lengths = [len(raw) for raw in rows]
    booked = [65536+192*n if n <= 32768 else None for n in lengths]
    tracemalloc.start()
    kept, real = [], []
    for raw in rows:
        before = tracemalloc.get_traced_memory()[0]
        kept.append(json.loads(raw))
        real.append(tracemalloc.get_traced_memory()[0]-before)
    total_real = tracemalloc.get_traced_memory()[0]
    tracemalloc.stop()
    small = [b for b in booked if b is not None]
    report = dict(rows=len(rows), canonical_bytes_total=sum(lengths), canonical_bytes_max=max(lengths),
                  canonical_bytes_mean=sum(lengths)/len(lengths),
                  rows_over_small_path=sum(b is None for b in booked),
                  booked_small_path_total=sum(small), booked_small_path_mean=sum(small)/len(small),
                  real_decoded_total=sum(real), real_decoded_mean=sum(real)/len(real), real_decoded_max=max(real),
                  traced_total_with_list=total_real,
                  booked_to_real_ratio=sum(small)/max(sum(real), 1),
                  retained_scope_limit=256 << 20,
                  note='real = tracemalloc growth of json.loads per row with all earlier rows held; '
                       'booked = record_views._export_ref small-row legacy charge')
    out.write_text(json.dumps(report, indent=1), encoding='utf8')
    print(json.dumps(report, indent=1))


if __name__ == '__main__':
    main()
