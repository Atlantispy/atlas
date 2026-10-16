"""Fresh native type/admission boundary for the segmented partition adapter."""
import gc
from pathlib import Path
import tempfile
import sys
import unittest
from unittest.mock import patch

import test_partition_native_patch as F

def setUpModule():
    F.setUpModule()
    sys.path.insert(0, str(F.HERE.parent))


tearDownModule = F.tearDownModule


class NativePartitionV2Tests(unittest.TestCase):
    def test_fresh_native_payload_is_segment_reference_only(self):
        from content_cache import create_retained_scope
        from compact_contracts import SegmentRef
        from interval_store_set import IntervalStoreSet
        import partition_workflow_patch as W
        budget = F.T.WorkBudget(1 << 30)
        scope = create_retained_scope(budget, process_epoch='wp4-native-payload')
        body, rows = F.T.tiny_partition(budget)
        operands = F.source_operands(body, budget)
        native = F.D.DifferentialPartition.restore(dict(body, supports=rows,
            partition_id=F.D._record_hash(body)), *operands, budget=budget)
        with tempfile.TemporaryDirectory(prefix='wp4-payload-', dir=F.HERE.parents[4]/'_t') as directory:
            stores = IntervalStoreSet.create_migration(str(Path(directory)/'catalog.json'),
                workflow_id='a'*64, scope=scope)
            candidate = stores.begin_interval(None, producer_identity='b'*64, runtime_identity='c'*64)
            with W.payload(None, native, operands[2], operands[0], operands[1], budget,
                    store=candidate, source_producer={'fixture': 'actual native payload adapter'}) as (header, arrays):
                self.assertEqual(arrays, {})
                self.assertEqual(header['record_blobs'], {})
                self.assertEqual(header['partition_id'], native.partition_id)
                ref = SegmentRef.from_wire(header['compact_partition'])
                self.assertEqual(ref.identity.canonical_bytes, len(F.D._encoded(native.descriptor())))
            del header, arrays, ref
            candidate.close(); stores.close()
        del native, operands
        gc.collect(); scope.close()
        self.assertEqual(budget.reserved_bytes, 0)

    def test_native_issued_support_header_and_borrow_lifetime(self):
        from content_cache import create_retained_scope
        import partition_tables as P
        import partition_native_patch as N
        from record_views import RecordRef
        budget = F.T.WorkBudget(1 << 30)
        scope = create_retained_scope(budget, process_epoch='wp4-native-v2')
        body, rows = F.T.tiny_partition(budget)
        operands = F.source_operands(body, budget)
        view = P.pack_partition_v2(body, iter(rows), expected_partition_id=F.D._record_hash(body), scope=scope)
        native = F.D.DifferentialPartition.from_compact(view, *operands, budget=budget)
        self.assertEqual(native.partition_id, F.D._record_hash(body))
        with self.assertRaises(F.D.V.VolumeError):
            native.record()
        with self.assertRaises(RuntimeError):
            view.close()
        root_index = view.record._root
        original = RecordRef.export
        def bounded_only(ref, **kwargs):
            self.assertNotEqual(ref.index, root_index, 'whole descriptor export forbidden')
            return original(ref, **kwargs)
        with patch.object(RecordRef, 'export', bounded_only):
            header = N.partition_fields(native, ('funding_id', 'source', 'end_time_s'))
            self.assertEqual(header.value, {k: body[k] for k in ('funding_id', 'source', 'end_time_s')})
            del header
            support = native.supports[1]
            self.assertEqual(support.support_id, F.D._record_hash(rows[1]))
            self.assertIsInstance(support._compact_ref, RecordRef)
            with N.owned_support_record(support) as owned:
                self.assertEqual(owned.value, rows[1])
        escaped = native.supports
        del native
        gc.collect()
        with self.assertRaises(RuntimeError):
            view.close()
        del support, escaped
        gc.collect()
        view.close()
        del operands
        gc.collect(); scope.close()
        self.assertEqual(budget.reserved_bytes, 0)


if __name__ == '__main__':
    unittest.main()
