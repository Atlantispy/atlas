"""Matched read-only reopen of saved Step 7 fixtures; one fresh child per sample."""
from hashlib import sha256
import json
from pathlib import Path
import sys
import threading
import time

HERE = Path(__file__).resolve().parent
R = HERE.parents[1]
C = R/'compact-geometry-r1'
mode, size, output = sys.argv[1:]
assert mode in ('baseline', 'candidate') and size in ('small', 'large')
sys.path[:0] = ([str(HERE/'baseline-src')] if mode == 'baseline' else []) + [
    str(C), str(R), str(R.parent/'runtime-integration-r1/runtime-src')]
import blosc2
import numpy as np
import psutil
from atlas_tectonics.resources import WorkBudget
from content_cache import create_retained_scope
from interval_store_set import IntervalStoreSet
import private_heat_snapshot_store_r4 as STORE
import heat_ledger_tables
import record_views
import segment_store

fixture = R/('probes/step7/matched-r2/compact' if size == 'small' else
             'probes/step7-heat-ledger-large-r1')
receipt = json.loads((fixture/'receipt.json').read_text(encoding='utf8'))
source_paths = [Path(module.__file__) for module in (STORE, heat_ledger_tables, record_views, segment_store)]
sources = {str(path): sha256(path.read_bytes()).hexdigest() for path in source_paths}
budget = WorkBudget(1 << 30)
scope = create_retained_scope(budget, process_epoch='step7b-'+mode+'-'+size)
process = psutil.Process()
initial = process.memory_info()
observed = dict(rss=initial.rss, private=initial.private)
stop = threading.Event()
def sample():
    while not stop.wait(.005):
        memory = process.memory_info()
        observed['rss'] = max(observed['rss'], memory.rss)
        observed['private'] = max(observed['private'], memory.private)
sampler = threading.Thread(target=sample)
sampler.start()
started = last = time.perf_counter()
def check_cancelled():
    global last
    now = time.perf_counter()
    if now-last >= 30:
        print(json.dumps(dict(stage='reopening', mode=mode, size=size, seconds=now-started)), flush=True)
        last = now
    return now-started > 600
class Cancellation:
    is_set = staticmethod(check_cancelled)
check = Cancellation()
try:
    stores = IntervalStoreSet.open_catalog(fixture/'catalog.json', scope=scope, cancel=check)
    with STORE.open(stores, receipt, expected_result_id=receipt['metadata']['result_id'],
                    bindings=receipt['metadata']['bindings'], scope=scope, cancel=check) as owner:
        restored = owner.value
        assert restored.result_id == receipt['metadata']['result_id']
        assert restored.metadata_identity.sha256 == receipt['metadata']['metadata_sha256']
        assert restored.metadata_identity.canonical_bytes == receipt['metadata']['metadata_bytes']
        array_hashes = {name:sha256(restored.array(name)).hexdigest() for name in restored.array_names}
        assert array_hashes == {row['name']:row['sha256'] for row in receipt['metadata']['fields']}
        if size == 'large':
            with restored.ledger as ledger:
                for name,count in (('cell_ids',80000),('face_ids',240000),
                                   ('exact_face_energy_j',240000),('exact_corrected_enthalpy_j',80000)):
                    with ledger.field(name) as row:
                        assert row.size == count
        retained_at_open = scope.stats().retained_bytes
        restored.close()
    del restored, owner
    stores.close()
    del stores
    scope.close()
    seconds = time.perf_counter()-started
finally:
    stop.set()
    sampler.join()
assert budget.reserved_bytes == 0
assert all(sha256(path.read_bytes()).hexdigest()==sources[str(path)] for path in source_paths)
memory = process.memory_info()
result = dict(mode=mode, size=size, seconds=seconds, source_sha256=sources,
    probe_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
    result_id=receipt['metadata']['result_id'], metadata_sha256=receipt['metadata']['metadata_sha256'],
    metadata_bytes=receipt['metadata']['metadata_bytes'], array_hashes=array_hashes,
    sampled_peak_rss_bytes=observed['rss'], sampled_peak_private_bytes=observed['private'],
    lifetime_peak_wset_bytes=memory.peak_wset, initial_rss_bytes=initial.rss,
    tracked_peak_bytes=budget.peak_reserved_bytes, retained_at_open=retained_at_open,
    reserved_after_close=budget.reserved_bytes,
    physical_store_bytes=sum(p.stat().st_size for p in fixture.iterdir()
                             if p.suffix=='.sqlite' or p.name=='catalog.json'),
    runtime=dict(python=sys.version,numpy=np.__version__,blosc2=blosc2.__version__),
    sample_ms=5, scope='read-only saved synthetic store; includes catalog, exact restore, array hashes and close; no heat solve; OS cache uncontrolled')
Path(output).write_text(json.dumps(result,indent=2,sort_keys=True)+'\n',encoding='utf8')
print(json.dumps(result),flush=True)
