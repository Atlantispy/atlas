"""Pinned outer entry for the unchanged native launcher under Python -B -s -P.

This changes no import path or native child command. The ordinary import
machinery handles non-helper imports; exact declared helper names use checked
source bytes. Importing this module never imports an Atlas helper or workload.
"""
import argparse
from hashlib import sha256
import importlib.abc
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import stat
import sys
import tracemalloc


T = Path("C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10")
REAL_ROOT = T / "ac/p13c14m-r1"
REAL_PYTHON = T / ".r44-env/Scripts/python.exe"
REAL_COUNTS = (239, 395)
ENTRY_NAME = "launch_fresh_interval.py"
MAX_COMPOSITION_BYTES = 8 << 20
PYTHON_ENV = {"PYTHONHASHSEED": "0", "PYTHONDONTWRITEBYTECODE": "1"}
THREAD_ENV = {"OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"}
HOOK_ENV = frozenset(("COVERAGE_PROCESS_START", "PYTHONPROFILEIMPORTTIME", "PYTHONTRACEMALLOC",
    "PYTHONSTARTUP", "PYTHONDEVMODE", "PYTHONMALLOC", "PYTHONMALLOCSTATS", "PYTHONINSPECT",
    "PYTHONOPTIMIZE", "PYTHONPATH", "PYTHONHOME", "ATLAS_INITIAL_MEASUREMENT_SEED", "ATLAS_DEV_TIMING"))


class BootstrapRefused(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise BootstrapRefused(message)


def ordinary(value, *, directory=False):
    """Check original ancestry before resolving so links cannot disappear."""
    path = Path(value)
    require(path.is_absolute(), "explicit absolute path required: " + str(path))
    info = None
    for item in (*reversed(path.parents), path):
        info = item.lstat()
        require(not stat.S_ISLNK(info.st_mode) and not getattr(info, "st_file_attributes", 0) & 0x400,
                "linked or reparse path refused: " + str(item))
    require(str(path) == str(path.resolve(strict=True)), "canonical path required: " + str(path))
    require(stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode),
            "ordinary directory required: " + str(path) if directory else "ordinary regular file required: " + str(path))
    return path


def full_sha(value):
    return type(value) is str and len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def checked_raw(path, pin):
    require(full_sha(pin), "complete lowercase source SHA-256 required")
    path = ordinary(path)
    before = path.stat()
    raw = path.read_bytes()
    after = ordinary(path).stat()
    require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) ==
            (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns) and
            sha256(raw).hexdigest() == pin, "source digest differs: " + str(path))
    return raw


def file_digest(path):
    path = ordinary(path)
    digest = sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate composition key: " + str(key))
        result[key] = value
    return result


def _invalid_number(value):
    raise BootstrapRefused("non-finite composition number: " + value)


def _relative_name(name):
    require(type(name) is str and name and "\\" not in name, "canonical relative inventory name required")
    path = PurePosixPath(name)
    require(path.parts and not path.is_absolute() and path.as_posix() == name
            and all(part not in ("", ".", "..") and ":" not in part for part in path.parts),
            "inventory path escaped its declared root: " + name)
    return path


def _inventory(root):
    ordinary(root, directory=True)
    result = {}

    def scan_error(error):
        raise BootstrapRefused("source inventory scan failed: " + str(error)) from error

    for directory, directories, files in os.walk(root, followlinks=False, onerror=scan_error):
        directory = ordinary(Path(directory), directory=True)
        for name in directories:
            ordinary(directory / name, directory=True)
        for name in files:
            path = ordinary(directory / name)
            result[path.relative_to(root).as_posix()] = file_digest(path)
    return result


class Composition:
    def __init__(self, path, pin, root, counts, helpers):
        self.path, self.pin, self.root, self.counts = path, pin, root, counts
        self.helpers = dict(helpers)
        self.entry = root / "helpers" / ENTRY_NAME

    def recheck(self):
        validate_composition(self.path, self.pin, expected_root=self.root, expected_counts=self.counts)


def validate_composition(path, pin, *, expected_root=REAL_ROOT, expected_counts=REAL_COUNTS):
    """Injected roots/counts are for disposable unit fixtures; CLI uses constants."""
    root = ordinary(expected_root, directory=True)
    path = ordinary(path)
    require(path == root / "composition.json", "composition must be the selected root's record")
    require(path.stat().st_size <= MAX_COMPOSITION_BYTES, "composition exceeds bounded JSON size")
    raw = checked_raw(path, pin)
    require(len(raw) <= MAX_COMPOSITION_BYTES, "composition changed beyond bounded JSON size")
    row = json.loads(raw, object_pairs_hook=_pairs, parse_constant=_invalid_number)
    require(type(row) is dict and type(row.get("root")) is str and Path(row["root"]) == root,
            "composition permanent root differs")
    require(type(expected_counts) is tuple and len(expected_counts) == 2
            and all(type(count) is int and count > 0 for count in expected_counts), "fixed inventory counts required")
    maps = []
    for field, folder, count in zip(("outputs", "helpers"), ("src", "helpers"), expected_counts, strict=True):
        declared = row.get(field)
        require(type(declared) is dict and len(declared) == count, "complete declared inventory required: " + field)
        for name, digest in declared.items():
            _relative_name(name)
            require(full_sha(digest), "unresolved declared source pin: " + str(name))
        require(_inventory(root / folder) == declared, "complete source inventory differs: " + folder)
        maps.append(declared)
    helpers = {}
    for name, digest in maps[1].items():
        relative = _relative_name(name)
        if len(relative.parts) == 1 and relative.suffix == ".py":
            require(relative.stem.isidentifier(), "invalid top-level helper module: " + name)
            require(relative.stem not in helpers, "duplicate helper module name: " + relative.stem)
            helpers[relative.stem] = (root / "helpers" / name, digest)
    require(ENTRY_NAME in maps[1] and Path(ENTRY_NAME).stem in helpers, "declared native launcher entry required")
    return Composition(path, pin, root, expected_counts, helpers)


def runtime_state():
    monitoring = getattr(sys, "monitoring", None)
    monitored = bool(monitoring is not None and any(
        monitoring.get_tool(tool) is not None or monitoring.get_events(tool) for tool in range(6)))
    return {"executable": str(Path(sys.executable).resolve(strict=True)),
        "dont_write_bytecode": bool(sys.flags.dont_write_bytecode and sys.dont_write_bytecode),
        "no_user_site": bool(sys.flags.no_user_site), "safe_path": bool(sys.flags.safe_path),
        "hash_randomization": sys.flags.hash_randomization,
        "ignore_environment": bool(sys.flags.ignore_environment), "isolated": bool(sys.flags.isolated),
        "trace": sys.gettrace() is not None, "profile": sys.getprofile() is not None,
        "tracemalloc": tracemalloc.is_tracing(), "monitoring": monitored,
        "xoptions": dict(sys._xoptions), "environment": dict(os.environ)}


def validate_runtime(state=None):
    """The optional state is a pure synthetic-test seam, never a CLI option."""
    state = runtime_state() if state is None else state
    require(Path(state["executable"]) == REAL_PYTHON, "selected Atlas Python required")
    require(all(state[name] is True for name in ("dont_write_bytecode", "no_user_site", "safe_path"))
            and type(state["hash_randomization"]) is int and state["hash_randomization"] == 0
            and state["ignore_environment"] is False and state["isolated"] is False,
            "selected Python -B -s -P with seed zero required")
    require(all(state[name] is False for name in ("trace", "profile", "tracemalloc", "monitoring"))
            and not state["xoptions"], "instrumented interpreter refused")
    environment = state["environment"]
    upper = {name.upper(): value for name, value in environment.items()}
    require(len(upper) == len(environment), "case-colliding environment names refused")
    require(not HOOK_ENV.intersection(upper), "instrumentation/import-path environment refused")
    python = {name: value for name, value in upper.items() if name.startswith("PYTHON")}
    require(python == PYTHON_ENV, "exact Python seed/write environment required")
    require(upper.get("ATLAS_DEV_STAGE_TIMING", "") in ("", "0"), "developer stage timing refused")
    require(all(upper.get(name) == value for name, value in THREAD_ENV.items()), "single-thread BLAS/OpenMP required")


def _verify_module(module, name, path, pin, loader):
    require(sys.modules.get(name) is module, "participating helper module was replaced: " + name)
    require(type(getattr(module, "__file__", None)) is str and ordinary(module.__file__) == path,
            "participating helper file origin differs: " + name)
    spec = getattr(module, "__spec__", None)
    require(spec is not None and spec.name == name and type(spec.origin) is str
            and ordinary(spec.origin) == path and spec.loader is loader,
            "participating helper spec origin differs: " + name)
    checked_raw(path, pin)


def _combined_failure(original, failure, label):
    if original is None:
        raise failure
    raise BaseExceptionGroup(label, [original, failure]) from None


class PinnedLoader(importlib.machinery.SourceFileLoader):
    def __init__(self, fullname, path, pin, finder):
        super().__init__(fullname, str(path))
        self.source_path, self.pin, self.finder = path, pin, finder

    def get_code(self, fullname):
        require(fullname == self.name, "helper loader name differs")
        return compile(checked_raw(self.source_path, self.pin), str(self.source_path), "exec", dont_inherit=True)

    def exec_module(self, module):
        self.finder.loaded[self.name] = (module, self.source_path, self.pin, self)
        original = None
        try:
            super().exec_module(module)
        except BaseException as error:
            original = error
            raise
        finally:
            try:
                _verify_module(module, self.name, self.source_path, self.pin, self)
            except BaseException as failure:
                _combined_failure(original, failure, "helper execution and source verification failed")


class HelperFinder(importlib.abc.MetaPathFinder):
    def __init__(self, closure):
        self.helpers, self.loaded = dict(closure.helpers), {}

    def find_spec(self, fullname, path=None, target=None):
        if path is not None or fullname not in self.helpers:
            return None
        source, pin = self.helpers[fullname]
        loader = PinnedLoader(fullname, source, pin, self)
        return importlib.util.spec_from_file_location(fullname, source, loader=loader)

    def verify_loaded(self):
        for name, (module, path, pin, loader) in self.loaded.items():
            _verify_module(module, name, path, pin, loader)


def execute_composition(closure, arguments):
    """Execute only the original native launcher, restoring caller-owned state."""
    require(type(arguments) is list and all(type(item) is str for item in arguments), "native argument list required")
    require(not any(name in sys.modules for name in closure.helpers), "preloaded same-name helper refused")
    finder = HelperFinder(closure)
    path_before, argv_before, meta_before = list(sys.path), sys.argv, list(sys.meta_path)
    missing = object()
    main_before = sys.modules.get("__main__", missing)
    path, pin = closure.helpers[Path(ENTRY_NAME).stem]
    require(path == closure.entry, "native launcher entry differs")
    loader = PinnedLoader("__main__", path, pin, finder)
    spec = importlib.util.spec_from_file_location("__main__", path, loader=loader)
    module = importlib.util.module_from_spec(spec)
    original = None
    sys.meta_path.insert(0, finder)
    sys.argv = [str(path), *arguments]
    sys.modules["__main__"] = module
    try:
        loader.exec_module(module)
        return module
    except BaseException as error:
        original = error
        raise
    finally:
        failures = []
        try:
            require(sys.path == path_before, "native entry left a changed sys.path")
            require(sys.meta_path == [finder, *meta_before], "native helper finder set was changed")
            finder.verify_loaded()
        except BaseException as failure:
            failures.append(failure)
        try:
            closure.recheck()
        except BaseException as failure:
            failures.append(failure)
        finally:
            sys.path[:] = path_before
            sys.meta_path[:] = meta_before
            sys.argv = argv_before
            if main_before is missing:
                sys.modules.pop("__main__", None)
            else:
                sys.modules["__main__"] = main_before
        if failures:
            failure = failures[0] if len(failures) == 1 else BaseExceptionGroup("source finality failures", failures)
            _combined_failure(original, failure, "native entry and source finality failed")


def main(argv=None):
    raw = list(sys.argv[1:] if argv is None else argv)
    require("--" in raw, "explicit -- boundary before native launcher arguments required")
    boundary = raw.index("--")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--composition", type=Path, required=True)
    parser.add_argument("--composition-sha256", required=True)
    args = parser.parse_args(raw[:boundary])
    validate_runtime()
    closure = validate_composition(args.composition, args.composition_sha256,
                                   expected_root=REAL_ROOT, expected_counts=REAL_COUNTS)
    execute_composition(closure, raw[boundary + 1:])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
