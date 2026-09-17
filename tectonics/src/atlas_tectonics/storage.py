"""Bounded local, lossless array snapshots with content-addressed chunk reuse.

SQLite owns transactions/locking and packs blobs into one file. No pickle, history
migration, garbage collection, lossy conversion, or network store. Caller owns the
local directory (not hostile). SHA-256 detects corruption, not an authorised
attacker who can replace both data and hashes. Numerical meaning stays in the
invocation metadata; equal payloads may be shared across different invocations.
"""
from __future__ import annotations

from collections import OrderedDict
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3
import struct
import threading
import tempfile
import time
from typing import Mapping

import numpy as np

from .resources import WorkBudget, select_budget, reserve_budgets


class StoreError(ValueError):
    """Corrupt, incompatible, unsafe or over-budget storage; never a cache miss."""


class StoreConflict(StoreError):
    """One immutable scientific identity was assigned conflicting results."""


_SHA = re.compile(r'[0-9a-f]{64}\Z')
_SCHEMA = 'atlas.array-store.v1'


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


def _sha(key):
    if type(key) is not str or _SHA.fullmatch(key) is None:
        raise StoreError('a lowercase SHA-256 identity is required')
    return key


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
        if self.chunk_bytes < 8 or self.chunk_bytes > 16 * 1024 * 1024:
            raise StoreError('chunk_bytes must be between 8 bytes and 16 MiB')
        if self.sqlite_cache_bytes < 1024:
            raise StoreError('SQLite cache allowance must be at least 1 KiB')
        if self.max_store_bytes < 65536:
            raise StoreError('store budget must accommodate at least 64 KiB')
        if type(self.decoded_cache_bytes) is not int or self.decoded_cache_bytes < 0:
            raise StoreError('decoded cache budget must be nonnegative')


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
    if name not in profiles:
        raise StoreError('profile must be fast, balanced or compact')
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
    if np.ma.isMaskedArray(value) or not isinstance(value, np.ndarray):
        raise StoreError('supply explicit unmasked NumPy arrays')
    _dtype(value.dtype.str)
    if value.ndim > 16:
        raise StoreError('at most 16 dimensions are supported')
    return value


def _path(path):
    # Refuse static links/reparse points, including directory ancestors.
    for p in (path, *path.parents):
        if p.exists() or p.is_symlink():
            st = p.lstat()
            if p.is_symlink() or getattr(st, 'st_file_attributes', 0) & 0x400:
                raise StoreError('linked/reparse store paths are forbidden')
            if p == path and p.is_file() and st.st_nlink != 1:
                raise StoreError('hard-linked database is forbidden')


class ArrayStore:
    """One connection, serialised operations; separate processes use SQLite locks.

    Use on a local filesystem. max_store_bytes bounds database pages and logical
    retained records; reserve up to another database-sized rollback journal on disk.
    max_array_bytes bounds a fully loaded snapshot, not merely one output field.
    iter_chunks reads independent chunks without materialising the full snapshot.
    Caller must not mutate inputs during put(). No implicit eviction of snapshots.
    Preparation uses a finite spool: staging_memory_bytes plus at most one chunk
    transiently before spilling, and max_staging_bytes of temporary storage. Decoder
    and palette workspace are charged separately. New codecs read old v1 records;
    older implementations refuse new codec labels rather than misreading them.
    """
    def __init__(self, path, limits: StoreLimits, compression: Compression = Compression(), *, budget=None):
        if not isinstance(limits, StoreLimits) or not isinstance(compression, Compression):
            raise StoreError('typed limits and compression required')
        self.path = Path(path).absolute()
        self.limits = limits
        self.compression = compression
        _path(self.path)
        if not self.path.parent.is_dir():
            raise StoreError('create the dedicated store directory explicitly')
        for suffix in ('-journal', '-wal', '-shm'):
            _path(Path(str(self.path) + suffix))
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
        except BaseException:
            self._resident_reservation.__exit__(None, None, None)
            raise
        try:
            self._db.execute('PRAGMA journal_mode=DELETE')
            self._db.execute('PRAGMA synchronous=FULL')
            self._db.execute('PRAGMA trusted_schema=OFF')
            self._db.execute('PRAGMA foreign_keys=ON')
            self._db.execute(f'PRAGMA cache_size=-{max(1, limits.sqlite_cache_bytes // 1024)}')
            page = self._db.execute('PRAGMA page_size').fetchone()[0]
            max_pages = limits.max_store_bytes // page
            current = self._db.execute('PRAGMA page_count').fetchone()[0]
            if current > max_pages:
                raise StoreError('existing database exceeds store budget')
            self._db.execute(f'PRAGMA max_page_count={max_pages}')
            existing = {r[0] for r in self._db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if existing and existing != {'settings', 'chunks', 'snapshots'}:
                raise StoreError('refusing to modify an unrelated database')
            self._db.execute('BEGIN IMMEDIATE')
            self._db.execute('CREATE TABLE IF NOT EXISTS settings (id INTEGER PRIMARY KEY CHECK(id=1), body BLOB NOT NULL)')
            wanted = _json({'schema': _SCHEMA, 'chunk_bytes': limits.chunk_bytes})
            row = self._db.execute('SELECT body FROM settings WHERE id=1').fetchone()
            if row and row[0] != wanted:
                raise StoreError('incompatible store schema or chunk size')
            self._db.execute('INSERT OR IGNORE INTO settings VALUES(1,?)', (wanted,))
            self._db.execute('CREATE TABLE IF NOT EXISTS chunks (id TEXT PRIMARY KEY, descriptor BLOB NOT NULL, codec TEXT NOT NULL, stored_sha TEXT NOT NULL, payload BLOB NOT NULL)')
            self._db.execute('CREATE TABLE IF NOT EXISTS snapshots (id TEXT PRIMARY KEY, body BLOB NOT NULL, digest TEXT NOT NULL)')
            self._db.execute('COMMIT')
        except BaseException:
            if self._db.in_transaction:
                self._db.execute('ROLLBACK')
            self._db.close()
            self._resident_reservation.__exit__(None, None, None)
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
        if self._closed:
            raise StoreError('store is closed')
        _path(self.path)

    @contextmanager
    def _read_scope(self, *, budget=None):
        """Pin one SQLite snapshot before trusting validated in-memory payloads.

        data_version catches other connections; total_changes catches direct SQL
        on this connection. Neither is a file-timestamp identity. Only successful
        verification in this snapshot may bypass repeated reads. Out-of-band raw
        file changes and malicious control of this process are not supported.
        """
        with self._lock:
            self._live()
            owner = not self._db.in_transaction
            reservation = None
            if owner:
                reservation = self._workspace(self._read_work_bytes(), budget,
                                              category="store-read")
                reservation.__enter__()
            try:
                if owner:
                    self._db.execute('BEGIN')
                # Touch a table to acquire a stable read view before data_version.
                settings = self._db.execute('SELECT body FROM settings WHERE id=1').fetchone()
                wanted = _json({'schema': _SCHEMA, 'chunk_bytes': self.limits.chunk_bytes})
                if settings is None or settings[0] != wanted:
                    raise StoreError('store settings changed during use')
                version = self._db.execute('PRAGMA data_version').fetchone()[0]
                changes = self._db.total_changes
                if version != self._cache_version or changes != self._cache_changes:
                    self._clear_caches()
                    self._cache_version, self._cache_changes = version, changes
                yield
            except sqlite3.Error as exc:
                raise StoreError('storage read transaction failed') from exc
            finally:
                try:
                    if owner and self._db.in_transaction:
                        self._db.execute('ROLLBACK')
                finally:
                    if reservation is not None:
                        reservation.__exit__(None, None, None)

    def _remember(self, key, desc, stored):
        self._verified[key] = (desc, stored)
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
        self._stats['encodes'] += 1
        width = dt.itemsize
        words = np.frombuffer(raw, dtype=f'<u{width}')
        if np.all(words == words[0]):
            return 'uniform', raw[:width]
        best = ('raw', raw)
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
                if len(candidate[1]) < len(best[1]):
                    best = candidate
            if self.compression.categorical == 'auto':
                starts = np.concatenate(([0], np.flatnonzero(a[1:] != a[:-1]) + 1))
                if 4 + starts.size * (4 + width) < len(best[1]):
                    runs = np.empty(starts.size, dtype=[('count', '<u4'), ('value', dt)])
                    runs['count'] = np.diff(np.append(starts, a.size))
                    runs['value'] = a[starts]
                    best = ('rle-v1', struct.pack('<I', starts.size) + runs.tobytes())
        if self.compression.codec == 'zstd':
            b = self._blosc
            filters = [b.Filter.NOFILTER] * 5 + [
                {'none': b.Filter.NOFILTER, 'byte': b.Filter.SHUFFLE,
                 'bit': b.Filter.BITSHUFFLE}[self.compression.shuffle]]
            encoded = b.compress2(raw, codec=b.Codec.ZSTD, clevel=self.compression.level,
                                 typesize=width, nthreads=1, filters=filters,
                                 use_dict=self.compression.use_dict)
            if len(encoded) < len(best[1]):
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
            if len(payload) != dt.itemsize:
                raise StoreError('invalid uniform record')
            raw = payload * count
        elif codec == 'palette8':
            if dt.kind not in 'biu' or len(payload) < 4:
                raise StoreError('invalid palette type')
            n = struct.unpack('<I', payload[:4])[0]
            cut = 4 + n * dt.itemsize
            if not 1 < n <= 256 or len(payload) != cut + count:
                raise StoreError('invalid palette dimensions')
            palette = np.frombuffer(payload, dtype=dt, offset=4, count=n)
            indices = np.frombuffer(payload, dtype='u1', offset=cut)
            if indices.size and int(indices.max()) >= n:
                raise StoreError('invalid palette index')
            raw = palette[indices].tobytes()
        elif codec == 'palette-packed-v1':
            if dt.kind not in 'biu' or len(payload) < 3:
                raise StoreError('invalid packed palette type/header')
            n, bits = struct.unpack('<HB', payload[:3])
            if bits not in (1, 2, 4, 8) or not 1 < n <= (1 << bits):
                raise StoreError('invalid packed palette dimensions')
            cut = 3 + n * dt.itemsize
            packed_bytes = (count * bits + 7) // 8
            if len(payload) != cut + packed_bytes:
                raise StoreError('invalid packed palette length')
            palette = np.frombuffer(payload, dtype=dt, offset=3, count=n)
            packed = np.frombuffer(payload, dtype='u1', offset=cut)
            if count * bits % 8 and int(packed[-1]) >> (count * bits % 8):
                raise StoreError('nonzero palette padding')
            indices = np.empty(count, dtype='u1')
            per_byte = 8 // bits
            for lane in range(per_byte):
                size = indices[lane::per_byte].size
                indices[lane::per_byte] = (packed[:size] >> (lane * bits)) & ((1 << bits) - 1)
            if np.any(indices >= n):
                raise StoreError('invalid packed palette index')
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
        _sha(key)
        known = self._verified.get(key)
        if known is not None:
            desc, _ = known
            meta = _parse(desc)
            if expected_dtype is not None and (meta['dtype'] != expected_dtype or meta['count'] != expected_count):
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
        row = self._db.execute('SELECT length(descriptor),length(payload),length(codec),length(stored_sha) FROM chunks WHERE id=?', (key,)).fetchone()
        if row is None:
            raise StoreError('snapshot has a missing chunk')
        if row[0] > 256 or row[1] > self.limits.chunk_bytes + 4096 or row[2] > 128 or row[3] != 64:
            raise StoreError('oversized chunk record')
        desc, codec, stored, payload = self._db.execute('SELECT descriptor,codec,stored_sha,payload FROM chunks WHERE id=?', (key,)).fetchone()
        self._stats['payload_reads'] += 1
        if _hash(desc + b'\0' + codec.encode() + b'\0' + payload) != stored:
            raise StoreError('stored chunk checksum mismatch')
        meta = _parse(desc)
        if set(meta) != {'dtype', 'count'} or type(meta['count']) is not int:
            raise StoreError('invalid chunk descriptor')
        dt, count = _dtype(meta['dtype']), meta['count']
        if dt.str != meta['dtype'] or not 0 < count * dt.itemsize <= self.limits.chunk_bytes:
            raise StoreError('invalid typed chunk size')
        if expected_dtype is not None and (dt.str != expected_dtype or count != expected_count):
            raise StoreError('chunk does not match manifest')
        raw = self._decode(codec, payload, dt, count)
        if self._blob_id(desc, raw) != key:
            raise StoreError('logical chunk checksum mismatch')
        self._remember(key, desc, stored)
        self._remember_raw(key, raw)
        return None if verify_only else raw

    def _manifest(self, key):
        _sha(key)
        row = self._db.execute('SELECT length(body) FROM snapshots WHERE id=?', (key,)).fetchone()
        if row is None:
            return None
        if row[0] > self.limits.max_manifest_bytes:
            raise StoreError('oversized manifest')
        body, digest = self._db.execute('SELECT body,digest FROM snapshots WHERE id=?', (key,)).fetchone()
        if _hash(body) != digest:
            raise StoreError('manifest checksum mismatch')
        m = _parse(body)
        if not isinstance(m, dict) or set(m) != {'schema','invocation','arrays','metadata'} or m['schema'] != _SCHEMA or m['invocation'] != key:
            raise StoreError('incompatible manifest')
        if not isinstance(m['arrays'], dict) or not m['arrays']:
            raise StoreError('invalid array inventory')
        chunks = 0
        for name, a in m['arrays'].items():
            if not isinstance(a, dict) or set(a) != {'dtype','shape','chunks'}:
                raise StoreError('invalid array description')
            dt = _dtype(a['dtype'])
            shape = a['shape']
            if not isinstance(shape, list) or len(shape) > 16 or any(type(n) is not int or n < 0 for n in shape):
                raise StoreError('invalid saved shape')
            count = math.prod(shape)
            if count * dt.itemsize > self.limits.max_array_bytes:
                raise StoreError('declared array exceeds decoder limit')
            width = self.limits.chunk_bytes // dt.itemsize
            ids = a['chunks']
            if not isinstance(ids, list) or len(ids) != (count + width - 1) // width:
                raise StoreError('invalid chunk inventory')
            chunks += len(ids)
            for chunk in ids:
                _sha(chunk)
        if chunks > self.limits.max_chunks:
            raise StoreError('too many chunk references')
        return m

    def reference(self, invocation: str, array_name: str) -> ArrayReference:
        """Return a checked reference; no array payload is materialised here."""
        with self._read_scope():
            m = self._manifest(invocation)
            if m is None or array_name not in m['arrays']:
                raise KeyError((invocation, array_name))
            return ArrayReference(str(self.path), invocation, array_name,
                                  _hash(_json(m['arrays'][array_name])))

    def put_incremental(self, invocation, parent, replacements, metadata=None, *,
                        publication_check=None, cancel=None, budget=None):
        """Replace named COMPLETE chunks; unspecified chunks come from the parent.

        No dirty flags are accepted. Retained data are the parent's actual stored
        chunks, never bytes from a caller's allegedly unchanged array. The new
        manifest directly references payloads, so it is not a temporal delta chain.
        """
        if (not isinstance(replacements, Mapping)
                or any(not isinstance(parts, Mapping) for parts in replacements.values())):
            raise StoreError('chunk replacements must map array names to chunk mappings')
        with self._read_scope():
            m = self._manifest(parent)
            if m is None:
                raise KeyError(parent)
            if any(name not in m['arrays'] for name in replacements):
                raise StoreError('replacement array is absent from parent')
            arrays = {}
            for name, desc in m['arrays'].items():
                ref = ArrayReference(str(self.path), parent, name, _hash(_json(desc)))
                arrays[name] = _EditedReference(ref, dict(replacements.get(name, {})))
            if metadata is None:
                metadata = m['metadata']
        return self.put(invocation, arrays, metadata, publication_check=publication_check,
                        cancel=cancel, budget=budget)

    def _reference_description(self, ref):
        if not isinstance(ref, ArrayReference) or ref.store_path != str(self.path):
            raise StoreError('reference must belong to this store')
        _sha(ref.invocation)
        _sha(ref.descriptor_sha256)
        if type(ref.array_name) is not str or not ref.array_name or len(ref.array_name) > 256:
            raise StoreError('invalid referenced array name')
        m = self._manifest(ref.invocation)
        if m is None or ref.array_name not in m['arrays']:
            raise StoreError('referenced array is missing')
        desc = m['arrays'][ref.array_name]
        if _hash(_json(desc)) != ref.descriptor_sha256:
            raise StoreError('referenced manifest changed')
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
        _sha(invocation)
        if publication_check is not None and not callable(publication_check):
            raise StoreError('publication_check must be callable')
        if not isinstance(arrays, Mapping) or not arrays:
            raise StoreError('nonempty array mapping required')
        # Freeze metadata, not arbitrary object graphs or caller array payloads.
        meta_bytes = _json({} if metadata is None else metadata)
        if len(meta_bytes) > self.limits.max_manifest_bytes:
            raise StoreError('metadata exceeds limit')
        metadata = _parse(meta_bytes)
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
        for value in values.values():
            if isinstance(value, (ArrayReference, _EditedReference)):
                ref = value.reference if isinstance(value, _EditedReference) else value
                with self._read_scope(budget=budget):
                    reference_count += len(self._reference_description(ref)['chunks'])
            else:
                a = _array_view(value)
                if a.nbytes > self.limits.max_array_bytes:
                    raise StoreError('array exceeds storage input limit')
                width = self.limits.chunk_bytes // a.itemsize
                reference_count += (a.size + width - 1) // width
        if reference_count > min(self.limits.max_chunks, self.limits.max_manifest_bytes // 68):
            raise StoreError('too many chunks for the manifest budget')
        projected_manifest = len(meta_bytes) + reference_count * 128 + len(values) * 4096 + 1024
        work = self._write_work_bytes(reference_count,
                                      min(projected_manifest, self.limits.max_manifest_bytes))
        with self._preparing, self._workspace(work, budget, category="store-stage"), tempfile.SpooledTemporaryFile(
                max_size=self.limits.staging_memory_bytes, mode='w+b', dir=self.path.parent) as spool:
            check_cancel()
            started = time.perf_counter()
            descriptions = {}
            staged = set()
            staged_bytes = 0
            dependencies = {}
            projected = 0

            def capture(value, dtype=None, count=None):
                nonlocal staged_bytes
                check_cancel()
                a = _array_view(value)
                dt = _dtype(a.dtype.str) if dtype is None else _dtype(dtype)
                if dtype is not None and (a.dtype.kind != dt.kind or a.itemsize != dt.itemsize or a.shape != (count,)):
                    raise StoreError('replacement chunk requires exact dtype and flat length')
                raw = np.asarray(a, dtype=dt, order='C').tobytes()
                if dt.kind == 'f' and not np.isfinite(np.frombuffer(raw, dtype=dt)).all():
                    raise StoreError('nonfinite values are not supported scientific state')
                desc = _json({'dtype': dt.str, 'count': len(raw) // dt.itemsize})
                key = self._blob_id(desc, raw)
                if key in staged:
                    return key
                # Existence is a hint, not verified authority. A cheap missing
                # lookup needs no retained read transaction; publication rechecks
                # races. Positive hits are authenticated in a pinned snapshot.
                with self._lock:
                    if self._closed:
                        raise StoreError('store is closed')
                    exists = self._db.execute('SELECT 1 FROM chunks WHERE id=?', (key,)).fetchone()
                if exists:
                    with self._read_scope():
                        if self._chunk(key, expected_dtype=dt.str, expected_count=len(raw)//dt.itemsize) != raw:
                            raise StoreConflict('logical chunk identity conflict')
                        dependencies[key] = desc
                        return key
                codec, payload = self._encode(raw, dt)
                # Attest logical equality once, outside the writer transaction.
                # Future references must not trust an unchecked encoder output.
                if self._decode(codec, payload, dt, len(raw)//dt.itemsize) != raw:
                    raise StoreError('encoder did not preserve typed payload')
                stored = _hash(desc + b'\0' + codec.encode() + b'\0' + payload)
                header = _json([key, desc.decode(), codec, stored, len(payload)])
                addition = 4 + len(header) + len(payload)
                if staged_bytes + addition > self.limits.max_staging_bytes:
                    raise StoreError('encoded preparation exceeds staging budget')
                spool.write(struct.pack('<I', len(header))); spool.write(header); spool.write(payload)
                staged_bytes += addition
                self._stats['peak_prepared_bytes'] = max(self._stats['peak_prepared_bytes'], staged_bytes)
                staged.add(key)
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
                    if any(type(i) is not int or not 0 <= i < len(ids) for i in changes):
                        raise StoreError('replacement chunk index outside array')
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
                            dependencies[key] = _json({'dtype': dt.str, 'count': count})
                    for i, a in changes.items():
                        count = min(width, math.prod(shape) - i * width)
                        ids[i] = capture(a, dt.str, count)
                else:
                    a = _array_view(value)
                    if a.nbytes > self.limits.max_array_bytes:
                        raise StoreError('array exceeds storage input limit')
                    dt, shape = _dtype(a.dtype.str), list(a.shape)
                    width = self.limits.chunk_bytes // dt.itemsize
                    projected += (a.size + width - 1) // width
                    if projected > min(self.limits.max_chunks, self.limits.max_manifest_bytes // 68):
                        raise StoreError('too many chunks for the manifest budget')
                    ids = []
                    for start in range(0, a.size, width):
                        # Only one flat chunk copied, including strided caller data.
                        ids.append(capture(a.flat[start:start+width]))
                descriptions[name] = {'dtype': dt.str, 'shape': list(shape), 'chunks': ids}
                if len(meta_bytes) + projected * 68 + len(descriptions) * 256 > self.limits.max_manifest_bytes:
                    raise StoreError('projected manifest exceeds limit')
            body = _json({'schema': _SCHEMA, 'invocation': invocation,
                          'arrays': descriptions, 'metadata': metadata})
            if len(body) > self.limits.max_manifest_bytes:
                raise StoreError('manifest exceeds limit')
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
                        for key, desc in dependencies.items():
                            meta = _parse(desc)
                            self._chunk(key, expected_dtype=meta['dtype'], expected_count=meta['count'], verify_only=True)
                    for name, value in values.items():
                        if isinstance(value, (ArrayReference, _EditedReference)):
                            self._reference_description(value.reference if isinstance(value, _EditedReference) else value)
                    previous = self._manifest(invocation)
                    if previous is not None and _json(previous) != body:
                        raise StoreConflict('same invocation produced different data or metadata')
                    batch, batch_bytes = [], 0
                    def flush():
                        nonlocal batch, batch_bytes
                        if batch:
                            self._db.executemany('INSERT INTO chunks VALUES(?,?,?,?,?)', batch)
                            for key, desc, _, stored, _ in batch:
                                self._remember(key, desc, stored)
                            self._stats['insert_batches'] += 1
                            batch, batch_bytes = [], 0
                    while True:
                        check_cancel()
                        prefix = spool.read(4)
                        if not prefix:
                            break
                        if len(prefix) != 4:
                            raise StoreError('truncated preparation record')
                        length = struct.unpack('<I', prefix)[0]
                        if not 0 < length < 2048:
                            raise StoreError('invalid preparation record')
                        key, desc, codec, stored, count = _parse(spool.read(length))
                        desc = desc.encode()
                        if not 0 <= count <= self.limits.chunk_bytes + 4096:
                            raise StoreError('invalid staged payload length')
                        payload = spool.read(count)
                        if len(payload) != count or _hash(desc+b'\0'+codec.encode()+b'\0'+payload) != stored:
                            raise StoreError('preparation checksum mismatch')
                        exists = self._db.execute('SELECT 1 FROM chunks WHERE id=?', (key,)).fetchone()
                        if exists:
                            # A concurrent writer may have published a different
                            # lossless encoding of the same logical chunk.
                            meta = _parse(desc)
                            expected = self._decode(codec, payload, _dtype(meta['dtype']), meta['count'])
                            if self._chunk(key, expected_dtype=meta['dtype'], expected_count=meta['count']) != expected:
                                raise StoreConflict('concurrent chunk identity conflict')
                        else:
                            if batch and batch_bytes + count > self.limits.insert_batch_bytes:
                                flush()
                            batch.append((key, desc, codec, stored, payload)); batch_bytes += count
                    flush()
                    if previous is None:
                        self._db.execute('INSERT INTO snapshots VALUES(?,?,?)', (invocation, body, _hash(body)))
                    used = self._db.execute('SELECT COALESCE(sum(length(payload)+length(descriptor)+128),0) FROM chunks').fetchone()[0]
                    used += self._db.execute('SELECT COALESCE(sum(length(body)+128),0) FROM snapshots').fetchone()[0]
                    if used > self.limits.max_store_bytes:
                        raise StoreError('retained records exceed store budget')
                    check_cancel()
                    if publication_check is not None:
                        publication_check()
                    self._db.execute('COMMIT')
                    # Our transaction added immutable rows only; retain validated
                    # attestations. data_version is NOT refreshed here: a writer
                    # committing immediately after ours must invalidate next read.
                    self._cache_changes = self._db.total_changes
                except BaseException as exc:
                    if self._db.in_transaction:
                        self._db.execute('ROLLBACK')
                    self._clear_caches()
                    if isinstance(exc, sqlite3.Error):
                        raise StoreError('storage transaction failed; no snapshot published') from exc
                    raise
                finally:
                    self._stats['writer_seconds'] += time.perf_counter() - writer_start
        return invocation

    def contains(self, invocation):
        """Manifest existence only; get() verifies all referenced payloads."""
        with self._read_scope():
            return self._manifest(invocation) is not None

    def metadata(self, invocation):
        with self._read_scope():
            m = self._manifest(invocation)
            return None if m is None else m['metadata']

    def read_chunk(self, invocation, array_name, index, *, budget=None):
        """Random access to one decoded chunk, with its flat element offset."""
        if type(index) is not int or index < 0:
            raise StoreError('chunk index must be a nonnegative integer')
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
            raw = self._chunk(a['chunks'][index], expected_dtype=dt.str, expected_count=count)
            return index * width, np.frombuffer(raw, dtype=dt)

    def iter_chunks(self, invocation, array_name, *, budget=None):
        """Yield (flat start, detached immutable typed chunk); no full array load."""
        with self._workspace(4 * self.limits.max_manifest_bytes, budget,
                             category="stream-manifest"):
            yield from self._iter_chunks(invocation, array_name, budget=budget)

    def _iter_chunks(self, invocation, array_name, *, budget):
        with self._read_scope(budget=budget):
            m = self._manifest(invocation)
            if m is None:
                raise KeyError(invocation)
            if array_name not in m['arrays']:
                raise KeyError(array_name)
            a = m['arrays'][array_name]
        dt, total = _dtype(a['dtype']), math.prod(a['shape'])
        width = self.limits.chunk_bytes // dt.itemsize
        for i, key in enumerate(a['chunks']):
            with self._read_scope(budget=budget):
                raw = self._chunk(key, expected_dtype=dt.str,
                                  expected_count=min(width, total-i*width))
            yield i * width, np.frombuffer(raw, dtype=dt)

    def get(self, invocation, *, budget: WorkBudget | None = None):
        """One stable read snapshot, one manifest parse, bounded chunk decoding."""
        with self._read_scope(budget=budget):
            m = self._manifest(invocation)
            if m is None:
                return None
            total = sum(math.prod(a['shape']) * _dtype(a['dtype']).itemsize for a in m['arrays'].values())
            if total > self.limits.max_array_bytes:
                raise StoreError('full result exceeds read limit; use iter_chunks')
            with self._workspace(2 * total, budget, category="store-output"):
                result = {}
                for name, a in m['arrays'].items():
                    dt = _dtype(a['dtype'])
                    count = math.prod(a['shape'])
                    width = self.limits.chunk_bytes // dt.itemsize
                    buffer = bytearray(count * dt.itemsize)
                    for i, key in enumerate(a['chunks']):
                        start = i * width
                        raw = self._chunk(key, expected_dtype=dt.str, expected_count=min(width, count-start))
                        buffer[start*dt.itemsize:start*dt.itemsize+len(raw)] = raw
                    result[name] = np.frombuffer(bytes(buffer), dtype=dt).reshape(a['shape'])
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
