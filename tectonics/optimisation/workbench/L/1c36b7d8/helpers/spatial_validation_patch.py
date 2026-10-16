"""Bounded compact inputs for the unchanged spatial acceptance equations.

These opt-in, exact source transforms do not edit a frozen runtime. Graphs
never become dictionaries: their identity is streamed and their cells are
visited one charged row at a time. Native transport reconstruction is the
explicit 32 MiB owned-export exception. Legacy dictionaries keep their routes.

WP7 must apply joined_source/context_source to its selected helper successors
and adapt the cold bridge plus restored binding restore/validate_for seams.
This component does not claim full cold-checkpoint compatibility by itself.
"""
from contextlib import ExitStack, contextmanager, nullcontext
import ast

from compact_contracts import ContractError
from record_views import RecordRef

SMALL_BYTES = 4 << 20
ROW_BYTES = 4 << 20
TRANSPORT_BYTES = 32 << 20
_GRAPH_FIELDS = frozenset(('graph', 'spatial_graph', 'finite_proposal', 'joined_heat_plan'))
_MARKER = '\nimport spatial_validation_patch as _SV  # compact validation r1\n'


def is_record(value):
    return type(value) is dict or isinstance(value, _Object) or (
        isinstance(value, RecordRef) and value.kind == 'object')


def is_state_record(value):
    if type(value) is dict:
        return True
    from spatial_records_patch import _OwnedDict
    from spatial_indexed_patch import _LogicalRecord
    if type(value) is _OwnedDict:
        if not value._owners:
            return False
        for owner in value._owners:
            owner.value  # Closed backing must refuse before native validation.
        return True
    return type(value) is _LogicalRecord and value._allocation._guard is not None


def _reference(value):
    return value.ref if isinstance(value, _Object) else value


class _Object:
    """Validator-local, non-Mapping accessor; no keys/items/full decode API.

    Only the finite set of fields explicitly requested by the native validator
    is retained. Its scope owns every exported value until that validator ends.
    Cells use a separate row lifetime and are never cached as decoded lists.
    """
    def __init__(self, ref, stack):
        self.ref, self.stack, self.cache = ref, stack, {}

    def __contains__(self, key):
        try:
            child = self.ref.field(key)
        except KeyError:
            return False
        child.close()
        return True

    def __getitem__(self, key):
        if key in self.cache:
            return self.cache[key]
        child = self.ref.field(key)
        self.stack.callback(child.close)
        if key in _GRAPH_FIELDS and child.kind == 'object':
            value = _Object(child, self.stack)
        elif key == 'cells' and child.kind == 'array':
            value = _Rows(child)
        else:
            limit = TRANSPORT_BYTES if key == 'transport' else SMALL_BYTES
            owned = (child.scalar(max_owned_bytes=limit) if child.kind == 'scalar'
                     else child.export(max_logical_bytes=limit, max_owned_bytes=limit))
            self.stack.enter_context(owned)
            value = owned.value
        self.cache[key] = value
        return value

    def get(self, key, default=None):
        try:
            return self[key]
        except KeyError:
            return default


class _Rows:
    """Reiterable row source with at most one decoded row in flight."""
    def __init__(self, ref):
        self.ref = ref

    def __len__(self):
        return self.ref.size

    def __iter__(self):
        with self.ref.iter_rows(max_rows=1, max_owned_bytes=ROW_BYTES) as stream:
            for block in stream:
                with block:
                    row = block.value[0]
                    try:
                        decoded = row.export(max_logical_bytes=ROW_BYTES,
                                             max_owned_bytes=ROW_BYTES)
                        # A caller's loop variable (including a failed
                        # traceback) owns the decoded row beyond generator
                        # resumption. Never credit that backing at yield end.
                        value = _OwnedRow(decoded.value, decoded)
                        yield value
                        value = decoded = None
                    finally:
                        row.close()


class _OwnedRow(dict):
    def __init__(self, value, owner):
        super().__init__(value)
        self._owned = owner


def copy_row(value, **changes):
    if type(value) is not _OwnedRow:
        return dict(value, **changes)
    from content_cache import ChargeSpec
    with value._owned.scope.reserve(ChargeSpec('spatial-row-copy', 4096+256*(len(value)+len(changes))),
                                   required=True) as reservation:
        owner = reservation.commit(None, dependencies=(value._owned,))
    return _OwnedRow(dict(value, **changes), owner)


def rows(value):
    return _Rows(value) if isinstance(value, RecordRef) else value


class _AppendedRows:
    def __init__(self, original):
        self.original, self.added = rows(original), []

    def append(self, row):
        self.added.append(row)

    def __len__(self):
        return len(self.original)+len(self.added)

    def __iter__(self):
        yield from self.original
        yield from self.added


def appendable_rows(value):
    return _AppendedRows(value) if isinstance(value, RecordRef) else list(value)


@contextmanager
def access(*values):
    """Explicit lifetime for requested scalars/fields, never a whole graph."""
    stack = ExitStack()
    converted = tuple(_Object(v, stack) if isinstance(v, RecordRef) else v for v in values)
    try:
        yield converted[0] if len(converted) == 1 else converted
    except BaseException:
        # The failing validation frame can retain raw decoded fields. Keep
        # callbacks/owners reachable through its accessor and this traceback;
        # GC retires them only once the exception is no longer retained.
        raise
    else:
        for value in converted:
            if isinstance(value, _Object) and value.stack is stack:
                value.cache.clear()
        stack.close()


@contextmanager
def transport_access(graph, result):
    """The sole native transport boundary, charged before decoding."""
    ref = _reference(result)
    stack = ExitStack()
    try:
        if isinstance(ref, RecordRef):
            owned = stack.enter_context(ref.export(max_logical_bytes=TRANSPORT_BYTES,
                                                   max_owned_bytes=TRANSPORT_BYTES))
            result = owned.value
        graph = stack.enter_context(access(graph))
        yield graph, result
    except BaseException:
        raise
    else:
        stack.close()


def identity(value, ordinary_hash):
    ref = _reference(value)
    return ref.identity().sha256 if isinstance(ref, RecordRef) else ordinary_hash(value)


def excluded_identity(value, excluded, ordinary_hash):
    ref = _reference(value)
    if not isinstance(ref, RecordRef):
        return ordinary_hash({k: v for k, v in value.items() if k not in excluded})
    selected = ref.without(excluded)
    try:
        return selected.identity().sha256
    finally:
        selected.close()


def exchange_identity(value, state_id, ordinary_hash):
    ref = _reference(value)
    if not isinstance(ref, RecordRef):
        body = {k: v for k, v in value.items() if k not in ('state_id', 'result_id')}
        return ordinary_hash(dict(state_id=state_id, exchange=body))
    # A public LogicalExchange may be an overlay. The explicit projection also
    # handles a full persisted record and preserves missing/extra-field checks.
    from hashlib import sha256
    import record_tables as tables
    body = ref.without(('state_id', 'result_id'))
    try:
        digest = sha256(b'{"exchange":')
        with body.iter_json() as stream:
            for block in stream:
                with block:
                    digest.update(block.value)
        digest.update(b',"state_id":'+tables.canonical(state_id)+b'}')
        return digest.hexdigest()
    finally:
        body.close()


def native_width(value, ordinary_width):
    # All compact exports above are already reserved by their ownership scope.
    # Native equation workspaces and numerical output reservations stay intact.
    return 0 if isinstance(_reference(value), RecordRef) else ordinary_width(value)


def encoding_capacity(value, budget, ordinary_capacity):
    return (0, 0) if isinstance(_reference(value), RecordRef) else ordinary_capacity(value, budget)


def codec_scope(value, budget, cancel, ordinary_codec):
    return nullcontext() if isinstance(_reference(value), RecordRef) else ordinary_codec(
        value, budget=budget, cancel=cancel)


def _replace(source, old, new, count=1):
    if source.count(old) != count:
        raise ContractError('compact validation source anchor differs: '+old[:160])
    return source.replace(old, new)


def _function(source, name, changes=(), *, scope=None):
    """Edit exactly one function and retain all untouched acceptance code."""
    nodes = [n for n in ast.walk(ast.parse(source))
             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name]
    if len(nodes) != 1:
        raise ContractError('compact validation function anchor differs: '+name)
    node = nodes[0]
    lines = source.splitlines(keepends=True)
    part = ''.join(lines[node.lineno-1:node.end_lineno])
    for change in changes:
        part = _replace(part, *change)
    if scope is not None:
        # Retain the docstring; place the ownership scope before the first
        # executable statement. Reparse after substitutions for exact offsets.
        import textwrap
        parsed = ast.parse(textwrap.dedent(part)).body[0]
        first = parsed.body[0]
        if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
            first = parsed.body[1]
        split = part.splitlines(keepends=True)
        indent = ' '*(node.col_offset+4)
        start = first.lineno-1
        part = ''.join(split[:start])+indent+scope+'\n'+''.join('    '+line if line.strip() else line for line in split[start:])
    lines[node.lineno-1:node.end_lineno] = [part]
    return ''.join(lines)


def _finish(source):
    if _MARKER in source:
        raise ContractError('compact validation transform already applied')
    result = source.rstrip()+_MARKER
    ast.parse(result)
    return result


def owner_source(source):
    if 'from spatial_transfer import validate_projected_payload' in source:
        source = _function(source, 'restore', (
            ("for row in body['cells']:", "for row in _SV.rows(body['cells']):"),
            ('type(record) is not dict', 'not _SV.is_state_record(record)'),
        ))
        source = _replace(source, 'from spatial_transfer import validate_projected_payload',
                          'from spatial_indexed_patch import validate_projected_payload')
        source = _function(source, '_check_measures', (
            ("cells = list(record['cells'])", "cells = _SV.appendable_rows(record['cells'])"),
        ))
        source = _function(source, '_carried_start_cells', (
            ("previous = {row['cell_id']: row for row in state['cells']}",
             "previous = {row['cell_id']: row for row in _SV.rows(state['cells'])}"),
            ('carried[child] = dict(old, cell_id=child)',
             'carried[child] = _SV.copy_row(old, cell_id=child)'),
        ))
        source = _function(source, 'from_saved', (
            ("for row in initial_record['cells']:", "for row in _SV.rows(initial_record['cells']):", 2),
        ))
    source = _function(source, '_validate_heat_plan', (
        ('type(definition) is dict and _hash(definition)',
         '_SV.is_record(definition) and _SV.identity(definition, _hash)'),
    ), scope='with _SV.access(definition, heat_record) as (definition, heat_record):')
    source = _function(source, 'validate_exchange', (
        ('type(exchange) is dict', '_SV.is_record(exchange)'),
        ('type(exchange) is not dict', 'not _SV.is_record(exchange)'),
        ("_hash(exchange['spatial_graph'])", "_SV.identity(exchange['spatial_graph'], _hash)"),
        ("body = {k: v for k, v in exchange.items() if k not in ('state_id', 'result_id')}",
         'body = _SV.exchange_identity(exchange, state.state_id, _hash)'),
        ('_hash(dict(state_id=state.state_id, exchange=body))', 'body'),
        ('3*_width(exchange)', '3*_SV.native_width(exchange, _width)'),
        ('type(finite) is not dict', 'not _SV.is_record(finite)'),
        ("for cell in r['cells']:", "for cell in _SV.rows(r['cells']):"),
    ), scope='with _SV.access(exchange) as exchange:')
    return _finish(source)


def indexed_owner_source(source):
    """Native restore gates after the existing indexed-state transform."""
    return owner_source(source)


def reservoir_source(source):
    source = _function(source, 'validate_saved', (
        ('8*sum(map(_width, (state_record, proposal_record, transport_record)))',
         '8*sum(_SV.native_width(v, _width) for v in (state_record, proposal_record, transport_record))'),
        ('type(proposal_record) is not dict', 'not _SV.is_record(proposal_record)'),
        ("_hash({k: v for k, v in proposal_record.items() if k != 'proposal_id'})",
         "_SV.excluded_identity(proposal_record, ('proposal_id',), _hash)"),
    ), scope='with _SV.transport_access(proposal_record, transport_record) as (proposal_record, transport_record):')
    source = _function(source, '_finished_record', (
        ("_hash(p['graph'])", "_SV.identity(p['graph'], _hash)"),
    ), scope='with _SV.transport_access(p, r) as (p, r):')
    return _finish(source)


def measures_source(source):
    source = _function(source, 'transport_audit', (
        ('_json_encoding_capacity(graph, budget)', '_SV.encoding_capacity(graph, budget, _json_encoding_capacity)'),
    ), scope='with _SV.transport_access(graph, result) as (graph, result):')
    source = _function(source, '_transport_audit', (
        ("hashlib.sha256(json.dumps(graph, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()",
         "_SV.identity(graph, lambda value: hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest())"),
    ), scope='with _SV.transport_access(graph, result) as (graph, result):')
    source = _function(source, '_dual_audit_capacity', (),
                       scope='with _SV.transport_access(graph, result) as (graph, result):')
    return _finish(source)


def workflow_source(source):
    source = _function(source, '_check_certification_records', (
        ("_hash(graph) != s['graph_id']", "_SV.identity(graph, _hash) != s['graph_id']"),
    ), scope='with _SV.access(graph) as graph:')
    # This exact scope retains graph fields through certification and releases
    # them before _refresh returns, including all refusal paths.
    start = "                            graph = exchange['spatial_graph']\n"
    call_anchor = "                            self._restore_certification(previous['differential_certification'], certification_arrays,\n"
    if source.count(start) != 1 or source.count(call_anchor) != 1:
        raise ContractError('compact refresh graph block anchor differs')
    left = source.index(start)
    call_line = source[:source.index(call_anchor, left)].count('\n')+1
    calls = [node for node in ast.walk(ast.parse(source)) if isinstance(node, ast.Call)
             and node.lineno == call_line and isinstance(node.func, ast.Attribute)
             and node.func.attr == '_restore_certification']
    if len(calls) != 1:
        raise ContractError('compact refresh certification call extent differs')
    right = sum(len(line) for line in source.splitlines(keepends=True)[:calls[0].end_lineno])
    block = source[left:right].replace(start,
        "                            graph = _validation_exchange['spatial_graph']\n", 1)
    source = source[:left]+"                            with _SV.access(exchange) as _validation_exchange:\n"+''.join(
        '    '+line if line.strip() else line for line in block.splitlines(keepends=True))+source[right:]
    return _finish(source)


def joined_source(source):
    # A bounded plan export is deliberately explicit. The original target
    # provenance check still receives its exact unchanged native dictionary.
    source = _function(source, 'validate_plan', (),
        scope='with _SV.access(definition, header) as (definition, header):')
    source = _function(source, 'validate_plan', (
        ('type(definition) is not dict', 'not _SV.is_record(definition)'),
        ('sha256(_json(definition)).hexdigest()',
         '_SV.identity(definition, lambda value: sha256(_json(value)).hexdigest())'),
    ))
    source = _function(source, 'validate_saved_exchange', (),
        scope='with _SV.access(exchange) as exchange:')
    return _finish(source)


def context_source(source):
    """For WP7's selected restored-binding successor, never modify r9 in place."""
    source = _function(source, '_context', (
        ('R.codec_for_value(exchange, budget=budget, cancel=cancel)',
         '_SV.codec_scope(exchange, budget, cancel, R.codec_for_value)'),
        ("body = {k: v for k,v in exchange.items() if k not in ('state_id','result_id')}",
         'body = _SV.exchange_identity(exchange, state.state_id, lambda value: R.stream_hash(value, cancel))'),
        ('type(finite) is not dict or type(finite.get(\'graph\')) is not dict',
         "not _SV.is_record(finite) or not _SV.is_record(finite.get('graph'))"),
        ("R.stream_hash(finite['graph'], cancel)",
         "_SV.identity(finite['graph'], lambda value: R.stream_hash(value, cancel))"),
        ('R.stream_hash(dict(state_id=state.state_id, exchange=body), cancel)', 'body'),
        ('R.stream_hash(graph, cancel)', '_SV.identity(graph, lambda value: R.stream_hash(value, cancel))'),
    ))
    # Returned plan/ref are native owned exports. Their lifetime must be the
    # caller's existing work stack, because _context's result escapes.
    source = _function(source, '_context', (
        ('    _verify(execution, cancel)\n',
         '    exchange = work.stack.enter_context(_SV.access(exchange))\n    _verify(execution, cancel)\n'),
    ))
    return _finish(source)
