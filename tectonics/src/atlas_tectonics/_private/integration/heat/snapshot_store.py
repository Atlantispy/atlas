"""Bounded compact heat persistence; historical r3 receipts remain immutable.

The receipt's logical block is exactly the old one. Physical ledger columns and
native field buffers use the existing segmented backend and interval lineage.
No path uses ArrayStore.get, a whole metadata decode or a six-times charge.
"""
from hashlib import sha256
import json
import math
from typing import cast

import numpy as np

from atlas_tectonics._private.codecs.compact_contracts import LogicalIdentity, SegmentRef, SnapshotLocator
from atlas_tectonics._private.codecs.content_cache import ChargeSpec, OwnedStream
from atlas_tectonics._private.codecs.heat_ledger_tables import CompactHeatSnapshot, LEDGER_SCHEMA, own_field
from atlas_tectonics._private.codecs.record_tables import canonical, require
from atlas_tectonics._private.codecs.record_views import CompactRecord
from atlas_tectonics._private.codecs.segment_store import ArrayInfo, SegmentBackend, cancel_check

SCHEMA = 'atlas.private.exact-snapshot-compact-store.r4'
LEGACY_SCHEMA = 'atlas.private.exact-snapshot-array-store.r1'
FIELDS_SCHEMA = 'atlas.private.heat-fields.v1'
PROFILE = 'atlas.private.heat-ledger.columns.v1'
LOOKUP_SCHEMA = 'atlas.private.heat-legacy-lookup.v1'
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
    return dict(value)


def _scope(obj, scope, budget):
    result = obj.scope if scope is None else scope
    return result


def _segment_ref(value):
    """Bound primitive widths before generic contract JSON encoding."""
    def visit(item, depth=0):
        if type(item) is dict:
            for key, child in item.items():
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
    fields = meta['fields']
    require(type(fields) is list and 1 <= len(fields) <= 128, 'bounded field inventory required')
    names, total = [], meta['metadata_bytes']
    for i, row in enumerate(fields):
        require(type(row) is dict and set(row) == {'name', 'shape', 'array', 'sha256'},
                'exact heat field descriptor required')
        require(type(row['name']) is str and 0 < len(row['name']) <= 512 and
                row['array'] == 'field_'+str(i), 'bounded ordered field names required')
        shape = row['shape']
        _bindings({'field': row['sha256']})
        names.append(row['name'])
        total += 8*math.prod(cast(list[int], shape))
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
    encoded = canonical(meta)
    require(len(encoded) <= 65536, 'heat receipt exceeds 64 KiB')
    return encoded


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
    scope = _scope(candidate, scope, budget)
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
    invocation = sha256(_manifest(metadata, compact=True)).hexdigest()
    cancel_check(token)
    return dict(invocation=invocation, metadata=metadata)


def _receipt(receipt, expected_result_id, bindings):
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
    meta = legacy_receipt['metadata']
    require(original_store.metadata(legacy_receipt['invocation']) == meta,
            'authenticated original heat manifest differs')
    with scope.reserve(ChargeSpec('heat-original-manifest', 9 << 20)) as reserved:
        original = reserved.commit(original_store._manifest(legacy_receipt['invocation']))
    manifest = original.value
    descriptions = [('metadata_utf8', [meta['metadata_bytes']], np.dtype('u1').str)]
    descriptions.extend((row['array'], row['shape'], np.dtype(np.float64).str) for row in meta['fields'])
    for name, shape, dtype in descriptions:
        pass
    _logical(snapshot, bindings)
    inventory = [('metadata_utf8', meta['metadata_bytes'], meta['metadata_sha256'], np.dtype('u1'))]
    inventory.extend((r['array'], 8*math.prod(r['shape']), r['sha256'], np.dtype(np.float64)) for r in meta['fields'])
    for name, size, expected, dtype in inventory:
        count, digest = 0, sha256()
        for offset, values in original_store.iter_chunks(legacy_receipt['invocation'], name, budget=scope.run_budget):
            cancel_check(token)
            raw = memoryview(values).cast('B')
            digest.update(raw)
            count += len(raw)
    require(original_store._manifest(legacy_receipt['invocation']) == manifest,
            'original heat changed during conversion')
    del manifest
    original.close()
    compact = save(candidate, snapshot, bindings=bindings, scope=scope, cancel=token)
    row = dict(schema=LOOKUP_SCHEMA, legacy=legacy_receipt, compact=compact)
    candidate.put_manifest(_lookup_key(legacy_receipt), row, cancel=token)
    return compact
