"""Where one authentic IV1 mesh pack spends its time (stack samples + phase times).

Usage: python -B profile_mesh_pack.py OUT_DIR [SAMPLE_SECONDS]
Reproduces measure_live_mesh_capacity.retain_mesh_blocks up to and including
one live_mesh_patch._pack of the authentic spatial-record:mesh: the authentic
partition is packed and admitted as PartitionV2, its SupportSource built, the
mesh decoded, each differential support verified and replaced by a shared
reference, then the mesh packed. Phase times go to OUT_DIR/phases.json; every
SAMPLE_SECONDS (default 15) the main thread stack is sampled into OUT_DIR/stacks.json
(a pure-Python sampler thread), a low-overhead statistical picture of the slow phase. Reads the
original store query-only; writes only OUT_DIR (inside R).
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
    seconds = float(sys.argv[2]) if len(sys.argv) > 2 else 15.0
    if out.parent != HERE:
        raise SystemExit('output must be directly inside the evidence folder')
    out.mkdir(exist_ok=False)
    sys.path[:0] = [str(C), str(R), str(I)]
    import measure_live_capacity as CAP
    import mesh_tables as M
    from measure_live_mesh_capacity import _read_record
    from atlas_tectonics.resources import WorkBudget
    from atlas_tectonics.storage import Compression, StoreLimits
    from content_cache import create_retained_scope
    import historical_admission as H
    from live_mesh_patch import _pack
    from partition_v2 import PartitionV2, DESCRIPTOR
    from record_tables import RecordCodec
    from support_source import SupportSource
    import psutil
    process = psutil.Process()
    phases, started = [], time.perf_counter()
    budget = None

    def phase(name):
        # Real memory (RSS now, OS peak working set so far) beside booked bytes.
        info = process.memory_info()
        phases.append(dict(name=name, seconds=round(time.perf_counter()-started, 3), rss_bytes=info.rss,
                           os_peak_working_set_bytes=getattr(info, 'peak_wset', None),
                           reserved_bytes=None if budget is None else budget.reserved_bytes))
        (out/'phases.json').write_text(json.dumps(phases, indent=1), encoding='utf8')
        print(name, phases[-1]['seconds'], flush=True)

    value = CAP.read_census()
    census = value['census']
    endpoint = census['endpoint']
    budget = WorkBudget(16 << 30)  # phase() reads it through the closure
    scope = create_retained_scope(budget, process_epoch='profile-mesh-pack')
    evidence = []
    with H.open_original_readonly(limits=StoreLimits(**endpoint['store_limits']),
                                  compression=Compression(**endpoint['store_compression']), budget=budget) as source:
        phase('partition-decode')
        held = _read_record(source, census['records']['partition-record:partition'], budget=budget,
                            check=lambda: None, evidence=evidence)
        phase('partition-pack')
        compact = RecordCodec().pack_record(held.value, record_schema=DESCRIPTOR, scope=scope, check=lambda: None)
        phase('partition-admit')
        partition = PartitionV2(compact, expected_partition_id=held.value['partition_id'], check=lambda: None)
        del held, compact
        phase('partition-publish')
        from interval_store_set import IntervalStoreSet
        from partition_store import publish_partition_v2
        stores = IntervalStoreSet.create_migration(out/'catalog.json',
            workflow_id=sha256(b'profile mesh pack').hexdigest(), scope=scope)
        candidate = stores.begin_interval(None, producer_identity='b'*64, runtime_identity='c'*64)
        publish_partition_v2(candidate, partition, producer=sha256(b'profile partition').hexdigest(),
                             check=lambda: None)
        support = SupportSource(partition, check=lambda: None)
        phase('mesh-decode')
        held = _read_record(source, census['records']['spatial-record:mesh'], budget=budget,
                            check=lambda: None, evidence=evidence)
        differential = held.value['support_tables'].get('differential_supports', {})
        phase('support-verify-%d' % len(differential))
        for ident in differential:
            row = differential[ident]
            raw = M.canonical(row)
            found = support.identity(ident)
            if not (sha256(raw).hexdigest() == ident == found.sha256 and len(raw) == found.canonical_bytes):
                raise SystemExit('authentic mesh support differs from its partition')
            differential[ident] = M.SharedSupportRecord(support, ident)
            del raw, row
        phase('mesh-pack')
        # Pure-Python sampler thread: faulthandler's watchdog dump ended the
        # first profile process mid-write, so frames are read with
        # sys._current_frames() instead and summarised per function.
        main_id, counts, stop = threading.get_ident(), {}, threading.Event()

        def sample():
            while not stop.wait(seconds):
                frame = sys._current_frames().get(main_id)
                stack = []
                while frame is not None:
                    stack.append('%s:%d %s' % (Path(frame.f_code.co_filename).name, frame.f_lineno,
                                               frame.f_code.co_name))
                    frame = frame.f_back
                key = ' <- '.join(stack[:12])
                counts[key] = counts.get(key, 0)+1
                (out/'stacks.json').write_text(json.dumps(sorted(counts.items(), key=lambda kv: -kv[1]),
                                                          indent=1), encoding='utf8')

        sampler = threading.Thread(target=sample, daemon=True)
        sampler.start()
        try:
            metadata, arrays, scratch, reader, dependencies = _pack(held, budget=budget, scope=scope,
                                                                    source=support)
            phase('mesh-packed')
            columns = dict(columns=len(arrays), column_bytes=sum(a.nbytes for a in arrays.values()),
                           tracked_after_pack=budget.statistics())
            # The rest of live_mesh_patch.finish, step by step with the same calls:
            # the frozen-column CompactMesh (streams each shared support once more),
            # the v3 publish and reopen, then the ExteriorMesh view.
            del held
            view = M.CompactMesh(metadata, arrays, support_reader=reader,
                expected_geometry_id=metadata['geometry_id'], budget=budget, scope=scope,
                dependencies=dependencies)
            del arrays, scratch, metadata, reader, dependencies
            phase('mesh-constructed')
            from compact_store import CompactMeshStoreV3
            from live_mesh_patch import _published
            producer = sha256(b'profile authentic IV1 mesh v3').hexdigest()
            adapter = CompactMeshStoreV3(candidate, scope=scope, support_source=support)
            ref = adapter.publish(view, producer=producer)
            identity = view.geometry_id
            phase('mesh-v3-published')
            # r6 (16 Oct): the produced view stays in memory, bound to the root
            # just published (live_mesh_patch._published); r5 measured the former
            # reopen at more than 24 min 53 s without finishing.
            view = _published(dict(resolver=candidate, support_source=support, producer=producer),
                              scope, view, ref)
            phase('mesh-v3-bound')
            # This harness imports the untransformed runtime package, which has no
            # ExteriorMesh.from_compact (exterior_mesh_patch adds it); r6 stopped
            # there. The wrapper is an O(1) admission, so it is not timed here.
            mesh = None
            # One complete stream, as the coverage gate and the reopen check read it.
            digest = sha256()
            for part in view.iter_legacy_json():
                digest.update(part)
            if digest.hexdigest() != identity:
                raise SystemExit('bound mesh stream differs from its geometry identity')
            phase('mesh-streamed-in-memory')
            del mesh, view
        finally:
            stop.set()
            sampler.join()
        phases.append(dict(columns, tracked=budget.statistics(),
                           process_os_peak_working_set_bytes=getattr(process.memory_info(), 'peak_wset', None)))
        (out/'phases.json').write_text(json.dumps(phases, indent=1, default=str), encoding='utf8')


if __name__ == '__main__':
    main()
