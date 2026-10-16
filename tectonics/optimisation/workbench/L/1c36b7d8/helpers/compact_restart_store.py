"""Bounded native-workflow facade over the sealed interval/segment store.

This is a storage compatibility boundary, not scientific admission. Native
invocation and ArrayReference identities are preserved by reconstructing their
exact v1 manifests. Only bounded metadata is accepted; large logical records
must already be represented by the compact record adapters.
"""
from __future__ import annotations

from collections import deque
from collections.abc import Mapping
from contextlib import contextmanager
from hashlib import sha256
import math
from threading import RLock

import numpy as np

from atlas_tectonics import storage as N
from compact_contracts import (ContractError, LogicalIdentity, SegmentRef,
                               SnapshotLocator, ROOT_METADATA_MAX)
from content_cache import ChargeSpec, OwnedStream
from interval_catalog import file_token
from interval_store_set import IntervalStoreSet, UnlistedCandidate, LIMITS
from segment_store import SegmentBackend, ArrayInfo, canonical, cancel_check, parse

ALIAS_SCHEMA = 'atlas.restart-native-alias.v1'
SNAPSHOT_SCHEMA = 'atlas.restart-native-snapshot.v1'
PROFILE = 'atlas.restart-native-arrays.v1'


class _HeldBytes(bytes):
    """An ordinary immutable NumPy backing buffer with one retained charge."""
    def __new__(cls, value, owner):
        result = super().__new__(cls, value)
        result._owner = owner
        return result

    def __del__(self):
        owner = getattr(self, '_owner', None)
        if owner is not None:
            owner.close()


class _ArraySource:
    def __init__(self, store, name, value):
        self.store, self.name, self.value = store, name, value
        self.reference = None
        self.edits = None
        if isinstance(value, (N.ArrayReference, N._EditedReference)):
            self.reference = value.reference if isinstance(value, N._EditedReference) else value
            desc = store._reference_description(self.reference)
            self.edits = dict(value.replacements) if isinstance(value, N._EditedReference) else {}
            if any(type(i) is not int or not 0 <= i < len(desc['chunks']) for i in self.edits):
                raise N.StoreError('replacement chunk index outside array')
            dtype, shape = desc['dtype'], tuple(desc['shape'])
        else:
            array = N._array_view(value)
            dtype, shape = N._dtype(array.dtype.str).str, tuple(array.shape)
        size = math.prod(shape) * np.dtype(dtype).itemsize
        if size > store.limits.max_array_bytes:
            raise N.StoreError('array exceeds storage input limit')
        self.info = ArrayInfo(name, dtype, shape, size)

    def _raw(self):
        dt = np.dtype(self.info.dtype)
        width = self.store.limits.chunk_bytes // dt.itemsize
        count = math.prod(self.info.shape)
        if self.reference is None:
            array = N._array_view(self.value)
            flat = array.reshape(-1) if array.flags.c_contiguous else array.flat
        for index, start in enumerate(range(0, count, width)):
            size = min(width, count - start)
            if self.reference is None:
                value = flat[start:start + size]
            elif index in self.edits:
                value = N._array_view(self.edits[index])
                if (value.dtype.kind != dt.kind or value.itemsize != dt.itemsize or
                        value.shape != (size,)):
                    raise N.StoreError('replacement chunk requires exact dtype and flat length')
            else:
                _, value = self.store.read_chunk(self.reference.invocation,
                                                 self.reference.array_name, index)
            raw = np.asarray(value, dtype=dt, order='C').tobytes()
            if len(raw) != size * dt.itemsize or (dt.kind == 'f' and
                    not np.isfinite(np.frombuffer(raw, dtype=dt)).all()):
                raise N.StoreError('invalid or nonfinite native array chunk')
            del value
            yield raw

    def blocks(self, *, max_owned_bytes):
        if max_owned_bytes != self.store.limits.chunk_bytes:
            raise ContractError('native source requires the unchanged 64 KiB chunk bound')
        def stream():
            for raw in self._raw():
                with self.store.scope.reserve(ChargeSpec('restart-source', len(raw))) as reservation:
                    yield reservation.commit(raw)
        return OwnedStream(stream(), scope=self.store.scope)

    def description(self, cancel):
        ids = []
        dt = np.dtype(self.info.dtype)
        for raw in self._raw():
            cancel_check(cancel)
            descriptor = canonical(dict(dtype=dt.str, count=len(raw) // dt.itemsize))
            ids.append(N.ArrayStore._blob_id(None, descriptor, raw))
        return dict(dtype=dt.str, shape=list(self.info.shape), chunks=ids)


class CompactRestartStore:
    """One facade, one actual candidate/resolver, and the caller's shared scope."""
    def __init__(self, resolver, *, scope, owns_resolver=False):
        if type(resolver) not in (UnlistedCandidate, IntervalStoreSet) or resolver.scope is not scope:
            raise ContractError('actual same-scope interval candidate or sealed resolver required')
        self.resolver, self.scope = resolver, scope
        self.candidate = resolver if type(resolver) is UnlistedCandidate else None
        self.store_set = resolver.stores if self.candidate is not None else resolver
        self._budget = scope.run_budget
        self.catalog_path = self.store_set.catalog_path
        # Reference identity stays constant across successor interval files.
        self.path = self.catalog_path
        self.limits, self.compression = LIMITS, N.Compression()
        self.readonly = self.candidate is None
        self._historical_readonly = self.readonly
        self.in_publication = False
        self._read_scope_depth = 0
        self._last_sealed_candidate = None
        self._owns_resolver, self._closed = owns_resolver, False
        self._lock = RLock()
        self._stats = dict(puts=0, reused_invocations=0, maximum_native_manifest_bytes=0,
                           maximum_metadata_bytes=0, maximum_put_array_bytes=0)
        self._put_usage = deque(maxlen=64)
        self._control = scope.reserve(ChargeSpec('restart-facade-control', 128 << 10)).commit(self._put_usage)

    def __getattr__(self, name):
        # Segment/record adapters use their existing candidate/resolver protocol.
        # In particular, readonly facades must NOT acquire an `interval` member.
        resolver = self.__dict__.get('resolver')
        if resolver is None or name.startswith('__'):
            raise AttributeError(name)
        return getattr(resolver, name)

    @classmethod
    def create_migration(cls, catalog_path, *, workflow_id, scope,
                         producer_identity, runtime_identity, cancel=None):
        stores = IntervalStoreSet.create_migration(catalog_path, workflow_id=workflow_id,
                                                   scope=scope, cancel=cancel)
        try:
            candidate = stores.begin_interval(None, producer_identity=producer_identity,
                                               runtime_identity=runtime_identity, cancel=cancel)
            return cls(candidate, scope=scope, owns_resolver=True)
        except BaseException:
            stores.close()
            raise

    @classmethod
    def open_catalog(cls, catalog_path, *, scope, cancel=None):
        stores = IntervalStoreSet.open_catalog(catalog_path, scope=scope, cancel=cancel)
        try:
            return cls(stores, scope=scope, owns_resolver=True)
        except BaseException:
            stores.close()
            raise

    def begin_interval(self, *, producer_identity, runtime_identity, cancel=None):
        self._live()
        if not self.readonly:
            raise ContractError('finish the current candidate before beginning another interval')
        candidate = self.store_set.begin_interval(self.store_set.head,
            producer_identity=producer_identity, runtime_identity=runtime_identity, cancel=cancel)
        try:
            return type(self)(candidate, scope=self.scope)
        except BaseException:
            candidate.close()
            raise

    def start_next_interval(self, *, producer_identity, runtime_identity, cancel=None):
        """Switch this stable resolver only at a quiescent native boundary.

        Candidate-created compact views retain this facade and resolve their
        old locators through the new candidate's sealed ancestry. A view that
        already enabled a sealed-page cache keeps SegmentView's existing
        fail-closed candidate/cache check; no cache identity is silently repinned.
        """
        with self._lock:
            self._live()
            if not self.readonly or self.in_publication or self._read_scope_depth:
                raise ContractError('next interval requires a quiescent sealed facade')
            candidate = self.store_set.begin_interval(self.store_set.head,
                producer_identity=producer_identity, runtime_identity=runtime_identity, cancel=cancel)
            self.resolver = self.candidate = candidate
            self.readonly = self._historical_readonly = False
            return self

    def _live(self):
        if self._closed:
            raise N.StoreError('compact restart store is closed')
        self.store_set._live()
        if self.candidate is not None:
            self.candidate._writing()

    def _workspace(self, count, budget=None, *, category='store-work'):
        if budget is not None and budget is not self._budget:
            raise ContractError('compact restart requires the same run budget')
        return self._budget.reserve(count, category=category)

    @contextmanager
    def _read_scope(self, *, budget=None):
        if budget is not None and budget is not self._budget:
            raise ContractError('compact restart requires the same run budget')
        with self._lock:
            self._live()
            self.store_set.assert_cached_read_safe()
            self._read_scope_depth += 1
            try:
                yield
                self.store_set.assert_cached_read_safe()
            finally:
                self._read_scope_depth -= 1

    def _intervals(self):
        head = self.store_set.head
        if head is None:
            return ()
        return tuple(sorted({head.interval, *(i for i, _ in head.references)}, reverse=True))

    def _locator(self, key):
        N._sha(key)
        if self.candidate is not None:
            return self.candidate.find_manifest(key)
        for interval in self._intervals():
            owner = self.store_set._handle(interval)
            try:
                owner.value.manifest(key)
            except KeyError:
                continue
            return SnapshotLocator(self.store_set.workflow_id, interval, key)
        return None

    def _alias(self, invocation):
        locator = self._locator(invocation)
        if locator is None:
            return None
        if self.candidate is not None:
            held = self.candidate.resolve_manifest(locator)
        else:
            held = self.store_set.resolve_manifest(self.store_set.head.interval, locator)
        with held:
            manifest = parse(held.value)
            value = manifest['metadata']
            if (type(value) is not dict or set(value) != {'schema', 'invocation', 'reference'} or
                    value['schema'] != ALIAS_SCHEMA or value['invocation'] != invocation):
                raise ContractError('native invocation does not resolve to a bounded restart alias')
            ref = SegmentRef.from_wire(value['reference'])
        if ref.identity.record_schema != SNAPSHOT_SCHEMA:
            raise ContractError('restart alias references a foreign record schema')
        return ref

    @contextmanager
    def _segment(self, invocation):
        ref = self._alias(invocation)
        if ref is None:
            yield None
            return
        view = SegmentBackend().open(self.resolver, ref, scope=self.scope)
        try:
            metadata = view._owner.value['metadata']
            if (view._owner.value['representation_profile'] != PROFILE or
                    type(metadata) is not dict or set(metadata) != {'invocation', 'metadata', 'execution_mode'} or
                    metadata['invocation'] != invocation or
                    metadata['execution_mode'] not in ('strict', 'release')):
                raise ContractError('restart snapshot binding differs')
            yield view
        finally:
            view.close()

    def _manifest_from_segment(self, invocation, view):
        arrays, chunks = {}, 0
        for entry in view._entries():
            leaf = entry['content']
            name = leaf['name']
            if name not in arrays:
                size = math.prod(leaf['shape']) * np.dtype(leaf['dtype']).itemsize
                if size > self.limits.max_array_bytes:
                    raise N.StoreError('declared array exceeds decoder limit')
                arrays[name] = dict(dtype=leaf['dtype'], shape=list(leaf['shape']), chunks=[])
            if leaf['chunk_id'] is not None:
                arrays[name]['chunks'].append(leaf['chunk_id'])
                chunks += 1
                if chunks > min(self.limits.max_chunks, self.limits.max_manifest_bytes // 68):
                    raise N.StoreError('native manifest exceeds chunk-reference bound')
        metadata = view._owner.value['metadata']
        manifest = dict(schema=N._SCHEMA, invocation=invocation, arrays=arrays,
                        metadata=metadata['metadata'])
        if metadata['execution_mode'] == 'release':
            manifest['execution_mode'] = 'release'
        raw = N._json(manifest)
        identity = view.ref.identity
        if (len(raw) > self.limits.max_manifest_bytes or sha256(raw).hexdigest() != identity.sha256 or
                len(raw) != identity.canonical_bytes):
            raise ContractError('reconstructed native manifest identity differs')
        return N._parse(raw)

    def _manifest(self, invocation):
        with self._read_scope(), self._workspace(8 * self.limits.max_manifest_bytes), self._segment(invocation) as view:
            return None if view is None else self._manifest_from_segment(invocation, view)

    def metadata(self, invocation):
        with self._read_scope(), self._segment(invocation) as view:
            if view is None:
                return None
            return N._parse(N._json(view._owner.value['metadata']['metadata']))

    def contains(self, invocation):
        with self._read_scope():
            return self._alias(invocation) is not None

    def execution_mode(self, invocation):
        with self._read_scope(), self._segment(invocation) as view:
            return None if view is None else view._owner.value['metadata']['execution_mode']

    reference = N.ArrayStore.reference
    _reference_description = N.ArrayStore._reference_description
    put_incremental = N.ArrayStore.put_incremental

    def put(self, invocation, arrays, metadata=None, *, publication_check=None, cancel=None, budget=None):
        from atlas_tectonics.reuse import execution_mode
        N._sha(invocation)
        if self.readonly or self.candidate is None:
            raise ContractError('sealed interval store is read-only')
        if publication_check is not None and not callable(publication_check):
            raise N.StoreError('publication_check must be callable')
        if not isinstance(arrays, Mapping) or not arrays:
            raise N.StoreError('nonempty array mapping required')
        if len(arrays) > self.limits.max_manifest_bytes // 256:
            raise N.StoreError('native array-name inventory exceeds bound')
        meta = N._json({} if metadata is None else metadata)
        if len(meta) > ROOT_METADATA_MAX:
            raise N.StoreError('legacy metadata exceeds 64 KiB; compact record references required')
        for name in arrays:
            if type(name) is not str or not name or len(name.encode('utf-8')) > 256:
                raise N.StoreError('short nonempty UTF-8 array names required')
        with self._read_scope(budget=budget), self._workspace(16 << 20, budget, category='restart-put'):
            sources = [_ArraySource(self, name, arrays[name]) for name in sorted(arrays, key=lambda n: n.encode('utf-8'))]
            total = sum(source.info.logical_bytes for source in sources)
            if total > self.limits.max_array_bytes:
                raise N.StoreError('snapshot exceeds the native full-read limit')
            descriptions = {source.name: source.description(cancel) for source in sources}
            if sum(len(row['chunks']) for row in descriptions.values()) > min(
                    self.limits.max_chunks, self.limits.max_manifest_bytes // 68):
                raise N.StoreError('native manifest exceeds chunk-reference bound')
            manifest = dict(schema=N._SCHEMA, invocation=invocation, arrays=descriptions,
                            metadata=N._parse(meta))
            if execution_mode() == 'release':
                manifest['execution_mode'] = 'release'
            previous = self._manifest(invocation)
            if previous is not None:
                if ({k: v for k, v in previous.items() if k != 'execution_mode'} !=
                        {k: v for k, v in manifest.items() if k != 'execution_mode'}):
                    raise N.StoreConflict('same invocation produced different data or metadata')
                # An idempotent release-mode call cannot rewrite original provenance.
                manifest = previous
            raw = N._json(manifest)
            if len(raw) > self.limits.max_manifest_bytes:
                raise N.StoreError('native manifest exceeds limit')
            candidate = self.candidate
            before = dict(candidate._stats)
            references = set(candidate._references)
            candidate._db.execute('SAVEPOINT restart_native_put')
            try:
                if previous is None:
                    identity = LogicalIdentity(SNAPSHOT_SCHEMA, sha256(raw).hexdigest(), len(raw))
                    bounded = canonical(dict(invocation=invocation, metadata=manifest['metadata'],
                                             execution_mode=manifest.get('execution_mode', 'strict')))
                    ref = SegmentBackend().publish(candidate, record_schema=SNAPSHOT_SCHEMA,
                        identity=identity, metadata=bounded, arrays=lambda: iter(sources),
                        producer=candidate.producer_identity, representation_profile=PROFILE,
                        scope=self.scope, cancel=cancel)
                    with SegmentBackend().open(candidate, ref, scope=self.scope) as view:
                        if self._manifest_from_segment(invocation, view) != manifest:
                            raise N.StoreConflict('input changed during native snapshot publication')
                    candidate.put_manifest(invocation, dict(schema=ALIAS_SCHEMA, invocation=invocation,
                                                             reference=ref.to_wire()), cancel=cancel)
                cancel_check(cancel)
                self.in_publication = True
                if publication_check is not None:
                    publication_check()
                cancel_check(cancel)
                candidate._db.execute('RELEASE restart_native_put')
            except BaseException:
                candidate._db.execute('ROLLBACK TO restart_native_put')
                candidate._db.execute('RELEASE restart_native_put')
                candidate._stats = before
                candidate._references = references
                raise
            finally:
                self.in_publication = False
            self._stats['puts'] += 1
            self._stats['reused_invocations'] += int(previous is not None)
            self._stats['maximum_native_manifest_bytes'] = max(self._stats['maximum_native_manifest_bytes'], len(raw))
            self._stats['maximum_metadata_bytes'] = max(self._stats['maximum_metadata_bytes'], len(meta))
            self._stats['maximum_put_array_bytes'] = max(self._stats['maximum_put_array_bytes'], total)
            after = candidate.local_statistics()
            held = self.scope.stats()
            self._put_usage.append(dict(invocation=invocation,
                native_manifest_bytes=len(raw), metadata_bytes=len(meta), array_bytes=total,
                reused=previous is not None,
                added_manifest_bytes=after['manifest_bytes'] - before['manifest_bytes'],
                added_encoded_payload_bytes=after['encoded_payload_bytes'] - before['encoded_payload_bytes'],
                added_chunks=after['local_chunks'] - before['local_chunks'],
                retained_bytes=held.retained_bytes, peak_retained_bytes=held.peak_retained_bytes))
        return invocation

    def _output(self, raw):
        with self.scope.reserve(ChargeSpec('restart-native-output', len(raw))) as reservation:
            return _HeldBytes(raw, reservation.commit(None))

    def read_chunk(self, invocation, array_name, index, *, budget=None):
        if type(index) is not int or index < 0:
            raise N.StoreError('chunk index must be a nonnegative integer')
        with self._read_scope(budget=budget), self._segment(invocation) as view:
            if view is None:
                raise KeyError(invocation)
            with view.info.array(array_name) as descriptor:
                info = descriptor.value
            dt = np.dtype(info.dtype)
            start = index * (self.limits.chunk_bytes // dt.itemsize)
            count = math.prod(info.shape)
            if start >= count:
                raise IndexError(index)
            with view.read(array_name, start, min(count, start + self.limits.chunk_bytes // dt.itemsize),
                           max_owned_bytes=self.limits.chunk_bytes) as held:
                result = np.frombuffer(self._output(held.value), dtype=dt)
            return start, result

    def iter_chunks(self, invocation, array_name, *, budget=None):
        with self._read_scope(budget=budget), self._segment(invocation) as view:
            if view is None:
                raise KeyError(invocation)
            with view.info.array(array_name) as descriptor:
                info = descriptor.value
        width = self.limits.chunk_bytes // np.dtype(info.dtype).itemsize
        for index in range((math.prod(info.shape) + width - 1) // width):
            yield self.read_chunk(invocation, array_name, index, budget=budget)

    def get(self, invocation, *, budget=None):
        with self._read_scope(budget=budget):
            manifest = self._manifest(invocation)
            if manifest is None:
                return None
            total = sum(math.prod(a['shape']) * np.dtype(a['dtype']).itemsize for a in manifest['arrays'].values())
            if total > self.limits.max_array_bytes:
                raise N.StoreError('full result exceeds native read limit')
            result = {}
            with self._workspace(total + 2 * self.limits.chunk_bytes, budget, category='restart-get'):
                for name, desc in manifest['arrays'].items():
                    dt = np.dtype(desc['dtype'])
                    buffer = bytearray(math.prod(desc['shape']) * dt.itemsize)
                    for start, chunk in self.iter_chunks(invocation, name, budget=budget):
                        buffer[start * dt.itemsize:start * dt.itemsize + chunk.nbytes] = memoryview(chunk).cast('B')
                    result[name] = np.frombuffer(self._output(buffer), dtype=dt).reshape(desc['shape'])
            return result

    def snapshot_keys(self):
        """Explicit streamed logical-alias census; never an implicit history cache."""
        self._live()
        intervals = self._intervals()
        if self.candidate is not None:
            intervals = (self.candidate.interval, *intervals)
        for interval in intervals:
            pin = None
            if self.candidate is not None and interval == self.candidate.interval:
                db = self.candidate._db
            else:
                pin = self.store_set.borrow_handle(interval)
                db = pin.value._db
            cursor = db.execute('SELECT id FROM snapshots ORDER BY id')
            try:
                for (key,) in cursor:
                    with self._workspace(8 * self.limits.max_manifest_bytes, category='restart-alias-scan'):
                        if pin is None:
                            parsed = N.ArrayStore._manifest(self.candidate, key)
                        else:
                            parsed = parse(pin.value.manifest(key))
                        meta = parsed['metadata']
                        if type(meta) is dict and meta.get('schema') == ALIAS_SCHEMA:
                            self._alias(key)
                            yield key
            finally:
                cursor.close()
                if pin is not None:
                    pin.close()

    def change_token(self):
        with self._read_scope():
            catalog_token = file_token(self.catalog_path) if self.catalog_path.exists() else None
            return (self.store_set.catalog_digest, catalog_token,
                    None if self.candidate is None else (self.candidate.interval, self.candidate._db.total_changes))

    def seal_and_promote(self, head_key, *, cancel=None):
        with self._lock:
            self._live()
            if self.candidate is None or self.in_publication or self._read_scope_depth:
                raise ContractError('no current candidate to seal')
            head = self._alias(head_key)
            if head is None:
                raise KeyError(head_key)
            sealed = self.candidate.seal(head, cancel=cancel)
            entry = self.store_set.promote(sealed, expected_catalog_digest=sealed.expected_catalog_digest, cancel=cancel)
            self._last_sealed_candidate = dict(self.candidate.local_statistics(), interval=entry.interval)
            self.resolver, self.candidate = self.store_set, None
            self.readonly = self._historical_readonly = True
            return entry

    def statistics(self):
        self._live()
        scope = self.scope.stats()
        local = self.candidate.local_statistics() if self.candidate is not None else {}
        entries = self.store_set._entries()
        # Scalar diagnostic aggregation only: routine statistics must not build
        # or authenticate a decoded all-history inventory. Explicit evidence
        # consumers use snapshot_keys(), which checks every selected alias.
        snapshots = 0
        for interval in self._intervals():
            with self.store_set.borrow_handle(interval) as owner:
                snapshots += owner.value._db.execute(
                    "SELECT count(*) FROM snapshots WHERE json_extract(body, '$.metadata.schema')=?",
                    (ALIAS_SCHEMA,)).fetchone()[0]
        if self.candidate is not None:
            snapshots += self.candidate._db.execute(
                "SELECT count(*) FROM snapshots WHERE json_extract(body, '$.metadata.schema')=?",
                (ALIAS_SCHEMA,)).fetchone()[0]
        return dict(snapshots=snapshots,
            database_bytes=sum((self.catalog_path.parent / e.filename).stat().st_size for e in entries)
                + (self.candidate.path.stat().st_size if self.candidate is not None else 0),
            operations=dict(self._stats), candidate=local,
            last_sealed_candidate=self._last_sealed_candidate,
            put_usage=list(self._put_usage),
            omitted_earlier_put_usage=max(0, self._stats['puts'] - len(self._put_usage)),
            compact_references_verified=dict(scope='manifest/index bindings only',
                payloads_verified=False, logical_body_verified=False),
            retained=dict(bytes=scope.retained_bytes, peak_bytes=scope.peak_retained_bytes,
                pending_bytes=scope.pending_bytes, pinned_bytes=scope.pinned_bytes,
                purpose_bytes=dict(scope.purpose_bytes)),
            cache=dict(hits=dict(scope.hits), misses=dict(scope.misses),
                entries=dict(scope.entries), category_bytes=dict(scope.category_bytes)),
            resource_allowances=dict(chunk_bytes=LIMITS.chunk_bytes,
                max_array_bytes=LIMITS.max_array_bytes, max_store_bytes=LIMITS.max_store_bytes,
                catalog_bytes=1 << 20, shared_retained_bytes=256 << 20),
            shared_budget=self._budget.statistics())

    def close(self):
        if self._closed:
            return
        if self.candidate is not None:
            self.candidate.close()
        if self._owns_resolver:
            self.store_set.close()
        self._put_usage.clear()
        self._control.close()
        self._closed = True

    def __enter__(self):
        self._live()
        return self

    def __exit__(self, *_):
        self.close()


def is_compact_restart_store(value):
    return type(value) is CompactRestartStore
