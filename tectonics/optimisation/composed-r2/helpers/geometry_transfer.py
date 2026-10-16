"""Explicit one-parent geometry binding after native/collar state transfer.

This is not a historical-acceptance issuer. The workflow migration root must
first authenticate the old endpoint and its complete geometry under its original
reader. This seam preserves the original partition/support bytes and permits
only their enumerated old collar-plan reference at that one restart boundary.
New interval partitions name the actual current collar plan as usual.
"""
import hashlib
import math
from pathlib import Path

import native_transfer as N


# Compact parents: the same _validate_parent_descriptor fields, read as owned
# selected rows; identity comes from the sealed codec, never from this header.
PARENT_COMPACT_FIELDS = ('schema', 'scope', 'collar_plan_id', 'funding_id', 'source', 'interval_id',
                         'end_time_s', 'endpoint_network_id', 'trajectory_id')
MATCH_COMPACT_FIELDS = ('collar_plan_id', 'funding_id')
# partition_native_patch.transform leaves a selected header in `old` here.
PARTITION_READER_MARKER = '    old, step, original = old_owner.value, interval.record(), funding.descriptor()\n'
PARTITION_READER_CALL = 'old_owner = partition_fields(parent_partition,'


class GeometryTransferRefused(ValueError):
    pass


def _json_decode_bytes(raw):
    """Bound one JSON decode from retained bytes without decoding/copying them.

    Eight bytes per encoded byte cover the input Unicode text plus decoded
    string/number payload. Separately admit container headers (256), member
    slots/scalar objects/decoder key memo (128 per separator plus one), and
    string headers (96). This is a CPython capacity allowance, not measured RSS.
    Count structural punctuation OUTSIDE strings: a long string of commas is
    not charged as thousands of Python objects. find/count scan the retained
    buffer in place; only integer counters and one token position are live.
    """
    if not isinstance(raw, bytes):
        raise GeometryTransferRefused('retained immutable JSON bytes required')
    cursor = containers = separators = strings = 0
    length = len(raw)
    while cursor < length:
        quote = raw.find(b'"', cursor)
        stop = length if quote < 0 else quote
        containers += raw.count(b'{', cursor, stop)+raw.count(b'[', cursor, stop)
        separators += raw.count(b':', cursor, stop)+raw.count(b',', cursor, stop)
        if quote < 0:
            break
        strings += 1
        end = quote
        while True:
            end = raw.find(b'"', end+1)
            if end < 0:
                raise GeometryTransferRefused('unterminated retained JSON string')
            escaped = end-1
            while escaped > quote and raw[escaped] == 92:
                escaped -= 1
            if (end-1-escaped) % 2 == 0:
                break
        cursor = end+1
    return 8*length+256*containers+128*(separators+1)+96*strings


def _plan_graph_scratch_bytes(collar):
    # Descriptor() encodes then decodes each already-owned definition. One
    # current graph plus the largest string/bytes/decoder overlap fits four
    # widths, including escaped Unicode; no full graph is serialised here.
    plans = (collar._native._transport, collar._native._heat, collar._native,
             collar._transport, collar._heat, collar)
    return 8192+4*sum(N._width(plan._definition) for plan in plans)


def _binding_scratch_bytes(native_transfer, collar):
    return 65536+_json_decode_bytes(native_transfer._record)+_plan_graph_scratch_bytes(collar)


def _binding_scratch(native_transfer, collar, budget):
    """(base, decoded) bindings of _binding_scratch_bytes, admitted before any decode.

    The decoded part funds the transfer record decode and the current plan
    graph; the binding releases it with them after the contract check. The
    base stays to the end of the binding, so a held field or parent refusal
    keeps its frame funded.
    """
    base = N._Allocation(budget, 65536, category='geometry-transfer-binding-scratch')
    decoded = N._Allocation(budget, _binding_scratch_bytes(native_transfer, collar)-65536,
                            category='geometry-transfer-binding-scratch')
    return base, decoded


def _transfer_scalars(evidence):
    """The only transfer-record values the field and parent checks need."""
    return (evidence['input']['historical_plan_graph']['collar']['plan_id'],
            evidence['current_collar']['fields']['time_s'])


def _matches_scratch_bytes(binding, body, collar):
    # The caller owns body. The hash stays streaming; its largest encoded
    # scalar/sorting work is bounded without reserialising that body up front.
    return (65536+_json_decode_bytes(binding._record)+_json_decode_bytes(binding._native._record)
            +_plan_graph_scratch_bytes(collar)+4*N._width(body))


def _validate_transfer_contract(native_transfer, evidence, current, budget):
    old = evidence['input']['historical_plan_graph']
    # compare_scientific_contract holds two scientific descriptor copies,
    # plus canonical string/byte comparisons and individual hash encodings.
    # Reserve these named plan graphs, NOT further whole provenance copies.
    state = native_transfer.state
    scratch = N._Allocation(budget,
        8192+3*(N._width(old)+N._width(current))
        +_json_decode_bytes(state.fields._metadata)+_json_decode_bytes(state.native_state._metadata),
        category='geometry-transfer-contract-scratch')
    if (current != evidence['input']['current_plan_graph']
            or N.compare_scientific_contract(old, current) != evidence['input']['compatibility']
            or state.record() != evidence['current_collar']):
        raise GeometryTransferRefused('actual native transfer/current plan binding differs')
    assert scratch.size > 0


def _fields_scratch_bytes(collar, state):
    # Native validation completes before the collar grid is checked. Each
    # _array can copy its retained bytes subclass; account all fields once,
    # two largest-field masks/gathers (including invalid zero-quadrature
    # paths), twelve binary64 scalar grids, the component reduction vector,
    # and ndarray/dictionary headers. This is not a solve/advance envelope.
    domains = []
    for snapshot, cells in ((state.native_state, collar._native.cells), (state.fields, collar.cells)):
        widths = [len(raw) for _, _, raw in snapshot._fields]
        domains.append(sum(widths)+2*max(widths, default=0)+96*math.prod(cells)
                       +1024*len(widths)+8*len(collar._native._composition))
    return (8192+max(domains)+_json_decode_bytes(state.fields._metadata)
            +_json_decode_bytes(state.native_state._metadata))


def _validate_fields(collar, state, budget):
    scratch = N._Allocation(budget, _fields_scratch_bytes(collar, state),
                            category='geometry-transfer-fields-scratch')
    collar._fields(state)
    # A held validator exception retains this frame/charge and its arrays.
    assert scratch.size > 0


def _validate_parent_descriptor(partition_descriptor, supports, geometry, funding, old_plan_id, clock, budget):
    from atlas_tectonics.integration_differential_geometry import _record_hash
    from atlas_tectonics import integration_wall_measures as W
    header_width = N._width({k: v for k, v in partition_descriptor.items()
                            if k not in ('partition_id', 'supports')})
    largest = max((N._width(row) for row in supports), default=0)
    scratch = N._Allocation(budget,
        65536+4*max(header_width, largest)+256*len(supports)
        +_json_decode_bytes(funding._snapshot._metadata)+_json_decode_bytes(geometry._json),
        category='geometry-transfer-parent-scratch')
    body = {k: v for k, v in partition_descriptor.items() if k not in ('partition_id', 'supports')}
    # Only source is needed from funding: avoid descriptor()'s additional
    # shallow dictionary with funding_id; the actual ID is checked below.
    original, step = funding._snapshot.descriptor(), geometry.record()
    if (body.get('schema') != 'atlas.differential-partition.v1'
            or body.get('scope') != 'physical-interval'
            or _record_hash(body) != partition_descriptor.get('partition_id')
            or [_record_hash(s) for s in supports] != body.get('support_ids')
            or body.get('collar_plan_id') != old_plan_id
            or body.get('funding_id') != funding.funding_id
            or body.get('source') != original['source']
            or body.get('interval_id') != geometry.interval_id
            or body.get('end_time_s') != step['end_time_s']
            or body.get('endpoint_network_id') != step['endpoint_network_id']
            or body.get('trajectory_id') != step['trajectory_id']
            or W._decode(body['end_time_s']) != W._q(clock)):
        raise GeometryTransferRefused('historical endpoint partition or clock differs')
    assert scratch.size > 0


def _is_v2(view):
    # Legacy helper closures need only the original v1 modules.
    from partition_tables import CompactPartition
    if type(view) is CompactPartition:
        return False
    from partition_v2 import PartitionV2
    return type(view) is PartitionV2


def _sealed_view(view, budget):
    # Exact codec type only: its constructor streamed the body and every ordered
    # support hash before fixing partition_id and sealing. Same owning budget.
    from partition_tables import CompactPartition
    if type(view) is CompactPartition:
        return getattr(view, '_sealed', False) is True and view.budget is budget
    if not _is_v2(view):
        return False
    from content_cache import RetainedScope
    return (getattr(view, '_sealed', False) is True and type(view.scope) is RetainedScope and
            not view.scope._closed and view.scope.run_budget is budget)


def _compact_ids(view, names):
    """Bounded scalar root reads: no identity stream and no container export."""
    if _is_v2(view):
        root, values = view.root(), {}
        try:
            for name in names:
                ref = root.field(name)
                try:
                    if ref.kind != 'scalar':
                        values[name] = None
                    else:
                        with ref.scalar(max_owned_bytes=65536) as held:
                            values[name] = held.value
                finally:
                    ref.close()
            return values
        finally:
            root.close()
    root, values = view.root(), {}
    for name in names:
        ref = root.field(name)
        values[name] = None if ref.kind in ('object', 'list') else ref.scalar().value
    return values


def _streamed_body_id(view):
    if _is_v2(view):
        root = view.root()
        try:
            return root.identity().sha256
        finally:
            root.close()
    digest = hashlib.sha256()
    for part in view.iter_legacy_json():
        digest.update(part)
    return digest.hexdigest()


def _verify_ordered_supports(view):
    # The dict route's [_record_hash(s) for s in supports] == support_ids,
    # repeated once at this restart boundary from the codec's own bytes.
    if _is_v2(view):
        root = view.root()
        ids = root.field('support_ids')
        try:
            if ids.kind != 'array' or ids.size != view.support_count:
                raise GeometryTransferRefused('ordered historical support inventory differs')
            for i in range(view.support_count):
                ident = view.support_id(i)
                node, support = ids.at(i), view.support(i)
                try:
                    with node.scalar(max_owned_bytes=65536) as held:
                        if held.value != ident or support.identity().sha256 != ident:
                            raise GeometryTransferRefused('ordered historical support identity differs')
                finally:
                    support.close()
                    node.close()
        finally:
            ids.close()
            root.close()
        return
    ids = view.root().field('support_ids')
    if ids.kind != 'list' or ids.size != view.support_count:
        raise GeometryTransferRefused('ordered historical support inventory differs')
    for i in range(view.support_count):
        ident = view.support_id(i)
        if ids.at(i).scalar().value != ident or view._hash(view.support(i).index) != ident:
            raise GeometryTransferRefused('ordered historical support identity differs')


def _compact_parent_scratch_bytes(funding, geometry):
    # Header rows and identity streams are funded by the view's own owners; the
    # transfer charges only the decoded funding metadata and geometry record.
    return 65536+_json_decode_bytes(funding._snapshot._metadata)+_json_decode_bytes(geometry._json)


def _matches_compact_scratch_bytes(binding, collar):
    # No decoded parent body exists, so the dict route's 4*width(body) is absent.
    return (65536+_json_decode_bytes(binding._record)+_json_decode_bytes(binding._native._record)
            +_plan_graph_scratch_bytes(collar))


def _validate_parent_compact(view, geometry, funding, old_plan_id, clock, budget):
    from partition_native_patch import _view_fields
    from atlas_tectonics import integration_wall_measures as W
    scratch = N._Allocation(budget, _compact_parent_scratch_bytes(funding, geometry),
                            category='geometry-transfer-compact-parent-scratch')
    if _is_v2(view):
        root = view.root()
        try:
            header = _view_fields(view, root, PARENT_COMPACT_FIELDS)
        finally:
            root.close()
    else:
        header = _view_fields(view, view.root(), PARENT_COMPACT_FIELDS)
    body = header.value
    original, step = funding._snapshot.descriptor(), geometry.record()
    if (body.get('schema') != 'atlas.differential-partition.v1'
            or body.get('scope') != 'physical-interval'
            or body.get('collar_plan_id') != old_plan_id
            or body.get('funding_id') != funding.funding_id
            or body.get('source') != original['source']
            or body.get('interval_id') != geometry.interval_id
            or body.get('end_time_s') != step['end_time_s']
            or body.get('endpoint_network_id') != step['endpoint_network_id']
            or body.get('trajectory_id') != step['trajectory_id']
            or W._decode(body['end_time_s']) != W._q(clock)):
        raise GeometryTransferRefused('historical endpoint partition or clock differs')
    # The decoded funding and geometry records end at their last use, before
    # the identity re-stream; a refusal above keeps them with their scratch.
    del original, step
    # Cheap header refusals first; then the identity is re-streamed exactly once.
    if _streamed_body_id(view) != view.partition_id:
        raise GeometryTransferRefused('historical compact partition body identity differs')
    _verify_ordered_supports(view)
    assert scratch.size > 0
    return view.partition_id


def _issue_binding(record, native_transfer, collar, funding, budget):
    raw = N._json(record)
    allocation = N._Allocation(budget, len(raw)+4096,
                                category='geometry-transfer-binding-retained')
    result = object.__new__(ParentGeometryTransfer)
    for name, value in dict(_record=N._RecordBytes(raw, allocation), _native=native_transfer,
            _collar=collar, _funding=funding, _budget=budget).items():
        object.__setattr__(result, name, value)
    return result


class ParentGeometryTransfer:
    __slots__ = ('_record', '_native', '_collar', '_funding', '_budget')

    def __init__(self, *args, **kwargs):
        raise TypeError('use bind_parent_geometry after authenticated historical read')

    def __setattr__(self, name, value):
        raise GeometryTransferRefused('geometry transfer binding is immutable')

    def record(self):
        import json
        return json.loads(self._record)

    def matches(self, body, *, funding, collar, budget):
        """Check this exact historical parent, never arbitrary old plan aliases."""
        from atlas_tectonics.integration_differential_geometry import _record_hash
        if (funding is not self._funding or collar is not self._collar
                or budget is not self._budget):
            return False
        scratch = N._Allocation(budget, _matches_scratch_bytes(self, body, collar),
                                category='geometry-transfer-match-scratch')
        expected = self.record()
        with collar._operation(None):
            if N.current_plan_graph(collar._native, collar) != self._native.record()['input']['current_plan_graph']:
                raise GeometryTransferRefused('current plan graph changed after geometry binding')
            assert scratch.size > 0
            return (_record_hash(body) == expected['historical_partition_id']
                and body.get('collar_plan_id') == expected['historical_collar_plan_id']
                and body.get('funding_id') == funding.funding_id
                and collar.plan_id == expected['current_collar_plan_id'])

    def matches_compact(self, view, *, funding, collar, budget):
        """Bounded check of this exact sealed parent: no re-stream per call.

        This runs inside workflow verify() and store writer transactions. The
        sealed constructor fixed view.partition_id from its streamed body hash
        and bind_parent_geometry_compact re-streamed it at the restart boundary,
        so a rehashed foreign parent has a different partition_id. Foreign
        owners return False before any allocation.
        """
        if (funding is not self._funding or collar is not self._collar
                or budget is not self._budget or not _sealed_view(view, budget)):
            return False
        scratch = N._Allocation(budget, _matches_compact_scratch_bytes(self, collar),
                                category='geometry-transfer-match-scratch')
        expected = self.record()
        if view.partition_id != expected['historical_partition_id']:
            return False
        with collar._operation(None):
            if N.current_plan_graph(collar._native, collar) != self._native.record()['input']['current_plan_graph']:
                raise GeometryTransferRefused('current plan graph changed after geometry binding')
            header = _compact_ids(view, MATCH_COMPACT_FIELDS)
            assert scratch.size > 0
            return (header['collar_plan_id'] == expected['historical_collar_plan_id']
                and header['funding_id'] == funding.funding_id
                and collar.plan_id == expected['current_collar_plan_id'])


def bind_parent_geometry(*, native_transfer, partition_descriptor, geometry,
                         funding, collar, budget):
    """Retain a narrow old/new plan bridge; no funding, geometry or fields reset.

    Supplied historical evidence is additionally content-checked here, but its
    authenticity is the independent historical-reader obligation, not inferred
    from the presence of hashes. Only an evolved physical interval is supported.
    """
    from atlas_tectonics import integration_differential_geometry as D
    from atlas_tectonics.integration_collar_geometry import FullCellFunding
    if (type(native_transfer) is not N.OwnedMigratedNativeCollar
            or type(partition_descriptor) is not dict
            or type(geometry) is not D.DifferentialInterval
            or type(funding) is not FullCellFunding
            or any(value is not budget for value in
                (geometry._resource, funding._resource, collar._budget))):
        raise GeometryTransferRefused('actual transferred state and retained physical geometry required')
    supports = partition_descriptor.get('supports')
    if type(supports) is not list:
        raise GeometryTransferRefused('complete retained support list required')
    scratch, decoded = _binding_scratch(native_transfer, collar, budget)
    with collar._operation(None):
        evidence = native_transfer.record()
        current = N.current_plan_graph(collar._native, collar)
        _validate_transfer_contract(native_transfer, evidence, current, budget)
        old_plan_id, clock = _transfer_scalars(evidence)
        del evidence, current, decoded
        _validate_fields(collar, native_transfer.state, budget)
        _validate_parent_descriptor(partition_descriptor, supports, geometry, funding, old_plan_id, clock, budget)
        record = dict(schema='atlas.parent-geometry-transfer.v1',
            native_transfer_id=native_transfer.transfer_id,
            historical_partition_id=partition_descriptor['partition_id'],
            historical_geometry_id=geometry.interval_id,
            historical_collar_plan_id=old_plan_id,
            current_collar_plan_id=collar.plan_id, funding_id=funding.funding_id,
            supports_unchanged=True, scientific_acceptance=False)
        raw = N._json(record)
        allocation = N._Allocation(budget, len(raw)+4096,
                                    category='geometry-transfer-binding-retained')
        result = object.__new__(ParentGeometryTransfer)
        for name, value in dict(_record=N._RecordBytes(raw, allocation), _native=native_transfer,
                _collar=collar, _funding=funding, _budget=budget).items():
            object.__setattr__(result, name, value)
        # Keep scratch in the active frame until all checks/construction finish.
        assert scratch.size > 0
        return result


def bind_parent_geometry_compact(*, native_transfer, compact_partition, geometry,
                                 funding, collar, budget):
    """Compact twin of bind_parent_geometry at the one restart boundary.

    The parent is the sealed CompactPartition on this budget. Its body hash and
    every ordered support hash are re-streamed once here, without decoding the
    whole partition. The record equals the dict route's for the same parent, so
    migration IDs are representation-independent. The view is not retained:
    a separately reopened copy of the same parent matches, a foreign one cannot.
    """
    from atlas_tectonics import integration_differential_geometry as D
    from atlas_tectonics.integration_collar_geometry import FullCellFunding
    if (type(native_transfer) is not N.OwnedMigratedNativeCollar
            or not _sealed_view(compact_partition, budget)
            or type(geometry) is not D.DifferentialInterval
            or type(funding) is not FullCellFunding
            or any(value is not budget for value in
                (geometry._resource, funding._resource, collar._budget))):
        raise GeometryTransferRefused('actual transferred state, sealed compact parent and retained physical geometry required')
    scratch, decoded = _binding_scratch(native_transfer, collar, budget)
    with collar._operation(None):
        evidence = native_transfer.record()
        current = N.current_plan_graph(collar._native, collar)
        _validate_transfer_contract(native_transfer, evidence, current, budget)
        old_plan_id, clock = _transfer_scalars(evidence)
        del evidence, current, decoded
        _validate_fields(collar, native_transfer.state, budget)
        identity = _validate_parent_compact(compact_partition, geometry, funding, old_plan_id, clock, budget)
        result = _issue_binding(dict(schema='atlas.parent-geometry-transfer.v1',
            native_transfer_id=native_transfer.transfer_id,
            historical_partition_id=identity,
            historical_geometry_id=geometry.interval_id,
            historical_collar_plan_id=old_plan_id,
            current_collar_plan_id=collar.plan_id, funding_id=funding.funding_id,
            supports_unchanged=True, scientific_acceptance=False), native_transfer, collar, funding, budget)
        # Keep scratch in the active frame until all checks/construction finish.
        assert scratch.size > 0
        return result


def collar_binding_matches(body, funding, collar, budget, transfer):
    if body.get('collar_plan_id') == collar.plan_id:
        return True
    return (type(transfer) is ParentGeometryTransfer
            and transfer.matches(body, funding=funding, collar=collar, budget=budget))


def collar_binding_matches_compact(view, funding, collar, budget, transfer):
    """Positional compact twin, as partition_native_patch.admit_partition calls it."""
    if not _sealed_view(view, budget):
        return False
    if _compact_ids(view, ('collar_plan_id',))['collar_plan_id'] == collar.plan_id:
        return True
    return (type(transfer) is ParentGeometryTransfer
            and transfer.matches_compact(view, funding=funding, collar=collar, budget=budget))


def candidate_source(package):
    """Two exact old-parent seams only; original default validation is unchanged."""
    source = (Path(package)/'integration_differential_geometry.py').read_text(encoding='utf8')
    return transform(source)


# Legacy parent: `header` is its full record (partition_fields), so the exact
# dict binding applies unchanged. Compact parent: the sealed view is checked.
_PARTITION_BINDING_HELPER = '''

def _transferred_partition_binding(partition, header, funding, collar, budget, transfer):
    if header.get('collar_plan_id') == collar.plan_id:
        return True
    if transfer is None:
        return False
    if getattr(partition, '_compact', None) is None:
        from geometry_transfer import collar_binding_matches
        return collar_binding_matches(header, funding, collar, budget, transfer)
    from partition_native_patch import compact_view
    from geometry_transfer import collar_binding_matches_compact
    return collar_binding_matches_compact(compact_view(partition), funding, collar, budget, transfer)
'''


def transform(source, *, compact=False):
    """Compose after other reviewed additive edits without writing source files.

    compact=True applies after partition_native_patch.transform, whose
    prepare_interval_partition holds a selected header in `old`; hashing that
    header can never equal the full parent ID. Its old-parent check therefore
    uses the actual partition. compact=False refuses such a source.
    """
    if compact:
        if source.count(PARTITION_READER_MARKER) != 1:
            raise GeometryTransferRefused('compact geometry transfer requires the exact partition reader seam')
    elif PARTITION_READER_CALL in source:
        raise GeometryTransferRefused('selected-header partition reader requires transform(..., compact=True)')
    prepare = ('_transferred_partition_binding(parent_partition, old, funding, collar, budget, _runtime_transfer)'
               if compact else '_transferred_collar_binding(old, funding, collar, budget, _runtime_transfer)')
    replacements = (
        ('def restore(cls, record, funding, collar, geometry, *, budget):',
         'def restore(cls, record, funding, collar, geometry, *, budget, _runtime_transfer=None):'),
        ("body.get('funding_id') != funding.funding_id or body.get('collar_plan_id') != collar.plan_id or",
         "body.get('funding_id') != funding.funding_id or not _transferred_collar_binding(body, funding, collar, budget, _runtime_transfer) or"),
        ('                               finite_stock_state, max_components, budget):',
         '                               finite_stock_state, max_components, budget, _runtime_transfer=None):'),
        ("old['collar_plan_id'] != collar.plan_id or previous_network != step['parent_network_id'] or",
         'not '+prepare+" or previous_network != step['parent_network_id'] or"),
    )
    for old, new in replacements:
        if source.count(old) != 1:
            raise GeometryTransferRefused('geometry transfer seam missing or ambiguous: '+old[:70])
        source = source.replace(old, new)
    source += '\n\ndef _transferred_collar_binding(body, funding, collar, budget, transfer):\n'
    source += "    if body.get('collar_plan_id') == collar.plan_id:\n        return True\n"
    source += '    if transfer is None:\n        return False\n'
    source += '    from geometry_transfer import collar_binding_matches\n'
    source += '    return collar_binding_matches(body, funding, collar, budget, transfer)\n'
    if compact:
        source += _PARTITION_BINDING_HELPER
    return source
