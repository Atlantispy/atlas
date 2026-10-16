"""Matched synthetic heat persistence and fresh-process reopen observations.

Input packaging is outside the timed save boundary. Cold processes start with
only the small receipt. This is storage evidence, not a heat solve benchmark.
"""
from hashlib import sha256
import gc
import json
from pathlib import Path
import sys
import threading
import time

R = Path(__file__).resolve().parents[2]
C = R/'compact-geometry-r1'
T = R.parents[3]
H = T/'fidelity-integration-20261005/heat-repair-20261007'
BASE = R.parent/'runtime-integration-r1'
sys.path[:0] = [str(C), str(R), str(BASE/'runtime-src'), str(H)]

import numpy as np
import psutil
import blosc2
import atlas_tectonics.regional_execution as NATIVE_SNAPSHOT
import atlas_tectonics.resources as NATIVE_RESOURCES
import atlas_tectonics.storage as NATIVE_STORE
from atlas_tectonics.regional_execution import RegionalMechanicalSnapshot
from atlas_tectonics.resources import WorkBudget
from atlas_tectonics.storage import ArrayStore
from compact_contracts import SegmentRef
from content_cache import create_retained_scope
from heat_ledger_tables import CompactHeatSnapshot
from interval_store_set import IntervalStoreSet, LIMITS
import private_heat_snapshot_store_r3 as OLD
import private_heat_snapshot_store_r4 as NEW

BINDINGS = {'source': 'f'*64, 'call': '1'*64}
FIELDS = ('enthalpy_j', 'input_capacity_j_k', 'input_enthalpy_j', 'input_source_w', 'temperature_k')


def fixture():
    n, nf = 512, 1536
    pair = ['0x'+'d'*540, '0x'+'e'*540]
    metadata = {name: [pair]*n for name in ('exact_corrected_enthalpy_j',
        'exact_retained_solver_residual_j', 'exact_stock_projection_residual_j',
        'exact_cell_storage_residual_j')}
    metadata.update(exact_paired_face_energy_j=[pair]*nf,
        cell_ids=[sha256(('cell'+str(i)).encode()).hexdigest() for i in range(n)],
        face_ids=[sha256(('face'+str(i)).encode()).hexdigest() for i in range(nf)],
        schema='EXPLICIT_SYNTHETIC_HEAT_STORAGE_NOT_PHYSICAL_ACCEPTANCE',
        caller_snapshot={'fixture_only': True}, exact_source_energy_j=['0x0', '0x1'],
        exact_outward_boundary_energy_j=['0x0', '0x1'])
    return metadata, {name: np.full(n, float(i+1)) for i, name in enumerate(FIELDS)}


def main():
    mode, stage, folder = sys.argv[1:]
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    budget = WorkBudget(1 << 30)
    scope = create_retained_scope(budget, process_epoch='step7-'+mode+'-'+stage)
    snapshot = None
    if stage == 'write':
        metadata, arrays = fixture()
        snapshot = (RegionalMechanicalSnapshot(metadata, arrays) if mode == 'legacy' else
                    CompactHeatSnapshot.from_components(metadata, arrays, scope=scope))
        del metadata, arrays
        gc.collect()
    else:
        receipt = json.loads((folder/'receipt.json').read_text(encoding='utf8'))
    process = psutil.Process()
    before = process.memory_info()
    observed = {'rss': before.rss, 'private': getattr(before, 'private', None)}
    stop = threading.Event()
    def sample():
        while not stop.wait(.005):
            memory = process.memory_info()
            observed['rss'] = max(observed['rss'], memory.rss)
            if observed['private'] is not None:
                observed['private'] = max(observed['private'], memory.private)
    sampler = threading.Thread(target=sample)
    sampler.start()
    started = time.perf_counter()
    try:
        if mode == 'legacy':
            with ArrayStore(folder/'heat.sqlite', LIMITS, budget=budget) as store:
                if stage == 'write':
                    receipt = OLD.save(store, snapshot, bindings=BINDINGS, budget=budget)
                else:
                    with OLD.restore(store, receipt, expected_result_id=receipt['metadata']['result_id'],
                                     bindings=BINDINGS, budget=budget) as owner:
                        restored = owner.value
                        result_id = restored.result_id
                        array_hashes = {name: sha256(restored.array(name)).hexdigest() for name in FIELDS}
                    del restored, owner
        elif stage == 'write':
            stores = IntervalStoreSet.create_migration(folder/'catalog.json', workflow_id='a'*64, scope=scope)
            candidate = stores.begin_interval(None, producer_identity='b'*64, runtime_identity='c'*64)
            receipt = NEW.save(candidate, snapshot, bindings=BINDINGS, scope=scope)
            sealed = candidate.seal(SegmentRef.from_wire(receipt['metadata']['ledger']))
            stores.promote(sealed, expected_catalog_digest=sealed.expected_catalog_digest)
            candidate.close()
            stores.close()
            del candidate, stores
        else:
            stores = IntervalStoreSet.open_catalog(folder/'catalog.json', scope=scope)
            with NEW.open(stores, receipt, expected_result_id=receipt['metadata']['result_id'],
                          bindings=BINDINGS, scope=scope) as owner:
                restored = owner.value
                result_id = restored.result_id
                array_hashes = {name: sha256(restored.array(name)).hexdigest() for name in FIELDS}
                restored.close()
            del restored, owner
            stores.close()
            del stores
        seconds = time.perf_counter()-started
    finally:
        stop.set()
        sampler.join()
    if stage == 'write':
        result_id = snapshot.result_id
        array_hashes = {name: sha256(snapshot.array(name)).hexdigest() for name in FIELDS}
        (folder/'receipt.json').write_text(json.dumps(receipt, sort_keys=True), encoding='utf8')
    memory = process.memory_info()
    source_modules = (OLD, NEW, NATIVE_SNAPSHOT, NATIVE_RESOURCES, NATIVE_STORE)
    result = dict(mode=mode, stage=stage, seconds=seconds, result_id=result_id,
        array_hashes=array_hashes, metadata_bytes=receipt['metadata']['metadata_bytes'],
        metadata_sha256=receipt['metadata']['metadata_sha256'], logical_bytes=receipt['metadata']['logical_bytes'],
        process_sample_ms=5, sampled_peak_rss_bytes=max(observed['rss'], memory.rss),
        sampled_peak_private_bytes=observed['private'], lifetime_peak_wset_bytes=getattr(memory,'peak_wset',None),
        operation_start_rss_bytes=before.rss, tracked_peak_bytes=budget.peak_reserved_bytes,
        runtime=dict(python=sys.version, numpy=np.__version__, blosc2=blosc2.__version__),
        native_source_sha256={str(Path(module.__file__).resolve()):
            sha256(Path(module.__file__).read_bytes()).hexdigest() for module in source_modules},
        physical_store_bytes=sum(p.stat().st_size for p in folder.iterdir()
                                 if p.suffix == '.sqlite' or p.name == 'catalog.json'),
        scope='synthetic persistence or cold data reopen; no heat equations or source admission')
    if isinstance(snapshot, CompactHeatSnapshot):
        snapshot.close()
    snapshot = None
    gc.collect()
    scope.close()
    result['reserved_after_close'] = budget.reserved_bytes
    print(json.dumps(result, sort_keys=True), flush=True)


if __name__ == '__main__':
    main()
