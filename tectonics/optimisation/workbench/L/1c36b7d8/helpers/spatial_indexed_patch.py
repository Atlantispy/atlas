"""Indexed spatial state ownership; exact logical IDs, explicit compact wire.

Source transforms retain the native scientific gates. A CompactMesh is storage
authentication, not physical acceptance. The state owns the exact compact view
and small immutable stock metadata, never an encoded/decoded complete mesh.
"""
from dataclasses import dataclass
from hashlib import sha256
import json
import math

import numpy as np


SCHEMA = 'atlas.compact-spatial-state.r1'
REFERENCE_SCHEMA = 'atlas.compact-mesh-store.v2'  # compact_store.SCHEMA (packed support blobs)
TRANSFER_SOURCE_SHA256 = '04a5945032e55a91add2ae57e65baa22983613aff66b8927d8e891c548f36c3b'
CELL_ROW_BYTES = 4 << 20


class IndexedSpatialRefused(ValueError):
    pass


def is_compact(value):
    # Lazy import keeps the ordinary transfer route independent of this codec.
    from mesh_tables import CompactMesh
    return type(value) is CompactMesh and getattr(value, '_sealed', False)


def _view(value, budget):
    if not is_compact(value) or value.budget is not budget:
        raise IndexedSpatialRefused('sealed actual compact mesh on the shared budget required')
    return value


def is_compact_cells(value):
    from record_views import RecordRef
    return isinstance(value, RecordRef)


def _cells_view(value, budget):
    if (not is_compact_cells(value) or value.scope.run_budget is not budget or
            value.kind != 'array'):
        raise IndexedSpatialRefused('compact state cells require an array on the actual shared budget')
    return value


def cell_count(value, budget):
    return _cells_view(value, budget).size if is_compact_cells(value) else len(value)


def iter_state_cells(value, budget):
    """Native rows with paid escaping ownership; never export the whole array."""
    if not is_compact_cells(value):
        yield from value
        return
    import native_transfer as N
    cells = _cells_view(value, budget)
    with cells.iter_rows(max_rows=1, max_owned_bytes=CELL_ROW_BYTES) as blocks:
        for block in blocks:
            with block:
                for row in block.value:
                    held = row.export(max_logical_bytes=CELL_ROW_BYTES,
                                      max_owned_bytes=CELL_ROW_BYTES)
                    if type(held.value) is not dict:
                        raise IndexedSpatialRefused('compact state cell must be an object')
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
            if type(key) is not str:
                raise IndexedSpatialRefused('canonical string object keys required')
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
    from mesh_tables import OwnedRow
    if type(mesh) is dict:
        return OwnedRow(mesh, None)
    if getattr(mesh, '_compact', None) is not None:
        mesh = mesh._compact
    return _view(mesh, budget).header()


def mesh_identity(mesh, ordinary_hash):
    return mesh.geometry_id if is_compact(mesh) else ordinary_hash(mesh)


def exterior_ids(mesh, budget):
    if type(mesh) is dict:
        yield from (r['logical_cell_id'] for r in mesh['cells'] if r['kind'] == 'exterior')
        return
    view = _view(mesh, budget)
    for index in range(view.cell_count):
        row = view.cell(index)
        if row.value['kind'] == 'exterior':
            yield row.value['logical_cell_id']
        del row


def _small_body(body):
    return {k: v for k, v in body.items() if k != 'thermal_mesh' and
            not (k == 'cells' and is_compact_cells(v))}


def retained_metadata_nbytes(body):
    import spatial_transfer as S
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
    import native_transfer as N
    from mesh_tables import _decode_charge
    snapshot = state._snapshot
    if type(snapshot) is not IndexedSpatialSnapshot:
        return state.record()
    _view(snapshot._mesh, state._budget)
    if snapshot._budget is not state._budget:
        raise IndexedSpatialRefused('indexed spatial snapshot has another budget')
    allocation = N._Allocation(state._budget, _decode_charge(snapshot._metadata)+65536,
                               category='indexed-spatial-record')
    value = dict(state_id=state.state_id, **json.loads(snapshot._metadata),
                 thermal_mesh=snapshot._mesh)
    if snapshot._cells is not None:
        value['cells'] = _cells_view(snapshot._cells, state._budget).borrow()
    return _LogicalRecord(value, allocation)


def indexed_record(state):
    from mesh_tables import OwnedRow
    result = logical_record(state)
    if type(result) is not _LogicalRecord:
        raise IndexedSpatialRefused('actual indexed spatial state required')
    # The plain dict API is explicit and borrowed; retain this OwnedRow. The
    # internal _bound adapter retains its allocation on the dict itself.
    return OwnedRow(dict(result), result._allocation)


def retained_snapshot(body, arrays, identity, metadata, allocation, budget):
    import native_transfer as N
    import spatial_transfer as S
    view = _view(body.get('thermal_mesh'), budget)
    cells = (_cells_view(body['cells'], budget).borrow()
             if is_compact_cells(body.get('cells')) else None)
    small = _small_body(body)
    scratch = N._Allocation(budget, 65536+3*N._width(small)+
        max((a.nbytes for a in arrays.values()), default=0), category='indexed-spatial-encoding')
    encoded = N._RecordBytes(N._json(small), allocation)
    fields = tuple((name, tuple(array.shape), N._RecordBytes(array.tobytes(order='C'), allocation))
                   for name, array in sorted(arrays.items()))
    if S._snapshot_id(body, S._bindings(arrays)) != identity or S._stream_stats(body)[0] != metadata:
        raise IndexedSpatialRefused('indexed logical snapshot binding differs')
    result = IndexedSpatialSnapshot(encoded, fields, identity, view,
        (metadata['sha256'], metadata['nbytes']), body['time_s'], budget, cells,
        None if view._owner is None else view._owner.retain())
    _ = scratch
    return result


def _checked_identity(snapshot):
    """Recompute from owned immutable bytes and actual streamed mesh content."""
    import native_transfer as N
    from mesh_tables import _decode_charge
    if type(snapshot) is not IndexedSpatialSnapshot:
        raise IndexedSpatialRefused('exact indexed spatial snapshot required')
    view = _view(snapshot._mesh, snapshot._budget)
    encoded, fields = snapshot._metadata, snapshot._fields
    if (type(encoded) is not N._RecordBytes or type(encoded._allocation) is not N._Allocation or
            encoded._allocation._guard is None or type(fields) is not tuple or not 0 < len(fields) <= 330):
        raise IndexedSpatialRefused('actual owned indexed snapshot bytes required')
    scratch = N._Allocation(snapshot._budget, _decode_charge(encoded)+65536+2048*len(fields),
                            category='indexed-spatial-identity')
    body = json.loads(encoded)
    if (type(body) is not dict or N._json(body) != encoded or 'thermal_mesh' in body or
            body.get('thermal_mesh_id') != view.geometry_id or body.get('time_s') != snapshot.time_s):
        raise IndexedSpatialRefused('compact snapshot body differs from its immutable mesh/time binding')
    if snapshot._cells is not None:
        if 'cells' in body:
            raise IndexedSpatialRefused('compact snapshot duplicates its cell body')
        body['cells'] = _cells_view(snapshot._cells, snapshot._budget)
    bindings, previous = {}, None
    for entry in fields:
        if type(entry) is not tuple or len(entry) != 3:
            raise IndexedSpatialRefused('complete immutable field binding required')
        name, shape, raw = entry
        if (type(name) is not str or not name or previous is not None and previous >= name or
                type(shape) is not tuple or any(type(d) is not int or d < 0 for d in shape) or
                type(raw) is not N._RecordBytes or raw._allocation is not encoded._allocation or
                math.prod(shape)*8 != len(raw)):
            raise IndexedSpatialRefused('indexed field ownership, order or byte shape differs')
        bindings[name] = dict(shape=shape, sha256=sha256(raw).hexdigest())
        previous = name
    body['thermal_mesh'] = view
    identity, metadata, size = sha256(), sha256(), 0
    identity.update(b'{"arrays":'+N._json(bindings)+b',"metadata":')
    for part in iter_logical_json(body):
        identity.update(part)
        metadata.update(part)
        size += len(part)
    identity.update(b'}')
    stats = dict(sha256=metadata.hexdigest(), nbytes=size)
    if (snapshot._logical_metadata != (stats['sha256'], stats['nbytes']) or
            identity.hexdigest() != snapshot.result_id):
        raise IndexedSpatialRefused('indexed logical metadata or complete snapshot identity differs')
    _ = scratch
    return identity.hexdigest(), stats


def snapshot_identity(snapshot, *, legacy_identity=None):
    """Private issuer seam: full logical identity, never compact-wire identity."""
    if type(snapshot) is not IndexedSpatialSnapshot:
        if legacy_identity is None:
            raise IndexedSpatialRefused('explicit original legacy identity routine required')
        return legacy_identity(snapshot)
    return _checked_identity(snapshot)[0]


def snapshot_metadata_matches(snapshot, binding):
    return _checked_identity(snapshot)[1] == binding


def issue(owner, body):
    """Called only by the actual native owner's existing issue boundary."""
    import native_transfer as N
    import spatial_transfer as S
    from atlas_tectonics.integration_spatial_owner import SpatialExteriorState, _project, _q
    view = _view(body.get('thermal_mesh'), owner._budget)
    if not is_compact_cells(body.get('cells')) and hasattr(owner, '_record_scope'):
        from exchange_record_patch import required_scope
        from record_tables import RecordCodec
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
    metadata, _ = S._stream_stats(body)
    identity = S._snapshot_id(body, S._bindings(fields))
    allocation = N._Allocation(owner._budget, 8192+retained_metadata_nbytes(body)+
        sum(a.nbytes for a in fields.values())+1024*len(fields), category='indexed-spatial-state')
    result = object.__new__(SpatialExteriorState)
    object.__setattr__(result, '_snapshot', retained_snapshot(body, fields, identity, metadata, allocation, owner._budget))
    object.__setattr__(result, '_budget', owner._budget)
    _ = scratch, view
    return result


def validate_projected_payload(owner, body, arrays, state_id):
    """Original restore tail, with compact rows and the same exact projection."""
    import spatial_transfer as S
    if not is_compact_cells(body.get('cells')):
        return S.validate_projected_payload(owner, body, arrays, state_id)
    from atlas_tectonics.integration_spatial_owner import _project, _q
    from atlas_tectonics._validation import TectonicsError
    import native_transfer as N
    names = set(owner._names) | {'volume_m3'}
    if set(arrays) != names:
        raise TectonicsError('saved exact inventories and projected arrays disagree')
    count = cell_count(body['cells'], owner._budget)
    scratch = N._Allocation(owner._budget, 65536+16*count,
                            category='indexed-spatial-projected-check')
    for name in sorted(names):
        expected = np.fromiter((_project(_q(row['volume_m3'] if name == 'volume_m3'
            else row['exact'][name])) for row in iter_state_cells(body['cells'], owner._budget)),
            dtype=np.float64, count=count)
        if not np.array_equal(arrays[name], expected):
            raise TectonicsError('saved exact inventories and projected arrays disagree')
    bindings = S._bindings(arrays)
    if S._snapshot_id(body, bindings) != state_id:
        raise TectonicsError('saved exact inventories and projected arrays disagree')
    _ = scratch
    return dict(state_id=state_id, metadata=S._stream_stats(body)[0], arrays=bindings)


def _reference(reference, geometry_id):
    import native_transfer as N
    if isinstance(reference, dict) and reference.get('schema') == 'atlas.compact-mesh-store.v3':
        from compact_contracts import SegmentRef
        if set(reference) != {'schema', 'segment', 'geometry_id', 'source_producer'}:
            raise IndexedSpatialRefused('complete mesh v3 segment reference required')
        ref = SegmentRef.from_wire(reference['segment'])
        if ref.identity.sha256 != geometry_id or reference['geometry_id'] != geometry_id:
            raise IndexedSpatialRefused('mesh v3 logical identity differs')
        return reference
    if (not isinstance(reference, dict) or set(reference) != {'schema', 'snapshot_key', 'geometry_id',
            'source_producer', 'array_bindings'} or
            reference['schema'] != REFERENCE_SCHEMA or reference['geometry_id'] != geometry_id):
        raise IndexedSpatialRefused('explicit compact mesh snapshot/geometry binding required')
    N._digest(reference['snapshot_key'], 'compact mesh snapshot')
    N._digest(geometry_id, 'logical thermal geometry')
    if (type(reference['array_bindings']) is not dict or not reference['array_bindings'] or
            not all(type(v) is str and len(v) == 64 and not v.strip('0123456789abcdef')
                    for v in reference['array_bindings'].values())):
        raise IndexedSpatialRefused('complete immutable mesh array descriptor digests required')
    return reference


def compact_record(state, *, mesh_reference):
    """Explicit persistable envelope, not a legacy full-mesh state record.

    Publication must bind the named actual CompactMeshStore root atomically.
    This function validates spelling and logical identity, not store authority.
    """
    import native_transfer as N
    from mesh_tables import OwnedRow, _decode_charge
    snapshot = state._snapshot
    if type(snapshot) is not IndexedSpatialSnapshot:
        raise IndexedSpatialRefused('actual indexed spatial state required')
    reference = _reference(mesh_reference, snapshot._mesh.geometry_id)
    allocation = N._Allocation(state._budget, _decode_charge(snapshot._metadata)+
                               4*N._width(dict(reference))+65536,
                               category='indexed-spatial-record')
    value = dict(schema=SCHEMA, state_id=state.state_id, state=json.loads(snapshot._metadata),
                 mesh_reference=json.loads(N._json(reference)), logical_metadata=dict(
                     sha256=snapshot._logical_metadata[0], nbytes=snapshot._logical_metadata[1]))
    if snapshot._cells is not None:
        value['state']['cells'] = _cells_view(snapshot._cells, state._budget).borrow()
    return OwnedRow(value, allocation)


def restore_compact(owner, envelope, arrays, *, compact_mesh, expected_mesh_reference):
    import native_transfer as N
    import spatial_transfer as S
    view = _view(compact_mesh, owner._budget)
    reference = _reference(expected_mesh_reference, view.geometry_id)
    if (type(envelope) is not dict or set(envelope) != {'schema', 'state_id', 'state',
            'mesh_reference', 'logical_metadata'} or envelope['schema'] != SCHEMA or
            envelope['mesh_reference'] != reference or type(envelope['state']) is not dict or
            'thermal_mesh' in envelope['state'] or envelope['state'].get('thermal_mesh_id') != view.geometry_id):
        raise IndexedSpatialRefused('compact spatial envelope or externally expected mesh reference differs')
    bounded = dict(envelope, state=_small_body(envelope['state']))
    scratch = N._Allocation(owner._budget, 65536+3*N._width(bounded), category='indexed-spatial-restore')
    body = dict(envelope['state'], thermal_mesh=view)
    if S._stream_stats(body)[0] != envelope['logical_metadata']:
        raise IndexedSpatialRefused('compact spatial logical metadata differs')
    # The native restore executes every original scientific/state gate before
    # issuing an indexed snapshot. The external workflow binds the store root.
    result = owner.restore(dict(state_id=envelope['state_id'], **body), arrays)
    _ = scratch
    return result


_STATE_METHOD = '''    def compact_record(self, *, mesh_reference):
        """Owned explicit compact persistence envelope; no legacy expansion."""
        from spatial_indexed_patch import compact_record
        return compact_record(self, mesh_reference=mesh_reference)

    def indexed_record(self):
        """Owned logical state with a sealed indexed mesh, not JSON wire."""
        from spatial_indexed_patch import indexed_record
        return indexed_record(self)

'''
_OWNER_METHOD = '''    def restore_compact(self, envelope, arrays, *, compact_mesh, expected_mesh_reference):
        from spatial_indexed_patch import restore_compact
        return restore_compact(self, envelope, arrays, compact_mesh=compact_mesh,
                               expected_mesh_reference=expected_mesh_reference)

'''


def transform(source):
    """After spatial_transfer's additive seam; never edit frozen source files."""
    if (type(source) is not str or sha256(source.encode()).hexdigest() != TRANSFER_SOURCE_SHA256 or
            'def from_migrated_checkpoint(' not in source or 'def compact_record(' in source):
        raise IndexedSpatialRefused('reviewed transfer source required exactly once')
    replacements = (
        ("        return self._snapshot.descriptor()['time_s']",
         '        from spatial_indexed_patch import IndexedSpatialSnapshot\n'
         '        if type(self._snapshot) is IndexedSpatialSnapshot:\n            return self._snapshot.time_s\n'
         "        return self._snapshot.descriptor()['time_s']"),
        ('    def arrays(self):\n        return {k: self._snapshot.array(k) for k in self._snapshot.array_names}',
         _STATE_METHOD+'    def arrays(self):\n        return {k: self._snapshot.array(k) for k in self._snapshot.array_names}'),
        ('    def _issue(self, record):\n',
         '    def _issue(self, record):\n'
         '        from spatial_indexed_patch import is_compact, issue\n'
         "        if is_compact(record.get('thermal_mesh')):\n            return issue(self, record)\n"),
        ('        r = state.record()\n',
         '        from spatial_indexed_patch import logical_record\n        r = logical_record(state)\n'),
        ("        mesh = body['thermal_mesh']\n", "        from spatial_indexed_patch import mesh_header, mesh_identity, exterior_ids\n"
         "        _mesh_header_owner = mesh_header(body['thermal_mesh'], self._budget)\n"
         '        mesh = _mesh_header_owner.value\n'),
        ("        if (mesh_hash(mesh) != body['thermal_mesh_id'] or mesh['support_id'] != body['support_id'] or",
         "        if (mesh_identity(body['thermal_mesh'], mesh_hash) != body['thermal_mesh_id'] or mesh['support_id'] != body['support_id'] or"),
        ("        if seen != {r['logical_cell_id'] for r in mesh['cells'] if r['kind'] == 'exterior'}:",
         "        if seen != set(exterior_ids(body['thermal_mesh'], self._budget)):"),
        ('    def restore(self, record, arrays, *, _validate_only=False):\n',
         _OWNER_METHOD+'    def restore(self, record, arrays, *, _validate_only=False):\n'),
        ("    if geometry.get('parent_partition_id') != state['thermal_mesh'].get('partition_id'):",
         "    from spatial_indexed_patch import mesh_header, is_compact\n"
         "    _parent_mesh = state['thermal_mesh']\n"
         '    _parent_header = mesh_header(_parent_mesh, _parent_mesh.budget if is_compact(_parent_mesh) else None)\n'
         "    if geometry.get('parent_partition_id') != _parent_header.value.get('partition_id'):"),
        ('                f = funding.descriptor()\n',
         '                f = funding.descriptor()\n'
         '                from spatial_indexed_patch import mesh_header\n'
         "                _initial_mesh_header = mesh_header(initial_record['thermal_mesh'], budget)\n"),
        ("                mesh = initial_record['thermal_mesh']\n", '                mesh = _initial_mesh_header.value\n'),
        ("                            any(initial_record['thermal_mesh'].get(k) != initial[k] for k in",
         "                            any(_initial_mesh_header.value.get(k) != initial[k] for k in"),
    )
    for old, new in replacements:
        if source.count(old) != 1:
            raise IndexedSpatialRefused('indexed spatial seam missing or ambiguous: '+old[:80])
        source = source.replace(old, new, 1)
    return source
