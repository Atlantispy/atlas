"""One-time, bounded conversion of authenticated original heat checkpoints."""
from hashlib import sha256
import json

import numpy as np


def migrate_heat_history(original_store, store, admission, *, source_producer, budget, check):
    import historical_admission as H
    import workflow_transfer as W
    import native_transfer as N
    import materialise_endpoint as M
    from heat_ledger_tables import CompactHeatSnapshot
    import private_heat_snapshot_store_r4 as S
    from compact_contracts import SegmentRef
    from segment_store import SegmentBackend

    H._require(W.is_compact_restart_store(store, budget=budget) and
        type(admission) is W.HistoricalEndpointAdmission, 'actual compact historical heat owners required')
    capsule_owner = W._decode_allocation(budget, admission._record)
    capsule = admission.record()
    binding = dict(schema='atlas.restart-compact-heat-history.v1',
        head_key=capsule['source']['head_key'], source_producer=source_producer)
    key = W.digest(binding)
    expected = {invocation: manifest['metadata'] for invocation, manifest in capsule['snapshot_manifests'].items()
        if manifest.get('metadata', {}).get('schema') == S.LEGACY_SCHEMA}
    source_manifest_sha256 = W.digest({invocation: capsule['snapshot_manifests'][invocation]
                                      for invocation in expected})
    saved = store.metadata(key)
    if saved is not None:
        H._require(set(saved) == {'binding', 'receipts', 'source_manifest_sha256'} and
            saved['source_manifest_sha256'] == source_manifest_sha256 and saved['binding'] == binding and
            set(saved['receipts']) == set(expected), 'compact heat migration inventory differs')
        for invocation, meta in expected.items():
            receipt = saved['receipts'][invocation]
            H._require(S._receipt(receipt, meta['result_id'], meta['bindings']) and
                all(receipt['metadata'][k] == meta[k] for k in S.LOGICAL_KEYS),
                'compact heat migration logical receipt differs')
            for name in ('ledger', 'field_payload'):
                SegmentBackend().verify(store, SegmentRef.from_wire(receipt['metadata'][name]),
                    scope=store.scope, cancel=S._token(check))
        return saved
    H._require(not store.readonly and store.interval == 0, 'missing compact heat migration evidence')
    receipts = {}
    for invocation, meta in expected.items():
        check()
        legacy = dict(invocation=invocation, metadata=meta)
        H._require(not S._receipt(legacy, meta['result_id'], meta['bindings']), 'legacy heat receipt required')
        size = meta['metadata_bytes']
        H._require(0 < size <= 512 << 20, 'historical heat decode exceeds explicit migration bound')
        arrays = H.read_selected_arrays(original_store, invocation,
            ['metadata_utf8', *(row['array'] for row in meta['fields'])],
            admission=admission, budget=budget, check=check)
        raw_owner = N._Allocation(budget, 65536+4*size, category='migration-heat-raw')
        values = arrays['metadata_utf8']
        H._require(values.dtype == np.dtype('uint8') and values.ndim == 1 and values.nbytes == size,
            'historical heat metadata layout differs')
        raw = values.tobytes()
        H._require(sha256(raw).hexdigest() == meta['metadata_sha256'], 'historical heat metadata bytes differ')
        slots = 1+sum(raw.count(token) for token in (b'{', b'[', b':', b','))
        decoded_owner = N._Allocation(budget, 65536+4*size+128*slots, category='migration-heat-decoded')
        decoded = json.loads(raw)
        H._require(type(decoded) is dict and M._canonical_equal(decoded, raw, budget),
            'historical heat metadata is not exact canonical JSON')
        fields = {row['name']: arrays[row['array']] for row in meta['fields']}
        snapshot = CompactHeatSnapshot.from_components(decoded, fields, scope=store.scope,
            check=check, expected_result_id=meta['result_id'])
        receipts[invocation] = S.register_legacy_lookup(store, original_store, legacy, snapshot,
            bindings=meta['bindings'], budget=budget, cancel=check)
        snapshot.close()
        del snapshot, fields, decoded, decoded_owner, raw, raw_owner, values, arrays
    row = dict(binding=binding, receipts=receipts, source_manifest_sha256=source_manifest_sha256)
    store.put(key, {'empty': np.empty(0, dtype=np.uint8)}, row, budget=budget)
    del capsule, capsule_owner
    return row
