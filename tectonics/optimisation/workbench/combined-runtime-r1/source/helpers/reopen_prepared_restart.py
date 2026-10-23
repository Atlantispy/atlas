"""Independent fresh-process reader of a migrated-root restart result.

The runner's same-process root reopen is not independent, and the runner no
longer cold-reopens an interval's successor at all (owner decision 14 Oct 2026),
so this reader performs that successor cold reopen. This entry point
reads the producer's pinned receipt and guard records store-free, then, in a
NEW guarded process with the same source-bound profile, preparation and memory
limits (by-need start gate, 12 GiB RSS / 1 GiB free guard, 16 GiB ledger):

- copies the producer checkpoint into a new output directory and opens only
  that copy, read-only when the reviewed adapter is selected;
- re-authenticates the ORIGINAL and reproduces the exact migrated base;
- reopens the migrated workflow through the actual current-runtime validators
  and compares saved state, arrays, sequence/time, funding, history and
  source/input identity with the producer receipt;
- proves no store writes and confirms clean worker exit and ownership release.

Mode 'successor' checks the advanced interval; 'root-only' checks a staged
STOPPED_BEFORE_ADVANCE_ROOT_PUBLISHED result. Nothing here re-runs physics or
replaces the old sequence-zero validator: validate_migrated_lineage is its
migrated-root replacement. Acceptance is reported only by --finalise, after the
guardian has exited cleanly; production_acceptance is always False.
"""
from contextlib import contextmanager, nullcontext
from fractions import Fraction
from hashlib import sha256
import argparse
import gc
import inspect
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

import run_prepared_restart as RUN

SG, RG = RUN.SG, RUN.RG


READER_SCHEMA = 'atlas.prepared-restart-reopen-result.v1'
FINAL_SCHEMA = 'atlas.prepared-restart-reopen-final.v1'
GUARD_SCHEMA = 'atlas.private.continuation-guard.r3'
MODES = ('successor', 'root-only')
STORE_ROUTES = ('readonly', 'copy-token')
PRODUCER_STATUS = {'successor': RUN.PASS_STATUS, 'root-only': RUN.STOPPED_STATUS}
WORKLOAD_STATUS = {'successor': 'PASS_SUCCESSOR_REOPENED_PENDING_FINALISE',
                   'root-only': 'PASS_ROOT_REOPENED_PENDING_FINALISE'}
FINAL_STATUS = {'successor': 'PASS_SECOND_INTERVAL_INDEPENDENT_REOPEN',
                'root-only': 'PASS_MIGRATED_ROOT_INDEPENDENT_REOPEN_NOT_INTERVAL_ACCEPTANCE'}
CHECKPOINT = 'checkpoint-reopen.sqlite'
COMPACT_DIRECTORY = 'compact-checkpoint'
COMPACT_CATALOG = 'interval-catalog.json'
STORAGE_SCHEMA = 'atlas.prepared-restart-storage.v1'
CATALOG_BYTES = 1 << 20
MAX_RECEIPT = 64 << 20
MAX_SNAPSHOTS = 8192
GROUPS = frozenset(('collar', 'native', 'exterior', 'source_audit', 'full_collar', 'spatial_audit'))
SPATIAL_AUDIT_PREFIX = 'spatial-audit:'
PREPARATIONS = frozenset(('owner', 'spatial_owner', 'native', 'collar', 'map', 'funding'))
CONTINUATION_FIELDS = frozenset(('parent_head_key', 'parent_interval_id', 'interval_id',
    'parent_interval_number', 'interval_number', 'parent_time_seconds', 'time_seconds',
    'root_key', 'funding_id'))
COMPLETED_FIELDS = frozenset(('workflow_id', 'root_key', 'root_metadata', 'head_key', 'producer_pid',
    'store_limits', 'store_compression', 'collar_result_id', 'native_result_id', 'exterior_state_id',
    'source_audit_id', 'joined_heat_id', 'array_records', 'preparation_ids', 'execution_provenance',
    'sequence'))
PUBLISHED_FIELDS = frozenset(('workflow_id', 'root_key', 'root_metadata_sha256', 'sequence', 'inspect',
    'producer_pid', 'store_limits', 'store_compression', 'execution_provenance', 'preparation_ids'))
OBSERVED_FIELDS = frozenset(('interval_id', 'partition_id', 'fields_time_s', 'native_time_s',
    'exterior_time_s', 'funding_id'))
COMPACT_CHECKS = frozenset(('compact_storage_authenticated', 'compact_record_identities_identical',
                            'retained_scope_released'))
RETAINED_SCALARS = ('retained_bytes', 'peak_retained_bytes', 'pinned_bytes', 'pending_bytes',
                    'evictable_bytes', 'non_cache_owned_bytes', 'optional_declines', 'required_refusals')
RETAINED_MAPPINGS = ('hits', 'misses', 'evictions', 'insertions', 'entries', 'reclaimed_bytes',
                     'category_bytes', 'category_peak_bytes', 'purpose_bytes', 'purpose_peak_bytes')
INDEPENDENT_CHECKS = {
    'root-only': frozenset(('source_bound_preparation', 'original_reauthenticated', 'migrated_base_reproduced',
        'initial_workload_reproduced', 'migrated_root_identity', 'funding_preserved', 'history_preserved',
        'store_unchanged', 'native_operations_unchanged', 'reader_copy_and_producer_checkpoint_unchanged',
        'original_database_unchanged')),
    'successor': frozenset(('source_bound_preparation', 'original_reauthenticated', 'migrated_base_reproduced',
        'initial_workload_reproduced', 'migrated_root_identity', 'successor_identity', 'state_identities',
        'all_six_field_groups_identical', 'migrated_lineage', 'funding_preserved', 'history_preserved',
        'store_unchanged', 'native_operations_unchanged', 'reader_copy_and_producer_checkpoint_unchanged',
        'original_database_unchanged'))}


class ReopenRefused(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise ReopenRefused(message)


def _identity(value):
    return type(value) is str and bool(value)


def _digest(value):
    return type(value) is str and len(value) == 64 and all(c in '0123456789abcdef' for c in value)


def _exact_pair(pair, label='exact time'):
    """Read only reduced canonical hexadecimal integer pairs, as native-r6 does."""
    require(type(pair) is list and len(pair) == 2 and all(type(value) is str for value in pair),
            label+' requires a canonical hexadecimal rational pair')
    try:
        numerator, denominator = (int(value, 16) for value in pair)
        require(denominator > 0, label+' requires a positive denominator')
        value = Fraction(numerator, denominator)
    except (ValueError, ZeroDivisionError) as error:
        raise ReopenRefused(label+' requires a canonical hexadecimal rational pair') from error
    require(pair == [hex(value.numerator), hex(value.denominator)],
            label+' is not a reduced canonical hexadecimal rational pair')
    return value


def _clock(value):
    require(type(value) in (int, float, Fraction) and (type(value) is not float or math.isfinite(value)),
            'a finite native endpoint clock is required')
    return Fraction(value)


def canonical_records(groups):
    """Six complete array-record groups, each sorted by unique name."""
    require(type(groups) is dict and set(groups) == GROUPS, 'all six complete endpoint field groups are required')
    result = {}
    for group, records in groups.items():
        require(type(records) is list and records, 'every endpoint group requires its complete array records')
        names = set()
        for row in records:
            require(type(row) is dict and set(row) == {'name', 'shape', 'dtype', 'sha256'} and
                    _identity(row['name']) and _identity(row['dtype']) and type(row['shape']) is list and
                    all(type(size) is int and size >= 0 for size in row['shape']) and _digest(row['sha256']),
                    'complete exact array name, shape, dtype and hash required')
            require(row['name'] not in names, 'duplicate exported array name')
            names.add(row['name'])
        result[group] = sorted(records, key=lambda row: row['name'])
    return result


def spatial_audit_arrays(workflow):
    """Only the successor head's saved 'spatial-audit:*' arrays, budget-charged.

    The native workflow.spatial_audit_arrays property calls store.get(head),
    which decodes EVERY head array, including the partition-dag:/spatial-mesh:
    compact aliases, and refuses the whole read above max_array_bytes (W4
    defect 1). As in restore_migrated_root and partition_workflow_patch.
    workflow_arrays, the head manifest is read once under a charged workspace and
    only the selected arrays' chunks are streamed through store.iter_chunks into
    one reservation that lives until the last returned array dies. Names (prefix
    removed), dtypes, shapes and bytes are those of the native property.
    """
    import numpy as np
    import native_transfer as N
    workflow._refresh()
    store, budget, head = workflow._store, workflow._budget, workflow._head
    require(workflow._is_spatial() and type(head) is dict and head.get('kind') == 'successor',
            'saved spatial audit arrays require a spatial successor head')
    key = head['key']
    with store._workspace(65536+8*store.limits.max_manifest_bytes, budget,
                          category='reopen-spatial-audit-manifest'):
        with store._read_scope(budget=budget):
            manifest = store._manifest(key)
        require(manifest is not None, 'successor head payload is missing')
        selected = {name: (list(row['shape']), row['dtype']) for name, row in manifest['arrays'].items()
                    if name.startswith(SPATIAL_AUDIT_PREFIX)}
        del manifest
    require(selected, 'successor head has no saved spatial audit arrays')
    total = sum(math.prod(shape)*np.dtype(dtype).itemsize for shape, dtype in selected.values())
    require(total <= store.limits.max_array_bytes, 'saved spatial audit arrays exceed the read allowance')
    allocation = N._Allocation(budget, total+65536+1024*len(selected), category='reopen-spatial-audit-arrays')
    result = {}
    for name, (shape, dtype) in sorted(selected.items()):
        dtype = np.dtype(dtype)
        size = math.prod(shape)*dtype.itemsize
        with store._workspace(2*size+65536, budget, category='reopen-spatial-audit-array-read'):
            buffer, count = bytearray(size), 0
            for offset, values in store.iter_chunks(key, name, budget=budget):
                raw = memoryview(values).cast('B')
                require(offset*dtype.itemsize == count and count+len(raw) <= size,
                        'saved spatial audit chunk coverage differs')
                buffer[count:count+len(raw)] = raw
                count += len(raw)
            require(count == size, 'saved spatial audit array is incomplete')
            result[name.removeprefix(SPATIAL_AUDIT_PREFIX)] = np.frombuffer(
                N._RecordBytes(buffer, allocation), dtype=dtype).reshape(shape)
            del buffer
    return result


def endpoint_array_records(D, workflow):
    """The producer's own formulas (probe r9 snapshots/arrays) on reopened state.

    The spatial-audit group reads only the head's audit arrays (spatial_audit_arrays).
    """
    state, exterior = workflow.state, workflow.exterior_state
    return dict(collar=D.snapshots(state.fields), native=D.snapshots(state.native_state),
        exterior=D.snapshots(exterior._snapshot), source_audit=D.snapshots(workflow.source_audit),
        full_collar=D.arrays(state.arrays()), spatial_audit=D.arrays(spatial_audit_arrays(workflow)))


def canonical_record_identities(identities, *, successor):
    """Closed exact logical identities, independent of compact physical layout."""
    expected = {'state', 'partition', 'mesh'}
    if successor:
        expected.update(('exchange', 'graph', 'transport', 'heat', 'certification', 'differential'))
    require(type(identities) is dict and set(identities) == expected,
            'complete compact endpoint logical record identities required')
    for value in identities.values():
        require(type(value) is dict and set(value) == {'sha256', 'nbytes'} and
                _digest(value['sha256']) and type(value['nbytes']) is int and value['nbytes'] > 0,
                'exact compact record hash and canonical byte length required')
    return identities


def endpoint_record_identities(workflow):
    """Recompute every persisted compact endpoint record without full exports.

    The native workflow validators already verify scientific state and lineage.
    This separate stream binds the exact legacy JSON bytes to the producer's
    receipt, including records whose expanded form exceeds native JSON limits.
    """
    import partition_native_patch as PN
    import partition_workflow_patch as PW
    import spatial_records_patch as SR
    import spatial_indexed_patch as SI
    from partition_v2 import PartitionV2
    from mesh_tables import CompactMesh
    store, budget, head = workflow._store, workflow._budget, workflow._head
    scope = getattr(store, 'scope', None)
    require(scope is not None and scope.run_budget is budget,
            'compact endpoint identities require the shared retained store scope')
    require(type(head) is dict and head.get('kind') in ('migrated-root', 'successor'),
            'compact endpoint requires a migrated root or successor')
    successor = head['kind'] == 'successor'
    state = head['exterior_state']
    refs = dict(state['record_blobs'])
    require(set(refs) == {'state'}, 'complete compact state record required')
    if successor:
        exchange = head['exterior_advance']['record_blobs']
        require(set(exchange) == {'exchange', 'graph', 'transport', 'heat'},
                'complete compact exchange records required')
        refs.update(exchange)
        for header, kind in (('differential_certification', 'certification'),
                             ('differential_geometry', 'differential')):
            refs[kind] = head[header]['record_blob']
    result = {}
    with SR.open_records(store, refs, budget=budget, scope=scope,
                         source_producer=state['compact_mesh']['source_producer']) as opened:
        # open_records has just streamed and checked each child's entire exact
        # identity. Reuse that proof instead of reconstructing the same JSON twice.
        for name in opened:
            result[name] = dict(sha256=refs[name]['sha256'], nbytes=refs[name]['bytes'])
        for child in opened.values():
            child.close()
    partition = PN.compact_view(workflow.differential_partition)
    require(type(partition) is PartitionV2 and partition.scope is scope,
            'compact endpoint requires its retained v2 partition')
    result['partition'] = PW.descriptor_stats(partition)
    held = workflow.exterior_state.indexed_record()
    mesh = held.value['thermal_mesh']
    require(type(mesh) is CompactMesh and mesh.scope is scope,
            'compact endpoint requires its retained v3 mesh')
    digest, size = sha256(), 0
    for block in SI.iter_logical_json(mesh):
        digest.update(block)
        size += len(block)
    result['mesh'] = dict(sha256=digest.hexdigest(), nbytes=size)
    del held
    return canonical_record_identities(result, successor=successor)


def validate_guard(guard, control, *, pid, supervisor_pid):
    """Clean worker exit and ownership release for one guarded process."""
    require(type(guard) is dict and type(control) is dict, 'guardian receipt and control required')
    parent = guard.get('parent')
    require(guard.get('schema') == GUARD_SCHEMA and guard.get('status') == 'STOPPED' and
            not guard.get('reason') and guard.get('workload_exit_confirmed') is True and
            guard.get('workload_exit_code') == 0 and
            guard.get('cleanup') == dict(remaining=[], action_errors=[]),
            'guardian did not stop cleanly with a confirmed zero exit and empty job')
    require(type(parent) is dict and type(pid) is int and parent.get('pid') == pid and
            type(parent.get('created_ticks')) is int and parent['created_ticks'] > 0 and
            control.get('parent') == parent, 'guardian parent differs from the recorded workload process')
    require(_identity(guard.get('nonce')) and control.get('nonce') == guard['nonce'] and
            control.get('close_requested') is True, 'guardian/control run identity or close handshake differs')
    guardian = guard.get('guardian')
    require(type(guardian) is dict and type(guardian.get('pid')) is int and guardian['pid'] == supervisor_pid,
            'guardian process differs from the recorded supervisor')
    limits = dict(rss_bytes=RUN.RSS_BYTES, free_floor_bytes=RUN.FREE_BYTES)
    require(guard.get('limits') == limits and control.get('limits') == limits,
            'exact 12 GiB / 1 GiB guardian limits required')


def _published(published, *, row, compact=False):
    require(type(published) is dict and set(published) == PUBLISHED_FIELDS, 'complete published root record required')
    require(_identity(published['workflow_id']) and _identity(published['root_key']) and
            _digest(published['root_metadata_sha256']) and type(published['sequence']) is int and
            published['sequence'] >= 1 and type(published['inspect']) is dict and
            published['inspect'].get('head') == published['root_key'] and
            published['inspect'].get('intervals') == published['sequence'] and
            published['inspect'].get('workflow_id') == published['workflow_id'],
            'published migrated root identity is incomplete')
    ids, provenance = published['preparation_ids'], published['execution_provenance']
    require(type(ids) is dict and set(ids) == PREPARATIONS and all(_identity(v) for v in ids.values()),
            'complete independently exported preparation identities required')
    require(type(provenance) is dict and set(provenance) == {'execution_identity', 'execution_mode'} and
            provenance['execution_mode'] == 'strict' and _digest(provenance['execution_identity']),
            'producer must retain strict source/runtime verification')
    limits = RUN.COMPACT_STORE_LIMITS if compact else row['store_limits']
    compression = RUN.COMPACT_COMPRESSION if compact else row['compression']
    require(published['store_limits'] == limits and published['store_compression'] == compression,
            'producer store limits or compression differ from the profile')
    require(published['inspect'].get('funding_id') == ids['funding'], 'published root funding differs')


def _completed(completed, published, *, pid):
    require(type(completed) is dict and set(completed) == COMPLETED_FIELDS, 'complete advanced endpoint record required')
    for name in ('workflow_id', 'root_key', 'head_key', 'collar_result_id', 'native_result_id',
                 'exterior_state_id', 'source_audit_id', 'joined_heat_id'):
        require(_identity(completed[name]), 'complete endpoint identities are required')
    root = completed['root_metadata']
    require(completed['producer_pid'] == pid and completed['workflow_id'] == published['workflow_id'] and
            completed['root_key'] == published['root_key'] and type(root) is dict and
            root.get('key') == completed['root_key'] and completed['head_key'] != completed['root_key'] and
            completed['sequence'] == published['sequence']+1 and
            completed['preparation_ids'] == published['preparation_ids'] and
            completed['execution_provenance'] == published['execution_provenance'] and
            completed['store_limits'] == published['store_limits'] and
            completed['store_compression'] == published['store_compression'],
            'advanced endpoint does not extend the published migrated root of this producer')
    canonical_records(completed['array_records'])


def _continuation(receipt, completed, published):
    continuation, previous, advanced = (receipt.get(k) for k in ('continuation', 'previous_endpoint',
                                                                'advanced_endpoint'))
    require(type(continuation) is dict and set(continuation) == CONTINUATION_FIELDS and
            type(previous) is dict and type(advanced) is dict, 'complete exported continuation lineage required')
    for name in ('parent_head_key', 'parent_interval_id', 'interval_id', 'root_key', 'funding_id'):
        require(_identity(continuation[name]), 'complete continuation identities required')
    parent_number, number = continuation['parent_interval_number'], continuation['interval_number']
    require(type(parent_number) is int and type(number) is int and parent_number == published['sequence'] and
            number == parent_number+1 == completed['sequence'], 'exactly one interval after the migrated root required')
    funding = published['preparation_ids']['funding']
    require(continuation['parent_head_key'] == continuation['root_key'] == completed['root_key'] and
            previous.get('head') == completed['root_key'] and advanced.get('head') == completed['head_key'] and
            previous.get('intervals') == parent_number and advanced.get('intervals') == number and
            continuation['funding_id'] == previous.get('funding_id') == advanced.get('funding_id') == funding and
            continuation['interval_id'] != continuation['parent_interval_id'],
            'continuation must advance the migrated root once with unchanged funding')
    parent_time = _exact_pair(continuation['parent_time_seconds'], 'parent time')
    time_value = _exact_pair(continuation['time_seconds'], 'continued time')
    require(0 <= parent_time < time_value, 'continued time must exceed its exact parent time')
    return continuation


def validate_producer_receipt(receipt, *, profile, receipt_sha256, guard_receipt, guard_control,
                              checkpoint_sha_now, consumer_pid, mode):
    """Pure closed checks of a producer result; returns the validated expectation."""
    require(mode in MODES and type(profile) is RUN.RestartProfile, 'typed profile and reader mode required')
    require(_digest(receipt_sha256) and _digest(checkpoint_sha_now), 'exact receipt and checkpoint pins required')
    row = profile.record()
    output = Path(row['output_directory'])
    require(type(receipt) is dict and receipt.get('schema') == RUN.RESULT_SCHEMA and
            receipt.get('status') == PRODUCER_STATUS[mode] and receipt.get('errors') == [] and
            receipt.get('final_reserved_bytes') == 0 and receipt.get('production_acceptance') is False and
            receipt.get('profile_sha256') == profile.sha256 and
            receipt.get('stop_before_advance') is (mode == 'root-only'),
            'successful producer result of this profile and mode required')
    pid = receipt.get('pid')
    require(type(pid) is int and pid > 0 and type(consumer_pid) is int and consumer_pid > 0 and
            pid != consumer_pid, 'separate producer and reader processes required')
    # Owner decision 14 Oct 2026: an interval producer no longer cold-reopens its
    # successor in process and records exactly why; a root-only producer still
    # records its same-process root reopen. Either way THIS reader is mandatory.
    require(receipt.get('original_database_unchanged') is True and receipt.get('independent_process_reopen') is False and
            (receipt.get('same_process_cold_reopen') is True and 'same_process_cold_reopen_reason' not in receipt
             if mode == 'root-only' else receipt.get('same_process_cold_reopen') is False and
             receipt.get('same_process_cold_reopen_reason') == RUN.SAME_PROCESS_REOPEN_DROPPED),
            'producer finalisation is incomplete')
    storage = receipt.get('compact_storage')
    require((storage is not None) is RUN.compact_profile(row),
            'producer storage format differs from the selected profile')
    if storage is not None:
        _storage_record(storage)
        require(Path(storage['catalog']).is_relative_to(output) and
                receipt.get('checkpoint') == storage['catalog'] and
                receipt.get('checkpoint_sha256') == checkpoint_sha_now == storage['catalog_sha256'],
                'producer compact checkpoint path or bytes differ')
        canonical_record_identities(receipt.get('record_identities'), successor=mode == 'successor')
        before = validate_retained_accounting(receipt.get('compact_retained_before_close'), pid=pid)
        after = validate_retained_accounting(receipt.get('compact_retained_after_close'), pid=pid)
        require(after['retained_bytes'] == 0 and before['scope_id'] == after['scope_id'],
                'producer compact retained scope was not released')
    else:
        require(receipt.get('checkpoint') == str(output/'checkpoint.sqlite') and
                receipt.get('checkpoint_sha256') == checkpoint_sha_now, 'producer checkpoint path or bytes differ')
        require('record_identities' not in receipt, 'logical record identities require compact storage')
    published = receipt.get('published_root')
    _published(published, row=row, compact=storage is not None)
    require(published['producer_pid'] == pid, 'published root was not recorded by this producer')
    base = receipt.get('migrated_base')
    require(type(base) is dict and base.get('schema') == 'atlas.migrated-workflow-base.v1' and
            base.get('sequence') == published['sequence'], 'exact migrated base record required')
    workload = receipt.get('initial_workload')
    require(type(workload) is dict and set(workload) == {'state', 'duration_s', 'gate'} and
            type(workload['duration_s']) is float, 'authenticated initial workload record required')
    expected = dict(mode=mode, receipt_sha256=receipt_sha256, producer_pid=pid, checkpoint=receipt['checkpoint'],
        checkpoint_sha256=checkpoint_sha_now, published_root=published, migrated_base=base,
        initial_workload=workload, previous_endpoint=receipt.get('previous_endpoint'))
    if storage is not None:
        expected.update(compact_storage=storage, record_identities=receipt['record_identities'])
    if mode == 'successor':
        completed = receipt.get('completed_endpoint')
        _completed(completed, published, pid=pid)
        expected.update(completed_endpoint=completed, continuation=_continuation(receipt, completed, published),
                        advanced_endpoint=receipt['advanced_endpoint'])
    else:
        require(not {'completed_endpoint', 'continuation', 'advanced_endpoint'} & set(receipt) and
                receipt.get('previous_endpoint') == published['inspect'],
                'a root-only result cannot carry an advanced endpoint')
    supervisor = receipt.get('supervisor')
    require(type(supervisor) is dict, 'producer supervisor record required')
    validate_guard(guard_receipt, guard_control, pid=pid, supervisor_pid=supervisor.get('pid'))
    return expected


def validate_migrated_lineage(*, root, head, continuation, base_record, observed):
    """Migrated-root replacement for the old sequence-zero continuation validator."""
    import workflow_transfer as W
    require(type(root) is dict and type(head) is dict and type(base_record) is dict and
            type(continuation) is dict and set(continuation) == CONTINUATION_FIELDS and
            type(observed) is dict and set(observed) == OBSERVED_FIELDS, 'complete lineage operands required')
    sequence = base_record.get('sequence')
    try:
        require(type(sequence) is int and root.get('kind') == 'migrated-root' and
                root.get('sequence') == sequence and root.get('migration') == base_record and
                root.get('historical_payload_key') == base_record.get('historical_head_key'),
                'migrated root does not bind its admitted base')
        require(head.get('kind') == 'successor' and head.get('workflow_id') == root.get('workflow_id') and
                head.get('key') == W.workflow_key('successor', root['key']) and
                head.get('parent_key') == root['key'] and head.get('parent_digest') == W.digest(root) and
                head.get('sequence') == sequence+1, 'successor does not link exactly once to the migrated root')
        require(continuation['root_key'] == continuation['parent_head_key'] == root['key'] and
                continuation['parent_interval_number'] == sequence and
                continuation['interval_number'] == sequence+1, 'continuation lineage differs from the stored chain')
        parent_geometry, geometry = root['differential_geometry'], head['differential_geometry']
        require(parent_geometry['interval_id'] == continuation['parent_interval_id'] and
                geometry['interval_id'] == continuation['interval_id'] == observed['interval_id'] and
                continuation['interval_id'] != continuation['parent_interval_id'],
                'parent or current differential interval identity differs')
        parent_time = _exact_pair(continuation['parent_time_seconds'], 'parent time')
        current_time = _exact_pair(continuation['time_seconds'], 'current time')
        require(0 <= parent_time < current_time and
                _exact_pair(parent_geometry['end_time_s'], 'root end time') == parent_time and
                _exact_pair(geometry['start_time_s'], 'successor start time') == parent_time and
                _exact_pair(geometry['end_time_s'], 'successor end time') == current_time,
                'exact parent/current interval clocks differ')
        require(_clock(root['state']['fields']['time_s']) == parent_time and
                _clock(head['state']['fields']['time_s']) == current_time and
                _clock(observed['fields_time_s']) == current_time and
                _clock(observed['native_time_s']) == current_time and
                _clock(observed['exterior_time_s']) == current_time,
                'stored or reopened state clocks differ from the exact interval clocks')
        require(head['differential_partition']['partition_id'] == observed['partition_id'],
                'reopened differential partition differs from the successor header')
        require(_identity(root.get('funding_id')) and
                root['funding_id'] == head.get('funding_id') == continuation['funding_id'] == observed['funding_id'],
                'original funding identity changed across the continuation')
    except (KeyError, TypeError) as error:
        raise ReopenRefused('migrated lineage header missing: '+repr(error)) from error
    return dict(continuation, migrated_root_is_parent=True, exactly_one_added_interval=True,
                original_root_and_funding_unchanged=True, exact_endpoint_clocks_identical=True)


def observed_lineage(workflow):
    state = workflow.state
    return dict(interval_id=workflow.differential_interval.interval_id,
        partition_id=workflow.differential_partition.partition_id,
        fields_time_s=state.fields.descriptor()['time_s'], native_time_s=state.native_state.descriptor()['time_s'],
        exterior_time_s=workflow.exterior_state.time_s, funding_id=workflow._funding.funding_id)


def _bounded_json(path, limit=RUN.MAX_CONFIG):
    path = RUN.ordinary(path)
    require(path.stat().st_size <= limit, 'record exceeds bounded size: '+path.name)
    raw = path.read_bytes()
    require(len(raw) <= limit, 'record grew beyond its bound: '+path.name)
    return RUN._json(raw)


def _storage_record(storage):
    """Closed receipt shape; full catalog semantics remain the store's gate."""
    require(type(storage) is dict and set(storage) ==
            {'schema', 'format', 'catalog', 'catalog_sha256', 'files'} and
            storage['schema'] == STORAGE_SCHEMA and storage['format'] == 'interval-catalog-v1' and
            _digest(storage['catalog_sha256']), 'complete compact storage inventory required')
    RUN.canonical_absolute(storage['catalog'], 'compact interval catalog')
    files = storage['files']
    require(type(files) is list and 0 < len(files) <= MAX_SNAPSHOTS,
            'bounded nonempty compact interval inventory required')
    names = []
    for row in files:
        require(type(row) is dict and set(row) == {'filename', 'sha256', 'nbytes'} and
                type(row['filename']) is str and
                re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,199}\.sqlite', row['filename']) is not None and
                _digest(row['sha256']) and type(row['nbytes']) is int and row['nbytes'] > 0,
                'safe exact compact interval file identity required')
        names.append(row['filename'])
    require(len(names) == len(set(name.casefold() for name in names)),
            'compact interval filenames must be unique')
    return storage


def storage_inventory(catalog, *, budget=None, check=lambda: None):
    """Authenticate every catalog member without importing a native runtime.

    The frozen catalog hash and each closed member's physical hash are checked
    here. The retained store separately authenticates all logical references,
    typed payloads and ancestor closure when opening this complete copied set.
    """
    path = RUN.ordinary(catalog)
    allowance = budget.reserve(65536+10*CATALOG_BYTES, category='reopen-storage-inventory') if budget else nullcontext()
    with allowance:
        check()
        pin = RUN.file_hash(path, check)
        row = _bounded_json(path, CATALOG_BYTES)
        require(type(row) is dict and set(row) == {'schema', 'workflow_id', 'generation', 'entries'} and
                row['schema'] == 'atlas.interval-catalog.v1' and _digest(row['workflow_id']) and
                type(row['generation']) is int and type(row['entries']) is list and
                0 < len(row['entries']) == row['generation'] <= MAX_SNAPSHOTS,
                'bounded complete interval catalog required')
        files = []
        for index, entry in enumerate(row['entries']):
            require(type(entry) is dict and entry.get('interval') == index and
                    type(entry.get('interval')) is int and type(entry.get('filename')) is str and
                    re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,199}\.sqlite', entry['filename']) is not None and
                    _digest(entry.get('file_sha256')), 'safe ordered interval catalog members required')
            member = RUN.ordinary(path.parent/entry['filename'])
            require(not any(Path(str(member)+suffix).exists() for suffix in ('-wal', '-journal', '-shm')),
                    'compact interval is not closed')
            found = RUN.file_hash(member, check)
            require(found == entry['file_sha256'], 'compact interval file differs from its catalog')
            files.append(dict(filename=entry['filename'], sha256=found, nbytes=member.stat().st_size))
        require(RUN.file_hash(path, check) == pin, 'interval catalog changed during authentication')
        result = dict(schema=STORAGE_SCHEMA, format='interval-catalog-v1', catalog=str(path),
                      catalog_sha256=pin, files=files)
        return _storage_record(result)


def verify_storage(storage, *, budget=None, check=lambda: None):
    expected = _storage_record(storage)
    require(storage_inventory(expected['catalog'], budget=budget, check=check) == expected,
            'compact storage differs from the pinned complete inventory')
    return expected


def copy_storage(storage, destination, *, budget, check):
    """Copy the exact immutable interval set to a fresh owned reader directory."""
    expected = verify_storage(storage, budget=budget, check=check)
    destination = Path(destination).absolute()
    RUN.ordinary(destination.parent, directory=True)
    require(not destination.exists(), 'fresh separate compact checkpoint directory required')
    source = Path(expected['catalog'])
    destination.mkdir()
    for member in expected['files']:
        original, target = source.parent/member['filename'], destination/member['filename']
        RUN._copy_bound_file(original, member['sha256'], target, budget=budget, check=check)
        shutil.copymode(original, target)
    catalog = destination/COMPACT_CATALOG
    RUN._copy_bound_file(source, expected['catalog_sha256'], catalog, budget=budget, check=check)
    copied = storage_inventory(catalog, budget=budget, check=check)
    require(copied == dict(expected, catalog=str(catalog)), 'compact checkpoint copy differs')
    verify_storage(expected, budget=budget, check=check)
    return copied


def retained_accounting(scope):
    """Report the fixed child and distinct verified partition carrier children."""
    stats = scope.stats()
    return dict(limit_bytes=(256 << 20) + stats.partition_carrier_limit_bytes,
                fixed_limit_bytes=256 << 20,
                fixed_peak_bytes=scope.retained_budget.statistics()['peak_reserved_bytes'],
                peak_limit_bytes=(256 << 20) + stats.partition_carrier_peak_limit_bytes,
                partition_carrier_bytes=stats.partition_carrier_bytes,
                partition_carrier_pools=[dict(record_schema=identity.record_schema,
                    sha256=identity.sha256, canonical_bytes=identity.canonical_bytes,
                    support_count=row[0], limit_bytes=row[1], retained_bytes=row[2])
                    for identity, row in stats.partition_carrier_pools.items()],
                scope_id=scope.scope_id, process_epoch=scope.process_epoch,
                **{name: getattr(stats, name) for name in RETAINED_SCALARS},
                **{name: dict(getattr(stats, name)) for name in RETAINED_MAPPINGS})


def validate_retained_accounting(value, *, pid):
    fields = {'limit_bytes', 'scope_id', 'process_epoch', *RETAINED_SCALARS, *RETAINED_MAPPINGS}
    extended = {'fixed_limit_bytes', 'fixed_peak_bytes', 'peak_limit_bytes',
                'partition_carrier_bytes', 'partition_carrier_pools'}
    require(type(value) is dict and set(value) in (fields, fields | extended) and
            _identity(value['scope_id']) and value['process_epoch'] == 'prepared-restart-'+str(pid),
            'complete shared retained scope accounting required')
    peak_limit = value['limit_bytes']
    if set(value) == fields:
        require(value['limit_bytes'] == 256 << 20, 'legacy fixed retained limit differs')
    else:
        require(all(type(value[name]) is int and value[name] >= 0 for name in
                    ('limit_bytes', 'fixed_limit_bytes', 'fixed_peak_bytes', 'peak_limit_bytes',
                     'partition_carrier_bytes')) and value['fixed_limit_bytes'] == 256 << 20 and
                value['fixed_peak_bytes'] <= value['fixed_limit_bytes'],
                'fixed retained limit or peak differs')
        pools = value['partition_carrier_pools']
        require(type(pools) is list and len(pools) <= 4096, 'bounded partition carrier pools required')
        identities = set()
        for pool in pools:
            require(type(pool) is dict and set(pool) == {'record_schema', 'sha256', 'canonical_bytes',
                    'support_count', 'limit_bytes', 'retained_bytes'} and
                    _identity(pool['record_schema']) and type(pool['sha256']) is str and
                    len(pool['sha256']) == 64 and all(c in '0123456789abcdef' for c in pool['sha256']) and
                    all(type(pool[name]) is int and pool[name] >= 0 for name in
                        ('canonical_bytes', 'support_count', 'limit_bytes', 'retained_bytes')) and
                    pool['limit_bytes'] == pool['support_count'] * 3 * 2112 and
                    pool['retained_bytes'] <= pool['limit_bytes'],
                    'partition carrier identity, count or capacity differs')
            identity = (pool['record_schema'], pool['sha256'], pool['canonical_bytes'])
            require(identity not in identities, 'duplicate partition carrier pool')
            identities.add(identity)
        require(value['limit_bytes'] == (256 << 20) + sum(pool['limit_bytes'] for pool in pools) and
                value['partition_carrier_bytes'] == sum(pool['retained_bytes'] for pool in pools) and
                type(value['retained_bytes']) is int and
                0 <= value['retained_bytes'] - value['partition_carrier_bytes'] <= 256 << 20 and
                value['peak_limit_bytes'] >= value['limit_bytes'],
                'fixed and partition retained accounting does not reconcile')
        peak_limit = value['peak_limit_bytes']
    require(all(type(value[name]) is int and value[name] >= 0 for name in RETAINED_SCALARS) and
            value['retained_bytes'] <= value['limit_bytes'] and
            value['retained_bytes'] <= value['peak_retained_bytes'] <= peak_limit and
            sum(value[name] for name in ('pinned_bytes', 'pending_bytes', 'evictable_bytes',
                                         'non_cache_owned_bytes')) == value['retained_bytes'],
            'retained held/cache accounting does not reconcile')
    for name in RETAINED_MAPPINGS:
        require(type(value[name]) is dict and len(value[name]) <= 4096 and
                all(_identity(key) and type(count) is int and count >= 0 for key, count in value[name].items()),
                'bounded retained held/cache counter maps required')
    require(sum(value['purpose_bytes'].values()) == value['retained_bytes'],
            'retained purpose accounting does not reconcile')
    return value


# S8 (observation only): a reader scope from RUN.new_retained_scope carries the named
# live-producer child, so PRODUCER_PURPOSES charges book there and not against the
# 256 MiB retained aggregate. The child is reported beside retained_accounting, in a
# sibling record field, so the existing retained schema and its validators are unchanged.
PRODUCER_SCALARS = ('producer_limit_bytes', 'producer_bytes', 'producer_peak_bytes', 'producer_refusals')
PRODUCER_MAPPINGS = ('producer_purpose_bytes', 'producer_purpose_peak_bytes')


def producer_accounting(scope):
    """The scope's live-producer child (all zero for a scope without one)."""
    stats = scope.stats()
    return dict(scope_id=scope.scope_id, **{name: getattr(stats, name) for name in PRODUCER_SCALARS},
                **{name: dict(getattr(stats, name)) for name in PRODUCER_MAPPINGS})


def validate_producer_accounting(value, *, scope_id):
    fields = {'scope_id', *PRODUCER_SCALARS, *PRODUCER_MAPPINGS}
    require(type(value) is dict and set(value) == fields and value['scope_id'] == scope_id and
            all(type(value[name]) is int and value[name] >= 0 for name in PRODUCER_SCALARS) and
            value['producer_bytes'] <= value['producer_peak_bytes'] <= value['producer_limit_bytes'],
            'live-producer child accounting does not reconcile')
    for name in PRODUCER_MAPPINGS:
        require(type(value[name]) is dict and len(value[name]) <= 4096 and
                all(type(key) is str and 0 < len(key) <= 256 and type(count) is int and count >= 0
                    for key, count in value[name].items()),
                'bounded live-producer counter maps required')
    require(sum(value['producer_purpose_bytes'].values()) == value['producer_bytes'],
            'live-producer purpose accounting does not reconcile')
    return value


def validate_retained_producer(reopen, retained):
    """Optional S8 field: absent in older receipts; when present it must be complete."""
    if 'retained_producer' not in reopen:
        return None
    producer = reopen['retained_producer']
    require(type(producer) is dict and set(producer) == {'before_close', 'after_close'},
            'live-producer child accounting is incomplete')
    for value in producer.values():
        validate_producer_accounting(value, scope_id=retained['before_close']['scope_id'])
    return producer


def producer_inputs(profile, *, sources, receipt_sha256, mode, consumer_pid):
    """Store-free producer preflight: pinned receipt, guard records, closed checkpoint."""
    require(type(sources) is RUN.RestartSources and sources.profile is profile, 'selected profile sources required')
    output = Path(profile.record()['output_directory'])
    receipt = RUN.pinned_json(output/'run.json', receipt_sha256, MAX_RECEIPT)
    guard = _bounded_json(output/'run.guard.json')
    control = _bounded_json(output/'run.guard-control.json')
    require(not (output/'run.guard-abort.json').exists() and not (output/'run.cancel').exists(),
            'producer was aborted or cancelled')
    if 'compact_storage' in receipt:
        storage = verify_storage(receipt['compact_storage'])
        checkpoint = RUN.ordinary(storage['catalog'])
        require(checkpoint.is_relative_to(output), 'compact producer catalog is outside its output')
    else:
        checkpoint = RUN.ordinary(output/'checkpoint.sqlite')
    require(not any(Path(str(checkpoint)+s).exists() for s in ('-wal', '-journal', '-shm')),
            'producer checkpoint is not closed')
    expected = validate_producer_receipt(receipt, profile=profile, receipt_sha256=receipt_sha256,
        guard_receipt=guard, guard_control=control, checkpoint_sha_now=RUN.file_hash(checkpoint),
        consumer_pid=consumer_pid, mode=mode)
    require(receipt.get('source_proof') == sources.verify(), 'producer source proof differs from the selected sources')
    return expected


def reader_output(profile, sources, value, *, exists):
    """A new canonical directory inside the workspace and outside the producer."""
    path = RUN.canonical_absolute(value, 'reader output directory')
    producer = Path(profile.record()['output_directory'])
    RUN.ordinary(path.parent, directory=True)
    require(path.is_relative_to(sources.workspace) and not path.is_relative_to(producer) and
            not producer.is_relative_to(path), 'reader output must be inside the workspace and outside the producer')
    if exists:
        require(RUN.ordinary(path, directory=True) == path, 'existing reader output directory required')
    else:
        require(not path.exists(), 'exclusive new reader output directory required')
    return path


def _own_pin(sources):
    own = Path(__file__).resolve()
    require(own.is_relative_to(sources.workspace) and
            sources.files().get(own.relative_to(sources.workspace).as_posix()) == RUN.file_hash(own),
            'independent reader itself must be pinned')
    return own


def gate_key(profile, python, *, producer_receipt_sha256, mode, store_route):
    sources = RUN.RestartSources(profile)
    sources.verify()
    _own_pin(sources)
    return RG.command_key(profile, python, entry=__file__, step='reader',
                          producer_receipt_sha256=producer_receipt_sha256, mode=mode, store_route=store_route)


def command(profile, python, *, producer_receipt_sha256, output_directory, mode='successor',
            store_route='readonly', start_gate=None):
    """Store-free preflight and the guarded argv; never launches."""
    require(mode in MODES and store_route in STORE_ROUTES, 'explicit reader mode and store route required')
    sources = RUN.RestartSources(profile)
    producer = producer_inputs(profile, sources=sources, receipt_sha256=producer_receipt_sha256,
                               mode=mode, consumer_pid=os.getpid())
    output = reader_output(profile, sources, output_directory, exists=False)
    staging = profile.record()['store_limits'].get('max_staging_bytes')
    require(type(staging) is int and staging > 0, 'explicit store staging bound required')
    size = Path(producer['checkpoint']).stat().st_size
    if 'compact_storage' in producer:
        require(store_route == 'readonly', 'compact reader requires the readonly interval catalog route')
        size += sum(member['nbytes'] for member in producer['compact_storage']['files'])
    require(shutil.disk_usage(output.parent).free >= size + staging,
            'insufficient disk headroom for the reader checkpoint copy and staging')
    own = _own_pin(sources)
    guard = sources.path(profile.record()['modules']['private_heat_continuation_guard_r3'])
    python = str(RUN.ordinary(python))
    return [python, '-B', str(guard), '--launch', '--output', str(output/'reopen.json'), '--',
        python, '-B', str(own), '--workload', '--profile', str(profile.path), '--profile-sha256', profile.sha256,
        '--producer-receipt-sha256', producer_receipt_sha256, '--output-directory', str(output),
        '--mode', mode, '--store-route', store_route,
        *([SG.ARGUMENT, SG.encode(start_gate)] if start_gate is not None else [])]


@contextmanager
def _reader_store(H, ArrayStore, path, *, route, pin, limits, compression, budget, check,
                  compact=None, scope=None):
    if compact is not None:
        require(route == 'readonly' and scope is not None and scope.run_budget is budget,
                'compact reader requires readonly storage and the one retained scope')
        require(RUN.file_hash(path, check) == pin, 'compact reader catalog differs before open')
        store = compact.CompactRestartStore.open_catalog(path, scope=scope)
        if store.store_set.catalog_digest != pin:
            store.close()
            raise ReopenRefused('compact reader catalog changed while opening')
    elif route == 'readonly':
        opener = getattr(H, 'open_successor_readonly', None)
        require(callable(opener), 'reviewed readonly successor adapter is missing; '
                'select --store-route copy-token explicitly')
        # Hashes the closed copy before SQLite sees it; mode=ro plus query_only.
        store = opener(path, expected_sha256=pin, limits=limits, compression=compression, budget=budget,
                       check=check)
    else:
        # Explicit fallback: ordinary store on this reader's own copy. No-write
        # proof is the change token, snapshot count and final file hash.
        store = ArrayStore(path, limits, compression, budget=budget)
    with store:
        yield store


def _history(store, base, admission, producer, *, W, budget, mode):
    """Original snapshots stay byte-identical; the original chain did not advance."""
    W._check_preserved_chain(store, base)
    scratch = W._decode_allocation(budget, admission._record)
    manifests = admission.record()['snapshot_manifests']
    historical = getattr(base, 'original_store', None) or store
    with historical._read_scope():
        for key, manifest in manifests.items():
            require(historical._manifest(key) == manifest, 'preserved original snapshot manifest changed: '+key)
    with store._read_scope():
        present = []
        keys = store.snapshot_keys() if hasattr(store, 'snapshot_keys') else (
            key for (key,) in store._db.execute('SELECT id FROM snapshots ORDER BY id'))
        for key in keys:
            present.append(key)
            require(len(present) <= MAX_SNAPSHOTS, 'reader snapshot inventory exceeds its bound')
    record = base.record()
    require(historical.metadata(W.workflow_key('successor', record['historical_head_key'])) is None,
            'original chain advanced beyond the admitted migration point')
    added = sorted(set(present)-set(manifests))
    expected = {producer['published_root']['root_key']}
    if mode == 'successor':
        expected.add(producer['completed_endpoint']['head_key'])
    require((historical is not store or set(manifests) <= set(present)) and expected <= set(added),
            'reader store lacks the original history, migrated root or successor')
    _ = scratch
    return dict(original_snapshots=len(manifests), added_snapshots=added,
                original_manifests_identical=True, original_chain_not_advanced=True)


def _root_identity(workflow, store, base, producer, *, W, budget):
    published = producer['published_root']
    scratch = W._decode_allocation(budget, workflow._root)
    root = json.loads(workflow._root)
    record = base.record()
    require(workflow.workflow_id == published['workflow_id'] and root['key'] == published['root_key'] and
            W.digest(store.metadata(root['key'])) == W.digest(root) == published['root_metadata_sha256'] and
            root.get('kind') == 'migrated-root' and root.get('migration') == record and
            root.get('historical_payload_key') == record['historical_head_key'] and
            root.get('sequence') == record['sequence'] == published['sequence'],
            'independently reopened migrated root differs from the producer')
    funding = workflow._funding
    require(workflow._exterior_owner.owner_id == published['preparation_ids']['spatial_owner'] and
            funding is base._spatial.funding and funding.funding_id == root['funding_id'] ==
            published['preparation_ids']['funding'] and funding.descriptor() == root['funding'],
            'migrated root owner or original funding differs (no second debit allowed)')
    _ = scratch
    return root


def _successor(workflow, store, base, producer, root, *, D, W):
    completed, continuation = producer['completed_endpoint'], producer['continuation']
    head = dict(workflow._head)
    require(head.get('key') == completed['head_key'] and head.get('kind') == 'successor' and
            head.get('parent_key') == root['key'] and head.get('parent_digest') == W.digest(store.metadata(root['key'])) and
            head.get('sequence') == base.record()['sequence']+1 and
            store.metadata(root['key']) == completed['root_metadata'] and
            workflow.inspect() == producer['advanced_endpoint'],
            'independently reopened successor identity differs')
    state, exterior = workflow.state, workflow.exterior_state
    found = dict(collar_result_id=state.result_id, native_result_id=state.native_state.result_id,
        exterior_state_id=exterior.state_id, source_audit_id=workflow.source_audit.result_id,
        joined_heat_id=head['exterior_advance']['joined_heat_id'])
    require(all(found[name] == completed[name] for name in found) and
            workflow._exterior_owner.owner_id == completed['preparation_ids']['spatial_owner'],
            'independently reopened state identities differ')
    groups = endpoint_array_records(D, workflow)
    require(canonical_records(groups) == canonical_records(completed['array_records']),
            'independently reopened endpoint arrays differ')
    del groups
    lineage = validate_migrated_lineage(root=root, head=head, continuation=continuation,
                                        base_record=base.record(), observed=observed_lineage(workflow))
    return dict(endpoint=found, continuation=lineage)


def reopen_prepared_restart(profile, *, sources, guard, record, save, producer, mode, store_route='readonly',
                            start_gate=None):
    """Fresh-process reader core; call under sources.selected() and the live guard."""
    require(type(profile) is RUN.RestartProfile and type(sources) is RUN.RestartSources and
            sources.profile is profile and sources.selected_now, 'actual selected pinned sources required')
    require(mode in MODES and store_route in STORE_ROUTES and type(producer) is dict and
            producer.get('mode') == mode, 'validated producer expectation for this mode required')
    import psutil
    available = psutil.virtual_memory().available
    admitted = SG.child_admit(start_gate, available)
    row = profile.record()
    H = sources.module('historical_admission')
    M = sources.module('materialise_endpoint')
    W = sources.module('workflow_transfer')
    P = sources.module('plan_preparation')
    IW = sources.module('initial_workload')
    from atlas_tectonics.resources import WorkBudget
    from atlas_tectonics.reuse import ExecutionContext, require_strict_execution
    from atlas_tectonics.storage import ArrayStore, StoreLimits, Compression
    from atlas_tectonics.integration_regional_workflow import CollarWorkflow
    bound = {name: sources.module(name) for name in RUN.REQUIRED_MODULES}
    D = bound['probe_heat_original_connected_r9']
    control = bound['i04_differential_modes'].ACTUATED_CONTROL
    import test_i04_spatial_workflow as FLOW
    _own_pin(sources)
    require(hasattr(CollarWorkflow, 'open_migrated') and 'working_store' in inspect.signature(M.materialise).parameters,
            'composed migrated-root reader and store-aware materialisation required')
    require_strict_execution()
    RUN._check_historical_root(sources, H, row)
    output = guard.output.parent
    reader_output(profile, sources, str(output), exists=True)
    guard.budget = budget = WorkBudget(RUN.LOGICAL_BYTES, max_predicate_work_units=1 << 44)
    RUN._guard_boundary(sources, guard, budget)
    check = lambda: guard.check(force=True)
    record.update(guard_limits=SG.guard_limits(admitted), start_gate=admitted,
        memory_at_start=dict(available_bytes=available), source_proof=sources.verify(),
        launch_environment={name: os.environ.get(name) for name in sorted(RUN.LAUNCH_ENV)},
        production_acceptance=False)
    limits, compression = StoreLimits(**row['store_limits']), Compression(**row['compression'])
    compact = sources.module('compact_restart_store') if 'compact_storage' in producer else None
    scope = None
    source = RUN.ordinary(producer['checkpoint'])
    copy = output/COMPACT_DIRECTORY/COMPACT_CATALOG if compact is not None else output/CHECKPOINT
    copy_bytes = source.stat().st_size + (sum(member['nbytes'] for member in
        producer['compact_storage']['files']) if compact is not None else 0)
    require(shutil.disk_usage(output).free >= copy_bytes + limits.max_staging_bytes,
            'insufficient disk headroom for the reader checkpoint copy and staging')
    guard.phase('copy-producer-checkpoint-to-reader-output')
    if compact is not None:
        record['compact_storage'] = copy_storage(producer['compact_storage'], output/COMPACT_DIRECTORY,
                                                 budget=budget, check=check)
    else:
        RUN._copy_bound_file(source, producer['checkpoint_sha256'], copy, budget=budget, check=check)
    preparation = P.load_preparation(sources.path(row['preparation']['path']))
    compatibility = RUN._compatibility(sources, row)
    published = producer['published_root']
    ids = published['preparation_ids']
    checks = dict.fromkeys(INDEPENDENT_CHECKS[mode] | (COMPACT_CHECKS if compact is not None else set()), False)
    original_path = original_pin = None
    guard.phase('prepare-current-plans-without-funding')
    try:
        scope = RUN.new_retained_scope(budget) if compact is not None else None
        with ExecutionContext('scipy') as execution, preparation(budget=budget, pressure_space='q1-p0',
                material_quadrature=True) as case:
            collar = case['collar']
            require(execution.provenance == published['execution_provenance'] and
                    case['owner'].owner_id == ids['owner'] and collar._native.plan_id == ids['native'] and
                    collar.plan_id == ids['collar'] and collar._map.volume_map_id == ids['map'],
                    'independently rebuilt runtime, plans or owner differ from the producer')
            checks['source_bound_preparation'] = True
            guard.phase('re-authenticate-historical-endpoint-readonly')
            with H.open_original_readonly(limits=limits, compression=compression, budget=budget) as original:
                admission = H.admit_historical_endpoint(original, execution=execution, budget=budget, guard=guard)
                require(type(admission) is W.HistoricalEndpointAdmission, 'historical issuer returned no admission')
                scratch = W._decode_allocation(budget, admission._binding)
                binding = admission.binding()
                original_path, original_pin = RUN.ordinary(binding['original_database_path']), binding['database_sha256']
                del scratch, binding
                checks['original_reauthenticated'] = True
                with _reader_store(H, ArrayStore, copy, route=store_route, pin=producer['checkpoint_sha256'],
                        limits=limits, compression=compression, budget=budget, check=check,
                        compact=compact, scope=scope) as store:
                    token, snapshots = store.change_token(), store.statistics()['snapshots']
                    guard.phase('reproduce-migrated-base-from-original')
                    # Forced check unwrapped; conversion/publication phases reach the guard.
                    with M.materialise(original_store=original, admission=admission, native=case['native'],
                            collar=collar, execution=execution, compatibility=compatibility,
                            budget=budget, check=check, working_store=store, phase=guard.phase,
                            **({'scope': scope} if compact is not None else {})) as base:
                        require(type(base) is W.MigratedWorkflowBase and base.record() == producer['migrated_base'],
                                'independently reproduced migrated base differs from the producer')
                        require(store.change_token() == token,
                                'base reproduction wrote to the reader store instead of finding compact tables')
                        RUN._check_runtime_binding(base, row, execution, budget)
                        checks['migrated_base_reproduced'] = True
                        state = IW.initial_workload_state(original_store=original, admission=admission,
                            collar=collar, budget=budget, check=check)
                        duration = IW.require_initial_duration(control, dict(case, funding=base._spatial.funding,
                            state=state), expected=IW.authenticated_duration(admission, budget))
                        require(state.record() == producer['initial_workload']['state'] and
                                duration == producer['initial_workload']['duration_s'],
                                'independently read initial workload differs from the producer')
                        del state
                        checks['initial_workload_reproduced'] = True
                        operations, accepted = FLOW.operations(collar), case['native'].statistics()['accepted_intervals']
                        guard.phase('independent-open-migrated-workflow')
                        with CollarWorkflow.open_migrated(store, published['workflow_id'], base,
                                budget=budget) as workflow:
                            root = _root_identity(workflow, store, base, producer, W=W, budget=budget)
                            checks.update(migrated_root_identity=True, funding_preserved=True)
                            if mode == 'successor':
                                evidence = _successor(workflow, store, base, producer, root, D=D, W=W)
                                checks.update(successor_identity=True, state_identities=True,
                                    all_six_field_groups_identical=True, migrated_lineage=True)
                            else:
                                inspected = workflow.inspect()
                                require(inspected == published['inspect'] and inspected['head'] == root['key'] and
                                        inspected['intervals'] == base.record()['sequence'],
                                        'root-only reopen differs from the published root')
                                evidence = dict(root=inspected)
                            if compact is not None:
                                identities = endpoint_record_identities(workflow)
                                require(identities == producer['record_identities'],
                                        'independently streamed compact endpoint records differ')
                                checks['compact_record_identities_identical'] = True
                                record['record_identities'] = identities
                            history = _history(store, base, admission, producer, W=W, budget=budget, mode=mode)
                            checks['history_preserved'] = True
                            del root
                        require(store.change_token() == token and store.statistics()['snapshots'] == snapshots,
                                'independent reopen wrote to the reader store')
                        checks['store_unchanged'] = True
                        require(FLOW.operations(collar) == operations and
                                case['native'].statistics()['accepted_intervals'] == accepted,
                                'independent reopen replayed a native operator or accepted an interval')
                        checks['native_operations_unchanged'] = True
                        record.update(evidence=evidence, history=history, store_route=store_route,
                                      independent_checks=checks)
                        if compact is not None:
                            record['compact_store_statistics'] = store.statistics()
                        save()
                        del base, workflow
                del admission
            execution.verify_boundary()
        sources.check_imported()
        sources.verify()
        require(RUN.file_hash(copy, check) == producer['checkpoint_sha256'] == RUN.file_hash(source, check),
                'reader copy or producer checkpoint changed')
        if compact is not None:
            verify_storage(producer['compact_storage'], budget=budget, check=check)
            verify_storage(record['compact_storage'], budget=budget, check=check)
            checks['compact_storage_authenticated'] = True
        checks['reader_copy_and_producer_checkpoint_unchanged'] = True
        require(RUN.file_hash(original_path, check) == original_pin, 'original checkpoint changed')
        checks['original_database_unchanged'] = True
        record.update(independent_checks=checks, checkpoint=str(copy), original_database_unchanged=True)
        return budget
    finally:
        if original_path is not None:
            active_error = sys.exception()
            try:
                require(RUN.file_hash(original_path, check) == original_pin,
                        'original checkpoint changed during failed reopen')
            except BaseException as verification_error:
                if active_error is None:
                    raise
                active_error.add_note('Original binding finalisation also failed: '+repr(verification_error))
        if scope is not None:
            active_error = sys.exception()
            record['retained_scope'] = dict(before_close=retained_accounting(scope))
            record['retained_producer'] = dict(before_close=producer_accounting(scope))
            try:
                scope.close()
                record['retained_scope']['after_close'] = retained_accounting(scope)
                record['retained_producer']['after_close'] = producer_accounting(scope)
                require(record['retained_scope']['after_close']['retained_bytes'] == 0,
                        'compact reader retained owners after scope closure')
                checks['retained_scope_released'] = True
            except BaseException as release_error:
                if active_error is None:
                    raise
                active_error.add_note('Retained scope finalisation also failed: '+repr(release_error))


def _workload(profile, *, producer_receipt_sha256, output_directory, mode, store_route, start_gate=None):
    require(sys.dont_write_bytecode, 'run with -B to preserve frozen sources')
    import psutil
    SG.child_admit(start_gate, psutil.virtual_memory().available)
    sources = RUN.RestartSources(profile)
    output = reader_output(profile, sources, output_directory, exists=True)/'reopen.json'
    record = dict(schema=READER_SCHEMA, status='STARTED', pid=os.getpid(), profile_sha256=profile.sha256,
        producer_receipt_sha256=producer_receipt_sha256, mode=mode, store_route=store_route, errors=[],
        production_acceptance=False, independent_process_reopen=True)
    guard = budget = None
    # The supervisor has already claimed sidecars. Receipt creation is exclusive.
    with output.open('x', encoding='utf8') as stream:
        json.dump(record, stream)
    with sources.selected():
        G = sources.module('private_heat_continuation_guard_r3')
        save = lambda: G._write(output, record)
        try:
            guard = G.ContinuationGuard(output, record, save)
            producer = producer_inputs(profile, sources=sources, receipt_sha256=producer_receipt_sha256,
                                       mode=mode, consumer_pid=os.getpid())
            budget = reopen_prepared_restart(profile, sources=sources, guard=guard, record=record, save=save,
                                             producer=producer, mode=mode, store_route=store_route, start_gate=start_gate)
            del producer
            record['status'] = 'VERIFYING_FINALISATION'
        except BaseException as error:
            record['status'] = 'FAILED'
            record['errors'].append(dict(type=type(error).__name__, message=str(error)))
            if guard is not None and guard.budget is not None:
                record['logical_budget_at_failure'] = guard.budget.statistics()
            save()
        finally:
            gc.collect()
            budget = budget if budget is not None else getattr(guard, 'budget', None)
            if budget is not None:
                record['final_reserved_bytes'] = budget.reserved_bytes
                statistics = budget.statistics()
                record['logical_budget_final'] = dict(peak_reserved_bytes=statistics['peak_reserved_bytes'],
                    category_peaks=statistics['category_peaks'])
                if budget.reserved_bytes:
                    record['errors'].append(dict(type='RetainedReservations', message=str(budget.reserved_bytes)))
            times = os.times()
            record['parent_cpu_seconds'] = dict(user=times.user, system=times.system)
            try:
                import psutil
                children = psutil.Process().children(recursive=True)
                record['remaining_children'] = [child.pid for child in children]
                require(not children, 'reader worker processes remain after the reopen')
                sources.check_imported()
                sources.verify()
                if guard is not None:
                    guard.check(force=True)
                    guard.close()
            except BaseException as error:
                record['errors'].append(dict(type=type(error).__name__, message=str(error)))
            record['status'] = 'FAILED' if record['errors'] else WORKLOAD_STATUS[mode]
            save()
    return 0 if not record['errors'] else 1


def validate_reopen_receipt(reopen, *, guard_receipt, guard_control, profile, producer, mode, store_route,
                            output):
    """Pure closed checks of the guarded reader result after its guardian exited."""
    compact = 'compact_storage' in producer
    checkpoint = output/COMPACT_DIRECTORY/COMPACT_CATALOG if compact else output/CHECKPOINT
    require(type(reopen) is dict and reopen.get('schema') == READER_SCHEMA and
            reopen.get('status') == WORKLOAD_STATUS[mode] and reopen.get('errors') == [] and
            reopen.get('final_reserved_bytes') == 0 and reopen.get('production_acceptance') is False and
            reopen.get('independent_process_reopen') is True and reopen.get('mode') == mode and
            reopen.get('store_route') == store_route and reopen.get('profile_sha256') == profile.sha256 and
            reopen.get('producer_receipt_sha256') == producer['receipt_sha256'] and
            reopen.get('remaining_children') == [] and reopen.get('original_database_unchanged') is True and
            reopen.get('checkpoint') == str(checkpoint),
            'successful independent reader result of this producer, profile and mode required')
    pid = reopen.get('pid')
    require(type(pid) is int and pid > 0 and pid != producer['producer_pid'],
            'reader must run in a process separate from the producer')
    checks = reopen.get('independent_checks')
    expected_checks = INDEPENDENT_CHECKS[mode] | (COMPACT_CHECKS if compact else set())
    require(type(checks) is dict and set(checks) == expected_checks and
            all(value is True for value in checks.values()), 'every independent reopen check must have passed')
    if compact:
        require(store_route == 'readonly' and reopen.get('compact_storage') ==
                dict(producer['compact_storage'], catalog=str(checkpoint)) and
                reopen.get('record_identities') == producer['record_identities'],
                'independent compact inventory or logical records differ')
        retained = reopen.get('retained_scope')
        require(type(retained) is dict and set(retained) == {'before_close', 'after_close'} and
                all(type(retained[name]) is dict and retained[name].get('limit_bytes') == 256 << 20
                    for name in retained) and retained['after_close'].get('retained_bytes') == 0 and
                retained['before_close'].get('scope_id') == retained['after_close'].get('scope_id') and
                _identity(retained['after_close'].get('scope_id')) and
                all(type(retained[name].get('peak_retained_bytes')) is int and
                    0 <= retained[name]['peak_retained_bytes'] <= 256 << 20 for name in retained),
                'independent compact retained scope release evidence is incomplete')
        for value in retained.values():
            validate_retained_accounting(value, pid=pid)
        validate_retained_producer(reopen, retained)
    supervisor = reopen.get('supervisor')
    require(type(supervisor) is dict, 'reader supervisor record required')
    validate_guard(guard_receipt, guard_control, pid=pid, supervisor_pid=supervisor.get('pid'))


def finalise(profile, *, producer_receipt_sha256, output_directory, mode, store_route, reopen_receipt_sha256):
    """Store-free acceptance of a completed guarded reader; exclusive final record."""
    sources = RUN.RestartSources(profile)
    output = reader_output(profile, sources, output_directory, exists=True)
    final = output/'reopen-final.json'
    require(not final.exists(), 'reader final record already exists')
    errors, gate_evidence = [], None
    try:
        proof = sources.verify()
        producer = producer_inputs(profile, sources=sources, receipt_sha256=producer_receipt_sha256,
                                   mode=mode, consumer_pid=os.getpid())
        snapshots = {name: RG.read_snapshot(path) for name, path in {
            'profile': profile.path, 'run': output/'reopen.json', 'guard': output/'reopen.guard.json',
            'control': output/'reopen.guard-control.json'}.items()}
        require(snapshots['run'][1]['sha256'] == reopen_receipt_sha256 and
                snapshots['profile'][1]['sha256'] == profile.sha256, 'reader/profile evidence pin changed')
        reopen = snapshots['run'][0]
        require(not (output/'reopen.guard-abort.json').exists() and not (output/'reopen.cancel').exists(),
                'reader was aborted or cancelled')
        validate_reopen_receipt(reopen, guard_receipt=snapshots['guard'][0],
            guard_control=snapshots['control'][0], profile=profile, producer=producer,
            mode=mode, store_route=store_route, output=output)
        require(reopen.get('source_proof') == proof, 'reader source proof differs from the selected sources')
        if 'compact_storage' in producer:
            verify_storage(reopen['compact_storage'])
        else:
            copy = RUN.ordinary(output/CHECKPOINT)
            require(not any(Path(str(copy)+s).exists() for s in ('-wal', '-journal', '-shm')) and
                    RUN.file_hash(copy) == producer['checkpoint_sha256'], 'reader checkpoint copy changed or is open')
        key = gate_key(profile, sys.executable, producer_receipt_sha256=producer_receipt_sha256,
                       mode=mode, store_route=store_route)
        gate_evidence = RG.evidence(key, snapshots)
    except Exception as error:
        errors.append(dict(type=type(error).__name__, message=str(error)))
    result = dict(schema=FINAL_SCHEMA, status='FAILED' if errors else FINAL_STATUS[mode], mode=mode,
        store_route=store_route, profile_sha256=profile.sha256, producer_receipt_sha256=producer_receipt_sha256,
        reopen_receipt_sha256=reopen_receipt_sha256, errors=errors, production_acceptance=False,
        independent_process_reopen=not errors)
    if not errors:
        result['gate_evidence'] = gate_evidence
    with final.open('x', encoding='utf8') as stream:
        json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write('\n')
    print(json.dumps(dict(status=result['status'], errors=errors)), flush=True)
    return 0 if not errors else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', type=Path, required=True)
    parser.add_argument('--profile-sha256', required=True)
    parser.add_argument('--producer-receipt-sha256', required=True)
    parser.add_argument('--output-directory', required=True)
    parser.add_argument('--mode', choices=MODES, default='successor')
    parser.add_argument('--store-route', choices=STORE_ROUTES, default='readonly')
    parser.add_argument('--reopen-receipt-sha256')
    action = parser.add_mutually_exclusive_group()
    action.add_argument('--launch', action='store_true')
    action.add_argument('--workload', action='store_true')
    action.add_argument('--finalise', action='store_true')
    parser.add_argument(SG.ARGUMENT)
    RG.add_arguments(parser)
    args = parser.parse_args(argv)
    require(args.start_gate is None or args.workload, '--start-gate is reserved for --workload')
    require(args.launch or not (args.peak_records or args.booking_bytes is not None or args.booking_basis is not None),
            'measurement/booking arguments belong to --launch')
    require((args.reopen_receipt_sha256 is not None) == args.finalise,
            '--reopen-receipt-sha256 is required with, and only with, --finalise')
    profile = RUN.RestartProfile.read(args.profile, args.profile_sha256)
    options = dict(producer_receipt_sha256=args.producer_receipt_sha256, output_directory=args.output_directory,
                   mode=args.mode, store_route=args.store_route)
    if args.workload:
        return _workload(profile, start_gate=args.start_gate, **options)
    if args.finalise:
        return finalise(profile, reopen_receipt_sha256=args.reopen_receipt_sha256, **options)
    gate = None
    if args.launch:
        gate = RG.decide(gate_key(profile, sys.executable, producer_receipt_sha256=args.producer_receipt_sha256,
                                 mode=args.mode, store_route=args.store_route), records=args.peak_records,
                         booking_bytes=args.booking_bytes, booking_basis=args.booking_basis)
    argv = command(profile, sys.executable, start_gate=gate, **options)
    print(json.dumps(dict(status='SOURCE_BOUND_COMMAND_ONLY_NOT_ADMISSION', command=argv,
        production_acceptance=False)), flush=True)
    if not args.launch:
        return 0
    import psutil
    SG.admit(gate, psutil.virtual_memory().available)
    output = Path(args.output_directory)
    output.mkdir(exist_ok=False)
    return subprocess.call(argv, env=RUN.launch_environment(), cwd=output)


if __name__ == '__main__':
    raise SystemExit(main())
