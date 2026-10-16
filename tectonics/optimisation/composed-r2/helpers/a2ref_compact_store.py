"""Immutable compact geometry in the existing ArrayStore, not admission.

Support blobs are staged as content-addressed snapshots in the SAME database.
The final mesh snapshot packs their hash-checked bytes, in content order, into
ONE array beside the codec columns (v2). The r9 head mesh has about 2,024
supports; one root array per support put its root, link and workflow aliases
over the 1 MiB manifest limit. Each read takes only the covering chunks of the
packed array and checks the blob's content hash. Cancellation may leave reusable
support snapshots; it never publishes a partial mesh root. No old snapshot is
rewritten, deleted or promoted to scientific acceptance.
"""
from concurrent.futures import CancelledError
from hashlib import sha256
import math

import numpy as np

from atlas_tectonics.resources import WorkBudget
from atlas_tectonics.storage import ArrayStore, StoreError, _json, _sha
from atlas_tectonics.integration_spatial_transport import _workspace
from mesh_tables import CompactMesh, MAX_SUPPORT_BYTES


SCHEMA = 'atlas.compact-mesh-store.v2'
SUPPORT_SCHEMA = 'atlas.compact-mesh-support.v1'
SUPPORT_ARRAY = 'support-blobs'
AUTHORITY = 'storage integrity only; scientific admission required'


class CompactStoreRefused(StoreError):
    pass


class _RetainedMetadata:
    """Keep the lazy reader's bounded support inventory charged with its view."""
    def __init__(self, budget, size):
        self.guard = None
        guard = budget.reserve(size, category='compact-store-support-inventory')
        guard.__enter__()
        self.guard = guard

    def __del__(self):
        guard = getattr(self, 'guard', None)
        if guard is not None:
            self.guard = None
            guard.__exit__(None, None, None)


def _digest(value):
    return sha256(_json(value)).hexdigest()


def descriptor_digest(description):
    """ArrayStore.reference's descriptor_sha256 of one manifest array description.

    A reference binds each array by this digest of its exact dtype, shape and
    chunk IDs, not by a copy of the chunk list, so its width does not grow with
    the referenced bytes.
    """
    return _digest(description)


def _cancel(token):
    if token is not None and token.is_set():
        raise CancelledError('compact mesh persistence cancelled')


def _support_record(content, size):
    _sha(content)
    if type(size) is not int or not 0 < size <= MAX_SUPPORT_BYTES:
        raise CompactStoreRefused('bounded nonempty support blob required')
    return dict(schema=SUPPORT_SCHEMA, content_sha256=content, nbytes=size,
                authority=AUTHORITY)


def _packed_offsets(supports):
    """Each blob's byte offset in the root's packed array (sorted content order) and its length."""
    offsets, total = {}, 0
    for content in sorted(supports):
        offsets[content] = total
        total += supports[content]
    return offsets, total


class CompactMeshStore:
    """Storage adapter with explicit shared budget and externally expected ID.

    A returned CompactMesh owns its geometry arrays. Its lazy support reader
    needs this store to remain open. Reading decodes only one bounded support;
    the codec owns the returned support bytes/row allocation during that call.
    """

    def __init__(self, store, *, budget):
        if (type(store) is not ArrayStore or type(budget) is not WorkBudget
                or store._budget is not budget):
            raise CompactStoreRefused('actual ArrayStore and shared WorkBudget required')
        self.store, self.budget = store, budget

    def _manifest(self, key):
        _sha(key)
        with self.store._read_scope(budget=self.budget):
            result = self.store._manifest(key)
            if result is None:
                raise CompactStoreRefused('compact snapshot is missing')
            return result

    def support_writer(self, content_sha256, canonical_bytes, *, cancel=None):
        """Pack callback: persist one hash-bound support blob, without JSON decode."""
        _cancel(cancel)
        if type(canonical_bytes) is not bytes:
            raise CompactStoreRefused('explicit canonical support bytes required')
        record = _support_record(content_sha256, len(canonical_bytes))
        if sha256(canonical_bytes).hexdigest() != content_sha256:
            raise CompactStoreRefused('support content hash differs')
        key = _digest(record)
        self.store.put(key, {'bytes': np.frombuffer(canonical_bytes, dtype=np.uint8)},
                       record, budget=self.budget, cancel=cancel)
        return key

    def _read_bytes(self, key, name, expected_size, content, *, cancel=None):
        """Bounded checked stream. Caller owns the returned bytes' lifetime."""
        _cancel(cancel)
        # The existing workspace owner follows an escaping exception or a
        # separately retained traceback, which can keep buffer/manifest alive.
        with _workspace(self.budget, 2*expected_size+65536+8*self.store.limits.max_manifest_bytes,
                        'compact-support-read'):
            with self.store._read_scope(budget=self.budget):
                manifest = self._manifest(key)
                row = manifest['arrays'].get(name)
                if row is None or row['dtype'] != '|u1' or row['shape'] != [expected_size]:
                    raise CompactStoreRefused('support array size or dtype differs')
                buffer, offset = bytearray(expected_size), 0
                for start, chunk in self.store.iter_chunks(key, name, budget=self.budget):
                    _cancel(cancel)
                    if start != offset or offset+chunk.size > expected_size:
                        raise CompactStoreRefused('support chunk coverage differs')
                    buffer[offset:offset+chunk.size] = memoryview(chunk).cast('B')
                    offset += chunk.size
                if offset != expected_size or sha256(buffer).hexdigest() != content:
                    raise CompactStoreRefused('support content hash or length differs')
                _cancel(cancel)
                return bytes(buffer)

    def _read_packed(self, chunks, total, offset, size, content, *, cancel=None):
        """One blob from a root's packed array: only its covering chunks, hash-checked.

        ``chunks``/``total`` come from the root manifest that _root validated; each
        chunk is still fully verified by the store (stored and logical checksums).
        Caller owns the returned bytes' lifetime.
        """
        _cancel(cancel)
        width = self.store.limits.chunk_bytes
        if type(size) is not int or size <= 0 or offset+size > total or (offset+size-1)//width >= len(chunks):
            raise CompactStoreRefused('packed support range differs')
        with _workspace(self.budget, 2*size+2*width+65536, 'compact-support-read'):
            buffer, position = bytearray(size), 0
            with self.store._read_scope(budget=self.budget):
                for index in range(offset//width, (offset+size-1)//width+1):
                    _cancel(cancel)
                    start = index*width
                    raw = self.store._chunk(chunks[index], expected_dtype='|u1',
                                            expected_count=min(width, total-start))
                    low, high = max(offset, start)-start, min(offset+size, start+len(raw))-start
                    buffer[position:position+high-low] = raw[low:high]
                    position += high-low
                    del raw
            if position != size or sha256(buffer).hexdigest() != content:
                raise CompactStoreRefused('support content hash or length differs')
            _cancel(cancel)
            return bytes(buffer)

    def support_reader(self, content_sha256, expected_nbytes, *, cancel=None):
        """Pack/validation callback for staged content-addressed support snapshots."""
        record = _support_record(content_sha256, expected_nbytes)
        key = _digest(record)
        with _workspace(self.budget, 8*self.store.limits.max_manifest_bytes,
                        'compact-store-support-metadata'):
            with self.store._read_scope(budget=self.budget):
                manifest = self._manifest(key)
                if manifest['metadata'] != record or set(manifest['arrays']) != {'bytes'}:
                    raise CompactStoreRefused('support snapshot identity differs')
                return self._read_bytes(key, 'bytes', expected_nbytes, content_sha256, cancel=cancel)

    def publish(self, metadata, arrays, *, expected_geometry_id, source_producer=None,
                parent_snapshot=None, cancel=None, publication_check=None):
        """Validate codec data then atomically append one immutable mesh root.

        source_producer is preserved verbatim, including None for unknown. This
        adapter does not infer producer identity from the recording process.
        """
        _cancel(cancel)
        _sha(expected_geometry_id)
        if publication_check is not None and not callable(publication_check):
            raise CompactStoreRefused('publication_check must be callable')
        with _workspace(self.budget, 8*self.store.limits.max_manifest_bytes,
                        'compact-store-publication-metadata'):
            if parent_snapshot is not None:
                self._root(parent_snapshot)
            view = CompactMesh(metadata, arrays,
                support_reader=lambda content, size: self.support_reader(content, size, cancel=cancel),
                expected_geometry_id=expected_geometry_id, budget=self.budget,
                check=lambda: _cancel(cancel))
            payload = view.storage_payload()
            metadata, arrays = payload.value
            supports = {}
            values = {'mesh:'+name: array for name, array in arrays.items()}
            base_width = len(_json(metadata))+len(_json(source_producer))+1024
            for content, size in view.support_bindings():
                previous = supports.setdefault(content, size)
                if previous != size:
                    raise CompactStoreRefused('one support identity has different lengths')
                if base_width+160*len(supports) > self.store.limits.max_manifest_bytes:
                    raise CompactStoreRefused('compact root support inventory exceeds manifest limit')
                _support_record(content, size)
            offsets, total = _packed_offsets(supports)
            if total > self.store.limits.max_array_bytes:
                raise CompactStoreRefused('packed support blobs exceed the array limit')
            record = dict(schema=SCHEMA, geometry_id=expected_geometry_id,
                codec_metadata=metadata, supports=supports,
                source_producer=source_producer, parent_snapshot=parent_snapshot,
                authority=AUTHORITY)
            key = _digest(record)
            # CompactMesh already independently verified the arrays/legacy hash.
            # ArrayStore now checks/reuses exact typed chunks, with all
            # dependency checks inside its final write transaction.
            def check():
                _cancel(cancel)
                if parent_snapshot is not None:
                    self._root(parent_snapshot)
                if publication_check is not None:
                    publication_check()
                _cancel(cancel)
            # The packed buffer is charged before it is filled; each blob comes
            # from its staged content-addressed snapshot and is hash-checked.
            with _workspace(self.budget, total+65536, 'compact-store-support-pack'):
                packed = bytearray(total)
                for content in sorted(supports):
                    raw = self.support_reader(content, supports[content], cancel=cancel)
                    packed[offsets[content]:offsets[content]+len(raw)] = raw
                    del raw
                if supports:
                    values[SUPPORT_ARRAY] = np.frombuffer(packed, dtype=np.uint8)
                    values[SUPPORT_ARRAY].flags.writeable = False
                self.store.put(key, values, record, budget=self.budget,
                               cancel=cancel, publication_check=check)
                return key

    def _root(self, key):
        manifest = self._manifest(key)
        record = manifest['metadata']
        required = {'schema', 'geometry_id', 'codec_metadata', 'supports',
                    'source_producer', 'parent_snapshot', 'authority'}
        if (type(record) is not dict or set(record) != required or record['schema'] != SCHEMA
                or record['authority'] != AUTHORITY or _digest(record) != key
                or type(record['supports']) is not dict
                or type(record['codec_metadata']) is not dict
                or type(record['codec_metadata'].get('arrays')) is not dict):
            raise CompactStoreRefused('invalid compact mesh root')
        _sha(record['geometry_id'])
        if record['parent_snapshot'] is not None:
            _sha(record['parent_snapshot'])
        expected = {'mesh:'+name for name in record['codec_metadata']['arrays']}
        for content, size in record['supports'].items():
            _support_record(content, size)
        if record['supports']:
            expected.add(SUPPORT_ARRAY)
            row = manifest['arrays'].get(SUPPORT_ARRAY)
            if row is None or row['dtype'] != '|u1' or row['shape'] != [_packed_offsets(record['supports'])[1]]:
                raise CompactStoreRefused('root packed support descriptor differs')
        if set(manifest['arrays']) != expected:
            raise CompactStoreRefused('root array inventory differs')
        return manifest, record

    def open(self, key, *, expected_geometry_id, cancel=None):
        """Reopen compact tables; never materialise the root's support collection."""
        _cancel(cancel)
        _sha(expected_geometry_id)
        with _workspace(self.budget, 8*self.store.limits.max_manifest_bytes,
                        'compact-store-open-metadata'):
            with self.store._read_scope(budget=self.budget):
                manifest, record = self._root(key)
                if record['geometry_id'] != expected_geometry_id:
                    raise CompactStoreRefused('independently expected geometry ID differs')
                names = record['codec_metadata']['arrays']
                total = sum(math.prod(manifest['arrays']['mesh:'+name]['shape'])*
                            np.dtype(manifest['arrays']['mesh:'+name]['dtype']).itemsize for name in names)
                if total > self.store.limits.max_array_bytes:
                    raise CompactStoreRefused('geometry arrays exceed full read limit')
                with _workspace(self.budget, 2*total+65536, 'compact-store-open-arrays'):
                    arrays = {}
                    for name in names:
                        _cancel(cancel)
                        row = manifest['arrays']['mesh:'+name]
                        dtype, count = np.dtype(row['dtype']), math.prod(row['shape'])
                        buffer, offset = bytearray(count*dtype.itemsize), 0
                        for start, chunk in self.store.iter_chunks(key, 'mesh:'+name, budget=self.budget):
                            _cancel(cancel)
                            if start != offset or offset+chunk.size > count:
                                raise CompactStoreRefused('geometry chunk coverage differs')
                            begin, end = offset*dtype.itemsize, (offset+chunk.size)*dtype.itemsize
                            buffer[begin:end] = memoryview(chunk).cast('B')
                            offset += chunk.size
                        if offset != count:
                            raise CompactStoreRefused('geometry array is incomplete')
                        arrays[name] = np.frombuffer(bytes(buffer), dtype=dtype).reshape(row['shape'])
                    supports = record['supports']
                    offsets, packed_total = _packed_offsets(supports)
                    chunks = tuple(manifest['arrays'][SUPPORT_ARRAY]['chunks']) if supports else ()
                    inventory_owner = _RetainedMetadata(self.budget, 8*len(_json(supports))+128*len(chunks)+4096)
                    def read_support(content, size, _owner=inventory_owner):
                        if supports.get(content) != size:
                            raise CompactStoreRefused('support absent from exact root binding')
                        return self._read_packed(chunks, packed_total, offsets[content], size, content, cancel=cancel)
                    result = CompactMesh(record['codec_metadata'], arrays,
                        support_reader=read_support, expected_geometry_id=expected_geometry_id,
                        budget=self.budget, check=lambda: _cancel(cancel))
                    if dict(result.support_bindings()) != supports:
                        raise CompactStoreRefused('support inventory has missing or unused bindings')
                    return result


V3_SCHEMA = 'atlas.compact-mesh-store.v3'
V3_PROFILE = 'atlas.mesh-partition-supports.v3'


class _ArraySource:
    """A lazy bounded typed source over an already owned codec column."""
    def __init__(self, scope, name, array):
        from segment_store import ArrayInfo
        self.scope, self.array = scope, array
        self.info = ArrayInfo(name, array.dtype.str, tuple(array.shape), array.nbytes)

    def blocks(self, *, max_owned_bytes):
        from content_cache import ChargeSpec, OwnedStream
        def generate():
            raw = memoryview(self.array.reshape(-1)).cast('B')
            for start in range(0, len(raw), max_owned_bytes):
                size = min(max_owned_bytes, len(raw)-start)
                with self.scope.reserve(ChargeSpec('mesh-column-block', size+4096)) as reservation:
                    yield reservation.commit(bytes(raw[start:start+size]))
        return OwnedStream(generate(), scope=self.scope)


class _V3Supports:
    def __init__(self, segment, arrays, source, static, owner):
        self.segment, self.arrays, self.source = segment, arrays, source
        self.static, self.owner = static, owner

    def ident(self, index):
        return self.arrays['id.bytes'][int(self.arrays['s.id'][index])].tobytes().hex()

    def is_shared(self, index):
        from mesh_tables import TABLES
        return TABLES[int(self.arrays['s.table'][index])] == 'differential_supports'

    def blob(self, index):
        return int(self.arrays['s.id'][index]) if self.is_shared(index) else self.static[index][0]

    def size(self, index):
        return (self.source.identity(self.ident(index)).canonical_bytes if self.is_shared(index)
                else self.static[index][1])

    def iter_json(self, index):
        from content_cache import OwnedStream
        from mesh_tables import require
        ident, size = self.ident(index), self.size(index)
        def generate():
            digest, count = sha256(), 0
            if self.is_shared(index):
                stream = self.source.iter_json(ident, max_chunk_bytes=65536)
                content = ident
            else:
                blob, _, start = self.static[index]
                content = self.arrays['id.bytes'][blob].tobytes().hex()
                def static_blocks():
                    for at in range(start, start+size, 65536):
                        yield self.segment.read('static.bytes', at, min(at+65536, start+size), max_owned_bytes=131072)
                stream = OwnedStream(static_blocks(), scope=self.segment.scope)
            with stream:
                for block in stream:
                    digest.update(block.value); count += len(block.value)
                    yield block
            require(count == size and digest.hexdigest() == content, 'shared/static support content binding differs')
        return OwnedStream(generate(), owners=(self.owner,), scope=self.segment.scope)

    def export(self, index):
        from content_cache import ChargeSpec
        from mesh_tables import _decode_charge, canonical, require
        import json
        size = self.size(index)
        require(size <= MAX_SUPPORT_BYTES, 'one-support export exceeds explicit bound')
        if self.is_shared(index):
            return self.source.export(self.ident(index), max_logical_bytes=MAX_SUPPORT_BYTES,
                                      max_owned_bytes=MAX_SUPPORT_BYTES)
        with self.segment.scope.reserve(ChargeSpec('static-support-export-bytes', 2*size+65536)) as reservation:
            buffer = bytearray()
            with self.iter_json(index) as stream:
                for held in stream:
                    with held:
                        buffer.extend(held.value)
            raw = reservation.commit(bytes(buffer), dependencies=(self.owner,))
        with self.segment.scope.reserve(ChargeSpec('static-support-export', _decode_charge(raw.value))) as reservation:
            value = json.loads(raw.value)
            require(canonical(value) == raw.value, 'static support is not canonical')
            result = reservation.commit(value, dependencies=(self.owner,))
        raw.close()
        return result


class CompactMeshStoreV3:
    """Explicit v3 only: segmented columns and one authenticated partition owner."""
    def __init__(self, resolver, *, scope, support_source=None):
        from mesh_tables import require
        from support_source import SupportSource
        require(resolver.scope is scope, 'mesh resolver has foreign retained scope')
        require(support_source is None or type(support_source) is SupportSource and support_source.scope is scope,
                'mesh support source has foreign retained scope')
        self.resolver, self.scope, self.source = resolver, scope, support_source

    def publish(self, view, *, producer, cancel=None):
        from compact_contracts import LogicalIdentity
        from content_cache import ChargeSpec
        from mesh_tables import TABLES, canonical, require
        from segment_store import SegmentBackend
        require(type(view) is CompactMesh and view.budget is self.scope.run_budget,
                'actual same-run mesh required')
        require(self.source is not None and self.source.scope is self.scope,
                'v3 requires its explicit partition support source')
        _cancel(cancel)
        SegmentBackend().verify(self.resolver, self.source.binding.partition, scope=self.scope, cancel=cancel)
        identity = view.identity()
        require(type(identity) is LogicalIdentity, 'verified mesh logical identity required')
        if view._segment is not None:
            require(view.scope is self.scope and
                    view._reader.source.binding.to_wire() == self.source.binding.to_wire(),
                    'v3 republication source differs')
            require(view._segment._owner.value['producer'] == producer,
                    'v3 republication producer differs')
            ref = view._segment.info.ref
            SegmentBackend().verify(self.resolver, ref, scope=self.scope, cancel=cancel)
            return ref
        with_view = view.storage_payload()
        codec, arrays = with_view.value
        header_support_ids = codec['header'].pop('support_ids', None)
        static_rows, static_bytes = [], 0
        # Differential support bodies remain partition-owned. Verify exact IDs
        # and lengths for every mesh entry, regardless of partition order.
        for index in range(len(arrays['s.id'])):
            _cancel(cancel)
            ident = view.ident(int(arrays['s.id'][index]))
            content = view.ident(int(arrays['s.blob'][index]))
            size = int(arrays['s.size'][index])
            if TABLES[int(arrays['s.table'][index])] == 'differential_supports':
                found = self.source.identity(ident)
                require(content == ident == found.sha256 and found.canonical_bytes == size,
                        'mesh/partition support content identity differs')
            else:
                static_rows.append((index, int(arrays['s.blob'][index]), size, static_bytes))
                static_bytes += size
        require(static_bytes <= 128 << 20, 'static mesh table exceeds explicit array bound')
        # Only static supports are copied. No per-differential snapshot or blob
        # array is requested, even transiently, by this v3 route.
        with self.scope.reserve(ChargeSpec('mesh-static-tables', static_bytes+128*len(static_rows)+65536)) as reservation:
            data = bytearray(static_bytes)
            for index, _, size, start in static_rows:
                _cancel(cancel)
                raw, held = view._support_blob(index)
                data[start:start+size] = raw
                del raw, held
            static_owner = reservation.commit(data)
        payload = {name: array for name, array in arrays.items() if name not in ('s.blob', 's.size')}
        payload['static.index'] = np.array(static_rows, dtype='<u8').reshape(-1, 4)
        payload['static.bytes'] = np.frombuffer(static_owner.value, dtype='u1')
        if header_support_ids is not None:
            payload['header.support_ids'] = np.frombuffer(
                b''.join(bytes.fromhex(value) for value in header_support_ids), dtype='u1').reshape(-1, 32)
        descriptors = {name: dict(dtype=array.dtype.str, shape=list(array.shape),
            sha256=sha256(memoryview(array.reshape(-1)).cast('B')).hexdigest()) for name, array in payload.items()}
        metadata = canonical(dict(schema=V3_SCHEMA, codec=codec, support_source=self.source.binding.to_wire(),
                                  header_support_ids=header_support_ids is not None, arrays=descriptors))
        require(len(metadata) <= 65536, 'mesh v3 metadata exceeds bounded root')
        ref = SegmentBackend().publish(self.resolver, record_schema=identity.record_schema,
            identity=identity, metadata=metadata,
            arrays=lambda payload=payload: (_ArraySource(self.scope, name, payload[name]) for name in sorted(payload)),
            producer=producer, representation_profile=V3_PROFILE, scope=self.scope, cancel=cancel)
        del payload, data, arrays, codec, with_view
        static_owner.close()
        return ref

    def open(self, ref, *, expected_geometry_id, cancel=None):
        from content_cache import ChargeSpec
        from mesh_tables import _decode_charge, require
        from record_views import _Segment
        from segment_store import SegmentBackend, parse
        segment = SegmentBackend().open(self.resolver, ref, scope=self.scope, cancel=cancel)
        with segment.metadata() as held:
            with self.scope.reserve(ChargeSpec('mesh-root-metadata', _decode_charge(held.value))) as reservation:
                metadata_owner = reservation.commit(parse(held.value))
        metadata = metadata_owner.value
        require(type(metadata) is dict and set(metadata) == {'schema', 'codec', 'support_source', 'arrays',
                'header_support_ids'} and type(metadata['header_support_ids']) is bool and
                metadata['schema'] == V3_SCHEMA, 'unsupported mesh v3 root')
        require(ref.identity.sha256 == expected_geometry_id == metadata['codec']['geometry_id'],
                'independently expected mesh geometry differs')
        source = self.source
        if source is None:
            from support_source import open_support_source
            source = open_support_source(self.resolver, metadata['support_source'], scope=self.scope,
                                         check=lambda: _cancel(cancel))
        require(source.scope is self.scope and source.binding.to_wire() == metadata['support_source'],
                'mesh shared support binding differs or has foreign scope')
        descriptors = metadata['arrays']
        require(set(descriptors) == (set(metadata['codec']['arrays'])-{'s.blob', 's.size'}) |
                {'static.index', 'static.bytes'} | ({'header.support_ids'} if metadata['header_support_ids'] else set()),
                'mesh v3 column inventory differs')
        require(segment.info.array_count == len(descriptors), 'mesh v3 segment inventory differs')
        flattened = {}
        for name, descriptor in descriptors.items():
            require(type(descriptor) is dict and set(descriptor) == {'dtype', 'shape', 'sha256'},
                    'mesh v3 column descriptor differs')
            if not name.startswith(('static.', 'header.')):
                require(descriptor == metadata['codec']['arrays'][name],
                        'mesh codec/segment column binding differs')
            with segment.info.array(name) as held:
                require(held.value.dtype == descriptor['dtype'] and list(held.value.shape) == descriptor['shape'],
                        'mesh v3 typed descriptor differs')
            digest = sha256()
            with segment.iter(name, block_bytes=65536, max_owned_bytes=131072) as stream:
                for block in stream:
                    with block:
                        digest.update(block.value)
            require(digest.hexdigest() == descriptor['sha256'], 'mesh v3 column bytes differ')
            flattened[name] = dict(descriptor, shape=[math.prod(descriptor['shape'])])
        columns = _Segment(segment, flattened)
        del metadata, descriptors, descriptor
        # Preparation is one internal read, just like admission below. Borrow
        # the existing paid pages and verify both sources before any result
        # escapes; scalar access still checks cancellation inside the batch.
        with columns.read_batch(), source._partition.record._read_batch():
            return self._prepare_open(segment, metadata_owner, columns, source, cancel=cancel)

    def _prepare_open(self, segment, metadata_owner, columns, source, *, cancel):
        from content_cache import ChargeSpec
        from mesh_tables import (DerivedSupportColumn, SegmentColumn, canonical, mesh_from_segment, require)
        metadata = metadata_owner.value
        descriptors = metadata['arrays']
        arrays = {name: SegmentColumn(columns, name, descriptor) for name, descriptor in descriptors.items()
                  if not name.startswith(('static.', 'header.'))}
        header_owner = None
        if metadata['header_support_ids']:
            column = SegmentColumn(columns, 'header.support_ids', descriptors['header.support_ids'])
            require(column.dtype.str == '|u1' and column.shape[1:] == (32,), 'header ID column differs')
            with self.scope.reserve(ChargeSpec('mesh-header-ids', 1024*len(column)+65536)) as reservation:
                header_owner = reservation.commit([row.tobytes().hex() for row in column])
            metadata['codec']['header']['support_ids'] = header_owner.value
        static_column = SegmentColumn(columns, 'static.index', descriptors['static.index'])
        require(static_column.dtype.str == '<u8' and static_column.shape[1:] == (4,),
                'static support index shape differs')
        owner = self.scope.reserve(ChargeSpec('mesh-support-index', 65536+192*len(static_column)+
            8*len(canonical(metadata['support_source'])))).commit({}, dependencies=(segment._owner, source._owner))
        static, previous, end = owner.value, -1, 0
        for row in static_column:
            index, blob, size, start = map(int, row)
            require(previous < index < len(arrays['s.id']) and start == end and 0 < size <= MAX_SUPPORT_BYTES,
                    'static support index coverage differs')
            static[index] = (blob, size, start)
            previous, end = index, start+size
        require(descriptors['static.bytes']['dtype'] == '|u1' and descriptors['static.bytes']['shape'] == [end],
                'static support payload coverage differs')
        reader = _V3Supports(segment, arrays, source, static, owner)
        for index in range(len(arrays['s.id'])):
            require(reader.is_shared(index) == (index not in static), 'static/shared support coverage differs')
            if reader.is_shared(index):
                require(source.identity(reader.ident(index)).sha256 == reader.ident(index),
                        'partition support ID differs from content')
        arrays['s.blob'] = DerivedSupportColumn(len(arrays['s.id']), reader.blob)
        arrays['s.size'] = DerivedSupportColumn(len(arrays['s.id']), reader.size)
        for name in ('s.blob', 's.size'):
            digest = sha256()
            for value in arrays[name]:
                digest.update(int(value).to_bytes(8, 'little'))
            require(digest.hexdigest() == metadata['codec']['arrays'][name]['sha256'],
                    'derived support column differs')
        result = mesh_from_segment(segment, metadata['codec'], arrays, reader, check=lambda: _cancel(cancel))
        if header_owner is not None:
            del metadata['codec']['header']['support_ids']
        del metadata, descriptors
        metadata_owner.close()
        if header_owner is not None:
            header_owner.close()
        return result
