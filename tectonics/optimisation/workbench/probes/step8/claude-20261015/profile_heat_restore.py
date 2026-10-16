"""Where one authentic IV1 heat-ledger restore spends its time.

Usage: python -B profile_heat_restore.py OUT_DIR [SAMPLE_SECONDS]
Saves the authentic heat ledger once into a fresh candidate store exactly as
the capacity overlaps' standalone restore input does (census bindings renamed
to the scientific field names, each field's SHA-256 and shape checked), then
reopens it through private_heat_snapshot_store_r4.open with a pure-Python
stack sampler on the main thread (every SAMPLE_SECONDS, default 1). Phase
times go to OUT_DIR/phases.json, samples to OUT_DIR/stacks.json. Reads the
original store query-only; writes only OUT_DIR (inside the evidence folder).
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


def main():
    out = Path(sys.argv[1]).resolve()
    seconds = float(sys.argv[2]) if len(sys.argv) > 2 else 1.0
    if out.parent != HERE:
        raise SystemExit('output must be directly inside the evidence folder')
    out.mkdir(exist_ok=False)
    sys.path[:0] = [str(C), str(R), str(I)]
    import historical_admission as H
    import measure_live_capacity as CAP
    import private_heat_snapshot_store_r4 as HEAT_STORE
    from atlas_tectonics.resources import WorkBudget
    from atlas_tectonics.storage import Compression, StoreLimits
    from content_cache import create_retained_scope
    from heat_ledger_tables import CompactHeatSnapshot
    from interval_store_set import IntervalStoreSet
    from measure_live_mesh_capacity import _read_record
    phases, started = [], time.perf_counter()

    def phase(name, **extra):
        phases.append(dict(name=name, seconds=round(time.perf_counter()-started, 3), **extra))
        (out/'phases.json').write_text(json.dumps(phases, indent=1, default=str), encoding='utf8')
        print(name, phases[-1]['seconds'], flush=True)

    census = CAP.read_census()['census']
    endpoint = census['endpoint']
    budget = WorkBudget(16 << 30)
    scope = create_retained_scope(budget, process_epoch='profile-heat-restore')
    binding = census['records']['heat:metadata_utf8']
    with H.open_original_readonly(limits=StoreLimits(**endpoint['store_limits']),
                                  compression=Compression(**endpoint['store_compression']), budget=budget) as source:
        stores = IntervalStoreSet.create_migration(out/'catalog.json',
            workflow_id=sha256(b'profile heat restore').hexdigest(), scope=scope)
        candidate = stores.begin_interval(None, producer_identity='b'*64, runtime_identity='c'*64)
        phase('heat-decode')
        held = _read_record(source, binding, budget=budget, check=lambda: None, evidence=[])
        metadata = source.metadata(binding['snapshot'])
        arrays = CAP.PaidArrays(budget, census['heat']['native_fields'], 1)
        hashes = CAP.fill_numeric(source, binding['snapshot'], arrays.blocks[0], lambda: None)
        named = CAP.native_heat_fields(census, arrays.blocks[0], hashes)
        phase('heat-pack')
        snapshot = CompactHeatSnapshot.from_components(held.value, named, scope=scope,
            check=lambda: None, expected_result_id=metadata['result_id'])
        phase('heat-save', ledger_canonical_bytes=binding['filebytes'],
              field_bytes=sum(a.nbytes for a in named.values()))
        receipt = HEAT_STORE.save(candidate, snapshot, bindings=dict(metadata['bindings'],
            capacity_block=sha256(b'profile').hexdigest()), scope=scope)
        result_id = snapshot.result_id
        del held, named
        snapshot.close()
        arrays.close()
        phase('heat-open')
        main_id, counts, stop = threading.get_ident(), {}, threading.Event()

        def sample():
            while not stop.wait(seconds):
                frame = sys._current_frames().get(main_id)
                stack = []
                while frame is not None:
                    stack.append('%s:%d %s' % (Path(frame.f_code.co_filename).name, frame.f_lineno,
                                               frame.f_code.co_name))
                    frame = frame.f_back
                key = ' <- '.join(stack[:14])
                counts[key] = counts.get(key, 0)+1
                (out/'stacks.json').write_text(json.dumps(sorted(counts.items(), key=lambda kv: -kv[1]),
                                                          indent=1), encoding='utf8')

        sampler = threading.Thread(target=sample, daemon=True)
        sampler.start()
        try:
            handle = HEAT_STORE.open(candidate, receipt, expected_result_id=result_id,
                                     bindings=receipt['metadata']['bindings'], scope=scope)
        finally:
            stop.set()
            sampler.join()
        phase('heat-opened', result_id_equal=handle.value.result_id == result_id,
              fields=len(handle.value._fields), scope=scope.stats()._asdict()
              if hasattr(scope.stats(), '_asdict') else str(scope.stats()))
        handle.value.close()
        handle.close()
        candidate.close()
        stores.close()
    scope.close()
    phase('closed', reserved=budget.reserved_bytes)


if __name__ == '__main__':
    main()
