"""Step 5B: bounded cold preparation retains exact admission and refusals."""
from concurrent.futures import CancelledError
import gc
import threading
import unittest
from unittest.mock import patch

import test_mesh_v3 as fixtures
from compact_contracts import ContractError
from compact_store import CompactMeshStoreV3
import mesh_tables as M
from segment_store import SegmentView


class MeshPreparationTests(unittest.TestCase):
    setUp = fixtures.MeshV3Tests.setUp
    tearDown = fixtures.MeshV3Tests.tearDown

    def sealed_fixture(self):
        mesh, record, source, partition, partition_ref = fixtures.fixture(self.scope, self.candidate, count=8)
        ref = CompactMeshStoreV3(self.candidate, scope=self.scope, support_source=source).publish(
            mesh, producer='b'*64)
        sealed = self.candidate.seal(ref)
        self.stores.promote(sealed, expected_catalog_digest=sealed.expected_catalog_digest)
        source.close(); partition.close()
        return ref, partition_ref

    def test_preparation_reuses_pages_and_checks_both_sources_before_return(self):
        ref, partition_ref = self.sealed_fixture()
        state = dict(preparing=False, reads=0, freshness=0)
        original_get = M.SegmentColumn.__getitem__
        original_validate = M.mesh_from_segment
        original_fresh = self.stores.assert_cached_read_safe

        def read(column, key):
            if column.name == 'header.support_ids':
                state['preparing'] = True
            if state['preparing']:
                state['reads'] += 1
            return original_get(column, key)

        def fresh(**kwargs):
            if state['preparing']:
                state['freshness'] += 1
            return original_fresh(**kwargs)

        def validate(*args, **kwargs):
            state['preparing'] = False
            return original_validate(*args, **kwargs)

        with patch.object(M.SegmentColumn, '__getitem__', read), \
                patch.object(M, 'mesh_from_segment', validate), \
                patch.object(self.stores, 'assert_cached_read_safe', fresh):
            opened = CompactMeshStoreV3(self.stores, scope=self.scope).open(
                ref, expected_geometry_id=ref.identity.sha256)
        self.assertGreater(state['reads'], 100)
        self.assertLess(state['freshness'], 20, state)
        self.assertEqual(opened.identity(), ref.identity)
        self.assertEqual(opened._reader.source.binding.partition, partition_ref)
        for columns in (opened._arrays['id.bytes'].columns, opened._reader.source._partition.record._columns):
            self.assertEqual(columns._batch_depth, 0)
            self.assertIsNone(columns._batch_pages)
            self.assertEqual(columns.segment._read_depth, 0)
        opened.close()

    def test_cancel_during_header_preparation_never_reaches_admission(self):
        ref, _ = self.sealed_fixture()
        event = threading.Event()
        original = M.SegmentColumn.__getitem__

        def read(column, key):
            if column.name == 'header.support_ids':
                event.set()
            return original(column, key)

        with patch.object(M.SegmentColumn, '__getitem__', read), \
                patch.object(M, 'mesh_from_segment') as validate:
            with self.assertRaises(CancelledError):
                CompactMeshStoreV3(self.stores, scope=self.scope).open(
                    ref, expected_geometry_id=ref.identity.sha256, cancel=event)
            validate.assert_not_called()
        event.clear()
        gc.collect()

    def test_changed_mesh_or_partition_at_batch_exit_is_refused(self):
        ref, partition_ref = self.sealed_fixture()
        original_validate = M.mesh_from_segment
        original_check = SegmentView.check_unchanged
        for target in (ref, partition_ref):
            with self.subTest(schema=target.identity.record_schema):
                completed = False

                def validate(*args, **kwargs):
                    nonlocal completed
                    result = original_validate(*args, **kwargs)
                    completed = True
                    return result

                def check(segment):
                    if completed and segment.ref == target and segment._read_depth == 0:
                        raise ContractError('source changed at preparation exit')
                    return original_check(segment)

                with patch.object(M, 'mesh_from_segment', validate), \
                        patch.object(SegmentView, 'check_unchanged', check):
                    with self.assertRaisesRegex(ContractError, 'source changed at preparation exit'):
                        CompactMeshStoreV3(self.stores, scope=self.scope).open(
                            ref, expected_geometry_id=ref.identity.sha256)
                self.assertTrue(completed)
                gc.collect()


if __name__ == '__main__':
    unittest.main()
