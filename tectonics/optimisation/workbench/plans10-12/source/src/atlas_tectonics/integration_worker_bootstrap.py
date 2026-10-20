"""Pinned pressure worker startup using the selected parent's source finder.

Configure once, after source_boundary.bind_imports and before ExecutionContext.
The parent owns selection and the existing dispatch owns process supervision.
No scientific code is imported by this file's ordinary import or configuration.
"""
from hashlib import sha256
import importlib
import json
import os
from pathlib import Path
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
    for item in (path, *path.parents):
        info = item.lstat()
        _require(not stat.S_ISLNK(info.st_mode)
                 and not getattr(info, "st_file_attributes", 0) & 0x400,
                 "worker startup refuses linked paths")


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


def launch(directory):
    """Create a bounded startup record and return command/env; never spawn."""
    if type(_selection) is bytes and _json(_selection).get("schema") == FRESH_STARTUP_SCHEMA:
        return _launch_fresh(directory)
    _require(type(_selection) is bytes, "worker startup has not been configured")
    _validate_interpreter()
    state = _json(_selection)
    _require(state["runtime"] == _runtime() and state["paths"] == _paths(),
             "parent interpreter or import paths changed after worker selection")
    job = _path(str(directory))
    _ordinary(job)
    _require(job.is_dir(), "worker job directory is absent")
    state["directory"] = str(job)
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
    return profile


def _load_fresh_modules(selection, *, include_runner):
    """Compile checked orchestration bytes; never use an adjacent pyc."""
    names = FRESH_RUNNER_MODULES if include_runner else FRESH_RUNNER_MODULES[:-1]
    _require(not any(name in sys.modules for name in names),
             "fresh startup requires unloaded orchestration")
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


def prepare_fresh_parent(selection):
    """Direct -B -s -P Runner entry, before its ordinary sibling imports."""
    _validate_interpreter()
    _validate_fresh_selection(selection)
    paths = _paths()
    runner_root = str(_path(selection["runner_modules"]["run_fresh_interval"][0]).parent)
    if runner_root not in paths:
        paths.insert(0, runner_root)
    sys.path[:] = paths
    _load_fresh_modules(selection, include_runner=False)


def configure_fresh_sources(sources, runner_module):
    """Freeze the actual active FreshSources fence, without replacing it."""
    global _selection
    _require(_selection is None, "worker startup is already configured")
    _validate_interpreter()
    _require(type(sources) is runner_module.FreshSources and sources.selected_now,
             "fresh worker startup requires active typed source selection")
    sources.verify()
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
             "paths": paths, "base_paths": paths[len(prefix):], "runtime": _runtime()}
    _selection = _encode(state)
    return {"schema": FRESH_STARTUP_SCHEMA, "profile_sha256": sources.profile.sha256,
            "source_manifest_sha256": sources.manifest_pin,
            "helper_sha256": selection["helper"][1]}


def _launch_fresh(directory):
    _validate_interpreter()
    state = _json(_selection)
    _require(state["runtime"] == _runtime() and state["paths"] == _paths(),
             "parent interpreter or import paths changed after worker selection")
    job = _path(str(directory))
    _ordinary(job)
    _require(job.is_dir(), "worker job directory is absent")
    state["directory"] = str(job)
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
             and set(state) == {"schema", "selection", "paths", "base_paths", "runtime", "directory"}
             and state["schema"] == FRESH_STARTUP_SCHEMA,
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
    _validate_fresh_selection(selection)
    sys.path[:] = state["base_paths"]
    _load_fresh_modules(selection, include_runner=True)
    runner = sys.modules["run_fresh_interval"]
    profile = runner.FreshProfile.read(selection["profile"]["path"], selection["profile"]["sha256"])
    sources = runner.FreshSources(profile)
    # Original selected() verifies the complete inventory, loaded imports and
    # historical/data-only exclusions; its finally restores paths and verifies.
    with sources.selected():
        canonical = importlib.import_module(MODULE)
        canonical.configure_fresh_sources(sources, runner)
        selected = dict(state)
        selected.pop("directory")
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
