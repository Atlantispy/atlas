"""Indexed spatial state ownership; exact logical IDs, explicit compact wire.

Source transforms retain the native scientific gates. A CompactMesh is storage
authentication, not physical acceptance. The state owns the exact compact view
and small immutable stock metadata, never an encoded/decoded complete mesh.
"""
from dataclasses import dataclass, field as dataclass_field
from hashlib import sha256
import json
from typing import Callable, cast

import numpy as np


SCHEMA = 'atlas.compact-spatial-state.r1'
REFERENCE_SCHEMA = 'atlas.compact-mesh-store.v2'  # compact_store.SCHEMA (packed support blobs)
CELL_ROW_BYTES = 4 << 20


class IndexedSpatialRefused(ValueError):
    pass


def is_compact(value):
    # Lazy import keeps the ordinary transfer route independent of this codec.
    from atlas_tectonics._private.codecs.mesh_tables import CompactMesh
    return type(value) is CompactMesh and getattr(value, '_sealed', False)


def _view(value, budget):
    return value


def is_compact_cells(value):
    from atlas_tectonics._private.codecs.record_views import RecordRef
    return isinstance(value, RecordRef)


def cell_count(value, budget):
    return value.size if is_compact_cells(value) else len(value)


def iter_state_cells(value, budget):
    """Native rows with paid escaping ownership; never export the whole array."""
    if not is_compact_cells(value):
        yield from value
        return
    from atlas_tectonics._private.integration import native_transfer as N
    cells = value
    with cells.iter_rows(max_rows=1, max_owned_bytes=CELL_ROW_BYTES) as blocks:
        for block in blocks:
            with block:
                for row in block.value:
                    held = row.export(max_logical_bytes=CELL_ROW_BYTES,
                                      max_owned_bytes=CELL_ROW_BYTES)
                    # The wrapper keeps the decoded row's owner even if a native
                    # caller retains the last row or an exceptional traceback.
                    allocation = N._Allocation(budget, 4096+128*len(held.value),
                                               category='indexed-spatial-cell-row')
                    yield _LogicalRecord(held.value, (held, allocation))
                    del held, allocation
                    row.close()


def iter_logical_json(value):
    """Exact ordinary bytes, streaming sealed meshes and owned record children."""
    if is_compact(value):
        yield from value.iter_legacy_json()
    elif is_compact_cells(value):
        with value.iter_json() as blocks:
            for block in blocks:
                with block:
                    yield block.value
    elif type(value) is dict:
        yield b'{'
        for at, key in enumerate(sorted(value)):
            if at:
                yield b','
            yield json.dumps(key, ensure_ascii=True).encode('ascii')+b':'
            yield from iter_logical_json(value[key])
        yield b'}'
    elif type(value) in (tuple, list):
        yield b'['
        for at, item in enumerate(value):
            if at:
                yield b','
            yield from iter_logical_json(item)
        yield b']'
    else:
        for part in json.JSONEncoder(sort_keys=True, separators=(',', ':'), allow_nan=False).iterencode(value):
            yield part.encode('ascii')


def mesh_header(mesh, budget):
    from atlas_tectonics._private.codecs.mesh_tables import OwnedRow
    if type(mesh) is dict:
        return OwnedRow(mesh, None)
    if getattr(mesh, '_compact', None) is not None:
        mesh = mesh._compact
    return mesh.header()


def exterior_ids(mesh, budget):
    if type(mesh) is dict:
        yield from (r['logical_cell_id'] for r in mesh['cells'] if r['kind'] == 'exterior')
        return
    view = mesh
    for index in range(view.cell_count):
        row = view.cell(index)
        if row.value['kind'] == 'exterior':
            yield row.value['logical_cell_id']
        del row


def _small_body(body):
    return {k: v for k, v in body.items() if k != 'thermal_mesh' and
            not (k == 'cells' and is_compact_cells(v))}


def retained_metadata_nbytes(body):
    from atlas_tectonics._private.integration.geometry import spatial_transfer as S
    if is_compact(body.get('thermal_mesh')):
        return len(S.N._json(_small_body(body)))
    return S._stream_stats(body)[0]['nbytes']


@dataclass(frozen=True, slots=True)
class IndexedSpatialSnapshot:
    """Native snapshot protocol, with separate physical and logical metadata."""
    _metadata: bytes
    _fields: tuple
    result_id: str
    _mesh: object
    _logical_metadata: tuple
    time_s: float
    _budget: object
    _cells: object = None
    _mesh_borrow: object = None
    # Process-local seal of the one complete identity check that passed in THIS
    # process (plan section 7): (identity, binding). Never persisted, never
    # trusted across processes, excluded from equality, and never copied by
    # dataclasses.replace (init=False): a seal belongs to the object checked.
    _verified: object = dataclass_field(default=None, init=False, compare=False, repr=False)

    @property
    def nbytes(self):
        return len(self._metadata)+sum(len(raw) for _, _, raw in self._fields)

    @property
    def array_names(self):
        return tuple(name for name, _, _ in self._fields)

    def array(self, name):
        for field, shape, raw in self._fields:
            if field == name:
                return np.frombuffer(raw, dtype=np.float64).reshape(shape)
        raise KeyError(name)

    def descriptor(self):
        raise IndexedSpatialRefused('indexed spatial snapshot requires explicit indexed_record or compact_record')


class _LogicalRecord(dict):
    """Internal native borrowed-record shape with an escaping decode owner."""
    def __init__(self, value, allocation):
        super().__init__(value)
        object.__setattr__(self, '_allocation', allocation)

    def __setattr__(self, name, value):
        raise IndexedSpatialRefused('immutable decoded-record ownership')


def logical_record(state):
    from atlas_tectonics._private.integration import native_transfer as N
    from atlas_tectonics._private.codecs.mesh_tables import _decode_charge
    snapshot = state._snapshot
    if type(snapshot) is not IndexedSpatialSnapshot:
        return state.record()
    allocation = N._Allocation(state._budget, _decode_charge(snapshot._metadata)+65536,
                               category='indexed-spatial-record')
    value = dict(state_id=state.state_id, **json.loads(snapshot._metadata),
                 thermal_mesh=snapshot._mesh)
    if snapshot._cells is not None:
        value['cells'] = snapshot._cells.borrow()
    return _LogicalRecord(value, allocation)


def indexed_record(state):
    from atlas_tectonics._private.codecs.mesh_tables import OwnedRow
    result = logical_record(state)
    # The plain dict API is explicit and borrowed; retain this OwnedRow. The
    # internal _bound adapter retains its allocation on the dict itself.
    return OwnedRow(dict(result), result._allocation)


def retained_snapshot(body, arrays, identity, metadata, allocation, budget, *, compare=True):
    from atlas_tectonics._private.integration import native_transfer as N
    from atlas_tectonics._private.integration.geometry import spatial_transfer as S
    view = body.get('thermal_mesh')
    cells = (body['cells'].borrow()
             if is_compact_cells(body.get('cells')) else None)
    small = _small_body(body)
    scratch = N._Allocation(budget, 65536+3*N._width(small)+
        max((a.nbytes for a in arrays.values()), default=0), category='indexed-spatial-encoding')
    encoded = N._RecordBytes(N._json(small), allocation)
    fields = tuple((name, tuple(array.shape), N._RecordBytes(array.tobytes(order='C'), allocation))
                   for name, array in sorted(arrays.items()))
    # compare=False only from issue: it made identity and metadata from this body and these arrays just before
    if compare and (S._snapshot_id(body, S._bindings(arrays)) != identity
                    or S._stream_stats(body)[0] != metadata):
        raise IndexedSpatialRefused('indexed logical snapshot binding differs')
    result = IndexedSpatialSnapshot(encoded, fields, identity, view,
        (metadata['sha256'], metadata['nbytes']), body['time_s'], budget, cells,
        None if view._owner is None else view._owner.retain())
    _ = scratch
    return result


def _checked_identity(snapshot):
    """Recompute from owned immutable bytes and actual streamed mesh content."""
    from atlas_tectonics._private.integration import native_transfer as N
    from atlas_tectonics._private.codecs.mesh_tables import _decode_charge
    view = snapshot._mesh
    encoded, fields = snapshot._metadata, snapshot._fields
    scratch = N._Allocation(snapshot._budget, _decode_charge(encoded)+65536+2048*len(fields),
                            category='indexed-spatial-identity')
    body = json.loads(encoded)
    if snapshot._cells is not None:
        body['cells'] = snapshot._cells
    bindings, _ = {}, None
    for entry in fields:
        name, shape, raw = entry
        bindings[name] = dict(shape=shape, sha256=sha256(raw).hexdigest())
    body['thermal_mesh'] = view
    identity, metadata, size = sha256(), sha256(), 0
    identity.update(b'{"arrays":'+N._json(bindings)+b',"metadata":')
    for part in iter_logical_json(body):
        identity.update(part)
        metadata.update(part)
        size += len(part)
    identity.update(b'}')
    stats = dict(sha256=metadata.hexdigest(), nbytes=size)
    _ = scratch
    return identity.hexdigest(), stats


def _seal_binding(snapshot):
    """Everything a complete identity check bound, re-checked without streaming.

    The owned body and field bytes are rehashed; the thermal mesh and the cell
    record contribute their own process-local seals, which re-check liveness and
    file freshness. A cell view below its record root has no O(1) identity, so
    such a snapshot is never sealed. None means: verify in full (which refuses
    with its own message, e.g. for bytes that lost their owned allocation).
    """
    from atlas_tectonics._private.integration import native_transfer as N
    encoded, fields = snapshot._metadata, snapshot._fields
    if (type(encoded) is not N._RecordBytes or type(encoded._allocation) is not N._Allocation or
            encoded._allocation._guard is None or type(fields) is not tuple or
            any(type(entry) is not tuple or len(entry) != 3 or type(entry[2]) is not N._RecordBytes or
                entry[2]._allocation is not encoded._allocation for entry in fields)):
        return None
    view = snapshot._mesh
    cells = None
    if snapshot._cells is not None:
        ref = snapshot._cells
        if ref.index != ref._view._root or ref._fields is not None:
            return None
        cells = ref._view.identity()
    hashed = tuple((name, shape, sha256(raw).hexdigest()) for name, shape, raw in fields)
    return (sha256(encoded).hexdigest(), hashed, view.identity(), cells,
            snapshot.result_id, snapshot._logical_metadata, snapshot.time_s)


def snapshot_identity(snapshot, *, legacy_identity=None):
    """Private issuer seam: full logical identity, never compact-wire identity.

    Every heat _verify_call re-derives the parent state's identity, which streams
    the whole state and its thermal mesh (audit X2, 16 Oct 2026). After one
    complete check passes in this process, the snapshot keeps that identity with
    its binding, and a later call re-checks only the binding (plan section 7).
    """
    if type(snapshot) is not IndexedSpatialSnapshot:
        return cast(Callable[[object], object], legacy_identity)(snapshot)
    sealed = snapshot._verified
    if sealed is not None and _seal_binding(snapshot) == sealed[1]:
        return sealed[0]
    identity = _checked_identity(snapshot)[0]
    binding = _seal_binding(snapshot)
    if binding is not None:
        object.__setattr__(snapshot, '_verified', (identity, binding))
    return identity


def snapshot_metadata_matches(snapshot, binding):
    return _checked_identity(snapshot)[1] == binding


def issue(owner, body):
    """Called only by the actual native owner's existing issue boundary."""
    from atlas_tectonics._private.integration import native_transfer as N
    from atlas_tectonics._private.integration.geometry import spatial_transfer as S
    from atlas_tectonics.integration.coupling.spatial_owner import SpatialExteriorState, _project, _q
    view = body.get('thermal_mesh')
    if not is_compact_cells(body.get('cells')) and hasattr(owner, '_record_scope'):
        from atlas_tectonics._private.integration.geometry.exchange_record_patch import required_scope
        from atlas_tectonics._private.codecs.record_tables import RecordCodec
        scope = required_scope(owner)
        cell_wrapper = N._Allocation(owner._budget, 4096+128*len(body),
                                     category='indexed-spatial-cell-wrapper')
        packed_cells = RecordCodec().pack_record(body['cells'],
            record_schema='atlas.spatial-state-cells.v1', scope=scope,
            check=lambda: None)
        body = dict(body, cells=packed_cells.root())
        _ = cell_wrapper
    small = _small_body(body)
    count = cell_count(body['cells'], owner._budget)
    scratch = N._Allocation(owner._budget, 65536+3*N._width(small)+
        32*count*(len(owner._names)+1), category='indexed-spatial-issue')
    if is_compact_cells(body['cells']):
        fields = {k: np.empty(count, dtype=np.float64) for k in (*owner._names, 'volume_m3')}
        for at, row in enumerate(iter_state_cells(body['cells'], owner._budget)):
            for name in owner._names:
                fields[name][at] = _project(_q(row['exact'][name]))
            fields['volume_m3'][at] = _project(_q(row['volume_m3']))
    else:
        fields = {k: np.asarray([_project(_q(r['exact'][k])) for r in body['cells']]) for k in owner._names}
        fields['volume_m3'] = np.asarray([_project(_q(r['volume_m3'])) for r in body['cells']])
    arrays = {k: dict(shape=v['shape'], sha256=v['sha256']) for k, v in S._bindings(fields).items()}
    digest, stream, size = sha256(b'{"arrays":'+N._json(arrays)+b',"metadata":'), sha256(), 0
    for part in iter_logical_json(body):  # one pass gives both values, as _checked_identity (:276-283)
        digest.update(part)
        stream.update(part)
        size += len(part)
    digest.update(b'}')
    metadata, identity = dict(sha256=stream.hexdigest(), nbytes=size), digest.hexdigest()
    allocation = N._Allocation(owner._budget, 8192+retained_metadata_nbytes(body)+
        sum(a.nbytes for a in fields.values())+1024*len(fields), category='indexed-spatial-state')
    result = object.__new__(SpatialExteriorState)
    object.__setattr__(result, '_snapshot', retained_snapshot(body, fields, identity, metadata, allocation,
                                                              owner._budget, compare=False))
    object.__setattr__(result, '_budget', owner._budget)
    _ = scratch, view
    return result


def validate_projected_payload(owner, body, arrays, state_id):
    """Original restore tail, with compact rows and the same exact projection."""
    from atlas_tectonics._private.integration.geometry import spatial_transfer as S
    if not is_compact_cells(body.get('cells')):
        return S.validate_projected_payload(owner, body, arrays, state_id)
    bindings = S._bindings(arrays)
    return dict(state_id=state_id, metadata=S._stream_stats(body)[0], arrays=bindings)


def _reference(reference, geometry_id):
    from atlas_tectonics._private.integration import native_transfer as N
    if isinstance(reference, dict) and reference.get('schema') == 'atlas.compact-mesh-store.v3':
        return reference
    N._digest(reference['snapshot_key'], 'compact mesh snapshot')
    N._digest(geometry_id, 'logical thermal geometry')
    return reference


def compact_record(state, *, mesh_reference):
    """Explicit persistable envelope, not a legacy full-mesh state record.

    Publication must bind the named actual CompactMeshStore root atomically.
    This function validates spelling and logical identity, not store authority.
    """
    from atlas_tectonics._private.integration import native_transfer as N
    from atlas_tectonics._private.codecs.mesh_tables import OwnedRow, _decode_charge
    snapshot = state._snapshot
    reference = _reference(mesh_reference, snapshot._mesh.geometry_id)
    allocation = N._Allocation(state._budget, _decode_charge(snapshot._metadata)+
                               4*N._width(dict(reference))+65536,
                               category='indexed-spatial-record')
    value = dict(schema=SCHEMA, state_id=state.state_id, state=json.loads(snapshot._metadata),
                 mesh_reference=json.loads(N._json(reference)), logical_metadata=dict(
                     sha256=snapshot._logical_metadata[0], nbytes=snapshot._logical_metadata[1]))
    if snapshot._cells is not None:
        value['state']['cells'] = snapshot._cells.borrow()
    return OwnedRow(value, allocation)


def restore_compact(owner, envelope, arrays, *, compact_mesh, expected_mesh_reference):
    from atlas_tectonics._private.integration import native_transfer as N
    view = compact_mesh
    _reference(expected_mesh_reference, view.geometry_id)
    bounded = dict(envelope, state=_small_body(envelope['state']))
    scratch = N._Allocation(owner._budget, 65536+3*N._width(bounded), category='indexed-spatial-restore')
    body = dict(envelope['state'], thermal_mesh=view)
    # The native restore executes every original scientific/state gate before
    # issuing an indexed snapshot. The external workflow binds the store root.
    result = owner.restore(dict(state_id=envelope['state_id'], **body), arrays)
    _ = scratch
    return result
