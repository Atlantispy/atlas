"""Bounded collar adoption access; native equations and issued types remain."""
from contextlib import ExitStack, contextmanager
from hashlib import sha256
from itertools import islice
import json

from compact_contracts import ContractError
from record_views import RecordRef
import live_spatial_patch as L
import spatial_validation_patch as V


class _Rows(V._Rows):
    def __getitem__(self, index):
        if type(index) is not int:
            raise TypeError('an individual collar row index is required')
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
                if child.kind != 'object':
                    raise ContractError('complete finite graph object required')
                value = _Object(child, self.stack)
            else:
                if child.kind != 'array':
                    raise ContractError('complete collar row array required')
                value = _Rows(child)
            self.cache[key] = value
        return super().__getitem__(key)


def _reference(value):
    return value.ref if isinstance(value, V._Object) else L.reference(value)


def _access(value, budget):
    if not isinstance(value, RecordRef):
        return value
    if value.scope.run_budget is not budget:
        raise ContractError('collar record requires its exact run budget')
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
    scopes = [ref.scope for value in values if isinstance(ref := _reference(value), RecordRef)]
    if scopes and any(scope is not scopes[0] for scope in scopes[1:]):
        raise ContractError('collar inputs require one shared retained scope')


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
        graph_ref = _reference(geometry)
        if isinstance(graph_ref, RecordRef) and mesh._compact.scope is not graph_ref.scope:
            raise ContractError('collar graph and mesh require the same retained scope')
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


def collar_source(source):
    source = L._once(source, 'import weakref\n',
        'import weakref\nimport live_collar_patch as LIVE_COLLAR\nimport live_spatial_patch as LIVE_SPATIAL\n')
    source = L._once(source, '        record = graph.record(); clock = source.record()\n',
        '        record = LIVE_COLLAR.graph_rows(graph); clock = source.record()\n')
    source = L._tail(source, 'transport_from_spatial',
        '            geometry, indices = self._spatial_layout(source, graph)\n',
        'with LIVE_COLLAR.layout(self, source, graph) as (geometry, indices):',
        '            LIVE_COLLAR.same_scope(data, geometry)\n')
    old = """                    proposal = finite_proposal.record()
                    extended = proposal['graph']
                    original = dict(extended)
                    original.pop('finite_inventory', None)
                    n, nf = len(geometry['cells']), len(geometry['transfers'])
                    original['cells'], original['transfers'] = extended['cells'][:n], extended['transfers'][:nf]
                    if (original != geometry or proposal['physical_cell_ids'] != [r['cell_id'] for r in geometry['cells']] or
                            any(row.get('kind') != 'inventory' for row in extended['cells'][n:]) or
                            proposal['source_stage_id'] != source.result_id or
                            proposal['transport_parent_id'] != data['state_id'] or
                            extended['finite_inventory']['registry_id'] != self._registry.registry_id or
                            proposal['stocks'] != data['exact_input_stocks']):
                        raise TectonicsError('finite extension changed actual physical graph, parent, source or input stocks')
                    solved_geometry, geometry_id = extended, _hash(extended)
"""
    # Keep the selected proposal alive through the remainder of adoption.
    # The surrounding scope explicitly closes it only on successful return.
    new = """                    proposal = _collar_proposal.enter_context(LIVE_COLLAR.proposal_access(finite_proposal))
                    LIVE_COLLAR.same_scope(proposal, geometry, data)
                    extended = proposal['graph']
                    n = len(geometry['cells'])
                    if (not LIVE_COLLAR.extension_matches(extended, geometry) or proposal['physical_cell_ids'] != [r['cell_id'] for r in geometry['cells']] or
                            any(row.get('kind') != 'inventory' for row in LIVE_COLLAR.inventory_tail(extended['cells'], n)) or
                            proposal['source_stage_id'] != source.result_id or
                            proposal['transport_parent_id'] != data['state_id'] or
                            extended['finite_inventory']['registry_id'] != self._registry.registry_id or
                            not LIVE_COLLAR.equal_records(proposal['stocks'], data['exact_input_stocks'])):
                        raise TectonicsError('finite extension changed actual physical graph, parent, source or input stocks')
                    solved_geometry, geometry_id = extended, LIVE_COLLAR.graph_identity(extended, _hash)
"""
    source = L._once(source, old, new)
    source = L._tail(source, 'transport_from_spatial', '        data = result.record()\n',
        'with LIVE_COLLAR.proposal_stack() as _collar_proposal:',
        '        data = _collar_proposal.enter_context(LIVE_SPATIAL.transport_access(result))\n')
    source = L._once(source,
        "self._budget.reserve(self._work_bytes+8*_width(data), category='regional-collar-spatial-adoption')",
        'LIVE_SPATIAL.workspace(self._budget, self._work_bytes+8*LIVE_COLLAR.width(data, _width))')
    source = L._once(source,
        "data['cell_ids'] != [r['cell_id'] for r in solved_geometry['cells']]",
        "not LIVE_COLLAR.equal_records(data['cell_ids'], [r['cell_id'] for r in solved_geometry['cells']])")
    source = L._tail(source, 'heat_from_spatial',
        '        geometry, transport, thermal = stage.spatial_graph.record(), stage.spatial_result.record(), mesh.record()\n',
        'with LIVE_COLLAR.heat_inputs(stage, mesh) as (geometry, transport, thermal):', '')
    source = L._once(source,
        "self._budget.reserve(self._work_bytes+2*sum(map(_width,\n                    (geometry, transport, thermal))), category='regional-collar-joint-heat-adoption')",
        'LIVE_SPATIAL.workspace(self._budget, self._work_bytes+2*sum(\n'
        '                    LIVE_COLLAR.width(v, _width) for v in (geometry, transport, thermal)))')
    compile(source, '<live-collar>', 'exec')
    return source


@contextmanager
def proposal_stack():
    stack = ExitStack()
    try:
        yield stack
    except BaseException:
        # Do not ExitStack.__exit__ a failed consumer's borrowed fields.
        raise
    else:
        stack.close()
