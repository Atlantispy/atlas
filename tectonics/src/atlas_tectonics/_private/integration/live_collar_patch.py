"""Bounded collar adoption access; native equations and issued types remain."""
from contextlib import ExitStack, contextmanager
from hashlib import sha256
from itertools import islice
import json

from atlas_tectonics._private.codecs.record_views import RecordRef
from atlas_tectonics._private.integration.geometry import live_spatial_patch as L
from atlas_tectonics._private.integration.geometry import spatial_validation_patch as V
from atlas_tectonics.integration.resources import _close_consumed_stack


proposal_stack = _close_consumed_stack


class _Rows(V._Rows):
    def __getitem__(self, index):
        if index < 0:
            index += len(self)
        with self.ref.at(index) as child:
            owned = child.export(max_logical_bytes=V.ROW_BYTES, max_owned_bytes=V.ROW_BYTES)
        return V._OwnedRow(owned.value, owned)


class _Object(L._Object):
    def __getitem__(self, key):
        if key not in self.cache and key in ('graph', 'cells', 'transfers', 'stocks'):
            child = self.ref.field(key)
            self.stack.callback(child.close)
            if key == 'stocks':
                value = child
            elif key == 'graph':
                value = _Object(child, self.stack)
            else:
                value = _Rows(child)
            self.cache[key] = value
        return super().__getitem__(key)


def _reference(value):
    return value.ref if isinstance(value, V._Object) else L.reference(value)


def _access(value, budget):
    if not isinstance(value, RecordRef):
        return value
    stack = ExitStack()
    stack.callback(value.close)
    return _Object(value, stack)


def graph_rows(graph):
    record = graph.record()
    return _access(record, graph._resource) if isinstance(record, RecordRef) else record


def _release(value):
    if isinstance(value, _Object):
        value.cache.clear()
        value.stack.close()


def same_scope(*values):
    [ref.scope for value in values if isinstance(ref := _reference(value), RecordRef)]


@contextmanager
def layout(collar, source, graph):
    record, indices = collar._spatial_layout(source, graph)
    try:
        yield record, indices
    except BaseException:
        # Failed native frames keep their paid field/row owners, unchanged.
        raise
    else:
        _release(record)


@contextmanager
def record_access(value, budget):
    record = _access(value, budget)
    try:
        yield record
    except BaseException:
        raise
    else:
        _release(record)


def proposal_access(proposal):
    return record_access(proposal.record(), proposal._owner._budget)


def _identity(value):
    ref = _reference(value)
    if isinstance(ref, RecordRef):
        return ref.identity().sha256
    return sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def _metadata_identity(value, excluded):
    ref = _reference(value)
    if isinstance(ref, RecordRef):
        with ref.without(excluded) as selected:
            return selected.identity().sha256
    return _identity({k: v for k, v in value.items() if k not in excluded})


def equal_records(left, right):
    if not any(isinstance(_reference(value), RecordRef) for value in (left, right)):
        return left == right
    return _identity(left) == _identity(right)


def _row_identity(rows, index):
    if type(rows) is _Rows:
        with rows.ref.at(index) as row:
            return row.identity().sha256
    return _identity(rows[index])


def extension_matches(extended, geometry):
    """Compare every original field and row without copying an augmented DAG."""
    if type(extended) is dict and type(geometry) is dict:
        original = dict(extended)
        original.pop('finite_inventory', None)
        n, nf = len(geometry['cells']), len(geometry['transfers'])
        original['cells'], original['transfers'] = extended['cells'][:n], extended['transfers'][:nf]
        return original == geometry
    if _metadata_identity(extended, ('finite_inventory', 'cells', 'transfers')) != _metadata_identity(
            geometry, ('cells', 'transfers')):
        return False
    for field in ('cells', 'transfers'):
        first, second = extended[field], geometry[field]
        if len(first) < len(second):
            return False
        for index in range(len(second)):
            if _row_identity(first, index) != _row_identity(second, index):
                return False
    return True


def inventory_tail(rows, start):
    return islice(rows, start, None)


def graph_identity(value, ordinary):
    ref = _reference(value)
    return ref.identity().sha256 if isinstance(ref, RecordRef) else ordinary(value)


def graph_content_identity(value, ordinary):
    """E-22: the finite graph's id in the content form, as the transport's geometry_id is made."""
    return V.content_identity(_reference(value), ordinary)


class _Cell:
    def __init__(self, owned):
        self.owned = owned

    def __getitem__(self, key):
        return self.owned.value[key]


class _Cells:
    def __init__(self, view):
        self.view = view

    def __len__(self):
        return self.view.cell_count

    def __iter__(self):
        for index in range(len(self)):
            yield _Cell(self.view.cell(index))


class _Mesh:
    def __init__(self, mesh):
        self.header, self.cells = mesh.header(), _Cells(mesh._compact)

    def __getitem__(self, key):
        return self.cells if key == 'cells' else self.header.value[key]

    def __contains__(self, key):
        return key == 'cells' or key in self.header.value

    def get(self, key, default=None):
        return self.cells if key == 'cells' else self.header.value.get(key, default)


@contextmanager
def heat_inputs(stage, mesh):
    geometry = graph_rows(stage.spatial_graph)
    if mesh.is_compact:
        _reference(geometry)
        thermal = _Mesh(mesh)
    else:
        thermal = mesh.record()
    transport_stack = ExitStack()
    transport = transport_stack.enter_context(L.transport_access(stage.spatial_result))
    same_scope(geometry, transport)
    try:
        yield geometry, transport, thermal
    except BaseException:
        raise
    else:
        _release(geometry)
        transport_stack.close()
        if type(thermal) is _Mesh:
            thermal.header = None


def width(value, ordinary):
    return 0 if isinstance(_reference(value), RecordRef) or type(value) is _Mesh else ordinary(value)


