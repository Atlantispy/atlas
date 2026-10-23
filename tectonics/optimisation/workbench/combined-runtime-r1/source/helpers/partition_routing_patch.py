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
import copy
from dataclasses import dataclass
from hashlib import sha256
import json
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
    partition = getattr(ref, '_partition', None)
    if P._is_v2(partition):
        # Only the ancestry actually retained by this handle uses the partition
        # allowance. Temporary exports and generic child borrows stay fixed.
        from content_cache import Owned
        held, stack = {}, [ref._owner, ref._selection_owner]
        while stack:
            share = stack.pop()
            if isinstance(share, Owned) and id(share) not in held:
                held[id(share)] = share
                stack.append(share._parent)
        partition._carrier_pool.adopt(partition._index.value[1][support.support_id], held.values())
    owner = M._Allocation(support._resource, 4096)
    exported = P._view_fields(ref._view, ref, HEADER)
    # The routing rows keep this handle for the whole interval. Keep plain copies of the three small
    # header values, charged at their measured size against the run budget, and release the field
    # exports (charged to the scope's fixed retained budget) and the fixed estimate once that is held.
    values = copy.deepcopy(exported.value)
    header = M.OwnedRow(values, (M._Allocation(support._resource, _plain_bytes(values)), ref._view))
    del exported
    result = object.__new__(CompactSupport)
    for key, value in dict(_ref=ref, _resource=support._resource, support_id=support.support_id,
            encoded_size=len(support._json), decoded_capacity=_routing()._decoded_json_capacity(support._json),
            _header=header, _owner=owner).items():
        object.__setattr__(result, key, value)
    return result


def _plain_bytes(value):
    """Measured bytes of plain decoded JSON data; each object counted once, small shared ones included."""
    seen, total, stack = set(), 0, [value]
    while stack:
        item = stack.pop()
        if id(item) in seen:
            continue
        seen.add(id(item))
        kind = type(item)
        if kind is dict:
            stack.extend(item.keys())
            stack.extend(item.values())
        elif kind is list:
            stack.extend(item)
        elif kind not in (str, int, float, bool, type(None)):
            raise TypeError('plain decoded header data required, not %s' % kind.__name__)
        total += sys.getsizeof(item)
    return total


def _canonical(value):
    """Canonical JSON bytes of plain header data: sorted keys, no whitespace, finite numbers only.

    Unlike ==, these bytes tell 1, 1.0 and True apart, and -0.0 from 0.0.
    """
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode()


def _guard_charges(guard):
    """(budget, category, bytes) admitted by an entered reserve or try_reserve guard; None once it has exited.

    Both are generator context managers in atlas_tectonics.resources. While one is entered, its suspended
    generator's frame holds the admitted (budget, category) pairs and the byte count.
    """
    frame = getattr(getattr(guard, 'gen', None), 'gi_frame', None)
    if frame is None:
        return None
    local = frame.f_locals
    return [(node, label, local.get('count')) for node, label in local.get('charged') or ()]


def _ownership_graph(handle):
    """Shares, base allocations and run-budget allocations reachable through a handle's ownership attributes.

    From handle._owner, the header's owner and handle._ref it follows RecordRef owners, selection owners and
    fields; OwnedRow owners; share allocations and parents; base-allocation dependencies; and plain containers.
    It never enters a record view or a budget, which are shared: a view's owner is reached as a share's
    allocation instead. It follows only tuple, list and dict containers and the types named here, so an
    allocation held behind a set, frozenset, weakref or any other object is not seen.
    """
    from content_cache import Owned, _Allocation as Base
    from record_views import RecordRef
    shares, bases, rows, seen = [], [], [], set()
    stack = [handle._owner, handle._header._owner, handle._ref]
    while stack:
        item = stack.pop()
        if item is None or id(item) in seen:
            continue
        seen.add(id(item))
        kind = type(item)
        if kind in (tuple, list):
            stack.extend(item)
        elif kind is dict:
            stack.extend(item.values())
        elif isinstance(item, Owned):
            shares.append(item)
            stack.extend((item._allocation, item._parent))
        elif kind is Base:
            bases.append(item)
            stack.extend(item.dependencies)
        elif kind is M._Allocation:
            rows.append(item)
        elif kind is M.OwnedRow:
            stack.append(item._owner)
        elif isinstance(item, RecordRef):
            stack.extend((item._owner, item._selection_owner, item._fields))
    return shares, bases, rows


def _run_allocation_problems(handle, name, allocation):
    charges = _guard_charges(allocation.guard)
    if charges is None:
        return ['%s allocation is released' % name]
    if not any(node is handle._resource and label == 'compact-mesh-owned' and count == allocation.size
               for node, label, count in charges):
        return ['%s allocation is not charged in full to the support budget' % name]
    return []


def _ownership_problems(handle, header_allocation):
    """The ownership half of retained_header_problems."""
    from content_cache import Owned
    ref = handle._ref
    shares, bases, rows = _ownership_graph(handle)
    held, stack = {}, [getattr(ref, '_owner', None), getattr(ref, '_selection_owner', None)]
    while stack:
        share = stack.pop()
        if isinstance(share, Owned) and id(share) not in held:
            held[id(share)] = share
            stack.append(share._parent)
    problems = []
    expected = {key for key, share in held.items() if share._carrier is not None}
    reachable = {id(share) for share in shares if share._carrier is not None}
    if not expected:
        problems.append('the record reference holds no retained share')
    if reachable != expected:
        problems.append('%d carriers are reachable from the handle, but its record reference holds %d'
                        % (len(reachable), len(expected)))
    try:
        scope = ref.scope
        retained = scope.retained_budget
    except (RuntimeError, AttributeError) as error:
        return problems + ['record reference scope unavailable: %s' % error]
    for key in sorted(expected):
        carrier = held[key]._carrier
        charges = _guard_charges(carrier.context)
        pool = carrier._support_pool
        charged_budget = retained if pool is None else pool.budget
        partition = getattr(ref, '_partition', None)
        if P._is_v2(partition):
            if (pool is not partition._carrier_pool or pool is None or pool.scope is not scope or
                    carrier._support_index != partition._index.value[1].get(handle.support_id)):
                problems.append('a carrier has foreign partition or support pool attribution')
        elif pool is not None:
            problems.append('a carrier pool has no actual reference partition')
        if carrier.spec.purpose != 'owner-carrier' or carrier.scope is not scope:
            problems.append('a carrier is not an owner-carrier charge of the reference scope')
        elif not charges or not any(node is charged_budget and label == 'retained:owner-carrier'
                                    and count == carrier.spec.total_bytes for node, label, count in charges):
            problems.append('a carrier is released or not charged in full to the retained budget')
    if any(base.charge.spec.purpose == 'record-export' for base in bases):
        problems.append('a record-export allocation is reachable from the handle')
    extra = [row for row in rows if row is not handle._owner and row is not header_allocation]
    if extra:
        problems.append('%d other run-budget allocations are reachable; an export estimate may be retained'
                        % len(extra))
    if type(handle._owner) is not M._Allocation:
        problems.append('the handle does not own a run-budget allocation')
    else:
        problems.extend(_run_allocation_problems(handle, 'handle', handle._owner))
    return problems


def _key_problems(side, value):
    """The key-set problem of one side of the header comparison; [] when value is a dict with exactly HEADER."""
    if type(value) is dict and set(value) == set(HEADER):
        return []
    return ['%s keys %s are not exactly %s' % (
        side, sorted(map(repr, value)) if type(value) is dict else type(value).__name__, list(HEADER))]


def retained_header_problems(handle):
    """Problems with a retained CompactSupport; [] when its header and ownership graph are exactly as built.

    Header: the value is plain JSON data whose keys are exactly HEADER, and whose canonical JSON bytes equal those
    of the support record's fields, which must have exactly the HEADER keys too. It is owned by exactly (a live
    run-budget allocation charged in full to handle._resource at no less than the value's measured size, the
    view).
    Ownership graph (_ownership_graph): the carriers reachable from the handle are exactly those of the record
    reference's own owner and selection shares and their parents. Each is live and charged in full as
    'retained:owner-carrier' to the reference scope's retained budget. No reachable allocation is a record export.
    The only run-budget allocations reachable are the handle's fixed one and the header's, both live and charged
    in full to handle._resource. The end-of-pass check that no record-export reservation remains is separate.
    The check is diagnostic: _ownership_graph does not follow every kind of container (see its docstring), so []
    does not prove that nothing else is retained.
    Before the fresh read, the record reference must be usable as partition_native_patch._view_fields uses it:
    it has a view; a RecordRef gives its scope's run budget, and any other reference has a callable row(). A
    closed, scope-less or stand-in reference that fails there with RuntimeError or AttributeError is reported as
    unavailable, and the read and the value comparison are skipped; the header's keys and the ownership checks
    still run. An error raised inside the read itself propagates unchanged.
    """
    header = getattr(handle, '_header', None)
    if type(handle) is not CompactSupport or type(header) is not M.OwnedRow:
        return ['not a retained compact support header']
    problems, owner = [], header._owner
    allocation = owner[0] if type(owner) is tuple and owner else None
    if (type(owner) is not tuple or len(owner) != 2 or type(allocation) is not M._Allocation
            or owner[1] is not getattr(handle._ref, '_view', None)):
        problems.append('owner is not exactly (run-budget allocation, view); an export owner may be retained')
    if type(allocation) is M._Allocation:
        problems.extend(_run_allocation_problems(handle, 'header', allocation))
    try:
        real = _plain_bytes(header.value)
    except TypeError as error:
        problems.append(str(error))
        real = None
    if real is not None and type(allocation) is M._Allocation and allocation.size < real:
        problems.append('charge %d is below the measured %d bytes' % (allocation.size, real))
    from record_views import RecordRef
    try:
        ref = handle._ref
        view = ref._view
        if isinstance(ref, RecordRef):
            _ = ref.scope.run_budget  # what _view_fields dereferences first
        elif not callable(ref.row):
            raise AttributeError('%s.row is not callable' % type(ref).__name__)
    except (RuntimeError, AttributeError) as error:
        problems.append('record reference unavailable: %s' % error)
        problems.extend(_key_problems('header', header.value))
    else:
        fresh = P._view_fields(view, ref, HEADER)
        try:
            problems.extend(_key_problems('header', header.value))
            problems.extend(_key_problems('support record', fresh.value))
            try:
                if _canonical(header.value) != _canonical(fresh.value):
                    problems.append('values differ from the support record')
            except (TypeError, ValueError) as error:
                problems.append('values are not canonical JSON: %s' % error)
        finally:
            del fresh
    problems.extend(_ownership_problems(handle, allocation))
    return problems


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
