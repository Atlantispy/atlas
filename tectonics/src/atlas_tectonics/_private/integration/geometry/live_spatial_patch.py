"""Step 8 spatial/heat construction lifetimes; no numerical kernel changes.

Apply these exact source seams after the compact Step 7 transformations. The
shared dictionaries below remain inside their original producer frames; no
new public record or unowned result is issued.
"""
import ast
import sys

import numpy as np

from atlas_tectonics._private.codecs.compact_contracts import ContractError
from atlas_tectonics._private.codecs.content_cache import ChargeSpec
from atlas_tectonics.integration.resources import _close_consumed_stack


input_stack = _close_consumed_stack


def _once(source, old, new):
    return source.replace(old, new, 1)


class _FloatSequence:
    """Borrow immutable paid binary64 backing, yielding original Python floats."""
    __slots__ = ('_owner',)

    def __init__(self, array, scope):
        backing = array.base
        for _ in range(8):
            if type(backing) is np.ndarray:
                backing = backing.base
            elif isinstance(backing, memoryview):
                backing = backing.obj
            else:
                break
        self._owner = scope.reserve(ChargeSpec('heat-public-field-view', 512)).commit(array)

    def __len__(self):
        return len(self._owner.value)

    def __iter__(self):
        for value in self._owner.value:
            yield float(value)


def float_sequence(array, *, scope):
    return _FloatSequence(array, scope)


def float_list(values):
    """Preserve the old conversion for external integer inputs; share floats."""
    return values if all(type(value) is float for value in values) else list(map(float, values))


def normalisation_capacity(value, check, depth=0):
    """Charge only tuple conversions and the containers on their parent paths."""
    check()
    if type(value) not in (dict, list, tuple):
        return 0
    children = value.values() if type(value) is dict else value
    changed, size = type(value) is tuple, 0
    for child in children:
        cost = normalisation_capacity(child, check, depth+1)
        changed |= cost != 0
        size += cost
    if not changed:
        return 0
    return size+(2*sys.getsizeof(value) if type(value) is dict else 256+16*len(value))


def normalise_containers(value, check):
    """Borrow unchanged producer containers only until synchronous packing ends."""
    if not normalisation_capacity(value, check):
        return value
    if type(value) is dict:
        return {key: normalise_containers(child, check) for key, child in value.items()}
    return [normalise_containers(child, check) for child in value]


# Fresh physical graph/bounds use the caller's one existing scope. Construction
# never installs a cache or creates a new scope on a view or holder.
from contextlib import ExitStack, contextmanager
from contextvars import ContextVar
from hashlib import sha256
import json

from atlas_tectonics._private.integration import live_composite as LIVE_COMPOSITE
from atlas_tectonics._private.codecs.record_tables import RecordBuilder, RecordCodec, Scratch
from atlas_tectonics._private.codecs.record_views import RecordRef
from atlas_tectonics._private.integration.geometry import spatial_validation_patch as VALIDATION

_ACTIVE = ContextVar('live-spatial-construction', default=None)
_LEGACY_READS = ContextVar('live-spatial-lexical-legacy-reads', default=())
_UNSPECIFIED = object()
# Step 8 early releases: the transport advance tail drops its exact rational
# tables once the metadata holds them encoded, and finish releases transport
# columns after their last use instead of at scope exit. Lifetimes only, no
# value changes. Test-only switch for same-source before/after measurement;
# the heat issuer captures it as part of its loaded identity.
EARLY_RELEASE = True
# Step 8: finish streams each state cell row into one exact builder instead
# of collecting the complete Python row list and packing it at issue. Same
# canonical bytes and cell_id order. Test-only switch, captured like the above.
STREAM_CELLS = True
STATE_CELLS_SCHEMA = 'atlas.spatial-state-cells.v1'
STATE_CELL_ROW_SCHEMA = 'atlas.spatial-state-cell.v1'
_ROW_FIELDS = frozenset(('cells', 'face_intervals', 'transfers',
    'inactive_zero_measure_cells', 'original_face_intervals',
    'selected_face_representatives'))


@contextmanager
def construction(scope, *, budget):
    token = _ACTIVE.set(scope)
    try:
        yield
    finally:
        _ACTIVE.reset(token)


def active_scope(budget):
    scope = _ACTIVE.get()
    return scope


def issue(cls, record, budget, ordinary):
    scope = active_scope(budget)
    if scope is None:
        return ordinary(cls, record, budget)
    from atlas_tectonics._private.integration.geometry import live_finite_patch as finite
    value = dict(record) if type(record) is finite.MutableRecord else record
    # Fields still borrowed from live bounds (remaining(), original intervals,
    # a differential bounds reference) stay borrowed: only native fields pack.
    packed = LIVE_COMPOSITE.compose_record(value, record_schema='atlas.spatial-working-record.v1',
                                           scope=scope, check=lambda: active_scope(budget))
    if packed is None:
        packed = RecordCodec().pack_record(value, record_schema='atlas.spatial-working-record.v1',
                                          scope=scope, check=lambda: active_scope(budget))
    # The original exact class, resource token and canonical identity remain.
    result = object.__new__(cls)
    object.__setattr__(result, '_json', packed)
    object.__setattr__(result, '_resource', budget)
    return result


def holder_identity(holder):
    payload = holder._json
    return payload.identity().sha256 if LIVE_COMPOSITE.is_compact(payload) else sha256(payload).hexdigest()


def holder_content_identity(holder):
    """E-22: bounds_id / geometry_id, the digest of the record's content form, made once per holder. A packed record
    is streamed; stored bytes are decoded once (json.loads gives plain dicts, so content_record sees every field).
    holder_identity stays the byte guard of the stored bytes."""
    known = getattr(holder, '_content_id', None)
    if known is None:
        payload = holder._json
        if LIVE_COMPOSITE.is_compact(payload):
            with payload.root() as root:
                known = VALIDATION.content_identity(root, None)
        else:
            from atlas_tectonics.integration.reuse import content_record
            with holder._resource.reserve(65536+4*len(payload), category='spatial-content-id'):
                record = json.loads(payload)
                content = content_record(record)
                known = sha256(payload if content is record else json.dumps(
                    content, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()
        object.__setattr__(holder, '_content_id', known)
    return known


def graph_content_identity(value, ordinary):
    """E-22: a spatial graph identifier from its content form; graph_identity is the byte form."""
    return VALIDATION.content_identity(reference(value), ordinary)


def holder_record(holder):
    payload = holder._json
    return payload.root() if LIVE_COMPOSITE.is_compact(payload) else json.loads(payload)


def holder_bytes(holder):
    payload = holder._json
    return payload.identity().canonical_bytes if LIVE_COMPOSITE.is_compact(payload) else len(payload)


class _Object(VALIDATION._Object):
    def __getitem__(self, key):
        if key in self.cache:
            return self.cache[key]
        if key in _ROW_FIELDS:
            child = self.ref.field(key)
            if child.kind != 'array':
                child.close()
                raise ContractError('complete spatial row array required')
            self.stack.callback(child.close)
            value = VALIDATION._Rows(child)
            self.cache[key] = value
            return value
        return super().__getitem__(key)


def is_record(value):
    return type(value) is dict or type(value) in (_Object, _TransportObject)


def reference(value):
    if type(value) in (_Object, VALIDATION._Object, _TransportObject, _Columns):
        return value.ref
    if type(value) is VALIDATION._Rows:
        return value.ref
    return value


class _Columns:
    """Explicit bounded per-field working lists, never a metadata export.

    Each column owns its own stack inside the shared one, so a column can be
    released after its last use (release) while every other column, and every
    column on a failure path, keeps the shared scope's retention rule.
    """
    def __init__(self, ref, stack):
        self.ref, self.stack, self.cache, self.columns = ref, stack, {}, {}

    def __iter__(self):
        with self.ref.keys(max_owned_bytes=65536) as names:
            yield from names.value

    def __len__(self):
        return self.ref.size

    def __getitem__(self, name):
        if name not in self.cache:
            column = ExitStack()
            self.stack.callback(column.close)
            self.columns[name] = column
            child = self.ref.field(name)
            column.callback(child.close)
            owned = child.export(max_logical_bytes=4 << 20, max_owned_bytes=4 << 20)
            column.enter_context(owned)
            self.cache[name] = owned.value
        return self.cache[name]

    def release(self, name):
        """End one column's paid export; the caller holds no alias of it."""
        self.cache.pop(name, None)
        column = self.columns.pop(name, None)
        if column is not None:
            column.close()

    def values(self):
        for name in self:
            yield self[name]

    def items(self):
        for name in self:
            yield name, self[name]


class _TransportObject(_Object):
    def __getitem__(self, key):
        if key not in self.cache and (key.startswith('exact_') or key == 'binary_stock_projection_accounts'):
            child = self.ref.field(key)
            self.stack.callback(child.close)
            value = _Columns(child, self.stack)
            self.cache[key] = value
        return super().__getitem__(key)


class CellSink:
    """Finish's state cell rows, streamed into one exact builder.

    The native loop appends one row dict at a time and may still set a key on
    the row it has just appended (cells[-1][...] = ...), so the newest row
    stays pending until the next append or the final sort. Every earlier row
    exists only as packed nodes in the builder's shared tables; the complete
    Python row list never exists. The finished array has exactly the
    canonical bytes of the sorted list the native issue would have packed.
    A failure leaves the builder and the pending row with the failed frame,
    paid until that traceback is released, like any other pack.
    """
    def __init__(self, scope, check):
        self._builder = RecordBuilder(scope=scope, check=check)
        self._nodes, self._pending, self._record = [], None, None

    def append(self, row):
        self._commit()
        self._pending = row

    def __getitem__(self, index):
        return self._pending

    def _commit(self):
        if self._pending is None:
            return
        row, self._pending = self._pending, None
        self._nodes.append((row['cell_id'], self._builder.append(row, record_schema=STATE_CELL_ROW_SCHEMA)))

    def sort_by_cell_id(self):
        self._commit()
        # The native key: rows ordered by cell_id with a stable sort.
        self._nodes.sort(key=lambda item: item[0])

    def finish(self):
        if self._record is None:
            self.sort_by_cell_id()
            nodes = [node for _, node in self._nodes]
            self._record = self._builder.finish(nodes, record_schema=STATE_CELLS_SCHEMA)
            self._nodes = []
        return self._record.root()


def cell_sink(owner, cancel=None):
    """A streamed sink when the owner issues compact state, else the native list."""
    scope = getattr(owner, '_record_scope', None)
    if not STREAM_CELLS or scope is None:
        return []
    return CellSink(scope, check=lambda: check_cancel(cancel))


def sort_cells(cells):
    if type(cells) is CellSink:
        cells.sort_by_cell_id()
    else:
        cells.sort(key=lambda row: row['cell_id'])


def state_cells(cells):
    """The value placed in the state record: compact array root or the list."""
    return cells.finish() if type(cells) is CellSink else cells


def release_columns(value, key, keep=()):
    """Release one exact_* object's columns after their last use.

    Called only on the success path, after the last read of those columns and
    once no caller alias of them is alive. Columns named in keep stay paid
    (the grouped heat account holds slices of the enthalpy columns until its
    context exits). Legacy dict records have nothing to release.
    """
    if type(value) is not _TransportObject:
        return
    columns = value.cache.get(key)
    if type(columns) is not _Columns:
        return
    for name in [name for name in columns.columns if name not in keep]:
        columns.release(name)


def is_transport_snapshot(value):
    from atlas_tectonics._private.integration.live_transport_result import CompactTransportSnapshot
    return type(value) is CompactTransportSnapshot


def transport_identity(value, budget, cancel=None):
    from atlas_tectonics._private.integration.live_transport_result import identity
    return identity(value, budget, cancel=cancel)


@contextmanager
def transport_access(result, *, scope=_UNSPECIFIED):
    if not is_transport_snapshot(result._snapshot):
        from atlas_tectonics._private.codecs.mesh_tables import _decode_charge
        with workspace(result._budget, _decode_charge(result._snapshot._metadata)):
            record = result.record()
            yield record
            del record
        return
    record = result.record()
    stack = ExitStack()
    stack.callback(record.close)
    value = _TransportObject(record, stack)
    try:
        yield value
    except BaseException:
        raise
    else:
        value.cache.clear()
        stack.close()


@contextmanager
def access(value):
    if not isinstance(value, RecordRef):
        yield value
        return
    stack = ExitStack()
    borrowed = value.borrow()
    stack.callback(borrowed.close)
    converted = _Object(borrowed, stack)
    try:
        yield converted
    except BaseException:
        # Never close paid field/row backing still held by a failed caller.
        raise
    else:
        converted.cache.clear()
        stack.close()


@contextmanager
def record_access(holder, *, scope=_UNSPECIFIED):
    if not LIVE_COMPOSITE.is_compact(holder._json):
        current = _LEGACY_READS.get()
        for original, payload, budget, record in reversed(current):
            if original is holder:
                digest = sha256()
                for part in json.JSONEncoder(sort_keys=True, separators=(',', ':'), allow_nan=False).iterencode(record):
                    digest.update(part.encode('utf8'))
                yield record
                return
        # Legacy compatibility still funds its explicit complete decode. Fresh
        # compact holders never enter this branch or allocate a JSON body.
        from atlas_tectonics._private.codecs.mesh_tables import _decode_charge
        with workspace(holder._resource, _decode_charge(holder._json)):
            record = holder.record()
            token = _LEGACY_READS.set(current+((holder, holder._json, holder._resource, record),))
            try:
                yield record
            finally:
                _LEGACY_READS.reset(token)
            del record
        return
    record = holder.record()
    if isinstance(record, RecordRef):
        with construction(record.scope, budget=holder._resource):
            with access(record) as value:
                yield value
            record.close()
    else:
        yield record


@contextmanager
def workspace(budget, size):
    owner = Scratch(budget, size)
    try:
        yield owner
    except BaseException:
        raise
    else:
        del owner


def remaining(value, excluded):
    """Preserve untouched metadata as child refs; no whole graph inventory."""
    ref = reference(value)
    if not isinstance(ref, RecordRef):
        return {key: child for key, child in value.items() if key not in excluded}
    # This is only the bounded top-level field list, never history or payload.
    with ref.keys(max_owned_bytes=65536) as keys:
        return {key: ref.field(key) for key in keys.value if key not in excluded}


def graph_identity(value, ordinary):
    ref = reference(value)
    return ref.identity().sha256 if isinstance(ref, RecordRef) else ordinary(value)


def graph_encoding(value, budget, ordinary):
    return (0, 0) if isinstance(reference(value), RecordRef) else ordinary(value, budget)


def graph_encoded(value, ordinary):
    return None if isinstance(reference(value), RecordRef) else ordinary(value)


class _MeshInput:
    """Actual indexed cell rows plus an explicit face-count operand."""
    def __init__(self, mesh):
        from atlas_tectonics._private.integration.heat import indexed_runtime as INDEXED
        self.mesh, self.rows = mesh, INDEXED.mesh_rows(mesh)
        self.required = None

    def __getitem__(self, key):
        if key == 'required_thermal_boundary_faces':
            view = self.mesh._compact
            if not view._required:
                raise KeyError(key)
            if self.required is None:
                from atlas_tectonics._private.codecs.mesh_tables import OwnedRow, _view_allocation
                owner = _view_allocation(view, 65536+256*len(view._arrays['required.face']))
                self.required = OwnedRow([view.face_id(int(index)) for index in view._arrays['required.face']], owner)
            return self.required.value
        # Native heat-plan validation uses only len(metric['faces']).
        return range(self.mesh._compact.face_count) if key == 'faces' else self.rows[key]

    def __contains__(self, key):
        return (self.mesh._compact._required if key == 'required_thermal_boundary_faces'
                else key in ('cells', 'faces') or key in self.rows.header.value)

    def get(self, key, default=None):
        return self[key] if key in self else default


def mesh_input(mesh):
    return _MeshInput(mesh) if mesh.is_compact else mesh.record()


def thermal_geometry(mesh, metric, budget, ordinary):
    return ordinary.from_compact(mesh._compact, budget=budget) if mesh.is_compact else ordinary(metric, budget=budget)


def mesh_value(mesh, metric):
    if not mesh.is_compact:
        return metric
    from atlas_tectonics._private.integration.heat import indexed_runtime as INDEXED
    return INDEXED.stored_mesh(mesh)


def check_cancel(cancel):
    from atlas_tectonics.regional.heat3d import _cancel
    _cancel(cancel)


def _tail(source, name, anchor, scope, replacement):
    """Open one bounded-access scope after all native pre-entry guards."""
    import textwrap
    part = _function_any(source, name)
    at = part.index(anchor)
    prefix, tail = part[:at], part[at:]
    indent = tail[:len(tail)-len(tail.lstrip(' '))]
    tail = tail.replace(anchor, replacement, 1)
    changed = prefix+indent+scope+'\n'+textwrap.indent(tail, '    ')
    return _once(source, part, changed)


def _function_any(source, name):
    matches = [node for node in ast.walk(ast.parse(source))
               if isinstance(node, ast.FunctionDef) and node.name == name]
    node = matches[0]
    return ''.join(source.splitlines(keepends=True)[node.lineno-1:node.end_lineno])
