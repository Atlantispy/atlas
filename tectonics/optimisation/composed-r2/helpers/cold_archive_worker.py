"""Bounded cold export worker. Its parent supplies the aggregate Windows Job cap.

CLI: cold_archive_worker.py REQUEST_JSON RESULT_JSON. No active storage is changed.
The only recursive removals are trees this invocation created in its new destination.
"""
from __future__ import annotations

from contextlib import contextmanager
import ctypes
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import threading
import time

TAR_SHA256 = "a3ac62fd4cdf619a7c53f71ca3fe5fb42f72020975670ff29afe3603f6416a8e"
MANIFEST_SCHEMA = "atlas.cold-bundle.v1"
RECEIPT_SCHEMA = "atlas.cold-bundle-receipt.v1"
KINDS = {"completed-diagnostics", "cold-export"}
BLOCK = 64 * 1024
MAX_FILES = 256
MAX_FILE = 64 * 1024 * 1024
MAX_TOTAL = 256 * 1024 * 1024
MAX_ARCHIVE = MAX_TOTAL + 2 * 1024 * 1024
MAX_JSON = 512 * 1024
RECEIPT_ALLOWANCE = 16 * 1024
REPARSE = 0x400
CONTROL_NAMES = {
    "catalog.json", "catalogue.json", "checkpoint.json", "checkpoints.json",
    "state.json", "resume.json", "restart.json", "control.json", "lease.json",
    "lock.json", "active.json", "runtime.json", "head", "current", "lock",
}
CONTROL_DIRS = {".git", ".r44-env", "__pycache__", "active", "checkpoints"}
RESERVED = re.compile(r"^(con|prn|aux|nul|conin\$|conout\$|com[1-9]|lpt[1-9])(?:\..*)?$", re.I)
HEX = re.compile(r"^[0-9a-f]{64}$")


def require(ok, message):
    if not ok:
        raise ValueError(message)


def json_bytes(value):
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")


def number(value, name, maximum):
    require(type(value) in (int, float) and math.isfinite(value) and 0 < value <= maximum,
            "invalid " + name)
    return float(value)


def safe_name(name):
    require(isinstance(name, str) and 0 < len(name) <= 100 and name.isascii(),
            "member names must be 1..100 ASCII bytes")
    require(not any(ord(c) < 32 or ord(c) == 127 or c in '\\:<>\"|?*' for c in name),
            "unsafe member character")
    parts = name.split("/")
    require(not any(p.startswith(("-", "@")) for p in parts), "unsupported archive filename")
    require(all(p not in ("", ".", "..") and p == p.rstrip(" .") and not RESERVED.fullmatch(p)
                for p in parts), "unsafe member path")
    lower = [p.lower() for p in parts]
    require(not any(p in CONTROL_DIRS for p in lower), "active/control directory refused")
    leaf = lower[-1]
    require(leaf not in CONTROL_NAMES, "active/control file refused")
    require(not re.search(r"(?:\.(?:sqlite\d*|db\d*|wal|shm|lock)|-(?:wal|shm|journal))$", leaf),
            "database or active lock data refused")
    return name


def names_checked(names):
    require(isinstance(names, list) and 1 <= len(names) <= MAX_FILES, "invalid explicit file count")
    names = [safe_name(name) for name in names]
    folded = [name.casefold() for name in names]
    require(len(set(folded)) == len(folded), "duplicate or case-alias member")
    all_names = set(folded)
    require(not any("/".join(name.split("/")[:i]) in all_names
                    for name in folded for i in range(1, len(name.split("/")))),
            "file/directory member collision")
    return names


def absolute(value):
    require(isinstance(value, str) and Path(value).is_absolute(), "absolute path required")
    return Path(os.path.abspath(value))


def checked_path(path, *, regular=False, directory=False, allow_hardlinks=False):
    """Check every existing ancestor without resolving away a reparse point."""
    path = Path(path)
    for component in reversed((path, *path.parents)):
        info = component.lstat()
        require(not stat.S_ISLNK(info.st_mode) and not (getattr(info, "st_file_attributes", 0) & REPARSE),
                "symlink or reparse point refused")
        if component != path:
            require(stat.S_ISDIR(info.st_mode), "non-directory path ancestor")
    if regular:
        require(stat.S_ISREG(info.st_mode) and (allow_hardlinks or info.st_nlink == 1),
                "non-regular or hardlinked file refused")
    if directory:
        require(stat.S_ISDIR(info.st_mode), "directory required")
    return info


def identity(info):
    # On this Windows/Python combination stat exposes ctime as birth time,
    # while fstat exposes change time. The explicit birthtime field agrees.
    created = getattr(info, 'st_birthtime_ns', info.st_ctime_ns)
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, created,
            info.st_nlink, getattr(info, "st_file_attributes", 0))


@contextmanager
def locked_binary(path, *, allow_hardlinks=False):
    """Windows read handle denies replacement/writes while tar also reads it."""
    checked_path(path, regular=True, allow_hardlinks=allow_hardlinks)
    if os.name == "nt":
        import msvcrt
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        create = kernel.CreateFileW
        create.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                           wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE)
        create.restype = wintypes.HANDLE
        handle = create(str(path), 0x80000000, 1, None, 3, 0x08200000, None)
        require(handle != ctypes.c_void_p(-1).value, "cannot lock input against write/replacement")
        try:
            fd = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
        except BaseException:
            kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
            kernel.CloseHandle(handle)
            raise
        file = os.fdopen(fd, "rb")
    else:
        file = open(path, "rb")
    try:
        info = os.fstat(file.fileno())
        require(stat.S_ISREG(info.st_mode) and (allow_hardlinks or info.st_nlink == 1), "invalid locked file")
        require(identity(info) == identity(checked_path(path, regular=True, allow_hardlinks=allow_hardlinks)),
                "input identity changed")
        yield file
        require(identity(info) == identity(os.fstat(file.fileno())) ==
                identity(checked_path(path, regular=True, allow_hardlinks=allow_hardlinks)),
                "input changed during operation")
    finally:
        file.close()


class Work:
    def __init__(self, request):
        self.start = time.monotonic()
        self.deadline = self.start + number(request.get("max_seconds", 30), "max_seconds", 30)
        self.request = request

    def remaining(self):
        remaining = self.deadline - time.monotonic()
        require(remaining > 0, "cold operation time limit exceeded")
        return remaining

    def digest(self, file, expected):
        require(0 <= expected <= MAX_ARCHIVE, "hash input size exceeds bound")
        digest, total = hashlib.sha256(), 0
        while True:
            self.remaining()
            block = file.read(min(BLOCK, expected - total + 1))
            if not block:
                break
            total += len(block)
            require(total <= expected, "input grew beyond declared bound")
            digest.update(block)
        require(total == expected, "input length changed")
        return digest.hexdigest()

    def copy(self, source, target, expected, expected_hash=None):
        require(0 <= expected <= MAX_FILE, "file size exceeds bound")
        checked_path(target.parent, directory=True)
        with locked_binary(source) as src:
            require(os.fstat(src.fileno()).st_size == expected, "source size changed before copy")
            digest, total = hashlib.sha256(), 0
            with target.open("xb") as dst:
                while True:
                    self.remaining()
                    block = src.read(min(BLOCK, expected - total + 1))
                    if not block:
                        break
                    total += len(block)
                    require(total <= expected, "source exceeded declared size")
                    dst.write(block)
                    digest.update(block)
            require(total == expected, "source truncated during copy")
            result = digest.hexdigest()
            require(expected_hash is None or result == expected_hash, "content hash mismatch")
        return result


class Native:
    """Bound stderr and wall time, with the parent's inherited aggregate Job cap."""
    def __init__(self, argv, work, temporary, stream=False):
        self.work, self.errors, self.exceeded, self.timed_out = work, bytearray(), False, False
        remaining = work.remaining()
        env = {key: os.environ[key] for key in ("SystemRoot", "WINDIR") if key in os.environ}
        env.update(TEMP=str(temporary), TMP=str(temporary), LC_ALL="C")
        self.child = subprocess.Popen(argv, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE if stream else subprocess.DEVNULL, stderr=subprocess.PIPE,
            cwd=temporary, env=env, creationflags=0x08000000 if os.name == "nt" else 0)
        self.thread = threading.Thread(target=self._stderr, daemon=True)
        self.timer = threading.Timer(remaining, self._timeout)
        self.thread.start()
        self.timer.start()

    def _kill(self):
        if self.child.poll() is None:
            try:
                self.child.kill()
            except OSError:
                pass

    def _timeout(self):
        self.timed_out = True
        self._kill()

    def _stderr(self):
        while block := self.child.stderr.read(4096):
            if len(self.errors) + len(block) > BLOCK:
                self.exceeded = True
                self._kill()
                break
            self.errors.extend(block)

    def finish(self):
        code = self.child.wait(timeout=self.work.remaining())
        self.thread.join(timeout=self.work.remaining())
        require(not self.thread.is_alive() and not self.exceeded, "native stderr exceeded bound")
        require(not self.timed_out, "native operation timed out")
        require(code == 0 and not self.errors,
                "native archive failure: " + self.errors.decode("utf-8", "replace")[:1024])

    def close(self):
        self.timer.cancel()
        self._kill()
        self.child.wait(timeout=5)
        if self.child.stdout:
            self.child.stdout.close()
        self.thread.join(timeout=5)
        self.child.stderr.close()


def fresh_directory(value):
    path = absolute(value)
    checked_path(path.parent, directory=True)
    require(not path.exists() and not path.is_symlink(), "destination must be new")
    path.mkdir()
    checked_path(path, directory=True)
    return path


def parent_for(root, name):
    target = root.joinpath(*safe_name(name).split("/"))
    target.parent.mkdir(parents=True, exist_ok=True)
    checked_path(target.parent, directory=True)
    require(target.is_relative_to(root), "target escaped private destination")
    return target


def remove_private_tree(root, name):
    target = root / name
    require(target.parent == root and target.resolve().is_relative_to(root.resolve()),
            "cleanup target escaped private destination")
    checked_path(target, directory=True)
    for directory, dirs, files in os.walk(target, followlinks=False):
        for entry in dirs + files:
            checked_path(Path(directory) / entry)
    shutil.rmtree(target)


def validate_manifest(manifest):
    require(isinstance(manifest, dict) and manifest.get("schema") == MANIFEST_SCHEMA,
            "invalid manifest schema")
    require(manifest.get("kind") in KINDS, "invalid cold bundle kind")
    entries = manifest.get("files")
    require(isinstance(entries, list) and all(isinstance(e, dict) for e in entries), "invalid manifest files")
    names_checked([e.get("path") for e in entries])
    for entry in entries:
        require(set(entry) == {"path", "size", "sha256"}, "invalid manifest entry fields")
        require(type(entry["size"]) is int and 0 <= entry["size"] <= MAX_FILE, "invalid member size")
        require(isinstance(entry["sha256"], str) and HEX.fullmatch(entry["sha256"]), "invalid member hash")
    total = sum(e["size"] for e in entries)
    require(total <= MAX_TOTAL and type(manifest.get("total_bytes")) is int and
            manifest["total_bytes"] == total, "invalid manifest total")
    return entries, total


def restore_stream(work, tar, archive, destination, entries):
    """Read only fixed ustar records; never call tar extraction or extractall."""
    limit = 1024 + sum(512 + ((e["size"] + 511) // 512) * 512 for e in entries)
    command = [str(tar), "-c", "-P", "--format=ustar", "-b", "1", "-f", "-", "@" + str(archive)]
    native = Native(command, work, destination, stream=True)
    consumed = 0

    def read_exact(size):
        nonlocal consumed
        require(0 <= size <= BLOCK and consumed + size <= limit, "raw tar stream bound exceeded")
        data = bytearray()
        while len(data) < size:
            work.remaining()
            part = native.child.stdout.read(size - len(data))
            require(part, "truncated native tar stream")
            data.extend(part)
        consumed += size
        return bytes(data)

    try:
        for entry in entries:
            header = read_exact(512)
            require(header[257:265] == b"ustar\x0000", "non-ustar header refused")
            member = tarfile.TarInfo.frombuf(header, "ascii", "strict")
            require(member.type in (tarfile.REGTYPE, tarfile.AREGTYPE) and not member.linkname,
                    "non-regular archive member refused")
            require(safe_name(member.name) == entry["path"] and member.size == entry["size"],
                    "archive member order/name/size differs from manifest")
            target = parent_for(destination, entry["path"])
            digest = hashlib.sha256()
            with target.open("xb") as output:
                left = member.size
                while left:
                    block = read_exact(min(BLOCK, left))
                    output.write(block)
                    digest.update(block)
                    left -= len(block)
            require(digest.hexdigest() == entry["sha256"], "restored member hash mismatch")
            padding = (-member.size) % 512
            require(read_exact(padding) == bytes(padding), "nonzero tar padding")
        require(read_exact(512) == bytes(512) and read_exact(512) == bytes(512), "invalid tar end markers")
        work.remaining()
        require(native.child.stdout.read(1) == b"", "unexpected trailing tar stream bytes")
        require(consumed == limit, "raw tar stream length mismatch")
        native.finish()
    finally:
        native.close()


def finalise(work, tar):
    request = work.request
    kind = request.get("kind")
    require(kind in KINDS, "invalid cold bundle kind")
    source = absolute(request.get("source_root"))
    checked_path(source, directory=True)
    names = names_checked(request.get("files"))
    candidates = []
    for name in names:
        info = checked_path(source.joinpath(*name.split("/")), regular=True)
        require(0 <= info.st_size <= MAX_FILE, "source file exceeds bound")
        candidates.append((name, info.st_size, identity(info)))
    raw = sum(size for _, size, _ in candidates)
    require(raw <= MAX_TOTAL, "source total exceeds bound")
    ratio_limit = number(request.get("ratio_limit", .8), "ratio_limit", .8)
    pack_budget = number(request.get("max_pack_seconds", 2 + raw / (16 * 1024 * 1024)),
                         "max_pack_seconds", 2 + raw / (16 * 1024 * 1024))
    restore_budget = number(request.get("max_restore_seconds", 1 + raw / (64 * 1024 * 1024)),
                            "max_restore_seconds", 1 + raw / (64 * 1024 * 1024))
    destination = fresh_directory(request.get("destination"))
    data = destination / "data"
    data.mkdir()
    started = time.monotonic()
    entries = []
    for name, size, before in candidates:
        original = source.joinpath(*name.split("/"))
        require(identity(checked_path(original, regular=True)) == before, "source changed before copy")
        sha = work.copy(original, parent_for(data, name), size)
        require(identity(checked_path(original, regular=True)) == before, "source changed after copy")
        entries.append({"path": name, "size": size, "sha256": sha})
    copy_seconds = time.monotonic() - started
    manifest = {"schema": MANIFEST_SCHEMA, "kind": kind, "files": entries, "total_bytes": raw}
    encoded_manifest = json_bytes(manifest)
    (destination / "manifest.json").write_bytes(encoded_manifest)
    archive = destination / "bundle.tar.zst"
    chosen, reason, archive_hash, archive_bytes = False, "below_minimum_raw_bytes", None, 0
    pack_seconds = restore_seconds = None
    if len(names) < 2:
        reason = "single_file_does_not_need_tar_packaging"
    if raw >= BLOCK and len(names) >= 2:
        file_list = destination / ".files.nul"
        file_list.write_bytes(b"\0".join(name.encode("ascii") for name in names) + b"\0")
        command = [str(tar), "-c", "--zstd", "--options", "zstd:compression-level=3", "--format=ustar",
                   "--no-recursion", "--no-acls", "--no-xattrs", "--no-fflags", "--no-mac-metadata",
                   "--no-read-sparse", "--uid", "0", "--gid", "0", "--uname", "root", "--gname", "root",
                   "-f", str(archive), "-C", str(data), "--null", "-T", str(file_list)]
        started = time.monotonic()
        native = Native(command, work, destination)
        try:
            native.finish()
        finally:
            native.close()
        pack_seconds = time.monotonic() - started
        file_list.unlink()
        archive_bytes = checked_path(archive, regular=True).st_size
        require(0 < archive_bytes <= MAX_ARCHIVE, "archive exceeds bound")
        verification = destination / ".verify"
        verification.mkdir()
        with locked_binary(archive) as compressed:
            require(compressed.read(4) == bytes.fromhex("28b52ffd"), "archive is not zstd")
            compressed.seek(0)
            archive_hash = work.digest(compressed, archive_bytes)
            started = time.monotonic()
            restore_stream(work, tar, archive, verification, entries)
            restore_seconds = time.monotonic() - started
        remove_private_tree(destination, ".verify")
        # The parent adds Job measurements to the receipt. Reserve a bounded
        # metadata allowance here so routing does not rely on ignoring them.
        metadata_allowance = len(encoded_manifest) + RECEIPT_ALLOWANCE
        if (archive_bytes + metadata_allowance) / (raw + metadata_allowance) > ratio_limit:
            reason = "insufficient_size_reduction"
        elif pack_seconds > pack_budget:
            reason = "pack_time_budget_exceeded"
        elif restore_seconds > restore_budget:
            reason = "restore_time_budget_exceeded"
        else:
            chosen, reason = True, "size_and_time_budgets_passed"
        if chosen:
            remove_private_tree(destination, "data")
        else:
            archive.unlink()
    payload_bytes = archive_bytes if chosen else raw
    receipt = {
        "schema": RECEIPT_SCHEMA, "selected_format": "tar.zst" if chosen else "directory",
        "reason": reason, "kind": kind, "manifest_sha256": hashlib.sha256(encoded_manifest).hexdigest(),
        "archive_sha256": archive_hash if chosen else None, "raw_bytes": raw, "stored_bytes": 0,
        "measurements": {"copy_seconds": copy_seconds, "pack_seconds": pack_seconds,
                         "restore_seconds": restore_seconds, "candidate_archive_bytes": archive_bytes or None},
        "temporary_peak_bytes": 3 * raw + archive_bytes + len(encoded_manifest),
        "temporary_peak_bytes_basis": "conservative logical-file-byte estimate: source + private data + archive + verification + manifest; excludes runtime and filesystem allocation overhead",
        "policy": {"minimum_raw_bytes": BLOCK, "minimum_archive_files": 2, "ratio_limit": ratio_limit, "max_pack_seconds": pack_budget,
                   "max_restore_seconds": restore_budget, "max_files": MAX_FILES, "max_file_bytes": MAX_FILE,
                   "max_total_bytes": MAX_TOTAL, "tar_sha256": TAR_SHA256, "zstd_level": 3, "codec_workers": 0},
    }
    receipt["policy"]["receipt_bytes_allowance_for_ratio"] = RECEIPT_ALLOWANCE
    receipt["policy"]["ratio_basis"] = "archive or plain data, plus exact manifest bytes and conservative receipt allowance"
    for _ in range(8):
        total = payload_bytes + len(encoded_manifest) + len(json_bytes(receipt))
        if receipt["stored_bytes"] == total:
            break
        receipt["stored_bytes"] = total
    else:
        raise ValueError("receipt size did not converge")
    require(len(json_bytes(receipt)) <= RECEIPT_ALLOWANCE, "receipt exceeds routing metadata allowance")
    (destination / "receipt.json").write_bytes(json_bytes(receipt))
    work.remaining()
    return {"status": "ok", "receipt": receipt, "manifest": manifest}


def restore(work, tar):
    request = work.request
    manifest, receipt = request.get("manifest"), request.get("receipt")
    entries, raw = validate_manifest(manifest)
    require(isinstance(receipt, dict) and receipt.get("schema") == RECEIPT_SCHEMA and
            receipt.get("kind") == manifest["kind"] and receipt.get("raw_bytes") == raw,
            "invalid trusted receipt")
    require(receipt.get("manifest_sha256") == hashlib.sha256(json_bytes(manifest)).hexdigest(),
            "trusted manifest identity mismatch")
    source = absolute(request.get("source_root"))
    checked_path(source, directory=True)
    with locked_binary(source / "manifest.json") as file:
        size = os.fstat(file.fileno()).st_size
        require(size <= MAX_JSON and work.digest(file, size) == receipt["manifest_sha256"],
                "stored manifest identity mismatch")
    destination = fresh_directory(request.get("destination"))
    selected = receipt.get("selected_format")
    if selected == "tar.zst":
        sha = receipt.get("archive_sha256")
        require(isinstance(sha, str) and HEX.fullmatch(sha), "invalid trusted archive hash")
        archive = source / "bundle.tar.zst"
        with locked_binary(archive) as compressed:
            size = os.fstat(compressed.fileno()).st_size
            require(0 < size <= MAX_ARCHIVE and compressed.read(4) == bytes.fromhex("28b52ffd"),
                    "invalid archive size or magic")
            compressed.seek(0)
            require(work.digest(compressed, size) == sha, "compressed archive identity mismatch")
            restore_stream(work, tar, archive, destination, entries)
    elif selected == "directory":
        require(receipt.get("archive_sha256") is None, "unexpected directory archive identity")
        for entry in entries:
            original = source / "data" / entry["path"]
            work.copy(original, parent_for(destination, entry["path"]), entry["size"], entry["sha256"])
    else:
        raise ValueError("unsupported cold bundle format")
    work.remaining()
    return {"status": "ok", "files": len(entries), "total_bytes": raw}


def execute(request):
    require(isinstance(request, dict), "request must be an object")
    work = Work(request)
    tar = absolute(request.get("tar_executable"))
    require(os.path.normcase(str(tar)) == os.path.normcase(r"C:\Windows\System32\tar.exe"),
            "only the pinned installed archive executable is supported")
    with locked_binary(tar, allow_hardlinks=True) as executable:
        size = os.fstat(executable.fileno()).st_size
        require(size <= 4 * 1024 * 1024 and work.digest(executable, size) == TAR_SHA256,
                "installed archive executable identity mismatch")
        action = request.get("action")
        if action == "finalise":
            return finalise(work, tar)
        if action == "restore":
            return restore(work, tar)
        raise ValueError("unsupported cold action")


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 2:
        return 2
    try:
        request_path = absolute(argv[0])
        with locked_binary(request_path) as file:
            encoded = file.read(MAX_JSON + 1)
        require(len(encoded) <= MAX_JSON, "request JSON exceeds bound")
        result = execute(json.loads(encoded))
        status = 0
    except Exception as error:
        result, status = {"status": "error", "error": (type(error).__name__ + ": " + str(error))[:2048]}, 1
    try:
        output = absolute(argv[1])
        checked_path(output.parent, directory=True)
        encoded = json_bytes(result)
        require(len(encoded) <= MAX_JSON, "result JSON exceeds bound")
        with output.open("xb") as file:
            file.write(encoded)
    except Exception:
        return 2
    return status


if __name__ == "__main__":
    raise SystemExit(main())
