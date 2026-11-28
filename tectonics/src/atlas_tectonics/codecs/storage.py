"""Bounded local, lossless array snapshots with content-addressed chunk reuse.

SQLite owns transactions/locking and packs blobs into one file. No pickle, history
migration, garbage collection, lossy conversion, or network store. Caller owns the
local directory (not hostile). SHA-256 detects corruption, not an authorised
attacker who can replace both data and hashes. Numerical meaning stays in the
invocation metadata; equal payloads may be shared across different invocations.
"""
from __future__ import annotations

from atlas_shared.errors import AtlasError
from collections import OrderedDict
from contextlib import contextmanager
from dataclasses import dataclass
import errno
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import stat
import struct
import threading
import tempfile
import time
from typing import Mapping, cast

import numpy as np

from atlas_tectonics.integration.resources import WorkBudget, select_budget, reserve_budgets
from atlas_tectonics.history import _stock_funding as _history


class StoreError(ValueError, AtlasError):
    """Corrupt, incompatible, unsafe or over-budget storage; never a cache miss."""


class StoreConflict(StoreError):
    """One immutable scientific identity was assigned conflicting results."""


class _SnapshotConflict(StoreConflict):
    """This invocation already has a different immutable snapshot."""


_SCHEMA = 'atlas.array-store.v1'
# The only schema a store may hold, as SQLite records it (IF NOT EXISTS is not kept in sqlite_master.sql). Every
# storage.py revision created exactly these tables. A view, trigger, generated column, default, check or extra
# index in a supplied database would run SQL the store never wrote, so anything else refuses before a statement
# touches the tables.
_DDL = {
    'settings': 'CREATE TABLE settings (id INTEGER PRIMARY KEY CHECK(id=1), body BLOB NOT NULL)',
    'chunks': 'CREATE TABLE chunks (id TEXT PRIMARY KEY, descriptor BLOB NOT NULL, codec TEXT NOT NULL, stored_sha TEXT NOT NULL, payload BLOB NOT NULL)',
    'snapshots': 'CREATE TABLE snapshots (id TEXT PRIMARY KEY, body BLOB NOT NULL, digest TEXT NOT NULL)',
}
_SCHEMA_OBJECTS = frozenset({('table', name, name, sql) for name, sql in _DDL.items()} | {
    ('index', 'sqlite_autoindex_chunks_1', 'chunks', None),
    ('index', 'sqlite_autoindex_snapshots_1', 'snapshots', None)})
# SQLite parses a database's whole schema at the first statement, before it can be compared. Every statement the
# store runs, and each of its schema rows, is far shorter than _MAX_SQL; _OPEN_TICKS bounds the virtual-machine work
# of the whole open sequence (ticks of _TICK_OPS operations). An oversized or crowded schema refuses early.
_MAX_SQL = 4096
_TICK_OPS, _OPEN_TICKS = 1000, 200


def _database_error(exc, action):
    """StoreError for an SQLite failure: contention, bounded work and file access stay distinguishable from damage."""
    name = getattr(exc, 'sqlite_errorname', '') or ''
    if name.startswith(('SQLITE_BUSY', 'SQLITE_LOCKED')) or 'database is locked' in str(exc):
        return StoreError(action + ': the database is locked by another connection; retry later')
    if name == 'SQLITE_INTERRUPT':
        return StoreError(action + ': the database schema exceeds the store\'s bounded opening work')
    if name.startswith(('SQLITE_READONLY', 'SQLITE_PERM', 'SQLITE_CANTOPEN', 'SQLITE_FULL', 'SQLITE_IOERR')):
        return StoreError(action + ': the database file could not be read or written (' + name + ')')
    return StoreError(action + ': corrupt, incompatible or unreadable database')


def _json(value) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(',', ':'),
                          allow_nan=False).encode('utf-8')
    except (TypeError, ValueError, OverflowError, RecursionError) as exc:
        raise StoreError('metadata must be finite JSON data') from exc


def _pairs(pairs):
    out = {}
    for k, v in pairs:
        if k in out:
            raise StoreError('duplicate metadata key')
        out[k] = v
    return out


def _parse(raw):
    try:
        return json.loads(raw, object_pairs_hook=_pairs,
                          parse_constant=lambda x: (_ for _ in ()).throw(StoreError('nonfinite metadata')))
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise StoreError('invalid metadata') from exc


def _hash(data):
    return hashlib.sha256(data).hexdigest()


def _positive(value, name):
    if type(value) is not int or value <= 0:
        raise StoreError(name + ' must be a positive integer')


@dataclass(frozen=True, slots=True)
class StoreLimits:
    chunk_bytes: int
    max_array_bytes: int
    max_store_bytes: int
    decoded_cache_bytes: int = 0
    max_manifest_bytes: int = 1024 * 1024
    max_chunks: int = 100_000
    staging_memory_bytes: int = 256 * 1024
    max_staging_bytes: int = 256 * 1024 * 1024
    verified_cache_entries: int = 2048
    insert_batch_bytes: int = 256 * 1024
    sqlite_cache_bytes: int = 2 * 1024 * 1024
    codec_workspace_bytes: int = 8 * 1024 * 1024

    def __post_init__(self):
        for name in ('chunk_bytes', 'max_array_bytes', 'max_store_bytes',
                     'max_manifest_bytes', 'max_chunks', 'staging_memory_bytes',
                     'max_staging_bytes', 'verified_cache_entries', 'insert_batch_bytes',
                     'sqlite_cache_bytes', 'codec_workspace_bytes'):
            _positive(getattr(self, name), name)


@dataclass(frozen=True, slots=True)
class Compression:
    codec: str = 'zstd'
    level: int = 1
    shuffle: str = 'byte'
    palette: bool = True
    categorical: str = 'auto'
    use_dict: bool = False

    def __post_init__(self):
        if self.codec not in ('raw', 'zstd') or self.shuffle not in ('none', 'byte', 'bit'):
            raise StoreError('supported codecs: raw/zstd; shuffle: none/byte/bit')
        if type(self.level) is not int or not 0 <= self.level <= 9:
            raise StoreError('Blosc2 compression level must be 0..9 (not direct Zstd levels)')
        if type(self.palette) is not bool or type(self.use_dict) is not bool:
            raise StoreError('palette and use_dict must be bool')
        if self.categorical not in ('auto', 'legacy'):
            raise StoreError('categorical must be auto or legacy')
        if self.use_dict and self.codec != 'zstd':
            raise StoreError('dictionary compression requires Zstd')


@dataclass(frozen=True, slots=True)
class StorageProfile:
    """A versioned starting configuration, not automatic hardware calibration."""
    name: str
    chunk_bytes: int
    compression: Compression


def storage_profile(name: str = 'balanced') -> StorageProfile:
    """Existing stores retain their chunk size; profiles never migrate a store."""
    profiles = {
        'fast': (16384, Compression(level=1)),
        'balanced': (65536, Compression(level=1)),
        'compact': (262144, Compression(level=3)),
    }
    size, compression = profiles[name]
    return StorageProfile(name + '-v1', size, compression)


@dataclass(frozen=True, slots=True)
class ArrayReference:
    """Reference an existing immutable array, not an assertion about caller data.

    The store revalidates the source manifest and chunks. These public fields are
    not capabilities: constructing or modifying a record cannot skip verification.
    """
    store_path: str
    invocation: str
    array_name: str
    descriptor_sha256: str


@dataclass(frozen=True, slots=True)
class _EditedReference:
    reference: ArrayReference
    replacements: Mapping[int, np.ndarray]



def _dtype(text):
    if type(text) is not str:
        raise StoreError('dtype must be explicit text')
    try:
        dt = np.dtype(text)
    except (ValueError, TypeError) as exc:
        raise StoreError('invalid dtype') from exc
    if dt.kind not in 'biuf' or dt.itemsize not in (1, 2, 4, 8) or dt.fields:
        raise StoreError('only fixed-width numeric/boolean arrays are supported')
    return dt.newbyteorder('<')


def _array_view(value):
    _dtype(value.dtype.str)
    return value


_ABSENT_ERRNOS = (errno.ENOENT, errno.ENOTDIR, errno.EBADF, errno.ELOOP)   # as pathlib's exists() treats them
_ABSENT_WINERRORS = (21, 123, 1921)          # not ready, invalid name, cannot resolve the name


def _path(path, *, sidecar=False):
    # Refuse static links/reparse points, including directory ancestors, from one lstat per path. A path is absent
    # where pathlib's exists() would say so (missing, under a regular file, a symbolic-link loop or an unusable name).
    # A rollback-journal sidecar can be deleted by another connection's commit between checks, and on Windows a file
    # being deleted refuses access, or shows no remaining link, until it is gone; either way it is absent, not a
    # failure (and never a hard link).
    for p in (path, *path.parents):
        try:
            st = p.lstat()
        except OSError as exc:
            if exc.errno in _ABSENT_ERRNOS or getattr(exc, 'winerror', None) in _ABSENT_WINERRORS:
                continue
            if isinstance(exc, PermissionError) and sidecar and p == path:
                continue
            raise
        if p == path and stat.S_ISREG(st.st_mode) and st.st_nlink != 1:
            if sidecar and st.st_nlink == 0:
                continue
            raise StoreError('hard-linked database is forbidden')


class ArrayStore:
    """One connection, serialised operations; separate processes use SQLite locks.

    Use on a local filesystem. max_store_bytes bounds database pages and logical
    retained records; reserve up to another database-sized rollback journal on disk.
    max_array_bytes bounds a fully loaded snapshot, not merely one output field: put()
    refuses a snapshot that get() under the same limits could not load. Streaming
    reads (iter_chunks, read_chunk, metadata) still check each declared array only, so
    snapshots written under larger limits stay readable piecewise.
    iter_chunks reads independent chunks without materialising the full snapshot.
    Opening bounds the schema parse SQLite performs first (statement length and
    virtual-machine work), refuses a database whose schema is not exactly the store's
    own tables (no views, triggers, generated columns or extra indexes), and writes
    nothing to an existing store. SQLite errors surface as StoreError; contention,
    bounded-work refusal and file access are named apart from a damaged database.
    Caller must not mutate inputs during put(). No implicit eviction of snapshots.
    Preparation uses a finite spool: staging_memory_bytes plus at most one chunk
    transiently before spilling, and max_staging_bytes of temporary storage. Decoder
    and palette workspace are charged separately. New codecs read old v1 records;
    older implementations refuse new codec labels rather than misreading them.
    """
    def __init__(self, path, limits: StoreLimits, compression: Compression = Compression(), *, budget=None):
        self.path = Path(path).absolute()
        self.limits = limits
        self.compression = compression
        _path(self.path)
        for suffix in ('-journal', '-wal', '-shm'):
            _path(Path(str(self.path) + suffix), sidecar=True)
        self._blosc = None
        if compression.codec == 'zstd':
            try:
                import blosc2
            except ImportError as exc:
                raise StoreError('zstd requested: optional blosc2 dependency is unavailable') from exc
            self._blosc = blosc2
        self._lock = threading.RLock()
        self._cache = OrderedDict()
        self._cached_bytes = 0
        self._cache_version = None
        self._cache_changes = -1
        # (pin, retained bytes) as of this connection's last successful publication, or None; see _retained_pin.
        self._retained = None
        self._verified = OrderedDict()
        self._stats = dict(payload_reads=0, decoded_hits=0, verified_hits=0,
                           encodes=0, staged_bytes=0, prepare_seconds=0.,
                           writer_seconds=0., insert_batches=0, peak_prepared_bytes=0)
        self._preparing = threading.Lock()
        self._budget = select_budget(budget)
        # Capacity reservations survive individual calls. They include allowances
        # for Python cache entries and SQLite pages, not a claim of measured RSS.
        self._resident_bytes = (limits.decoded_cache_bytes + limits.sqlite_cache_bytes
                                + 1024 * limits.verified_cache_entries + 16384)
        self._resident_reservation = self._budget.reserve(self._resident_bytes,
                                                         category="store-retained")
        self._resident_reservation.__enter__()
        try:
            self._db = sqlite3.connect(self.path, timeout=5, isolation_level=None,
                                       check_same_thread=False)
        except BaseException as exc:
            self._resident_reservation.__exit__(None, None, None)
            if isinstance(exc, sqlite3.Error):
                raise _database_error(exc, 'cannot open store') from exc
            raise
        try:
            # The first statement parses whatever schema a supplied file holds; bound that before running any.
            self._db.setlimit(sqlite3.SQLITE_LIMIT_SQL_LENGTH, _MAX_SQL)
            ticks = [0]
            def bounded():
                ticks[0] += 1
                return ticks[0] > _OPEN_TICKS
            self._db.set_progress_handler(bounded, _TICK_OPS)
            self._db.execute('PRAGMA journal_mode=DELETE')
            self._db.execute('PRAGMA synchronous=FULL')
            self._db.execute('PRAGMA trusted_schema=OFF')
            self._db.execute('PRAGMA foreign_keys=ON')
            self._db.execute(f'PRAGMA cache_size=-{max(1, limits.sqlite_cache_bytes // 1024)}')
            page = self._db.execute('PRAGMA page_size').fetchone()[0]
            max_pages = limits.max_store_bytes // page
            self._db.execute(f'PRAGMA max_page_count={max_pages}')
            self._db.execute('BEGIN IMMEDIATE')
            # Checked inside the write lock, before any statement reads or writes a table, so no other writer can
            # add a schema object between this comparison and the settings insert below.
            existing = set(self._db.execute('SELECT type, name, tbl_name, sql FROM sqlite_master'))
            if existing and existing != _SCHEMA_OBJECTS:
                raise StoreError('refusing to modify an unrelated database')
            self._db.execute(_DDL['settings'].replace('CREATE TABLE ', 'CREATE TABLE IF NOT EXISTS ', 1))
            chunk_bytes = limits.chunk_bytes
            wanted = _json({'schema': _SCHEMA, 'chunk_bytes': chunk_bytes})
            self._initial_settings = (_SCHEMA, chunk_bytes, wanted)
            row = self._db.execute('SELECT body FROM settings WHERE id=1').fetchone()
            self._db.execute('INSERT OR IGNORE INTO settings VALUES(1,?)', (wanted,))
            self._db.execute(_DDL['chunks'].replace('CREATE TABLE ', 'CREATE TABLE IF NOT EXISTS ', 1))
            self._db.execute(_DDL['snapshots'].replace('CREATE TABLE ', 'CREATE TABLE IF NOT EXISTS ', 1))
            # An existing store is only read here: ending without a write lets open succeed beside a reader.
            self._db.execute('COMMIT' if not existing or row is None else 'ROLLBACK')
            self._db.set_progress_handler(None, 0)
        except BaseException as exc:
            try:
                if self._db.in_transaction:
                    self._db.execute('ROLLBACK')
            except sqlite3.Error:
                pass                                  # closing the connection rolls back regardless
            self._db.close()
            self._resident_reservation.__exit__(None, None, None)
            if isinstance(exc, sqlite3.Error):
                raise _database_error(exc, 'cannot open store') from exc
            raise
        self._closed = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def close(self):
        # A concurrent encoder still owns the spool and connection. Refuse an
        # unsafe close rather than release its memory reservation prematurely.
        if not self._preparing.acquire(blocking=False):
            raise StoreError("finish/cancel and join active preparation before closing store")
        try:
            with self._lock:
                if not self._closed:
                    self._clear_caches()
                    try:
                        self._db.close()
                    finally:
                        self._resident_reservation.__exit__(None, None, None)
                        self._closed = True
        finally:
            self._preparing.release()

    def _workspace(self, count, budget=None, *, category="store-work"):
        """Keep store and caller limits binding without charging ancestors twice."""
        if budget is None:
            return self._budget.reserve(count, category=category)
        return reserve_budgets(count, self._budget, select_budget(budget), category=category)

    def _history_roots(self, budget):
        return (self._budget,) if budget is None else (self._budget, select_budget(budget))

    def resource_requirements(self):
        """Configured capacities/allowances, not measured RSS or free-disk checks.

        Allow one journal per database, one spool per concurrent writer, and each
        requested backup separately. Several connections to one database share
        its persistent/journal capacity but each owns a page cache and spool.
        """
        return dict(retained_ram_allowance=self._resident_bytes,
                    codec_workspace_allowance=self.limits.codec_workspace_bytes,
                    write_workspace_allowance=self._write_work_bytes(),
                    read_workspace_allowance=self._read_work_bytes(),
                    database_capacity=self.limits.max_store_bytes,
                    rollback_journal_capacity=self.limits.max_store_bytes,
                    staging_capacity_per_writer=self.limits.max_staging_bytes,
                    backup_capacity_per_copy=self.limits.max_store_bytes,
                    process_rss_cap=False)

    def _write_work_bytes(self, references=None, manifest_bytes=None):
        # Hash sets, manifest lists and dependency maps coexist with encoded data.
        # Their in-memory cost is greater than their compact JSON representation.
        if references is None:
            references = min(self.limits.max_chunks, self.limits.max_manifest_bytes // 68 + 1)
        if manifest_bytes is None:
            manifest_bytes = self.limits.max_manifest_bytes
        return (32 * self.limits.chunk_bytes + 8 * manifest_bytes
                + 768 * references + 2 * self.limits.staging_memory_bytes
                + 2 * self.limits.insert_batch_bytes + self.limits.codec_workspace_bytes)

    def _read_work_bytes(self):
        return (8 * self.limits.chunk_bytes + 4 * self.limits.max_manifest_bytes
                + self.limits.codec_workspace_bytes)

    def _clear_caches(self):
        self._cache.clear()
        self._verified.clear()
        self._cached_bytes = 0

    def _live(self):
        _path(self.path)

    def _retained_pin(self):
        """Read inside a write transaction: what must stay equal for a running retained total to stay exact.

        data_version changes when another connection commits; total_changes when this connection inserts, updates
        or deletes rows (trigger programs included); schema_version when the schema changes, including through DDL
        or a backup into this connection, which neither of the others counts. Any other change, a first use, a
        refused or failed publication, or a schema that is not exactly the store's own leaves the full scan in use.
        Out-of-band raw file changes are not covered, as for the store's caches; max_page_count still binds.
        """
        return (self._db.execute('PRAGMA data_version').fetchone()[0], self._db.total_changes,
                self._db.execute('PRAGMA schema_version').fetchone()[0])

    @contextmanager
    def _read_scope(self, *, budget=None, _history_manifest=False):
        """Pin one SQLite snapshot before trusting validated in-memory payloads.

        data_version catches other connections; total_changes catches direct SQL
        on this connection. Neither is a file-timestamp identity. Only successful
        verification in this snapshot may bypass repeated reads. Out-of-band raw
        file changes and malicious control of this process are not supported.
        """
        with self._lock:
            self._live()
            owner = not self._db.in_transaction
            funding = None
            if getattr(self, '_w08_history_holds', None) is not None:
                funding = _history.ManifestFunds(*self._history_roots(budget))
            reservation = None
            if owner:
                if funding is None:
                    reservation = self._workspace(self._read_work_bytes(), budget,
                                                  category="store-read")
                    reservation.__enter__()
                else:
                    funding.enter(self._read_work_bytes())
            try:
                if owner:
                    self._db.execute('BEGIN')
                # Touch a table to acquire a stable read view before data_version.
                settings = self._db.execute('SELECT body FROM settings WHERE id=1').fetchone()
                schema, chunk_bytes, wanted = self._initial_settings
                current_chunk_bytes = self.limits.chunk_bytes
                if (schema != _SCHEMA or type(chunk_bytes) is not int
                        or type(current_chunk_bytes) is not int or chunk_bytes != current_chunk_bytes):
                    wanted = _json({'schema': _SCHEMA, 'chunk_bytes': current_chunk_bytes})
                if settings is None or settings[0] != wanted:
                    raise StoreError('store settings changed during use')
                version = self._db.execute('PRAGMA data_version').fetchone()[0]
                changes = self._db.total_changes
                if version != self._cache_version or changes != self._cache_changes:
                    self._clear_caches()
                    self._cache_version, self._cache_changes = version, changes
                if _history_manifest and funding is not None:
                    with _history.bind(self, '_w08_history_read', funding):
                        yield funding
                else:
                    yield funding
            except sqlite3.Error as exc:
                raise _database_error(exc, 'storage read transaction failed') from exc
            finally:
                try:
                    if owner and self._db.in_transaction:
                        self._db.execute('ROLLBACK')
                finally:
                    if reservation is not None:
                        reservation.__exit__(None, None, None)

    def _remember(self, key, dtype, count):
        self._verified[key] = (dtype, count)
        self._verified.move_to_end(key)
        while len(self._verified) > self.limits.verified_cache_entries:
            old, _ = self._verified.popitem(last=False)
            raw = self._cache.pop(old, None)
            if raw is not None:
                self._cached_bytes -= len(raw)

    def _remember_raw(self, key, raw):
        if len(raw) > self.limits.decoded_cache_bytes:
            return
        old = self._cache.pop(key, None)
        if old is not None:
            self._cached_bytes -= len(old)
        while self._cache and self._cached_bytes + len(raw) > self.limits.decoded_cache_bytes:
            _, old = self._cache.popitem(last=False)
            self._cached_bytes -= len(old)
        self._cache[key] = raw
        self._cached_bytes += len(raw)

    def _blob_id(self, descriptor, raw):
        h = hashlib.sha256(b'atlas-typed-chunk-v1\0')
        h.update(descriptor)
        h.update(b'\0')
        h.update(raw)
        return h.hexdigest()

    def _encode(self, raw, dt):
        """Pick the smallest exact representation; never quantise physical fields.

        Categoricals may use 1/2/4/8-bit palette indices or run-length records.
        Legacy palette8 is retained for explicit compatibility tests. Zstd uses
        one native thread; an embedded per-frame dictionary has no external file.
        """
        transformed = ArrayStore._encode_transformed(self, raw, dt)
        return ('raw', raw) if transformed is None else transformed

    def _encode_transformed(self, raw, dt):
        """Return the chosen transformed payload, or None when raw wins."""
        self._stats['encodes'] += 1
        width = dt.itemsize
        words = np.frombuffer(raw, dtype=f'<u{width}')
        if np.all(words == words[0]):
            return 'uniform', raw[:width]
        best = None
        best_size = len(raw)
        if self.compression.palette and dt.kind in 'biu':
            a = np.frombuffer(raw, dtype=dt)
            values, inverse = np.unique(a, return_inverse=True)
            n = len(values)
            if 1 < n <= 256:
                indices = inverse.astype('u1')
                if self.compression.categorical == 'legacy':
                    candidate = ('palette8', struct.pack('<I', n) + values.tobytes() + indices.tobytes())
                else:
                    bits = next(b for b in (1, 2, 4, 8) if n <= 1 << b)
                    per_byte = 8 // bits
                    size = (indices.size + per_byte - 1) // per_byte
                    packed = np.zeros(size, dtype='u1')
                    for lane in range(per_byte):
                        part = indices[lane::per_byte]
                        packed[:part.size] |= part << (lane * bits)
                    candidate = ('palette-packed-v1', struct.pack('<HB', n, bits)
                                 + values.tobytes() + packed.tobytes())
                if len(candidate[1]) < best_size:
                    best = candidate
                    best_size = len(candidate[1])
            if self.compression.categorical == 'auto':
                starts = np.concatenate(([0], np.flatnonzero(a[1:] != a[:-1]) + 1))
                if 4 + starts.size * (4 + width) < best_size:
                    runs = np.empty(starts.size, dtype=[('count', '<u4'), ('value', dt)])
                    runs['count'] = np.diff(np.append(starts, a.size))
                    runs['value'] = a[starts]
                    best = ('rle-v1', struct.pack('<I', starts.size) + runs.tobytes())
                    best_size = len(best[1])
        if self.compression.codec == 'zstd':
            b = self._blosc
            filters = [b.Filter.NOFILTER] * 5 + [
                {'none': b.Filter.NOFILTER, 'byte': b.Filter.SHUFFLE,
                 'bit': b.Filter.BITSHUFFLE}[self.compression.shuffle]]
            encoded = b.compress2(raw, codec=b.Codec.ZSTD, clevel=self.compression.level,
                                 typesize=width, nthreads=1, filters=filters,
                                 use_dict=self.compression.use_dict)
            if len(encoded) < best_size:
                version = b.clib_info(b.Codec.ZSTD)[1].decode()
                dictionary = 'dict' if self.compression.use_dict else 'nodict'
                label = (f'blosc2-zstd-{self.compression.shuffle}:{self.compression.level}:'
                         f'{b.__version__}:{version}:{dictionary}')
                best = (label, bytes(encoded))
        return best

    def _decode(self, codec, payload, dt, count):
        nbytes = count * dt.itemsize
        if codec == 'raw':
            raw = payload
        elif codec == 'uniform':
            raw = payload * count
        elif codec == 'palette8':
            n = struct.unpack('<I', payload[:4])[0]
            cut = 4 + n * dt.itemsize
            palette = np.frombuffer(payload, dtype=dt, offset=4, count=n)
            indices = np.frombuffer(payload, dtype='u1', offset=cut)
            raw = palette[indices].tobytes()
        elif codec == 'palette-packed-v1':
            n, bits = struct.unpack('<HB', payload[:3])
            cut = 3 + n * dt.itemsize
            palette = np.frombuffer(payload, dtype=dt, offset=3, count=n)
            packed = np.frombuffer(payload, dtype='u1', offset=cut)
            indices = np.empty(count, dtype='u1')
            per_byte = 8 // bits
            for lane in range(per_byte):
                size = indices[lane::per_byte].size
                indices[lane::per_byte] = (packed[:size] >> (lane * bits)) & ((1 << bits) - 1)
            raw = palette[indices].tobytes()
        elif codec == 'rle-v1':
            if dt.kind not in 'biu' or len(payload) < 4:
                raise StoreError('invalid run-length type/header')
            n = struct.unpack('<I', payload[:4])[0]
            if not 0 < n <= count or len(payload) != 4 + n * (4 + dt.itemsize):
                raise StoreError('invalid run-length dimensions')
            runs = np.frombuffer(payload, dtype=[('count', '<u4'), ('value', dt)], offset=4)
            lengths = runs['count']
            if np.any(lengths == 0) or int(lengths.sum(dtype=np.uint64)) != count:
                raise StoreError('invalid run-length total')
            raw = np.repeat(runs['value'], lengths.astype(np.intp)).tobytes()
        elif codec.split(':', 1)[0] in ('blosc2-zstd-none', 'blosc2-zstd-byte', 'blosc2-zstd-bit'):
            try:
                import blosc2 as b
                if len(payload) < 32:
                    raise StoreError('truncated compressed chunk')
                declared, compressed, block = b.get_cbuffer_sizes(payload)
                if declared != nbytes or compressed != len(payload) or not 0 < block <= nbytes:
                    raise StoreError('invalid compressed size before allocation')
                raw = bytes(b.decompress2(payload, nthreads=1))
            except (ImportError, RuntimeError, ValueError) as exc:
                raise StoreError('unavailable codec or invalid compressed chunk') from exc
        else:
            raise StoreError('unsupported stored codec')
        if len(raw) != nbytes:
            raise StoreError('decoded length mismatch')
        return raw

    def _chunk(self, key, *, expected_dtype=None, expected_count=None, verify_only=False):
        """Must run in _read_scope or a write transaction with its view pinned."""
        known = self._verified.get(key)
        if known is not None:
            if expected_dtype is not None and known != (expected_dtype, expected_count):
                raise StoreError('chunk does not match manifest')
            self._verified.move_to_end(key)
            if verify_only:
                self._stats['verified_hits'] += 1
                return None
            raw = self._cache.get(key)
            if raw is not None:
                self._cache.move_to_end(key)
                self._stats['decoded_hits'] += 1
                return raw
        bounds = ("typeof(descriptor)='blob' AND typeof(payload)='blob' AND "
                  "typeof(codec)='text' AND typeof(stored_sha)='text' AND "
                  'length(descriptor)<=256 AND length(payload)<=:payload_limit AND '
                  'length(codec)<=128 AND length(stored_sha)=64')
        payload_limit = self.limits.chunk_bytes + 4096
        row = self._db.execute(
            'SELECT length(descriptor),length(payload),length(codec),length(stored_sha),'
            'typeof(descriptor),typeof(payload),typeof(codec),typeof(stored_sha),'
            f'CASE WHEN {bounds} THEN descriptor END,CASE WHEN {bounds} THEN codec END,'
            f'CASE WHEN {bounds} THEN stored_sha END,CASE WHEN {bounds} THEN payload END '
            'FROM chunks WHERE id=:key',
            {'key': key, 'payload_limit': payload_limit}).fetchone()
        if row[4:8] != ('blob', 'blob', 'text', 'text'):
            raise StoreError('invalid chunk record types')
        if row[0] > 256 or row[1] > payload_limit or row[2] > 128 or row[3] != 64:
            raise StoreError('oversized chunk record')
        desc, codec, stored, payload = row[8:]
        self._stats['payload_reads'] += 1
        if _hash(desc + b'\0' + codec.encode() + b'\0' + payload) != stored:
            raise StoreError('stored chunk checksum mismatch')
        meta = _parse(desc)
        if set(meta) != {'dtype', 'count'} or type(meta['count']) is not int:
            raise StoreError('invalid chunk descriptor')
        dt, count = _dtype(meta['dtype']), meta['count']
        raw = self._decode(codec, payload, dt, count)
        if self._blob_id(desc, raw) != key:
            raise StoreError('logical chunk checksum mismatch')
        self._remember(key, dt.str, count)
        self._remember_raw(key, raw)
        return None if verify_only else raw

    def _manifest(self, key, *, _return_body=False):
        """The interval reader can retain the validated bytes inside its own workspace."""
        funding = getattr(self, '_w08_history_read', None)
        row = self._db.execute('SELECT length(body),typeof(body),typeof(digest) FROM snapshots WHERE id=?', (key,)).fetchone()
        if row is None:
            return None
        ArrayStore._check_manifest_header(row, self.limits)
        if funding is not None:
            funding.before_fetch(row[0])
        body, digest = self._db.execute('SELECT body,digest FROM snapshots WHERE id=?', (key,)).fetchone()
        ArrayStore._check_manifest_checksum(body, digest)
        if funding is not None:
            del row, digest
            funding.before_parse(len(body))
        m = _parse(body)
        if funding is not None:
            del body
            funding.parsed()
        ArrayStore._check_manifest_fields(m, key, self.limits)
        return (m, body) if _return_body and funding is None else m

    def _candidate_manifest_body(self, key):
        """Read a local manifest under the candidate writer's funded workspace."""
        body_size = "CASE WHEN typeof(body)='blob' THEN length(body) END"
        admitted = f"({body_size})<=:limit AND typeof(digest)='text'"
        row = self._db.execute(
            f'SELECT {body_size},typeof(body),typeof(digest),'
            f'CASE WHEN {admitted} THEN body END,CASE WHEN {admitted} THEN digest END '
            'FROM snapshots WHERE id=:key',
            {'key': key, 'limit': self.limits.max_manifest_bytes}).fetchone()
        if row is None:
            return None
        ArrayStore._check_manifest_header(row, self.limits)
        body, digest = row[3:]
        del row
        ArrayStore._check_manifest_checksum(body, digest)
        ArrayStore._check_manifest_fields(_parse(body), key, self.limits)
        return body

    @staticmethod
    def _check_manifest_header(row, limits):
        if row[1:3] != ('blob', 'text'):
            raise StoreError('invalid manifest record types')
        if row[0] > limits.max_manifest_bytes:
            raise StoreError('oversized manifest')

    @staticmethod
    def _check_manifest_checksum(body, digest):
        if _hash(body) != digest:
            raise StoreError('manifest checksum mismatch')

    @staticmethod
    def _check_manifest_fields(m, key, limits):
        chunks = 0
        for name, a in m['arrays'].items():
            dt = _dtype(a['dtype'])
            shape = a['shape']
            count = math.prod(shape)
            if count * dt.itemsize > limits.max_array_bytes:
                raise StoreError('declared array exceeds decoder limit')
            ids = a['chunks']
            chunks += len(ids)
        if chunks > limits.max_chunks:
            raise StoreError('too many chunk references')

    def reference(self, invocation: str, array_name: str) -> ArrayReference:
        """Return a checked reference; no array payload is materialised here."""
        with self._read_scope():
            m = cast(dict, self._manifest(invocation))
            return ArrayReference(str(self.path), invocation, array_name,
                                  _hash(_json(m['arrays'][array_name])))

    def put_incremental(self, invocation, parent, replacements, metadata=None, *,
                        publication_check=None, cancel=None, budget=None):
        """Replace named COMPLETE chunks; unspecified chunks come from the parent.

        No dirty flags are accepted. Retained data are the parent's actual stored
        chunks, never bytes from a caller's allegedly unchanged array. The new
        manifest directly references payloads, so it is not a temporal delta chain.
        """
        with self._read_scope():
            m = cast(dict, self._manifest(parent))
            arrays = {}
            for name, desc in m['arrays'].items():
                ref = ArrayReference(str(self.path), parent, name, _hash(_json(desc)))
                arrays[name] = _EditedReference(ref, dict(replacements.get(name, {})))
            if metadata is None:
                metadata = m['metadata']
        return self.put(invocation, arrays, metadata, publication_check=publication_check,
                        cancel=cancel, budget=budget)

    def _reference_description(self, ref):
        m = cast(dict, self._manifest(ref.invocation))
        desc = m['arrays'][ref.array_name]
        return desc

    def put(self, invocation: str, arrays: Mapping, metadata=None, *,
            publication_check=None, cancel=None, budget=None):
        """Prepare bounded candidates OUTSIDE the writer lock; publish atomically.

        One encoder per store instance bounds local scratch; other connections may
        prepare concurrently. A bounded spool spills to the trusted store folder.
        Recheck all dependencies in the final write transaction. No eviction,
        history migration, async background writes or silent dependency fallback.
        Mutable input arrays must stay unchanged until this call returns.
        """
        history_roots = (self._history_roots(budget)
                         if getattr(self, '_w08_history_holds', None) is not None else ())
        if history_roots:
            _write_inputs = _history.Hold(_history.SESSION+_history.NUMERIC, *history_roots,
                                          category='w08-store-write-inputs')
        # Freeze metadata, not arbitrary object graphs or caller array payloads.
        if history_roots:
            encoded = _history.Hold(_history.ENCODE+_history.BODY, *history_roots,
                                     category='w08-store-metadata-bytes')
        meta_bytes = _json({} if metadata is None else metadata)
        if len(meta_bytes) > self.limits.max_manifest_bytes:
            raise StoreError('metadata exceeds limit')
        if history_roots:
            encoded.resize(64+len(meta_bytes))
            frozen_metadata = _history.Hold(_history.GRAPH+_history.PARSE, *history_roots,
                                             category='w08-store-metadata-freeze')
        metadata = _parse(meta_bytes)
        if history_roots:
            frozen_metadata.resize(_history.GRAPH)
        values = dict(arrays)
        for name in values:
            if type(name) is not str or not name or len(name) > 256:
                raise StoreError('short nonempty array names required')
        def check_cancel():
            if cancel is not None and cancel.is_set():
                from concurrent.futures import CancelledError
                raise CancelledError('storage preparation cancelled')
        # This is an estimated allocation envelope, not RSS or filesystem capacity.
        reference_count = 0
        # get() loads the whole snapshot and refuses totals above max_array_bytes, so publication refuses them too:
        # a record this store could not read back in full is never written. Referenced and edited arrays count at
        # their declared size (edits keep the dtype and shape).
        total = 0
        for value in values.values():
            if isinstance(value, (ArrayReference, _EditedReference)):
                ref = value.reference if isinstance(value, _EditedReference) else value
                with self._read_scope(budget=budget):
                    desc = self._reference_description(ref)
                reference_count += len(desc['chunks'])
                total += math.prod(desc['shape']) * _dtype(desc['dtype']).itemsize
            else:
                a = _array_view(value)
                width = self.limits.chunk_bytes // a.itemsize
                reference_count += (a.size + width - 1) // width
                total += a.nbytes
        if total > self.limits.max_array_bytes:
            raise StoreError('snapshot exceeds the full read limit (max_array_bytes); get() could not load it')
        if reference_count > min(self.limits.max_chunks, self.limits.max_manifest_bytes // 68):
            raise StoreError('too many chunks for the manifest budget')
        projected_manifest = len(meta_bytes) + reference_count * 128 + len(values) * 4096 + 1024
        work = self._write_work_bytes(reference_count,
                                      min(projected_manifest, self.limits.max_manifest_bytes))
        stage = (_history.retained_context(work, *history_roots, category='store-stage') if history_roots
                 else self._workspace(work, budget, category='store-stage'))
        with self._preparing, stage as _stage_funds, tempfile.SpooledTemporaryFile(
                max_size=self.limits.staging_memory_bytes, mode='w+b', dir=self.path.parent) as spool:
            check_cancel()
            started = time.perf_counter()
            descriptions = {}
            staged = set()
            staged_types = {}
            staged_bytes = 0
            dependencies = {}
            projected = 0

            def capture(value, dtype=None, count=None):
                nonlocal staged_bytes
                check_cancel()
                a = _array_view(value)
                dt = _dtype(a.dtype.str) if dtype is None else _dtype(dtype)
                raw = np.asarray(a, dtype=dt, order='C').tobytes()
                if dt.kind == 'f' and not np.isfinite(np.frombuffer(raw, dtype=dt)).all():
                    raise StoreError('nonfinite values are not supported scientific state')
                typed = (dt.str, len(raw) // dt.itemsize)
                desc = _json({'dtype': typed[0], 'count': typed[1]})
                key = self._blob_id(desc, raw)
                if key in staged:
                    return key
                # Existence is a hint, not verified authority. A cheap missing
                # lookup needs no retained read transaction; publication rechecks
                # races. Positive hits are authenticated in a pinned snapshot.
                with self._lock:
                    try:
                        exists = self._db.execute('SELECT 1 FROM chunks WHERE id=?', (key,)).fetchone()
                    except sqlite3.Error as exc:
                        raise _database_error(exc, 'storage preparation failed; no snapshot published') from exc
                if exists:
                    with self._read_scope() as hit_funds:
                        if self._chunk(key, expected_dtype=typed[0], expected_count=typed[1]) != raw:
                            raise StoreConflict('logical chunk identity conflict')
                        dependencies[key] = typed
                    del hit_funds
                    return key
                codec, payload = self._encode(raw, dt)
                stored = _hash(desc + b'\0' + codec.encode() + b'\0' + payload)
                header = _json([key, desc.decode(), codec, stored, len(payload)])
                addition = 4 + len(header) + len(payload)
                if staged_bytes + addition > self.limits.max_staging_bytes:
                    raise StoreError('encoded preparation exceeds staging budget')
                spool.write(struct.pack('<I', len(header))); spool.write(header); spool.write(payload)
                staged_bytes += addition
                self._stats['peak_prepared_bytes'] = max(self._stats['peak_prepared_bytes'], staged_bytes)
                staged.add(key)
                staged_types.setdefault(desc, typed)
                return key

            for name, value in sorted(values.items()):
                check_cancel()
                if isinstance(value, (ArrayReference, _EditedReference)):
                    ref = value.reference if isinstance(value, _EditedReference) else value
                    with self._read_scope():
                        original = self._reference_description(ref)
                    dt = _dtype(original['dtype'])
                    shape = original['shape']
                    ids = list(original['chunks'])
                    changes = dict(value.replacements) if isinstance(value, _EditedReference) else {}
                    projected += len(ids)
                    if projected > min(self.limits.max_chunks, self.limits.max_manifest_bytes // 68):
                        raise StoreError('too many chunks for the manifest budget')
                    width = self.limits.chunk_bytes // dt.itemsize
                    # A checked per-version attestation avoids rescanning unchanged
                    # payloads. Cold references verify each chunk at least once.
                    with self._read_scope():
                        for i, key in enumerate(ids):
                            if i in changes:
                                continue
                            count = min(width, math.prod(shape) - i * width)
                            self._chunk(key, expected_dtype=dt.str, expected_count=count, verify_only=True)
                            dependencies[key] = (dt.str, count)
                    for i, a in changes.items():
                        count = min(width, math.prod(shape) - i * width)
                        ids[i] = capture(a, dt.str, count)
                else:
                    a = _array_view(value)
                    dt, shape = _dtype(a.dtype.str), list(a.shape)
                    width = self.limits.chunk_bytes // dt.itemsize
                    projected += (a.size + width - 1) // width
                    if projected > min(self.limits.max_chunks, self.limits.max_manifest_bytes // 68):
                        raise StoreError('too many chunks for the manifest budget')
                    ids = []
                    # C-order views avoid a temporary chunk copy before capture's
                    # detached bytes. Strided arrays keep bounded flat slicing.
                    flat = np.asarray(a).reshape(-1) if a.flags.c_contiguous else a.flat
                    for start in range(0, a.size, width):
                        ids.append(capture(flat[start:start+width]))
                descriptions[name] = {'dtype': dt.str, 'shape': list(shape), 'chunks': ids}
                if len(meta_bytes) + projected * 68 + len(descriptions) * 256 > self.limits.max_manifest_bytes:
                    raise StoreError('projected manifest exceeds limit')
            manifest = {'schema': _SCHEMA, 'invocation': invocation,
                        'arrays': descriptions, 'metadata': metadata}
            if history_roots:
                manifest_bytes = _history.Hold(_history.ENCODE+_history.BODY, *history_roots,
                                                category='w08-store-manifest-encode')
            body = _json(manifest)
            if len(body) > self.limits.max_manifest_bytes:
                raise StoreError('manifest exceeds limit')
            if history_roots:
                manifest_bytes.resize(64+len(body))
            self._stats['staged_bytes'] = staged_bytes
            self._stats['prepare_seconds'] += time.perf_counter() - started
            check_cancel()
            spool.seek(0)
            with self._lock:
                self._live()
                writer_start = time.perf_counter()
                try:
                    self._db.execute('BEGIN IMMEDIATE')
                    with self._read_scope():
                        for key, (dtype, count) in dependencies.items():
                            self._chunk(key, expected_dtype=dtype, expected_count=count, verify_only=True)
                    for name, value in values.items():
                        if isinstance(value, (ArrayReference, _EditedReference)):
                            self._reference_description(value.reference if isinstance(value, _EditedReference) else value)
                    if history_roots:
                        previous_funds = _history.ManifestFunds(*history_roots)
                        with _history.bind(self, '_w08_history_read', previous_funds):
                            previous = self._manifest(invocation)
                    else:
                        previous = self._manifest(invocation)
                    if previous is not None and (
                            {k: v for k, v in previous.items() if k != 'execution_mode'} !=
                            {k: v for k, v in manifest.items() if k != 'execution_mode'}):
                        raise _SnapshotConflict('same invocation produced different data or metadata')
                    # The write lock is held and nothing is inserted yet: if the pin still equals the one recorded
                    # at this connection's last publication, the tables hold exactly the total recorded with it.
                    pin = self._retained_pin()
                    known = self._retained
                    base = known[1] if known is not None and known[0] == pin else None
                    added, rows = 0, 0                # bytes and rows this transaction inserts, as the scan counts
                    batch, batch_bytes = [], 0
                    def flush():
                        nonlocal batch, batch_bytes, added, rows
                        if batch:
                            self._db.executemany('INSERT INTO chunks VALUES(?,?,?,?,?)', batch)
                            for key, desc, _, _, payload in batch:
                                self._remember(key, *staged_types[desc])
                                added += len(payload) + len(desc) + 128
                            rows += len(batch)
                            self._stats['insert_batches'] += 1
                            batch, batch_bytes = [], 0
                    while True:
                        check_cancel()
                        prefix = spool.read(4)
                        if not prefix:
                            break
                        length = struct.unpack('<I', prefix)[0]
                        key, desc, codec, stored, count = _parse(spool.read(length))
                        desc = desc.encode()
                        payload = spool.read(count)
                        exists = self._db.execute('SELECT 1 FROM chunks WHERE id=?', (key,)).fetchone()
                        if exists:
                            # A concurrent writer may have published a different
                            # lossless encoding of the same logical chunk.
                            dtype, count_typed = staged_types[desc]
                            expected = self._decode(codec, payload, _dtype(dtype), count_typed)
                            if self._chunk(key, expected_dtype=dtype, expected_count=count_typed) != expected:
                                raise StoreConflict('concurrent chunk identity conflict')
                        else:
                            if batch and batch_bytes + count > self.limits.insert_batch_bytes:
                                flush()
                            batch.append((key, desc, codec, stored, payload)); batch_bytes += count
                    flush()
                    insert_snapshot = previous is None
                    if history_roots:
                        del previous, previous_funds
                    if insert_snapshot:
                        self._db.execute('INSERT INTO snapshots VALUES(?,?,?)', (invocation, body, _hash(body)))
                        added += len(body) + 128
                        rows += 1
                    # Blobs are bound as bytes, so length() is len(); every counted row is one of ours.
                    exact = base is not None and self._db.total_changes == pin[1] + rows
                    if exact:
                        used = base + added
                    else:
                        used = self._db.execute('SELECT COALESCE(sum(length(payload)+length(descriptor)+128),0) FROM chunks').fetchone()[0]
                        used += self._db.execute('SELECT COALESCE(sum(length(body)+128),0) FROM snapshots').fetchone()[0]
                        # A scanned total is kept only beside the store's own schema (no trigger or view).
                        exact = set(self._db.execute('SELECT type, name, tbl_name, sql FROM sqlite_master')) == _SCHEMA_OBJECTS
                    if used > self.limits.max_store_bytes:
                        raise StoreError('retained records exceed store budget')
                    inserted = self._db.total_changes
                    check_cancel()
                    if publication_check is not None:
                        publication_check()
                    self._db.execute('COMMIT')
                    # Our transaction added immutable rows only; retain validated
                    # attestations. data_version is NOT refreshed here: a writer
                    # committing immediately after ours must invalidate next read.
                    self._cache_changes = self._db.total_changes
                    # Our own commit leaves data_version unchanged; a later commit by anyone else changes it.
                    self._retained = (((pin[0], inserted, pin[2]), used)
                                      if exact and self._db.total_changes == inserted else None)
                except BaseException as exc:
                    self._retained = None
                    if self._db.in_transaction:
                        self._db.execute('ROLLBACK')
                    self._clear_caches()
                    if isinstance(exc, sqlite3.Error):
                        raise _database_error(exc, 'storage transaction failed; no snapshot published') from exc
                    raise
                finally:
                    self._stats['writer_seconds'] += time.perf_counter() - writer_start
        return invocation

    def contains(self, invocation):
        """Manifest existence only; get() verifies all referenced payloads."""
        with self._read_scope():
            return self._manifest(invocation) is not None

    def change_token(self):
        """An opaque value, read in one pinned snapshot, that changes whenever the database may have changed.

        PRAGMA data_version changes when another connection commits; total_changes when rows are inserted, updated or
        deleted through this one (schema changes made directly through this connection are not counted). Equal tokens
        mean nothing was written in between through those channels; a changed token means only that something may
        have been. Out-of-band raw file changes are not covered, as for the store's own caches.
        """
        with self._read_scope():
            return self._db.execute('PRAGMA data_version').fetchone()[0], self._db.total_changes

    def metadata(self, invocation):
        holds = getattr(self, '_w08_history_holds', None)
        scope = self._read_scope() if holds is None else self._read_scope(_history_manifest=True)
        with scope as funding:
            m = self._manifest(invocation)
            if m is not None and funding is not None:
                holds.append(funding.graph)
            return None if m is None else m['metadata']

    def read_chunk(self, invocation, array_name, index, *, budget=None):
        """Random access to one decoded chunk, with its flat element offset."""
        with self._read_scope(budget=budget):
            m = self._manifest(invocation)
            if m is None:
                raise KeyError(invocation)
            a = m['arrays'][array_name]
            if index >= len(a['chunks']):
                raise IndexError(index)
            dt = _dtype(a['dtype'])
            width = self.limits.chunk_bytes // dt.itemsize
            count = min(width, math.prod(a['shape']) - index * width)
            raw = cast(bytes, self._chunk(a['chunks'][index], expected_dtype=dt.str, expected_count=count))
            return index * width, np.frombuffer(raw, dtype=dt)

    def iter_chunks(self, invocation, array_name, *, budget=None):
        """Yield (flat start, detached immutable typed chunk); no full array load."""
        with self._workspace(4 * self.limits.max_manifest_bytes, budget,
                             category="stream-manifest"):
            yield from self._iter_chunks(invocation, array_name, budget=budget)

    def _iter_chunks(self, invocation, array_name, *, budget):
        with self._read_scope(budget=budget):
            m = cast(dict, self._manifest(invocation))
            a = m['arrays'][array_name]
        dt, total = _dtype(a['dtype']), math.prod(a['shape'])
        width = self.limits.chunk_bytes // dt.itemsize
        for i, key in enumerate(a['chunks']):
            with self._read_scope(budget=budget):
                raw = cast(bytes, self._chunk(key, expected_dtype=dt.str,
                                  expected_count=min(width, total-i*width)))
            yield i * width, np.frombuffer(raw, dtype=dt)

    def get(self, invocation, *, budget: WorkBudget | None = None):
        """One stable read snapshot, one manifest parse, bounded chunk decoding."""
        return self._restore_snapshot(invocation, budget=budget)

    def _restore_snapshot(self, invocation, *, budget=None, evidence=False):
        holds = getattr(self, '_w08_history_holds', None)
        scope = (self._read_scope(budget=budget) if holds is None
                 else self._read_scope(budget=budget, _history_manifest=True))
        with scope as funding:
            m = self._manifest(invocation)
            if m is None:
                return None
            total = sum(math.prod(a['shape']) * _dtype(a['dtype']).itemsize for a in m['arrays'].values())
            if total > self.limits.max_array_bytes:
                raise StoreError('full result exceeds read limit; use iter_chunks')
            output = (self._workspace(2*total, budget, category='store-output') if funding is None
                      else _history.retained_context(2*total, *funding.roots, category='store-output'))
            with output as output_funds:
                if funding is not None:
                    array_headers = _history.Hold(8192+768*len(m['arrays']), *funding.roots,
                                                  category='w08-store-returned-array-headers')
                    if any(a['chunks'] for a in m['arrays'].values()):
                        funding.before_chunks(8*self.limits.chunk_bytes+self.limits.codec_workspace_bytes)
                result = {}
                buffer = raw = None
                for name, a in m['arrays'].items():
                    dt = _dtype(a['dtype'])
                    count = math.prod(a['shape'])
                    width = self.limits.chunk_bytes // dt.itemsize
                    buffer = bytearray(count * dt.itemsize)
                    for i, key in enumerate(a['chunks']):
                        start = i * width
                        raw = cast(bytes, self._chunk(key, expected_dtype=dt.str, expected_count=min(width, count-start)))
                        buffer[start*dt.itemsize:start*dt.itemsize+len(raw)] = raw
                    result[name] = np.frombuffer(bytes(buffer), dtype=dt).reshape(a['shape'])
                if funding is not None:
                    del buffer, raw
                    output_funds.resize(total)
                    holds.extend((output_funds, array_headers))
                    if evidence:
                        holds.append(funding.graph)
                if evidence:
                    return result, m['metadata']
                return result

    def statistics(self):
        with self._read_scope():
            row = self._db.execute('SELECT count(*),COALESCE(sum(length(payload)),0) FROM chunks').fetchone()
            return {'unique_chunks': row[0], 'encoded_payload_bytes': row[1],
                    'snapshots': self._db.execute('SELECT count(*) FROM snapshots').fetchone()[0],
                    'database_bytes': self.path.stat().st_size,
                    'decoded_cache_bytes': self._cached_bytes,
                    'verified_cache_entries': len(self._verified),
                    'operations': dict(self._stats),
                    'resource_allowances': self.resource_requirements(),
                    'shared_budget': self._budget.statistics()}

    def backup_to(self, destination):
        """Consistent database backup to a new local file; no overwrite or cleanup."""
        import os
        target = Path(destination).absolute()
        _path(target)
        with self._lock:
            self._live()
            fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            os.close(fd)
            other = sqlite3.connect(target)
            try:
                self._db.backup(other)
            finally:
                other.close()
        return target
