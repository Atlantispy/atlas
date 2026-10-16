"""Rebuild live owners from a separately authenticated historical endpoint.

No fresh funding, initial-state construction or physical solve is performed.
Historical scientific checks remain bound to their original runtime; current
owners validate unchanged state under a separately reviewed compatibility
policy. Compact migration converts archived records one charged decode at a
time, retaining their exact logical bytes as evidence without re-admitting them.
"""
from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import sha256
import json
import sys
from pathlib import Path

import native_transfer as N
import workflow_transfer as W


class EndpointMaterialisationRefused(ValueError):
    pass


@dataclass(frozen=True)
class DecodedRecord:
    """Borrow value only while retaining this owner, including in tracebacks."""
    value: dict
    _allocations: tuple


def _require(value, message):
    if not value:
        raise EndpointMaterialisationRefused(message)


def _canonical_bound(value, raw):
    """(encoded bytes, sorted-item entries) upper bounds; ``value`` is json.loads(raw).

    Each token json.loads keeps from ``raw`` becomes one output token of the
    canonical encoding. Whitespace and overwritten duplicate keys only shrink;
    integers and true/false/null never grow; a float token has at least 3 bytes
    and its repr at most 24. Canonical output contains only ASCII without NUL
    or DEL. If ``raw`` does too, json.loads decodes it as UTF-8 and no string
    code point escapes to more bytes than its raw spelling. Otherwise a code
    point escapes to at most 12 bytes (two \\uXXXX for non-BMP) from at least
    one raw byte. Sorting copies a dict's items while its subtree encodes, so
    the entries on the deepest path bound that workspace.
    """
    escaped = not (raw.isascii() and b'\x00' not in raw and b'\x7f' not in raw)
    floats = grown = path = deepest = 0
    stack = [value]
    while stack:
        item = stack.pop()
        kind = type(item)
        if kind is dict:
            path += len(item)
            deepest = max(deepest, path)
            stack.append((len(item),))  # leaves this dict's path; JSON has no tuples
            stack.extend(item.values())
            if escaped:
                stack.extend(item)
        elif kind is list:
            stack.extend(item)
        elif kind is tuple:
            path -= item[0]
        elif kind is float:
            floats += 1
        elif escaped and kind is str and not (item.isascii() and item.isprintable()):
            grown += len(item)
    return len(raw)+21*floats+11*grown, deepest


def _canonical_equal(value, raw, budget):
    """Exactly ``W.canonical(value) == raw``, without its 8 MiB metadata cap.

    W.canonical's cap bounds small migration metadata; authenticated historical
    records (r9 head partition 114 MB, mesh 191 MB) need the same check. Same
    encoder call and the same refusal for an unencodable value. The re-encoding
    workspace is charged before encoding and stays charged while a raised error
    retains this frame: the C encoder's writer over-allocates by half and may
    copy on growth (2.5x output), .encode() then holds str and bytes (2x), and
    each sorted dict item list (72 bytes per entry) lives while its subtree
    encodes. 256 KiB covers the bounded-depth markers and per-scalar text.
    """
    width, entries = _canonical_bound(value, raw)
    workspace = N._Allocation(budget, (1 << 18)+(5*width+1)//2+80*entries,
                              category='restart-canonical-encode')
    try:
        encoded = json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    except (TypeError, ValueError) as error:
        raise W.WorkflowTransferRefused('finite JSON metadata required') from error
    result = encoded == raw
    del encoded, workspace
    return result


def check_field_group(arrays, rows):
    """Only spelling-equivalent native little-endian binary64 is normalised."""
    import numpy as np
    _require(type(rows) is list and rows and type(arrays) is dict,
             'complete recorded physical field group required')
    _require(set(arrays) == {row['name'] for row in rows} and
             len(rows) == len(arrays), 'physical field coverage differs')
    for row in rows:
        array = arrays[row['name']]
        _require(sys.byteorder == 'little' and row['dtype'] in ('float64', '<f8') and
                 type(array) is np.ndarray and array.dtype == np.dtype('<f8') and
                 list(array.shape) == row['shape'] and array.flags.c_contiguous and
                 sha256(memoryview(array).cast('B')).hexdigest() == row['sha256'],
                 'recorded physical field bytes, order or type differ: '+row['name'])


@contextmanager
def partition_record(header, arrays, budget):
    """Decode only the exact canonical archived parent, retaining its charge."""
    import numpy as np
    from atlas_tectonics.integration_regional_workflow import CollarWorkflow
    refs = header.get('record_blobs', {})
    _require(set(refs) == {'partition'} and set(arrays) == {'partition-record:partition'},
             'complete evolved parent partition payload required')
    ref, values = refs['partition'], arrays['partition-record:partition']
    _require(set(ref) == {'array', 'bytes', 'sha256'} and ref['array'] == 'partition-record:partition' and
             type(values) is np.ndarray and values.dtype == np.dtype('uint8') and values.ndim == 1 and
             type(ref['bytes']) is int and ref['bytes'] == values.nbytes,
             'parent partition byte layout differs')
    scratch = N._Allocation(budget, 65536+4*values.nbytes, category='restart-partition-raw')
    raw = values.tobytes()
    _require(sha256(raw).hexdigest() == ref['sha256'], 'parent partition bytes changed')
    slots = 1+sum(raw.count(token) for token in (b'{', b'[', b':', b','))
    decoded = N._Allocation(budget, 65536+4*len(raw)+128*slots, category='restart-partition-decoded')
    record = json.loads(raw)
    _require(type(record) is dict and _canonical_equal(record, raw, budget),
             'parent partition is not canonical')
    _require(CollarWorkflow._partition_header(record, refs) == header,
             'parent partition header differs from complete record')
    del raw, scratch
    # A held exception retains both the graph and its allocation. Do not release
    # charged decoded storage while traceback frames can still refer to it.
    yield DecodedRecord(record, (decoded,))
    _ = decoded


@contextmanager
def spatial_records(header, arrays, budget, *, compact_mesh=None, working_store=None,
                    source_producer=None, check=lambda: None, scope=None, compact_partition=None):
    """Original state/mesh checks with traceback-owned decode reservations.

    Deliberately state-only: authenticated historical exchange/heat records stay
    in the original store, not in the new current owner's state. There is no
    acceptance claim for those records under the new runtime.
    """
    import numpy as np
    from atlas_tectonics.integration_regional_workflow import CollarWorkflow
    refs = header.get('record_blobs', {})
    required_arrays = {'spatial-record:state'} if compact_mesh is not None else {'spatial-record:state', 'spatial-record:mesh'}
    _require(set(refs) == {'state', 'mesh'} and set(arrays) == required_arrays,
             'complete saved spatial state and mesh required')
    records, allocations = {}, []
    for kind in sorted(refs):
        if kind == 'mesh' and compact_mesh is not None:
            import spatial_transfer as S
            identity, _ = S._stream_stats(compact_mesh)
            _require(identity == {'sha256': refs['mesh']['sha256'], 'nbytes': refs['mesh']['bytes']},
                     'compact mesh differs from original authenticated historical bytes')
            records[kind] = compact_mesh
            continue
        ref, values = refs[kind], arrays['spatial-record:'+kind]
        _require(set(ref) == {'array', 'bytes', 'sha256'} and ref['array'] == 'spatial-record:'+kind and
                 type(values) is np.ndarray and values.dtype == np.dtype('uint8') and values.ndim == 1 and
                 type(ref['bytes']) is int and ref['bytes'] == values.nbytes,
                 'saved spatial record byte layout differs')
        raw_owner = N._Allocation(budget, 65536+2*values.nbytes, category='restart-spatial-record-read')
        raw = values.tobytes()
        _require(sha256(raw).hexdigest() == ref['sha256'], 'saved spatial record bytes changed')
        slots = 1+sum(raw.count(token) for token in (b'{', b'[', b':', b','))
        decoded_allocation = N._Allocation(budget, 65536+6*len(raw)+128*slots,
                                          category='restart-spatial-record-decode')
        record = json.loads(raw)
        _require(type(record) is dict and _canonical_equal(record, raw, budget), 'saved spatial record is not canonical')
        if kind == 'mesh' and working_store is not None:
            if scope is not None:
                view = convert_mesh_v3(working_store, record, expected_geometry_id=ref['sha256'],
                    source_producer=source_producer, budget=budget, scope=scope,
                    partition=compact_partition, check=check)
            else:
                import spatial_workflow_patch as X
                view, _reference = X.convert_mesh(working_store, record, expected_geometry_id=ref['sha256'],
                    source_producer=source_producer, budget=budget, check=check)
            records[kind] = view
            del record, decoded_allocation
        else:
            records[kind] = record
            allocations.append(decoded_allocation)
        del raw, raw_owner
    state = dict(records['state'], thermal_mesh=records['mesh'])
    _require(CollarWorkflow._spatial_headers(state, None, refs) == (header, None),
             'spatial compact lineage differs from its actual full records')
    yield DecodedRecord(state, tuple(allocations))
    # contextlib may remove this generator from an external error traceback.
    # The explicit returned owner therefore travels with the caller's value.
    _ = allocations


def _working_copy(original_store, working_store, budget, scope=None):
    """Distinct actual same-budget working copy; True for a readonly successor view."""
    from atlas_tectonics.storage import ArrayStore
    compact = W.is_compact_restart_store(working_store, budget=budget, scope=scope)
    _require(not compact or scope is not None, 'compact materialisation requires its explicit retained scope')
    _require((compact or type(working_store) is ArrayStore and scope is None) and working_store._budget is budget and
             Path(working_store.path).resolve() != Path(original_store.path).resolve() and
             (not Path(working_store.path).exists() or not Path(working_store.path).samefile(original_store.path)),
             'compact conversion requires a distinct actual working copy on the shared budget')
    return working_store.readonly if compact else getattr(working_store, '_historical_readonly', None) is not None


def historical_partition_v2(*, original_store, working_store, admission, head,
                            source_producer, budget, scope, check, phase=None):
    """Convert an authenticated legacy descriptor once; reopen only saved v2."""
    import historical_admission as H
    import partition_workflow_patch as PW
    from partition_tables import pack_partition_v2
    from partition_store import publish_partition_v2, open_partition_v2
    readonly = _working_copy(original_store, working_store, budget, scope)
    header = head['differential_partition']
    refs = header.get('record_blobs', {})
    _require(type(header) is dict and 'compact_partition' not in header and set(refs) == {'partition'} and
             type(refs['partition']) is dict and set(refs['partition']) == {'array', 'bytes', 'sha256'} and
             refs['partition']['array'] == 'partition-record:partition',
             'exact historical partition blob binding required')
    binding = dict(schema='atlas.restart-partition-v2-link.v1', partition_id=header['partition_id'],
                   source_producer=source_producer)
    ref = W.compact_migration_reference(working_store, binding, budget=budget)
    bounded = PW.throttled(check)
    if ref is None:
        _require(not readonly, 'readonly successor store lacks its converted compact partition')
        if phase is not None:
            phase('convert-historical-partition')
        check()
        arrays = H.read_selected_arrays(original_store, head['key'], ['partition-record:partition'],
                                        admission=admission, budget=budget, check=check)
        with partition_record(header, arrays, budget) as decoded:
            record = decoded.value
            _require(record.get('partition_id') == header['partition_id'] and type(record.get('supports')) is list,
                     'historical partition descriptor shape differs')
            body = {k: v for k, v in record.items() if k not in PW.DESCRIPTOR_EXTRAS}
            view = pack_partition_v2(body, iter(record['supports']), expected_partition_id=header['partition_id'],
                                     scope=scope, check=bounded)
            del body, record
        del decoded, arrays
        check()
        if phase is not None:
            phase('publish-compact-partition')
        ref = publish_partition_v2(working_store, view,
            producer=W.digest(source_producer), check=check)
        W.compact_migration_reference(working_store, binding, reference=ref, budget=budget)
        view.close()
        del view
    view = open_partition_v2(working_store, ref, scope=scope, check=bounded)
    _require(PW.compact_header(view, refs) == header, 'compact partition differs from the historical header')
    _require(PW.descriptor_stats(view) == {'sha256': refs['partition']['sha256'], 'nbytes': refs['partition']['bytes']},
             'compact partition differs from the authenticated historical bytes')
    check()
    return view


def convert_mesh_v3(store, record, *, expected_geometry_id, source_producer, budget,
                    scope, partition, check):
    """Import owned legacy mesh rows without collecting encoded support blobs."""
    import mesh_tables as M
    import spatial_workflow_patch as X
    from compact_store import CompactMeshStoreV3
    from support_source import SupportSource
    _require(W.is_compact_restart_store(store, budget=budget, scope=scope) and partition.scope is scope,
             'mesh conversion requires the exact retained scope and partition')
    # Values remain borrowed from the caller's charged decoded graph. The lookup
    # adds references only; each encoded support is temporary and codec-funded.
    count = sum(len(rows) for rows in record['support_tables'].values())
    lookup_owner = N._Allocation(budget, 65536+512*count, category='restart-mesh-support-lookup')
    by_content = {}
    for rows in record['support_tables'].values():
        for value in rows.values():
            check()
            by_content[M.digest(value)] = value
    metadata, arrays = M.pack_mesh(record, support_writer=lambda _h, _raw: None, budget=budget, check=check)
    mesh = M.CompactMesh(metadata, arrays,
        support_reader=lambda content, _size, held=(by_content, lookup_owner): M.canonical(held[0][content]),
        expected_geometry_id=expected_geometry_id, budget=budget, check=check)
    source = SupportSource(partition, check=check)
    adapter = CompactMeshStoreV3(store, scope=scope, support_source=source)
    ref = adapter.publish(mesh, producer=W.digest(source_producer), cancel=X._token(check))
    binding = X._link_record(expected_geometry_id, source_producer)
    reference = dict(schema='atlas.compact-mesh-store.v3', segment=ref.to_wire(),
                     geometry_id=expected_geometry_id, source_producer=source_producer)
    W.compact_migration_reference(store, binding, reference=reference, budget=budget, mesh=True)
    del mesh, metadata, arrays, by_content, lookup_owner
    return adapter.open(ref, expected_geometry_id=expected_geometry_id, cancel=X._token(check))


def compact_historical_records(*, original_store, working_store, admission, head,
                               source_producer, budget, scope, check):
    """D6 legacy blobs, one decoded owner at a time; originals remain evidence."""
    import numpy as np
    import historical_admission as H
    import spatial_records_patch as R
    readonly = _working_copy(original_store, working_store, budget, scope)
    scratch = W._decode_allocation(budget, admission._record)
    capsule = admission.record()
    manifest = capsule['snapshot_manifests'][head['key']]
    names = sorted(name for name in manifest['arrays'] if name.startswith(
        ('spatial-record:', 'differential-record:', 'certification-record:')) and name != 'spatial-record:mesh')
    _require(names and 'spatial-record:state' in names, 'complete original historical record inventory required')
    binding = W.compact_history_binding(head['key'], source_producer)
    key = W.digest(binding)
    previous = working_store.metadata(key)
    if previous is not None:
        _require(type(previous) is dict and set(previous) == {'binding', 'records', 'source_manifest_sha256'} and
                 previous['source_manifest_sha256'] == W.digest(manifest) and previous['binding'] == binding and
                 set(previous['records']) == set(names), 'compact historical record inventory differs')
        for name, descriptor in previous['records'].items():
            R.verify_records(working_store, {name: descriptor}, budget=budget,
                             source_producer=source_producer)
        return previous
    _require(not readonly, 'readonly successor store lacks its compact historical records')
    records = {}
    for name in names:
        check()
        arrays = H.read_selected_arrays(original_store, head['key'], [name],
                                        admission=admission, budget=budget, check=check)
        values = arrays[name]
        _require(type(values) is np.ndarray and values.dtype == np.dtype('uint8') and values.ndim == 1,
                 'historical record requires exact byte-array layout')
        raw_owner = N._Allocation(budget, 65536+2*values.nbytes, category='restart-history-raw')
        raw = values.tobytes()
        slots = 1+sum(raw.count(token) for token in (b'{', b'[', b':', b','))
        decoded_owner = N._Allocation(budget, 65536+6*len(raw)+128*slots, category='restart-history-decoded')
        value = json.loads(raw)
        _require(type(value) is dict and _canonical_equal(value, raw, budget), 'historical record is not canonical')
        expected = dict(sha256=sha256(raw).hexdigest(), bytes=len(raw))
        descriptor = R.publish_records(working_store, {name: value}, budget=budget,
            source_producer=source_producer, scope=scope)[name]
        _require({k: descriptor[k] for k in ('sha256', 'bytes')} == expected,
                 'compact historical logical bytes changed')
        records[name] = descriptor
        del value, raw, values, arrays, decoded_owner, raw_owner
        check()
    result = dict(binding=binding, records=records, source_manifest_sha256=W.digest(manifest))
    W.publish_compact_history(working_store, key, result, budget=budget)
    del capsule, manifest, scratch
    return result


def compact_parent_partition(*, original_store, working_store, admission, head, native_transfer,
                             interval, funding, collar, budget, check, phase=None, scope=None,
                             compact_partition=None):
    """X-7: the historical parent as a sealed compact partition and its exact transfer.

    PW.historical_partition finds this working copy's converted root, or converts
    the authenticated original blob exactly once; the view is always opened from
    the working store and bound to the historical header and blob bytes. ``check``
    goes in unwrapped: per-node codec callbacks are throttled there, phase-boundary
    and per-chunk checks stay forced. A readonly successor view must already hold
    the root: a missing one refuses before any original read, conversion or write.
    The transfer record equals bind_parent_geometry's for the same parent, so base
    and root identities do not depend on the representation.
    """
    import geometry_transfer as G
    import partition_store as PS
    import partition_workflow_patch as PW
    import spatial_workflow_patch as X
    from atlas_tectonics import integration_differential_geometry as D
    readonly = _working_copy(original_store, working_store, budget, scope)
    source_producer = X.producer(collar)
    header = head.get('differential_partition') if type(head) is dict else None
    _require(type(header) is dict and type(header.get('partition_id')) is str,
             'historical differential partition header required')
    if scope is not None:
        view = compact_partition
        if view is None:
            view = historical_partition_v2(original_store=original_store, working_store=working_store,
                admission=admission, head=head, source_producer=source_producer, budget=budget,
                scope=scope, check=check, phase=phase)
        from partition_v2 import PartitionV2
        _require(type(view) is PartitionV2 and view.scope is scope and
                 view.partition_id == header['partition_id'], 'actual matching same-scope historical partition required')
    elif readonly:
        _require(PS.CompactPartitionStore(working_store, budget=budget).find(header['partition_id'],
                 source_producer) is not None, 'readonly successor store lacks its converted compact partition')
    if scope is None:
        view = PW.historical_partition(original_store=original_store, working_store=working_store,
            admission=admission, head=head, source_producer=source_producer, budget=budget, check=check, phase=phase)
    bridge = G.bind_parent_geometry_compact(native_transfer=native_transfer, compact_partition=view,
        geometry=interval, funding=funding, collar=collar, budget=budget)
    partition = D.DifferentialPartition.from_compact(view, funding, collar, interval,
                                                     budget=budget, _runtime_transfer=bridge)
    del view
    return bridge, partition


@contextmanager
def materialise(*, original_store, admission, native, collar, execution,
                compatibility, budget, check, working_store=None, phase=None, scope=None):
    """Yield an actual migrated base, closing its owner on all exit paths.

    ``compatibility`` supplies the exact pinned policy/source paths accepted by
    runtime_compatibility.admit. The enclosing frozen launcher owns those pins.
    ``check`` is its existing resource/cancellation check, not another watchdog.
    The readonly original remains the source even after a working copy advances.
    With ``working_store`` the mesh and partition are found in, or converted once
    into, that copy; a readonly successor view must already hold both. ``phase``
    optionally marks 'convert-historical-partition'/'publish-compact-partition'.
    """
    import numpy as np
    import historical_admission as H
    import spatial_transfer as S
    import geometry_transfer as G
    import runtime_compatibility as C
    from atlas_tectonics import integration_differential_geometry as D
    from atlas_tectonics.integration_regional_workflow import CollarWorkflow
    _require(type(admission) is W.HistoricalEndpointAdmission and type(compatibility) is dict,
             'actual historical admission and bound policy arguments required')
    _require(original_store._budget is budget and native._resource is budget and collar._budget is budget,
             'one shared budget required')
    _require(phase is None or callable(phase), 'optional callable phase marker required')
    _require(scope is None or working_store is not None, 'retained materialisation requires its interval store')
    readonly = False if working_store is None else _working_copy(original_store, working_store, budget, scope)
    scratch = W._decode_allocation(budget, admission._record, admission._binding)
    capsule, binding = admission.record(), admission.binding()
    root, head = capsule['chain_metadata'][0], capsule['chain_metadata'][-1]
    groups = capsule['producer']['array_records']
    _require(set(groups) == {'collar', 'native', 'exterior', 'source_audit', 'full_collar', 'spatial_audit'},
             'all original endpoint groups required')
    _require(Path(original_store.path).resolve() == Path(binding['original_database_path']).resolve(),
             'materialisation requires the independently authenticated original store')
    graph = H.derive_historical_plan_graph(N.current_plan_graph(native, collar), admission)
    check()
    fields = H.read_selected_arrays(original_store, head['key'],
        [row['name'] for row in groups['full_collar']], admission=admission, budget=budget, check=check)
    check_field_group(fields, groups['full_collar'])
    native_scratch = N._Allocation(budget, 65536+sum(a.nbytes for a in fields.values()),
                                    category='restart-native-field-slices')
    native_fields = {name: np.ascontiguousarray(collar._slice(name, value)) for name, value in fields.items()}
    check_field_group(native_fields, groups['native'])
    with N.admit_migrated_native_collar(native=native, collar=collar, historical_graph=graph,
            historical_native=head['state']['native'], historical_native_id=head['native_state_id'],
            native_arrays=native_fields, historical_collar=head['state'], collar_arrays=fields,
            origin=binding['origin']) as lease:
        transferred = lease.adopt()
    del fields, native_fields, native_scratch
    runtime = C.admit(**compatibility, historical_admission=admission,
        native_transfer=transferred, execution=execution, budget=budget)
    check()
    funding_arrays = H.read_selected_arrays(original_store, root['key'], sorted(N._REQUIRED_ARRAYS),
        admission=admission, budget=budget, check=check)
    spatial_arrays = H.read_selected_arrays(original_store, head['key'],
        ['exterior-fv:'+row['name'] for row in groups['exterior']],
        admission=admission, budget=budget, check=check)
    spatial_arrays = {name.removeprefix('exterior-fv:'): value for name, value in spatial_arrays.items()}
    check_field_group(spatial_arrays, groups['exterior'])
    compact_mesh, compact_partition, source_producer, conversion_check = None, None, None, check
    if working_store is not None:
        import spatial_workflow_patch as X
        import partition_workflow_patch as PW
        from compact_store import CompactMeshStore
        source_producer = X.producer(collar)
        # M23: per-node mesh codec callbacks reach the forced check at most every
        # 0.25 s; the partition route throttles its own per-node callbacks.
        conversion_check = PW.throttled(check)
        if scope is not None:
            compact_partition = historical_partition_v2(original_store=original_store, working_store=working_store,
                admission=admission, head=head, source_producer=source_producer, budget=budget,
                scope=scope, check=check, phase=phase)
        ref = X.existing_mesh(working_store, head['exterior_state']['thermal_mesh_id'], source_producer, budget=budget)
        if ref is not None:
            if scope is not None:
                from compact_store import CompactMeshStoreV3
                from compact_contracts import SegmentRef
                _require(ref['schema'] == 'atlas.compact-mesh-store.v3', 'retained materialisation requires mesh v3')
                compact_mesh = CompactMeshStoreV3(working_store, scope=scope).open(
                    SegmentRef.from_wire(ref['segment']), expected_geometry_id=head['exterior_state']['thermal_mesh_id'],
                    cancel=X._token(conversion_check))
            else:
                compact_mesh = CompactMeshStore(working_store, budget=budget).open(ref['snapshot_key'],
                    expected_geometry_id=head['exterior_state']['thermal_mesh_id'], cancel=X._token(conversion_check))
        else:
            _require(not readonly, 'readonly successor store lacks its converted compact mesh')
    blob_names = ['spatial-record:state']+([] if compact_mesh is not None else ['spatial-record:mesh'])
    blobs = H.read_selected_arrays(original_store, head['key'], blob_names,
                                   admission=admission, budget=budget, check=check)
    spatial = None
    try:
        with spatial_records(head['exterior_state'], blobs, budget, compact_mesh=compact_mesh,
                working_store=working_store, source_producer=source_producer, check=conversion_check,
                scope=scope, compact_partition=compact_partition) as decoded:
            funding_binding = dict(funding_id=root['funding_id'], debit_count=1,
                ledger_sha256=W.digest(dict(funding=root['funding'],
                    exterior_remainder=root['exterior_remainder'], historical_admission=W.digest(binding))))
            with S.admit_migrated_spatial_owner(collar=collar, native_transfer=transferred,
                    funding_record=root['funding'], funding_arrays=funding_arrays,
                    historical_owner_definition=root['exterior_owner'], historical_spatial_record=decoded.value,
                    spatial_arrays=spatial_arrays, funding_binding=funding_binding, origin=binding['origin']) as lease:
                spatial = lease.adopt()
            if scope is not None:
                _require(spatial.owner._budget is budget and
                         getattr(spatial.owner, '_record_scope', scope) is scope,
                         'transferred owner has a foreign retained scope')
                spatial.owner._record_scope = scope
        del decoded, blobs, funding_arrays, spatial_arrays, compact_mesh
        check()
        inventory = capsule['snapshot_manifests'][head['key']]['arrays']
        geometry_names = [name for name in inventory
                          if name == 'differential-record:geometry' or name.startswith('differential-network:')]
        geometry_arrays = H.read_selected_arrays(original_store, head['key'], geometry_names,
            admission=admission, budget=budget, check=check)
        interval = CollarWorkflow._restore_differential(head['differential_geometry'], geometry_arrays, budget)
        del geometry_arrays
        if working_store is not None:
            bridge, partition = compact_parent_partition(original_store=original_store,
                working_store=working_store, admission=admission, head=head, native_transfer=transferred,
                interval=interval, funding=spatial.funding, collar=collar, budget=budget, check=check, phase=phase,
                scope=scope, compact_partition=compact_partition)
        else:
            parent_arrays = H.read_selected_arrays(original_store, head['key'], ['partition-record:partition'],
                admission=admission, budget=budget, check=check)
            with partition_record(head['differential_partition'], parent_arrays, budget) as decoded:
                bridge = G.bind_parent_geometry(native_transfer=transferred, partition_descriptor=decoded.value,
                    geometry=interval, funding=spatial.funding, collar=collar, budget=budget)
                partition = D.DifferentialPartition.restore(decoded.value, spatial.funding, collar, interval,
                                                           budget=budget, _runtime_transfer=bridge)
            del decoded, parent_arrays
        check()
        if scope is not None:
            compact_historical_records(original_store=original_store, working_store=working_store,
                admission=admission, head=head, source_producer=source_producer,
                budget=budget, scope=scope, check=check)
            from historical_compact_heat import migrate_heat_history
            migrate_heat_history(original_store, working_store, admission,
                source_producer=source_producer, budget=budget, check=check)
        base = W.bind_migrated_base(native_transfer=transferred, spatial_transfer=spatial,
            geometry_transfer=bridge, interval=interval, partition=partition,
            historical_admission=admission, runtime_admission=runtime, budget=budget,
            original_store=original_store if scope is not None else None)
        del capsule, binding, graph, groups, root, head, inventory, scratch
        yield base
    finally:
        if spatial is not None:
            spatial.owner.close()
