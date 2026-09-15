"""Bounded, authenticated, local result reuse without changing scientific results.

The caller must derive ``namespace`` from the exact code/runtime identity and
``key`` from the complete invocation, including every relevant input and seed.
This module authenticates saved results; it cannot establish those identities or
prove that a producer's calculation was correct. Required final scientific QA is
not replaced by cache hits.

A dedicated absolute root is owned by this store. It contains one 32-byte key,
one process-lock byte and SHA-named namespace/record paths. The key is created
exclusively, never regenerated over existing records, and never returned in
statistics. Authentication protects against record corruption or replacement by
someone who does not possess the key. It is NOT a security boundary against the
local owner, an attacker possessing the key, or hostile concurrent replacement
of the root's ancestor directories. Static links/reparse points and hard-linked
files are rejected; use a local, access-controlled filesystem supporting locks
and atomic same-directory replacement. There is no automatic eviction.
"""

from __future__ import annotations

from contextlib import contextmanager
import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import re
import secrets
import stat
import tempfile
import threading
import time


MAX_RECORD_BYTES = 8 * 1024 * 1024
DEFAULT_MAX_BYTES = 256 * 1024 * 1024
SCHEMA = "diadem.runtime-cache.r12"
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_KEY_NAME = ".cache-key"
_LOCK_NAME = ".store.lock"
_LOCK_WAIT_SECONDS = 10.0
_MAX_DEPTH = 128


class CacheError(ValueError):
    """Unsafe, incompatible or corrupt cache state; never a valid cache miss."""


class CacheConflictError(CacheError):
    """An identical invocation identity produced different result bytes."""


class _Oversize(CacheError):
    pass


def _sha(value: str, label: str) -> str:
    if type(value) is not str or _SHA.fullmatch(value) is None:
        raise CacheError(label + " must be a lowercase SHA-256 identity")
    return value


def _check_json(value, depth=0, active=None):
    if depth > _MAX_DEPTH:
        raise CacheError("JSON nesting limit exceeded")
    kind = type(value)
    if value is None or kind in (str, int, bool):
        return
    if kind is float:
        if not math.isfinite(value):
            raise CacheError("Nonfinite JSON number")
        return
    if kind not in (dict, list):
        raise CacheError("Only exact JSON value types are supported")
    if active is None:
        active = set()
    identity = id(value)
    if identity in active:
        raise CacheError("Cyclic JSON value")
    active.add(identity)
    try:
        if kind is dict:
            for key, item in value.items():
                if type(key) is not str:
                    raise CacheError("JSON object keys must be strings")
                _check_json(item, depth + 1, active)
        else:
            for item in value:
                _check_json(item, depth + 1, active)
    finally:
        active.remove(identity)


def _encode(value, limit=MAX_RECORD_BYTES) -> bytes:
    _check_json(value)
    result = bytearray()
    try:
        encoder = json.JSONEncoder(ensure_ascii=False, allow_nan=False,
                                   sort_keys=True, separators=(",", ":"))
        for fragment in encoder.iterencode(value):
            chunk = fragment.encode("utf-8")
            if len(result) + len(chunk) > limit:
                raise _Oversize("Cache record byte limit exceeded")
            result.extend(chunk)
    except _Oversize:
        raise
    except (TypeError, ValueError, UnicodeError, OverflowError, RecursionError) as exc:
        raise CacheError("Invalid JSON value") from exc
    return bytes(result)


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise CacheError("Duplicate JSON object key")
        result[key] = value
    return result


def _constant(_value):
    raise CacheError("Nonfinite JSON number")


def _decode(raw: bytes):
    try:
        result = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs,
                            parse_constant=_constant)
        _check_json(result)
    except CacheError:
        raise
    except (UnicodeError, ValueError, RecursionError, OverflowError) as exc:
        raise CacheError("Invalid saved JSON") from exc
    return result


def _check_path(path: Path, *, missing=False, directory=None):
    """Inspect lexical ancestors before opening, never resolve through a link."""
    for component in (*reversed(path.parents), path):
        try:
            info = component.lstat()
        except FileNotFoundError:
            if missing:
                continue
            raise CacheError("Cache path is missing") from None
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise CacheError("Linked or reparse cache paths are forbidden")
        if component != path:
            if not stat.S_ISDIR(info.st_mode):
                raise CacheError("Cache ancestor is not a directory")
        elif directory is True and not stat.S_ISDIR(info.st_mode):
            raise CacheError("Cache directory is not a directory")
        elif directory is False:
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise CacheError("Cache files must be unlinked regular files")


def _open_regular(path: Path, flags: int, *, create=False):
    _check_path(path, missing=create, directory=False)
    flags |= getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, 0o600)
    try:
        _check_path(path, directory=False)
        opened = os.fstat(descriptor)
        current = path.lstat()
        if (not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1
                or (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino)):
            raise CacheError("Cache file changed while opening")
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _read_regular(path: Path, limit: int) -> bytes:
    descriptor = _open_regular(path, os.O_RDONLY)
    with os.fdopen(descriptor, "rb") as handle:
        if os.fstat(handle.fileno()).st_size > limit:
            raise CacheError("Saved cache file exceeds its byte limit")
        raw = handle.read(limit + 1)
        if len(raw) > limit:
            raise CacheError("Saved cache file exceeds its byte limit")
        return raw


class Store:
    """JSON-dict result store. Corruption raises; only absence returns ``None``.

    ``get(key)`` returns an independent decoded dictionary. ``put(key, value)``
    commits atomically, is idempotent for equal canonical bytes, and rejects a
    different result for an existing invocation. Oversized results or a full
    store are not cached and increment ``skipped_oversize`` / ``skipped_full``.
    The total bound includes all namespaces, the key and lock; no files are
    evicted. ``stats`` is a defensive snapshot of this instance's counters.
    """

    def __init__(self, root: Path, namespace: str, *, max_bytes=DEFAULT_MAX_BYTES):
        if not isinstance(root, Path) or not root.is_absolute() or ".." in root.parts:
            raise CacheError("Cache root must be an absolute Path without parent traversal")
        if root == Path(root.anchor):
            raise CacheError("A filesystem root cannot be a cache root")
        self.root = root
        self.namespace = _sha(namespace, "namespace")
        if os.name == "nt":
            # Keep full content identities and ordinary Windows paths. Check
            # the longest destination before creating any directory/key/lock.
            destination = root / self.namespace / ("0" * 64 + ".json")
            units = len(str(destination).encode("utf-16-le")) // 2
            if units >= 260:
                raise CacheError("Windows cache record path uses " + str(units)
                                 + " UTF-16 units (maximum 259); use a shorter cache root/directory name")
        if type(max_bytes) is not int or max_bytes < 33:
            raise CacheError("max_bytes must be an integer of at least 33")
        self.max_bytes = max_bytes
        self._mutex = threading.RLock()
        self._stats = {name: 0 for name in (
            "hits", "misses", "writes", "unchanged", "skipped_oversize",
            "skipped_full", "errors", "bytes_read", "bytes_written")}
        _check_path(root, missing=True, directory=True)
        root.mkdir(parents=True, exist_ok=True)
        _check_path(root, directory=True)
        with self._locked():
            key_path = root / _KEY_NAME
            if not key_path.exists():
                if any(path.name != _LOCK_NAME for path in root.iterdir()):
                    raise CacheError("Existing cache contents have no authentication key")
                descriptor = _open_regular(
                    key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, create=True)
                with os.fdopen(descriptor, "wb") as handle:
                    handle.write(secrets.token_bytes(32))
                    handle.flush()
                    os.fsync(handle.fileno())
            self._key = self._load_key()
            if self._inventory_bytes() > self.max_bytes:
                raise CacheError("Existing cache contents exceed max_bytes; no eviction performed")

    @property
    def stats(self) -> dict:
        with self._mutex:
            return dict(self._stats)

    def _load_key(self):
        path = self.root / _KEY_NAME
        raw = _read_regular(path, 32)
        if len(raw) != 32:
            raise CacheError("Invalid cache authentication key length")
        if os.name != "nt" and path.lstat().st_mode & 0o077:
            raise CacheError("Cache authentication key permissions are not private")
        return raw

    def _check_key(self):
        if not hmac.compare_digest(self._load_key(), self._key):
            raise CacheError("Cache authentication key changed")

    @contextmanager
    def _locked(self):
        with self._mutex:
            _check_path(self.root, directory=True)
            lock_path = self.root / _LOCK_NAME
            try:
                descriptor = _open_regular(
                    lock_path, os.O_RDWR | os.O_CREAT | os.O_EXCL, create=True)
            except FileExistsError:
                descriptor = _open_regular(lock_path, os.O_RDWR)
            locked = False
            try:
                # Locking bytes beyond current EOF is supported by both locking
                # primitives. Initialise/check the byte only after acquiring it.
                deadline = time.monotonic() + _LOCK_WAIT_SECONDS
                while not locked:
                    try:
                        if os.name == "nt":
                            import msvcrt
                            os.lseek(descriptor, 0, os.SEEK_SET)
                            msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
                        else:
                            import fcntl
                            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        locked = True
                    except OSError as exc:
                        if time.monotonic() >= deadline:
                            raise CacheError("Cache lock unavailable within bounded wait") from exc
                        time.sleep(0.01)
                size = os.fstat(descriptor).st_size
                if size == 0:
                    os.write(descriptor, b"\x00")
                    os.fsync(descriptor)
                elif size != 1:
                    raise CacheError("Invalid cache lock file")
                _check_path(lock_path, directory=False)
                yield
            finally:
                if locked:
                    if os.name == "nt":
                        import msvcrt
                        os.lseek(descriptor, 0, os.SEEK_SET)
                        msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(descriptor, fcntl.LOCK_UN)
                os.close(descriptor)

    def _inventory_bytes(self):
        total = 0
        for path in self.root.iterdir():
            _check_path(path)
            if path.name in (_KEY_NAME, _LOCK_NAME):
                _check_path(path, directory=False)
                total += path.stat().st_size
            elif _SHA.fullmatch(path.name):
                _check_path(path, directory=True)
                for record in path.iterdir():
                    if record.suffix != ".json" or _SHA.fullmatch(record.stem) is None:
                        raise CacheError("Unexpected file in dedicated cache namespace")
                    _check_path(record, directory=False)
                    size = record.stat().st_size
                    if size > MAX_RECORD_BYTES:
                        raise CacheError("Saved cache file exceeds its byte limit")
                    total += size
            else:
                raise CacheError("Unexpected file in dedicated cache root")
        return total

    def _path(self, key):
        return self.root / self.namespace / (_sha(key, "key") + ".json")

    def _read(self, key):
        path = self._path(key)
        _check_path(path, missing=True, directory=False)
        if not path.exists():
            return None
        raw = _read_regular(path, MAX_RECORD_BYTES)
        record = _decode(raw)
        if type(record) is not dict or set(record) != {
                "schema", "namespace", "key", "value_sha256", "value", "mac"}:
            raise CacheError("Invalid authenticated cache envelope")
        if (record["schema"] != SCHEMA or record["namespace"] != self.namespace
                or record["key"] != key or type(record["value"]) is not dict):
            raise CacheError("Cache record identity does not match invocation")
        _sha(record["value_sha256"], "value hash")
        _sha(record["mac"], "authentication code")
        if _encode(record) != raw:
            raise CacheError("Cache record is not canonical JSON")
        body = {name: value for name, value in record.items() if name != "mac"}
        expected_mac = hmac.new(self._key, _encode(body), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected_mac, record["mac"]):
            raise CacheError("Cache record authentication failed")
        value_raw = _encode(record["value"])
        if not hmac.compare_digest(hashlib.sha256(value_raw).hexdigest(),
                                   record["value_sha256"]):
            raise CacheError("Cache result hash does not match")
        self._stats["bytes_read"] += len(raw)
        return record["value"]

    def get(self, key: str) -> dict | None:
        try:
            with self._locked():
                self._check_key()
                result = self._read(key)
                self._stats["misses" if result is None else "hits"] += 1
                return result
        except (CacheError, OSError):
            with self._mutex:
                self._stats["errors"] += 1
            raise

    def put(self, key: str, value: dict) -> None:
        try:
            key = _sha(key, "key")
            if type(value) is not dict:
                raise CacheError("Cache results must be JSON dictionaries")
            try:
                value_raw = _encode(value)
                body = {"schema": SCHEMA, "namespace": self.namespace, "key": key,
                        "value_sha256": hashlib.sha256(value_raw).hexdigest(),
                        "value": _decode(value_raw)}
                body_raw = _encode(body)
                record = dict(body, mac=hmac.new(
                    self._key, body_raw, hashlib.sha256).hexdigest())
                raw = _encode(record)
            except _Oversize:
                with self._locked():
                    self._check_key()
                    if self._read(key) is not None:
                        # An existing bounded record cannot have equal canonical
                        # bytes to an oversized value/envelope for this identity.
                        raise CacheConflictError("Oversized different result for identical invocation identity")
                    self._stats["skipped_oversize"] += 1
                return
            with self._locked():
                self._check_key()
                old = self._read(key)
                if old is not None:
                    if _encode(old) != value_raw:
                        raise CacheConflictError("Different result for identical invocation identity")
                    self._stats["unchanged"] += 1
                    return
                if self._inventory_bytes() + len(raw) > self.max_bytes:
                    self._stats["skipped_full"] += 1
                    return
                path = self._path(key)
                path.parent.mkdir(exist_ok=True)
                _check_path(path.parent, directory=True)
                temporary = None
                try:
                    descriptor, name = tempfile.mkstemp(prefix=".pending-", dir=path.parent)
                    temporary = Path(name)
                    with os.fdopen(descriptor, "wb") as handle:
                        _check_path(temporary, directory=False)
                        handle.write(raw)
                        handle.flush()
                        os.fsync(handle.fileno())
                    _check_path(path, missing=True, directory=False)
                    os.replace(temporary, path)
                    temporary = None
                    self._stats["writes"] += 1
                    self._stats["bytes_written"] += len(raw)
                finally:
                    if temporary is not None:
                        _check_path(temporary, directory=False)
                        temporary.unlink()
        except (CacheError, OSError):
            with self._mutex:
                self._stats["errors"] += 1
            raise
