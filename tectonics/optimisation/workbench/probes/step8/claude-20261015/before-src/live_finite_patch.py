"""Step 8 finite/dual mutable working rows over immutable compact provenance."""
from contextlib import ExitStack, contextmanager
from copy import deepcopy
import ast
from hashlib import sha256
import json

from compact_contracts import ContractError
from record_tables import RecordCodec, Scratch
from record_views import CompactRecord, RecordRef, _ObjectRecordRef
import live_spatial_patch as L

MAX_MUTABLE_BYTES = 64 << 20


class MutableRecord(dict):
    def __init__(self, value, owners, budget):
        super().__init__(value)
        self._owners = owners
        self._budget = budget


def clone_mutable(value, fields, *, budget):
    """Detach only row collections that the physical calculation mutates."""
    ref = L.reference(value)
    if not isinstance(ref, RecordRef):
        return deepcopy(value)
    if ref.scope.run_budget is not budget:
        raise ContractError('mutable finite graph requires its exact run budget')
    with ref.keys(max_owned_bytes=65536) as keys:
        names = keys.value
        owners = [Scratch(budget, 65536+512*len(names))]
        result = {}
        for name in names:
            child = ref.field(name)
            if name in fields:
                held = child.export(max_logical_bytes=MAX_MUTABLE_BYTES,
                                    max_owned_bytes=MAX_MUTABLE_BYTES)
                owners.append(held)
                result[name] = held.value
                child.close()
            else:
                result[name] = child
    return MutableRecord(result, owners, budget)


@contextmanager
def graph_input(value, *, budget):
    ref = L.reference(value)
    if isinstance(ref, RecordRef):
        with L.construction(ref.scope, budget=budget), L.access(ref) as selected:
            yield selected
    else:
        yield value


def clone_graph(value, budget, owned, ordinary):
    if isinstance(L.reference(value), RecordRef):
        return clone_mutable(value, ('cells', 'transfers'), budget=budget)
    return ordinary(value, budget, owned)


def issue(cls, record, owner, ordinary):
    scope = L.active_scope(owner._budget)
    if scope is None or cls.__name__ != 'FiniteStockProposal':
        return ordinary(cls, record, owner)
    from atlas_tectonics.integration_spatial_reservoir import FiniteStockProposal
    if cls is not FiniteStockProposal:
        raise ContractError('actual native finite proposal class required')
    payload = dict(record)
    if type(payload.get('graph')) is MutableRecord:
        payload['graph'] = dict(payload['graph'])
    packed = RecordCodec().pack_record(payload, record_schema='atlas.finite-spatial-stock-proposal.v1',
                                       scope=scope, check=lambda: None)
    result = object.__new__(cls)
    object.__setattr__(result, '_encoded', packed)
    object.__setattr__(result, '_owner', owner)
    return result


def identity(proposal):
    data = proposal._encoded
    return data.identity().sha256 if type(data) is CompactRecord else sha256(data).hexdigest()


def record(proposal):
    data = proposal._encoded
    if type(data) is not CompactRecord:
        return dict(proposal_id=identity(proposal), **json.loads(data))
    base = data.root()
    header = RecordCodec().pack_record(dict(proposal_id=identity(proposal)),
        record_schema='atlas.finite-proposal-header.v1', scope=data.scope, check=data._check)
    return _ObjectRecordRef(base, overlay=header.root())


def graph(proposal):
    if type(proposal._encoded) is CompactRecord:
        return proposal._encoded.root().field('graph')
    return json.loads(proposal._encoded)['graph']


def stocks(proposal, decode):
    if type(proposal._encoded) is not CompactRecord:
        return {key: tuple(map(decode, values))
                for key, values in json.loads(proposal._encoded)['stocks'].items()}
    with proposal._encoded.root().field('stocks') as ref:
        held = ref.export(max_logical_bytes=MAX_MUTABLE_BYTES, max_owned_bytes=MAX_MUTABLE_BYTES)
    # The caller receives an owned dictionary: converted exact arithmetic and
    # its input export stay funded for the actual result lifetime.
    owner = Scratch(proposal._owner._budget, 65536+16*len(json.dumps(held.value)))
    return MutableRecord({key: tuple(map(decode, values)) for key, values in held.value.items()},
                         [held, owner], proposal._owner._budget)


def is_stocks(value, budget):
    return type(value) is dict or (type(value) is MutableRecord and value._budget is budget
                                  and bool(value._owners))


def transport_inputs(proposal, decode):
    ref = graph(proposal)
    if not isinstance(ref, RecordRef):
        return ref, stocks(proposal, decode)
    stack = ExitStack()
    stack.callback(ref.close)
    return L._Object(ref, stack), stocks(proposal, decode)


def width(value, ordinary):
    ref = L.reference(value)
    return ref.identity().canonical_bytes if isinstance(ref, RecordRef) else ordinary(value)


def graph_hash(value, ordinary):
    return L.graph_identity(value, ordinary)


def dual_copy(record):
    ref = L.reference(record)
    if not isinstance(ref, RecordRef):
        return deepcopy(record)
    # face intervals are appended to; cells are amended. Exchange rows are
    # read by the native equations and returned separately from provenance.
    return clone_mutable(record, ('cells', 'face_intervals', 'finite_exchange_intervals'),
                         budget=ref.scope.run_budget)


def _once(source, old, new):
    if source.count(old) != 1:
        raise ValueError('finite source boundary differs: '+old[:80])
    return source.replace(old, new, 1)


def _method(source, class_name, method_name, replacement):
    tree = ast.parse(source)
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == class_name)
    node = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == method_name)
    old = ''.join(source.splitlines(keepends=True)[node.lineno-1:node.end_lineno])
    return _once(source, old, replacement)


def reservoir_source(source):
    source = _once(source, 'import weakref\n',
        'import weakref\nimport live_finite_patch as LIVE_FINITE\nimport live_spatial_patch as LIVE_SPATIAL\n')
    source = _once(source, 'def _clone_graph(record, budget, owned):\n',
        'def _clone_graph(record, budget, owned):\n'
        '    return LIVE_FINITE.clone_graph(record, budget, owned, _legacy_clone_graph)\n\n\n'
        'def _legacy_clone_graph(record, budget, owned):\n')
    source = _once(source, 'def _issue(cls, record, owner):\n',
        'def _issue(cls, record, owner):\n'
        '    return LIVE_FINITE.issue(cls, record, owner, _legacy_issue)\n\n\n'
        'def _legacy_issue(cls, record, owner):\n')
    source = _once(source, 'def _hash(value):\n',
        'def _hash(value):\n    return LIVE_FINITE.graph_hash(value, _legacy_hash)\n\n\n'
        'def _legacy_hash(value):\n')
    for name, body in (
        ('proposal_id', 'return LIVE_FINITE.identity(self)'),
        ('record', 'return LIVE_FINITE.record(self)'),
        ('graph', 'return LIVE_FINITE.graph(self)'),
        ('stocks', 'return LIVE_FINITE.stocks(self, _q)'),
        ('_transport_inputs', 'return LIVE_FINITE.transport_inputs(self, _q)')):
        source = _method(source, 'FiniteStockProposal', name,
                         '    def '+name+'(self):\n        '+body+'\n')
    source = _once(source, '    def prepare(self, state, physical_graph, physical_stocks, exchanges, *, source_stage_id,\n',
        '    def prepare(self, state, physical_graph, physical_stocks, exchanges, *, source_stage_id,\n'
        '                transport_parent_id=None):\n'
        '        with LIVE_FINITE.graph_input(physical_graph, budget=self._budget) as graph:\n'
        '            return self._prepare_live(state, graph, physical_stocks, exchanges,\n'
        '                source_stage_id=source_stage_id, transport_parent_id=transport_parent_id)\n\n'
        '    def _prepare_live(self, state, physical_graph, physical_stocks, exchanges, *, source_stage_id,\n')
    source = _once(source, 'type(exchanges) is not list or type(physical_graph) is not dict',
                   'type(exchanges) is not list or not LIVE_SPATIAL.is_record(physical_graph)')
    source = L._tail(source, 'finish',
        '        p, r = proposal.record(), result.record()\n',
        'with LIVE_SPATIAL.access(proposal.record()) as p, LIVE_SPATIAL.access(result.record()) as r:',
        '')
    source = _once(source, '_width(p)+_width(r)',
                   'LIVE_FINITE.width(p, _width)+LIVE_FINITE.width(r, _width)')
    compile(source, '<live-finite-reservoir>', 'exec')
    return source


def dual_source(source):
    source = _once(source, 'from copy import deepcopy\n',
                   'from copy import deepcopy\nimport live_finite_patch as LIVE_FINITE\n')
    source = _once(source, '    result = deepcopy(record)\n',
                   '    result = LIVE_FINITE.dual_copy(record)\n')
    compile(source, '<live-finite-dual>', 'exec')
    return source
