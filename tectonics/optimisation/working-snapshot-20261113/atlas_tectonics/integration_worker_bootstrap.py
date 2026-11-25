"""Pinned pressure worker startup using the selected parent's source finder.

Configure once, after source_boundary.bind_imports and before ExecutionContext.
The parent owns selection and the existing dispatch owns process supervision.
No scientific code is imported by this file's ordinary import or configuration.
"""
from contextlib import contextmanager
from hashlib import sha256
import importlib
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path, PureWindowsPath
from threading import local
import stat
import sys
import types


MODULE = "atlas_tectonics.integration_worker_bootstrap"
WORKER = "atlas_tectonics.integration_parallel_worker"
DISPATCH = "atlas_tectonics.integration_parallel_dispatch"
SCHEMA = "atlas.private.pressure-worker-startup.r1"
MAX_STARTUP_BYTES = 1 << 20
PYTHON_ENV = {"PYTHONHASHSEED": "0", "PYTHONDONTWRITEBYTECODE": "1"}
THREAD_ENV = {"OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"}
# Checked source is compiled directly before any selected package is imported.
# Arguments, including paths with spaces, remain individual Popen list elements.
ENTRY = (
    "import hashlib,pathlib,sys,types;"
    "len(sys.argv)==8 and sys.argv[5:7]=="
    "['-m','atlas_tectonics.integration_parallel_worker'] or "
    "sys.exit('worker supervision command marker mismatch');"
    "p=pathlib.Path(sys.argv[1]);r=p.read_bytes();"
    "h=hashlib.sha256(r).hexdigest();"
    "h==sys.argv[2] or sys.exit('worker bootstrap source digest mismatch');"
    "m=types.ModuleType('_plan07_worker_startup');m.__file__=str(p);"
    "exec(compile(r,str(p),'exec'),m.__dict__);"
    "m.run_worker(sys.argv[3],sys.argv[4],sys.argv[7])"
)
_selection = None


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _pin(value):
    return type(value) is str and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def _path(value):
    _require(type(value) is str and value and Path(value).is_absolute(),
             "worker startup requires explicit absolute paths")
    path = Path(value)
    _require("bridge" not in (part.lower() for part in path.parts),
             "worker startup excludes bridge")
    return path.resolve()


def _ordinary(path):
    target = None
    for item in (path, *path.parents):
        info = item.lstat()
        _require(not stat.S_ISLNK(info.st_mode)
                 and not getattr(info, "st_file_attributes", 0) & 0x400,
                 "worker startup refuses linked paths")
        if item == path:
            target = info
    return target


def _raw(path, expected):
    _require(_pin(expected), "worker startup requires a complete source pin")
    _ordinary(path)
    _require(path.is_file(), "worker startup source is not a file")
    raw = path.read_bytes()
    _require(sha256(raw).hexdigest() == expected, "worker startup source digest mismatch: " + str(path))
    return raw


def _pairs(values):
    result = {}
    for key, value in values:
        _require(key not in result, "duplicate worker startup key")
        result[key] = value
    return result


def _json(raw):
    def invalid(value):
        raise ValueError("non-finite worker startup JSON: " + value)
    return json.loads(raw, object_pairs_hook=_pairs, parse_constant=invalid)


def _encode(value):
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    _require(len(raw) <= MAX_STARTUP_BYTES, "worker startup record exceeds its bound")
    return raw


def _runtime():
    return {
        "executable": str(Path(sys.executable).resolve()),
        "version": sys.version,
        "flags": list(sys.flags),
        "xoptions": dict(sys._xoptions),
        "warnoptions": list(sys.warnoptions),
        "prefix": sys.prefix,
        "base_prefix": sys.base_prefix,
    }


def _validate_interpreter():
    _require(sys.flags.dont_write_bytecode and sys.dont_write_bytecode
             and sys.flags.no_user_site and sys.flags.safe_path
             and not sys.flags.hash_randomization
             and not sys.flags.ignore_environment and not sys.flags.isolated,
             "worker startup requires -B -s -P and seed zero")
    present = {key: value for key, value in os.environ.items() if key.upper().startswith("PYTHON")}
    _require(present == PYTHON_ENV, "worker startup Python environment differs from selected allowlist")
    _require(all(os.environ.get(key) == value for key, value in THREAD_ENV.items()),
             "worker startup requires single-threaded BLAS/OpenMP")


def _paths():
    _require(type(sys.path) is list and sys.path, "worker startup requires explicit import paths")
    # A non-existing absolute standard-library zip path is normal on Windows.
    # No empty/cwd/relative entry is admitted and order is retained exactly.
    return [str(_path(item)) for item in sys.path]


def _wire_boundary(boundary):
    _require(type(boundary) is dict, "selected source boundary required")
    modules = boundary.get("modules")
    _require(type(modules) is dict and modules, "selected source map required")
    result = {}
    for name, row in modules.items():
        _require(type(name) is str and name and all(part.isidentifier() for part in name.split(".")),
                 "invalid selected module name")
        _require(type(row) in (tuple, list) and len(row) == 2 and _pin(row[1]),
                 "invalid selected module source row")
        result[name] = [str(_path(str(row[0]))), row[1]]
    for name in (MODULE, WORKER, DISPATCH, "atlas_tectonics"):
        _require(name in result, "selected source map omits " + name)
    package = Path(result["atlas_tectonics"][0]).parent
    _require(Path(result["atlas_tectonics"][0]).name == "__init__.py",
             "selected package root is not an ordinary package")
    for name in (MODULE, WORKER, DISPATCH):
        _require(Path(result[name][0]) == package / (name.rsplit(".", 1)[-1] + ".py"),
                 "selected worker module escaped its package")
    fixtures = boundary.get("fixture_names")
    _require(type(fixtures) in (set, frozenset, list, tuple)
             and all(type(name) is str and name.isidentifier() for name in fixtures),
             "selected fixture exclusion names required")
    return {"modules": result, "fixture_names": sorted(fixtures)}


def _restore_boundary(wire):
    _require(type(wire) is dict and set(wire) == {"modules", "fixture_names"},
             "invalid worker source map")
    restored = {
        "modules": {name: (Path(row[0]), row[1]) for name, row in wire["modules"].items()},
        "fixture_names": set(wire["fixture_names"]),
    }
    _require(_wire_boundary(restored) == wire, "worker source map is not canonical")
    return restored


def configure(boundary_module, boundary, *, boundary_sha256):
    """Bind the already-installed parent finder; never install another one.

    Root must include this canonical package source in its selected source map.
    Call once in each fresh parent, before constructing its ExecutionContext.
    """
    global _selection
    _require(_selection is None, "worker startup is already configured")
    _validate_interpreter()
    wire = _wire_boundary(boundary)
    own = wire["modules"][MODULE]
    _require(_path(str(__file__)) == Path(own[0]), "loaded worker startup helper is not selected")
    _raw(Path(own[0]), own[1])
    loader_path = _path(str(boundary_module.__file__))
    _raw(loader_path, boundary_sha256)
    matches = [finder for finder in sys.meta_path
               if type(finder) is boundary_module._PinnedFinder and finder.boundary is boundary]
    _require(len(matches) == 1 and sys.meta_path[0] is matches[0],
             "selected source finder must already own the first import boundary")
    own_spec = getattr(sys.modules.get(MODULE), "__spec__", None)
    _require(own_spec is not None
             and type(own_spec.loader) is boundary_module._PinnedSourceLoader
             and own_spec.loader.digest == own[1],
             "worker startup helper was not loaded from its pinned source")
    state = {
        "schema": SCHEMA,
        "boundary_path": str(loader_path),
        "boundary_sha256": boundary_sha256,
        "boundary": wire,
        "paths": _paths(),
        "runtime": _runtime(),
    }
    # Freeze the complete configuration bytes once; launches add only their
    # existing owned job path. Mutation of the caller's map cannot repin this.
    _selection = _encode(state)
    return {"schema": SCHEMA, "modules": len(wire["modules"]),
            "boundary_sha256": boundary_sha256, "helper_sha256": own[1]}


def clean_child_env():
    env = {key: value for key, value in os.environ.items() if not key.upper().startswith("PYTHON")}
    env.update(PYTHON_ENV)
    env.update(THREAD_ENV)
    return env


_worker_mode_token = None


def bind_worker_mode(startup_path, startup_sha256):
    """Install only the mode from the already authenticated one-shot startup record."""
    global _worker_mode_token
    _require(_worker_mode_token is None, "worker mode is already bound")
    path = _path(str(startup_path))
    _require(path.stat().st_size <= MAX_STARTUP_BYTES, "worker startup record exceeds its bound")
    state = _json(_raw(path,startup_sha256))
    mode = state.get('execution_mode','strict')
    _require(mode in ('strict','release'), "worker execution mode is invalid")
    _require(path == _path(state['directory'])/'startup.json', "worker mode is outside its owned startup")
    _worker_mode_token = (str(path),startup_sha256,mode,state.get('execution_identity'))


def worker_execution_mode():
    """Strict by default; Release needs the immutable source-bound startup transport."""
    if _worker_mode_token is None:
        return 'strict'
    path,pin,mode,_ = _worker_mode_token
    state = _json(_raw(_path(path),pin))
    _require(state.get('execution_mode','strict') == mode, "worker execution mode changed")
    return mode


def worker_execution_identity():
    """The parent's execution identity from the bound fresh startup record; None with none bound (every parent)."""
    return None if _worker_mode_token is None else _worker_mode_token[3]


def _parent_worker_mode(state):
    from .reuse import execution_mode
    mode = execution_mode()
    _require(mode in ('strict','release'), "parent execution mode is invalid")
    if mode == 'release':
        state['execution_mode'] = mode


def launch(directory, execution_identity):
    """Create a bounded startup record and return command/env; never spawn."""
    if type(_selection) is bytes and _json(_selection).get("schema") == FRESH_STARTUP_SCHEMA:
        return _launch_fresh(directory, execution_identity)
    _require(type(_selection) is bytes, "worker startup has not been configured")
    _validate_interpreter()
    state = _json(_selection)
    _require(state["runtime"] == _runtime() and state["paths"] == _paths(),
             "parent interpreter or import paths changed after worker selection")
    job = _path(str(directory))
    _ordinary(job)
    _require(job.is_dir(), "worker job directory is absent")
    state["directory"] = str(job)
    _parent_worker_mode(state)
    raw = _encode(state)
    startup = job / "startup.json"
    # Existing dispatch directories are one-shot. Never replace an old launch.
    with startup.open("xb") as stream:
        stream.write(raw)
    helper, helper_pin = state["boundary"]["modules"][MODULE]
    # _Child._worker_record recognises exactly this last-three-argument
    # marker, including the owned directory. Under -c these are script
    # arguments; ENTRY and run_worker validate them before the native entry.
    command = [sys.executable, "-B", "-s", "-P", "-c", ENTRY,
               helper, helper_pin, str(startup), sha256(raw).hexdigest(),
               "-m", WORKER, str(job)]
    return command, clean_child_env()


def run_worker(startup_path, startup_sha256, marker_directory):
    """Verified -c entry: restore source boundary before any native import."""
    _validate_interpreter()
    startup = _path(startup_path)
    _require(startup.stat().st_size <= MAX_STARTUP_BYTES, "worker startup record exceeds its bound")
    state = _json(_raw(startup, startup_sha256))
    expected = {"schema", "boundary_path", "boundary_sha256", "boundary", "paths", "runtime", "directory"}
    if type(state) is dict and "execution_mode" in state:
        expected.add("execution_mode")
    _require(type(state) is dict and set(state) == expected and state["schema"] == SCHEMA,
             "worker startup schema differs")
    job = _path(state["directory"])
    _require(startup == job / "startup.json", "worker startup is outside its owned job directory")
    _require(_path(marker_directory) == job, "worker supervision directory differs from startup record")
    _require(state["runtime"] == _runtime(), "worker interpreter differs from selected parent")
    paths = state["paths"]
    _require(type(paths) is list and paths and paths == [str(_path(item)) for item in paths],
             "worker import paths are not explicit and canonical")
    boundary = _restore_boundary(state["boundary"])
    helper, helper_pin = state["boundary"]["modules"][MODULE]
    _require(_path(str(__file__)) == Path(helper), "worker bootstrap loaded a foreign helper")
    _raw(Path(helper), helper_pin)
    source = _path(state["boundary_path"])
    raw = _raw(source, state["boundary_sha256"])
    boundary_module = types.ModuleType("_plan07_worker_source_boundary")
    boundary_module.__file__ = str(source)
    # This module imports only stdlib. Compile checked bytes, never its pyc.
    exec(compile(raw, str(source), "exec"), boundary_module.__dict__)
    sys.path[:] = paths
    boundary_module.bind_imports(boundary)
    canonical = importlib.import_module(MODULE)
    canonical.configure(boundary_module, boundary, boundary_sha256=state["boundary_sha256"])
    canonical.bind_worker_mode(startup,startup_sha256)
    # Use the original entry's actual source, selected by the same finder as
    # the parent. The original worker's runtime/source/receipt checks remain.
    import runpy
    sys.argv = [state["boundary"]["modules"][WORKER][0], str(job)]
    runpy.run_module(WORKER, run_name="__main__", alter_sys=True)


# Appended to the pinned bootstrap helper; its proof configure/run path is unchanged.
FRESH_SELECTION_SCHEMA = "atlas.private.pressure-fresh-selection.r1"
FRESH_STARTUP_SCHEMA = "atlas.private.pressure-fresh-worker.r1"
FRESH_ENTRY = ENTRY.replace("m.run_worker(", "m.run_fresh_worker(")
FRESH_RUNNER_MODULES = ("start_gate", "route2_gate", "run_prepared_restart", "run_fresh_interval")


def _fresh_relative(workspace, value):
    _require(type(value) is str and value and "\\" not in value and ":" not in value
             and not Path(value).is_absolute() and ".." not in Path(value).parts,
             "fresh startup requires a contained relative source")
    path = workspace / value
    _ordinary(path)
    _require(path.resolve().is_relative_to(workspace), "fresh startup source escaped workspace")
    return path.resolve()


def _validate_fresh_selection(selection):
    _require(type(selection) is dict
             and set(selection) == {"schema", "profile", "helper", "runner_modules"}
             and selection["schema"] == FRESH_SELECTION_SCHEMA,
             "fresh startup selection schema differs")
    binding = selection["profile"]
    _require(type(binding) is dict and set(binding) == {"path", "sha256"},
             "fresh startup needs the explicit profile pin")
    profile = _json(_raw(_path(binding["path"]), binding["sha256"]))
    workspace = _path(profile["workspace"])
    manifest_binding = profile["source_manifest"]
    manifest = _json(_raw(_fresh_relative(workspace, manifest_binding["path"]),
                          manifest_binding["sha256"]))
    files = manifest["files"]
    FixtureSources(manifest, workspace)
    modules = selection["runner_modules"]
    _require(type(modules) is dict and set(modules) == set(FRESH_RUNNER_MODULES),
             "fresh startup orchestration closure differs")
    runner = _path(modules["run_fresh_interval"][0])
    for name in FRESH_RUNNER_MODULES:
        row = modules[name]
        _require(type(row) is list and len(row) == 2
                 and _path(row[0]) == runner.parent / (name + ".py"),
                 "fresh startup orchestration is not the selected sibling")
        path = _path(row[0])
        _require(path.is_relative_to(workspace)
                 and files.get(path.relative_to(workspace).as_posix()) == row[1],
                 "fresh startup orchestration is absent from source closure")
        _raw(path, row[1])
    helper = selection["helper"]
    expected = _fresh_relative(workspace, profile["native_root"]) / "atlas_tectonics/integration_worker_bootstrap.py"
    _require(type(helper) is list and len(helper) == 2 and _path(helper[0]) == expected
             and _path(str(__file__)) == expected
             and files.get(expected.relative_to(workspace).as_posix()) == helper[1],
             "fresh startup helper is absent from selected source closure")
    _raw(expected, helper[1])
    return profile, manifest


def _load_fresh_modules(selection, *, include_runner, source_selection, parent_proved=False):
    """Compile checked orchestration bytes; never use an adjacent pyc."""
    names = FRESH_RUNNER_MODULES if include_runner else FRESH_RUNNER_MODULES[:-1]
    runner_path = _path(selection['runner_modules']['run_fresh_interval'][0])
    if runner_path.parent.name == '_private' and runner_path.parent.parent.name == 'atlas_tectonics':
        binding = selection['profile']
        prepare_installed_runner(binding['path'], binding['sha256'], str(runner_path), runner_modules=names,
                                 parent_proved=parent_proved)
        return
    profile, manifest = source_selection
    workspace = _path(profile['workspace'])
    root = _fresh_relative(workspace, profile['native_root'])
    files = manifest['files']
    _require(not any(name in sys.modules for name in names) and _bound_importables(runner_path.parent, workspace, files),
             "fresh startup requires unloaded orchestration")
    verify_installed_modules(root, files, workspace, manifest=manifest)
    _installed_registry()
    loader = _installed_loader(workspace, files)

    class Finder:
        def find_spec(self, fullname, path=None, target=None):
            if installed_source_package(fullname) is not None:
                return _installed_spec(root, fullname, path, target, loader)
            return None

    finder = Finder()
    before = list(sys.path)
    sys.path.insert(0, str(root))
    sys.meta_path.insert(0, finder)
    try:
        with public_import_scope(root, finder):
            for name in ('machine.resources_monitor', 'machine.resources_gate'):
                importlib.import_module('atlas_shared.'+name)
            for name in names:
                path, pin = selection["runner_modules"][name]
                raw = _raw(_path(path), pin)
                module = types.ModuleType(name)
                module.__file__ = path
                module.__package__ = ""
                sys.modules[name] = module
                try:
                    exec(compile(raw, path, "exec", dont_inherit=True), module.__dict__)
                except BaseException:
                    sys.modules.pop(name, None)
                    raise
    finally:
        sys.meta_path.remove(finder)
        sys.path[:] = before


_INSTALLED_PACKAGE = 'atlas_tectonics._private'


def _fresh_runner(runner_path):
    """The loaded Runner, named from its package: installed beside the package's helpers, else bare.

    The qualified name is built from the package, not written as one literal, so these bytes need no
    change when the helpers are folded into the package."""
    installed = runner_path.parent.name == '_private' and runner_path.parent.parent.name == 'atlas_tectonics'
    runner = sys.modules.get((_INSTALLED_PACKAGE + '.' if installed else '') + 'run_fresh_interval')
    # an explicit branch, not _require or assert, so the checker narrows the module and -O keeps the refusal
    if runner is None or _path(str(getattr(runner, '__file__', ''))) != runner_path:
        raise ValueError("fresh worker Runner is not the selected runner module")
    return runner


def prepare_fresh_parent(selection):
    """Direct -B -s -P Runner entry, before its ordinary sibling imports."""
    _validate_interpreter()
    source_selection = _validate_fresh_selection(selection)
    runner = _path(selection["runner_modules"]["run_fresh_interval"][0])
    if runner.parent.name == '_private' and runner.parent.parent.name == 'atlas_tectonics':
        _load_fresh_modules(selection, include_runner=False, source_selection=source_selection)
        return
    _require(not (Path(__file__).absolute().parents[2] / '.desktop-runtime.json').exists(),
             "packaged release requires the installed atlas_tectonics._private fresh startup route")
    paths = _paths()
    runner_root = str(runner.parent)
    if runner_root not in paths:
        paths.insert(0, runner_root)
    sys.path[:] = paths
    _load_fresh_modules(selection, include_runner=False, source_selection=source_selection)


_INSTALLED_REGISTRY = '_atlas_checked_installed_modules'


def installed_source_package(name):
    package = name.partition('.')[0]
    return package if package in ('atlas_tectonics', 'atlas_shared') else None


def installed_source_location(root, name, location):
    package = installed_source_package(name)
    if package is None:
        return False
    member = root.joinpath(*name.split('.'))
    return location == member / '__init__.py' or (
        name != package and location == member.with_suffix('.py'))


def verify_installed_modules(native_root, pins, workspace, *, manifest=None, shared_only=False):
    """Require the same executed objects recorded by the checked loader."""
    root, workspace = Path(native_root).resolve(), Path(workspace).resolve()
    if manifest is not None:
        FixtureSources(manifest, workspace)
    packages = ('atlas_shared',) if shared_only else ('atlas_tectonics', 'atlas_shared')
    loaded = {name: module for name, module in tuple(sys.modules.items())
              if installed_source_package(name) in packages}
    registry = sys.modules.get(_INSTALLED_REGISTRY)
    _require(not loaded or registry is not None, 'unproven preloaded installed package')
    if registry is None:
        return
    for name, module in loaded.items():
        row = registry.records.get(name)
        _require(row is not None and row[0] is module, 'unproven or replaced loaded module: ' + name)
        _, path, pin = row
        filename = getattr(module, '__file__', None)
        _require(type(filename) is str and _path(filename) == path
                 and installed_source_location(root, name, path)
                 and pins.get(path.relative_to(workspace).as_posix()) == pin,
                 'loaded module belongs to another selection: ' + name)
        # Checked execution provenance is distinct from runtime state. Existing
        # overlay/source guards own deliberate function replacement and caches.


def record_installed_module(module, path, pin):
    """Called only after the selected source loader executes checked bytes."""
    path = Path(path).resolve()
    _raw(path, pin)
    _record_checked_installed_module(module, path, pin)


def _record_checked_installed_module(module, path, pin):
    registry = sys.modules.get(_INSTALLED_REGISTRY)
    _require(registry is not None, 'installed checked loader was not bootstrapped')
    registry.records[module.__name__] = (module, path, pin)


def _installed_registry():
    if _INSTALLED_REGISTRY not in sys.modules:
        registry = types.ModuleType(_INSTALLED_REGISTRY)
        registry.records = {}
        registry.public_import = local()
        sys.modules[_INSTALLED_REGISTRY] = registry
    return sys.modules[_INSTALLED_REGISTRY]


@contextmanager
def public_import_scope(root, finder):
    """Keep the authenticated owner's finder active across the first native import."""
    selection = _installed_registry().public_import
    previous = getattr(selection, 'owner', None)
    _require(sys.meta_path[0] is finder and (previous is None or previous[0] == root),
             'conflicting public package source selection')
    selection.owner = root, finder
    try:
        yield
    finally:
        selection.owner = previous


def read_application_source_manifest(root, *, pin_error=ValueError):
    manifest_path = root / 'atlas_tectonics/_application_sources.json'
    pin_path = root / 'atlas_tectonics/_application_sources.sha256'
    manifest_info = _ordinary(manifest_path)
    _ordinary(pin_path)
    with pin_path.open('rb') as stream:
        raw_pin = stream.read(66)
    if (len(raw_pin) != 65 or raw_pin[-1:] != b'\n'
            or any(c not in b'0123456789abcdef' for c in raw_pin[:-1])):
        raise pin_error('invalid installed application source pin')
    pin = raw_pin[:-1].decode('ascii')
    _require(stat.S_ISREG(manifest_info.st_mode), 'worker startup source is not a file')
    bound = 8 * 1024**2
    _require(manifest_info.st_size <= bound, 'application declaration is too large')
    with manifest_path.open('rb') as stream:
        raw = stream.read(bound + 1)
    _require(len(raw) <= bound, 'application declaration is too large')
    _require(sha256(raw).hexdigest() == pin, 'worker startup source digest mismatch: ' + str(manifest_path))
    return pin, json.loads(raw, object_pairs_hook=_pairs)


def bind_shared_exact():
    """Load the exact-arithmetic leaf under the active or adjacent selection."""
    root = Path(__file__).resolve().parent.parent
    registry = sys.modules.get(_INSTALLED_REGISTRY)
    active = getattr(getattr(registry, 'public_import', None), 'owner', None)
    if active is not None:
        _require(active[0] == root and active[1] in sys.meta_path,
                 'conflicting public package source selection')
        importlib.import_module('atlas_shared.exact.exact_arithmetic')
        return

    package = root / 'atlas_tectonics'
    if not (package / '_application_sources.json').exists() and not (package / '_application_sources.sha256').exists():
        _require(not any((package / '_fixtures').rglob('*.py')),
                 'packaged fixtures require an installed application declaration')
        return
    _, manifest = read_application_source_manifest(root)
    _require(type(manifest) is dict and all(type(manifest.get(key)) is dict
             for key in ('files', 'source_hashes', 'data_only')), 'invalid installed application declaration')
    files = manifest['files']
    _require(all(name not in manifest['data_only'] and _pin(files.get(name))
                 and files[name] == manifest['source_hashes'].get(name)
                 for name in ('atlas_shared/__init__.py', 'atlas_shared/exact/__init__.py',
                              'atlas_shared/exact/exact_arithmetic.py')),
             'installed application exact-arithmetic sources are unbound')
    finder = application_shared_finder(root, files)
    sys.meta_path.insert(0, finder)
    try:
        importlib.import_module('atlas_shared.exact.exact_arithmetic')
    finally:
        sys.meta_path.remove(finder)


def _installed_loader(workspace, files):
    class Loader(importlib.machinery.SourceFileLoader):
        def _checked_code(self):
            path = _path(self.path)
            relative = path.relative_to(workspace).as_posix()
            _require(relative in files, 'unbound installed startup import')
            pin = files[relative]
            code = compile(_raw(path, pin), str(path), 'exec', dont_inherit=True)
            return code, path, pin

        def get_code(self, fullname):
            return self._checked_code()[0]

        def exec_module(self, module):
            code, path, pin = self._checked_code()
            exec(code, module.__dict__)
            _record_checked_installed_module(module, path, pin)

    return Loader


def _installed_spec(root, fullname, path, target, loader):
    spec = importlib.machinery.PathFinder.find_spec(fullname, path, target)
    _require(spec is not None and spec.origin and _checked_spec_origin(spec.origin),
             'installed startup package member unavailable')
    location = _path(spec.origin)
    _require(installed_source_location(root, fullname, location), 'installed package shadowing refused')
    spec.loader = loader(fullname, str(location))
    return spec


def application_shared_finder(root, files):
    """Reuse the installed source loader under the application declaration."""
    verify_installed_modules(root, files, root, shared_only=True)
    _installed_registry()
    loader = _installed_loader(root, files)

    class Finder:
        def find_spec(self, fullname, path=None, target=None):
            if installed_source_package(fullname) == 'atlas_shared':
                return _installed_spec(root, fullname, path, target, loader)
            return None

    return Finder()


def prepare_installed_runner(profile_path, profile_sha256, runner_path, *,
                             runner_modules=('start_gate', 'route2_gate'), parent_proved=False):
    """Authenticate a folded script before its qualified orchestration imports.

    The existing profile and complete source/data manifest remain authority.
    Package initialisers and requested sibling modules compile checked source,
    never adjacent bytecode. This adds no admission or scientific permission.
    """
    profile = _json(_raw(_path(str(profile_path)), profile_sha256))
    workspace = _path(profile['workspace'])
    root = _fresh_relative(workspace, profile['native_root'])
    runner = _path(str(runner_path))
    private = root/'atlas_tectonics/_private'
    _require(runner.parent == private and runner.name in ('run_fresh_interval.py','run_prepared_restart.py','reopen_fresh_restart.py','reopen_prepared_restart.py','private_heat_continuation_guard_r3.py'),
             'installed runner is outside the explicitly selected package')
    binding = profile['source_manifest']
    manifest = _json(_raw(_fresh_relative(workspace,binding['path']),binding['sha256']))
    files, data = manifest['files'], manifest['data_only']
    _require(type(files) is dict and files and type(data) is dict and not files.keys() & data.keys(),
             'installed startup requires disjoint complete source/data bindings')
    if not parent_proved:  # W-3 E-1: a fresh worker holds its parent's proof (source_proof); imports stay checked
        for name, pin in {**files, **data}.items():
            _raw(_fresh_relative(workspace,name),pin)
        actual = {p.relative_to(root).as_posix():sha256(p.read_bytes()).hexdigest()
                  for p in sorted((root/'atlas_tectonics').rglob('*.py'))}
        _require(actual and actual == manifest['source_hashes'] and _bound_importables(root, workspace, files), 'installed package source inventory differs')
        for name, pin in actual.items():
            path = root/name
            _require(files.get(path.relative_to(workspace).as_posix()) == pin,
                     'installed native source missing from import closure')
    for path in (root/'atlas_tectonics/__init__.py',private/'__init__.py',runner,Path(__file__).resolve()):
        _require(path.is_relative_to(workspace) and
                 files.get(path.relative_to(workspace).as_posix()) == sha256(path.read_bytes()).hexdigest(),
                 'installed startup package/runner/helper is unbound')
    _require(type(runner_modules) is tuple and all(type(n) is str and n.isidentifier() for n in runner_modules),
             'installed startup needs explicit sibling names')
    package = 'atlas_tectonics._private'
    fixtures = FixtureSources(manifest, workspace)
    verify_installed_modules(root, files, workspace, manifest=manifest)
    _require(not any(package+'.'+n in sys.modules for n in runner_modules),
             'installed startup requires unloaded orchestration')

    loader = _installed_loader(workspace, files)

    class Finder:
        def find_spec(self, fullname, path=None, target=None):
            declared = fixtures.find_spec(fullname, path, target)
            if declared is not None:
                return declared
            if installed_source_package(fullname) is None:
                return _workspace_spec(fullname, path, target, workspace, loader)
            return _installed_spec(root, fullname, path, target, loader)

    before = list(sys.path)
    _installed_registry()
    finder = Finder()
    if str(root) not in sys.path:
        sys.path.insert(0,str(root))
    sys.meta_path.insert(0,finder)
    try:
        with public_import_scope(root, finder):
            importlib.import_module(package)
            importlib.import_module(MODULE)
            for name in runner_modules:
                module = importlib.import_module(package+'.'+name)
                _require(_path(module.__file__) == private/(name+'.py'), 'installed sibling shadowing refused')
    except BaseException:
        sys.path[:] = before
        raise
    finally:
        sys.meta_path.remove(finder)
    return package


def configure_fresh_sources(sources, runner_module):
    """Freeze the actual active FreshSources fence, without replacing it."""
    global _selection
    _require(_selection is None, "worker startup is already configured")
    _validate_interpreter()
    _require(type(sources) is runner_module.FreshSources and sources.selected_now,
             "fresh worker startup requires active typed source selection")
    proof = sources.verify()
    sources.check_imported()
    finder = sys.meta_path[0]
    _require(getattr(finder, "owner", None) is sources
             and type(finder).__module__ == runner_module.RUN.__name__
             and type(finder).__qualname__ == "RestartSources.selected.<locals>.Finder",
             "actual Runner source finder must own the first import boundary")
    selection = runner_module.pressure_startup_selection(sources)
    _validate_fresh_selection(selection)
    module = sys.modules.get(MODULE)
    loader = getattr(getattr(module, "__spec__", None), "loader", None)
    if getattr(runner_module.RUN, '__package__', None) == 'atlas_tectonics._private':
        # The checked installed bootstrap necessarily precedes selected().
        # Its recorded executed object is authoritative, not its filename or
        # the fact that this function is currently executing.
        verify_installed_modules(sources.native_root, _json(sources._manifest)['files'], sources.workspace)
        _require(module is sys.modules.get(__name__) and module is not None
                 and _path(module.__file__) == _path(selection['helper'][0]),
                 'fresh installed worker helper differs from checked selection')
    else:
        _require(module is sys.modules.get(__name__) and loader is not None
                 and type(loader).__module__ == runner_module.RUN.__name__
                 and type(loader).__qualname__ == "RestartSources.selected.<locals>.Loader"
                 and _path(loader.path) == _path(selection["helper"][0]),
                 "fresh worker helper was not imported by the actual pinned Runner loader")
    paths = _paths()
    prefix = [str(_path(str(sources.native_root))),
              *(str(_path(str(path))) for path in sources.import_roots)]
    _require(paths[:len(prefix)] == prefix and paths[len(prefix):],
             "fresh worker selection has changed its final import paths")
    state = {"schema": FRESH_STARTUP_SCHEMA, "selection": selection,
             "paths": paths, "base_paths": paths[len(prefix):], "runtime": _runtime(),
             "source_proof": proof}
    _selection = _encode(state)
    return {"schema": FRESH_STARTUP_SCHEMA, "profile_sha256": sources.profile.sha256,
            "source_manifest_sha256": sources.manifest_pin,
            "helper_sha256": selection["helper"][1]}


def _launch_fresh(directory, execution_identity):
    _validate_interpreter()
    state = _json(_selection)
    _require(state["runtime"] == _runtime() and state["paths"] == _paths(),
             "parent interpreter or import paths changed after worker selection")
    job = _path(str(directory))
    _ordinary(job)
    _require(job.is_dir(), "worker job directory is absent")
    state["directory"] = str(job)
    state["execution_identity"] = execution_identity
    _parent_worker_mode(state)
    raw = _encode(state)
    startup = job / "startup.json"
    with startup.open("xb") as stream:
        stream.write(raw)
    helper, pin = state["selection"]["helper"]
    return ([sys.executable, "-B", "-s", "-P", "-c", FRESH_ENTRY, helper, pin,
             str(startup), sha256(raw).hexdigest(), "-m", WORKER, str(job)],
            clean_child_env())


def run_fresh_worker(startup_path, startup_sha256, marker_directory):
    """Reconstruct the real Runner context, including its finally checks."""
    _validate_interpreter()
    startup = _path(startup_path)
    _require(startup.stat().st_size <= MAX_STARTUP_BYTES,
             "worker startup record exceeds its bound")
    state = _json(_raw(startup, startup_sha256))
    _require(type(state) is dict
             and set(state) - {"execution_mode"} == {"schema", "selection", "paths", "base_paths", "runtime",
                                                    "directory", "source_proof", "execution_identity"}
             and state["schema"] == FRESH_STARTUP_SCHEMA
             and type(state["execution_identity"]) is str and len(state["execution_identity"]) == 64
             and not state["execution_identity"].strip("0123456789abcdef"),
             "fresh worker startup schema differs")
    job = _path(state["directory"])
    _require(startup == job / "startup.json" and _path(marker_directory) == job,
             "worker supervision directory differs from startup record")
    _require(state["runtime"] == _runtime(), "worker interpreter differs from selected parent")
    for key in ("paths", "base_paths"):
        paths = state[key]
        _require(type(paths) is list and paths and paths == [str(_path(item)) for item in paths],
                 "fresh worker paths are not explicit and canonical")
    selection = state["selection"]
    source_selection = _validate_fresh_selection(selection)
    sys.path[:] = state["base_paths"]
    _load_fresh_modules(selection, include_runner=True, source_selection=source_selection, parent_proved=True)
    runner = _fresh_runner(_path(selection['runner_modules']['run_fresh_interval'][0]))
    profile = runner.FreshProfile.read(selection["profile"]["path"], selection["profile"]["sha256"])
    sources = runner.FreshSources(profile)
    sources.adopt_proof(state["source_proof"])  # W-3 E-2: the parent's verify(), under the startup digest
    # Original selected() verifies the complete inventory, loaded imports and
    # historical/data-only exclusions; its finally restores paths and verifies.
    with sources.selected():
        canonical = importlib.import_module(MODULE)
        canonical.bind_worker_mode(startup,startup_sha256)
        canonical.configure_fresh_sources(sources, runner)
        selected = dict(state)
        selected.pop("directory")
        selected.pop("execution_mode",None)
        selected.pop("execution_identity")
        _require(canonical._selection == _encode(selected),
                 "reconstructed Runner selection differs from parent")
        import runpy
        sys.argv = [str(sources.native_root / "atlas_tectonics/integration_parallel_worker.py"), str(job)]
        try:
            runpy.run_module(WORKER, run_name="__main__", alter_sys=True)
        except SystemExit as error:
            if error.code not in (None, 0):
                raise
        # A successful native main normally raises SystemExit(0). Consume only
        # that success so selected() also performs its post-yield import check.


class FixtureSources:
    """Explicit executable fixtures; no ambient lookup or bytecode execution."""
    def __init__(self, manifest, workspace):
        self.workspace = Path(workspace).resolve()
        declaration = manifest.get('fixture_source_map')
        self.modules = {}
        self.files = manifest['files']
        if declaration is None:
            return
        _require(type(declaration) is dict and set(declaration) in ({'schema', 'modules'}, {'schema', 'modules', 'by_path'})
                 and declaration['schema'] == 'atlas.executable-fixtures.r1',
                 'unsupported executable fixture declaration')
        names = declaration['modules']
        self.by_path = declaration.get('by_path', {})
        _require(type(self.by_path) is dict, 'explicit by-path fixture names required')
        _require(type(names) is dict and names, 'explicit fixture names required')
        _require(not names.keys() & self.by_path.keys(), 'fixture alias collides with logical name')
        for name, relative in {**names, **self.by_path}.items():
            _require(type(name) is str and name.isidentifier()
                     and name not in sys.stdlib_module_names, 'invalid fixture name')
            path = _fresh_relative(self.workspace, relative)
            _require(path.suffix == '.py' and (path.stem == name or name in self.by_path)
                     and relative in self.files and relative not in manifest['data_only'],
                     'fixture must be an explicit executable source')
            self.modules[name] = (path, self.files[relative])
        self.verify()

    def verify(self):
        registry = sys.modules.get('_atlas_checked_fixture_modules')
        for name, (path, pin) in self.modules.items():
            module = sys.modules.get(name)
            if module is not None:
                row = None if registry is None else registry.records.get(name)
                _require(row is not None and row == (module, path, pin),
                         'foreign or replaced fixture module: '+name)
                filename = getattr(module, '__file__', None)
                _require(type(filename) is str and _path(filename) == path,
                         'fixture module source metadata changed: '+name)

    def find_spec(self, fullname, path=None, target=None):
        if not self.modules:
            return None
        _require(not fullname.startswith('atlas_tectonics._fixtures'),
                 'fixture assets require declared logical imports')
        if fullname not in self.modules:
            # A source file in the fixture directories is never an implicit import.
            spec = importlib.machinery.PathFinder.find_spec(fullname, path, target)
            if spec and spec.origin:
                location = Path(spec.origin).resolve()
                _require(not any(location.is_relative_to(p.parent) for p, _ in self.modules.values()),
                         'undeclared local fixture import: '+fullname)
            return None
        source, pin = self.modules[fullname]
        owner = self
        class Loader:
            def create_module(self, spec):
                return None
            def exec_module(self, module):
                raw = _raw(source, pin)
                before = list(sys.path)
                registry = sys.modules.get('_atlas_checked_fixture_modules')
                if registry is None:
                    registry = types.ModuleType('_atlas_checked_fixture_modules')
                    registry.records = {}
                    sys.modules[registry.__name__] = registry
                module.__file__ = str(source)
                # This fixture-local importlib view intercepts the explicitly
                # declared legacy by-path call without altering shared stdlib.
                import builtins
                original_import = builtins.__import__
                util_view = types.ModuleType('importlib.util')
                util_view.__dict__.update(importlib.util.__dict__)
                def checked_spec(name, location, *args, **kwargs):
                    _require(name in owner.by_path and not args and not kwargs,
                             'undeclared by-path fixture execution')
                    selected, _ = owner.modules[name]
                    _require(_path(str(location)) == selected, 'foreign by-path fixture source')
                    _require(name not in sys.modules, 'by-path fixture already loaded')
                    return owner.find_spec(name)
                util_view.spec_from_file_location = checked_spec
                import_view = types.ModuleType('importlib')
                import_view.__dict__.update(importlib.__dict__)
                import_view.util = util_view
                def checked_import(name, globals=None, locals=None, fromlist=(), level=0):
                    if name in ('importlib', 'importlib.util') and level == 0:
                        return util_view if name == 'importlib.util' and fromlist else import_view
                    return original_import(name, globals, locals, fromlist, level)
                module.__dict__['__builtins__'] = dict(vars(builtins), __import__=checked_import)
                prior = set(registry.records)
                # Register before exec to support ordinary Python import cycles.
                registry.records[fullname] = (module, source, pin)
                try:
                    exec(compile(raw, str(source), 'exec', dont_inherit=True), module.__dict__)
                    owner.verify()
                except BaseException:
                    for failed in set(registry.records)-prior:
                        executed, _, _ = registry.records.pop(failed)
                        if sys.modules.get(failed) is executed:
                            sys.modules.pop(failed, None)
                    raise
                finally:
                    sys.path[:] = before
        return importlib.util.spec_from_file_location(fullname, source, loader=Loader())


# RULE R6-IMPORTABLES, appended so that no earlier line moves. An importable is a file whose lower-cased
# name ends with a suffix of the pinned tuple below, or any file under a __pycache__ folder. Under the
# workspace, outside its .r44-env interpreter environment, this file enforces the rule in two places:
# - prepare_installed_runner's Finder, only while that function runs (it removes the Finder as it returns):
#   a package member, or another name that resolves under the workspace, must be a checked source spelt
#   as its folder lists it, and it runs only from its bound bytes through the checked Loader; any other
#   importable found there is refused before it runs. Declared fixtures run through FixtureSources' own
#   loader; other names are left to the ordinary finders.
# - _bound_importables, at the installed and fresh start-ups, before checked orchestration runs: it
#   refuses an interpreter whose import suffixes differ from the pinned tuple, and any .pth under the
#   root (suffix case ignored), bound or not, whatever it holds; every importable under the root,
#   imported or not, must be a checked source that the manifest binds by its exact spelling, and a case
#   variant of '__init__.py' is refused, bound or not.
# Imports made before these checks are outside them. They use the default loaders, with the script's
# folder first on sys.path for a script launched without -P: the runners' own top-of-file imports, such
# as start_gate and route2_gate on the helper route. The launch shape and the payload pins exclude what
# runs there, not this rule; an inventory refuses a planted importable by its presence only when it next
# runs. Once the Finder is removed, the runner's own source finder and its inventory and closure checks
# apply. A native library loaded by ctypes is pinned data, not an importable.
# --- R6-IMPORTABLES definition: begin ---
# The one definition is in integration_worker_bootstrap.py; run_prepared_restart.py holds these lines
# verbatim between the same two markers. Only interpreter_suffixes_pinned reads the running interpreter,
# so a checker on another host that imports this file gets the pinned answer from every other name.
# importlib.machinery.all_suffixes() of the pinned CPython 3.12 win_amd64 interpreters, in its order:
IMPORTABLE_SUFFIXES = ('.py', '.pyw', '.pyc', '.cp312-win_amd64.pyd', '.pyd')


def interpreter_suffixes_pinned():
    """The start-up check: this interpreter's importlib.machinery.all_suffixes() equals the pinned
    tuple exactly, order included. An inventory refuses any other interpreter rather than classify."""
    return tuple(importlib.machinery.all_suffixes()) == IMPORTABLE_SUFFIXES


def in_pycache(path):
    """The __pycache__ rule: every file under a folder named __pycache__, in any case, is an importable."""
    return any(part.casefold() == '__pycache__' for part in PureWindowsPath(path).parent.parts)


def importable(path):
    """The lower-case rule, with the __pycache__ rule: a file whose lower-cased name ends with a pinned
    suffix is an importable, whatever the case of its suffix."""
    return PureWindowsPath(path).name.lower().endswith(IMPORTABLE_SUFFIXES) or in_pycache(path)


def checked_source(path):
    """The one importable kind a checked loader may run: an exact '.py' name outside __pycache__."""
    return PureWindowsPath(path).name.endswith('.py') and not in_pycache(path)


def case_variant_init(path):
    """'__INIT__.py', '__Init__.py', '__init__.PY': FileFinder takes any of them for a package's
    '__init__.py' (its _path_isfile has no case check) and writes the canonical name into origin."""
    name = PureWindowsPath(path).name
    return name != '__init__.py' and name.lower() == '__init__.py'


def path_configuration(path):
    """A .pth file, its suffix case ignored. A delivery holds none: an inventory refuses every one, bound
    or not, whatever it holds (even one plain 'lib.zip' line puts that archive on sys.path)."""
    return PureWindowsPath(path).name.lower().endswith('.pth')
# --- R6-IMPORTABLES definition: end ---


def _checked_spec_origin(origin):
    """A spec's file is a checked source spelt as its folder lists it. Windows opens 'foo.PY' or
    '__init__.Py' for the canonical 'foo.py' or '__init__.py' that FileFinder writes into origin."""
    path = Path(origin)
    _require(checked_source(path) and path.name in os.listdir(path.parent),
             'importable that is not a checked .py source refused before execution: ' + str(origin))
    return True


def _workspace_spec(fullname, path, target, workspace, loader):
    """A name outside the package that resolves under the workspace (its .r44-env aside) is a checked
    source and runs through the checked LOADER, as a package member does; other names are left to the
    ordinary finders, as before."""
    spec = importlib.machinery.PathFinder.find_spec(fullname, path, target)
    if spec is None or not spec.origin:
        return None
    location = Path(spec.origin).resolve()
    if not location.is_relative_to(workspace) or location.is_relative_to(workspace / '.r44-env'):
        return None
    _checked_spec_origin(spec.origin)
    spec.loader = loader(fullname, str(location))
    return spec


def _bound_importables(root, workspace, files):
    """Every importable under ROOT, imported or not, is a checked source bound by its exact spelling,
    and none is a case variant of '__init__.py'. Any .pth is refused, bound or not, whatever it holds.
    A link is refused, as _ordinary refuses one: the walk cannot vouch for what lies behind it. First,
    an interpreter whose import suffixes differ from the pinned tuple is refused."""
    _require(interpreter_suffixes_pinned(), 'interpreter import suffixes differ from the pinned R6-IMPORTABLES '
             'tuple: ' + repr(tuple(importlib.machinery.all_suffixes())))
    environment, pending = workspace / '.r44-env', [Path(root)]
    while pending:
        with os.scandir(pending.pop()) as entries:
            for entry in entries:
                path, info = Path(entry.path), entry.stat(follow_symlinks=False)
                relative = path.relative_to(workspace).as_posix()
                _require(not stat.S_ISLNK(info.st_mode) and not getattr(info, 'st_file_attributes', 0) & 0x400,
                         'linked path in a selected root refused: ' + relative)
                if stat.S_ISDIR(info.st_mode):
                    if path != environment:
                        pending.append(path)
                elif path_configuration(path):
                    raise ValueError('a .pth file inside the delivery is refused: ' + relative)
                elif importable(path):
                    _require(checked_source(path) and relative in files,
                             'importable that is not a bound exact .py source refused: ' + relative)
                    _require(not case_variant_init(path), 'case variant of __init__.py refused: ' + relative)
    return True


