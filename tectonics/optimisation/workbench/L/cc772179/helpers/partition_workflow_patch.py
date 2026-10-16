"""ArrayStore-bound compact partition workflow publication and reopening.

Runtime helpers for the seams in partition_workflow_transform. A converted or
published DAG is storage integrity, not scientific admission: every native
source/funding/collar/geometry gate still runs through from_compact or the
explicit geometry transfer. Normal reopen keeps indexed NodeRef/support handles;
identity is bound by bounded streaming of the exact legacy descriptor bytes, and
no complete support JSON is rebuilt. A fresh native chart's working dictionary
is converted once, at publication.
"""
from contextlib import contextmanager
from hashlib import sha256
import json
import math
import time

import numpy as np

import native_transfer as N
import mesh_tables as M
import partition_tables as P
import partition_native_patch as PN
import partition_store as PS
import spatial_workflow_patch as Y
from compact_store import _cancel, descriptor_digest


PREFIX = 'partition-dag:'
HEADER_KEYS = ('partition_id', 'scope', 'funding_id', 'collar_plan_id', 'grid_id',
               'start_time_s', 'end_time_s', 'current_geometry_id', 'interval_id', 'parent_partition_id')
DESCRIPTOR_EXTRAS = ('partition_id', 'supports')
CHECK_INTERVAL_S = 0.25


class CompactPartitionWorkflowRefused(ValueError):
    pass


def require(value, message):
    if not value:
        raise CompactPartitionWorkflowRefused(message)


def _sealed(view):
    require(type(view) in (P.CompactPartition, P.PartitionV2) and getattr(view, '_sealed', False),
            'actual sealed compact partition required')
    return view


def throttled(check, interval=CHECK_INTERVAL_S):
    """Forward per-node codec callbacks to `check` at most once per interval.

    Phase boundaries still call the caller's check directly. A raising check is
    propagated at once and is retried on the next callback.
    """
    require(callable(check) and type(interval) in (int, float) and 0 < interval <= 60,
            'callable check and bounded positive interval required')
    last = [None]
    def bounded():
        now = time.monotonic()
        if last[0] is None or now-last[0] >= interval:
            check()
            last[0] = time.monotonic()
    return bounded


def _extra(view, name):
    yield M.canonical(name)+b':'
    if name == 'partition_id':
        yield M.canonical(view.partition_id)
        return
    yield b'['
    for i in range(view.support_count):
        if i:
            yield b','
        yield from view.iter_legacy_json(view.support(i))
    yield b']'


def iter_descriptor_json(view):
    """Exact canonical bytes of dict(partition_id, **body, supports=[...]).

    This is the legacy 'partition-record:partition' blob, streamed from the DAG
    in sorted-key order without decoding the graph or any support record.
    """
    _sealed(view)
    if type(view) is P.PartitionV2:
        with view.iter_json() as stream:
            for part in stream:
                with part:
                    yield part.value
        return
    require(view.root().kind == 'object', 'partition body object required')
    lo, hi = view._bounds(view._body)
    keys, children = view._arrays['edge.key'], view._arrays['edge.child']
    offsets, strings = view._arrays['string.offset'], view._arrays['string.bytes']
    owner = M._Allocation(view.budget, 65536+8*P.MAX_STRING_BYTES)
    pending, first = list(DESCRIPTOR_EXTRAS), True
    yield b'{'
    for edge in range(lo, hi):
        k = int(keys[edge])
        raw = strings[int(offsets[k]):int(offsets[k+1])].tobytes()
        name = json.loads(raw)
        require(name not in DESCRIPTOR_EXTRAS, 'partition body shadows a descriptor field')
        while pending and pending[0] < name:
            if not first:
                yield b','
            first = False
            yield from _extra(view, pending.pop(0))
        if not first:
            yield b','
        first = False
        yield raw+b':'
        yield from view.iter_legacy_json(P.NodeRef(view, int(children[edge])))
    while pending:
        if not first:
            yield b','
        first = False
        yield from _extra(view, pending.pop(0))
    yield b'}'
    _ = owner


def descriptor_stats(view):
    digest, size = sha256(), 0
    for part in iter_descriptor_json(view):
        digest.update(part)
        size += len(part)
    return {'sha256': digest.hexdigest(), 'nbytes': size}


class _OwnedHeader(dict):
    """Small header carrying its own charge; a nested reference keeps its own."""
    def __init__(self, value, budget):
        charged = {k: v for k, v in value.items() if k != 'compact_partition'}
        allocation = N._Allocation(budget, 4*N._width(charged)+4096, category='compact-partition-header')
        super().__init__(value)
        object.__setattr__(self, '_allocation', allocation)

    def __setattr__(self, name, value):
        raise CompactPartitionWorkflowRefused('immutable header ownership')


def compact_header(view, refs, reference=None):
    """CollarWorkflow._partition_header(descriptor, refs), plus a compact reference."""
    _sealed(view)
    require(type(refs) is dict and (reference is None or isinstance(reference, dict)),
            'plain record references and optional compact reference required')
    owned = PN._view_fields(view, view.root(), HEADER_KEYS[1:])
    value = dict({'partition_id': view.partition_id}, **owned.value)
    value['record_blobs'] = refs
    if reference is not None:
        value['compact_partition'] = reference
    # Charge the returned header before the selected-field owners are released.
    result = _OwnedHeader(value, view.budget)
    del value, owned
    return result


def field(partition, name):
    """Owned scalar or bounded subtree; the native path keeps its full decode."""
    view = PN.compact_view(partition)
    if view is None:
        # The ordinary expression, unchanged: record()[name] with its own lifetime.
        return M.OwnedRow(partition.record()[name], None)
    owned = PN._view_fields(view, view.root(), (name,))
    return M.OwnedRow(owned.value[name], owned)


def binding(partition, hash_function):
    """The workflow's (pid, parent pid, support-ID hash, pid) partition binding.

    The native path is the original expression. The compact path streams the
    canonical support_ids bytes, i.e. the same sha256-of-canonical-JSON as the
    workflow's _hash; any difference refuses, it cannot accept another partition.
    """
    view = PN.compact_view(partition)
    if view is None:
        p = partition.record()
        return (partition.partition_id, p['parent_partition_id'], hash_function(p['support_ids']), partition.partition_id)
    parent = PN.partition_fields(partition, ('parent_partition_id',))
    digest = sha256()
    if type(view) is P.PartitionV2:
        root = view.root()
        ids = root.field('support_ids')
        try:
            with ids.iter_json() as stream:
                for part in stream:
                    with part:
                        digest.update(part.value)
        finally:
            ids.close(); root.close()
    else:
        for part in view.iter_legacy_json(view.root().field('support_ids')):
            digest.update(part)
    return (view.partition_id, parent.value['parent_partition_id'], digest.hexdigest(), view.partition_id)


class _NativeSupportRows:
    """Decode one native support at a time; each row stays charged while live.

    The packer's loop name holds a row until the next one is yielded, so the
    previous charge is kept one step longer and the last until this is dropped.
    """
    __slots__ = ('_supports', '_budget', '_held')

    def __init__(self, supports, budget):
        self._supports, self._budget, self._held = supports, budget, ()

    def __iter__(self):
        for support in self._supports:
            owner = M._Allocation(self._budget, M._decode_charge(support._json)+65536)
            row = json.loads(support._json)
            self._held = self._held[-1:]+(owner,)
            del owner
            yield row
            row = None


def convert_native(partition, budget, *, check=lambda: None, scope=None):
    """Fresh native partition -> sealed CompactPartition, converted exactly once."""
    from atlas_tectonics.integration_differential_geometry import DifferentialPartition
    require(type(partition) is DifferentialPartition and partition._resource is budget and
            PN.compact_view(partition) is None, 'fresh native shared-budget partition required')
    owner = M._Allocation(budget, M._decode_charge(partition._json)+65536)
    body = json.loads(partition._json)
    rows = _NativeSupportRows(partition.supports, budget)
    if scope is not None:
        from partition_v2 import PartitionV2, pack_partition_v2_record
        require(scope.run_budget is budget, 'same retained scope/run budget required')
        record = pack_partition_v2_record(body, rows, expected_partition_id=partition.partition_id,
                                          scope=scope, check=check)
        # Step 8: the decoded body, its rows and their decode charge end before
        # whole-record validation, as on the CompactPartition branch below.
        del body, rows, owner
        return PartitionV2(record, expected_partition_id=partition.partition_id, check=check)
    metadata, arrays = P.pack_partition(body, rows, expected_partition_id=partition.partition_id,
                                        budget=budget, check=check)
    del body, rows, owner
    view = P.CompactPartition(metadata, arrays, expected_partition_id=partition.partition_id,
                              budget=budget, check=check)
    del metadata, arrays
    return view


def _aliases(store, ref):
    return {PREFIX+name: store.reference(ref['snapshot_key'], name) for name in ref['array_bindings']}


def historical_partition(*, original_store, working_store, admission, head, source_producer, budget, check,
                         phase=None):
    """Find or convert once from the authenticated original, then open from the working copy.

    Both the converting and every later process use a view opened from the
    working store, bound to the historical header and byte-exactly to the
    original 'partition-record:partition' blob. A reopen reads no partition JSON
    and writes nothing. Pass the caller's forced check unwrapped: per-node codec
    callbacks are throttled here, while phase boundaries and the per-chunk
    original read and publication call it directly.
    """
    import historical_admission as H
    import materialise_endpoint as E
    require(callable(check) and (phase is None or callable(phase)), 'callable check and phase required')
    require(working_store is not original_store, 'conversion requires the distinct working copy')
    header = head['differential_partition']
    require(type(header) is dict and 'compact_partition' not in header and type(header.get('record_blobs')) is dict,
            'historical legacy partition header required')
    refs = header['record_blobs']
    require(set(refs) == {'partition'} and type(refs['partition']) is dict and
            set(refs['partition']) == {'array', 'bytes', 'sha256'} and
            refs['partition']['array'] == 'partition-record:partition', 'exact historical partition blob binding required')
    adapter = PS.CompactPartitionStore(working_store, budget=budget)
    bounded = throttled(check)
    ref = adapter.find(header['partition_id'], source_producer)
    if ref is None:
        if phase is not None:
            phase('convert-historical-partition')
        check()
        arrays = H.read_selected_arrays(original_store, head['key'], ['partition-record:partition'],
                                        admission=admission, budget=budget, check=check)
        with E.partition_record(header, arrays, budget) as decoded:
            record = decoded.value
            require(record.get('partition_id') == header['partition_id'] and type(record.get('supports')) is list,
                    'historical partition descriptor shape differs')
            body = {k: v for k, v in record.items() if k not in DESCRIPTOR_EXTRAS}
            metadata, packed = P.pack_partition(body, iter(record['supports']), expected_partition_id=header['partition_id'],
                                                budget=budget, check=bounded)
            del body, record
        # The decoded graph and raw blob die before the second (validated) copy.
        del decoded, arrays
        check()
        view = P.CompactPartition(metadata, packed, expected_partition_id=header['partition_id'],
                                  budget=budget, check=bounded)
        del metadata, packed
        if phase is not None:
            phase('publish-compact-partition')
        ref = adapter.publish(view, source_producer=source_producer, check=check)
        del view
        check()
    view = adapter.open(ref, expected_partition_id=header['partition_id'], check=bounded)
    require(compact_header(view, refs) == header, 'compact partition differs from the historical header')
    require(descriptor_stats(view) == {'sha256': refs['partition']['sha256'], 'nbytes': refs['partition']['bytes']},
            'compact partition differs from the authenticated historical bytes')
    return view


def root_partition(store, partition, source_producer, *, persist, cancel=None):
    """Migrated-root reference/aliases for a compact base partition; never converts."""
    view = PN.compact_view(partition)
    require(view is not None, 'compact base partition required')
    adapter = PS.CompactPartitionStore(store, budget=view.budget)
    ref = adapter.find(view.partition_id, source_producer)
    if ref is None:
        require(persist is True, 'compact partition has not been published in this working store')
        ref = adapter.publish(view, source_producer=source_producer, cancel=cancel)
    return ref, _aliases(store, ref)


def _native_header(partition, reference):
    """compact_header's value for a native partition whose root is already stored."""
    owned = PN.partition_fields(partition, HEADER_KEYS[1:])
    value = dict({'partition_id': partition.partition_id},
                 **{k: owned.value[k] for k in HEADER_KEYS[1:] if k in owned.value})
    value['record_blobs'] = {}
    value['compact_partition'] = reference
    # Charge the returned header before the decoded record's owner is released.
    result = _OwnedHeader(value, partition._resource)
    del value, owned
    return result


@contextmanager
def payload(cls, partition, geometry, funding, collar, budget, *, store, source_producer, cancel=None):
    """Native interval-scope publication gates on owned fields, then one compact root.

    Yields (header, aliases). The root is a separate immutable put before the
    successor's; cancellation can leave a reusable root, never a successor. A
    native partition whose root is already stored (a retry after cancellation or
    a republication) is found first and not converted again; restore() still
    opens and fully validates that root against this header.
    """
    from atlas_tectonics.integration_differential_geometry import DifferentialPartition, DifferentialInterval
    from atlas_tectonics.storage import ArrayStore
    compact_candidate = type(store) is not ArrayStore and getattr(store, 'scope', None) is not None
    require(type(partition) is DifferentialPartition and type(geometry) is DifferentialInterval and
            ((type(store) is ArrayStore and store._budget is budget) or
             (compact_candidate and store.scope.run_budget is budget)) and
            all(r is budget for r in (partition._resource, geometry._resource, funding._resource, collar._budget)),
            'actual interval partition, working store and one shared funding/collar budget required')
    require(type(source_producer) is dict and bool(source_producer), 'actual partition producer required')
    token = Y._token(lambda: None, cancel)
    _cancel(token)
    fields = PN.partition_fields(partition, ('scope', 'funding_id', 'collar_plan_id', 'source', 'interval_id'))
    row = fields.value
    require(row.get('scope') == 'physical-interval' and row.get('funding_id') == funding.funding_id and
            row.get('collar_plan_id') == collar.plan_id and row.get('source') == funding.descriptor()['source'] and
            row.get('interval_id') == geometry.interval_id,
            'partition differs from actual source, geometry or native layout')
    del row, fields
    if compact_candidate:
        view = PN.compact_view(partition)
        if view is None:
            view = convert_native(partition, budget, scope=store.scope,
                                  check=throttled(lambda: _cancel(token)))
        require(type(view) is P.PartitionV2 and view.scope is store.scope,
                'explicit v2 partition required for interval candidate')
        ref = PS.publish_partition_v2(store, view, producer=sha256(N._json(source_producer)).hexdigest(),
                                      cancel=token)
        header = compact_header(view, {}, ref.to_wire())
        del view
        yield header, {}
        return
    adapter = PS.CompactPartitionStore(store, budget=budget)
    view = PN.compact_view(partition)
    ref = None if view is not None else adapter.find(partition.partition_id, source_producer)
    if ref is not None:
        header = _native_header(partition, ref)
    else:
        if view is None:
            view = convert_native(partition, budget, check=throttled(lambda: _cancel(token)))
        ref = adapter.publish(view, source_producer=source_producer, cancel=token)
        header = compact_header(view, {}, ref)
    del view
    yield header, {}


def restore(cls, header, arrays, funding, collar, budget, *, interval, store):
    """Open the successor's compact partition by reference; no legacy blob or transfer."""
    from atlas_tectonics.integration_differential_geometry import DifferentialPartition, DifferentialInterval
    from atlas_tectonics.storage import ArrayStore
    compact_resolver = type(store) is not ArrayStore and getattr(store, 'scope', None) is not None
    require(type(interval) is DifferentialInterval and interval._resource is budget and
            ((type(store) is ArrayStore and store._budget is budget) or
             (compact_resolver and store.scope.run_budget is budget)),
            'actual differential interval and shared-budget working store required')
    require(type(arrays) is dict and not arrays, 'compact partition header cannot also carry legacy partition blobs')
    require(type(header) is dict and {'partition_id', 'record_blobs', 'compact_partition'} <= set(header) and
            set(header) <= set(HEADER_KEYS)|{'record_blobs', 'compact_partition'} and header['record_blobs'] == {},
            'complete compact partition header required')
    ref = header['compact_partition']
    if compact_resolver:
        from compact_contracts import SegmentRef
        view = PS.open_partition_v2(store, SegmentRef.from_wire(ref), scope=store.scope)
    else:
        view = PS.CompactPartitionStore(store, budget=budget).open(ref, expected_partition_id=header['partition_id'])
    require(compact_header(view, {}, ref) == header, 'saved compact partition lineage differs from its stored DAG')
    # New partitions carry the current collar plan: no parent geometry transfer.
    partition = DifferentialPartition.from_compact(view, funding, collar, interval, budget=budget)
    return partition, interval


def _alias_reference(metadata):
    nested = metadata.get('differential_partition')
    found = [ref for ref in (metadata.get('compact_partition'),
                             nested.get('compact_partition') if type(nested) is dict else None) if ref is not None]
    require(len(found) == 1, 'exactly one compact partition reference location required')
    return found[0]


def workflow_arrays(store, key, *, budget):
    """Read non-geometry operands; partition/mesh aliases authenticate, not duplicate."""
    from atlas_tectonics.integration_spatial_transport import _workspace
    with _workspace(budget, 65536+8*store.limits.max_manifest_bytes, 'compact-partition-workflow-manifest'):
        with store._read_scope(budget=budget):
            manifest = store._manifest(key)
            if manifest is None:
                return None
            if any(name.startswith(PREFIX) for name in manifest['arrays']):
                return _aliased_arrays(store, key, manifest, budget)
            meshes = any(name.startswith(Y.PREFIX) for name in manifest['arrays'])
            del manifest
    if meshes:
        # Mesh aliases only: the tested spatial reader runs unchanged.
        return Y.workflow_arrays(store, key, budget=budget)
    # No alias of either kind: the ordinary read itself, after this manifest
    # workspace is released, so its peak is unchanged. Snapshot keys are
    # append-only and immutable, so it reads the manifest classified above.
    return store.get(key, budget=budget)


def _aliased_arrays(store, key, manifest, budget):
    from atlas_tectonics.integration_spatial_transport import _workspace
    metadata = manifest['metadata']
    require(type(metadata) is dict, 'workflow metadata object required')
    ref = _alias_reference(metadata)
    require(isinstance(ref, dict) and type(ref.get('array_bindings')) is dict, 'complete compact partition reference required')
    PS.CompactPartitionStore(store, budget=budget).verify_reference(ref, expected_partition_id=ref.get('partition_id'))
    names = {name for name in manifest['arrays'] if name.startswith(PREFIX)}
    require(names == {PREFIX+n for n in ref['array_bindings']} and
            all(descriptor_digest(manifest['arrays'][PREFIX+n]) == digest for n, digest in ref['array_bindings'].items()),
            'workflow compact partition aliases differ from bound immutable chunks')
    meshes = {name for name in manifest['arrays'] if name.startswith(Y.PREFIX)}
    if meshes:
        exterior = metadata.get('exterior_state')
        mesh = exterior.get('compact_mesh') if type(exterior) is dict else None
        Y.verify_reference(store, mesh, budget=budget)
        require(meshes == {Y.PREFIX+n for n in mesh['array_bindings']} and
                all(descriptor_digest(manifest['arrays'][Y.PREFIX+n]) == digest
                    for n, digest in mesh['array_bindings'].items()),
                'workflow compact mesh aliases differ from bound immutable chunks')
    selected = {n: row for n, row in manifest['arrays'].items() if not n.startswith((PREFIX, Y.PREFIX))}
    total = sum(math.prod(r['shape'])*np.dtype(r['dtype']).itemsize for r in selected.values())
    require(total <= store.limits.max_array_bytes, 'workflow operands exceed read allowance')
    allocation = N._Allocation(budget, total+65536+1024*len(selected), category='compact-partition-workflow-arrays')
    result = {}
    for name, row in selected.items():
        dtype = np.dtype(row['dtype'])
        size = math.prod(row['shape'])*dtype.itemsize
        with _workspace(budget, 2*size+65536, 'compact-partition-workflow-array-read'):
            buffer, count = bytearray(size), 0
            for offset, values in store.iter_chunks(key, name, budget=budget):
                raw = memoryview(values).cast('B')
                require(offset*dtype.itemsize == count and count+len(raw) <= size,
                        'workflow operand chunk coverage differs')
                buffer[count:count+len(raw)] = raw
                count += len(raw)
            require(count == size, 'workflow operand is incomplete')
            result[name] = np.frombuffer(N._RecordBytes(buffer, allocation), dtype=dtype).reshape(row['shape'])
    return result
