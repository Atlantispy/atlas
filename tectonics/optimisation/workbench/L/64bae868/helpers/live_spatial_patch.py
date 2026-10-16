"""Step 8 spatial/heat construction lifetimes; no numerical kernel changes.

Apply these exact source seams after the compact Step 7 transformations. The
shared dictionaries below remain inside their original producer frames; no
new public record or unowned result is issued.
"""
import ast
import sys

import numpy as np

from compact_contracts import ContractError
from content_cache import ChargeSpec, RetainedScope


def _once(source, old, new):
    if source.count(old) != 1:
        raise ValueError('live spatial source seam missing or ambiguous: '+old[:90])
    return source.replace(old, new, 1)


def _function(source, name):
    matches = [node for node in ast.parse(source).body
               if isinstance(node, ast.FunctionDef) and node.name == name]
    if len(matches) != 1:
        raise ValueError('one live spatial function required: '+name)
    return ast.get_source_segment(source, matches[0])


class _FloatSequence:
    """Borrow immutable paid binary64 backing, yielding original Python floats."""
    __slots__ = ('_owner',)

    def __init__(self, array, scope):
        from heat_ledger_tables import _FieldBytes
        if (type(array) is not np.ndarray or array.dtype != np.float64 or
                array.ndim != 1 or not array.flags.c_contiguous or array.flags.writeable or
                not isinstance(scope, RetainedScope) or scope._closed):
            raise ContractError('immutable contiguous native binary64 field required')
        backing = array.base
        for _ in range(8):
            if type(backing) is np.ndarray:
                backing = backing.base
            elif isinstance(backing, memoryview):
                backing = backing.obj
            else:
                break
        if (type(backing) is not _FieldBytes or
                getattr(getattr(backing, '_owner', None), 'scope', None) is not scope):
            raise ContractError('heat public field requires its same-scope paid backing')
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
    if depth > 128:
        raise ContractError('heat metadata container depth exceeds bound')
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


def joined_source(source):
    """Reuse finish's records in the nested account, then release dead inputs.

    The public grouped_account keeps every validation. Its private twin reuses
    the enclosing finish's records with the same checks and exact arithmetic.
    """
    if '_grouped_account_records' in source or 'import live_spatial_patch' in source:
        raise ValueError('live spatial joined source already transformed')
    source = _once(source, 'import private_heat_grouped_account_r1 as ACCOUNT\n',
                   'import private_heat_grouped_account_r1 as ACCOUNT\n'
                   'import live_spatial_patch as LIVE_SPATIAL\n')
    original = _function(source, 'grouped_account')
    shared = _once(original,
        'def grouped_account(value, owner, step, mesh, *, cancel=None):',
        'def _grouped_account_records(value, owner, step, mesh, *, graph, transported, metric, prior, cancel=None):')
    shared = _once(shared,
        '    graph, transported, metric = step.graph.record(), step.result.record(), INDEXED.mesh_rows(mesh)\n', '')
    shared = _once(shared,
        "    prior = owner._bound(step.parent)['projection_accounts']['enthalpy_j']\n", '')
    shared = _once(shared, "        public = value.array('enthalpy_j').tolist()\n",
                   "        public = LIVE_SPATIAL.float_sequence(value.array('enthalpy_j'),\n"
                   "            scope=EXCHANGE_RECORD.required_scope(owner))\n")
    source = _once(source, original, original+'\n\n\n'+shared)
    source = _once(source, '    with grouped_account(heat, owner, step, mesh, cancel=cancel) as grouped:\n',
        '    with _grouped_account_records(heat, owner, step, mesh, graph=graph,\n'
        '            transported=transported, metric=metric,\n'
        "            prior=old['projection_accounts']['enthalpy_j'], cancel=cancel) as grouped:\n")
    source = _once(source, "        accounts = {k: O._enc(v) for k,v in projection.items()}\n",
        "        cells.sort(key=lambda row: row['cell_id'])\n"
        "        accounts = {k: O._enc(v) for k,v in projection.items()}\n")
    source = _once(source,
        "        exact, native, cells = transported['exact_stocks'], collar_advance.state.fields, []\n",
        "        if LIVE_SPATIAL.EARLY_RELEASE:\n"
        "            # Each non-enthalpy projection column was read once, above.\n"
        "            LIVE_SPATIAL.release_columns(transported, 'exact_projection_accounts', keep=('enthalpy_j',))\n"
        "        exact, native, cells = transported['exact_stocks'], collar_advance.state.fields, []\n")
    source = _once(source, "        end = float(O._q(graph['end_time_s']))\n",
        "        if LIVE_SPATIAL.EARLY_RELEASE:\n"
        "            # Stock columns and the thermal lookup end with the cell loop;\n"
        "            # the grouped account still holds both enthalpy slices.\n"
        "            exact = thermal = None\n"
        "            LIVE_SPATIAL.release_columns(transported, 'exact_stocks', keep=('enthalpy_j',))\n"
        "        end = float(O._q(graph['end_time_s']))\n")
    source = _once(source, "thermal_mesh=INDEXED.stored_mesh(mesh), cells=sorted(cells, key=lambda r: r['cell_id']), projection_accounts=accounts)",
                   'thermal_mesh=INDEXED.stored_mesh(mesh), cells=cells, projection_accounts=accounts)')
    source = _once(source, '        state = owner._issue(record)\n',
        '        state = owner._issue(record)\n'
        '        del record, cells, old, metric, thermal, native, exact\n')
    source = _once(source,
        '            check=lambda: R.check(cancel))\n        validate_owner(heat, owner, step, mesh, cancel=cancel)\n',
        '            check=lambda: R.check(cancel))\n'
        '        del exchange, graph, transported\n'
        '        validate_owner(heat, owner, step, mesh, cancel=cancel)\n')
    source = _tail(source, 'grouped_account',
        '    graph, transported, metric = step.graph.record(), step.result.record(), INDEXED.mesh_rows(mesh)\n',
        'with LIVE_SPATIAL.record_access(step.graph, scope=EXCHANGE_RECORD.required_scope(owner)) as graph:',
        '    transported = _live_inputs.enter_context(LIVE_SPATIAL.transport_access(step.result, scope=EXCHANGE_RECORD.required_scope(owner)))\n'
        '    metric = INDEXED.mesh_rows(mesh)\n')
    source = _tail(source, 'finish',
        '    old, graph, transported = owner._bound(step.parent), step.graph.record(), step.result.record()\n',
        'with LIVE_SPATIAL.record_access(step.graph, scope=EXCHANGE_RECORD.required_scope(owner)) as graph:',
        '    old = owner._bound(step.parent)\n'
        '    transported = _live_inputs.enter_context(LIVE_SPATIAL.transport_access(step.result, scope=EXCHANGE_RECORD.required_scope(owner)))\n')
    source = source.replace('with LIVE_SPATIAL.record_access(step.graph, scope=EXCHANGE_RECORD.required_scope(owner)) as graph:',
        'with LIVE_SPATIAL.input_stack() as _live_inputs, LIVE_SPATIAL.record_access(step.graph, scope=EXCHANGE_RECORD.required_scope(owner)) as graph:')
    source = _once(source, 'spatial_graph_id=step.graph.geometry_id, spatial_graph=graph,',
        'spatial_graph_id=step.graph.geometry_id, spatial_graph=LIVE_SPATIAL.reference(graph),')
    source = _once(source, 'transport=transported,', 'transport=LIVE_SPATIAL.reference(transported),')
    compile(source, '<live-spatial-joined>', 'exec')
    return source


def projection_source(source):
    """Share the five float lists already retained by the projection owner."""
    old = """    output = dict(metadata=metadata, arrays=dict(enthalpy_j=list(record['enthalpy_j']),
        temperature_k=list(record['temperature_k']), input_enthalpy_j=list(map(float, arrays[0])),
        input_capacity_j_k=list(map(float, arrays[1])), input_source_w=list(map(float, arrays[2]))))"""
    new = """    # Native projection has already checked and captured these lists. Its
    # owner stays live until the independent immutable snapshot is admitted.
    output = dict(metadata=metadata, arrays=dict(enthalpy_j=record['enthalpy_j'],
        temperature_k=record['temperature_k'], input_enthalpy_j=LIVE_SPATIAL.float_list(arrays[0]),
        input_capacity_j_k=LIVE_SPATIAL.float_list(arrays[1]), input_source_w=LIVE_SPATIAL.float_list(arrays[2])))"""
    source = _once(source, 'import heat_ledger_issuer_patch as HEAT_LEDGER\n',
        'import heat_ledger_issuer_patch as HEAT_LEDGER\nimport live_spatial_patch as LIVE_SPATIAL\n')
    return _once(source, old, new)


def issuer_source(source):
    """End the original call-list lifetime once projection owns its capture."""
    source = _once(source,
        '            cancel=cancel, record_scope=HEAT_LEDGER.verify_scope(call))\n        with projection_owner:\n',
        '            cancel=cancel, record_scope=HEAT_LEDGER.verify_scope(call))\n'
        '        del values\n'
        '        with projection_owner:\n')
    source = _once(source, 'import heat_ledger_issuer_patch as HEAT_LEDGER\n',
        'import heat_ledger_issuer_patch as HEAT_LEDGER\nimport live_spatial_patch as LIVE_SPATIAL\n')
    source = _once(source,
        '        with RESOURCES.decoded(step.graph._json, budget=owner._budget, cancel=cancel) as gv:\n'
        '            g = scope.stack.enter_context(RESOURCES.extracted(gv, _GRAPH_FIELDS,\n'
        '                budget=owner._budget, cancel=cancel)).value\n',
        '        g = scope.stack.enter_context(LIVE_SPATIAL.record_access(step.graph,\n'
        '            scope=HEAT_LEDGER.required_scope((owner,), owner._budget)))\n')
    source = _once(source,
        '        with RESOURCES.decoded(step.result._snapshot._metadata,\n'
        '                               budget=owner._budget, cancel=cancel) as tv:\n'
        '            t = scope.stack.enter_context(RESOURCES.extracted(tv, _TRANSPORT_FIELDS,\n'
        '                budget=owner._budget, cancel=cancel)).value\n',
        '        t = scope.stack.enter_context(LIVE_SPATIAL.transport_access(step.result,\n'
        '            scope=HEAT_LEDGER.required_scope((owner,), owner._budget)))\n')
    source = _once(source, '    if type(snapshot) is HEAT_TABLES.CompactHeatSnapshot:\n',
        '    if LIVE_SPATIAL.is_transport_snapshot(snapshot):\n'
        '        return LIVE_SPATIAL.transport_identity(snapshot, budget, cancel)\n'
        '    if type(snapshot) is HEAT_TABLES.CompactHeatSnapshot:\n')
    return source

# Fresh physical graph/bounds use the caller's one existing scope. Construction
# never installs a cache or creates a new scope on a view or holder.
from contextlib import ExitStack, contextmanager
from contextvars import ContextVar
from hashlib import sha256
import json

import live_composite as LIVE_COMPOSITE
from record_tables import RecordCodec, Scratch
from record_views import CompactRecord, RecordRef
import spatial_validation_patch as VALIDATION

_ACTIVE = ContextVar('live-spatial-construction', default=None)
_LEGACY_READS = ContextVar('live-spatial-lexical-legacy-reads', default=())
_UNSPECIFIED = object()
# Step 8 early releases: the transport advance tail drops its exact rational
# tables once the metadata holds them encoded, and finish releases transport
# columns after their last use instead of at scope exit. Lifetimes only, no
# value changes. Test-only switch for same-source before/after measurement;
# the heat issuer captures it as part of its loaded identity.
EARLY_RELEASE = True
_ROW_FIELDS = frozenset(('cells', 'face_intervals', 'transfers',
    'inactive_zero_measure_cells', 'original_face_intervals',
    'selected_face_representatives'))


@contextmanager
def construction(scope, *, budget):
    if (not isinstance(scope, RetainedScope) or scope._closed or
            scope.run_budget is not budget):
        raise ContractError('fresh spatial construction requires the existing same-budget scope')
    prior = _ACTIVE.get()
    if prior is not None and prior is not scope:
        raise ContractError('fresh spatial construction cannot replace an active scope')
    token = _ACTIVE.set(scope)
    try:
        yield
    finally:
        _ACTIVE.reset(token)


def active_scope(budget):
    scope = _ACTIVE.get()
    if scope is not None and (scope._closed or scope.run_budget is not budget):
        raise ContractError('fresh spatial producer has a foreign or closed scope')
    return scope


def issue(cls, record, budget, ordinary):
    scope = active_scope(budget)
    if scope is None:
        return ordinary(cls, record, budget)
    import live_finite_patch as finite
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


def _compact(payload):
    return type(payload) is CompactRecord or LIVE_COMPOSITE.is_live(payload)


def holder_identity(holder):
    payload = holder._json
    return payload.identity().sha256 if _compact(payload) else sha256(payload).hexdigest()


def holder_record(holder):
    payload = holder._json
    return payload.root() if _compact(payload) else json.loads(payload)


def holder_bytes(holder):
    payload = holder._json
    return payload.identity().canonical_bytes if _compact(payload) else len(payload)


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


def is_rows(value):
    return type(value) is list or type(value) is VALIDATION._Rows


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
            if child.kind != 'array':
                raise ContractError('transport field column requires an array')
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
            if child.kind != 'object':
                raise ContractError('transport exact fields require an object')
            value = _Columns(child, self.stack)
            self.cache[key] = value
        return super().__getitem__(key)


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


@contextmanager
def input_stack():
    stack = ExitStack()
    try:
        yield stack
    except BaseException:
        raise
    else:
        stack.close()


def is_transport_snapshot(value):
    from live_transport_result import CompactTransportSnapshot
    return type(value) is CompactTransportSnapshot


def transport_identity(value, budget, cancel=None):
    from live_transport_result import identity
    return identity(value, budget, cancel=cancel)


@contextmanager
def transport_access(result, *, scope=_UNSPECIFIED):
    if not is_transport_snapshot(result._snapshot):
        from mesh_tables import _decode_charge
        with workspace(result._budget, _decode_charge(result._snapshot._metadata)):
            record = result.record()
            yield record
            del record
        return
    record = result.record()
    if scope is not _UNSPECIFIED and record.scope is not scope:
        raise ContractError('transport result has a foreign retained scope')
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
    if not _compact(holder._json):
        current = _LEGACY_READS.get()
        for original, payload, budget, record in reversed(current):
            if original is holder:
                if holder._json is not payload or holder._resource is not budget:
                    raise ContractError('legacy holder changed during bounded record access')
                digest = sha256()
                for part in json.JSONEncoder(sort_keys=True, separators=(',', ':'), allow_nan=False).iterencode(record):
                    digest.update(part.encode('utf8'))
                if digest.digest() != sha256(payload).digest():
                    raise ContractError('legacy working record changed before nested access')
                yield record
                return
        if len(current) >= 16:
            raise ContractError('legacy spatial access nesting exceeds bound')
        # Legacy compatibility still funds its explicit complete decode. Fresh
        # compact holders never enter this branch or allocate a JSON body.
        from mesh_tables import _decode_charge
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
        if scope is not _UNSPECIFIED and record.scope is not scope:
            raise ContractError('spatial holder has a foreign retained scope')
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
        import private_heat_indexed_runtime as INDEXED
        self.mesh, self.rows = mesh, INDEXED.mesh_rows(mesh)
        self.required = None

    def __getitem__(self, key):
        if key == 'required_thermal_boundary_faces':
            view = self.mesh._compact
            if not view._required:
                raise KeyError(key)
            if self.required is None:
                from mesh_tables import OwnedRow, _view_allocation
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
    if mesh.is_compact and mesh._compact.scope is not None and active_scope(mesh._resource) is not mesh._compact.scope:
        raise ContractError('native heat mesh has a foreign retained scope')
    return _MeshInput(mesh) if mesh.is_compact else mesh.record()


def thermal_geometry(mesh, metric, budget, ordinary):
    return ordinary.from_compact(mesh._compact, budget=budget) if mesh.is_compact else ordinary(metric, budget=budget)


def mesh_value(mesh, metric):
    if not mesh.is_compact:
        return metric
    import private_heat_indexed_runtime as INDEXED
    return INDEXED.stored_mesh(mesh)


def check_cancel(cancel):
    from atlas_tectonics.regional_heat3d import _cancel
    _cancel(cancel)


def _tail(source, name, anchor, scope, replacement):
    """Open one bounded-access scope after all native pre-entry guards."""
    import textwrap
    part = _function_any(source, name)
    if part.count(anchor) != 1:
        raise ValueError('live spatial tail anchor differs: '+name)
    at = part.index(anchor)
    prefix, tail = part[:at], part[at:]
    indent = tail[:len(tail)-len(tail.lstrip(' '))]
    tail = tail.replace(anchor, replacement, 1)
    changed = prefix+indent+scope+'\n'+textwrap.indent(tail, '    ')
    return _once(source, part, changed)


def _function_any(source, name):
    matches = [node for node in ast.walk(ast.parse(source))
               if isinstance(node, ast.FunctionDef) and node.name == name]
    if len(matches) != 1:
        raise ValueError('one live spatial function required: '+name)
    node = matches[0]
    return ''.join(source.splitlines(keepends=True)[node.lineno-1:node.end_lineno])


def _import(source):
    return _once(source, 'import weakref\n',
                 'import weakref\nimport live_spatial_patch as LIVE_SPATIAL\n')


def ale_source(source):
    source = _import(source)
    source = _once(source, 'def _issue(cls, record, budget):\n',
        'def _issue(cls, record, budget):\n'
        '    return LIVE_SPATIAL.issue(cls, record, budget, _legacy_issue)\n\n\n'
        'def _legacy_issue(cls, record, budget):\n')
    if source.count('return hashlib.sha256(self._json).hexdigest()') != 2:
        raise ValueError('native spatial holder identity inventory differs')
    source = source.replace('return hashlib.sha256(self._json).hexdigest()',
                            'return LIVE_SPATIAL.holder_identity(self)')
    if source.count('return json.loads(self._json)') != 2:
        raise ValueError('native spatial holder record inventory differs')
    source = source.replace('return json.loads(self._json)',
                            'return LIVE_SPATIAL.holder_record(self)')
    if source.count('_json: bytes = field(repr=False)') != 2:
        raise ValueError('native spatial holder storage inventory differs')
    source = source.replace('_json: bytes = field(repr=False)',
                            '_json: object = field(repr=False)')
    source = _once(source,
        "result = {k: v for k, v in record.items() if k not in ('cells', 'face_intervals', 'schema')}",
        "result = LIVE_SPATIAL.remaining(record, ('cells', 'face_intervals', 'schema'))")
    source = _once(source, 'original_face_intervals=transfers,',
                   'original_face_intervals=LIVE_SPATIAL.reference(transfers),')
    source = _tail(source, 'close_spatial_ale',
        "    with budget.reserve(65536+8*len(bounds._json), category='spatial-ale-closure'), V._work(tuple(start_volumes_m3.values()), budget):\n",
        'with LIVE_SPATIAL.record_access(bounds) as working:',
        '    with LIVE_SPATIAL.workspace(budget, 65536+8*LIVE_SPATIAL.holder_bytes(bounds)), V._work(tuple(start_volumes_m3.values()), budget):\n')
    source = _once(source, '_close_record(bounds.record(), start_volumes_m3, budget)',
                   '_close_record(working, start_volumes_m3, budget)')
    source = _once(source, '            return _issue(SpatialALEGraph, record, budget)',
        '            result = _issue(SpatialALEGraph, record, budget)\n'
        '            del record\n'
        '            return result')
    compile(source, '<live-spatial-ale>', 'exec')
    return source


def transport_source(source):
    source = _import(source)
    source = _once(source, 'import live_spatial_patch as LIVE_SPATIAL\n',
        'import live_spatial_patch as LIVE_SPATIAL\nimport live_finite_patch as LIVE_FINITE\n'
        'import live_transport_result as LIVE_TRANSPORT\n')
    source = _once(source, 'return dict(result_id=self.result_id, **self._snapshot.descriptor())',
                   'return LIVE_TRANSPORT.result_record(self)')
    source = _once(source, 'snapshot = RegionalMechanicalSnapshot(metadata, projected)',
                   'if LIVE_SPATIAL.EARLY_RELEASE:\n'
                   '                # The metadata now holds every exact table encoded; the\n'
                   '                # rational tuples would otherwise live through the pack.\n'
                   '                del exact_old, exact_new, exact_faces, exact_residual, binary_residual\n'
                   '                del old, new, moved, residual, projection, concentration, densities\n'
                   '            snapshot = LIVE_TRANSPORT.make_snapshot(metadata, projected, self._budget, '
                   'RegionalMechanicalSnapshot, check=lambda: _cancel(cancel))')
    source = _once(source, '_retain(result, 8192+3*_width(metadata)+sum(a.nbytes for a in projected.values()), self._budget)',
                   'LIVE_TRANSPORT.retain(result, 8192+3*_width(metadata)+sum(a.nbytes for a in projected.values()), self._budget, _retain)')
    source = _once(source, 'type(stocks) is not dict',
                   'not LIVE_FINITE.is_stocks(stocks, self._budget)')
    source = _once(source, 'type(budget) is not WorkBudget or type(geometry) is not dict',
                   'type(budget) is not WorkBudget or not LIVE_SPATIAL.is_record(geometry)')
    source = _once(source, 'type(rows) is not list or not rows or type(faces) is not list',
                   'not LIVE_SPATIAL.is_rows(rows) or not rows or not LIVE_SPATIAL.is_rows(faces)')
    source = _once(source, 'encoded_bytes, encoding_scratch = _json_encoding_capacity(geometry, budget)',
                   'encoded_bytes, encoding_scratch = LIVE_SPATIAL.graph_encoding(geometry, budget, _json_encoding_capacity)')
    source = _once(source, 'self._encoded = _json(geometry)',
                   'self._encoded = LIVE_SPATIAL.graph_encoded(geometry, _json)')
    source = _once(source, 'self.geometry_id = hashlib.sha256(self._encoded).hexdigest()',
                   'self.geometry_id = LIVE_SPATIAL.graph_identity(geometry, lambda value: hashlib.sha256(self._encoded).hexdigest())')
    compile(source, '<live-spatial-transport>', 'exec')
    return source


def owner_source(source):
    source = _import(source)
    source = _tail(source, 'close_graph',
        '        r, b = self._bound(state), bounds.record()\n',
        "with LIVE_SPATIAL.record_access(bounds, scope=getattr(self, '_record_scope', None)) as b:",
        '        r = self._bound(state)\n')
    source = _tail(source, 'transport',
        '        g, r = graph.record(), self._bound(state)\n',
        "with LIVE_SPATIAL.record_access(graph, scope=getattr(self, '_record_scope', None)) as g:",
        '        r = self._bound(state)\n')
    source = _tail(source, 'heat',
        '        m, g, t = mesh.record(), step.graph.record(), step.result.record()\n',
        "with LIVE_SPATIAL.input_stack() as _live_inputs, LIVE_SPATIAL.record_access(step.graph, scope=getattr(self, '_record_scope', None)) as g:",
        "        t = _live_inputs.enter_context(LIVE_SPATIAL.transport_access(step.result, scope=getattr(self, '_record_scope', None)))\n"
        '        m = LIVE_SPATIAL.mesh_input(mesh)\n')
    source = _once(source, 'geometry = MimeticGeometry(m, budget=self._budget)',
        'geometry = LIVE_SPATIAL.thermal_geometry(mesh, m, self._budget, MimeticGeometry)')
    source = _tail(source, 'finish',
        '        old, graph, transported = self._bound(step.parent), step.graph.record(), step.result.record()\n',
        "with LIVE_SPATIAL.input_stack() as _live_inputs, LIVE_SPATIAL.record_access(step.graph, scope=getattr(self, '_record_scope', None)) as graph:",
        '        old = self._bound(step.parent)\n'
        "        transported = _live_inputs.enter_context(LIVE_SPATIAL.transport_access(step.result, scope=getattr(self, '_record_scope', None)))\n")
    source = _once(source, 'metric, heat_meta = mesh.record(), heat.descriptor()',
        'metric, heat_meta = LIVE_SPATIAL.mesh_input(mesh), heat.descriptor()')
    source = _once(source, "            exact = transported['exact_stocks']\n",
        "            if LIVE_SPATIAL.EARLY_RELEASE:\n"
        "                # Every projection column was read once, above.\n"
        "                LIVE_SPATIAL.release_columns(transported, 'exact_projection_accounts')\n"
        "            exact = transported['exact_stocks']\n")
    source = _once(source, "            end = float(_q(graph['end_time_s']))\n",
        "            if LIVE_SPATIAL.EARLY_RELEASE:\n"
        "                # Stock columns and the thermal lookup end with the cell loop.\n"
        "                exact = thermal = None\n"
        "                LIVE_SPATIAL.release_columns(transported, 'exact_stocks')\n"
        "            end = float(_q(graph['end_time_s']))\n")
    source = _once(source, "            record = dict(schema='atlas.spatial-exterior-state.v1', owner_id=self.owner_id,",
        "            cells.sort(key=lambda row: row['cell_id'])\n"
        "            record = dict(schema='atlas.spatial-exterior-state.v1', owner_id=self.owner_id,")
    source = _once(source, "thermal_mesh=metric, cells=sorted(cells, key=lambda r: r['cell_id']),",
        'thermal_mesh=LIVE_SPATIAL.mesh_value(mesh, metric), cells=cells,')
    source = _once(source, '            state = self._issue(record)\n',
        '            state = self._issue(record)\n'
        '            del record, cells, old, metric, thermal, native, exact\n')
    source = _once(source, 'spatial_graph_id=step.graph.geometry_id, spatial_graph=graph,',
        'spatial_graph_id=step.graph.geometry_id, spatial_graph=LIVE_SPATIAL.reference(graph),')
    source = _once(source, 'global_transport_id=step.result.result_id, transport=transported,',
        'global_transport_id=step.result.result_id, transport=LIVE_SPATIAL.reference(transported),')
    source = _once(source,
        "            with self._budget.reserve(65536+3*_width(exchange), category='spatial-exchange-encoding'):\n"
        '                result = SpatialExteriorAdvance(state, _json(exchange), step.result, heat)\n'
        '                _retain(result, 8192+len(result._record), self._budget)\n',
        '            if LIVE_SPATIAL.active_scope(self._budget) is not None:\n'
        '                result = _EXCHANGE_RECORD.build_advance(SpatialExteriorAdvance, state, exchange,\n'
        '                    step.result, heat, scope=_EXCHANGE_RECORD.required_scope(self), check=lambda: LIVE_SPATIAL.check_cancel(cancel))\n'
        '            else:\n'
        "                with self._budget.reserve(65536+3*_width(exchange), category='spatial-exchange-encoding'):\n"
        '                    result = SpatialExteriorAdvance(state, _json(exchange), step.result, heat)\n'
        '                    _retain(result, 8192+len(result._record), self._budget)\n'
        '            del exchange, graph, transported\n')
    compile(source, '<live-spatial-owner>', 'exec')
    return source


def differential_source(source):
    """Use the same compact bounds through the original finite/dual closure."""
    source = _import(source)
    source = _once(source, 'import live_spatial_patch as LIVE_SPATIAL\n',
        'import live_spatial_patch as LIVE_SPATIAL\nimport live_finite_patch as LIVE_FINITE\n')
    source = _tail(source, 'close_differential_ale', '    record = bounds.record()\n',
        'with LIVE_SPATIAL.record_access(bounds) as record:',
        '    # The original schema and lineage gates below still precede closure.\n')
    source = _once(source,
        'with budget.reserve(65536+4*len(bounds._json)+4*len(finite_stock_state._encoded),\n'
        "                            category='differential-finite-volume-closure'):",
        'with LIVE_SPATIAL.workspace(budget, 65536+4*LIVE_SPATIAL.holder_bytes(bounds)+4*len(finite_stock_state._encoded)):')
    source = _once(source, 'augmented = json.loads(_encoded(record))',
        "augmented = LIVE_FINITE.clone_mutable(record, ('cells', 'face_intervals', 'finite_exchange_intervals'), budget=budget)")
    source = _once(source, 'bounds_id=bounds_id, bounds=record, finite_stock_state=stock_record,',
        'bounds_id=bounds_id, bounds=LIVE_SPATIAL.reference(record), finite_stock_state=stock_record,')
    source = _once(source, '            return A._issue(A.SpatialALEGraph, result, budget)',
        '            issued_graph = A._issue(A.SpatialALEGraph, result, budget)\n'
        '            del result\n'
        '            return issued_graph')
    compile(source, '<live-spatial-differential>', 'exec')
    return source


