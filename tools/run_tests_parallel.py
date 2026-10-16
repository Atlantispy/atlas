#!/usr/bin/env python3
"""Run a tree's unittest suites in parallel worker processes, with per-test outcomes and durations.

WORKING NON-CANON development tool (docs/DEVELOPMENT_TOOLS.md). Standard library only in the driver; the workers use
the interpreter given by ``--python`` (the tested environment), so no private path is recorded here.

* Without ``--pattern`` the selection is the tree's full verify.py discovery (its ``FULL_PATTERNS``, read without
  importing it; ``test_*.py`` and ``check_native_transport.py`` for a tree that does not name them), so a default
  run is never narrower than verify.py's full run.
* Units are test classes, or whole modules where ``setUpModule``/``tearDownModule``/``load_tests`` exist, so module
  fixtures keep their meaning. Units run in a pool of long-lived worker processes (``--fresh`` starts a new process
  for every unit, as the impact recorder needs). A unit is never split across processes.
* Every worker runs with single-threaded BLAS/OpenMP, its own temporary directory, and
  ``PYTHONPYCACHEPREFIX`` pointing at a bytecode cache outside the tree (never ``.pyc`` files beside sources).
  The temporary directories and the default cache are short siblings in the inherited temporary folder
  (``--tmp-root``): several tests budget Windows path lengths from the temporary folder, and a deep cache path can
  exceed the path limit, after which Python silently recompiles every module in every worker.
* Units named in the serial group (``--serial-unit`` and ``SERIAL_UNITS``) run after the parallel phase, one at a
  time, for anything that proves timing- or memory-sensitive under load.
* ``--quick`` omits the tree's registered slow tests (``SLOW_TESTS`` in tectonics/verify.py, or ``--slow-file``),
  refusing a stale registry entry exactly as verify.py does. A quick run is a developer selection, never a gate.
* ``--serial`` runs the whole selection the conventional way, in one process in discovery order: the reference
  against which parallel outcomes are compared (``compare``).
* Results stream to ``<run-dir>/results.jsonl`` as units finish (crash-safe); the summary JSON is written atomically.
  A worker that dies or exceeds ``--unit-timeout`` is reported as such and replaced; other units continue.

Nothing here relaxes a test: outcomes are recorded as unittest reports them, skips included.
"""
from __future__ import annotations

import argparse
import ast
import fnmatch
import hashlib
import json
import os
from pathlib import Path
import queue
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import time

SCHEMA = 'atlas.dev.parallel-test-run.v2'
# Units measured to depend on what ran before them in a shared worker. They run after the parallel phase, one at a time,
# each in its own fresh process. MultigridPlanTests.test_default_budget_admits_a_nine_cube_... expects the multigrid
# factor reservation and failed in 2 of 7 shared-worker full runs at 30a79e6 (passing in the others, in every
# fresh-per-unit run, and alone on the same trees): its outcome depends on earlier units in the same process.
SERIAL_UNITS = ('test_regional_multigrid3d.MultigridPlanTests',)
THREAD_VARIABLES = ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS',
                    'VECLIB_MAXIMUM_THREADS', 'BLIS_NUM_THREADS')
OUTCOMES = ('success', 'failure', 'error', 'skipped', 'expected_failure', 'unexpected_success')
_CO_OPTIMIZED = 0x0001     # inspect.CO_OPTIMIZED: set for function code, clear for module and class bodies
# Distribution-metadata and module discovery (entry points, pkgutil): they list sys.path folders for names only.
_METADATA_FILES = tuple(os.path.normcase(os.path.join(*parts)) for parts in (
    ('importlib', 'metadata', '__init__.py'), ('importlib', 'metadata', '_adapters.py'), ('pkgutil.py',),
    ('importlib', '_bootstrap_external.py')))


# ---------------------------------------------------------------------------------------------------------------
# The tree's full discovery and slow-test registry (shared with verify.py's convention).

# verify.py's full discovery before it named FULL_PATTERNS (its default run also discovers check_native_transport.py).
DEFAULT_FULL_PATTERNS = ('test_*.py', 'check_native_transport.py')


def full_patterns(root):
    """The tree's full verify.py discovery: its FULL_PATTERNS literal, read without importing the tree, or
    DEFAULT_FULL_PATTERNS for a tree that does not name it. The runner's default selection, so that a default run is
    never narrower than verify.py's full run."""
    verify = Path(root)/'tectonics'/'verify.py'
    if verify.is_file():
        for node in ast.parse(verify.read_text(encoding='utf-8')).body:
            if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'FULL_PATTERNS'
                                                    for t in node.targets):
                return tuple(str(p) for p in ast.literal_eval(node.value))
    return DEFAULT_FULL_PATTERNS


def load_slow_registry(root, slow_file=None):
    """{test or class ID: measured seconds} from ``slow_file`` (JSON object) or the tree's verify.py SLOW_TESTS
    literal; {} when neither exists. Read without importing the tree."""
    if slow_file is not None:
        data = json.loads(Path(slow_file).read_text(encoding='utf-8'))
        if not isinstance(data, dict):
            raise ValueError('the slow-test file must be a JSON object of ID -> seconds')
        return {str(k): float(v) for k, v in data.items()}
    verify = Path(root)/'tectonics'/'verify.py'
    if not verify.is_file():
        return {}
    for node in ast.parse(verify.read_text(encoding='utf-8')).body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'SLOW_TESTS' for t in node.targets):
            value = node.value
            if isinstance(value, ast.Call) and value.args:          # MappingProxyType({...})
                value = value.args[0]
            return {str(k): float(v) for k, v in ast.literal_eval(value).items()}
    return {}


def quick_filter(test_ids, registry, patterns):
    """(kept IDs, omitted IDs). A registry entry is a test ID or a class ID (``module.Class``); an entry whose
    module matches a selected pattern but is not discovered refuses (a stale registry never silently broadens)."""
    ids = set(test_ids)
    classes = {i.rsplit('.', 1)[0] for i in ids}
    omitted = set()
    for entry in registry:
        module = entry.split('.', 1)[0]
        if not any(fnmatch.fnmatch(module+'.py', p) for p in patterns):
            continue
        if entry in ids:
            omitted.add(entry)
        elif entry in classes:
            omitted |= {i for i in ids if i.rsplit('.', 1)[0] == entry}
        else:
            raise ValueError('slow-test registry entry is stale (not discovered): '+entry)
    return [i for i in test_ids if i not in omitted], sorted(omitted)


# ---------------------------------------------------------------------------------------------------------------
# Worker side (runs in the tested interpreter).

def _leaves(suite):
    import unittest
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from _leaves(item)
        else:
            yield item


class _Recorder:
    """A unittest result that keeps per-test outcomes and durations (setUpClass errors included)."""

    def __new__(cls, stream):
        import unittest

        class Result(unittest.TextTestResult):
            def __init__(self):
                super().__init__(stream, True, 1)
                self.records, self._started, self._sub_failed = {}, {}, {}

            def startTest(self, test):
                self._started[test.id()] = time.perf_counter()
                super().startTest(test)

            def _put(self, test, outcome, detail=None):
                start = self._started.pop(test.id(), None)
                self.records[test.id()] = dict(outcome=outcome, seconds=None if start is None else
                                               time.perf_counter()-start, detail=detail)

            def addSuccess(self, test):
                super().addSuccess(test)
                self._put(test, 'success')

            def addFailure(self, test, err):
                super().addFailure(test, err)
                self._put(test, 'failure', self.failures[-1][1])

            def addError(self, test, err):
                super().addError(test, err)
                self._put(test, 'error', self.errors[-1][1])

            def addSkip(self, test, reason):
                super().addSkip(test, reason)
                parent = getattr(test, 'test_case', None)          # a skipped subtest
                if parent is not None:
                    self.records[test.id()] = dict(outcome='skipped', seconds=None, detail=reason)
                    self._sub_failed.setdefault(parent.id(), 'skipped')
                else:
                    self._put(test, 'skipped', reason)

            def addExpectedFailure(self, test, err):
                super().addExpectedFailure(test, err)
                self._put(test, 'expected_failure')

            def addUnexpectedSuccess(self, test):
                super().addUnexpectedSuccess(test)
                self._put(test, 'unexpected_success')

            def addSubTest(self, test, subtest, err):
                super().addSubTest(test, subtest, err)
                if err is not None:
                    kind = 'failure' if issubclass(err[0], test.failureException) else 'error'
                    self.records[subtest.id()] = dict(outcome=kind, seconds=None, detail=self._exc_info_to_string(
                        err, test))
                    if self._sub_failed.get(test.id()) != 'error':
                        self._sub_failed[test.id()] = kind

            def stopTest(self, test):
                # unittest reports no outcome of its own for a test whose subtests failed or were skipped: record
                # the worst (error, then failure, then skipped) rather than leaving the test unrecorded.
                if test.id() not in self.records and test.id() in self._sub_failed:
                    self._put(test, self._sub_failed[test.id()], 'subtest outcomes are listed separately')
                super().stopTest(test)
        return Result()


def _load_unit(unit, test_ids):
    import unittest
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromName(unit)
    tests = list(_leaves(suite))
    if test_ids is not None:
        keep = set(test_ids)
        tests = [t for t in tests if t.id() in keep]
    if loader.errors:
        raise ImportError('\n'.join(loader.errors))
    return unittest.TestSuite(tests)


class _Tracer:
    """Record what a fresh process executes and opens (test_impact's recorder): code objects started (functions and
    module bodies, by file and qualified name), files opened (and which of those the execution-identity guard read),
    directories listed, processes spawned and compiled numba dispatchers. Started before the unit is loaded."""

    def __init__(self):
        self.executed, self.modules, self.opened, self.scanned = set(), set(), set(), set()
        self.functions, self.identity_reads, self.import_reads, self.copied = set(), set(), set(), set()
        self.spawned = []
        monitoring = sys.monitoring
        self.tool = 4
        monitoring.use_tool_id(self.tool, 'atlas-test-impact')
        monitoring.register_callback(self.tool, monitoring.events.PY_START, self._start)
        monitoring.set_events(self.tool, monitoring.events.PY_START)
        sys.addaudithook(self._audit)

    def _start(self, code, offset):
        # Every code object that starts is reported once per process (DISABLE), which is all a dependency set needs.
        # Module and class bodies (no CO_OPTIMIZED flag) run at import: they belong to the module skeleton. Functions,
        # methods, lambdas, generator expressions and nested code are execution.
        if code.co_name == '<module>' or not code.co_flags & _CO_OPTIMIZED:
            self.modules.add(os.path.abspath(code.co_filename) if not code.co_filename.startswith('<')
                             else code.co_filename)
        else:
            filename = os.path.abspath(code.co_filename) if not code.co_filename.startswith('<') else code.co_filename
            self.executed.add(filename)
            self.functions.add(filename+'::'+code.co_qualname)
        return sys.monitoring.DISABLE

    @staticmethod
    def _path(value):
        """An absolute path for a path-like audit argument, resolved now (a test may change directory later)."""
        if isinstance(value, (str, bytes, os.PathLike)):
            try:
                return os.path.abspath(os.fsdecode(value))
            except (TypeError, ValueError):
                return None
        return None

    @staticmethod
    def _caller(listing=False):
        """'identity' for the execution-identity guard's source reads; 'import' for the import system's own work
        (compiling a module it imports; for a listing, searching sys.path folders for a module or distribution
        metadata); else None. Those listings read names only, and a changed name is an added or deleted file, which
        selects everything anyway. Byte reads by metadata code still count."""
        frame, depth = sys._getframe(2), 0
        while frame is not None and depth < 10:
            code = frame.f_code
            if code.co_name == '_source_bytes':
                return 'identity'
            if code.co_filename.startswith('<frozen importlib') and code.co_name in ('get_code', '_fill_cache'):
                return 'import'
            if listing and os.path.normcase(code.co_filename).endswith(_METADATA_FILES):
                return 'import'
            frame, depth = frame.f_back, depth+1
        return None

    def _audit(self, event, args):
        if event == 'open':
            path = self._path(args[0]) if args else None
            if path is None:
                return
            # The import system compiling a module it imports is that import (recorded as a module body), not a read
            # of the file's bytes as data. Every other open, including the identity guard's, linecache's and any
            # hashing, is a dependency on the bytes.
            caller = self._caller()
            if caller == 'import':
                self.import_reads.add(path)
                return
            self.opened.add(path)
            if caller == 'identity':
                self.identity_reads.add(path)
        elif event in ('sqlite3.connect', 'ctypes.dlopen', 'shutil.copyfile', 'shutil.copytree', 'shutil.move',
                       '_winapi.CopyFile2'):
            # Files read by C code without an 'open' event: databases, native libraries and copy sources (a copied
            # folder counts as every tracked file inside it).
            path = self._path(args[0]) if args else None
            if path is not None:
                (self.copied if event.startswith(('shutil.', '_winapi.')) else self.opened).add(path)
        elif event in ('os.listdir', 'os.scandir', 'glob.glob', 'glob.glob/2', 'os.walk', 'pathlib.Path.glob',
                       'pathlib.Path.rglob'):
            if self._caller(listing=True) == 'import':
                return                                   # the import system searching sys.path for a module
            path = self._path(args[0]) if args and args[0] is not None else os.getcwd()
            if path is not None:
                self.scanned.add(path)
        elif event in ('subprocess.Popen', 'os.system', 'os.posix_spawn', 'os.spawn', 'os.exec', 'os.startfile',
                       '_winapi.CreateProcess', 'os.fork', 'os.forkpty', 'os.posix_spawnp'):
            self.spawned.append(event)

    def numba_compiled(self):
        """Files of every numba dispatcher that compiled at least one signature, wherever it is held."""
        dispatcher = sys.modules.get('numba.core.dispatcher')
        if dispatcher is None:
            return []
        import gc
        out = set()
        for value in gc.get_objects():
            if isinstance(value, dispatcher.Dispatcher) and value.overloads:
                out.add(value.py_func.__code__.co_filename)
        return sorted(out)

    def record(self):
        sys.monitoring.set_events(self.tool, 0)
        return dict(executed=sorted(self.executed), modules=sorted(self.modules), opened=sorted(self.opened),
                    functions=sorted(self.functions), identity_reads=sorted(self.identity_reads),
                    import_reads=sorted(self.import_reads), copied=sorted(self.copied),
                    scanned=sorted(self.scanned), spawned=sorted(set(self.spawned)),
                    numba_compiled=self.numba_compiled())


def _run_one(unit, test_ids, log_path):
    import unittest
    started = time.perf_counter()
    with open(log_path, 'w', encoding='utf-8', errors='replace') as log:
        saved = os.dup(1), os.dup(2)
        out_stream, err_stream = sys.stdout, sys.stderr
        try:
            os.dup2(log.fileno(), 1)
            os.dup2(log.fileno(), 2)
            sys.stdout = sys.stderr = log
            result = _Recorder(log)
            try:
                suite = _load_unit(unit, test_ids)
                suite.run(result)
            except BaseException as exc:                                  # import or loader failure
                result.records[unit] = dict(outcome='error', seconds=None, detail=repr(exc))
            log.flush()
        finally:
            sys.stdout, sys.stderr = out_stream, err_stream
            os.dup2(saved[0], 1)
            os.dup2(saved[1], 2)
            os.close(saved[0])
            os.close(saved[1])
    # unittest reports setUpClass/setUpModule errors through an _ErrorHolder whose id names the fixture.
    return dict(unit=unit, wall_seconds=time.perf_counter()-started, tests=result.records)


def _worker_main(args):
    from multiprocessing.connection import Client
    os.chdir(args.cwd)
    sys.path.insert(0, args.tests_dir)
    tracer = _Tracer() if args.trace_dir else None
    connection = Client(args.address, authkey=bytes.fromhex(os.environ.pop('ATLAS_DEV_RUNNER_KEY')))
    connection.send(dict(hello=os.environ.pop('ATLAS_DEV_WORKER_TOKEN'), pid=os.getpid()))
    while True:
        message = connection.recv()
        if message is None:
            break
        if message.get('suite'):                                          # the conventional serial reference
            outcome = _run_suite(message['patterns'], message['tests'], message['log'])
        else:
            outcome = _run_one(message['unit'], message['tests'], message['log'])
        if tracer is not None:
            Path(args.trace_dir, message['unit']+'.json').write_text(json.dumps(dict(
                unit=message['unit'], **tracer.record())), encoding='utf-8')
        connection.send(outcome)
        if args.fresh:
            break
    connection.close()


def _run_suite(patterns, test_ids, log_path):
    """All selected tests in one process, in discovery order (the conventional run)."""
    import unittest
    started = time.perf_counter()
    loader = unittest.TestLoader()
    tests = []
    for pattern in patterns:
        tests += list(_leaves(loader.discover(sys.path[0], pattern=pattern, top_level_dir=sys.path[0])))
    keep = set(test_ids)
    suite = unittest.TestSuite([t for t in tests if t.id() in keep or t.id().split('.')[0] in keep])
    with open(log_path, 'w', encoding='utf-8', errors='replace') as log:
        saved = os.dup(1), os.dup(2)
        out_stream, err_stream = sys.stdout, sys.stderr
        try:
            os.dup2(log.fileno(), 1)
            os.dup2(log.fileno(), 2)
            sys.stdout = sys.stderr = log
            result = _Recorder(log)
            suite.run(result)
            log.flush()
        finally:
            sys.stdout, sys.stderr = out_stream, err_stream
            os.dup2(saved[0], 1)
            os.dup2(saved[1], 2)
            os.close(saved[0])
            os.close(saved[1])
    return dict(unit='<serial suite>', wall_seconds=time.perf_counter()-started, tests=result.records)


def _discover_main(args):
    """Print the units of the selection as JSON: per module, its classes and test IDs, and whether module-level
    fixtures make the module one unit."""
    import unittest
    os.chdir(args.cwd)
    sys.path.insert(0, args.tests_dir)
    loader = unittest.TestLoader()
    out, errors = [], []
    for pattern in args.pattern:
        suite = loader.discover(args.tests_dir, pattern=pattern, top_level_dir=args.tests_dir)
        for test in _leaves(suite):
            out.append(test.id())
    errors = list(loader.errors)
    modules = {}
    for test_id in out:
        module = test_id.split('.', 1)[0]
        modules.setdefault(module, []).append(test_id)
    fixtures = {}
    for module in modules:
        mod = sys.modules.get(module)
        fixtures[module] = bool(mod is not None and any(hasattr(mod, n) for n in (
            'setUpModule', 'tearDownModule', 'load_tests')))
    print(json.dumps(dict(tests=out, module_fixtures=fixtures, errors=errors)))


# ---------------------------------------------------------------------------------------------------------------
# Driver side.

def source_snapshot(root):
    """Bind actual tracked bytes and the clean commit; never infer executed bytes from Git alone."""
    def git(*args):
        proc = subprocess.run(['git', '-c', 'core.autocrlf=false', '-C', str(root), *args],
                              capture_output=True, check=True)
        return proc.stdout
    if Path(git('rev-parse', '--show-toplevel').decode().strip()).resolve() != Path(root).resolve():
        raise ValueError('recording root must be the repository root')
    if git('status', '--porcelain', '--untracked-files=all').strip():
        raise ValueError('recording source must be a clean commit; keep outputs ignored or outside the tree')
    commit = git('rev-parse', 'HEAD').decode().strip()
    blobs, hashes = {}, {}
    for row in git('ls-tree', '-rz', 'HEAD').split(b'\0'):
        if not row:
            continue
        meta, name = row.split(b'\t', 1)
        mode, kind, blob = meta.decode().split()
        path = name.decode('utf-8')
        full = Path(root)/path
        if kind != 'blob' or mode not in ('100644', '100755') or any(p.is_symlink() for p in (full, *full.parents)):
            raise ValueError('recording input is not a regular source file: ' + path)
        blobs[path] = blob
        hashes[path] = hashlib.sha256(full.read_bytes()).hexdigest()
    return dict(commit=commit, files=blobs, sha256=hashes)


def _worker_env(src):
    env = dict(os.environ)
    for name in THREAD_VARIABLES:
        env[name] = '1'
    inherited = env.get('PYTHONPATH')
    paths = [str(Path(src).resolve())]
    if inherited:
        # Python resolves these at process start, before the worker changes directory.
        paths += [os.path.abspath(p or os.curdir) for p in inherited.split(os.pathsep)]
    env['PYTHONPATH'] = os.pathsep.join(paths)
    env['PYTHONIOENCODING'] = 'utf-8'
    return env


_FINGERPRINT = r'''
import hashlib, json, os, sys
from importlib import metadata
root, tests, runner = sys.argv[1:]
def normal(path):
    path = os.path.normcase(os.path.realpath(path))
    if path == root or path.startswith(root + os.sep):
        return '<root>' + path[len(root):].replace(os.sep, '/')
    return path
own = {'PYTHONPATH', 'PYTHONPYCACHEPREFIX', 'PYTHONIOENCODING', 'PYTHONDONTWRITEBYTECODE'}
env = {k: v for k, v in os.environ.items() if k.startswith(('ATLAS_', 'NUMBA_', 'PYTHON')) and k not in own
       and not k.startswith('ATLAS_DEV_')}
names = sorted('%s==%s' % (d.metadata['Name'], d.version) for d in metadata.distributions())
print(json.dumps(dict(executable=os.path.normcase(os.path.realpath(sys.executable)), version=sys.version,
    executable_sha256=hashlib.sha256(open(sys.executable, 'rb').read()).hexdigest(),
    distributions=hashlib.sha256('\n'.join(names).encode()).hexdigest(), environment=env,
    worker_import_paths=[normal(p) for p in [tests, runner, *sys.path[1:]]])))
'''


def runtime_fingerprint(python, root, src=None, tests_dir=None):
    """Observe the tested interpreter with the same inherited import environment as the workers."""
    root = Path(root).resolve()
    env = _worker_env(src or root/'tectonics'/'src')
    env.pop('PYTHONPYCACHEPREFIX', None)
    env.pop('PYTHONDONTWRITEBYTECODE', None)
    proc = subprocess.run([python, '-B', '-c', _FINGERPRINT, os.path.normcase(str(root)),
                           str(tests_dir or root/'tectonics'/'tests'), str(Path(__file__).resolve().parent)],
                          env=env, capture_output=True, text=True, check=True)
    return json.loads(proc.stdout)


def run_provenance(args, root):
    return dict(source=source_snapshot(root),
                fingerprint=runtime_fingerprint(args.python, root, args.src, args.tests_dir),
                cwd=str(args.cwd), src=str(args.src), tests_dir=str(args.tests_dir))


def _child_env(args, worker_tmp):
    env = _worker_env(args.src)
    env['PYTHONPYCACHEPREFIX'] = str(args.pycache)
    env.pop('PYTHONDONTWRITEBYTECODE', None)
    for name in ('TMP', 'TEMP', 'TMPDIR'):
        env[name] = str(worker_tmp)
    env['PYTHONIOENCODING'] = 'utf-8'
    return env


def discover(args):
    proc = subprocess.run([args.python, str(Path(__file__).resolve()), '--discover', '--cwd', str(args.cwd),
                           '--tests-dir', str(args.tests_dir), *sum((['--pattern', p] for p in args.pattern), [])],
                          capture_output=True, text=True, env=_child_env(args, Path(tempfile.gettempdir())))
    if proc.returncode:
        raise RuntimeError('discovery failed:\n'+proc.stderr[-4000:])
    data = json.loads(proc.stdout.strip().splitlines()[-1])
    if data['errors']:
        raise RuntimeError('discovery import errors:\n'+'\n'.join(data['errors'])[-4000:])
    return data


def units_of(tests, module_fixtures):
    """{unit: [test IDs]}: one unit per class, or per module with module-level fixtures."""
    units = {}
    for test_id in tests:
        module = test_id.split('.', 1)[0]
        unit = module if module_fixtures.get(module) else test_id.rsplit('.', 1)[0]
        units.setdefault(unit, []).append(test_id)
    return units


class Driver:
    def __init__(self, args):
        self.args = args
        self.lock = threading.Lock()
        self.spawn_lock = threading.Lock()
        self.results = {}
        self.jsonl = open(Path(args.run_dir)/'results.jsonl', 'a', encoding='utf-8')
        self.key = secrets.token_bytes(16)
        from multiprocessing.connection import Listener
        self.listener = Listener(authkey=self.key)
        self.counter = 0
        self.worker_tmps = []

    def _spawn(self):
        with self.spawn_lock:                       # one pending connection at a time: accept() gets this worker
            return self._spawn_locked()

    def _spawn_locked(self):
        with self.lock:
            self.counter += 1
            number = self.counter
        # Short, beside the inherited temporary folder: several tests budget Windows path lengths from it.
        worker_tmp = Path(tempfile.mkdtemp(prefix='atw%d-' % number, dir=self.args.tmp_root))
        with self.lock:
            self.worker_tmps.append(worker_tmp)
        env = _child_env(self.args, worker_tmp)
        env['ATLAS_DEV_RUNNER_KEY'] = self.key.hex()
        token = secrets.token_hex(8)
        env['ATLAS_DEV_WORKER_TOKEN'] = token
        command = [self.args.python, str(Path(__file__).resolve()), '--worker', '--address', self.listener.address,
                   '--cwd', str(self.args.cwd), '--tests-dir', str(self.args.tests_dir)]
        if self.args.fresh:
            command.append('--fresh')
        if self.args.trace_dir:
            command += ['--trace-dir', str(self.args.trace_dir)]
        log = open(Path(self.args.run_dir)/'workers'/('w%04d.log' % number), 'w', encoding='utf-8')
        proc = subprocess.Popen(command, env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)
        connection = self.listener.accept()
        hello = connection.recv()
        if hello.get('hello') != token:
            raise RuntimeError('a worker connection does not belong to the spawned worker')
        proc.worker_pid = hello['pid']          # the real interpreter (a venv launcher may be its parent)
        return proc, connection, log

    def _record(self, outcome):
        with self.lock:
            self.results[outcome['unit']] = outcome
            self.jsonl.write(json.dumps(outcome)+'\n')
            self.jsonl.flush()

    def _serve(self, work, fresh=None):
        """Run queued units in one worker at a time; ``fresh`` gives every unit its own new process."""
        fresh = self.args.fresh if fresh is None else fresh
        proc = connection = log = None
        while True:
            try:
                item = work.get_nowait()
            except queue.Empty:
                break
            unit, tests = item
            if isinstance(unit, tuple):                  # the serial reference: one whole-suite message
                message = unit[1]
                unit = message['unit']
            else:
                message = dict(unit=unit, tests=tests, log=str(Path(self.args.run_dir)/'logs'/(unit+'.log')))
            if proc is None:
                proc, connection, log = self._spawn()
            try:
                connection.send(message)
                if self.args.unit_timeout and not connection.poll(self.args.unit_timeout):
                    raise TimeoutError
                outcome = connection.recv()
            except TimeoutError:
                _kill(proc)
                outcome = dict(unit=unit, wall_seconds=self.args.unit_timeout, tests={
                    t: dict(outcome='error', seconds=None, detail='unit timeout') for t in tests}, timeout=True)
                proc = None
            except (EOFError, OSError, ConnectionError):
                proc.wait()
                outcome = dict(unit=unit, wall_seconds=None, crashed=proc.returncode, tests={
                    t: dict(outcome='error', seconds=None, detail='worker died (exit %s)' % proc.returncode)
                    for t in tests})
                proc = None
            self._record(outcome)
            if fresh and proc is not None:
                if not self.args.fresh:                  # a reusable worker: ask it to finish
                    try:
                        connection.send(None)
                    except OSError:
                        pass
                proc.wait()
                proc = None
        if proc is not None:
            try:
                connection.send(None)
            except OSError:
                pass
            proc.wait()

    def run(self, parallel_units, serial_units):
        for name in ('logs', 'workers'):
            (Path(self.args.run_dir)/name).mkdir(parents=True, exist_ok=True)
        work = queue.Queue()
        for item in parallel_units:
            work.put(item)
        threads = [threading.Thread(target=self._serve, args=(work,), daemon=True)
                   for _ in range(min(self.args.workers, max(1, work.qsize())))]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        if serial_units:
            work = queue.Queue()
            for item in serial_units:
                work.put(item)
            self._serve(work, fresh=True)              # one at a time, each in its own new process
        self.jsonl.close()
        self.listener.close()
        if not self.args.keep_tmp:
            for folder in self.worker_tmps:              # only the folders this run created
                shutil.rmtree(folder, ignore_errors=True)


def _kill(proc):
    """Stop a worker and its real interpreter (on Windows a venv python.exe is a launcher with a child)."""
    pid = getattr(proc, 'worker_pid', None)
    if pid is not None and pid != proc.pid:
        try:
            if os.name == 'nt':
                subprocess.run(['taskkill', '/F', '/T', '/PID', str(pid)], capture_output=True)
            else:
                os.kill(pid, 9)
        except OSError:
            pass
    proc.kill()
    proc.wait()


def _order(units, durations):
    """Longest known first (then by name), so long units start early; deterministic."""
    return sorted(units.items(), key=lambda kv: (-durations.get(kv[0], 0.), kv[0]))


def run(args):
    started = time.perf_counter()
    root = Path(args.root).resolve()
    args.cwd = Path(args.cwd or root).resolve()
    args.tests_dir = Path(args.tests_dir or root/'tectonics'/'tests').resolve()
    args.src = Path(args.src or root/'tectonics'/'src').resolve()
    args.run_dir = Path(args.run_dir).resolve()
    args.tmp_root = str(Path(args.tmp_root or tempfile.gettempdir()).resolve())
    # A short default cache: on Windows a deep run folder plus a deep source path can exceed the path limit, and then
    # Python silently stops caching and recompiles every module in every worker.
    own_cache = args.pycache is None
    args.pycache = Path(args.pycache or tempfile.mkdtemp(prefix='atpyc-', dir=args.tmp_root)).resolve()
    for inside in (args.tests_dir, args.src):
        if args.pycache == inside or inside in args.pycache.parents:
            raise ValueError('the bytecode cache must lie outside src/tests')
    args.run_dir.mkdir(parents=True, exist_ok=True)
    if args.trace_dir:
        args.trace_dir = str(Path(args.trace_dir).resolve())
        Path(args.trace_dir).mkdir(parents=True, exist_ok=True)
    try:
        return _run(args, root, started)
    finally:
        if own_cache and not args.keep_tmp:
            shutil.rmtree(args.pycache, ignore_errors=True)


def _run(args, root, started):
    provenance = None
    if args.trace_dir:
        try:
            provenance = dict(before=run_provenance(args, root))
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            provenance = dict(error=str(error))
    data = discover(args)
    tests = data['tests']
    omitted = []
    if args.quick:
        tests, omitted = quick_filter(tests, load_slow_registry(root, args.slow_file), args.pattern)
    if args.only:
        keep = set(args.only)
        tests = [t for t in tests if t in keep or t.rsplit('.', 1)[0] in keep or t.split('.', 1)[0] in keep]
    if not tests:
        raise ValueError('empty selection')
    durations = {}
    if args.durations:
        for line in Path(args.durations).read_text(encoding='utf-8').splitlines():
            row = json.loads(line) if line.strip() else None
            if row and row.get('wall_seconds') is not None:
                durations[row['unit']] = row['wall_seconds']
    driver = Driver(args)
    if args.serial:
        message = dict(unit='<serial suite>', suite=True, patterns=args.pattern, tests=tests,
                       log=str(args.run_dir/'logs'/'serial-suite.log'))
        args.workers, args.fresh = 1, False
        driver.run([(('<serial suite>', message), tests)], [])
    else:
        units = units_of(tests, data['module_fixtures'])
        serial = set(SERIAL_UNITS) | set(args.serial_unit or ())
        driver.run([(u, t) for u, t in _order({u: t for u, t in units.items() if u not in serial}, durations)],
                   [(u, t) for u, t in sorted(units.items()) if u in serial])
    per_test = {}
    for outcome in driver.results.values():
        per_test.update(outcome['tests'])
    missing = sorted(set(tests)-set(per_test))
    for test_id in missing:
        per_test[test_id] = dict(outcome='error', seconds=None, detail='no result recorded')
    counts = {name: 0 for name in OUTCOMES}
    for row in per_test.values():
        counts[row['outcome']] = counts.get(row['outcome'], 0)+1
    leaked = sorted(str(p) for folder in (args.src, args.tests_dir) for p in folder.rglob('*.pyc'))
    if provenance is not None and 'before' in provenance:
        try:
            provenance['after'] = run_provenance(args, root)
            provenance['unchanged'] = provenance['before'] == provenance['after']
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            provenance.update(unchanged=False, error=str(error))
    summary = dict(schema=SCHEMA, root=str(root), patterns=args.pattern, quick=bool(args.quick),
                   only=args.only or [], provenance=provenance,
                   omitted_slow=omitted, serial_reference=bool(args.serial), workers=args.workers,
                   fresh_process_per_unit=bool(args.fresh), wall_seconds=time.perf_counter()-started,
                   worker_tmp_root=args.tmp_root, pycache=str(args.pycache),
                   tests_selected=len(tests), counts=counts, passed=(counts['failure'] == counts['error'] ==
                   counts['unexpected_success'] == 0 and not leaked and not missing),
                   local_bytecode=leaked, units={u: dict(wall_seconds=o.get('wall_seconds'),
                   crashed=o.get('crashed'), timeout=o.get('timeout', False)) for u, o in
                   sorted(driver.results.items())},
                   tests={k: per_test[k] for k in sorted(per_test)})
    target = Path(args.summary or args.run_dir/'summary.json')
    temporary = target.with_suffix('.tmp')
    temporary.write_text(json.dumps(summary, indent=1), encoding='utf-8')
    os.replace(temporary, target)
    print(json.dumps(dict(summary=str(target), wall_seconds=round(summary['wall_seconds'], 1),
                          tests_selected=len(tests), counts=counts, passed=summary['passed'],
                          local_bytecode=len(leaked))))
    return 0 if summary['passed'] else 1


def compare(first, second):
    """Per-test outcome differences between two summaries (durations ignored)."""
    a = json.loads(Path(first).read_text(encoding='utf-8'))['tests']
    b = json.loads(Path(second).read_text(encoding='utf-8'))['tests']
    differences = {k: [a.get(k, {}).get('outcome'), b.get(k, {}).get('outcome')]
                   for k in sorted(set(a) | set(b)) if a.get(k, {}).get('outcome') != b.get(k, {}).get('outcome')}
    print(json.dumps(dict(tests=[len(a), len(b)], differences=differences), indent=1))
    return 0 if not differences else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--discover', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--address', help=argparse.SUPPRESS)
    parser.add_argument('--trace-dir', help=argparse.SUPPRESS)
    parser.add_argument('--compare', nargs=2, metavar=('SUMMARY_A', 'SUMMARY_B'),
                        help='compare per-test outcomes of two summaries and exit')
    parser.add_argument('--root', default='.', help='the tree to test (repository root); default: the current folder')
    parser.add_argument('--python', default=sys.executable, help='the tested interpreter for the workers')
    parser.add_argument('--pattern', action='append',
                        help="discovery pattern(s), e.g. 'test_i0[12]_*.py' (default: the tree's verify.py "
                             "FULL_PATTERNS, i.e. its full discovery including check_native_transport.py)")
    parser.add_argument('--only', action='append', help='restrict to these test, class or module IDs')
    parser.add_argument('--workers', type=int, default=max(1, (os.cpu_count() or 2)-2))
    parser.add_argument('--serial', action='store_true', help='the conventional single-process reference run')
    parser.add_argument('--serial-unit', action='append', help='a unit to run in the serial group')
    parser.add_argument('--fresh', action='store_true', help='a new worker process for every unit')
    parser.add_argument('--quick', action='store_true', help="omit the tree's registered slow tests")
    parser.add_argument('--slow-file', help='a JSON {ID: seconds} registry instead of verify.py SLOW_TESTS')
    parser.add_argument('--durations', help='a previous results.jsonl, to start long units first')
    parser.add_argument('--unit-timeout', type=float, default=None, help='seconds per unit (default: none)')
    parser.add_argument('--run-dir', default=None, help='output folder (default: a new temporary folder)')
    parser.add_argument('--summary', default=None, help='summary JSON path (default: RUN_DIR/summary.json)')
    parser.add_argument('--pycache', default=None,
                        help='bytecode cache outside src/tests (default: a new short folder beside the temporary '
                             'folders, removed afterwards)')
    parser.add_argument('--tmp-root', default=None,
                        help='where each worker gets its own short temporary folder (default: the inherited one); '
                             'keep it short, tests budget Windows path lengths from it')
    parser.add_argument('--keep-tmp', action='store_true', help='keep the workers\' temporary folders')
    parser.add_argument('--cwd', default=None, help='worker working directory (default: the root)')
    parser.add_argument('--tests-dir', default=None, help='default: ROOT/tectonics/tests')
    parser.add_argument('--src', default=None, help='default: ROOT/tectonics/src (prepended to PYTHONPATH)')
    args = parser.parse_args(argv)
    if args.worker:
        args.fresh = bool(args.fresh)
        return _worker_main(args)
    if args.discover:
        return _discover_main(args)
    if args.compare:
        return compare(*args.compare)
    args.pattern = args.pattern or list(full_patterns(args.root))          # verify.py's full discovery
    args.run_dir = args.run_dir or tempfile.mkdtemp(prefix='atlas-tests-')
    return run(args)


if __name__ == '__main__':
    raise SystemExit(main())
