"""Bounded interval catalog, cooperative CAS lock and durable local replacement.

The catalog is the only accepted-state index. Orphan candidates and temporary
catalogs are deliberately preserved. Windows publication requests MoveFileExW
WRITE_THROUGH after explicit FlushFileBuffers. This does not establish a measured
power-loss or atomic-filesystem guarantee for a particular device/filesystem.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import ctypes
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import uuid

from compact_contracts import CATALOG_BYTES, ContractError, SegmentRef, _sha, _uint

CATALOG_SCHEMA = 'atlas.interval-catalog.v1'
_BASENAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,199}\.sqlite\Z')


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=True, allow_nan=False).encode('ascii')


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
            if part == path and existing:
                raise ContractError('required interval file is missing') from None
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise ContractError('linked/reparse paths are forbidden')
        if part == path:
            target_info = info
        if part == path and stat.S_ISREG(info.st_mode) and info.st_nlink != 1:
            raise ContractError('hard-linked files are forbidden')
    if existing and (target_info is None or not stat.S_ISREG(target_info.st_mode)):
        raise ContractError('required path is not a regular file')
    return path, target_info


def safe_path(path, *, existing=False):
    return _checked_path(path, existing=existing)[0]


def relative_file(root, filename):
    if type(filename) is not str or not _BASENAME.fullmatch(filename):
        raise ContractError('catalog filename must be a safe SQLite basename')
    if filename.split('.')[0].upper() in {'CON', 'PRN', 'AUX', 'NUL',
            *(f'COM{i}' for i in range(1, 10)), *(f'LPT{i}' for i in range(1, 10))}:
        raise ContractError('reserved Windows filename')
    return safe_path(Path(root) / filename)


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
        if type(self.filename) is not str or not _BASENAME.fullmatch(self.filename):
            raise ContractError('unsafe interval basename')
        for field in ('file_sha256', 'logical_seal', 'producer_identity', 'runtime_identity'):
            _sha(getattr(self, field), field)
        if self.interval == 0:
            if self.parent_interval is not None or self.parent_seal is not None:
                raise ContractError('migration root cannot have a parent')
        else:
            if type(self.parent_interval) is not int or self.parent_interval != self.interval - 1:
                raise ContractError('parent must be the previous interval')
            _sha(self.parent_seal, 'parent seal')
        if type(self.head) is not SegmentRef or self.head.root_key.interval > self.interval:
            raise ContractError('invalid head reference')
        if type(self.references) is not tuple:
            raise ContractError('references must be an immutable tuple')
        previous = -1
        for pair in self.references:
            if type(pair) is not tuple or len(pair) != 2:
                raise ContractError('malformed reference edge')
            interval, seal = pair
            _uint(interval, 'reference interval')
            _sha(seal, 'reference seal')
            if not previous < interval < self.interval:
                raise ContractError('references must be sorted unique earlier intervals')
            previous = interval

    def to_wire(self):
        return {name: getattr(self, name) for name in (
            'interval', 'filename', 'file_sha256', 'logical_seal',
            'parent_interval', 'parent_seal', 'producer_identity', 'runtime_identity')} | {
                'head': self.head.to_wire(), 'references': [list(p) for p in self.references]}

    @classmethod
    def from_wire(cls, value):
        fields = {'interval', 'filename', 'file_sha256', 'logical_seal', 'parent_interval',
                  'parent_seal', 'head', 'producer_identity', 'runtime_identity', 'references'}
        if type(value) is not dict or set(value) != fields or type(value['references']) is not list:
            raise ContractError('unknown catalog entry fields')
        if any(type(p) is not list or len(p) != 2 for p in value['references']):
            raise ContractError('invalid catalog reference')
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
        if type(self.entries) is not tuple or not self.entries or self.generation != len(self.entries):
            raise ContractError('catalog generation/entry count mismatch')
        filenames = set()
        for i, entry in enumerate(self.entries):
            if type(entry) is not CatalogEntry or entry.interval != i:
                raise ContractError('catalog intervals must be contiguous from zero')
            if entry.filename in filenames:
                raise ContractError('duplicate catalog filename')
            filenames.add(entry.filename)
            if entry.head.root_key.workflow_id != self.workflow_id:
                raise ContractError('foreign workflow head')
            if i and entry.parent_seal != self.entries[i - 1].logical_seal:
                raise ContractError('catalog parent seal mismatch')
            for owner, seal in entry.references:
                if self.entries[owner].logical_seal != seal:
                    raise ContractError('catalog reference seal mismatch')
            allowed = {i, *(owner for owner, _ in entry.references)}
            for owner, _ in entry.references:
                if any(ancestor not in allowed for ancestor, _ in self.entries[owner].references):
                    raise ContractError('incomplete transitive reference closure')
            if entry.head.root_key.interval not in allowed or entry.head.array_bindings.root_key.interval not in allowed:
                raise ContractError('head refers outside declared closure')

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
        if type(raw) is not bytes or len(raw) > CATALOG_BYTES:
            raise ContractError('catalog exceeds 1 MiB bound')
        from compact_contracts import _pairs, _nonfinite
        try:
            value = json.loads(raw, object_pairs_hook=_pairs, parse_constant=_nonfinite)
        except (ValueError, UnicodeError, RecursionError) as exc:
            raise ContractError('invalid catalog JSON') from exc
        if type(value) is not dict or set(value) != {'schema', 'workflow_id', 'generation', 'entries'}:
            raise ContractError('unknown catalog fields')
        if value['schema'] != CATALOG_SCHEMA or type(value['entries']) is not list:
            raise ContractError('unknown catalog schema')
        result = cls(value['workflow_id'], value['generation'],
                     tuple(CatalogEntry.from_wire(e) for e in value['entries']))
        if result.to_bytes() != raw:
            raise ContractError('noncanonical catalog JSON')
        return result


def read_catalog(path):
    path = safe_path(path, existing=True)
    before = file_token(path)
    if before[2] > CATALOG_BYTES:
        raise ContractError('catalog exceeds 1 MiB bound')
    with path.open('rb') as source:
        raw = source.read(CATALOG_BYTES + 1)
    if file_token(path) != before:
        raise ContractError('catalog changed while reading')
    return Catalog.from_bytes(raw), digest(raw)


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


def flush_file(file):
    file.flush()
    if os.name == 'nt':
        import msvcrt
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        flush = kernel.FlushFileBuffers
        flush.argtypes, flush.restype = [ctypes.c_void_p], ctypes.c_int
        if not flush(msvcrt.get_osfhandle(file.fileno())):
            raise ctypes.WinError(ctypes.get_last_error())
    else:
        os.fsync(file.fileno())


def durable_replace(source, target):
    safe_path(source, existing=True)
    safe_path(target)
    if os.name == 'nt':
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        move = kernel.MoveFileExW
        move.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint32]
        move.restype = ctypes.c_int
        if not move(str(source), str(target), 0x1 | 0x8):
            raise ctypes.WinError(ctypes.get_last_error())
    else:
        os.replace(source, target)
        directory = os.open(Path(target).parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)


def publish_catalog(path, catalog, *, expected_digest, cancel=None, crash_hook=None):
    """CAS under a process lock. A post-replace exception has uncertain outcome.

    Callers must reopen the catalog after such an exception; never retry blindly.
    """
    path = safe_path(path)
    raw = catalog.to_bytes()
    check_cancel(cancel)
    with publication_lock(path):
        current = read_catalog(path)[1] if path.exists() else None
        if current != expected_digest:
            raise ContractError('catalog compare-and-swap conflict')
        temporary = safe_path(path.with_name(path.name + '.tmp-' + uuid.uuid4().hex))
        with temporary.open('xb') as out:
            out.write(raw)
            flush_file(out)
        if crash_hook:
            crash_hook('catalog_flushed')
        check_cancel(cancel)
        durable_replace(temporary, path)
        if crash_hook:
            crash_hook('catalog_replaced')
    return digest(raw)
