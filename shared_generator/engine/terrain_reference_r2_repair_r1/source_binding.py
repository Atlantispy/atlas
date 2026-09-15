"""Load the repaired runtime from the exact bytes recorded in its identity.

Dependencies are private modules: a pre-existing global ``core``/``water`` does
not substitute another implementation. This is source provenance, not a hostile
Python sandbox. The caller's own import bytes are supplied before dependencies
load; every recorded path is checked again before returning and before a run.
"""
import hashlib
from pathlib import Path
import stat
import sys
import types

RUNTIME_DEPENDENCIES = ("core.py", "materials.py", "constructive.py", "water.py", "basin_topology.py")
MAX_SOURCE_BYTES = 16 * 1024 * 1024


def read_source(path):
    path = Path(path).absolute()
    for part in (path, *path.parents):
        info = part.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValueError("linked runtime source rejected: " + str(part))
    before = path.stat()
    if not path.is_file() or before.st_size > MAX_SOURCE_BYTES:
        raise ValueError("bounded regular runtime source required")
    with path.open("rb") as stream:
        raw = stream.read(MAX_SOURCE_BYTES + 1)
    after = path.stat()
    if len(raw) > MAX_SOURCE_BYTES or (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
        raise ValueError("runtime source changed while reading")
    return raw


def records(sources):
    return tuple({"name": name, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
                 for name, raw in sorted(sources.items()))


def verify(root, expected):
    current = records({row["name"]: read_source(Path(root) / row["name"]) for row in expected})
    if current != expected:
        raise ValueError("runtime source identity changed since import; restart with one source set")
    return current


def load(root, caller_sources):
    root = Path(root).resolve()
    sources = dict(caller_sources)
    sources.update({name: read_source(root / name)
                    for name in (*RUNTIME_DEPENDENCIES, "NUMERICAL_CONTRACT.json")})
    pins = records(sources)
    modules = {}
    created = []
    try:
        for name in RUNTIME_DEPENDENCIES:
            raw = sources[name]
            # Distinct import instances cannot share mutable module globals.
            module_name = "_terrain_r2_repair_" + Path(name).stem + "_" + str(id(modules))
            module = types.ModuleType(module_name)
            module.__file__ = str(root / name)
            sys.modules[module_name] = module
            created.append(module_name)
            exec(compile(raw, str(root / name), "exec"), module.__dict__)
            modules[name] = module
        verify(root, pins)
    except BaseException:
        for name in created:
            sys.modules.pop(name, None)
        raise
    return modules, pins
