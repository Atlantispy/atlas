"""Audit-guarded bootstrap for the reviewed, pinned History A Python producer.

This is NOT an OS security sandbox and does not make arbitrary Python safe.
Python audit events do not cover every native-library call, inherited handle,
memory modification or filesystem race. The parent must independently pin the
producer/runtime, retain an isolated fresh output tree, and verify inputs and
outputs after execution. In particular, this guard is not an input-hash check.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import runpy
import stat
import sys
import tempfile
from typing import Any


class AuditGuardError(PermissionError):
    """A covered operation violates the isolated replay's write policy."""


def plain_local_path(value: Any, *, absolute: bool = False) -> Path:
    """Lexically normalise without following links or Windows device aliases."""
    if isinstance(value, int):
        raise AuditGuardError("descriptor addressing is not supported here")
    try:
        raw = os.fsdecode(os.fspath(value))
    except TypeError as exc:
        raise AuditGuardError("filesystem address must be a path") from exc
    lexical = raw.replace("\\", "/")
    if not raw or "\x00" in raw or lexical.startswith("//") or lexical.startswith("/??/"):
        raise AuditGuardError("plain local paths only; network/device paths are prohibited")
    parts = lexical.split("/")
    if ".." in parts:
        raise AuditGuardError("path traversal is prohibited")
    if os.name == "nt":
        # Reject ADS, DOS devices, drive-relative paths and Win32 aliases before IO.
        if len(lexical) >= 2 and lexical[1] == ":":
            if not lexical[0].isalpha() or len(lexical) < 3 or lexical[2] != "/":
                raise AuditGuardError("drive-relative paths are prohibited")
            parts = lexical[3:].split("/")
        reserved = {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"}
        reserved.update(f"{prefix}{number}" for prefix in ("COM", "LPT") for number in "123456789¹²³")
        for part in parts:
            if part in ("", "."):
                continue
            if ":" in part or part.endswith((" ", ".")) or part.split(".", 1)[0].upper() in reserved:
                raise AuditGuardError("Windows device, stream or aliased path is prohibited")
    path = Path(raw)
    if absolute and not path.is_absolute():
        raise AuditGuardError("an absolute local path is required")
    return Path(os.path.abspath(path))


def reject_links(path: Path) -> None:
    """Check existing path components with lstat, including dangling links."""
    for component in (path, *path.parents):
        try:
            info = component.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise AuditGuardError(f"linked/reparse path is prohibited: {component}")
        if stat.S_ISREG(info.st_mode) and info.st_nlink > 1:
            raise AuditGuardError(f"hard-linked file is prohibited for guarded writes: {component}")


def inspect_paths(write_root: Any, script: Any) -> tuple[Path, Path]:
    root = plain_local_path(write_root, absolute=True)
    producer = plain_local_path(script, absolute=True)
    reject_links(root)
    reject_links(producer)
    if not root.is_dir():
        raise AuditGuardError("write root must be an existing directory")
    if producer == root or not producer.is_relative_to(root) or not producer.is_file():
        raise AuditGuardError("script must be an existing file beneath the write root")
    return root, producer


class WriteAuditGuard:
    """Restrict covered filesystem mutations, process creation and socket IO."""

    def __init__(self, write_root: Path):
        self.write_root = write_root

    def check_path(self, value: Any) -> Path:
        target = plain_local_path(value)
        if not target.is_relative_to(self.write_root):
            raise AuditGuardError(f"write outside root is prohibited: {target}")
        reject_links(target)
        return target

    @staticmethod
    def check_dir_fd(args: tuple, *positions: int) -> None:
        for position in positions:
            if position < len(args):
                value = args[position]
                # CPython emits -1 for the omitted dir_fd audit argument.
                if value is not None and not (type(value) is int and value == -1):
                    raise AuditGuardError("dir_fd filesystem addressing is unsupported")

    def __call__(self, event: str, args: tuple) -> None:
        if event == "open":
            path, mode, flags = args
            write_mode = isinstance(mode, str) and any(char in mode for char in "wax+")
            write_flags = 0
            for name in ("O_WRONLY", "O_RDWR", "O_APPEND", "O_CREAT", "O_TRUNC"):
                write_flags |= getattr(os, name, 0)
            writing = write_mode or (isinstance(flags, int) and bool(flags & write_flags))
            if writing:
                if type(path) is int and path in (1, 2):
                    return  # The parent owns stdout/stderr pipes.
                self.check_path(path)
        elif event in {"os.link", "os.symlink"}:
            raise AuditGuardError("creating hard links or symlinks is prohibited")
        elif event in {"os.rename", "os.replace"}:
            self.check_dir_fd(args, 2, 3)
            self.check_path(args[0])
            self.check_path(args[1])
        elif event in {"os.remove", "os.rmdir"}:
            self.check_dir_fd(args, 1)
            self.check_path(args[0])
        elif event in {"os.mkdir", "os.chmod"}:
            self.check_dir_fd(args, 2)
            self.check_path(args[0])
        elif event == "os.utime":
            self.check_dir_fd(args, 3)
            self.check_path(args[0])
        elif event in {"os.truncate", "os.chdir"}:
            self.check_path(args[0])
        elif event == "shutil.rmtree":
            self.check_dir_fd(args, 1)
            self.check_path(args[0])
        elif event in {"os.chown", "os.setxattr", "os.removexattr"}:
            if event == "os.chown":
                self.check_dir_fd(args, 3)
            self.check_path(args[0])
        elif event in {"subprocess.Popen", "os.system", "os.exec", "os.posix_spawn",
                       "os.spawn", "os.fork", "os.forkpty", "pty.spawn",
                       "os.startfile", "os.startfile/2"}:
            raise AuditGuardError("creating another process is prohibited")
        elif event in {"socket.connect", "socket.connect_ex", "socket.bind",
                       "socket.sendto", "socket.sendmsg", "socket.getaddrinfo"}:
            raise AuditGuardError("network connection or transmission is prohibited")


def install_guard(root: Path) -> None:
    sys.addaudithook(WriteAuditGuard(root))
    original_open = os.open

    def guarded_os_open(path, flags, mode=0o777, *, dir_fd=None):
        # CPython's `open` audit event omits os.open's dir_fd. Reject it at this
        # Python entry point as well, rather than resolving the audited name
        # against cwd while the actual syscall addresses another directory.
        # Saved/native aliases are one reason this is not a security sandbox.
        if dir_fd is not None:
            raise AuditGuardError("dir_fd filesystem addressing is unsupported")
        return original_open(path, flags, mode)

    os.open = guarded_os_open


def prepare_runtime(root: Path) -> Path:
    """Create only the reserved fresh in-root runtime directory, before hooking."""
    runtime = root / "_runtime"
    reject_links(runtime)
    runtime.mkdir(exist_ok=False)
    for name in ("tmp", "cache", "matplotlib", "numba", "pycache"):
        (runtime / name).mkdir()
    environment = {
        "TEMP": runtime / "tmp", "TMP": runtime / "tmp", "TMPDIR": runtime / "tmp",
        "XDG_CACHE_HOME": runtime / "cache", "MPLCONFIGDIR": runtime / "matplotlib",
        "NUMBA_CACHE_DIR": runtime / "numba", "PYTHONPYCACHEPREFIX": runtime / "pycache",
    }
    for name, value in environment.items():
        os.environ[name] = str(value)
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    sys.dont_write_bytecode = True
    tempfile.tempdir = str(runtime / "tmp")
    return runtime


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write-root", required=True)
    parser.add_argument("--script", required=True)
    args = parser.parse_args(argv)
    try:
        root, script = inspect_paths(args.write_root, args.script)
        prepare_runtime(root)
        # This changes only the bootstrap subprocess, and only into its root.
        os.chdir(root)
        install_guard(root)
        sys.argv = [str(script)]
        runpy.run_path(str(script), run_name="__main__")
        return 0
    except AuditGuardError as exc:
        print(json.dumps({"status": "GUARD_BLOCKED", "error": str(exc),
                          "os_security_sandbox": False}), file=sys.stderr)
        return 2
    except OSError as exc:
        print(json.dumps({"status": "BOOTSTRAP_OR_PRODUCER_IO_FAILED", "error": str(exc),
                          "os_security_sandbox": False}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
