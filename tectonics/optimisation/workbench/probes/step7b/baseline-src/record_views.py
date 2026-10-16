"""Owned non-Mapping references over generic columns or bounded segment reads."""
from __future__ import annotations

from dataclasses import dataclass
from contextlib import contextmanager, nullcontext
from collections import OrderedDict
from hashlib import sha256
import json
import math

import numpy as np

from atlas_tectonics.resources import WorkBudget, MemoryLimitError
from compact_contracts import ContractError, LogicalIdentity
from content_cache import ChargeSpec, OwnedStream, VerifiedCacheKey, get_content_cache
import record_tables as T

_NAMES = frozenset(('node.kind', 'node.payload', 'node.shape', 'node.length',
    'node.charge', 'node.offset', 'edge.child', 'shape.offset', 'shape.key',
    'token.offset', 'token.bytes', 'int.offset', 'int.bytes', 'int.sign',
    'int.mode', 'int.exponent', 'float.value', 'id.bytes', 'q.numerator', 'q.denominator'))
_BYTE = {'node.kind', 'token.bytes', 'int.bytes', 'int.sign', 'int.mode', 'id.bytes'}
_U64 = {'node.length', 'node.charge', 'node.offset', 'shape.offset', 'token.offset',
        'int.offset', 'int.exponent'}
OWNER_BYTES = 4096


def _owned(scope, count, factory, purpose='record-output', dependencies=()):
    with scope.reserve(ChargeSpec(purpose, count), required=True, cancel=None) as reservation:
        return reservation.commit(factory(), dependencies=dependencies)


def _bound(value, name, maximum=(1 << 64)-1):
    T.require(type(value) is int and 0 <= value <= maximum, 'invalid '+name)


class _Memory:
    def __init__(self, arrays):
        self.arrays = arrays

    def value(self, name, index):
        return self.arrays[name][index].item()

    def raw(self, name, start, stop):
        return memoryview(self.arrays[name]).cast('B')[start:stop]


@dataclass(frozen=True, slots=True)
class _ColumnPage:
    binding: bytes
    expected_sha256: str
    expected_bytes: int
    raw: bytes


@dataclass(frozen=True, slots=True)
class _NativeChunkPage:
    binding: bytes
    expected_sha256: str
    expected_bytes: int
    raw: bytes
    descriptor: bytes


def _column_key(epoch, binding, expected_sha256, expected_bytes):
    digest = sha256(b'atlas.record-column-page.v1\0')
    digest.update(len(binding).to_bytes(8, 'little'))
    digest.update(binding)
    digest.update(bytes.fromhex(expected_sha256))
    digest.update(expected_bytes.to_bytes(8, 'little'))
    return VerifiedCacheKey('pages', epoch, digest.digest())


def _verify_column_page(key, page):
    if (type(page) not in (_ColumnPage, _NativeChunkPage) or type(page.raw) is not bytes or
            not len(page.raw) == page.expected_bytes <= T.CHUNK or
            _column_key(key.process_epoch, page.binding, page.expected_sha256,
                        page.expected_bytes) != key):
        return False
    if type(page) is _ColumnPage:
        return sha256(page.raw).hexdigest() == page.expected_sha256
    return (type(page.descriptor) is bytes and len(page.descriptor) <= 1024 and
            sha256(b'atlas-typed-chunk-v1\0'+page.descriptor+b'\0'+page.raw).hexdigest()
            == page.expected_sha256)


class _OptionalScratch(T.Scratch):
    def __init__(self, budget, size):
        self._lease = budget.try_reserve(size, category='record-column-lookup')
        self.admitted = self._lease.__enter__()


class _BatchPage:
    """Internal immutable borrow, valid only while the compound read owns it."""
    __slots__ = ('_owner',)

    def __init__(self, owner):
        self._owner = owner

    @property
    def value(self):
        return self._owner.value

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


class _Segment:
    """No eager array load. Payload reads remain bounded and owned by WP1."""
    def __init__(self, segment, descriptors, *, use_page_cache=True):
        self.segment, self.descriptors = segment, descriptors
        self.cache = None
        self._page_cursors = None
        self._batch_pages = None
        self._batch_depth = 0
        self.file_identity = segment.cache_identity() if use_page_cache else None
        if self.file_identity is not None:
            T.require(type(self.file_identity) is bytes and len(self.file_identity) == 32,
                      'bounded authenticated file identity required for cached columns')
            try:
                self.cache = get_content_cache(segment.scope, 'pages', enabled=True,
                                               verifier=_verify_column_page)
            except MemoryLimitError:
                # Optional reuse must not prevent the existing required read.
                self.cache = None
        if self.cache is not None and any(row['shape'][0]*np.dtype(row['dtype']).itemsize > T.CHUNK
                                           for row in descriptors.values()):
            # At most 128 authenticated leaf bindings, not another payload
            # cache. Their bounded index shares the existing retained scope.
            reservation = segment.scope.reserve(ChargeSpec('record-page-cursors', 128*2048+4096),
                                                 required=False, cancel=segment.cancel)
            if reservation is not None:
                with reservation:
                    self._page_cursors = reservation.commit(OrderedDict())

    @contextmanager
    def read_batch(self):
        """Pin at most 128 existing verified immutable pages for one atomic read.

        No payload copy or independent cache: these are charged borrows from
        the shared page cache, released before the operation returns/yields.
        Failed frames keep their paid registry until their traceback is freed.
        """
        with self.segment.verified_read():
            outer = self._batch_depth == 0
            registry = None
            if outer and self.cache is not None:
                reservation = self.segment.scope.reserve(
                    ChargeSpec('record-batch-page-borrows', 128*2048+4096),
                    required=False, cancel=self.segment.cancel)
                if reservation is not None:
                    with reservation:
                        registry = reservation.commit(OrderedDict())
                self._batch_pages = registry
            self._batch_depth += 1
            try:
                yield
            except BaseException:
                if outer:
                    self._batch_pages = None
                raise
            else:
                if outer:
                    self._drop_batch_pages()
            finally:
                self._batch_depth -= 1

    def _drop_batch_pages(self):
        registry, self._batch_pages = self._batch_pages, None
        if registry is not None:
            pages = registry.value
            for owner in pages.values():
                owner.close()
            pages.clear()
            registry.close()

    def _borrowed(self, key):
        if self._batch_pages is None:
            return None
        pages = self._batch_pages.value
        owner = pages.get(key)
        if owner is not None:
            pages.move_to_end(key)
            return _BatchPage(owner)
        return None

    def _pin_page(self, key, owner):
        if owner is None or self._batch_pages is None:
            return owner
        pages = self._batch_pages.value
        if len(pages) == 128:
            _, previous = pages.popitem(last=False)
            previous.close()
        pages[key] = owner
        return _BatchPage(owner)

    def _fill(self, name, descriptor, binding, size):
        reservation = self.segment.scope.reserve(
            ChargeSpec('record-column-page', size+len(binding)+4096), required=False,
            cancel=self.segment.cancel)
        if reservation is None:
            return None
        with reservation:
            with self.segment.read(name, 0, descriptor['shape'][0], max_owned_bytes=T.CHUNK+OWNER_BYTES) as source:
                return reservation.commit(_ColumnPage(binding, descriptor['sha256'], size,
                                          bytes(memoryview(source.value))))

    def _cached_owner(self, name, descriptor, dtype, size):
        self.segment.check_unchanged()
        borrowed = self._borrowed((name, 0))
        if borrowed is not None:
            return borrowed
        scratch = _OptionalScratch(self.segment.scope.run_budget, 16384)
        if not scratch.admitted:
            return None
        binding = T.canonical(dict(file_identity=self.file_identity.hex(),
            segment=self.segment.info.ref.to_wire(), name=name, dtype=dtype.str,
            shape=descriptor['shape'], start=0, stop=descriptor['shape'][0]))
        key = _column_key(self.segment.scope.process_epoch, binding, descriptor['sha256'], size)
        held = self.cache.get(key, cancel=self.segment.cancel)
        if held is None:
            # Independent paid immutable copy lets the shared cache
            # outlive this view without pinning its SegmentView owner.
            held = self._fill(name, descriptor, binding, size)
            if held is not None:
                self.cache.offer_verified(key, held, cancel=self.segment.cancel)
        return self._pin_page((name, 0), held)

    def _cached_value(self, name, index, descriptor, dtype, size):
        held = self._cached_owner(name, descriptor, dtype, size)
        if held is None:
            return None
        with held:
            result = np.frombuffer(held.value.raw, dtype=dtype, count=1,
                                   offset=index*dtype.itemsize)[0].item()
        self.segment.check_unchanged()
        return result

    def _native_binding(self, name, index, descriptor, dtype):
        with self.segment._read_lock:
            return self._native_binding_locked(name, index, descriptor, dtype)

    def _native_binding_locked(self, name, index, descriptor, dtype):
        width = T.CHUNK//dtype.itemsize
        start = index//width*width
        stop = min(start+width, descriptor['shape'][0])
        cursors, cursor_key = self._page_cursors.value, (name, start)
        entry = cursors.get(cursor_key)
        if entry is not None:
            cursors.move_to_end(cursor_key)
            return entry
        rows = list(self.segment._entries(name=name, start=start, stop=stop))
        T.require(len(rows) == 1, 'native page must bind exactly one authenticated chunk')
        row, body = rows[0], rows[0]['content']
        T.require(body['start'] == start and body['count'] == stop-start and
                  body['dtype'] == dtype.str and math.prod(body['shape']) == descriptor['shape'][0],
                  'native page typed range differs')
        entry = (start, stop, body['chunk_id'], T.canonical(row['descriptor']), row['owner'])
        if len(cursors) == 128:
            cursors.popitem(last=False)
        cursors[cursor_key] = entry
        return entry

    def _cached_native_owner(self, name, index, descriptor, dtype):
        self.segment.check_unchanged()
        start = index//(T.CHUNK//dtype.itemsize)*(T.CHUNK//dtype.itemsize)
        borrowed = self._borrowed((name, start))
        if borrowed is not None:
            return borrowed, start, min(start+T.CHUNK//dtype.itemsize, descriptor['shape'][0])
        scratch = _OptionalScratch(self.segment.scope.run_budget, 16384)
        if not scratch.admitted:
            return None
        start, stop, chunk_id, native_descriptor, owner = self._native_binding(name, index, descriptor, dtype)
        size = (stop-start)*dtype.itemsize
        binding = T.canonical(dict(kind='native-chunk-v1', file_identity=self.file_identity.hex(),
            segment=self.segment.info.ref.to_wire(), name=name, dtype=dtype.str,
            shape=descriptor['shape'], start=start, stop=stop, owner=owner))
        key = _column_key(self.segment.scope.process_epoch, binding, chunk_id, size)
        held = self.cache.get(key, cancel=self.segment.cancel)
        if held is None:
            reservation = self.segment.scope.reserve(ChargeSpec('record-native-page', size+len(binding)+8192),
                                                      required=False, cancel=self.segment.cancel)
            if reservation is None:
                return None
            with reservation:
                with self.segment.read(name, start, stop, max_owned_bytes=T.CHUNK+OWNER_BYTES) as source:
                    held = reservation.commit(_NativeChunkPage(binding, chunk_id, size,
                        bytes(memoryview(source.value)), native_descriptor))
            self.cache.offer_verified(key, held, cancel=self.segment.cancel)
        return self._pin_page((name, start), held), start, stop

    def _cached_native_raw(self, name, start, stop, descriptor, dtype):
        size = (stop-start)*dtype.itemsize
        if size > T.CHUNK:
            return None
        reservation = self.segment.scope.reserve(ChargeSpec('record-column-slice', 2*size+4096),
                                                  required=False, cancel=self.segment.cancel)
        if reservation is None:
            return None
        with reservation:
            raw = bytearray()
            at = start
            while at < stop:
                result = self._cached_native_owner(name, at, descriptor, dtype)
                if result is None:
                    return None
                held, lo, hi = result
                end = min(stop, hi)
                with held:
                    raw.extend(memoryview(held.value.raw)[(at-lo)*dtype.itemsize:(end-lo)*dtype.itemsize])
                at = end
            self.segment.check_unchanged()
            return reservation.commit(bytes(raw))

    def value(self, name, index):
        descriptor = self.descriptors[name]
        T.require(type(index) is int and 0 <= index < descriptor['shape'][0],
                  'column index outside bounds')
        dtype = np.dtype(descriptor['dtype'])
        size = descriptor['shape'][0]*dtype.itemsize
        if self.cache is not None and size <= T.CHUNK:
            # Complete small columns use the authenticated column digest.
            try:
                result = self._cached_value(name, index, descriptor, dtype, size)
            except MemoryLimitError:
                result = None
            if result is not None:
                return result
        elif self.cache is not None and self._page_cursors is not None:
            try:
                page = self._cached_native_owner(name, index, descriptor, dtype)
                if page is not None:
                    held, start, _ = page
                    with held:
                        result = np.frombuffer(held.value.raw, dtype=dtype, count=1,
                            offset=(index-start)*dtype.itemsize)[0].item()
                    self.segment.check_unchanged()
                    return result
            except MemoryLimitError:
                pass
        self._drop_batch_pages()
        with self.segment.read(name, index, index+1, max_owned_bytes=65536) as row:
            return np.frombuffer(row.value, dtype=dtype, count=1)[0].item()

    def raw(self, name, start, stop):
        # Keys and string bodies use the same verified column as scalar reads.
        # Return a paid independent slice; no unowned cache backing can escape.
        descriptor = self.descriptors[name]
        dtype = np.dtype(descriptor['dtype'])
        size = descriptor['shape'][0]*dtype.itemsize
        T.require(type(start) is int and type(stop) is int and
                  0 <= start <= stop <= descriptor['shape'][0], 'raw column range outside bounds')
        if self.cache is not None and size <= T.CHUNK:
            try:
                held = self._cached_owner(name, descriptor, dtype, size)
                if held is not None:
                    with held:
                        result = _owned(self.segment.scope, (stop-start)*dtype.itemsize+4096,
                            lambda: bytes(memoryview(held.value.raw)[start*dtype.itemsize:stop*dtype.itemsize]),
                            'record-column-slice')
                        self.segment.check_unchanged()
                        return result
            except MemoryLimitError:
                pass
        elif self.cache is not None and self._page_cursors is not None:
            try:
                result = self._cached_native_raw(name, start, stop, descriptor, dtype)
                if result is not None:
                    return result
            except MemoryLimitError:
                pass
        self._drop_batch_pages()
        return self.segment.read(name, start, stop, max_owned_bytes=65536+2*(stop-start))


def _metadata(raw):
    T.require(type(raw) is bytes and len(raw) <= 65536, 'bounded immutable record metadata required')
    def pairs(rows):
        result = {}
        for key, value in rows:
            T.require(key not in result, 'duplicate metadata key')
            result[key] = value
        return result
    try:
        value = json.loads(raw, object_pairs_hook=pairs)
    except (ValueError, UnicodeError) as exc:
        raise ContractError('invalid record metadata') from exc
    T.require(type(value) is dict and set(value) == {'schema', 'profile', 'features', 'root', 'identity', 'arrays'},
              'unknown/missing record metadata field')
    T.require(T.canonical(value) == raw, 'noncanonical record metadata')
    T.require(value['schema'] == T.SCHEMA and value['profile'] == T.PROFILE and value['features'] == [],
              'unknown physical schema, profile or feature')
    identity = LogicalIdentity.from_wire(value['identity'])
    descriptors = value['arrays']
    T.require(type(descriptors) is dict and set(descriptors) == _NAMES, 'unknown/missing record column')
    for name, row in descriptors.items():
        T.require(type(row) is dict and set(row) == {'dtype', 'shape', 'sha256'}, 'invalid column descriptor')
        allowed = ('|u1',) if name in _BYTE else ('<u8',) if name in _U64 else ('<f8',) if name == 'float.value' else ('|u1', '<u2', '<u4', '<u8')
        T.require(row['dtype'] in allowed and type(row['shape']) is list and len(row['shape']) == 1,
                  'invalid authenticated dtype/shape')
        _bound(row['shape'][0], 'column length')
        T.require(type(row['sha256']) is str and len(row['sha256']) == 64 and
                  all(c in '0123456789abcdef' for c in row['sha256']), 'invalid column digest')
    return value, identity


class CompactRecord:
    """Sealed exact logical identity with explicitly owned traversal/expansion."""
    def __init__(self, owner, metadata, identity, columns, check):
        self._owner, self._meta, self._identity = owner, metadata, identity
        self._columns, self._check = columns, check
        self._root = metadata['root']

    @classmethod
    def _from_built(cls, raw_metadata, arrays, *, scope, check):
        metadata, identity = _metadata(raw_metadata)
        total = sum(a.nbytes for a in arrays.values())
        owner = _owned(scope, total+65536+len(raw_metadata)*8+1024*len(arrays),
                       lambda: (raw_metadata, T.freeze_arrays(arrays)), 'record-tables')
        return cls(owner, metadata, identity, _Memory(owner.value[1]), check)

    @classmethod
    def from_payload(cls, raw_metadata, arrays, *, scope, check, expected_identity=None):
        metadata_scratch = T.Scratch(scope.run_budget, 2 << 20)
        metadata, identity = _metadata(raw_metadata)
        T.require(set(arrays) == _NAMES, 'unknown/missing record array')
        for name, descriptor in metadata['arrays'].items():
            array = arrays[name]
            T.require(type(array) is np.ndarray and array.dtype.str == descriptor['dtype'] and
                      list(array.shape) == descriptor['shape'] and array.flags.c_contiguous,
                      'column descriptor differs')
            T.require(sha256(memoryview(array).cast('B')).hexdigest() == descriptor['sha256'], 'column digest differs')
        if expected_identity is not None:
            T.require(expected_identity == identity, 'logical identity differs')
        result = cls._from_built(raw_metadata, arrays, scope=scope, check=check)
        result._validate()
        del metadata_scratch
        return result

    @classmethod
    def from_segment(cls, segment, metadata=None, *, check=lambda: None, use_page_cache=True):
        """Own the SegmentView until all child references/streams are released.

        Metadata is the original bounded codec payload. WP1 authenticates the
        segment bindings; this layer checks physical dispatch and logical bytes.
        """
        scope = segment.scope
        metadata_scratch = T.Scratch(scope.run_budget, 2 << 20)
        if metadata is None:
            with segment.metadata() as held:
                raw = held.value
                parsed, identity = _metadata(raw)
        else:
            raw = metadata
            parsed, identity = _metadata(raw)
        T.require(segment.info.ref.identity == identity, 'segment logical identity differs')
        T.require(segment.info.array_count == len(_NAMES), 'segment array inventory differs')
        for name, descriptor in parsed['arrays'].items():
            with segment.info.array(name) as held:
                info = held.value
                T.require(info.dtype == descriptor['dtype'] and list(info.shape) == descriptor['shape'],
                          'segment column descriptor differs')
            digest = sha256()
            with segment.iter(name, block_bytes=T.CHUNK, max_owned_bytes=2*T.CHUNK) as stream:
                for block in stream:
                    with block:
                        digest.update(block.value)
            T.require(digest.hexdigest() == descriptor['sha256'], 'segment column digest differs')
        # Segment is intentionally owned as a dependency by this wrapper. Its
        # close is delayed until this backing allocation has no live borrows.
        owner = _owned(scope, 65536+8*len(raw), lambda: raw, 'record-segment-view',
                       dependencies=(segment._owner,))
        result = cls(owner, parsed, identity, _Segment(segment, parsed['arrays'],
                     use_page_cache=use_page_cache), check)
        result._validate()
        del metadata_scratch
        return result

    @property
    def scope(self):
        return self._owner.scope

    def _live(self):
        self._owner.value
        self._check()

    def _read_batch(self):
        return (self._columns.read_batch()
                if isinstance(self._columns, _Segment) else nullcontext())

    def identity(self):
        self._live()
        return self._identity

    def root(self):
        self._live()
        return RecordRef(self, self._root)

    def close(self):
        self._owner.assert_unborrowed()
        self._columns = self._meta = None
        self._owner.close()

    def _v(self, name, index):
        return self._columns.value(name, index)

    def _n(self, name):
        return self._meta['arrays'][name]['shape'][0]

    def _range(self, name, index):
        return self._v(name+'.offset', index), self._v(name+'.offset', index+1)

    def _bytes(self, name, start, stop):
        for at in range(start, stop, T.CHUNK):
            end = min(stop, at+T.CHUNK)
            if isinstance(self._columns, _Memory):
                yield self._columns.raw(name, at, end)
            else:
                with self._columns.raw(name, at, end) as held:
                    yield held.value

    def _token(self, index):
        a, b = self._range('token', index)
        return json.loads(b''.join(self._bytes('token.bytes', a, b)))

    def _int(self, index):
        if self._v('int.mode', index):
            value = 1 << self._v('int.exponent', index)
        else:
            a, b = self._range('int', index)
            value = int.from_bytes(b''.join(self._bytes('int.bytes', a, b)), 'little')
        return -value if self._v('int.sign', index) else value

    def _hex(self, index):
        yield b'"-0x' if self._v('int.sign', index) else b'"0x'
        if self._v('int.mode', index):
            exponent = self._v('int.exponent', index)
            yield b'1248'[exponent % 4:exponent % 4+1]
            zeros = exponent//4
            while zeros:
                amount = min(T.CHUNK, zeros)
                yield b'0'*amount
                zeros -= amount
        else:
            a, b = self._range('int', index)
            if a == b:
                yield b'0'
            first = True
            while b > a:
                lo = max(a, b-T.CHUNK//2)
                raw = b''.join(self._bytes('int.bytes', lo, b))
                token = raw[::-1].hex().encode('ascii')
                yield token.lstrip(b'0') if first else token
                first = False
                b = lo
        yield b'"'

    def _children(self, node):
        kind, payload = self._v('node.kind', node), self._v('node.payload', node)
        if kind == T.RATIONAL:
            return (self._v('q.numerator', payload), self._v('q.denominator', payload))
        a, b = self._range('node', node)
        return range(a, b)

    def _child(self, node, position):
        kind, payload = self._v('node.kind', node), self._v('node.payload', node)
        if kind == T.RATIONAL:
            return self._v('q.numerator' if position == 0 else 'q.denominator', payload)
        a, _ = self._range('node', node)
        return self._v('edge.child', a+position)

    def _size(self, node):
        kind = self._v('node.kind', node)
        if kind == T.RATIONAL:
            return 2
        if kind in (T.ARRAY, T.OBJECT):
            a, b = self._range('node', node)
            return b-a
        return self._v('node.length', node)

    def _parts(self, node, depth=0):
        self._check()
        T.require(depth <= T.MAX_DEPTH, 'record depth exceeds bound')
        kind, payload = self._v('node.kind', node), self._v('node.payload', node)
        if kind == T.TEXT:
            a, b = self._range('token', payload)
            yield from self._bytes('token.bytes', a, b)
        elif kind == T.HEX:
            yield from self._hex(payload)
        elif kind == T.IDENT:
            raw = b''.join(self._bytes('id.bytes', 32*payload, 32*(payload+1)))
            yield b'"'+raw.hex().encode('ascii')+b'"'
        elif kind in (T.ARRAY, T.OBJECT, T.RATIONAL):
            yield b'{' if kind == T.OBJECT else b'['
            size = self._size(node)
            if kind == T.OBJECT:
                a, _ = self._range('shape', self._v('node.shape', node))
            for i in range(size):
                if i:
                    yield b','
                if kind == T.OBJECT:
                    key = self._v('shape.key', a+i)
                    lo, hi = self._range('token', key)
                    yield from self._bytes('token.bytes', lo, hi)
                    yield b':'
                yield from self._parts(self._child(node, i), depth+1)
            yield b'}' if kind == T.OBJECT else b']'
        else:
            value = (None if kind == T.NULL else bool(payload) if kind == T.BOOL else
                     self._int(payload) if kind == T.INTEGER else self._v('float.value', payload))
            yield T.canonical(value)

    def _stream(self, node, max_chunk_bytes, parent_owner=None):
        _bound(max_chunk_bytes, 'chunk bound', T.CHUNK)
        T.require(max_chunk_bytes > 0, 'positive chunk bound required')
        self._live()
        anchor = (self._owner if parent_owner is None else parent_owner).retain()
        def chunks():
            scratch = T.Scratch(self.scope.run_budget, 3*T.CHUNK+65536+T.MAX_DEPTH*1024)
            buffer = bytearray()
            for part in self._parts(node):
                for start in range(0, len(part), max_chunk_bytes):
                    token = part[start:start+max_chunk_bytes]
                    if len(buffer)+len(token) > max_chunk_bytes:
                        yield _owned(self.scope, len(buffer)+128, lambda: bytes(buffer))
                        buffer.clear()
                    buffer.extend(token)
            if buffer:
                yield _owned(self.scope, len(buffer)+128, lambda: bytes(buffer))
            del scratch
        def generate():
            iterator = chunks()
            while True:
                with self._read_batch():
                    try:
                        block = next(iterator)
                    except StopIteration:
                        return
                yield block
        return OwnedStream(generate(), owners=(anchor,), scope=self.scope)

    def iter_json(self, *, max_chunk_bytes=T.CHUNK):
        return self._stream(self._root, max_chunk_bytes)

    def _export(self, node, *, max_logical_bytes, max_owned_bytes):
        with RecordRef(self, node) as ref:
            return _export_ref(ref, max_logical_bytes=max_logical_bytes,
                               max_owned_bytes=max_owned_bytes)

    def export(self, *, max_logical_bytes, max_owned_bytes):
        return self._export(self._root, max_logical_bytes=max_logical_bytes, max_owned_bytes=max_owned_bytes)

    def metadata_bytes(self):
        self._live()
        return _owned(self.scope, 65536, lambda: T.canonical(self._meta), 'record-metadata')

    def storage_payload(self):
        self._live()
        T.require(isinstance(self._columns, _Memory), 'persisted views use array_sources without eager arrays')
        return _owned(self.scope, 65536, lambda: (T.canonical(self._meta), self._columns.arrays),
                      'record-payload', dependencies=(self._owner,))

    def array_sources(self):
        self._live()
        for name in sorted(self._meta['arrays'], key=lambda n: n.encode('utf-8')):
            source = _ArraySource(self, name)
            try:
                yield source
            finally:
                source.close()

    def _validate(self):
        with self._read_batch():
            self._validate_batch()

    def _validate_batch(self):
        """Bounded structural scan plus exact identity; no recursive expansion."""
        work_budget = WorkBudget(T.MAX_BUILD_BYTES, parent=self.scope.run_budget)
        n = self._n('node.kind')
        T.require(0 < n <= T.MAX_ITEMS and type(self._root) is int and 0 <= self._root < n,
                  'invalid root/node count')
        for name in ('node.payload', 'node.shape', 'node.length', 'node.charge'):
            T.require(self._n(name) == n, 'node column count differs')
        for name in ('int.sign', 'float.value', 'q.numerator', 'q.denominator'):
            T.require(self._n(name) <= T.MAX_ITEMS, 'pool count exceeds bound')
        for name in ('token.offset', 'shape.offset'):
            T.require(1 <= self._n(name) <= T.MAX_ITEMS+1, 'offset pool count exceeds bound')
        T.require(self._n('edge.child') <= 4*T.MAX_ITEMS and self._n('shape.key') <= 4*T.MAX_ITEMS and
                  self._n('id.bytes') <= 32*T.MAX_ITEMS, 'edge/key/ID inventory exceeds bound')
        for prefix, count, total in (('node', n, self._n('edge.child')),
                ('shape', self._n('shape.offset')-1, self._n('shape.key')),
                ('token', self._n('token.offset')-1, self._n('token.bytes')),
                ('int', self._n('int.sign'), self._n('int.bytes'))):
            T.require(self._n(prefix+'.offset') == count+1 and self._v(prefix+'.offset', 0) == 0 and
                      self._v(prefix+'.offset', count) == total, 'invalid CSR extent')
            previous = 0
            for i in range(count+1):
                current = self._v(prefix+'.offset', i)
                T.require(previous <= current <= total, 'invalid CSR ordering')
                previous = current
        ints = self._n('int.sign')
        T.require(self._n('int.mode') == ints == self._n('int.exponent'), 'integer columns differ')
        T.require(self._n('q.numerator') == self._n('q.denominator') and self._n('id.bytes') % 32 == 0,
                  'invalid pair/ID columns')
        scratch = T.Scratch(work_budget, 65536+256*n)
        depths = np.zeros(n, dtype='u1')
        reachable = np.zeros(n, dtype='u1')
        widths = np.zeros(n, dtype='<u8')
        seen_nodes = {}
        for i in range(ints):
            self._check()
            a, b = self._range('int', i)
            mode, sign, exp = self._v('int.mode', i), self._v('int.sign', i), self._v('int.exponent', i)
            T.require(sign in (0, 1) and mode in (0, 1) and b-a <= T.MAX_INTEGER_BYTES,
                      'unknown integer sign/mode or magnitude bound')
            if mode:
                T.require(a == b and 64 <= exp < 8*T.MAX_INTEGER_BYTES, 'invalid dyadic encoding')
            else:
                T.require(exp == 0 and (b > a or sign == 0), 'invalid integer zero/exponent')
                if b > a:
                    T.require(next(self._bytes('int.bytes', b-1, b))[0] != 0, 'nonminimal binary integer')
        for i in range(self._n('float.value')):
            T.require(math.isfinite(self._v('float.value', i)), 'nonfinite float')
        for i in range(self._n('token.offset')-1):
            a, b = self._range('token', i)
            T.require(2 <= b-a <= T.MAX_TOKEN_BYTES, 'token length exceeds bound')
            token_scratch = T.Scratch(work_budget, 4096+16*(b-a))
            raw = b''.join(self._bytes('token.bytes', a, b))
            value = json.loads(raw)
            T.require(type(value) is str and T.canonical(value) == raw, 'noncanonical string token')
            del raw, value, token_scratch
        limits = {T.NULL: 1, T.BOOL: 2, T.INTEGER: ints, T.FLOAT: self._n('float.value'),
                  T.TEXT: self._n('token.offset')-1, T.IDENT: self._n('id.bytes')//32,
                  T.HEX: ints, T.RATIONAL: self._n('q.numerator')}
        ref_max = max(n, ints, limits[T.TEXT], limits[T.FLOAT], limits[T.IDENT],
                      limits[T.RATIONAL], self._n('shape.offset')-1)
        for name, maximum in (('node.payload', ref_max), ('node.shape', self._n('shape.offset')-1),
                              ('edge.child', n), ('shape.key', limits[T.TEXT]),
                              ('q.numerator', n), ('q.denominator', n)):
            T.require(self._meta['arrays'][name]['dtype'] == np.dtype(T.narrow(maximum)).str,
                      'pool references are not the narrowest authenticated width')
        for i in range(n):
            self._check()
            kind, payload, shape = self._v('node.kind', i), self._v('node.payload', i), self._v('node.shape', i)
            a, b = self._range('node', i)
            T.require(0 <= kind <= T.RATIONAL, 'unknown node tag')
            if kind in (T.ARRAY, T.OBJECT, T.RATIONAL):
                T.require(kind == T.RATIONAL or payload == 0, 'hidden container payload')
                if kind == T.RATIONAL:
                    T.require(payload < limits[kind] and a == b, 'invalid rational reference')
                size = self._size(i)
                width = 2+max(0, size-1)
                if kind == T.OBJECT:
                    T.require(shape < self._n('shape.offset')-1, 'shape reference outside pool')
                    sa, sb = self._range('shape', shape)
                    T.require(sb-sa == size, 'shape/row cardinality differs')
                    previous = None
                    previous_scratch = None
                    for j in range(sa, sb):
                        key = self._v('shape.key', j)
                        T.require(key < limits[T.TEXT], 'shape key outside pool')
                        lo, hi = self._range('token', key)
                        key_scratch = T.Scratch(work_budget, 4096+32*(hi-lo))
                        value = self._token(key)
                        T.require(previous is None or previous < value, 'key shape not sorted and unique')
                        # The preceding decoded key survives across iterations;
                        # its lease must survive with it, including on failure.
                        previous = None
                        del previous_scratch
                        previous = value
                        previous_scratch = key_scratch
                        width += hi-lo+1
                        del value, key_scratch
                    previous = None
                    del previous_scratch
                else:
                    T.require(shape == 0, 'hidden shape on array')
                depth = 1
                for j in range(size):
                    child = self._child(i, j)
                    T.require(child < i, 'forward/cyclic child reference')
                    if kind == T.RATIONAL:
                        T.require(self._v('node.kind', child) == T.HEX, 'rational spelling class differs')
                    depth = max(depth, 1+int(depths[child]))
                    width += int(widths[child])
                T.require(depth <= T.MAX_DEPTH, 'DAG depth exceeds bound')
                depths[i] = depth
            else:
                T.require(a == b and shape == 0 and payload < limits[kind], 'invalid scalar reference')
                minimum = 4096
                if kind in (T.TEXT, T.HEX):
                    minimum = max(minimum, 4096+16*self._v('node.length', i))
                if kind == T.INTEGER:
                    lo, hi = self._range('int', payload)
                    binary = (self._v('int.exponent', payload)//8+1
                              if self._v('int.mode', payload) else hi-lo)
                    minimum = max(minimum, 4096+16*binary)
                T.require(self._v('node.charge', i) >= minimum, 'understated scalar allocation bound')
                if kind == T.TEXT:
                    lo, hi = self._range('token', payload)
                    width = hi-lo
                elif kind == T.IDENT:
                    width = 66
                elif kind == T.HEX:
                    if self._v('int.mode', payload):
                        digits = self._v('int.exponent', payload)//4+1
                    else:
                        lo, hi = self._range('int', payload)
                        high = next(self._bytes('int.bytes', hi-1, hi))[0] if hi > lo else 0
                        digits = max(1, 2*(hi-lo)-(high < 16))
                    width = 4+digits+self._v('int.sign', payload)
                else:
                    scalar_scratch = T.Scratch(work_budget, self._v('node.charge', i))
                    width = sum(len(part) for part in self._parts(i))
                    del scalar_scratch
            T.require(width <= (1 << 64)-1 and width == self._v('node.length', i),
                      'node canonical length differs')
            widths[i] = width
            key_hash = sha256(bytes((kind,))+payload.to_bytes(8, 'little')+shape.to_bytes(8, 'little'))
            for edge in range(a, b):
                key_hash.update(self._v('edge.child', edge).to_bytes(8, 'little'))
            key = key_hash.digest()
            if key in seen_nodes:
                other = seen_nodes[key]
                oa, ob = self._range('node', other)
                equal = (kind == self._v('node.kind', other) and payload == self._v('node.payload', other)
                         and shape == self._v('node.shape', other) and b-a == ob-oa and
                         all(self._v('edge.child', a+j) == self._v('edge.child', oa+j) for j in range(b-a)))
                T.require(not equal, 'duplicate hash-consed node')
            seen_nodes[key] = i
        reachable[self._root] = 1
        for i in range(n-1, -1, -1):
            if reachable[i] and self._v('node.kind', i) in (T.ARRAY, T.OBJECT, T.RATIONAL):
                for j in range(self._size(i)):
                    reachable[self._child(i, j)] = 1
        T.require(bool(np.all(reachable)), 'unreachable hidden scientific node')
        digest, length = sha256(), 0
        stream_scratch = T.Scratch(work_budget, 65536*4+T.MAX_DEPTH*1024)
        for part in self._parts(self._root):
            digest.update(part); length += len(part)
        T.require(length == self._identity.canonical_bytes == self._v('node.length', self._root) and
                  digest.hexdigest() == self._identity.sha256, 'logical canonical identity differs')
        del stream_scratch, scratch


class RecordRef:
    """Explicit reference. Intentionally has no mapping/sequence protocol."""
    def __init__(self, view, index, *, fields=None, selection_owner=None, parent_owner=None):
        T.require(isinstance(view, CompactRecord) and type(index) is int and
                  0 <= index < view._n('node.kind'), 'reference outside validated record')
        self._view, self.index, self._fields = view, index, fields
        self._owner = (view._owner if parent_owner is None else parent_owner).retain()
        self._selection_owner = None if selection_owner is None else selection_owner.retain()

    @property
    def scope(self):
        return self._owner.scope

    def _live(self):
        self._owner.value
        self._view._check()

    def borrow(self):
        """An independently paid child wrapper; the parent remains borrowed."""
        from copy import copy
        self._live()
        result = copy(self)
        result._owner = self._owner.retain()
        if self._selection_owner is not None:
            result._selection_owner = self._selection_owner.retain()
        return result

    def __enter__(self):
        self._live()
        return self

    def __exit__(self, *_):
        self.close()

    def _logical_length(self):
        self._live()
        T.require(self._fields is None, 'row projection requires explicit object selection')
        return self._view._v('node.length', self.index)

    def keys(self, *, max_owned_bytes=4 << 20):
        """Explicit paid object-key inventory, never a Mapping protocol."""
        self._live()
        T.require(self.kind == 'object', 'object keys required')
        _bound(max_owned_bytes, 'key inventory bound')
        with self._view._read_batch():
            view = self._view
            start, stop = view._range('shape', view._v('node.shape', self.index))
            charge = 4096+128*(stop-start)
            for at in range(start, stop):
                token = view._v('shape.key', at)
                a, b = view._range('token', token)
                charge += 32*(b-a)
            T.require(charge+OWNER_BYTES <= max_owned_bytes, 'object keys exceed owned byte bound')
            def decode():
                return tuple(view._token(view._v('shape.key', at)) for at in range(start, stop)
                             if self._fields is None or view._token(view._v('shape.key', at)) in self._fields)
            return _owned(self.scope, charge, decode, 'record-keys', dependencies=(self._owner,))

    def get(self, name, default=None, *, max_owned_bytes=4 << 20):
        """Owned scalar or explicit child reference; containers never expand."""
        try:
            child = self.field(name)
        except KeyError:
            T.require(default is None or type(default) in (bool, int, float, str),
                      'missing-field default must be a scalar')
            record = T.RecordCodec().pack_record(default, record_schema='atlas.json-value.v1',
                                                scope=self.scope, check=self._live)
            with record.root() as root:
                result = root.scalar(max_owned_bytes=max_owned_bytes)
            record.close()
            return result
        if child.kind != 'scalar':
            return child
        try:
            return child.scalar(max_owned_bytes=max_owned_bytes)
        finally:
            child.close()

    def select(self, names):
        return _ObjectRecordRef(self, fields=names)

    def without(self, names):
        return _ObjectRecordRef(self, without=names)

    @property
    def kind(self):
        self._live()
        kind = self._view._v('node.kind', self.index)
        return 'object' if kind == T.OBJECT else 'array' if kind in (T.ARRAY, T.RATIONAL) else 'scalar'

    @property
    def size(self):
        self._live()
        return len(self._fields) if self._fields is not None else self._view._size(self.index)

    def field(self, name):
        self._live()
        with self._view._read_batch():
            return self._field_batch(name)

    def _field_batch(self, name):
        T.require(self.kind == 'object' and type(name) is str, 'object and string field required')
        if self._fields is not None and name not in self._fields:
            raise KeyError(name)
        v = self._view
        start, stop = v._range('shape', v._v('node.shape', self.index))
        low, high = start, stop
        while low < high:
            middle = (low+high)//2
            token = v._v('shape.key', middle)
            a, b = v._range('token', token)
            scratch = T.Scratch(self.scope.run_budget, 4096+32*(b-a))
            key = v._token(token)
            if key < name:
                low = middle+1
            else:
                high = middle
            del key, scratch
        if low == stop:
            raise KeyError(name)
        token = v._v('shape.key', low)
        a, b = v._range('token', token)
        scratch = T.Scratch(self.scope.run_budget, 4096+32*(b-a))
        if v._token(token) != name:
            raise KeyError(name)
        del scratch
        return RecordRef(v, v._child(self.index, low-start), parent_owner=self._owner)

    def at(self, index):
        T.require(self.kind == 'array' and type(index) is int and 0 <= index < self.size, 'array index outside record')
        return RecordRef(self._view, self._view._child(self.index, index), parent_owner=self._owner)

    def scalar(self, *, max_owned_bytes):
        self._live()
        with self._view._read_batch():
            return self._scalar_batch(max_owned_bytes=max_owned_bytes)

    def _scalar_batch(self, *, max_owned_bytes):
        T.require(self.kind == 'scalar', 'container expansion requires explicit export')
        _bound(max_owned_bytes, 'scalar allocation bound')
        charge = self._view._v('node.charge', self.index)
        T.require(charge+OWNER_BYTES <= max_owned_bytes, 'scalar allocation bound exceeded before decode')
        return _owned(self.scope, charge, lambda: json.loads(b''.join(self._view._parts(self.index))), 'record-scalar')

    def iter_rows(self, *, max_rows, max_owned_bytes, fields=None):
        T.require(self.kind == 'array', 'row iteration requires array')
        _bound(max_rows, 'row count', T.MAX_ITEMS)
        _bound(max_owned_bytes, 'row byte bound')
        T.require(max_rows > 0 and max_owned_bytes >= OWNER_BYTES+8192, 'positive bounded row block required')
        selection = None
        if fields is not None:
            T.require(type(fields) in (tuple, list) and len(fields) <= T.MAX_ITEMS and
                      all(type(f) is str for f in fields), 'bounded string fields required')
            field_charge = 4096+128*len(fields)+sum(16*len(f) for f in fields)
            T.require(field_charge+OWNER_BYTES <= max_owned_bytes, 'field selection exceeds owned byte bound')
            def selected_fields():
                T.require(len(set(fields)) == len(fields), 'distinct string fields required')
                return tuple(fields)
            selection = _owned(self.scope, field_charge, selected_fields, 'record-selected-fields')
            fields = selection.value
        view, node = self._view, self.index
        anchor = self._owner.retain()
        def generate():
            at, size = 0, view._size(node)
            count = min(max_rows, (max_owned_bytes-OWNER_BYTES)//(12288 if selection else 8192))
            T.require(count > 0, 'row block cannot fit one shallow reference')
            while at < size:
                amount = min(count, size-at)
                def make():
                    rows = tuple(RecordRef(view, view._child(node, i), fields=fields,
                                          selection_owner=selection, parent_owner=anchor)
                                 for i in range(at, at+amount))
                    if fields is not None:
                        for row in rows:
                            T.require(row.kind == 'object', 'field selection requires object rows')
                            for field in fields:
                                child = row.field(field)
                                child.close()
                    return rows
                yield _owned(self.scope, 1024+amount*1024, make, 'record-rows')
                at += amount
        return OwnedStream(generate(), owners=(anchor,) if selection is None else (anchor, selection), scope=self.scope)

    def identity(self):
        self._live()
        if self._fields is not None:
            raise ContractError('projection has no implicit full-record identity')
        digest, length = sha256(), 0
        with self.iter_json() as stream:
            for held in stream:
                with held:
                    digest.update(held.value); length += len(held.value)
        return LogicalIdentity(self._view._identity.record_schema, digest.hexdigest(), length)

    def iter_json(self, *, max_chunk_bytes=T.CHUNK):
        self._live()
        T.require(self._fields is None, 'projection streaming requires an explicit selected-object adapter')
        return self._view._stream(self.index, max_chunk_bytes, parent_owner=self._owner)

    def export(self, *, max_logical_bytes, max_owned_bytes):
        self._live()
        T.require(self._fields is None, 'projection export requires explicit field selection')
        return _export_ref(self, max_logical_bytes=max_logical_bytes, max_owned_bytes=max_owned_bytes)

    def close(self):
        self._owner.close()
        self._fields = None
        if self._selection_owner is not None:
            self._selection_owner.close()
            self._selection_owner = None
        self._view = None


class LogicalRecord(RecordRef):
    pass


class LogicalExchange(LogicalRecord):
    @classmethod
    def from_body(cls, record, *, state_id, result_id):
        """Public exchange fields over one compact body; no second body pack."""
        from compact_contracts import _sha
        _sha(state_id, 'state ID'); _sha(result_id, 'result ID')
        body = record.root() if isinstance(record, CompactRecord) else record.borrow()
        headers = T.RecordCodec().pack_record(dict(state_id=state_id, result_id=result_id),
            record_schema='atlas.exchange-header.v1', scope=body.scope, check=body._view._check)
        overlay = headers.root()
        result = _ObjectRecordRef(body, overlay=overlay)
        # The result retains the tiny header backing as well as the original body.
        return result

    @classmethod
    def from_records(cls, body, **children):
        """Compose borrowed child records without encoding them again."""
        return _ObjectRecordRef(body, overrides=children)

    def body(self):
        return self.without(('state_id', 'result_id'))

    def composite_identity(self, state_id, *, record_schema='atlas.exchange-result.v1'):
        """Original identity is hash({state_id, exchange: body}), in that order
        after legacy sorted-key canonicalisation (exchange precedes state_id).
        Role separation is explicit; no Mapping conversion or synthetic merge.
        """
        T.require(type(state_id) is str and len(state_id) == 64 and
                  all(c in '0123456789abcdef' for c in state_id), 'state_id must be an exact content ID')
        digest, length = sha256(), 0
        prefix, suffix = b'{"exchange":', b',"state_id":'+T.canonical(state_id)+b'}'
        digest.update(prefix); length += len(prefix)
        with self.iter_json() as stream:
            for block in stream:
                with block:
                    digest.update(block.value); length += len(block.value)
        digest.update(suffix); length += len(suffix)
        return LogicalIdentity(record_schema, digest.hexdigest(), length)


class _ObjectRecordRef(LogicalExchange):
    """Paid, canonical object selection/overlay over immutable child references."""
    def __init__(self, base, *, fields=None, without=(), overlay=None, overrides=None):
        T.require(isinstance(base, RecordRef) and base.kind == 'object', 'object base required')
        T.require(overlay is None or isinstance(overlay, RecordRef) and
                  overlay.kind == 'object' and overlay.scope is base.scope, 'same-scope object overlay required')
        for names in (without, () if fields is None else fields):
            T.require(type(names) in (tuple, list) and len(names) <= T.MAX_ITEMS and
                      all(type(name) is str for name in names), 'explicit bounded string field names required')
        T.require(overrides is None or type(overrides) is dict and
                  all(type(k) is str and isinstance(v, RecordRef) and v.scope is base.scope
                      for k, v in overrides.items()), 'same-scope child overrides required')
        T.require(overlay is None or overrides is None, 'one overlay source required')
        with base.keys(max_owned_bytes=T.MAX_ROW_WORK_BYTES) as base_keys:
            extra = None if overlay is None else overlay.keys(max_owned_bytes=T.MAX_ROW_WORK_BYTES)
            try:
                overlay_keys = tuple(overrides) if overrides is not None else (() if extra is None else extra.value)
                charge = (8192+256*(len(base_keys.value)+len(overlay_keys))+
                          32*sum(map(len, base_keys.value))+32*sum(map(len, overlay_keys)))
                T.require(charge+OWNER_BYTES <= T.MAX_ROW_WORK_BYTES, 'object selection exceeds row bound')
                def make():
                    keys = set(base_keys.value) | set(overlay_keys)
                    if fields is not None:
                        T.require(len(set(fields)) == len(fields), 'duplicate selected fields')
                        for name in fields:
                            if name not in keys:
                                raise KeyError(name)
                        keys.intersection_update(fields)
                    keys.difference_update(without)
                    keys = tuple(sorted(keys))
                    length = 2+max(0, len(keys)-1)
                    for name in keys:
                        child = (overrides[name].borrow() if overrides is not None and name in overrides
                                 else (overlay if name in overlay_keys else base).field(name))
                        with child:
                            length += len(T.canonical(name))+1+child._logical_length()
                    return (base.borrow(), None if overlay is None else overlay.borrow(),
                            keys, frozenset(overlay_keys), length,
                            {} if overrides is None else {k: v.borrow() for k, v in overrides.items()})
                self._owner = _owned(base.scope, charge, make, 'record-object-view',
                    dependencies=(base._owner,) if overlay is None else (base._owner, overlay._owner))
            finally:
                if extra is not None:
                    extra.close()
        self._view, self.index = base._view, base.index
        self._fields = self._selection_owner = None

    def _live(self):
        base, overlay, _, _, _, overrides = self._owner.value
        base._live()
        if overlay is not None:
            overlay._live()
        for child in overrides.values():
            child._live()

    @property
    def kind(self):
        self._live()
        return 'object'

    @property
    def size(self):
        self._live()
        return len(self._owner.value[2])

    def _logical_length(self):
        self._live()
        return self._owner.value[4]

    def keys(self, *, max_owned_bytes=4 << 20):
        self._live()
        _bound(max_owned_bytes, 'key inventory bound')
        names = self._owner.value[2]
        charge = 4096+128*len(names)+32*sum(map(len, names))
        T.require(charge+OWNER_BYTES <= max_owned_bytes, 'object keys exceed owned byte bound')
        return _owned(self.scope, charge, lambda: names, 'record-keys', dependencies=(self._owner,))

    def field(self, name):
        self._live()
        T.require(type(name) is str, 'string field required')
        base, overlay, names, overridden, _, overrides = self._owner.value
        if name not in names:
            raise KeyError(name)
        if name in overrides:
            return overrides[name].borrow()
        return (overlay if name in overridden else base).field(name)

    def iter_json(self, *, max_chunk_bytes=T.CHUNK):
        self._live()
        T.require(type(max_chunk_bytes) is int and 0 < max_chunk_bytes <= T.CHUNK,
                  'positive bounded object stream chunk required')
        anchor = self.borrow()
        def parts():
            yield b'{'
            for at, name in enumerate(anchor._owner.value[2]):
                if at:
                    yield b','
                yield from T.string_parts(name, max_chunk_bytes)
                yield b':'
                with anchor.field(name) as child, child.iter_json(max_chunk_bytes=max_chunk_bytes) as stream:
                    for block in stream:
                        with block:
                            yield block.value
            yield b'}'
        def generate():
            scratch = T.Scratch(anchor.scope.run_budget, 65536+4*max_chunk_bytes)
            buffer = bytearray()
            for part in parts():
                anchor._live()
                for at in range(0, len(part), max_chunk_bytes):
                    buffer.extend(part[at:at+max_chunk_bytes])
                    if len(buffer) >= max_chunk_bytes:
                        raw = _owned(anchor.scope, 4096+max_chunk_bytes,
                                     lambda chunk_buffer=buffer: bytes(chunk_buffer[:max_chunk_bytes]), 'record-object-chunk')
                        del buffer[:max_chunk_bytes]
                        yield raw
            if buffer:
                yield _owned(anchor.scope, 4096+len(buffer), lambda chunk_buffer=buffer: bytes(chunk_buffer), 'record-object-chunk')
            del buffer, scratch
        return OwnedStream(generate(), owners=(anchor._owner,), scope=self.scope)

    def export(self, *, max_logical_bytes, max_owned_bytes):
        return _export_ref(self, max_logical_bytes=max_logical_bytes, max_owned_bytes=max_owned_bytes)


def _decoded_stats(ref, cap, memo):
    """Bound expanded Python objects using validated structure, not JSON width.

    Repeated DAG children count on every edge: deduplicated storage never
    discounts the separate objects a native consumer requests. The bounded
    memo only avoids re-counting the same immutable subtree.
    """
    ref._live()
    ordinary = type(ref) in (RecordRef, LogicalRecord, LogicalExchange)
    key = ((id(ref._view), ref.index) if ordinary else
           (ref._owner.allocation_id, ref.index, ref.kind, ref._logical_length()))
    if key in memo:
        return memo[key]
    kind, maximum = ref.kind, 0
    if kind == 'scalar':
        length = ref._logical_length()
        tag = ref._view._v('node.kind', ref.index) if ordinary else None
        if not ordinary:
            # Domain adapters can expose authenticated scalars outside the
            # backing DAG. Bound their actual canonical width conservatively.
            cost = 128+4*length
        elif tag in (T.TEXT, T.HEX, T.IDENT):
            # Unicode may widen an otherwise ASCII string. Exact hex and IDs
            # are authenticated ASCII and cannot have that widening.
            cost = 128+4*length if tag == T.TEXT else 64+length
        elif tag == T.INTEGER:
            cost = 128+4*length
        else:
            cost = 128
        maximum = length
    else:
        count = ref.size
        # Includes container growth and a native row's one shallow dict copy.
        cost = 512+128*count if kind == 'object' else 64+8*count
        if kind == 'object':
            with ref.keys(max_owned_bytes=T.MAX_ROW_WORK_BYTES) as names:
                for name in names.value:
                    key_bytes = sum(len(part) for part in T.string_parts(name))
                    cost += 128+4*key_bytes
                    maximum = max(maximum, key_bytes)
                    with ref.field(name) as child:
                        amount, scalar = _decoded_stats(child, cap, memo)
                    cost += amount
                    maximum = max(maximum, scalar)
                    T.require(cost <= cap, 'owned export bound exceeded before allocation')
        else:
            for at in range(count):
                with ref.at(at) as child:
                    amount, scalar = _decoded_stats(child, cap, memo)
                cost += amount
                maximum = max(maximum, scalar)
                T.require(cost <= cap, 'owned export bound exceeded before allocation')
    T.require(cost <= cap, 'owned export bound exceeded before allocation')
    result = cost, maximum
    if len(memo) < 256:
        memo[key] = result
    return result


def _decode_ref(ref):
    """Direct bounded construction: only individual scalars pass through JSON."""
    with ref._view._read_batch():
        if ref.kind == 'scalar':
            if type(ref) not in (RecordRef, LogicalRecord, LogicalExchange):
                with ref.scalar(max_owned_bytes=T.MAX_ROW_WORK_BYTES) as scalar:
                    return scalar.value
            return json.loads(b''.join(ref._view._parts(ref.index)))
        if ref.kind == 'object':
            result = {}
            with ref.keys(max_owned_bytes=T.MAX_ROW_WORK_BYTES) as names:
                for name in names.value:
                    with ref.field(name) as child:
                        result[name] = _decode_ref(child)
            return result
        # Allocate the exact pointer vector once, avoiding append overgrowth.
        result = [None]*ref.size
        for at in range(ref.size):
            with ref.at(at) as child:
                result[at] = _decode_ref(child)
        return result


def _export_ref(ref, *, max_logical_bytes, max_owned_bytes):
    _bound(max_logical_bytes, 'logical export bound')
    _bound(max_owned_bytes, 'owned export bound')
    ref._live()
    length = ref._logical_length()
    T.require(length <= max_logical_bytes, 'logical export bound exceeded')
    # Keep the established C JSON decoder for small rows where its conservative
    # admission already fits. Larger fields use the structural/direct route;
    # no whole graph can enter through this bounded 32 KiB fast path.
    legacy_charge = 65536+192*length
    if (type(ref) in (RecordRef, LogicalRecord, LogicalExchange) and length <= 32768 and
            legacy_charge+OWNER_BYTES <= max_owned_bytes):
        def small_decode():
            with ref._view._read_batch():
                return json.loads(b''.join(ref._view._parts(ref.index)))
        return _owned(ref.scope, legacy_charge, small_decode, 'record-export')
    # Fixed preflight funding covers the bounded memo, traversal stack and
    # key-encoding chunks; all child/key carriers have their own reservations.
    scratch = T.Scratch(ref.scope.run_budget, 65536+256*256+T.MAX_DEPTH*1024)
    with ref._view._read_batch():
        decoded, scalar = _decoded_stats(ref, max_owned_bytes, {})
    charge = 65536+decoded+8*scalar
    T.require(charge+OWNER_BYTES <= max_owned_bytes, 'owned export bound exceeded before allocation')
    del scratch
    return _owned(ref.scope, charge, lambda: _decode_ref(ref), 'record-export')


class _ArraySource:
    def __init__(self, record, name):
        self.record, self.name = record, name
        self._owner = record._owner.retain()
        row = record._meta['arrays'][name]
        self.info = T.ArrayInfo(name, row['dtype'], tuple(row['shape']),
                               row['shape'][0]*np.dtype(row['dtype']).itemsize)

    def blocks(self, *, max_owned_bytes):
        T.require(max_owned_bytes >= OWNER_BYTES+128+8, 'array output bound too small')
        amount = min(T.CHUNK, max_owned_bytes-OWNER_BYTES-128)
        itemsize = np.dtype(self.info.dtype).itemsize
        amount -= amount % itemsize
        T.require(amount > 0, 'array output bound below element width')
        record, name = self.record, self.name
        anchor = self._owner.retain()
        def generate():
            for start in range(0, self.info.logical_bytes, amount):
                stop = min(self.info.logical_bytes, start+amount)
                if isinstance(record._columns, _Memory):
                    yield _owned(record.scope, stop-start+128,
                                 lambda: bytes(record._columns.raw(name, start, stop)), 'record-array-block')
                else:
                    yield record._columns.segment.read(name, start//itemsize, stop//itemsize,
                                                       max_owned_bytes=max_owned_bytes)
        return OwnedStream(generate(), owners=(anchor,), scope=record.scope)

    def close(self):
        self._owner.close()
        self.record = None
