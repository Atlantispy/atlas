"""X2 measurement: compact transport identity, unsealed against sealed, at IV1 record size.

Usage: python -B measure_transport_seal.py OUT_JSON

Builds one synthetic transport metadata record of about the IV1 size (census:
spatial-record:transport 6,422,727 B, about 203k rationals), makes the compact
snapshot through live_transport_result.make_snapshot (whose own complete
computation seals it), then times identity() on the sealed object and on an
unsealed copy (dataclasses.replace), several times each. Read-only apart from
OUT_JSON; synthetic data only.
"""
import gc
import json
import sys
import time
from dataclasses import replace
from pathlib import Path

HERE = Path(__file__).resolve().parent
C = HERE.parents[3]/'compact-geometry-r1'


def main():
    out = Path(sys.argv[1])
    sys.path.insert(0, str(C))
    import numpy as np
    import test_spatial_records_patch as F
    from atlas_tectonics.regional_execution import RegionalMechanicalSnapshot
    import live_spatial_patch as LIVE
    import live_transport_result as RESULT
    cells, fields = 855, 44
    stocks = {'field:'+str(f): [[hex((c*7919+f*104729) % (1 << 120) | 1), hex(3**((c+f) % 70)+1)]
                                for c in range(cells)] for f in range(fields)}
    faces = [[hex((i*65537) % (1 << 100) | 1), hex(5**(i % 40)+2)] for i in range(165000)]
    metadata = dict(schema='atlas.spatial-implicit-transport.v1', exact_stocks=stocks,
                    exact_face_transfers={'enthalpy_j': faces}, cell_ids=['cell-'+str(c) for c in range(cells)])
    raw_bytes = len(json.dumps(metadata, sort_keys=True, separators=(',', ':')).encode())
    arrays = {'stock:'+str(f): np.arange(cells, dtype='float64')+f for f in range(fields)}
    budget = F.WorkBudget(4 << 30)
    scope = F.create_retained_scope(budget, process_epoch='x2-transport-seal')
    started = time.perf_counter()
    with LIVE.construction(scope, budget=budget):
        compact = RESULT.make_snapshot(metadata, arrays, budget, RegionalMechanicalSnapshot)
    construct = time.perf_counter()-started
    sealed, unsealed = [], []
    for _ in range(5):
        t0 = time.perf_counter()
        sealed_id = RESULT.identity(compact, budget)
        sealed.append(time.perf_counter()-t0)
        copy = replace(compact)
        t0 = time.perf_counter()
        unsealed_id = RESULT.identity(copy, budget)
        unsealed.append(time.perf_counter()-t0)
        del copy
    if not sealed_id == unsealed_id == compact.result_id:
        raise SystemExit('sealed and unsealed identities differ')
    result = dict(record_json_bytes=raw_bytes, construct_seconds=round(construct, 3),
                  sealed_seconds=[round(s, 4) for s in sealed], unsealed_seconds=[round(s, 4) for s in unsealed],
                  sealed_median=round(sorted(sealed)[2], 4), unsealed_median=round(sorted(unsealed)[2], 4),
                  identity=compact.result_id)
    del compact
    gc.collect()
    scope.close()
    out.write_text(json.dumps(result, indent=1), encoding='utf8')
    print(json.dumps(result, indent=1))


if __name__ == '__main__':
    main()
