"""WP5 fresh exchange packaging and native holder source seams.

The numerical finish body stays unchanged. The caller must attach its existing
retained scope explicitly; this module neither creates scopes nor composes a
runtime. WP7 registers producer_source and WP8 attaches owner._record_scope.
"""
from hashlib import sha256
import json

from compact_contracts import ContractError
from content_cache import RetainedScope
import live_composite as LIVE_COMPOSITE
from record_tables import RecordCodec
from record_views import CompactRecord, LogicalExchange


BODY_SCHEMA = 'atlas.spatial-exchange-body.v1'
MAX_HEADER_BYTES = 4 << 20
HEADER_FIELDS = ('result_id', 'state_id', 'schema', 'owner_id', 'parent_state_id',
    'collar_state_id', 'source_flow_stage_id', 'source_audit_id', 'spatial_graph_id',
    'global_transport_id', 'joined_heat_id', 'heat_boundary_account',
    'heat_projection_rule', 'physical_geometry')
JOINED_SHA = 'eed99e320c981867eec67fabba2b6061f1996b91fbfe10a6f765ab88d6765324'
INDEXED_JOINED_SHA = 'a9e0c241861e059907e818ea3c16e3732d48505205ac8819984b74250a3cd420'
OWNER_SHA = '0973cb3f0bccc833f476bbfa555864d62a6f906035b871f73e9d8a9c1ded9559'
INDEXED_OWNER_SHA = 'dc79b4b942bd6b34ecca0a04068b6ebfd5732dc72bac7a916469b9239ca0878c'


def required_scope(owner):
    """No creation, ancestry guessing, alternate epoch or duplicate cache."""
    scope = getattr(owner, '_record_scope', None)
    if (not isinstance(scope, RetainedScope) or scope._closed or
            scope.run_budget is not owner._budget):
        raise ContractError('fresh exchange requires the existing owner record scope')
    return scope


def build_advance(advance_type, state, exchange, transport, heat, *, scope, check):
    """Pack only native fields; borrow live graph/transport/proposal records.

    The caller already owns the native producer dictionaries. A value that
    holds RecordRefs from live holders (the compact graph, transport result and
    finite proposal) is issued as a small packed skeleton plus paid borrows of
    those records, so no second copy of them is built while they stay live.
    Native-only values keep the unchanged single exact pack. Builder scratch
    and the escaping columns are separately charged. Exceptional frames retain
    their owners until released; no finally block credits live traceback data.
    """
    if not isinstance(scope, RetainedScope) or scope._closed:
        raise ContractError('fresh exchange requires an open retained scope')
    if getattr(state, '_budget', None) is not scope.run_budget:
        raise ContractError('fresh exchange state has a foreign resource owner')
    if type(exchange) is not dict or 'state_id' in exchange or 'result_id' in exchange:
        raise ContractError('fresh exchange must be an unwrapped native body')
    check()
    # The holder caches only its composite result ID, so the body identity
    # is not streamed here (a whole extra pass over graph and transport).
    packed = LIVE_COMPOSITE.compose_record(exchange, record_schema=BODY_SCHEMA, scope=scope,
                                           check=check, eager_identity=False)
    if packed is None:
        packed = RecordCodec().pack_record(exchange, record_schema=BODY_SCHEMA,
                                          scope=scope, check=check)
    result = advance_type(state, packed, transport, heat)
    check()
    return result


def _compact(record):
    return isinstance(record, CompactRecord) or LIVE_COMPOSITE.is_live(record)


def initialise(holder):
    """Cache the exact composite identity once, without body materialisation."""
    if _compact(holder._record):
        if holder._record.scope.run_budget is not holder.state._budget:
            raise ContractError('exchange holder has a foreign resource owner')
        body = (LogicalExchange(holder._record, holder._record._root)
                if isinstance(holder._record, CompactRecord) else holder._record.root())
        try:
            result_id = body.composite_identity(holder.state.state_id).sha256
        except BaseException:
            # Keep the charged body borrow in the traceback that still owns it.
            raise
        else:
            body.close()
        object.__setattr__(holder, '_result_id', result_id)


def result_id(holder, ordinary_hash):
    if _compact(holder._record):
        holder._record._live()
        return holder._result_id
    return ordinary_hash(dict(state_id=holder.state.state_id,
                              exchange=json.loads(holder._record)))


def record(holder, ordinary_hash):
    if _compact(holder._record):
        return LogicalExchange.from_body(holder._record, state_id=holder.state.state_id,
                                         result_id=result_id(holder, ordinary_hash))
    return dict(result_id=result_id(holder, ordinary_hash), state_id=holder.state.state_id,
                **json.loads(holder._record))


def header(holder, *, fields=HEADER_FIELDS):
    """A paid bounded metadata export; large children cannot sneak through."""
    if not _compact(holder._record):
        raise ContractError('owned exchange header requires a compact holder')
    if type(fields) not in (tuple, list) or any(name not in HEADER_FIELDS for name in fields):
        raise ContractError('exchange header contains an unapproved field')
    full = LogicalExchange.from_body(holder._record, state_id=holder.state.state_id,
                                     result_id=holder._result_id)
    for name in fields:
        child = full.field(name)
        if child.kind != 'scalar':
            raise ContractError('exchange header field is not a scalar')
        child.close()
    selected = full.select(fields)
    try:
        held = selected.export(max_logical_bytes=MAX_HEADER_BYTES,
                               max_owned_bytes=MAX_HEADER_BYTES)
    except BaseException:
        raise
    else:
        selected.close()
        full.close()
        return held


def close(holder):
    if _compact(holder._record):
        holder._record.close()


def _replace(source, old, new):
    if source.count(old) != 1:
        raise ValueError('exchange source seam missing or ambiguous: '+old[:80])
    return source.replace(old, new, 1)


def _source(source, allowed):
    if type(source) is not str or sha256(source.encode()).hexdigest() not in allowed:
        raise ValueError('exchange source differs from exact reviewed predecessor')


_HOLDER_OLD = '''    @property
    def result_id(self):
        return _hash(dict(state_id=self.state.state_id, exchange=json.loads(self._record)))

    def record(self):
        return dict(result_id=self.result_id, state_id=self.state.state_id, **json.loads(self._record))
'''
_HOLDER_NEW = '''    _result_id: str | None = field(default=None, init=False, repr=False, compare=False)

    def __post_init__(self):
        _EXCHANGE_RECORD.initialise(self)

    @property
    def result_id(self):
        return _EXCHANGE_RECORD.result_id(self, _hash)

    def record(self):
        return _EXCHANGE_RECORD.record(self, _hash)

    def header(self, *, fields=_EXCHANGE_RECORD.HEADER_FIELDS):
        return _EXCHANGE_RECORD.header(self, fields=fields)

    def close(self):
        _EXCHANGE_RECORD.close(self)
'''


def holder_source(source):
    """Apply before WP6 validation transforms, after indexed state if enabled."""
    _source(source, (OWNER_SHA, INDEXED_OWNER_SHA))
    source = _replace(source, 'import weakref\n',
                      'import weakref\nimport exchange_record_patch as _EXCHANGE_RECORD\n')
    source = _replace(source, '    _record: bytes = field(repr=False)\n',
                      '    _record: object = field(repr=False)\n')
    return _replace(source, _HOLDER_OLD, _HOLDER_NEW)


_PRODUCER_OLD = '''        with owner._budget.reserve(65536+3*O._width(exchange), category='spatial-exchange-encoding'):
            result = O.SpatialExteriorAdvance(state, O._json(exchange), step.result, heat)
            O._retain(result, 8192+len(result._record), owner._budget)
'''
_PRODUCER_NEW = '''        result = EXCHANGE_RECORD.build_advance(O.SpatialExteriorAdvance, state, exchange,
            step.result, heat, scope=EXCHANGE_RECORD.required_scope(owner),
            check=lambda: R.check(cancel))
'''


def producer_source(source):
    """Hook for WP7; authenticate raw r6 or its exact indexed-mesh successor."""
    _source(source, (JOINED_SHA, INDEXED_JOINED_SHA))
    source = _replace(source, 'import private_heat_grouped_account_r1 as ACCOUNT\n',
        'import private_heat_grouped_account_r1 as ACCOUNT\n'
        'import exchange_record_patch as EXCHANGE_RECORD\n')
    return _replace(source, _PRODUCER_OLD, _PRODUCER_NEW)
