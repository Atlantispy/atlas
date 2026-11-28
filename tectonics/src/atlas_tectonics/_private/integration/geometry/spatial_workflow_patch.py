"""ArrayStore-bound compact spatial workflow publication and cold loading."""
from contextlib import contextmanager
from hashlib import sha256
import json
import math
from types import SimpleNamespace
from typing import cast

import numpy as np

from atlas_tectonics._private.integration import native_transfer as N
from atlas_tectonics._private.integration.geometry import spatial_indexed_patch as X
from atlas_tectonics._private.codecs.compact_store import CompactMeshStore, descriptor_digest
from atlas_tectonics._private.codecs.mesh_tables import CompactMesh, _decode_charge, pack_mesh


PREFIX = 'spatial-mesh:'
LINK_SCHEMA = 'atlas.compact-mesh-link.r1'


def require(value, message):
    if not value:
        raise X.IndexedSpatialRefused(message)


class _OwnedReference(dict):
    def __init__(self, value, budget):
        allocation = N._Allocation(budget, 4*N._width(value)+4096, category='compact-workflow-reference')
        super().__init__(value)
        object.__setattr__(self, '_allocation', allocation)

    def __setattr__(self, name, value):
        raise X.IndexedSpatialRefused('immutable reference ownership')


def producer(collar):
    """Actual conversion/runtime identity, not retrospective scientific credit."""
    return dict(execution_identity=collar._native.descriptor()['execution'], collar_plan_id=collar.plan_id,
                role='lossless indexed storage; original logical geometry identity unchanged')


def _link_record(geometry_id, source_producer):
    return dict(schema=LINK_SCHEMA, geometry_id=geometry_id, source_producer=source_producer)


def reference(store, key, *, geometry_id, source_producer, budget):
    """Construct references only from the authenticated actual current store.

    Each array is bound by its ArrayReference descriptor digest (exact dtype,
    shape and chunk IDs), not a copy of its chunk list: the reference is carried
    in link, migrated-root and successor metadata under the 1 MiB manifest limit.
    """
    from atlas_tectonics.integration.coupling.spatial_transport import _workspace
    with _workspace(budget, 65536+8*store.limits.max_manifest_bytes, 'compact-workflow-reference-read'):
        adapter = CompactMeshStore(store, budget=budget)
        manifest, record = adapter._root(key)
        bindings = {name: descriptor_digest(row) for name, row in manifest['arrays'].items()}
        return _OwnedReference(dict(schema=record['schema'], snapshot_key=key, geometry_id=geometry_id,
                    source_producer=record['source_producer'], array_bindings=bindings), budget)


def verify_reference(store, expected, *, budget):
    X._reference(expected, expected.get('geometry_id'))
    if expected['schema'] == 'atlas.compact-mesh-store.v3':
        from atlas_tectonics._private.codecs.compact_contracts import SegmentRef
        from atlas_tectonics._private.codecs.segment_store import SegmentBackend
        scope = getattr(store, 'scope', None)
        _link_record(expected['geometry_id'], expected['source_producer'])
        with SegmentBackend().open(store, SegmentRef.from_wire(expected['segment']), scope=scope) as segment:
            require(segment._owner.value['producer'] == sha256(N._json(expected['source_producer'])).hexdigest(),
                    'v3 reference producer differs from authenticated root')
        return expected
    actual = reference(store, expected['snapshot_key'], geometry_id=expected['geometry_id'],
                       source_producer=expected['source_producer'], budget=budget)
    return actual


def existing_mesh(store, geometry_id, source_producer, *, budget):
    from atlas_tectonics.integration.coupling.spatial_transport import _workspace
    binding = _link_record(geometry_id, source_producer)
    key = sha256(N._json(binding)).hexdigest()
    with _workspace(budget, 65536+8*store.limits.max_manifest_bytes, 'compact-workflow-link-read'):
        row = store.metadata(key)
        if row is None:
            return None
        return verify_reference(store, row['mesh_reference'], budget=budget)


def _token(check, cancel=None):
    def stopped():
        check()
        return False if cancel is None else (cancel.is_set() if hasattr(cancel, 'is_set') else cancel())
    return SimpleNamespace(is_set=stopped)


def persist_mesh(store, view, source_producer, *, budget, check=lambda: None, cancel=None,
                 scope=None, support_source=None):
    from atlas_tectonics._private.codecs.compact_store import _cancel
    token = _token(check, cancel)
    _cancel(token)
    if scope is not None or view.scope is not None:
        from atlas_tectonics._private.codecs.compact_store import CompactMeshStoreV3, V3_SCHEMA
        _link_record(view.geometry_id, source_producer)
        producer_digest = sha256(N._json(source_producer)).hexdigest()
        scope = view.scope if scope is None else scope
        if support_source is None:
            support_source = view._reader.source
        # A view already bound to this immutable source needs only its segment
        # reference, verified through the current resolver's manifest route.
        from atlas_tectonics._private.codecs.segment_store import SegmentBackend
        if view._segment is not None:
            view.identity()
            ref = view._segment.info.ref
            SegmentBackend().verify(store, ref, scope=scope, cancel=token)
            SegmentBackend().verify(store, support_source.binding.partition, scope=scope, cancel=token)
        else:
            adapter = CompactMeshStoreV3(store, scope=scope, support_source=support_source)
            ref = adapter.publish(view, producer=producer_digest, cancel=token)
        return _OwnedReference(dict(schema=V3_SCHEMA, segment=ref.to_wire(),
            geometry_id=view.geometry_id, source_producer=source_producer), budget)
    previous = existing_mesh(store, view.geometry_id, source_producer, budget=budget)
    if previous is not None:
        return previous
    adapter = CompactMeshStore(store, budget=budget)
    # The incoming view may read supports from the readonly original or another
    # store. Persist one at a time under the same content hash before the root.
    for blob in view.support_blobs():
        ident, raw = blob.value
        adapter.support_writer(ident, raw, cancel=token)
        del raw, blob
    owned = view.storage_payload()
    metadata, arrays = owned.value
    key = adapter.publish(metadata, arrays, expected_geometry_id=view.geometry_id,
                          source_producer=source_producer, cancel=token)
    ref = reference(store, key, geometry_id=view.geometry_id, source_producer=source_producer, budget=budget)
    binding = _link_record(view.geometry_id, source_producer)
    link = sha256(N._json(binding)).hexdigest()
    store.put(link, {name: store.reference(key, name) for name in ref['array_bindings']},
              dict(binding=binding, mesh_reference=ref), budget=budget, cancel=token)
    return ref


def convert_mesh(store, record, *, expected_geometry_id, source_producer, budget, check=lambda: None):
    adapter = CompactMeshStore(store, budget=budget)
    token = _token(check)
    metadata, arrays = cast(tuple, pack_mesh(record, support_writer=lambda h, raw: adapter.support_writer(h, raw, cancel=token),
                                budget=budget, check=check))
    view = CompactMesh(metadata, arrays, support_reader=lambda h, size: adapter.support_reader(h, size, cancel=token),
                       expected_geometry_id=expected_geometry_id, budget=budget, check=check)
    ref = persist_mesh(store, view, source_producer, budget=budget, check=check)
    return adapter.open(ref['snapshot_key'], expected_geometry_id=expected_geometry_id, cancel=token), ref


def state_record(state):
    return state if type(getattr(state, '_snapshot', None)) is X.IndexedSpatialSnapshot else state.record()


def logical_record(state):
    return X.logical_record(state)


def mesh_partition(mesh, budget):
    owned = X.mesh_header(mesh, budget)
    return owned.value.get('partition_id')


@contextmanager
def records(cls, state, exchange, budget, *, store, source_producer, persist=True, cancel=None,
            aliases=None, scope=None, support_source=None):
    if getattr(store, 'scope', None) is not None:
        from atlas_tectonics._private.integration.geometry import spatial_records_patch as records_v3
        with records_v3.records(cls, state, exchange, budget, store=store,
                source_producer=source_producer, persist=persist, cancel=cancel,
                aliases=aliases, scope=scope, support_source=support_source) as result:
            yield result
        return
    from atlas_tectonics.integration.coupling.spatial_transport import _workspace
    if scope is None:
        scope = getattr(store, 'scope', None)
    owned = state.indexed_record()
    view = owned.value['thermal_mesh']
    aliases = view.scope is None if aliases is None else aliases
    ref = (persist_mesh(store, view, source_producer, budget=budget, cancel=cancel,
                        scope=scope, support_source=support_source) if persist or view.scope is not None else
           existing_mesh(store, view.geometry_id, source_producer, budget=budget))
    envelope = state.compact_record(mesh_reference=ref)
    rows = dict(state=envelope.value)
    if exchange is not None:
        rows.update(exchange={k: v for k, v in exchange.items() if k not in ('spatial_graph', 'transport', 'joined_heat')},
                    graph=exchange['spatial_graph'], transport=exchange['transport'], heat=exchange['joined_heat'])
    with _workspace(budget, 65536+3*sum(N._width(row) for row in rows.values()), 'compact-workflow-encode'):
        arrays, refs = {}, {'compact_mesh': ref}
        for kind, row in rows.items():
            raw = N._json(row)
            name = 'spatial-record:'+kind
            arrays[name] = np.frombuffer(raw, dtype=np.uint8)
            refs[kind] = dict(array=name, bytes=len(raw), sha256=sha256(raw).hexdigest())
        if aliases:
            arrays.update({PREFIX+name: store.reference(ref['snapshot_key'], name) for name in ref['array_bindings']})
        a, b = cls._spatial_headers(owned.value, exchange, refs)
        yield a, b, arrays


@contextmanager
def restore_records(cls, state_header, exchange_header, arrays, budget, *, store,
                    scope=None, support_source=None):
    if getattr(store, 'scope', None) is not None:
        from atlas_tectonics._private.integration.geometry import spatial_records_patch as records_v3
        with records_v3.restore_records(cls, state_header, exchange_header, arrays, budget,
                store=store, scope=scope, support_source=support_source) as result:
            yield result
        return
    from atlas_tectonics.integration.coupling.spatial_transport import _workspace
    expected = state_header['compact_mesh']
    scope = getattr(store, 'scope', None) if scope is None else scope
    if expected['schema'] == 'atlas.compact-mesh-store.v3':
        from atlas_tectonics._private.codecs.compact_contracts import SegmentRef
        from atlas_tectonics._private.codecs.compact_store import CompactMeshStoreV3
        view = CompactMeshStoreV3(store, scope=scope, support_source=support_source).open(
            SegmentRef.from_wire(expected['segment']), expected_geometry_id=expected['geometry_id'])
    else:
        view = CompactMeshStore(store, budget=budget).open(expected['snapshot_key'],
                                                         expected_geometry_id=expected['geometry_id'])
    refs = dict(state_header['record_blobs'])
    if exchange_header is not None:
        other = exchange_header['record_blobs']
        refs.update(other)
    kinds = {'state'} | (set() if exchange_header is None else {'exchange', 'graph', 'transport', 'heat'})
    for name, values in arrays.items():
        require(type(values) is np.ndarray and values.dtype == np.dtype('uint8') and values.ndim == 1,
                'canonical spatial byte arrays required')
    size = 65536+sum(_decode_charge(v)+2*v.nbytes for v in arrays.values())
    with _workspace(budget, size, 'compact-workflow-decode'):
        rows = {}
        for kind in sorted(kinds):
            name = 'spatial-record:'+kind
            raw, _ = arrays[name].tobytes(), refs[kind]
            row = json.loads(raw)
            rows[kind] = row
        envelope = rows['state']
        state = dict(state_id=envelope['state_id'], **envelope['state'], thermal_mesh=view)
        exchange = None if exchange_header is None else dict(rows['exchange'], spatial_graph=rows['graph'],
                                                             transport=rows['transport'], joined_heat=rows['heat'])
        refs['compact_mesh'] = expected
        yield state, exchange


def workflow_arrays(store, key, *, budget):
    """Read non-geometry operands; geometry aliases authenticate, not duplicate."""
    from atlas_tectonics.integration.coupling.spatial_transport import _workspace
    with _workspace(budget, 65536+8*store.limits.max_manifest_bytes, 'compact-workflow-manifest'):
        with store._read_scope(budget=budget):
            manifest = store._manifest(key)
            if manifest is None:
                return None
            names = [name for name in manifest['arrays'] if name.startswith(PREFIX)]
            if not names:
                return store.get(key, budget=budget)
            selected = {n: row for n, row in manifest['arrays'].items() if not n.startswith(PREFIX)}
            total = sum(math.prod(r['shape'])*np.dtype(r['dtype']).itemsize for r in selected.values())
            allocation = N._Allocation(budget, total+65536+1024*len(selected), category='compact-workflow-arrays')
            result = {}
            for name, row in selected.items():
                dtype = np.dtype(row['dtype'])
                size = math.prod(row['shape'])*dtype.itemsize
                with _workspace(budget, 2*size+65536, 'compact-workflow-array-read'):
                    buffer, count = bytearray(size), 0
                    for offset, values in store.iter_chunks(key, name, budget=budget):
                        raw = memoryview(values).cast('B')
                        buffer[count:count+len(raw)] = raw
                        count += len(raw)
                    result[name] = np.frombuffer(N._RecordBytes(buffer, allocation), dtype=dtype).reshape(row['shape'])
            return result


