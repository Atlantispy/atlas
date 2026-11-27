"""WP5 fresh exchange packaging and native holder source seams.

The numerical finish body stays unchanged. The caller must attach its existing
retained scope explicitly; this module neither creates scopes nor composes a
runtime. WP8 attaches owner._record_scope.
"""
from hashlib import sha256
import json

from atlas_tectonics._private.integration import live_composite as LIVE_COMPOSITE
from atlas_tectonics._private.codecs.record_tables import RecordCodec, canonical
from atlas_tectonics._private.codecs.record_views import CompactRecord, LogicalExchange


BODY_SCHEMA = 'atlas.spatial-exchange-body.v1'
MAX_HEADER_BYTES = 4 << 20
HEADER_FIELDS = ('result_id', 'state_id', 'schema', 'owner_id', 'parent_state_id',
    'collar_state_id', 'source_flow_stage_id', 'source_audit_id', 'spatial_graph_id',
    'global_transport_id', 'joined_heat_id', 'heat_boundary_account',
    'heat_projection_rule', 'physical_geometry')


def required_scope(owner):
    """No creation, ancestry guessing, alternate epoch or duplicate cache."""
    scope = getattr(owner, '_record_scope', None)
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
    check()
    # The holder caches only its composite result ID, so the body identity
    # is not streamed here (a whole extra pass over graph and transport).
    packed = LIVE_COMPOSITE.compose_record(exchange, record_schema=BODY_SCHEMA, scope=scope,
                                           check=check, eager_identity=False)
    if packed is None:
        packed = _pack_with_composite(exchange, state.state_id, scope, check)
    result = advance_type(state, packed, transport, heat)
    check()
    return result


def _pack_with_composite(exchange, state_id, scope, check):
    """Pack the body and hash its composite identity in the same pass, so
    initialise need not stream the body again."""
    also = sha256(b'{"exchange":')
    packed = RecordCodec().pack_record(exchange, record_schema=BODY_SCHEMA,
                                      scope=scope, check=check, also=also)
    also.update(b',"state_id":'+canonical(state_id)+b'}')
    packed._composite = (state_id, also.hexdigest())
    return packed


def _compact(record):
    return isinstance(record, CompactRecord) or LIVE_COMPOSITE.is_live(record)


def initialise(holder):
    """Cache the exact composite identity once, without body materialisation."""
    if _compact(holder._record):
        composite = getattr(holder._record, '_composite', None)
        if composite is not None and composite[0] == holder.state.state_id:
            object.__setattr__(holder, '_result_id', composite[1])
            return
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
    full = LogicalExchange.from_body(holder._record, state_id=holder.state.state_id,
                                     result_id=holder._result_id)
    for name in fields:
        child = full.field(name)
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
