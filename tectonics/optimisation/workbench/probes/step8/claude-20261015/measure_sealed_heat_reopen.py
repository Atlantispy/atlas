"""Sealed reopen time of one authentic IV1 heat ledger (D3 measurement).

Usage:
  python -B measure_sealed_heat_reopen.py save OUT_DIR
  python -B measure_sealed_heat_reopen.py open OUT_DIR [SAMPLE_SECONDS]
save: packs the authentic heat ledger exactly as the capacity harness does,
saves it to a fresh interval candidate, publishes a small root, then seals and
promotes the candidate. The receipt and result ID go to OUT_DIR/saved.json.
open: in a fresh process (as the independent reader would), opens the sealed
catalog read-only and reopens the ledger through
private_heat_snapshot_store_r4.open with the sealed IntervalStoreSet as
resolver, sampling the main-thread stack every SAMPLE_SECONDS (default 1).
Writes OUT_DIR/open.json and OUT_DIR/open-stacks.json. Original store is read
query-only; nothing is written outside OUT_DIR.
"""
import json
import sys
import threading
import time
from hashlib import sha256
from pathlib import Path

HERE = Path(__file__).resolve().parent
R = HERE.parents[2]
C = R/'compact-geometry-r1'
I = R.parent/'runtime-integration-r1'/'runtime-src'


def _paths():
    sys.path[:0] = [str(C), str(R), str(I)]


def save(out):
    import historical_admission as H
    import measure_live_capacity as CAP
    import private_heat_snapshot_store_r4 as HEAT_STORE
    from atlas_tectonics.resources import WorkBudget
    from atlas_tectonics.storage import Compression, StoreLimits
    from content_cache import create_retained_scope
    from heat_ledger_tables import CompactHeatSnapshot
    from interval_store_set import IntervalStoreSet
    from measure_live_mesh_capacity import _read_record
    from record_tables import RecordCodec
    out.mkdir(exist_ok=False)
    census = CAP.read_census()['census']
    endpoint = census['endpoint']
    budget = WorkBudget(16 << 30)
    scope = create_retained_scope(budget, process_epoch='sealed-heat-reopen-save')
    binding = census['records']['heat:metadata_utf8']
    started = time.perf_counter()
    with H.open_original_readonly(limits=StoreLimits(**endpoint['store_limits']),
                                  compression=Compression(**endpoint['store_compression']), budget=budget) as source:
        stores = IntervalStoreSet.create_migration(out/'catalog.json',
            workflow_id=sha256(b'sealed heat reopen').hexdigest(), scope=scope)
        candidate = stores.begin_interval(None, producer_identity='b'*64, runtime_identity='c'*64)
        held = _read_record(source, binding, budget=budget, check=lambda: None, evidence=[])
        metadata = source.metadata(binding['snapshot'])
        arrays = CAP.PaidArrays(budget, census['heat']['native_fields'], 1)
        hashes = CAP.fill_numeric(source, binding['snapshot'], arrays.blocks[0], lambda: None)
        named = CAP.native_heat_fields(census, arrays.blocks[0], hashes)
        snapshot = CompactHeatSnapshot.from_components(held.value, named, scope=scope,
            check=lambda: None, expected_result_id=metadata['result_id'])
        receipt = HEAT_STORE.save(candidate, snapshot, bindings=dict(metadata['bindings'],
            capacity_block=sha256(b'sealed reopen').hexdigest()), scope=scope)
        result_id = snapshot.result_id
        saved_seconds = time.perf_counter()-started
        del held, named
        snapshot.close()
        arrays.close()
        root = RecordCodec().pack_record({'schema': 'atlas.sealed-heat-reopen-root.v1', 'result_id': result_id},
                                         record_schema='atlas.sealed-heat-reopen-root.v1', scope=scope,
                                         check=lambda: None)
        token = CAP.CheckToken(lambda: None)
        root_ref = CAP.publish_record(candidate, root, scope, 'd'*64, token)
        sealed = candidate.seal(root_ref, cancel=token)
        stores.promote(sealed, expected_catalog_digest=stores.catalog_digest)
        root.close()
        candidate.close()
        stores.close()
    scope.close()
    record = dict(result_id=result_id, receipt=receipt, save_seconds=round(saved_seconds, 3),
                  sealed_after_seconds=round(time.perf_counter()-started, 3),
                  disk_bytes=sum(p.stat().st_size for p in out.rglob('*') if p.is_file()))
    (out/'saved.json').write_text(json.dumps(record, indent=1), encoding='utf8')
    print(json.dumps({k: v for k, v in record.items() if k != 'receipt'}, indent=1))


def open_sealed(out, seconds):
    import private_heat_snapshot_store_r4 as HEAT_STORE
    import psutil
    from atlas_tectonics.resources import WorkBudget
    from content_cache import create_retained_scope
    from interval_store_set import IntervalStoreSet
    saved = json.loads((out/'saved.json').read_text(encoding='utf8'))
    budget = WorkBudget(16 << 30)
    scope = create_retained_scope(budget, process_epoch='sealed-heat-reopen-open')
    main_id, counts, stop = threading.get_ident(), {}, threading.Event()

    def sample():
        while not stop.wait(seconds):
            frame = sys._current_frames().get(main_id)
            stack = []
            while frame is not None:
                stack.append('%s:%d %s' % (Path(frame.f_code.co_filename).name, frame.f_lineno, frame.f_code.co_name))
                frame = frame.f_back
            key = ' <- '.join(stack[:14])
            counts[key] = counts.get(key, 0)+1

    started = time.perf_counter()
    stores = IntervalStoreSet.open_catalog(out/'catalog.json', scope=scope)
    opened_catalog = time.perf_counter()-started
    sampler = threading.Thread(target=sample, daemon=True)
    sampler.start()
    try:
        handle = HEAT_STORE.open(stores, saved['receipt'], expected_result_id=saved['result_id'],
                                 bindings=saved['receipt']['metadata']['bindings'], scope=scope)
    finally:
        stop.set()
        sampler.join()
    reopen = time.perf_counter()-started
    stats = scope.stats()
    record = dict(catalog_open_seconds=round(opened_catalog, 3), heat_reopen_seconds=round(reopen, 3),
                  result_id_equal=handle.value.result_id == saved['result_id'],
                  fields=len(handle.value._fields), retained_bytes=stats.retained_bytes,
                  peak_retained_bytes=stats.peak_retained_bytes,
                  process_peak_rss_bytes=getattr(psutil.Process().memory_info(), 'peak_wset', None),
                  samples=sum(counts.values()))
    handle.value.close()
    handle.close()
    stores.close()
    scope.close()
    (out/'open.json').write_text(json.dumps(record, indent=1), encoding='utf8')
    (out/'open-stacks.json').write_text(json.dumps(sorted(counts.items(), key=lambda kv: -kv[1]), indent=1),
                                        encoding='utf8')
    print(json.dumps(record, indent=1))


def main():
    mode, out = sys.argv[1], Path(sys.argv[2]).resolve()
    # The catalog writes catalog.json.tmp-<32 hex>; under the evidence folder
    # that path passes Windows' 259-character limit, so a short folder directly
    # in probes/step8 is also allowed (still inside R).
    if out.parent not in (HERE, HERE.parent):
        raise SystemExit('output must be directly inside the evidence folder or probes/step8')
    _paths()
    if mode == 'save':
        save(out)
    elif mode == 'open':
        open_sealed(out, float(sys.argv[3]) if len(sys.argv) > 3 else 1.0)
    else:
        raise SystemExit('mode must be save or open')


if __name__ == '__main__':
    main()
