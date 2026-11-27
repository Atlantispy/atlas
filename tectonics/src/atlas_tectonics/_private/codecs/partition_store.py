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

from atlas_tectonics._private.integration import native_transfer as N
from atlas_tectonics._private.codecs.partition_tables import CompactPartition
from atlas_tectonics._private.codecs.compact_store import _cancel, descriptor_digest
from atlas_tectonics._private.integration.geometry.spatial_workflow_patch import _OwnedReference, _token
from atlas_tectonics.codecs.storage import StoreError
from atlas_tectonics.integration.coupling.spatial_transport import _workspace

SCHEMA = 'atlas.compact-partition-store.v1'
AUTHORITY = 'storage integrity only; scientific admission required'


def publish_partition_v2(candidate, view, *, producer, check=lambda: None, cancel=None):
    """One descriptor segment root, with no support snapshots or workflow aliases."""
    from atlas_tectonics._private.integration.geometry.partition_adapter import DESCRIPTOR, PROFILE
    from atlas_tectonics._private.codecs.segment_store import SegmentBackend
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
    from atlas_tectonics._private.integration.geometry.partition_adapter import PartitionV2
    from atlas_tectonics._private.codecs.record_views import CompactRecord
    from atlas_tectonics._private.codecs.segment_store import SegmentBackend
    token = _token(check, cancel)
    segment = SegmentBackend().open(resolver, ref, scope=scope, cancel=token)
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
    return partition_id


def binding(partition_id, source_producer):
    return dict(schema=SCHEMA, partition_id=partition_id, source_producer=source_producer)


def key_for(partition_id, source_producer):
    return sha256(N._json(binding(partition_id, source_producer))).hexdigest()


class CompactPartitionStore:
    def __init__(self, store, *, budget):
        self.store, self.budget = store, budget

    def _root(self, key):
        manifest = self.store._manifest(key)
        row = manifest['metadata']
        codec = row['codec_metadata']
        for name, desc in codec['arrays'].items():
            desc['sha256']
        return manifest, row

    def reference(self, key, *, expected_partition_id, source_producer):
        """Bind each DAG array by its ArrayReference descriptor digest, not its chunk list."""
        with _workspace(self.budget, 65536+8*self.store.limits.max_manifest_bytes, 'partition-store-reference'):
            with self.store._read_scope(budget=self.budget):
                manifest, row = self._root(key)
                bindings = {name: descriptor_digest(desc) for name, desc in manifest['arrays'].items()}
                return _OwnedReference(dict(schema=SCHEMA, snapshot_key=key, partition_id=expected_partition_id,
                    source_producer=row['source_producer'], array_bindings=bindings), self.budget)

    def verify_reference(self, reference, *, expected_partition_id):
        actual = self.reference(reference['snapshot_key'], expected_partition_id=expected_partition_id,
                                source_producer=reference['source_producer'])
        return actual

    def find(self, partition_id, source_producer):
        key = key_for(partition_id, source_producer)
        with _workspace(self.budget, 65536+8*self.store.limits.max_manifest_bytes, 'partition-store-lookup'):
            with self.store._read_scope(budget=self.budget):
                if self.store._manifest(key) is None:
                    return None
            return self.reference(key, expected_partition_id=partition_id, source_producer=source_producer)

    def publish(self, view, *, source_producer, check=lambda: None, cancel=None, publication_check=None):
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
        with _workspace(self.budget, 65536+8*self.store.limits.max_manifest_bytes, 'partition-store-manifest'):
            with self.store._read_scope(budget=self.budget):
                self.verify_reference(reference, expected_partition_id=expected_partition_id)
                manifest, row = self._root(reference['snapshot_key'])
                total = sum(math.prod(d['shape'])*np.dtype(d['dtype']).itemsize for d in manifest['arrays'].values())
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
                            buffer[count:count+len(raw)] = raw
                            count += len(raw)
                        arrays[name] = np.frombuffer(N._RecordBytes(buffer, allocation), dtype=dtype).reshape(desc['shape'])
                        buffer = raw = None
                del manifest, row
        # Full validation streams the logical body and every support hash; it must
        # not hold the store lock or keep an SQLite read transaction open.
        return CompactPartition(codec, arrays, expected_partition_id=expected_partition_id,
                                budget=self.budget, check=lambda: _cancel(token))
