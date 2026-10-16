"""Route (1) fresh-start runner: run A (the root) and run B (interval 1).

Each run ends in a Step 9(a) seal (option B, coordinator approval 16 Oct 2026):
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

The guard, gates, retained scope, storage points and successor checks are
run_prepared_restart's. The launcher takes the head and both identities from
the runner record, never from its own arguments (storage chat, 16 Oct 2026);
without that record a sealed file can only be quarantined. Every refusal is
recorded with its first-raised exception.
"""
import argparse
import gc
import inspect
import json
import os
import shutil
import subprocess
import sys
from concurrent.futures import CancelledError
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path

import run_prepared_restart as RUN

PROFILE_SCHEMA = 'atlas.fresh-interval-profile.v1'
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
# Coordinator, 16 Oct 2026: the composition declares its completed-query store
# in the pinned source manifest. WP17's batched columnar store is used only when
# declared (Step 10 enables it after its durability refuter runs clean), else the
# file store; a declared store the runtime lacks refuses, never a silent fallback.
# flush() precedes the recorded counts with either store.
QUERY_STORE_FLAG = 'completed_query_store'
QUERY_STORES = {'columnar': {'storage': 'columnar', 'batch_entries': 128, 'batch_seconds': 10},
                'files': {'storage': 'files'}}
# Route (1) helpers, bound to reviewed paths before any work; the driver is
# bound separately, as advance_driver.
# The joined helper is r8 (G-R3-1 (b'), 16 Oct 2026): its end mesh is compact and unpublished
# (publish_mesh_patch), and _publish publishes it after its partition.
FRESH_MODULES = ('prepared_interval_driver', 'probe_heat_original_connected_r9',
                 'private_heat_original_spatial_r1', 'private_heat_original_joined_r8',
                 'private_heat_joined_consumer_r6', 'private_heat_geometry_observer_r1',
                 'i04_differential_fixture', 'i04_differential_modes', 'test_i04_differential_force',
                 'compact_restart_store', 'compact_restart_patch', 'bounded_preseal', 'reopen_prepared_restart',
                 'content_cache', 'historical_admission', 'private_heat_continuation_guard_r3',
                 'windows_workload_job', 'private_heat_resource_diagnostics_r1', 'dev_stage_timing',
                 'publish_mesh_patch')
WORKFLOW_ENTRY_POINTS = ('create', 'open', '_identity', '_exterior_inputs')
ROOT_REOPEN_DEFERRED = 'Step 9(a): the independent fresh-process reader reopens the sealed root before promotion'
# Coordinator, 16 Oct 2026 (piece 3): a bounded pre-seal refusal costs a review, not the
# interval's compute. The candidate is still sealed (sealing accepts nothing), the runner
# record names the refusal and the state is REVIEW_STATUS. Nothing in that state is ever
# adopted automatically: reopen_fresh_restart.adopt needs the reader's PASS on that file,
# a written diagnosis showing a checker (not data) defect, and a recorded approval. A data
# integrity cause means quarantine and a rerun. A failure of the seal itself stays fatal.
REVIEW_STATUS = 'FAILED_PRESEAL_SEALED_FOR_REVIEW'
REVIEW_ADOPTION = ('never automatic: the reader PASS on this file, a written diagnosis showing a checker '
                   'defect and a recorded approval naming the file SHA-256 and the verdict are all required')


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


def mode_output(row, mode):
    require(mode in MODES, 'explicit route (1) mode required')
    return Path(row['output_directory'])/('run-'+mode)


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
        fields = {'schema', 'workspace', 'source_manifest', 'native_root', 'import_roots', 'modules',
                  'advance_driver', 'output_directory', 'store_directory', 'completed_query_directory',
                  'completed_query_limits'}
        require(type(row) is dict and set(row) == fields and row['schema'] == PROFILE_SCHEMA,
                'closed reviewed fresh-interval profile required')
        require(type(row['modules']) is dict and set(row['modules']) == set(FRESH_MODULES),
                'complete explicit route (1) helper bindings required')
        manifest, driver = row['source_manifest'], row['advance_driver']
        require(type(manifest) is dict and set(manifest) == {'path', 'sha256'},
                'explicit path and source pin required: source_manifest')
        RUN._sha(manifest['sha256'])
        require(type(driver) is dict and set(driver) == {'module', 'path', 'sha256'} and driver['module'] == DRIVER,
                'the route (1) driver binding is exactly fresh_interval_driver')
        RUN._sha(driver['sha256'])
        require(type(row['import_roots']) is list and row['import_roots'], 'explicit import roots required')
        output = RUN.canonical_absolute(row['output_directory'], 'attempt output directory')
        store = RUN.canonical_absolute(row['store_directory'], 'compact store directory')
        require(not any(store.is_relative_to(output/('run-'+mode)) for mode in MODES) and
                not output.is_relative_to(store), 'the store directory must outlive both run outputs')
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
    """RestartSources' import fence and pins, for a route (1) profile."""

    def __init__(self, profile):
        require(type(profile) is FreshProfile, 'typed pinned fresh-interval profile required')
        profile.verify()
        self.profile = profile
        row = profile.record()
        self.workspace = RUN.ordinary(row['workspace'], directory=True)
        self.native_root = self.path(row['native_root'], directory=True)
        self.import_roots = tuple(self.path(p, directory=True) for p in row['import_roots'])
        self.manifest_path = self.path(row['source_manifest']['path'])
        self.manifest_pin = row['source_manifest']['sha256']
        manifest = RUN.pinned_json(self.manifest_path, self.manifest_pin)
        require(type(manifest.get('files')) is dict and manifest['files'] and
                type(manifest.get('source_hashes')) is dict and manifest['source_hashes'],
                'whole native inventory and all participating helpers required')
        require(type(manifest.get('data_only')) is dict and not set(manifest['data_only']) & set(manifest['files']),
                'explicit data-only references disjoint from importable sources required')
        require(manifest.get(QUERY_STORE_FLAG) in QUERY_STORES,
                'the composition must declare its completed-query store: columnar or files')
        self._manifest = canonical(manifest)
        self.selected_now = False
        self._sealed = True

    def query_store(self):
        """The completed-query store the pinned composition declares."""
        return RUN._json(self._manifest)[QUERY_STORE_FLAG]

    def verify(self):
        """RestartSources.verify without the migrated route's preparation and policy pins."""
        self.profile.verify()
        observed = RUN.pinned_json(self.manifest_path, self.manifest_pin)
        require(canonical(observed) == self._manifest, 'in-memory source manifest differs from its pinned record')
        manifest = RUN._json(self._manifest)
        for name, pin in manifest['files'].items():
            require(RUN.file_hash(self.path(name)) == RUN._sha(pin), 'participating source changed: '+name)
        for name, pin in manifest['data_only'].items():
            require(RUN.file_hash(self.path(name)) == RUN._sha(pin), 'data-only reference changed: '+name)
        actual = {p.relative_to(self.native_root).as_posix(): RUN.file_hash(p)
                  for p in sorted((self.native_root/'atlas_tectonics').rglob('*.py'))}
        require(actual and actual == manifest['source_hashes'], 'complete native package inventory changed')
        for name, pin in actual.items():
            relative = (self.native_root/name).relative_to(self.workspace).as_posix()
            require(manifest['files'].get(relative) == pin, 'native source absent from import closure')
        row = self.profile.record()
        for name in row['modules'].values():
            require(name in manifest['files'], 'route (1) helper missing from the source closure: '+name)
        require(manifest['files'].get(row['advance_driver']['path']) == row['advance_driver']['sha256'],
                'route (1) driver absent from the source closure')
        for own in (Path(__file__).resolve(), Path(RUN.__file__).resolve()):
            require(own.is_relative_to(self.workspace) and
                    manifest['files'].get(own.relative_to(self.workspace).as_posix()) == RUN.file_hash(own),
                    'route (1) runner and its shared orchestration must be pinned: '+own.name)
        return {'source_manifest_sha256': self.manifest_pin,
                'native_source_digest': sha256(canonical(actual)).hexdigest()}


def query_store_arguments(owner_type, declared):
    """Constructor arguments of the declared completed-query store; refuses before any work.

    A runtime whose owner predates the storage choice has only the file store, so
    'files' passes no storage argument there and the owner's default is checked.
    """
    require(declared in QUERY_STORES, 'the composition must declare its completed-query store: columnar or files')
    try:
        parameters = set(inspect.signature(owner_type).parameters)
    except (TypeError, ValueError):
        parameters = set()
    if declared == 'columnar':
        require(set(QUERY_STORES['columnar']) <= parameters and callable(getattr(owner_type, 'flush', None)),
                'the composition declares the WP17 columnar store but the selected runtime lacks it')
        return dict(QUERY_STORES['columnar'])
    return dict(QUERY_STORES['files']) if 'storage' in parameters else {}


def composition(sources):
    """The module namespace fresh_interval_driver reads: r9's modules with the r7 joined helper."""
    from types import SimpleNamespace

    from atlas_tectonics import integration_differential_geometry as G
    from atlas_tectonics import integration_parallel_profile as PF
    from atlas_tectonics.integration_parallel_selection import InterfaceParallelPolicy
    from atlas_tectonics.integration_regional_workflow import CollarWorkflow
    from atlas_tectonics.reuse import ExecutionContext
    from atlas_tectonics.storage import ArrayStore, Compression, StoreLimits
    from threadpoolctl import threadpool_limits
    module = sources.module
    require(all(callable(getattr(CollarWorkflow, name, None)) for name in WORKFLOW_ENTRY_POINTS),
            'the selected runtime lacks the fresh-root workflow entry points')
    return SimpleNamespace(
        ExecutionContext=ExecutionContext, ArrayStore=ArrayStore, StoreLimits=StoreLimits, Compression=Compression,
        radial_differential_fixture=module('i04_differential_fixture').radial_differential_fixture,
        spatial=module('private_heat_original_spatial_r1'), D=module('probe_heat_original_connected_r9'),
        J=module('private_heat_joined_consumer_r6'), Workflow=CollarWorkflow,
        joined=module('private_heat_original_joined_r8'),
        check_initial_pressure_force=module('test_i04_differential_force').check_initial_pressure_force,
        ACTUATED_CONTROL=module('i04_differential_modes').ACTUATED_CONTROL,
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
    candidate = store.candidate
    require(candidate is not None and candidate.producer_identity == identities['producer_identity'] and
            candidate.runtime_identity == identities['runtime_identity'],
            'runner identities differ from the candidate being sealed')
    written = {}

    def record_head(head):
        value = {**extra, 'schema': RUNNER_RECORD_SCHEMA, 'interval': interval, 'head': head, **identities}
        path = runner_record_path(store_directory, interval)
        written['sha256'] = write_durable(path, value)
        record['runner_record'] = {'path': str(path), 'sha256': written['sha256']}
        save()
    sealed = store.seal_pending(head_key, record_head=record_head)
    entry = sealed['entry']
    require(entry['interval'] == interval and entry['producer_identity'] == identities['producer_identity'] and
            entry['runtime_identity'] == identities['runtime_identity'],
            'sealed entry differs from the runner record identities')
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
    """Run B's precondition: the accepted catalog holds exactly run A's adopted root.

    The chain is run A's runner record -> its sealed record -> the reader's PASS
    verdict on that entry -> the accepted catalog entry. Returns the runner record.
    """
    runner = read_record(runner_record_path(store_directory, 0), schema=RUNNER_RECORD_SCHEMA)
    runner_sha = sha256(canonical(runner)).hexdigest()
    sealed = read_record(sealed_record_path(store_directory, 0), schema=SEALED_SCHEMA)
    verdict = read_record(verdict_path(store_directory, 0), schema=VERDICT_SCHEMA)
    require(sealed['runner_record_sha256'] == runner_sha and sealed['interval'] == runner['interval'] == 0,
            'run A sealed record does not bind its runner record')
    require(verdict['status'] == READER_PASS['root'] and verdict['interval'] == 0 and
            verdict['runner_record_sha256'] == runner_sha and verdict['entry'] == sealed['entry'],
            'run A root has no independent reader PASS for exactly its sealed entry')
    accepted = store.store_set.head
    require(accepted is not None and accepted.interval == 0 and accepted.to_wire() == sealed['entry'] and
            accepted.head.to_wire() == runner['head'] and store.workflow_id == runner['workflow_id'],
            'run B requires the accepted catalog to hold exactly run A adopted root')
    return runner


@contextmanager
def completed_queries(owner_type, directory, *, declared, arguments, execution, budget, cancel, limits, record,
                      save):
    """The declared completed-query owner; flush() BEFORE its counts are recorded.

    Held queries are acknowledged in ``written`` only by their commit, so counts
    recorded before flush() would miss the last batch (coordinator, 16 Oct 2026).
    An owner without flush() predates batching: every query it acknowledges is
    already durable, which the record says. A flush failure during another
    failure is attached to that failure as a note, never raised in its place; on
    the success path it is raised.
    """
    with owner_type(directory, context=execution, budget=budget, cancel=cancel,
                    max_store_bytes=limits['max_store_bytes'], max_entries=limits['max_entries'],
                    **arguments) as owner:
        require(getattr(owner, 'storage', 'files') == QUERY_STORES[declared]['storage'],
                'completed-query owner differs from the declared store')
        flush = getattr(owner, 'flush', None)
        require(declared == 'files' or callable(flush), 'a batched completed-query store must flush')
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
                record['completed_queries'] = {
                    'directory': str(directory), 'store': declared, 'arguments': arguments,
                    'hits': owner.hits, 'misses': owner.misses, 'written': owner.written,
                    'incomplete': owner.incomplete, 'unflushed': getattr(owner, 'unflushed', 0),
                    'flush': 'flushed before recording' if flush is not None else 'serial store holds none',
                    'scope': 'validated completed queries only; strict current execution binding'}
                save()


@contextmanager
def _focused_capture(artifacts, fence):
    """run_prepared_restart._advance_checked's capture directory and import fences."""
    variable = 'ATLAS_FOCUSED_ARTIFACT_DIR'
    previous = os.environ.get(variable)
    fence()
    os.environ[variable] = str(RUN.ordinary(artifacts, directory=True))
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop(variable, None)
        else:
            os.environ[variable] = previous
    fence()


def _store_configuration(store):
    require(asdict(store.limits) == RUN.COMPACT_STORE_LIMITS and asdict(store.compression) == RUN.COMPACT_COMPRESSION,
            'compact runtime storage configuration differs from reviewed bounds')


def run_fresh_interval(profile, *, sources, guard, record, save, mode, stop_before_advance=False):
    """Run A or run B under the selected pinned sources and the live external guard.

    ``stop_before_advance`` (run B only, the smoke): stop after the adopted root is
    reopened and compared; interval 1 is never begun.
    """
    require(type(profile) is FreshProfile and type(sources) is FreshSources and sources.profile is profile and
            sources.selected_now and mode in MODES, 'actual selected pinned sources and a route (1) mode required')
    require(type(stop_before_advance) is bool and (mode == 'interval' or not stop_before_advance),
            'stop-before-advance applies to run B only')
    row = profile.record()
    bound = {name: sources.module(name) for name in (DRIVER, *FRESH_MODULES)}
    FRESH, CRS, PRESEAL = bound[DRIVER], bound['compact_restart_store'], bound['bounded_preseal']
    H, timing = bound['historical_admission'], bound['dev_stage_timing']
    from atlas_tectonics.integration_endpoint_checkpoints import EndpointCheckpoints
    from atlas_tectonics.resources import WorkBudget
    from atlas_tectonics.reuse import require_strict_execution
    declared = sources.query_store()
    query_arguments = query_store_arguments(EndpointCheckpoints, declared)
    record['completed_query_store'] = {'declared': declared, 'arguments': query_arguments}
    m = composition(sources)
    require_strict_execution()
    record.update(RUN.interpreter_gate(), mode=mode, interval=INTERVALS[mode])
    output = mode_output(row, mode)
    store_directory = Path(row['store_directory'])
    require(RUN.ordinary(output, directory=True) == output and output.is_relative_to(sources.workspace) and
            guard.output == output/'run.json', 'guard and fresh run output directory differ')
    catalog = store_directory/CATALOG
    limits = row['completed_query_limits']
    import psutil
    available = psutil.virtual_memory().available
    require(available >= RUN.START_BYTES, 'a route (1) run requires 10 GiB available at startup')
    guard.budget = budget = WorkBudget(RUN.LOGICAL_BYTES, max_predicate_work_units=1 << 44)
    RUN._guard_boundary(sources, guard, budget)
    check = lambda: guard.check(force=True)
    H._loaded_source_fence(FRESH, row['advance_driver']['sha256'], check)
    proof = sources.verify()
    identities = {'producer_identity': profile.sha256, 'runtime_identity': proof['native_source_digest']}
    record.update(guard_limits={'rss_bytes': RUN.RSS_BYTES, 'free_floor_bytes': RUN.FREE_BYTES,
                                'start_available_bytes': RUN.START_BYTES, 'logical_budget_bytes': RUN.LOGICAL_BYTES},
                  memory_at_start={'available_bytes': available}, source_proof=proof, identities=identities,
                  completed_query_limits=dict(limits), production_acceptance=False)
    RUN.ordinary(store_directory.parent, directory=True)
    require(shutil.disk_usage(store_directory.parent).free >= RUN.COMPACT_STORE_LIMITS['max_store_bytes'] +
            RUN.COMPACT_STORE_LIMITS['max_staging_bytes'] + limits['max_store_bytes'],
            'insufficient disk headroom for the interval file, its staging and the query quota')
    with RUN.retained_run(budget, record) as scope:
        if mode == 'root':
            require(not store_directory.exists(), 'run A requires a new store directory')
            store_directory.mkdir()

            @contextmanager
            def open_store(workflow_id):
                record['workflow_id'] = workflow_id
                with CRS.CompactRestartStore.create_migration(catalog, workflow_id=workflow_id, scope=scope,
                                                              **identities) as store:
                    _store_configuration(store)
                    yield store

            def finish_root(_workflow, store, root):
                sources.check_imported()
                record['published_root'] = root
                RUN.storage_point(record, 'root-published', checkpoint=catalog, store=store)
                save()
                guard.phase('seal-root-awaiting-reader')
                return seal_with_records(store, root['root_key'], store_directory=store_directory, interval=0,
                    identities=identities, record=record, save=save,
                    extra={'workflow_id': root['workflow_id'], 'root': root, 'producer_pid': os.getpid()})
            with _focused_capture(output, sources.check_imported):
                record['sealed'] = FRESH.create_root(m, open_store=open_store, budget=budget, artifacts=output,
                                                     phase=guard.phase, finish_root=finish_root)
            record.update(same_process_cold_reopen=False, same_process_cold_reopen_reason=ROOT_REOPEN_DEFERRED)
        else:
            query_directory = sources.workspace/row['completed_query_directory']
            RUN.ordinary(query_directory.parent, directory=True)
            require(query_directory.resolve().is_relative_to(sources.workspace) and
                    not query_directory.is_relative_to(Path(row['output_directory'])),
                    'explicit reusable completed-query directory must be outside this attempt')
            query_directory.mkdir(exist_ok=True)
            with CRS.CompactRestartStore.open_catalog(catalog, scope=scope) as store:
                _store_configuration(store)
                root_runner = require_promoted_root(store, store_directory)
                if stop_before_advance:
                    # The smoke: run B's chain, catalog and admission, then the adopted root
                    # reopened and compared. No candidate is begun; nothing of interval 1 runs.
                    guard.phase('reopen-adopted-root-stop-before-advance')
                    with _focused_capture(output, sources.check_imported):
                        record['root_reproduced'] = FRESH.reopen_root(m, store=store,
                            expected_root=root_runner['root'], budget=budget, artifacts=output, phase=guard.phase)
                    record.update(stop_before_advance=True, compact_operations=store.statistics())
                else:
                    record['sealed'] = _advance(record=record, save=save, guard=guard, store=store, m=m, FRESH=FRESH,
                        PRESEAL=PRESEAL, sources=sources, root_runner=root_runner, identities=identities,
                        budget=budget, output=output, catalog=catalog, query_directory=query_directory,
                        store_directory=store_directory, check=check, query_store=(EndpointCheckpoints, declared,
                        query_arguments, limits))
                    record['compact_operations'] = store.statistics()
        timing.checkpoint('sealed-awaiting-reader' if not stop_before_advance else 'stopped-before-advance')
    record['store_directory_after_close'] = RUN._tree(store_directory)
    sources.check_imported()
    sources.verify()
    timing.checkpoint('sources-verified')
    return budget


def _advance(*, record, save, guard, store, m, FRESH, PRESEAL, sources, root_runner, identities, budget, output,
             catalog, query_directory, store_directory, check, query_store):
    """Run B's interval: begin interval 1, advance once, then the post-advance protocol with the workflow open."""
    owner_type, declared, query_arguments, limits = query_store
    store.start_next_interval(**identities)

    def query_checkpoints(execution):
        return completed_queries(owner_type, query_directory, declared=declared, arguments=query_arguments,
                                 execution=execution, budget=budget, cancel=check, limits=limits, record=record,
                                 save=save)

    def finish(workflow, *, before, after, parent, root_bytes):
        sources.check_imported()
        checked = RUN._successor_checks(workflow, store=store, before=before, parent=parent,
                                        root_bytes=root_bytes, budget=budget)
        require(checked == after, 'live successor differs from the driver endpoint')
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
                'producer_pid': os.getpid(), 'root_runner_record_sha256': sha256(canonical(root_runner)).hexdigest()}

        def seal_for_review(cause):
            record['preseal_refused'] = cause
            save()
            guard.phase('seal-interval-for-review')
            sealed = seal_with_records(store, after['head'], store_directory=store_directory, interval=1,
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
        record.update(record_identities=identities_record, preseal_bounded_check=evidence)
        RUN.storage_point(record, 'after-advance', checkpoint=catalog, query_directory=query_directory, store=store)
        save()
        guard.phase('seal-interval-awaiting-reader')
        return seal_with_records(store, after['head'], store_directory=store_directory, interval=1,
            identities=identities, record=record, save=save, extra=dict(base, record_identities=identities_record))
    RUN.storage_point(record, 'before-advance', checkpoint=catalog, query_directory=query_directory, store=store)
    save()
    guard.phase('advance-exactly-one-fresh-interval')
    with _focused_capture(output, sources.check_imported):
        return FRESH.advance_first_interval(m, store=store, expected_root=root_runner['root'], budget=budget,
            artifacts=output, phase=guard.phase, guard=guard, record=record, save=save,
            query_checkpoints=query_checkpoints, finish=finish)


def final_status(errors, mode, record=None):
    # A sealed file is never an interval result until the reader passed and it was adopted.
    if record is not None and record.get('review_only'):
        return REVIEW_STATUS
    if errors:
        return 'FAILED'
    return STOPPED_STATUS if record is not None and record.get('stop_before_advance') else SEALED_STATUS[mode]


def command(profile, python, *, mode, dev_timing=False, stop_before_advance=False):
    """Inspectable guarded command only; never launches or reads a store."""
    require(type(dev_timing) is bool, 'dev timing flag must be boolean')
    require(type(stop_before_advance) is bool and (mode == 'interval' or not stop_before_advance),
            'stop-before-advance applies to run B only')
    sources = FreshSources(profile)
    sources.verify()
    row = profile.record()
    output = mode_output(row, mode)
    RUN.ordinary(output.parent, directory=True)
    require(output.is_relative_to(sources.workspace) and not output.exists(), 'exclusive new run output directory required')
    guard = sources.path(row['modules']['private_heat_continuation_guard_r3'])
    return [str(RUN.ordinary(python)), '-B', str(guard), '--launch', '--output', str(output/'run.json'), '--',
            str(RUN.ordinary(python)), '-B', str(Path(__file__).resolve()), '--workload',
            '--profile', str(profile.path), '--profile-sha256', profile.sha256, '--mode', mode,
            *(['--dev-timing'] if dev_timing else []), *(['--stop-before-advance'] if stop_before_advance else [])]


def _error(error):
    origin = first_raised(error)
    return {'type': type(error).__name__, 'message': str(error),
            'first_raised': {'type': type(origin).__name__, 'message': str(origin)}}


def _workload(profile, *, mode, dev_timing=False, stop_before_advance=False):
    dev_timing = RUN._dev_timing_enabled(dev_timing)
    require(sys.dont_write_bytecode, 'run with -B to preserve frozen sources')
    sources = FreshSources(profile)
    output = mode_output(profile.record(), mode)/'run.json'
    record: dict = {'schema': RESULT_SCHEMA, 'status': 'STARTED', 'pid': os.getpid(), 'mode': mode,
                    'profile_sha256': profile.sha256, 'errors': [], 'production_acceptance': False,
                    'stop_before_advance': stop_before_advance}
    guard = budget = None
    # The supervisor has already claimed sidecars. Receipt creation is exclusive.
    with output.open('x', encoding='utf8') as stream:
        json.dump(record, stream)
    with sources.selected():
        G = sources.module('private_heat_continuation_guard_r3')
        timing = sources.module('dev_stage_timing')
        dev_timing = timing.enabled(dev_timing)
        save = lambda: G._write(output, record)
        try:
            guard = G.ContinuationGuard(output, record, save)
            with timing.collect(guard, output.parent, enabled=dev_timing, record=record,
                                metadata={'profile_sha256': profile.sha256, 'mode': mode}):
                budget = run_fresh_interval(profile, sources=sources, guard=guard, record=record, save=save, mode=mode,
                                            stop_before_advance=stop_before_advance)
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
                sources.check_imported()
                sources.verify()
                if guard is not None:
                    guard.check(force=True)
                    guard.close()
            except BaseException as error:  # noqa: BLE001 - a finalisation failure is recorded, never lost
                record['errors'].append(_error(error))
            record['status'] = final_status(record['errors'], mode, record)
            save()
    return 0 if not record['errors'] else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', type=Path, required=True)
    parser.add_argument('--profile-sha256', required=True)
    parser.add_argument('--mode', choices=MODES, required=True)
    parser.add_argument('--dev-timing', action='store_true', help='opt-in development timing and memory diagnostics')
    parser.add_argument('--stop-before-advance', action='store_true', help='run B only: the smoke, never interval 1')
    action = parser.add_mutually_exclusive_group()
    action.add_argument('--launch', action='store_true')
    action.add_argument('--workload', action='store_true')
    args = parser.parse_args(argv)
    dev_timing = RUN._dev_timing_enabled(args.dev_timing)
    profile = FreshProfile.read(args.profile, args.profile_sha256)
    if args.workload:
        return _workload(profile, mode=args.mode, dev_timing=dev_timing, stop_before_advance=args.stop_before_advance)
    argv = command(profile, sys.executable, mode=args.mode, dev_timing=dev_timing,
                   stop_before_advance=args.stop_before_advance)
    print(json.dumps({'status': 'SOURCE_BOUND_COMMAND_ONLY_NOT_ADMISSION', 'command': argv,
                      'production_acceptance': False}), flush=True)
    if not args.launch:
        return 0
    import psutil
    require(psutil.virtual_memory().available >= RUN.START_BYTES, 'a route (1) run requires 10 GiB available')
    output = mode_output(profile.record(), args.mode)
    output.mkdir(exist_ok=False)
    return subprocess.call(argv, env=RUN.launch_environment(), cwd=output)


if __name__ == '__main__':
    raise SystemExit(main())
