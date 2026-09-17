"""Bounded local, lossless array snapshots with content-addressed chunk reuse.

SQLite owns transactions/locking and packs blobs into one file. No pickle, history
migration, garbage collection, lossy conversion, or network store. Caller owns the
local directory (not hostile). SHA-256 detects corruption, not an authorised
attacker who can replace both data and hashes. Numerical meaning stays in the
invocation metadata; equal payloads may be shared across different invocations.
"""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3
import struct
import threading
from typing import Mapping

import numpy as np

from .resources import WorkBudget


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

    def __post_init__(self):
        for name in ('chunk_bytes', 'max_array_bytes', 'max_store_bytes',
                     'max_manifest_bytes', 'max_chunks'):
            _positive(getattr(self, name), name)
        if self.chunk_bytes < 8 or self.chunk_bytes > 16 * 1024 * 1024:
            raise StoreError('chunk_bytes must be between 8 bytes and 16 MiB')
        if self.max_store_bytes < 65536:
            raise StoreError('store budget must accommodate at least 64 KiB')
        if type(self.decoded_cache_bytes) is not int or self.decoded_cache_bytes < 0:
            raise StoreError('decoded cache budget must be nonnegative')


@dataclass(frozen=True, slots=True)
class Compression:
    codec: str = 'raw'
    level: int = 3
    shuffle: str = 'byte'
    palette: bool = False

    def __post_init__(self):
        if self.codec not in ('raw', 'zstd') or self.shuffle not in ('none', 'byte', 'bit'):
            raise StoreError('supported codecs: raw/zstd; shuffle: none/byte/bit')
        if type(self.level) is not int or not 0 <= self.level <= 9:
            raise StoreError('Blosc2 compression level must be 0..9 (not direct Zstd levels)')
        if type(self.palette) is not bool:
            raise StoreError('palette must be bool')


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
    """
    def __init__(self, path, limits: StoreLimits, compression: Compression = Compression()):
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
        self._db = sqlite3.connect(self.path, timeout=5, isolation_level=None,
                                   check_same_thread=False)
        try:
            self._db.execute('PRAGMA journal_mode=DELETE')
            self._db.execute('PRAGMA synchronous=FULL')
            self._db.execute('PRAGMA trusted_schema=OFF')
            self._db.execute('PRAGMA foreign_keys=ON')
            self._db.execute('PRAGMA cache_size=-2048')
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
            raise
        self._closed = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def close(self):
        with self._lock:
            if not self._closed:
                self._cache.clear()
                self._cached_bytes = 0
                self._db.close()
                self._closed = True

    def _live(self):
        if self._closed:
            raise StoreError('store is closed')
        _path(self.path)
        version = self._db.execute('PRAGMA data_version').fetchone()[0]
        if version != self._cache_version:
            self._cache.clear()
            self._cached_bytes = 0
            self._cache_version = version

    def _blob_id(self, descriptor, raw):
        h = hashlib.sha256(b'atlas-typed-chunk-v1\0')
        h.update(descriptor)
        h.update(b'\0')
        h.update(raw)
        return h.hexdigest()

    def _encode(self, raw, dt):
        # Exact uniform encoding precedes palette/compression; signed zeros differ.
        width = dt.itemsize
        first = raw[:width]
        if raw == first * (len(raw) // width):
            return 'uniform', first
        best = ('raw', raw)
        if self.compression.palette and dt.kind in 'biu':
            values, inverse = np.unique(np.frombuffer(raw, dtype=dt), return_inverse=True)
            n = len(values)
            if 1 < n <= 256:
                packed = struct.pack('<I', n) + values.tobytes() + inverse.astype('u1').tobytes()
                if len(packed) < len(best[1]):
                    best = ('palette8', packed)
        if self.compression.codec == 'zstd':
            b = self._blosc
            filters = [b.Filter.NOFILTER] * 5 + [
                {'none': b.Filter.NOFILTER, 'byte': b.Filter.SHUFFLE,
                 'bit': b.Filter.BITSHUFFLE}[self.compression.shuffle]]
            encoded = b.compress2(raw, codec=b.Codec.ZSTD, clevel=self.compression.level,
                                 typesize=width, nthreads=1, filters=filters,
                                 use_dict=False)
            if len(encoded) < len(best[1]):
                version = b.clib_info(b.Codec.ZSTD)[1].decode()
                label = f'blosc2-zstd-{self.compression.shuffle}:{self.compression.level}:{b.__version__}:{version}'
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

    def _chunk(self, key, *, expected_dtype=None, expected_count=None):
        _sha(key)
        row = self._db.execute('SELECT length(descriptor),length(payload),length(codec) FROM chunks WHERE id=?', (key,)).fetchone()
        if row is None:
            raise StoreError('snapshot has a missing chunk')
        if row[0] > 256 or row[1] > self.limits.chunk_bytes + 4096 or row[2] > 128:
            raise StoreError('oversized chunk record')
        desc, codec, stored, payload = self._db.execute('SELECT descriptor,codec,stored_sha,payload FROM chunks WHERE id=?', (key,)).fetchone()
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
        cache_key = (key, stored)
        raw = self._cache.get(cache_key)
        if raw is None:
            raw = self._decode(codec, payload, dt, count)
            if self._blob_id(desc, raw) != key:
                raise StoreError('logical chunk checksum mismatch')
            if len(raw) <= self.limits.decoded_cache_bytes:
                while self._cache and self._cached_bytes + len(raw) > self.limits.decoded_cache_bytes:
                    _, old = self._cache.popitem(last=False)
                    self._cached_bytes -= len(old)
                self._cache[cache_key] = raw
                self._cached_bytes += len(raw)
        else:
            self._cache.move_to_end(cache_key)
        return raw

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

    def put(self, invocation: str, arrays: Mapping[str, np.ndarray], metadata=None):
        """Atomically add an immutable result. Repeated keys must match exactly.

        No automatic eviction. Chunk identities exclude location/time so identical
        typed bytes deduplicate; the manifest retains their scientific placement.
        Encoding choices never enter the numerical invocation identity.
        """
        _sha(invocation)
        if not isinstance(arrays, Mapping) or not arrays:
            raise StoreError('nonempty array mapping required')
        views = {}
        projected_chunks = 0
        for name, value in arrays.items():
            if type(name) is not str or not name or len(name) > 256:
                raise StoreError('short nonempty array names required')
            a = _array_view(value)
            if a.nbytes > self.limits.max_array_bytes:
                raise StoreError('array exceeds storage input limit')
            projected_chunks += (a.size + self.limits.chunk_bytes // a.itemsize - 1) // (self.limits.chunk_bytes // a.itemsize)
            views[name] = a
        if projected_chunks > self.limits.max_chunks:
            raise StoreError('too many chunks')
        metadata = {} if metadata is None else metadata
        if len(_json(metadata)) + projected_chunks * 68 + len(views) * 256 > self.limits.max_manifest_bytes:
            raise StoreError('projected manifest exceeds limit')
        with self._lock:
            self._live()
            try:
                self._db.execute('BEGIN IMMEDIATE')
                description = {}
                for name, a in sorted(views.items()):
                    dt = _dtype(a.dtype.str)
                    width = self.limits.chunk_bytes // dt.itemsize
                    ids = []
                    for start in range(0, a.size, width):
                        # flat slicing copies at most one chunk, including strided arrays.
                        block = np.asarray(a.flat[start:start+width], dtype=dt)
                        if dt.kind == 'f' and not np.isfinite(block).all():
                            raise StoreError('nonfinite values are not supported scientific state')
                        raw = block.tobytes()
                        desc = _json({'dtype': dt.str, 'count': block.size})
                        key = self._blob_id(desc, raw)
                        if self._db.execute('SELECT 1 FROM chunks WHERE id=?', (key,)).fetchone():
                            if self._chunk(key, expected_dtype=dt.str, expected_count=block.size) != raw:
                                raise StoreConflict('logical chunk identity conflict')
                        else:
                            codec, payload = self._encode(raw, dt)
                            digest = _hash(desc + b'\0' + codec.encode() + b'\0' + payload)
                            self._db.execute('INSERT INTO chunks VALUES(?,?,?,?,?)', (key, desc, codec, digest, payload))
                        ids.append(key)
                    description[name] = {'dtype': dt.str, 'shape': list(a.shape), 'chunks': ids}
                body = _json({'schema': _SCHEMA, 'invocation': invocation,
                              'arrays': description, 'metadata': metadata})
                if len(body) > self.limits.max_manifest_bytes:
                    raise StoreError('manifest exceeds limit')
                previous = self._db.execute('SELECT body FROM snapshots WHERE id=?', (invocation,)).fetchone()
                if previous and previous[0] != body:
                    raise StoreConflict('same invocation produced different data or metadata')
                if previous:
                    self._manifest(invocation)
                else:
                    self._db.execute('INSERT INTO snapshots VALUES(?,?,?)', (invocation, body, _hash(body)))
                # Includes metadata/payload logically; max_page_count also caps database allocation.
                used = self._db.execute('SELECT COALESCE(sum(length(payload)+length(descriptor)+128),0) FROM chunks').fetchone()[0]
                used += self._db.execute('SELECT COALESCE(sum(length(body)+128),0) FROM snapshots').fetchone()[0]
                if used > self.limits.max_store_bytes:
                    raise StoreError('retained records exceed store budget')
                self._db.execute('COMMIT')
            except BaseException as exc:
                if self._db.in_transaction:
                    self._db.execute('ROLLBACK')
                self._cache.clear()
                self._cached_bytes = 0
                if isinstance(exc, sqlite3.Error):
                    raise StoreError('storage transaction failed; no snapshot published') from exc
                raise
        return invocation

    def contains(self, invocation):
        """Manifest existence only; get() verifies all referenced payloads."""
        with self._lock:
            self._live()
            return self._manifest(invocation) is not None

    def metadata(self, invocation):
        with self._lock:
            self._live()
            m = self._manifest(invocation)
            return None if m is None else m['metadata']

    def read_chunk(self, invocation, array_name, index):
        """Random access to one decoded chunk, with its flat element offset."""
        if type(index) is not int or index < 0:
            raise StoreError('chunk index must be a nonnegative integer')
        with self._lock:
            self._live()
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

    def iter_chunks(self, invocation, array_name):
        """Yield (flat start, detached immutable typed chunk); no full array load."""
        with self._lock:
            self._live()
            m = self._manifest(invocation)
            if m is None:
                raise KeyError(invocation)
            if array_name not in m['arrays']:
                raise KeyError(array_name)
            a = m['arrays'][array_name]
        dt, total = _dtype(a['dtype']), math.prod(a['shape'])
        width = self.limits.chunk_bytes // dt.itemsize
        for i, key in enumerate(a['chunks']):
            with self._lock:
                self._live()
                raw = self._chunk(key, expected_dtype=dt.str,
                                  expected_count=min(width, total-i*width))
            yield i * width, np.frombuffer(raw, dtype=dt)

    def get(self, invocation, *, budget: WorkBudget | None = None):
        """Restore a full result or return None for an absent invocation only."""
        with self._lock:
            self._live()
            m = self._manifest(invocation)
            if m is None:
                return None
        total = sum(math.prod(a['shape']) * _dtype(a['dtype']).itemsize for a in m['arrays'].values())
        if total > self.limits.max_array_bytes:
            raise StoreError('full result exceeds read limit; use iter_chunks')
        policy = budget or WorkBudget(2 * self.limits.max_array_bytes + 8 * self.limits.chunk_bytes)
        with policy.reserve(2 * total + 8 * self.limits.chunk_bytes):
            result = {}
            for name, a in m['arrays'].items():
                dt = _dtype(a['dtype'])
                buffer = bytearray(math.prod(a['shape']) * dt.itemsize)
                for start, chunk in self.iter_chunks(invocation, name):
                    buffer[start*dt.itemsize:(start+chunk.size)*dt.itemsize] = memoryview(chunk).cast('B')
                result[name] = np.frombuffer(bytes(buffer), dtype=dt).reshape(a['shape'])
            return result

    def statistics(self):
        with self._lock:
            self._live()
            row = self._db.execute('SELECT count(*),COALESCE(sum(length(payload)),0) FROM chunks').fetchone()
            return {'unique_chunks': row[0], 'encoded_payload_bytes': row[1],
                    'snapshots': self._db.execute('SELECT count(*) FROM snapshots').fetchone()[0],
                    'database_bytes': self.path.stat().st_size,
                    'decoded_cache_bytes': self._cached_bytes}

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
