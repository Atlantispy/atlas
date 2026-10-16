"""Independent fresh-process reader of a route (1) sealed interval (Step 9(a), option B).

The runner (run_fresh_interval.py) sealed its interval file without promoting it,
after recording durably the head and identities it asserts (the runner record);
the sealed record followed the seal. In a NEW guarded process with the same
pinned sources and limits (10 GiB start gate, 12 GiB RSS / 1 GiB free guard,
16 GiB ledger) this reader:

- validates the producer's run.json, guard records and both durable records
  store-free (``producer_inputs``);
- opens the accepted catalog plus EXACTLY that pending sealed file through
  IntervalStoreSet.open_pending, which verifies the file's SHA-256, its seal and
  its reference closure and binds the runner's head and identities. The view
  never writes;
- rebuilds the deterministic admission (fresh_interval_driver.admission) and
  reopens the workflow through CollarWorkflow.open, which compares every root
  field with the rebuilt definitions and the initial state from funding;
- mode ``root``: the reopened root equals run A's root identity and its records'
  exact identities are recomputed: a native root's state and mesh JSON arrays
  (what Workflow.create stores at sequence 0), or a compact root's state record
  and v3 mesh;
- mode ``interval``: the root still equals run A's; the successor's inspect,
  state identities, six array-record groups and compact record identities equal
  the producer's; the head is the one successor of the root with its clock
  advanced and its funding unchanged;
- records the width of every exact field (width_gate) on the record bytes it
  proves; at interval 1 the approved pre-interval-2 gate is evaluated against
  interval 0's recorded widths;
- proves the store unchanged.

``--finalise`` (store-free, after the guardian exited cleanly) validates the
reader receipt and writes the reader verdict, which binds the pending view
digest. ``--adopt`` then promotes the sealed file with adopt_and_promote, using
only the runner record, the sealed record and that verdict. Nothing else here
promotes, and no width-gate result blocks the adoption of a correct interval:
the gate decides whether the NEXT interval may run (coordinator and Michael).
"""
import argparse
import gc
import json
import os
import subprocess
import sys
from hashlib import sha256
from pathlib import Path

import reopen_prepared_restart as RO
import run_fresh_interval as F
import run_prepared_restart as RUN

READER_SCHEMA = 'atlas.fresh-interval-reopen-result.v1'
FINAL_SCHEMA = 'atlas.fresh-interval-reopen-final.v1'
ADOPTED_SCHEMA = 'atlas.fresh-interval-adopted.v1'
MODES = F.MODES
WORKLOAD_STATUS = {'root': 'PASS_ROOT_REOPENED_PENDING_FINALISE',
                   'interval': 'PASS_INTERVAL_REOPENED_PENDING_FINALISE'}
ADOPTED_STATUS = 'ADOPTED_AFTER_INDEPENDENT_READER'
CHECKS = {
    'root': frozenset(('pending_file_verified', 'source_bound_admission', 'root_identity', 'root_record_identities',
                       'widths_recorded', 'store_unchanged', 'retained_scope_released')),
    'interval': frozenset(('pending_file_verified', 'source_bound_admission', 'root_identity', 'successor_identity',
                           'state_identities', 'all_six_field_groups_identical', 'compact_record_identities_identical',
                           'fresh_lineage', 'widths_recorded', 'width_gate_evaluated', 'store_unchanged',
                           'retained_scope_released'))}
# A review-only interval (bounded pre-seal refused, file sealed for diagnosis) is read with
# --review: its identities are recorded, not compared, since the refusal left none to compare.
REVIEW_CHECKS = (CHECKS['interval']-{'compact_record_identities_identical'}) | {'compact_record_identities_recorded'}
REVIEW_APPROVAL_SCHEMA = 'atlas.fresh-interval-review-approval.v1'
REVIEW_APPROVERS = ('coordinator', 'Michael')
REOPEN_REASON = {'root': F.ROOT_REOPEN_DEFERRED, 'interval': RUN.SAME_PROCESS_REOPEN_DROPPED}
ROOT_FIELDS = frozenset(('workflow_id', 'root_key', 'kind', 'sequence', 'inspect', 'producer_pid',
                         'root_metadata_sha256', 'store_limits', 'store_compression', 'execution_provenance',
                         'preparation_ids'))
ROOT_RECORDS = frozenset(('state', 'mesh'))


class ReaderRefused(F.FreshRefused):
    pass


def require(condition, message):
    if not condition:
        raise ReaderRefused(message)


def reader_output(row, mode):
    require(mode in MODES, 'explicit route (1) reader mode required')
    return Path(row['output_directory'])/('reader-'+mode)


def adopted_path(store_directory, interval):
    return Path(store_directory)/F.record_name('adopted', interval)


def approval_path(store_directory, interval):
    return Path(store_directory)/F.record_name('review-approval', interval)


def _own_pin(sources):
    own = Path(__file__).resolve()
    require(own.is_relative_to(sources.workspace) and
            sources.files().get(own.relative_to(sources.workspace).as_posix()) == RUN.file_hash(own),
            'independent fresh reader itself must be pinned')
    return own


def _root_record(root):
    """Run A's published root record: closed shape, strict execution, compact bounds."""
    require(type(root) is dict and set(root) == ROOT_FIELDS, 'complete fresh root record required')
    inspected = root['inspect']
    require(RO._identity(root['workflow_id']) and RO._identity(root['root_key']) and root['kind'] == 'root' and
            root['sequence'] == 0 and RO._digest(root['root_metadata_sha256']) and type(inspected) is dict and
            inspected.get('head') == root['root_key'] and inspected.get('intervals') == 0 and
            inspected.get('workflow_id') == root['workflow_id'], 'fresh root identity is incomplete')
    ids, provenance = root['preparation_ids'], root['execution_provenance']
    require(type(ids) is dict and set(ids) == RO.PREPARATIONS and all(RO._identity(v) for v in ids.values()),
            'complete independently exported preparation identities required')
    require(type(provenance) is dict and set(provenance) == {'execution_identity', 'execution_mode'} and
            provenance['execution_mode'] == 'strict' and RO._digest(provenance['execution_identity']),
            'producer must retain strict source/runtime verification')
    require(root['store_limits'] == RUN.COMPACT_STORE_LIMITS and root['store_compression'] == RUN.COMPACT_COMPRESSION,
            'producer compact store bounds differ from the reviewed ones')
    require(inspected.get('funding_id') == ids['funding'], 'fresh root funding differs')
    return root


def _completed(completed, *, root, pid, advanced):
    """The driver's completed-endpoint record extends exactly run A's root, once."""
    require(type(completed) is dict and set(completed) == RO.COMPLETED_FIELDS,
            'complete advanced endpoint record required')
    for name in ('workflow_id', 'root_key', 'head_key', 'collar_result_id', 'native_result_id',
                 'exterior_state_id', 'source_audit_id', 'joined_heat_id'):
        require(RO._identity(completed[name]), 'complete endpoint identities are required')
    metadata = completed['root_metadata']
    require(completed['producer_pid'] == pid and completed['workflow_id'] == root['workflow_id'] and
            completed['root_key'] == root['root_key'] and type(metadata) is dict and
            metadata.get('key') == root['root_key'] and
            sha256(F.canonical(metadata)).hexdigest() == root['root_metadata_sha256'] and
            completed['head_key'] == advanced['head'] != root['root_key'] and completed['sequence'] == 1 and
            completed['preparation_ids'] == root['preparation_ids'] and
            completed['execution_provenance'] == root['execution_provenance'] and
            completed['store_limits'] == root['store_limits'] and
            completed['store_compression'] == root['store_compression'],
            'advanced endpoint does not extend run A root of this producer')
    RO.canonical_records(completed['array_records'])
    return completed


def _producer_receipt(receipt, *, profile, mode, consumer_pid, review=False):
    require(mode == 'interval' or not review, 'only an interval can be sealed for review')
    if review:
        errors = receipt.get('errors') if type(receipt) is dict else None
        state = receipt.get('review_only') if type(receipt) is dict else None
        settled = (type(errors) is list and [e.get('type') for e in errors] == ['PresealSealedForReview'] and
                   type(state) is dict and state.get('state') == F.REVIEW_STATUS)
    else:
        settled = type(receipt) is dict and receipt.get('errors') == []
    require(settled and receipt.get('schema') == F.RESULT_SCHEMA and
            receipt.get('status') == (F.REVIEW_STATUS if review else F.SEALED_STATUS[mode]) and
            receipt.get('final_reserved_bytes') == 0 and receipt.get('production_acceptance') is False and
            receipt.get('profile_sha256') == profile.sha256 and receipt.get('mode') == mode and
            receipt.get('interval') == F.INTERVALS[mode], 'successful sealed producer result of this profile and mode required')
    pid = receipt.get('pid')
    require(type(pid) is int and pid > 0 and type(consumer_pid) is int and consumer_pid > 0 and pid != consumer_pid,
            'separate producer and reader processes required')
    require(receipt.get('same_process_cold_reopen') is False and
            receipt.get('same_process_cold_reopen_reason') == REOPEN_REASON[mode],
            'producer reopen scope differs: this reader is the mandatory cold reopen')
    before = RO.validate_retained_accounting(receipt.get('compact_retained_before_close'), pid=pid)
    after = RO.validate_retained_accounting(receipt.get('compact_retained_after_close'), pid=pid)
    require(after['retained_bytes'] == 0 and before['scope_id'] == after['scope_id'],
            'producer compact retained scope was not released')
    proof = receipt.get('source_proof')
    require(type(proof) is dict and receipt.get('identities') == {
            'producer_identity': profile.sha256, 'runtime_identity': proof.get('native_source_digest')},
            'producer identities differ from its profile and selected runtime')
    return pid


def validate_producer_receipt(receipt, *, profile, receipt_sha256, runner, sealed, guard_receipt, guard_control,
                              consumer_pid, mode, root_runner=None, review=False):
    """Pure closed checks of a sealed producer result; returns the validated expectation."""
    require(mode in MODES and type(profile) is F.FreshProfile, 'typed profile and reader mode required')
    require(RO._digest(receipt_sha256), 'exact producer receipt pin required')
    pid = _producer_receipt(receipt, profile=profile, mode=mode, consumer_pid=consumer_pid, review=review)
    interval, entry, identities = F.INTERVALS[mode], sealed['entry'], receipt['identities']
    runner_sha = sha256(F.canonical(runner)).hexdigest()
    require(runner['interval'] == sealed['interval'] == entry['interval'] == interval and
            runner['head'] == entry['head'] and runner['producer_pid'] == pid and
            runner['producer_identity'] == entry['producer_identity'] == identities['producer_identity'] and
            runner['runtime_identity'] == entry['runtime_identity'] == identities['runtime_identity'] and
            sealed['runner_record_sha256'] == runner_sha == receipt['runner_record']['sha256'] and
            receipt['sealed'] == sealed, 'sealed entry, runner record and producer receipt differ')
    if mode == 'root':
        root = _root_record(runner['root'])
        require(receipt['published_root'] == root and root['producer_pid'] == pid and
                runner['workflow_id'] == root['workflow_id'] == receipt['workflow_id'] and
                sealed['expected_catalog_digest'] is None,
                'run A root record differs from its receipt or is not the first interval')
        expected = {'root': root}
    else:
        require(type(root_runner) is dict, 'run A runner record required for interval 1')
        root = _root_record(root_runner['root'])
        previous, advanced = runner['previous_endpoint'], runner['advanced_endpoint']
        require(runner['root_runner_record_sha256'] == sha256(F.canonical(root_runner)).hexdigest() and
                runner['workflow_id'] == root_runner['workflow_id'] == root['workflow_id'] and
                RO._digest(sealed['expected_catalog_digest']) and
                receipt['advanced_endpoint'] == advanced and receipt['previous_endpoint'] == previous,
                'run B records do not extend run A or differ from their receipt')
        if review:
            state = receipt['review_only']
            require(runner.get('review_only') is True and 'record_identities' not in runner and
                    'record_identities' not in receipt and
                    runner.get('preseal_refused') == receipt.get('preseal_refused') == state.get('cause') and
                    state.get('sealed_file') == {k: entry[k] for k in ('filename', 'file_sha256', 'logical_seal')},
                    'review-only records do not name one refusal and this sealed file')
        else:
            require('review_only' not in runner and receipt['record_identities'] == runner['record_identities'],
                    'run B record identities differ from their receipt')
            RO.canonical_record_identities(runner['record_identities'], successor=True)
        require(type(previous) is dict and type(advanced) is dict and previous.get('head') == root['root_key'] and
                previous.get('intervals') == 0 and advanced.get('intervals') == 1 and
                advanced.get('head') != previous.get('head') and
                advanced.get('funding_id') == previous.get('funding_id') == root['preparation_ids']['funding'] and
                all(type(e.get('time_s')) in (int, float) for e in (previous, advanced)) and
                advanced['time_s'] > previous['time_s'],
                'run B must advance run A root exactly once with unchanged funding')
        queries = receipt.get('completed_queries')
        declared = (receipt.get('completed_query_store') or {}).get('declared')
        require(type(queries) is dict and declared in F.QUERY_STORES and queries.get('store') == declared and
                all(type(queries.get(k)) is int and queries[k] >= 0 for k in ('hits', 'misses', 'written',
                                                                              'incomplete', 'unflushed')),
                'run B completed-query record is incomplete')
        expected = {'root': root, 'previous_endpoint': previous, 'advanced_endpoint': advanced,
                    'completed_endpoint': _completed(receipt.get('completed_endpoint'), root=root, pid=pid,
                                                     advanced=advanced)}
    supervisor = receipt.get('supervisor')
    require(type(supervisor) is dict, 'producer supervisor record required')
    RO.validate_guard(guard_receipt, guard_control, pid=pid, supervisor_pid=supervisor.get('pid'))
    return dict(expected, mode=mode, interval=interval, receipt_sha256=receipt_sha256, producer_pid=pid,
                runner=runner, runner_sha256=runner_sha, sealed=sealed, entry=entry, review=review)


def producer_inputs(profile, *, sources, mode, receipt_sha256, consumer_pid, review=False):
    """Store-free preflight: pinned receipt, guard records, durable records, closed sealed file."""
    require(type(sources) is F.FreshSources and sources.profile is profile, 'selected profile sources required')
    row = profile.record()
    output, store_directory = F.mode_output(row, mode), Path(row['store_directory'])
    receipt = RUN.pinned_json(output/'run.json', receipt_sha256, RO.MAX_RECEIPT)
    guard = RO._bounded_json(output/'run.guard.json')
    control = RO._bounded_json(output/'run.guard-control.json')
    require(not (output/'run.guard-abort.json').exists() and not (output/'run.cancel').exists(),
            'producer was aborted or cancelled')
    interval = F.INTERVALS[mode]
    pins = (receipt.get('runner_record'), receipt.get('sealed_awaiting_reader'))
    paths = (F.runner_record_path(store_directory, interval), F.sealed_record_path(store_directory, interval))
    require(all(type(pin) is dict and set(pin) == {'path', 'sha256'} and pin['path'] == str(path)
                for pin, path in zip(pins, paths, strict=True)), 'producer durable record pins required')
    runner = F.read_record(paths[0], schema=F.RUNNER_RECORD_SCHEMA, expected_sha256=pins[0]['sha256'])
    sealed = F.read_record(paths[1], schema=F.SEALED_SCHEMA, expected_sha256=pins[1]['sha256'])
    root_runner = root_widths = None
    if mode == 'interval':
        root_runner = F.read_record(F.runner_record_path(store_directory, 0), schema=F.RUNNER_RECORD_SCHEMA)
        verdict = F.read_record(F.verdict_path(store_directory, 0), schema=F.VERDICT_SCHEMA)
        adopted = F.read_record(adopted_path(store_directory, 0), schema=ADOPTED_SCHEMA)
        require(verdict['status'] == F.READER_PASS['root'] and
                verdict['runner_record_sha256'] == sha256(F.canonical(root_runner)).hexdigest() and
                adopted['status'] == ADOPTED_STATUS and adopted['entry'] == verdict['entry'] and
                adopted['verdict_sha256'] == sha256(F.canonical(verdict)).hexdigest(),
                'interval 1 requires run A adopted after its own reader PASS')
        root_widths = verdict['widths']
    member = RUN.ordinary(store_directory/sealed['entry']['filename'])
    require(member.parent == store_directory and not os.access(member, os.W_OK) and
            not any(Path(str(member)+suffix).exists() for suffix in ('-wal', '-journal', '-shm')),
            'pending sealed interval file must be read-only and closed')
    expected = validate_producer_receipt(receipt, profile=profile, receipt_sha256=receipt_sha256, runner=runner,
        sealed=sealed, guard_receipt=guard, guard_control=control, consumer_pid=consumer_pid, mode=mode,
        root_runner=root_runner, review=review)
    require(receipt.get('source_proof') == sources.verify(), 'producer source proof differs from the selected sources')
    if root_widths is not None:
        expected['root_widths'] = root_widths
    return expected


def _scanned(table, kind, chunks):
    """Scan one record's canonical chunks into ``table``; returns the bytes' SHA-256 and length."""
    digest, size = sha256(), 0

    def counted():
        nonlocal size
        for chunk in chunks:
            digest.update(chunk)
            size += memoryview(chunk).nbytes
            yield chunk
    table.scan(kind, counted())
    return {'sha256': digest.hexdigest(), 'nbytes': size}


def _proved_records(store, refs, *, budget, scope, source_producer, table):
    """open_records proves every exact identity; one more stream records each record's widths.

    The width stream must be the proved bytes: its SHA-256 and length are
    compared with the reference before the widths count.
    """
    import spatial_records_patch as SR
    result = {}
    with SR.open_records(store, refs, budget=budget, scope=scope, source_producer=source_producer) as opened:
        require(set(opened) == set(refs), 'compact record inventory differs from its references')
        for name, child in opened.items():
            proved = {'sha256': refs[name]['sha256'], 'nbytes': refs[name]['bytes']}
            require(_scanned(table, name, child.iter_json()) == proved,
                    'width stream differs from the proved record: '+name)
            result[name] = proved
            child.close()
    return result


def _mesh(workflow, scope, table):
    import spatial_indexed_patch as SI
    from mesh_tables import CompactMesh
    held = workflow.exterior_state.indexed_record()
    mesh = held.value['thermal_mesh']
    require(type(mesh) is CompactMesh and mesh.scope is scope, 'compact endpoint requires its retained v3 mesh')
    result = _scanned(table, 'mesh', SI.iter_logical_json(mesh))
    del held, mesh
    return result


def _native_records(store, root_key, refs, *, budget, table):
    """A native root's records: each is one canonical JSON byte array of the root, streamed in
    stored chunks; the width stream is the proved bytes (SHA-256 and length equal the header)."""
    result = {}
    for name in sorted(refs):
        reference = refs[name]
        require(type(reference) is dict and set(reference) == {'array', 'bytes', 'sha256'} and
                reference['array'] == 'spatial-record:'+name, 'native root record reference differs: '+name)
        chunks = (memoryview(chunk).cast('B') for _, chunk in store.iter_chunks(root_key, reference['array'],
                                                                                budget=budget))
        proved = {'sha256': reference['sha256'], 'nbytes': reference['bytes']}
        require(_scanned(table, name, chunks) == proved, 'width stream differs from the proved record: '+name)
        result[name] = proved
    return result


def root_record_identities(workflow, table):
    """The fresh root's records, widths recorded on the proved bytes.

    Workflow.create stores the sequence-0 exterior state natively (record_blobs
    state and mesh, as JSON byte arrays of the root); a compact root (record_blobs
    state plus a compact v3 mesh reference) is read through its proved records.
    """
    store, budget, head = workflow._store, workflow._budget, workflow._head
    scope = getattr(store, 'scope', None)
    require(scope is not None and scope.run_budget is budget,
            'root identities require the shared retained store scope')
    require(type(head) is dict and head.get('kind') == 'root', 'fresh root required')
    state = head['exterior_state']
    refs = dict(state['record_blobs'])
    if 'compact_mesh' in state:
        require(set(refs) == {'state'}, 'complete compact root state record required')
        result = _proved_records(store, refs, budget=budget, scope=scope,
                                 source_producer=state['compact_mesh']['source_producer'], table=table)
        result['mesh'] = _mesh(workflow, scope, table)
    else:
        require(set(refs) == ROOT_RECORDS, 'complete native root state and mesh records required')
        result = _native_records(store, head['key'], refs, budget=budget, table=table)
    require(set(result) == ROOT_RECORDS, 'complete root record identities required')
    return result


def successor_record_identities(workflow, table):
    """reopen_prepared_restart.endpoint_record_identities in one proved pass, widths recorded.

    Same inventory, refusals and canonical result; the records are opened once
    for both the identity proof and the width stream.
    """
    import partition_native_patch as PN
    import partition_workflow_patch as PW
    from partition_v2 import PartitionV2
    store, budget, head = workflow._store, workflow._budget, workflow._head
    scope = getattr(store, 'scope', None)
    require(scope is not None and scope.run_budget is budget,
            'compact endpoint identities require the shared retained store scope')
    require(type(head) is dict and head.get('kind') == 'successor', 'compact fresh successor required')
    state = head['exterior_state']
    refs = dict(state['record_blobs'])
    require(set(refs) == {'state'}, 'complete compact state record required')
    exchange = head['exterior_advance']['record_blobs']
    require(set(exchange) == {'exchange', 'graph', 'transport', 'heat'}, 'complete compact exchange records required')
    refs.update(exchange)
    for header, kind in (('differential_certification', 'certification'), ('differential_geometry', 'differential')):
        refs[kind] = head[header]['record_blob']
    result = _proved_records(store, refs, budget=budget, scope=scope,
                             source_producer=state['compact_mesh']['source_producer'], table=table)
    partition = PN.compact_view(workflow.differential_partition)
    require(type(partition) is PartitionV2 and partition.scope is scope,
            'compact endpoint requires its retained v2 partition')
    result['partition'] = PW.descriptor_stats(partition)
    result['mesh'] = _mesh(workflow, scope, table)
    return RO.canonical_record_identities(result, successor=True)


def validate_fresh_lineage(*, root, head, observed):
    """Root -> one successor: exact clocks, interval, partition and funding."""
    require(type(root) is dict and type(head) is dict and type(observed) is dict and
            set(observed) == RO.OBSERVED_FIELDS, 'complete fresh lineage operands required')
    try:
        geometry = head['differential_geometry']
        parent_time = RO._clock(root['state']['fields']['time_s'])
        start = RO._exact_pair(geometry['start_time_s'], 'successor start time')
        end = RO._exact_pair(geometry['end_time_s'], 'successor end time')
        require(start == parent_time < end, 'exact parent/current interval clocks differ')
        require(RO._clock(head['state']['fields']['time_s']) == end and RO._clock(observed['fields_time_s']) == end and
                RO._clock(observed['native_time_s']) == end and RO._clock(observed['exterior_time_s']) == end,
                'stored or reopened state clocks differ from the exact interval clocks')
        require(geometry['interval_id'] == observed['interval_id'] and
                head['differential_partition']['partition_id'] == observed['partition_id'],
                'reopened differential interval or partition differs from the successor header')
        require(RO._identity(root.get('funding_id')) and root['funding_id'] == head.get('funding_id') ==
                observed['funding_id'], 'original funding identity changed across the interval')
    except (KeyError, TypeError) as error:
        raise ReaderRefused('fresh lineage header missing: '+repr(error)) from error
    return {'root_is_parent': True, 'exactly_one_added_interval': True, 'exact_endpoint_clocks_identical': True,
            'funding_unchanged': True, 'interval_id': observed['interval_id']}


def _successor(workflow, store, producer, *, D, W):
    completed, root, advanced = producer['completed_endpoint'], producer['root'], producer['advanced_endpoint']
    head = dict(workflow._head)
    root_key = root['root_key']
    root_metadata = store.metadata(root_key)
    require(head.get('key') == completed['head_key'] == advanced['head'] and head.get('kind') == 'successor' and
            head.get('key') == W.workflow_key('successor', root_key) and head.get('parent_key') == root_key and
            head.get('parent_digest') == W.digest(root_metadata) and head.get('sequence') == 1 and
            root_metadata == completed['root_metadata'] and workflow.inspect() == advanced and
            store.metadata(W.workflow_key('successor', head['key'])) is None,
            'independently reopened successor identity differs')
    state, exterior = workflow.state, workflow.exterior_state
    found = {'collar_result_id': state.result_id, 'native_result_id': state.native_state.result_id,
             'exterior_state_id': exterior.state_id, 'source_audit_id': workflow.source_audit.result_id,
             'joined_heat_id': head['exterior_advance']['joined_heat_id']}
    require(all(found[name] == completed[name] for name in found) and
            workflow._exterior_owner.owner_id == completed['preparation_ids']['spatial_owner'],
            'independently reopened state identities differ')
    groups = RO.endpoint_array_records(D, workflow)
    require(RO.canonical_records(groups) == RO.canonical_records(completed['array_records']),
            'independently reopened endpoint arrays differ')
    del groups
    lineage = validate_fresh_lineage(root=root_metadata, head=head, observed=RO.observed_lineage(workflow))
    return {'endpoint': found, 'lineage': lineage}


def reopen_fresh_interval(profile, *, sources, guard, record, save, producer, mode):
    """Fresh-process reader core; call under sources.selected() and the live guard."""
    require(type(profile) is F.FreshProfile and type(sources) is F.FreshSources and sources.profile is profile and
            sources.selected_now, 'actual selected pinned sources required')
    require(mode in MODES and type(producer) is dict and producer.get('mode') == mode,
            'validated producer expectation for this mode required')
    row = profile.record()
    bound = {name: sources.module(name) for name in (F.DRIVER, *F.FRESH_MODULES)}
    FRESH, CRS, H = bound[F.DRIVER], bound['compact_restart_store'], bound['historical_admission']
    D = bound['probe_heat_original_connected_r9']
    import interval_store_set as IS
    import width_gate as WG
    import workflow_transfer as W
    from atlas_tectonics.resources import WorkBudget
    from atlas_tectonics.reuse import require_strict_execution
    from compact_contracts import SegmentRef
    _own_pin(sources)
    m = F.composition(sources)
    require_strict_execution()
    record.update(RUN.interpreter_gate())
    output = guard.output.parent
    require(output == reader_output(row, mode) and RUN.ordinary(output, directory=True) == output,
            'guard and reader output directory differ')
    import psutil
    available = psutil.virtual_memory().available
    require(available >= RUN.START_BYTES, 'independent reopen requires 10 GiB available at startup')
    guard.budget = budget = WorkBudget(RUN.LOGICAL_BYTES, max_predicate_work_units=1 << 44)
    RUN._guard_boundary(sources, guard, budget)
    check = lambda: guard.check(force=True)
    H._loaded_source_fence(FRESH, row['advance_driver']['sha256'], check)
    record.update(guard_limits={'rss_bytes': RUN.RSS_BYTES, 'free_floor_bytes': RUN.FREE_BYTES,
                                'start_available_bytes': RUN.START_BYTES, 'logical_budget_bytes': RUN.LOGICAL_BYTES},
                  memory_at_start={'available_bytes': available}, source_proof=sources.verify(),
                  launch_environment={name: os.environ.get(name) for name in sorted(RUN.LAUNCH_ENV)},
                  production_acceptance=False)
    entry, runner, sealed, root = producer['entry'], producer['runner'], producer['sealed'], producer['root']
    catalog = Path(row['store_directory'])/F.CATALOG
    review = producer['review']
    checks = dict.fromkeys(REVIEW_CHECKS if review else CHECKS[mode], False)
    record['review_only'] = review
    scope = RUN.new_retained_scope(budget)
    try:
        guard.phase('open-pending-sealed-interval')
        view = IS.IntervalStoreSet.open_pending(catalog, entry['filename'], scope=scope,
            workflow_id=runner['workflow_id'], expected_catalog_digest=sealed['expected_catalog_digest'],
            expected_sha256=entry['file_sha256'], expected_logical_seal=entry['logical_seal'],
            head=SegmentRef.from_wire(runner['head']), producer_identity=runner['producer_identity'],
            runtime_identity=runner['runtime_identity'])
        try:
            store = CRS.CompactRestartStore(view, scope=scope, owns_resolver=True)
        except BaseException:
            view.close()
            raise
        with store:
            require(view.pending_entry.to_wire() == entry and store.readonly, 'pending view differs from the sealed entry')
            F._store_configuration(store)
            record.update(view_digest=view.catalog_digest, accepted_catalog_digest=view.accepted_catalog_digest)
            checks['pending_file_verified'] = True
            token = store.change_token()
            guard.phase('rebuild-fresh-admission')
            with FRESH.admission(m, budget=budget, artifacts=output, phase=guard.phase) as a:
                require(a.heat_execution.provenance == root['execution_provenance'] and
                        FRESH.preparation_ids(a.case, a.owner) == root['preparation_ids'],
                        'independently rebuilt runtime, plans or owner differ from run A')
                checks['source_bound_admission'] = True
                guard.phase('independent-open-fresh-workflow')
                with m.Workflow.open(store, runner['workflow_id'], a.case['collar'], a.case['owner'],
                                     a.case['funding'], budget=budget, exterior_owner=a.owner) as workflow:
                    found = FRESH.published_root(workflow, store, a)
                    differing = [name for name in FRESH.ROOT_IDENTITY if found[name] != root[name]]
                    require(not differing, 'independently reopened root differs from run A: '+', '.join(differing))
                    require(found['store_limits'] == root['store_limits'] and
                            found['store_compression'] == root['store_compression'],
                            'reader store bounds differ from run A')
                    checks['root_identity'] = True
                    table = WG.WidthTable(F.INTERVALS[mode])
                    guard.phase('independent-record-identities-and-widths')
                    if mode == 'root':
                        require(found['inspect'] == root['inspect'] and workflow._head.get('kind') == 'root',
                                'root reopen differs from run A root')
                        record['root_record_identities'] = root_record_identities(workflow, table)
                        checks['root_record_identities'] = True
                        evidence = {'root': found['inspect']}
                    else:
                        evidence = _successor(workflow, store, producer, D=D, W=W)
                        checks.update(successor_identity=True, state_identities=True,
                                      all_six_field_groups_identical=True, fresh_lineage=True)
                        identities = successor_record_identities(workflow, table)
                        record['record_identities'] = identities
                        if review:
                            # The refused pre-seal left no production identities to compare with:
                            # these are recorded for the diagnosis, which decides alone.
                            checks['compact_record_identities_recorded'] = True
                        else:
                            require(identities == runner['record_identities'],
                                    'independently streamed compact endpoint records differ')
                            checks['compact_record_identities_identical'] = True
                    record['widths'] = table.wire()
                    checks['widths_recorded'] = True
                    if mode == 'interval':
                        record['width_gate'] = WG.gate(WG.WidthTable.from_wire(producer['root_widths']), table)
                        checks['width_gate_evaluated'] = True
                    record['evidence'] = evidence
                    save()
                    del workflow
            require(store.change_token() == token, 'independent reopen wrote to the pending view')
            checks['store_unchanged'] = True
            record['compact_store_statistics'] = store.statistics()
        sources.check_imported()
        sources.verify()
        record['independent_checks'] = checks
        return budget
    finally:
        active_error = sys.exception()
        record['retained_scope'] = {'before_close': RO.retained_accounting(scope)}
        try:
            scope.close()
            record['retained_scope']['after_close'] = RO.retained_accounting(scope)
            require(record['retained_scope']['after_close']['retained_bytes'] == 0,
                    'fresh reader retained owners after scope closure')
            checks['retained_scope_released'] = True
        except BaseException as release_error:
            if active_error is None:
                raise
            active_error.add_note('Retained scope finalisation also failed: '+repr(release_error))


def command(profile, python, *, mode, producer_receipt_sha256, review=False):
    """Store-free preflight and the guarded argv; never launches."""
    sources = F.FreshSources(profile)
    producer_inputs(profile, sources=sources, mode=mode, receipt_sha256=producer_receipt_sha256,
                    consumer_pid=os.getpid(), review=review)
    row = profile.record()
    output = reader_output(row, mode)
    RUN.ordinary(output.parent, directory=True)
    require(output.is_relative_to(sources.workspace) and not output.exists(), 'exclusive new reader output directory required')
    own = _own_pin(sources)
    guard = sources.path(row['modules']['private_heat_continuation_guard_r3'])
    python = str(RUN.ordinary(python))
    return [python, '-B', str(guard), '--launch', '--output', str(output/'reopen.json'), '--',
            python, '-B', str(own), '--workload', '--profile', str(profile.path), '--profile-sha256', profile.sha256,
            '--mode', mode, '--producer-receipt-sha256', producer_receipt_sha256, *(['--review'] if review else [])]


def _workload(profile, *, mode, producer_receipt_sha256, review=False):
    require(sys.dont_write_bytecode, 'run with -B to preserve frozen sources')
    sources = F.FreshSources(profile)
    output = reader_output(profile.record(), mode)/'reopen.json'
    record: dict = {'schema': READER_SCHEMA, 'status': 'STARTED', 'pid': os.getpid(), 'profile_sha256': profile.sha256,
                    'producer_receipt_sha256': producer_receipt_sha256, 'mode': mode, 'errors': [],
                    'production_acceptance': False, 'independent_process_reopen': True, 'review_only': review}
    guard = budget = None
    # The supervisor has already claimed sidecars. Receipt creation is exclusive.
    with output.open('x', encoding='utf8') as stream:
        json.dump(record, stream)
    with sources.selected():
        G = sources.module('private_heat_continuation_guard_r3')
        save = lambda: G._write(output, record)
        try:
            guard = G.ContinuationGuard(output, record, save)
            producer = producer_inputs(profile, sources=sources, mode=mode, receipt_sha256=producer_receipt_sha256,
                                       consumer_pid=os.getpid(), review=review)
            budget = reopen_fresh_interval(profile, sources=sources, guard=guard, record=record, save=save,
                                           producer=producer, mode=mode)
            del producer
            record['status'] = 'VERIFYING_FINALISATION'
        except BaseException as error:  # noqa: BLE001 - every failure, guard aborts included, is recorded
            record['status'] = 'FAILED'
            record['errors'].append(F._error(error))
            if guard is not None and guard.budget is not None:
                record['logical_budget_at_failure'] = guard.budget.statistics()
            save()
        finally:
            gc.collect()
            budget = budget if budget is not None else getattr(guard, 'budget', None)
            if budget is not None:
                record['final_reserved_bytes'] = budget.reserved_bytes
                statistics = budget.statistics()
                record['logical_budget_final'] = {'peak_reserved_bytes': statistics['peak_reserved_bytes'],
                                                  'category_peaks': statistics['category_peaks']}
                if budget.reserved_bytes:
                    record['errors'].append({'type': 'RetainedReservations', 'message': str(budget.reserved_bytes)})
            times = os.times()
            record['parent_cpu_seconds'] = {'user': times.user, 'system': times.system}
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
            except BaseException as error:  # noqa: BLE001 - a finalisation failure is recorded, never lost
                record['errors'].append(F._error(error))
            record['status'] = 'FAILED' if record['errors'] else WORKLOAD_STATUS[mode]
            save()
    return 0 if not record['errors'] else 1


def validate_reopen_receipt(reopen, *, guard_receipt, guard_control, profile, producer, mode):
    """Pure closed checks of the guarded reader result after its guardian exited."""
    import width_gate as WG
    review = producer['review']
    require(type(reopen) is dict and reopen.get('schema') == READER_SCHEMA and
            reopen.get('status') == WORKLOAD_STATUS[mode] and reopen.get('errors') == [] and
            reopen.get('final_reserved_bytes') == 0 and reopen.get('production_acceptance') is False and
            reopen.get('independent_process_reopen') is True and reopen.get('mode') == mode and
            reopen.get('profile_sha256') == profile.sha256 and reopen.get('review_only') is review and
            reopen.get('producer_receipt_sha256') == producer['receipt_sha256'] and
            reopen.get('remaining_children') == [],
            'successful independent reader result of this producer, profile and mode required')
    pid = reopen.get('pid')
    require(type(pid) is int and pid > 0 and pid != producer['producer_pid'],
            'reader must run in a process separate from the producer')
    checks = reopen.get('independent_checks')
    expected = REVIEW_CHECKS if review else CHECKS[mode]
    require(type(checks) is dict and set(checks) == expected and all(value is True for value in checks.values()),
            'every independent reopen check must have passed')
    require(RO._digest(reopen.get('view_digest')), 'pending view digest required')
    widths = WG.WidthTable.from_wire(reopen.get('widths'))
    require(widths.interval == producer['interval'], 'reader widths belong to another interval')
    if mode == 'root':
        identities = reopen.get('root_record_identities')
        require(type(identities) is dict and set(identities) == ROOT_RECORDS and
                all(type(v) is dict and set(v) == {'sha256', 'nbytes'} and RO._digest(v['sha256']) and
                    type(v['nbytes']) is int and v['nbytes'] > 0 for v in identities.values()),
                'complete root record identities required')
    else:
        if review:
            RO.canonical_record_identities(reopen.get('record_identities'), successor=True)
        else:
            require(reopen.get('record_identities') == producer['runner']['record_identities'],
                    'independent compact logical records differ')
        gate = reopen.get('width_gate')
        require(type(gate) is dict and gate.get('schema') == 'atlas.exact-width-gate.v1' and
                type(gate.get('passed')) is bool, 'evaluated pre-interval-2 width gate required')
    retained = reopen.get('retained_scope')
    require(type(retained) is dict and set(retained) == {'before_close', 'after_close'} and
            retained['after_close'].get('retained_bytes') == 0 and
            retained['before_close'].get('scope_id') == retained['after_close'].get('scope_id'),
            'independent compact retained scope release evidence is incomplete')
    for value in retained.values():
        RO.validate_retained_accounting(value, pid=pid)
    supervisor = reopen.get('supervisor')
    require(type(supervisor) is dict, 'reader supervisor record required')
    RO.validate_guard(guard_receipt, guard_control, pid=pid, supervisor_pid=supervisor.get('pid'))


def finalise(profile, *, mode, producer_receipt_sha256, reopen_receipt_sha256, review=False):
    """Store-free acceptance of a completed guarded reader; the exclusive verdict on PASS.

    A review-only verdict says so: it is evidence for the review, never an adoption by itself.
    """
    sources = F.FreshSources(profile)
    row = profile.record()
    output = reader_output(row, mode)
    final = output/'reopen-final.json'
    require(RUN.ordinary(output, directory=True) == output and not final.exists(), 'reader final record already exists')
    errors, verdict_sha256, gate = [], None, None
    try:
        proof = sources.verify()
        producer = producer_inputs(profile, sources=sources, mode=mode, receipt_sha256=producer_receipt_sha256,
                                   consumer_pid=os.getpid(), review=review)
        reopen = RUN.pinned_json(output/'reopen.json', reopen_receipt_sha256, RO.MAX_RECEIPT)
        require(not (output/'reopen.guard-abort.json').exists() and not (output/'reopen.cancel').exists(),
                'reader was aborted or cancelled')
        validate_reopen_receipt(reopen, guard_receipt=RO._bounded_json(output/'reopen.guard.json'),
            guard_control=RO._bounded_json(output/'reopen.guard-control.json'), profile=profile,
            producer=producer, mode=mode)
        require(reopen.get('source_proof') == proof, 'reader source proof differs from the selected sources')
        # This store-free process imported its validators normally: each must be a pinned source.
        sources.check_imported()
        gate = reopen.get('width_gate')
        verdict = {'schema': F.VERDICT_SCHEMA, 'status': F.READER_PASS[mode], 'interval': producer['interval'],
                   'entry': producer['entry'], 'runner_record_sha256': producer['runner_sha256'],
                   'view_digest': reopen['view_digest'], 'accepted_catalog_digest': reopen['accepted_catalog_digest'],
                   'producer_receipt_sha256': producer_receipt_sha256, 'reopen_receipt_sha256': reopen_receipt_sha256,
                   'reader_pid': reopen['pid'], 'widths': reopen['widths'],
                   **({} if gate is None else {'width_gate': gate}),
                   **({'review_only': True, 'preseal_refused': producer['runner']['preseal_refused'],
                       'record_identities': reopen['record_identities']} if review else {})}
        verdict_sha256 = F.write_durable(F.verdict_path(Path(row['store_directory']), producer['interval']), verdict)
    except Exception as error:  # noqa: BLE001 - the final record carries every refusal
        errors.append(F._error(error))
    result = {'schema': FINAL_SCHEMA, 'status': 'FAILED' if errors else F.READER_PASS[mode], 'mode': mode,
              'profile_sha256': profile.sha256, 'producer_receipt_sha256': producer_receipt_sha256,
              'reopen_receipt_sha256': reopen_receipt_sha256, 'verdict_sha256': verdict_sha256,
              'width_gate_passed': None if gate is None else gate['passed'], 'errors': errors,
              'production_acceptance': False, 'independent_process_reopen': not errors}
    with final.open('x', encoding='utf8') as stream:
        json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write('\n')
    print(json.dumps({'status': result['status'], 'verdict_sha256': verdict_sha256,
                      'width_gate_passed': result['width_gate_passed'], 'errors': errors}), flush=True)
    return 0 if not errors else 1


def review_approval(store_directory, interval, approval_sha256, *, entry, verdict_sha256):
    """The coordinator's conditions for adopting a review-only interval (16 Oct 2026), all required.

    (a) the reader PASS on this exact file (the verdict, checked by the caller);
    (b) a written diagnosis showing a checker defect, not a data defect;
    (c) a recorded approval by the coordinator or Michael naming the file SHA-256 and the verdict.
    A data-integrity cause is quarantined and never adopted: the interval is rerun after the fix.
    """
    approval = F.read_record(approval_path(store_directory, interval), schema=REVIEW_APPROVAL_SCHEMA,
                             expected_sha256=approval_sha256)
    require(approval.get('interval') == interval and approval.get('file_sha256') == entry['file_sha256'] and
            approval.get('verdict_sha256') == verdict_sha256 and approval.get('approver') in REVIEW_APPROVERS and
            type(approval.get('approved_at')) is str and approval['approved_at'],
            'review approval does not name this sealed file, its reader verdict and an approver')
    require(approval.get('cause_class') == 'checker-defect',
            'a data-integrity cause is quarantined, never adopted: rerun the interval after the fix')
    diagnosis = approval.get('diagnosis')
    require(type(diagnosis) is dict and set(diagnosis) == {'path', 'sha256'} and Path(diagnosis['path']).is_file() and
            RUN.file_hash(diagnosis['path']) == diagnosis['sha256'], 'written diagnosis evidence required')
    return approval


def adoption_inputs(store_directory, interval, verdict_sha256, approval_sha256=None):
    """The records adopt_and_promote may use, and nothing else; refuses any inconsistency."""
    verdict = F.read_record(F.verdict_path(store_directory, interval), schema=F.VERDICT_SCHEMA,
                            expected_sha256=verdict_sha256)
    runner = F.read_record(F.runner_record_path(store_directory, interval), schema=F.RUNNER_RECORD_SCHEMA,
                           expected_sha256=verdict['runner_record_sha256'])
    sealed = F.read_record(F.sealed_record_path(store_directory, interval), schema=F.SEALED_SCHEMA)
    entry = sealed['entry']
    mode = MODES[interval]
    require(verdict['status'] == F.READER_PASS[mode] and verdict['interval'] == interval == entry['interval'] and
            verdict['entry'] == entry and sealed['runner_record_sha256'] == verdict['runner_record_sha256'] and
            runner['head'] == entry['head'] and runner['producer_identity'] == entry['producer_identity'] and
            runner['runtime_identity'] == entry['runtime_identity'] and RO._digest(verdict['view_digest']),
            'adoption requires one consistent runner record, sealed record and reader PASS')
    review = bool(runner.get('review_only')) or bool(verdict.get('review_only'))
    require(review == (approval_sha256 is not None),
            'a review-only interval needs its recorded approval, and only a review-only interval takes one')
    if review:
        require(runner.get('review_only') is True and verdict.get('review_only') is True,
                'review-only runner record and verdict required')
        review_approval(store_directory, interval, approval_sha256, entry=entry, verdict_sha256=verdict_sha256)
    return verdict, runner, sealed


def adopt(profile, *, mode, verdict_sha256, approval_sha256=None):
    """Promote the sealed interval after its reader PASS, from the durable records only."""
    sources = F.FreshSources(profile)
    row = profile.record()
    store_directory, interval = Path(row['store_directory']), F.INTERVALS[mode]
    path = adopted_path(store_directory, interval)
    require(not path.exists(), 'this interval was already adopted')
    verdict, runner, sealed = adoption_inputs(store_directory, interval, verdict_sha256, approval_sha256)
    sources.check_imported()
    entry = sealed['entry']
    with sources.selected():
        import interval_store_set as IS
        from atlas_tectonics.resources import WorkBudget
        from compact_contracts import SegmentRef
        from content_cache import create_retained_scope
        budget = WorkBudget(RUN.LOGICAL_BYTES)
        scope = create_retained_scope(budget, process_epoch='fresh-adopt-'+str(os.getpid()))
        catalog = store_directory/F.CATALOG
        try:
            stores = (IS.IntervalStoreSet.create_migration(catalog, workflow_id=runner['workflow_id'], scope=scope)
                      if sealed['expected_catalog_digest'] is None else
                      IS.IntervalStoreSet.open_catalog(catalog, scope=scope))
            try:
                adopted = stores.adopt_and_promote(entry['filename'], expected_sha256=entry['file_sha256'],
                    expected_logical_seal=entry['logical_seal'], head=SegmentRef.from_wire(runner['head']),
                    producer_identity=runner['producer_identity'], runtime_identity=runner['runtime_identity'],
                    expected_catalog_digest=sealed['expected_catalog_digest'],
                    reader_view_digest=verdict['view_digest'])
                require(adopted.to_wire() == entry, 'adopted entry differs from the sealed entry')
                catalog_digest = stores.catalog_digest
            finally:
                stores.close()
        finally:
            active_error = sys.exception()
            gc.collect()
            try:
                scope.close()
            except BaseException as release_error:
                if active_error is None:
                    raise
                active_error.add_note('Adoption scope finalisation also failed: '+repr(release_error))
        sources.check_imported()
    sources.verify()
    value = {'schema': ADOPTED_SCHEMA, 'status': ADOPTED_STATUS, 'interval': interval, 'entry': entry,
             'catalog_digest': catalog_digest, 'catalog_sha256': RUN.file_hash(catalog),
             'verdict_sha256': verdict_sha256, 'runner_record_sha256': verdict['runner_record_sha256'],
             'adopter_pid': os.getpid(), **({'review_approval_sha256': approval_sha256} if approval_sha256 else {})}
    pin = F.write_durable(path, value)
    print(json.dumps({'status': ADOPTED_STATUS, 'adopted': str(path), 'sha256': pin}), flush=True)
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', type=Path, required=True)
    parser.add_argument('--profile-sha256', required=True)
    parser.add_argument('--mode', choices=MODES, required=True)
    parser.add_argument('--producer-receipt-sha256')
    parser.add_argument('--reopen-receipt-sha256')
    parser.add_argument('--verdict-sha256')
    parser.add_argument('--review', action='store_true', help='read an interval sealed for review after a pre-seal refusal')
    parser.add_argument('--review-approval-sha256', help='with --adopt: the recorded approval of a review-only interval')
    action = parser.add_mutually_exclusive_group()
    for name in ('--launch', '--workload', '--finalise', '--adopt'):
        action.add_argument(name, action='store_true')
    args = parser.parse_args(argv)
    require((args.reopen_receipt_sha256 is not None) == args.finalise and
            (args.verdict_sha256 is not None) == args.adopt and
            (args.producer_receipt_sha256 is not None) == (not args.adopt) and
            not (args.review and args.adopt) and (args.review_approval_sha256 is None or args.adopt),
            '--reopen-receipt-sha256 goes with --finalise, --verdict-sha256 and --review-approval-sha256 with '
            '--adopt, --review and --producer-receipt-sha256 with every other action')
    profile = F.FreshProfile.read(args.profile, args.profile_sha256)
    if args.adopt:
        return adopt(profile, mode=args.mode, verdict_sha256=args.verdict_sha256,
                     approval_sha256=args.review_approval_sha256)
    if args.workload:
        return _workload(profile, mode=args.mode, producer_receipt_sha256=args.producer_receipt_sha256,
                         review=args.review)
    if args.finalise:
        return finalise(profile, mode=args.mode, producer_receipt_sha256=args.producer_receipt_sha256,
                        reopen_receipt_sha256=args.reopen_receipt_sha256, review=args.review)
    argv = command(profile, sys.executable, mode=args.mode, producer_receipt_sha256=args.producer_receipt_sha256,
                   review=args.review)
    print(json.dumps({'status': 'SOURCE_BOUND_COMMAND_ONLY_NOT_ADMISSION', 'command': argv,
                      'production_acceptance': False}), flush=True)
    if not args.launch:
        return 0
    import psutil
    require(psutil.virtual_memory().available >= RUN.START_BYTES, 'independent reopen requires 10 GiB available')
    output = reader_output(profile.record(), args.mode)
    output.mkdir(exist_ok=False)
    return subprocess.call(argv, env=RUN.launch_environment(), cwd=output)


if __name__ == '__main__':
    raise SystemExit(main())
