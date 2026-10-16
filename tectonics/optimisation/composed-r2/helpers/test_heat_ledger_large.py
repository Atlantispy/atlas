"""Required 80k-cell/240k-face, roughly 616 MB logical heat ledger gate.

Deliberately high-sharing synthetic rational/ID data. This is storage capacity
and bounded decoding evidence, not scientific admission or typical compression.
Run directly with a new output directory; no historical store is opened.
"""
import gc
from hashlib import sha256
import json
from pathlib import Path
import sys
from time import perf_counter

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parents[1]/'runtime-integration-r1'/'runtime-src'), str(HERE.parent)]
from atlas_tectonics.resources import WorkBudget
from compact_contracts import SegmentRef
from content_cache import ChargeSpec, create_retained_scope
from heat_ledger_tables import CompactHeatSnapshot
from interval_store_set import IntervalStoreSet
from record_tables import StreamingRows, canonical
import private_heat_snapshot_store_r4 as S


def run(path):
    path.mkdir(parents=True, exist_ok=False)
    budget = WorkBudget(1 << 30)
    scope = create_retained_scope(budget, process_epoch='large-heat')
    stores = IntervalStoreSet.create_migration(path/'catalog.json', workflow_id='a'*64, scope=scope)
    candidate = stores.begin_interval(None, producer_identity='b'*64, runtime_identity='c'*64)
    n, nf = 80000, 240000
    q = ['0x'+'a'*525, '0x'+'b'*525]
    values = dict(cell_ids=(n, 'd'*64), face_ids=(nf, 'e'*64),
        exact_corrected_enthalpy_j=(n, q), exact_input_enthalpy_j=(n, q),
        exact_residual_j=(n, q), exact_source_j=(n, q), exact_face_energy_j=(nf, q))
    def rows(count, value):
        for _ in range(count):
            with scope.reserve(ChargeSpec('large-heat-row', 65536)) as reservation:
                yield reservation.commit(value)
    metadata = {k: StreamingRows(count, lambda count=count, value=value: rows(count, value))
                for k, (count, value) in values.items()}
    # Independent legacy canonical digest uses arithmetic repetition; never an
    # expanded list or the 616 MB JSON allocation. All fields still get visited
    # by the production StreamingRows packer and independent cold reader.
    digest, length = sha256(), 0
    def emit(raw):
        nonlocal length
        digest.update(raw); length += len(raw)
    emit(b'{')
    for at, name in enumerate(sorted(values)):
        if at:
            emit(b',')
        emit(canonical(name)+b':[')
        count, value = values[name]
        item = canonical(value)
        for i in range(count):
            if i:
                emit(b',')
            emit(item)
        emit(b']')
    emit(b'}')
    expected = (digest.hexdigest(), length)
    assert 616_000_000 <= length < 617_000_000, length
    started = last = perf_counter()
    def check():
        nonlocal last
        now = perf_counter()
        if now-last > 30:
            print(json.dumps(dict(stage='working', seconds=now-started,
                                  retained_bytes=scope.stats().retained_bytes)), flush=True)
            last = now
        if now-started > 1500:
            raise RuntimeError('bounded large-heat gate exceeded1500 seconds')
    snapshot = CompactHeatSnapshot.from_components(metadata,
        {'enthalpy_j': np.zeros(n), 'face_temperature_k': np.zeros(nf)}, scope=scope, check=check)
    packed = perf_counter()
    assert (snapshot.metadata_identity.sha256, snapshot.metadata_identity.canonical_bytes) == expected
    print(json.dumps(dict(stage='packed', seconds=packed-started, logical_bytes=length,
                          retained_bytes=scope.stats().retained_bytes)), flush=True)
    result_id = snapshot.result_id
    bindings = {'source': 'f'*64, 'call': '1'*64}
    receipt = S.save(candidate, snapshot, bindings=bindings, scope=scope, cancel=lambda: check() or False)
    saved = perf_counter()
    statistics = candidate.local_statistics()
    sealed = candidate.seal(SegmentRef.from_wire(receipt['metadata']['ledger']))
    stores.promote(sealed, expected_catalog_digest=sealed.expected_catalog_digest)
    (path/'receipt.json').write_text(json.dumps(receipt), encoding='utf-8')
    snapshot.close(); candidate.close(); stores.close(); gc.collect(); scope.close()
    assert budget.reserved_bytes == 0, budget.statistics()
    output = dict(cells=n, faces=nf, metadata_bytes=length, result_id=result_id,
                  pack_seconds=packed-started, save_seconds=saved-packed,
                  tracked_peak=budget.statistics(), store_statistics=statistics,
                  source_sha256={name: sha256((HERE/name).read_bytes()).hexdigest() for name in
                      ('heat_ledger_tables.py', 'private_heat_snapshot_store_r4.py', 'record_tables.py', 'record_views.py')})
    (path/'measurement.json').write_text(json.dumps(output, indent=2), encoding='utf-8')
    print(json.dumps(dict(stage='saved', **output)), flush=True)


def cold(path):
    receipt = json.loads((path/'receipt.json').read_text(encoding='utf-8'))
    budget = WorkBudget(1 << 30)
    scope = create_retained_scope(budget, process_epoch='large-heat-cold')
    stores = IntervalStoreSet.open_catalog(path/'catalog.json', scope=scope)
    started = last = perf_counter()
    def check():
        nonlocal last
        now = perf_counter()
        if now-last > 30:
            print(json.dumps(dict(stage='cold-working', seconds=now-started,
                                  retained_bytes=scope.stats().retained_bytes)), flush=True)
            last = now
        return now-started > 1500
    with S.open(stores, receipt, expected_result_id=receipt['metadata']['result_id'],
                bindings=receipt['metadata']['bindings'], scope=scope, cancel=check) as owner:
        snapshot = owner.value
        assert snapshot.metadata_identity.canonical_bytes == receipt['metadata']['metadata_bytes']
        with snapshot.ledger as ledger:
            for name, count in (('cell_ids', 80000), ('face_ids', 240000),
                                ('exact_face_energy_j', 240000), ('exact_corrected_enthalpy_j', 80000)):
                with ledger.field(name) as row:
                    assert row.size == count
        seconds, held = perf_counter()-started, scope.stats().retained_bytes
        snapshot.close()
    del snapshot
    stores.close(); gc.collect(); scope.close()
    assert budget.reserved_bytes == 0, budget.statistics()
    output = dict(stage='cold-complete', seconds=seconds, retained_at_open=held,
                  tracked=budget.statistics(), disk_bytes=sum(p.stat().st_size for p in path.iterdir() if p.is_file()))
    (path/'cold-measurement.json').write_text(json.dumps(output, indent=2), encoding='utf-8')
    print(json.dumps(output), flush=True)


if __name__ == '__main__':
    (cold if sys.argv[1] == 'cold' else run)(Path(sys.argv[2]))
