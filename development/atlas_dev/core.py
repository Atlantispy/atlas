"""Explicit new public bindings and offline environments, never historical rebinding.

These local records detect changes, not a hostile owner who can replace both code
and records. The original generator's validators remain independent. Only the
public profiles in PROFILES.json are executable through this package.
"""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import stat
import struct
import subprocess
import sys
import sysconfig
import tempfile
from typing import Any
import venv

from . import SCOPE, VERSION

BINDING_SCHEMA = "atlas.public-development.binding.v1"
ROOT = Path(__file__).resolve().parents[2]
MAX_FILE = 8 * 1024 * 1024
MAX_TOTAL = 128 * 1024 * 1024
MAX_FILES = 5000
SOURCE_ROOTS = ("development", "tools", "tests", "engineering/work", "shared_generator/engine")
SUFFIXES = {".py", ".json", ".md", ".txt", ".toml", ".yaml", ".yml"}


class DevelopmentError(ValueError):
    """Unverified, incompatible or out-of-scope public development request."""


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      allow_nan=False, ensure_ascii=True).encode("utf-8")


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DevelopmentError("duplicate JSON key: " + key)
        result[key] = value
    return result


def parse(raw: bytes) -> Any:
    def nonfinite(value: str) -> None:
        raise DevelopmentError("non-finite JSON number: " + value)
    if len(raw) > MAX_FILE:
        raise DevelopmentError("bounded JSON file required")
    try:
        return json.loads(raw, object_pairs_hook=_pairs, parse_constant=nonfinite)
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise DevelopmentError("valid bounded UTF-8 JSON required") from exc


def safe(path: Path) -> Path:
    path = Path(os.path.abspath(path))
    for part in (path, *path.parents):
        try:
            info = part.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise DevelopmentError("linked/reparse path refused: " + str(part))
    return path


def read(path: Path, limit: int = MAX_FILE) -> bytes:
    path = safe(path)
    before = path.stat()
    if not stat.S_ISREG(before.st_mode) or before.st_size > limit:
        raise DevelopmentError("bounded regular file required: " + str(path))
    with path.open("rb") as stream:
        opened = os.fstat(stream.fileno())
        if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
            raise DevelopmentError("file replaced before read")
        raw = stream.read(limit + 1)
        after = os.fstat(stream.fileno())
    current = safe(path).stat()
    if len(raw) > limit or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
            after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns) or (
            current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns) != (
            after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
        raise DevelopmentError("file changed during read")
    return raw


def write_new(path: Path, raw: bytes) -> None:
    """Publish one new complete file with no overwrite, on the same filesystem."""
    path = safe(path)
    if path.exists():
        raise DevelopmentError("destination already exists; choose a new record")
    path.parent.mkdir(parents=True, exist_ok=True)
    safe(path.parent)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".atlas-new-", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        safe(path)
        # Hard-link publication fails rather than overwriting a concurrently
        # created destination. No copy/rename-over-existing fallback is allowed.
        os.link(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def source_inventory(root: Path = ROOT) -> dict[str, dict[str, Any]]:
    root = safe(root)
    result: dict[str, dict[str, Any]] = {}
    total = 0
    for relative in SOURCE_ROOTS:
        directory = safe(root / relative)
        if not directory.is_dir():
            raise DevelopmentError("source directory missing: " + relative)
        # Walk without following directory links; refuse them, do not ignore them.
        for parent, dirs, names in os.walk(directory, followlinks=False):
            dirs[:] = sorted(name for name in dirs if name != "__pycache__")
            for name in dirs:
                safe(Path(parent) / name)
            for name in sorted(names):
                path = Path(parent) / name
                if path.suffix not in SUFFIXES:
                    continue
                raw = read(path)
                total += len(raw)
                if len(result) >= MAX_FILES or total > MAX_TOTAL:
                    raise DevelopmentError("public source inventory limit exceeded")
                result[path.relative_to(root).as_posix()] = {"sha256": digest(raw), "bytes": len(raw)}
    if not result:
        raise DevelopmentError("empty public source inventory")
    return dict(sorted(result.items()))


def profiles(root: Path = ROOT) -> dict[str, Any]:
    value = parse(read(root / "development/PROFILES.json"))
    if (type(value) is not dict or value.get("schema") != "atlas.public-development.profiles.v1"
            or type(value.get("profiles")) is not dict):
        raise DevelopmentError("reviewed public profile configuration required")
    for name, record in value["profiles"].items():
        if type(name) is not str or type(record) is not dict or type(record.get("tests")) is not list:
            raise DevelopmentError("malformed public test profile")
        tests = record["tests"]
        if not tests or len(tests) > 32 or any(type(test) is not str or not test or
                any(not part.isidentifier() for part in test.split(".")) for test in tests):
            raise DevelopmentError("bounded explicit dotted test names required")
    return value


def runtime_identity(*, require_environment: bool = True) -> dict[str, Any]:
    version = f"{sys.version_info.major}.{sys.version_info.minor}"
    config = parse(read(ROOT / "development/ENVIRONMENT.json"))
    if (platform.python_implementation() != config["implementation"] or
            version not in config["python_minors"] or sys.flags.optimize != 0):
        raise DevelopmentError("CPython 3.12/3.13 without optimisation is required")
    distributions = sorted((d.metadata.get("Name", ""), d.version)
                           for d in importlib.metadata.distributions())
    if require_environment:
        if sys.prefix == sys.base_prefix or not sys.flags.isolated or not sys.dont_write_bytecode:
            raise DevelopmentError("use the isolated public venv with -I -B")
        if distributions:
            raise DevelopmentError("public venv must have no installed third-party distributions")
        config_path = Path(sys.prefix) / "pyvenv.cfg"
        settings = {}
        for line in read(config_path).decode("utf-8").splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                settings[key.strip()] = value.strip().lower()
        if settings.get("include-system-site-packages") != "false":
            raise DevelopmentError("system site-packages must be disabled")
        link_path = Path(sysconfig.get_path("purelib")) / "atlas_public_source.pth"
        if read(link_path) != source_link(ROOT):
            raise DevelopmentError("public editable source paths changed")
    # Resolve the interpreter's ordinary installation symlinks explicitly. This
    # does not relax the independent no-links rule for project source/data.
    executable = Path(sys.executable).resolve()
    base = Path(getattr(sys, "_base_executable", sys.executable)).resolve()
    return {
        "python": sys.version, "implementation": platform.python_implementation(),
        "executable": str(executable), "executable_sha256": digest(read(executable, 64 * 1024 * 1024)),
        "base_executable_sha256": digest(read(base, 64 * 1024 * 1024)),
        "platform": platform.platform(), "machine": platform.machine(),
        "byteorder": sys.byteorder, "pointer_bits": struct.calcsize("P") * 8,
        "soabi": sysconfig.get_config_var("SOABI"), "optimisation": sys.flags.optimize,
        "stdlib": sysconfig.get_path("stdlib"), "third_party_distributions": distributions,
        "source_link_sha256": digest(source_link(ROOT)) if require_environment else None,
    }


def verify_executed(inventory: dict[str, dict[str, Any]], root: Path = ROOT) -> None:
    """Check captured package/launcher execution, not just whichever bytes are on disk."""
    if safe(root) != ROOT:
        return  # Only unit-test inventory fixtures may supply an alternate root.
    for name, module in tuple(sys.modules.items()):
        if name == "atlas_dev" or name.startswith("atlas_dev."):
            path = Path(module.__file__)
            relative = path.relative_to(ROOT).as_posix()
            if getattr(module, "_ATLAS_DEV_EXECUTED_SHA256", None) != inventory.get(relative, {}).get("sha256"):
                raise DevelopmentError("executed public development source differs: " + relative)
    main = sys.modules.get("__main__")
    if (not main or Path(getattr(main, "__file__", "")).absolute() != ROOT / "tools/develop.py"
            or getattr(main, "_EXECUTED_SHA256", None) != inventory.get("tools/develop.py", {}).get("sha256")):
        raise DevelopmentError("use the source-captured tools/develop.py launcher")


def capture(root: Path = ROOT) -> dict[str, Any]:
    """Create a NEW public identity; cannot import or update any prior binding."""
    root = safe(root)
    first = source_inventory(root)
    runtime = runtime_identity()
    verify_executed(first, root)
    if first != source_inventory(root):
        raise DevelopmentError("source changed while capturing public binding")
    body = {"schema": BINDING_SCHEMA, "scope": SCOPE, "package_version": VERSION,
            "source_root": str(root), "source_files": first, "runtime": runtime}
    return {"binding": body, "binding_sha256": digest(canonical(body))}


def verify(record: dict[str, Any], root: Path = ROOT) -> str:
    if type(record) is not dict or set(record) != {"binding", "binding_sha256"}:
        raise DevelopmentError("new public-development binding required; no historical checkpoints")
    body = record["binding"]
    expected = {"schema", "scope", "package_version", "source_root", "source_files", "runtime"}
    if (type(body) is not dict or set(body) != expected or body["schema"] != BINDING_SCHEMA
            or body["scope"] != SCOPE or body["package_version"] != VERSION
            or body["source_root"] != str(safe(root))
            or record["binding_sha256"] != digest(canonical(body))):
        raise DevelopmentError("binding schema, scope, location or commitment differs")
    if type(body["source_files"]) is not dict or type(body["runtime"]) is not dict:
        raise DevelopmentError("binding inventories must be objects")
    current = source_inventory(root)
    if body["source_files"] != current:
        changed = [key for key in sorted(set(body["source_files"]) | set(current))
                   if body["source_files"].get(key) != current.get(key)]
        raise DevelopmentError("public source changed; capture a NEW binding after review: " + ", ".join(changed[:4]))
    verify_executed(current, root)
    if body["runtime"] != runtime_identity():
        raise DevelopmentError("development runtime changed; no silent adoption")
    return record["binding_sha256"]


def source_link(root: Path) -> bytes:
    """Plain editable source paths only; never executable .pth statements."""
    paths = [str(safe(root) / part) for part in ("development", "engineering")]
    if any("\n" in path or "\r" in path for path in paths):
        raise DevelopmentError("source path cannot contain newline characters")
    return ("\n".join(paths) + "\n").encode("utf-8")


def install_sources(interpreter: Path, root: Path) -> None:
    """Install this checkout as a local editable package without pip or network."""
    command = [str(interpreter), "-I", "-B", "-c",
               "import sysconfig; print(sysconfig.get_path('purelib'))"]
    result = subprocess.run(command, capture_output=True, text=True, check=True, timeout=30)
    purelib = safe(Path(result.stdout.strip()))
    environment = safe(root / ".atlas-dev/venv")
    if not purelib.is_relative_to(environment) or not purelib.is_dir():
        raise DevelopmentError("new interpreter reported site-packages outside its environment")
    write_new(purelib / "atlas_public_source.pth", source_link(root))


def bootstrap(root: Path = ROOT) -> Path:
    """Create a fresh offline, package-free environment; never reuse or clear one."""
    runtime_identity(require_environment=False)
    root = safe(root)
    parent = safe(root / ".atlas-dev")
    parent.mkdir(exist_ok=True)
    destination = safe(parent / "venv")
    destination.mkdir()  # Exclusive reservation; an existing venv is not adopted.
    try:
        venv.EnvBuilder(system_site_packages=False, clear=False, symlinks=False,
                        with_pip=False, upgrade=False, upgrade_deps=False,
                        prompt="atlas-public-dev").create(destination)
    except BaseException:
        # Preserve partial installation for explicit inspection; no broad cleanup.
        raise DevelopmentError("environment setup incomplete; partial directory retained")
    executable = destination / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not executable.is_file():
        raise DevelopmentError("new environment lacks its interpreter")
    install_sources(executable, root)
    return executable
