"""Additive native partition admission and bounded readers; frozen source intact.

Compact admission repeats the native restore source/budget/geometry gates after
the codec has independently checked the original body and ordered support IDs.
Native supports are issued one at a time for existing exact query validators.
They carry a compact reference so routing/schedulers can retain that reference
instead of their temporary JSON. Those callers need their own explicit adapter:
this module does NOT claim the complete ALE routing path has been converted.

The continuation transform reads the old partition's selected fields and source
region projections. Native construction of the NEW charts/partition is unchanged;
its chart dictionaries are still live work, not eliminated by this reader seam.
"""
from dataclasses import dataclass
import weakref

from atlas_tectonics._private.codecs import mesh_tables as M
from atlas_tectonics._private.codecs.partition_tables import CompactPartition


MAX_NATIVE_SUPPORT_BYTES = 128 << 20
MAX_HEADER_BYTES = 16 << 20


def _is_v2(view):
    from atlas_tectonics._private.integration.geometry.partition_adapter import PartitionV2
    return type(view) is PartitionV2


def _native():
    from atlas_tectonics.integration.geometry import differential_geometry as D
    return D


def compact_view(partition):
    _native()
    view = getattr(partition, '_compact', None)
    return view


def _size(view, ref, ceiling):
    from atlas_tectonics._private.codecs.record_views import RecordRef
    if isinstance(ref, RecordRef):
        total = ref._logical_length() if type(ref) is RecordRef else ref.identity().canonical_bytes
        if total > ceiling:
            raise _native().V.VolumeError('selected native partition operand exceeds explicit byte bound')
        return total
    total = 0
    for chunk in view.iter_legacy_json(ref):
        total += len(chunk)
        if total > ceiling:
            raise _native().V.VolumeError('selected native partition operand exceeds explicit byte bound')
    return total


def _view_fields(view, ref, fields):
    from atlas_tectonics._private.codecs.record_views import RecordRef
    if isinstance(ref, RecordRef):
        allocation = M._Allocation(ref.scope.run_budget, 4096+512*len(fields))
        result, owners, total = {}, [], 0
        for name in fields:
            try:
                child = ref.field(name)
            except KeyError:
                continue
            try:
                total += _size(view, child, MAX_HEADER_BYTES)
                if total > MAX_HEADER_BYTES:
                    raise _native().V.VolumeError('selected partition header exceeds explicit byte bound')
                owner = child.export(max_logical_bytes=MAX_HEADER_BYTES, max_owned_bytes=256 << 20)
                owners.append(owner); result[name] = owner.value
            finally:
                child.close()
        return M.OwnedRow(result, (allocation, tuple(owners), view))
    names = ref.row()
    allocation = M._Allocation(view.budget, 4096+512*len(fields))
    result, owners, total = {}, [], 0
    for name in fields:
        if name not in names.value:
            continue
        child = names.value[name]
        total += _size(view, child, MAX_HEADER_BYTES)
        if total > MAX_HEADER_BYTES:
            raise _native().V.VolumeError('selected partition header exceeds explicit byte bound')
        owner = child.scalar() if child.kind not in ('object', 'list') else view.legacy_record(child)
        owners.append(owner)
        result[name] = owner.value
    return M.OwnedRow(result, (allocation, tuple(owners), view))


def partition_fields(partition, fields):
    """Owned selection; never turn the compact root into a complete dictionary."""
    view = compact_view(partition)
    if view is not None:
        return _view_fields(view, view.root(), fields)
    # Ordinary native path has the same complete record, with explicit lifetime
    # accounting for the decoded copy; no native field or gate is removed.
    owner = M._Allocation(partition._resource, M._decode_charge(partition._json)+65536)
    return M.OwnedRow(partition.record(), owner)


def partition_rows(partition, field, *, fields=None):
    """Yield owned rows. Keep each yielded wrapper while borrowing its value."""
    view = compact_view(partition)
    if view is None:
        owner = partition_fields(partition, ())
        for row in owner.value[field]:
            yield M.OwnedRow(row if fields is None else {k: row[k] for k in fields if k in row}, owner)
        return
    rows = view.root().field(field)
    for i in range(rows.size):
        row = rows.at(i)
        if fields is None:
            _size(view, row, MAX_HEADER_BYTES)
            yield view.legacy_record(row)
        else:
            yield _view_fields(view, row, fields)


def owned_support_record(support):
    """One owned decoded support, respecting legacy and compact source routes."""
    _native()
    ref = getattr(support, '_compact_ref', None)
    if ref is not None:
        from atlas_tectonics._private.codecs.record_views import RecordRef
        if isinstance(ref, RecordRef):
            return ref.export(max_logical_bytes=MAX_NATIVE_SUPPORT_BYTES, max_owned_bytes=256 << 20)
        _size(ref._view, ref, MAX_NATIVE_SUPPORT_BYTES)
        return ref._view.legacy_record(ref)
    owner = M._Allocation(support._resource, M._decode_charge(support._json)+65536)
    return M.OwnedRow(support.record(), owner)


def support_records(partition, *, fields=None):
    """One paid support row/selection; keep the yielded owner while borrowing."""
    view = compact_view(partition)
    if view is None:
        for support in partition.supports:
            yield owned_support_record(support)
        return
    for index in range(view.support_count):
        ref = view.support(index)
        if fields is not None:
            owned = _view_fields(view, ref, fields)
        elif _is_v2(view):
            owned = ref.export(max_logical_bytes=MAX_NATIVE_SUPPORT_BYTES,
                               max_owned_bytes=256 << 20)
        else:
            _size(view, ref, MAX_NATIVE_SUPPORT_BYTES)
            owned = view.legacy_record(ref)
        if _is_v2(view):
            ref.close()
        yield owned
        del owned, ref


def materialise_support(view, index):
    """Actual native exact-query handle; caller must not retain all JSON handles."""
    D = _native()
    ref = view.support(index)
    _size(view, ref, MAX_NATIVE_SUPPORT_BYTES)
    owned = (view.legacy_record(ref, max_logical_bytes=MAX_NATIVE_SUPPORT_BYTES)
             if _is_v2(view) else view.legacy_record(ref))
    result = D._issue(D.DifferentialSupport, owned.value, view.budget)
    object.__setattr__(result, '_compact_ref', ref)
    return result


@dataclass(frozen=True, slots=True)
class _Supports:
    view: CompactPartition
    owner: object = None

    def __len__(self):
        return self.view.support_count

    def __iter__(self):
        for i in range(len(self)):
            yield materialise_support(self.view, i)

    def __getitem__(self, i):
        if i < 0:
            i += len(self)
        return materialise_support(self.view, i)


class _RetainedRows:
    """Retain decode charges, not whole rows, for descendants in new charts."""
    def __init__(self, partition):
        self.owner = M._Allocation(partition._resource, 4096+256*len(partition.supports))
        self.leases = []

    def keep(self, row):
        from atlas_tectonics._private.codecs.content_cache import Owned
        self.leases.append(row.retain() if isinstance(row, Owned) else row._owner)


def admit_partition(cls, view, funding, collar, geometry, *, budget, _runtime_transfer=None, _source=None):
    """_source: the caller's own decode of funding.descriptor()['source'] from
    this same call (Step 8), so the source gate needs no second whole decode."""
    D = _native()
    M._budget(budget)
    header = _view_fields(view, view.root(), ('schema', 'funding_id', 'collar_plan_id', 'source',
        'scope', 'current_geometry_id', 'interval_id'))
    body = header.value
    collar_matches = body.get('collar_plan_id') == collar.plan_id
    if not collar_matches and _runtime_transfer is not None:
        from atlas_tectonics._private.integration.geometry.geometry_transfer import collar_binding_matches_compact
        collar_matches = collar_binding_matches_compact(view, funding, collar, budget, _runtime_transfer)
    if body['scope'] == 'initial-current':
        type(geometry) is D.CurrentGeometry and body['current_geometry_id'] == geometry.geometry_id
    else:
        type(geometry) is D.DifferentialInterval and body['interval_id'] == geometry.interval_id
    lease = budget.reserve(2048, category='compact-partition-native-wrapper')
    lease.__enter__()
    try:
        result = object.__new__(cls)
        # Distinct compact identities must not compare equal through the native
        # dataclass's byte field. This is explicitly NOT a legacy JSON payload.
        object.__setattr__(result, '_json', b'compact-partition:'+view.partition_id.encode('ascii'))
        object.__setattr__(result, '_resource', budget)
        object.__setattr__(result, '_compact', view)
        object.__setattr__(result, '_supports', _Supports(view,
            view.record._owner.retain() if _is_v2(view) else None))
        weakref.finalize(result, lease.__exit__, None, None, None)
        return result
    except BaseException:
        lease.__exit__(None, None, None)
        raise
