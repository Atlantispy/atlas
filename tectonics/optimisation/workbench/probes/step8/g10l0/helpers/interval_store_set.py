"""Read-only sealed native-v1 interval files and unlisted transactional candidates.

No historical store is opened by a writer constructor. Native schema, typed
content hashing, codec labels and local-string chunk arrays remain unchanged.
External chunk owners belong exclusively in versioned caller metadata.
"""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
import hashlib
import logging
import math
import os
from pathlib import Path
import re
import sqlite3
import stat
import sys
import threading
import time
import uuid
from functools import wraps

import numpy as np

from atlas_tectonics import storage as native
from atlas_tectonics.integration_spatial_transport import _workspace
from compact_contracts import (CATALOG_BYTES, ContractError, MAX_OPEN_FILES, NATIVE_CHUNK_BYTES,
                               ROOT_METADATA_MAX, SEGMENT_MANIFEST_BYTES,
                               SEGMENT_CHUNK_REFERENCES, SEGMENT_BYTES,
                               SegmentRef, SnapshotLocator, _sha)
from content_cache import ChargeSpec
from interval_catalog import (Catalog, CatalogEntry, _checked_path, canonical, check_cancel,
                              digest, file_token, flush_file, publication_lock,
                              publish_catalog, read_catalog, relative_file, safe_path, tagged)


LIMITS = native.StoreLimits(chunk_bytes=65536, max_array_bytes=512 << 20,
                           max_store_bytes=4 << 30, max_manifest_bytes=1 << 20,
                           max_staging_bytes=1 << 30, decoded_cache_bytes=0)
# Upper bound of the former fixed catalog charge (decoded catalog/index capacity
# plus 768 B for each possible verified file-token entry). Kept as the ceiling:
# the retained owner is now booked from the decoded catalog actually held
# (catalog_retained_charge) and read/rewrite transients from the file size.
CATALOG_CHARGE = 12 * (1 << 20) + 16384
VERIFIED_TOKEN_ENTRIES = CATALOG_BYTES // 512
TOKEN_ENTRY_CHARGE = 768
# Measured (W1, 16 Oct): sqlite3_memory_used per read-only handle after a full
# seal scan is the 2 MiB page cache plus about 132-153 KB of fixed connection
# state (lookaside, schema, statements). 192 KiB covers it (review M6/S4W-2).
HANDLE_CHARGE = LIMITS.sqlite_cache_bytes + (192 << 10)
# Writer candidate owner: unchanged booking (measured 2,077,496 B held).
WRITER_CHARGE = LIMITS.sqlite_cache_bytes + 65536 + (1 << 20)
# Measured tracemalloc peak / catalog bytes: read 6.7-7.5x, rewrite 7.7-8.6x.
CATALOG_TRANSIENT_FACTOR = 9
SEAL_SCHEMA = 'atlas.interval-seal.v1'
QUARANTINE_SCHEMA = 'atlas.interval-quarantine.v1'
_SIDECAR_SUFFIXES = ('-journal', '-wal', '-shm')
_LOG = logging.getLogger('atlas.interval_store_set')


def _deep_size(value):
    """sys.getsizeof closure of a decoded catalog (shared objects counted once)."""
    seen, stack, total = set(), [value], 0
    while stack:
        item = stack.pop()
        if id(item) in seen:
            continue
        seen.add(id(item))
        total += sys.getsizeof(item)
        if isinstance(item, (str, bytes, int, float, bool)) or item is None:
            continue
        if isinstance(item, (tuple, list, set, frozenset)):
            stack.extend(item)
        elif isinstance(item, dict):
            stack.extend(item.keys())
            stack.extend(item.values())
        else:
            for cls in type(item).__mro__:
                for slot in getattr(cls, '__slots__', ()):
                    if hasattr(item, slot):
                        stack.append(getattr(item, slot))
    return total


def catalog_retained_charge(catalog):
    """Retained booking for a decoded catalog and its verified-token index.

    Allocator rounding and the identity string are covered by 1.25x the
    getsizeof closure plus 16 KiB; the token index holds at most one entry
    per catalog interval. Never above the former fixed CATALOG_CHARGE.
    """
    if catalog is None:
        return 16384
    charge = (_deep_size(catalog) * 5) // 4 + 16384 + TOKEN_ENTRY_CHARGE * len(catalog.entries)
    return min(charge, CATALOG_CHARGE)


def catalog_transient_charge(size):
    return min(CATALOG_TRANSIENT_FACTOR * size + 65536, CATALOG_CHARGE)


def seal_key(workflow_id, interval):
    return tagged('atlas.interval-seal-key.v1',
                  {'workflow_id': workflow_id, 'interval': interval})


def typed_descriptor(raw):
    if type(raw) is not bytes or len(raw) > 256:
        raise ContractError('invalid bounded native chunk descriptor')
    value = native._parse(raw)
    if type(value) is not dict or set(value) != {'dtype', 'count'}:
        raise ContractError('unknown native chunk descriptor')
    dt = native._dtype(value['dtype'])
    if dt.str != value['dtype'] or type(value['count']) is not int:
        raise ContractError('noncanonical native chunk descriptor')
    if not 0 < value['count'] * dt.itemsize <= NATIVE_CHUNK_BYTES or canonical(value) != raw:
        raise ContractError('invalid native typed chunk size/spelling')
    return value, dt


def chunk_id(descriptor, raw):
    return native.ArrayStore._blob_id(None, descriptor, raw)


def _owned(scope, count, producer, *, cancel=None, dependencies=()):
    check_cancel(cancel)
    with scope.reserve(ChargeSpec('interval-owned', count),
                       required=True, cancel=cancel) as reservation:
        value = producer()
        check_cancel(cancel)
        return reservation.commit(value, dependencies=dependencies)


def _serial(method):
    @wraps(method)
    def locked(self, *args, **kwargs):
        with self._lock:
            try:
                return method(self, *args, **kwargs)
            except (InterruptedError, sqlite3.Error):
                if hasattr(self, '_failed'):
                    self._failed = True
                raise
    return locked


def _sidecars_absent(path):
    file_token(path, reject_sidecars=True)


def _rename_no_replace(source, target):
    """Atomic same-directory rename that never replaces an existing target."""
    if os.name == 'nt':
        import ctypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        move = kernel.MoveFileExW
        move.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint32]
        move.restype = ctypes.c_int
        # MOVEFILE_WRITE_THROUGH only: no REPLACE_EXISTING, no COPY_ALLOWED.
        if not move(str(source), str(target), 0x8):
            raise ctypes.WinError(ctypes.get_last_error())
    else:
        if os.path.lexists(target):
            raise FileExistsError(target)
        os.rename(source, target)
        directory = os.open(Path(target).parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)


def _immutable(path):
    info = path.stat()
    if os.name == 'nt':
        return bool(getattr(info, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_READONLY)
    return not info.st_mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH)


_TEMPORARY_CATALOG = re.compile(r'(.+)\.tmp-[0-9a-f]{32}')
_INTERVAL_FAMILY = re.compile(r'interval-[0-9]{4,}\.sqlite(?:-journal|-wal|-shm)?(?:\.quarantined-.+)?')
# Canonical catalog JSON (sorted keys) always starts with these bytes.
_CATALOG_PREFIX = b'{"entries":['


def _foreign_catalog_file(catalog_path, cancel):
    """Name of a file in the catalog directory that belongs to another catalog.

    Another catalog's publication lock, quarantine log or publish temporary,
    or any other catalog-shaped file (canonical catalog JSON prefix), proves
    the directory is shared. Unreadable candidates count as foreign.
    """
    # Names compare under the platform's case rule, so a catalog opened through
    # a differently cased path still recognises its own files.
    own = os.path.normcase(catalog_path.name)
    allowed = {own, own + '.lock', own + '.quarantine.jsonl'}
    with os.scandir(catalog_path.parent) as entries:
        for count, entry in enumerate(entries):
            if count % 256 == 0:
                check_cancel(cancel)
            name = entry.name
            key = os.path.normcase(name)
            if key in allowed or _INTERVAL_FAMILY.fullmatch(name):
                continue
            if key.endswith(('.lock', '.quarantine.jsonl')):
                return name
            temporary = _TEMPORARY_CATALOG.fullmatch(name)
            if temporary is not None:
                if os.path.normcase(temporary.group(1)) != own:
                    return name
                continue
            try:
                if not entry.is_file(follow_symlinks=False):
                    continue
                if entry.stat(follow_symlinks=False).st_size > CATALOG_BYTES:
                    continue
                with open(entry.path, 'rb') as stream:
                    prefix = stream.read(len(_CATALOG_PREFIX))
            except OSError:
                return name
            if prefix == _CATALOG_PREFIX:
                return name
    return None


class ReadOnlyNative:
    """Genuine mode=ro SQLite reader; constructor performs no writable operation."""

    def __init__(self, path, *, scope, require_immutable=True):
        self.path = safe_path(path, existing=True)
        self.scope, self.limits = scope, LIMITS
        self._closed = False
        self.token = file_token(self.path, reject_sidecars=True)
        if self.token[2] > self.limits.max_store_bytes:
            raise ContractError('interval exceeds native file bound')
        if require_immutable and not _immutable(self.path):
            raise ContractError('accepted interval is not sealed read-only')
        # Refuse a WAL-mode header before SQLite can create -shm/-wal (L18):
        # bytes 18/19 are the write/read format versions, 1 = rollback journal.
        with self.path.open('rb') as stream:
            header = stream.read(100)
        if len(header) != 100 or header[:16] != b'SQLite format 3\x00' or header[18:20] != b'\x01\x01':
            raise ContractError('interval is not a rollback-journal native SQLite file')
        if file_token(self.path, reject_sidecars=True) != self.token:
            raise ContractError('immutable interval file identity changed')
        self._db = sqlite3.connect(self.path.as_uri() + '?mode=ro', uri=True,
                                   isolation_level=None, timeout=0, check_same_thread=False)
        try:
            self._db.setlimit(sqlite3.SQLITE_LIMIT_SQL_LENGTH, native._MAX_SQL)
            ticks = [0]
            def bounded():
                ticks[0] += 1
                return ticks[0] > native._OPEN_TICKS
            self._db.set_progress_handler(bounded, native._TICK_OPS)
            self._db.execute('PRAGMA query_only=ON')
            self._db.execute('PRAGMA trusted_schema=OFF')
            self._db.execute(f'PRAGMA cache_size=-{self.limits.sqlite_cache_bytes // 1024}')
            self._db.execute('BEGIN')
            schema = set(self._db.execute('SELECT type,name,tbl_name,sql FROM sqlite_master'))
            if schema != native._SCHEMA_OBJECTS:
                raise ContractError('unknown native SQLite schema')
            wanted = native._json({'schema': native._SCHEMA, 'chunk_bytes': NATIVE_CHUNK_BYTES})
            settings = self._db.execute('SELECT id,body FROM settings').fetchall()
            if settings != [(1, wanted)]:
                raise ContractError('incompatible native settings')
            self._db.execute('ROLLBACK')
            self._db.set_progress_handler(None, 0)
            self._check_identity()
        except BaseException:
            self._db.close()
            raise

    def _check_identity(self):
        if self._closed:
            raise ContractError('interval handle is closed')
        if file_token(self.path, reject_sidecars=True) != self.token:
            raise ContractError('immutable interval file identity changed')

    def manifest(self, key):
        self._check_identity()
        _sha(key, 'manifest identity')
        if not self._db.execute('SELECT 1 FROM snapshots WHERE id=?', (key,)).fetchone():
            self._check_identity()
            raise KeyError(key)
        # Native validator performs bounded lengths/types, schema and array checks.
        with _workspace(self.scope.run_budget, 8 * LIMITS.max_manifest_bytes,
                        'interval-manifest-verify'):
            parsed = native.ArrayStore._manifest(self, key)
            if parsed is None:
                raise KeyError(key)
            row = self._db.execute('SELECT body FROM snapshots WHERE id=?', (key,)).fetchone()
            body = row[0]
            if native._json(parsed) != body:
                raise ContractError('noncanonical native manifest')
            self._check_identity()
            del parsed
        return body

    def contains_chunk(self, key, descriptor):
        self._check_identity()
        _sha(key, 'chunk identity')
        row = self._db.execute('SELECT length(descriptor),typeof(descriptor) FROM chunks WHERE id=?', (key,)).fetchone()
        if row is None:
            self._check_identity()
            return False
        if row[1] != 'blob' or row[0] > 256:
            raise ContractError('invalid chunk descriptor record')
        actual = self._db.execute('SELECT descriptor FROM chunks WHERE id=?', (key,)).fetchone()[0]
        if actual != descriptor:
            raise ContractError('typed content identity descriptor conflict')
        self._check_identity()
        return True

    def chunk(self, key, descriptor):
        self._check_identity()
        meta, dt = typed_descriptor(descriptor)
        _sha(key, 'chunk identity')
        row = self._db.execute('SELECT length(descriptor),length(payload),length(codec),length(stored_sha),'
                               'typeof(descriptor),typeof(payload),typeof(codec),typeof(stored_sha) FROM chunks WHERE id=?',
                               (key,)).fetchone()
        if row is None:
            raise ContractError('missing referenced chunk')
        if row[4:] != ('blob', 'blob', 'text', 'text') or row[0] > 256 or row[1] > NATIVE_CHUNK_BYTES + 4096 or row[2] > 128 or row[3] != 64:
            raise ContractError('invalid bounded native chunk record')
        desc, codec, stored, payload = self._db.execute('SELECT descriptor,codec,stored_sha,payload FROM chunks WHERE id=?', (key,)).fetchone()
        if desc != descriptor or digest(desc + b'\0' + codec.encode() + b'\0' + payload) != stored:
            raise ContractError('stored chunk/descriptor checksum mismatch')
        raw = native.ArrayStore._decode(self, codec, payload, dt, meta['count'])
        if chunk_id(desc, raw) != key:
            raise ContractError('typed decoded chunk checksum mismatch')
        self._check_identity()
        return raw

    def close(self):
        if not self._closed:
            self._db.close()
            self._closed = True


def _seal_digest(reader, *, workflow_id, interval, parent_seal, references, cancel=None):
    """Stream sorted native inventories; never materialise the whole history."""
    key = seal_key(workflow_id, interval)
    h = hashlib.sha256(b'atlas.interval-seal.v1\0')
    h.update(b'{"chunks":[')
    first = True
    for cid, length, kind in reader._db.execute('SELECT id,length(descriptor),typeof(descriptor) FROM chunks ORDER BY id'):
        check_cancel(cancel)
        _sha(cid, 'local chunk identity')
        if kind != 'blob' or length > 256:
            raise ContractError('invalid descriptor in seal inventory')
        descriptor = reader._db.execute('SELECT descriptor FROM chunks WHERE id=?', (cid,)).fetchone()[0]
        meta, _ = typed_descriptor(descriptor)
        if not first:
            h.update(b',')
        first = False
        h.update(canonical([cid, tagged('atlas.chunk-descriptor.v1', meta)]))
    h.update(b'],"interval":' + canonical(interval) + b',"manifests":[')
    first = True
    for mid, in reader._db.execute('SELECT id FROM snapshots ORDER BY id'):
        check_cancel(cancel)
        _sha(mid, 'manifest identity')
        if mid == key:
            continue
        body = reader.manifest(mid)
        if not first:
            h.update(b',')
        first = False
        h.update(canonical([mid, digest(body)]))
    h.update(b'],"parent_seal":' + canonical(parent_seal))
    h.update(b',"references":' + canonical([list(p) for p in references]))
    h.update(b',"workflow_id":' + canonical(workflow_id) + b'}')
    return h.hexdigest()


def _seal_metadata(entry, workflow_id):
    return {'schema': SEAL_SCHEMA, 'workflow_id': workflow_id,
            'interval': entry.interval, 'logical_seal': entry.logical_seal,
            'parent_seal': entry.parent_seal,
            'references': [list(p) for p in entry.references]}


def _manifest_bytes(key, metadata, arrays=None):
    if arrays is None:
        arrays = {'_carrier': {'dtype': '|u1', 'shape': [0], 'chunks': []}}
    return native._json({'schema': native._SCHEMA, 'invocation': key,
                         'arrays': arrays, 'metadata': metadata})


def _verify_seal(reader, entry, workflow_id, cancel=None):
    with _workspace(reader.scope.run_budget, 8 * LIMITS.max_manifest_bytes,
                    'interval-seal-inventory'):
        return _verify_seal_inner(reader, entry, workflow_id, cancel)


def _verify_seal_inner(reader, entry, workflow_id, cancel=None):
    key = seal_key(workflow_id, entry.interval)
    try:
        manifest = reader.manifest(key)
    except KeyError as exc:
        raise ContractError('unsealed interval file') from exc
    # L8: the stored seal manifest is canonical native JSON; compare bytes.
    if manifest != _manifest_bytes(key, _seal_metadata(entry, workflow_id)):
        raise ContractError('reserved seal metadata/carrier mismatch')
    actual = _seal_digest(reader, workflow_id=workflow_id, interval=entry.interval,
                          parent_seal=entry.parent_seal, references=entry.references,
                          cancel=cancel)
    if actual != entry.logical_seal:
        raise ContractError('interval logical seal mismatch')


@dataclass(frozen=True, slots=True)
class SealedCandidate:
    entry: CatalogEntry
    expected_catalog_digest: str | None
    _owner: object


class IntervalStoreSet:
    """One workflow, one shared retained scope, at most eight pinned native handles."""

    def __init__(self, catalog_path, *, scope, workflow_id, catalog, catalog_digest, owner):
        self.catalog_path = safe_path(catalog_path)
        self.scope, self.workflow_id = scope, workflow_id
        self._catalog, self.catalog_digest, self._owner = catalog, catalog_digest, owner
        self._handles = OrderedDict()
        self._verified_tokens = {}
        self._candidate = None
        self._closed = False
        self._lock = threading.RLock()
        self.crash_hook = None
        self.opened_intervals = []

    @classmethod
    def create_migration(cls, catalog_path, *, workflow_id, scope, cancel=None):
        _sha(workflow_id, 'workflow identity')
        path = safe_path(catalog_path)
        if path.exists() or not path.parent.is_dir():
            raise ContractError('migration requires explicit existing directory and absent catalog')
        owner = _owned(scope, catalog_retained_charge(None), lambda: None, cancel=cancel)
        return cls(path, scope=scope, workflow_id=workflow_id, catalog=None,
                   catalog_digest=None, owner=owner)

    @classmethod
    def open_catalog(cls, catalog_path, *, scope, cancel=None):
        check_cancel(cancel)
        size = file_token(safe_path(catalog_path, existing=True))[2]
        if size > CATALOG_BYTES:
            raise ContractError('catalog exceeds 1 MiB bound')
        # Read/decode transient on the run budget, scaled to the actual file
        # (L16); the read refuses a file that changed size since this stat.
        with _workspace(scope.run_budget, catalog_transient_charge(size), 'catalog-read'):
            decoded = read_catalog(catalog_path, expected_size=size)
        owner = _owned(scope, catalog_retained_charge(decoded[0]), lambda: decoded,
                       cancel=cancel)
        catalog, identity = owner.value
        result = cls(catalog_path, scope=scope, workflow_id=catalog.workflow_id,
                     catalog=catalog, catalog_digest=identity, owner=owner)
        try:
            # Validate closure paths/existence, but open only head now; ancestors lazily.
            required = {catalog.entries[-1].interval,
                        *(i for i, _ in catalog.entries[-1].references)}
            for i in required:
                entry = catalog.entries[i]
                safe_path(relative_file(result.catalog_path.parent, entry.filename), existing=True)
            result._handle(catalog.entries[-1].interval, cancel=cancel)
            return result
        except BaseException:
            # The failure traceback still holds catalog/owner/result. Close native
            # resources, but keep the catalog allocation charged until that frame
            # and its decoded metadata become unreachable together.
            for handle in result._handles.values():
                handle.value.close()
                handle.close()
            result._handles.clear()
            result._closed = True
            raise

    @property
    def head(self):
        return self._catalog.entries[-1] if self._catalog else None

    def _live(self):
        if self._closed:
            raise ContractError('interval store set is closed')

    def _entries(self):
        return self._catalog.entries if self._catalog else ()

    def _entry(self, interval):
        self._live()
        if type(interval) is not int or not 0 <= interval < len(self._entries()):
            raise ContractError('missing, future or unlisted interval')
        return self._entries()[interval]

    def _allowed(self, requester, owner):
        request = self._entry(requester)
        self._entry(owner)
        if owner != requester and owner not in {i for i, _ in request.references}:
            raise ContractError('reference owner outside declared closure')

    def _handle(self, interval, *, cancel=None, validate=True):
        self._live()
        check_cancel(cancel)
        with self._lock:
            if interval in self._handles:
                result = self._handles[interval]
                if validate:
                    result.value._check_identity()
                self._handles.move_to_end(interval)
                return result
            entry = self._entry(interval)
            candidate_open = self._candidate is not None and self._candidate._state == 'WRITING' and not self._candidate._closed
            if len(self._handles) >= MAX_OPEN_FILES - int(candidate_open):
                for old_interval, old in list(self._handles.items()):
                    # Pin preflight and native close happen under the same owner lock.
                    reader = old.value
                    try:
                        old.assert_unborrowed()
                    except (ValueError, RuntimeError):
                        continue
                    reader.close()
                    old.close()
                    del self._handles[old_interval]
                    break
                else:
                    raise ContractError('all eight native handles are pinned')
            path = relative_file(self.catalog_path.parent, entry.filename)
            with self.scope.reserve(ChargeSpec('interval-handle', HANDLE_CHARGE),
                                    required=True, cancel=cancel) as reservation:
                reader = ReadOnlyNative(path, scope=self.scope)
                try:
                    previous_token = self._verified_tokens.get(interval)
                    if previous_token is not None and reader.token != previous_token:
                        raise ContractError('previously verified interval file identity changed')
                    if previous_token is None and len(self._verified_tokens) >= VERIFIED_TOKEN_ENTRIES:
                        raise ContractError('verified file-token capacity exceeded')
                    # S4W-5: a reopen of a file whose authenticated token is
                    # unchanged since its full seal verification in this store
                    # set skips only the inventory rescan (the same token trust
                    # that cached reads and promotion already rely on). Header,
                    # schema, settings, sidecar and identity checks still run.
                    if previous_token is None:
                        _verify_seal(reader, entry, self.workflow_id, cancel)
                    check_cancel(cancel)
                    owner = reservation.commit(reader)
                except BaseException:
                    reader.close()
                    raise
            self._handles[interval] = owner
            self._verified_tokens[interval] = reader.token
            self.opened_intervals.append(interval)
            # Bounded diagnostic tail, never an unbounded per-read history.
            if len(self.opened_intervals) > MAX_OPEN_FILES:
                del self.opened_intervals[:-MAX_OPEN_FILES]
            return owner

    @_serial
    def borrow_handle(self, interval, *, cancel=None):
        """Explicit paid pin for a long-lived view; no raw unowned handle escape."""
        return self._handle(interval, cancel=cancel).retain()

    @_serial
    def assert_cached_read_safe(self, *, cancel=None):
        """Fresh identity/path/sidecar checks before using owned cached bytes.

        Checks every observed sealed source, including files whose handles have
        been evicted. The bounded token index is prepaid by the catalog owner.
        It opens no new SQLite handle and never repins a changed immutable file.
        """
        self._live()
        check_cancel(cancel)
        for interval, expected in self._verified_tokens.items():
            check_cancel(cancel)
            handle = self._handles.get(interval)
            if handle is not None:
                handle.value._check_identity()
            else:
                entry = self._entry(interval)
                path = self.catalog_path.parent / entry.filename
                if file_token(path, reject_sidecars=True) != expected:
                    raise ContractError('previously verified interval file identity changed')
        check_cancel(cancel)

    @_serial
    def resolve_manifest(self, requester_interval, locator, *, cancel=None):
        if type(locator) is not SnapshotLocator or locator.workflow_id != self.workflow_id:
            raise ContractError('foreign/invalid snapshot locator')
        self._allowed(requester_interval, locator.interval)
        handle = self._handle(locator.interval, cancel=cancel, validate=False)
        return _owned(self.scope, LIMITS.max_manifest_bytes,
                      lambda: handle.value.manifest(locator.snapshot_key), cancel=cancel,
                      dependencies=(handle,))

    @_serial
    def resolve_chunk(self, requester_interval, owner_interval, chunk_id, descriptor, *, cancel=None):
        self._allowed(requester_interval, owner_interval)
        typed_descriptor(descriptor)
        handle = self._handle(owner_interval, cancel=cancel, validate=False)
        with _workspace(self.scope.run_budget, LIMITS.codec_workspace_bytes + 8 * NATIVE_CHUNK_BYTES,
                        'interval-chunk-decode'):
            return _owned(self.scope, NATIVE_CHUNK_BYTES,
                          lambda: handle.value.chunk(chunk_id, descriptor), cancel=cancel,
                          dependencies=(handle,))

    @_serial
    def verify_file_sha256(self, interval, *, cancel=None):
        """Explicit full physical-file verification, separate from selective reads."""
        entry = self._entry(interval)
        owner = self._handle(interval, cancel=cancel).retain()
        try:
            with _workspace(self.scope.run_budget, 2 * NATIVE_CHUNK_BYTES, 'interval-file-hash'):
                h = hashlib.sha256()
                with owner.value.path.open('rb') as stream:
                    while True:
                        check_cancel(cancel)
                        block = stream.read(NATIVE_CHUNK_BYTES)
                        if not block:
                            break
                        h.update(block)
                owner.value._check_identity()
                if h.hexdigest() != entry.file_sha256:
                    raise ContractError('physical interval file SHA-256 mismatch')
                return True
        finally:
            owner.close()

    @_serial
    def begin_interval(self, parent, *, producer_identity, runtime_identity, cancel=None):
        self._live()
        check_cancel(cancel)
        if parent != self.head or (self._candidate is not None and not self._candidate._closed):
            raise ContractError('candidate parent changed or writer is already active')
        if len(self._handles) == MAX_OPEN_FILES:
            for interval, owner in list(self._handles.items()):
                try:
                    owner.assert_unborrowed()
                except (ValueError, RuntimeError):
                    continue
                owner.value.close()
                owner.close()
                del self._handles[interval]
                break
            else:
                raise ContractError('all eight native handles are pinned')
        candidate = UnlistedCandidate(self, producer_identity, runtime_identity, cancel=cancel)
        self._candidate = candidate
        return candidate

    @_serial
    def quarantine_orphan(self, *, reason, cancel=None):
        """Logged quarantine of an orphaned candidate for the next interval (M5).

        Refuses unless the file is provably not accepted state: under the
        catalog publication lock the on-disk catalog must still equal this
        store set's catalog (absent for a migration), no accepted entry may
        name the file, no live candidate of this store set may own it, the
        directory must hold no other catalog (one catalog per directory), and
        a sealed orphan must carry this workflow's seal for this interval and
        parent. The orphan and every SQLite sidecar (-journal, -wal, -shm) are
        renamed, never deleted, to one unique diagnostic name that can never
        be a catalog basename; sidecars move first and, if any rename fails,
        every moved file is renamed back. Time, reason, sizes and SHA-256 are appended to
        '<catalog>.quarantine.jsonl' and logged. Returns the record, or None
        when there is nothing to quarantine.
        """
        self._live()
        check_cancel(cancel)
        if type(reason) is not str or not 0 < len(reason) <= 512 or not reason.isprintable():
            raise ContractError('quarantine requires a bounded printable reason')
        if self._candidate is not None and not self._candidate._closed:
            raise ContractError('a live candidate of this store set owns the next interval file')
        interval = len(self._entries())
        main = relative_file(self.catalog_path.parent, f'interval-{interval:04d}.sqlite')
        paths = [Path(str(main) + suffix) for suffix in _SIDECAR_SUFFIXES] + [main]
        with publication_lock(self.catalog_path):
            check_cancel(cancel)
            if self.catalog_path.exists():
                size = file_token(self.catalog_path)[2]
                if size > CATALOG_BYTES:
                    raise ContractError('catalog exceeds 1 MiB bound')
                with _workspace(self.scope.run_budget, catalog_transient_charge(size),
                                'quarantine-catalog-read'):
                    accepted, identity = read_catalog(self.catalog_path, expected_size=size)
            else:
                accepted, identity = None, None
            if identity != self.catalog_digest:
                raise ContractError('accepted catalog changed; reopen it before quarantine')
            listed = {entry.filename for entry in accepted.entries} if accepted else set()
            if main.name in listed or any(entry.interval >= interval for entry in (accepted.entries if accepted else ())):
                raise ContractError('refusing to quarantine a file named by the accepted catalog')
            present = []
            for path in paths:
                try:
                    path.lstat()
                except FileNotFoundError:
                    continue
                # Links, reparse points, hard links and non-regular files refuse.
                _checked_path(path, existing=True)
                present.append(path)
            if not present:
                return None
            # A3: one catalog per directory. Refuse unless the directory is
            # provably dedicated to this catalog, and unless a sealed orphan
            # carries this workflow's seal for this interval and parent.
            foreign = _foreign_catalog_file(self.catalog_path, cancel)
            if foreign is not None:
                raise ContractError('refusing to quarantine: directory is not dedicated to this catalog '
                                    f'({foreign!r} belongs to another catalog)')
            if main in present:
                # A sidecar-only orphan has no seal to check; the dedicated-
                # directory scan above still guards it.
                self._check_orphan_seal(main, interval, cancel)
            check_cancel(cancel)
            stamp = time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())
            suffix = f'.quarantined-{stamp}-{uuid.uuid4().hex}'
            moved, failure = [], None
            for path in present:
                target = path.with_name(path.name + suffix)
                try:
                    _rename_no_replace(path, target)
                except OSError as exc:
                    failure = exc
                    break
                moved.append((path, target))
            if failure is not None:
                # A4: the orphan and its sidecars move as one unit. Rename
                # every already moved file back (never replacing) so a failed
                # quarantine leaves nothing half-moved; anything that cannot
                # be put back stays listed in the logged record.
                for original, target in reversed(list(moved)):
                    try:
                        _rename_no_replace(target, original)
                    except OSError:
                        continue
                    moved.remove((original, target))
            files, unhashed = [], False
            for original, target in moved:
                # The record is always written once files have moved: a moved
                # file that cannot be read (for example another process's
                # handle without read sharing) is logged without a hash.
                row = {'original': original.name, 'quarantined': target.name, 'bytes': None, 'sha256': None}
                try:
                    h = hashlib.sha256()
                    with target.open('rb') as stream:
                        while True:
                            block = stream.read(NATIVE_CHUNK_BYTES)
                            if not block:
                                break
                            h.update(block)
                    row['bytes'], row['sha256'] = target.stat().st_size, h.hexdigest()
                except OSError as exc:
                    row['error'] = type(exc).__name__
                    unhashed = True
                files.append(row)
            record = {'schema': QUARANTINE_SCHEMA, 'time_utc': stamp, 'reason': reason,
                      'workflow_id': self.workflow_id, 'catalog_digest': identity,
                      'interval': interval, 'complete': failure is None, 'files': files}
            line = canonical(record)
            log_path = safe_path(str(self.catalog_path) + '.quarantine.jsonl')
            with log_path.open('ab') as log:
                log.write(line + b'\n')
                flush_file(log)
            _LOG.warning('interval candidate quarantined: %s', line.decode('ascii'))
            if failure is not None:
                if moved:
                    raise ContractError('orphan quarantine incomplete; files that could not be '
                                        'renamed back are logged') from failure
                raise ContractError('orphan quarantine refused: a file could not be renamed; '
                                    'every moved file was renamed back') from failure
            if unhashed:
                raise ContractError('orphan quarantine complete but some moved files could not be '
                                    'hashed; see the quarantine log')
            return record

    def _check_orphan_seal(self, main, interval, cancel):
        """A sealed (read-only) orphan must carry this catalog's own seal."""
        if not _immutable(main):
            return
        refusal = 'refusing to quarantine a sealed file that is not this catalog\'s candidate'
        parent_seal = self.head.logical_seal if self.head else None
        with _workspace(self.scope.run_budget, HANDLE_CHARGE + 8 * LIMITS.max_manifest_bytes,
                        'quarantine-seal-check'):
            try:
                reader = ReadOnlyNative(main, scope=self.scope)
            except ContractError as exc:
                raise ContractError(refusal) from exc
            try:
                try:
                    body = reader.manifest(seal_key(self.workflow_id, interval))
                except KeyError:
                    raise ContractError(refusal) from None
                check_cancel(cancel)
                metadata = native._parse(body).get('metadata')
                if type(metadata) is not dict or canonical(
                        [metadata.get('schema'), metadata.get('workflow_id'),
                         metadata.get('interval'), metadata.get('parent_seal')]) != canonical(
                        [SEAL_SCHEMA, self.workflow_id, interval, parent_seal]):
                    raise ContractError(refusal)
                del metadata, body
            finally:
                reader.close()

    @_serial
    def promote(self, sealed, *, expected_catalog_digest, cancel=None):
        self._live()
        if type(sealed) is not SealedCandidate or sealed._owner is not self:
            raise ContractError('foreign sealed candidate')
        if expected_catalog_digest != self.catalog_digest or expected_catalog_digest != sealed.expected_catalog_digest:
            raise ContractError('stale expected catalog digest')
        entry = sealed.entry
        if entry.interval != len(self._entries()):
            raise ContractError('candidate interval is not the next interval')
        candidate = self._candidate
        if candidate is None or candidate._state != 'SEALED' or candidate._sealed != sealed:
            raise ContractError('candidate is not sealed')
        # Verify final bytes again only if file identity changed; immutable token is trust-bound.
        if file_token(candidate.path) != candidate._sealed_token or not _immutable(candidate.path):
            raise ContractError('sealed candidate changed before promotion')
        for owner, _ in entry.references:
            self._handle(owner, cancel=cancel)
        catalog = Catalog(self.workflow_id, entry.interval + 1, (*self._entries(), entry))
        # L16: rewrite transient scaled to the new catalog's size bound (old
        # file + the new entry's wire + generation digits); the retained owner
        # for the new catalog is reserved before publication, so a refusal
        # cannot follow an accepted catalog replacement.
        old_size = file_token(self.catalog_path)[2] if self._catalog is not None else 128
        new_size = min(old_size + len(canonical(entry.to_wire())) + 64, CATALOG_BYTES)
        def still_sealed():
            # A2: repeated under the publication lock just before the durable
            # replace; quarantine_orphan takes the same lock, so a file it
            # moved (or any later change) is refused here, never accepted.
            try:
                unchanged = (file_token(candidate.path, reject_sidecars=True) == candidate._sealed_token
                             and _immutable(candidate.path))
            except (OSError, ContractError) as exc:
                raise ContractError('sealed candidate changed before promotion') from exc
            if not unchanged:
                raise ContractError('sealed candidate changed before promotion')

        with self.scope.reserve(ChargeSpec('interval-owned', catalog_retained_charge(catalog)),
                                required=True, cancel=cancel) as reservation:
            with _workspace(self.scope.run_budget, catalog_transient_charge(new_size), 'catalog-rewrite'):
                identity = publish_catalog(self.catalog_path, catalog,
                                           expected_digest=expected_catalog_digest,
                                           cancel=cancel, crash_hook=self.crash_hook,
                                           precondition=still_sealed)
            owner = reservation.commit((catalog, identity))
        previous_owner, self._owner = self._owner, owner
        previous_owner.close()
        self._catalog, self.catalog_digest = catalog, identity
        candidate._state = 'CATALOG_PROMOTED'
        candidate.close()
        return entry

    @_serial
    def close(self):
        if self._closed:
            return
        if self._candidate is not None and not self._candidate._closed:
            self._candidate.close()
        for owner in self._handles.values():
            owner.assert_unborrowed()
        for interval, owner in list(self._handles.items()):
            reader = owner.value
            reader.close()
            owner.close()
            del self._handles[interval]
        self._catalog = None
        self._verified_tokens.clear()
        self._owner.close()
        self._closed = True


class UnlistedCandidate:
    """One unlisted writer. The sole final seal write is followed by read-only mode."""

    def __init__(self, stores, producer_identity, runtime_identity, *, cancel=None):
        _sha(producer_identity, 'producer identity')
        _sha(runtime_identity, 'runtime identity')
        self.stores, self.scope, self.workflow_id = stores, stores.scope, stores.workflow_id
        self.interval = len(stores._entries())
        self.producer_identity, self.runtime_identity = producer_identity, runtime_identity
        self.expected_catalog_digest = stores.catalog_digest
        self.path = relative_file(stores.catalog_path.parent, f'interval-{self.interval:04d}.sqlite')
        self._state, self._closed, self._failed = 'WRITING', False, False
        self._references = set()
        self._lock = threading.RLock()
        self._sealed = None
        self._reader = None
        self.limits = LIMITS
        self.compression = native.Compression()
        self._stats = {'encodes': 0, 'local_chunks': 0, 'manifests': 0,
                       'manifest_bytes': 0, 'encoded_payload_bytes': 0,
                       'retained_record_bytes': 0}
        self._owner = _owned(self.scope, WRITER_CHARGE, lambda: None, cancel=cancel)
        try:
            check_cancel(cancel)
            # O_EXCL makes orphan collision a refusal, including stale sealed files.
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(fd)
            import blosc2
            self._blosc = blosc2
            self._db = sqlite3.connect(self.path, isolation_level=None, timeout=0,
                                       check_same_thread=False)
            self._db.execute('PRAGMA journal_mode=DELETE')
            self._db.execute('PRAGMA synchronous=FULL')
            self._db.execute('PRAGMA trusted_schema=OFF')
            self._db.execute(f'PRAGMA cache_size=-{LIMITS.sqlite_cache_bytes // 1024}')
            page = self._db.execute('PRAGMA page_size').fetchone()[0]
            self._db.execute(f'PRAGMA max_page_count={LIMITS.max_store_bytes // page}')
            self._db.execute('BEGIN IMMEDIATE')
            for ddl in native._DDL.values():
                self._db.execute(ddl)
            self._db.execute('INSERT INTO settings VALUES(1,?)',
                             (native._json({'schema': native._SCHEMA, 'chunk_bytes': NATIVE_CHUNK_BYTES}),))
        except BaseException:
            if hasattr(self, '_db'):
                self._db.close()
            self._owner.close()
            self._closed = True
            raise

    def _writing(self, cancel=None):
        if self._closed or self._state != 'WRITING' or self._failed:
            raise ContractError('candidate is not a usable writer')
        try:
            check_cancel(cancel)
        except BaseException:
            self._failed = True
            raise

    def _reference(self, owner):
        if owner != self.interval:
            entry = self.stores._entry(owner)
            self._references.add(owner)
            # Preserve complete required closure in the successor's reference set.
            self._references.update(i for i, _ in entry.references)

    def _ancestors(self):
        # Earlier sealed catalog entries form the eligible immutable lineage.
        return range(self.interval)

    @_serial
    def find_manifest(self, snapshot_key, *, cancel=None):
        self._writing(cancel)
        _sha(snapshot_key, 'snapshot identity')
        if self._db.execute('SELECT 1 FROM snapshots WHERE id=?', (snapshot_key,)).fetchone():
            return SnapshotLocator(self.workflow_id, self.interval, snapshot_key)
        for owner in self._ancestors():
            handle = self.stores._handle(owner, cancel=cancel, validate=False)
            try:
                handle.value.manifest(snapshot_key)
            except KeyError:
                continue
            self._reference(owner)
            return SnapshotLocator(self.workflow_id, owner, snapshot_key)
        return None

    @_serial
    def find_chunk(self, chunk_id, descriptor, *, cancel=None):
        self._writing(cancel)
        typed_descriptor(descriptor)
        _sha(chunk_id, 'chunk identity')
        owner = self._find_chunk_location(chunk_id, descriptor, cancel=cancel)
        if owner is not None:
            with self.resolve_chunk(owner, chunk_id, descriptor, cancel=cancel):
                pass
        return owner

    def _find_chunk_location(self, chunk_id, descriptor, *, cancel=None):
        # Current candidate first, then deterministic earliest sealed ancestor.
        # Location is only a hint; both callers authenticate decoded bytes once.
        row = self._db.execute('SELECT descriptor FROM chunks WHERE id=?', (chunk_id,)).fetchone()
        if row:
            if row[0] != descriptor:
                raise ContractError('candidate chunk descriptor conflict')
            return self.interval
        for owner in self._ancestors():
            handle = self.stores._handle(owner, cancel=cancel, validate=False)
            if handle.value.contains_chunk(chunk_id, descriptor):
                self._reference(owner)
                return owner
        return None

    @_serial
    def put_chunk(self, descriptor, raw, *, cancel=None):
        self._writing(cancel)
        meta, dt = typed_descriptor(descriptor)
        if type(raw) is not bytes or len(raw) != dt.itemsize * meta['count']:
            raise ContractError('chunk bytes do not match descriptor')
        if dt.kind == 'f' and not np.isfinite(np.frombuffer(raw, dtype=dt)).all():
            raise ContractError('nonfinite native chunk values')
        key = chunk_id(descriptor, raw)
        owner = self._find_chunk_location(key, descriptor, cancel=cancel)
        if owner is not None:
            with self.resolve_chunk(owner, key, descriptor, cancel=cancel) as old:
                if old.value != raw:
                    raise ContractError('typed logical content conflict')
            return owner, key
        with _workspace(self.scope.run_budget, LIMITS.codec_workspace_bytes + 32 * NATIVE_CHUNK_BYTES,
                        'interval-chunk-encode'):
            codec, payload = native.ArrayStore._encode(self, raw, dt)
            if native.ArrayStore._decode(self, codec, payload, dt, meta['count']) != raw:
                self._failed = True
                raise ContractError('native encoder changed typed bytes')
            stored = digest(descriptor + b'\0' + codec.encode() + b'\0' + payload)
            addition = len(payload) + len(descriptor) + 128
            if self._stats['retained_record_bytes'] + addition > LIMITS.max_store_bytes:
                raise ContractError('candidate exceeds native retained-record limit')
            self._writing(cancel)
            self._db.execute('INSERT INTO chunks VALUES(?,?,?,?,?)',
                             (key, descriptor, codec, stored, payload))
        self._stats['local_chunks'] += 1
        self._stats['encoded_payload_bytes'] += len(payload)
        self._stats['retained_record_bytes'] += addition
        return self.interval, key

    @_serial
    def put_manifest(self, snapshot_key, metadata, *, arrays=None, cancel=None):
        self._writing(cancel)
        _sha(snapshot_key, 'snapshot identity')
        if snapshot_key == seal_key(self.workflow_id, self.interval):
            raise ContractError('reserved final seal snapshot identity')
        with _workspace(self.scope.run_budget, 8 * SEGMENT_MANIFEST_BYTES, 'interval-manifest-write'):
            meta_bytes = native._json(metadata)
            if len(meta_bytes) > ROOT_METADATA_MAX:
                raise ContractError('metadata exceeds 64 KiB bound')
            body = _manifest_bytes(snapshot_key, metadata, arrays)
            if len(body) > SEGMENT_MANIFEST_BYTES:
                raise ContractError('manifest exceeds 256 KiB bound')
            parsed = native._parse(body)
            logical_bytes = references = 0
            for desc in parsed['arrays'].values():
                if type(desc) is not dict or set(desc) != {'dtype', 'shape', 'chunks'}:
                    raise ContractError('invalid local array descriptor')
                dt = native._dtype(desc['dtype'])
                shape, ids = desc['shape'], desc['chunks']
                if type(shape) is not list or len(shape) > 16 or any(type(n) is not int or n < 0 for n in shape):
                    raise ContractError('invalid local array shape')
                count = math.prod(shape)
                width = NATIVE_CHUNK_BYTES // dt.itemsize
                if type(ids) is not list or len(ids) != (count + width - 1) // width:
                    raise ContractError('invalid local array chunk inventory')
                logical_bytes += count * dt.itemsize
                references += len(ids)
                for index, cid in enumerate(ids):
                    _sha(cid, 'native local chunk identity')
                    wanted = canonical({'dtype': dt.str, 'count': min(width, count - index * width)})
                    row = self._db.execute('SELECT descriptor FROM chunks WHERE id=?', (cid,)).fetchone()
                    if row is None or row[0] != wanted:
                        raise ContractError('native arrays may reference only matching local string chunks')
            if not parsed['arrays'] or logical_bytes > SEGMENT_BYTES or references > SEGMENT_CHUNK_REFERENCES:
                raise ContractError('native backing put exceeds segment bounds')
            previous = self._db.execute('SELECT body FROM snapshots WHERE id=?', (snapshot_key,)).fetchone()
            if previous:
                if previous[0] != body:
                    raise ContractError('immutable manifest identity conflict')
                return SnapshotLocator(self.workflow_id, self.interval, snapshot_key)
            if self._stats['retained_record_bytes'] + len(body) + 128 > LIMITS.max_store_bytes:
                raise ContractError('candidate exceeds retained-record native limit')
            self._writing(cancel)
            self._db.execute('INSERT INTO snapshots VALUES(?,?,?)', (snapshot_key, body, digest(body)))
            self._stats['manifests'] += 1
            self._stats['manifest_bytes'] += len(body)
            self._stats['retained_record_bytes'] += len(body) + 128
        return SnapshotLocator(self.workflow_id, self.interval, snapshot_key)

    @_serial
    def resolve_manifest(self, locator, *, cancel=None):
        self._writing(cancel)
        if type(locator) is not SnapshotLocator or locator.workflow_id != self.workflow_id:
            raise ContractError('foreign candidate locator')
        if locator.interval != self.interval:
            self._reference(locator.interval)
            return self.stores.resolve_manifest(locator.interval, locator, cancel=cancel)
        def load():
            with _workspace(self.scope.run_budget, 8 * LIMITS.max_manifest_bytes,
                            'candidate-manifest-verify'):
                manifest = native.ArrayStore._manifest(self, locator.snapshot_key)
                if manifest is None:
                    raise KeyError(locator.snapshot_key)
                return self._db.execute('SELECT body FROM snapshots WHERE id=?', (locator.snapshot_key,)).fetchone()[0]
        return _owned(self.scope, LIMITS.max_manifest_bytes, load, cancel=cancel, dependencies=(self._owner,))

    @_serial
    def resolve_chunk(self, owner_interval, chunk_id, descriptor, *, cancel=None):
        self._writing(cancel)
        if owner_interval != self.interval:
            self._reference(owner_interval)
            return self.stores.resolve_chunk(owner_interval, owner_interval, chunk_id, descriptor, cancel=cancel)
        meta, dt = typed_descriptor(descriptor)
        def load():
            row = self._db.execute('SELECT descriptor,codec,stored_sha,payload FROM chunks WHERE id=?', (chunk_id,)).fetchone()
            if row is None or row[0] != descriptor:
                raise ContractError('missing or conflicting local chunk')
            desc, codec, stored, payload = row
            if digest(desc + b'\0' + codec.encode() + b'\0' + payload) != stored:
                raise ContractError('candidate stored chunk checksum mismatch')
            raw = native.ArrayStore._decode(self, codec, payload, dt, meta['count'])
            if native.ArrayStore._blob_id(self, descriptor, raw) != chunk_id:
                raise ContractError('candidate typed chunk checksum mismatch')
            return raw
        with _workspace(self.scope.run_budget, LIMITS.codec_workspace_bytes + 8 * NATIVE_CHUNK_BYTES,
                        'interval-candidate-decode'):
            return _owned(self.scope, NATIVE_CHUNK_BYTES, load, cancel=cancel, dependencies=(self._owner,))

    def local_statistics(self):
        return dict(self._stats, state=self._state)

    @_serial
    def seal(self, head, *, cancel=None):
        self._writing(cancel)
        if type(head) is not SegmentRef or head.root_key.workflow_id != self.workflow_id or head.root_key.interval > self.interval:
            raise ContractError('invalid candidate head')
        # Root existence and exact reference binding; domain/science admission is caller-owned.
        with _workspace(self.scope.run_budget, 8 * LIMITS.max_manifest_bytes, 'candidate-head-verify'):
            with self.resolve_manifest(head.root_key, cancel=cancel) as body:
                metadata = native._parse(body.value)['metadata']
                # L8: exact canonical bytes, so 1/1.0/true never alias.
                if (type(metadata) is not dict or metadata.get('schema') != 'atlas.segment-root.v1' or
                        'reference' not in metadata or canonical(metadata['reference']) != canonical(head.to_wire())):
                    raise ContractError('head root does not bind the supplied SegmentRef')
                del metadata
        self._reference(head.array_bindings.root_key.interval)
        with self.resolve_manifest(head.array_bindings.root_key, cancel=cancel):
            pass
        references = tuple((i, self.stores._entry(i).logical_seal) for i in sorted(self._references))
        parent_seal = self.stores.head.logical_seal if self.stores.head else None
        # Refuse live returned buffers before quiescence; release after DB close below.
        self._owner.assert_unborrowed()
        self._db.execute('COMMIT')
        self._db.close()
        self._state = 'QUIESCED'
        _sidecars_absent(self.path)
        if self.stores.crash_hook:
            self.stores.crash_hook('candidate_quiesced')
        check_cancel(cancel)
        # Transient finalisation handle and scan are explicitly charged.
        with _workspace(self.scope.run_budget, HANDLE_CHARGE + 8 * LIMITS.max_manifest_bytes,
                        'interval-finalise'):
            reader = ReadOnlyNative(self.path, scope=self.scope, require_immutable=False)
            try:
                logical_seal = _seal_digest(reader, workflow_id=self.workflow_id,
                                            interval=self.interval, parent_seal=parent_seal,
                                            references=references, cancel=cancel)
            finally:
                reader.close()
            temporary_entry = CatalogEntry(self.interval, self.path.name, '0' * 64,
                                            logical_seal, self.interval - 1 if self.interval else None,
                                            parent_seal, head, self.producer_identity,
                                            self.runtime_identity, references)
            key = seal_key(self.workflow_id, self.interval)
            seal_metadata = _seal_metadata(temporary_entry, self.workflow_id)
            if len(canonical(seal_metadata)) > ROOT_METADATA_MAX:
                raise ContractError('final seal metadata exceeds 64 KiB bound')
            body = _manifest_bytes(key, seal_metadata)
            if len(body) > SEGMENT_MANIFEST_BYTES:
                raise ContractError('final seal manifest exceeds 256 KiB bound')
            if self._stats['retained_record_bytes'] + len(body) + 128 > LIMITS.max_store_bytes:
                raise ContractError('final seal exceeds native retained-record file limit')
            final = sqlite3.connect(self.path, isolation_level=None, timeout=0)
            try:
                final.execute('PRAGMA synchronous=FULL')
                page = final.execute('PRAGMA page_size').fetchone()[0]
                final.execute(f'PRAGMA max_page_count={LIMITS.max_store_bytes // page}')
                final.execute('BEGIN IMMEDIATE')
                final.execute('INSERT INTO snapshots VALUES(?,?,?)', (key, body, digest(body)))
                check_cancel(cancel)
                final.execute('COMMIT')
            finally:
                final.close()
            _sidecars_absent(self.path)
            if self.path.stat().st_size > LIMITS.max_store_bytes:
                raise ContractError('final interval exceeds native physical file limit')
            with self.path.open('r+b') as stream:
                flush_file(stream)
            if self.stores.crash_hook:
                self.stores.crash_hook('seal_written')
            # L17: read-only first and capture the token, hash, then require
            # the same token, so no later writer can pass between the hash and
            # the read-only attribute.
            os.chmod(self.path, stat.S_IREAD)
            sealed_token = file_token(self.path, reject_sidecars=True)
            h = hashlib.sha256()
            with self.path.open('rb') as stream:
                while True:
                    check_cancel(cancel)
                    raw = stream.read(NATIVE_CHUNK_BYTES)
                    if not raw:
                        break
                    h.update(raw)
            if file_token(self.path, reject_sidecars=True) != sealed_token:
                raise ContractError('sealed candidate changed while hashing')
            self._sealed_token = sealed_token
        entry = CatalogEntry(self.interval, self.path.name, h.hexdigest(), logical_seal,
                             self.interval - 1 if self.interval else None, parent_seal,
                             head, self.producer_identity, self.runtime_identity, references)
        # L17: re-verify the logical seal on the final read-only bytes, so a
        # write between the logical scan and read-only is refused here rather
        # than accepted into the catalog and refused at every later open.
        with _workspace(self.scope.run_budget, HANDLE_CHARGE + 8 * LIMITS.max_manifest_bytes,
                        'interval-final-verify'):
            reader = ReadOnlyNative(self.path, scope=self.scope)
            try:
                if reader.token != sealed_token:
                    raise ContractError('sealed candidate changed before final verification')
                _verify_seal(reader, entry, self.workflow_id, cancel)
                reader._check_identity()
            finally:
                reader.close()
        for owner, _ in references:
            self.stores._handle(owner, cancel=cancel)
        self._sealed = SealedCandidate(entry, self.expected_catalog_digest, self.stores)
        self._state = 'SEALED'
        if self.stores.crash_hook:
            self.stores.crash_hook('file_sealed')
        return self._sealed

    @_serial
    def close(self):
        if self._closed:
            return
        if self._state == 'WRITING':
            # Refuse retained outputs before releasing/rolling back their owner.
            self._owner.assert_unborrowed()
            self._db.close()
        self._references.clear()
        self._owner.close()
        self._closed = True
