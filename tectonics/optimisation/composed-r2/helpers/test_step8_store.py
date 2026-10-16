"""Bounded synthetic Step 8 facade fixtures; no historical migration or IV2."""
import gc
from hashlib import sha256
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
COMPACT = HERE / 'compact-geometry-r1'
RUNTIME = HERE.parent / 'runtime-integration-r1' / 'runtime-src'
sys.path[:0] = [str(COMPACT), str(RUNTIME), str(HERE)]

import numpy as np
from atlas_tectonics.resources import WorkBudget
from atlas_tectonics.storage import ArrayStore, StoreConflict, StoreError
from compact_contracts import ContractError
from content_cache import create_retained_scope
from compact_restart_store import CompactRestartStore
from interval_store_set import LIMITS
from segment_store import SegmentBackend


def key(text):
    return sha256(text.encode()).hexdigest()


class Step8StoreTests(unittest.TestCase):
    def setUp(self):
        temporary_root = HERE.parents[3] / '_t'
        temporary_root.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='step8-facade-', dir=temporary_root)
        self.root = Path(self.temp.name)
        self.assertTrue(self.root.resolve().is_relative_to(temporary_root.resolve()))
        self.budget = WorkBudget(768 << 20)
        self.scope = create_retained_scope(self.budget, process_epoch='step8-store-tests')
        self.store = CompactRestartStore.create_migration(self.root / 'catalog.json',
            workflow_id=key('workflow'), scope=self.scope, producer_identity=key('producer'),
            runtime_identity=key('runtime'))
        self.others = []

    def tearDown(self):
        for store in self.others:
            store.close()
        self.store.close()
        gc.collect()
        self.scope.close()
        self.assertEqual(self.budget.reserved_bytes, 0)
        for path in self.root.iterdir():
            if path.is_file():
                os.chmod(path, stat.S_IREAD | stat.S_IWRITE)
        self.temp.cleanup()

    def test_native_manifest_reference_and_output_lifetime(self):
        arrays = {'empty': np.empty((0, 3), dtype='<f8'),
                  'values': np.arange(20000, dtype='>i4')[::2]}
        invocation = key('first')
        metadata = {'schema': 'fixture.native.v1', 'literal': ['x', 1, False]}
        self.store.put(invocation, arrays, metadata)
        with ArrayStore(self.root / 'native.sqlite', LIMITS, budget=self.budget) as native:
            native.put(invocation, arrays, metadata)
            with native._read_scope():
                expected = native._manifest(invocation)
            self.assertEqual(self.store._manifest(invocation), expected)
            self.assertEqual(self.store.reference(invocation, 'values').descriptor_sha256,
                             native.reference(invocation, 'values').descriptor_sha256)
        before = self.scope.stats().retained_bytes
        result = self.store.get(invocation)
        self.assertGreater(self.scope.stats().retained_bytes, before)
        np.testing.assert_array_equal(result['values'], arrays['values'])
        self.assertFalse(result['values'].flags.writeable)
        self.assertEqual(result['empty'].shape, (0, 3))
        del result
        gc.collect()
        self.assertEqual(self.scope.stats().retained_bytes, before)

    def test_reference_incremental_and_immutable_conflict(self):
        first, second, third = key('first'), key('second'), key('third')
        original = np.arange(20000, dtype='<i8')
        self.store.put(first, {'a': original}, {'sequence': 0})
        self.store.put(second, {'a': self.store.reference(first, 'a')}, {'sequence': 1})
        self.assertEqual(self.store._manifest(first)['arrays'], self.store._manifest(second)['arrays'])
        replacement = np.full((8192,), -7, dtype='<i8')
        self.store.put_incremental(third, second, {'a': {1: replacement}}, {'sequence': 2})
        result = self.store.get(third)
        expected = original.copy()
        expected[8192:16384] = replacement
        np.testing.assert_array_equal(result['a'], expected)
        del result
        before = self.store.candidate.local_statistics()
        with self.assertRaises(StoreConflict):
            self.store.put(first, {'a': np.zeros_like(original)}, {'sequence': 0})
        self.assertEqual(before, self.store.candidate.local_statistics())
        self.store.put(first, {'a': original}, {'sequence': 0})
        self.assertEqual(set(self.store.snapshot_keys()), {first, second, third})

    def test_publication_check_rollback_and_metadata_bound(self):
        invocation = key('rolled-back')
        before = self.store.candidate.local_statistics()
        def check():
            self.assertTrue(self.store.in_publication)
            self.assertEqual(self.store.metadata(invocation), {'x': 3})
            raise RuntimeError('fixture refusal')
        with self.assertRaisesRegex(RuntimeError, 'fixture refusal'):
            self.store.put(invocation, {'a': np.arange(40)}, {'x': 3}, publication_check=check)
        self.assertFalse(self.store.in_publication)
        self.assertFalse(self.store.contains(invocation))
        self.assertEqual(before, self.store.candidate.local_statistics())
        with self.assertRaisesRegex(StoreError, 'compact record references'):
            self.store.put(key('large-meta'), {'a': np.zeros(1)}, {'raw': 'x' * (64 << 10)})
        self.assertEqual(before, self.store.candidate.local_statistics())
        self.store.put(invocation, {'a': np.arange(40)}, {'x': 3})

    def test_two_intervals_and_fresh_process_read_only(self):
        first, second = key('first'), key('second')
        values = np.arange(18000, dtype='<i8')
        self.store.put(first, {'values': values}, {'sequence': 0})
        entry = self.store.seal_and_promote(first)
        original_path = self.root / entry.filename
        original_hash = sha256(original_path.read_bytes()).hexdigest()
        self.assertTrue(self.store.readonly)
        with self.assertRaises(ContractError):
            self.store.put(key('denied'), {'a': values})
        successor = self.store.begin_interval(producer_identity=key('producer2'), runtime_identity=key('runtime'))
        self.others.append(successor)
        successor.put(second, {'values': successor.reference(first, 'values')}, {'sequence': 1})
        self.assertEqual(successor.candidate.local_statistics()['local_chunks'], 0)
        successor.seal_and_promote(second)
        self.assertEqual(sha256(original_path.read_bytes()).hexdigest(), original_hash)
        self.assertEqual(set(successor.snapshot_keys()), {first, second})
        script = '''
import gc, json, sys
from pathlib import Path
sys.path[:0] = sys.argv[2:5]
from atlas_tectonics.resources import WorkBudget
from content_cache import create_retained_scope
from compact_restart_store import CompactRestartStore
budget = WorkBudget(512 << 20)
scope = create_retained_scope(budget, process_epoch='step8-cold-reader')
with CompactRestartStore.open_catalog(sys.argv[1], scope=scope) as store:
    token = store.change_token()
    assert store.readonly and store._historical_readonly
    assert not hasattr(store, 'interval')
    for expected, name in enumerate(sys.argv[5:7]):
        assert store.metadata(name) == {'sequence': expected}
        arrays = store.get(name)
        assert len(arrays['values']) == 18000 and int(arrays['values'][-1]) == 17999
        del arrays
    assert token == store.change_token()
    stats = store.statistics()
    assert stats['snapshots'] == 2
    assert stats['compact_references_verified']['payloads_verified'] is False
gc.collect()
scope.close()
assert budget.reserved_bytes == 0
print(json.dumps({'status': 'PASS', 'intervals': 2, 'final_reserved_bytes': budget.reserved_bytes}))
'''
        result = subprocess.run([sys.executable, '-B', '-c', script, str(self.root / 'catalog.json'),
            str(COMPACT), str(RUNTIME), str(HERE), first, second], capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)['status'], 'PASS')

    def test_stable_facade_retains_candidate_view_across_interval_boundary(self):
        first, second = key('retained-first'), key('retained-second')
        self.store.put(first, {'a': np.arange(12, dtype='<i8')}, {'sequence': 0})
        view = SegmentBackend().open(self.store, self.store._alias(first), scope=self.scope)
        try:
            self.assertIsNone(view.cache_identity())
            self.store.seal_and_promote(first)
            with self.store._read_scope():
                with self.assertRaisesRegex(ContractError, 'quiescent'):
                    self.store.start_next_interval(producer_identity=key('p2'), runtime_identity=key('runtime'))
            self.assertIs(self.store.start_next_interval(producer_identity=key('p2'),
                                                        runtime_identity=key('runtime')), self.store)
            with view.read('a', 3, 6, max_owned_bytes=24) as held:
                self.assertEqual(np.frombuffer(held.value, dtype='<i8').tolist(), [3, 4, 5])
            self.store.put(second, {'a': self.store.reference(first, 'a')}, {'sequence': 1})
            self.store.seal_and_promote(second)
            self.assertEqual(self.store.statistics()['last_sealed_candidate']['interval'], 1)
        finally:
            view.close()


if __name__ == '__main__':
    unittest.main()
