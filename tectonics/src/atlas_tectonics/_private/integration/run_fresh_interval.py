"""Route (1) fresh-start runner: run A (the root) and run B (interval 1).

Each run ends in a Step 9(a) seal (option B, explicit sealing contract):
the runner seals its interval file and exits without promoting it. The launcher
(launch_fresh_interval.py) runs the independent fresh-process reader on the
sealed file and promotes it only after the reader passed, with
IntervalStoreSet.adopt_and_promote. Nothing is adopted or promoted here.

- Mode ``root`` (run A):
  - the deterministic admission (fresh_interval_driver.create_root);
  - the interval catalog, created under the admission's own workflow ID;
  - the sequence-0 root.
  The runner record (head SegmentRef, producer and runtime identities, root
  identity) is then written durably BEFORE interval-0000 is sealed, and a
  sealed-awaiting-reader record follows the seal.
- Mode ``interval`` (run B):
  - open the accepted catalog, which must hold exactly run A's root, adopted
    from run A's records after the reader's PASS, and begin interval-0001;
  - re-derive the admission and open the sealed root; any ROOT_IDENTITY
    difference from run A's record refuses before the advance;
  - advance exactly one interval through the composed joined helper (r7), with
    the batched columnar completed-query store (WP17);
  - with the workflow still open: the successor checks and bounded_preseal,
    then the durable runner record, then the seal of interval-0001.
- Mode ``interval`` with ``interval`` N >= 2 (item 21): run B one interval further. The
  sealed-lineage gate checks the records of intervals 0..N-1 from the explicit adopted(N-1)
  pin before the catalog opens, and the opened catalog must hold exactly that head; then
  fresh_interval_driver.advance_successor_interval advances once and interval N is sealed
  the same way. Interval 1 keeps every path, label and record unchanged.

The guard, gates, retained scope, storage points and successor checks are
run_prepared_restart's. The launcher takes the head and both identities from
the runner record, never from its own arguments (storage contract);
without that record a sealed file can only be quarantined. Every refusal is
recorded with its first-raised exception.
"""
import argparse
import gc
import inspect
import json
import os
import subprocess
import sys
import time
from concurrent.futures import CancelledError
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path

# Launched as a script (-s -P): the package folder is not on sys.path yet.
if __name__ == '__main__':
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))


from atlas_shared.execution import profiling
from atlas_tectonics._private.integration import run_prepared_restart as RUN
from atlas_tectonics._private.integration import start_gate as SG
from atlas_tectonics._private.integration.interval_admission import admitted, protect_profile
from atlas_shared.machine import resources_monitor as MONITOR

PROFILE_SCHEMA = 'atlas.fresh-interval-profile.v2'
RESULT_SCHEMA = 'atlas.fresh-interval-result.v1'
RUNNER_RECORD_SCHEMA = 'atlas.fresh-interval-runner-record.v1'
SEALED_SCHEMA = 'atlas.fresh-interval-sealed-awaiting-reader.v1'
VERDICT_SCHEMA = 'atlas.fresh-interval-reader-verdict.v1'
MODES = ('root', 'interval')
INTERVALS = {'root': 0, 'interval': 1}
SEALED_STATUS = {'root': 'SEALED_ROOT_AWAITING_READER', 'interval': 'SEALED_INTERVAL_AWAITING_READER'}
STOPPED_STATUS = 'STOPPED_BEFORE_ADVANCE_ROOT_REOPENED'
READER_PASS = {'root': 'PASS_ROOT_INDEPENDENT_REOPEN', 'interval': 'PASS_INTERVAL_INDEPENDENT_REOPEN'}
CATALOG = 'interval-catalog.json'
DRIVER = 'fresh_interval_driver'
# The profile declares its completed-query store. WP17's batched columnar store is used only when
# declared (Step 10 enables it after its durability refuter runs clean), else the
# file store; a declared store the runtime lacks refuses, never a silent fallback.
# flush() precedes the recorded counts with either store.
QUERY_STORE_FLAG = 'completed_query_store'
QUERY_STORES = {'columnar': {'storage': 'columnar', 'batch_entries': 128, 'batch_seconds': 10},
                'files': {'storage': 'files'}}
# Route (1) helpers, bound to reviewed paths before any work; the driver is
# bound separately, as advance_driver.
# The joined helper is r8 (G-R3-1 (b')): its end mesh is compact and unpublished
# (publish_mesh_patch), and _publish publishes it after its partition.
FRESH_MODULES = ('prepared_interval_driver', 'heat_interval_r9_spec',
                 'private_heat_original_spatial_r1', 'private_heat_original_joined_r8',
                 'private_heat_joined_consumer_r6', 'private_heat_geometry_observer_r1',
                 'runtime_radial_fixture', 'initial_pressure_force',
                 'compact_restart_store', 'compact_restart_patch', 'bounded_preseal', 'reopen_prepared_restart',
                 'content_cache', 'historical_admission', 'private_heat_continuation_guard_r3',
                 'windows_workload_job', 'private_heat_resource_diagnostics_r1',
                 'publish_mesh_patch', 'interface_worker_selection')
ROOT_REOPEN_DEFERRED = 'Step 9(a): the independent fresh-process reader reopens the sealed root before promotion'
# A bounded pre-seal refusal requires review and preserves the
# interval's compute. The candidate is still sealed (sealing accepts nothing), the runner
# record names the refusal and the state is REVIEW_STATUS. Nothing in that state is ever
# adopted automatically: reopen_fresh_restart.adopt needs the reader's PASS on that file,
# a written diagnosis showing a checker (not data) defect, and a recorded approval. A data
# integrity cause means quarantine and a rerun. A failure of the seal itself stays fatal.
REVIEW_STATUS = 'FAILED_PRESEAL_SEALED_FOR_REVIEW'
REVIEW_ADOPTION = ('never automatic: the reader PASS on this file, a written diagnosis showing a checker '
                   'defect and a recorded approval naming the file SHA-256 and the verdict are all required')
# Item 7 sealing contract: every run records
# its closed initial measurement store (the driver's cache) after its admission closed. Run B
# may start from run A's store, explicitly and only after run A's reader passed and the root
# was adopted: the runner copies exactly the store run A's own receipt names, by SHA-256,
# before its admission. A hit re-checks each stored field's consistency with its request
# (integration_dual_geometry.cached_initial_component); ROOT_IDENTITY still compares the
# re-derived admission with run A's root. The independent reader always admits with a fresh
# store and refuses any seed. Outside a diagnostic tree every seed refusal stops before the
# admission. In a diagnostic tree it is a miss: run B starts unseeded and measures everything
# (MISS_UNSEEDED, still anchored to run A's verdict and adoption), and files already at the copy
# target are moved aside under a dated name, never deleted (REUSE-MISS-SEED-ROUTE-PLAN-r1, S-1).
MEASUREMENT_STORE = 'initial-measurements.sqlite'
MEASUREMENT_RECORD = 'initial-measurements.json'
MEASUREMENT_SIDECARS = ('-wal', '-journal', '-shm')
MEASUREMENT_COUNTS = ('unique_chunks', 'snapshots', 'encoded_payload_bytes', 'database_bytes', 'operations')
SEED_SCHEMA = 'atlas.fresh-interval-reused-initial-cache.v1'
SEED_FIELDS = frozenset(('receipt_sha256', 'store_sha256'))
SEED_ACROSS = 'across_change'          # D-3: the earlier profile, by path and SHA-256
COMPOSITION = frozenset(('profile_sha256', 'execution_identity', 'advance_driver_sha256', 'interpreter_seed'))
DIAGNOSTIC = 'DIAGNOSTIC_UNCERTIFIED_NO_QUALIFICATION'
# Never read: seeds are explicit arguments only. The runner and the reader refuse it if set.
SEED_ENVIRONMENT = 'ATLAS_INITIAL_MEASUREMENT_SEED'
# reopen_fresh_restart's adoption record, restated here (the reader imports this module, not the
# reverse); test_run_fresh_interval checks both against the reader's own definitions.
ADOPTED_SCHEMA = 'atlas.fresh-interval-adopted.v1'
ADOPTED_STATUS = 'ADOPTED_AFTER_INDEPENDENT_READER'
# Item 21. The review approval of a review-only interval moved here from reopen_fresh_restart,
# which aliases it: the lineage gate re-runs it for every review-adopted parent.
REVIEW_APPROVAL_SCHEMA = 'atlas.fresh-interval-review-approval.v1'
REVIEW_APPROVERS = ('reviewer', 'owner')
# fresh_interval_driver's and prepared_interval_driver's; test_run_fresh_interval checks all three.
LINEAGE_SCHEMA = 'atlas.fresh-interval-lineage.v1'
MAX_RECEIPT = 64 << 20
COPY_BLOCK = 1 << 20


class FreshRefused(RUN.RestartRefused):
    pass


class PresealSealedForReview(FreshRefused):
    pass


def require(condition, message):
    if not condition:
        raise FreshRefused(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def record_name(kind, interval):
    return f'{kind}-interval-{interval:04d}.json'


def runner_record_path(store_directory, interval):
    return Path(store_directory)/record_name('runner-record', interval)


def sealed_record_path(store_directory, interval):
    return Path(store_directory)/record_name('sealed-awaiting-reader', interval)


def verdict_path(store_directory, interval):
    return Path(store_directory)/record_name('reader-verdict', interval)


def adopted_path(store_directory, interval):
    return Path(store_directory)/record_name('adopted', interval)


def approval_path(store_directory, interval):
    return Path(store_directory)/record_name('review-approval', interval)


def interval_number(mode, interval=None):
    """The interval a run seals: the mode's own, or an explicit N >= 1 of the interval mode (item 21)."""
    if interval is None:
        return INTERVALS[mode]
    require(mode == 'interval' and type(interval) is int and interval >= 1,
            'an explicit interval is N >= 1 of the interval mode')
    return interval


def parent_pin(number, parent_adopted_sha256):
    """The explicit adopted(N-1) file pin: required for interval N >= 2 and refused otherwise."""
    require((number >= 2) == (parent_adopted_sha256 is not None),
            'interval N >= 2 needs exactly the adopted(N-1) pin, and only it')
    return None if parent_adopted_sha256 is None else RUN._sha(parent_adopted_sha256)


def mode_output(row, mode, interval=None):
    number = interval_number(mode, interval)
    output = Path(row['output_directory'])/('run-'+mode+('' if number <= 1 else f'-{number:04d}'))
    # The profile already keeps the store outside run-root and run-interval; it cannot name interval N's.
    require(number <= 1 or not Path(row['store_directory']).is_relative_to(output),
            'the interval store must outlive the interval N run output')
    return output


def write_durable(path, value):
    """Exclusive, flushed and fsynced canonical JSON; returns its SHA-256.

    A record that exists is never replaced: a second attempt for the same
    interval refuses, so no later process can overwrite an earlier assertion.
    """
    raw = canonical(value)
    with Path(path).open('xb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return sha256(raw).hexdigest()


def read_record(path, *, schema, expected_sha256=None):
    """A canonical durable record of one schema, optionally pinned by SHA-256."""
    raw = RUN.ordinary(path).read_bytes()
    require(len(raw) <= RUN.MAX_CONFIG, 'durable record exceeds bounded size: '+str(path))
    value = RUN._json(raw)
    require(type(value) is dict and value.get('schema') == schema and canonical(value) == raw,
            'canonical '+schema+' record required: '+str(path))
    require(expected_sha256 is None or sha256(raw).hexdigest() == expected_sha256,
            'durable record differs from its recorded SHA-256: '+str(path))
    return value


def first_raised(error):
    """The earliest exception of a chain (cause, else context), cycle-safe."""
    seen = set()
    while id(error) not in seen:
        seen.add(id(error))
        following = error.__cause__ if error.__cause__ is not None else error.__context__
        if following is None:
            break
        error = following
    return error


@dataclass(frozen=True)
class FreshProfile(RUN.RestartProfile):
    """Pinned route (1) profile: sources, helpers, attempt, store and query directories."""

    @classmethod
    def read(cls, path, pin):
        path = RUN.ordinary(path)
        row = RUN.pinned_json(path, pin)
        fields = {'schema', 'workspace', 'completed_query_store', 'qualification_status', 'native_root', 'import_roots', 'modules',
                  'advance_driver', 'output_directory', 'store_directory', 'completed_query_directory',
                  'completed_query_limits', 'historical_inputs'}
        require(type(row) is dict and set(row) == fields and row['schema'] == PROFILE_SCHEMA,
                'closed reviewed fresh-interval profile required; an older profile is moved with '
                'tools/runs/migrate_run_profile.py')
        required = set(FRESH_MODULES)
        # A previous-run reader may still inspect a pinned pre-move profile.
        require(type(row['modules']) is dict and set(row['modules']) in (required, required | {'dev_stage_timing'}),
                'complete explicit route (1) helper bindings required')
        driver = row['advance_driver']
        require(row['completed_query_store'] in QUERY_STORES,
                'the profile must declare its completed-query store: columnar or files')
        require(type(row['qualification_status']) is str and row['qualification_status'],
                'the profile must declare its qualification status')
        historical = row['historical_inputs']
        require(type(historical) is dict and set(historical) == {'path', 'sha256'}
                and RUN._sha(historical['sha256']) == RUN.HISTORICAL_INPUTS_SHA256,
                'explicit fixed historical input catalogue required')
        RUN._sha(driver['sha256'])
        RUN.canonical_absolute(row['output_directory'], 'attempt output directory')
        RUN.canonical_absolute(row['store_directory'], 'compact store directory')
        query_path = row['completed_query_directory']
        require(type(query_path) is str and query_path and '\\' not in query_path and ':' not in query_path and
                not Path(query_path).is_absolute() and '..' not in Path(query_path).parts,
                'explicit contained completed-query directory required')
        quota = row['completed_query_limits']
        require(type(quota) is dict and set(quota) == RUN.QUERY_LIMIT_FIELDS and
                all(type(value) is int and value > 0 for value in quota.values()),
                'explicit positive completed-query entry and byte limits required')
        return cls(path, pin, canonical(row))


class FreshSources(RUN.RestartSources):
    """RestartSources for a route (1) profile."""

    def __init__(self, profile):
        super().__init__(profile)


def query_store_arguments(owner_type, declared):
    """Constructor arguments of the declared completed-query store; refuses before any work.

    A runtime whose owner predates the storage choice has only the file store, so
    'files' passes no storage argument there and the owner's default is checked.
    """
    try:
        parameters = set(inspect.signature(owner_type).parameters)
    except (TypeError, ValueError):
        parameters = set()
    if declared == 'columnar':
        return dict(QUERY_STORES['columnar'])
    return dict(QUERY_STORES['files']) if 'storage' in parameters else {}


def composition(sources):
    """The module namespace fresh_interval_driver reads: r9's modules with the r7 joined helper."""
    from types import SimpleNamespace

    from atlas_tectonics.integration.geometry import differential_geometry as G
    from atlas_tectonics.integration.parallel import profile as PF
    from atlas_tectonics.integration.parallel.selection import InterfaceParallelPolicy
    from atlas_tectonics.integration.coupling.regional_workflow import CollarWorkflow
    from atlas_tectonics.integration.reuse import ExecutionContext
    from atlas_tectonics.codecs.storage import ArrayStore, Compression, StoreLimits
    from threadpoolctl import threadpool_limits
    from atlas_tectonics._fixtures.tests.i04_differential_modes import ACTUATED_CONTROL
    module = sources.module
    return SimpleNamespace(
        ExecutionContext=ExecutionContext, ArrayStore=ArrayStore, StoreLimits=StoreLimits, Compression=Compression,
        radial_differential_fixture=module('runtime_radial_fixture').radial_differential_fixture,
        spatial=module('private_heat_original_spatial_r1'), D=module('heat_interval_r9_spec'),
        J=module('private_heat_joined_consumer_r6'), Workflow=CollarWorkflow,
        joined=module('private_heat_original_joined_r8'),
        check_initial_pressure_force=module('initial_pressure_force').check_initial_pressure_force,
        ACTUATED_CONTROL=ACTUATED_CONTROL,
        geometry_observer=module('private_heat_geometry_observer_r1'), threadpool_limits=threadpool_limits,
        PF=PF, prepared_interval_driver=module('prepared_interval_driver'), G=G,
        InterfaceParallelPolicy=InterfaceParallelPolicy)


def seal_with_records(store, head_key, *, store_directory, interval, identities, record, save, extra):
    """Durable runner record, then the seal without promotion, then the sealed record.

    ``identities`` are the producer and runtime identities the candidate was
    begun with. The runner record asserts them with the head, so the launcher
    takes all three from that record and from nothing else. The sealed file does
    not bind the identities, so they are compared with the candidate before
    anything is recorded, and with the sealed entry after.
    """
    written = {}

    def record_head(head):
        value = {**extra, 'schema': RUNNER_RECORD_SCHEMA, 'interval': interval, 'head': head, **identities}
        path = runner_record_path(store_directory, interval)
        written['sha256'] = write_durable(path, value)
        record['runner_record'] = {'path': str(path), 'sha256': written['sha256']}
        save()
    sealed = store.seal_pending(head_key, record_head=record_head)
    entry = sealed['entry']
    value = {'schema': SEALED_SCHEMA, 'interval': interval, 'entry': entry,
             'expected_catalog_digest': sealed['expected_catalog_digest'], 'runner_record_sha256': written['sha256']}
    path = sealed_record_path(store_directory, interval)
    record['sealed_awaiting_reader'] = {'path': str(path), 'sha256': write_durable(path, value)}
    save()
    return value


def preseal_or_review(preseal, *, seal_for_review, check):
    """bounded_preseal's evidence; on its refusal, or any checker defect, seal for review and raise.

    Memory exhaustion and cancellation are not checker verdicts: they propagate
    unsealed. ``check`` (the forced guard check) runs before any seal, so a live
    guard abort also stops here. ``seal_for_review(cause)`` writes the durable
    record and seals; if it fails, that failure propagates (a seal failure is fatal).
    """
    try:
        return preseal()
    except (MemoryError, CancelledError):
        raise
    except Exception as error:  # every checker refusal or defect is kept for review, then re-raised
        check()
        cause = _error(error)
        seal_for_review(cause)
        raise PresealSealedForReview('bounded pre-seal refused; the interval is sealed for review only: '
                                     + cause['message']) from error


def require_promoted_root(store, store_directory):
    runner, _, _ = _promoted_root(store, store_directory)
    return runner


def _promoted_root(store, store_directory):
    """Run B's precondition: the accepted catalog holds exactly run A's adopted root.

    The chain is run A's runner record -> its sealed record -> the reader's PASS
    verdict on that entry -> the accepted catalog entry.
    """
    runner = read_record(runner_record_path(store_directory, 0), schema=RUNNER_RECORD_SCHEMA)
    runner_sha = sha256(canonical(runner)).hexdigest()
    read_record(sealed_record_path(store_directory, 0), schema=SEALED_SCHEMA)
    verdict = read_record(verdict_path(store_directory, 0), schema=VERDICT_SCHEMA)
    return runner, runner_sha, verdict


def review_approval(store_directory, interval, approval_sha256, *, entry, verdict_sha256):
    """The conditions for adopting a review-only interval, all required.

    (a) the reader PASS on this exact file (the verdict, checked by the caller);
    (b) a written diagnosis showing a checker defect, not a data defect;
    (c) a recorded approval by a recognised approver naming the file SHA-256 and the verdict.
    A data-integrity cause is quarantined and never adopted: the interval is rerun after the fix.
    """
    approval = read_record(approval_path(store_directory, interval), schema=REVIEW_APPROVAL_SCHEMA,
                           expected_sha256=approval_sha256)
    require(approval.get('interval') == interval and approval.get('file_sha256') == entry['file_sha256'] and
            approval.get('verdict_sha256') == verdict_sha256 and approval.get('approver') in REVIEW_APPROVERS and
            type(approval.get('approved_at')) is str and approval['approved_at'],
            'review approval does not name this sealed file, its reader verdict and an approver')
    return approval


def _record_sha(value):
    return sha256(canonical(value)).hexdigest()


WIDTH_GATE_V1, WIDTH_GATE_V2 = 'atlas.exact-width-gate.v1', 'atlas.exact-width-gate.v2'
SEED_REUSED = ('FULL_REUSE', 'MISSES_MEASURED')
SEED_MISS = 'MISS_UNSEEDED'


def width_gate_passed(gate, k):
    """Interval k >= 1's durable width gate passed before k+1: v1 at k = 1, v2 for k at k >= 2."""
    return type(gate) is dict and gate.get('passed') is True and (
        gate.get('schema') == WIDTH_GATE_V1 and 'interval' not in gate
        if k == 1 else gate.get('schema') == WIDTH_GATE_V2 and gate.get('interval') == k and
        gate.get('next_interval') == k+1)


def interval_one_route(profile):
    """Where interval 2's gate finds interval 1's producer receipt: this profile's interval-1 output."""
    return {'output': mode_output(profile.record(), 'interval'), 'profile_sha256': profile.sha256,
            'diagnostic': diagnostic_tree(FreshSources(profile))}            # D-3: may it take an across capture


def diagnostic_tree(sources):
    """Whether this tree's profile is a diagnostic one (rulings 4a, 27: proof and real trees are not)."""
    return sources.profile.record()['qualification_status'] == DIAGNOSTIC


def _pin_sha(value):
    return value.get('sha256') if type(value) is dict else None


def _prior(ok, message, recorded, found):
    """Decision 289: a test of how an earlier producer ended. Refused as before unless the run records."""
    if not ok:
        require(recorded is not None, message)
        recorded.append('%s: %s' % (message, found))


def _recording(sources, asked):
    """The list recorded tests go to, or None. Only a diagnostic tree records (RFR's _recording)."""
    if not asked:
        return None
    require(diagnostic_tree(sources),
            '--record-failed-prior is for diagnostic trees only')
    return []


def _errors_text(errors):
    if type(errors) is not list:
        return repr(errors)
    return '; '.join('%s: %s' % (e.get('type'), e.get('message')) if type(e) is dict else repr(e) for e in errors)


def root_anchor(chain, interval_one, recorded=None):
    """Interval 2's gate: verdict(0) and adopted(0) as interval 1's seeded runner hashed them.

    adopted(1) (explicitly pinned) -> verdict(1).producer_receipt_sha256 -> interval 1's run.json,
    which must bind interval 1's runner and sealed records and be an ordinary completed producer
    (seed FULL_REUSE or MISSES_MEASURED, counts agreeing) or an approved review producer (seed
    still COPIED_BEFORE_ADMISSION), or in a diagnostic tree a seed miss (MISS_UNSEEDED: interval 1 measured
    everything, status and errors still tested). Its seed capture names run A's receipt and both root files'
    canonical SHA-256s. Without that capture (an unseeded interval 1) interval 2 refuses: today's
    root files are no anchor for themselves. The receipt is read again by every interval-2 gate,
    the reader's and finalise's included, so it must outlive interval 2's adoption.
    """
    root, first = chain[0], chain[1]
    path = Path(interval_one['output'])/'run.json'
    receipt = RUN.pinned_json(path, RUN._sha(first['verdict'].get('producer_receipt_sha256')), MAX_RECEIPT)
    require(type(receipt) is dict and receipt.get('schema') == RESULT_SCHEMA and receipt.get('mode') == 'interval' and
            receipt.get('interval') == 1 and receipt.get('profile_sha256') == interval_one['profile_sha256'] and
            _pin_sha(receipt.get('runner_record')) == first['link']['runner_sha256'] and
            _pin_sha(receipt.get('sealed_awaiting_reader')) == first['link']['sealed_sha256'] and
            receipt.get('production_acceptance') is False,
            "interval 1's producer receipt does not bind interval 1 of this lineage")
    _prior(receipt.get('final_reserved_bytes') == 0, "interval 1's producer receipt does not bind interval 1 of this lineage",
           recorded, 'final_reserved_bytes %r' % (receipt.get('final_reserved_bytes'),))
    reused, errors = receipt.get('reused_initial_cache'), receipt.get('errors')
    missed = interval_one['diagnostic'] is True and reused.get('status') == SEED_MISS   # anchored, unseeded
    if 'review_approval_sha256' in first['adopted']:
        pass
    else:
        _prior(receipt.get('status') == SEALED_STATUS['interval'], 'interval 1 is neither a completed nor an approved review producer with a valid seed capture',
               recorded, 'status %r' % (receipt.get('status'),))
        _prior(errors == [], 'interval 1 is neither a completed nor an approved review producer with a valid seed capture', recorded, 'errors '+_errors_text(errors))
    require((missed or reused.get('composition_equal') is True or             # D-3: or across a recorded change
             interval_one['diagnostic'] is True and type(reused.get('across_change')) is dict) and
            _pin_sha(reused.get('receipt')) == root['verdict'].get('producer_receipt_sha256') and
            reused.get('verdict_sha256') == root['link']['verdict_sha256'] and
            reused.get('adopted_sha256') == root['link']['adopted_sha256'],
            "run A's verdict or adoption differs from interval 1's seeded capture of them")


def sealed_lineage(store_directory, interval, parent_adopted_sha256, *, interval_one=None, recorded=None):
    """Item 21's gate for interval N >= 2, on records only, before the catalog opens.

    From the explicit adopted(N-1) pin down to the root, each interval k must have a runner
    record, its sealed record, the reader's PASS for exactly that entry and its adoption from
    exactly that verdict and runner record; a review-adopted k also needs its pinned approval,
    checked again. For k >= 2, runner(k) pins runner(k-1) and the adopted(k-1) file. Forward
    from the root, every k >= 1 extends k-1 of the same workflow and was sealed against the
    catalog digest adopting k-1 left. The catalog file must be the one adopting N-1 left.
    Every k >= 1 was read with its own width gate passed (v1 at k = 1, v2 for k at k >= 2),
    review-adopted or not: a failed gate stops the chain and is no parent here.
    verdict(0) and adopted(0) have no file pin in runner(1), which predates item 21. At N = 2
    root_anchor authenticates both against interval 1's seeded receipt (``interval_one``, from
    interval_one_route); from N = 3 the links 0..N-2 must equal runner(N-1)'s pinned lineage,
    which carries that capture forward. Returns the lineage record and its parents.
    """
    RUN._sha(parent_adopted_sha256)
    directory, pin, chain = Path(store_directory), parent_adopted_sha256, []
    for k in range(interval-1, -1, -1):
        adopted = read_record(adopted_path(directory, k), schema=ADOPTED_SCHEMA, expected_sha256=pin)
        runner = read_record(runner_record_path(directory, k), schema=RUNNER_RECORD_SCHEMA)
        sealed = read_record(sealed_record_path(directory, k), schema=SEALED_SCHEMA)
        verdict = read_record(verdict_path(directory, k), schema=VERDICT_SCHEMA)
        runner_sha, verdict_sha, entry = _record_sha(runner), _record_sha(verdict), sealed['entry']
        review = 'review_approval_sha256' in adopted
        link = {'interval': k, 'runner_sha256': runner_sha, 'sealed_sha256': _record_sha(sealed),
                'verdict_sha256': verdict_sha, 'adopted_sha256': _record_sha(adopted)}
        if review:
            approval = review_approval(directory, k, adopted['review_approval_sha256'], entry=entry,
                                       verdict_sha256=verdict_sha)
            link.update(review_approval_sha256=adopted['review_approval_sha256'],
                        diagnosis_sha256=approval['diagnosis']['sha256'])
        parents = [runner.get(name) for name in ('parent_runner_record_sha256', 'parent_adopted_sha256')]
        pin = parents[1]
        chain.append({'runner': runner, 'sealed': sealed, 'verdict': verdict, 'adopted': adopted, 'link': link})
    chain.reverse()
    root = chain[0]['runner']
    head = root['root']['root_key']
    for k in range(1, interval):
        runner, _ = chain[k]['runner'], chain[k-1]
        before, after = runner.get('previous_endpoint'), runner.get('advanced_endpoint')
        require(runner['workflow_id'] == root['workflow_id'] and
                runner.get('root_runner_record_sha256') == chain[0]['link']['runner_sha256'] and
                type(before) is dict and type(after) is dict and before.get('head') == head and
                before.get('intervals') == k-1 and after.get('intervals') == k and type(after.get('head')) is str and
                after['head'] != head, 'interval %d does not extend interval %d of this workflow' % (k, k-1))
        head = after['head']
    last = chain[-1]
    if interval == 2:
        root_anchor(chain, interval_one, recorded)
    else:
        recorded = last['runner'].get('lineage')
    lineage = {'schema': LINEAGE_SCHEMA, 'interval': interval-1, 'workflow_id': root['workflow_id'],
               'root_key': root['root']['root_key'], 'head_key': head,
               'catalog_digest': last['adopted']['catalog_digest'], 'catalog_sha256': last['adopted']['catalog_sha256'],
               'records': [item['link'] for item in chain]}
    return {'lineage': lineage, 'root_runner': root, 'parent_runner': last['runner'], 'parent_sealed': last['sealed'],
            'parent_verdict': last['verdict'], 'parent_adopted': last['adopted'],
            'parent_adopted_sha256': parent_adopted_sha256}


def measured_successor_workers(profile, lineage, number, selector, recorded=None, *, logical_budget_bytes):
    """Bind N>=2 worker selection to the adopted parent's exact producer receipt."""
    path = mode_output(profile.record(), 'interval', number-1)/'run.json'
    pin = RUN._sha(lineage['parent_verdict'].get('producer_receipt_sha256'))
    receipt = RUN.pinned_json(path, pin, MAX_RECEIPT)
    link = lineage['lineage']['records'][-1]
    require(type(receipt) is dict and receipt.get('schema') == RESULT_SCHEMA and
            receipt.get('mode') == 'interval' and receipt.get('interval') == number-1 and
            receipt.get('profile_sha256') == profile.sha256 and
            _pin_sha(receipt.get('runner_record')) == link['runner_sha256'] and
            _pin_sha(receipt.get('sealed_awaiting_reader')) == link['sealed_sha256'] and
            receipt.get('production_acceptance') is False,
            'parent worker receipt does not bind the adopted parent and current profile')
    _prior(receipt.get('final_reserved_bytes') == 0, 'parent worker receipt does not bind the adopted parent and current profile',
           recorded, 'final_reserved_bytes %r' % (receipt.get('final_reserved_bytes'),))
    if 'review_approval_sha256' in lineage['parent_adopted']:
        pass
    else:
        _prior(receipt.get('status') == SEALED_STATUS['interval'], 'parent worker receipt is neither complete nor an explicitly approved review producer',
               recorded, 'status %r' % (receipt.get('status'),))
        _prior(receipt.get('errors') == [], 'parent worker receipt is neither complete nor an explicitly approved review producer',
               recorded, 'errors '+_errors_text(receipt.get('errors')))
    parent = {'real_peak_bytes': receipt.get('resources', {}).get('sampled_peak_bytes', {}).get('parent_rss'),
              'logical_peak_bytes': receipt.get('logical_budget_final', {}).get('peak_reserved_bytes')}
    result = {'schema': selector.PARENT_SELECTION_SCHEMA,
              'parent_receipt': {'path': str(path), 'sha256': pin}, 'parent': parent,
              'decision': selector.select_composed(parent=parent, logical_budget_bytes=logical_budget_bytes)}
    selector.policy_from_selection(result)
    return result


def require_lineage_head(store, lineage):
    """After the catalog opens: it holds exactly the lineage's adopted interval N-1. Returns run A's runner record."""
    accepted, sealed = store.store_set.head, lineage['parent_sealed']
    require(store.store_set.catalog_digest == lineage['parent_adopted']['catalog_digest'] and accepted is not None and
            accepted.interval == lineage['lineage']['interval'] and accepted.to_wire() == sealed['entry'] and
            accepted.head.to_wire() == lineage['parent_runner']['head'] and
            store.workflow_id == lineage['root_runner']['workflow_id'],
            'interval N requires the accepted catalog to hold exactly the adopted interval N-1 of its lineage')
    return lineage['root_runner']


def measurement_composition(profile, *, execution_identity, interpreter_seed):
    """What a reusable initial measurement store is bound to (review condition 2).

    The profile pin, the execution identity, the driver's SHA-256 and the
    interpreter seed. Every run records it with its closed store; a seeded run B refuses
    unless run A's equals its own, field by field.
    """
    row = profile.record()
    return {'profile_sha256': profile.sha256, 'execution_identity': execution_identity,
            'advance_driver_sha256': row['advance_driver']['sha256'],
            'interpreter_seed': dict(interpreter_seed)}


def _sidecars(path):
    return [Path(str(path)+suffix).name for suffix in MEASUREMENT_SIDECARS if Path(str(path)+suffix).exists()]


def closed_measurement_store(artifacts, check=lambda: None):
    """One run's closed initial measurement store: file name, bytes and SHA-256; no sidecar may remain."""
    path = Path(artifacts)/MEASUREMENT_STORE
    size = RUN.ordinary(path).stat().st_size
    return {'filename': MEASUREMENT_STORE, 'bytes': size, 'sha256': RUN.file_hash(path, check)}


def observe_measurements(observed, closed=None):
    """The driver's ``measurements`` hook: counts only; nothing of the admission is kept.

    Each exterior cell carrying ``initial_accuracy`` is one cached_initial_component call
    (enclose_initial_partition), so one store lookup: a hit, or a miss that measured and put
    exactly one new snapshot (the store has no delete). The bounds record is parsed once per
    producer, transiently and unbooked (a few MB).
    """
    def observe(statistics, bounds):
        cells = bounds.record()['cells']
        observed.update(statistics={name: statistics[name] for name in MEASUREMENT_COUNTS},
                        initial_component_queries=sum('initial_accuracy' in cell for cell in cells))
        if closed is not None:
            closed()
    return observe


def measurement_record(artifacts, *, binding, observed, check=lambda: None):
    """Recorded only after the admission closed (review condition 1): the closed store, its binding, its counts.

    ``binding`` is measurement_composition's, recorded as the store's ``composition``.
    """
    return dict(closed_measurement_store(artifacts, check), composition=binding, **observed)


def _copy_pinned(source, target, pin, check):
    """Exclusive byte copy of a closed store whose SHA-256 is ``pin``; the copy is hashed once, against the pin."""
    found = _sidecars(source)
    require(not found, 'the seed store has a journal or WAL: '+', '.join(found))
    require(not target.exists() and not _sidecars(target), 'the seed target already exists: '+str(target))
    size = 0
    with RUN.ordinary(source).open('rb') as reader, target.open('xb') as writer:
        while block := reader.read(COPY_BLOCK):
            check()
            size += len(block)
            writer.write(block)
        writer.flush()
        os.fsync(writer.fileno())
    require(RUN.file_hash(target, check) == pin and not _sidecars(source),
            'the seed copy differs from the pinned SHA-256')
    return size


def seed_initial_measurements(seed, *, profile_sha256, root_runner, store_directory, root_output, artifacts,
                              binding, check=lambda: None, recorded=None, _promoted=None):
    """Item 7: copy run A's closed, pinned measurement store before this producer's admission.

    ``root_runner`` is require_promoted_root's: run A's root has its reader PASS for exactly
    its sealed entry, and the accepted catalog holds it. This also requires run A's adoption
    record after exactly that verdict, the receipt that reader passed (by SHA-256) holding a
    clean sealed root of this profile, the store that receipt names (by SHA-256) and an equal
    composition (``binding``, this run's measurement_composition). The copy is exclusive and
    fsynced, and both files are re-digested after it.
    Returns the reuse record; reuse_outcome adds the counts after the admission.
    """
    earlier = seed.get(SEED_ACROSS)                                     # D-3: across a recorded change
    expected_profile = profile_sha256 if earlier is None else earlier['sha256']
    receipt_sha256, pin = RUN._sha(seed['receipt_sha256']), RUN._sha(seed['store_sha256'])
    root_sha, verdict, adopted = _root_capture(store_directory, root_runner, _promoted)
    require((_promoted is not None or verdict['status'] == READER_PASS['root'] and
             verdict['runner_record_sha256'] == root_sha) and verdict['interval'] == 0 and
            verdict.get('producer_receipt_sha256') == receipt_sha256,
            'the seed receipt is not the run A receipt its reader passed')
    receipt_path = Path(root_output)/'run.json'
    receipt = RUN.pinned_json(receipt_path, receipt_sha256, MAX_RECEIPT)
    require(type(receipt) is dict and receipt.get('schema') == RESULT_SCHEMA and receipt.get('mode') == 'root' and
            receipt.get('profile_sha256') == expected_profile and receipt.get('pid') == root_runner['producer_pid'] and
            receipt.get('workflow_id') == root_runner['workflow_id'],
            'the seed receipt is not run A clean sealed root of this profile')
    _prior(receipt.get('status') == SEALED_STATUS['root'], 'the seed receipt is not run A clean sealed root of this profile', recorded, 'status %r' % (receipt.get('status'),))
    _prior(receipt.get('errors') == [], 'the seed receipt is not run A clean sealed root of this profile', recorded, 'errors '+_errors_text(receipt.get('errors')))
    stored = receipt.get('initial_measurement_store')
    theirs = stored.get('composition')
    differing = sorted(name for name in set(binding) | set(theirs)
                       if name not in theirs or name not in binding or theirs[name] != binding[name])
    across = None
    if earlier is None:
        require(not differing, 'run A measurement composition differs from this run: '+', '.join(differing))
    else:
        across = _across_change(theirs, binding, earlier['sha256'])
    source, target = Path(root_output)/MEASUREMENT_STORE, Path(artifacts)/MEASUREMENT_STORE
    started = time.monotonic()
    size = _copy_pinned(source, target, pin, check)
    return {'schema': SEED_SCHEMA, 'status': 'COPIED_BEFORE_ADMISSION', 'source': str(source), 'target': str(target),
            'pinned_sha256': pin, 'bytes': size, 'copy_seconds': time.monotonic()-started,
            **_anchor(receipt_path, receipt_sha256, verdict, adopted),
            'composition_equal': across is None or not across['differences'],
            **({} if across is None else {SEED_ACROSS: across}),
            'seed_snapshots': stored['statistics']['snapshots'],
            'seed_initial_component_queries': stored.get('initial_component_queries')}


def _root_capture(store_directory, root_runner, _promoted=None):
    """Run A's root runner SHA-256, reader verdict and adoption record: none of them depends on the seed."""
    if _promoted is None:
        root_sha = sha256(canonical(root_runner)).hexdigest()
        verdict = read_record(verdict_path(store_directory, 0), schema=VERDICT_SCHEMA)
    else:
        root_sha, verdict = _promoted
    return root_sha, verdict, read_record(Path(store_directory)/record_name('adopted', 0), schema=ADOPTED_SCHEMA)


def _anchor(receipt_path, receipt_sha256, verdict, adopted):
    """What interval 2's gate compares with run A's records (root_anchor), seeded or missed."""
    return {'receipt': {'path': str(receipt_path), 'sha256': receipt_sha256},
            'verdict_sha256': sha256(canonical(verdict)).hexdigest(),
            'adopted_sha256': sha256(canonical(adopted)).hexdigest()}


def _move_aside(target):
    """S-1: the copy target and its side files, renamed together under one dated name; nothing is deleted.
    A rename that fails puts back the ones done and refuses (review C-1: never a store beside a stale WAL)."""
    found = [path for path in (Path(target), *(Path(str(target)+s) for s in MEASUREMENT_SIDECARS)) if path.exists()]
    stamp, count = time.strftime('%Y%m%dT%H%M%SZ', time.gmtime()), 0
    aside = lambda path: path.with_name(path.name+'.aside-'+stamp+('' if count == 0 else f'-{count}'))
    while any(aside(path).exists() for path in found):
        count += 1
    done = []
    try:
        for path in found:
            os.replace(path, aside(path))
            done.append(path)
    except OSError as error:
        for path in reversed(done):
            os.replace(aside(path), path)
        require(False, 'the seed target could not be moved aside: '+str(error))
    return [{'from': str(path), 'to': str(aside(path))} for path in found]


def _seed_failure(seed, error, diagnostic, target, *, receipt_path, store_directory, root_runner, _promoted=None):
    """The record of a failed seed. A cancel or guard abort (CancelledError), or any failure outside a diagnostic
    tree, is the refusal it always was. A diagnostic failure is S1's miss: our partial copy goes (the target was
    moved aside before the call, so a file there now is ours) and run B starts unseeded, anchored when run A's
    records can be read."""
    if isinstance(error, CancelledError) or not diagnostic:
        return {'schema': SEED_SCHEMA, 'status': 'REFUSED_BEFORE_ADMISSION', 'requested': seed, 'refusal': _error(error)}
    Path(target).unlink(missing_ok=True)
    record = {'schema': SEED_SCHEMA, 'status': SEED_MISS, 'requested': seed, 'miss': _error(error)}
    try:
        _, verdict, adopted = _root_capture(store_directory, root_runner, _promoted)
        record.update(_anchor(receipt_path, RUN._sha(seed['receipt_sha256']), verdict, adopted))
    except Exception as anchor_error:  # noqa: BLE001 - recorded; interval 2 then refuses for run A's records
        if isinstance(anchor_error, CancelledError):
            raise
        record['anchor_missing'] = _error(anchor_error)
    return record


def _across_change(theirs, binding, earlier_sha256):
    """D-3: run A's composition against this run's across a recorded change, member by member."""
    unknown = sorted((set(theirs) ^ COMPOSITION) | (set(binding) ^ COMPOSITION))
    require(not unknown, 'run A measurement composition has members this run does not know: '+', '.join(unknown))
    require(theirs['interpreter_seed'] == binding['interpreter_seed'],
            'run A measurement composition differs from this run: interpreter_seed')
    require(theirs['profile_sha256'] == earlier_sha256, "run A measurement composition is not the earlier profile's")
    differences = [name for name in ('profile_sha256', 'execution_identity', 'advance_driver_sha256')
                   if theirs[name] != binding[name]]
    return {'earlier_profile_sha256': earlier_sha256, 'differences': differences}


def reuse_outcome(reused, measured):
    """A seeded admission's hits and misses (review condition 5); full reuse means unchanged bytes.

    Misses are the new snapshots (each miss measured and put exactly one, and the store has
    no delete); hits are the other lookups. A miss is a milestone, not a failure: exactness
    rests on each hit's consistency check, ROOT_IDENTITY and the independent reader.
    """
    queries = measured['initial_component_queries']
    misses = measured['statistics']['snapshots'] - reused['seed_snapshots']
    hits = queries - misses
    full = measured['sha256'] == reused['pinned_sha256']
    agree = misses >= 0 and hits >= 0 and (misses == 0) == full
    return dict(reused, status=('FULL_REUSE' if full else 'MISSES_MEASURED') if agree else 'COUNTS_DISAGREE_WITH_BYTES',
                initial_component_queries=queries, hits=hits, misses=misses, after_sha256=measured['sha256'],
                full_reuse=full, counts_agree_with_bytes=agree,
                chunk_reads=measured['statistics']['operations'].get('payload_reads'))


QUERY_STAGE_FIELDS = ('hits', 'misses', 'written', 'incomplete')
QUERY_SPLIT_FIELDS = ('hits_restart', 'hits_after_write', 'hits_warm')  # WP17 Tier 1 owners only


class QueryStages:
    """S1 (WP17 instrumentation): completed-query counts per guard stage; observation only.

    ContinuationGuard.phase() (private_heat_continuation_guard_r3.py) sets record['stage'],
    runs _sync() and then calls the runner's save(), so save() normally sees each stage
    change after that stage's last query. If _sync() raises, that save() is skipped; the
    next observation (a save(), an owner open or finish()) closes the stage instead.

    Each row holds, per counter, the sum over every completed-query owner open in the stage
    of that owner's exact counter deltas (record['completed_queries'] holds the last owner's
    totals only), ``unflushed`` as read when the row was last updated, and the owner opens
    (query_checkpoints calls) in the stage. A stage with no live owner has null counts,
    never 0. Nothing wraps the owner, the guard or a query; the guard's phase names and
    order are unchanged.

    Schema v2 adds the owner's hit split (QUERY_SPLIT_FIELDS, WP17 Tier 1) and its
    split_status to each row, summed the same way but only from an owner that
    has them: with an older owner they stay null and its opened_with entries keep
    the v1 shape. A split owner's opened_with entry also carries its split_status
    and entries_at_open.

    An Exception here is recorded (status INCOMPLETE, error) and stops only this
    observation; the rows keep the stages closed before it (recording failures stay
    diagnostic, as in dev_stage_timing). A BaseException (KeyboardInterrupt, SystemExit)
    is never swallowed: it may land between two updates of a row, so it is recorded the
    same way (the rows are then not trusted as COMPLETE) and re-raised. Either way the
    status is stored first, by a plain dict store with no call before it, so a second
    interrupt arriving while the failure is recorded cannot leave the rows unmarked.
    finish() closes the last row and sets status COMPLETE; observation stops there. A run
    killed hard never reaches finish(): its run.json keeps the rows of the stages closed
    by its last save(), with no status and no in-progress row.
    """

    def __init__(self, record):
        self.record, self.owner, self.base, self.stage = record, None, None, record.get('stage')
        self.value = record['completed_queries_by_stage'] = {
            'schema': 'atlas.completed-queries-by-stage.v2', 'fields': list(QUERY_STAGE_FIELDS+QUERY_SPLIT_FIELDS),
            'scope': ("per stage, the sum over every completed-query owner open in it of that owner's counter "
                      "deltas (completed_queries holds the last owner only); null outside an owner's life"),
            'rows': [], 'opened_with': []}
        self.row = self._new_row()

    def _new_row(self):
        return dict(stage=self.stage, opens=0, unflushed=None, split_status=None,
                    **dict.fromkeys(QUERY_STAGE_FIELDS+QUERY_SPLIT_FIELDS))

    @staticmethod
    def _counts(owner):
        counts = {name: getattr(owner, name) for name in QUERY_STAGE_FIELDS}
        if hasattr(owner, 'split_status'):  # a Tier 1 owner: its split is read as strictly
            counts.update({name: getattr(owner, name) for name in QUERY_SPLIT_FIELDS})
        return counts

    def _accumulate(self):
        # Every read and sum first, then one update: a failed read leaves the row as it was.
        if self.owner is not None:
            now, unflushed = self._counts(self.owner), getattr(self.owner, 'unflushed', 0)
            sums = {name: (self.row[name] or 0)+now[name]-self.base[name] for name in now}
            # A later open cannot make an earlier truncated contribution complete.
            split = {}
            if 'hits_warm' in now:
                status = self.owner.split_status
                if self.row['split_status'] == 'TRUNCATED':
                    status = 'TRUNCATED'
                split['split_status'] = status
            self.row.update(sums, unflushed=unflushed, **split)
            self.base = now

    def _observe(self):
        stage = self.record.get('stage')
        if stage != self.stage:
            self._accumulate()
            self.value['rows'].append(self.row)
            self.stage = stage
            self.row = self._new_row()

    def _stop(self, error):
        self.owner = self.base = None
        self.value.update(status='INCOMPLETE', error=type(error).__name__+': '+str(error)[:256])

    def _safely(self, step):
        if 'status' in self.value:  # finished (COMPLETE) or failed (INCOMPLETE): observation has stopped
            return
        try:
            step()
        except Exception as error:  # noqa: BLE001 - instrumentation never fails the run
            self.value['status'] = 'INCOMPLETE'  # first, with no call before it: see the class docstring
            self._stop(error)
        except BaseException as error:
            # An interrupt may have landed between two updates of a row: mark the rows, stop, re-raise.
            self.value['status'] = 'INCOMPLETE'  # first, with no call before it: see the class docstring
            self._stop(error)
            raise

    def observe(self):
        self._safely(self._observe)

    def opened(self, owner):
        def step():
            self._observe()
            base = self._counts(owner)
            self.owner, self.base = owner, base
            opened = dict(stage=self.stage, **base)
            if 'hits_warm' in base:
                opened.update(split_status=owner.split_status, entries_at_open=getattr(owner, 'entries_at_open', None))
            self.value['opened_with'].append(opened)
            self.row.update({name: self.row[name] or 0 for name in base}, opens=self.row['opens']+1)
        self._safely(step)

    def closed(self, owner):
        def step():
            self._accumulate()
            self.owner = self.base = None
        self._safely(step)

    def finish(self):
        def step():
            self._observe()
            self._accumulate()
            self.owner = self.base = None
            self.value['rows'].append(self.row)
            self.row = None
            self.value['status'] = 'COMPLETE'
        self._safely(step)


@contextmanager
def completed_queries(owner_type, directory, *, declared, arguments, execution, budget, cancel, limits, record,
                      save, query_stages=None):
    """The declared completed-query owner; flush() BEFORE its counts are recorded.

    Held queries are acknowledged in ``written`` only by their commit, so counts
    recorded before flush() would miss the last batch.
    An owner without flush() predates batching: every query it acknowledges is
    already durable, which the record says. A flush failure during another
    failure is attached to that failure as a note, never raised in its place; on
    the success path it is raised.
    """
    with owner_type(directory, context=execution, budget=budget, cancel=cancel,
                    max_store_bytes=limits['max_store_bytes'], max_entries=limits['max_entries'],
                    **arguments) as owner:
        flush = getattr(owner, 'flush', None)
        if query_stages is not None:
            query_stages.opened(owner)
        try:
            yield owner
        finally:
            active = sys.exception()
            try:
                if flush is not None:
                    flush()
            except BaseException as flush_error:
                if active is None:
                    raise
                active.add_note('Completed-query flush also failed: '+repr(flush_error))
            finally:
                if query_stages is not None:
                    query_stages.closed(owner)
                record['completed_queries'] = {
                    'directory': str(directory), 'store': declared, 'arguments': arguments,
                    'hits': owner.hits, 'misses': owner.misses, 'written': owner.written,
                    'incomplete': owner.incomplete, 'unflushed': getattr(owner, 'unflushed', 0),
                    'hits_restart': getattr(owner, 'hits_restart', None),
                    'hits_after_write': getattr(owner, 'hits_after_write', None),
                    'hits_warm': getattr(owner, 'hits_warm', None),
                    'split_status': getattr(owner, 'split_status', None),
                    'entries_at_open': getattr(owner, 'entries_at_open', None),
                    'flush': 'flushed before recording' if flush is not None else 'serial store holds none',
                    'scope': 'validated completed queries only; strict current execution binding'}
                save()


@contextmanager
def _focused_capture(artifacts):
    """Expose the selected directory for the lifetime of the focused capture."""
    variable = 'ATLAS_FOCUSED_ARTIFACT_DIR'
    previous = os.environ.get(variable)
    os.environ[variable] = str(RUN.ordinary(artifacts, directory=True))
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop(variable, None)
        else:
            os.environ[variable] = previous


def _store_configuration(store):
    require(asdict(store.limits) == RUN.COMPACT_STORE_LIMITS and asdict(store.compression) == RUN.COMPACT_COMPRESSION,
            'compact runtime storage configuration differs from reviewed bounds')


def run_fresh_interval(profile, *, sources, guard, record, save, mode, stop_before_advance=False, seed=None,
                       start_gate=None, query_stages=None, interval=None, parent_adopted_sha256=None,
                       recorded=None, require_heat_pool=False):
    """Run A or run B under the selected pinned sources and the live external guard.

    ``stop_before_advance`` (run B only, the smoke): stop after the adopted root is
    reopened and compared; interval 1 is never begun. ``seed`` (run B only, item 7): run A's
    receipt and measurement-store SHA-256s; see seed_initial_measurements. ``start_gate``: the launcher's
    start_gate decision (encoded), admitted again here against this process's free memory.
    ``interval`` and ``parent_adopted_sha256`` (item 21): run B of interval N >= 2 from exactly that
    adopted(N-1) file; see sealed_lineage. Neither is derived here.
    """
    require(type(profile) is FreshProfile and type(sources) is FreshSources and sources.profile is profile and
            mode in MODES, 'actual pinned sources and a route (1) mode required')
    number = interval_number(mode, interval)
    parent_adopted_sha256 = parent_pin(number, parent_adopted_sha256)
    require(SEED_ENVIRONMENT not in os.environ or diagnostic_tree(sources),
            'measurement seeds are explicit arguments only: '+SEED_ENVIRONMENT+' is refused')
    if SEED_ENVIRONMENT in os.environ:   # a diagnostic tree reports it and carries on: it is never read
        print(SEED_ENVIRONMENT+' is set and ignored: measurement seeds are explicit arguments only', flush=True)
    row = profile.record()
    bound = {name: sources.module(name) for name in (DRIVER, *FRESH_MODULES)}
    FRESH, CRS, PRESEAL = bound[DRIVER], bound['compact_restart_store'], bound['bounded_preseal']
    from atlas_tectonics.integration.endpoint_checkpoints import EndpointCheckpoints
    from atlas_tectonics.integration.resources import WorkBudget
    declared = sources.query_store()
    query_arguments = query_store_arguments(EndpointCheckpoints, declared)
    record['completed_query_store'] = {'declared': declared, 'arguments': query_arguments}
    m = composition(sources)
    record.update(RUN.interpreter_gate(), mode=mode, interval=number)
    output = mode_output(row, mode, interval)
    store_directory = Path(row['store_directory'])
    catalog = store_directory/CATALOG
    limits = row['completed_query_limits']
    available = MONITOR.free_memory()
    admitted = SG.child_admit(start_gate, available)
    selected_limits = SG.guard_limits(admitted)
    guard.budget = budget = WorkBudget(selected_limits['logical_budget_bytes'], max_predicate_work_units=1 << 44)
    RUN._guard_boundary(sources, guard, budget, limits=selected_limits)
    check = lambda: guard.check(force=True)
    check()
    from atlas_tectonics.integration.reuse import execution_identity
    execution = execution_identity('scipy')
    identities = {'producer_identity': profile.sha256, 'runtime_identity': execution}
    record.update(guard_limits=selected_limits, start_gate=admitted,
                  memory_at_start=dict(available_bytes=admitted['available_bytes']), identities=identities,
                  completed_query_limits=dict(limits), production_acceptance=False)
    binding = measurement_composition(profile, execution_identity=execution, interpreter_seed=record['interpreter_seed'])
    observed = {}
    _publish = bound['private_heat_continuation_guard_r3']._write   # the package's atomic JSON write (temporary, os.replace)

    def publish_store():    # once, when the admission has closed its store (N6)
        record['initial_measurement_store'] = measurement_record(output, binding=binding, observed=observed,
                                                                 check=check)
        save()
        _publish(output/MEASUREMENT_RECORD, record['initial_measurement_store'])  # whole file, then renamed in
    measurements = observe_measurements(observed, closed=publish_store)
    RUN.ordinary(store_directory.parent, directory=True)
    with RUN.retained_run(budget, record) as scope:
        if mode == 'root':
            if store_directory.exists():
                # A protected pre-root restart may leave the persistent publisher lock.
                lock = store_directory/(CATALOG+'.lock')
                require(diagnostic_tree(sources)
                        and set(store_directory.iterdir()) == {lock} and RUN.ordinary(lock).read_bytes() == b'\0',
                        'run A requires a new store or a diagnostic store with only its persistent catalog lock')
            else:
                store_directory.mkdir()

            @contextmanager
            def open_store(workflow_id):
                record['workflow_id'] = workflow_id
                with CRS.CompactRestartStore.create_migration(catalog, workflow_id=workflow_id, scope=scope,
                                                              **identities) as store:
                    _store_configuration(store)
                    yield store

            def finish_root(_workflow, store, root):
                record['published_root'] = root
                RUN.storage_point(record, 'root-published', checkpoint=catalog, store=store)
                save()
                guard.phase('seal-root-awaiting-reader')
                return seal_with_records(store, root['root_key'], store_directory=store_directory, interval=0,
                    identities=identities, record=record, save=save,
                    extra={'workflow_id': root['workflow_id'], 'root': root, 'producer_pid': os.getpid()})
            with _focused_capture(output):
                record['sealed'] = FRESH.create_root(m, open_store=open_store, budget=budget, artifacts=output,
                                                     phase=guard.phase, finish_root=finish_root,
                                                     measurements=measurements)
            record.update(same_process_cold_reopen=False, same_process_cold_reopen_reason=ROOT_REOPEN_DEFERRED)
            save()
        else:
            query_directory = sources.workspace/row['completed_query_directory']
            RUN.ordinary(query_directory.parent, directory=True)
            query_directory.mkdir(exist_ok=True)
            lineage = None
            if number >= 2:
                guard.phase('sealed-lineage-gate')
                lineage = sealed_lineage(store_directory, number, parent_adopted_sha256,
                                         interval_one=interval_one_route(profile) if number == 2 else None,
                                         recorded=recorded)
                record['lineage'] = lineage['lineage']
                lineage['worker_selection'] = measured_successor_workers(
                    profile, lineage, number, bound['interface_worker_selection'], recorded=recorded,
                    logical_budget_bytes=selected_limits['logical_budget_bytes'])
                record['interface_worker_selection'] = lineage['worker_selection']
                save()
            with CRS.CompactRestartStore.open_catalog(catalog, scope=scope) as store:
                _store_configuration(store)
                promoted = None
                if lineage is None:
                    root_runner, root_sha, verdict = _promoted_root(store, store_directory)
                    promoted = root_sha, verdict
                else:
                    root_runner = require_lineage_head(store, lineage)
                    root_sha = lineage['lineage']['records'][0]['runner_sha256']
                reused = None
                if seed is not None:
                    guard.phase('seed-initial-measurements')
                    diagnostic = diagnostic_tree(sources)
                    if diagnostic and (moved := _move_aside(output/MEASUREMENT_STORE)):
                        record['moved_aside'] = moved
                        save()
                        print('seed target moved aside: '+', '.join(m['from']+' -> '+m['to'] for m in moved), flush=True)
                    try:
                        reused = seed_initial_measurements(seed, profile_sha256=profile.sha256,
                            root_runner=root_runner, store_directory=store_directory,
                            root_output=mode_output(row, 'root'), artifacts=output, binding=binding, check=check,
                            recorded=recorded, _promoted=promoted)
                    except Exception as error:  # noqa: BLE001 - recorded; a diagnostic one is a miss (S1)
                        record['reused_initial_cache'] = _seed_failure(seed, error, diagnostic, output/MEASUREMENT_STORE,
                            receipt_path=mode_output(row, 'root')/'run.json', store_directory=store_directory,
                            root_runner=root_runner, _promoted=promoted)
                        save()
                        if record['reused_initial_cache']['status'] != SEED_MISS:
                            raise
                        print('seed miss: '+str(error)+'; starting unseeded (recompute)', flush=True)
                    else:
                        record['reused_initial_cache'] = reused
                        save()
                if stop_before_advance:
                    # The smoke: run B's chain, catalog and admission, then the adopted root
                    # reopened and compared. No candidate is begun; nothing of interval 1 runs.
                    guard.phase('reopen-adopted-root-stop-before-advance')
                    with _focused_capture(output):
                        record['root_reproduced'] = FRESH.reopen_root(m, store=store,
                            expected_root=root_runner['root'], budget=budget, artifacts=output, phase=guard.phase,
                            measurements=measurements)
                    record.update(stop_before_advance=True, compact_operations=store.statistics())
                else:
                    record['sealed'] = _advance(record=record, save=save, guard=guard, store=store, m=m, FRESH=FRESH,
                        PRESEAL=PRESEAL, sources=sources, root_runner=root_runner, root_runner_sha256=root_sha,
                        identities=identities,
                        budget=budget, output=output, catalog=catalog, query_directory=query_directory,
                        store_directory=store_directory, check=check, query_stages=query_stages,
                        number=number, lineage=lineage, query_store=(EndpointCheckpoints, declared,
                        query_arguments, limits), measurements=measurements,
                        **({'require_heat_pool': True} if require_heat_pool else {}))
                    record['compact_operations'] = store.statistics()
                if reused is not None:
                    record['reused_initial_cache'] = reuse_outcome(reused, record['initial_measurement_store'])
                save()
        profiling.checkpoint('sealed-awaiting-reader' if not stop_before_advance else 'stopped-before-advance')
    record['store_directory_after_close'] = RUN._tree(store_directory)
    return budget


def _advance(*, record, save, guard, store, m, FRESH, PRESEAL, sources, root_runner, root_runner_sha256,
             identities, budget, output, catalog, query_directory, store_directory, check, query_store,
             measurements=None, query_stages=None, number=1, lineage=None,
             require_heat_pool=False):
    """Run B's interval: begin interval ``number``, advance once, then the post-advance protocol with the workflow open.

    Interval 1 advances from the adopted root; interval N >= 2 from the adopted interval N-1 of
    ``lineage`` (sealed_lineage's result), whose runner record and adoption its own record pins.
    """
    owner_type, declared, query_arguments, limits = query_store
    end_provider_factory = None
    if lineage is None:
        from atlas_tectonics._private.integration.geometry.endpoint_factory import make_factory
        qualification = Path(os.environ['ATLAS_REAL_INPUT_QUALIFICATION'])
        def note_q297_provider(selection):
            record['q297_end_geometry'].update(selection='issued for actual END mesh', **selection)
            save()
        end_provider_factory = make_factory(run_root=qualification/'runs',
            grid_path=qualification/'iv1-diagnostic-prep/landing-gp-r1/successor-grid.json',
            selected_observer=note_q297_provider)
        record['q297_end_geometry'] = dict(selection='configured first-interval END provider',
            scientific_changes=True, grid_sha256='0afc36b4b7e13d2422b34c02ea1704b099c062101e793344223ed6109939871f',
            sweep_payload_sha256='290d83c1afc94a0917078b01175d0f5aa3ee18edb8561d373a9d311de054accc',
            carry_proof_sha256='cae83be7428db8c3a7a9a48bfcb0ab9e1c870c9949dbaf585c911c3ded70fc93',
            inherited_witness_refinements=1, qualification_grid_split='-33/8',
            graph_id='not yet issued', scientifically_certified=False)
        save()
    store.start_next_interval(**identities)
    profiling.checkpoint('parent-store-next-interval-begun')

    def query_checkpoints(execution):
        return completed_queries(owner_type, query_directory, declared=declared, arguments=query_arguments,
                                 execution=execution, budget=budget, cancel=check, limits=limits, record=record,
                                 save=save, query_stages=query_stages)

    def finish(workflow, *, before, after, parent, root_bytes):
        RUN._successor_checks(workflow, store=store, before=before, parent=parent,
                                        root_bytes=root_bytes, budget=budget)
        record.update(advanced_endpoint=after, previous_endpoint=before,
                      successor_checks=list(RUN.SUCCESSOR_CHECKS), same_process_cold_reopen=False,
                      same_process_cold_reopen_reason=RUN.SAME_PROCESS_REOPEN_DROPPED)
        # What the publication kept: R2's adopted token, R3's heat-checkpoint token decision
        # ({token_kept, reason, rows}; absent unless R3 is composed) and the end mesh's
        # supports (shared or copied, with the copy's bytes and booking; G-R3-1 (b')).
        published = getattr(workflow, '_published_identity', None) or {}
        record['publication'] = {'token_adopted': published.get('token_adopted'),
                                 'r3_heat_checkpoint': getattr(workflow, '_r3_heat_checkpoint', None),
                                 'end_mesh_supports': list(sources.module('publish_mesh_patch').END_MESH_SUPPORTS)}
        base = {'workflow_id': after['workflow_id'], 'advanced_endpoint': after, 'previous_endpoint': before,
                'producer_pid': os.getpid(), 'root_runner_record_sha256': root_runner_sha256}
        if lineage is not None:
            base.update(parent_runner_record_sha256=lineage['lineage']['records'][-1]['runner_sha256'],
                        parent_adopted_sha256=lineage['parent_adopted_sha256'], lineage=lineage['lineage'])

        def seal_for_review(cause):
            record['preseal_refused'] = cause
            save()
            guard.phase('seal-interval-for-review')
            sealed = seal_with_records(store, after['head'], store_directory=store_directory, interval=number,
                identities=identities, record=record, save=save,
                extra=dict(base, preseal_refused=cause, review_only=True))
            entry = sealed['entry']
            record['review_only'] = {'state': REVIEW_STATUS, 'cause': cause, 'adoption': REVIEW_ADOPTION,
                'sealed_file': {k: entry[k] for k in ('filename', 'file_sha256', 'logical_seal')}}
            save()
        # R2 option A: bounded pre-seal checks of this unsealed interval
        # only; the independent reader re-derives the rest on the sealed file.
        evidence = preseal_or_review(lambda: PRESEAL.bounded_preseal(workflow, store=store, before=before,
            after=after, budget=budget, cancel=check), seal_for_review=seal_for_review, check=check)
        identities_record = evidence.pop('record_identities')
        # Unit A: the widths from the publication's renders. Its identities are not compared with
        # identities_record at run time (ruling 4d; test T-9).
        from atlas_tectonics._private.integration import width_gate as WG   # function-local: not a pressure-startup module
        widths = WG.producer_widths(workflow, store, number)
        record.update(record_identities=identities_record, preseal_bounded_check=evidence, **widths)
        RUN.storage_point(record, 'after-advance', checkpoint=catalog, query_directory=query_directory, store=store)
        save()
        guard.phase('seal-interval-awaiting-reader')
        return seal_with_records(store, after['head'], store_directory=store_directory, interval=number,
            identities=identities, record=record, save=save,
            extra=dict(base, record_identities=identities_record, **widths))
    RUN.storage_point(record, 'before-advance', checkpoint=catalog, query_directory=query_directory, store=store)
    save()
    # SL-D2: the pose memo carried between interval processes, beside the store folder, never inside it
    # (the store is sealed, measured and read by a separate reader). No input to any result. The first
    # interval starts empty (D-2).
    from atlas_tectonics.integration.geometry import wall_measures    # function-local, as width_gate below
    memo_path = store_directory.with_name(wall_measures.pose_memo_name(store_directory.name))
    held = frozenset() if lineage is None else wall_measures.load_pose_memo(memo_path)
    guard.phase('advance-exactly-one-fresh-interval')
    # Unit A: the publications inside the advance enter their proofs for finish's width pass.
    from atlas_tectonics._private.integration import width_gate as WG       # function-local: not a pressure-startup module
    with _focused_capture(output), WG.collect_proofs(store):
        if lineage is None:
            sealed = FRESH.advance_first_interval(m, store=store, expected_root=root_runner['root'], budget=budget,
                artifacts=output, phase=guard.phase, guard=guard, record=record, save=save,
                query_checkpoints=query_checkpoints, finish=finish, measurements=measurements,
                end_geometry_provider_factory=end_provider_factory,
                **({'require_heat_pool': True} if require_heat_pool else {}))
        else:
            sealed = FRESH.advance_successor_interval(m, store=store, expected_root=root_runner['root'],
                lineage=lineage['lineage'], budget=budget, artifacts=output, phase=guard.phase, guard=guard,
                record=record, save=save, query_checkpoints=query_checkpoints, finish=finish,
                measurements=measurements, worker_selection=lineage['worker_selection'])
        # Only this process's entries: the loaded, older histories can no longer be a prefix.
        wall_measures.save_pose_memo(memo_path, held)    # not in a finally: a failed advance saves nothing
        return sealed


def final_status(errors, mode, record=None):
    # A sealed file is never an interval result until the reader passed and it was adopted.
    if record is not None and record.get('review_only'):
        return REVIEW_STATUS
    if errors:
        return 'FAILED'
    return STOPPED_STATUS if record is not None and record.get('stop_before_advance') else SEALED_STATUS[mode]


def _seed(seed, mode):
    """An explicit measurement seed: run B only, exactly its two SHA-256 pins; across a recorded change also the
    earlier profile by path and SHA-256 (D-3)."""
    if seed is None:
        return None
    out = {name: RUN._sha(seed[name]) for name in sorted(SEED_FIELDS)}
    if SEED_ACROSS in seed:
        earlier = seed[SEED_ACROSS]
        out[SEED_ACROSS] = {'path': earlier['path'], 'sha256': RUN._sha(earlier['sha256'])}
    return out


def _require_heat_pool_route(enabled, *, number, seed, stop_before_advance):
    require(type(enabled) is bool, 'require-heat-pool flag must be boolean')
    if enabled:
        require(number == 1 and seed is not None and SEED_ACROSS in seed and not stop_before_advance,
                '--require-heat-pool needs a strict diagnostic first interval with a prior-profile seed')


# Inserted before run_fresh_interval.command; only stdlib and existing RUN used.
def pressure_launch_environment(environ=None):
    values = os.environ if environ is None else environ
    result = {key: value for key, value in values.items() if not key.upper().startswith('PYTHON')}
    result.update(PYTHONHASHSEED='0', PYTHONDONTWRITEBYTECODE='1',
                  OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1')
    return result


@protect_profile
def command(profile, python, *, mode, stop_before_advance=False, seed=None, start_gate=None,
            interval=None, parent_adopted_sha256=None, record_failed_prior=False,
            open_proofs=False, run_profile=frozenset(), require_heat_pool=False, _sources=None):
    """Inspectable guarded command only; never launches or reads a store. ``start_gate`` goes last."""
    number = interval_number(mode, interval)
    pin = parent_pin(number, parent_adopted_sha256)
    seed = _seed(seed, mode)
    sources = FreshSources(profile) if _sources is None else _sources
    _require_heat_pool_route(require_heat_pool, number=number, seed=seed, stop_before_advance=stop_before_advance)
    if require_heat_pool:
        require(diagnostic_tree(sources), '--require-heat-pool needs a diagnostic first interval')
    row = profile.record()
    output = mode_output(row, mode, interval)
    RUN.ordinary(output.parent, directory=True)
    guard = sources.path(row['modules']['private_heat_continuation_guard_r3'])
    return [str(RUN.ordinary(python)), '-B', str(guard), '--launch', '--output', str(output/'run.json'), '--',
            str(RUN.ordinary(python)), '-B', '-s', '-P', str(Path(__file__).resolve()),
            '--workload',
            '--profile', str(profile.path), '--profile-sha256', profile.sha256, '--mode', mode,
            *profiling.profile_words(run_profile),
            *(['--seed-receipt-sha256', seed['receipt_sha256'], '--seed-store-sha256', seed['store_sha256']]
              if seed else []),
            *(['--reuse-previous-run', seed[SEED_ACROSS]['path'], '--reuse-previous-run-sha256',
               seed[SEED_ACROSS]['sha256']] if seed and SEED_ACROSS in seed else []),
            *(['--stop-before-advance'] if stop_before_advance else []),
            *(['--require-heat-pool'] if require_heat_pool else []),
            *(['--interval', str(number), '--parent-adopted-sha256', pin] if number >= 2 else []),
            *(['--record-failed-prior'] if record_failed_prior else []),
            *(['--open-proofs'] if open_proofs else []),
            *([SG.ARGUMENT, SG.encode(start_gate)] if start_gate is not None else [])]


def _error(error):
    origin = first_raised(error)
    selected = None
    trace = origin.__traceback__
    while trace is not None:
        code = trace.tb_frame.f_code
        if 'atlas_tectonics' in code.co_filename.replace('\\', '/'):
            selected = {'file': code.co_filename, 'function': code.co_name, 'line': trace.tb_lineno}
        trace = trace.tb_next
    return {'type': type(error).__name__, 'message': str(error),
            'first_raised': {'type': type(origin).__name__, 'message': str(origin)},
            'innermost_selected_frame': selected}


def _heat_faces(folder, sources):
    """U-2 (designs/step5-save-as-it-goes-r1.md s3): the heat pool of this process saves its faces in ``folder`` and a
    later run of the same call takes them. Diagnostic trees only, as _recording: a proof or real run has no such
    manifest. Returns the folder, or None (the variable is then unset, whatever was given)."""
    variable = 'ATLAS_HEAT_FACES_DIR'
    os.environ.pop(variable, None)
    if not diagnostic_tree(sources):
        return None
    os.environ[variable] = str(folder)
    return folder


@protect_profile
def _workload(profile, *, mode, stop_before_advance=False, seed=None, start_gate=None,
              interval=None, parent_adopted_sha256=None, record_failed_prior=False,
              open_proofs=False, run_profile=frozenset(), require_heat_pool=False):
    if open_proofs:    # proof mode, on before anything is opened, never off
        from atlas_tectonics._private.codecs import compact_contracts
        compact_contracts.open_proofs = True
    seed = _seed(seed, mode)
    number = interval_number(mode, interval)
    parent_adopted_sha256 = parent_pin(number, parent_adopted_sha256)
    sources = FreshSources(profile)
    _require_heat_pool_route(require_heat_pool, number=number, seed=seed, stop_before_advance=stop_before_advance)
    recorded = _recording(sources, record_failed_prior)
    if seed is not None and SEED_ACROSS in seed:                # D-3: diagnostic trees only; the earlier profile by its pin
        FreshProfile.read(Path(seed[SEED_ACROSS]['path']), seed[SEED_ACROSS]['sha256'])
    row = profile.record()
    output = mode_output(row, mode, interval)/'run.json'
    home = Path(row['output_directory']).parent
    if profiling.stacks_enabled(run_profile):
        profiling.start_stacks(home/'profile-stacks', mode)
    _heat_faces(home/'completed-heat', sources)
    record: dict = {'schema': RESULT_SCHEMA, 'status': 'STARTED', 'pid': os.getpid(), 'mode': mode,
                    'profile_sha256': profile.sha256, 'errors': [], 'production_acceptance': False,
                    'stop_before_advance': stop_before_advance, 'initial_measurement_seed': seed,
                    'open_proofs': open_proofs, 'run_mode': 'debug' if run_profile else 'release',
                    **({'profile_tree': 'profile-tree.raw'} if 'tree' in run_profile else {})}
    guard = budget = None
    # The supervisor has already claimed sidecars. Receipt creation is exclusive.
    with output.open('x', encoding='utf8') as stream:
        json.dump(record, stream)
    G = sources.module('private_heat_continuation_guard_r3')
    query_stages = QueryStages(record)

    def save():
        query_stages.observe()
        G._write(output, record)
    try:
        guard = G.ContinuationGuard(output, record, save, **SG.child_limits(start_gate))
        record_stages = 'stages' in run_profile
        with profiling.collect(guard, output.parent, enabled=record_stages, record=record,
                            metadata={'profile_sha256': profile.sha256, 'mode': mode}):
            budget = run_fresh_interval(profile, sources=sources, guard=guard, record=record, save=save, mode=mode,
                                        stop_before_advance=stop_before_advance, seed=seed,
                                        start_gate=start_gate, query_stages=query_stages,
                                        interval=interval, parent_adopted_sha256=parent_adopted_sha256,
                                        recorded=recorded, require_heat_pool=require_heat_pool)
        record['status'] = 'VERIFYING_FINALISATION'
    except BaseException as error:  # noqa: BLE001 - every failure, guard aborts included, is recorded in run.json
        record['status'] = 'FAILED'
        record['errors'].append(_error(error))
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
            if guard is not None:
                guard.check(force=True)
                guard.close()
        except BaseException as error:  # noqa: BLE001 - a finalisation failure is recorded, never lost
            record['errors'].append(_error(error))
        query_stages.finish()
        if recorded:
            record['recorded'] = recorded
        record['status'] = final_status(record['errors'], mode, record)
        save()
    return 0 if not record['errors'] else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', type=Path, required=True)
    parser.add_argument('--profile-sha256', required=True)
    parser.add_argument('--mode', choices=MODES, required=True)
    parser.add_argument('--run-profile', default='off')
    parser.add_argument('--profile-tool', type=Path, help='with --run-profile tree: the sampling profiler executable')
    parser.add_argument('--stop-before-advance', action='store_true', help='run B only: the smoke, never interval 1')
    parser.add_argument('--require-heat-pool', action='store_true',
                        help='defer a matched ordinary interval if fewer than two heat workers are configured')
    parser.add_argument('--seed-receipt-sha256', help='run B only, with --seed-store-sha256: run A receipt (item 7)')
    parser.add_argument('--seed-store-sha256', help='run B only: the measurement store SHA-256 run A recorded')
    parser.add_argument('--reuse-previous-run', help='run B with a seed, diagnostic only: the earlier profile (D-3)')
    parser.add_argument('--reuse-previous-run-sha256', help='with --reuse-previous-run: its SHA-256')
    parser.add_argument('--interval', type=int, help='run B only, item 21: the interval N >= 2 to seal')
    parser.add_argument('--parent-adopted-sha256', help='with --interval N >= 2: the adopted(N-1) file SHA-256')
    parser.add_argument('--open-proofs', action='store_true',
                        help='proof mode: the open of an adopted head proves what it loads (decision 542)')
    parser.add_argument('--record-failed-prior', action='store_true',
                        help='diagnostic trees only: record how an earlier producer ended (decision 289)')
    action = parser.add_mutually_exclusive_group()
    action.add_argument('--launch', action='store_true')
    action.add_argument('--workload', action='store_true')
    parser.add_argument(SG.ARGUMENT, dest='start_gate', help='the launcher\'s start gate decision (--workload)')
    SG.add_arguments(parser)
    args = parser.parse_args(argv)
    run_profile = profiling.profile_selection(args.run_profile)
    if not args.workload:
        profiling.profile_tool(run_profile, args.profile_tool)
    require((args.seed_receipt_sha256 is None) == (args.seed_store_sha256 is None),
            'a measurement seed needs both its receipt and store SHA-256')
    seed = (None if args.seed_receipt_sha256 is None else
            {'receipt_sha256': args.seed_receipt_sha256, 'store_sha256': args.seed_store_sha256})
    require((args.reuse_previous_run is None) == (args.reuse_previous_run_sha256 is None) and
            (args.reuse_previous_run is None or seed is not None),
            'the earlier profile needs its path, its SHA-256 and a measurement seed (D-3)')
    if args.reuse_previous_run is not None:
        seed[SEED_ACROSS] = {'path': args.reuse_previous_run, 'sha256': args.reuse_previous_run_sha256}
    gate_args = bool(args.peak_records) or args.booking_bytes is not None or args.booking_basis is not None
    SG.require(args.start_gate is None or args.workload, SG.ARGUMENT+' is the guarded child\'s argument only')
    SG.require(not (gate_args and args.workload), 'the start gate is decided by whoever launches, not the child')
    # Decided before anything is read or made; a launch always needs one, a printed command only if asked.
    gate = (SG.stage_decision(SG.stage_key(args.mode, interval_number(args.mode, args.interval)),
                              records=args.peak_records,
                              booking_bytes=args.booking_bytes, booking_basis=args.booking_basis)
            if args.launch or gate_args else None)
    profile = FreshProfile.read(args.profile, args.profile_sha256)
    with admitted((profile.record()['store_directory'],)):
        if args.workload:
            return _workload(profile, mode=args.mode, stop_before_advance=args.stop_before_advance,
                             seed=seed, start_gate=args.start_gate, interval=args.interval,
                             parent_adopted_sha256=args.parent_adopted_sha256,
                             record_failed_prior=args.record_failed_prior, open_proofs=args.open_proofs,
                             run_profile=run_profile, require_heat_pool=args.require_heat_pool)
        argv = command(profile, sys.executable, mode=args.mode,
                       stop_before_advance=args.stop_before_advance, seed=seed, start_gate=gate, interval=args.interval,
                       parent_adopted_sha256=args.parent_adopted_sha256,
                       record_failed_prior=args.record_failed_prior, open_proofs=args.open_proofs,
                       run_profile=run_profile, require_heat_pool=args.require_heat_pool)
        output = mode_output(profile.record(), args.mode, args.interval)
        argv = profiling.profile_command(run_profile, argv, raw_path=output/'profile-tree.raw',
                                         executable=args.profile_tool)
        print(json.dumps({'status': 'SOURCE_BOUND_COMMAND_ONLY_NOT_ADMISSION', 'command': argv,
                          'production_acceptance': False}), flush=True)
        if not args.launch:
            return 0
        SG.admit(gate, MONITOR.free_memory())
        output.mkdir(exist_ok=False)
        return subprocess.call(argv, env=pressure_launch_environment(), cwd=output)


if __name__ == '__main__':
    raise SystemExit(main())
