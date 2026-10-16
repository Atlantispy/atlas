"""Explicit compact-support retention at native routing/scheduling boundaries.

Runtime helpers for the text edits in partition_routing_transform. Not a
replacement scientific issuer: every numerical call receives an actual native
DifferentialSupport with the identical canonical bytes (identity checked).
Only retained routing definitions/handles are DAG references. A failed query
is replayed from the arena's prepaid two-operand capacity, with no reservation
after the refusal. Worker input copies have their own retained charges; native
source/request/result binding, transport ceilings, worker adoption and
cancellation are unchanged. A plain native support or partition takes the
original statements: no new decode, reservation or retained object.
"""
from dataclasses import dataclass
from hashlib import sha256
import sys

import mesh_tables as M
import partition_native_patch as P
from partition_tables import NodeRef, LIST, OBJECT, MAX_DEPTH


HEADER = ('interval_id', 'start_time_s', 'end_time_s')
CONTINUATION_FIELDS = ('scope', 'interval_id', 'endpoint_network_id', 'end_time_s')


def _routing():
    from atlas_tectonics import integration_routing_views as R
    return R


@dataclass(frozen=True, slots=True, init=False, eq=False)
class CompactSupport:
    """Private retained reference, deliberately NOT a native issued support.

    Identity semantics (eq=False): the owned header holds a dict, and two
    handles of one support are distinct owners, not equal values.
    """
    _ref: NodeRef
    _resource: object
    support_id: str
    encoded_size: int
    decoded_capacity: int
    _header: object
    _owner: object

    def __init__(self, *args, **kwargs):
        raise TypeError('retain an actual native compact support')


def _bound_ref(support):
    """The validated compact reference of an actual native support, or None."""
    D = P._native()
    if type(support) is not D.DifferentialSupport:
        raise TypeError('actual native differential support required')
    ref = getattr(support, '_compact_ref', None)
    from record_views import RecordRef
    if isinstance(ref, RecordRef):
        origin = getattr(ref, '_partition', None)
        if (not P._is_v2(origin) or not origin._sealed or origin.record is not ref._view or
                ref.scope.run_budget is not support._resource or
                origin.support_node(support.support_id) != ref.index or
                origin.support_identity(support.support_id).canonical_bytes != len(support._json)):
            raise ValueError('support reference, inventory or budget differs')
        ref._live()
        return ref
    if ref is not None and (type(ref) is not NodeRef or not getattr(ref._view, '_sealed', False) or
            ref._view.budget is not support._resource or
            ref._view.support_by_id(support.support_id).index != ref.index):
        raise ValueError('support reference, inventory or budget differs')
    return ref


def retain_support(support):
    """Small owned handle for a compact native support; anything native else unchanged."""
    if type(support) is CompactSupport:
        return support
    ref = _bound_ref(support)
    if ref is None:
        return support
    owner = M._Allocation(support._resource, 4096)
    header = P._view_fields(ref._view, ref, HEADER)
    result = object.__new__(CompactSupport)
    for key, value in dict(_ref=ref, _resource=support._resource, support_id=support.support_id,
            encoded_size=len(support._json), decoded_capacity=_routing()._decoded_json_capacity(support._json),
            _header=header, _owner=owner).items():
        object.__setattr__(result, key, value)
    return result


def support_fields(support, fields):
    """Owned selected fields; a plain native support pays one charged full decode."""
    if type(support) is CompactSupport:
        return P._view_fields(support._ref._view, support._ref, fields)
    ref = _bound_ref(support)
    if ref is not None:
        return P._view_fields(ref._view, ref, fields)
    return P.owned_support_record(support)


def support_header(support):
    """(interval_id, start_time_s, end_time_s) owner; a plain support is read as before."""
    if type(support) is CompactSupport:
        return support._header
    if getattr(support, '_compact_ref', None) is not None:
        return support_fields(support, HEADER)
    return M.OwnedRow(support.record(), None)


def as_native_with_record(support):
    """(native support, its owned decoded record) for a handle; others pass through."""
    if type(support) is not CompactSupport:
        return support, None
    D, ref = P._native(), support._ref
    P._size(ref._view, ref, P.MAX_NATIVE_SUPPORT_BYTES)
    from record_views import RecordRef
    owned = (ref.export(max_logical_bytes=P.MAX_NATIVE_SUPPORT_BYTES, max_owned_bytes=256 << 20)
             if isinstance(ref, RecordRef) else ref._view.legacy_record(ref))
    result = D._issue(D.DifferentialSupport, owned.value, support._resource)
    if result.support_id != support.support_id:
        raise ValueError('materialised native support identity differs')
    object.__setattr__(result, '_compact_ref', ref)
    return result, owned


def as_native(support):
    return as_native_with_record(support)[0]


def owned_constraint(value):
    """A retained DAG definition decoded and owned while borrowed; others unchanged."""
    from record_views import RecordRef
    if isinstance(value, RecordRef):
        return value.export(max_logical_bytes=P.MAX_NATIVE_SUPPORT_BYTES, max_owned_bytes=256 << 20)
    if type(value) is NodeRef:
        return value._view.legacy_record(value)
    return M.OwnedRow(value, None)


def wall(support, *args, **kwargs):
    return P._native().enclose_component_wall(as_native(support), *args, **kwargs)


def interface(support, *args, **kwargs):
    if type(kwargs.get('other_support')) is CompactSupport:
        kwargs['other_support'] = as_native(kwargs['other_support'])
    return P._native().enclose_component_interface(as_native(support), *args, **kwargs)


def project_compact(rows, support):
    """One native decoded input; retain only small rows and DAG references.

    The original two-graph/decoder admission already covers this input. The
    projected descendants have the same explicit operation-local lease as the
    original RoutingViews, but no complete constraint definition is retained.
    """
    R = _routing()
    views = rows._views
    if type(rows) is not R.SupportRoutingRows or not views._active or support._resource is not rows._budget:
        raise RuntimeError('active same-budget routing owner required')
    handle = retain_support(support)
    record = support.record()
    if type(record) is not dict or not R._REQUIRED <= record.keys():
        raise ValueError('complete decoded support routing/cell metadata required')
    source, parts = record['constraints'], record['components']
    if type(source) is not dict or type(parts) is not list:
        raise TypeError('plain constraint dictionary and component list required')
    with views._budget.reserve(65536+256*(len(source)+len(parts)+len(record)+1),
                               category='compact-routing-project'):
        used = set()
        for part in parts:
            if type(part) is not dict or not R._PART <= part.keys():
                raise ValueError('complete component routing/cell metadata required')
            for name, _sign in part['constraints']:
                if type(name) is not str or name not in source:
                    raise ValueError('component literal has no named definition')
                used.add(name)
        definitions = {}
        root = handle._ref.field('constraints')
        for name, value in source.items():
            if name in used:
                if type(value) is not dict:
                    raise TypeError('plain constraint definition dictionaries required')
                R._json_definition(value)
                definitions[name] = root.field(name)
        projected = [{k: v for k, v in part.items() if k in R._PART} for part in parts]
        view = {k: (definitions if k == 'constraints' else projected if k == 'components' else v)
                for k, v in record.items() if k in R._ROW}
        shell = {k: v for k, v in view.items() if k != 'constraints'}
        capacity = 4096+R._width(shell)+256*(len(view)+len(projected)+len(definitions))
        capacity += sum(R._width(name) for name in definitions)
        # Atomic admission: nothing below is mutated if this refuses.
        views._lease.add(capacity, category='routing-view-retained')
        views._stats['view_bytes'] += capacity
        views._stats['projected_supports'] += 1
        rows._handles[handle.support_id] = handle
        return view


def _prepaid_decode(view, node):
    """Private decoder; caller MUST hold the actual live diagnostic owner.

    No NodeRef.row/field/scalar calls here: those correctly reserve for ordinary
    reads, which would be wrong after a failure. Expanded children are decoded
    independently, matching the graph capacity counted from native JSON bytes.
    """
    from record_views import CompactRecord, _Memory
    if type(view) is CompactRecord:
        if type(view._columns) is not _Memory:
            raise RuntimeError('persisted v2 diagnostic capture requires pending WP16 compact replay adapter')
        view._live()
        return _prepaid_generic(view, node)
    view._check()
    kind = int(view._arrays['node.kind'][node])
    if kind not in (LIST, OBJECT):
        return view._scalar(node)
    lo, hi = view._bounds(node)
    children = view._arrays['edge.child']
    if kind == LIST:
        return [_prepaid_decode(view, int(children[i])) for i in range(lo, hi)]
    return {view._text(int(view._arrays['edge.key'][i])): _prepaid_decode(view, int(children[i]))
            for i in range(lo, hi)}


def _prepaid_generic(view, node):
    """In-memory scalar/graph decode under the arena's original prepaid owner.

    No owner, column page, stream buffer or admission is created here. The
    expanded graph is the same graph counted from the native issued bytes.
    Persisted columns deliberately cannot reach this function.
    """
    import record_tables as T
    kind, payload = view._v('node.kind', node), view._v('node.payload', node)
    if kind == T.OBJECT:
        start, _ = view._range('shape', view._v('node.shape', node))
        return {view._token(view._v('shape.key', start+i)):
                _prepaid_generic(view, view._child(node, i)) for i in range(view._size(node))}
    if kind in (T.ARRAY, T.RATIONAL):
        return [_prepaid_generic(view, view._child(node, i)) for i in range(view._size(node))]
    if kind == T.TEXT:
        return view._token(payload)
    if kind == T.HEX:
        return b''.join(view._hex(payload))[1:-1].decode('ascii')
    if kind == T.IDENT:
        return b''.join(view._bytes('id.bytes', 32*payload, 32*(payload+1))).hex()
    return (None if kind == T.NULL else bool(payload) if kind == T.BOOL else
            view._int(payload) if kind == T.INTEGER else view._v('float.value', payload))


def diagnostic(rows, key):
    """A failed query's complete support record, from prepaid capacity only.

    Only while the rows' RoutingArena is still building its refusal (its
    failure owner live). The payload keeps that owner, as the arena's own
    failure payloads do, so its charges outlive neither the error nor it.
    """
    R = _routing()
    owner = getattr(getattr(rows, '_arena', None), '_failure_owner', None)
    if type(rows) is not R.SupportRoutingRows or owner is None or not owner.release.alive:
        raise RuntimeError('prepaid routing diagnostic owner is no longer live')
    if key not in rows._diagnostics:
        if len(rows._diagnostics) >= 2:
            raise RuntimeError('one failed physical query has more than two support operands')
        handle = rows._handles[key]
        if type(handle) is not CompactSupport or handle._resource is not rows._budget:
            raise ValueError('compact diagnostic support or budget differs')
        rows._diagnostics[key] = R._OwnedPayload(_prepaid_decode(handle._ref._view, handle._ref.index), owner)
    return rows._diagnostics[key]


def _cache_key(support):
    ref = support._ref if type(support) is CompactSupport else getattr(support, '_compact_ref', None)
    from record_views import RecordRef
    if type(ref) is not NodeRef and not isinstance(ref, RecordRef):
        raise TypeError('compact support reference required')
    # The cached handle retains its view, so this id cannot be reused while cached.
    return id(ref._view), ref.index


def _iter_ref(ref):
    """Borrow one bounded canonical chunk while its explicit owner is live."""
    from record_views import RecordRef
    if isinstance(ref, RecordRef):
        with ref.iter_json() as stream:
            for part in stream:
                with part:
                    yield part.value
    else:
        yield from ref._view.iter_legacy_json(ref)


def _trace_parts(view, index=None):
    if not P._is_v2(view):
        yield from view.iter_legacy_json(None if index is None else view.support(index))
        return
    ref = view.root() if index is None else view.support(index)
    try:
        yield from _iter_ref(ref)
    finally:
        ref.close()


def rolling_facts(rolling, support):
    """_Rolling._facts for a compact support: one entry per support node, holding its handle."""
    key = _cache_key(support)
    found = rolling.identities.get(key)
    if found is None:
        if len(rolling.identities) >= rolling.cached:
            rolling.identities.clear()
        held = retain_support(support)
        found = rolling.identities[key] = [held, held.support_id, False]
    return found


def batch_facts(session, support, transport):
    """BatchParallelSession._support_facts from the owned header; no support decode."""
    key = _cache_key(support)
    held = session._facts.get(key)
    if held is None:
        if len(session._facts) >= 512:
            session._facts.clear()
        kept = retain_support(support)
        record = kept._header.value
        held = session._facts[key] = (kept, (kept.support_id, record['interval_id'],
            record['start_time_s'], record['end_time_s'], transport(kept) is not None))
    return held[1]


def compact_transport(support, maximum, storage):
    """The native transport() size filters, from sizes counted on the issued bytes."""
    if type(support) is not CompactSupport:
        raise TypeError('compact support handle required')
    if support.encoded_size <= maximum and support.decoded_capacity+65536+4*support.encoded_size <= storage//4:
        return support.support_id, support.encoded_size
    return None


class InputMap(dict):
    """Exact issued bytes per input name, plus the owners those bytes need.

    A handle is streamed once into an exact copy under its own retained charge
    (length and SHA-256 checked against its identity) only after the unchanged
    transport filter accepts it. A temporary native support of a compact
    partition is kept, so its issue lease outlives the borrowed bytes. A plain
    native support is stored exactly as before. Owners live as long as the map
    (the job or batch, until it finishes, retires or closes).
    """
    def __init__(self, maximum, storage):
        super().__init__()
        self._limits, self._owners = (maximum, storage), []

    def add(self, name, support):
        if type(support) is not CompactSupport:
            if getattr(support, '_compact_ref', None) is not None:
                self._owners.append((None, support))
            self[name] = support._json
            return
        if compact_transport(support, *self._limits) is None:
            raise ValueError('compact support exceeds the unchanged optional transport envelope')
        ref, size = support._ref, support.encoded_size
        retained = M._Allocation(support._resource, 4096+size)
        # Byte buffer, its immutable copy, the largest scalar and the walk stack.
        scratch = M._Allocation(support._resource, 65536+2*size+
                                2*getattr(ref._view, '_max_scalar', 0)+512*MAX_DEPTH)
        raw, position = bytearray(size), 0
        from record_views import RecordRef
        parts = _iter_ref(ref) if isinstance(ref, RecordRef) else ref._view._iter(ref.index)
        for piece in parts:
            end = position+len(piece)
            if end > size:
                raise ValueError('compact encoded support length differs')
            raw[position:end] = piece
            position = end
        encoded = bytes(raw)
        del raw
        if position != size or sha256(encoded).hexdigest() != support.support_id:
            raise ValueError('compact encoded support identity differs')
        self._owners.append((retained, support))
        self[name] = encoded
        del scratch


def compact_continuation_state(partition, spatial_state):
    """Whether the continuation must read a compact partition or indexed material state."""
    indexed = sys.modules.get('spatial_indexed_patch')
    return (getattr(partition, '_compact', None) is not None or indexed is not None and
            type(getattr(spatial_state, '_snapshot', None)) is indexed.IndexedSpatialSnapshot)


def continuation_records(current, partition, prior, spatial_state):
    """(geo, part, accepted, material_state, owner), read in the original order.

    A compact partition yields only the four fields the continuation checks;
    the material record is the indexed logical record (or record() as before).
    Keep the returned owner while part is borrowed.
    """
    from spatial_indexed_patch import logical_record
    geo = current.record()
    if getattr(partition, '_compact', None) is None:
        part, owner = partition.record(), None
    else:
        owner = P.partition_fields(partition, CONTINUATION_FIELDS)
        part = owner.value
    accepted = prior.record()
    return geo, part, accepted, logical_record(spatial_state), owner


def retain_compact_trace(number, partition, volume_map, arguments, budget, *, name, scope):
    """Stream the original diagnostic shape, never reconstruct all supports.

    Diagnostic only: every Exception, including a refused view or budget, is
    printed and the workflow continues; a BaseException removes only the new
    incomplete file and propagates. Exclusive creation never replaces a file.
    Decompressed bytes equal the legacy _retain_failure capture.
    """
    import gzip
    import json
    import os
    from pathlib import Path
    folder = os.environ.get('ATLAS_FOCUSED_ARTIFACT_DIR')
    if not folder:
        return
    try:
        view = P.compact_view(partition)
        if view is None or view.budget is not budget:
            raise ValueError('actual same-budget compact trace partition required')
        if number is None:
            number = 1+sum(1 for _ in Path(folder).glob(name+'-*.json.gz'))
        target = Path(folder)/('%s-%02d.json.gz' % (name, number))
        # Gzip buffers, largest scalar, retained map decode and its encoder.
        # No reservation proportional to the expanded partition/support graph.
        owner = M._Allocation(budget, 262144+4*getattr(view, '_max_scalar', 0)+
                              16*len(volume_map._record)+8*M._width(arguments))
        mapped = volume_map.record()
        encoder = json.JSONEncoder(sort_keys=True, separators=(',', ':'), allow_nan=False)
        def encode(value):
            for chunk in encoder.iterencode(value):
                yield chunk.encode('ascii')
        raw = target.open('xb')
        try:
            with raw, gzip.GzipFile(fileobj=raw, mode='wb', mtime=0) as stream:
                stream.write(b'{"arguments":')
                for piece in encode(arguments):
                    stream.write(piece)
                stream.write(b',"partition":')
                for piece in _trace_parts(view):
                    stream.write(piece)
                stream.write(b',"scope":')
                for piece in encode(scope):
                    stream.write(piece)
                stream.write(b',"supports":[')
                for i in range(view.support_count):
                    if i:
                        stream.write(b',')
                    for piece in _trace_parts(view, i):
                        stream.write(piece)
                stream.write(b'],"volume_map":')
                for piece in encode(mapped):
                    stream.write(piece)
                stream.write(b'}')
        except BaseException:
            raw.close()
            target.unlink()
            raise
        del owner
    except Exception as error:
        print('Trace inputs not retained (%s):' % name, type(error).__name__, error, flush=True)
