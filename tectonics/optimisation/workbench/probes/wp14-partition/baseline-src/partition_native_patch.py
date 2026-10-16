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
from hashlib import sha256
import weakref

import mesh_tables as M
from partition_tables import CompactPartition, NodeRef


BASE_SHA256 = '7d93bae4aef24b1124a05930a49a921662aff9aa36d4995ab62fac2bd19b1034'
COUPLING_SHA256 = '9938992a75e5a70323810a055be1e7e0b8519f44c04c56c0142ac1df90d327c7'
MAX_NATIVE_SUPPORT_BYTES = 128 << 20
MAX_HEADER_BYTES = 16 << 20


def _is_v2(view):
    from partition_v2 import PartitionV2
    return type(view) is PartitionV2


def _native():
    from atlas_tectonics import integration_differential_geometry as D
    return D


def compact_view(partition):
    D = _native()
    if type(partition) is not D.DifferentialPartition:
        raise D.V.VolumeError('actual issued differential partition required')
    view = getattr(partition, '_compact', None)
    if view is not None and ((type(view) is not CompactPartition and not _is_v2(view)) or not getattr(view, '_sealed', False)
                             or view.budget is not partition._resource):
        raise D.V.VolumeError('actual immutable same-budget compact partition required')
    return view


def _size(view, ref, ceiling):
    from record_views import RecordRef
    if isinstance(ref, RecordRef):
        total = ref.identity().canonical_bytes
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
    from record_views import RecordRef
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
    if rows.kind not in ('list', 'array'):
        raise _native().V.VolumeError('indexed partition list required')
    for i in range(rows.size):
        row = rows.at(i)
        if fields is None:
            _size(view, row, MAX_HEADER_BYTES)
            yield view.legacy_record(row)
        else:
            yield _view_fields(view, row, fields)


def owned_support_record(support):
    """One owned decoded support, respecting legacy and compact source routes."""
    D = _native()
    if type(support) is not D.DifferentialSupport:
        raise D.V.VolumeError('actual issued differential support required')
    ref = getattr(support, '_compact_ref', None)
    if ref is not None:
        from record_views import RecordRef
        if isinstance(ref, RecordRef):
            if ref.scope.run_budget is not support._resource:
                raise D.V.VolumeError('support compact reference or budget differs')
            return ref.export(max_logical_bytes=MAX_NATIVE_SUPPORT_BYTES, max_owned_bytes=256 << 20)
        if type(ref) is not NodeRef or ref._view.budget is not support._resource:
            raise D.V.VolumeError('support compact reference or budget differs')
        _size(ref._view, ref, MAX_NATIVE_SUPPORT_BYTES)
        return ref._view.legacy_record(ref)
    owner = M._Allocation(support._resource, M._decode_charge(support._json)+65536)
    return M.OwnedRow(support.record(), owner)


def materialise_support(view, index):
    """Actual native exact-query handle; caller must not retain all JSON handles."""
    D = _native()
    if (type(view) is not CompactPartition and not _is_v2(view)) or not getattr(view, '_sealed', False):
        raise D.V.VolumeError('actual validated compact partition required')
    ref = view.support(index)
    _size(view, ref, MAX_NATIVE_SUPPORT_BYTES)
    owned = (view.legacy_record(ref, max_logical_bytes=MAX_NATIVE_SUPPORT_BYTES)
             if _is_v2(view) else view.legacy_record(ref))
    result = D._issue(D.DifferentialSupport, owned.value, view.budget)
    if result.support_id != view.support_id(index):
        raise D.V.VolumeError('native materialised support identity differs')
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
        if type(i) is not int:
            raise TypeError('explicit support index required; no eager slice')
        if i < 0:
            i += len(self)
        return materialise_support(self.view, i)


class _RetainedRows:
    """Retain decode charges, not whole rows, for descendants in new charts."""
    def __init__(self, partition):
        self.owner = M._Allocation(partition._resource, 4096+256*len(partition.supports))
        self.leases = []

    def keep(self, row):
        from content_cache import Owned
        self.leases.append(row.retain() if isinstance(row, Owned) else row._owner)


def admit_partition(cls, view, funding, collar, geometry, *, budget, _runtime_transfer=None):
    D = _native()
    if (cls is not D.DifferentialPartition or (type(view) is not CompactPartition and not _is_v2(view)) or
            not getattr(view, '_sealed', False) or view.budget is not budget):
        raise D.V.VolumeError('complete validated compact partition and shared budget required')
    M._budget(budget)
    header = _view_fields(view, view.root(), ('schema', 'funding_id', 'collar_plan_id', 'source',
        'scope', 'current_geometry_id', 'interval_id'))
    body = header.value
    collar_matches = body.get('collar_plan_id') == collar.plan_id
    if not collar_matches and _runtime_transfer is not None:
        from geometry_transfer import collar_binding_matches_compact
        collar_matches = collar_binding_matches_compact(view, funding, collar, budget, _runtime_transfer)
    # Hash/ordered-support checks were made by CompactPartition, not inferred
    # from booleans. These are the remaining original native restore gates.
    if (body.get('schema') != 'atlas.differential-partition.v1' or
            body.get('funding_id') != funding.funding_id or not collar_matches or
            body.get('source') != funding.descriptor()['source'] or
            any(b is not budget for b in (funding._resource, collar._budget, geometry._resource))):
        raise D.V.VolumeError('retained partition source, geometry inventory or identity differs')
    if body['scope'] == 'initial-current':
        valid = type(geometry) is D.CurrentGeometry and body['current_geometry_id'] == geometry.geometry_id
    else:
        valid = type(geometry) is D.DifferentialInterval and body['interval_id'] == geometry.interval_id
    if not valid:
        raise D.V.VolumeError('retained partition belongs to a different actual geometry')
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


def _once(source, old, new):
    if source.count(old) != 1:
        raise ValueError('native partition patch seam differs: '+old[:100])
    return source.replace(old, new, 1)


def transform(source):
    """Exact frozen geometry source -> private additive native candidate."""
    if sha256(source.encode()).hexdigest() != BASE_SHA256:
        raise ValueError('unreviewed differential geometry source')
    source = _once(source, '    _supports: tuple = field(repr=False, compare=False)\n',
                   '    _supports: tuple = field(repr=False, compare=False)\n'
                   '    _compact: object = field(repr=False, compare=False)\n')
    at = source.index('class DifferentialSupport:')
    end = source.index('\n\n@dataclass', at)
    support = source[at:end]
    support = _once(support, '    _resource: object = field(repr=False, compare=False)\n',
        '    _resource: object = field(repr=False, compare=False)\n'
        '    _compact_ref: object = field(repr=False, compare=False)\n')
    source = source[:at]+support+source[end:]
    at = source.index('class DifferentialPartition:')
    end = source.index('\n\n@dataclass', at)
    part = source[at:end]
    part = _once(part, '        return hashlib.sha256(self._json).hexdigest()\n',
        "        compact = getattr(self, '_compact', None)\n"
        '        return compact.partition_id if compact is not None else hashlib.sha256(self._json).hexdigest()\n')
    part = _once(part, '    def record(self):\n        return json.loads(self._json)\n',
        "    def record(self):\n        if getattr(self, '_compact', None) is not None:\n"
        "            raise V.VolumeError('compact partition requires indexed access or owned legacy_record export')\n"
        '        return json.loads(self._json)\n\n'
        '    def compact_view(self):\n'
        '        from partition_native_patch import compact_view\n'
        '        return compact_view(self)\n\n'
        '    def legacy_record(self):\n'
        '        from partition_native_patch import partition_fields\n'
        '        compact = self.compact_view()\n'
        '        return partition_fields(self, ()) if compact is None else compact.legacy_record()\n\n'
        '    @classmethod\n'
        '    def from_compact(cls, view, funding, collar, geometry, *, budget, _runtime_transfer=None):\n'
        '        from partition_native_patch import admit_partition\n'
        '        return admit_partition(cls, view, funding, collar, geometry, budget=budget, _runtime_transfer=_runtime_transfer)\n')
    source = source[:at]+part+source[end:]
    at = source.index('def prepare_interval_partition(')
    end = source.index('\n\ndef enclose_initial_partition(', at)
    prepare = source[at:end]
    prepare = _once(prepare, '    old, step, original = parent_partition.record(), interval.record(), funding.descriptor()\n',
        '    from partition_native_patch import partition_fields, partition_rows, owned_support_record, _RetainedRows\n'
        "    old_owner = partition_fields(parent_partition, ('scope', 'network_id', 'endpoint_network_id',\n"
        "        'trajectory_id', 'funding_id', 'source', 'collar_plan_id', 'end_time_s', 'start_time_s', 'grid_lines'))\n"
        '    old, step, original = old_owner.value, interval.record(), funding.descriptor()\n'
        '    retained_rows = _RetainedRows(parent_partition)\n')
    prepare = _once(prepare, '    for support in parent_partition.supports:\n        r = support.record()\n',
        '    for support in parent_partition.supports:\n'
        '        support_owner = owned_support_record(support)\n'
        '        retained_rows.keep(support_owner)\n'
        '        r = support_owner.value\n')
    prepare = _once(prepare,
        "                matching = {r['radial_band'] for r in old['source_regions'] if r['plate_id'] == plate and\n"
        "                            r['radial_layer'] == layer.record()}\n",
        "                matching = {owned.value['radial_band'] for owned in partition_rows(parent_partition,\n"
        "                    'source_regions', fields=('radial_band', 'plate_id', 'radial_layer'))\n"
        "                    if owned.value['plate_id'] == plate and owned.value['radial_layer'] == layer.record()}\n")
    return source[:at]+prepare+source[end:]


def transform_coupling(source):
    """Only the accepted-parent header read changes; all native checks remain."""
    if sha256(source.encode()).hexdigest() != COUPLING_SHA256:
        raise ValueError('unreviewed differential coupling source')
    return _once(source,
        '        current, part, force, drive = current_geometry.record(), parent_partition.record(), pressure.descriptor(), initial_driver.descriptor()\n',
        '        from partition_native_patch import partition_fields\n'
        "        part_owner = partition_fields(parent_partition, ('end_time_s', 'funding_id'))\n"
        '        current, part, force, drive = current_geometry.record(), part_owner.value, pressure.descriptor(), initial_driver.descriptor()\n')
