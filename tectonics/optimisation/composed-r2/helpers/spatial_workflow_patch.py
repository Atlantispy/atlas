"""ArrayStore-bound compact spatial workflow publication and cold loading."""
from contextlib import contextmanager
from hashlib import sha256
import json
import math
from types import SimpleNamespace

import numpy as np

import native_transfer as N
import spatial_indexed_patch as X
from compact_store import CompactMeshStore, descriptor_digest
from mesh_tables import CompactMesh, _decode_charge, pack_mesh


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
    N._digest(geometry_id, 'original logical geometry')
    require(type(source_producer) is dict and bool(source_producer), 'actual producer binding required')
    return dict(schema=LINK_SCHEMA, geometry_id=geometry_id, source_producer=source_producer)


def reference(store, key, *, geometry_id, source_producer, budget):
    """Construct references only from the authenticated actual current store.

    Each array is bound by its ArrayReference descriptor digest (exact dtype,
    shape and chunk IDs), not a copy of its chunk list: the reference is carried
    in link, migrated-root and successor metadata under the 1 MiB manifest limit.
    """
    from atlas_tectonics.integration_spatial_transport import _workspace
    with _workspace(budget, 65536+8*store.limits.max_manifest_bytes, 'compact-workflow-reference-read'):
        adapter = CompactMeshStore(store, budget=budget)
        manifest, record = adapter._root(key)
        require(record['geometry_id'] == geometry_id and record['source_producer'] == source_producer,
                'compact mesh original geometry or producer binding differs')
        bindings = {name: descriptor_digest(row) for name, row in manifest['arrays'].items()}
        return _OwnedReference(dict(schema=record['schema'], snapshot_key=key, geometry_id=geometry_id,
                    source_producer=record['source_producer'], array_bindings=bindings), budget)


def verify_reference(store, expected, *, budget):
    require(isinstance(expected, dict), 'complete compact mesh reference required')
    X._reference(expected, expected.get('geometry_id'))
    if expected['schema'] == 'atlas.compact-mesh-store.v3':
        from compact_contracts import SegmentRef
        from segment_store import SegmentBackend
        scope = getattr(store, 'scope', None)
        require(scope is not None and scope.run_budget is budget,
                'v3 reference verification needs its retained resolver')
        _link_record(expected['geometry_id'], expected['source_producer'])
        with SegmentBackend().open(store, SegmentRef.from_wire(expected['segment']), scope=scope) as segment:
            require(segment._owner.value['producer'] == sha256(N._json(expected['source_producer'])).hexdigest(),
                    'v3 reference producer differs from authenticated root')
        return expected
    actual = reference(store, expected['snapshot_key'], geometry_id=expected['geometry_id'],
                       source_producer=expected['source_producer'], budget=budget)
    require(actual == expected, 'compact mesh current immutable store reference differs')
    return actual


def existing_mesh(store, geometry_id, source_producer, *, budget):
    from atlas_tectonics.integration_spatial_transport import _workspace
    binding = _link_record(geometry_id, source_producer)
    key = sha256(N._json(binding)).hexdigest()
    with _workspace(budget, 65536+8*store.limits.max_manifest_bytes, 'compact-workflow-link-read'):
        row = store.metadata(key)
        if row is None:
            return None
        require(type(row) is dict and set(row) == {'binding', 'mesh_reference'} and row['binding'] == binding,
                'immutable compact mesh lookup binding differs')
        return verify_reference(store, row['mesh_reference'], budget=budget)


def _token(check, cancel=None):
    def stopped():
        check()
        return False if cancel is None else (cancel.is_set() if hasattr(cancel, 'is_set') else cancel())
    return SimpleNamespace(is_set=stopped)


def persist_mesh(store, view, source_producer, *, budget, check=lambda: None, cancel=None,
                 scope=None, support_source=None):
    from compact_store import _cancel
    token = _token(check, cancel)
    _cancel(token)
    require(type(view) is CompactMesh and view.budget is budget, 'actual shared-budget compact geometry required')
    if scope is not None or view.scope is not None:
        from compact_store import CompactMeshStoreV3, V3_SCHEMA
        _link_record(view.geometry_id, source_producer)
        producer_digest = sha256(N._json(source_producer)).hexdigest()
        scope = view.scope if scope is None else scope
        require(scope is not None and scope.run_budget is budget and store.scope is scope,
                'v3 publication requires the actual retained interval scope')
        if support_source is None:
            require(view._segment is not None, 'fresh v3 publication requires its explicit support source')
            support_source = view._reader.source
        # A view already bound to this immutable source needs only its segment
        # reference, verified through the current resolver's manifest route.
        from segment_store import SegmentBackend
        if view._segment is not None:
            from support_source import SupportSource
            require(type(support_source) is SupportSource and support_source.scope is scope and
                    support_source.binding.to_wire() == view._reader.source.binding.to_wire(),
                    'v3 reference publication source differs')
            view.identity()
            require(view._segment._owner.value['producer'] == producer_digest,
                    'v3 publication producer differs from authenticated root')
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
    metadata, arrays = pack_mesh(record, support_writer=lambda h, raw: adapter.support_writer(h, raw, cancel=token),
                                budget=budget, check=check)
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
        import spatial_records_patch as records_v3
        with records_v3.records(cls, state, exchange, budget, store=store,
                source_producer=source_producer, persist=persist, cancel=cancel,
                aliases=aliases, scope=scope, support_source=support_source) as result:
            yield result
        return
    from atlas_tectonics.integration_spatial_transport import _workspace
    if scope is None:
        scope = getattr(store, 'scope', None)
    require(store is not None and (getattr(store, '_budget', None) is budget or
            scope is not None and getattr(store, 'scope', None) is scope and scope.run_budget is budget),
            'compact workflow requires its actual working store')
    owned = state.indexed_record()
    view = owned.value['thermal_mesh']
    aliases = view.scope is None if aliases is None else aliases
    ref = (persist_mesh(store, view, source_producer, budget=budget, cancel=cancel,
                        scope=scope, support_source=support_source) if persist or view.scope is not None else
           existing_mesh(store, view.geometry_id, source_producer, budget=budget))
    require(ref is not None, 'compact mesh has not been published in this working store')
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
            require(ref['schema'] != 'atlas.compact-mesh-store.v3',
                    'v3 successors are reference-only; legacy aliases require the explicit v2 route')
            arrays.update({PREFIX+name: store.reference(ref['snapshot_key'], name) for name in ref['array_bindings']})
        a, b = cls._spatial_headers(owned.value, exchange, refs)
        yield a, b, arrays


@contextmanager
def restore_records(cls, state_header, exchange_header, arrays, budget, *, store,
                    scope=None, support_source=None):
    if getattr(store, 'scope', None) is not None:
        import spatial_records_patch as records_v3
        with records_v3.restore_records(cls, state_header, exchange_header, arrays, budget,
                store=store, scope=scope, support_source=support_source) as result:
            yield result
        return
    from atlas_tectonics.integration_spatial_transport import _workspace
    expected = state_header['compact_mesh']
    scope = getattr(store, 'scope', None) if scope is None else scope
    require(store is not None and (getattr(store, '_budget', None) is budget or
            scope is not None and getattr(store, 'scope', None) is scope and scope.run_budget is budget),
            'compact restore requires actual working store')
    verify_reference(store, expected, budget=budget)
    if expected['schema'] == 'atlas.compact-mesh-store.v3':
        from compact_contracts import SegmentRef
        from compact_store import CompactMeshStoreV3
        view = CompactMeshStoreV3(store, scope=scope, support_source=support_source).open(
            SegmentRef.from_wire(expected['segment']), expected_geometry_id=expected['geometry_id'])
    else:
        view = CompactMeshStore(store, budget=budget).open(expected['snapshot_key'],
                                                         expected_geometry_id=expected['geometry_id'])
    refs = dict(state_header['record_blobs'])
    if exchange_header is not None:
        other = exchange_header['record_blobs']
        require(not set(refs) & set(other), 'duplicate compact workflow record reference')
        refs.update(other)
    kinds = {'state'} | (set() if exchange_header is None else {'exchange', 'graph', 'transport', 'heat'})
    require(set(refs) == kinds and set(arrays) == {'spatial-record:'+k for k in kinds},
            'complete compact spatial record inventory required')
    for name, values in arrays.items():
        require(type(values) is np.ndarray and values.dtype == np.dtype('uint8') and values.ndim == 1,
                'canonical spatial byte arrays required')
    size = 65536+sum(_decode_charge(v)+2*v.nbytes for v in arrays.values())
    with _workspace(budget, size, 'compact-workflow-decode'):
        rows = {}
        for kind in sorted(kinds):
            name = 'spatial-record:'+kind
            raw, bound = arrays[name].tobytes(), refs[kind]
            require(set(bound) == {'array', 'bytes', 'sha256'} and bound['array'] == name and
                    type(bound['bytes']) is int and len(raw) == bound['bytes'] and
                    sha256(raw).hexdigest() == bound['sha256'], 'compact spatial record byte binding differs')
            row = json.loads(raw)
            require(type(row) is dict and N._json(row) == raw, 'canonical compact spatial record required')
            rows[kind] = row
        envelope = rows['state']
        require(set(envelope) == {'schema', 'state_id', 'state', 'mesh_reference', 'logical_metadata'} and
                envelope['schema'] == X.SCHEMA and envelope['mesh_reference'] == expected and
                'thermal_mesh' not in envelope['state'], 'compact spatial envelope differs')
        state = dict(state_id=envelope['state_id'], **envelope['state'], thermal_mesh=view)
        import spatial_transfer as S
        require(S._stream_stats({k: v for k, v in state.items() if k != 'state_id'})[0] == envelope['logical_metadata'],
                'compact spatial original logical metadata differs')
        exchange = None if exchange_header is None else dict(rows['exchange'], spatial_graph=rows['graph'],
                                                             transport=rows['transport'], joined_heat=rows['heat'])
        refs['compact_mesh'] = expected
        require(cls._spatial_headers(state, exchange, refs) == (state_header, exchange_header),
                'compact spatial lineage differs from full logical state')
        yield state, exchange


def workflow_arrays(store, key, *, budget):
    """Read non-geometry operands; geometry aliases authenticate, not duplicate."""
    from atlas_tectonics.integration_spatial_transport import _workspace
    with _workspace(budget, 65536+8*store.limits.max_manifest_bytes, 'compact-workflow-manifest'):
        with store._read_scope(budget=budget):
            manifest = store._manifest(key)
            if manifest is None:
                return None
            names = [name for name in manifest['arrays'] if name.startswith(PREFIX)]
            if not names:
                return store.get(key, budget=budget)
            ref = manifest['metadata'].get('exterior_state', {}).get('compact_mesh')
            verify_reference(store, ref, budget=budget)
            require(set(names) == {PREFIX+n for n in ref['array_bindings']} and
                    all(descriptor_digest(manifest['arrays'][PREFIX+n]) == digest
                        for n, digest in ref['array_bindings'].items()),
                    'workflow compact mesh aliases differ from bound immutable chunks')
            selected = {n: row for n, row in manifest['arrays'].items() if not n.startswith(PREFIX)}
            total = sum(math.prod(r['shape'])*np.dtype(r['dtype']).itemsize for r in selected.values())
            require(total <= store.limits.max_array_bytes, 'workflow operands exceed read allowance')
            allocation = N._Allocation(budget, total+65536+1024*len(selected), category='compact-workflow-arrays')
            result = {}
            for name, row in selected.items():
                dtype = np.dtype(row['dtype'])
                size = math.prod(row['shape'])*dtype.itemsize
                with _workspace(budget, 2*size+65536, 'compact-workflow-array-read'):
                    buffer, count = bytearray(size), 0
                    for offset, values in store.iter_chunks(key, name, budget=budget):
                        raw = memoryview(values).cast('B')
                        require(offset*dtype.itemsize == count and count+len(raw) <= size,
                                'workflow operand chunk coverage differs')
                        buffer[count:count+len(raw)] = raw
                        count += len(raw)
                    require(count == size, 'workflow operand is incomplete')
                    result[name] = np.frombuffer(N._RecordBytes(buffer, allocation), dtype=dtype).reshape(row['shape'])
            return result


def transform(source):
    """Disjoint spatial seams, after nonzero_cursor_source; no frozen edits."""
    require(type(source) is str and 'def open_migrated(' in source and 'import spatial_workflow_patch as' not in source,
            'reviewed migrated workflow source required exactly once')
    source = source.replace('import json\n', 'import json\nimport spatial_workflow_patch as _COMPACT_SPATIAL\n', 1)
    require('import spatial_workflow_patch as _COMPACT_SPATIAL' in source, 'workflow import seam absent')
    changes = (
        ("        state_header['record_blobs'] = {k: refs[k] for k in ('state', 'mesh')}",
         "        state_header['record_blobs'] = {k: refs[k] for k in (('state',) if 'compact_mesh' in refs else ('state', 'mesh'))}\n"
         "        if 'compact_mesh' in refs:\n            state_header['compact_mesh'] = refs['compact_mesh']"),
        ('    def _spatial_records(cls, state, exchange, budget):\n',
         '    def _spatial_records(cls, state, exchange, budget, *, store=None, source_producer=None, persist_mesh=True, cancel=None):\n'
         "        if type(getattr(state, '_snapshot', None)) is _COMPACT_SPATIAL.X.IndexedSpatialSnapshot:\n"
         '            with _COMPACT_SPATIAL.records(cls, state, exchange, budget, store=store,\n'
         '                    source_producer=source_producer, persist=persist_mesh, cancel=cancel) as result:\n                yield result\n            return\n'),
        ('    def _spatial_restore_records(cls, state_header, exchange_header, arrays, budget):\n',
         '    def _spatial_restore_records(cls, state_header, exchange_header, arrays, budget, *, store=None):\n'
         "        if 'compact_mesh' in state_header:\n"
         '            with _COMPACT_SPATIAL.restore_records(cls, state_header, exchange_header, arrays, budget, store=store) as result:\n'
         '                yield result\n            return\n'),
        ("        arrays = self._store.get(previous['key'], budget=self._budget)",
         "        arrays = _COMPACT_SPATIAL.workflow_arrays(self._store, previous['key'], budget=self._budget)"),
        ("                payload = store.get(root['key'], budget=budget)",
         "                payload = _COMPACT_SPATIAL.workflow_arrays(store, root['key'], budget=budget)"),
        ('record_arrays, self._budget) as (saved, exchange):',
         'record_arrays, self._budget, store=self._store) as (saved, exchange):'),
        ("blobs, budget) as (saved, _):", "blobs, budget, store=store) as (saved, _):"),
        ("saved['thermal_mesh'].get('partition_id')", "_COMPACT_SPATIAL.mesh_partition(saved['thermal_mesh'], self._budget)"),
        ("record = exterior_state.record()", "record = _COMPACT_SPATIAL.logical_record(exterior_state)"),
        ("self._exterior_state.record()", "_COMPACT_SPATIAL.logical_record(self._exterior_state)"),
        ("exterior_owner.initial_state.record()['thermal_mesh'].get('physical_geometry_family')",
         "_COMPACT_SPATIAL.X.mesh_header(_COMPACT_SPATIAL.logical_record(exterior_owner.initial_state)['thermal_mesh'], exterior_owner._budget).value.get('physical_geometry_family')"),
        ("exterior_advance.state.record()", "_COMPACT_SPATIAL.state_record(exterior_advance.state)"),
        ("exterior.record()", "_COMPACT_SPATIAL.state_record(exterior)"),
        ("exterior_owner.initial_state.record(), None, budget)",
         "_COMPACT_SPATIAL.state_record(exterior_owner.initial_state), None, budget, store=store, source_producer=_COMPACT_SPATIAL.producer(collar), persist_mesh=False)"),
        ("cls._spatial_records(_COMPACT_SPATIAL.state_record(exterior), None, budget)",
         "cls._spatial_records(_COMPACT_SPATIAL.state_record(exterior), None, budget, store=store, source_producer=_COMPACT_SPATIAL.producer(collar))"),
        ("row['exterior_state'], row['exterior_advance'], self._budget))",
         "row['exterior_state'], row['exterior_advance'], self._budget, store=self._store, source_producer=_COMPACT_SPATIAL.producer(self._collar), cancel=cancel))"),
    )
    for old, new in changes:
        count = source.count(old)
        require(count > 0, 'compact workflow source seam absent: '+old[:80])
        source = source.replace(old, new)
    return source


def transform_v3(source):
    """Additive live/header and reference-only successor seam after v2 transforms."""
    anchor = '        geometry, thermal = bounds.record(), mesh.record()'
    require(type(source) is str and source.count(anchor) == 1,
            'live compact mesh header seam missing or ambiguous')
    source = source.replace(anchor,
        '        _thermal_header = _COMPACT_SPATIAL.X.mesh_header(mesh, self._budget)\n'
        '        geometry, thermal = bounds.record(), _thermal_header.value', 1)
    changes = (
        ('persist_mesh=True, cancel=None):\n', 'persist_mesh=True, cancel=None, aliases=False):\n'),
        ('source_producer=source_producer, persist=persist_mesh, cancel=cancel) as result:',
         'source_producer=source_producer, persist=persist_mesh, cancel=cancel, aliases=aliases) as result:'),
        ('persist_mesh=False)', 'persist_mesh=False, aliases=True)'),
    )
    for old, new in changes:
        require(source.count(old) == 1, 'v3 spatial source seam missing or ambiguous: '+old)
        source = source.replace(old, new, 1)
    return source
