"""One matched small storage fixture, four fresh processes; no science acceptance."""
from __future__ import annotations

import argparse
from dataclasses import asdict
from hashlib import sha256
import json
import os
from pathlib import Path
import platform
import stat
import subprocess
import sys
import tempfile
import time

R = Path(__file__).resolve().parents[2]
T = R.parents[3]
C = R/'compact-geometry-r1'
RUNTIME = R.parent/'runtime-integration-r1/runtime-src'


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def pin(path):
    digest = sha256()
    with Path(path).open('rb') as stream:
        while block := stream.read(1 << 20):
            digest.update(block)
    return digest.hexdigest()


def fixture(sequence):
    cells = [dict(cell_id=sha256(str(index).encode()).hexdigest(), exact=['0x7', '0x2'])
             for index in range(8)]
    face = dict(face_id='f'*64, exact=['0x'+('e'*128), '0x1'], supports=['a'*64, 'b'*64])
    graph = dict(schema='synthetic.step8.graph', cells=cells, faces=[face]*24)
    return dict(state=dict(schema='synthetic.step8.state', sequence=sequence, cells=cells),
        graph=graph, heat=dict(schema='synthetic.step8.heat', rows=[dict(graph=graph, flux=['0x7', '0x2'])]*3))


def imported_sources():
    paths = {Path(__file__).resolve()}
    for module in tuple(sys.modules.values()):
        path = getattr(module, '__file__', None)
        if path and Path(path).suffix == '.py' and Path(path).resolve().is_relative_to(T):
            paths.add(Path(path).resolve())
    return {str(path.relative_to(T)): pin(path) for path in sorted(paths)}


def worker(mode, action, directory, result_path, expected_pin):
    sys.path[:0] = [str(C), str(RUNTIME), str(R)]
    import numpy as np
    from atlas_tectonics.resources import WorkBudget
    from atlas_tectonics.storage import ArrayStore, Compression
    from interval_store_set import LIMITS
    from content_cache import create_retained_scope
    from compact_restart_store import CompactRestartStore
    import historical_admission as H
    import reopen_prepared_restart as X
    import spatial_records_patch as SR

    budget = WorkBudget(1 << 30)
    scope = create_retained_scope(budget, process_epoch='prepared-restart-'+str(os.getpid())) if mode == 'compact' else None
    keys = [sha256(('synthetic endpoint '+str(index)).encode()).hexdigest() for index in range(2)]
    database, catalog = directory/'checkpoint.sqlite', directory/X.COMPACT_CATALOG
    producer = {'role': 'Step8 matched storage-only measurement', 'version': 1}
    result = dict(mode=mode, action=action, pid=os.getpid(), scientific_acceptance=False)
    with budget.reserve(4 << 20, category='fixture-inputs'):
        records = [fixture(index) for index in range(2)]
        raw = [{name: canonical(value) for name, value in row.items()} for row in records]
        values = np.arange(18000, dtype='<f8')
        identities = [{name: dict(sha256=sha256(value).hexdigest(), nbytes=len(value))
                       for name, value in row.items()} for row in raw]
        expected = dict(keys=keys, records=identities, numeric=dict(dtype=values.dtype.str,
            shape=list(values.shape), nbytes=values.nbytes, sha256=sha256(values.tobytes()).hexdigest()))
        result['fixture'] = dict(numeric_elements=18000, numeric_dtype='<f8', endpoints=2,
            record_kinds=['state', 'graph', 'heat'], logical_records_bytes=sum(sum(len(v) for v in row.values()) for row in raw),
            logical_numeric_bytes=2*values.nbytes, identity_sha256=sha256(canonical(expected)).hexdigest(),
            deliberate_sharing='24 repeated face rows and three graph copies per heat ledger; unchanged numeric payload')
        if action == 'write':
            started = time.perf_counter()
            if mode == 'legacy':
                with ArrayStore(database, LIMITS, Compression(), budget=budget) as store:
                    for index in range(2):
                        arrays = {'record:'+name: np.frombuffer(value, dtype=np.uint8) for name, value in raw[index].items()}
                        arrays['numeric'] = values if index == 0 else store.reference(keys[0], 'numeric')
                        store.put(keys[index], arrays, dict(schema='synthetic.step8.endpoint', sequence=index), budget=budget)
                    result['storage_statistics'] = store.statistics()
                physical = [database]
            else:
                with CompactRestartStore.create_migration(catalog, workflow_id=sha256(b'step8 fixture').hexdigest(),
                        scope=scope, producer_identity=sha256(canonical(producer)).hexdigest(), runtime_identity='3'*64) as store:
                    local = []
                    for index in range(2):
                        if index:
                            store.start_next_interval(producer_identity=sha256(canonical(producer)).hexdigest(), runtime_identity='3'*64)
                        refs = SR.publish_records(store, records[index], budget=budget, source_producer=producer)
                        numeric = values if index == 0 else store.reference(keys[0], 'numeric')
                        store.put(keys[index], {'numeric': numeric}, dict(schema='synthetic.step8.endpoint',
                            sequence=index, record_refs=refs), budget=budget)
                        local.append(store.candidate.local_statistics())
                        store.seal_and_promote(keys[index])
                    result['storage_statistics'] = store.statistics()
                    result['interval_local_statistics'] = local
                physical = [catalog, *(directory/entry['filename'] for entry in json.loads(catalog.read_bytes())['entries'])]
            result['elapsed_seconds'] = time.perf_counter()-started
            expected['files'] = {path.name: dict(sha256=pin(path), nbytes=path.stat().st_size) for path in physical}
            result['physical_bytes'] = sum(path.stat().st_size for path in physical)
            (directory/'expected.json').write_bytes(canonical(expected))
        else:
            expected_path = directory/'expected.json'
            assert pin(expected_path) == expected_pin
            saved = json.loads(expected_path.read_bytes())
            assert {name: saved[name] for name in expected} == expected
            started = time.perf_counter()
            for name, info in saved['files'].items():
                assert pin(directory/name) == info['sha256']
            store = (H.open_successor_readonly(database, expected_sha256=saved['files'][database.name]['sha256'],
                       limits=LIMITS, compression=Compression(), budget=budget)
                if mode == 'legacy' else CompactRestartStore.open_catalog(catalog, scope=scope))
            with store:
                token = store.change_token()
                for index, key in enumerate(keys):
                    header = store.metadata(key)
                    assert header['schema'] == 'synthetic.step8.endpoint' and header['sequence'] == index
                    if mode == 'legacy':
                        found = {}
                        for name in records[index]:
                            digest, count = sha256(), 0
                            for offset, data in store.iter_chunks(key, 'record:'+name, budget=budget):
                                assert offset == count
                                digest.update(memoryview(data).cast('B')); count += data.nbytes
                            del data
                            found[name] = dict(sha256=digest.hexdigest(), nbytes=count)
                    else:
                        refs = header['record_refs']
                        with SR.open_records(store, refs, budget=budget, scope=scope, source_producer=producer) as opened:
                            found = {name: dict(sha256=refs[name]['sha256'], nbytes=refs[name]['bytes']) for name in opened}
                            for child in opened.values():
                                child.close()
                        del opened, child
                    assert found == identities[index]
                    digest, count = sha256(), 0
                    for offset, data in store.iter_chunks(key, 'numeric', budget=budget):
                        assert offset*8 == count
                        assert data.dtype.str == '<f8'
                        digest.update(memoryview(data).cast('B')); count += data.nbytes
                    del data
                    assert dict(dtype='<f8', shape=[18000], nbytes=count, sha256=digest.hexdigest()) == expected['numeric']
                assert token == store.change_token()
            for name, info in saved['files'].items():
                assert pin(directory/name) == info['sha256']
            result['elapsed_seconds'] = time.perf_counter()-started
            result['physical_bytes'] = sum(row['nbytes'] for row in saved['files'].values())
            result['independent_reader'] = True
        result['identity_checks'] = dict(all_record_hashes_and_lengths=True, numeric_dtype_shape_hash=True,
                                        complete_endpoint_coverage=True, original_files_unchanged=True)
        if action == 'write':
            if mode == 'legacy':
                del arrays
            else:
                del numeric
        del records, raw, values
    if scope is not None:
        result['retained_before_close'] = X.retained_accounting(scope)
        scope.close()
        result['retained_after_close'] = X.retained_accounting(scope)
        X.validate_retained_accounting(result['retained_after_close'], pid=os.getpid())
    result['logical_budget'] = budget.statistics()
    assert budget.reserved_bytes == 0
    result['final_reserved_bytes'] = 0
    result['source_sha256'] = imported_sources()
    result['runtime'] = dict(python=sys.version, numpy=np.__version__, platform=platform.platform(),
                            store_limits=asdict(LIMITS), compression=asdict(Compression()))
    result_path.write_bytes(canonical(result))
    print(json.dumps(dict(status='PASS', mode=mode, action=action, elapsed_seconds=result['elapsed_seconds'])), flush=True)


def run_child(mode, action, directory, target):
    import psutil
    expected = pin(directory/'expected.json') if action == 'read' else '-'
    environment = dict(os.environ)
    environment.update({name: '1' for name in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS')})
    command = [sys.executable, '-B', str(Path(__file__).resolve()), '--worker', mode, action,
               str(directory), str(target), expected]
    started = time.perf_counter()
    with target.with_suffix('.log').open('w', encoding='utf8') as log:
        process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, env=environment)
        observed = psutil.Process(process.pid)
        samples, rss, private, peak_working_set, maximum_members = 0, 0, None, None, 0
        owned = {observed.pid: observed}
        try:
            while process.poll() is None:
                if time.perf_counter()-started > 60:
                    raise TimeoutError('bounded measurement worker exceeded 60 seconds: '+str(target))
                try:
                    members = [observed, *observed.children(recursive=True)]
                    owned.update({member.pid: member for member in members})
                    maximum_members = max(maximum_members, len(members))
                    current_rss, current_private = 0, 0
                    private_available = True
                    for member in members:
                        memory = member.memory_info()
                        current_rss += memory.rss
                        if hasattr(memory, 'private'):
                            current_private += memory.private
                        else:
                            private_available = False
                        if hasattr(memory, 'peak_wset'):
                            peak_working_set = max(peak_working_set or 0, memory.peak_wset)
                    samples += 1
                    rss = max(rss, current_rss)
                    if private_available:
                        private = max(private or 0, current_private)
                except psutil.NoSuchProcess:
                    pass
                time.sleep(.005)
        finally:
            if process.poll() is None:
                for member in reversed(tuple(owned.values())):
                    try:
                        member.kill()
                    except psutil.NoSuchProcess:
                        pass
                process.wait(timeout=10)
        if process.returncode:
            raise RuntimeError('measurement worker failed: '+str(target.with_suffix('.log')))
    result = json.loads(target.read_bytes())
    result['process_observation'] = dict(sampling_interval_seconds=.005, samples=samples,
        sampled_peak_rss_bytes=rss, sampled_peak_private_bytes=private,
        maximum_os_reported_member_peak_working_set_bytes=peak_working_set,
        maximum_observed_processes=maximum_members,
        whole_process_seconds=time.perf_counter()-started,
        timing_scope='elapsed phase excludes imports/input fixture creation; process-tree peaks include them and venv launcher')
    target.write_bytes(canonical(result))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--worker', nargs=5)
    args = parser.parse_args()
    if args.worker:
        mode, action, directory, result, expected = args.worker
        worker(mode, action, Path(directory), Path(result), expected)
        return
    destination = Path(__file__).resolve().parent
    final = destination/'measurement.json'
    if final.exists():
        raise FileExistsError('preserve existing measurement; do not overwrite without a new run destination')
    temporary_root = T/'_t'
    temporary_root.mkdir(exist_ok=True)
    measurements = {}
    with tempfile.TemporaryDirectory(prefix='step8-measure-', dir=temporary_root) as folder:
        root = Path(folder).resolve()
        assert root.is_relative_to(temporary_root.resolve())
        try:
            for mode in ('legacy', 'compact'):
                directory = root/mode
                directory.mkdir()
                measurements[mode] = {action: run_child(mode, action, directory, destination/(mode+'-'+action+'.json'))
                    for action in ('write', 'read')}
        finally:
            for path in root.rglob('*'):
                if path.is_file():
                    os.chmod(path, stat.S_IREAD | stat.S_IWRITE)
    identities = {entry['fixture']['identity_sha256'] for mode in measurements.values() for entry in mode.values()}
    assert len(identities) == 1
    assert len({entry['pid'] for mode in measurements.values() for entry in mode.values()}) == 4
    summary = {}
    for mode, runs in measurements.items():
        summary[mode] = dict(publish_seal_seconds=runs['write']['elapsed_seconds'],
            independent_read_seconds=runs['read']['elapsed_seconds'], physical_bytes=runs['write']['physical_bytes'],
            peak_tracked_bytes=max(run['logical_budget']['peak_reserved_bytes'] for run in runs.values()),
            sampled_peak_rss_bytes=max(run['process_observation']['sampled_peak_rss_bytes'] for run in runs.values()),
            sampled_peak_private_bytes=max(run['process_observation']['sampled_peak_private_bytes'] for run in runs.values()))
    report = dict(schema='atlas.step8.synthetic-storage-measurement.v1', status='PASS',
        scientific_acceptance=False, fixture_identity_sha256=identities.pop(), repetitions_per_mode=1,
        summary=summary, observations=measurements,
        initial_harness_diagnostics=['Initial single-process observer assertion refused the venv launcher plus child interpreter; no measurement completed. Corrected to owned whole-tree sampling and guaranteed error teardown; an exact-path process check confirmed no remaining worker.'],
        limits=['Synthetic storage integration fixture only; no historical migration, native physics or IV2 advance.',
                'One fresh writer and one separate fresh reader per mode; no statistical performance claim.',
                'Legacy JSON payloads and compact DAGs preserve identical logical content; physical layouts differ.',
                'Deliberate subtree sharing and unchanged numeric values are not representative real-workload compression.',
                'OS cache and system load uncontrolled; sampled process peaks include interpreter imports and fixture preparation.',
                'Physical file lengths exclude filesystem allocation overhead; temporary stores removed only after evidence saved.'])
    final.write_bytes(canonical(report))
    print(json.dumps(dict(status='PASS', summary=summary, evidence=str(final))), flush=True)


if __name__ == '__main__':
    main()
