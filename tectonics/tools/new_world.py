"""Bounded configuration CLI; never imports or runs the scientific generator.

SPDX-License-Identifier: AGPL-3.0-only

Saved plans are immutable through this interface: publication uses an exclusive
hard link, never replacement. Paths must be local and have no symlink/reparse
components. This is a trusted local CLI, not a filesystem sandbox against a
hostile process concurrently renaming directories.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import secrets
import stat
import sys

from new_world_contract import (
    ContractError, canonical_bytes, contract_description, new_request,
    parse_json, resolve_request, validate_plan,
)


RESPONSE_SCHEMA = "atlas.new-world-response.v1"
MAX_INPUT_BYTES = 64 * 1024
_REPARSE = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
_DEVICE = re.compile(r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)", re.I)


def _fail(code: str, message: str):
    raise ContractError(code, message)


def _bounded_read(stream):
    body = stream.read(MAX_INPUT_BYTES + 1)
    if isinstance(body, str):
        body = body.encode("utf-8")
    if len(body) > MAX_INPUT_BYTES:
        _fail("INPUT_TOO_LARGE", "JSON input exceeds 64 KiB.")
    return parse_json(body)


def _unsafe(info):
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & _REPARSE
    )


def _identity(info):
    return info.st_dev, info.st_ino


def _checked_path(raw):
    # Reject aliases before abspath can erase a symlink followed by '..'.
    if (not isinstance(raw, str) or not raw or len(raw) > 4096
            or "\0" in raw or raw.startswith(("\\\\", "//"))):
        _fail("INVALID_PATH", "Use a bounded local file path.")
    parts = re.split(r"[\\/]", raw)
    if len(parts) > 128 or ".." in parts:
        _fail("INVALID_PATH", "Parent traversal and excessive path depth are unsupported.")
    for index, part in enumerate(parts):
        if index == 0 and os.name == "nt" and re.fullmatch(r"[a-zA-Z]:", part):
            continue
        if (":" in part or _DEVICE.match(part)
                or (part not in ("", ".") and part.endswith((".", " ")))):
            _fail("INVALID_PATH", "Device paths and ambiguous file names are unsupported.")
    path = Path(os.path.abspath(raw))
    if not path.name or len(path.parts) > 128:
        _fail("INVALID_PATH", "A bounded local file path is required.")
    parents = []
    for parent in reversed(path.parents):
        info = parent.lstat()
        if _unsafe(info):
            _fail("UNSAFE_PATH", "Symlinks and reparse paths are unsupported.")
        if not stat.S_ISDIR(info.st_mode):
            _fail("INVALID_PATH", "The parent must be an existing directory.")
        parents.append((parent, _identity(info)))
    return path, parents


def _check_parents(parents):
    for path, identity in parents:
        info = path.lstat()
        if _unsafe(info) or not stat.S_ISDIR(info.st_mode) or _identity(info) != identity:
            _fail("UNSAFE_PATH", "The file's parent directories changed.")


class _Directory:
    """Use an anchored directory descriptor where the platform supports it."""

    def __init__(self, path, parents):
        self.path, self.parents, self.fd = path, parents, None

    def __enter__(self):
        _check_parents(self.parents)
        if all(fn in os.supports_dir_fd for fn in (os.open, os.stat, os.link, os.unlink)):
            self.fd = os.open(self.path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            if _identity(os.fstat(self.fd)) != self.parents[-1][1]:
                os.close(self.fd)
                self.fd = None
                _fail("UNSAFE_PATH", "The file's parent directory changed.")
        return self

    def __exit__(self, *_):
        if self.fd is not None:
            os.close(self.fd)

    def name(self, name):
        return self.path / name if self.fd is None else name

    def kwargs(self):
        return {} if self.fd is None else {"dir_fd": self.fd}

    def inspect(self, name):
        return os.stat(self.name(name), follow_symlinks=False, **self.kwargs())

    def open(self, name, flags):
        return os.open(self.name(name), flags, 0o600, **self.kwargs())

    def publish(self, source, target):
        _check_parents(self.parents)
        options = {} if self.fd is None else {"src_dir_fd": self.fd, "dst_dir_fd": self.fd}
        os.link(self.name(source), self.name(target), follow_symlinks=False, **options)

    def remove_owned(self, name, identity):
        _check_parents(self.parents)
        try:
            info = self.inspect(name)
        except FileNotFoundError:
            return
        if _unsafe(info) or _identity(info) != identity:
            _fail("UNSAFE_PATH", "Temporary-file ownership changed; cleanup refused.")
        os.unlink(self.name(name), **self.kwargs())


def save_plan(raw_path, record):
    """Validate first, then publish a new complete file without replacing any path."""
    plan = validate_plan(record)
    body = canonical_bytes(plan) + b"\n"
    if len(body) > MAX_INPUT_BYTES:
        _fail("INPUT_TOO_LARGE", "The saved plan exceeds 64 KiB.")
    path, parents = _checked_path(raw_path)
    with _Directory(path.parent, parents) as directory:
        try:
            existing = directory.inspect(path.name)
        except FileNotFoundError:
            pass
        else:
            if _unsafe(existing):
                _fail("UNSAFE_PATH", "Symlinks and reparse paths are unsupported.")
            _fail("FILE_EXISTS", "The destination already exists; nothing was replaced.")
        temporary = ".atlas-new-world-" + secrets.token_hex(16) + ".tmp"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
        fd = directory.open(temporary, flags)
        identity = _identity(os.fstat(fd))
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(body)
                handle.flush()
                os.fsync(handle.fileno())
            _check_parents(parents)
            current = directory.inspect(temporary)
            if _unsafe(current) or _identity(current) != identity:
                _fail("UNSAFE_PATH", "Temporary-file ownership changed; publication refused.")
            try:
                directory.publish(temporary, path.name)
            except FileExistsError:
                _fail("FILE_EXISTS", "The destination already exists; nothing was replaced.")
        finally:
            directory.remove_owned(temporary, identity)
    return plan


def load_plan(raw_path):
    """Read at most 64 KiB, validate the stored binding, and never write."""
    path, parents = _checked_path(raw_path)
    with _Directory(path.parent, parents) as directory:
        info = directory.inspect(path.name)
        if _unsafe(info):
            _fail("UNSAFE_PATH", "Symlinks and reparse paths are unsupported.")
        if not stat.S_ISREG(info.st_mode):
            _fail("INVALID_PATH", "The input must be a regular file.")
        if info.st_size > MAX_INPUT_BYTES:
            _fail("INPUT_TOO_LARGE", "JSON input exceeds 64 KiB.")
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        flags |= getattr(os, "O_NONBLOCK", 0)
        fd = directory.open(path.name, flags)
        with os.fdopen(fd, "rb") as handle:
            opened = os.fstat(handle.fileno())
            if (_unsafe(opened) or not stat.S_ISREG(opened.st_mode)
                    or _identity(opened) != _identity(info)):
                _fail("UNSAFE_PATH", "The input file changed while opening.")
            record = _bounded_read(handle)
        _check_parents(parents)
    return validate_plan(record)


def response(argv, stdin):
    """Return the complete path-free machine response and process exit status."""
    try:
        if argv == ["describe"]:
            data = contract_description()
        elif argv == ["seed"]:
            data = {"seed": new_request()["seed"]}
        elif argv == ["prepare"]:
            data = resolve_request(_bounded_read(stdin))
        elif len(argv) == 3 and argv[0] in ("save", "load") and argv[1] == "--file":
            data = (save_plan(argv[2], _bounded_read(stdin)) if argv[0] == "save"
                    else load_plan(argv[2]))
        else:
            _fail("INVALID_ARGUMENTS", "Use describe, seed, prepare, save --file PATH or load --file PATH.")
        return {"schema": RESPONSE_SCHEMA, "status": "ok", "data": data}, 0
    except ContractError as error:
        code, message = error.code, str(error)
    except FileNotFoundError:
        code, message = "FILE_NOT_FOUND", "The file or parent directory does not exist."
    except FileExistsError:
        code, message = "FILE_EXISTS", "The destination already exists; nothing was replaced."
    except (OSError, ValueError, UnicodeError):
        code, message = "IO_ERROR", "The local file operation could not be completed."
    except Exception:
        code, message = "INTERNAL_ERROR", "The configuration command could not be completed."
    return {"schema": RESPONSE_SCHEMA, "status": "error", "error": {
        "code": code, "message": message,
    }}, 2


def main(argv=None):
    answer, status = response(list(sys.argv[1:] if argv is None else argv),
                              getattr(sys.stdin, "buffer", sys.stdin))
    sys.stdout.write(canonical_bytes(answer).decode("utf-8") + "\n")
    return status


if __name__ == "__main__":
    raise SystemExit(main())
