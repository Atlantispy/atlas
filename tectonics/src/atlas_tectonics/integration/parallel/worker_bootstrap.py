"""Pressure worker start: the parent writes startup.json and starts the child; the child sets sys.path from it.

No scientific code is imported by this file's ordinary import.
"""
import json
import os
from pathlib import Path
import stat
import sys


MODULE = "atlas_tectonics.integration.parallel.worker_bootstrap"
WORKER = "atlas_tectonics.integration.parallel.worker"
SCHEMA = "atlas.private.pressure-worker-startup.r2"
MAX_STARTUP_BYTES = 1 << 20
PYTHON_ENV = {"PYTHONHASHSEED": "0", "PYTHONDONTWRITEBYTECODE": "1"}
THREAD_ENV = {"OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"}
# The child has no PYTHONPATH (the allow-list forbids it), so a stub sets sys.path from the record before
# anything of ours is imported. Arguments, including paths with spaces, stay individual Popen list elements.
ENTRY = (
    "import json,sys;"
    "len(sys.argv)==5 and sys.argv[2:4]==['-m',"
    f"'{WORKER}'] or sys.exit('worker supervision command marker mismatch');"
    "sys.path[:]=json.load(open(sys.argv[1],'rb'))['paths'];"
    f"import {MODULE} as m;"
    "m.run_worker(sys.argv[1],sys.argv[4])"
)


def _require(condition, message):
    if not condition:
        raise ValueError(message)


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


def clean_child_env():
    env = {key: value for key, value in os.environ.items() if not key.upper().startswith("PYTHON")}
    env.update(PYTHON_ENV)
    env.update(THREAD_ENV)
    return env


def launch(directory):
    """Create a bounded startup record and return command/env; never spawn."""
    _validate_interpreter()
    job = _path(str(directory))
    _ordinary(job)
    _require(job.is_dir(), "worker job directory is absent")
    state = {"schema": SCHEMA, "paths": _paths(), "runtime": _runtime(), "directory": str(job)}
    startup = job / "startup.json"
    # Existing dispatch directories are one-shot. Never replace an old launch.
    with startup.open("xb") as stream:
        stream.write(_encode(state))
    # _Child._worker_record recognises exactly this last-three-argument marker, including the owned directory.
    return [sys.executable, "-B", "-s", "-P", "-c", ENTRY, str(startup), "-m", WORKER, str(job)], clean_child_env()


def run_worker(startup_path, marker_directory):
    """Child entry, after the stub has set sys.path: check the record, then run the worker module."""
    _validate_interpreter()
    startup = _path(startup_path)
    _require(startup.stat().st_size <= MAX_STARTUP_BYTES, "worker startup record exceeds its bound")
    state = _json(startup.read_bytes())
    _require(type(state) is dict and set(state) == {"schema", "paths", "runtime", "directory"}
             and state["schema"] == SCHEMA, "worker startup schema differs")
    job = _path(state["directory"])
    _require(startup == job / "startup.json", "worker startup is outside its owned job directory")
    _require(_path(marker_directory) == job, "worker supervision directory differs from startup record")
    _require(state["runtime"] == _runtime(), "worker interpreter differs from parent")
    import runpy
    sys.argv = [WORKER, str(job)]
    runpy.run_module(WORKER, run_name="__main__", alter_sys=True)
