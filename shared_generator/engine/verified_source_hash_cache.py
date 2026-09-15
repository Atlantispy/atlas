"""Fail-safe cache for previously verified source-file SHA-256 values.

The cache is an optimisation, never an authority. A hit requires a matching
logical binding plus a Windows file identity and NTFS change-journal token.
If that strong token is unavailable, the source is byte-hashed instead of
trusting weak path, size, or timestamp metadata. Deep audits can always force
byte hashing.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import struct
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, BinaryIO, Callable, Mapping


SCHEMA = "diadem-verified-source-hash-cache-1.0"
REPARSE_POINT_ATTRIBUTE = 0x400
TokenProvider = Callable[[BinaryIO, Path], Mapping[str, Any] | None]


class SourceHashCacheError(RuntimeError):
    """Base error for source verification."""


class SourceHashMismatchError(SourceHashCacheError):
    """The source bytes do not match the declared authority digest."""


class SourceChangedDuringHashError(SourceHashCacheError):
    """The source identity or change-journal evidence changed during verification."""


@dataclass(frozen=True)
class VerificationResult:
    logical_id: str
    path: str
    sha256: str
    size_bytes: int
    cache_hit: bool
    bytes_hashed: int
    reason: str
    token_kind: str | None


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _valid_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def _resolved_regular_file(path: Path) -> Path:
    unresolved = Path(os.path.abspath(os.fspath(path.expanduser())))
    for component in (unresolved, *unresolved.parents):
        try:
            component_info = component.lstat()
        except FileNotFoundError:
            continue
        component_attributes = int(getattr(component_info, "st_file_attributes", 0))
        if stat.S_ISLNK(component_info.st_mode) or component_attributes & REPARSE_POINT_ATTRIBUTE:
            raise SourceHashCacheError(
                f"Source path must not traverse a symbolic link or reparse point: {component}"
            )
    candidate = unresolved.resolve(strict=True)
    info = candidate.stat()
    if not stat.S_ISREG(info.st_mode):
        raise SourceHashCacheError(f"Source is not a regular file: {candidate}")
    attributes = int(getattr(info, "st_file_attributes", 0))
    if candidate.is_symlink() or attributes & REPARSE_POINT_ATTRIBUTE:
        raise SourceHashCacheError(f"Source must not be a symbolic link or reparse point: {candidate}")
    return candidate


def _stream_state(stream: BinaryIO) -> dict[str, int]:
    info = os.fstat(stream.fileno())
    return {
        "size_bytes": int(info.st_size),
        "mtime_ns": int(info.st_mtime_ns),
        "ctime_ns": int(info.st_ctime_ns),
        "device": int(info.st_dev),
        "inode": int(info.st_ino),
    }


def _entry_key(*, logical_id: str, path: str, expected_sha256: str) -> str:
    return _sha256_bytes(
        _canonical_json_bytes(
            {
                "logical_id": logical_id,
                "path": path,
                "expected_sha256": expected_sha256,
            }
        )
    )


@lru_cache(maxsize=1)
def _windows_api() -> Mapping[str, Any] | None:
    if os.name != "nt":
        return None
    try:
        import ctypes
        import msvcrt
        from ctypes import wintypes

        class FileId128(ctypes.Structure):
            _fields_ = [("Identifier", ctypes.c_uint8 * 16)]

        class FileIdInfo(ctypes.Structure):
            _fields_ = [
                ("VolumeSerialNumber", ctypes.c_uint64),
                ("FileId", FileId128),
            ]

        class ReadFileUsnData(ctypes.Structure):
            _fields_ = [
                ("MinMajorVersion", ctypes.c_uint16),
                ("MaxMajorVersion", ctypes.c_uint16),
            ]

        class UsnJournalDataV0(ctypes.Structure):
            _fields_ = [
                ("UsnJournalID", ctypes.c_uint64),
                ("FirstUsn", ctypes.c_int64),
                ("NextUsn", ctypes.c_int64),
                ("LowestValidUsn", ctypes.c_int64),
                ("MaxUsn", ctypes.c_int64),
                ("MaximumSize", ctypes.c_uint64),
                ("AllocationDelta", ctypes.c_uint64),
            ]

        if (
            ctypes.sizeof(FileIdInfo) != 24
            or ctypes.sizeof(ReadFileUsnData) != 4
            or ctypes.sizeof(UsnJournalDataV0) != 56
        ):
            return None

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.GetFileInformationByHandleEx.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            wintypes.LPVOID,
            wintypes.DWORD,
        ]
        kernel32.GetFileInformationByHandleEx.restype = wintypes.BOOL
        kernel32.DeviceIoControl.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            wintypes.LPVOID,
            wintypes.DWORD,
            wintypes.LPVOID,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
            wintypes.LPVOID,
        ]
        kernel32.DeviceIoControl.restype = wintypes.BOOL
        kernel32.CreateFileW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.LPVOID,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.HANDLE,
        ]
        kernel32.CreateFileW.restype = wintypes.HANDLE
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        return {
            "ctypes": ctypes,
            "msvcrt": msvcrt,
            "wintypes": wintypes,
            "kernel32": kernel32,
            "FileIdInfo": FileIdInfo,
            "ReadFileUsnData": ReadFileUsnData,
            "UsnJournalDataV0": UsnJournalDataV0,
        }
    except (ImportError, AttributeError, OSError):
        return None


@contextmanager
def _locked_read_stream(path: Path):
    """Open a source for sequential reading while denying writes and replacement."""

    api = _windows_api()
    if api is None:
        with path.open("rb") as stream:
            yield stream
        return

    ctypes = api["ctypes"]
    kernel32 = api["kernel32"]
    invalid_handle = api["wintypes"].HANDLE(-1).value
    handle = invalid_handle
    for attempt in range(3):
        handle = kernel32.CreateFileW(
            str(path),
            0x80000000,
            0x00000001,
            None,
            3,
            0x00000080 | 0x08000000,
            None,
        )
        if handle != invalid_handle:
            break
        error = ctypes.get_last_error()
        if error not in {32, 33} or attempt == 2:
            raise SourceHashCacheError(
                f"Could not acquire stable read handle for {path}: {ctypes.WinError(error)}"
            )
        time.sleep(0.05 * (attempt + 1))
    try:
        descriptor = api["msvcrt"].open_osfhandle(
            handle,
            os.O_RDONLY | getattr(os, "O_BINARY", 0),
        )
    except OSError:
        kernel32.CloseHandle(handle)
        raise
    with os.fdopen(descriptor, "rb", closefd=True) as stream:
        yield stream


def windows_file_change_token(stream: BinaryIO, path: Path) -> Mapping[str, Any] | None:
    """Read file identity, current file USN, and journal epoch from one handle."""

    api = _windows_api()
    if api is None:
        return None
    ctypes = api["ctypes"]
    wintypes = api["wintypes"]
    kernel32 = api["kernel32"]
    try:
        handle = wintypes.HANDLE(api["msvcrt"].get_osfhandle(stream.fileno()))
        identity = api["FileIdInfo"]()
        if not kernel32.GetFileInformationByHandleEx(
            handle,
            18,
            ctypes.byref(identity),
            ctypes.sizeof(identity),
        ):
            return None

        def journal_id() -> int | None:
            output = ctypes.create_string_buffer(128)
            returned = wintypes.DWORD()
            if not kernel32.DeviceIoControl(
                handle,
                0x000900F4,
                None,
                0,
                output,
                ctypes.sizeof(output),
                ctypes.byref(returned),
                None,
            ) or returned.value < 56:
                return None
            prefix = api["UsnJournalDataV0"].from_buffer_copy(output.raw[:56])
            return int(prefix.UsnJournalID)

        epoch_before = journal_id()
        if epoch_before is None:
            return None
        request = api["ReadFileUsnData"](2, 3)
        output = ctypes.create_string_buffer(64 * 1024)
        returned = wintypes.DWORD()
        if not kernel32.DeviceIoControl(
            handle,
            0x000900EB,
            ctypes.byref(request),
            ctypes.sizeof(request),
            output,
            ctypes.sizeof(output),
            ctypes.byref(returned),
            None,
        ):
            return None
        epoch_after = journal_id()
        if epoch_after is None or epoch_after != epoch_before:
            return None

        record_length, major, _minor = struct.unpack_from("<IHH", output.raw, 0)
        usn_offset = {2: 24, 3: 40}.get(major)
        if usn_offset is None or returned.value < usn_offset + 8 or record_length > returned.value:
            return None
        file_id = bytes(identity.FileId.Identifier)
        if not any(file_id) or epoch_after == 0:
            return None
        if major == 2:
            record_id = struct.unpack_from("<Q", output.raw, 8)[0]
            if record_id != int.from_bytes(file_id[:8], "little") or any(file_id[8:]):
                return None
        elif output.raw[8:24] != file_id:
            return None
        file_usn = struct.unpack_from("<q", output.raw, usn_offset)[0]
        if file_usn < 0:
            return None
        state = _stream_state(stream)
        return {
            "kind": "windows_ntfs_file_id_usn_v1",
            "volume_serial": f"{identity.VolumeSerialNumber:016x}",
            "file_id_128": file_id.hex(),
            "journal_id": f"{epoch_after:016x}",
            "file_usn": int(file_usn),
            "size_bytes": state["size_bytes"],
        }
    except (OSError, ValueError, struct.error):
        return None


class VerifiedSourceHashCache:
    """Reuse digests only while strong file-change evidence is unchanged."""

    def __init__(
        self,
        cache_path: Path,
        *,
        namespace: str,
        chunk_size: int = 8 * 1024 * 1024,
        token_provider: TokenProvider | None = None,
    ) -> None:
        if not namespace:
            raise ValueError("Cache namespace must be non-empty")
        if chunk_size <= 0:
            raise ValueError("chunk_size must be positive")
        self.cache_path = cache_path.expanduser().resolve()
        self.namespace = namespace
        self.chunk_size = chunk_size
        self._token_provider = token_provider or windows_file_change_token
        self._entries: dict[str, dict[str, Any]] = {}
        self._rechecks: dict[str, dict[str, Any]] = {}
        self._dirty = False
        self.load_status = "absent"
        self.hits = 0
        self.misses = 0
        self.files_hashed = 0
        self.bytes_hashed = 0
        self.forced_rehashes = 0
        self.no_strong_token_hashes = 0
        self.write_status = "not_needed"
        self._load()

    def _load(self) -> None:
        if not self.cache_path.is_file():
            return
        try:
            envelope = json.loads(self.cache_path.read_text(encoding="utf-8"))
            if not isinstance(envelope, Mapping) or envelope.get("schema") != SCHEMA:
                raise ValueError("unsupported schema")
            payload = envelope.get("payload")
            if not isinstance(payload, Mapping):
                raise ValueError("missing payload")
            if envelope.get("payload_sha256") != _sha256_bytes(_canonical_json_bytes(payload)):
                raise ValueError("payload integrity mismatch")
            if payload.get("namespace") != self.namespace:
                self.load_status = "namespace_mismatch"
                return
            entries = payload.get("entries")
            if not isinstance(entries, dict):
                raise ValueError("entries is not an object")
            self._entries = {
                str(key): dict(value)
                for key, value in entries.items()
                if isinstance(key, str) and isinstance(value, Mapping)
            }
            self.load_status = "loaded"
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError, TypeError):
            self._entries = {}
            self.load_status = "invalid_ignored"

    def _token(self, stream: BinaryIO, path: Path) -> Mapping[str, Any] | None:
        try:
            value = self._token_provider(stream, path)
        except (OSError, RuntimeError, ValueError):
            return None
        return dict(value) if isinstance(value, Mapping) else None

    def verify(
        self,
        *,
        logical_id: str,
        path: Path,
        expected_sha256: str,
        force_rehash: bool = False,
    ) -> VerificationResult:
        expected = expected_sha256.lower()
        if not logical_id:
            raise ValueError("logical_id must be non-empty")
        if not _valid_sha256(expected):
            raise ValueError("expected_sha256 must be a lowercase SHA-256 digest")

        resolved = _resolved_regular_file(path)
        resolved_text = str(resolved)
        key = _entry_key(
            logical_id=logical_id,
            path=resolved_text,
            expected_sha256=expected,
        )
        entry = self._entries.get(key)

        with _locked_read_stream(resolved) as stream:
            state_before = _stream_state(stream)
            token_before = self._token(stream, resolved)
            binding = {
                "logical_id": logical_id,
                "path": resolved_text,
                "expected_sha256": expected,
                "verified_sha256": expected,
                "file_state": state_before,
                "change_token": token_before,
            }
            if not force_rehash and token_before is not None and entry == binding:
                state_after = _stream_state(stream)
                token_after = self._token(stream, resolved)
                if state_after == state_before and token_after == token_before:
                    self.hits += 1
                    self._rechecks[key] = binding
                    return VerificationResult(
                        logical_id=logical_id,
                        path=resolved_text,
                        sha256=expected,
                        size_bytes=state_after["size_bytes"],
                        cache_hit=True,
                        bytes_hashed=0,
                        reason="verified_ntfs_change_token_match",
                        token_kind=str(token_after.get("kind")),
                    )

            self.misses += 1
            if force_rehash:
                self.forced_rehashes += 1
            stream.seek(0)
            digest = hashlib.sha256()
            for chunk in iter(lambda: stream.read(self.chunk_size), b""):
                digest.update(chunk)
            state_after = _stream_state(stream)
            token_after = self._token(stream, resolved)

        if state_before != state_after or token_before != token_after:
            raise SourceChangedDuringHashError(f"Source changed while being hashed: {resolved}")
        actual = digest.hexdigest()
        self.files_hashed += 1
        self.bytes_hashed += state_after["size_bytes"]
        if actual != expected:
            raise SourceHashMismatchError(
                f"Source hash mismatch for {logical_id}: {actual} != {expected} ({resolved})"
            )

        if token_after is not None:
            with _locked_read_stream(resolved) as rebound:
                rebound_state = _stream_state(rebound)
                rebound_token = self._token(rebound, resolved)
            if rebound_state != state_after or rebound_token != token_after:
                raise SourceChangedDuringHashError(f"Source path rebound after hashing: {resolved}")
            binding = {
                "logical_id": logical_id,
                "path": resolved_text,
                "expected_sha256": expected,
                "verified_sha256": actual,
                "file_state": state_after,
                "change_token": dict(token_after),
            }
            self._entries[key] = binding
            self._rechecks[key] = binding
            self._dirty = True
            reason = "forced_byte_hash" if force_rehash else "cache_miss_byte_hash"
            token_kind = str(token_after.get("kind"))
        else:
            self.no_strong_token_hashes += 1
            reason = "byte_hash_no_strong_change_token"
            token_kind = None

        return VerificationResult(
            logical_id=logical_id,
            path=resolved_text,
            sha256=actual,
            size_bytes=state_after["size_bytes"],
            cache_hit=False,
            bytes_hashed=state_after["size_bytes"],
            reason=reason,
            token_kind=token_kind,
        )

    def _verify_rechecks(self) -> None:
        for key, expected in sorted(self._rechecks.items()):
            path = Path(expected["path"])
            with _locked_read_stream(path) as stream:
                observed_state = _stream_state(stream)
                observed_token = self._token(stream, path)
            if observed_state != expected["file_state"] or observed_token != expected["change_token"]:
                raise SourceChangedDuringHashError(
                    f"Source changed before cache commit: {path} ({key})"
                )

    def flush(self) -> None:
        self._verify_rechecks()
        if not self._dirty:
            return
        payload = {
            "namespace": self.namespace,
            "entries": dict(sorted(self._entries.items())),
        }
        envelope = {
            "schema": SCHEMA,
            "written_at_utc": datetime.now(UTC).replace(microsecond=0).isoformat(),
            "payload_sha256": _sha256_bytes(_canonical_json_bytes(payload)),
            "payload": payload,
        }
        encoded = _canonical_json_bytes(envelope) + b"\n"
        temporary = self.cache_path.with_name(
            f".{self.cache_path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
        )
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            with temporary.open("xb") as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.cache_path)
        except OSError:
            self.write_status = "write_failed"
            return
        finally:
            try:
                temporary.unlink()
            except OSError:
                pass
        self._dirty = False
        self.write_status = "committed"

    def report(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA,
            "cache_path": str(self.cache_path),
            "namespace": self.namespace,
            "load_status": self.load_status,
            "entry_count": len(self._entries),
            "hits": self.hits,
            "misses": self.misses,
            "files_hashed": self.files_hashed,
            "bytes_hashed": self.bytes_hashed,
            "forced_rehashes": self.forced_rehashes,
            "no_strong_token_hashes": self.no_strong_token_hashes,
            "token_kind": "windows_ntfs_file_id_usn_v1" if self._rechecks else None,
            "write_status": self.write_status,
            "dirty": self._dirty,
        }


__all__ = [
    "SCHEMA",
    "SourceChangedDuringHashError",
    "SourceHashCacheError",
    "SourceHashMismatchError",
    "VerificationResult",
    "VerifiedSourceHashCache",
    "windows_file_change_token",
]
