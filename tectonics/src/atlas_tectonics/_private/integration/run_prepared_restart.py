"""Guarded, source-selected restart orchestration; no default production profile.

A reviewed enclosing launcher must pin the profile AND this source. A supplied
hash identifies bytes, not review authority. The profile names the final composed
package/helpers and a separately reviewed runtime-compatibility policy. This
module never writes that policy, accepts JSON PASS as admission, imports an old
runtime, funds initial material or resets state. No production run is implied by
the focused fixture tests.

The named driver must export advance_prepared_interval with keyword arguments
case, workflow, base, execution, guard, record, save, artifacts, query_checkpoints. Its return value
is deliberately ignored: exact structural one-successor checks on the live
workflow and the persisted store metadata establish that one interval was
persisted. By owner decision the runner no longer cold-reopens the
successor in this process; the mandatory independent fresh-process reader
(reopen_prepared_restart.py) performs that cold reopen. The published migrated
root is still cold-reopened here before any advance. The retained H
probe_heat_original_continue_r9.py nested second() is the implementation seam;
its old ordinary-root _validate_continuation is NOT a migrated-root validator.
case['state'] is the authenticated frozen initial workload (initial_workload.py)
and must reproduce the authenticated first-interval duration before the driver.

CLI inspection reads small source/configuration files only. --launch is explicit
and uses the unchanged external Windows-job guard. No profile is shipped here:
composition, compatibility review and compact reader integration remain owners'
work. A completed workload is still PENDING_INDEPENDENT_REOPEN, never accepted;
--stop-before-advance ends at STOPPED_BEFORE_ADVANCE_ROOT_PUBLISHED, never PASS.
"""
from contextlib import contextmanager, nullcontext
from dataclasses import asdict, dataclass
from hashlib import sha256
import argparse
import gc
import importlib
import inspect
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys


if __name__ == '__main__' and Path(__file__).resolve().parent.parts[-3:] == ('atlas_tectonics', '_private', 'integration'):
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    __package__ = 'atlas_tectonics._private.integration'


from atlas_shared.errors import AtlasError
from atlas_shared.execution import profiling
from atlas_tectonics._private.integration import start_gate as SG
from atlas_tectonics._private.integration import route2_gate as RG
from atlas_shared.machine import resources_monitor as MONITOR
from atlas_shared.machine import resources_gate as GATE

PROFILE_SCHEMA = 'atlas.prepared-restart-launch.v3'
RESULT_SCHEMA = 'atlas.prepared-restart-result.v1'
PASS_STATUS = 'PASS_ONE_INTERVAL_PENDING_INDEPENDENT_REOPEN'
STOPPED_STATUS = 'STOPPED_BEFORE_ADVANCE_ROOT_PUBLISHED'
MAX_CONFIG = 8 << 20
HISTORICAL_SOURCE_MANIFEST_SHA256 = 'f81fd25ca3b68d031b006a0e6eab4d6b278affa86e5d062baeafd748f17ee42c'
# Seed and thread settings are fixed at interpreter start; workers inherit them.
LAUNCH_ENV = dict(OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1', PYTHONHASHSEED='0',
                  PYTHONDONTWRITEBYTECODE='1')
REQUIRED_MODULES = ('native_transfer', 'spatial_transfer', 'geometry_transfer',
    'workflow_transfer', 'historical_admission', 'runtime_compatibility',
    'materialise_endpoint', 'plan_preparation', 'private_heat_continuation_guard_r3',
    'windows_workload_job', 'private_heat_resource_diagnostics_r1', 'initial_workload',
    'funding_transfer', 'continuation_transfer', 'compact_store', 'mesh_tables',
    'spatial_indexed_patch', 'spatial_workflow_patch', 'partition_tables', 'partition_store',
    'partition_workflow_patch', 'partition_native_patch', 'partition_routing_patch',
    'partition_routing_transform', 'pressure_indexed_patch', 'heat_payload_indexed_patch',
    'private_heat_indexed_runtime', 'private_heat_restored_binding_ram_context_r1',
    'private_heat_restored_binding_ram_recovery_r1', 'private_heat_process_meter_r1',
    'private_heat_gmp_resources_r1', 'private_heat_functionals_parallel_r1',
    'private_heat_issuer_resources_r1', 'private_heat_original_coverage_r3',
    'heat_interval_r9_spec', 'private_heat_joined_consumer_r6',
    'private_heat_original_joined_r6', 'private_heat_original_continuation_r1',
    'private_heat_geometry_observer_r1', 'i04_differential_modes')
QUERY_LIMIT_FIELDS = frozenset(('max_entries', 'max_store_bytes'))
# The completed-query store the pinned source manifest declares, read as on the fresh leg
# (run_fresh_interval): a declared store the runtime lacks refuses, never a silent fallback,
# and flush() precedes the recorded counts. These constants and the units before
# run_prepared_restart are run_fresh_interval's, AST-identical (test_restart_query_store).
QUERY_STORE_FLAG = 'completed_query_store'
QUERY_STORES = {'columnar': {'storage': 'columnar', 'batch_entries': 128, 'batch_seconds': 10},
                'files': {'storage': 'files'}}
STORE_STATISTICS = ('unique_chunks', 'encoded_payload_bytes', 'snapshots', 'database_bytes')
SAME_PROCESS_REOPEN_DROPPED = ('dropped by owner decision; '
                               'the mandatory independent fresh-process reader performs the cold reopen')
# Each name is one refusal in _successor_checks, in order; run.json lists them.
SUCCESSOR_CHECKS = ('live_head_identity', 'live_head_advanced_exactly_one_interval',
    'live_root_workflow_and_funding_unchanged', 'successor_head_persisted',
    'persisted_head_equals_live_head', 'persisted_successor_links_parent', 'persisted_parent_unchanged',
    'persisted_root_unchanged', 'clock_advanced_and_persisted', 'no_further_successor',
    'store_unchanged_during_checks')
class RestartRefused(ValueError, AtlasError):
    pass


def require(condition, message):
    if not condition:
        raise RestartRefused(message)


def _sha(value):
    require(type(value) is str and len(value) == 64 and
            all(c in '0123456789abcdef' for c in value), 'exact lowercase SHA-256 required')
    return value


def ordinary(path, *, directory=False):
    path = Path(path).absolute()
    for item in (path, *path.parents):
        info = item.lstat()
        require(not stat.S_ISLNK(info.st_mode) and
                not getattr(info, 'st_file_attributes', 0) & 0x400, 'linked/reparsed path refused')
    require(path.is_dir() if directory else path.is_file(), 'ordinary file/directory required')
    return path.resolve()


def canonical_absolute(value, label):
    """String identity, not Path equality: case and 8.3 aliases must not differ."""
    require(type(value) is str and value and Path(value).is_absolute() and
            str(Path(value)) == value == str(Path(value).resolve()),
            'canonical absolute '+label+' required')
    return Path(value)


def file_hash(path, check=lambda: None):
    path = ordinary(path)
    before = path.stat()
    result = sha256()
    with path.open('rb') as stream:
        while block := stream.read(1 << 20):
            check()
            result.update(block)
        after = os.fstat(stream.fileno())
    identity = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns)
    require(identity(before) == identity(after) == identity(path.stat()), 'file changed during hash')
    return result.hexdigest()


def _json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'duplicate JSON key')
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=pairs,
        parse_constant=lambda _: (_ for _ in ()).throw(RestartRefused('nonfinite JSON')))


def pinned_json(path, pin, limit=MAX_CONFIG):
    path = ordinary(path)
    require(path.stat().st_size <= limit, 'configuration exceeds bounded size')
    raw = path.read_bytes()
    require(len(raw) <= limit and sha256(raw).hexdigest() == _sha(pin), 'pinned configuration changed')
    return _json(raw)


def _dev_timing_enabled(flag=False, environ=None):
    """Resolve CLI opt-in without importing a helper outside selected sources."""
    require(type(flag) is bool, 'dev timing flag must be boolean')
    value = (os.environ if environ is None else environ).get('ATLAS_DEV_STAGE_TIMING', '')
    require(value in ('', '0', '1'), 'ATLAS_DEV_STAGE_TIMING must be unset, 0 or 1')
    return flag or value == '1'


def launch_environment():
    return dict(os.environ, **LAUNCH_ENV)


def historical_import_path(workspace, entry, *, historical_inputs):
    inputs = verified_historical_inputs(historical_inputs)
    require(inputs.workspace == ordinary(workspace, directory=True),
            'historical import catalogue workspace differs')
    return inputs.historical_import_path(entry)


def final_status(errors, *, stop_before_advance):
    # A stopped staged run is never an interval result, whatever else passed.
    return 'FAILED' if errors else (STOPPED_STATUS if stop_before_advance else PASS_STATUS)


COMPACT_MODULES = ('compact_restart_store', 'compact_restart_patch', 'reopen_prepared_restart',
    'content_cache', 'compact_contracts', 'interval_catalog', 'interval_store_set', 'segment_store',
    'record_tables', 'record_views', 'spatial_records_patch', 'partition_v2',
    'heat_ledger_tables', 'heat_ledger_issuer_patch', 'private_heat_snapshot_store_r4',
    'historical_compact_heat', 'bounded_preseal')
COMPACT_STORE_LIMITS = dict(chunk_bytes=65536, max_array_bytes=512 << 20,
    max_store_bytes=4 << 30, decoded_cache_bytes=0, max_manifest_bytes=1 << 20,
    max_chunks=100000, staging_memory_bytes=256 << 10, max_staging_bytes=1 << 30,
    verified_cache_entries=2048, insert_batch_bytes=256 << 10,
    sqlite_cache_bytes=2 << 20, codec_workspace_bytes=8 << 20)
COMPACT_COMPRESSION = dict(codec='zstd', level=1, shuffle='byte', palette=True,
                           categorical='auto', use_dict=False)


def compact_profile(row):
    return row.get('storage_format') == 'interval-catalog-v1'


def new_retained_scope(budget):
    # The runner advances the live interval, so its scope carries the named
    # live-producer child (decision D2-A): in-memory producer
    # records are booked there, and the 256 MiB aggregate keeps meaning views
    # and caches. The independent reader creates its own cold scope without it.
    # A child cap above its run budget would be meaningless (the parent always
    # governs), so a smaller test budget gets a child no larger than itself.
    from atlas_tectonics._private.codecs.content_cache import LIVE_PRODUCER_BYTES, create_retained_scope
    return create_retained_scope(budget, process_epoch='prepared-restart-'+str(os.getpid()),
                                 live_producer_bytes=min(LIVE_PRODUCER_BYTES, budget.max_bytes))


@contextmanager
def retained_run(budget, record):
    """One 256 MiB child for the full run; live owners cannot be credited early."""
    from atlas_tectonics._private.integration import reopen_prepared_restart as reader
    scope = new_retained_scope(budget)
    try:
        yield scope
    finally:
        active_error = sys.exception()
        record['compact_retained_before_close'] = reader.retained_accounting(scope)
        try:
            scope.close()
            record['compact_retained_after_close'] = reader.retained_accounting(scope)
        except BaseException as release_error:
            if active_error is None:
                raise
            active_error.add_note('Retained scope finalisation also failed: '+repr(release_error))


HISTORICAL_INPUTS_SHA256 = '019944bf42007397c3cacb8756ea2e62862afa5170c79e28601d7a914cd86d22'


def _historical_inputs_api():
    from atlas_tectonics._private.integration import historical_input_contract
    return historical_input_contract


def load_historical_inputs(workspace, binding):
    api = _historical_inputs_api()
    try:
        return api.load(workspace, binding)
    except api.HistoricalInputsRefused as error:
        raise RestartRefused(str(error)) from error


def verified_historical_inputs(value):
    api = _historical_inputs_api()
    try:
        return api.verified(value)
    except api.HistoricalInputsRefused as error:
        raise RestartRefused(str(error)) from error


@dataclass(frozen=True)
class RestartProfile:
    path: Path
    sha256: str
    # Retain bytes, not a mutable dictionary that could silently change pins.
    _record: bytes

    @classmethod
    def read(cls, path, pin):
        path = ordinary(path)
        row = pinned_json(path, pin)
        fields = {'schema', 'workspace', 'completed_query_store', 'qualification_status', 'native_root', 'import_roots',
            'modules', 'preparation', 'compatibility_policy', 'evidence_root',
            'historical_root', 'historical_source_root', 'advance_driver', 'output_directory',
            'store_limits', 'compression', 'completed_query_directory', 'completed_query_limits', 'historical_inputs'}
        require(type(row) is dict and set(row) in (fields, fields | {'storage_format'}) and row['schema'] == PROFILE_SCHEMA,
                'closed reviewed restart profile required; an older profile is moved with '
                'tools/runs/migrate_run_profile.py')
        require(row.get('storage_format', 'native-v1') in ('native-v1', 'interval-catalog-v1'),
                'reviewed storage format required')
        required = set(REQUIRED_MODULES) | (set(COMPACT_MODULES) if compact_profile(row) else set())
        require(type(row['modules']) is dict and set(row['modules']) in (required, required | {'dev_stage_timing'}),
                'complete explicit helper module bindings required')
        require(row['completed_query_store'] in QUERY_STORES,
                'the profile must declare its completed-query store: columnar or files')
        require(type(row['qualification_status']) is str and row['qualification_status'],
                'the profile must declare its qualification status')
        for field in ('preparation', 'compatibility_policy', 'historical_inputs'):
            require(type(row[field]) is dict and set(row[field]) == {'path', 'sha256'},
                    'explicit path and source pin required: '+field)
            _sha(row[field]['sha256'])
        require(row['historical_inputs']['sha256'] == HISTORICAL_INPUTS_SHA256,
                'the fixed historical input catalogue is required')
        driver = row['advance_driver']
        require(type(driver) is dict and set(driver) == {'module', 'path', 'sha256'} and
                type(driver['module']) is str and driver['module'].isidentifier() and
                driver['module'] not in REQUIRED_MODULES, 'one explicit interval driver binding required')
        _sha(driver['sha256'])
        require(type(row['import_roots']) is list and row['import_roots'] and
                type(row['store_limits']) is dict and type(row['compression']) is dict,
                'explicit import roots and original native store configuration required')
        canonical_absolute(row['output_directory'], 'restart output directory')
        query_path = row['completed_query_directory']
        require(type(query_path) is str and query_path and '\\' not in query_path and
                ':' not in query_path and not Path(query_path).is_absolute() and
                '..' not in Path(query_path).parts,
                'explicit contained completed-query directory required')
        historical = row['historical_root']
        require(type(historical) is str and historical and '\\' not in historical and ':' not in historical and
                not Path(historical).is_absolute() and '..' not in Path(historical).parts,
                'explicit contained historical root required')
        quota = row['completed_query_limits']
        require(type(quota) is dict and set(quota) == QUERY_LIMIT_FIELDS and
                all(type(value) is int and value > 0 for value in quota.values()),
                'explicit positive completed-query entry and byte limits required')
        return cls(path, pin, json.dumps(row, sort_keys=True, separators=(',', ':')).encode())

    def record(self):
        return _json(self._record)

    def verify(self):
        row = pinned_json(self.path, self.sha256)
        require(json.dumps(row, sort_keys=True, separators=(',', ':')).encode() == self._record,
                'in-memory profile differs from the pinned reviewed record')


class RestartSources:
    """What the reviewed profile names: workspace paths, helper module names, the declared query store.

    Helpers are found by plain import; native_root and import_roots go on sys.path once.
    """
    __slots__ = ('profile', 'workspace', 'native_root', 'import_roots', 'historical_inputs', '_sealed')

    def __setattr__(self, name, value):
        if getattr(self, '_sealed', False):
            raise RestartRefused('selected source configuration is immutable')
        object.__setattr__(self, name, value)

    def __init__(self, profile):
        require(isinstance(profile, RestartProfile), 'typed pinned restart profile required')
        profile.verify()
        self.profile = profile
        row = profile.record()
        self.workspace = ordinary(row['workspace'], directory=True)
        self.native_root = self.path(row['native_root'], directory=True)
        self.import_roots = tuple(self.path(p, directory=True) for p in row['import_roots'])
        self.historical_inputs = load_historical_inputs(self.workspace, row['historical_inputs'])
        for root in (self.native_root, *self.import_roots):
            if str(root) not in sys.path:
                sys.path.insert(0, str(root))
        self.check_paths()
        self._sealed = True

    def path(self, name, *, directory=False):
        require(type(name) is str and name and '\\' not in name and ':' not in name and
                not Path(name).is_absolute() and '..' not in Path(name).parts,
                'canonical contained workspace-relative path required')
        path = ordinary(self.workspace/name, directory=directory)
        require(path.is_relative_to(self.workspace), 'source escaped workspace')
        return path

    def query_store(self):
        """The completed-query store the reviewed profile declares."""
        return self.profile.record()[QUERY_STORE_FLAG]

    def check_paths(self):
        """No live sys.path entry may expose the historical runtime or helpers.

        Native ALE workers inherit this list; a late historical entry would make
        them import the old package only after hours of work.
        """
        inputs = verified_historical_inputs(self.historical_inputs)
        for entry in tuple(sys.path):
            require(not inputs.historical_import_path(entry),
                    'historical import root on sys.path refused: '+str(entry))

    def module(self, name):
        row = self.profile.record()
        expected = (row['advance_driver']['path'] if name == row['advance_driver']['module']
                    else row['modules'][name])
        require(type(name) is str and name.isidentifier(), 'plain helper name required')
        path = self.path(expected)
        if path.is_relative_to(self.native_root):
            name = '.'.join(path.relative_to(self.native_root).with_suffix('').parts)
        module = importlib.import_module(name)
        require(ordinary(module.__file__) == path, 'helper module shadowing refused: '+name)
        return module


def interpreter_gate():
    """Seed and hook state the native automatic selector reads at decision time.

    Neither can be repaired after the interpreter starts. An unseeded or
    instrumented launch would otherwise run serial geometry for hours.
    """
    import tracemalloc
    monitoring = sys.monitoring
    tools = {str(i): monitoring.get_tool(i) for i in range(6) if monitoring.get_tool(i) is not None}
    seed = dict(PYTHONHASHSEED=os.environ.get('PYTHONHASHSEED'), hash_randomization=sys.flags.hash_randomization)
    hooks = dict(trace=sys.gettrace() is not None, profile=sys.getprofile() is not None,
                 monitoring_tools=tools, tracemalloc=tracemalloc.is_tracing())
    require(seed == dict(PYTHONHASHSEED='0', hash_randomization=0),
            'automatic geometry requires an interpreter started with PYTHONHASHSEED=0')
    require(not hooks['trace'] and not hooks['profile'] and not tools and not hooks['tracemalloc'],
            'foreign instrumentation present at start')
    return dict(interpreter_seed=seed, instrumentation_at_start=hooks,
                launch_environment={name: os.environ.get(name) for name in sorted(LAUNCH_ENV)})


PRODUCTION_MODULE = 'runtime_production_entry'


def production_policy_module(sources):
    """Load the fixed private policy only from the selected native root."""
    require(__package__ == 'atlas_tectonics._private.integration',
            'production policy requires the actual installed source selection')
    expected = sources.native_root/'atlas_tectonics/_private/integration/runtime_production_entry.py'
    path = ordinary(expected)
    require(path == expected and ordinary(__file__).parent == path.parent,
            'production policy must be the exact selected private sibling')
    workspace = ordinary(sources.workspace, directory=True)
    require(path.is_relative_to(workspace), 'production policy source escaped the selected workspace')
    module = importlib.import_module('atlas_tectonics._private.integration.runtime_production_entry')
    require(type(getattr(module, '__file__', None)) is str and ordinary(module.__file__) == path,
            'production policy module shadowing refused')
    return module


def production_decision(sources, route):
    return production_policy_module(sources).packet(sources,route,SG)


def production_admission(sources, route, start_gate):
    import psutil
    from atlas_tectonics.integration.reuse import execution_mode
    require(execution_mode() == 'release', 'production Release requires the actual packaged identity mode')
    return production_policy_module(sources).child_admit(start_gate,sources,route,SG,psutil.virtual_memory())


def producer_policy(receipt, sources, *, expected_route):
    """Independent-reader policy; historical receipts retain their original exact strict guard contract."""
    require(expected_route in ('fresh-root', 'fresh-interval', 'prepared'),
            'trusted expected producer route required')
    if type(receipt) is dict and 'production_release' not in receipt:
        require(receipt.get('execution_mode','strict') == 'strict', 'unbound Release producer refused')
        limits = receipt.get('guard_limits')
        require(type(limits) is dict and set(limits) == {'rss_bytes','free_floor_bytes','start_available_bytes','logical_budget_bytes'}
                and {name: limits[name] for name in ('rss_bytes', 'free_floor_bytes', 'logical_budget_bytes')}
                    == SG.run_limits(receipt.get('start_gate'))
                and type(limits['start_available_bytes']) is int and limits['start_available_bytes'] > 0,
                'strict producer requires the exact guard limits of its own start decision')
        return {'execution_mode':'strict','guard_limits':dict(limits)}
    return production_policy_module(sources).producer_policy(receipt,sources=sources,gate=SG,expected_route=expected_route)


def _guard_boundary(sources, guard, budget, *, limits):
    G = sources.module('private_heat_continuation_guard_r3')
    J = sources.module('windows_workload_job')
    require(type(guard) is G.ContinuationGuard and not guard.closed and guard.budget is budget,
            'actual active shared-budget Windows-job guardian required')
    expected = dict(rss_bytes=limits['rss_bytes'],free_floor_bytes=limits['free_floor_bytes'])
    require(type(expected['rss_bytes']) is int and 0 < expected['rss_bytes'] <= GATE.cap_bound(MONITOR.machine_memory())
            and expected['free_floor_bytes'] >= GATE.FLOOR_BYTES, 'resource guards cannot be widened')
    require(guard._control['limits'] == expected, 'exact authenticated resource guards required')
    context = _json(os.environ[G.ENV])
    require(context['nonce'] == guard.nonce and context['output'] == str(guard.output) and
            J.verify_current_membership(context['job_name']) == guard.identity and
            guard._sync()['status'] == 'RUNNING', 'current external guardian membership differs')
    guard.check(force=True)


def _check_historical_root(sources, H, row):
    """Historical evidence remains at the explicitly bound current-workspace original."""
    inputs = verified_historical_inputs(sources.historical_inputs)
    root = sources.path(row['historical_root'], directory=True)
    require(root == sources.path(inputs.historical_relative, directory=True)
            and H.historical_root(root, historical_inputs=inputs) == root
            and sources.path(row['historical_source_root'], directory=True) == root/inputs.historical_native_relative,
            'historical evidence root differs from the workspace-anchored original candidate')
    return root


def _compatibility(sources, row):
    return dict(policy_path=sources.path(row['compatibility_policy']['path']),
        policy_sha256=row['compatibility_policy']['sha256'],
        evidence_root=sources.path(row['evidence_root'], directory=True),
        historical_source_root=sources.path(row['historical_source_root'], directory=True))


def _check_runtime_binding(base, row, execution, budget):
    """The admitted policy must name the historical manifest and this run's execution identity."""
    from atlas_tectonics._private.integration import workflow_transfer as W
    scratch = W._decode_allocation(budget, base._runtime._record)
    runtime = base._runtime.record()
    require(runtime['historical_source_manifest_sha256'] == HISTORICAL_SOURCE_MANIFEST_SHA256 and
            runtime['current_execution_identity'] == execution.provenance['execution_identity'],
            'reviewed runtime admission does not bind the historical manifest and execution')
    _ = scratch


def _copy_bound_file(source, expected, destination, *, budget, check):
    """Exclusive fsynced copy whose bytes equal an existing authenticated pin."""
    from atlas_tectonics._private.integration import native_transfer as N
    source = ordinary(source)
    destination = Path(destination).absolute()
    ordinary(destination.parent, directory=True)
    require(not destination.exists() and destination != source, 'fresh separate checkpoint required')
    require(not any(Path(str(source)+s).exists() for s in ('-wal', '-journal', '-shm')),
            'source checkpoint must remain closed without sidecars')
    expected = _sha(expected)
    # Hash the source bytes as they are written to the exclusive destination.
    allocation = N._Allocation(budget, (1 << 20)+8192, category='restart-checkpoint-copy')
    digest = sha256()
    before = source.stat()
    with source.open('rb') as original, destination.open('xb') as target:
        while block := original.read(1 << 20):
            check()
            digest.update(block)
            target.write(block)
        target.flush()
        os.fsync(target.fileno())
    after = source.stat()
    require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) ==
            (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns) and
            digest.hexdigest() == expected, 'authenticated checkpoint copy differs')
    _ = allocation
    return source, expected


def _copy_original(admission, destination, *, budget, check):
    from atlas_tectonics._private.integration import workflow_transfer as W
    require(type(admission) is W.HistoricalEndpointAdmission, 'authenticated historical admission required')
    scratch = W._decode_allocation(budget, admission._binding)
    binding = admission.binding()
    result = _copy_bound_file(binding['original_database_path'], binding['database_sha256'],
                              destination, budget=budget, check=check)
    _ = scratch
    return result


def _census(directory):
    """Completed-query files by kind; committed entries end in .query."""
    result = dict(query_files=0, query_bytes=0, partial_files=0, partial_bytes=0,
                  other_files=0, other_bytes=0)
    with os.scandir(directory) as entries:
        for entry in entries:
            if entry.name == 'owner.lock':
                continue
            kind = ('query' if entry.name.endswith('.query') else
                    'partial' if '.partial-' in entry.name else 'other')
            result[kind+'_files'] += 1
            result[kind+'_bytes'] += entry.stat(follow_symlinks=False).st_size
    return result


def _tree(directory):
    files = size = 0
    pending = [directory]
    while pending:
        with os.scandir(pending.pop()) as entries:
            for entry in entries:
                if entry.is_dir(follow_symlinks=False):
                    pending.append(entry.path)
                else:
                    files += 1
                    size += entry.stat(follow_symlinks=False).st_size
    return dict(files=files, bytes=size)


def storage_point(record, label, *, checkpoint, query_directory=None, output=None, store=None):
    """Stat-only persistent storage census; SQLite is read only via ArrayStore."""
    path = Path(checkpoint)
    compact = store is not None and getattr(store, 'scope', None) is not None
    if path.exists():
        path = ordinary(path)
    else:
        require(compact and path == store.catalog_path, 'checkpoint is missing')
    row = dict(label=label, checkpoint=str(path), checkpoint_bytes=path.stat().st_size if path.exists() else 0,
        sidecars=[s for s in ('-wal', '-journal', '-shm') if Path(str(path)+s).exists()])
    if query_directory is not None:
        row['completed_query_directory'] = _census(ordinary(query_directory, directory=True))
    if output is not None:
        row['output_tree'] = _tree(ordinary(output, directory=True))
    if store is not None:
        statistics = store.statistics()
        row['store'] = statistics if compact else {key: statistics[key] for key in STORE_STATISTICS}
    record.setdefault('storage', []).append(row)
    return row


@contextmanager
def publish_and_reopen(store, base, *, budget, check, phase, prepare_next=False,
                       producer_identity=None, runtime_identity=None):
    """Real publication + cold reopen, reusable by the explicitly synthetic test.

    Both called issuers reject dicts and preserve original immutable history.
    The enclosing public runner supplies the authenticated, current live base.
    """
    from atlas_tectonics._private.integration import workflow_transfer as W
    from atlas_tectonics.integration.coupling.regional_workflow import CollarWorkflow
    from atlas_tectonics.codecs.storage import ArrayStore
    compact = W.is_compact_restart_store(store, budget=budget)
    require(type(base) is W.MigratedWorkflowBase and (type(store) is ArrayStore or compact) and
            base._budget is budget and store._budget is budget, 'actual shared-budget base/store required')
    phase('publish-migrated-root')
    check()
    with W.publish_migrated_root(store, base, budget=budget) as published:
        require(type(published) is CollarWorkflow, 'actual published workflow required')
        before = published.inspect()
        workflow_id = published.workflow_id
    if compact:
        store.seal_and_promote(before['head'])
        if prepare_next:
            store.start_next_interval(producer_identity=producer_identity, runtime_identity=runtime_identity)
    phase('cold-reopen-migrated-root')
    token = store.change_token()
    with CollarWorkflow.open_migrated(store, workflow_id, base, budget=budget) as workflow:
        require(type(workflow) is CollarWorkflow and workflow.inspect() == before and
                store.change_token() == token, 'migration root cold reopen changed state or wrote to store')
        check()
        yield workflow


def _published_root(workflow, store, base, case, execution, budget):
    """Root identity a fresh reader must reproduce; recorded in both run modes."""
    from atlas_tectonics._private.integration import workflow_transfer as W
    root_bytes = workflow._root
    scratch = W._decode_allocation(budget, root_bytes)
    root = json.loads(root_bytes)
    require(store.metadata(root['key']) == root, 'published root differs from its reopened metadata')
    collar = case['collar']
    workflow_id = root['workflow_id']
    if len(root_bytes) > W.MAX_METADATA_BYTES:
        raise W.WorkflowTransferRefused('bounded migration metadata exceeds 8 MiB')
    result = dict(workflow_id=workflow_id, root_key=root['key'], root_metadata_sha256=sha256(root_bytes).hexdigest(),
        sequence=root['sequence'], inspect=workflow.inspect(), producer_pid=os.getpid(),
        store_limits=asdict(store.limits), store_compression=asdict(store.compression),
        execution_provenance=execution.provenance,
        preparation_ids=dict(owner=case['owner'].owner_id, spatial_owner=base._spatial.owner.owner_id,
            native=collar._native.plan_id, collar=collar.plan_id, map=collar._map.volume_map_id,
            funding=base._spatial.funding.funding_id))
    _ = scratch
    return result


def _successor_checks(workflow, *, store, before, parent, root_bytes, budget):
    """Cheap structural proof that exactly one valid successor was persisted.

    Owner decision: the successor is no longer cold-reopened in this
    process; the mandatory independent fresh-process reader performs that cold
    reopen. Only the live workflow and small store metadata are read here (the
    new head, its parent, the root and the absent next key); no array or payload.
    inspect() on the live workflow is cheap when the driver's own publication
    adopted the store token it produced inside its writer transaction (R2
    option A, publication_token_transform); if any other write intervened the
    token stays unset and the native _refresh re-validates the persisted chain
    and restores its head (slower, never weaker). The successor is not
    re-validated per scalar before the seal: bounded_preseal runs the bounded
    pre-seal checks and the fresh reader re-derives every record on the sealed
    file. ``store`` is the workflow's store captured before the driver. A
    textual success, an unpersisted or foreign head, a changed parent, root,
    workflow, store or funding, a stalled clock or a second successor is refused.
    Returns the live inspect() record, the producer's advanced endpoint.
    """
    from atlas_tectonics._private.integration import workflow_transfer as W
    checks = iter(SUCCESSOR_CHECKS)

    def refuse(name, condition):
        require(name == next(checks), 'successor check order changed')
        require(condition, 'driver did not persist exactly one valid successor: '+name)

    require(workflow._store is store, 'driver did not persist exactly one valid successor: workflow store replaced')
    token = store.change_token()
    after = workflow.inspect()
    head = workflow._head
    try:
        refuse('live_head_identity', type(after) is dict and type(head) is dict and
               type(after.get('head')) is str and head.get('key') == after['head'])
        refuse('live_head_advanced_exactly_one_interval',
               after['intervals'] == before['intervals']+1 and after['head'] != before['head'])
        refuse('live_root_workflow_and_funding_unchanged', workflow._root == root_bytes and
               after['workflow_id'] == before['workflow_id'] and after['funding_id'] == before['funding_id'])
        stored = store.metadata(after['head'])
        refuse('successor_head_persisted', stored is not None)
        refuse('persisted_head_equals_live_head', stored == head)
        refuse('persisted_successor_links_parent', stored['kind'] == 'successor' and
               stored['key'] == W.workflow_key('successor', before['head']) and
               stored['sequence'] == after['intervals'] and stored['workflow_id'] == after['workflow_id'] and
               stored['parent_key'] == before['head'] and stored['parent_digest'] == W.digest(parent) and
               stored['funding_id'] == before['funding_id'])
        refuse('persisted_parent_unchanged', store.metadata(before['head']) == parent)
        scratch = W._decode_allocation(budget, root_bytes)
        root = json.loads(root_bytes)
        refuse('persisted_root_unchanged', store.metadata(root['key']) == root)
        del scratch, root
        refuse('clock_advanced_and_persisted', after['time_s'] > before['time_s'] and
               stored['state']['fields']['time_s'] == after['time_s'])
        refuse('no_further_successor', store.metadata(W.workflow_key('successor', after['head'])) is None)
        refuse('store_unchanged_during_checks', store.change_token() == token)
    except (KeyError, TypeError) as error:
        raise RestartRefused('driver did not persist exactly one valid successor: '
                             'successor metadata incomplete: '+repr(error)) from error
    require(next(checks, None) is None, 'successor check order changed')
    return after


def _advance_checked(driver, *, workflow, base, case, execution, guard, record, save, artifacts,
                     query_checkpoints=None):
    """Ignore textual success; structurally check one persisted successor.

    No same-process cold reopen follows the driver (owner decision);
    _successor_checks reads the live workflow and small store metadata only.
    The independent fresh-process reader remains mandatory.
    """
    from atlas_tectonics._private.integration import workflow_transfer as W
    from atlas_tectonics.integration.coupling.regional_workflow import CollarWorkflow
    require(type(workflow) is CollarWorkflow and type(base) is W.MigratedWorkflowBase and
            workflow._migration is base, 'actual admitted migrated workflow required')
    before = workflow.inspect()
    parent = dict(workflow._head)
    root_bytes, store = workflow._root, workflow._store
    capture_variable = 'ATLAS_FOCUSED_ARTIFACT_DIR'
    previous_capture = os.environ.get(capture_variable)
    os.environ[capture_variable] = str(ordinary(artifacts, directory=True))
    try:
        driver(case=case, workflow=workflow, base=base, execution=execution, guard=guard,
               record=record, save=save, artifacts=artifacts, query_checkpoints=query_checkpoints)
    finally:
        if previous_capture is None:
            os.environ.pop(capture_variable, None)
        else:
            os.environ[capture_variable] = previous_capture
    # No token or execution identity is overwritten to coerce a reader into
    # accepting persisted bytes; the independent reader cold-reopens them.
    return before, _successor_checks(workflow, store=store, before=before, parent=parent,
                                     root_bytes=root_bytes, budget=base._budget)


# The fresh leg's completed-query units, copied by AST span from run_fresh_interval so
# that each leg raises its own refusal type; test_restart_query_store fails on any drift.
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
            require(self.owner is None, 'one completed-query owner at a time')
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
            require(owner is self.owner, 'a different completed-query owner closed')
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
        require(getattr(owner, 'storage', 'files') == QUERY_STORES[declared]['storage'],
                'completed-query owner differs from the declared store')
        flush = getattr(owner, 'flush', None)
        require(declared == 'files' or callable(flush), 'a batched completed-query store must flush')
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


def run_prepared_restart(profile, *, sources, guard, record, save, stop_before_advance=False, start_gate=None,
                         query_stages=None, production_release=False):
    """Actual prepare/admit/transfer/copy/publish/reopen/advance orchestration.

    Call under the live external guard. No mock or JSON
    capability is accepted. All output paths derive from the one fresh profile
    directory; neither the original store nor prior receipts are writable here.
    With stop_before_advance the published root is reopened and recorded, and
    no driver, completed-query owner or physical interval work runs.
    ``query_stages`` (S1): _workload's per-stage completed-query observer, handed to the owner.
    """
    require(type(profile) is RestartProfile and type(sources) is RestartSources and
            sources.profile is profile, 'actual pinned sources required')
    require(type(stop_before_advance) is bool, 'explicit stop-before-advance mode required')
    available = MONITOR.free_memory()
    admission = production_admission(sources,'prepared',start_gate) if production_release else None
    admitted = admission['start_gate'] if admission is not None else SG.child_admit(start_gate, available)
    selected_limits = admission['guard_limits'] if admission is not None else SG.guard_limits(admitted)
    row = profile.record()
    H = sources.module('historical_admission')
    compact = compact_profile(row)
    compact_module = sources.module('compact_restart_store') if compact else None
    reader = sources.module('reopen_prepared_restart') if compact else None
    M = sources.module('materialise_endpoint')
    W = sources.module('workflow_transfer')
    P = sources.module('plan_preparation')
    IW = sources.module('initial_workload')
    driver_module = sources.module(row['advance_driver']['module'])
    require('working_store' in inspect.signature(M.materialise).parameters,
            'store-aware compact endpoint materialisation is not composed')
    driver = getattr(driver_module, 'advance_prepared_interval', None)
    require(inspect.isfunction(driver) and driver.__module__ == driver_module.__name__,
            'named source-bound next-interval implementation required')
    inspect.signature(driver).bind(**{k: None for k in
        ('case', 'workflow', 'base', 'execution', 'guard', 'record', 'save', 'artifacts',
         'query_checkpoints')})
    from atlas_tectonics.integration.resources import WorkBudget
    from atlas_tectonics.integration.reuse import ExecutionContext, require_strict_execution
    from atlas_tectonics.codecs.storage import ArrayStore, StoreLimits, Compression
    from atlas_tectonics.integration.coupling.regional_workflow import CollarWorkflow
    from atlas_tectonics.integration.endpoint_checkpoints import EndpointCheckpoints
    declared = sources.query_store()
    query_arguments = query_store_arguments(EndpointCheckpoints, declared)
    record['completed_query_store'] = {'declared': declared, 'arguments': query_arguments}
    # Bind every participating helper to its reviewed path before any work; a
    # same-named historical original can then never be resolved by later imports.
    bound = {name: sources.module(name) for name in (*REQUIRED_MODULES, *(COMPACT_MODULES if compact else ()))}
    control = bound['i04_differential_modes'].ACTUATED_CONTROL
    require(hasattr(CollarWorkflow, 'open_migrated'), 'composed migrated-root native reader is missing')
    require(type(production_release) is bool, 'explicit production option required')
    if not production_release:
        require_strict_execution()
    record.update(interpreter_gate(), stop_before_advance=stop_before_advance)
    historical_root = _check_historical_root(sources, H, row)
    output = Path(row['output_directory'])
    require(ordinary(output, directory=True) == output and output.is_relative_to(sources.workspace) and
            guard.output == output/'run.json', 'guard and fresh restart output directory differ')
    destination = output/'compact-checkpoint'/'interval-catalog.json' if compact else output/'checkpoint.sqlite'
    require(not destination.exists() and not any(output.glob('checkpoint.sqlite*')) and
            (not compact or not destination.parent.exists()),
            'restart checkpoint output already exists')
    if compact:
        destination.parent.mkdir()
    query_directory = sources.workspace/row['completed_query_directory']
    ordinary(query_directory.parent, directory=True)
    require(query_directory.resolve().is_relative_to(sources.workspace) and
            not query_directory.is_relative_to(output),
            'explicit reusable completed-query directory must be outside this attempt')
    query_directory.mkdir(exist_ok=True)
    ordinary(query_directory, directory=True)
    query_limits = row['completed_query_limits']
    guard.budget = budget = WorkBudget(selected_limits['logical_budget_bytes'], max_predicate_work_units=1 << 44)
    _guard_boundary(sources, guard, budget, limits=selected_limits)
    record.update(guard_limits=selected_limits, start_gate=admitted,
        memory_at_start=dict(available_bytes=admitted['available_bytes'],
            **({'physical_bytes':admitted['physical_bytes']} if production_release else {})),
        execution_mode='release' if production_release else 'strict', 
        completed_query_limits=dict(query_limits),
        production_acceptance=False, original_producer_status_unchanged=True)
    if admission is not None:
        record['production_release'] = admission['production_release']
    limits, compression = StoreLimits(**row['store_limits']), Compression(**row['compression'])
    store_bytes = COMPACT_STORE_LIMITS['max_store_bytes'] if compact else limits.max_store_bytes
    staging_bytes = COMPACT_STORE_LIMITS['max_staging_bytes'] if compact else limits.max_staging_bytes
    require(shutil.disk_usage(output).free >= 2*store_bytes + staging_bytes +
            query_limits['max_store_bytes'],
            'insufficient disk headroom for preserved source, new checkpoint/staging and query quota')
    preparation = P.load_preparation(sources.path(row['preparation']['path']))
    compatibility = _compatibility(sources, row)
    check = lambda: guard.check(force=True)
    guard.phase('prepare-current-plans-without-funding')
    original_path = original_pin = None
    try:
        with retained_run(budget, record) if compact else nullcontext(None) as scope, \
                ExecutionContext('scipy') as execution, preparation(budget=budget, pressure_space='q1-p0',
                material_quadrature=True) as case:
            profiling.checkpoint('current-plans-prepared')
            guard.phase('authenticate-historical-endpoint-readonly')
            with H.open_original_readonly(root=historical_root, historical_inputs=sources.historical_inputs, limits=limits, compression=compression,
                                          budget=budget) as original:
                admission = H.admit_historical_endpoint(original, root=historical_root, historical_inputs=sources.historical_inputs, execution=execution,
                                                        budget=budget, guard=guard, production_release=production_release)
                require(type(admission) is W.HistoricalEndpointAdmission, 'historical issuer returned no admission')
                profiling.checkpoint('historical-endpoint-authenticated')
                guard.phase('bind-authenticated-original-for-compact-migration' if compact else
                            'copy-authenticated-checkpoint-to-fresh-output')
                if compact:
                    original_path, original_pin = original.path, admission.binding()['database_sha256']
                else:
                    original_path, original_pin = _copy_original(admission, destination, budget=budget, check=check)
                profiling.checkpoint('authenticated-original-bound' if compact else 'authenticated-checkpoint-copied')
                storage_point(record, 'original', checkpoint=original_path)
                if not compact:
                    storage_point(record, 'after-copy', checkpoint=destination, query_directory=query_directory,
                                  output=output)
                save()
                # Compact conversion publishes only into this exclusive output.
                current_store = (compact_module.CompactRestartStore.create_migration(destination,
                    workflow_id=admission.record()['source']['workflow_id'], scope=scope,
                    producer_identity=profile.sha256, runtime_identity=execution.provenance['execution_identity'])
                    if compact else ArrayStore(destination, limits, compression, budget=budget))
                with current_store as store:
                    if compact:
                        require(asdict(store.limits) == COMPACT_STORE_LIMITS and
                            asdict(store.compression) == COMPACT_COMPRESSION,
                            'compact runtime storage configuration differs from reviewed bounds')
                    guard.phase('transfer-authenticated-endpoint-to-current-owners')
                    # The forced check stays unwrapped (materialise throttles the
                    # mesh side, PW the partition nodes); phases reach the guard.
                    with M.materialise(original_store=original, admission=admission, native=case['native'],
                            collar=case['collar'], execution=execution, compatibility=compatibility,
                            budget=budget, check=check, working_store=store, phase=guard.phase,
                            **({'scope': scope} if compact else {})) as base:
                        profiling.checkpoint('endpoint-materialised')
                        require(type(base) is W.MigratedWorkflowBase and
                                type(base._runtime) is W.RuntimeCompatibilityAdmission,
                                'materialiser returned no authenticated current base')
                        _check_runtime_binding(base, row, execution, budget)
                        storage_point(record, 'after-materialise', checkpoint=destination, store=store)
                        guard.phase('authenticate-frozen-initial-workload')
                        state = IW.initial_workload_state(original_store=original, admission=admission,
                            collar=case['collar'], budget=budget, check=check)
                        # The original plan-only owner remains in its own context;
                        # continuation receives the actual evolved spatial owner.
                        continuation_case = dict(case, funding=base._spatial.funding,
                            created_tracers=('tracer:accumulated_strain_ii',), state=state)
                        duration = IW.require_initial_duration(control, continuation_case,
                            expected=IW.authenticated_duration(admission, budget))
                        record['initial_workload'] = dict(state=state.record(), duration_s=duration,
                            gate='equals the authenticated historical head advance duration_s')
                        del state
                        profiling.checkpoint('frozen-initial-workload-authenticated')
                        publication = dict(prepare_next=not stop_before_advance,
                            producer_identity=profile.sha256,
                            runtime_identity=execution.provenance['execution_identity']) if compact else {}
                        with publish_and_reopen(store, base, budget=budget, check=check, phase=guard.phase,
                                                **publication) as workflow:
                            profiling.checkpoint('root-published-and-reopened')
                            record['published_root'] = _published_root(workflow, store, base, case,
                                                                       execution, budget)
                            storage_point(record, 'after-publish-reopen', checkpoint=destination, store=store)
                            save()
                            if stop_before_advance:
                                before, after = record['published_root']['inspect'], None
                                guard.phase('stopped-before-advance-root-published')
                            else:
                                guard.phase('advance-exactly-one-current-interval')
                                # The declared owner records its counts after flush(), on success and failure.
                                with completed_queries(EndpointCheckpoints, query_directory, declared=declared,
                                        arguments=query_arguments, execution=execution, budget=budget,
                                        cancel=check, limits=query_limits, record=record, save=save,
                                        query_stages=query_stages) as query_checkpoints:
                                    storage_point(record, 'before-advance', checkpoint=destination,
                                                  query_directory=query_directory, store=store)
                                    save()
                                    before, after = _advance_checked(driver, workflow=workflow, base=base,
                                        case=continuation_case, execution=execution, guard=guard,
                                        record=record, save=save, artifacts=output,
                                        query_checkpoints=query_checkpoints)
                                storage_point(record, 'after-advance', checkpoint=destination,
                                              query_directory=query_directory, store=store)
                                save()
                                del query_checkpoints
                            if compact:
                                if after is None:      # root-only: store already sealed (line 636); unchanged
                                    record['record_identities'] = reader.endpoint_record_identities(workflow)
                                else:
                                    # R2 option A: bounded
                                    # pre-seal checks of this unsealed interval only, no
                                    # per-scalar decode; the fresh reader re-derives the rest.
                                    from atlas_tectonics._private.integration import bounded_preseal as PRESEAL
                                    evidence = PRESEAL.bounded_preseal(workflow, store=store, before=before,
                                        after=after, budget=base._budget, cancel=check)
                                    record['record_identities'] = evidence.pop('record_identities')
                                    record['preseal_bounded_check'] = evidence
                                    save()
                                    store.seal_and_promote(after['head'])
                                record['compact_operations'] = store.statistics()
                        # publish_and_reopen cold-reopened the published root in
                        # this process. The successor is not reopened here (owner
                        # decision): _advance_checked ran the cheap
                        # structural checks, bounded_preseal ran the bounded
                        # pre-seal checks (R2 option A), and the mandatory
                        # independent fresh-process reader performs the successor
                        # cold reopen and per-scalar re-derivation on the sealed file.
                        record.update(migrated_base=base.record(), previous_endpoint=before,
                            checkpoint=str(destination), independent_process_reopen=False)
                        if after is None:
                            record['same_process_cold_reopen'] = True
                        else:
                            record.update(advanced_endpoint=after, same_process_cold_reopen=False,
                                same_process_cold_reopen_reason=SAME_PROCESS_REOPEN_DROPPED,
                                successor_checks=list(SUCCESSOR_CHECKS))
                        del continuation_case, base, workflow
                del current_store, store
                storage_point(record, 'after-store-close', checkpoint=destination,
                              query_directory=query_directory, output=output)
                save()
                del admission
        require(file_hash(original_path, check) == original_pin, 'original checkpoint changed')
        record['checkpoint_sha256'] = file_hash(destination, check)
        if compact:
            record['compact_storage'] = reader.storage_inventory(destination, budget=budget, check=check)
        record['original_database_unchanged'] = True
        profiling.checkpoint('sources-and-original-verified')
        return budget
    finally:
        # Even a failed continuation cannot silently lose its original binding.
        # The outer workload records errors/held memory before retiring frames.
        if original_path is not None:
            active_error = sys.exception()
            try:
                require(file_hash(original_path, check) == original_pin, 'original checkpoint changed during failed work')
            except BaseException as verification_error:
                if active_error is None:
                    raise
                active_error.add_note('Original binding finalisation also failed: '+repr(verification_error))


def gate_key(profile, python, *, stop_before_advance=False, dev_timing=False):
    return RG.command_key(profile, python, entry=__file__, step='producer',
                          stop_before_advance=stop_before_advance, dev_timing=dev_timing)


def command(profile, python, *, stop_before_advance=False, dev_timing=False, start_gate=None,
            production_release=False, run_profile=frozenset(), _sources=None):
    """Inspectable guarded command only; never launches or reads the database."""
    require(type(stop_before_advance) is bool, 'explicit stop-before-advance mode required')
    require(type(dev_timing) is bool, 'dev timing flag must be boolean')
    require(type(production_release) is bool and not (production_release and (dev_timing or run_profile)),
            'production Release is explicit and development diagnostics remain strict-only')
    sources = RestartSources(profile) if _sources is None else _sources
    if production_release:
        expected = production_decision(sources,'prepared')
        require(start_gate == expected, 'production command requires its authenticated source/table decision')
    row = profile.record()
    output = Path(row['output_directory'])
    ordinary(output.parent, directory=True)
    require(output.is_relative_to(sources.workspace) and not output.exists(), 'exclusive new output directory required')
    guard = sources.path(row['modules']['private_heat_continuation_guard_r3'])
    return [str(ordinary(python)), '-B', str(guard), '--launch', '--output', str(output/'run.json'), '--',
        str(ordinary(python)), '-B', str(Path(__file__).resolve()), '--workload',
        '--profile', str(profile.path), '--profile-sha256', profile.sha256,
        *(['--stop-before-advance'] if stop_before_advance else []),
        *(['--dev-timing'] if dev_timing else []),
        *profiling.profile_words(run_profile.intersection(('stages',))),
        *(['--production-release'] if production_release else []),
        *([SG.ARGUMENT, SG.encode(start_gate)] if start_gate is not None else [])]


def _workload(profile, *, stop_before_advance=False, dev_timing=False, start_gate=None,
              production_release=False, run_profile=frozenset()):
    require(sys.dont_write_bytecode, 'run with -B to preserve frozen sources')
    require(type(production_release) is bool and not (production_release and (dev_timing or run_profile)),
            'production Release is explicit and development diagnostics remain strict-only')
    child = None if production_release else SG.child_admit(start_gate, MONITOR.free_memory())
    sources = RestartSources(profile)
    admitted = production_admission(sources,'prepared',start_gate) if production_release else None
    output = Path(profile.record()['output_directory'])/'run.json'
    record = dict(schema=RESULT_SCHEMA, status='STARTED', pid=os.getpid(),
        profile_sha256=profile.sha256, errors=[], production_acceptance=False,
        stop_before_advance=stop_before_advance)
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
        guard = G.ContinuationGuard(output, record, save,
            **({key:admitted['guard_limits'][key] for key in ('rss_bytes','free_floor_bytes')}
               if admitted is not None else SG.guardian_limits(child)))
        record_stages = dev_timing or 'stages' in run_profile
        with profiling.collect(guard, output.parent, enabled=record_stages, record=record,
                            metadata=dict(profile_sha256=profile.sha256)):
            budget = run_prepared_restart(profile, sources=sources, guard=guard, record=record, save=save,
                                          stop_before_advance=stop_before_advance, start_gate=start_gate,
                                          query_stages=query_stages, production_release=production_release)
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
            if guard is not None:
                guard.check(force=True)
                guard.close()
        except BaseException as error:
            record['errors'].append(dict(type=type(error).__name__, message=str(error)))
        query_stages.finish()
        record['status'] = final_status(record['errors'], stop_before_advance=stop_before_advance)
        save()
    return 0 if not record['errors'] else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', type=Path, required=True)
    parser.add_argument('--profile-sha256', required=True)
    parser.add_argument('--stop-before-advance', action='store_true')
    parser.add_argument('--dev-timing', action='store_true', help='opt-in development timing and memory diagnostics')
    parser.add_argument('--run-profile', default='off')
    parser.add_argument('--production-release',action='store_true',help='explicit authenticated packaged production only')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--launch', action='store_true')
    mode.add_argument('--workload', action='store_true')
    parser.add_argument(SG.ARGUMENT)
    RG.SG.add_arguments(
        parser,
        peak_help='matching Route 2 successor LM postcheck or reader final record (repeatable)',
        bytes_help='declared peak; used only without measured records',
        basis_help='explicit source/basis of that booking',
    )
    args = parser.parse_args(argv)
    require(args.start_gate is None or args.workload, '--start-gate is reserved for --workload')
    require(not args.workload or not (args.peak_records or args.booking_bytes is not None or args.booking_basis is not None),
            'measurement/booking arguments belong to --launch')
    dev_timing = _dev_timing_enabled(args.dev_timing)
    run_profile = profiling.profile_selection(args.run_profile)
    require(not args.production_release or not (dev_timing or run_profile or args.peak_records or args.booking_bytes is not None
            or args.booking_basis is not None), 'production Release never books and refuses development diagnostics')
    profile = RestartProfile.read(args.profile, args.profile_sha256)
    if args.workload:
        return _workload(profile, stop_before_advance=args.stop_before_advance, dev_timing=dev_timing,
                         start_gate=args.start_gate, production_release=args.production_release, run_profile=run_profile)
    gate = None
    sources = None
    if args.production_release:
        sources = RestartSources(profile)
        gate = production_decision(sources,'prepared')
    elif args.launch:
        gate = RG.decide(gate_key(profile, sys.executable, stop_before_advance=args.stop_before_advance,
                                 dev_timing=dev_timing), records=args.peak_records,
                         booking_bytes=args.booking_bytes, booking_basis=args.booking_basis)
    argv = command(profile, sys.executable, stop_before_advance=args.stop_before_advance, dev_timing=dev_timing,
                   start_gate=gate, production_release=args.production_release, run_profile=run_profile, _sources=sources)
    print(json.dumps(dict(status='SOURCE_BOUND_COMMAND_ONLY_NOT_ADMISSION', command=argv,
        production_acceptance=False)), flush=True)
    if not args.launch:
        return 0
    if args.production_release:
        production_admission(sources,'prepared',SG.encode(gate))
    else:
        SG.admit(gate, MONITOR.free_memory())
    output = Path(profile.record()['output_directory'])
    output.mkdir(exist_ok=False)
    return subprocess.call(argv, env=launch_environment(), cwd=output)


if __name__ == '__main__':
    raise SystemExit(main())
