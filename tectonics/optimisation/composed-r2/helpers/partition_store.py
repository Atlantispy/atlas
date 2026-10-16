"""Immutable typed partition DAG arrays in the existing ArrayStore.

Content integrity only. Native source/geometry admission remains a separate gate.
One root per (partition_id, source_producer); publication finds an existing root
first and otherwise appends one atomic put. Opening reads owned immutable column
buffers inside one pinned read snapshot, then runs the full codec validation
(streamed body and every ordered support identity) outside the store lock.
"""
from hashlib import sha256
import math
import numpy as np

import native_transfer as N
import mesh_tables as M
from partition_tables import CompactPartition
from compact_store import _cancel, descriptor_digest
from spatial_workflow_patch import _OwnedReference, _token
from atlas_tectonics.resources import WorkBudget
from atlas_tectonics.storage import ArrayStore, StoreError
from atlas_tectonics.integration_spatial_transport import _workspace

SCHEMA = 'atlas.compact-partition-store.v1'
AUTHORITY = 'storage integrity only; scientific admission required'
REFERENCE_KEYS = frozenset(('schema', 'snapshot_key', 'partition_id', 'source_producer', 'array_bindings'))


def publish_partition_v2(candidate, view, *, producer, check=lambda: None, cancel=None):
    """One descriptor segment root, with no support snapshots or workflow aliases."""
    from partition_v2 import PartitionV2, DESCRIPTOR, PROFILE
    from segment_store import SegmentBackend
    require(type(view) is PartitionV2 and view._sealed and candidate.scope is view.scope,
            'sealed same-scope partition v2 required')
    token = _token(check, cancel)
    _cancel(token)
    with view.record.metadata_bytes() as metadata:
        ref = SegmentBackend().publish(candidate, record_schema=DESCRIPTOR,
            identity=view.identity(), metadata=metadata.value,
            arrays=view.record.array_sources, producer=producer,
            representation_profile=PROFILE, scope=view.scope, cancel=token)
    _cancel(token)
    view.bind_segment(ref)
    return ref


def open_partition_v2(resolver, ref, *, scope, check=lambda: None, cancel=None):
    """Read a partition v2 from its bounded authenticated segment directory."""
    from compact_contracts import SegmentRef
    from partition_v2 import PartitionV2, DESCRIPTOR, PROFILE
    from record_views import CompactRecord
    from segment_store import SegmentBackend
    require(type(ref) is SegmentRef and ref.identity.record_schema == DESCRIPTOR and
            resolver.scope is scope, 'partition v2 reference and same-scope resolver required')
    token = _token(check, cancel)
    segment = SegmentBackend().open(resolver, ref, scope=scope, cancel=token)
    require(segment._owner.value['representation_profile'] == PROFILE,
            'unsupported partition representation profile')
    record = CompactRecord.from_segment(segment, check=lambda: _cancel(token))
    root = record.root()
    child = root.field('partition_id')
    try:
        with child.scalar(max_owned_bytes=1 << 20) as owned:
            partition_id = owned.value
    finally:
        child.close(); root.close()
    return PartitionV2(record, expected_partition_id=partition_id, segment_ref=ref,
                       check=lambda: _cancel(token))


class CompactPartitionStoreRefused(StoreError):
    pass


def require(value, message):
    if not value:
        raise CompactPartitionStoreRefused(message)


def _identity(partition_id):
    require(type(partition_id) is str and len(partition_id) == 64 and
            all(c in '0123456789abcdef' for c in partition_id), 'canonical partition SHA-256 required')
    return partition_id


def binding(partition_id, source_producer):
    _identity(partition_id)
    require(type(source_producer) is dict and bool(source_producer), 'actual partition producer required')
    return dict(schema=SCHEMA, partition_id=partition_id, source_producer=source_producer)


def key_for(partition_id, source_producer):
    return sha256(N._json(binding(partition_id, source_producer))).hexdigest()


class CompactPartitionStore:
    def __init__(self, store, *, budget):
        require(type(budget) is WorkBudget, 'actual shared WorkBudget required')
        require(type(store) is ArrayStore and store._budget is budget, 'actual same-budget ArrayStore required')
        self.store, self.budget = store, budget

    def _root(self, key):
        manifest = self.store._manifest(key)
        require(manifest is not None, 'compact partition root is missing')
        row = manifest['metadata']
        require(type(row) is dict and set(row) == {'schema', 'partition_id', 'source_producer', 'codec_metadata', 'authority'}
                and row['schema'] == SCHEMA and row['authority'] == AUTHORITY,
                'complete compact partition root required')
        require(key_for(row['partition_id'], row['source_producer']) == key, 'partition root producer/identity differs')
        codec = row['codec_metadata']
        require(type(codec) is dict and type(codec.get('arrays')) is dict and
                set(manifest['arrays']) == set(codec['arrays']), 'complete compact partition array inventory required')
        for name, desc in codec['arrays'].items():
            require(type(desc) is dict and set(desc) == {'dtype', 'shape', 'sha256'} and
                    manifest['arrays'][name]['dtype'] == desc['dtype'] and
                    manifest['arrays'][name]['shape'] == desc['shape'], 'compact partition typed binding differs')
            _identity(desc['sha256'])
        return manifest, row

    def reference(self, key, *, expected_partition_id, source_producer):
        """Bind each DAG array by its ArrayReference descriptor digest, not its chunk list."""
        with _workspace(self.budget, 65536+8*self.store.limits.max_manifest_bytes, 'partition-store-reference'):
            with self.store._read_scope(budget=self.budget):
                manifest, row = self._root(key)
                require(row['partition_id'] == expected_partition_id and row['source_producer'] == source_producer,
                        'partition original identity or producer differs')
                bindings = {name: descriptor_digest(desc) for name, desc in manifest['arrays'].items()}
                return _OwnedReference(dict(schema=SCHEMA, snapshot_key=key, partition_id=expected_partition_id,
                    source_producer=row['source_producer'], array_bindings=bindings), self.budget)

    def verify_reference(self, reference, *, expected_partition_id):
        require(isinstance(reference, dict) and set(reference) == REFERENCE_KEYS and reference['schema'] == SCHEMA and
                    reference['partition_id'] == expected_partition_id, 'complete externally bound partition reference required')
        actual = self.reference(reference['snapshot_key'], expected_partition_id=expected_partition_id,
                                source_producer=reference['source_producer'])
        require(actual == reference, 'current immutable partition reference differs')
        return actual

    def find(self, partition_id, source_producer):
        key = key_for(partition_id, source_producer)
        with _workspace(self.budget, 65536+8*self.store.limits.max_manifest_bytes, 'partition-store-lookup'):
            with self.store._read_scope(budget=self.budget):
                if self.store._manifest(key) is None:
                    return None
            return self.reference(key, expected_partition_id=partition_id, source_producer=source_producer)

    def publish(self, view, *, source_producer, check=lambda: None, cancel=None, publication_check=None):
        require(type(view) is CompactPartition and view.budget is self.budget and getattr(view, '_sealed', False),
                'actual immutable shared-budget compact partition required')
        require(publication_check is None or callable(publication_check), 'publication_check must be callable')
        require(getattr(self.store, '_historical_readonly', None) is None, 'never publish into the authenticated original')
        token = _token(check, cancel)
        _cancel(token)
        # The key binds only (partition_id, producer). A stored root is revalidated
        # on every open, so an existing one is reused rather than restaged.
        existing = self.find(view.partition_id, source_producer)
        if existing is not None:
            return existing
        owned = view.storage_payload()
        metadata, arrays = owned.value
        # No rebuild: the sealed constructor already streamed every column, the
        # original body, each ordered support digest and the schema gate over
        # these same immutable buffers. Neither confers scientific acceptance.
        row = dict(binding(view.partition_id, source_producer), codec_metadata=metadata, authority=AUTHORITY)
        key = key_for(view.partition_id, source_producer)
        def commit_check():
            _cancel(token)
            require(self.store._db.in_transaction and self.store.metadata(key) == row,
                    'atomic compact partition publication differs')
            if publication_check is not None:
                publication_check()
            _cancel(token)
        self.store.put(key, arrays, row, budget=self.budget, cancel=token, publication_check=commit_check)
        del metadata, arrays, owned
        return self.reference(key, expected_partition_id=view.partition_id, source_producer=source_producer)

    def open(self, reference, *, expected_partition_id, check=lambda: None, cancel=None):
        token = _token(check, cancel)
        _cancel(token)
        _identity(expected_partition_id)
        with _workspace(self.budget, 65536+8*self.store.limits.max_manifest_bytes, 'partition-store-manifest'):
            with self.store._read_scope(budget=self.budget):
                self.verify_reference(reference, expected_partition_id=expected_partition_id)
                manifest, row = self._root(reference['snapshot_key'])
                total = sum(math.prod(d['shape'])*np.dtype(d['dtype']).itemsize for d in manifest['arrays'].values())
                require(total <= min(M.MAX_BYTES, self.store.limits.max_array_bytes), 'partition arrays exceed read bound')
                codec = row['codec_metadata']
                # One retained owner funds the columns (and the small codec row)
                # until the constructor's own frozen copies replace them; a held
                # failure traceback keeps it, and so its charge, alive.
                allocation = N._Allocation(self.budget, total+65536+1024*len(manifest['arrays'])+4*N._width(codec),
                                           category='partition-store-arrays')
                arrays = {}
                for name, desc in manifest['arrays'].items():
                    _cancel(token)
                    dtype = np.dtype(desc['dtype'])
                    size = math.prod(desc['shape'])*dtype.itemsize
                    with _workspace(self.budget, 2*size+65536, 'partition-store-array-read'):
                        buffer, count, raw = bytearray(size), 0, None
                        for offset, values in self.store.iter_chunks(reference['snapshot_key'], name, budget=self.budget):
                            _cancel(token)
                            raw = memoryview(values).cast('B')
                            require(offset*dtype.itemsize == count and count+len(raw) <= size,
                                    'compact partition chunk coverage differs')
                            buffer[count:count+len(raw)] = raw
                            count += len(raw)
                        require(count == size and sha256(buffer).hexdigest() == codec['arrays'][name]['sha256'],
                                'compact partition column bytes differ')
                        arrays[name] = np.frombuffer(N._RecordBytes(buffer, allocation), dtype=dtype).reshape(desc['shape'])
                        buffer = raw = None
                del manifest, row
        # Full validation streams the logical body and every support hash; it must
        # not hold the store lock or keep an SQLite read transaction open.
        return CompactPartition(codec, arrays, expected_partition_id=expected_partition_id,
                                budget=self.budget, check=lambda: _cancel(token))
