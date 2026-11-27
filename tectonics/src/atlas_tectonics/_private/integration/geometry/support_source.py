"""Paid shared support access to one published compact partition.

A published SegmentRef binds the immutable partition value. It does not imply
that its interval has been promoted. Cold readers authenticate that separately
through the supplied resolver. No support snapshots or decoded-support cache
are created here.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import ClassVar

from atlas_tectonics._private.codecs.compact_contracts import (SegmentRef,
                               _sha, _uint)
from atlas_tectonics._private.codecs.content_cache import ChargeSpec, OwnedStream, check_cancel
from atlas_tectonics._private.codecs import record_tables as T
from atlas_tectonics._private.codecs.record_views import RecordRef

SCHEMA = 'atlas.partition-support-source.v1'
SUPPORT_SCHEMA = 'atlas.differential-physical-support.v1'
SOURCE_BYTES = 32768


@dataclass(frozen=True, slots=True)
class SupportBinding:
    """Exact versioned wire contract; construction alone proves no authority."""
    partition: SegmentRef
    inventory_digest: str
    count: int
    schema: ClassVar[str] = SCHEMA

    def __post_init__(self):
        _sha(self.inventory_digest, 'support inventory digest')
        _uint(self.count, 'support inventory count')

    def to_wire(self):
        return dict(schema=SCHEMA, partition=self.partition.to_wire(),
                    inventory_digest=self.inventory_digest, count=self.count)

    @classmethod
    def from_wire(cls, value):
        row = value
        return cls(SegmentRef.from_wire(row['partition']), row['inventory_digest'], row['count'])


class _SupportRef(RecordRef):
    """A verified support whose paid ancestry terminates at its source."""
    def __init__(self, ref, owner, identity, check):
        super().__init__(ref._view, ref.index, parent_owner=owner)
        self._support_identity = identity
        self._source_check = check

    def _live(self):
        super()._live()
        self._source_check()

    def identity(self):
        self._live()
        return self._support_identity

    def iter_json(self, *, max_chunk_bytes=T.CHUNK):
        self._live()
        def generate():
            digest, length = sha256(), 0
            with super(_SupportRef, self).iter_json(max_chunk_bytes=max_chunk_bytes) as stream:
                for block in stream:
                    self._source_check()
                    digest.update(block.value)
                    length += len(block.value)
                    yield block
            self._source_check()
        return OwnedStream(generate(), owners=(self._owner,), scope=self.scope)


class SupportSource:
    def __init__(self, partition_view, *, check=lambda: None, cancel=None,
                 _owns_partition=False):
        ref = partition_view.segment_ref
        scope = partition_view.scope
        self._check, self._cancel = check, cancel
        self._partition, self._owns_partition = partition_view, _owns_partition
        self._closed = False
        # Reuse the partition's already paid, validated exact ID index. Only
        # one hash state and one scalar ID are live while binding the inventory.
        with scope.reserve(ChargeSpec('partition-support-source', SOURCE_BYTES),
                           required=True, cancel=cancel) as reservation:
            digest = sha256(b'[')
            count = partition_view.support_count
            _uint(count, 'support inventory count')
            for i in range(count):
                self._tick()
                identity = partition_view.support_id(i)
                _sha(identity, 'support ID')
                if i:
                    digest.update(b',')
                digest.update(T.canonical(identity))
            digest.update(b']')
            binding = SupportBinding(ref, digest.hexdigest(), count)
            self._owner = reservation.commit((partition_view, binding), dependencies=(
                partition_view.record._owner, partition_view._index))
        self._binding = binding

    def _tick(self):
        check_cancel(self._cancel)
        self._check()
        check_cancel(self._cancel)

    def _live(self):
        self._owner.value
        self._tick()
        # PartitionV2.identity checks the physical file and observed sealed
        # ancestors (or its immutable in-memory owner) before reusing its seal.

    def check_unchanged(self):
        """Check physical freshness before reusing an authenticated identity."""
        self._live()

    @property
    def scope(self):
        self._live()
        return self._owner.scope

    @property
    def binding(self):
        self._live()
        return self._binding

    @property
    def count(self):
        self._live()
        return self._binding.count

    def id_at(self, index):
        self._live()
        return self._partition.support_id(index)

    def ref_for(self, support_id):
        """Reuse the partition's streamed proof and exact paid support lookup."""
        self._live()
        _sha(support_id, 'support ID')
        identity = self._partition.support_identity(support_id)
        ref = self._partition.support_by_id(support_id)
        try:
            result = _SupportRef(ref, self._owner, identity, self.check_unchanged)
        except BaseException:
            # Failed lookup frames retain their paid references until their
            # traceback is released, without replacing the original error.
            del ref
            raise
        ref.close()
        return result

    def identity(self, support_id):
        self._live()
        _sha(support_id, 'support ID')
        identity = self._partition.support_identity(support_id)
        return identity

    def iter_json(self, support_id, *, max_chunk_bytes=T.CHUNK):
        ref = self.ref_for(support_id)
        # The stream owns its ancestry. Discarding this temporary wrapper lets
        # that paid ancestry retire when the stream releases its last child.
        try:
            return ref.iter_json(max_chunk_bytes=max_chunk_bytes)
        finally:
            del ref

    def export(self, support_id, *, max_logical_bytes, max_owned_bytes):
        ref = self.ref_for(support_id)
        try:
            result = ref.export(max_logical_bytes=max_logical_bytes,
                                max_owned_bytes=max_owned_bytes)
        except BaseException:
            # A refused export keeps its failing frames' paid borrows until the
            # traceback is released; closing here would replace the original error.
            del ref
            raise
        ref.close()
        return result

    def close(self):
        if self._closed:
            return
        self._owner.assert_unborrowed()
        self._owner.close()
        if self._owns_partition:
            self._partition.close()
        self._partition = None
        self._closed = True


def support_source(partition_view):
    return SupportSource(partition_view)


def open_support_source(resolver, binding, *, scope, check=lambda: None, cancel=None):
    """Open and own the partition identified by an exact support binding."""
    from atlas_tectonics._private.codecs.partition_store import open_partition_v2
    if type(binding) is dict:
        binding = SupportBinding.from_wire(binding)
    partition = open_partition_v2(resolver, binding.partition, scope=scope, check=check, cancel=cancel)
    source = None
    try:
        source = SupportSource(partition, check=check, cancel=cancel, _owns_partition=True)
        return source
    except BaseException:
        if source is not None:
            source.close()
        else:
            partition.close()
        raise
