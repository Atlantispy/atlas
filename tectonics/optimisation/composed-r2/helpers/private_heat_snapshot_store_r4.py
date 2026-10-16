"""Bounded compact heat persistence; historical r3 receipts remain immutable.

The receipt's logical block is exactly the old one. Physical ledger columns and
native field buffers use the existing segmented backend and interval lineage.
No path uses ArrayStore.get, a whole metadata decode or a six-times charge.
"""
from hashlib import sha256
import json
import math

import numpy as np

from compact_contracts import LogicalIdentity, SegmentRef, SnapshotLocator
from content_cache import ChargeSpec, OwnedStream
from heat_ledger_tables import CompactHeatSnapshot, LEDGER_SCHEMA, own_field
from record_tables import canonical, require
from record_views import CompactRecord
from segment_store import ArrayInfo, SegmentBackend, cancel_check

SCHEMA = 'atlas.private.exact-snapshot-compact-store.r4'
LEGACY_SCHEMA = 'atlas.private.exact-snapshot-array-store.r1'
FIELDS_SCHEMA = 'atlas.private.heat-fields.v1'
PROFILE = 'atlas.private.heat-ledger.columns.v1'
LOOKUP_SCHEMA = 'atlas.private.heat-legacy-lookup.v1'
MAX_LOGICAL_BYTES = 16 << 30
LOGICAL_KEYS = frozenset(('result_id', 'bindings', 'metadata_bytes', 'metadata_sha256',
    'fields', 'logical_bytes', 'detached_only', 'native_admission'))


class _Cancellation:
    def __init__(self, callback):
        self.callback = callback

    def is_set(self):
        return self.callback is not None and self.callback()


def _token(cancel):
    return cancel if cancel is None or hasattr(cancel, 'is_set') else _Cancellation(cancel)


def _bindings(value):
    require(type(value) is dict and 0 < len(value) <= 32 and all(
        type(k) is str and 0 < len(k) <= 128 and type(v) is str and len(v) == 64 and
        all(c in '0123456789abcdef' for c in v) for k, v in value.items()),
        'explicit bounded source/call/plan SHA256 bindings required')
    return dict(value)


def _scope(obj, scope, budget):
    result = obj.scope if scope is None else scope
    require(obj.scope is result and (budget is None or result.run_budget is budget),
            'same retained scope and run budget required')
    return result


def _segment_ref(value):
    """Bound primitive widths before generic contract JSON encoding."""
    def visit(item, depth=0):
        require(depth <= 4, 'heat segment envelope nesting exceeds bound')
        if type(item) is dict:
            require(len(item) <= 8, 'heat segment envelope field count exceeds bound')
            for key, child in item.items():
                require(type(key) is str and len(key) <= 32, 'heat segment envelope key exceeds bound')
                visit(child, depth+1)
        elif type(item) is str:
            require(len(item) <= 256, 'heat segment envelope string exceeds bound')
        else:
            require(type(item) is int and 0 <= item < 1 << 64, 'heat segment envelope scalar differs')
    visit(value)
    return SegmentRef.from_wire(value)


def _manifest(meta, *, compact):
    expected = LOGICAL_KEYS | {'schema'} | ({'ledger', 'field_payload', 'shared_mesh'} if compact else set())
    require(type(meta) is dict and set(meta) == expected and
            meta['schema'] == (SCHEMA if compact else LEGACY_SCHEMA), 'exact heat receipt schema required')
    _bindings(meta['bindings'])
    _bindings({name: meta[name] for name in ('result_id', 'metadata_sha256')})
    require(meta['detached_only'] is True and meta['native_admission'] is False,
            'detached-only heat receipt required')
    require(all(type(meta[name]) is int and 0 < meta[name] <= MAX_LOGICAL_BYTES
                for name in ('metadata_bytes', 'logical_bytes')), 'heat logical size exceeds bound')
    fields = meta['fields']
    require(type(fields) is list and 1 <= len(fields) <= 128, 'bounded field inventory required')
    names, total = [], meta['metadata_bytes']
    for i, row in enumerate(fields):
        require(type(row) is dict and set(row) == {'name', 'shape', 'array', 'sha256'},
                'exact heat field descriptor required')
        require(type(row['name']) is str and 0 < len(row['name']) <= 512 and
                row['array'] == 'field_'+str(i), 'bounded ordered field names required')
        shape = row['shape']
        require(type(shape) is list and len(shape) <= 16 and all(type(n) is int and
                0 <= n <= (512 << 20) for n in shape) and 8*math.prod(shape) <= 512 << 20,
                'heat field shape exceeds 512 MiB bound')
        _bindings({'field': row['sha256']})
        names.append(row['name'])
        total += 8*math.prod(shape)
    require(names == sorted(set(names)) and total == meta['logical_bytes'],
            'heat field order or logical size differs')
    if compact:
        ledger, payload = (_segment_ref(meta[k]) for k in ('ledger', 'field_payload'))
        shared = meta['shared_mesh']
        if shared is None:
            require(ledger.identity == LogicalIdentity(LEDGER_SCHEMA, meta['metadata_sha256'], meta['metadata_bytes']),
                    'heat ledger logical binding differs')
        else:
            require(type(shared) is dict and set(shared) == {'geometry_id', 'cell_count', 'face_count', 'caller_ids', 'segment'},
                    'bounded exact shared heat mesh binding required')
            _bindings({'geometry': shared['geometry_id']})
            require(all(type(shared[k]) is int and 0 <= shared[k] <= 4_000_000 for k in ('cell_count', 'face_count'))
                    and type(shared['caller_ids']) is bool and ledger.identity.record_schema == LEDGER_SCHEMA,
                    'bounded mesh ID count required')
            require(shared['segment'] is not None, 'persisted shared heat IDs require an authenticated mesh segment')
            mesh = _segment_ref(shared['segment'])
            require(mesh.identity.sha256 == shared['geometry_id'] and
                    mesh.root_key.workflow_id == ledger.root_key.workflow_id,
                    'shared heat mesh geometry/workflow differs')
        require(payload.identity == _field_identity(fields), 'heat field logical binding differs')
        require(payload.root_key.workflow_id == ledger.root_key.workflow_id,
                'heat field/ledger workflows differ')
    require(len(canonical(meta)) <= 65536, 'heat receipt exceeds 64 KiB')


def _field_identity(fields):
    raw = canonical(fields)
    return LogicalIdentity(FIELDS_SCHEMA, sha256(raw).hexdigest(), len(raw))


def _logical(snapshot, bindings):
    fields = [dict(name=name, shape=list(shape), array='field_'+str(i), sha256=sha256(raw).hexdigest())
              for i, (name, shape, raw) in enumerate(snapshot._fields)]
    identity = snapshot.metadata_identity
    return dict(result_id=snapshot.result_id, bindings=_bindings(bindings),
        metadata_bytes=identity.canonical_bytes, metadata_sha256=identity.sha256,
        fields=fields, logical_bytes=snapshot.nbytes, detached_only=True, native_admission=False)


class _FieldSource:
    def __init__(self, snapshot, i):
        _, shape, raw = snapshot._fields[i]
        self.raw, self.scope = raw, snapshot.scope
        self.info = ArrayInfo('field_'+str(i), np.dtype(np.float64).str, shape, len(raw))

    def blocks(self, *, max_owned_bytes):
        def rows():
            for at in range(0, len(self.raw), max_owned_bytes):
                with self.scope.reserve(ChargeSpec('heat-field-block', max_owned_bytes)) as reserved:
                    yield reserved.commit(bytes(memoryview(self.raw)[at:at+max_owned_bytes]))
        return OwnedStream(rows(), scope=self.scope)


def save(candidate, snapshot, *, bindings, budget=None, scope=None, cancel=None):
    require(type(snapshot) is CompactHeatSnapshot, 'compact heat snapshot required')
    scope = _scope(candidate, scope, budget)
    require(snapshot.scope is scope, 'same-scope heat snapshot required')
    token = _token(cancel)
    cancel_check(token)
    snapshot.verify_identity(check=lambda: cancel_check(token))
    logical = _logical(snapshot, bindings)
    producer = sha256(canonical(logical['bindings'])).hexdigest()
    backend = SegmentBackend()
    with snapshot.record.metadata_bytes() as encoded:
        ledger = backend.publish(candidate, record_schema=LEDGER_SCHEMA,
            identity=snapshot.record.identity(), metadata=encoded.value,
            arrays=snapshot.record.array_sources, producer=producer,
            representation_profile=PROFILE, scope=scope, cancel=token)
    def arrays():
        for i in sorted(range(len(snapshot._fields)), key=lambda i: ('field_'+str(i)).encode()):
            yield _FieldSource(snapshot, i)
    fields = backend.publish(candidate, record_schema=FIELDS_SCHEMA,
        identity=_field_identity(logical['fields']), metadata=canonical({'fields': logical['fields']}),
        arrays=arrays, producer=producer, representation_profile=PROFILE, scope=scope, cancel=token)
    metadata = dict(schema=SCHEMA, **logical, ledger=ledger.to_wire(), field_payload=fields.to_wire(),
                    shared_mesh=snapshot.mesh_binding)
    _manifest(metadata, compact=True)
    cancel_check(token)
    return dict(invocation=sha256(canonical(metadata)).hexdigest(), metadata=metadata)


def _receipt(receipt, expected_result_id, bindings):
    require(type(receipt) is dict and set(receipt) == {'invocation', 'metadata'},
            'exact caller-retained heat receipt required')
    meta = receipt['metadata']
    compact = type(meta) is dict and meta.get('schema') == SCHEMA
    _manifest(meta, compact=compact)
    require(meta['result_id'] == expected_result_id and meta['bindings'] == _bindings(bindings)
            and sha256(canonical(meta)).hexdigest() == receipt['invocation'],
            'expected heat source/call/plan/result identity differs')
    return compact


def _resolve(resolver, locator, token):
    if hasattr(resolver, 'interval'):
        return resolver.resolve_manifest(locator, cancel=token)
    require(resolver.head is not None, 'sealed heat lookup requires a head')
    return resolver.resolve_manifest(resolver.head.interval, locator, cancel=token)


def _lookup_key(receipt):
    return sha256(canonical(dict(schema=LOOKUP_SCHEMA, legacy=receipt))).hexdigest()


def open(resolver, receipt, *, expected_result_id, bindings, scope=None, budget=None, cancel=None, mesh=None):
    scope = _scope(resolver, scope, budget)
    token = _token(cancel)
    cancel_check(token)
    # Freeze the small caller envelope before touching a store.
    with scope.reserve(ChargeSpec('heat-receipt', 1 << 20)) as reservation:
        compact = _receipt(receipt, expected_result_id, bindings)
        owned_receipt = reservation.commit(json.loads(canonical(receipt)))
    receipt = owned_receipt.value
    if not compact:
        locator = SnapshotLocator(resolver.workflow_id, 0, _lookup_key(receipt))
        with _resolve(resolver, locator, token) as lookup:
            manifest = json.loads(lookup.value)
            row = manifest['metadata']
            require(type(row) is dict and set(row) == {'schema', 'legacy', 'compact'} and
                    row['schema'] == LOOKUP_SCHEMA and row['legacy'] == receipt,
                    'authenticated historical heat lookup differs')
            successor = row['compact']
            require(_receipt(successor, expected_result_id, bindings), 'compact lookup target required')
            require(all(successor['metadata'][k] == receipt['metadata'][k] for k in LOGICAL_KEYS),
                    'historical heat logical block changed')
            result = open(resolver, successor, expected_result_id=expected_result_id,
                          bindings=bindings, scope=scope, cancel=token, mesh=mesh)
        owned_receipt.close()
        return result
    meta = receipt['metadata']
    backend = SegmentBackend()
    producer = sha256(canonical(_bindings(bindings))).hexdigest()
    ledger_segment = backend.open(resolver, SegmentRef.from_wire(meta['ledger']), scope=scope, cancel=token)
    require(ledger_segment._owner.value['representation_profile'] == PROFILE and
            ledger_segment._owner.value['producer'] == producer, 'heat ledger profile/source producer differs')
    record = CompactRecord.from_segment(ledger_segment, check=lambda: cancel_check(token))
    payload = backend.open(resolver, SegmentRef.from_wire(meta['field_payload']), scope=scope, cancel=token)
    require(payload._owner.value['representation_profile'] == PROFILE and payload._owner.value['producer'] == producer and
            payload.info.array_count == len(meta['fields']), 'heat field representation differs')
    with payload.metadata() as metadata:
        require(metadata.value == canonical({'fields': meta['fields']}), 'heat field metadata differs')
    fields = []
    for row in meta['fields']:
        cancel_check(token)
        with payload.info.array(row['array']) as info:
            require(info.value.dtype == np.dtype(np.float64).str and list(info.value.shape) == row['shape'],
                    'native heat field descriptor differs')
        count = 8*math.prod(row['shape'])
        with scope.reserve(ChargeSpec('heat-field-restore', count+65536)) as reservation:
            buffer = reservation.commit(bytearray(count))
        at, digest, raw = 0, sha256(), None
        with payload.iter(row['array'], block_bytes=65536, max_owned_bytes=131072) as stream:
            for block in stream:
                with block:
                    raw = block.value
                    buffer.value[at:at+len(raw)] = raw
                    at += len(raw)
                    digest.update(raw)
        require(at == count and digest.hexdigest() == row['sha256'], 'native heat field bytes differ')
        fields.append((row['name'], tuple(row['shape']), own_field(buffer.value, scope=scope)))
        del raw
        buffer.close()
    snapshot = CompactHeatSnapshot(record, tuple(fields), check=lambda: cancel_check(token),
        expected_result_id=expected_result_id, mesh=mesh, mesh_binding=meta['shared_mesh'],
        expected_metadata_identity=LogicalIdentity(LEDGER_SCHEMA, meta['metadata_sha256'], meta['metadata_bytes']))
    payload.close()
    owned_receipt.close()
    cancel_check(token)
    with scope.reserve(ChargeSpec('heat-snapshot-handle', 65536)) as reservation:
        return reservation.commit(snapshot)


restore = open


def register_legacy_lookup(candidate, original_store, legacy_receipt, snapshot, *, bindings,
                           budget=None, scope=None, cancel=None):
    """D6's authenticated original-to-compact link, only in migration interval 0.

    The caller supplies its bounded converted snapshot. This gate independently
    hashes original native chunks; it never trusts a supplied legacy receipt
    without matching the original store or modifies original/historical bytes.
    """
    scope = _scope(candidate, scope, budget)
    token = _token(cancel)
    require(candidate.interval == 0, 'historical heat lookup belongs in interval-0000')
    require(not _receipt(legacy_receipt, snapshot.result_id, bindings), 'historical r3 receipt required')
    meta = legacy_receipt['metadata']
    require(original_store.metadata(legacy_receipt['invocation']) == meta,
            'authenticated original heat manifest differs')
    from atlas_tectonics.storage import ArrayStore
    require(type(original_store) is ArrayStore and original_store.limits.max_manifest_bytes <= 1 << 20,
            'bounded original native ArrayStore required')
    with scope.reserve(ChargeSpec('heat-original-manifest', 9 << 20)) as reserved:
        original = reserved.commit(original_store._manifest(legacy_receipt['invocation']))
    manifest = original.value
    require(set(manifest['arrays']) == {'metadata_utf8', *(row['array'] for row in meta['fields'])},
            'complete original heat field inventory required')
    descriptions = [('metadata_utf8', [meta['metadata_bytes']], np.dtype('u1').str)]
    descriptions.extend((row['array'], row['shape'], np.dtype(np.float64).str) for row in meta['fields'])
    for name, shape, dtype in descriptions:
        descriptor = manifest['arrays'][name]
        require(descriptor['dtype'] == dtype and descriptor['shape'] == shape,
                'original heat field shape/dtype differs')
    converted = _logical(snapshot, bindings)
    require(all(converted[k] == meta[k] for k in LOGICAL_KEYS),
            'converted heat logical block differs from original')
    inventory = [('metadata_utf8', meta['metadata_bytes'], meta['metadata_sha256'], np.dtype('u1'))]
    inventory.extend((r['array'], 8*math.prod(r['shape']), r['sha256'], np.dtype(np.float64)) for r in meta['fields'])
    for name, size, expected, dtype in inventory:
        count, digest = 0, sha256()
        for offset, values in original_store.iter_chunks(legacy_receipt['invocation'], name, budget=scope.run_budget):
            cancel_check(token)
            raw = memoryview(values).cast('B')
            require(values.dtype == dtype and offset*dtype.itemsize == count and count+len(raw) <= size,
                    'original heat chunk coverage differs')
            digest.update(raw)
            count += len(raw)
        require(count == size and digest.hexdigest() == expected, 'original heat bytes differ')
    require(original_store._manifest(legacy_receipt['invocation']) == manifest,
            'original heat changed during conversion')
    del manifest
    original.close()
    compact = save(candidate, snapshot, bindings=bindings, scope=scope, cancel=token)
    row = dict(schema=LOOKUP_SCHEMA, legacy=legacy_receipt, compact=compact)
    candidate.put_manifest(_lookup_key(legacy_receipt), row, cancel=token)
    return compact
