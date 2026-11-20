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

def _prepare_packaged_script(argv):
    """Authenticate the stdlib bootstrap before a direct installed-script import.

    As the runners do, with this reader's own sibling imports. Returns the
    package and the (profile, pin) authenticated here, which main() requires.
    """
    def argument(flag):
        if argv.count(flag) != 1:
            raise ValueError('one explicit '+flag+' required for installed startup')
        index = argv.index(flag)
        if index + 1 >= len(argv):
            raise ValueError('missing installed startup argument')
        return argv[index + 1]

    # Only the two exact spellings: argparse would also take '--profile=...' or an
    # abbreviation such as '--profile-sha', and so read a profile not authenticated here.
    for token in argv:
        name = token.split('=', 1)[0]
        if (token.startswith('--') and len(name) > 2 and '--profile-sha256'.startswith(name)
                and token not in ('--profile', '--profile-sha256')):
            raise ValueError('installed startup takes only --profile and --profile-sha256, spelt out: '+token)
    profile_path, profile_pin = argument('--profile'), argument('--profile-sha256')
    raw = Path(profile_path).read_bytes()
    if sha256(raw).hexdigest() != profile_pin:
        raise ValueError('installed startup profile pin differs')
    profile = json.loads(raw)
    workspace = Path(profile['workspace']).resolve()
    def contained(name):
        if (type(name) is not str or not name or '\\' in name or ':' in name
                or Path(name).is_absolute() or '..' in Path(name).parts):
            raise ValueError('noncanonical installed startup path')
        path = (workspace/name).resolve()
        if not path.is_relative_to(workspace):
            raise ValueError('installed startup path escaped workspace')
        return path
    binding = profile['source_manifest']
    manifest_raw = contained(binding['path']).read_bytes()
    if sha256(manifest_raw).hexdigest() != binding['sha256']:
        raise ValueError('installed startup manifest pin differs')
    manifest = json.loads(manifest_raw)
    bootstrap = contained(profile['native_root'])/'atlas_tectonics/integration_worker_bootstrap.py'
    bootstrap = bootstrap.resolve()
    relative = bootstrap.relative_to(workspace).as_posix()
    raw = bootstrap.read_bytes()
    if sha256(raw).hexdigest() != manifest['files'].get(relative):
        raise ValueError('installed startup bootstrap pin differs')
    import types
    helper = types.ModuleType('_installed_runner_bootstrap')
    helper.__file__ = str(bootstrap)
    exec(compile(raw, str(bootstrap), 'exec', dont_inherit=True), helper.__dict__)
    package = helper.prepare_installed_runner(profile_path, profile_pin, __file__, runner_modules=(
        'reopen_prepared_restart', 'run_fresh_interval', 'run_prepared_restart', 'start_gate', 'overlap_reader',
        'reader_overlap_gate', 'reuse_previous_run', 'width_gate'))
    return package, (profile_path, profile_pin)


_PACKAGED_STARTUP = None        # (profile, pin) of an installed startup
if (__name__ == '__main__' and Path(__file__).resolve().parent.name == '_private'
        and Path(__file__).resolve().parent.parent.name == 'atlas_tectonics'):
    __package__, _PACKAGED_STARTUP = _prepare_packaged_script(sys.argv[1:])


from atlas_tectonics._private import reopen_prepared_restart as RO
from atlas_tectonics._private import run_fresh_interval as F
from atlas_tectonics._private import run_prepared_restart as RUN
from atlas_tectonics._private import start_gate as SG
from atlas_tectonics._private import overlap_reader as OR
from atlas_tectonics._private import reader_overlap_gate as OG
from atlas_tectonics._private import reuse_previous_run as REUSE
# Unit A: the shared width pass lives in width_gate, so the producer imports nothing of this reader.
from atlas_tectonics._private.width_gate import (ROOT_RECORDS, _mesh, _native_records,  # noqa: F401
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
REOPEN_REASON = {'root': F.ROOT_REOPEN_DEFERRED, 'interval': RUN.SAME_PROCESS_REOPEN_DROPPED}
ROOT_FIELDS = frozenset(('workflow_id', 'root_key', 'kind', 'sequence', 'inspect', 'producer_pid',
                         'root_metadata_sha256', 'store_limits', 'store_compression', 'execution_provenance',
                         'preparation_ids'))
# Item 21: what an interval N >= 2 runner record adds to bind its sealed lineage.
LINEAGE_FIELDS = ('parent_runner_record_sha256', 'parent_adopted_sha256', 'lineage')


class ReaderRefused(F.FreshRefused):
    pass


def require(condition, message):
    if not condition:
        raise ReaderRefused(message)


def reader_output(row, mode, interval=None, *, fallback=False):
    require(mode in MODES, 'explicit route (1) reader mode required')
    number = F.interval_number(mode, interval)
    require(type(fallback) is bool, 'explicit reader fallback flag required')
    output = Path(row['output_directory'])/('reader-'+mode+('' if number <= 1 else f'-{number:04d}')+
                                           ('-fallback' if fallback else ''))
    require(number <= 1 or not Path(row['store_directory']).is_relative_to(output),
            'the interval store must outlive the interval N reader output')
    return output


adopted_path, approval_path, review_approval = F.adopted_path, F.approval_path, F.review_approval


def _own_pin(sources):
    own = Path(__file__).resolve()
    require(own.is_relative_to(sources.workspace) and
            sources.files().get(own.relative_to(sources.workspace).as_posix()) == RUN.file_hash(own),
            'independent fresh reader itself must be pinned')
    return own


def seed_from_producer(stored, source, output, check, *, binding, previous):
    """Decision 326: the reader admits from its producer's closed measurement store, copied by the receipt's pin.

    The reader measures nothing the producer measured. Its PASS does not attest the initial metrics a second time.
    ``stored`` is the store's record: the receipt's, or the one an overlap reader's producer published (decision 344).
    ``binding`` is this reader's F.measurement_composition; the store's must equal it field by field, as the
    producer's own seed requires. ``previous``: the producer is a previous run's (decision 278, diagnostic trees
    only); the fields that differ are then recorded and the store is used (rulings 4a, 6)."""
    require(type(stored) is dict and stored.get('filename') == F.MEASUREMENT_STORE and RO._digest(stored.get('sha256'))
            and type(stored.get('statistics')) is dict and type(stored['statistics'].get('snapshots')) is int
            and type(stored.get('composition')) is dict,
            'the producer receipt does not name its closed measurement store and its composition')
    theirs = stored['composition']
    differing = sorted(name for name in set(binding) | set(theirs)
                       if name not in theirs or name not in binding or theirs[name] != binding[name])
    require(previous or not differing,
            'the producer measurement composition differs from this reader: '+', '.join(differing))
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
        if not OG.process_alive(spec['launcher']):
            raise OG.WaitFailure('launcher_lost', 'before the producer published its measurement store')
        if clock() >= deadline:
            raise OG.WaitFailure('wait_expired', 'before the producer published its measurement store')
        sleep(1.0)
    return OR.read_json(path)[0]


def _root_record(root, *, execution_mode='strict'):
    """Run A's published root record: closed shape, authenticated producer mode, compact bounds."""
    require(type(root) is dict and set(root) == ROOT_FIELDS, 'complete fresh root record required')
    inspected = root['inspect']
    require(RO._identity(root['workflow_id']) and RO._identity(root['root_key']) and root['kind'] == 'root' and
            root['sequence'] == 0 and RO._digest(root['root_metadata_sha256']) and type(inspected) is dict and
            inspected.get('head') == root['root_key'] and inspected.get('intervals') == 0 and
            inspected.get('workflow_id') == root['workflow_id'], 'fresh root identity is incomplete')
    ids, provenance = root['preparation_ids'], root['execution_provenance']
    require(type(ids) is dict and set(ids) == RO.PREPARATIONS and all(RO._identity(v) for v in ids.values()),
            'complete independently exported preparation identities required')
    RO.validate_execution_provenance(provenance, execution_mode=execution_mode)
    require(root['store_limits'] == RUN.COMPACT_STORE_LIMITS and root['store_compression'] == RUN.COMPACT_COMPRESSION,
            'producer compact store bounds differ from the reviewed ones')
    require(inspected.get('funding_id') == ids['funding'], 'fresh root funding differs')
    return root


def _completed(completed, *, root, pid, advanced, sequence=1, producer_mode='strict'):
    """The driver's completed-endpoint record extends run A's root, at exactly ``sequence``."""
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
            completed['head_key'] == advanced['head'] != root['root_key'] and completed['sequence'] == sequence and
            completed['preparation_ids'] == root['preparation_ids'] and
            completed['execution_provenance'] == dict(root['execution_provenance'], execution_mode=producer_mode) and
            completed['store_limits'] == root['store_limits'] and
            completed['store_compression'] == root['store_compression'],
            'advanced endpoint does not extend run A root of this producer')
    RO.canonical_records(completed['array_records'])
    return completed


def _said(errors):
    """An error list as text: each error's type and message."""
    return '; '.join(f"{e.get('type')}: {e.get('message')}" if type(e) is dict else repr(e) for e in errors)


def _producer_receipt(receipt, *, profile, mode, consumer_pid, review=False, interval=None, recorded=None):
    require(mode == 'interval' or not review, 'only an interval can be sealed for review')
    if review:
        errors = receipt.get('errors') if type(receipt) is dict else None
        state = receipt.get('review_only') if type(receipt) is dict else None
        settled = (type(errors) is list and [e.get('type') for e in errors] == ['PresealSealedForReview'] and
                   type(state) is dict and state.get('state') == F.REVIEW_STATUS)
    else:  # decision 285: how the producer ended is a prior test, below; its data are tested here
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
    require(type(pid) is int and pid > 0 and type(consumer_pid) is int and consumer_pid > 0 and pid != consumer_pid,
            'separate producer and reader processes required')
    require(receipt.get('same_process_cold_reopen') is False and
            receipt.get('same_process_cold_reopen_reason') == REOPEN_REASON[mode],
            'producer reopen scope differs: this reader is the mandatory cold reopen')
    before = RO.validate_retained_accounting(receipt.get('compact_retained_before_close'), pid=pid)
    after = RO.validate_retained_accounting(receipt.get('compact_retained_after_close'), pid=pid)
    RO.prior(RO.retained_release_agrees(before, after), 'producer compact retained scope was not released', recorded)
    proof = receipt.get('source_proof')
    require(type(proof) is dict and receipt.get('identities') == {
            'producer_identity': profile.sha256, 'runtime_identity': proof.get('native_source_digest')},
            'producer identities differ from its profile and selected runtime')
    return pid


def validate_producer_receipt(receipt, *, profile, receipt_sha256, runner, sealed, guard_receipt, guard_control,
                              consumer_pid, mode, root_runner=None, review=False, interval=None, lineage=None,
                              production_policy=None, recorded=None):
    """Pure closed checks of a sealed producer result; returns the validated expectation.

    Interval N >= 2 (item 21) takes ``lineage``, the runner's sealed-lineage gate on adopted
    interval N-1, re-run by this reader; its run A runner record is the gate's.
    """
    require(mode in MODES and type(profile) is F.FreshProfile, 'typed profile and reader mode required')
    require(RO._digest(receipt_sha256), 'exact producer receipt pin required')
    number = F.interval_number(mode, interval)
    require((number >= 2) == (lineage is not None) and
            (lineage is None or type(lineage) is dict and lineage.get('root_runner') == root_runner and
             type(lineage.get('lineage')) is dict and lineage['lineage'].get('interval') == number-1),
            'interval N >= 2 is read from its own sealed lineage gate, and only it')
    pid = _producer_receipt(receipt, profile=profile, mode=mode, consumer_pid=consumer_pid, review=review,
                            interval=interval, recorded=recorded)
    producer_mode, producer_limits = RO._producer_policy(receipt, production_policy)
    interval, entry, identities = number, sealed['entry'], receipt['identities']
    runner_sha = sha256(F.canonical(runner)).hexdigest()
    require(runner['interval'] == sealed['interval'] == entry['interval'] == interval and
            runner['head'] == entry['head'] and runner['producer_pid'] == pid and
            runner['producer_identity'] == entry['producer_identity'] == identities['producer_identity'] and
            runner['runtime_identity'] == entry['runtime_identity'] == identities['runtime_identity'] and
            sealed['runner_record_sha256'] == runner_sha == receipt['runner_record']['sha256'] and
            receipt['sealed'] == sealed, 'sealed entry, runner record and producer receipt differ')
    if mode == 'root':
        root = _root_record(runner['root'], execution_mode=producer_mode)
        require(receipt['published_root'] == root and root['producer_pid'] == pid and
                runner['workflow_id'] == root['workflow_id'] == receipt['workflow_id'] and
                sealed['expected_catalog_digest'] is None,
                'run A root record differs from its receipt or is not the first interval')
        expected = {'root': root}
    else:
        require(type(root_runner) is dict, 'run A runner record required for interval 1')
        # The adopted root keeps run A's provenance; this producer may use another mode.
        prior_root = root_runner.get('root')
        prior_provenance = prior_root.get('execution_provenance') if type(prior_root) is dict else None
        prior_mode = prior_provenance.get('execution_mode') if type(prior_provenance) is dict else None
        root = _root_record(prior_root, execution_mode=prior_mode)
        previous, advanced = runner['previous_endpoint'], runner['advanced_endpoint']
        require(runner['root_runner_record_sha256'] == sha256(F.canonical(root_runner)).hexdigest() and
                runner['workflow_id'] == root_runner['workflow_id'] == root['workflow_id'] and
                RO._digest(sealed['expected_catalog_digest']) and
                receipt['advanced_endpoint'] == advanced and receipt['previous_endpoint'] == previous,
                'run B records do not extend run A or differ from their receipt')
        if lineage is None:
            parent_key = root['root_key']
            require(not any(name in runner for name in LINEAGE_FIELDS),
                    'run B records do not extend run A or differ from their receipt')
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
            require('review_only' not in runner and receipt['record_identities'] == runner['record_identities'],
                    'run B record identities differ from their receipt')
            RO.canonical_record_identities(runner['record_identities'], successor=True)
        require(type(previous) is dict and type(advanced) is dict and previous.get('head') == parent_key and
                previous.get('intervals') == interval-1 and advanced.get('intervals') == interval and
                advanced.get('head') != previous.get('head') and
                advanced.get('funding_id') == previous.get('funding_id') == root['preparation_ids']['funding'] and
                all(type(e.get('time_s')) in (int, float) for e in (previous, advanced)) and
                advanced['time_s'] > previous['time_s'],
                'run B must advance run A root exactly once with unchanged funding' if interval == 1 else
                'interval N must advance its parent exactly once with unchanged funding')
        queries = receipt.get('completed_queries')
        declared = (receipt.get('completed_query_store') or {}).get('declared')
        require(type(queries) is dict and declared in F.QUERY_STORES and queries.get('store') == declared and
                all(type(queries.get(k)) is int and queries[k] >= 0 for k in ('hits', 'misses', 'written',
                                                                              'incomplete', 'unflushed')),
                'run B completed-query record is incomplete')
        expected = {'root': root, 'previous_endpoint': previous, 'advanced_endpoint': advanced,
                    'parent_key': parent_key,
                    'completed_endpoint': _completed(receipt.get('completed_endpoint'), root=root, pid=pid,
                                                     advanced=advanced, sequence=interval, producer_mode=producer_mode)}
        if lineage is not None:
            expected['lineage'] = lineage['lineage']
    supervisor = receipt.get('supervisor')
    require(type(supervisor) is dict, 'producer supervisor record required')
    guard = guard_receipt
    if review:
        # The review producer exits 1 with its one PresealSealedForReview error, which the receipt
        # check above has already required. After checking that exact exit, an in-memory copy with
        # only the exit set to 0 lets RO.validate_guard run its other checks unchanged. The copy is
        # never written or returned; the guard file keeps the real exit.
        require(type(guard_receipt) is dict and guard_receipt.get('workload_exit_confirmed') is True and
                type(guard_receipt.get('workload_exit_code')) is int and guard_receipt['workload_exit_code'] == 1,
                'a review producer exits 1, confirmed by its guardian')
        guard = dict(guard_receipt, workload_exit_code=0)
    RO.validate_guard(guard, guard_control, pid=pid, supervisor_pid=supervisor.get('pid'),
                      limits=producer_limits, recorded=recorded)
    return dict(expected, mode=mode, interval=interval, receipt_sha256=receipt_sha256, producer_pid=pid,
                runner=runner, runner_sha256=runner_sha, sealed=sealed, entry=entry, review=review,
                measurement_store=receipt.get('initial_measurement_store'))


def producer_inputs(profile, *, sources, mode, receipt_sha256, consumer_pid, review=False, interval=None,
                    source_proof=None, reuse=None, recorded=None):
    """Store-free preflight: pinned receipt, guard records, durable records, closed sealed file.

    Interval N >= 2 re-runs the runner's sealed-lineage gate from runner(N)'s own adopted(N-1)
    pin; runner(N) itself is pinned by the producer receipt this reader was given.
    """
    require(type(sources) is F.FreshSources and (sources.profile if reuse is None else reuse['previous']) is profile,
            'selected profile sources required')
    row = profile.record()
    number = F.interval_number(mode, interval)
    output, store_directory = F.mode_output(row, mode, interval), Path(row['store_directory'])
    receipt = RUN.pinned_json(output/'run.json', receipt_sha256, RO.MAX_RECEIPT)
    require(type(receipt) is dict and mode in F.MODES and receipt.get('mode') == mode,
            'producer receipt mode differs from the expected fresh route')
    require(reuse is None or 'production_release' not in receipt, 'reuse-previous-run reads a diagnostic producer only')
    guard = RO._bounded_json(output/'run.guard.json')
    control = RO._bounded_json(output/'run.guard-control.json')
    require(not (output/'run.guard-abort.json').exists() and not (output/'run.cancel').exists(),
            'producer was aborted or cancelled')
    pins = (receipt.get('runner_record'), receipt.get('sealed_awaiting_reader'))
    paths = (F.runner_record_path(store_directory, number), F.sealed_record_path(store_directory, number))
    require(all(type(pin) is dict and set(pin) == {'path', 'sha256'} and pin['path'] == str(path)
                for pin, path in zip(pins, paths, strict=True)), 'producer durable record pins required')
    runner = F.read_record(paths[0], schema=F.RUNNER_RECORD_SCHEMA, expected_sha256=pins[0]['sha256'])
    sealed = F.read_record(paths[1], schema=F.SEALED_SCHEMA, expected_sha256=pins[1]['sha256'])
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
    expected = validate_producer_receipt(receipt, profile=profile, receipt_sha256=receipt_sha256, runner=runner,
        sealed=sealed, guard_receipt=guard, guard_control=control, consumer_pid=consumer_pid, mode=mode,
        root_runner=root_runner, review=review, interval=interval, lineage=gate,
        production_policy=RUN.producer_policy(receipt, sources, expected_route='fresh-'+mode), recorded=recorded)
    # source_proof: a verify() the caller has just made (repeat fix K15); None verifies here, except for the
    # records-only core, which checks no sources (unit A; the chain's first step did, decision 516).
    if source_proof is not None or not records_only(mode, review, runner):
        proof = sources.verify() if source_proof is None else source_proof
        require(receipt.get('source_proof') == (proof if reuse is None else reuse['source_proof']),
                'producer source proof differs from the selected sources')
    if parent_widths is not None:
        expected['parent_widths'] = parent_widths
    return expected


def _producer_inputs_retry(profile, **kwargs):
    """Retry the complete unchanged bounded, store-free producer preflight."""
    return OG._retry_sharing(lambda: producer_inputs(profile, **kwargs), 'producer input records')


def producer_gate_pins(profile, producer, *, mode, interval=None):
    """Pins of actual authenticated immutable records; no producer store is opened."""
    row = profile.record()
    number = F.interval_number(mode, interval)
    output = F.mode_output(row, mode, interval)
    directory = Path(row['store_directory'])
    paths = (output/'run.json', output/'run.guard.json',
             F.runner_record_path(directory, number), F.sealed_record_path(directory, number))
    limits = (RO.MAX_RECEIPT, RUN.MAX_CONFIG, RUN.MAX_CONFIG, RUN.MAX_CONFIG)
    records = [OR.read_json(path, limit=limit) for path, limit in zip(paths, limits, strict=True)]
    require(records[0][1] == producer['receipt_sha256'] and
            records[2][1] == producer['runner_sha256'] and records[2][0] == producer['runner'] and
            records[3][0] == producer['sealed'] and records[1][0].get('status') == 'STOPPED' and
            records[1][0].get('workload_exit_confirmed') is True,
            'authenticated producer records changed before gate binding')
    return dict(zip(('producer_receipt_sha256', 'guard_receipt_sha256', 'runner_sha256', 'sealed_sha256'),
                    (record[1] for record in records), strict=True))


def _reader_options(profile, *, mode, interval, producer_receipt_sha256, review, overlap_spec,
                    fallback, fallback_claim_sha256):
    require(type(fallback) is bool and not (fallback and review), 'fallback is an ordinary reader only')
    require((fallback_claim_sha256 is not None) == fallback and
            (not fallback or RO._digest(fallback_claim_sha256)), 'fallback requires its exact once-only claim pin')
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
    from atlas_tectonics._private import interval_store_set as IS
    from atlas_tectonics._private import width_gate as WG
    from atlas_tectonics._private.compact_contracts import SegmentRef
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
        require(view.pending_entry.to_wire() == entry and store.readonly, 'pending view differs from the sealed entry')
        F._store_configuration(store)
        record.update(view_digest=view.catalog_digest, accepted_catalog_digest=view.accepted_catalog_digest)
        checks['pending_file_verified'] = True
        guard.phase('records-only-widths')
        if mode == 'root':
            head = store.metadata(root['root_key'])
            require(type(head) is dict and head.get('kind') == 'root' and head.get('key') == root['root_key'],
                    'fresh root required')
            state = head['exterior_state']
            # A compact root would need the full core; a fresh-route root is native (Workflow.create).
            require('compact_mesh' not in state and set(state['record_blobs']) == ROOT_RECORDS,
                    'records-only reader requires a native root')
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
    require(all(found[name] == completed[name] for name in found) and
            workflow._exterior_owner.owner_id == completed['preparation_ids']['spatial_owner'],
            'independently reopened state identities differ')
    groups = RO.endpoint_array_records(D, workflow)
    require(RO.canonical_records(groups) == RO.canonical_records(completed['array_records']),
            'independently reopened endpoint arrays differ')
    del groups
    lineage = validate_fresh_lineage(root=parent_metadata, head=head, observed=RO.observed_lineage(workflow),
                                     parent_interval=number-1)
    return {'endpoint': found, 'lineage': lineage}


def _read_store(row, reuse):
    """The store this reader reads: under reuse, the previous run's."""
    return Path((row if reuse is None else reuse['previous'].record())['store_directory'])


def _reader_status(errors, mode, reuse):
    return 'FAILED' if errors else WORKLOAD_STATUS[mode] if reuse is None else REUSE.STATUS


def reopen_fresh_interval(profile, *, sources, guard, record, save, producer, mode, start_gate=None,
                          overlap_spec=None, fallback=False, fallback_claim_sha256=None, scope_state=None,
                          reuse=None):
    """Fresh-process reader core; call under sources.selected() and the live guard. ``start_gate``: the
    launcher's start_gate decision (encoded), admitted again here against this process's free memory."""
    require(type(profile) is F.FreshProfile and type(sources) is F.FreshSources and sources.profile is profile and
            sources.selected_now, 'actual selected pinned sources required')
    if type(overlap_spec) is str:
        overlap_spec = OR.decode_spec(overlap_spec)
    require(mode in MODES and (type(producer) is dict and producer.get('mode') == mode or
                              producer is None and overlap_spec is not None),
            'validated producer expectation or deferred overlap required')
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
        FRESH, H, D = bound[F.DRIVER], bound['historical_admission'], bound['heat_interval_r9_spec']
    from atlas_tectonics._private import interval_store_set as IS
    from atlas_tectonics._private import width_gate as WG
    from atlas_tectonics._private import workflow_transfer as W
    from atlas_tectonics.resources import WorkBudget
    from atlas_tectonics.reuse import require_strict_execution
    from atlas_tectonics._private.compact_contracts import SegmentRef
    if not records:
        _own_pin(sources)
        m = F.composition(sources)
    require_strict_execution()
    record.update(RUN.interpreter_gate())
    output = guard.output.parent
    require(output == reader_output(row, mode, _explicit(number), fallback=fallback) and
            RUN.ordinary(output, directory=True) == output,
            'guard and reader output directory differ')
    import psutil
    available = psutil.virtual_memory().available
    admitted = SG.child_admit(start_gate, available)
    guard.budget = budget = WorkBudget(RUN.LOGICAL_BYTES, max_predicate_work_units=1 << 44)
    RUN._guard_boundary(sources, guard, budget)
    check = lambda: guard.check(force=True)
    if not records:
        H._loaded_source_fence(FRESH, row['advance_driver']['sha256'], check)
        record['source_proof'] = sources.verify()
    record.update(guard_limits=SG.guard_limits(admitted), start_gate=admitted,
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
            from atlas_tectonics._private import cold_bridge_r1 as COLD_BRIDGE
            contexts.enter_context(COLD_BRIDGE.selected())
            guard.phase('rebuild-fresh-admission')
            then = row if reuse is None else reuse['previous'].record()     # as _read_store has it (:675)
            source = F.mode_output(then, mode, _explicit(number))
            binding = F.measurement_composition(profile, sources, proof=record['source_proof'],
                                                interpreter_seed=record['interpreter_seed'])
            seeded = {}

            def seed():     # N6 calls it at the point of use: after the fixture and partition, before the store opens
                if overlap_spec is None:
                    stored = producer['measurement_store']
                else:       # decision 344: the producer is still running
                    guard.phase('wait-for-producer-measurement-store')
                    stored = _published_store(source, overlap_spec, check)
                seeded.update(seed_from_producer(stored, source, output, check, binding=binding,
                                                 previous=reuse is not None))
                record['initial_measurements'] = seeded
                save()
            requested = 0                                   # decision 326: nothing is measured, so no pool
            admission = FRESH.admission(m, budget=budget, artifacts=output, phase=guard.phase, initial_workers=requested,
                before_measurements=seed,
                measurements=lambda statistics, bounds: seeded.update(measured=statistics['snapshots']-seeded['seed_snapshots']))
            if overlap_spec is not None:
                a, producer = contexts.enter_context(OR.admitted_before_gate(
                    admission=admission, spec=overlap_spec, record=record, save=save, guard=guard,
                    verify_sources=sources.check_imported,
                    producer_inputs=lambda pin: _producer_inputs_retry(profile, sources=sources, mode=mode,
                        receipt_sha256=pin, consumer_pid=os.getpid(), review=False, interval=_explicit(number)),
                    producer_pins=lambda value: producer_gate_pins(profile, value, mode=mode, interval=_explicit(number)),
                    memory_admit=lambda free: SG.child_admit(start_gate, free),
                    available_memory=lambda: psutil.virtual_memory().available, waiter=guard.identity))
                require(producer['measurement_store'] == seeded['store'],
                        'the producer receipt names another measurement store than the one this reader admitted from')
            else:
                a = contexts.enter_context(admission)
                # Comparable normal readers use the same admission ordering and
                # repeat the unchanged prediction immediately before pending access.
                sources.check_imported()
                guard.check(force=True)
                record['memory_before_open_pending'] = SG.child_admit(start_gate, psutil.virtual_memory().available)
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
            require(not live, 'initial admission workers alive after the pass closed')
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
                require(view.pending_entry.to_wire() == entry and store.readonly, 'pending view differs from the sealed entry')
                F._store_configuration(store)
                record.update(view_digest=view.catalog_digest, accepted_catalog_digest=view.accepted_catalog_digest)
                checks['pending_file_verified'] = True
                token = store.change_token()
                require(RO.strict_execution_matches(a.heat_execution.provenance, root['execution_provenance']) and
                        FRESH.preparation_ids(a.case, a.owner) == root['preparation_ids'],
                        'independently rebuilt runtime, plans or owner differ from run A')
                checks['source_bound_admission'] = True
                from atlas_tectonics._private import compact_contracts
                compact_contracts.open_proofs = True    # decision 542: the full core's open proves; never off (N-2)
                guard.phase('independent-open-fresh-workflow')
                # One store-set read batch for the whole stage: one file check before, one after.
                with WG.collect_proofs(store) as proofs, view.read_batch(), m.Workflow.open(
                        store, runner['workflow_id'], a.case['collar'], a.case['owner'], a.case['funding'],
                        budget=budget, exterior_owner=a.owner) as workflow:
                    found = FRESH.published_root(workflow, store, a)
                    differing = [name for name in FRESH.ROOT_IDENTITY if name != 'execution_provenance' and
                                 found[name] != root[name]]
                    if not RO.strict_execution_matches(found['execution_provenance'], root['execution_provenance']):
                        differing.append('execution_provenance')
                    require(not differing, 'independently reopened root differs from run A: '+', '.join(differing))
                    require(found['store_limits'] == root['store_limits'] and
                            found['store_compression'] == root['store_compression'],
                            'reader store bounds differ from run A')
                    checks['root_identity'] = True
                    table = WG.WidthTable(producer['interval'])
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
                        identities = successor_record_identities(workflow, table, proofs)
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
        sources.check_imported()
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


def command(profile, python, *, mode, producer_receipt_sha256, review=False, start_gate=None, interval=None,
            overlap_spec=None, fallback=False, fallback_claim_sha256=None, reuse_previous=None,
            record_failed_prior=False):
    """Store-free preflight and the guarded argv; never launches. ``start_gate`` goes last."""
    sources = F.FreshSources(profile)
    recorded = _recording(sources, record_failed_prior)
    reuse = None if reuse_previous is None else REUSE.plan(profile, sources, *reuse_previous)
    overlap_spec = _reader_options(profile, mode=mode, interval=interval,
        producer_receipt_sha256=producer_receipt_sha256, review=review, overlap_spec=overlap_spec,
        fallback=fallback, fallback_claim_sha256=fallback_claim_sha256)
    if overlap_spec is None:
        _producer_inputs_retry(profile if reuse is None else reuse['previous'], sources=sources, mode=mode,
                               receipt_sha256=producer_receipt_sha256, consumer_pid=os.getpid(), review=review,
                               interval=interval, reuse=reuse, recorded=recorded)
    else:
        sources.verify()
    row = profile.record()
    if fallback:
        _fallback_binding(row, mode, interval, fallback_claim_sha256)
    output = reader_output(row, mode, interval, fallback=fallback)
    RUN.ordinary(output.parent, directory=True)
    require(output.is_relative_to(sources.workspace) and not output.exists(), 'exclusive new reader output directory required')
    own = _own_pin(sources)
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


def _workload(profile, *, mode, producer_receipt_sha256, review=False, start_gate=None, interval=None,
              overlap_spec=None, fallback=False, fallback_claim_sha256=None, reuse_previous=None,
              record_failed_prior=False):
    require(sys.dont_write_bytecode, 'run with -B to preserve frozen sources')
    sources = F.FreshSources(profile)
    recorded = _recording(sources, record_failed_prior)
    reuse = None if reuse_previous is None else REUSE.plan(profile, sources, *reuse_previous)
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
    with sources.selected():
        G = sources.module('private_heat_continuation_guard_r3')
        save = lambda: G._write(output, record)
        try:
            if overlap_spec is None:
                # o2: the producer's worker startup (run_fresh_interval :1448); a serial reader needs none
                record['pressure_worker_startup'] = sources.configure_pressure_workers()
            guard = G.ContinuationGuard(output, record, save)
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
            if recorded:  # decision 285: what this reader accepted of how its producer ended
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
                    if record.get('reader_core') != 'records':    # unit A: the records-only core checks no sources
                        sources.check_imported()
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
    from atlas_tectonics._private import width_gate as WG
    review = producer['review']
    require(type(reopen) is dict and reopen.get('schema') == READER_SCHEMA and
            type(reopen.get('errors')) is list and reopen.get('production_acceptance') is False and
            reopen.get('independent_process_reopen') is True and reopen.get('mode') == mode and
            reopen.get('profile_sha256') == profile.sha256 and reopen.get('review_only') is review and
            reopen.get('producer_receipt_sha256') == producer['receipt_sha256'] and
            reopen.get('remaining_children') == [] and
            (reopen.get('interval') == producer['interval'] if producer['interval'] >= 2 else 'interval' not in reopen),
            'successful independent reader result of this producer, profile and mode required')
    # decision 285: how the reader ended; refused unless the run records
    RO.prior(reopen.get('status') == WORKLOAD_STATUS[mode], f"reader status {reopen.get('status')!r}", recorded)
    RO.prior(reopen['errors'] == [], 'reader errors: '+_said(reopen['errors']), recorded)
    RO.prior(reopen.get('final_reserved_bytes') == 0,
             f"reader final_reserved_bytes {reopen.get('final_reserved_bytes')!r}", recorded)
    pid = reopen.get('pid')
    require(type(pid) is int and pid > 0 and pid != producer['producer_pid'],
            'reader must run in a process separate from the producer')
    checks = reopen.get('independent_checks')
    core = reopen.get('reader_core', 'full')
    # Unit A: a records-only record only for a producer that core reads, never a review-only one.
    require(core == 'full' or core == 'records' and records_only(mode, review, producer['runner']),
            'records-only reader result of a producer it cannot read')
    expected = RECORDS_CHECKS[mode] if core == 'records' else REVIEW_CHECKS if review else CHECKS[mode]
    require(type(checks) is dict and set(checks) == expected, 'every independent reopen check must have run')
    false = sorted(name for name, value in checks.items() if value is not True)
    RO.prior(not false, 'independent reopen checks not passed: '+', '.join(false), recorded)
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
    require(type(retained) is dict and set(retained) == {'before_close', 'after_close'} and
            retained['before_close'].get('scope_id') == retained['after_close'].get('scope_id'),
            'independent compact retained scope release evidence is incomplete')
    for value in retained.values():
        RO.validate_retained_accounting(value, pid=pid)
    # review S-4: the bytes left after the close and the agreement of the two counts are how the reader ended
    RO.prior(retained['after_close'].get('retained_bytes') == 0,
             f"reader retained_bytes after close {retained['after_close'].get('retained_bytes')!r}", recorded)
    RO.prior(RO.retained_release_agrees(retained['before_close'], retained['after_close']),
             'independent compact retained scope release counts disagree', recorded)
    RO.validate_retained_producer(reopen, retained)
    supervisor = reopen.get('supervisor')
    require(type(supervisor) is dict, 'reader supervisor record required')
    RO.validate_guard(guard_receipt, guard_control, pid=pid, supervisor_pid=supervisor.get('pid'), recorded=recorded)
    import ctypes
    directory = ctypes.create_unicode_buffer(32768)
    require(ctypes.windll.kernel32.GetSystemDirectoryW(directory, len(directory)) > 0,
            'Windows system directory unavailable')
    host_image = os.path.normcase(os.path.join(directory.value, 'conhost.exe'))
    evidence = reopen.get('reader_process_proof')
    require(type(evidence) is dict and set(evidence) == {'parent', 'console_host', 'image', 'argv'}
            and evidence == guard_receipt.get('diagnostic_reader_close'),
            'reader process proof differs from guardian close census')
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
    terminal = guard_receipt.get('diagnostic_reader_terminal')
    require(type(terminal) is dict and type(terminal.get('active_processes')) is int and terminal['active_processes'] == 0,
            'reader terminal job is not empty')
    binding = reopen.get('reader_guard_binding')
    require(type(binding) is dict and identity(binding.get('parent')) and
            binding == {'job_name': guard_receipt.get('job_name'),
            'nonce': guard_receipt.get('nonce'), 'parent': parent} and
            type(guard_receipt.get('job_name')) is str and bool(guard_receipt['job_name']),
            'reader launch context differs from guardian')


def _recording(sources, asked):
    """The list that recorded tests go to, or None. Only a diagnostic tree records (decision 285)."""
    if not asked:
        return None
    manifest = RUN.pinned_json(sources.manifest_path, sources.manifest_pin)
    require(manifest['installed_binding']['qualification_status'] == REUSE.DIAGNOSTIC,
            '--record-failed-prior is for diagnostic trees only')
    return []


def _imported(sources, recorded):
    """The proof that every loaded module is a pinned source. recorded is None unless the run records: refuse, as before."""
    try:
        sources.check_imported()
    except ValueError as error:     # ruling 4a (decision 315): every refusal of the proof is a ValueError
        if recorded is None:
            raise
        recorded.append('loaded-module proof: '+str(error))


def finalise(profile, *, mode, producer_receipt_sha256, reopen_receipt_sha256, guard_receipt_sha256,
             guard_control_sha256, review=False, interval=None,
             overlap_gate_sha256=None, fallback=False, fallback_claim_sha256=None, reuse_previous=None,
             record_failed_prior=False):
    """Store-free acceptance of a completed guarded reader; the exclusive verdict on PASS.

    Under reuse_previous (decision 278) the records are the previous tree's and are tested against its profile
    and source proof; the sources are this tree's.

    A review-only verdict says so: it is evidence for the review, never an adoption by itself.
    """
    sources = F.FreshSources(profile)
    _reader_options(profile, mode=mode, interval=interval, producer_receipt_sha256=producer_receipt_sha256,
        review=review, overlap_spec=None, fallback=fallback, fallback_claim_sha256=fallback_claim_sha256)
    require(RO._digest(reopen_receipt_sha256), 'exact completed reader receipt pin required')
    require(RO._digest(guard_receipt_sha256) and RO._digest(guard_control_sha256),
            'exact terminal guard and control pins required')
    require(not fallback or overlap_gate_sha256 is None, 'sequential fallback cannot inherit an overlap gate pin')
    row = profile.record()
    output = reader_output(row, mode, interval, fallback=fallback)
    final = output/'reopen-final.json'
    require(RUN.ordinary(output, directory=True) == output and not final.exists(), 'reader final record already exists')
    errors, verdict_sha256, gate, reuse, recorded, core = [], None, None, None, None, None
    try:
        recorded = _recording(sources, record_failed_prior)
        reuse = None if reuse_previous is None else REUSE.plan(profile, sources, *reuse_previous)
        then = profile if reuse is None else reuse['previous']
        reopen, _ = OR.read_json(output/'reopen.json', pin=reopen_receipt_sha256, limit=RO.MAX_RECEIPT)
        core = reopen.get('reader_core', 'full') if type(reopen) is dict else None
        # Unit A (NR33): a records-only result is finalised without the source checks; the chain's first step made them.
        proof = None if core == 'records' else sources.verify()
        producer = _producer_inputs_retry(then, sources=sources, mode=mode, receipt_sha256=producer_receipt_sha256,
                                          consumer_pid=os.getpid(), review=review, interval=interval,
                                          source_proof=proof, reuse=reuse, recorded=recorded)
        require(not (output/'reopen.guard-abort.json').exists() and not (output/'reopen.cancel').exists(),
                'reader was aborted or cancelled')
        reader_guard, _ = OR.read_json(output/'reopen.guard.json', pin=guard_receipt_sha256)
        reader_control, _ = OR.read_json(output/'reopen.guard-control.json', pin=guard_control_sha256)
        with sources.selected():
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
                authenticated = OG.read_gate(published)
                require(OG.gate_sha256(authenticated) == overlap_gate_sha256, 'published overlap gate pin differs')
                expected = {'attempt': str(Path(row['output_directory']).resolve()), 'stage': mode,
                            'interval': producer['interval'], 'profile_sha256': profile.sha256,
                            'launcher': authenticated['launcher'], 'launcher_nonce': authenticated['launcher_nonce']}
                OR.validate_finalise(reopen, expected=expected, path=published, pin=overlap_gate_sha256,
                    producer_pins=producer_gate_pins(profile, producer, mode=mode, interval=interval),
                    waiter=reader_guard['parent'], memory_validator=SG.admit)
        if core != 'records':
            require(reopen.get('source_proof') == (proof if reuse is None else reuse['source_proof']),
                    'reader source proof differs from the selected sources')
            # This store-free process imported its validators normally: each must be a pinned source.
            _imported(sources, recorded)
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


def adoption_inputs(store_directory, interval, verdict_sha256, approval_sha256=None):
    """The records adopt_and_promote may use, and nothing else; refuses any inconsistency."""
    verdict = F.read_record(F.verdict_path(store_directory, interval), schema=F.VERDICT_SCHEMA,
                            expected_sha256=verdict_sha256)
    runner = F.read_record(F.runner_record_path(store_directory, interval), schema=F.RUNNER_RECORD_SCHEMA,
                           expected_sha256=verdict['runner_record_sha256'])
    sealed = F.read_record(F.sealed_record_path(store_directory, interval), schema=F.SEALED_SCHEMA)
    entry = sealed['entry']
    mode = 'root' if interval == 0 else 'interval'
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


def adopt(profile, *, mode, verdict_sha256, approval_sha256=None, interval=None):
    """Promote the sealed interval after its reader PASS, from the durable records only."""
    sources = F.FreshSources(profile)
    row = profile.record()
    store_directory, interval = Path(row['store_directory']), F.interval_number(mode, interval)
    path = adopted_path(store_directory, interval)
    done = path.exists()                  # S-4: the record written, the driver not told
    verdict, runner, sealed = adoption_inputs(store_directory, interval, verdict_sha256, approval_sha256)
    entry = sealed['entry']
    with sources.selected():
        from atlas_tectonics._private import interval_store_set as IS
        from atlas_tectonics.resources import WorkBudget
        from atlas_tectonics._private.compact_contracts import SegmentRef
        from atlas_tectonics._private.content_cache import create_retained_scope
        budget = WorkBudget(RUN.LOGICAL_BYTES)
        scope = create_retained_scope(budget, process_epoch='fresh-adopt-'+str(os.getpid()))
        catalog = store_directory/F.CATALOG
        try:
            fresh = sealed['expected_catalog_digest'] is None and not done and not os.path.lexists(catalog)
            stores = (IS.IntervalStoreSet.create_migration(catalog, workflow_id=runner['workflow_id'], scope=scope)
                      if fresh else IS.IntervalStoreSet.open_catalog(catalog, scope=scope))
            try:
                promoted = ((done or stores.catalog_digest != sealed['expected_catalog_digest'])   # S-4: reopened,
                            and stores.head is not None and stores.head.to_wire() == entry)     # never retried
                require(promoted or not done, 'this interval was already adopted')
                adopted = stores.head if promoted else stores.adopt_and_promote(entry['filename'], expected_sha256=entry['file_sha256'],
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
    value = {'schema': ADOPTED_SCHEMA, 'status': ADOPTED_STATUS, 'interval': interval, 'entry': entry,
             'catalog_digest': catalog_digest, 'catalog_sha256': RUN.file_hash(catalog),
             'verdict_sha256': verdict_sha256, 'runner_record_sha256': verdict['runner_record_sha256'],
             'adopter_pid': os.getpid(), **({'review_approval_sha256': approval_sha256} if approval_sha256 else {})}
    if done:                              # S-4: equal but for adopter_pid; the same line again
        earlier = F.read_record(path, schema=ADOPTED_SCHEMA)
        require(dict(earlier, adopter_pid=None) == dict(value, adopter_pid=None), 'this interval was already adopted')
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
    require((args.guard_receipt_sha256 is not None) == args.finalise and
            (args.guard_control_sha256 is not None) == args.finalise,
            'terminal reader guard and control pins belong to finalise')
    require(_PACKAGED_STARTUP is None or (Path(_PACKAGED_STARTUP[0]) == args.profile
                                          and _PACKAGED_STARTUP[1] == args.profile_sha256),
            'the installed startup authenticated another profile')
    require((args.reopen_receipt_sha256 is not None) == args.finalise and
            (args.verdict_sha256 is not None) == args.adopt and
            (args.producer_receipt_sha256 is not None) == (not args.adopt and args.overlap_spec is None) and
            not (args.review and args.adopt) and (args.review_approval_sha256 is None or args.adopt),
            '--reopen-receipt-sha256 goes with --finalise, --verdict-sha256 and --review-approval-sha256 with '
            '--adopt, --review and --producer-receipt-sha256 with every other action')
    require(args.overlap_spec is None or not (args.finalise or args.adopt or args.review or args.reader_fallback),
            '--overlap-spec is an ordinary admitted-ahead reader only')
    require(args.overlap_gate_sha256 is None or args.finalise and not args.reader_fallback,
            '--overlap-gate-sha256 belongs to ordinary overlap finalise')
    require((args.fallback_claim_sha256 is not None) == args.reader_fallback and
            not (args.reader_fallback and (args.adopt or args.review)),
            'explicit fallback flag and claim pin must occur together outside adoption/review')
    reusing = args.reuse_previous_run is not None
    require((args.reuse_previous_run_sha256 is not None) == reusing and (reusing or not args.reuse_identity_override)
            and (not reusing or args.mode == 'interval' and args.interval is None and not (
                args.adopt or args.review or args.overlap_spec is not None or args.reader_fallback)),
            'reuse-previous-run: both reuse flags, interval 1 only, no adopt, review, overlap or '
            'fallback; --reuse-identity-override only with them')
    require(not (args.record_failed_prior and args.adopt), '--record-failed-prior is not an adoption flag')
    reuse_previous = ((args.reuse_previous_run, args.reuse_previous_run_sha256, args.reuse_identity_override)
                      if reusing else None)
    gate_args = bool(args.peak_records) or args.booking_bytes is not None or args.booking_basis is not None
    SG.require(args.start_gate is None or args.workload, SG.ARGUMENT+' is the guarded child\'s argument only')
    SG.require(not (gate_args and (args.workload or args.finalise or args.adopt)), 'the start gate is decided by whoever launches, not the child')
    # Decided before anything is read or made; a launch always needs one, a printed command only if asked.
    gate = (SG.stage_decision(SG.stage_key(args.mode, F.interval_number(args.mode, args.interval)),
                              records=args.peak_records,
                              booking_bytes=args.booking_bytes, booking_basis=args.booking_basis)
            if args.launch or gate_args else None)
    profile = F.FreshProfile.read(args.profile, args.profile_sha256)
    if args.adopt:
        return adopt(profile, mode=args.mode, verdict_sha256=args.verdict_sha256,
                     approval_sha256=args.review_approval_sha256, interval=args.interval)
    if args.workload:
        F._profile_sampler(Path(profile.record()['output_directory']).parent/'profile-stacks', 'reader-'+args.mode)
        return _workload(profile, mode=args.mode, producer_receipt_sha256=args.producer_receipt_sha256,
                         review=args.review, start_gate=args.start_gate, interval=args.interval,
                         overlap_spec=args.overlap_spec, fallback=args.reader_fallback,
                         fallback_claim_sha256=args.fallback_claim_sha256, reuse_previous=reuse_previous,
                         record_failed_prior=args.record_failed_prior)
    if args.finalise:
        return finalise(profile, mode=args.mode, producer_receipt_sha256=args.producer_receipt_sha256,
                        reopen_receipt_sha256=args.reopen_receipt_sha256,
                        guard_receipt_sha256=args.guard_receipt_sha256, guard_control_sha256=args.guard_control_sha256,
                        review=args.review,
                        interval=args.interval, overlap_gate_sha256=args.overlap_gate_sha256,
                        fallback=args.reader_fallback, fallback_claim_sha256=args.fallback_claim_sha256,
                        reuse_previous=reuse_previous, record_failed_prior=args.record_failed_prior)
    argv = command(profile, sys.executable, mode=args.mode, producer_receipt_sha256=args.producer_receipt_sha256,
                   review=args.review, start_gate=gate, interval=args.interval, overlap_spec=args.overlap_spec,
                   fallback=args.reader_fallback, fallback_claim_sha256=args.fallback_claim_sha256,
                   reuse_previous=reuse_previous, record_failed_prior=args.record_failed_prior)
    print(json.dumps({'status': 'SOURCE_BOUND_COMMAND_ONLY_NOT_ADMISSION', 'command': argv,
                      'production_acceptance': False}), flush=True)
    if not args.launch:
        return 0
    import psutil
    SG.admit(gate, psutil.virtual_memory().available)
    output = reader_output(profile.record(), args.mode, args.interval, fallback=args.reader_fallback)
    output.mkdir(exist_ok=False)
    return subprocess.call(argv, env=F.pressure_launch_environment(), cwd=output)


if __name__ == '__main__':
    raise SystemExit(main())
