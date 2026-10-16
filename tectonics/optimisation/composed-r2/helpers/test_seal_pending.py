"""Step 9(a) runner seal: the head is durably recorded first, nothing is promoted."""
import gc
import json
import os
import stat
import sys
import tempfile
import unittest
from hashlib import sha256
from pathlib import Path

HERE = Path(__file__).resolve().parent
COMPACT = HERE / 'compact-geometry-r1'
RUNTIME = HERE.parent / 'runtime-integration-r1' / 'runtime-src'
sys.path[:0] = [str(COMPACT), str(RUNTIME), str(HERE)]

import numpy as np
from atlas_tectonics.resources import WorkBudget
from compact_contracts import ContractError
from compact_restart_store import CompactRestartStore
from content_cache import create_retained_scope
from interval_store_set import IntervalStoreSet


def key(text):
    return sha256(text.encode()).hexdigest()


class SealPendingTests(unittest.TestCase):
    def setUp(self):
        temporary_root = HERE.parents[3] / '_t'
        temporary_root.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='seal-pending-', dir=temporary_root)
        self.root = Path(self.temp.name)
        self.budget = WorkBudget(512 << 20)
        self.scope = create_retained_scope(self.budget, process_epoch='seal-pending-tests')
        self.catalog = self.root / 'catalog.json'
        self.store = CompactRestartStore.create_migration(self.catalog, workflow_id=key('workflow'),
            scope=self.scope, producer_identity=key('producer'), runtime_identity=key('runtime'))
        self.head = key('root')
        self.store.put(self.head, {'a': np.arange(4096, dtype='<i8')}, {'kind': 'root', 'sequence': 0})

    def tearDown(self):
        self.store.close()
        gc.collect()
        self.scope.close()
        self.assertEqual(self.budget.reserved_bytes, 0)
        for path in self.root.iterdir():
            if path.is_file():
                os.chmod(path, stat.S_IREAD | stat.S_IWRITE)
        self.temp.cleanup()

    def test_head_recorded_before_seal_and_nothing_promoted(self):
        candidate, recorded = self.store.candidate, []

        def record_head(head):
            # Durable record first: the file is still the live writer here.
            self.assertEqual(candidate._state, 'WRITING')
            path = self.root / 'runner-record.json'
            with path.open('x', encoding='utf8') as stream:
                json.dump({'head': head}, stream)
                stream.flush()
                os.fsync(stream.fileno())
            recorded.append(head)

        before = self.catalog.read_bytes() if self.catalog.exists() else None
        sealed = self.store.seal_pending(self.head, record_head=record_head)
        self.assertEqual(len(recorded), 1)
        self.assertEqual(sealed['entry']['interval'], 0)
        self.assertIsNone(sealed['expected_catalog_digest'])
        self.assertEqual(sealed['entry']['head'], recorded[0])
        self.assertEqual(sealed['entry']['producer_identity'], key('producer'))
        self.assertEqual(sealed['entry']['runtime_identity'], key('runtime'))
        self.assertEqual(candidate._state, 'SEALED')
        # Not promoted: the accepted catalog is unchanged and the facade is read-only.
        self.assertEqual(self.catalog.read_bytes() if self.catalog.exists() else None, before)
        self.assertTrue(self.store.readonly)
        self.assertIsNone(self.store.candidate)
        sealed_file = self.root / sealed['entry']['filename']
        self.assertFalse(os.access(sealed_file, os.W_OK))
        with self.assertRaisesRegex(ContractError, 'no current candidate'):
            self.store.seal_pending(self.head, record_head=recorded.append)

    def test_failed_record_leaves_the_candidate_unsealed(self):
        candidate = self.store.candidate

        def failing(head):
            raise OSError('disk full while recording the head')
        with self.assertRaisesRegex(OSError, 'disk full'):
            self.store.seal_pending(self.head, record_head=failing)
        self.assertEqual(candidate._state, 'WRITING')
        self.assertIs(self.store.candidate, candidate)
        with self.assertRaisesRegex(ContractError, 'durable head record'):
            self.store.seal_pending(self.head, record_head=None)
        self.assertEqual(candidate._state, 'WRITING')

    @unittest.skipUnless(hasattr(IntervalStoreSet, 'open_pending'), 'Step 9(a) storage primitives not merged yet')
    def test_launcher_adopts_only_from_the_recorded_head(self):
        recorded = []
        sealed = self.store.seal_pending(self.head, record_head=recorded.append)
        entry = sealed['entry']
        from compact_contracts import SegmentRef
        head = SegmentRef.from_wire(recorded[0])
        # The pending view is a plain store set: closed explicitly, no context protocol.
        view = IntervalStoreSet.open_pending(self.catalog, entry['filename'], scope=self.scope,
            workflow_id=key('workflow'), expected_catalog_digest=None,
            expected_sha256=entry['file_sha256'], expected_logical_seal=entry['logical_seal'],
            head=head, producer_identity=entry['producer_identity'],
            runtime_identity=entry['runtime_identity'])
        try:
            digest = view.catalog_digest
        finally:
            view.close()
        self.store.close()
        stores = IntervalStoreSet.create_migration(self.catalog, workflow_id=key('workflow'), scope=self.scope)
        try:
            adopted = stores.adopt_and_promote(entry['filename'], expected_sha256=entry['file_sha256'],
                expected_logical_seal=entry['logical_seal'], head=head,
                producer_identity=entry['producer_identity'], runtime_identity=entry['runtime_identity'],
                expected_catalog_digest=None, reader_view_digest=digest)
            self.assertEqual(adopted.to_wire(), entry)
        finally:
            stores.close()


if __name__ == '__main__':
    unittest.main()
