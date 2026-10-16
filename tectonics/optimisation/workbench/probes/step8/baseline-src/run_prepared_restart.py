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
persisted. By owner decision (14 Oct 2026) the runner no longer cold-reopens the
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
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from hashlib import sha256
import argparse
import gc
import importlib
import importlib.machinery
import inspect
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys


RSS_BYTES, FREE_BYTES, START_BYTES, LOGICAL_BYTES = 12 << 30, 1 << 30, 10 << 30, 16 << 30
PROFILE_SCHEMA = 'atlas.prepared-restart-launch.v1'
RESULT_SCHEMA = 'atlas.prepared-restart-result.v1'
PASS_STATUS = 'PASS_ONE_INTERVAL_PENDING_INDEPENDENT_REOPEN'
STOPPED_STATUS = 'STOPPED_BEFORE_ADVANCE_ROOT_PUBLISHED'
MAX_CONFIG = 8 << 20
HISTORICAL_RELATIVE = 'fidelity-integration-20261005/heat-repair-20261007'
HISTORICAL_NATIVE_RELATIVE = 'native-composed-r7/tectonics/src'
HISTORICAL_SOURCE_MANIFEST_SHA256 = 'f81fd25ca3b68d031b006a0e6eab4d6b278affa86e5d062baeafd748f17ee42c'
# Seed and thread settings are fixed at interpreter start; workers inherit them.
LAUNCH_ENV = dict(OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1', PYTHONHASHSEED='0',
                  PYTHONDONTWRITEBYTECODE='1')
REQUIRED_MODULES = ('native_transfer', 'spatial_transfer', 'geometry_transfer',
    'workflow_transfer', 'historical_admission', 'runtime_compatibility',
    'materialise_endpoint', 'plan_preparation', 'private_heat_continuation_guard_r3',
    'windows_workload_job', 'private_heat_resource_diagnostics_r1', 'dev_stage_timing', 'initial_workload',
    'funding_transfer', 'continuation_transfer', 'compact_store', 'mesh_tables',
    'spatial_indexed_patch', 'spatial_workflow_patch', 'partition_tables', 'partition_store',
    'partition_workflow_patch', 'partition_native_patch', 'partition_routing_patch',
    'partition_routing_transform', 'pressure_indexed_patch', 'heat_payload_indexed_patch',
    'private_heat_indexed_runtime', 'private_heat_restored_binding_ram_context_r1',
    'private_heat_restored_binding_ram_recovery_r1', 'private_heat_process_meter_r1',
    'private_heat_gmp_resources_r1', 'private_heat_functionals_parallel_r1',
    'private_heat_issuer_resources_r1', 'private_heat_original_coverage_r3',
    'probe_heat_original_connected_r9', 'private_heat_joined_consumer_r6',
    'private_heat_original_joined_r6', 'private_heat_original_continuation_r1',
    'private_heat_geometry_observer_r1', 'i04_differential_modes')
QUERY_LIMIT_FIELDS = frozenset(('max_entries', 'max_store_bytes'))
STORE_STATISTICS = ('unique_chunks', 'encoded_payload_bytes', 'snapshots', 'database_bytes')
SAME_PROCESS_REOPEN_DROPPED = ('dropped by owner decision 14 Oct 2026; '
                               'the mandatory independent fresh-process reader performs the cold reopen')
# Each name is one refusal in _successor_checks, in order; run.json lists them.
SUCCESSOR_CHECKS = ('live_head_identity', 'live_head_advanced_exactly_one_interval',
    'live_root_workflow_and_funding_unchanged', 'successor_head_persisted',
    'persisted_head_equals_live_head', 'persisted_successor_links_parent', 'persisted_parent_unchanged',
    'persisted_root_unchanged', 'clock_advanced_and_persisted', 'no_further_successor',
    'store_unchanged_during_checks')


class RestartRefused(ValueError):
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


def historical_import_path(workspace, entry):
    """H itself, its old native src or any H/native-composed-r* tree.

    H/source/tectonics/tests stays importable: it holds the retained controls.
    The historical helpers in H's root must come from the composed copies.
    """
    historical = Path(workspace)/HISTORICAL_RELATIVE
    path = Path(entry or '.').resolve()
    if not path.is_relative_to(historical):
        return False
    relative = path.relative_to(historical).parts
    return not relative or relative == ('source', 'tectonics', 'src') or relative[0].startswith('native-composed-r')


def final_status(errors, *, stop_before_advance):
    # A stopped staged run is never an interval result, whatever else passed.
    return 'FAILED' if errors else (STOPPED_STATUS if stop_before_advance else PASS_STATUS)


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
        fields = {'schema', 'workspace', 'source_manifest', 'native_root', 'import_roots',
            'modules', 'preparation', 'compatibility_policy', 'evidence_root',
            'historical_source_root', 'advance_driver', 'output_directory',
            'store_limits', 'compression', 'completed_query_directory', 'completed_query_limits'}
        require(type(row) is dict and set(row) == fields and row['schema'] == PROFILE_SCHEMA,
                'closed reviewed restart profile required')
        require(type(row['modules']) is dict and set(row['modules']) == set(REQUIRED_MODULES),
                'complete explicit helper module bindings required')
        for field in ('source_manifest', 'preparation', 'compatibility_policy'):
            require(type(row[field]) is dict and set(row[field]) == {'path', 'sha256'},
                    'explicit path and source pin required: '+field)
            _sha(row[field]['sha256'])
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
    """Parameterised I/runtime.py fence; complete package and helper membership.

    The manifest's existing files map uses workspace-relative paths and its
    source_hashes map uses native-root-relative paths. data_only names files
    read as data and never imported. Import directories are explicit, not
    discovered from unrelated work. No source alias is installed.
    """
    __slots__ = ('profile', 'workspace', 'native_root', 'import_roots', 'manifest_path',
                 'manifest_pin', '_manifest', 'selected_now', '_sealed')

    def __setattr__(self, name, value):
        if getattr(self, '_sealed', False):
            raise RestartRefused('selected source configuration is immutable')
        object.__setattr__(self, name, value)

    def __init__(self, profile):
        require(type(profile) is RestartProfile, 'typed pinned restart profile required')
        profile.verify()
        self.profile = profile
        row = profile.record()
        self.workspace = ordinary(row['workspace'], directory=True)
        self.native_root = self.path(row['native_root'], directory=True)
        self.import_roots = tuple(self.path(p, directory=True) for p in row['import_roots'])
        self.manifest_path = self.path(row['source_manifest']['path'])
        self.manifest_pin = row['source_manifest']['sha256']
        manifest = pinned_json(self.manifest_path, self.manifest_pin)
        require(type(manifest.get('files')) is dict and manifest['files'] and
                type(manifest.get('source_hashes')) is dict and manifest['source_hashes'],
                'whole native inventory and all participating helpers required')
        require(type(manifest.get('data_only')) is dict and
                not set(manifest['data_only']) & set(manifest['files']),
                'explicit data-only references disjoint from importable sources required')
        self._manifest = json.dumps(manifest, sort_keys=True, separators=(',', ':')).encode()
        self.selected_now = False
        self._sealed = True

    def path(self, name, *, directory=False):
        require(type(name) is str and name and '\\' not in name and ':' not in name and
                not Path(name).is_absolute() and '..' not in Path(name).parts,
                'canonical contained workspace-relative path required')
        path = ordinary(self.workspace/name, directory=directory)
        require(path.is_relative_to(self.workspace), 'source escaped workspace')
        return path

    def files(self):
        return dict(_json(self._manifest)['files'])

    def verify(self):
        self.profile.verify()
        observed = pinned_json(self.manifest_path, self.manifest_pin)
        require(json.dumps(observed, sort_keys=True, separators=(',', ':')).encode() == self._manifest,
                'in-memory source manifest differs from its pinned record')
        manifest = _json(self._manifest)
        for name, pin in manifest['files'].items():
            require(file_hash(self.path(name)) == _sha(pin), 'participating source changed: '+name)
        for name, pin in manifest['data_only'].items():
            require(file_hash(self.path(name)) == _sha(pin), 'data-only reference changed: '+name)
        actual = {p.relative_to(self.native_root).as_posix(): file_hash(p)
                  for p in sorted((self.native_root/'atlas_tectonics').rglob('*.py'))}
        require(actual and actual == manifest['source_hashes'], 'complete native package inventory changed')
        for name, pin in actual.items():
            relative = (self.native_root/name).relative_to(self.workspace).as_posix()
            require(manifest['files'].get(relative) == pin, 'native source absent from import closure')
        row = self.profile.record()
        for name in row['modules'].values():
            require(name in manifest['files'], 'required transfer/guard helper missing from closure')
        for binding in (row['preparation'], row['advance_driver']):
            require(manifest['files'].get(binding['path']) == binding['sha256'],
                    'prepared fixture or next-interval driver absent from source closure')
        own = Path(__file__).resolve()
        require(own.is_relative_to(self.workspace) and
                manifest['files'].get(own.relative_to(self.workspace).as_posix()) == file_hash(own),
                'restart orchestrator itself must be pinned')
        pinned_json(self.path(row['compatibility_policy']['path']), row['compatibility_policy']['sha256'])
        return dict(source_manifest_sha256=self.manifest_pin,
            native_source_digest=sha256(json.dumps(actual, sort_keys=True, separators=(',', ':')).encode()).hexdigest())

    def check_paths(self):
        """No live sys.path entry may expose the historical runtime or helpers.

        Native ALE workers inherit this list; a late historical entry would make
        them import the old package only after hours of work.
        """
        for entry in tuple(sys.path):
            require(not historical_import_path(self.workspace, entry),
                    'historical import root on sys.path refused: '+str(entry))

    def check_imported(self):
        manifest = _json(self._manifest)
        pins, data = manifest['files'], manifest['data_only']
        self.check_paths()
        native = self.native_root/'atlas_tectonics'
        roots = (self.native_root, *self.import_roots)
        found = {}
        for name, module in tuple(sys.modules.items()):
            filename = getattr(module, '__file__', None)
            if name == 'atlas_tectonics' or name.startswith('atlas_tectonics.'):
                require(type(filename) is str and Path(filename).resolve().is_relative_to(native),
                        'native module outside the selected runtime refused: '+name)
            if not filename:
                continue
            path = Path(filename).resolve()
            if (not path.is_relative_to(self.workspace) or path.suffix != '.py' or
                    path.is_relative_to(self.workspace/'.r44-env')):
                continue
            relative = path.relative_to(self.workspace).as_posix()
            require(relative not in data, 'data-only reference imported as code: '+relative)
            require(relative in pins and file_hash(path) == pins[relative], 'unbound participating import: '+relative)
            if '.' not in name and name != '__main__' and path.stem == name:
                # The same name must still resolve to this file over the selected
                # roots; a later path edit cannot substitute a same-named original.
                first = next((candidate for root in roots
                              for candidate in (root/name/'__init__.py', root/(name+'.py'))
                              if candidate.is_file()), None)
                require(first is not None and first.resolve() == path,
                        'top-level module is not its first resolution over selected roots: '+name)
            found[relative] = pins[relative]
        return found

    def module(self, name):
        require(self.selected_now, 'source selection must precede imports')
        row = self.profile.record()
        expected = (row['advance_driver']['path'] if name == row['advance_driver']['module']
                    else row['modules'][name])
        module = importlib.import_module(name)
        require(ordinary(module.__file__) == self.path(expected), 'helper module shadowing refused: '+name)
        self.check_imported()
        return module

    @contextmanager
    def selected(self):
        require(not self.selected_now, 'nested runtime selection refused')
        self.verify()
        loaded = sys.modules.get('atlas_tectonics')
        require(loaded is None, 'native runtime selection requires a fresh process')
        before = list(sys.path)
        owner = self
        pins = _json(self._manifest)['files']

        class Loader(importlib.machinery.SourceFileLoader):
            def get_code(self, fullname):
                path = ordinary(self.path)
                name = path.relative_to(owner.workspace).as_posix()
                raw = path.read_bytes()
                require(name in pins and sha256(raw).hexdigest() == pins[name], 'unbound source import: '+name)
                return compile(raw, str(path), 'exec', dont_inherit=True)

        class Finder:
            def find_spec(self, fullname, path=None, target=None):
                spec = importlib.machinery.PathFinder.find_spec(fullname, path, target)
                if spec and spec.origin and spec.origin.endswith('.py'):
                    location = Path(spec.origin).resolve()
                    if (location.is_relative_to(owner.workspace) and
                            not location.is_relative_to(owner.workspace/'.r44-env')):
                        spec.loader = Loader(fullname, str(location))
                return spec

        finder = Finder()
        sys.path[:0] = [str(self.native_root), *(str(p) for p in self.import_roots)]
        sys.meta_path.insert(0, finder)
        object.__setattr__(self, 'selected_now', True)
        try:
            self.check_imported()
            yield self
            self.check_imported()
        finally:
            object.__setattr__(self, 'selected_now', False)
            sys.meta_path.remove(finder)
            sys.path[:] = before
            self.verify()


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


def _guard_boundary(sources, guard, budget):
    H = sources.module('historical_admission')
    G = sources.module('private_heat_continuation_guard_r3')
    J = sources.module('windows_workload_job')
    R = sources.module('private_heat_resource_diagnostics_r1')
    require(type(guard) is G.ContinuationGuard and not guard.closed and guard.budget is budget,
            'actual active shared-budget Windows-job guardian required')
    require(guard._control['limits'] == dict(rss_bytes=RSS_BYTES, free_floor_bytes=FREE_BYTES),
            'exact retained 12 GiB / 1 GiB resource guards required')
    check = lambda: guard.check(force=True)
    H._loaded_source_fence(G, H.GUARD_PIN, check)
    H._loaded_source_fence(J, H.JOB_PIN, check)
    # Passive diagnostics run inside the guardian; bind them like the guard.
    require(getattr(G, 'RESOURCE_DIAGNOSTICS', None) is R and getattr(R, 'WJ', None) is J,
            'guardian diagnostics binding replaced')
    require(type(getattr(H, 'DIAGNOSTICS_PIN', None)) is str, 'reviewed guardian diagnostics pin missing')
    H._loaded_source_fence(R, H.DIAGNOSTICS_PIN, check)
    context = _json(os.environ[G.ENV])
    require(context['nonce'] == guard.nonce and context['output'] == str(guard.output) and
            J.verify_current_membership(context['job_name']) == guard.identity and
            guard._sync()['status'] == 'RUNNING', 'current external guardian membership differs')
    check()


def _check_historical_root(sources, H, row):
    """Historical evidence stays bound to the original H, wherever H.py lives."""
    root = sources.path(HISTORICAL_RELATIVE, directory=True)
    require(Path(H.HISTORICAL_ROOT).resolve() == root and
            sources.path(row['historical_source_root'], directory=True) == root/HISTORICAL_NATIVE_RELATIVE,
            'historical evidence root differs from the workspace-anchored original candidate')


def _compatibility(sources, row):
    return dict(policy_path=sources.path(row['compatibility_policy']['path']),
        policy_sha256=row['compatibility_policy']['sha256'],
        evidence_root=sources.path(row['evidence_root'], directory=True),
        historical_source_root=sources.path(row['historical_source_root'], directory=True),
        current_source_root=sources.native_root)


def _check_runtime_binding(base, row, execution, budget):
    """The admitted policy must name the manifest and execution actually selected."""
    import workflow_transfer as W
    scratch = W._decode_allocation(budget, base._runtime._record)
    runtime = base._runtime.record()
    require(runtime['current_source_manifest_sha256'] == row['source_manifest']['sha256'] and
            runtime['historical_source_manifest_sha256'] == HISTORICAL_SOURCE_MANIFEST_SHA256 and
            runtime['current_execution_identity'] == execution.provenance['execution_identity'],
            'reviewed runtime admission does not bind the selected manifest and execution')
    _ = scratch


def _copy_bound_file(source, expected, destination, *, budget, check):
    """Exclusive fsynced copy whose bytes equal an existing authenticated pin."""
    import native_transfer as N
    source = ordinary(source)
    destination = Path(destination).absolute()
    ordinary(destination.parent, directory=True)
    require(not destination.exists() and destination != source, 'fresh separate checkpoint required')
    require(not any(Path(str(source)+s).exists() for s in ('-wal', '-journal', '-shm')),
            'source checkpoint must remain closed without sidecars')
    expected = _sha(expected)
    # Copy and hash once, then independently hash the closed destination. The
    # source pin is authenticated before this phase; callers recheck it at exit.
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
            digest.hexdigest() == expected == file_hash(destination, check), 'authenticated checkpoint copy differs')
    _ = allocation
    return source, expected


def _copy_original(admission, destination, *, budget, check):
    import workflow_transfer as W
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
    path = ordinary(checkpoint)
    row = dict(label=label, checkpoint=str(path), checkpoint_bytes=path.stat().st_size,
        sidecars=[s for s in ('-wal', '-journal', '-shm') if Path(str(path)+s).exists()])
    if query_directory is not None:
        row['completed_query_directory'] = _census(ordinary(query_directory, directory=True))
    if output is not None:
        row['output_tree'] = _tree(ordinary(output, directory=True))
    if store is not None:
        statistics = store.statistics()
        row['store'] = {key: statistics[key] for key in STORE_STATISTICS}
    record.setdefault('storage', []).append(row)
    return row


@contextmanager
def publish_and_reopen(store, base, *, budget, check, phase):
    """Real publication + cold reopen, reusable by the explicitly synthetic test.

    Both called issuers reject dicts and preserve original immutable history.
    The enclosing public runner supplies the authenticated, current live base.
    """
    import workflow_transfer as W
    from atlas_tectonics.integration_regional_workflow import CollarWorkflow
    from atlas_tectonics.storage import ArrayStore
    require(type(base) is W.MigratedWorkflowBase and type(store) is ArrayStore and
            base._budget is budget and store._budget is budget, 'actual shared-budget base/store required')
    phase('publish-migrated-root')
    check()
    with W.publish_migrated_root(store, base, budget=budget) as published:
        require(type(published) is CollarWorkflow, 'actual published workflow required')
        before = published.inspect()
        workflow_id = published.workflow_id
    phase('cold-reopen-migrated-root')
    token = store.change_token()
    with CollarWorkflow.open_migrated(store, workflow_id, base, budget=budget) as workflow:
        require(type(workflow) is CollarWorkflow and workflow.inspect() == before and
                store.change_token() == token, 'migration root cold reopen changed state or wrote to store')
        check()
        yield workflow


def _published_root(workflow, store, base, case, execution, budget):
    """Root identity a fresh reader must reproduce; recorded in both run modes."""
    import workflow_transfer as W
    scratch = W._decode_allocation(budget, workflow._root)
    root = json.loads(workflow._root)
    require(store.metadata(root['key']) == root, 'published root differs from its reopened metadata')
    collar = case['collar']
    result = dict(workflow_id=workflow.workflow_id, root_key=root['key'], root_metadata_sha256=W.digest(root),
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

    Owner decision 14 Oct 2026: the successor is no longer cold-reopened in this
    process; the mandatory independent fresh-process reader performs that cold
    reopen. Only the live workflow and small store metadata are read here (the
    new head, its parent, the root and the absent next key); no array or payload.
    inspect() on the live workflow is cheap when the driver's own publication
    left it at the current store token; a workflow left stale makes the native
    _refresh re-validate the persisted chain and restore its head (slower, never
    weaker). ``store`` is the workflow's store captured before the driver. A
    textual success, an unpersisted or foreign head, a changed parent, root,
    workflow, store or funding, a stalled clock or a second successor is refused.
    Returns the live inspect() record, the producer's advanced endpoint.
    """
    import workflow_transfer as W
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
                     query_checkpoints=None, fence):
    """Ignore textual success; structurally check one persisted successor.

    No same-process cold reopen follows the driver (owner decision 14 Oct 2026);
    _successor_checks reads the live workflow and small store metadata only.
    The independent fresh-process reader remains mandatory.
    """
    import workflow_transfer as W
    from atlas_tectonics.integration_regional_workflow import CollarWorkflow
    require(type(workflow) is CollarWorkflow and type(base) is W.MigratedWorkflowBase and
            workflow._migration is base and callable(fence), 'actual admitted migrated workflow required')
    before = workflow.inspect()
    parent = dict(workflow._head)
    root_bytes, store = workflow._root, workflow._store
    capture_variable = 'ATLAS_FOCUSED_ARTIFACT_DIR'
    previous_capture = os.environ.get(capture_variable)
    # Workers inherit sys.path at spawn; check it immediately before and after.
    fence()
    os.environ[capture_variable] = str(ordinary(artifacts, directory=True))
    try:
        driver(case=case, workflow=workflow, base=base, execution=execution, guard=guard,
               record=record, save=save, artifacts=artifacts, query_checkpoints=query_checkpoints)
    finally:
        if previous_capture is None:
            os.environ.pop(capture_variable, None)
        else:
            os.environ[capture_variable] = previous_capture
    fence()
    # No token or execution identity is overwritten to coerce a reader into
    # accepting persisted bytes; the independent reader cold-reopens them.
    return before, _successor_checks(workflow, store=store, before=before, parent=parent,
                                     root_bytes=root_bytes, budget=base._budget)


def run_prepared_restart(profile, *, sources, guard, record, save, stop_before_advance=False):
    """Actual prepare/admit/transfer/copy/publish/reopen/advance orchestration.

    Call under sources.selected() and the live external guard. No mock or JSON
    capability is accepted. All output paths derive from the one fresh profile
    directory; neither the original store nor prior receipts are writable here.
    With stop_before_advance the published root is reopened and recorded, and
    no driver, completed-query owner or physical interval work runs.
    """
    require(type(profile) is RestartProfile and type(sources) is RestartSources and
            sources.profile is profile and sources.selected_now, 'actual selected pinned sources required')
    require(type(stop_before_advance) is bool, 'explicit stop-before-advance mode required')
    row = profile.record()
    H = sources.module('historical_admission')
    M = sources.module('materialise_endpoint')
    W = sources.module('workflow_transfer')
    P = sources.module('plan_preparation')
    IW = sources.module('initial_workload')
    timing = sources.module('dev_stage_timing')
    driver_module = sources.module(row['advance_driver']['module'])
    require('working_store' in inspect.signature(M.materialise).parameters,
            'store-aware compact endpoint materialisation is not composed')
    driver = getattr(driver_module, 'advance_prepared_interval', None)
    require(inspect.isfunction(driver) and driver.__module__ == driver_module.__name__,
            'named source-bound next-interval implementation required')
    inspect.signature(driver).bind(**{k: None for k in
        ('case', 'workflow', 'base', 'execution', 'guard', 'record', 'save', 'artifacts',
         'query_checkpoints')})
    from atlas_tectonics.resources import WorkBudget
    from atlas_tectonics.reuse import ExecutionContext, require_strict_execution
    from atlas_tectonics.storage import ArrayStore, StoreLimits, Compression
    from atlas_tectonics.integration_regional_workflow import CollarWorkflow
    from atlas_tectonics.integration_endpoint_checkpoints import EndpointCheckpoints
    # Bind every participating helper to its reviewed path before any work; a
    # same-named historical original can then never be resolved by later imports.
    bound = {name: sources.module(name) for name in REQUIRED_MODULES}
    control = bound['i04_differential_modes'].ACTUATED_CONTROL
    require(hasattr(CollarWorkflow, 'open_migrated'), 'composed migrated-root native reader is missing')
    require_strict_execution()
    record.update(interpreter_gate(), stop_before_advance=stop_before_advance)
    _check_historical_root(sources, H, row)
    output = Path(row['output_directory'])
    require(ordinary(output, directory=True) == output and output.is_relative_to(sources.workspace) and
            guard.output == output/'run.json', 'guard and fresh restart output directory differ')
    destination = output/'checkpoint.sqlite'
    require(not destination.exists() and not any(output.glob('checkpoint.sqlite*')),
            'restart checkpoint output already exists')
    query_directory = sources.workspace/row['completed_query_directory']
    ordinary(query_directory.parent, directory=True)
    require(query_directory.resolve().is_relative_to(sources.workspace) and
            not query_directory.is_relative_to(output),
            'explicit reusable completed-query directory must be outside this attempt')
    query_directory.mkdir(exist_ok=True)
    ordinary(query_directory, directory=True)
    query_limits = row['completed_query_limits']
    import psutil
    available = psutil.virtual_memory().available
    require(available >= START_BYTES, 'restart requires 10 GiB available at startup')
    guard.budget = budget = WorkBudget(LOGICAL_BYTES, max_predicate_work_units=1 << 44)
    _guard_boundary(sources, guard, budget)
    H._loaded_source_fence(driver_module, row['advance_driver']['sha256'],
                           lambda: guard.check(force=True))
    record.update(guard_limits=dict(rss_bytes=RSS_BYTES, free_floor_bytes=FREE_BYTES,
        start_available_bytes=START_BYTES, logical_budget_bytes=LOGICAL_BYTES),
        memory_at_start=dict(available_bytes=available), source_proof=sources.verify(),
        completed_query_limits=dict(query_limits),
        production_acceptance=False, original_producer_status_unchanged=True)
    limits, compression = StoreLimits(**row['store_limits']), Compression(**row['compression'])
    require(shutil.disk_usage(output).free >= 2*limits.max_store_bytes + limits.max_staging_bytes +
            query_limits['max_store_bytes'],
            'insufficient disk headroom for preserved source, new checkpoint/staging and query quota')
    preparation = P.load_preparation(sources.path(row['preparation']['path']))
    compatibility = _compatibility(sources, row)
    check = lambda: guard.check(force=True)
    guard.phase('prepare-current-plans-without-funding')
    original_path = original_pin = None
    try:
        with ExecutionContext('scipy') as execution, preparation(budget=budget, pressure_space='q1-p0',
                material_quadrature=True) as case:
            timing.checkpoint('current-plans-prepared')
            guard.phase('authenticate-historical-endpoint-readonly')
            with H.open_original_readonly(limits=limits, compression=compression, budget=budget) as original:
                admission = H.admit_historical_endpoint(original, execution=execution, budget=budget, guard=guard)
                require(type(admission) is W.HistoricalEndpointAdmission, 'historical issuer returned no admission')
                timing.checkpoint('historical-endpoint-authenticated')
                guard.phase('copy-authenticated-checkpoint-to-fresh-output')
                original_path, original_pin = _copy_original(admission, destination, budget=budget, check=check)
                timing.checkpoint('authenticated-checkpoint-copied')
                storage_point(record, 'original', checkpoint=original_path)
                storage_point(record, 'after-copy', checkpoint=destination, query_directory=query_directory,
                              output=output)
                save()
                # Compact conversion may publish immutable table snapshots only
                # in this exclusive copy, never in the authenticated original.
                with ArrayStore(destination, limits, compression, budget=budget) as store:
                    guard.phase('transfer-authenticated-endpoint-to-current-owners')
                    # The forced check stays unwrapped (materialise throttles the
                    # mesh side, PW the partition nodes); phases reach the guard.
                    with M.materialise(original_store=original, admission=admission, native=case['native'],
                            collar=case['collar'], execution=execution, compatibility=compatibility,
                            budget=budget, check=check, working_store=store, phase=guard.phase) as base:
                        timing.checkpoint('endpoint-materialised')
                        require(type(base) is W.MigratedWorkflowBase and
                                type(base._runtime) is W.RuntimeCompatibilityAdmission,
                                'materialiser returned no authenticated current base')
                        sources.verify()
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
                        timing.checkpoint('frozen-initial-workload-authenticated')
                        with publish_and_reopen(store, base, budget=budget, check=check, phase=guard.phase) as workflow:
                            timing.checkpoint('root-published-and-reopened')
                            record['published_root'] = _published_root(workflow, store, base, case,
                                                                       execution, budget)
                            storage_point(record, 'after-publish-reopen', checkpoint=destination, store=store)
                            save()
                            if stop_before_advance:
                                before, after = record['published_root']['inspect'], None
                                guard.phase('stopped-before-advance-root-published')
                            else:
                                guard.phase('advance-exactly-one-current-interval')
                                with EndpointCheckpoints(query_directory, context=execution,
                                        budget=budget, cancel=check, max_store_bytes=query_limits['max_store_bytes'],
                                        max_entries=query_limits['max_entries']) as query_checkpoints:
                                    storage_point(record, 'before-advance', checkpoint=destination,
                                                  query_directory=query_directory, store=store)
                                    save()
                                    try:
                                        before, after = _advance_checked(driver, workflow=workflow, base=base,
                                            case=continuation_case, execution=execution, guard=guard,
                                            record=record, save=save, artifacts=output,
                                            query_checkpoints=query_checkpoints, fence=sources.check_imported)
                                    finally:
                                        record['completed_queries'] = dict(directory=str(query_directory),
                                            hits=query_checkpoints.hits, misses=query_checkpoints.misses,
                                            written=query_checkpoints.written, incomplete=query_checkpoints.incomplete,
                                            scope='validated completed queries only; strict current execution binding')
                                        save()
                                storage_point(record, 'after-advance', checkpoint=destination,
                                              query_directory=query_directory, store=store)
                                save()
                                del query_checkpoints
                        # publish_and_reopen cold-reopened the published root in
                        # this process. The successor is not reopened here (owner
                        # decision 14 Oct 2026): _advance_checked ran the cheap
                        # structural checks and the mandatory independent
                        # fresh-process reader performs the successor cold reopen.
                        record.update(migrated_base=base.record(), previous_endpoint=before,
                            checkpoint=str(destination), independent_process_reopen=False)
                        if after is None:
                            record['same_process_cold_reopen'] = True
                        else:
                            record.update(advanced_endpoint=after, same_process_cold_reopen=False,
                                same_process_cold_reopen_reason=SAME_PROCESS_REOPEN_DROPPED,
                                successor_checks=list(SUCCESSOR_CHECKS))
                        del continuation_case, base, workflow
                storage_point(record, 'after-store-close', checkpoint=destination,
                              query_directory=query_directory, output=output)
                save()
                del admission
            execution.verify_boundary()
        sources.check_imported()
        sources.verify()
        require(file_hash(original_path, check) == original_pin, 'original checkpoint changed')
        record['checkpoint_sha256'] = file_hash(destination, check)
        record['original_database_unchanged'] = True
        timing.checkpoint('sources-and-original-verified')
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


def command(profile, python, *, stop_before_advance=False, dev_timing=False):
    """Inspectable guarded command only; never launches or reads the database."""
    require(type(stop_before_advance) is bool, 'explicit stop-before-advance mode required')
    require(type(dev_timing) is bool, 'dev timing flag must be boolean')
    sources = RestartSources(profile)
    sources.verify()
    row = profile.record()
    output = Path(row['output_directory'])
    ordinary(output.parent, directory=True)
    require(output.is_relative_to(sources.workspace) and not output.exists(), 'exclusive new output directory required')
    guard = sources.path(row['modules']['private_heat_continuation_guard_r3'])
    return [str(ordinary(python)), '-B', str(guard), '--launch', '--output', str(output/'run.json'), '--',
        str(ordinary(python)), '-B', str(Path(__file__).resolve()), '--workload',
        '--profile', str(profile.path), '--profile-sha256', profile.sha256,
        *(['--stop-before-advance'] if stop_before_advance else []),
        *(['--dev-timing'] if dev_timing else [])]


def _workload(profile, *, stop_before_advance=False, dev_timing=False):
    dev_timing = _dev_timing_enabled(dev_timing)
    require(sys.dont_write_bytecode, 'run with -B to preserve frozen sources')
    sources = RestartSources(profile)
    output = Path(profile.record()['output_directory'])/'run.json'
    record = dict(schema=RESULT_SCHEMA, status='STARTED', pid=os.getpid(),
        profile_sha256=profile.sha256, errors=[], production_acceptance=False,
        stop_before_advance=stop_before_advance)
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
                                metadata=dict(profile_sha256=profile.sha256)):
                budget = run_prepared_restart(profile, sources=sources, guard=guard, record=record, save=save,
                                              stop_before_advance=stop_before_advance)
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
                sources.check_imported()
                sources.verify()
                if guard is not None:
                    guard.check(force=True)
                    guard.close()
            except BaseException as error:
                record['errors'].append(dict(type=type(error).__name__, message=str(error)))
            record['status'] = final_status(record['errors'], stop_before_advance=stop_before_advance)
            save()
    return 0 if not record['errors'] else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', type=Path, required=True)
    parser.add_argument('--profile-sha256', required=True)
    parser.add_argument('--stop-before-advance', action='store_true')
    parser.add_argument('--dev-timing', action='store_true', help='opt-in development timing and memory diagnostics')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--launch', action='store_true')
    mode.add_argument('--workload', action='store_true')
    args = parser.parse_args(argv)
    dev_timing = _dev_timing_enabled(args.dev_timing)
    profile = RestartProfile.read(args.profile, args.profile_sha256)
    if args.workload:
        return _workload(profile, stop_before_advance=args.stop_before_advance, dev_timing=dev_timing)
    argv = command(profile, sys.executable, stop_before_advance=args.stop_before_advance, dev_timing=dev_timing)
    print(json.dumps(dict(status='SOURCE_BOUND_COMMAND_ONLY_NOT_ADMISSION', command=argv,
        production_acceptance=False)), flush=True)
    if not args.launch:
        return 0
    import psutil
    require(psutil.virtual_memory().available >= START_BYTES, 'restart requires 10 GiB available at startup')
    output = Path(profile.record()['output_directory'])
    output.mkdir(exist_ok=False)
    return subprocess.call(argv, env=launch_environment(), cwd=output)


if __name__ == '__main__':
    raise SystemExit(main())
