"""Step 8 finite/dual mutable working rows over immutable compact provenance."""
from contextlib import ExitStack, contextmanager
from copy import deepcopy
from hashlib import sha256
import json

from atlas_tectonics._private.codecs.compact_contracts import ContractError
from atlas_tectonics._private.integration import live_composite as LIVE_COMPOSITE
from atlas_tectonics._private.codecs.record_tables import RecordCodec, Scratch
from atlas_tectonics._private.codecs.record_views import RecordRef, _ObjectRecordRef
from atlas_tectonics._private.integration.geometry import live_spatial_patch as L

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
    from atlas_tectonics.integration.coupling.spatial_reservoir import FiniteStockProposal
    if cls is not FiniteStockProposal:
        raise ContractError('actual native finite proposal class required')
    payload = dict(record)
    if type(payload.get('graph')) is MutableRecord:
        payload['graph'] = dict(payload['graph'])
    # Unchanged graph fields stay borrowed from the live graph record; only
    # the mutated rows and the proposal's own fields are packed.
    packed = LIVE_COMPOSITE.compose_record(payload, record_schema='atlas.finite-spatial-stock-proposal.v1',
                                           scope=scope, check=lambda: None)
    if packed is None:
        packed = RecordCodec().pack_record(payload, record_schema='atlas.finite-spatial-stock-proposal.v1',
                                           scope=scope, check=lambda: None)
    result = object.__new__(cls)
    object.__setattr__(result, '_encoded', packed)
    object.__setattr__(result, '_owner', owner)
    return result


def identity(proposal):
    data = proposal._encoded
    return data.identity().sha256 if LIVE_COMPOSITE.is_compact(data) else sha256(data).hexdigest()


def record(proposal):
    data = proposal._encoded
    if not LIVE_COMPOSITE.is_compact(data):
        return dict(proposal_id=identity(proposal), **json.loads(data))
    base = data.root()
    header = RecordCodec().pack_record(dict(proposal_id=identity(proposal)),
        record_schema='atlas.finite-proposal-header.v1', scope=data.scope, check=data._check)
    return _ObjectRecordRef(base, overlay=header.root())


def graph(proposal):
    if LIVE_COMPOSITE.is_compact(proposal._encoded):
        return proposal._encoded.root().field('graph')
    return json.loads(proposal._encoded)['graph']


def _decode_stocks(rows, decode):
    return {key: tuple(map(decode, values)) for key, values in rows.items()}


def stocks(proposal, decode):
    if not LIVE_COMPOSITE.is_compact(proposal._encoded):
        return _decode_stocks(json.loads(proposal._encoded)['stocks'], decode)
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
    if type(proposal._encoded) is bytes:
        record = json.loads(proposal._encoded)
        detached_graph, rows = record['graph'], record['stocks']
        del record
        return detached_graph, _decode_stocks(rows, decode)
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
    restored = L.VALIDATION.proposal_identity(value)  # restore: the audit's exact-dict proposal
    return L.graph_identity(value, ordinary) if restored is None else restored


def dual_copy(record):
    ref = L.reference(record)
    if not isinstance(ref, RecordRef):
        return deepcopy(record)
    # face intervals are appended to; cells are amended. Exchange rows are
    # read by the native equations and returned separately from provenance.
    return clone_mutable(record, ('cells', 'face_intervals', 'finite_exchange_intervals'),
                         budget=ref.scope.run_budget)
