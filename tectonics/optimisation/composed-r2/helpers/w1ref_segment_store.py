"""Bounded, authenticated typed segments over an immutable interval store set.

Native v1 chunk identities and per-file schemas are unchanged. This layer puts
external locators in bounded metadata pages, never native local chunk arrays.
Logical JSON admission belongs to the codec/domain consumer, not this module.
"""
from __future__ import annotations

from concurrent.futures import CancelledError
from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import sha256
import json
import math
from threading import RLock

import numpy as np

from atlas_tectonics.integration_spatial_transport import _workspace

from compact_contracts import (BindingIndexRef, ContractError, LogicalIdentity,
    SnapshotLocator, SegmentRef, SEGMENT_REF_SCHEMA, BINDING_INDEX_SCHEMA,
    BINDING_PAGE_BYTES, INDEX_MAX_DEPTH, NATIVE_CHUNK_BYTES, ROOT_METADATA_MAX,
    SEGMENT_MANIFEST_BYTES, UINT64_MAX, validate_segment_budget)
from content_cache import ChargeSpec, OwnedStream

ROOT_SCHEMA = 'atlas.segment-root.v1'
PAGE_SCHEMA = 'atlas.binding-page.v1'
# A fixed fan-out keeps the content tree independent of locator/codec spelling.
# 16 also leaves room for maximal 256-byte names and 16 uint64 dimensions.
FANOUT = 16
BUILDER_BYTES = 8 << 20


def require(condition, message):
    if not condition:
        raise ContractError(message)


def cancel_check(cancel):
    if cancel is not None and cancel.is_set():
        raise CancelledError('segmented operation cancelled')


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=True, allow_nan=False).encode('ascii')


def _pairs(items):
    result = {}
    for key, value in items:
        require(key not in result, 'duplicate metadata key')
        result[key] = value
    return result


def parse(raw):
    try:
        result = json.loads(raw, object_pairs_hook=_pairs,
                            parse_constant=lambda _: (_ for _ in ()).throw(ContractError('nonfinite metadata')))
        require(canonical(result) == raw, 'noncanonical metadata')
        return result
    except (ValueError, TypeError, UnicodeError, RecursionError) as exc:
        if isinstance(exc, ContractError):
            raise
        raise ContractError('invalid canonical metadata') from exc


def h(tag, body):
    return sha256(tag.encode('ascii') + b'\0' + canonical(body)).hexdigest()


def _uint(value, name):
    require(type(value) is int and 0 <= value <= UINT64_MAX, name + ' is not uint64')
    return value


def _digest(value):
    require(type(value) is str and len(value) == 64 and
            all(c in '0123456789abcdef' for c in value), 'invalid digest')
    return value


def _owned(scope, value, size, purpose, *, dependencies=()):
    reservation = scope.reserve(ChargeSpec(purpose, size), required=True, cancel=None)
    return reservation.commit(value, dependencies=dependencies)


def _same_scope(obj, scope):
    require(obj.scope is scope, 'foreign retained scope')


def _requester(resolver):
    if hasattr(resolver, 'interval'):
        return resolver.interval
    require(resolver.head is not None, 'no accepted interval head')
    return resolver.head.interval


def _manifest(resolver, locator, cancel):
    if hasattr(resolver, 'interval'):
        return resolver.resolve_manifest(locator, cancel=cancel)
    return resolver.resolve_manifest(_requester(resolver), locator, cancel=cancel)


def _chunk(resolver, owner, key, descriptor, cancel):
    if hasattr(resolver, 'interval'):
        return resolver.resolve_chunk(owner, key, descriptor, cancel=cancel)
    return resolver.resolve_chunk(_requester(resolver), owner, key, descriptor, cancel=cancel)


def _metadata(resolver, locator, scope, cancel):
    """Decode bounded native manifest metadata under a paid owner.

    The raw owner and reservation deliberately remain in failed frames. The
    ownership implementation keeps their charge if a traceback is retained.
    """
    raw = _manifest(resolver, locator, cancel)
    require(len(raw.value) <= SEGMENT_MANIFEST_BYTES, 'native manifest exceeds segment target')
    reserve = scope.reserve(ChargeSpec('segment-metadata', 8 * len(raw.value) + 65536),
                            required=True, cancel=cancel)
    native = parse(raw.value)
    require(type(native) is dict and native.get('schema') == 'atlas.array-store.v1' and
            native.get('invocation') == locator.snapshot_key, 'native root binding differs')
    arrays = native.get('arrays')
    require(type(arrays) is dict and bool(arrays), 'metadata carrier inventory missing')
    for desc in arrays.values():
        require(type(desc) is dict and set(desc) == {'dtype', 'shape', 'chunks'} and
                desc['chunks'] == [] and math.prod(desc['shape']) == 0,
                'index/root has unexpected payload arrays')
    metadata = native.get('metadata')
    require(type(metadata) is dict and len(canonical(metadata)) <= ROOT_METADATA_MAX,
            'root/index metadata exceeds bound')
    result = reserve.commit(metadata)
    del native, arrays
    raw.close()
    return result


@dataclass(frozen=True, slots=True)
class ArrayInfo:
    name: str
    dtype: str
    shape: tuple[int, ...]
    logical_bytes: int

    def __post_init__(self):
        require(type(self.name) is str and bool(self.name) and
                len(self.name.encode('utf-8')) <= 256, 'bounded UTF-8 array name required')
        try:
            dtype = np.dtype(self.dtype)
        except (TypeError, ValueError) as exc:
            raise ContractError('invalid typed array') from exc
        require(dtype.str == self.dtype and dtype.kind in 'biuf' and dtype.itemsize in (1, 2, 4, 8),
                'unsupported/noncanonical array dtype')
        require(type(self.shape) is tuple and len(self.shape) <= 16, 'bounded shape required')
        for n in self.shape:
            _uint(n, 'dimension')
        _uint(self.logical_bytes, 'logical array bytes')
        require(math.prod(self.shape) * dtype.itemsize == self.logical_bytes,
                'typed logical size differs')


@dataclass(frozen=True, slots=True)
class SegmentBlock:
    """One owned native range from an ordered, authenticated segment scan."""
    info: ArrayInfo
    start: int
    stop: int
    data: bytes


class BytesArraySource:
    """Convenience source for already-owned bytes; never copies a whole array."""
    def __init__(self, info, value):
        require(type(info) is ArrayInfo, 'ArrayInfo required')
        require(len(value.value) == info.logical_bytes, 'source byte length differs')
        self.info, self.owner = info, value.retain()

    def blocks(self, *, max_owned_bytes):
        require(type(max_owned_bytes) is int and max_owned_bytes > 0, 'positive block bound required')
        owner = self.owner.retain()
        def stream():
            for start in range(0, self.info.logical_bytes, max_owned_bytes):
                size = min(max_owned_bytes, self.info.logical_bytes - start)
                reservation = owner.scope.reserve(ChargeSpec('segment-source-block', size),
                                                   required=True, cancel=None)
                yield reservation.commit(bytes(memoryview(owner.value)[start:start + size]))
        return OwnedStream(stream(), owners=(owner,), scope=owner.scope)

    def close(self):
        self.owner.close()


def _leaf_digest(leaf):
    return h('atlas.segment-leaf.v1', leaf)


def _branch_digest(children):
    return h('atlas.segment-branch.v1', {
        'leaf_count': sum(c['leaf_count'] for c in children),
        'children': [{'first_ordinal': c['first_ordinal'], 'leaf_count': c['leaf_count'],
                      'digest': c['tree_digest']} for c in children]})


def _bounds(entries, leaf):
    if not entries:
        return {'first_name': None, 'last_name': None, 'first_start': 0, 'last_stop': 0}
    first, last = entries[0], entries[-1]
    if leaf:
        a, b = first['content'], last['content']
        return dict(first_name=a['name'], last_name=b['name'], first_start=a['start'],
                    last_stop=b['start'] + b['count'])
    return {name: first[name] if name.startswith('first_') else last[name]
            for name in ('first_name', 'last_name', 'first_start', 'last_stop')}


class _IndexBuilder:
    def __init__(self, candidate, scope, cancel):
        self.candidate, self.scope, self.cancel = candidate, scope, cancel
        self.buffer, self.levels = [], [[] for _ in range(INDEX_MAX_DEPTH)]
        self.owner = _owned(scope, (self.buffer, self.levels), BUILDER_BYTES, 'segment-index-builder')

    def _page(self, entries, leaf):
        cancel_check(self.cancel)
        first = entries[0]['content']['ordinal'] if leaf and entries else (
            entries[0]['first_ordinal'] if entries else 0)
        count = len(entries) if leaf else sum(c['leaf_count'] for c in entries)
        children = [{'first_ordinal': e['content']['ordinal'], 'leaf_count': 1,
                     'tree_digest': _leaf_digest(e['content'])} for e in entries] if leaf else entries
        page = dict(schema=PAGE_SCHEMA, kind='leaves' if leaf else 'branch',
                    first_ordinal=first, leaf_count=count, entries=list(entries))
        wire = canonical(page)
        require(len(wire) <= BINDING_PAGE_BYTES, 'binding page exceeds encoded byte cap')
        if leaf:
            validate_segment_budget(
                logical_bytes=sum(e['content']['count'] * np.dtype(e['content']['dtype']).itemsize for e in entries),
                chunk_references=sum(e['content']['chunk_id'] is not None for e in entries),
                manifest_bytes=len(wire) + 1024, metadata_bytes=len(wire))
        digest = h(PAGE_SCHEMA, page)
        key = h('atlas.binding-page-key.v1', {'digest': digest})
        locator = self.candidate.put_manifest(key, page, cancel=self.cancel)
        return dict(locator=locator.to_wire(), digest=digest, first_ordinal=first,
                    leaf_count=count, tree_digest=_branch_digest(children), **_bounds(entries, leaf))

    def _push(self, level, node):
        require(level < INDEX_MAX_DEPTH, 'binding index exceeds maximum depth')
        self.levels[level].append(node)
        if len(self.levels[level]) == FANOUT:
            require(level + 1 < INDEX_MAX_DEPTH, 'binding index exceeds maximum depth')
            parent = self._page(self.levels[level], False)
            self.levels[level].clear()
            self._push(level + 1, parent)

    def add(self, entry):
        self.buffer.append(entry)
        if len(self.buffer) == FANOUT:
            node = self._page(self.buffer, True)
            self.buffer.clear()
            self._push(0, node)

    def finish(self):
        if self.buffer:
            node = self._page(self.buffer, True)
            self.buffer.clear()
            self._push(0, node)
        if not any(self.levels):
            result = self._page([], False)
        else:
            result = None
            for level, nodes in enumerate(self.levels):
                if not nodes:
                    continue
                if len(nodes) == 1 and not any(self.levels[level + 1:]):
                    result = nodes.pop()
                    break
                node = self._page(nodes, False)
                nodes.clear()
                self._push(level + 1, node)
            require(result is not None, 'invalid binding index completion')
        self.owner.close()
        return result


@dataclass(frozen=True, slots=True)
class VerificationEvidence:
    manifests_verified: bool
    full_file_sha256_verified: bool = False
    payloads_verified: bool = False
    logical_body_verified: bool = False
    checked_payload_bytes: int = 0


class SegmentBackend:
    def publish(self, candidate, *, record_schema, identity, metadata, arrays,
                producer, representation_profile, scope, cancel=None):
        _same_scope(candidate, scope)
        require(type(identity) is LogicalIdentity and record_schema == identity.record_schema,
                'logical schema/identity mismatch')
        _digest(producer)
        require(type(representation_profile) is str and 0 < len(representation_profile.encode('utf-8')) <= 256,
                'bounded representation profile required')
        require(type(metadata) is bytes and len(metadata) <= ROOT_METADATA_MAX, 'bounded canonical metadata required')
        cancel_check(cancel)
        metadata_owner = scope.reserve(ChargeSpec('segment-input-metadata', 8 * len(metadata) + 65536),
                                       required=True, cancel=cancel).commit(parse(metadata))
        preimage = dict(identity=identity.to_wire(), producer=producer,
                        representation_profile=representation_profile)
        key = h(ROOT_SCHEMA, preimage)
        old_locator = candidate.find_manifest(key, cancel=cancel)
        if old_locator is not None:
            old = _metadata(candidate, old_locator, scope, cancel)
            row = old.value
            require(row.get('schema') == ROOT_SCHEMA and row.get('identity') == identity.to_wire() and
                    row.get('producer') == producer and row.get('representation_profile') == representation_profile and
                    row.get('metadata') == metadata_owner.value, 'immutable segment invocation conflict')
            ref = SegmentRef.from_wire(row['reference'])
            require(ref.root_key == old_locator, 'existing root locator mismatch')
            old.close()
            self.verify(candidate, ref, scope=scope, cancel=cancel)
            metadata_owner.close()
            return ref
        require(callable(arrays), 'lazy array factory required')
        builder = _IndexBuilder(candidate, scope, cancel)
        ordinal = array_count = logical_bytes = 0
        last_name = None
        # One bounded splice buffer; arbitrary producer block sizes are refused.
        scratch = scope.reserve(ChargeSpec('segment-chunk-buffer', 2 * NATIVE_CHUNK_BYTES),
                                required=True, cancel=cancel).commit(bytearray())
        iterator = iter(arrays())
        for source in iterator:
            cancel_check(cancel)
            supplied = source.info
            info = ArrayInfo(supplied.name, supplied.dtype, tuple(supplied.shape), supplied.logical_bytes)
            require(last_name is None or info.name.encode('utf-8') > last_name,
                    'array source names must be unique and in UTF-8 order')
            last_name = info.name.encode('utf-8')
            dt = np.dtype(info.dtype)
            count = math.prod(info.shape)
            position = 0
            def emit(raw):
                nonlocal ordinal, position
                n = len(raw) // dt.itemsize
                require(len(raw) == n * dt.itemsize and n > 0, 'unaligned typed block')
                descriptor = canonical({'dtype': info.dtype, 'count': n})
                owner, chunk_id = candidate.put_chunk(descriptor, raw, cancel=cancel)
                leaf = dict(ordinal=ordinal, array_ordinal=array_count, name=info.name,
                            dtype=info.dtype, shape=list(info.shape), start=position,
                            count=n, chunk_id=chunk_id)
                builder.add(dict(content=leaf, owner=owner, descriptor=parse(descriptor)))
                ordinal += 1
                position += n
            stream = source.blocks(max_owned_bytes=NATIVE_CHUNK_BYTES)
            for block in stream:
                _same_scope(block, scope)
                cancel_check(cancel)
                raw = block.value
                require(isinstance(raw, (bytes, bytearray, memoryview)) and len(raw) <= NATIVE_CHUNK_BYTES,
                        'producer block exceeds requested bound')
                require(position * dt.itemsize + len(scratch.value) + len(raw) <= info.logical_bytes,
                        'source has excess array bytes')
                offset = 0
                while offset < len(raw):
                    take = min(NATIVE_CHUNK_BYTES - len(scratch.value), len(raw) - offset)
                    scratch.value.extend(memoryview(raw)[offset:offset + take])
                    offset += take
                    if len(scratch.value) == NATIVE_CHUNK_BYTES:
                        emit(bytes(scratch.value))
                        scratch.value.clear()
                del raw
                block.close()
            stream.close()
            if scratch.value:
                emit(bytes(scratch.value))
                scratch.value.clear()
            require(position == count, 'source has missing array bytes')
            if count == 0:
                leaf = dict(ordinal=ordinal, array_ordinal=array_count, name=info.name,
                            dtype=info.dtype, shape=list(info.shape), start=0, count=0, chunk_id=None)
                builder.add(dict(content=leaf, owner=None, descriptor=None))
                ordinal += 1
            logical_bytes += info.logical_bytes
            _uint(logical_bytes, 'record logical bytes')
            array_count += 1
        close = getattr(iterator, 'close', None)
        if close is not None:
            close()
        scratch.close()
        tree = builder.finish()
        locator = SnapshotLocator(candidate.workflow_id, candidate.interval, key)
        ref = SegmentRef(SEGMENT_REF_SCHEMA, locator, identity, logical_bytes,
            BindingIndexRef(BINDING_INDEX_SCHEMA, SnapshotLocator.from_wire(tree['locator']), tree['digest'], array_count),
            h('atlas.segment-content.v1', dict(identity=identity.to_wire(), array_count=array_count,
                                              logical_bytes=logical_bytes, tree_digest=tree['tree_digest'])))
        root = dict(schema=ROOT_SCHEMA, **preimage, metadata=metadata_owner.value,
                    reference=ref.to_wire(), index=tree)
        require(len(canonical(root)) <= ROOT_METADATA_MAX, 'complete root metadata exceeds cap')
        cancel_check(cancel)
        published = candidate.put_manifest(key, root, cancel=cancel)
        require(published == locator, 'published root locator differs')
        metadata_owner.close()
        return ref

    def open(self, stores, ref, *, scope, cancel=None):
        _same_scope(stores, scope)
        return SegmentView(stores, ref, scope=scope, cancel=cancel)

    def verify(self, stores, ref, *, scope, cancel=None):
        view = self.open(stores, ref, scope=scope, cancel=cancel)
        view.close()
        return VerificationEvidence(True)


class SegmentInfo:
    def __init__(self, view):
        self._view = view
        self.ref = view.ref
        self.array_count = view.ref.array_bindings.count

    def array(self, name):
        view = self._view
        view._live()
        for entry in view._entries(name=name):
            leaf = entry['content']
            value = ArrayInfo(name, leaf['dtype'], tuple(leaf['shape']),
                              math.prod(leaf['shape']) * np.dtype(leaf['dtype']).itemsize)
            return _owned(view.scope, value, 4096, 'segment-array-info', dependencies=(view._owner,))
        raise KeyError(name)


class SegmentView:
    def __init__(self, resolver, ref, *, scope, cancel=None):
        require(type(ref) is SegmentRef, 'validated SegmentRef required')
        _same_scope(resolver, scope)
        self.resolver, self.ref, self.scope, self.cancel = resolver, ref, scope, cancel
        self._closed = False
        self._read_depth = 0
        self._read_lock = RLock()
        self._owner = _metadata(resolver, ref.root_key, scope, cancel)
        row = self._owner.value
        require(set(row) == {'schema', 'identity', 'producer', 'representation_profile', 'metadata', 'reference', 'index'} and
                row['schema'] == ROOT_SCHEMA and row['identity'] == ref.identity.to_wire() and
                row['reference'] == ref.to_wire(), 'segment root metadata/reference mismatch')
        require(h(ROOT_SCHEMA, {k: row[k] for k in ('identity', 'producer', 'representation_profile')}) == ref.root_key.snapshot_key,
                'segment root key mismatch')
        index = row['index']
        require(index['locator'] == ref.array_bindings.root_key.to_wire() and
                index['digest'] == ref.array_bindings.digest, 'index reference mismatch')
        self._validate()

    @property
    def info(self):
        # Keep ownership one-way: escaped info owns its view, but the view
        # must not retain its own metadata through a reciprocal info cycle.
        self._live()
        return SegmentInfo(self)

    def _live(self):
        require(not self._closed, 'segment view closed')
        cancel_check(self.cancel)

    def cache_identity(self):
        """Bind cache ranges to the catalog's sealed file identities.

        Candidate readers have no immutable file identity and cannot use this
        cache path. The record key also binds this view's exact SegmentRef.
        """
        self._live()
        if hasattr(self.resolver, 'interval'):
            return None
        require(self.resolver.catalog_digest is not None, 'sealed catalog identity missing')
        return sha256(b'atlas.segment-cache-catalog.v1\0' + canonical(dict(
            workflow_id=self.resolver.workflow_id,
            catalog_digest=self.resolver.catalog_digest))).digest()

    def check_unchanged(self):
        with self._read_lock:
            self._live()
            require(not hasattr(self.resolver, 'interval'), 'candidate cannot serve sealed cached reads')
            if not self._read_depth:
                self.resolver.assert_cached_read_safe(cancel=self.cancel)

    @contextmanager
    def verified_read(self):
        """One atomic internal read, with freshness checked before and after.

        No result may escape while this context is entered. Streaming callers
        exit it before each yielded block. Nested scalar lookups still check
        cancellation; physical payload reads retain their own authentication.
        """
        with self._read_lock:
            self._live()
            sealed = not hasattr(self.resolver, 'interval')
            pin = self._owner.retain() if not self._read_depth else None
            try:
                if sealed:
                    self.check_unchanged()
                self._read_depth += 1
                try:
                    yield
                finally:
                    self._read_depth -= 1
                # A failed body keeps its original error. Successful results
                # are withheld until this final freshness check passes.
                if sealed:
                    self.check_unchanged()
                else:
                    self._live()
            finally:
                if pin is not None:
                    pin.close()

    def _load_page(self, node):
        locator = SnapshotLocator.from_wire(node['locator'])
        require(locator.workflow_id == self.ref.root_key.workflow_id and
                locator.interval <= self.ref.root_key.interval, 'foreign/future index page')
        owner = _metadata(self.resolver, locator, self.scope, self.cancel)
        page = owner.value
        require(set(page) == {'schema', 'kind', 'first_ordinal', 'leaf_count', 'entries'} and
                page['schema'] == PAGE_SCHEMA and page['kind'] in ('leaves', 'branch') and
                type(page['entries']) is list and len(page['entries']) <= FANOUT,
                'unknown or oversized binding page')
        require(h(PAGE_SCHEMA, page) == node['digest'] and
                locator.snapshot_key == h('atlas.binding-page-key.v1', {'digest': node['digest']}),
                'binding page digest mismatch')
        return owner

    def _walk(self, node, *, depth=1, name=None, start=None, stop=None, validate=False):
        require(depth <= INDEX_MAX_DEPTH, 'binding tree depth exceeded')
        expected_fields = {'locator', 'digest', 'first_ordinal', 'leaf_count', 'tree_digest',
                           'first_name', 'last_name', 'first_start', 'last_stop'}
        require(type(node) is dict and set(node) == expected_fields, 'complete index node required')
        _uint(node['first_ordinal'], 'first ordinal')
        _uint(node['leaf_count'], 'leaf count')
        _digest(node['digest']); _digest(node['tree_digest'])
        if name is not None and node['first_name'] is not None:
            if name.encode('utf-8') < node['first_name'].encode('utf-8') or name.encode('utf-8') > node['last_name'].encode('utf-8'):
                return
            if node['first_name'] == node['last_name'] == name and start is not None:
                if node['last_stop'] <= start or node['first_start'] >= stop:
                    return
        owner = self._load_page(node)
        page = owner.value
        leaf = page['kind'] == 'leaves'
        entries = page['entries']
        require(page['first_ordinal'] == node['first_ordinal'] and page['leaf_count'] == node['leaf_count'],
                'binding node count differs')
        require(_bounds(entries, leaf) == {k: node[k] for k in ('first_name', 'last_name', 'first_start', 'last_stop')},
                'index range summary mismatch')
        cursor = node['first_ordinal']
        children = []
        for entry in entries:
            cancel_check(self.cancel)
            if leaf:
                require(type(entry) is dict and set(entry) == {'content', 'owner', 'descriptor'}, 'invalid binding leaf')
                body = entry['content']
                require(type(body) is dict and set(body) == {'ordinal', 'array_ordinal', 'name', 'dtype', 'shape', 'start', 'count', 'chunk_id'},
                        'invalid content leaf')
                require(body['ordinal'] == cursor and type(body['ordinal']) is int, 'duplicate/reordered leaf')
                info = ArrayInfo(body['name'], body['dtype'], tuple(body['shape']),
                                 math.prod(body['shape']) * np.dtype(body['dtype']).itemsize)
                _uint(body['array_ordinal'], 'array ordinal')
                _uint(body['start'], 'range start'); _uint(body['count'], 'range count')
                count = math.prod(info.shape)
                require(body['start'] + body['count'] <= count, 'chunk range outside array')
                if body['count']:
                    _digest(body['chunk_id']); _uint(entry['owner'], 'chunk owner')
                    require(entry['owner'] <= self.ref.root_key.interval and
                            entry['descriptor'] == {'dtype': info.dtype, 'count': body['count']},
                            'chunk owner/descriptor mismatch')
                    validate_segment_budget(logical_bytes=body['count'] * np.dtype(info.dtype).itemsize,
                                            chunk_references=1, manifest_bytes=4096, metadata_bytes=0)
                else:
                    require(count == 0 and body['start'] == 0 and body['chunk_id'] is None and
                            entry['owner'] is None and entry['descriptor'] is None, 'invalid empty-array leaf')
                children.append(dict(first_ordinal=cursor, leaf_count=1, tree_digest=_leaf_digest(body)))
                cursor += 1
                if name is None or (body['name'] == name and (start is None or
                        body['start'] < stop and body['start'] + body['count'] > start)):
                    yield entry
            else:
                require(entry['first_ordinal'] == cursor and entry['leaf_count'] > 0, 'branch gaps/duplicates')
                children.append(entry)
                yield from self._walk(entry, depth=depth + 1, name=name, start=start, stop=stop, validate=validate)
                cursor += entry['leaf_count']
        require(cursor == node['first_ordinal'] + node['leaf_count'] and
                _branch_digest(children) == node['tree_digest'], 'binding Merkle/count mismatch')
        owner.close()

    def _entries(self, **kwargs):
        self._live()
        yield from self._walk(self._owner.value['index'], **kwargs)

    def _validate(self):
        arrays = logical = ordinal = 0
        previous = None
        end = 0
        expected_count = 0
        require(self._owner.value['index']['first_ordinal'] == 0, 'root ordinal must start at zero')
        for entry in self._entries(validate=True):
            body = entry['content']
            require(body['ordinal'] == ordinal, 'global leaf ordinal mismatch')
            ordinal += 1
            if previous is None or body['name'] != previous['name']:
                require(end == expected_count, 'array has incomplete coverage')
                require(previous is None or previous['name'].encode('utf-8') < body['name'].encode('utf-8'),
                        'duplicate or unordered array')
                require(body['array_ordinal'] == arrays, 'array ordinal mismatch')
                arrays += 1
                expected_count = math.prod(body['shape'])
                logical += expected_count * np.dtype(body['dtype']).itemsize
                end = 0
            else:
                require(body['shape'] == previous['shape'] and body['dtype'] == previous['dtype'] and
                        body['array_ordinal'] == previous['array_ordinal'], 'array descriptor changes within record')
                require(body['count'] > 0, 'duplicate empty-array leaf')
            require(body['start'] == end, 'logical range has a gap or overlap')
            width = NATIVE_CHUNK_BYTES // np.dtype(body['dtype']).itemsize
            require(body['count'] == min(width, expected_count - end), 'noncanonical typed chunk range')
            end += body['count']
            previous = body
        require(end == expected_count and arrays == self.ref.array_bindings.count and logical == self.ref.logical_bytes,
                'complete segment inventory differs')
        expected = h('atlas.segment-content.v1', dict(identity=self.ref.identity.to_wire(), array_count=arrays,
            logical_bytes=logical, tree_digest=self._owner.value['index']['tree_digest']))
        require(expected == self.ref.merkle_root, 'record content Merkle mismatch')

    def metadata_bytes(self):
        self._live()
        reservation = self.scope.reserve(ChargeSpec('segment-user-metadata', ROOT_METADATA_MAX),
                                         required=True, cancel=self.cancel)
        return reservation.commit(canonical(self._owner.value['metadata']), dependencies=(self._owner,))

    def metadata(self):
        return self.metadata_bytes()

    def read(self, name, start, stop, *, max_owned_bytes):
        self._live()
        _uint(start, 'read start'); _uint(stop, 'read stop')
        _uint(max_owned_bytes, 'owned read allowance')
        descriptor = self.info.array(name)
        info = descriptor.value
        require(start <= stop <= math.prod(info.shape), 'read range outside array')
        itemsize = np.dtype(info.dtype).itemsize
        size = (stop - start) * itemsize
        require(size <= max_owned_bytes, 'explicit read allowance exceeded')
        reservation = self.scope.reserve(ChargeSpec('segment-read', size), required=True, cancel=self.cancel)
        # Scratch uses the existing failure-retaining run workspace. Only the
        # final immutable bytes enter retained ownership; a 128 MiB read does
        # not need two retained slots or expose mutable memoryview.obj backing.
        with _workspace(self.scope.run_budget, size + 65536, 'segment-read-scratch'):
            result = bytearray(size)
            offset = 0
            for entry in self._entries(name=name, start=start, stop=stop):
                body = entry['content']
                raw = _chunk(self.resolver, entry['owner'], body['chunk_id'], canonical(entry['descriptor']), self.cancel)
                lo, hi = max(start, body['start']), min(stop, body['start'] + body['count'])
                count = (hi - lo) * itemsize
                source_offset = (lo - body['start']) * itemsize
                require(len(raw.value) == body['count'] * itemsize and offset + count <= size, 'decoded chunk size differs')
                result[offset:offset + count] = memoryview(raw.value)[source_offset:source_offset + count]
                offset += count
                raw.close()
            require(offset == size, 'read coverage differs')
            owned = reservation.commit(bytes(result), dependencies=(self._owner,))
            del result
        descriptor.close()
        return owned

    def iter(self, name, *, block_bytes, max_owned_bytes):
        self._live()
        _uint(block_bytes, 'block bytes'); _uint(max_owned_bytes, 'block allowance')
        require(0 < block_bytes <= max_owned_bytes, 'invalid block allowance')
        descriptor = self.info.array(name)
        info = descriptor.value
        step = block_bytes // np.dtype(info.dtype).itemsize
        require(step > 0, 'block smaller than one element')
        count = math.prod(info.shape)
        descriptor.close()
        def stream():
            for start in range(0, count, step):
                yield self.read(name, start, min(count, start + step), max_owned_bytes=max_owned_bytes)
        return OwnedStream(stream(), owners=(self._owner,), scope=self.scope)

    def scan(self, *, max_owned_bytes):
        """Visit each sealed binding once, including every empty array.

        Each yield owns at most one native payload plus its bounded immutable
        descriptor. The walk retains only its bounded page/depth stack, never
        an inventory of unowned rows. Freshness is checked around every step,
        before its result can escape; cancellation and native authentication
        remain active. Candidate readers must use their existing fresh reads.
        """
        self._live()
        require(not hasattr(self.resolver, 'interval'), 'candidate cannot serve sealed scans')
        _uint(max_owned_bytes, 'scan allowance')
        require(max_owned_bytes >= NATIVE_CHUNK_BYTES, 'scan allowance below native chunk size')

        def stream():
            entries = self._entries()
            while True:
                with self.verified_read():
                    entry = next(entries, None)
                    if entry is None:
                        return
                    body = entry['content']
                    size = body['count'] * np.dtype(body['dtype']).itemsize
                    require(size <= max_owned_bytes, 'scan allowance exceeded')
                    reservation = self.scope.reserve(
                        ChargeSpec('segment-scan-block', size + 4096),
                        required=True, cancel=self.cancel)
                    info = ArrayInfo(body['name'], body['dtype'], tuple(body['shape']),
                                     math.prod(body['shape']) * np.dtype(body['dtype']).itemsize)
                    if size:
                        raw = _chunk(self.resolver, entry['owner'], body['chunk_id'],
                                     canonical(entry['descriptor']), self.cancel)
                        require(len(raw.value) == size, 'decoded chunk size differs')
                        # Copy under the result's own charge: an escaped block
                        # never borrows a page row or the transient chunk owner.
                        data = bytes(memoryview(raw.value))
                    else:
                        raw, data = None, b''
                    owned = reservation.commit(SegmentBlock(
                        info, body['start'], body['start'] + body['count'], data),
                        dependencies=(self._owner,))
                    if raw is not None:
                        raw.close()
                    del data, raw, info, entry, body
                yield owned
        return OwnedStream(stream(), owners=(self._owner,), scope=self.scope)

    def close(self):
        if not self._closed:
            self._owner.close()
            self._closed = True

    def __enter__(self):
        self._live()
        return self

    def __exit__(self, kind, value, traceback):
        if kind is None:
            self.close()
