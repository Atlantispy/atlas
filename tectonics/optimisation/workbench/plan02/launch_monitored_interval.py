"""External tracked launcher for one monitored prepared-restart interval.

Never imported by the workload and outside the native package. The launch uses
only the runner's RestartProfile.read and command() for the exact guarded argv,
adding what automatic geometry needs before the interpreter starts:
PYTHONHASHSEED=0, single-thread OpenBLAS/OpenMP and no bytecode writes. Every
preflight refusal precedes any output. Admission uses the source-bound
Route 2 measured peak or an explicit booking; the guard keeps its
unchanged 12 GiB RSS / 1 GiB free-floor policy.

  --launch     preflight (a-i), exclusive OUT.launch.json, launch, wait at most
               60 s for RUNNING, print the tracking line, wait, then postcheck
  --status     read-only summary (never touches the query-store lock)
  --cancel     exclusive OUT/run.cancel; wait at most 15 s for a terminal guard
  --postcheck  closed acceptance checklist into exclusive OUT.postcheck.json
  --stop-before-advance (with --launch) the staged smoke: root published and
               reopened, no interval; its postcheck expects that status only

A postcheck PASS means PASS_ONE_INTERVAL_PENDING_INDEPENDENT_REOPEN (or, staged,
STOPPED_BEFORE_ADVANCE_ROOT_PUBLISHED) with clean guard, worker, reservation and
source evidence; it is not acceptance. The independent fresh-process reader
remains mandatory: since the owner decision of 14 Oct 2026 the runner no longer
cold-reopens the interval's successor itself and records exactly that, with its
reason; a staged run still records its same-process root reopen.
"""
from hashlib import sha256
import argparse
from datetime import datetime, timezone
import importlib.util
import inspect
import json
import math
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
_SELF_SHA = sha256(Path(__file__).read_bytes()).hexdigest()
import start_gate as SG
import route2_gate as RG

RSS_BYTES, FREE_BYTES, LOGICAL_BYTES = SG.RSS_BYTES, SG.FREE_BYTES, SG.LOGICAL_BYTES
WARN_BYTES = 14 << 30  # Route 1 launcher advisory only (published L records memory.warning); no gate effect
RUNNING_SECONDS, CANCEL_SECONDS, POLL_SECONDS = 60., 15., .25
DEFAULT_QUERY_STORE_BYTES = 1 << 30  # EndpointCheckpoints default when no profile limit exists
LAUNCH_ENV = dict(PYTHONHASHSEED='0', OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1', PYTHONDONTWRITEBYTECODE='1')
# Instrumentation or import-path overrides change the selector gate or the
# imported closure; refuse them rather than silently strip them.
HOOK_ENV = ('COVERAGE_PROCESS_START', 'PYTHONPROFILEIMPORTTIME', 'PYTHONTRACEMALLOC', 'PYTHONSTARTUP',
            'PYTHONDEVMODE', 'PYTHONMALLOC', 'PYTHONMALLOCSTATS', 'PYTHONINSPECT', 'PYTHONOPTIMIZE',
            'PYTHONPATH', 'PYTHONHOME')
REBOOT_KEYS = (r'SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\RebootRequired',
               r'SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\RebootPending')
ORIGINAL_DATABASE = ('fidelity-integration-20261005/heat-repair-20261007/'
                     'heat-original-connected-20261013-r9.artifacts/native-joined.sqlite',
                     '3f70c26de17535a96b7ddd494aee72900decee272ae0f88edab3a42af1548899')
GUARD_SCHEMA = 'atlas.private.continuation-guard.r3'
SUMMARY_SCHEMA = 'atlas.private.resource-summary.r1'
RUN_SCHEMA = 'atlas.prepared-restart-result.v1'
PASS_STATUS = 'PASS_ONE_INTERVAL_PENDING_INDEPENDENT_REOPEN'
STOPPED_STATUS = 'STOPPED_BEFORE_ADVANCE_ROOT_PUBLISHED'
SEED_RECORD = {'PYTHONHASHSEED': '0', 'hash_randomization': 0}
CLEAN = {'remaining': [], 'action_errors': []}
EPOCH_TICKS = 116444736000000000  # FILETIME ticks at the Unix epoch
# The runner's reason for not cold-reopening an interval's successor in process.
COLD_REOPEN_DROPPED = ('dropped by owner decision 14 Oct 2026; '
                       'the mandatory independent fresh-process reader performs the cold reopen')


class LaunchRefused(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise LaunchRefused(message)


def _sha(value):
    require(type(value) is str and len(value) == 64 and all(c in '0123456789abcdef' for c in value),
            'exact lowercase SHA-256 required')
    return value


def _ordinary(path, *, directory=False):
    path = Path(path).absolute()
    for item in (path, *path.parents):
        info = item.lstat()
        require(not stat.S_ISLNK(info.st_mode) and not getattr(info, 'st_file_attributes', 0) & 0x400,
                'linked/reparsed path refused')
    require(path.is_dir() if directory else path.is_file(), 'ordinary file/directory required: '+str(path))
    return path.resolve()


def file_hash(path):
    path = _ordinary(path)
    identity = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns)
    before, result = path.stat(), sha256()
    with path.open('rb') as stream:
        while block := stream.read(1 << 20):
            result.update(block)
        after = os.fstat(stream.fileno())
    require(identity(before) == identity(after) == identity(path.stat()), 'file changed during hash: '+str(path))
    return result.hexdigest()


def _json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'duplicate JSON key')
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=pairs,
        parse_constant=lambda _: (_ for _ in ()).throw(LaunchRefused('nonfinite JSON')))


def _read(path, tries=50):
    """A guard-owned JSON written by replace; tolerate only sharing races."""
    for attempt in range(tries):
        try:
            return _json(Path(path).read_bytes())
        except FileNotFoundError:
            return None
        except (PermissionError, json.JSONDecodeError):
            if attempt == tries-1:
                raise
            time.sleep(.02)


def _peek(path):
    """Polling read while the run is live: a sharing race is not a launcher failure."""
    try:
        return _read(path)
    except (OSError, ValueError):
        return None


def _write_exclusive(path, value):
    raw = (json.dumps(value, indent=2, sort_keys=True, allow_nan=False)+'\n').encode()
    with open(path, 'xb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return sha256(raw).hexdigest()


def paths(output):
    output = Path(output)
    sibling = lambda suffix: output.parent/(output.name+suffix)
    return dict(out=output, launch=sibling('.launch.json'), log=sibling('.launch.log'),
        tracking=sibling('.tracking.json'), postcheck=sibling('.postcheck.json'), run=output/'run.json',
        guard=output/'run.guard.json', control=output/'run.guard-control.json',
        abort=output/'run.guard-abort.json', cancel=output/'run.cancel', checkpoint=output/'checkpoint.sqlite')


def _exec_runner(path, raw, pin):
    name = '_monitored_runner_'+sha256((str(path)+pin).encode()).hexdigest()[:16]
    module = sys.modules.get(name)
    if module is None:
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        try:
            exec(compile(raw, str(path), 'exec', dont_inherit=True), module.__dict__)
        except BaseException:
            del sys.modules[name]
            raise
    require(file_hash(path) == pin, 'runner source changed while loading')
    profile = getattr(module, 'RestartProfile', None)
    require(callable(getattr(module, 'command', None)) and callable(getattr(profile, 'read', None)),
            'runner lacks RestartProfile.read and command()')
    return module


def load_runner(profile_path, profile_sha256, path=None):
    """Execute only runner bytes that the pinned profile's pinned manifest names.

    The profile and manifest pins are checked here BEFORE any runner code runs;
    the runner's own RestartProfile.read then applies its closed schema.
    """
    path = _ordinary(HERE/'run_prepared_restart.py' if path is None else path)
    raw = path.read_bytes()
    pin = sha256(raw).hexdigest()
    profile = _ordinary(profile_path)
    data = profile.read_bytes()
    require(sha256(data).hexdigest() == _sha(profile_sha256), 'pinned restart profile changed')
    row = _json(data)
    require(type(row) is dict, 'restart profile object required')
    workspace, manifest = _pinned_manifest(row)
    _bound_file(workspace, manifest, path, pin, 'runner')
    return _exec_runner(path, raw, pin), path, pin


def _pinned_manifest(row):
    workspace = _ordinary(row['workspace'], directory=True)
    binding = row['source_manifest']
    path = _ordinary(workspace/binding['path'])
    require(path.is_relative_to(workspace), 'source manifest escaped workspace')
    raw = path.read_bytes()
    require(sha256(raw).hexdigest() == _sha(binding['sha256']), 'pinned source manifest changed')
    manifest = _json(raw)
    require(type(manifest.get('files')) is dict, 'source manifest files map required')
    return workspace, manifest


def _bound_file(workspace, manifest, path, pin, label):
    path = _ordinary(path)
    require(path.is_relative_to(workspace) and
            manifest['files'].get(path.relative_to(workspace).as_posix()) == pin,
            label+' bytes are not the profile manifest pin')


def _fold(text):
    return os.path.normcase(str(text))


def _available_bytes():
    import psutil
    return psutil.virtual_memory().available


def _disk_free(path):
    return shutil.disk_usage(path).free


def _pending_reboot():
    """Read-only HKLM key presence; unreadable keys fail closed upstream."""
    import winreg
    found = []
    for key in REBOOT_KEYS:
        try:
            winreg.CloseKey(winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key, 0, winreg.KEY_READ))
            found.append(key)
        except FileNotFoundError:
            pass
    return found


def _matching_processes(needles):
    """Live Python processes naming this run, except this launcher and its ancestors.

    Launcher, guardian, workload and workers are all Python; an editor or shell
    merely viewing a receipt is not a live run and must not fail a postcheck.
    """
    import psutil
    own = {os.getpid(), *(p.pid for p in psutil.Process().parents())}
    folded = [_fold(n) for n in needles]
    rows = []
    for process in psutil.process_iter(['pid', 'name', 'cmdline']):
        if process.info['pid'] in own or not (process.info.get('name') or '').lower().startswith('py'):
            continue
        text = _fold(' '.join(process.info.get('cmdline') or ()))
        if any(n in text for n in folded):
            rows.append(dict(pid=process.info['pid'], cmdline=process.info['cmdline']))
    return rows


def _alive(identity):
    """Exact pid plus FILETIME creation identity; PID reuse is not liveness."""
    import psutil
    pid, ticks = identity.get('pid'), identity.get('created_ticks')
    require(type(pid) is int and type(ticks) is int, 'exact process identity required')
    try:
        created = psutil.Process(pid).create_time()
    except psutil.NoSuchProcess:
        return False
    return abs(created - (ticks-EPOCH_TICKS)/1e7) < .01


def _lock_held(path):
    if os.name != 'nt':
        import fcntl
        with open(path, 'rb') as stream:
            try:
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                return True
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
            return False
    import msvcrt
    # Opened read-only: the probe never creates or truncates the owner lock.
    with open(path, 'rb') as stream:
        try:
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            return True
        stream.seek(0)
        msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        return False


def _query_state(directory, *, probe_lock):
    state = dict(path=str(directory), exists=directory.is_dir(), queries=0, query_bytes=0,
                 partials=0, partial_bytes=0, other=0, lock_held=None)
    if not state['exists']:
        return state
    with os.scandir(directory) as entries:
        for entry in entries:
            if entry.name == 'owner.lock':
                continue
            size = entry.stat(follow_symlinks=False).st_size
            if entry.name.endswith('.query'):
                state['queries'] += 1
                state['query_bytes'] += size
            elif '.partial-' in entry.name:
                state['partials'] += 1
                state['partial_bytes'] += size
            else:
                state['other'] += 1
    lock = directory/'owner.lock'
    if probe_lock:
        state['lock_held'] = lock.exists() and _lock_held(lock)
    return state


def _profile(module, profile_path, profile_sha256):
    profile = module.RestartProfile.read(Path(profile_path), _sha(profile_sha256))
    row = profile.record()
    output = Path(row['output_directory']).absolute()
    # The guard compares resolved strings; a case/8.3 alias would fail late.
    require(str(output) == str(output.resolve()), 'canonical absolute output directory required')
    return profile, row, output


def _dev_timing_enabled(flag=False, environ=None):
    """Validate opt-in locally; preflight never imports the workload helper."""
    require(type(flag) is bool, 'dev timing flag must be boolean')
    value = (os.environ if environ is None else environ).get('ATLAS_DEV_STAGE_TIMING', '')
    require(value in ('', '0', '1'), 'ATLAS_DEV_STAGE_TIMING must be unset, 0 or 1')
    return flag or value == '1'


def preflight(profile_path, profile_sha256, *, runner=None, python=None, environ=None,
              stop_before_advance=False, dev_timing=False, peak_records=(), booking_bytes=None, booking_basis=None):
    """Checks a-i; returns the launch plan. Writes and launches nothing."""
    require(os.name == 'nt', 'Windows job-object launch required')
    require(type(stop_before_advance) is bool, 'explicit staged/interval mode required')
    environ = dict(os.environ if environ is None else environ)
    dev_timing = _dev_timing_enabled(dev_timing, environ)
    module, runner_path, runner_pin = load_runner(profile_path, profile_sha256, runner)
    profile, row, output = _profile(module, profile_path, profile_sha256)                 # a
    workspace = _ordinary(row['workspace'], directory=True)
    python = _ordinary(sys.executable if python is None else python)
    staged = {}
    if stop_before_advance:
        require('stop_before_advance' in inspect.signature(module.command).parameters,
                'runner has no stop-before-advance mode')
        staged = dict(stop_before_advance=True)
    if dev_timing:
        require('dev_timing' in inspect.signature(module.command).parameters,
                'runner has no dev-timing mode')
        staged['dev_timing'] = True
    require(callable(getattr(module, 'gate_key', None)), 'runner has no Route 2 admission interface')
    gate = RG.decide(module.gate_key(profile, python, stop_before_advance=stop_before_advance,
                                    dev_timing=dev_timing), records=peak_records,
                     booking_bytes=booking_bytes, booking_basis=booking_basis)
    argv = module.command(profile, python, start_gate=gate, **staged)                    # a: sources verified
    p = paths(output)
    tail = ['--profile', str(profile.path), '--profile-sha256', profile_sha256]
    tail += ['--stop-before-advance'] if stop_before_advance else []
    tail += ['--dev-timing'] if dev_timing else []
    tail += [SG.ARGUMENT, SG.encode(gate)]
    require(type(argv) is list and all(type(item) is str for item in argv) and len(argv) >= 10+len(tail) and
            argv[:2] == [str(python), '-B'] and argv[3:7] == ['--launch', '--output', str(p['run']), '--'] and
            argv[7:9] == [str(python), '-B'] and argv[-len(tail):] == tail,
            'runner command differs from the guarded launch shape')
    guard, workload = _ordinary(argv[2]), _ordinary(argv[9])
    available = _available_bytes()                                                      # b
    admitted = SG.admit(gate, available)
    limits = module.COMPACT_STORE_LIMITS if row.get('storage_format') == 'interval-catalog-v1' else row['store_limits']
    query_limits = row.get('completed_query_limits') or {}
    query_bytes = query_limits.get('max_store_bytes', DEFAULT_QUERY_STORE_BYTES)
    parts = (limits.get('max_store_bytes'), limits.get('max_staging_bytes'), query_bytes)
    require(all(type(v) is int and v > 0 for v in parts), 'explicit positive store/query byte limits required')
    required, free = 2*parts[0]+parts[1]+parts[2], _disk_free(output.parent)           # c
    require(free >= required, 'insufficient disk headroom for checkpoint, staging and query quota')
    siblings = sorted(item.name for item in output.parent.iterdir() if _fold(item.name) == _fold(output.name)
                      or _fold(item.name).startswith(_fold(output.name)+'.'))
    require(not siblings, 'fresh output and sibling records required: '+', '.join(siblings))  # d
    query = workspace/row['completed_query_directory']
    _ordinary(query.parent, directory=True)                                             # e
    queries = _query_state(query, probe_lock=True)
    require(not queries['lock_held'], 'completed-query owner lock is held by a live process')
    matches = _matching_processes([str(output)+os.sep, str(profile.path)])             # f
    require(not matches, 'a live process already names this output or profile')
    hooks = sorted(name for name in HOOK_ENV if name in environ)                        # g
    require(not hooks, 'instrumentation/import-path environment refused: '+', '.join(hooks))
    require(environ.get('PYTHONHASHSEED') in (None, '0'), 'PYTHONHASHSEED must be unset or 0')
    reboot = _pending_reboot()                                                          # h
    require(not reboot, 'pending Windows restart: '+'; '.join(reboot))
    env = dict(environ, **LAUNCH_ENV)
    record = dict(schema='atlas.private.monitored-interval-launch.r1', status='PREFLIGHT_PASSED',
        utc=datetime.now(timezone.utc).isoformat(), launcher=dict(pid=os.getpid(), path=str(Path(__file__).resolve()),
        sha256=_SELF_SHA), python=str(python), argv=argv, cwd=str(output),
        env={name: env[name] for name in LAUNCH_ENV}, profile=dict(path=str(profile.path), sha256=profile_sha256),
        runner=dict(path=str(runner_path), sha256=runner_pin), guard=dict(path=str(guard), sha256=file_hash(guard)),
        workload=dict(path=str(workload), sha256=file_hash(workload)), source_manifest=row['source_manifest'],
        memory=dict(available_bytes=available, hard_gate_bytes=admitted['gate_bytes']), start_gate=admitted,
        disk=dict(free_bytes=free, required_bytes=required, query_quota_bytes=query_bytes,
                  query_quota_source='profile' if 'max_store_bytes' in query_limits else 'endpoint-checkpoint default'),
        completed_queries=queries, pending_reboot=reboot, process_matches=matches,
        stop_before_advance=stop_before_advance, dev_timing=dev_timing, production_acceptance=False)
    return dict(argv=argv, env=env, paths=p, record=record, gate=gate)


def _terminal(receipt):
    status = (receipt or {}).get('status')
    return status in ('PARENT_EXITED', 'HARD_STOPPED', 'HARD_STOP_FAILED', 'GUARDIAN_FAILED') or (
        status == 'STOPPED' and receipt.get('workload_exit_confirmed') is True)


def _await_running(process, p):
    deadline = time.monotonic()+RUNNING_SECONDS
    while process.poll() is None:
        receipt = _peek(p['guard'])
        if receipt is not None and receipt.get('status') == 'RUNNING' and receipt.get('parent'):
            return receipt
        if time.monotonic() >= deadline:
            # Not RUNNING within 60 s: cooperative cancel; the guard hard-stops.
            try:
                open(p['cancel'], 'x').close()
            except FileExistsError:
                pass
            return None
        time.sleep(POLL_SECONDS)
    return None


def _track(process, receipt, p):
    import psutil
    child = psutil.Process(process.pid)
    guardian = receipt['guardian']['pid']
    members = {child.pid: child, **{item.pid: item for item in child.children(recursive=True)}}
    require(guardian in members, 'guardian is not the launched process or its descendant')
    row = dict(schema='atlas.private.monitored-interval-tracking.r1', output=str(p['out']),
        utc=datetime.now(timezone.utc).isoformat(), launcher_pid=os.getpid(),
        child=dict(pid=child.pid, create_time=child.create_time()),
        guardian=dict(pid=guardian, create_time=members[guardian].create_time(), cmdline=members[guardian].cmdline()),
        job_name=receipt.get('job_name'), parent=receipt['parent'], launch_cohort=receipt.get('launch_cohort'))
    _write_exclusive(p['tracking'], row)
    return row


def launch(profile_path, profile_sha256, *, runner=None, python=None, environ=None, stop_before_advance=False,
           dev_timing=False, peak_records=(), booking_bytes=None, booking_basis=None, emit=print):
    plan = preflight(profile_path, profile_sha256, runner=runner, python=python, environ=environ,
                     stop_before_advance=stop_before_advance, dev_timing=dev_timing, peak_records=peak_records,
                     booking_bytes=booking_bytes, booking_basis=booking_basis)
    p = plan['paths']
    _write_exclusive(p['launch'], plan['record'])                                       # i
    emit(json.dumps(dict(status='PREFLIGHT_PASSED', output=str(p['out']),
        hard_gate_bytes=plan['record']['memory']['hard_gate_bytes'], available_bytes=plan['record']['memory']['available_bytes'])))
    p['out'].mkdir(exist_ok=False)
    with open(p['log'], 'xb') as log:
        process = subprocess.Popen(plan['argv'], env=plan['env'], cwd=p['out'], stdin=subprocess.DEVNULL,
            stdout=log, stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        receipt = _await_running(process, p)
        if receipt is None:
            emit(json.dumps(dict(status='NOT_RUNNING', output=str(p['out']), exit=process.poll())))
        else:
            try:
                tracking = _track(process, receipt, p)
                emit(json.dumps(dict(status='RUNNING', guardian=tracking['guardian']['pid'],
                    parent=tracking['parent'], job_name=tracking['job_name'],
                    launch_cohort=tracking['launch_cohort'], output=str(p['out']))))
            except Exception as error:
                # The guarded run is live; never abandon it. Postcheck will refuse.
                emit(json.dumps(dict(status='RUNNING_UNTRACKED', reason=repr(error), output=str(p['out']))))
        code = process.wait()
    except KeyboardInterrupt:
        emit(json.dumps(dict(status='LAUNCHER_DETACHED', output=str(p['out']),
            note='the guarded run continues; use --status, --cancel or --postcheck')))
        return 130
    result = postcheck(profile_path, profile_sha256, runner=runner)
    emit(json.dumps(dict(status=result['status'], guardian_exit=code, failures=result['failures'],
                         postcheck=str(p['postcheck']))))
    return 0 if code == 0 and result['status'] == 'PASS' else 1


def postcheck(profile_path, profile_sha256, *, runner=None, write=True):
    """Closed checklist after exit. Each check fails closed on any exception."""
    module, runner_path, runner_pin = load_runner(profile_path, profile_sha256, runner)
    profile, row, output = _profile(module, profile_path, profile_sha256)
    p = paths(output)
    require(not p['postcheck'].exists(), 'exclusive postcheck record required')
    checks, warnings, records, snapshots = [], [], {}, {}
    for name in ('launch', 'tracking', 'run', 'guard', 'control'):
        try:
            snapshots[name] = RG.read_snapshot(p[name])
            records[name] = snapshots[name][0]
        except (OSError, ValueError) as error:
            records[name] = None
            warnings.append(name+' unreadable: '+repr(error))
    launch, tracking, run, guard, control = (records[k] or {} for k in ('launch', 'tracking', 'run', 'guard', 'control'))
    # The mode comes only from the exclusive launch record; staged is never PASS of an interval.
    staged = launch.get('stop_before_advance') is True

    def check(name, test):
        try:
            ok, detail = test(), None
            if type(ok) is tuple:
                ok, detail = ok
        except Exception as error:
            ok, detail = False, repr(error)
        checks.append(dict(name=name, ok=ok is True, detail=detail))

    integer = lambda v, low=0: type(v) is int and v >= low
    number = lambda v: type(v) in (int, float) and math.isfinite(v)
    # Guard, control, tracking and launch bindings.
    check('guard_schema', lambda: guard['schema'] == GUARD_SCHEMA)
    check('guard_stopped', lambda: (guard['status'] == 'STOPPED' and not guard.get('reason'),
                                    dict(status=guard.get('status'), reason=guard.get('reason'))))
    check('guard_exit', lambda: (guard['workload_exit_confirmed'] is True and guard['workload_exit_code'] == 0,
                                 guard.get('workload_exit_code')))
    check('guard_cleanup', lambda: guard['cleanup'] == CLEAN and 'cleanup_error' not in guard)
    check('guard_limits', lambda: guard['limits'] == dict(rss_bytes=RSS_BYTES, free_floor_bytes=FREE_BYTES) and
          guard['sample_interval'] == .25 and guard['grace_seconds'] == 5.)
    check('guard_parent', lambda: integer(guard['parent']['pid'], 1) and guard['parent']['pid'] == run['pid'] and
          integer(guard['parent']['created_ticks'], 1))
    check('guard_control', lambda: control['parent'] == guard['parent'] and control['nonce'] == guard['nonce'] and
          control['close_requested'] is True and control['limits'] == guard['limits'])
    check('guard_supervisor', lambda: integer(guard['guardian']['pid'], 1) and
          run['supervisor']['pid'] == guard['guardian']['pid'] and run['supervisor']['status'] == 'STOPPED')
    check('guard_no_abort', lambda: not p['abort'].exists() and not p['cancel'].exists())
    check('resource_summary', lambda: guard['resource_summary']['schema'] == SUMMARY_SCHEMA)
    if guard.get('resource_summary_error'):
        warnings.append('passive resource summary stopped: '+str(guard['resource_summary_error']))
    check('tracking', lambda: tracking['guardian']['pid'] == guard['guardian']['pid'] and
          tracking['parent'] == guard['parent'] and tracking['output'] == str(output))
    check('launch_record', lambda: launch['schema'] == 'atlas.private.monitored-interval-launch.r1' and
          launch['profile']['sha256'] == profile_sha256 and launch['runner']['sha256'] == runner_pin and
          launch['launcher']['sha256'] == _SELF_SHA and launch['cwd'] == str(output) and
          launch['env'] == LAUNCH_ENV and type(launch['stop_before_advance']) is bool)
    check('launch_sources_unchanged', lambda: file_hash(launch['guard']['path']) == launch['guard']['sha256'] and
          file_hash(launch['workload']['path']) == launch['workload']['sha256'] and file_hash(runner_path) == runner_pin)

    def no_live_workers():
        identities = [guard['parent'], *guard.get('launch_cohort', [])]
        live = [identity for identity in identities if _alive(identity)]
        import psutil
        try:
            guardian = psutil.Process(tracking['guardian']['pid'])
            if guardian.create_time() == tracking['guardian']['create_time']:
                live.append(dict(guardian=tracking['guardian']['pid']))
        except psutil.NoSuchProcess:
            pass
        named = _matching_processes([str(output)+os.sep])
        return not live and not named, dict(live=live, named=named)
    check('no_live_workers', no_live_workers)
    # The workload's own receipt: one committed interval, nothing retained.
    check('run_schema', lambda: run['schema'] == RUN_SCHEMA)
    check('run_status', lambda: (run['status'] == (STOPPED_STATUS if staged else PASS_STATUS) and
                                 run['stop_before_advance'] is staged, run.get('status')))
    check('run_errors', lambda: (run['errors'] == [], run.get('errors')))
    check('zero_reservations', lambda: (run['final_reserved_bytes'] == 0 and integer(run['final_reserved_bytes']),
                                        run.get('final_reserved_bytes')))
    check('not_production_acceptance', lambda: run['production_acceptance'] is False)
    check('original_unchanged_recorded', lambda: run['original_database_unchanged'] is True)
    # Interval: the runner's structural successor checks replace its same-process
    # cold reopen (owner decision 14 Oct 2026), recorded with exactly that reason.
    # Staged: only the published root, cold-reopened in the runner's process.
    check('reopen_scope', lambda: run['independent_process_reopen'] is False and (
        run['same_process_cold_reopen'] is True and 'same_process_cold_reopen_reason' not in run if staged else
        run['same_process_cold_reopen'] is False and run['same_process_cold_reopen_reason'] == COLD_REOPEN_DROPPED))

    def one_interval():
        before, after = run['previous_endpoint'], run['advanced_endpoint']
        return (integer(before['intervals']) and after['intervals'] == before['intervals']+1 and
                number(before['time_s']) and number(after['time_s']) and after['time_s'] > before['time_s'] and
                after['head'] != before['head'] and after['funding_id'] == before['funding_id'])
    if staged:
        check('root_only', lambda: integer(run['previous_endpoint']['intervals']) and
              'advanced_endpoint' not in run and 'completed_queries' not in run)
    else:
        check('one_interval', one_interval)
    check('run_guard_limits', lambda: run['guard_limits'] == SG.guard_limits(run['start_gate']))
    def run_start_gate():
        key = module.gate_key(profile, launch['python'], stop_before_advance=staged,
                              dev_timing=launch['dev_timing'])
        child = run['start_gate']
        class Seed:
            hash_randomization = child.get('hash_randomization')
        SG.admit(child, child.get('available_bytes'), Seed())
        strip = lambda value: {k: v for k, v in value.items() if k not in ('available_bytes', 'hash_randomization')}
        return child['key'] == key and strip(child) == strip(launch['start_gate'])
    check('run_start_gate', run_start_gate)
    check('profile_pin', lambda: run['profile_sha256'] == profile_sha256)
    check('interpreter_seed', lambda: (run['interpreter_seed'] == SEED_RECORD, run.get('interpreter_seed')))
    if not staged:
        check('completed_queries', lambda: all(integer(run['completed_queries'][k])
                                               for k in ('hits', 'misses', 'written', 'incomplete')))
    # Persisted bytes and source/input stability, recomputed now.
    def checkpoint():
        if row.get('storage_format') == 'interval-catalog-v1':
            import reopen_prepared_restart as reader
            workspace, manifest = _pinned_manifest(row)
            reader_path = _ordinary(reader.__file__)
            require(reader_path == _ordinary(workspace/row['modules']['reopen_prepared_restart']),
                    'compact storage verifier helper shadowed')
            _bound_file(workspace, manifest, reader_path, file_hash(reader_path), 'compact storage verifier')
            expected = output/'compact-checkpoint'/'interval-catalog.json'
            storage = reader.verify_storage(run['compact_storage'])
            return (run['checkpoint'] == storage['catalog'] == str(expected) and
                run['checkpoint_sha256'] == storage['catalog_sha256'] and
                run['compact_retained_after_close']['retained_bytes'] == 0)
        return (run['checkpoint'] == str(p['checkpoint']) and
            not any(Path(str(p['checkpoint'])+s).exists() for s in ('-wal', '-journal', '-shm')) and
            file_hash(p['checkpoint']) == _sha(run['checkpoint_sha256']))
    check('checkpoint', checkpoint)
    original = Path(row['workspace'])/ORIGINAL_DATABASE[0]
    check('original_database', lambda: not any(Path(str(original)+s).exists() for s in ('-wal', '-journal', '-shm'))
          and file_hash(original) == ORIGINAL_DATABASE[1])
    check('sources', lambda: (module.RestartSources(profile).verify() == run['source_proof'], run.get('source_proof')))
    gate_evidence = None
    if all(item['ok'] for item in checks):
        def capture_gate_evidence():
            nonlocal gate_evidence
            snapshots['profile'] = RG.read_snapshot(profile.path)
            require(snapshots['profile'][1]['sha256'] == profile_sha256, 'completion profile changed')
            key = module.gate_key(profile, launch['python'], stop_before_advance=staged,
                                  dev_timing=launch['dev_timing'])
            gate_evidence = RG.evidence(key, snapshots)
            return True
        check('gate_evidence', capture_gate_evidence)
    failures = [item['name'] for item in checks if not item['ok']]
    result = dict(schema='atlas.private.monitored-interval-postcheck.r1', status='FAILED' if failures else 'PASS',
        utc=datetime.now(timezone.utc).isoformat(), output=str(output), profile_sha256=profile_sha256,
        launcher_sha256=_SELF_SHA, stop_before_advance=staged, checks=checks, failures=failures, warnings=warnings,
        production_acceptance=False, independent_process_reopen_required=True)
    if not failures:
        result['gate_evidence'] = gate_evidence
    if write:
        _write_exclusive(p['postcheck'], result)
    return result


def status(profile_path, profile_sha256, *, runner=None):
    """Read-only. Never probes or takes the live query-store owner lock."""
    import psutil
    module, _, _ = load_runner(profile_path, profile_sha256, runner)
    _, row, output = _profile(module, profile_path, profile_sha256)
    p = paths(output)
    guard, run, tracking = _read(p['guard']) or {}, _read(p['run']) or {}, _read(p['tracking']) or {}
    sample = guard.get('latest_sample') or {}
    least = [phase.get('least_available_ram') for phase in (guard.get('sampled_peak_by_phase') or {}).values()]
    alive = None
    if tracking:
        try:
            alive = psutil.Process(tracking['guardian']['pid']).create_time() == tracking['guardian']['create_time']
        except psutil.NoSuchProcess:
            alive = False
    latest = ((guard.get('resource_summary') or {}).get('latest') or {})
    return dict(schema='atlas.private.monitored-interval-status.r1', output=str(output),
        launched=p['launch'].exists(), postchecked=p['postcheck'].exists(), guardian_alive=alive,
        guard=dict(status=guard.get('status'), reason=guard.get('reason'), phase=guard.get('phase'),
            elapsed_seconds=guard.get('elapsed_seconds'), samples=guard.get('samples'),
            available_ram_bytes=sample.get('available_ram_bytes'),
            least_available_ram_bytes=min((v for v in least if type(v) is int), default=None),
            process_tree_rss_bytes=sample.get('process_tree_rss_bytes'),
            process_tree_private_bytes=sample.get('process_tree_private_bytes'),
            worker_process_count=sample.get('worker_process_count'),
            cpu_percent=latest.get('overlapping_identity_cpu_percent'),
            sampled_peak_bytes=guard.get('sampled_peak_bytes'),
            resource_summary_error=guard.get('resource_summary_error')),
        run=dict(status=run.get('status'), stage=run.get('stage'), errors=len(run.get('errors') or ()),
                 phases=run.get('phases')),
        completed_queries=_query_state(Path(row['workspace'])/row['completed_query_directory'], probe_lock=False))


def cancel(profile_path, profile_sha256, *, runner=None, terminate_unresponsive_guardian=False):
    """Cooperative cancel through the guard's own file; never kills by name.

    Only with the explicit flag, after 15 s without a terminal receipt, the
    exact tracked guardian (pid, creation time and command line) is terminated;
    its kill-on-close job then ends every workload member.
    """
    module, _, _ = load_runner(profile_path, profile_sha256, runner)
    _, _, output = _profile(module, profile_path, profile_sha256)
    p = paths(output)
    require(p['launch'].is_file() and p['out'].is_dir(), 'no launched interval at this profile output')
    receipt = _peek(p['guard'])
    if _terminal(receipt):
        return dict(status='ALREADY_TERMINAL', guard_status=receipt['status'], reason=receipt.get('reason'))
    try:
        open(p['cancel'], 'x').close()
        requested = True
    except FileExistsError:
        requested = False
    deadline = time.monotonic()+CANCEL_SECONDS
    while time.monotonic() < deadline:
        receipt = _peek(p['guard']) or receipt
        if _terminal(receipt):
            run = _peek(p['run']) or {}
            return dict(status='CANCELLED', created_cancel=requested, guard_status=receipt['status'],
                        reason=receipt.get('reason'), cleanup=receipt.get('cleanup'), run_status=run.get('status'))
        time.sleep(POLL_SECONDS)
    tracking = _peek(p['tracking'])
    if not terminate_unresponsive_guardian or not tracking:
        return dict(status='CANCEL_REQUESTED_UNCONFIRMED', created_cancel=requested,
                    guard_status=(receipt or {}).get('status'), guardian=(tracking or {}).get('guardian'))
    import psutil
    expected = tracking['guardian']
    guardian = psutil.Process(expected['pid'])
    require(guardian.create_time() == expected['create_time'] and guardian.cmdline() == expected['cmdline'],
            'tracked guardian identity differs; nothing terminated')
    guardian.terminate()
    guardian.wait(5)
    return dict(status='GUARDIAN_TERMINATED', created_cancel=requested, guardian=expected['pid'])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group(required=True)
    for name in ('--launch', '--status', '--cancel', '--postcheck'):
        mode.add_argument(name, action='store_true')
    parser.add_argument('--profile', type=Path, required=True)
    parser.add_argument('--profile-sha256', required=True)
    parser.add_argument('--runner', type=Path, help='default: run_prepared_restart.py beside this launcher')
    parser.add_argument('--stop-before-advance', action='store_true', help='staged smoke; only with --launch')
    parser.add_argument('--dev-timing', action='store_true', help='opt-in development diagnostics; only with --launch')
    parser.add_argument('--terminate-unresponsive-guardian', action='store_true', help='only with --cancel')
    RG.add_arguments(parser)
    args = parser.parse_args(argv)
    if ((args.stop_before_advance or args.dev_timing) and not args.launch
            or args.terminate_unresponsive_guardian and not args.cancel):
        parser.error('--stop-before-advance and --dev-timing need --launch; '
                     '--terminate-unresponsive-guardian needs --cancel')
    if not args.launch and (args.peak_records or args.booking_bytes is not None or args.booking_basis is not None):
        parser.error('measurement/booking arguments belong to --launch')
    emit = lambda line: print(line, flush=True)
    try:
        if args.launch:
            return launch(args.profile, args.profile_sha256, runner=args.runner,
                          stop_before_advance=args.stop_before_advance, dev_timing=args.dev_timing,
                          peak_records=args.peak_records, booking_bytes=args.booking_bytes,
                          booking_basis=args.booking_basis, emit=emit)
        if args.status:
            emit(json.dumps(status(args.profile, args.profile_sha256, runner=args.runner), sort_keys=True))
            return 0
        if args.cancel:
            result = cancel(args.profile, args.profile_sha256, runner=args.runner,
                            terminate_unresponsive_guardian=args.terminate_unresponsive_guardian)
            emit(json.dumps(result, sort_keys=True))
            return 0 if result['status'] in ('CANCELLED', 'ALREADY_TERMINAL', 'GUARDIAN_TERMINATED') else 3
        result = postcheck(args.profile, args.profile_sha256, runner=args.runner)
        emit(json.dumps(dict(status=result['status'], failures=result['failures'], warnings=result['warnings'])))
        return 0 if result['status'] == 'PASS' else 1
    except (ValueError, OSError) as error:
        emit(json.dumps(dict(status='REFUSED', type=type(error).__name__, reason=str(error))))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
