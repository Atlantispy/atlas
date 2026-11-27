"""Independent fresh-process reader of a route (1) sealed interval (Step 9(a), option B).

The runner (run_fresh_interval.py) sealed its interval file without promoting it,
after recording durably the head and identities it asserts (the runner record);
the sealed record followed the seal. In a NEW guarded process with the same
pinned sources and limits (the by-need start gate, 12 GiB RSS / 1 GiB free guard,
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
the gate decides whether the NEXT interval may run (reviewer and owner).
"""
import argparse
from contextlib import ExitStack
from contextlib import contextmanager
from functools import wraps
import gc
import json
import os
import subprocess
import sys
import time
from hashlib import sha256
from pathlib import Path


# o2 C2: fixed scalar subset of InitialParallel.report (its log and stats are unbounded).
INITIAL_ADMISSION_KEYS = ('workers', 'batch_jobs', 'outstanding', 'opened', 'batches', 'offered', 'unshipped',
                          'skipped', 'retired', 'adopted', 'serial', 'refused', 'note', 'cause', 'last_error')

if __name__ == '__main__' and Path(__file__).resolve().parent.parts[-3:] == ('atlas_tectonics', '_private', 'integration'):
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    __package__ = 'atlas_tectonics._private.integration'


from atlas_tectonics._private.integration import reopen_prepared_restart as RO
from atlas_shared.execution import profiling
from atlas_tectonics._private.integration import run_fresh_interval as F
from atlas_tectonics._private.integration import run_prepared_restart as RUN
from atlas_tectonics._private.integration import start_gate as SG
from atlas_tectonics._private.integration.interval_admission import admitted, protect_profile
from atlas_shared.machine import resources_monitor as MONITOR
from atlas_tectonics._private.integration.geometry import overlap_reader as OR
from atlas_tectonics._private.integration.geometry import reader_overlap_gate as OG
from atlas_tectonics._private.integration import reuse_previous_run as REUSE
# Unit A: the shared width pass lives in width_gate, so the producer imports nothing of this reader.
from atlas_tectonics._private.integration.width_gate import (ROOT_RECORDS, _mesh, _native_records,  # noqa: F401
    _proved_records, _scanned, root_record_identities, successor_record_identities)

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
# Unit A (design duplicate-removal-r1 A-2): the records-only core runs no admission and opens no workflow.
RECORDS_CHECKS = {
    'root': frozenset(('pending_file_verified', 'root_record_identities', 'widths_recorded',
                       'retained_scope_released')),
    'interval': frozenset(('pending_file_verified', 'widths_adopted', 'widths_recorded', 'width_gate_evaluated',
                           'retained_scope_released'))}
# The review approval is checked by the runner's sealed-lineage gate as well, so it lives there (item 21).
REVIEW_APPROVAL_SCHEMA, REVIEW_APPROVERS = F.REVIEW_APPROVAL_SCHEMA, F.REVIEW_APPROVERS
ROOT_FIELDS = frozenset(('workflow_id', 'root_key', 'kind', 'sequence', 'inspect', 'producer_pid',
                         'root_metadata_sha256', 'store_limits', 'store_compression', 'execution_provenance',
                         'preparation_ids'))
# Item 21: what an interval N >= 2 runner record adds to bind its sealed lineage.


class ReaderRefused(F.FreshRefused):
    pass


def require(condition, message):
    if not condition:
        raise ReaderRefused(message)


def reader_output(row, mode, interval=None, *, fallback=False):
    number = F.interval_number(mode, interval)
    output = Path(row['output_directory'])/('reader-'+mode+('' if number <= 1 else f'-{number:04d}')+
                                           ('-fallback' if fallback else ''))
    return output


adopted_path, approval_path, review_approval = F.adopted_path, F.approval_path, F.review_approval


def seed_from_producer(stored, source, output, check, *, binding, previous):
    """Decision 326: the reader admits from its producer's closed measurement store, copied by the receipt's pin.

    The reader measures nothing the producer measured. Its PASS does not attest the initial metrics a second time.
    ``stored`` is the store's record: the receipt's, or the one an overlap reader's producer published.
    ``binding`` is this reader's F.measurement_composition; the store's must equal it field by field, as the
    producer's own seed requires. ``previous``: the producer is a previous run's (diagnostic trees
    only); the fields that differ are then recorded and the store is used (rulings 4a, 6)."""
    require(type(stored) is dict and stored.get('filename') == F.MEASUREMENT_STORE and RO._digest(stored.get('sha256'))
            and type(stored.get('statistics')) is dict and type(stored['statistics'].get('snapshots')) is int
            and type(stored.get('composition')) is dict,
            'the producer receipt does not name its closed measurement store and its composition')
    theirs = stored['composition']
    differing = sorted(name for name in set(binding) | set(theirs)
                       if name not in theirs or name not in binding or theirs[name] != binding[name])
    size = F._copy_pinned(Path(source)/F.MEASUREMENT_STORE, Path(output)/F.MEASUREMENT_STORE, stored['sha256'], check)
    return {'source': 'producer-store', 'pinned_sha256': stored['sha256'], 'bytes': size,
            'seed_snapshots': stored['statistics']['snapshots'], 'composition_differing': differing, 'store': stored}


def _published_store(source, spec, check, *, clock=time.monotonic, sleep=time.sleep):
    """Decision 344: an overlap reader's measurement store, taken at its point of use.

    Waits, under the gate's own bounds (the specification's timeout, its launcher, the live guard), for the record
    the producer publishes when it closes its store (F.MEASUREMENT_RECORD). Nothing in it is authenticated yet:
    the store is copied by its pin, and after the gate the receipt must name the same record."""
    path, deadline = Path(source)/F.MEASUREMENT_RECORD, clock()+spec['timeout_seconds']
    while not path.exists():
        check()
        if clock() >= deadline:
            raise OG.WaitFailure('wait_expired', 'before the producer published its measurement store')
        sleep(1.0)
    return OR.read_json(path)[0]


def _root_record(root):
    """Run A's published root record: closed shape, producer provenance, compact bounds."""
    inspected = root['inspect']
    require(RO._identity(root['workflow_id']) and RO._identity(root['root_key']) and root['kind'] == 'root' and
            root['sequence'] == 0 and RO._digest(root['root_metadata_sha256']) and type(inspected) is dict and
            inspected.get('head') == root['root_key'] and inspected.get('intervals') == 0 and
            inspected.get('workflow_id') == root['workflow_id'], 'fresh root identity is incomplete')
    _, provenance = root['preparation_ids'], root['execution_provenance']
    RO.validate_execution_provenance(provenance)
    return root


def _completed(completed, *, root, pid, advanced, sequence=1):
    """The driver's completed-endpoint record extends run A's root, at exactly ``sequence``."""
    metadata = completed['root_metadata']
    require(completed['producer_pid'] == pid and completed['workflow_id'] == root['workflow_id'] and
            completed['root_key'] == root['root_key'] and type(metadata) is dict and
            metadata.get('key') == root['root_key'] and
            sha256(F.canonical(metadata)).hexdigest() == root['root_metadata_sha256'] and
            completed['head_key'] == advanced['head'] != root['root_key'] and completed['sequence'] == sequence and
            completed['preparation_ids'] == root['preparation_ids'] and
            RO.execution_matches(completed['execution_provenance'], root['execution_provenance']) and
            completed['store_limits'] == root['store_limits'] and
            completed['store_compression'] == root['store_compression'],
            'advanced endpoint does not extend run A root of this producer')
    RO.canonical_records(completed['array_records'])
    return completed


def _said(errors):
    """An error list as text: each error's type and message."""
    return '; '.join(f"{e.get('type')}: {e.get('message')}" if type(e) is dict else repr(e) for e in errors)


def _producer_receipt(receipt, *, profile, mode, consumer_pid, review=False, interval=None, recorded=None):
    if review:
        errors = receipt.get('errors') if type(receipt) is dict else None
        state = receipt.get('review_only') if type(receipt) is dict else None
        settled = (type(errors) is list and [e.get('type') for e in errors] == ['PresealSealedForReview'] and
                   type(state) is dict and state.get('state') == F.REVIEW_STATUS)
    else:  # how the producer ended is a prior test, below; its data are tested here
        settled = type(receipt) is dict and type(receipt.get('errors')) is list
    require(settled and receipt.get('schema') == F.RESULT_SCHEMA and
            (not review or receipt.get('status') == F.REVIEW_STATUS and receipt.get('final_reserved_bytes') == 0) and
            receipt.get('production_acceptance') is False and
            receipt.get('profile_sha256') == profile.sha256 and receipt.get('mode') == mode and
            receipt.get('interval') == F.interval_number(mode, interval), 'successful sealed producer result of this profile and mode required')
    if not review:
        RO.prior(receipt['errors'] == [], 'producer errors: '+_said(receipt['errors']), recorded)
        RO.prior(receipt.get('status') == F.SEALED_STATUS[mode], f"producer status {receipt.get('status')!r}", recorded)
        RO.prior(receipt.get('final_reserved_bytes') == 0,
                 f"producer final_reserved_bytes {receipt.get('final_reserved_bytes')!r}", recorded)
    pid = receipt.get('pid')
    before = RO.validate_retained_accounting(receipt.get('compact_retained_before_close'), pid=pid)
    after = RO.validate_retained_accounting(receipt.get('compact_retained_after_close'), pid=pid)
    RO.prior(RO.retained_release_agrees(before, after), 'producer compact retained scope was not released', recorded)
    identities = receipt.get('identities')
    require(type(identities) is dict and set(identities) == {'producer_identity', 'runtime_identity'} and
            identities['producer_identity'] == profile.sha256, 'producer identities differ from its profile')
    return pid


def validate_producer_receipt(receipt, *, profile, receipt_sha256, runner, sealed, guard_receipt, guard_control,
                              consumer_pid, mode, root_runner=None, review=False, interval=None, lineage=None,
                              recorded=None, _runner_sha256=None):
    """Pure closed checks of a sealed producer result; returns the validated expectation.

    Interval N >= 2 (item 21) takes ``lineage``, the runner's sealed-lineage gate on adopted
    interval N-1, re-run by this reader; its run A runner record is the gate's.
    """
    number = F.interval_number(mode, interval)
    require((number >= 2) == (lineage is not None) and
            (lineage is None or type(lineage) is dict and lineage.get('root_runner') == root_runner and
             type(lineage.get('lineage')) is dict and lineage['lineage'].get('interval') == number-1),
            'interval N >= 2 is read from its own sealed lineage gate, and only it')
    pid = _producer_receipt(receipt, profile=profile, mode=mode, consumer_pid=consumer_pid, review=review,
                            interval=interval, recorded=recorded)
    RO._producer_limits(receipt)
    interval, entry, identities = number, sealed['entry'], receipt['identities']
    runner_sha = sha256(F.canonical(runner)).hexdigest() if _runner_sha256 is None else _runner_sha256
    require(runner['interval'] == sealed['interval'] == entry['interval'] == interval and
            runner['head'] == entry['head'] and runner['producer_pid'] == pid and
            runner['producer_identity'] == entry['producer_identity'] == identities['producer_identity'] and
            runner['runtime_identity'] == entry['runtime_identity'] == identities['runtime_identity'] and
            sealed['runner_record_sha256'] == runner_sha == receipt['runner_record']['sha256'] and
            receipt['sealed'] == sealed, 'sealed entry, runner record and producer receipt differ')
    if mode == 'root':
        root = _root_record(runner['root'])
        expected = {'root': root}
    else:
        root = _root_record(root_runner.get('root'))
        previous, advanced = runner['previous_endpoint'], runner['advanced_endpoint']
        require(runner['root_runner_record_sha256'] == sha256(F.canonical(root_runner)).hexdigest() and
                runner['workflow_id'] == root_runner['workflow_id'] == root['workflow_id'] and
                RO._digest(sealed['expected_catalog_digest']) and
                receipt['advanced_endpoint'] == advanced and receipt['previous_endpoint'] == previous,
                'run B records do not extend run A or differ from their receipt')
        if lineage is None:
            parent_key = root['root_key']
        else:
            bound = lineage['lineage']
            parent_key = bound['head_key']
            require(runner.get('parent_runner_record_sha256') == bound['records'][-1]['runner_sha256'] and
                    runner.get('parent_adopted_sha256') == lineage['parent_adopted_sha256'] and
                    runner.get('lineage') == bound and bound['workflow_id'] == root['workflow_id'] and
                    bound['root_key'] == root['root_key'] and
                    sealed['expected_catalog_digest'] == bound['catalog_digest'],
                    'run B records do not extend the adopted interval N-1 of their lineage')
        if review:
            state = receipt['review_only']
            require(runner.get('review_only') is True and 'record_identities' not in runner and
                    'record_identities' not in receipt and
                    runner.get('preseal_refused') == receipt.get('preseal_refused') == state.get('cause') and
                    state.get('sealed_file') == {k: entry[k] for k in ('filename', 'file_sha256', 'logical_seal')},
                    'review-only records do not name one refusal and this sealed file')
        else:
            RO.canonical_record_identities(runner['record_identities'], successor=True)
        require(type(previous) is dict and type(advanced) is dict and previous.get('head') == parent_key and
                previous.get('intervals') == interval-1 and advanced.get('intervals') == interval and
                advanced.get('head') != previous.get('head') and
                advanced.get('funding_id') == previous.get('funding_id') == root['preparation_ids']['funding'] and
                all(type(e.get('time_s')) in (int, float) for e in (previous, advanced)) and
                advanced['time_s'] > previous['time_s'],
                'run B must advance run A root exactly once with unchanged funding' if interval == 1 else
                'interval N must advance its parent exactly once with unchanged funding')
        expected = {'root': root, 'previous_endpoint': previous, 'advanced_endpoint': advanced,
                    'parent_key': parent_key,
                    'completed_endpoint': _completed(receipt.get('completed_endpoint'), root=root, pid=pid,
                                                     advanced=advanced, sequence=interval)}
        if lineage is not None:
            expected['lineage'] = lineage['lineage']
    if review:
        pass
    return dict(expected, mode=mode, interval=interval, receipt_sha256=receipt_sha256, producer_pid=pid,
                runner=runner, runner_sha256=runner_sha, sealed=sealed, entry=entry, review=review,
                measurement_store=receipt.get('initial_measurement_store'))


def producer_inputs(profile, *, sources, mode, receipt_sha256, consumer_pid, review=False, interval=None,
                    reuse=None, recorded=None):
    """Store-free preflight: pinned receipt, guard records, durable records, closed sealed file.

    Interval N >= 2 re-runs the runner's sealed-lineage gate from runner(N)'s own adopted(N-1)
    pin; runner(N) itself is pinned by the producer receipt this reader was given.
    """
    row = profile.record()
    number = F.interval_number(mode, interval)
    output, store_directory = F.mode_output(row, mode, interval), Path(row['store_directory'])
    receipt, receipt_pin = OR.read_json(RUN.ordinary(output/'run.json'), limit=RO.MAX_RECEIPT,
                                        pin=RUN._sha(receipt_sha256))
    if reuse is not None:
        reuse['record']['miss'] = reuse['record']['miss'] or REUSE.identity_miss(reuse, receipt.get('identities'))
        if reuse['record']['miss']:
            return None     # nothing more of the previous run is read; the caller reports the miss
    guard, guard_pin = OR.read_json(RUN.ordinary(output/'run.guard.json'), limit=RUN.MAX_CONFIG)
    control = RO._bounded_json(output/'run.guard-control.json')
    require(not (output/'run.guard-abort.json').exists() and not (output/'run.cancel').exists(),
            'producer was aborted or cancelled')
    pins = (receipt.get('runner_record'), receipt.get('sealed_awaiting_reader'))
    paths = (F.runner_record_path(store_directory, number), F.sealed_record_path(store_directory, number))
    records = []
    for path, pin, schema in zip(paths, pins, (F.RUNNER_RECORD_SCHEMA, F.SEALED_SCHEMA), strict=True):
        value, digest = OR.read_json(RUN.ordinary(path), limit=RUN.MAX_CONFIG, pin=RUN._sha(pin['sha256']),
                                     canonical=F.canonical)
        require(value.get('schema') == schema, 'canonical '+schema+' record required: '+str(path))
        records.append((value, digest))
    (runner, runner_pin), (sealed, sealed_pin) = records
    root_runner = parent_widths = gate = None
    if number >= 2:
        gate = F.sealed_lineage(store_directory, number, runner.get('parent_adopted_sha256'),
                                interval_one=F.interval_one_route(profile) if number == 2 else None)
        root_runner, parent_widths = gate['root_runner'], gate['parent_verdict']['widths']
    elif mode == 'interval':
        root_runner = F.read_record(F.runner_record_path(store_directory, 0), schema=F.RUNNER_RECORD_SCHEMA)
        verdict = F.read_record(F.verdict_path(store_directory, 0), schema=F.VERDICT_SCHEMA)
        adopted = F.read_record(adopted_path(store_directory, 0), schema=ADOPTED_SCHEMA)
        require(verdict['status'] == F.READER_PASS['root'] and
                verdict['runner_record_sha256'] == sha256(F.canonical(root_runner)).hexdigest() and
                adopted['status'] == ADOPTED_STATUS and adopted['entry'] == verdict['entry'] and
                adopted['verdict_sha256'] == sha256(F.canonical(verdict)).hexdigest(),
                'interval 1 requires run A adopted after its own reader PASS')
        parent_widths = verdict['widths']
    member = RUN.ordinary(store_directory/sealed['entry']['filename'])
    require(member.parent == store_directory and not os.access(member, os.W_OK) and
            not any(Path(str(member)+suffix).exists() for suffix in ('-wal', '-journal', '-shm')),
            'pending sealed interval file must be read-only and closed')
    expected = validate_producer_receipt(receipt, profile=profile, receipt_sha256=receipt_pin, runner=runner,
        sealed=sealed, guard_receipt=guard, guard_control=control, consumer_pid=consumer_pid, mode=mode,
        root_runner=root_runner, review=review, interval=interval, lineage=gate,
        recorded=recorded,
        _runner_sha256=runner_pin)
    if parent_widths is not None:
        expected['parent_widths'] = parent_widths
    expected['gate_pins'] = dict(producer_receipt_sha256=receipt_pin, guard_receipt_sha256=guard_pin,
                                 runner_sha256=runner_pin, sealed_sha256=sealed_pin)
    return expected


def _producer_inputs_retry(profile, **kwargs):
    """Retry the complete unchanged bounded, store-free producer preflight."""
    return OG._retry_sharing(lambda: producer_inputs(profile, **kwargs), 'producer input records')


def _reader_options(profile, *, mode, interval, producer_receipt_sha256, review, overlap_spec,
                    fallback, fallback_claim_sha256):
    if overlap_spec is not None:
        overlap_spec = OR.decode_spec(overlap_spec) if type(overlap_spec) is str else OR.validate_spec(overlap_spec)
        require(producer_receipt_sha256 is None and review is False and not fallback,
                'overlap reader defers its producer pin and cannot review or fall back')
        require(overlap_spec['attempt'] == str(Path(profile.record()['output_directory']).resolve()) and
                overlap_spec['stage'] == mode and overlap_spec['interval'] == F.interval_number(mode, interval) and
                overlap_spec['profile_sha256'] == profile.sha256,
                'overlap specification differs from this profile, attempt or stage')
    else:
        require(RO._digest(producer_receipt_sha256), 'normal reader requires an exact producer receipt pin')
    return overlap_spec


def records_only(mode, review, runner):
    """Unit A: which core reads this producer. A non-review interval whose runner record carries widths, or a
    root (a fresh root is native, Workflow.create); anything else runs the full core."""
    return not review and (mode == 'root' or 'widths' in runner)


def _records_only(CRS, *, catalog, scope, producer, mode, record, save, checks, guard):
    """Unit A's records-only core (A-2 steps 2-6): open-pending hashes the sealed file; the interval takes the
    producer's width table, the root scans its two native records; then the width gate."""
    from atlas_tectonics._private.codecs import interval_store_set as IS
    from atlas_tectonics._private.integration import width_gate as WG
    from atlas_tectonics._private.codecs.compact_contracts import SegmentRef
    entry, runner, sealed, root = producer['entry'], producer['runner'], producer['sealed'], producer['root']
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
        F._store_configuration(store)
        record.update(view_digest=view.catalog_digest, accepted_catalog_digest=view.accepted_catalog_digest)
        checks['pending_file_verified'] = True
        guard.phase('records-only-widths')
        if mode == 'root':
            head = store.metadata(root['root_key'])
            state = head['exterior_state']
            table = WG.WidthTable(producer['interval'])
            record['root_record_identities'] = _native_records(store, head['key'], state['record_blobs'],
                                                               budget=scope.run_budget, table=table)
            checks['root_record_identities'] = True
        else:
            table = WG.WidthTable.from_wire(runner['widths'])
            checks['widths_adopted'] = True
        record['widths'] = table.wire()
        checks['widths_recorded'] = True
        if mode == 'interval':
            record['width_gate'] = (
                WG.gate(WG.WidthTable.from_wire(producer['parent_widths']), table)
                if producer['interval'] == 1 else
                WG.gate_next(WG.WidthTable.from_wire(producer['parent_widths']), table))
            checks['width_gate_evaluated'] = True
        record['reader_core'] = 'records'
        save()


def _fallback_binding(row, mode, interval, pin):
    original = reader_output(row, mode, interval)
    target = reader_output(row, mode, interval, fallback=True)
    return OR.validate_fallback_claim(original/'sequential-fallback.claim.json', pin=pin,
                                      original=original, directory=target, receipt_limit=RO.MAX_RECEIPT)


def validate_fresh_lineage(*, root, head, observed, parent_interval=0):
    """Parent -> one successor: exact clocks, interval, partition and funding.

    ``root`` is the parent's metadata: run A's root, or adopted interval ``parent_interval`` (item 21).
    """
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
    parent = ({'root_is_parent': True} if parent_interval == 0 else
              {'parent_is_adopted_head': True, 'parent_interval': parent_interval})
    return {**parent, 'exactly_one_added_interval': True, 'exact_endpoint_clocks_identical': True,
            'funding_unchanged': True, 'interval_id': observed['interval_id']}


def _successor(workflow, store, producer, *, D, W):
    completed, root, advanced = producer['completed_endpoint'], producer['root'], producer['advanced_endpoint']
    head = dict(workflow._head)
    root_key, parent_key, number = root['root_key'], producer['parent_key'], producer['interval']
    root_metadata, parent_metadata = store.metadata(root_key), store.metadata(parent_key)
    require(type(parent_metadata) is dict and parent_metadata.get('key') == parent_key and
            head.get('key') == completed['head_key'] == advanced['head'] and head.get('kind') == 'successor' and
            head.get('key') == W.workflow_key('successor', parent_key) and head.get('parent_key') == parent_key and
            head.get('parent_digest') == W.digest(parent_metadata) and head.get('sequence') == number and
            root_metadata == completed['root_metadata'] and workflow.inspect() == advanced and
            store.metadata(W.workflow_key('successor', head['key'])) is None,
            'independently reopened successor identity differs')
    state, exterior = workflow.state, workflow.exterior_state
    found = {'collar_result_id': state.result_id, 'native_result_id': state.native_state.result_id,
             'exterior_state_id': exterior.state_id, 'source_audit_id': workflow.source_audit.result_id,
             'joined_heat_id': head['exterior_advance']['joined_heat_id']}
    groups = RO.endpoint_array_records(D, workflow)
    del groups
    lineage = validate_fresh_lineage(root=parent_metadata, head=head, observed=RO.observed_lineage(workflow),
                                     parent_interval=number-1)
    return {'endpoint': found, 'lineage': lineage}


def _read_store(row, reuse):
    """The store this reader reads: under reuse, the previous run's."""
    return Path((row if reuse is None else reuse['previous'].record())['store_directory'])


def _reader_status(errors, mode, reuse):
    return ('FAILED' if errors else WORKLOAD_STATUS[mode] if reuse is None else
            REUSE.MISS_STATUS if reuse['record']['miss'] else REUSE.STATUS)


def _missed(reuse):
    return reuse is not None and reuse['record']['miss'] is not None


def reopen_fresh_interval(profile, *, sources, guard, record, save, producer, mode, start_gate=None,
                          overlap_spec=None, fallback=False, fallback_claim_sha256=None, scope_state=None,
                          reuse=None):
    """Fresh-process reader core; call under the live guard. ``start_gate``: the
    launcher's start_gate decision (encoded), admitted again here against this process's free memory."""
    require(type(profile) is F.FreshProfile and type(sources) is F.FreshSources and sources.profile is profile,
            'sources of this profile required')
    if type(overlap_spec) is str:
        overlap_spec = OR.decode_spec(overlap_spec)
    number = overlap_spec['interval'] if overlap_spec is not None else producer['interval']
    overlap_spec = _reader_options(profile, mode=mode, interval=_explicit(number),
        producer_receipt_sha256=None if producer is None else producer['receipt_sha256'],
        review=False if producer is None else producer['review'], overlap_spec=overlap_spec,
        fallback=fallback, fallback_claim_sha256=fallback_claim_sha256)
    row = profile.record()
    # Unit A: a sequential reader of a producer records_only accepts reads the records only.
    records = overlap_spec is None and records_only(mode, producer['review'], producer['runner'])
    bound = {name: sources.module(name) for name in
             (('compact_restart_store',) if records else (F.DRIVER, *F.FRESH_MODULES))}
    CRS = bound['compact_restart_store']
    if not records:
        FRESH, D = bound[F.DRIVER], bound['heat_interval_r9_spec']
    from atlas_tectonics._private.codecs import interval_store_set as IS
    from atlas_tectonics._private.integration import width_gate as WG
    from atlas_tectonics._private.integration import workflow_transfer as W
    from atlas_tectonics.integration.resources import WorkBudget
    from atlas_tectonics.integration.reuse import execution_identity
    from atlas_tectonics._private.codecs.compact_contracts import SegmentRef
    if not records:
        m = F.composition(sources)
    record.update(RUN.interpreter_gate())
    output = guard.output.parent
    import psutil
    available = MONITOR.free_memory()
    admitted = SG.child_admit(start_gate, available)
    selected_limits = SG.guard_limits(admitted)
    guard.budget = budget = WorkBudget(selected_limits['logical_budget_bytes'], max_predicate_work_units=1 << 44)
    RUN._guard_boundary(sources, guard, budget, limits=selected_limits)
    check = lambda: guard.check(force=True)
    record.update(guard_limits=selected_limits, start_gate=admitted,
                  memory_at_start={'available_bytes': available},
                  launch_environment={name: os.environ.get(name) for name in sorted(RUN.LAUNCH_ENV)},
                  production_acceptance=False)
    catalog = _read_store(row, reuse)/F.CATALOG
    review = False if producer is None else producer['review']
    checks = dict.fromkeys(RECORDS_CHECKS[mode] if records else REVIEW_CHECKS if review else CHECKS[mode], False)
    record['review_only'] = review
    scope = RUN.new_retained_scope(budget)
    if scope_state is not None:
        scope_state['scope'] = scope
    try:
        if records:
            _records_only(CRS, catalog=catalog, scope=scope, producer=producer, mode=mode, record=record, save=save,
                          checks=checks, guard=guard)
            record['independent_checks'] = checks
            return budget
        with ExitStack() as contexts:
            # diag22: CollarWorkflow's cold restore resolves the private derived bridge in this scope.
            from atlas_tectonics._private.integration.heat import cold_bridge as COLD_BRIDGE
            contexts.enter_context(COLD_BRIDGE.selected())
            guard.phase('rebuild-fresh-admission')
            then = row if reuse is None else reuse['previous'].record()     # as _read_store has it (:675)
            source = F.mode_output(then, mode, _explicit(number))
            binding = F.measurement_composition(profile, execution_identity=execution_identity('scipy'),
                                                interpreter_seed=record['interpreter_seed'])
            seeded = {}

            def seed():     # N6 calls it at the point of use: after the fixture and partition, before the store opens
                if overlap_spec is None:
                    stored = producer['measurement_store']
                else:       # the producer is still running
                    guard.phase('wait-for-producer-measurement-store')
                    stored = _published_store(source, overlap_spec, check)
                seeded.update(seed_from_producer(stored, source, output, check, binding=binding,
                                                 previous=reuse is not None))
                record['initial_measurements'] = seeded
                save()
            requested = 0                                   # nothing is measured, so no pool
            admission = FRESH.admission(m, budget=budget, artifacts=output, phase=guard.phase, initial_workers=requested,
                before_measurements=seed,
                measurements=lambda statistics, bounds: seeded.update(measured=statistics['snapshots']-seeded['seed_snapshots']))
            if overlap_spec is not None:
                a, producer = contexts.enter_context(OR.admitted_before_gate(
                    admission=admission, spec=overlap_spec, record=record, save=save, guard=guard,
                    producer_inputs=lambda pin: _producer_inputs_retry(profile, sources=sources, mode=mode,
                        receipt_sha256=pin, consumer_pid=os.getpid(), review=False, interval=_explicit(number)),
                    memory_admit=lambda free: SG.child_admit(start_gate, free),
                    available_memory=MONITOR.free_memory, waiter=guard.identity))
            else:
                a = contexts.enter_context(admission)
                # Comparable normal readers use the same admission ordering and
                # repeat the unchanged prediction immediately before pending access.
                guard.check(force=True)
                record['memory_before_open_pending'] = SG.child_admit(start_gate, MONITOR.free_memory())
                save()
            # o2 C2: the admission route actually used (never keyed initial_parallel: chain driver :881).
            report = a.initial_parallel
            admission_record = record['initial_admission'] = {'requested_workers': requested,
                'route': 'parallel' if report and report.get('opened') and report.get('adopted', 0) > 0 else 'serial',
                'report': None if report is None else {k: (v if v is None or isinstance(v, (bool, int, float, str))
                    else str(v)[:512]) for k in INITIAL_ADMISSION_KEYS for v in (report.get(k),)}}
            # o2 C3: the pass's workers must be gone now, not only at the close census.
            live = []
            for c in psutil.Process().children(recursive=True):
                try:
                    if c.name().lower() != 'conhost.exe':
                        live.append(c.pid)
                except psutil.NoSuchProcess:
                    pass    # exited during the listing: gone, which is what this check asks
            admission_record['workers_alive_after_close'] = 0
            save()
            entry, runner, sealed, root = producer['entry'], producer['runner'], producer['sealed'], producer['root']
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
                F._store_configuration(store)
                record.update(view_digest=view.catalog_digest, accepted_catalog_digest=view.accepted_catalog_digest)
                checks['pending_file_verified'] = True
                token = store.change_token()
                require(FRESH.preparation_ids(a.case, a.owner) == root['preparation_ids'],
                        'independently rebuilt runtime, plans or owner differ from run A')
                checks['source_bound_admission'] = True
                from atlas_tectonics._private.codecs import compact_contracts
                compact_contracts.open_proofs = True    # the full core's open proves; never off (N-2)
                guard.phase('independent-open-fresh-workflow')
                # One store-set read batch for the whole stage: one file check before, one after.
                with WG.collect_proofs(store) as proofs, view.read_batch(), m.Workflow.open(
                        store, runner['workflow_id'], a.case['collar'], a.case['owner'], a.case['funding'],
                        budget=budget, exterior_owner=a.owner) as workflow:
                    found = FRESH.published_root(workflow, store, a)
                    checks['root_identity'] = True
                    table = WG.WidthTable(producer['interval'])
                    guard.phase('independent-record-identities-and-widths')
                    if mode == 'root':
                        record['root_record_identities'] = root_record_identities(workflow, table)
                        checks['root_record_identities'] = True
                        evidence = {'root': found['inspect']}
                    else:
                        evidence = _successor(workflow, store, producer, D=D, W=W)
                        checks.update(successor_identity=True, state_identities=True,
                                      all_six_field_groups_identical=True, fresh_lineage=True)
                        identities = successor_record_identities(workflow, table, proofs)
                        record['record_identities'] = identities
                        if review:
                            # The refused pre-seal left no production identities to compare with:
                            # these are recorded for the diagnosis, which decides alone.
                            checks['compact_record_identities_recorded'] = True
                        else:
                            checks['compact_record_identities_identical'] = True
                    record['widths'] = table.wire()
                    checks['widths_recorded'] = True
                    if mode == 'interval':
                        # Interval 1 keeps gate() and its v1 record; N >= 2 gates N+1 from N-1's widths.
                        record['width_gate'] = (
                            WG.gate(WG.WidthTable.from_wire(producer['parent_widths']), table)
                            if producer['interval'] == 1 else
                            WG.gate_next(WG.WidthTable.from_wire(producer['parent_widths']), table))
                        checks['width_gate_evaluated'] = True
                    record['evidence'] = evidence
                    save()
                    del workflow
                require(store.change_token() == token, 'independent reopen wrote to the pending view')
                checks['store_unchanged'] = True
                record['compact_store_statistics'] = store.statistics()
        record['independent_checks'] = checks
        return budget
    finally:
        active_error = sys.exception()
        record['retained_scope'] = {'before_close': RO.retained_accounting(scope)}
        record['retained_producer'] = {'before_close': RO.producer_accounting(scope)}
        # The workload owns the scope after an exception so it can first drop
        # the traceback's borrowed views, then close the same scope for real.
        if scope_state is None:  # a caller that passed scope_state closes the scope, after this frame is gone
            try:
                scope.close()
                record['retained_scope']['after_close'] = RO.retained_accounting(scope)
                record['retained_producer']['after_close'] = RO.producer_accounting(scope)
                require(record['retained_scope']['after_close']['retained_bytes'] == 0,
                        'fresh reader retained owners after scope closure')
                checks['retained_scope_released'] = True
            except BaseException as release_error:
                if active_error is None:
                    raise
                active_error.add_note('Retained scope finalisation also failed: '+repr(release_error))


def _explicit(number):
    """The --interval argument naming ``number``: none for the root and interval 1."""
    return None if number <= 1 else number


@contextmanager
def _reader_admission(profile, reuse_previous, previous=None):
    stores = [profile.record()['store_directory']]
    if reuse_previous is not None:
        if previous is None:
            previous = F.FreshProfile.read(reuse_previous[0], reuse_previous[1])
        stores.append(previous.record()['store_directory'])
    with admitted(stores):
        yield previous


def _protected_reader(function):
    @wraps(function)
    def protected(profile, *args, **kwargs):
        with _reader_admission(profile, kwargs.get('reuse_previous'), kwargs.get('_previous')) as previous:
            return function(profile, *args, **dict(kwargs, _previous=previous))
    return protected


@_protected_reader
def command(profile, python, *, mode, producer_receipt_sha256, review=False, start_gate=None, interval=None,
            overlap_spec=None, fallback=False, fallback_claim_sha256=None, reuse_previous=None,
            record_failed_prior=False, _previous=None, run_profile=frozenset()):
    """Store-free preflight and the guarded argv; never launches. ``start_gate`` goes last."""
    sources = F.FreshSources(profile)
    recorded = _recording(sources, record_failed_prior)
    reuse = None if reuse_previous is None else REUSE.plan(profile, sources, *reuse_previous, previous=_previous)
    if _missed(reuse):
        return REUSE.miss_exit(reuse)
    overlap_spec = _reader_options(profile, mode=mode, interval=interval,
        producer_receipt_sha256=producer_receipt_sha256, review=review, overlap_spec=overlap_spec,
        fallback=fallback, fallback_claim_sha256=fallback_claim_sha256)
    if overlap_spec is None:
        _producer_inputs_retry(profile if reuse is None else reuse['previous'], sources=sources, mode=mode,
                               receipt_sha256=producer_receipt_sha256, consumer_pid=os.getpid(), review=review,
                               interval=interval, reuse=reuse, recorded=recorded)
        if _missed(reuse):
            return REUSE.miss_exit(reuse)
    row = profile.record()
    if fallback:
        _fallback_binding(row, mode, interval, fallback_claim_sha256)
    output = reader_output(row, mode, interval, fallback=fallback)
    RUN.ordinary(output.parent, directory=True)
    own = Path(__file__).resolve()
    guard = sources.path(row['modules']['private_heat_continuation_guard_r3'])
    python = str(RUN.ordinary(python))
    return [python, '-B', str(guard), '--launch', '--output', str(output/'reopen.json'), '--diagnostic-reader-integrity', '--',
            python, '-B', '-s', '-P', str(own), '--workload', '--profile', str(profile.path), '--profile-sha256', profile.sha256,
            '--mode', mode,
            *(['--producer-receipt-sha256', producer_receipt_sha256] if overlap_spec is None else
              ['--overlap-spec', OR.encode_spec(overlap_spec)]), *(['--review'] if review else []),
            *(['--reader-fallback', '--fallback-claim-sha256', fallback_claim_sha256] if fallback else []),
            *(['--interval', str(interval)] if interval is not None else []),
            *([] if reuse_previous is None else
              ['--reuse-previous-run', str(reuse_previous[0]), '--reuse-previous-run-sha256', reuse_previous[1],
               *(['--reuse-identity-override'] if reuse_previous[2] else [])]),
            *(['--record-failed-prior'] if record_failed_prior else []),
            *profiling.profile_words(run_profile.intersection(('stacks', 'tree'))),
            *([SG.ARGUMENT, SG.encode(start_gate)] if start_gate is not None else [])]


def _reader_error_detail(error):
    """Capture bounded source locations without retaining traceback frames."""
    result = F._error(error)
    trace = F.first_raised(error).__traceback__
    selected = []
    omitted = 0
    while trace is not None:
        code = trace.tb_frame.f_code
        if 'atlas_tectonics' in code.co_filename.replace('\\', '/'):
            if len(selected) == 32:
                selected.pop(0)
                omitted += 1
            selected.append({'file': code.co_filename, 'function': code.co_name, 'line': trace.tb_lineno})
        trace = trace.tb_next
    result['selected_frames'] = selected
    result['selected_frames_omitted'] = omitted
    return result


def _reader_error(error):
    """Never turn a reporting failure into a successful reader receipt."""
    try:
        return _reader_error_detail(error)
    except BaseException as reporting_error:
        return {'type': type(error).__name__, 'message': 'Error details unavailable',
                'reporting_error': type(reporting_error).__name__}


@_protected_reader
def _workload(profile, *, mode, producer_receipt_sha256, review=False, start_gate=None, interval=None,
              overlap_spec=None, fallback=False, fallback_claim_sha256=None, reuse_previous=None,
              record_failed_prior=False, _previous=None):
    sources = F.FreshSources(profile)
    recorded = _recording(sources, record_failed_prior)
    reuse = None if reuse_previous is None else REUSE.plan(profile, sources, *reuse_previous, previous=_previous)
    if _missed(reuse):
        return REUSE.miss_exit(reuse)
    overlap_spec = _reader_options(profile, mode=mode, interval=interval,
        producer_receipt_sha256=producer_receipt_sha256, review=review, overlap_spec=overlap_spec,
        fallback=fallback, fallback_claim_sha256=fallback_claim_sha256)
    number = F.interval_number(mode, interval)
    output = reader_output(profile.record(), mode, interval, fallback=fallback)/'reopen.json'
    record: dict = {'schema': READER_SCHEMA, 'status': 'STARTED', 'pid': os.getpid(), 'profile_sha256': profile.sha256,
                    'producer_receipt_sha256': producer_receipt_sha256, 'mode': mode, 'errors': [],
                    'production_acceptance': False, 'independent_process_reopen': True, 'review_only': review,
                    **({'interval': number} if number >= 2 else {}),
                    **({} if reuse is None else {'reuse_previous_run': reuse['record']})}
    guard = budget = None
    scope_state = {}
    # The supervisor has already claimed sidecars. Receipt creation is exclusive.
    with output.open('x', encoding='utf8') as stream:
        json.dump(record, stream)
    G = sources.module('private_heat_continuation_guard_r3')
    save = lambda: G._write(output, record)
    try:
        guard = G.ContinuationGuard(output, record, save, **SG.child_limits(start_gate))
        context = json.loads(os.environ[G.ENV])
        record['reader_guard_binding'] = {'job_name': context['job_name'], 'nonce': guard.nonce,
                                          'parent': guard.identity}
        if fallback:
            evidence = _fallback_binding(profile.record(), mode, interval, fallback_claim_sha256)
            require(evidence['profile_sha256'] == profile.sha256 and evidence['stage'] == mode and
                    evidence['interval'] == number, 'fallback failure belongs to another profile or stage')
            record.update(reader_fallback=True, fallback_claim_sha256=fallback_claim_sha256,
                          fallback_evidence=evidence)
            save()
        producer = (None if overlap_spec is not None else
                    _producer_inputs_retry(profile if reuse is None else reuse['previous'], sources=sources,
                        mode=mode, receipt_sha256=producer_receipt_sha256, consumer_pid=os.getpid(),
                        review=review, interval=interval, reuse=reuse, recorded=recorded))
        if _missed(reuse):   # met only when run without its command's preflight; the finally records the miss
            return REUSE.miss_exit(reuse)
        if recorded:  # what this reader accepted of how its producer ended
            record['recorded'] = recorded
            save()
        budget = reopen_fresh_interval(profile, sources=sources, guard=guard, record=record, save=save,
            producer=producer, mode=mode, start_gate=start_gate, overlap_spec=overlap_spec,
            fallback=fallback, fallback_claim_sha256=fallback_claim_sha256, scope_state=scope_state,
            reuse=reuse)
        del producer
        record['status'] = 'VERIFYING_FINALISATION'
    except BaseException as error:  # noqa: BLE001 - every failure, guard aborts included, is recorded
        record['status'] = 'FAILED'
        record['errors'].append(_reader_error(error))
        reason = OR.failure_reason(error)
        if reason is not None and overlap_spec is not None:
            record['overlap_failure_reason'] = reason
        if guard is not None and guard.budget is not None:
            record['logical_budget_at_failure'] = guard.budget.statistics()
        save()
    finally:
        # Every post-work failure is retained; none may skip an acquired guard's close.
        try:
            gc.collect()
            scope = scope_state.pop('scope', None)
            if scope is not None:
                try:
                    scope.close()
                    record['retained_scope']['after_close'] = RO.retained_accounting(scope)
                    record['retained_producer']['after_close'] = RO.producer_accounting(scope)
                    require(record['retained_scope']['after_close']['retained_bytes'] == 0,
                            'fresh reader retained owners after scope closure')
                    if 'independent_checks' in record:  # there only when the reader's work passed (RFR:809)
                        record['independent_checks']['retained_scope_released'] = True
                except BaseException as close_error:  # retain primary and cleanup failures separately
                    record['errors'].append(_reader_error(close_error))
                finally:
                    del scope
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
            if guard is not None:
                guard.check(force=True)
        except BaseException as error:  # noqa: BLE001 - retain accounting and verification failures
            record['errors'].append(_reader_error(error))
        finally:
            if guard is not None:
                try:
                    receipt = guard.close()
                    record['reader_process_proof'] = receipt['diagnostic_reader_close']
                    record['remaining_children'] = []
                except BaseException as error:  # noqa: BLE001 - preserve close and earlier failures
                    record['errors'].append(_reader_error(error))
            record['status'] = _reader_status(record['errors'], mode, reuse)
            save()

    return 0 if not record['errors'] else 1


def validate_reopen_receipt(reopen, *, guard_receipt, guard_control, profile, producer, mode, recorded=None):
    """Pure closed checks of the guarded reader result after its guardian exited."""
    review = producer['review']
    require(type(reopen) is dict and reopen.get('schema') == READER_SCHEMA and
            type(reopen.get('errors')) is list and reopen.get('production_acceptance') is False and
            reopen.get('independent_process_reopen') is True and reopen.get('mode') == mode and
            reopen.get('profile_sha256') == profile.sha256 and reopen.get('review_only') is review and
            reopen.get('producer_receipt_sha256') == producer['receipt_sha256'] and
            reopen.get('remaining_children') == [] and
            (reopen.get('interval') == producer['interval'] if producer['interval'] >= 2 else 'interval' not in reopen),
            'successful independent reader result of this producer, profile and mode required')
    # how the reader ended; refused unless the run records
    RO.prior(reopen.get('status') == WORKLOAD_STATUS[mode], f"reader status {reopen.get('status')!r}", recorded)
    RO.prior(reopen['errors'] == [], 'reader errors: '+_said(reopen['errors']), recorded)
    RO.prior(reopen.get('final_reserved_bytes') == 0,
             f"reader final_reserved_bytes {reopen.get('final_reserved_bytes')!r}", recorded)
    pid = reopen.get('pid')
    checks = reopen.get('independent_checks')
    core = reopen.get('reader_core', 'full')
    false = sorted(name for name, value in checks.items() if value is not True)
    RO.prior(not false, 'independent reopen checks not passed: '+', '.join(false), recorded)
    if mode == 'root':
        pass
    else:
        if review:
            RO.canonical_record_identities(reopen.get('record_identities'), successor=True)
        elif core == 'full':
            require(reopen.get('record_identities') == producer['runner']['record_identities'],
                    'independent compact logical records differ')
        gate, number = reopen.get('width_gate'), producer['interval']
        require(type(gate) is dict and type(gate.get('passed')) is bool and
                (gate.get('schema') == 'atlas.exact-width-gate.v1' if number == 1 else
                 gate.get('schema') == 'atlas.exact-width-gate.v2' and gate.get('interval') == number and
                 gate.get('next_interval') == number+1),
                'evaluated width gate before the next interval required')
    retained = reopen.get('retained_scope')
    for value in retained.values():
        RO.validate_retained_accounting(value, pid=pid)
    # review S-4: the bytes left after the close and the agreement of the two counts are how the reader ended
    RO.prior(retained['after_close'].get('retained_bytes') == 0,
             f"reader retained_bytes after close {retained['after_close'].get('retained_bytes')!r}", recorded)
    RO.prior(RO.retained_release_agrees(retained['before_close'], retained['after_close']),
             'independent compact retained scope release counts disagree', recorded)
    import ctypes
    directory = ctypes.create_unicode_buffer(32768)
    require(ctypes.windll.kernel32.GetSystemDirectoryW(directory, len(directory)) > 0,
            'Windows system directory unavailable')
    host_image = os.path.normcase(os.path.join(directory.value, 'conhost.exe'))
    evidence = reopen.get('reader_process_proof')
    def identity(value):
        return (type(value) is dict and set(value) == {'pid', 'created_ticks'} and
                all(type(value[key]) is int and value[key] > 0 for key in value))
    parent, host = evidence['parent'], evidence['console_host']
    close_proof = guard_receipt['diagnostic_reader_close']
    require(identity(parent) and identity(close_proof['parent']) and
            identity(guard_receipt.get('parent')) and identity(guard_receipt.get('launcher')) and
            identity(guard_control.get('parent')) and
            parent == guard_receipt.get('parent') == guard_receipt.get('launcher') == guard_control.get('parent') and
            ((host is None and close_proof['console_host'] is None and evidence['image'] is None and evidence['argv'] is None) or
             (identity(host) and identity(close_proof['console_host']) and parent['pid'] != host['pid'] and
              evidence['image'] == host_image and evidence['argv'] == [host_image, '0x4'])),
            'reader process roles or identities differ')
    binding = reopen.get('reader_guard_binding')
    require(type(binding) is dict and identity(binding.get('parent')) and
            binding == {'job_name': guard_receipt.get('job_name'),
            'nonce': guard_receipt.get('nonce'), 'parent': parent} and
            type(guard_receipt.get('job_name')) is str and bool(guard_receipt['job_name']),
            'reader launch context differs from guardian')


def _recording(sources, asked):
    """The list that recorded tests go to, or None. Only a diagnostic tree records."""
    if not asked:
        return None
    require(F.diagnostic_tree(sources), '--record-failed-prior is for diagnostic trees only')
    return []


@_protected_reader
def finalise(profile, *, mode, producer_receipt_sha256, reopen_receipt_sha256, guard_receipt_sha256,
             guard_control_sha256, review=False, interval=None,
             overlap_gate_sha256=None, fallback=False, fallback_claim_sha256=None, reuse_previous=None,
             record_failed_prior=False, _previous=None):
    """Store-free acceptance of a completed guarded reader; the exclusive verdict on PASS.

    Under reuse_previous the records are the previous tree's and are tested against its profile;
    the sources are this tree's.

    A review-only verdict says so: it is evidence for the review, never an adoption by itself.
    """
    sources = F.FreshSources(profile)
    _reader_options(profile, mode=mode, interval=interval, producer_receipt_sha256=producer_receipt_sha256,
        review=review, overlap_spec=None, fallback=fallback, fallback_claim_sha256=fallback_claim_sha256)
    row = profile.record()
    output = reader_output(row, mode, interval, fallback=fallback)
    final = output/'reopen-final.json'
    errors, verdict_sha256, gate, reuse, recorded, core = [], None, None, None, None, None
    try:
        recorded = _recording(sources, record_failed_prior)
        reuse = None if reuse_previous is None else REUSE.plan(profile, sources, *reuse_previous, previous=_previous)
        if _missed(reuse):
            return REUSE.miss_exit(reuse)
        then = profile if reuse is None else reuse['previous']
        reopen, _ = OR.read_json(output/'reopen.json', pin=reopen_receipt_sha256, limit=RO.MAX_RECEIPT)
        core = reopen.get('reader_core', 'full') if type(reopen) is dict else None
        producer = _producer_inputs_retry(then, sources=sources, mode=mode, receipt_sha256=producer_receipt_sha256,
                                          consumer_pid=os.getpid(), review=review, interval=interval,
                                          reuse=reuse, recorded=recorded)
        if _missed(reuse):
            return REUSE.miss_exit(reuse)
        require(not (output/'reopen.guard-abort.json').exists() and not (output/'reopen.cancel').exists(),
                'reader was aborted or cancelled')
        reader_guard, _ = OR.read_json(output/'reopen.guard.json', pin=guard_receipt_sha256)
        reader_control, _ = OR.read_json(output/'reopen.guard-control.json', pin=guard_control_sha256)
        validate_reopen_receipt(reopen, guard_receipt=reader_guard,
            guard_control=reader_control, profile=then,
            producer=producer, mode=mode, recorded=recorded)
        overlap_fields = {'overlap_gate', 'overlap_wait_spec', 'admitted_ahead', 'gate_wait_seconds'}
        published = OR.gate_path(str(Path(row['output_directory']).resolve()), mode, producer['interval'])
        if fallback:
            require(not overlap_fields.intersection(reopen) and reopen.get('reader_fallback') is True and
                    reopen.get('fallback_claim_sha256') == fallback_claim_sha256,
                    'fallback cannot inherit a failed overlap marker')
            evidence = _fallback_binding(row, mode, interval, fallback_claim_sha256)
            require(reopen.get('fallback_evidence') == evidence and evidence['profile_sha256'] == profile.sha256 and
                    evidence['stage'] == mode and evidence['interval'] == producer['interval'],
                    'fallback claim or original failed-reader evidence changed')
        else:
            require('reader_fallback' not in reopen and 'fallback_claim_sha256' not in reopen and
                    'fallback_evidence' not in reopen, 'ordinary reader cannot carry fallback authority')
            if overlap_fields.intersection(reopen) or published.exists() or overlap_gate_sha256 is not None:
                require(RO._digest(overlap_gate_sha256) and not review,
                        'published overlap requires the explicit complete gate pin and receipt binding')
                expected = {'attempt': str(Path(row['output_directory']).resolve()), 'stage': mode,
                            'interval': producer['interval'], 'profile_sha256': profile.sha256}
                OR.validate_finalise(reopen, expected=expected, path=published, pin=overlap_gate_sha256,
                    producer_pins=producer['gate_pins'],
                    waiter=reader_guard['parent'], memory_validator=SG.admit)
        gate = reopen.get('width_gate')
        verdict = {'schema': F.VERDICT_SCHEMA, 'status': F.READER_PASS[mode], 'interval': producer['interval'],
                   'entry': producer['entry'], 'runner_record_sha256': producer['runner_sha256'],
                   'view_digest': reopen['view_digest'], 'accepted_catalog_digest': reopen['accepted_catalog_digest'],
                   'producer_receipt_sha256': producer_receipt_sha256, 'reopen_receipt_sha256': reopen_receipt_sha256,
                   'reader_pid': reopen['pid'], 'widths': reopen['widths'], 'reader_core': core,
                   **({} if gate is None else {'width_gate': gate}),
                   **({'review_only': True, 'preseal_refused': producer['runner']['preseal_refused'],
                       'record_identities': reopen['record_identities']} if review else {})}
        verdict_file = F.verdict_path(Path(row['store_directory']), producer['interval'])
        verdict_raw = F.canonical(verdict)
        if os.path.lexists(verdict_file) and RUN.ordinary(verdict_file).read_bytes() == verdict_raw:   # S-3: stopped
            verdict_sha256 = sha256(verdict_raw).hexdigest()     # before its final record: the same verdict, taken
        else:
            verdict_sha256 = F.write_durable(verdict_file, verdict)     # other bytes refuse, as before
    except Exception as error:  # noqa: BLE001 - the final record carries every refusal
        errors.append(F._error(error))
    result = {'schema': FINAL_SCHEMA, 'status': 'FAILED' if errors else F.READER_PASS[mode], 'mode': mode,
              'profile_sha256': profile.sha256, 'producer_receipt_sha256': producer_receipt_sha256,
              'reopen_receipt_sha256': reopen_receipt_sha256, 'verdict_sha256': verdict_sha256,
              'width_gate_passed': None if gate is None else gate['passed'], 'errors': errors,
              **({} if core is None else {'reader_core': core}),
              **({'overlap_gate_sha256': overlap_gate_sha256} if overlap_gate_sha256 is not None else {}),
              **({'reader_fallback': True, 'fallback_claim_sha256': fallback_claim_sha256} if fallback else {}),
              **({'recorded': recorded} if recorded else {}),
              **({} if reuse is None else {'reuse_previous_run': reuse['record']}),
              'production_acceptance': False, 'independent_process_reopen': not errors}
    with final.open('x', encoding='utf8') as stream:
        json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write('\n')
    print(json.dumps({'status': result['status'], 'verdict_sha256': verdict_sha256,
                      'width_gate_passed': result['width_gate_passed'], 'errors': errors}), flush=True)
    return 0 if not errors else 1


def adoption_inputs(store_directory, interval, verdict_sha256, approval_sha256=None, *, location=None):
    """The records adopt_and_promote may use, and nothing else; refuses any inconsistency."""
    if location is None:
        location = lambda path: path
    verdict = F.read_record(location(F.verdict_path(store_directory, interval)), schema=F.VERDICT_SCHEMA,
                            expected_sha256=verdict_sha256)
    runner = F.read_record(location(F.runner_record_path(store_directory, interval)), schema=F.RUNNER_RECORD_SCHEMA,
                           expected_sha256=verdict['runner_record_sha256'])
    sealed = F.read_record(location(F.sealed_record_path(store_directory, interval)), schema=F.SEALED_SCHEMA)
    entry = sealed['entry']
    mode = 'root' if interval == 0 else 'interval'
    require(verdict['status'] == F.READER_PASS[mode] and verdict['interval'] == interval == entry['interval'] and
            verdict['entry'] == entry and sealed['runner_record_sha256'] == verdict['runner_record_sha256'] and
            runner['head'] == entry['head'] and runner['producer_identity'] == entry['producer_identity'] and
            runner['runtime_identity'] == entry['runtime_identity'] and RO._digest(verdict['view_digest']),
            'adoption requires one consistent runner record, sealed record and reader PASS')
    review = bool(runner.get('review_only')) or bool(verdict.get('review_only'))
    if review:
        review_approval(store_directory, interval, approval_sha256, entry=entry, verdict_sha256=verdict_sha256)
    return verdict, runner, sealed


def park_retained_interval(store_directory, aside, interval, *, pins, parent_adopted_pin, scope,
                           assert_exclusive, save_disposition, crash_hook=None):
    """Park one accepted catalog tail in a home owned exclusively by the caller."""
    from atlas_tectonics._private.codecs import interval_catalog as IC
    from atlas_tectonics._private.codecs.interval_store_set import (_immutable, catalog_transient_charge,
                                                            pending_view_digest)
    directory = IC.safe_path(store_directory)
    archive = IC.safe_path(aside)
    require(archive.is_dir() and archive != directory and not archive.is_relative_to(directory),
            'protected output archive must be outside the active store')
    assert_exclusive()
    live = IC.safe_path(directory/F.CATALOG)
    saved_catalog = IC.safe_path(archive/F.CATALOG)

    def location(path):
        parked = archive/path.name
        active, retained = os.path.lexists(path), os.path.lexists(parked)
        require(active != retained, 'protected output is missing or has a conflicting owner: '+path.name)
        return IC.safe_path(path if active else parked, existing=True)

    verdict_path = F.verdict_path(directory, interval)
    runner_path = F.runner_record_path(directory, interval)
    seal_path = F.sealed_record_path(directory, interval)
    adopted_record_path = F.adopted_path(directory, interval)
    records = (verdict_path, runner_path, seal_path, adopted_record_path)
    require(set(pins) == {path.name for path in records}, 'exact protected interval record pins required')
    for path in records:
        RUN._sha(pins[path.name])
    adopted = F.read_record(location(adopted_record_path), schema=F.ADOPTED_SCHEMA,
                            expected_sha256=pins[adopted_record_path.name])
    verdict, _, sealed = adoption_inputs(directory, interval, pins[verdict_path.name],
        adopted.get('review_approval_sha256'), location=location)
    entry = sealed['entry']
    require(adopted['status'] == ADOPTED_STATUS and adopted['interval'] == interval and adopted['entry'] == entry
            and adopted['verdict_sha256'] == pins[verdict_path.name]
            and adopted['runner_record_sha256'] == pins[runner_path.name] == verdict['runner_record_sha256']
            and sha256(F.canonical(sealed)).hexdigest() == pins[seal_path.name],
            'protected interval outputs do not bind their original adoption')
    segment = IC.relative_file(directory, entry['filename'])
    original_segment = location(segment)
    segment_token = IC.file_token(original_segment, reject_sidecars=True)
    require(_immutable(original_segment) and RUN.file_hash(original_segment) == entry['file_sha256'],
            'protected interval seal differs from its accepted file')

    with IC.publication_lock(live):
        assert_exclusive()
        image = saved_catalog if saved_catalog.exists() else live
        size = IC.file_token(image)[2]
        with scope.run_budget.reserve(catalog_transient_charge(size), category='retained-catalog-transition'):
            raw, previous = IC._read_catalog_image(image, expected_size=size)
            require(previous == adopted['catalog_digest'] == adopted['catalog_sha256'],
                    'original catalog image differs from its adoption')
            catalog = IC.Catalog.from_bytes(raw)
            require(catalog.entries[-1].to_wire() == entry and catalog.generation == interval+1,
                    'protected interval must be the original catalog tail')
            prefix = None
            prefix_raw = None
            if interval:
                parent = F.read_record(F.adopted_path(directory, interval-1), schema=F.ADOPTED_SCHEMA,
                                       expected_sha256=RUN._sha(parent_adopted_pin))
                prefix_raw = IC.Catalog(catalog.workflow_id, interval, catalog.entries[:-1]).to_bytes()
                prefix = IC.digest(prefix_raw)
                require(parent['entry'] == catalog.entries[-2].to_wire() and
                        parent['catalog_digest'] == parent['catalog_sha256'] == prefix,
                        'authenticated prefix differs from its original adoption')
            else:
                require(parent_adopted_pin is None, 'pre-root transition cannot name a parent adoption')
            require(sealed['expected_catalog_digest'] == prefix and
                    verdict['view_digest'] == pending_view_digest(prefix, catalog.entries[-1]),
                    'protected tail was not read against the authenticated prefix')
            active = (previous if image == live else IC._read_catalog_image(live)[1] if live.exists() else None)
            require(active in (previous, prefix), 'active catalog is outside the pending protected transition')
            save_disposition({'interval': interval, 'before': previous, 'after': prefix,
                              'archive': str(archive), 'records': dict(pins), 'parent_adopted_sha256': parent_adopted_pin,
                              'interval_sha256': entry['file_sha256'], 'filename': entry['filename']})
            def stable_segment():
                assert_exclusive()
                require(IC.file_token(original_segment, reject_sidecars=True) == segment_token
                        and _immutable(original_segment), 'protected sealed file changed before publication')

            if active == previous:
                if prefix_raw is None:
                    require(not saved_catalog.exists(), 'conflicting archived original catalog')
                    stable_segment()
                    IC.durable_replace(live, saved_catalog)
                    if crash_hook:
                        crash_hook('catalog_replaced')
                else:
                    if not saved_catalog.exists():
                        temporary = saved_catalog.with_suffix('.tmp')
                        with temporary.open('wb') as stream:
                            stream.write(raw)
                            IC.flush_file(stream)
                        IC.durable_replace(temporary, saved_catalog)
                    IC._publish_checked_image(live, prefix_raw, crash_hook=crash_hook, precondition=stable_segment)
            for path in (*records, segment):
                original = location(path)
                if original == path:
                    IC.durable_replace(path, archive/path.name)
    return prefix


def restore_retained_interval(store_directory, disposition, *, scope, assert_exclusive, save_disposition,
                              crash_hook=None, check_adoption=None):
    """Reinstate the named tail after its original predecessor has been established."""
    from atlas_tectonics._private.codecs import interval_catalog as IC
    from atlas_tectonics._private.codecs import interval_store_set as IS
    from atlas_tectonics._private.codecs.compact_contracts import SegmentRef
    directory = IC.safe_path(store_directory)
    archive = IC.safe_path(disposition['archive'])
    require(archive.is_dir() and not archive.is_relative_to(directory),
            'protected output archive must be outside the active store')
    assert_exclusive()
    interval, pins = disposition['interval'], disposition['records']
    catalog = directory/F.CATALOG
    original_catalog = archive/F.CATALOG
    with scope.run_budget.reserve(IS.catalog_transient_charge(IC.file_token(original_catalog)[2]),
                                  category='retained-catalog-restoration'):
        raw, original = IC._read_catalog_image(original_catalog)
        history = IC.Catalog.from_bytes(raw)
        require(original == disposition['before'] and history.generation == interval+1,
                'retained catalog does not match its protected disposition')
        archived_entry = history.entries[-1]

        def location(path):
            parked = archive/path.name
            active, retained = os.path.lexists(path), os.path.lexists(parked)
            require(active or retained, 'protected output is missing: '+path.name)
            return IC.safe_path(path if active else parked, existing=True)

        adoption = F.adopted_path(directory, interval)
        verdict_path = F.verdict_path(directory, interval)
        runner_path = F.runner_record_path(directory, interval)
        seal_path = F.sealed_record_path(directory, interval)
        require(set(pins) == {path.name for path in (adoption, verdict_path, runner_path, seal_path)},
                'exact protected interval record pins required')
        old_adoption = F.read_record(location(adoption), schema=ADOPTED_SCHEMA, expected_sha256=pins[adoption.name])
        if check_adoption is not None:
            check_adoption(adoption, pins[adoption.name], old_adoption)
        approval = old_adoption.get('review_approval_sha256')
        verdict, runner, sealed = adoption_inputs(directory, interval, pins[verdict_path.name], approval,
                                                  location=location)
        entry = sealed['entry']
        segment = IC.relative_file(directory, entry['filename'])
        sealed_file = location(segment)
        token = IC.file_token(sealed_file, reject_sidecars=True)
        require(IS._immutable(sealed_file) and RUN.file_hash(sealed_file) == entry['file_sha256'],
                'restored seal differs from its original interval')
        before = sealed['expected_catalog_digest']
        active = IC._read_catalog_image(catalog)[1] if catalog.exists() else None
        if interval:
            parent = F.read_record(F.adopted_path(directory, interval-1), schema=ADOPTED_SCHEMA,
                                   expected_sha256=RUN._sha(disposition['parent_adopted_sha256']))
            require(parent['catalog_digest'] == parent['catalog_sha256'] == before
                    and parent['entry'] == history.entries[-2].to_wire(),
                    'retained interval names a different original parent adoption')
        require(archived_entry.to_wire() == entry and original == old_adoption['catalog_digest'] ==
                old_adoption['catalog_sha256'] and before == disposition['after'] and
                active in (before, original) and entry['filename'] == disposition['filename'] and
                entry['file_sha256'] == disposition['interval_sha256'] and
                verdict['runner_record_sha256'] == pins[runner_path.name] and
                sha256(F.canonical(sealed)).hexdigest() == pins[seal_path.name],
                'protected restoration has a different parent or original proof')
        save_disposition(dict(disposition, restoring=True))
        assert_exclusive()
        if active == before:
            require(not adoption.exists() and IC.file_token(sealed_file, reject_sidecars=True) == token,
                    'protected restoration has a foreign adoption or a changed sealed file')
            for path in (runner_path, seal_path, verdict_path, segment):
                source = location(path)
                if source != path:
                    IC.durable_replace(source, path)
            stores = (IS.IntervalStoreSet.create_migration(catalog, workflow_id=runner['workflow_id'], scope=scope)
                      if before is None else IS.IntervalStoreSet.open_catalog(catalog, scope=scope))
            try:
                stores.crash_hook = crash_hook
                adopted = stores.adopt_and_promote(entry['filename'], expected_sha256=entry['file_sha256'],
                    expected_logical_seal=entry['logical_seal'], head=SegmentRef.from_wire(runner['head']),
                    producer_identity=runner['producer_identity'], runtime_identity=runner['runtime_identity'],
                    expected_catalog_digest=before, reader_view_digest=verdict['view_digest'])
                require(adopted.to_wire() == entry and stores.catalog_digest == original,
                        'restored catalog differs from the original adoption')
            finally:
                stores.close()
        else:
            require(all(location(path) == path for path in (runner_path, seal_path, verdict_path, segment)),
                    'promoted catalog has no complete active interval')
        value = {'schema': ADOPTED_SCHEMA, 'status': ADOPTED_STATUS, 'interval': interval, 'entry': entry,
                 'catalog_digest': original, 'catalog_sha256': original, 'verdict_sha256': pins[verdict_path.name],
                 'runner_record_sha256': pins[runner_path.name], 'adopter_pid': None,
                 **({'review_approval_sha256': approval} if approval else {})}
        require(dict(old_adoption, adopter_pid=None) == value, 'restored adoption differs from the original receipt')
        source = location(adoption)
        if source != adoption:
            assert_exclusive()
            IC.durable_replace(source, adoption)
        return pins[adoption.name]


@protect_profile
def adopt(profile, *, mode, verdict_sha256, approval_sha256=None, interval=None):
    """Promote the sealed interval after its reader PASS, from the durable records only."""
    F.FreshSources(profile)        # puts the profile's roots on sys.path
    row = profile.record()
    store_directory, interval = Path(row['store_directory']), F.interval_number(mode, interval)
    path = adopted_path(store_directory, interval)
    done = path.exists()                  # S-4: the record written, the driver not told
    verdict, runner, sealed = adoption_inputs(store_directory, interval, verdict_sha256, approval_sha256)
    entry = sealed['entry']
    from atlas_tectonics._private.codecs import interval_store_set as IS
    from atlas_tectonics.integration.resources import WorkBudget
    from atlas_tectonics._private.codecs.compact_contracts import SegmentRef
    from atlas_tectonics._private.codecs.content_cache import create_retained_scope
    budget = WorkBudget(MONITOR.machine_memory())
    scope = create_retained_scope(budget, process_epoch='fresh-adopt-'+str(os.getpid()))
    catalog = store_directory/F.CATALOG
    try:
        fresh = sealed['expected_catalog_digest'] is None and not done and not os.path.lexists(catalog)
        stores = (IS.IntervalStoreSet.create_migration(catalog, workflow_id=runner['workflow_id'], scope=scope)
                  if fresh else IS.IntervalStoreSet.open_catalog(catalog, scope=scope))
        try:
            promoted = ((done or stores.catalog_digest != sealed['expected_catalog_digest'])   # S-4: reopened,
                        and stores.head is not None and stores.head.to_wire() == entry)     # never retried
            stores.head if promoted else stores.adopt_and_promote(entry['filename'], expected_sha256=entry['file_sha256'],
                expected_logical_seal=entry['logical_seal'], head=SegmentRef.from_wire(runner['head']),
                producer_identity=runner['producer_identity'], runtime_identity=runner['runtime_identity'],
                expected_catalog_digest=sealed['expected_catalog_digest'],
                reader_view_digest=verdict['view_digest'])
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
    value = {'schema': ADOPTED_SCHEMA, 'status': ADOPTED_STATUS, 'interval': interval, 'entry': entry,
             'catalog_digest': catalog_digest, 'catalog_sha256': RUN.file_hash(catalog),
             'verdict_sha256': verdict_sha256, 'runner_record_sha256': verdict['runner_record_sha256'],
             'adopter_pid': os.getpid(), **({'review_approval_sha256': approval_sha256} if approval_sha256 else {})}
    if done:                              # S-4: equal but for adopter_pid; the same line again
        F.read_record(path, schema=ADOPTED_SCHEMA)
        pin = sha256(RUN.ordinary(path).read_bytes()).hexdigest()
    else:
        pin = F.write_durable(path, value)
    print(json.dumps({'status': ADOPTED_STATUS, 'adopted': str(path), 'sha256': pin}), flush=True)
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', type=Path, required=True)
    parser.add_argument('--profile-sha256', required=True)
    parser.add_argument('--mode', choices=MODES, required=True)
    parser.add_argument('--run-profile', default='off')
    parser.add_argument('--profile-tool', type=Path, help='with --run-profile tree: the sampling profiler executable')
    parser.add_argument('--interval', type=int, help='item 21: interval N >= 2 of the interval mode')
    parser.add_argument('--producer-receipt-sha256')
    parser.add_argument('--reopen-receipt-sha256')
    parser.add_argument('--guard-receipt-sha256')
    parser.add_argument('--guard-control-sha256')
    parser.add_argument('--verdict-sha256')
    parser.add_argument('--overlap-spec', help='closed store-free admission/wait specification')
    parser.add_argument('--overlap-gate-sha256', help='required external gate pin for overlap finalise')
    parser.add_argument('--reader-fallback', action='store_true', help='explicit reviewer-approved sequential sibling')
    parser.add_argument('--fallback-claim-sha256')
    parser.add_argument('--review', action='store_true', help='read an interval sealed for review after a pre-seal refusal')
    parser.add_argument('--review-approval-sha256', help='with --adopt: the recorded approval of a review-only interval')
    parser.add_argument('--reuse-previous-run', type=Path, help='diagnostic: the previous profile to read from')
    parser.add_argument('--reuse-previous-run-sha256')
    parser.add_argument('--reuse-identity-override', action='store_true', help='with the reuse pair, override tree')
    parser.add_argument('--record-failed-prior', action='store_true',
                        help='diagnostic trees only: record, not refuse, how an earlier step ended (decision 285)')
    action = parser.add_mutually_exclusive_group()
    for name in ('--launch', '--workload', '--finalise', '--adopt'):
        action.add_argument(name, action='store_true')
    parser.add_argument(SG.ARGUMENT, dest='start_gate', help='the launcher\'s start gate decision (--workload)')
    SG.add_arguments(parser)
    args = parser.parse_args(argv)
    require((args.reopen_receipt_sha256 is not None) == args.finalise and
            (args.verdict_sha256 is not None) == args.adopt and
            (args.producer_receipt_sha256 is not None) == (not args.adopt and args.overlap_spec is None) and
            not (args.review and args.adopt) and (args.review_approval_sha256 is None or args.adopt),
            '--reopen-receipt-sha256 goes with --finalise, --verdict-sha256 and --review-approval-sha256 with '
            '--adopt, --review and --producer-receipt-sha256 with every other action')
    reusing = args.reuse_previous_run is not None
    require((args.reuse_previous_run_sha256 is not None) == reusing and (reusing or not args.reuse_identity_override)
            and (not reusing or args.mode == 'interval' and args.interval is None and not (
                args.adopt or args.review or args.overlap_spec is not None or args.reader_fallback)),
            'reuse-previous-run: both reuse flags, interval 1 only, no adopt, review, overlap or '
            'fallback; --reuse-identity-override only with them')
    reuse_previous = ((args.reuse_previous_run, args.reuse_previous_run_sha256, args.reuse_identity_override)
                      if reusing else None)
    gate_args = bool(args.peak_records) or args.booking_bytes is not None or args.booking_basis is not None
    # Decided before anything is read or made; a launch always needs one, a printed command only if asked.
    gate = (SG.stage_decision(SG.stage_key(args.mode, F.interval_number(args.mode, args.interval)),
                              records=args.peak_records,
                              booking_bytes=args.booking_bytes, booking_basis=args.booking_basis)
            if args.launch or gate_args else None)
    profile = F.FreshProfile.read(args.profile, args.profile_sha256)
    run_profile = profiling.profile_selection(args.run_profile)
    if args.launch:
        profiling.profile_tool(run_profile, args.profile_tool)
    with _reader_admission(profile, reuse_previous) as previous:
        if args.adopt:
            return adopt(profile, mode=args.mode, verdict_sha256=args.verdict_sha256,
                         approval_sha256=args.review_approval_sha256, interval=args.interval)
        if args.workload:
            if profiling.stacks_enabled(run_profile):
                profiling.start_stacks(Path(profile.record()['output_directory']).parent/'profile-stacks',
                                       'reader-'+args.mode)
            return _workload(profile, mode=args.mode, producer_receipt_sha256=args.producer_receipt_sha256,
                             review=args.review, start_gate=args.start_gate, interval=args.interval,
                             overlap_spec=args.overlap_spec, fallback=args.reader_fallback,
                             fallback_claim_sha256=args.fallback_claim_sha256, reuse_previous=reuse_previous, _previous=previous,
                             record_failed_prior=args.record_failed_prior)
        if args.finalise:
            return finalise(profile, mode=args.mode, producer_receipt_sha256=args.producer_receipt_sha256,
                            reopen_receipt_sha256=args.reopen_receipt_sha256,
                            guard_receipt_sha256=args.guard_receipt_sha256, guard_control_sha256=args.guard_control_sha256,
                            review=args.review,
                            interval=args.interval, overlap_gate_sha256=args.overlap_gate_sha256,
                            fallback=args.reader_fallback, fallback_claim_sha256=args.fallback_claim_sha256,
                            reuse_previous=reuse_previous, _previous=previous, record_failed_prior=args.record_failed_prior)
        argv = command(profile, sys.executable, mode=args.mode, producer_receipt_sha256=args.producer_receipt_sha256,
                       review=args.review, start_gate=gate, interval=args.interval, overlap_spec=args.overlap_spec,
                       fallback=args.reader_fallback, fallback_claim_sha256=args.fallback_claim_sha256,
                       reuse_previous=reuse_previous, _previous=previous, record_failed_prior=args.record_failed_prior, run_profile=run_profile)
        if argv == REUSE.REUSE_MISS_EXIT:   # a reuse miss, already printed: nothing is launched
            return argv
        output = reader_output(profile.record(), args.mode, args.interval, fallback=args.reader_fallback)
        argv = profiling.profile_command(run_profile, argv, raw_path=output/'profile-tree.raw',
                                         executable=args.profile_tool)
        print(json.dumps({'status': 'SOURCE_BOUND_COMMAND_ONLY_NOT_ADMISSION', 'command': argv,
                          'production_acceptance': False}), flush=True)
        if not args.launch:
            return 0
        SG.admit(gate, MONITOR.free_memory())
        output.mkdir(exist_ok=False)
        return subprocess.call(argv, env=F.pressure_launch_environment(), cwd=output)


if __name__ == '__main__':
    raise SystemExit(main())
