"""Exact compact heat metadata and native binary64 fields, without a JSON body.

The generic codec owns rational spelling and integer pools. This module owns
only the snapshot boundary: its old logical identity, paid field buffers and
explicit bounded access. A snapshot is detached data, never native admission.
"""
from hashlib import sha256
import json
import math
from contextlib import nullcontext

import numpy as np

from compact_contracts import ContractError
from content_cache import ChargeSpec, OwnedStream
from record_tables import RecordCodec, canonical, require
from record_views import CompactRecord, LogicalExchange, RecordRef, _owned

LEDGER_SCHEMA = 'atlas.private.heat-ledger.logical.v1'
MAX_FIELD_BYTES = 512 << 20
MAX_FIELDS = 128


class _MeshIds(RecordRef):
    """Exact 64-character IDs borrowed from an admitted mesh column.

    A tiny scalar template supplies the generic bounded-export type inventory;
    no identity array or duplicated ID pool is stored in the heat record.
    """
    def __init__(self, mesh, kind, template):
        base = template.root()
        self._view, self.index = base._view, base.index
        self._fields = self._selection_owner = None
        self.mesh, self.mesh_kind, self.position = mesh, kind, None
        self._owner = _owned(template.scope, 8192, lambda: None, 'heat-mesh-id-view',
                             dependencies=(template._owner, mesh._owner))
        base.close()

    def _live(self):
        self._owner.value
        self.mesh._owner.value
        self.mesh._check()

    @property
    def kind(self):
        self._live()
        return 'array' if self.position is None else 'scalar'

    @property
    def size(self):
        self._live()
        require(self.position is None, 'scalar mesh ID has no size')
        return getattr(self.mesh, self.mesh_kind+'_count')

    def _logical_length(self):
        return (2+67*self.size-(1 if self.size else 0)) if self.position is None else 66

    def at(self, index):
        require(type(index) is int and 0 <= index < self.size, 'mesh identity index outside column')
        result = self.borrow()
        result.position = index
        result.index = self._view._child(self.index, 0)
        return result

    def scalar(self, *, max_owned_bytes):
        self._live()
        require(self.position is not None and max_owned_bytes >= 16384, 'bounded mesh identity scalar required')
        self.mesh.identity()
        # The ID is a newly decoded immutable string, like RecordRef.scalar.
        # Its paid allocation can outlive this borrowed column row.
        return _owned(self.scope, 8192, lambda: getattr(self.mesh, self.mesh_kind+'_id')(self.position),
                      'heat-mesh-id-scalar')

    def iter_rows(self, *, max_rows, max_owned_bytes, fields=None):
        require(fields is None and self.position is None and type(max_rows) is int and
                0 < max_rows <= 4_000_000 and type(max_owned_bytes) is int and
                max_owned_bytes >= 16384, 'bounded mesh identity rows required')
        anchor = self.borrow()
        count = min(max_rows, (max_owned_bytes-8192)//8192)
        def rows():
            for at in range(0, anchor.size, count):
                amount = min(count, anchor.size-at)
                yield _owned(anchor.scope, 4096+amount*8192,
                    lambda: tuple(anchor.at(i) for i in range(at, at+amount)), 'heat-mesh-id-rows')
        return OwnedStream(rows(), owners=(anchor._owner,), scope=self.scope)

    def iter_json(self, *, max_chunk_bytes=65536):
        require(type(max_chunk_bytes) is int and 0 < max_chunk_bytes <= 65536, 'bounded mesh ID stream required')
        anchor = self.borrow()
        def chunks():
            anchor.mesh.identity()
            count = anchor.size if anchor.position is None else 1
            with anchor.scope.reserve(ChargeSpec('heat-mesh-id-stream', 131072)) as reserved:
                buffer_owner = reserved.commit(bytearray())
            buffer = buffer_owner.value
            if anchor.position is None:
                buffer.extend(b'[')
            for at in range(count):
                anchor._live()
                if at and anchor.position is None:
                    buffer.extend(b',')
                value = getattr(anchor.mesh, anchor.mesh_kind+'_id')(at if anchor.position is None else anchor.position)
                require(type(value) is str and len(value) == 64 and all(c in '0123456789abcdef' for c in value),
                        'canonical mesh identity required')
                buffer.extend(b'"'+value.encode('ascii')+b'"')
                while len(buffer) >= max_chunk_bytes:
                    yield _owned(anchor.scope, max_chunk_bytes+4096,
                        lambda chunk_buffer=buffer: bytes(chunk_buffer[:max_chunk_bytes]), 'heat-mesh-id-block')
                    del buffer[:max_chunk_bytes]
            if anchor.position is None:
                buffer.extend(b']')
            if buffer:
                yield _owned(anchor.scope, len(buffer)+4096,
                             lambda chunk_buffer=buffer: bytes(chunk_buffer), 'heat-mesh-id-block')
            del buffer
            buffer_owner.close()
            anchor.mesh.identity()
        def stream():
            iterator = chunks()
            columns = anchor.mesh._arrays['id.bytes']
            while True:
                anchor._live()
                batch = columns.columns.read_batch() if hasattr(columns, 'columns') else nullcontext()
                with batch:
                    try:
                        block = next(iterator)
                    except StopIteration:
                        return
                yield block
        return OwnedStream(stream(), owners=(anchor._owner,), scope=self.scope)


def _shared_ledger(record, mesh, *, caller_ids):
    template = RecordCodec().pack_record(['0'*64], record_schema=LEDGER_SCHEMA,
        scope=record.scope, check=record._check)
    cells, faces = _MeshIds(mesh, 'cell', template), _MeshIds(mesh, 'face', template)
    base = record.root()
    children = dict(cell_ids=cells, face_ids=faces)
    if caller_ids:
        old = base.field('caller_snapshot')
        caller = LogicalExchange.from_records(old, cell_ids=cells)
        children['caller_snapshot'] = caller
    result = LogicalExchange.from_records(base, **children)
    # The result owns child borrows. Let input carriers retire; an explicit
    # close would correctly refuse while their dependent views remain alive.
    return result


def _ordered_mesh_binding(metadata, mesh):
    """Check and bind all three ID uses before omitting their duplicated bodies."""
    mesh.identity()
    for name, kind in (('cell_ids', 'cell'), ('face_ids', 'face')):
        values = metadata.get(name)
        count = getattr(mesh, kind+'_count')
        require(type(values) in (tuple, list) and len(values) == count, 'mesh/heat identity count differs')
        for at, value in enumerate(values):
            require(value == getattr(mesh, kind+'_id')(at), 'mesh/heat identity order differs')
    caller = metadata.get('caller_snapshot')
    caller_ids = type(caller) is dict and 'cell_ids' in caller
    if caller_ids:
        require(caller['cell_ids'] == metadata['cell_ids'], 'caller/heat cell identity order differs')
    mesh.identity()
    segment = getattr(mesh, '_segment', None)
    return dict(geometry_id=mesh.geometry_id, cell_count=mesh.cell_count, face_count=mesh.face_count,
                caller_ids=caller_ids, segment=None if segment is None else segment.info.ref.to_wire())


class _FieldBytes(bytes):
    """The buffer itself pins its funding, including escaped numpy bases."""
    def __new__(cls, raw, owner):
        value = super().__new__(cls, raw)
        object.__setattr__(value, '_owner', owner.retain())
        return value

    def __setattr__(self, name, value):
        raise ContractError('immutable heat field ownership')


def own_field(raw, *, scope):
    size = len(raw)
    require(size <= MAX_FIELD_BYTES, 'heat field exceeds 512 MiB bound')
    # Includes the actual immutable copy, its allocator overhead and carrier.
    with scope.reserve(ChargeSpec('heat-field', 65536+size+(size >> 3))) as reservation:
        owner = reservation.commit(None)
        result = _FieldBytes(raw, owner)
        owner._retire()
        return result


FINITE_BLOCK = 1 << 16


def _require_finite(value, *, scope, check):
    """The r12 RegionalMechanicalSnapshot gate (L21), checked in fixed blocks.

    Legacy frozen() refuses a non-finite field with this exact error and
    message, in sorted field order after the metadata encoding. The boolean
    block is the only allocation and is paid for the check.
    """
    flat = value.reshape(-1)
    with scope.reserve(ChargeSpec('heat-field-finite-check', 8192+FINITE_BLOCK)):
        for at in range(0, flat.size, FINITE_BLOCK):
            check()
            if not np.isfinite(flat[at:at+FINITE_BLOCK]).all():
                from atlas_tectonics._validation import TectonicsError
                raise TectonicsError('numerical result is outside finite binary64 range')


def field_descriptors(fields):
    return {name: dict(shape=list(shape), sha256=sha256(raw).hexdigest())
            for name, shape, raw in fields}


def snapshot_identity(record, fields, *, check=lambda: None):
    """Original RegionalMechanicalSnapshot identity, streamed in JSON order."""
    digest = sha256()
    digest.update(b'{"arrays":')
    digest.update(canonical(field_descriptors(fields)))
    digest.update(b',"metadata":')
    with record.iter_json() as stream:
        for block in stream:
            with block:
                check()
                digest.update(block.value)
    digest.update(b'}')
    check()
    return digest.hexdigest()


class CompactHeatSnapshot:
    """Immutable compact snapshot; consumers must request bounded fields/rows."""
    __slots__ = ('record', '_fields', 'result_id', '_check', '_closed', '_ledger', '_metadata_identity', '_mesh_binding')

    def __init__(self, record, fields, *, check=lambda: None, expected_result_id=None,
                 mesh=None, mesh_binding=None, expected_metadata_identity=None):
        require(type(record) is CompactRecord, 'owned compact ledger required')
        require(record.identity().record_schema == LEDGER_SCHEMA, 'heat ledger schema differs')
        require(type(fields) is tuple and 1 <= len(fields) <= MAX_FIELDS,
                'one to128 immutable heat fields required')
        previous = None
        for name, shape, raw in fields:
            require(type(name) is str and name and len(name) <= 512 and
                    (previous is None or previous < name), 'sorted unique heat field names required')
            require(type(shape) is tuple and len(shape) <= 16 and
                    all(type(n) is int and n >= 0 for n in shape), 'exact heat field shape required')
            require(isinstance(raw, _FieldBytes) and raw._owner.scope is record.scope and
                    len(raw) == 8*math.prod(shape), 'same-scope native binary64 field required')
            previous = name
        if mesh_binding is not None:
            from mesh_tables import CompactMesh
            require(type(mesh) is CompactMesh and mesh.scope is record.scope and mesh.geometry_id == mesh_binding['geometry_id'] and
                    mesh.cell_count == mesh_binding['cell_count'] and mesh.face_count == mesh_binding['face_count'],
                    'shared mesh heat binding differs')
            actual_segment = getattr(mesh, '_segment', None)
            require(mesh_binding['segment'] is None or (actual_segment is not None and
                    actual_segment.info.ref.to_wire() == mesh_binding['segment']), 'shared heat mesh segment differs')
        logical = record if mesh_binding is None else _shared_ledger(record, mesh, caller_ids=mesh_binding['caller_ids'])
        metadata_identity = logical.identity()
        require(expected_metadata_identity is None or expected_metadata_identity == metadata_identity,
                'complete heat metadata identity differs')
        result_id = snapshot_identity(logical, fields, check=check)
        require(expected_result_id is None or expected_result_id == result_id,
                'compact heat result identity differs')
        object.__setattr__(self, 'record', record)
        object.__setattr__(self, '_fields', fields)
        object.__setattr__(self, 'result_id', result_id)
        object.__setattr__(self, '_check', check)
        object.__setattr__(self, '_closed', False)
        object.__setattr__(self, '_ledger', logical)
        object.__setattr__(self, '_metadata_identity', metadata_identity)
        object.__setattr__(self, '_mesh_binding', canonical(mesh_binding))

    def __setattr__(self, name, value):
        raise ContractError('compact heat snapshots are immutable')

    @classmethod
    def from_components(cls, metadata, fields, *, scope, check=lambda: None,
                        expected_result_id=None, mesh=None):
        require(type(fields) is dict and 1 <= len(fields) <= MAX_FIELDS,
                'bounded native field mapping required')
        binding = None
        if mesh is not None:
            from mesh_tables import CompactMesh
            require(type(metadata) is dict and type(mesh) is CompactMesh and mesh.budget is scope.run_budget,
                    'heat/mesh shared run budget required')
            binding = _ordered_mesh_binding(metadata, mesh)
            if mesh.scope is scope:
                metadata = {k: v for k, v in metadata.items() if k not in ('cell_ids', 'face_ids')}
                if binding['caller_ids']:
                    metadata['caller_snapshot'] = {k: v for k, v in metadata['caller_snapshot'].items() if k != 'cell_ids'}
            else:
                require(mesh.scope is None, 'foreign mesh scope')
                binding = None
        record = RecordCodec().pack_record(metadata, record_schema=LEDGER_SCHEMA,
                                           scope=scope, check=check)
        owned_fields = []
        for name, value in sorted(fields.items()):
            check()
            require(type(value) is np.ndarray and value.dtype == np.float64 and
                    value.flags.c_contiguous and value.nbytes <= MAX_FIELD_BYTES,
                    'bounded contiguous native binary64 arrays required')
            _require_finite(value, scope=scope, check=check)
            # A zero-size field has no bytes to view (memoryview.cast refuses
            # zeros in the shape); r12 accepts it with sha256(b'') (Decision 5).
            raw = memoryview(value).cast('B') if value.size else b''
            owned_fields.append((name, tuple(value.shape), own_field(raw, scope=scope)))
        return cls(record, tuple(owned_fields), check=check, expected_result_id=expected_result_id,
                   mesh=mesh, mesh_binding=binding)

    def _live(self):
        require(not self._closed, 'closed compact heat snapshot')
        self.record._live()
        self._check()

    @property
    def scope(self):
        return self.record.scope

    @property
    def _record(self):
        return self.record

    @property
    def mesh_binding(self):
        self._live()
        return json.loads(self._mesh_binding)

    def verify_identity(self, *, check=lambda: None):
        self._live()
        actual = snapshot_identity(self._ledger, self._fields, check=check)
        require(actual == self.result_id, 'compact heat result identity differs')
        return actual

    @property
    def metadata_identity(self):
        self._live()
        return self._metadata_identity

    @property
    def ledger(self):
        self._live()
        return self._ledger.root() if type(self._ledger) is CompactRecord else self._ledger.borrow()

    @property
    def array_names(self):
        self._live()
        return tuple(name for name, _, _ in self._fields)

    @property
    def nbytes(self):
        return self.metadata_identity.canonical_bytes+sum(len(raw) for _, _, raw in self._fields)

    def array(self, name):
        self._live()
        for key, shape, raw in self._fields:
            if key == name:
                return np.frombuffer(raw, dtype=np.float64).reshape(shape)
        raise ContractError('unknown compact heat field')

    def field(self, name, *, max_logical_bytes=4 << 20, max_owned_bytes=4 << 20):
        with self.ledger as root, root.field(name) as child:
            return child.export(max_logical_bytes=max_logical_bytes, max_owned_bytes=max_owned_bytes)

    def descriptor(self):
        raise ContractError('whole heat descriptor refused; use bounded fields or ledger rows')

    def validate_mesh_order(self, mesh):
        """Recheck exact ID order against an explicitly supplied admitted mesh."""
        from mesh_tables import CompactMesh
        require(type(mesh) is CompactMesh and mesh.budget is self.scope.run_budget and
                (mesh.scope is None or mesh.scope is self.scope), 'same-budget mesh identity view required')
        mesh.identity()
        for field, kind in (('cell_ids', 'cell'), ('face_ids', 'face')):
            count = getattr(mesh, kind+'_count')
            with self.ledger as root, root.field(field) as values:
                require(values.size == count, 'mesh/heat identity count differs')
                for i in range(count):
                    expected = getattr(mesh, kind+'_id')(i)
                    with values.at(i) as ref, ref.scalar(max_owned_bytes=65536) as value:
                        require(value.value == expected, 'mesh/heat identity order differs')
        mesh.identity()

    def close(self):
        if not self._closed:
            if self._ledger is not self.record:
                self._ledger.close()
            self.record.close()
            object.__setattr__(self, '_fields', ())
            object.__setattr__(self, '_closed', True)
