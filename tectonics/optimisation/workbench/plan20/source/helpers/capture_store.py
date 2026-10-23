"""WP16 immutable, bounded, byte-exact diagnostic transport.

This is storage integrity, never scientific admission. ``verify`` or a fully
consumed stream authenticates the complete file. A partially consumed stream
only verifies its returned chunks. Keep each CaptureBytes owner alive while
using its ``value``; keep the reader alive while using its ``header``.

The existing WorkBudget owns all admissions. No retained-scope replacement,
cache, background work, codec installation or original-file rewrite occurs.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import struct
import tempfile
from types import MappingProxyType, SimpleNamespace

from atlas_tectonics.resources import WorkBudget

FORMAT = 'atlas.diagnostic-capture.v1'
MAGIC = b'ATCP16\x00\x01'
MAX_CHUNK_BYTES = 65536
MAX_HEADER_BYTES = 65536
DEFAULT_MAX_BYTES = 4 << 30
# Covers bounded JSON input, parse/freeze structures, hash/file state and Python
# overhead. This is conservative logical accounting, not measured process RSS.
HEADER_WORK_BYTES = 8 << 20
STREAM_WORK_BYTES = 5 * MAX_CHUNK_BYTES + 32768
OWNER_BYTES = 4096
PREAMBLE = struct.Struct('<8sI')
FRAME = struct.Struct('<cQBII32s32s')
FOOTER = struct.Struct('<cQQ32s32s')
_SHA = re.compile(r'[0-9a-f]{64}\Z')
_HEADER_KEYS = frozenset(('format', 'kind', 'representation', 'metadata',
                          'codec', 'level', 'backend_sha256'))


class CaptureError(ValueError):
    """Invalid, changed, incomplete or unsupported capture."""


class _Lease:
    """A lease follows retained traceback frames as well as ordinary owners."""
    def __init__(self, budget, count, purpose):
        self._context = None
        context = budget.reserve(count, category='capture:' + purpose)
        context.__enter__()
        self._context = context

    def close(self):
        context, self._context = self._context, None
        if context is not None:
            context.__exit__(None, None, None)

    def __del__(self):
        self.close()


class CaptureBytes:
    """Explicit paid byte owner; raw escapes require this owner to stay alive."""
    def __init__(self, budget, capacity):
        self._lease = _Lease(budget, capacity + OWNER_BYTES, 'bytes')
        self._value = None

    @property
    def value(self):
        if self._value is None:
            raise RuntimeError('closed or unfilled capture byte owner')
        return self._value

    def close(self):
        self._value = None
        lease, self._lease = self._lease, None
        if lease is not None:
            lease.close()

    def __enter__(self):
        self.value
        return self

    def __exit__(self, kind, value, traceback):
        # Exceptions can retain the raw value in their traceback.
        if kind is None:
            self.close()
        return False

    def __del__(self):
        if hasattr(self, '_lease'):
            self.close()


def _limits(budget, logical, stored):
    if not isinstance(budget, WorkBudget):
        raise TypeError('capture requires an existing WorkBudget')
    if any(type(n) is not int or not 0 <= n <= (1 << 63) - 1
           for n in (logical, stored)):
        raise ValueError('capture limits must be bounded nonnegative integers')


def _plain_path(path, *, missing=False):
    path = Path(os.path.abspath(os.fspath(path)))
    for part in reversed((path,) + tuple(path.parents)):
        try:
            info = part.lstat()
        except FileNotFoundError:
            if missing and part == path:
                continue
            raise
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise CaptureError('capture paths must not contain links or reparse points')
        if part != path and not stat.S_ISDIR(info.st_mode):
            raise CaptureError('capture parent is not a directory')
        if part == path:
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise CaptureError('capture must be a regular single-link file')
    return path


def _identity(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)


def _text(value, name):
    if type(value) is not str or not 1 <= len(value) <= 128:
        raise ValueError(name + ' must contain 1..128 characters')
    value.encode('utf-8')
    return value


def _metadata(value):
    """Reject oversized/deep caller objects before serialising or copying."""
    if type(value) is not dict:
        raise ValueError('metadata must be a JSON object')
    nodes = 0
    characters = 0

    def walk(item, depth):
        nonlocal nodes, characters
        nodes += 1
        if nodes > 4096 or depth > 12:
            raise CaptureError('capture metadata exceeds node/depth limit')
        if item is None or type(item) is bool:
            return
        if type(item) is int:
            if item.bit_length() > 128:
                raise CaptureError('capture metadata integer exceeds limit')
            return
        if type(item) is float:
            if not math.isfinite(item):
                raise CaptureError('capture metadata must be finite')
            return
        if type(item) is str:
            characters += len(item)
            if characters > MAX_HEADER_BYTES:
                raise CaptureError('capture metadata exceeds text limit')
            return
        if type(item) is list:
            if len(item) > 4096:
                raise CaptureError('capture metadata list exceeds limit')
            for child in item:
                walk(child, depth + 1)
            return
        if type(item) is dict:
            if len(item) > 4096:
                raise CaptureError('capture metadata object exceeds limit')
            for key, child in item.items():
                if type(key) is not str:
                    raise CaptureError('capture metadata keys must be strings')
                walk(key, depth + 1)
                walk(child, depth + 1)
            return
        raise CaptureError('capture metadata must contain only JSON values')

    walk(value, 0)


def _backend(backend, expected=None):
    # Raw mode has no native dependency. A zstd caller explicitly supplies the
    # existing backend whose constructor already checks the pinned DLL/ABI.
    from storage_zstd_backend import ZstdBackend
    if not isinstance(backend, ZstdBackend):
        raise CaptureError('zstd capture requires the pinned ZstdBackend')
    if not _SHA.fullmatch(backend.library_sha256):
        raise CaptureError('invalid native backend identity')
    if expected is not None and backend.library_sha256 != expected:
        raise CaptureError('capture native backend identity mismatch')
    return backend


def _json_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise CaptureError('duplicate capture header key')
        result[key] = value
    return result


def _no_constant(value):
    raise CaptureError('nonfinite capture header constant: ' + value)


def _freeze(value):
    if type(value) is dict:
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if type(value) is list:
        return tuple(_freeze(item) for item in value)
    return value


def _write_all(target, data, check):
    view = memoryview(data)
    offset = 0
    while offset < len(view):
        check()
        written = target.write(view[offset:])
        if type(written) is not int or not 0 < written <= len(view) - offset:
            raise OSError('capture write made no progress or returned invalid length')
        offset += written


def _validate_header(header):
    if type(header) is not dict or set(header) != _HEADER_KEYS:
        raise CaptureError('unknown capture header fields')
    if header['format'] != FORMAT:
        raise CaptureError('unknown capture format')
    _text(header['kind'], 'kind')
    _text(header['representation'], 'representation')
    _metadata(header['metadata'])
    if header['codec'] not in ('raw', 'zstd'):
        raise CaptureError('unknown capture codec')
    if type(header['level']) is not int or not 0 <= header['level'] <= 9:
        raise CaptureError('invalid capture codec level')
    pin = header['backend_sha256']
    if ((header['codec'] == 'raw' and pin is not None) or
            (header['codec'] == 'zstd' and
             (type(pin) is not str or not _SHA.fullmatch(pin)))):
        raise CaptureError('invalid capture backend identity')


def _encode(raw, backend, level, budget):
    rule = SimpleNamespace(codec='zstd', shuffle='none', level=level,
                           dictionary_sha256=None)
    bound = backend.encode_workspace_bound(len(raw), 'u1', rule)
    if type(bound) is not int or not 0 < bound <= 8 << 20:
        raise CaptureError('invalid native encode workspace bound')
    lease = _Lease(budget, bound, 'encode')
    label, payload = backend.encode(raw, 'u1', rule)
    if label == 'raw':
        if payload != raw:
            raise CaptureError('native raw fallback changed bytes')
        code = 0
    elif label == f'wp10-zstd-v1:none:{level}:-':
        if type(payload) is not bytes or not 0 < len(payload) < len(raw):
            raise CaptureError('invalid bounded compressed payload')
        code = 1
    else:
        raise CaptureError('unexpected native compression label')
    lease.close()
    return code, payload


def _decode(payload, length, backend, level, budget):
    label = f'wp10-zstd-v1:none:{level}:-'
    bound = backend.inspect_decode(label, payload, 'u1', length)
    if type(bound) is not int or not 0 < bound <= 8 << 20:
        raise CaptureError('invalid native decode workspace bound')
    lease = _Lease(budget, bound, 'decode')
    raw = backend.decode(label, payload, 'u1', length)
    if type(raw) is not bytes or len(raw) != length:
        raise CaptureError('invalid native decoded length')
    lease.close()
    return raw


def _result(header, raw_hash, raw_bytes, stored_bytes, count, codecs, file_hash):
    return {'format': FORMAT, 'kind': header['kind'],
            'representation': header['representation'],
            'raw_sha256': raw_hash.hexdigest(), 'raw_bytes': raw_bytes,
            'stored_bytes': stored_bytes, 'chunks': count,
            'codec_counts': dict(codecs), 'container_sha256': file_hash.hexdigest()}


def _write_frames(target, chunks, header, budget, backend, check,
                  max_logical_bytes, max_stored_bytes):
    lease = _Lease(budget, STREAM_WORK_BYTES, 'writer-stream')
    encoded = json.dumps(header, ensure_ascii=True, allow_nan=False,
                         sort_keys=True, separators=(',', ':')).encode('ascii')
    if len(encoded) > MAX_HEADER_BYTES:
        raise CaptureError('capture header exceeds 64 KiB')
    file_hash, raw_hash = hashlib.sha256(), hashlib.sha256()
    stored_bytes = raw_bytes = count = 0
    codecs = {'raw': 0, 'zstd': 0}

    def emit(data):
        nonlocal stored_bytes
        if stored_bytes + len(data) + FOOTER.size > max_stored_bytes:
            raise CaptureError('capture exceeds stored-byte limit')
        _write_all(target, data, check)
        file_hash.update(data)
        stored_bytes += len(data)

    emit(PREAMBLE.pack(MAGIC, len(encoded)))
    emit(encoded)
    emit(hashlib.sha256(encoded).digest())
    pending = bytearray()

    def frame(raw):
        nonlocal count, raw_bytes
        check()
        if raw_bytes + len(raw) > max_logical_bytes:
            raise CaptureError('capture exceeds logical-byte limit')
        code, payload = (0, raw) if header['codec'] == 'raw' else _encode(
            raw, backend, header['level'], budget)
        emit(FRAME.pack(b'C', count, code, len(raw), len(payload),
                        hashlib.sha256(raw).digest(), hashlib.sha256(payload).digest()))
        emit(payload)
        raw_hash.update(raw)
        raw_bytes += len(raw)
        count += 1
        codecs['zstd' if code else 'raw'] += 1

    for part in chunks:
        check()
        if type(part) is not bytes or len(part) > MAX_CHUNK_BYTES:
            raise CaptureError('input chunks must be bytes of at most 64 KiB')
        # Reject the aggregate before appending or invoking a codec.
        if raw_bytes + len(pending) + len(part) > max_logical_bytes:
            raise CaptureError('capture exceeds logical-byte limit')
        offset = 0
        while offset < len(part):
            take = min(MAX_CHUNK_BYTES - len(pending), len(part) - offset)
            pending.extend(part[offset:offset + take])
            offset += take
            if len(pending) == MAX_CHUNK_BYTES:
                frame(bytes(pending))
                pending.clear()
    if pending:
        frame(bytes(pending))
    footer = FOOTER.pack(b'F', count, raw_bytes, raw_hash.digest(), file_hash.digest())
    _write_all(target, footer, check)
    file_hash.update(footer)
    stored_bytes += len(footer)
    result = _result(header, raw_hash, raw_bytes, stored_bytes, count, codecs, file_hash)
    pending.clear()
    lease.close()
    return result


def write_capture(path, chunks, *, kind, representation='exact-bytes', metadata=None,
                  budget, codec='zstd', level=3, backend=None, check=lambda: None,
                  max_logical_bytes=DEFAULT_MAX_BYTES,
                  max_stored_bytes=DEFAULT_MAX_BYTES):
    """Publish one new immutable capture atomically; existing paths are refused."""
    _limits(budget, max_logical_bytes, max_stored_bytes)
    check()
    path = _plain_path(path, missing=True)
    if path.exists():
        raise FileExistsError(path)
    lease = _Lease(budget, HEADER_WORK_BYTES, 'writer-header')
    if codec not in ('raw', 'zstd'):
        raise CaptureError('unknown capture codec')
    native = _backend(backend) if codec == 'zstd' else None
    header = {'format': FORMAT, 'kind': kind, 'representation': representation,
              'metadata': {} if metadata is None else metadata,
              'codec': codec, 'level': level,
              'backend_sha256': None if native is None else native.library_sha256}
    _validate_header(header)
    temporary = None
    try:
        fd, name = tempfile.mkstemp(prefix='.' + path.name + '-', suffix='.tmp', dir=path.parent)
        temporary = Path(name)
        with os.fdopen(fd, 'wb', buffering=0) as target:
            result = _write_frames(target, chunks, header, budget, native, check,
                                   max_logical_bytes, max_stored_bytes)
            target.flush()
            os.fsync(target.fileno())
        check()
        _plain_path(path, missing=True)
        if os.name == 'nt':
            # Windows rename refuses an existing destination atomically.
            os.rename(temporary, path)
        else:
            # POSIX rename overwrites; exclusive link publication does not.
            os.link(temporary, path)
            temporary.unlink()
        temporary = None
        header = None
        lease.close()
        return result
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


class CaptureStream:
    """One serial walk, holding its reader open until close or exhaustion."""
    def __init__(self, reader):
        self._reader = reader
        self._lease = _Lease(reader._budget, STREAM_WORK_BYTES, 'reader-stream')
        self._iterator = reader._walk()
        self._failed = False
        self.result = None
        reader._active = self

    def __iter__(self):
        return self

    def __next__(self):
        if self._iterator is None:
            raise StopIteration
        try:
            return next(self._iterator)
        except StopIteration as end:
            self.result = end.value
            self.close()
            raise
        except BaseException:
            self._failed = True
            raise

    def close(self):
        if self._iterator is not None:
            iterator, self._iterator = self._iterator, None
            iterator.close()
            self._reader._active = None
            self._reader = None
            # A failed producer frame may survive generator.close via traceback.
            # Its stream remains charged until that traceback/owner disappears.
            if not self._failed:
                self._lease.close()
                self._lease = None

    def __enter__(self):
        return self

    def __exit__(self, kind, value, traceback):
        if kind is not None:
            self._failed = True
        self.close()
        return False

    def __del__(self):
        if hasattr(self, '_iterator'):
            self.close()


class CaptureReader:
    """Context-owned metadata and one active bounded stream; no chunk index."""
    def __init__(self, path, *, budget, backend=None, expected_sha256=None,
                 check=lambda: None, max_logical_bytes=DEFAULT_MAX_BYTES,
                 max_stored_bytes=DEFAULT_MAX_BYTES):
        _limits(budget, max_logical_bytes, max_stored_bytes)
        if expected_sha256 is not None and (type(expected_sha256) is not str or
                                           not _SHA.fullmatch(expected_sha256)):
            raise ValueError('invalid expected capture SHA-256')
        self._file = None
        self._active = None
        self._lease = _Lease(budget, HEADER_WORK_BYTES, 'reader-header')
        self._budget, self._backend = budget, backend
        self._check, self._expected = check, expected_sha256
        self._max_logical, self._max_stored = max_logical_bytes, max_stored_bytes
        self._header = None
        check()
        self._path = _plain_path(path)
        info = self._path.stat()
        self._identity = _identity(info)
        if info.st_size > max_stored_bytes or info.st_size < PREAMBLE.size + 32 + FOOTER.size:
            raise CaptureError('capture stored size outside limits')
        self._file = self._path.open('rb', buffering=0)
        self._fresh()
        prefix = self._read(PREAMBLE.size)
        magic, size = PREAMBLE.unpack(prefix)
        if magic != MAGIC or not 1 <= size <= MAX_HEADER_BYTES:
            raise CaptureError('unknown capture magic/header size')
        encoded = self._read(size)
        digest = self._read(32)
        if hashlib.sha256(encoded).digest() != digest:
            raise CaptureError('capture header hash mismatch')
        try:
            header = json.loads(encoded, object_pairs_hook=_json_pairs,
                                parse_constant=_no_constant)
        except (UnicodeError, json.JSONDecodeError, RecursionError) as error:
            raise CaptureError('invalid capture header JSON') from error
        _validate_header(header)
        self._header = _freeze(header)
        self._prefix = prefix + encoded + digest
        self._offset = self._file.tell()
        self._fresh()

    @property
    def header(self):
        if self._file is None or self._header is None:
            raise RuntimeError('closed capture reader')
        return self._header

    def _read(self, count):
        data = self._file.read(count)
        if len(data) != count:
            raise CaptureError('truncated capture')
        return data

    def _fresh(self, *, path=True):
        self._check()
        if path:
            _plain_path(self._path)
        if ((path and _identity(self._path.stat()) != self._identity) or
                _identity(os.fstat(self._file.fileno())) != self._identity):
            raise CaptureError('capture changed during read')

    def iter_bytes(self):
        if self._file is None:
            raise RuntimeError('closed capture reader')
        if self._active is not None:
            raise RuntimeError('capture reader already has a live stream')
        self._fresh()
        self._file.seek(self._offset)
        return CaptureStream(self)

    def _walk(self):
        raw_hash, file_hash = hashlib.sha256(), hashlib.sha256(self._prefix)
        raw_bytes = count = 0
        codecs = {'raw': 0, 'zstd': 0}
        while True:
            self._fresh(path=False)
            tag = self._read(1)
            if tag == b'F':
                footer = tag + self._read(FOOTER.size - 1)
                _, expected_count, expected_bytes, expected_raw, expected_file = FOOTER.unpack(footer)
                if ((expected_count, expected_bytes) != (count, raw_bytes) or
                        expected_raw != raw_hash.digest() or expected_file != file_hash.digest()):
                    raise CaptureError('capture footer identity mismatch')
                file_hash.update(footer)
                if self._file.read(1):
                    raise CaptureError('trailing bytes after capture footer')
                if self._expected is not None and self._expected != file_hash.hexdigest():
                    raise CaptureError('expected capture SHA-256 mismatch')
                self._fresh()
                return _result(self._header, raw_hash, raw_bytes, self._file.tell(),
                               count, codecs, file_hash)
            if tag != b'C':
                raise CaptureError('unknown capture frame tag')
            frame = tag + self._read(FRAME.size - 1)
            _, sequence, code, length, stored, expected_raw, expected_stored = FRAME.unpack(frame)
            if sequence != count:
                raise CaptureError('capture frame sequence mismatch')
            if (code not in (0, 1) or not 1 <= length <= MAX_CHUNK_BYTES or
                    not 1 <= stored <= MAX_CHUNK_BYTES or
                    (code == 0 and stored != length) or (code == 1 and stored >= length)):
                raise CaptureError('capture frame lengths/codec outside bounds')
            if code and self._header['codec'] != 'zstd':
                raise CaptureError('compressed frame under raw capture policy')
            if raw_bytes + length > self._max_logical:
                raise CaptureError('capture exceeds logical-byte limit')
            if self._file.tell() + stored + FOOTER.size > self._identity[2]:
                raise CaptureError('truncated capture payload/footer')
            owner = CaptureBytes(self._budget, length)
            payload = self._read(stored)
            if hashlib.sha256(payload).digest() != expected_stored:
                raise CaptureError('stored capture chunk hash mismatch')
            file_hash.update(frame)
            file_hash.update(payload)
            owner._value = payload if code == 0 else _decode(
                payload, length, _backend(self._backend, self._header['backend_sha256']),
                self._header['level'], self._budget)
            if hashlib.sha256(owner.value).digest() != expected_raw:
                raise CaptureError('raw capture chunk hash mismatch')
            raw_hash.update(owner.value)
            raw_bytes += length
            count += 1
            codecs['zstd' if code else 'raw'] += 1
            self._fresh(path=False)
            payload = None
            yield owner
            owner = None

    def verify(self):
        """Perform a complete new walk, including footer, EOF and freshness."""
        with self.iter_bytes() as stream:
            for owner in stream:
                owner.close()
        return stream.result

    def close(self):
        if self._active is not None:
            raise RuntimeError('capture reader has a live stream')
        if self._file is not None:
            source, self._file = self._file, None
            source.close()
        self._header = self._prefix = None
        lease, self._lease = self._lease, None
        if lease is not None:
            lease.close()

    def __enter__(self):
        if self._file is None:
            raise RuntimeError('closed capture reader')
        return self

    def __exit__(self, kind, value, traceback):
        if kind is None:
            self.close()
        return False

    def __del__(self):
        if getattr(self, '_active', None) is None and hasattr(self, '_lease'):
            self.close()
