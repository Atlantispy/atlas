"""Small-block freshness for shared heat IDs from a real sealed tiny mesh."""
from concurrent.futures import CancelledError
from contextlib import ExitStack
from pathlib import Path
import threading
import traceback
import unittest
from unittest.mock import patch
from types import SimpleNamespace

import test_segment_store as base_fixture
from compact_contracts import ContractError
from compact_store import CompactMeshStoreV3
from heat_ledger_tables import _MeshIds, LEDGER_SCHEMA
from heat_cold_patch import _LedgerArray
from record_tables import RecordCodec, canonical
from test_mesh_v3 import fixture


class Step7BMeshStreamTests(unittest.TestCase):
    def setUp(self):
        base_fixture.SegmentStoreTests.setUp(self)
        old, _, self.source, self.partition, _ = fixture(self.scope, self.candidate, count=1)
        adapter = CompactMeshStoreV3(self.candidate, scope=self.scope, support_source=self.source)
        ref = adapter.publish(old, producer='b' * 64)
        sealed = self.candidate.seal(ref)
        self.stores.promote(sealed, expected_catalog_digest=sealed.expected_catalog_digest)
        self.mesh = CompactMeshStoreV3(self.stores, scope=self.scope,
            support_source=self.source).open(ref, expected_geometry_id=old.geometry_id)
        self.template = RecordCodec().pack_record(['0' * 64], record_schema=LEDGER_SCHEMA,
            scope=self.scope, check=lambda: None)
        self.ids = _MeshIds(self.mesh, 'face', self.template)

    def tearDown(self):
        for owner in (self.ids, self.template, self.mesh, self.source, self.partition):
            if owner is not None:
                owner.close()
        base_fixture.SegmentStoreTests.tearDown(self)

    def test_exact_custom_ids_and_scalar_bytes_with_batch_exited_before_yield(self):
        expected = canonical([self.mesh.face_id(i) for i in range(self.mesh.face_count)])
        result = bytearray()
        with self.ids.iter_json(max_chunk_bytes=7) as stream:
            for block in stream:
                with block:
                    self.assertLessEqual(len(block.value), 7)
                    self.assertEqual(self.mesh._segment._read_depth, 0)
                    result.extend(block.value)
        self.assertEqual(bytes(result), expected)
        result.clear()
        with self.ids.at(0) as scalar, scalar.iter_json(max_chunk_bytes=7) as stream:
            for block in stream:
                with block:
                    result.extend(block.value)
        self.assertEqual(bytes(result), canonical(self.mesh.face_id(0)))

    def test_cold_ledger_scalar_detaches_before_row_and_source_close(self):
        expected = [self.mesh.face_id(i) for i in range(self.mesh.face_count)]
        with ExitStack() as stack:
            column = _LedgerArray(self.ids, stack, SimpleNamespace(check=lambda cancel: None), None)
            self.assertEqual(column, expected)
            escaped = column[0]
        self.ids.close(); self.ids = None
        self.template.close(); self.template = None
        self.mesh.close(); self.mesh = None
        self.assertEqual(escaped.value, expected[0])
        self.assertGreater(self.scope.stats().purpose_bytes.get('retained:heat-mesh-id-scalar', 0), 0)
        del escaped, column
        self.assertEqual(self.scope.stats().purpose_bytes.get('retained:heat-mesh-id-scalar', 0), 0)

    def test_changed_file_and_cancellation_between_buffered_blocks_refuse(self):
        stream = self.ids.iter_json(max_chunk_bytes=7)
        next(stream).close()
        sidecar = Path(str(self.path / self.stores.head.filename) + '-journal')
        sidecar.write_bytes(b'synthetic source mutation between buffered ID blocks')
        try:
            with self.assertRaisesRegex(ContractError, 'sidecar'):
                next(stream)
        finally:
            sidecar.unlink()
            stream.close()
        del stream

        stream = self.ids.iter_json(max_chunk_bytes=7)
        next(stream).close()
        event = threading.Event()
        self.mesh._segment.cancel = event
        event.set()
        with self.assertRaises(CancelledError):
            next(stream)
        event.clear()
        stream.close()
        del stream
        self.assertEqual(self.mesh._segment._read_depth, 0)

    def test_escaped_output_remains_paid_after_stream_and_source_view_close(self):
        expected = canonical([self.mesh.face_id(i) for i in range(self.mesh.face_count)])[:7]
        stream = self.ids.iter_json(max_chunk_bytes=7)
        block = next(stream)
        stream.close()
        self.assertEqual(self.scope.stats().purpose_bytes.get('retained:heat-mesh-id-stream', 0), 0)
        self.ids.close()
        self.ids = None
        self.template.close()
        self.template = None
        self.mesh.close()
        self.mesh = None
        self.assertEqual(block.value, expected)
        self.assertGreater(self.scope.stats().purpose_bytes['retained:heat-mesh-id-block'], 0)
        block.close()
        self.assertEqual(self.scope.stats().purpose_bytes.get('retained:heat-mesh-id-block', 0), 0)

    def test_final_freshness_failure_withholds_output_and_retains_its_charge(self):
        original = self.stores.assert_cached_read_safe
        calls = 0

        def freshness(**kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise ContractError('changed during mesh ID block')
            original(**kwargs)

        failure = None
        stream = self.ids.iter_json(max_chunk_bytes=7)
        with patch.object(self.stores, 'assert_cached_read_safe', side_effect=freshness):
            try:
                next(stream)
            except ContractError as exc:
                failure = exc
            else:
                self.fail('mesh ID block escaped its final freshness check')
        self.assertIsNotNone(failure)
        self.assertIn('changed during', str(failure))
        self.assertGreater(self.scope.stats().purpose_bytes['retained:heat-mesh-id-block'], 0)
        stream.close()
        traceback.clear_frames(failure.__traceback__)
        failure.__traceback__ = None
        del failure, stream
        self.assertEqual(self.scope.stats().purpose_bytes.get('retained:heat-mesh-id-block', 0), 0)
        self.assertEqual(self.mesh._segment._read_depth, 0)


if __name__ == '__main__':
    unittest.main()
