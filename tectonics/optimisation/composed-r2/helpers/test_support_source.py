"""Synthetic shared-partition support ownership; no historical stores or solve."""
from concurrent.futures import CancelledError
from dataclasses import FrozenInstanceError, replace
import gc
from hashlib import sha256
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
TASK = HERE.parents[4]
sys.path[:0] = [str(HERE.parents[1] / 'runtime-integration-r1' / 'runtime-src'), str(HERE.parent)]

from atlas_tectonics.resources import WorkBudget
from compact_contracts import ContractError
from content_cache import ChargeSpec, create_retained_scope
from interval_store_set import IntervalStoreSet
import partition_store as PS
from partition_v2 import PartitionV2, pack_partition_v2
import record_tables as T
from record_views import CompactRecord, RecordRef
from support_source import SupportBinding, open_support_source, support_source
from test_partition_tables import tiny_partition


class SupportSourceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='step5-support-', dir=TASK / '_t')
        self.budget = WorkBudget(512 << 20)
        self.scope = create_retained_scope(self.budget, process_epoch='step5-support')
        self.stores = IntervalStoreSet.create_migration(Path(self.temp.name) / 'catalog.json',
            workflow_id='a' * 64, scope=self.scope)
        self.candidate = self.stores.begin_interval(None, producer_identity='b' * 64,
                                                     runtime_identity='c' * 64)
        self.body, self.supports = tiny_partition(self.budget, count=3, depth=0)
        self.partition = pack_partition_v2(self.body, iter(self.supports),
            expected_partition_id=sha256(T.canonical(self.body)).hexdigest(), scope=self.scope)
        self.ref = PS.publish_partition_v2(self.candidate, self.partition, producer='b' * 64)
        self.sources = []

    def tearDown(self):
        for source in reversed(self.sources):
            source.close()
        self.partition.close()
        self.candidate.close()
        self.stores.close()
        gc.collect()
        self.scope.close()
        self.assertEqual(self.budget.reserved_bytes, 0)
        self.temp.cleanup()

    def source(self):
        source = support_source(self.partition)
        self.sources.append(source)
        return source

    def promote(self):
        sealed = self.candidate.seal(self.ref)
        self.stores.promote(sealed, expected_catalog_digest=sealed.expected_catalog_digest)

    def test_full_inventory_and_shuffled_consumer_ids_exact_streams(self):
        before = self.candidate.local_statistics()
        with patch.object(CompactRecord, 'export', side_effect=AssertionError('whole export')):
            source = self.source()
            self.assertIs(source.scope, self.scope)
            self.assertEqual(source.count, len(self.supports))
            self.assertEqual([source.id_at(i) for i in range(source.count)], self.body['support_ids'])
            self.assertEqual(source.binding.inventory_digest,
                             sha256(T.canonical(self.body['support_ids'])).hexdigest())
            for i in (2, 0, 1):
                identity = self.body['support_ids'][i]
                expected = T.canonical(self.supports[i])
                logical = source.identity(identity)
                self.assertEqual(logical.record_schema, self.supports[i]['schema'])
                self.assertEqual((logical.sha256, logical.canonical_bytes),
                                 (identity, len(expected)))
                chunks = []
                with source.iter_json(identity, max_chunk_bytes=97) as stream:
                    for block in stream:
                        with block:
                            self.assertIs(block.scope, self.scope)
                            self.assertLessEqual(len(block.value), 97)
                            chunks.append(block.value)
                self.assertEqual(b''.join(chunks), expected)
        self.assertEqual(self.candidate.local_statistics(), before)

    def test_binding_is_exact_versioned_immutable_and_detached(self):
        binding = self.source().binding
        wire = binding.to_wire()
        self.assertEqual(set(wire), {'schema', 'partition', 'inventory_digest', 'count'})
        self.assertEqual(SupportBinding.from_wire(wire), binding)
        wire['partition']['identity']['sha256'] = 'f' * 64
        self.assertNotEqual(wire, binding.to_wire())
        with self.assertRaises(FrozenInstanceError):
            binding.count = 1
        for change in ({'schema': 'unsupported'}, {'count': True}, {'extra': None}):
            with self.assertRaises(ContractError):
                SupportBinding.from_wire(dict(binding.to_wire(), **change))

    def test_missing_changed_and_foreign_supports_refused(self):
        source = self.source()
        for bad in ('f' * 64, 'static-support-id', None):
            with self.assertRaises(ContractError):
                source.ref_for(bad)
        with patch.object(PartitionV2, 'support_by_id',
                          lambda view, identity: view.support(1)):
            with self.assertRaisesRegex(ContractError, 'support ID'):
                source.ref_for(self.body['support_ids'][0])
        other_budget = WorkBudget(512 << 20)
        other_scope = create_retained_scope(other_budget, process_epoch='foreign-support')
        other = pack_partition_v2(self.body, iter(self.supports),
            expected_partition_id=self.partition.partition_id, scope=other_scope)
        with patch.object(PartitionV2, 'support_by_id', lambda view, identity: other.support(0)):
            with self.assertRaisesRegex(ContractError, 'foreign support'):
                source.ref_for(self.body['support_ids'][0])
        gc.collect()
        other.close()
        other_scope.close()
        self.assertEqual(other_budget.reserved_bytes, 0)

    def test_unpublished_unsealed_changed_and_foreign_resolver_refused(self):
        original = self.partition._segment_ref
        object.__setattr__(self.partition, '_segment_ref', None)
        with self.assertRaisesRegex(ContractError, 'published'):
            support_source(self.partition)
        object.__setattr__(self.partition, '_segment_ref', original)
        object.__setattr__(self.partition, '_sealed', False)
        with self.assertRaisesRegex(ContractError, 'sealed'):
            support_source(self.partition)
        object.__setattr__(self.partition, '_sealed', True)
        source = self.source()
        object.__setattr__(self.partition, '_segment_ref', replace(original, merkle_root='f' * 64))
        with self.assertRaisesRegex(ContractError, 'binding changed'):
            source.identity(self.body['support_ids'][0])
        object.__setattr__(self.partition, '_segment_ref', original)
        other_budget = WorkBudget(128 << 20)
        other_scope = create_retained_scope(other_budget, process_epoch='foreign-resolver')
        with self.assertRaisesRegex(ContractError, 'foreign support resolver'):
            open_support_source(self.candidate, source.binding, scope=other_scope)
        other_scope.close()
        self.assertEqual(other_budget.reserved_bytes, 0)

    def test_refs_streams_and_mesh_dependency_hold_source_and_partition(self):
        source = self.source()
        with self.assertRaises(RuntimeError):
            self.partition.close()
        ref = source.ref_for(self.body['support_ids'][0])
        child = ref.field('components')
        with self.assertRaises(RuntimeError):
            source.close()
        with self.assertRaises(RuntimeError):
            ref.close()
        child.close()
        ref.close()
        stream = source.iter_json(self.body['support_ids'][0], max_chunk_bytes=79)
        with self.assertRaises(RuntimeError):
            source.close()
        block = next(stream)
        stream.close()
        with self.scope.reserve(ChargeSpec('fixture-mesh-owner', 256)) as reservation:
            mesh = reservation.commit(None, dependencies=(source._owner,))
        with self.assertRaises(RuntimeError):
            source.close()
        mesh.close()
        source.close()
        # Escaped bytes have their own funding and do not borrow the source.
        self.assertIs(block.scope, self.scope)
        self.assertGreater(block.charged_bytes, 0)
        block.close()

    def test_bounded_one_support_export_no_all_row_expansion(self):
        source = self.source()
        identity = self.body['support_ids'][1]
        size = len(T.canonical(self.supports[1]))
        with patch.object(CompactRecord, 'export', side_effect=AssertionError('whole export')):
            with self.assertRaisesRegex(ContractError, 'logical export bound'):
                source.export(identity, max_logical_bytes=size-1, max_owned_bytes=16 << 20)
            with self.assertRaisesRegex(ContractError, 'owned export bound'):
                source.export(identity, max_logical_bytes=size, max_owned_bytes=100)
            with source.export(identity, max_logical_bytes=size, max_owned_bytes=16 << 20) as held:
                self.assertEqual(held.value, self.supports[1])
                self.assertLessEqual(held.charged_bytes, 16 << 20)
            escaped = source.export(identity, max_logical_bytes=size, max_owned_bytes=16 << 20)
            source.close()
            self.assertEqual(escaped.value, self.supports[1])
            escaped.close()

    def test_verified_identities_are_reused_without_body_rehash(self):
        source = self.source()
        identity = self.body['support_ids'][0]
        with patch.object(RecordRef, 'iter_json', side_effect=AssertionError('support rehashed')):
            for _ in range(5):
                self.assertEqual(source.identity(identity).sha256, identity)
                ref = source.ref_for(identity)
                self.assertEqual(ref.identity().sha256, identity)
                ref.close()
        original = RecordRef.iter_json
        visits = []
        def counted(ref, **kwargs):
            visits.append(ref.index)
            return original(ref, **kwargs)
        with patch.object(RecordRef, 'iter_json', counted):
            with source.iter_json(identity) as stream:
                for block in stream:
                    block.close()
        self.assertEqual(visits, [self.partition.support_node(identity)])

    def test_cold_open_checks_full_inventory_and_cleans_owned_partition(self):
        binding = self.source().binding
        self.promote()
        for changed in (replace(binding, count=binding.count-1),
                        replace(binding, inventory_digest='f' * 64)):
            with self.assertRaisesRegex(ContractError, 'inventory binding differs'):
                open_support_source(self.stores, changed, scope=self.scope)
        opened = open_support_source(self.stores, binding.to_wire(), scope=self.scope)
        self.sources.append(opened)
        partition = opened._partition
        self.assertEqual(opened.identity(self.body['support_ids'][2]).sha256,
                         self.body['support_ids'][2])
        opened.close()
        with self.assertRaises(RuntimeError):
            partition.identity()

    def test_sealed_identity_reuse_checks_physical_freshness(self):
        binding = self.source().binding
        self.promote()
        opened = open_support_source(self.stores, binding, scope=self.scope)
        self.sources.append(opened)
        ref = opened.ref_for(self.body['support_ids'][0])
        with patch.object(self.stores, 'assert_cached_read_safe',
                          side_effect=ContractError('fixture sealed file changed')):
            for action in (opened.check_unchanged, lambda: opened.id_at(0),
                           lambda: opened.identity(self.body['support_ids'][0]), ref.identity):
                with self.assertRaisesRegex(ContractError, 'sealed file changed'):
                    action()
        ref.close()

    def test_cancelled_stream_preserves_error_and_paid_failure_lifetime(self):
        source = self.source()
        calls = 0
        def check():
            nonlocal calls
            calls += 1
            if calls == 4:
                raise CancelledError('fixture support cancelled')
        source._check = check
        saved = None
        stream = source.iter_json(self.body['support_ids'][0])
        try:
            next(stream)
        except CancelledError as error:
            saved = error
        self.assertIsNotNone(saved)
        with self.assertRaises(RuntimeError):
            source.close()
        saved = None
        stream.close()
        stream = None
        gc.collect()
        source._check = lambda: None
        self.assertEqual(source.identity(self.body['support_ids'][0]).sha256,
                         self.body['support_ids'][0])


if __name__ == '__main__':
    unittest.main()
