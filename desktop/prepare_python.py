"""Copy an explicit Windows CPython base and pinned wheels into a NEW payload.

No install, source-environment edit, checkpoint repin or scientific validation.
Run with CPython 3.12. Copies exclude user bytecode, venv launchers and direct URLs.
"""
from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tempfile

ROOT_FILES = ("python.exe", "pythonw.exe", "python3.dll", "python312.dll",
              "vcruntime140.dll", "vcruntime140_1.dll", "LICENSE.txt")
PIN = re.compile(r"([A-Za-z0-9][A-Za-z0-9_.-]*)==([A-Za-z0-9_.+!-]+)")
NOTICE = re.compile(r"licen[cs]e|copying|notice", re.I)


def canonical(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def checked_path(path):
    """Reject links/junctions before resolving, including existing ancestors."""
    path = Path(os.path.abspath(path))
    for part in (path, *path.parents):
        if part.is_symlink() or part.is_junction():
            raise ValueError(f"Linked input/output is unsupported: {part.name}")
    return path


def requirements(paths):
    pins, visited, active = {}, set(), set()
    binary_only = False

    def read(path, root, depth):
        nonlocal binary_only
        path = checked_path(path)
        if not path.is_relative_to(root) or depth > 4:
            raise ValueError("Requirement include escaped its directory or depth bound")
        if path in active:
            raise ValueError("Cyclic requirement include")
        if path in visited:
            return
        if len(visited) >= 32 or path.stat().st_size > 1_000_000:
            raise ValueError("Requirements exceed the bounded input size")
        visited.add(path)
        active.add(path)
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            line = line.split("#", 1)[0].strip()
            if not line:
                continue
            if line == "--only-binary=:all:":
                binary_only = True
            elif line.startswith("-r "):
                read(path.parent / line[3:].strip(), root, depth + 1)
            elif match := PIN.fullmatch(line):
                name, version = canonical(match[1]), match[2]
                if name in pins and pins[name] != version:
                    raise ValueError(f"Conflicting versions for {name}")
                pins[name] = version
            else:
                raise ValueError(f"Unsupported requirement: {line}")
        active.remove(path)

    for path in paths:
        path = checked_path(path)
        read(path, path.parent, 0)
    if not pins or not binary_only:
        raise ValueError("Exact pins and --only-binary=:all: are required")
    return dict(sorted(pins.items()))


def tree_files(root, excluded=()):
    checked_path(root)
    for child in sorted(root.iterdir()):
        if child.name in excluded or child.name == "__pycache__":
            continue
        checked_path(child)
        if child.is_dir():
            yield from tree_files(child)
        elif child.is_file() and child.suffix.lower() not in {".pyc", ".pyo"}:
            yield child
        elif not child.is_file():
            raise ValueError(f"Non-regular runtime input: {child.name}")


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def record_path(value):
    path = PurePosixPath(value)
    if path.is_absolute() or "\\" in value or ":" in value:
        raise ValueError("Unsafe installed RECORD path")
    if ".." in path.parts:
        # pip-created console scripts contain source-venv paths and are omitted.
        if len(path.parts) == 4 and path.parts[:3] == ("..", "..", "Scripts"):
            return None
        if value == "../../share/man/man1/ttx.1":
            return None  # fonttools' console-command manual is not a runtime input.
        raise ValueError("Installed RECORD escaped site-packages")
    if not path.parts:
        raise ValueError("Empty installed RECORD path")
    return path


def wheel_files(site, pins):
    installed = {}
    # Metadata must be checked before importlib reads it as well as before copy.
    for child in site.iterdir():
        if child.name.endswith(".dist-info"):
            checked_path(child)
            for name in ("METADATA", "WHEEL", "RECORD"):
                checked_path(child / name)
    for dist in importlib.metadata.distributions(path=[str(site)]):
        installed.setdefault(canonical(dist.metadata["Name"]), []).append(dist)
    packages, plan = [], []
    for name, version in pins.items():
        matches = installed.get(name, [])
        if len(matches) != 1 or matches[0].version != version:
            raise ValueError(f"Expected exactly {name}=={version} in source site-packages")
        dist = matches[0]
        if not dist.read_text("WHEEL") or not dist.files:
            raise ValueError(f"{name} is not an installed wheel with RECORD")
        selected, notices, record = [], [], None
        for item in dist.files:
            relative = record_path(str(item))
            if relative is None:
                continue
            if item.name == "RECORD" and relative.parts[0].endswith(".dist-info"):
                record = relative
                continue
            if ("__pycache__" in relative.parts or item.suffix.lower() in {".pyc", ".pyo"}
                    or item.name in {"direct_url.json", "REQUESTED"}):
                continue
            if item.suffix.lower() in {".pth", ".egg-link"}:
                raise ValueError(f"{name} contains a path injection file")
            source = checked_path(site.joinpath(*relative.parts))
            if not source.is_file():
                raise ValueError(f"Missing installed file for {name}: {relative}")
            target = PurePosixPath("Lib/site-packages") / relative
            selected.append((source, target, item.hash, item.size))
            if NOTICE.search(str(relative)):
                notices.append(target.as_posix())
        if record is None or not notices:
            raise ValueError(f"{name} lacks a RECORD or bundled licence/notice")
        plan.extend(selected)
        packages.append(dict(name=name, version=version, notices=sorted(notices), record=record, files=selected))
    return packages, plan


SMOKE = r'''
import importlib, json, os, pathlib, site, subprocess, sys, tempfile
root = pathlib.Path(sys.executable).parent.resolve()
paths = [pathlib.Path(p).resolve() for p in sys.path if p]
assert all(p.is_relative_to(root) for p in paths), "external sys.path"
assert pathlib.Path(sys.prefix).resolve() == root
assert sys.prefix == sys.base_prefix and not site.ENABLE_USER_SITE
versions = {}
for name in ("numpy", "scipy", "numba", "llvmlite", "blosc2", "shapely", "psutil", "matplotlib"):
    module = importlib.import_module(name)
    assert pathlib.Path(module.__file__).resolve().is_relative_to(root), name
    versions[name] = module.__version__
import numpy as np
from scipy.linalg import solve
from numba import njit
from shapely.geometry import Point
import blosc2, psutil
assert np.allclose(solve(np.array([[2.0, 0.0], [0.0, 4.0]]), np.array([4.0, 8.0])), [2, 2])
assert njit(lambda x: x + 1)(2) == 3
assert blosc2.decompress(blosc2.compress(b"atlas" * 16)) == b"atlas" * 16
assert Point(0, 0).buffer(1).area > 3
assert psutil.Process().pid == os.getpid()
import matplotlib
matplotlib.use("Agg")
from matplotlib.figure import Figure
from matplotlib.backends.backend_agg import FigureCanvasAgg
fig = Figure(figsize=(1, 1)); FigureCanvasAgg(fig); fig.add_subplot().plot([0, 1]); fig.canvas.draw()
with tempfile.TemporaryDirectory(prefix="atlas-python-smoke-") as temporary:
    work = pathlib.Path(temporary)
    (work / "atlas_payload_probe.py").write_text("VALUE = 73\n", encoding="utf-8")
    script = work / "probe.py"
    script.write_text("import atlas_payload_probe, pathlib, sys\n"
        "assert atlas_payload_probe.VALUE == 73\n"
        "root = pathlib.Path(sys.executable).parent.resolve()\n"
        "allowed = pathlib.Path(__file__).parent.resolve()\n"
        "assert all(pathlib.Path(p).resolve().is_relative_to(root) or pathlib.Path(p).resolve() == allowed for p in sys.path if p)\n", encoding="utf-8")
    child = dict(os.environ, PYTHONPATH=str(work), PYTHONSAFEPATH="1", PYTHONNOUSERSITE="1")
    child.pop("PYTHONHOME", None)
    subprocess.run([sys.executable, "-B", str(script)], check=True, cwd=work, env=child)
print(json.dumps({"status": "PASS", "version": sys.version, "versions": versions,
    "sys_path": [p.relative_to(root).as_posix() for p in paths],
    "isolated_imports": True, "script_and_pythonpath_without_pythonhome": True}))
'''


def smoke(output):
    keys = {"systemroot", "windir", "temp", "tmp", "processor_architecture", "processor_architew6432"}
    env = {key: value for key, value in os.environ.items() if key.lower() in keys}
    env.update(PYTHONNOUSERSITE="1", PYTHONDONTWRITEBYTECODE="1", PYTHONSAFEPATH="1")
    system = next((value for key, value in env.items() if key.lower() == "systemroot"), r"C:\Windows")
    env["PATH"] = os.pathsep.join([str(output), str(Path(system) / "System32")])
    with tempfile.TemporaryDirectory(prefix="atlas-mpl-smoke-") as config:
        env["MPLCONFIGDIR"] = config
        result = subprocess.run([str(output / "python.exe"), "-I", "-B", "-c", SMOKE],
                                check=True, env=env, cwd=output, text=True,
                                capture_output=True, timeout=120)
    if result.stderr.strip():
        print(result.stderr.strip(), file=sys.stderr)
    return json.loads(result.stdout)


def prepare(base, site, inputs, output, runtime_notices=()):
    if sys.platform != "win32" or sys.version_info[:2] != (3, 12):
        raise ValueError("Run with Windows CPython 3.12")
    base, site, output = map(checked_path, (base, site, output))
    if not base.is_dir() or not site.is_dir():
        raise ValueError("Explicit Python base and site-packages must exist")
    for source in (base, site):
        if output.is_relative_to(source) or source.is_relative_to(output):
            raise ValueError("Output and source trees must not overlap")
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError("Refusing to overwrite a non-empty output")
    packages, plan = wheel_files(site, requirements(inputs))
    for filename in ROOT_FILES:
        source = checked_path(base / filename)
        if not source.is_file():
            raise ValueError(f"Incomplete standalone Python base: {filename}")
        plan.append((source, PurePosixPath(filename), None, None))
    for directory in ("Lib", "DLLs", "tcl"):
        for source in tree_files(base / directory, {"site-packages"}):
            plan.append((source, PurePosixPath(source.relative_to(base).as_posix()), None, None))
    for notice in runtime_notices:
        notice = checked_path(notice)
        plan.append((notice, PurePosixPath("runtime-notices") / notice.name, None, None))
    targets = [str(item[1]).lower() for item in plan]
    if len(targets) != len(set(targets)):
        raise ValueError("Duplicate payload destination")
    output.mkdir(parents=True, exist_ok=True)
    digests = {}
    for source, relative, expected_hash, expected_size in sorted(plan, key=lambda item: str(item[1])):
        checked_path(source)
        target = output.joinpath(*relative.parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        with source.open("rb") as original, target.open("xb") as copied:
            shutil.copyfileobj(original, copied, length=1024 * 1024)
        value, size = digest(target), target.stat().st_size
        if expected_size is not None and size != expected_size:
            raise ValueError(f"Installed wheel size mismatch: {relative}")
        if expected_hash:
            encoded = base64.urlsafe_b64encode(bytes.fromhex(value)).rstrip(b"=").decode()
            if expected_hash.mode != "sha256" or encoded != expected_hash.value:
                raise ValueError(f"Installed wheel digest mismatch: {relative}")
        digests[str(relative)] = (value, size)
    package_manifest = []
    for package in packages:
        rows = []
        for _, relative, _, _ in package["files"]:
            value, size = digests[str(relative)]
            encoded = base64.urlsafe_b64encode(bytes.fromhex(value)).rstrip(b"=").decode()
            rows.append((relative.relative_to("Lib/site-packages").as_posix(), "sha256=" + encoded, size))
        rows.append((str(package["record"]), "", ""))
        with (output / "Lib/site-packages" / str(package["record"])).open("x", encoding="utf-8", newline="") as stream:
            csv.writer(stream, lineterminator="\n").writerows(sorted(rows))
        package_manifest.append({key: package[key] for key in ("name", "version", "notices")})
    check = smoke(output)
    inventory = "\n".join(f"{key}\0{value}\0{size}" for key, (value, size) in sorted(digests.items()))
    manifest = {"schema": "atlas.desktop-python-payload.v1", "status": "WORKING NON-CANON",
                "python": check["version"], "interpreter_sha256": digests["python.exe"][0],
                "distribution_count": len(packages), "copied_file_count": len(digests),
                "copied_bytes": sum(size for _, size in digests.values()),
                "copied_inventory_sha256": hashlib.sha256(inventory.encode()).hexdigest(),
                "packages": package_manifest, "smoke": check,
                "runtime_notices": ["LICENSE.txt", "tcl/tk8.6/license.terms"] + ["runtime-notices/" + Path(p).name for p in runtime_notices],
                "omitted": ["development site-packages", "bytecode", "venv launchers", "fonttools ttx man page", "direct_url.json", "REQUESTED"],
                "identity_note": "Copied base interpreter; native runtime guards remain authoritative. No checkpoint repin or scientific validation."}
    with (output / "atlas-python-payload.json").open("x", encoding="utf-8") as stream:
        json.dump(manifest, stream, indent=2, sort_keys=True)
        stream.write("\n")
    with (output / "THIRD_PARTY_NOTICES.txt").open("x", encoding="utf-8") as stream:
        stream.write("Atlas desktop Python runtime\n\nCPython and bundled libraries: LICENSE.txt and runtime-notices/\n"
                     "Tcl/Tk notices remain within tcl/. Python distribution notices remain in Lib/site-packages/.\n"
                     "See atlas-python-payload.json for all notice locations. Numerical wheel binaries are unchanged.\n"
                     "Venv launchers and cached bytecode are omitted; RECORD files describe delivered files.\n")
    return {key: manifest[key] for key in ("schema", "distribution_count", "copied_file_count", "copied_bytes", "interpreter_sha256", "smoke")}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python-base", type=Path, required=True)
    parser.add_argument("--site-packages", type=Path, required=True)
    parser.add_argument("--requirements", type=Path, action="append", required=True)
    parser.add_argument("--runtime-notice", type=Path, action="append", default=[])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = prepare(args.python_base, args.site_packages, args.requirements, args.output, args.runtime_notice)
    except subprocess.CalledProcessError as error:
        print(error.stdout or "", file=sys.stderr)
        print(error.stderr or "", file=sys.stderr)
        print("Payload smoke failed; partial output retained for diagnosis.", file=sys.stderr)
        return 1
    except (OSError, ValueError, subprocess.TimeoutExpired) as error:
        print(f"Payload refused: {error}. Any partial output is retained.", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
