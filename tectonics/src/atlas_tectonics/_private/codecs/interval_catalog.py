"""Bounded interval catalog, cooperative CAS lock and durable local replacement.

The catalog is the only accepted-state index. Orphan candidates and temporary
catalogs are deliberately preserved. Windows publication requests MoveFileExW
WRITE_THROUGH after explicit FlushFileBuffers. This does not establish a measured
power-loss or atomic-filesystem guarantee for a particular device/filesystem.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import stat
import uuid

from atlas_tectonics._private.codecs.compact_contracts import CATALOG_BYTES, ContractError, SegmentRef, _sha, _uint
from atlas_tectonics._private.integration.interval_admission import durable_replace, flush_file
from atlas_tectonics.integration.resources import canonical_json as canonical

CATALOG_SCHEMA = 'atlas.interval-catalog.v1'


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def tagged(tag, value):
    return digest(tag.encode('ascii') + b'\0' + canonical(value))


def check_cancel(cancel):
    if cancel is not None and cancel.is_set():
        raise InterruptedError('interval operation cancelled')


def _checked_path(path, *, existing=False):
    """Reject links/reparse points and hard-linked regular targets, not just '..'."""
    path = Path(path).absolute()
    target_info = None
    for part in (path, *path.parents):
        try:
            info = part.lstat()
        except FileNotFoundError:
            continue
        if part == path:
            target_info = info
    return path, target_info


def safe_path(path, *, existing=False):
    return _checked_path(path, existing=existing)[0]


def relative_file(root, filename, *, existing=False):
    path, info = _checked_path(Path(root) / filename)
    if existing:
        if info is None:
            raise ContractError('required interval file is missing')
        if not stat.S_ISREG(info.st_mode):
            raise ContractError('required path is not a regular file')
    return path


def file_token(path, *, reject_sidecars=False):
    path, info = _checked_path(path, existing=True)
    if reject_sidecars:
        # The three siblings share the already checked ancestor chain. Their own
        # lstat detects even dangling links/reparse entries without following them.
        for suffix in ('-journal', '-wal', '-shm'):
            sidecar = Path(str(path) + suffix)
            try:
                sidecar.lstat()
            except FileNotFoundError:
                continue
            raise ContractError('sealed interval has a journal/WAL sidecar')
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns,
            info.st_ctime_ns, info.st_mode, getattr(info, 'st_file_attributes', 0))


@dataclass(frozen=True, slots=True)
class CatalogEntry:
    interval: int
    filename: str
    file_sha256: str
    logical_seal: str
    parent_interval: int | None
    parent_seal: str | None
    head: SegmentRef
    producer_identity: str
    runtime_identity: str
    references: tuple[tuple[int, str], ...]

    def __post_init__(self):
        _uint(self.interval, 'interval')
        for field in ('file_sha256', 'logical_seal', 'producer_identity', 'runtime_identity'):
            _sha(getattr(self, field), field)
        if self.interval == 0:
            if self.parent_interval is not None or self.parent_seal is not None:
                raise ContractError('migration root cannot have a parent')
        else:
            _sha(self.parent_seal, 'parent seal')
        for pair in self.references:
            interval, seal = pair
            _uint(interval, 'reference interval')
            _sha(seal, 'reference seal')

    def to_wire(self):
        return {name: getattr(self, name) for name in (
            'interval', 'filename', 'file_sha256', 'logical_seal',
            'parent_interval', 'parent_seal', 'producer_identity', 'runtime_identity')} | {
                'head': self.head.to_wire(), 'references': [list(p) for p in self.references]}

    @classmethod
    def from_wire(cls, value):
        return cls(**(value | {'head': SegmentRef.from_wire(value['head']),
                              'references': tuple(tuple(p) for p in value['references'])}))


@dataclass(frozen=True, slots=True)
class Catalog:
    workflow_id: str
    generation: int
    entries: tuple[CatalogEntry, ...]

    def __post_init__(self):
        _sha(self.workflow_id, 'workflow identity')
        _uint(self.generation, 'catalog generation')
        filenames = set()
        for i, entry in enumerate(self.entries):
            filenames.add(entry.filename)
            for owner, seal in entry.references:
                if self.entries[owner].logical_seal != seal:
                    raise ContractError('catalog reference seal mismatch')

    def to_bytes(self):
        if len(self.entries) > CATALOG_BYTES // 512:
            raise ContractError('catalog exceeds 1 MiB bound')
        value = {'schema': CATALOG_SCHEMA, 'workflow_id': self.workflow_id,
                 'generation': self.generation, 'entries': [e.to_wire() for e in self.entries]}
        raw = bytearray()
        encoder = json.JSONEncoder(sort_keys=True, separators=(',', ':'),
                                   ensure_ascii=True, allow_nan=False)
        for part in encoder.iterencode(value):
            block = part.encode('ascii')
            if len(raw) + len(block) > CATALOG_BYTES:
                raise ContractError('catalog exceeds 1 MiB bound')
            raw.extend(block)
        return bytes(raw)

    @classmethod
    def from_bytes(cls, raw):
        from atlas_tectonics._private.codecs.compact_contracts import _pairs, _nonfinite
        try:
            value = json.loads(raw, object_pairs_hook=_pairs, parse_constant=_nonfinite)
        except (ValueError, UnicodeError, RecursionError) as exc:
            raise ContractError('invalid catalog JSON') from exc
        result = cls(value['workflow_id'], value['generation'],
                     tuple(CatalogEntry.from_wire(e) for e in value['entries']))
        return result


def _read_catalog_image(path, *, expected_size=None):
    path = Path(path).absolute()
    before = file_token(path)
    if expected_size is not None and before[2] != expected_size:
        raise ContractError('catalog changed while reading')
    # Read the stat size plus one byte (not a 1 MiB preallocation); a file that
    # grew is caught by the length and token checks below.
    with path.open('rb') as source:
        raw = source.read(before[2] + 1)
    if file_token(path) != before or len(raw) != before[2]:
        raise ContractError('catalog changed while reading')
    return raw, digest(raw)


def read_catalog(path, *, expected_size=None):
    raw, pin = _read_catalog_image(path, expected_size=expected_size)
    return Catalog.from_bytes(raw), pin


@contextmanager
def publication_lock(catalog_path):
    path = safe_path(str(catalog_path) + '.lock')
    # One persistent non-authoritative lock file; a crashed process releases the OS lock.
    with path.open('a+b') as lock:
        if lock.tell() == 0:
            lock.write(b'\0')
            lock.flush()
        lock.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise ContractError('another catalog publisher holds the lock') from exc
        try:
            yield
        finally:
            lock.seek(0)
            if os.name == 'nt':
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock, fcntl.LOCK_UN)


def _publish_checked_image(path, raw, *, cancel=None, crash_hook=None, precondition=None):
    """Publish a verified image while the caller holds its publication lock."""
    temporary = safe_path(path.with_name(path.name + '.tmp-' + uuid.uuid4().hex))
    with temporary.open('xb') as out:
        out.write(raw)
        flush_file(out)
    if crash_hook:
        crash_hook('catalog_flushed')
    check_cancel(cancel)
    if precondition is not None:
        try:
            precondition()
        except BaseException:
            try:
                temporary.unlink()
            except OSError:
                pass
            raise
    durable_replace(temporary, path)
    if crash_hook:
        crash_hook('catalog_replaced')


def publish_catalog(path, catalog, *, expected_digest, cancel=None, crash_hook=None,
                    precondition=None):
    """CAS under a process lock. A post-replace exception has uncertain outcome.

    Callers must reopen the catalog after such an exception; never retry blindly.
    ``precondition`` (optional, no arguments) runs under the same lock
    immediately before the durable replace; if it raises, nothing is replaced.
    """
    path = safe_path(path)
    raw = catalog.to_bytes()
    check_cancel(cancel)
    with publication_lock(path):
        read_catalog(path)[1] if path.exists() else None
        _publish_checked_image(path, raw, cancel=cancel, crash_hook=crash_hook, precondition=precondition)
    return digest(raw)
