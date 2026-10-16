"""Tiny real-store partition DAG controls; no historical DB, checkpoint or simulation."""
from concurrent.futures import CancelledError
from copy import deepcopy
import gc
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
RUNTIME = HERE.parents[1]/'runtime-integration-r1'/'runtime-src'
sys.path[:0] = [str(RUNTIME), str(HERE.parent)]

import mesh_tables as M
import partition_tables as P
import partition_store as PS
import partition_workflow_patch as PW
import test_partition_tables as TP
from atlas_tectonics import integration_differential_geometry as D
from atlas_tectonics.resources import WorkBudget
from atlas_tectonics.storage import ArrayStore, StoreLimits

PRODUCER = {'execution_identity': 'd'*64, 'collar_plan_id': TP.ident('collar'),
            'role': 'synthetic storage fixture; no scientific authority'}


def limits():
    return StoreLimits(chunk_bytes=256, max_array_bytes=2 << 20,
        max_store_bytes=16 << 20, max_manifest_bytes=256 << 10,
        sqlite_cache_bytes=65536, codec_workspace_bytes=65536)


def observed(view):
    return dict(partition_id=view.partition_id, descriptor=PW.descriptor_stats(view),
                support_ids=[view.support_id(i) for i in range(view.support_count)],
                arrays={k: sha256(M._raw_view(v)).hexdigest() for k, v in sorted(view._arrays.items())})


def child(path, reference, expected):
    budget = WorkBudget(128 << 20)
    with ArrayStore(Path(path), limits(), budget=budget) as store:
        adapter = PS.CompactPartitionStore(store, budget=budget)
        before = store.change_token()
        with patch.object(P.CompactPartition, 'legacy_record', side_effect=AssertionError('whole export forbidden')):
            view = adapter.open(json.loads(reference), expected_partition_id=expected)
            result = observed(view)
            del view
        assert store.change_token() == before, 'reopen wrote to the store'
    gc.collect()
    assert budget.reserved_bytes == 0, budget.statistics()
    print(json.dumps(dict(result=result, reserved_after_close=0), sort_keys=True))


def caught(action, kind):
    try:
        action()
    except kind as failure:
        return failure
    raise AssertionError('expected actual failure')


class PartitionStoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='.ps-', dir=HERE.parents[4])
        self.path = Path(self.temporary.name)/'partition.sqlite'
        self.budget = WorkBudget(128 << 20)
        self.store = ArrayStore(self.path, limits(), budget=self.budget)
        self.adapter = PS.CompactPartitionStore(self.store, budget=self.budget)
        self.body, self.supports = TP.tiny_partition(self.budget)
        self.view, metadata, arrays = TP.opened(self.body, self.supports, self.budget)
        self.metadata = deepcopy(metadata)
        del metadata, arrays

    def tearDown(self):
        self.view = None
        self.store.close()
        gc.collect()
        self.assertEqual(self.budget.reserved_bytes, 0)
        self.temporary.cleanup()

    def forged(self, ref, producer, change):
        """Same-store root at the producer key whose codec row or column differs."""
        codec, arrays = deepcopy(self.metadata), {n: self.store.reference(ref['snapshot_key'], n)
                                                  for n in ref['array_bindings']}
        change(codec, arrays)
        key = PS.key_for(self.view.partition_id, producer)
        self.store.put(key, arrays, dict(PS.binding(self.view.partition_id, producer),
                       codec_metadata=codec, authority=PS.AUTHORITY), budget=self.budget)
        return self.adapter.reference(key, expected_partition_id=self.view.partition_id, source_producer=producer)

    def test_publish_open_roundtrip_exact_ids_order_no_legacy_export(self):
        pid = self.view.partition_id
        legacy = D._encoded(dict(partition_id=pid, **self.body, supports=self.supports))
        with patch.object(P.CompactPartition, 'legacy_record', side_effect=AssertionError('whole export forbidden')):
            ref = self.adapter.publish(self.view, source_producer=PRODUCER)
            self.assertEqual(set(ref), PS.REFERENCE_KEYS)
            row = self.store.metadata(ref['snapshot_key'])
            self.assertEqual(set(row), {'schema', 'partition_id', 'source_producer', 'codec_metadata', 'authority'})
            self.assertEqual((row['partition_id'], row['source_producer'], row['authority']), (pid, PRODUCER, PS.AUTHORITY))
            opened = self.adapter.open(ref, expected_partition_id=pid)
            self.assertIsNot(opened, self.view)
            self.assertEqual(opened.partition_id, pid)
            self.assertEqual([opened.support_id(i) for i in range(opened.support_count)], self.body['support_ids'])
            self.assertEqual(set(opened._arrays), set(self.view._arrays))
            for name, array in self.view._arrays.items():
                self.assertEqual((opened._arrays[name].dtype, opened._arrays[name].shape), (array.dtype, array.shape))
                self.assertEqual(bytes(M._raw_view(opened._arrays[name])), bytes(M._raw_view(array)), name)
                self.assertFalse(opened._arrays[name].flags.writeable)
            self.assertEqual(b''.join(PW.iter_descriptor_json(opened)), legacy)
            self.assertEqual(PW.descriptor_stats(opened), {'sha256': sha256(legacy).hexdigest(), 'nbytes': len(legacy)})
            for i, record in enumerate(self.supports):
                self.assertEqual(b''.join(opened.iter_legacy_json(opened.support(i))), D._encoded(record))
            del opened

    def test_republish_is_idempotent_and_shares_chunks(self):
        first = self.adapter.publish(self.view, source_producer=PRODUCER)
        token, before = self.store.change_token(), self.store.statistics()
        with patch.object(self.store, 'put', side_effect=AssertionError('existing root must not be restaged')):
            again = self.adapter.publish(self.view, source_producer=PRODUCER)
        self.assertEqual(again, first)
        self.assertEqual(self.store.change_token(), token)
        self.assertIsNone(self.adapter.find(self.view.partition_id, dict(PRODUCER, role='other')))
        second = self.adapter.publish(self.view, source_producer=dict(PRODUCER, role='other'))
        after = self.store.statistics()
        self.assertNotEqual(second['snapshot_key'], first['snapshot_key'])
        self.assertEqual(second['array_bindings'], first['array_bindings'])
        self.assertEqual((after['unique_chunks'], after['encoded_payload_bytes']),
                         (before['unique_chunks'], before['encoded_payload_bytes']))
        self.assertEqual(after['snapshots'], before['snapshots']+1)
        self.assertEqual(self.store.metadata(first['snapshot_key'])['source_producer'], PRODUCER)

    def test_reference_and_root_tamper_refused(self):
        pid = self.view.partition_id
        ref = self.adapter.publish(self.view, source_producer=PRODUCER)
        name = sorted(ref['array_bindings'])[0]
        # Bindings are ArrayReference descriptor digests of the root's exact
        # dtype/shape/chunk descriptions; a forged digest or a copied old-style
        # description both differ from the current reference.
        with self.store._read_scope():
            stored = self.store._manifest(ref['snapshot_key'])['arrays']
        self.assertEqual(ref['array_bindings'], {n: self.store.reference(ref['snapshot_key'], n).descriptor_sha256
                                                 for n in stored})
        wrong = [dict(ref, source_producer=dict(PRODUCER, role='changed')), dict(ref, snapshot_key='e'*64),
                 dict(ref, array_bindings=dict(ref['array_bindings'], **{name: 'f'*64})),
                 dict(ref, array_bindings=dict(ref['array_bindings'], **{name: stored[name]})),
                 dict(ref, schema='atlas.other'), {k: v for k, v in ref.items() if k != 'array_bindings'}]
        for changed in wrong:
            with self.assertRaises(PS.CompactPartitionStoreRefused):
                self.adapter.verify_reference(changed, expected_partition_id=pid)
            with self.assertRaises(PS.CompactPartitionStoreRefused):
                self.adapter.open(changed, expected_partition_id=pid)
        with self.assertRaises(PS.CompactPartitionStoreRefused):
            self.adapter.verify_reference(ref, expected_partition_id='0'*64)
        with self.assertRaises(PS.CompactPartitionStoreRefused):
            self.adapter.open(ref, expected_partition_id='0'*64)
        with self.assertRaises(PS.CompactPartitionStoreRefused):
            PS.key_for('not-a-sha', PRODUCER)
        # Forged roots at their own producer keys: a codec row naming another
        # body node, a consistently rehashed changed column, and a stale digest.
        body_node = self.forged(ref, dict(PRODUCER, role='forged body'),
            lambda codec, arrays: codec.__setitem__('body_node', codec['body_node']-1))
        with self.assertRaises(P.PartitionTablesRefused):
            self.adapter.open(body_node, expected_partition_id=pid)
        def column(codec, arrays, rehash=True):
            values = self.view._arrays['float.value'].copy()
            values[0] = 1.0
            arrays['float.value'] = values
            if rehash:
                codec['arrays']['float.value']['sha256'] = sha256(values.tobytes()).hexdigest()
        rehashed = self.forged(ref, dict(PRODUCER, role='forged column'), column)
        with self.assertRaisesRegex(P.PartitionTablesRefused, 'hash differs'):
            self.adapter.open(rehashed, expected_partition_id=pid)
        stale = self.forged(ref, dict(PRODUCER, role='stale digest'), lambda c, a: column(c, a, rehash=False))
        with self.assertRaisesRegex(PS.CompactPartitionStoreRefused, 'column bytes differ'):
            self.adapter.open(stale, expected_partition_id=pid)
        self.assertEqual(self.adapter.open(ref, expected_partition_id=pid).partition_id, pid)

    def test_cancel_and_publication_check_leave_no_root_or_lease(self):
        before, baseline = self.store.statistics(), self.budget.reserved_bytes
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(CancelledError):
            self.adapter.publish(self.view, source_producer=PRODUCER, cancel=cancel)
        cancel.clear()
        with self.assertRaises(CancelledError):
            self.adapter.publish(self.view, source_producer=PRODUCER, cancel=cancel, publication_check=cancel.set)
        def interrupted():
            raise CancelledError('interrupt at final atomic publication')
        with self.assertRaisesRegex(CancelledError, 'final atomic'):
            self.adapter.publish(self.view, source_producer=PRODUCER, publication_check=interrupted)
        with self.assertRaisesRegex(PS.CompactPartitionStoreRefused, 'callable'):
            self.adapter.publish(self.view, source_producer=PRODUCER, publication_check='not callable')
        self.store._historical_readonly = object()
        try:
            with self.assertRaisesRegex(PS.CompactPartitionStoreRefused, 'authenticated original'):
                self.adapter.publish(self.view, source_producer=PRODUCER)
        finally:
            del self.store._historical_readonly
        other = WorkBudget(128 << 20)
        with self.assertRaises(PS.CompactPartitionStoreRefused):
            PS.CompactPartitionStore(self.store, budget=other)
        foreign = TP.opened(self.body, self.supports, other)[0]
        with self.assertRaises(PS.CompactPartitionStoreRefused):
            self.adapter.publish(foreign, source_producer=PRODUCER)
        del foreign
        gc.collect()
        self.assertEqual(other.reserved_bytes, 0)
        after = self.store.statistics()
        for name in ('snapshots', 'unique_chunks', 'encoded_payload_bytes'):
            self.assertEqual(before[name], after[name], name)
        self.assertIsNone(self.adapter.find(self.view.partition_id, PRODUCER))
        gc.collect()
        self.assertEqual(self.budget.reserved_bytes, baseline)

    def test_open_validates_outside_store_lock_and_held_error_is_funded(self):
        pid = self.view.partition_id
        ref = self.adapter.publish(self.view, source_producer=PRODUCER)
        original, seen = PS.CompactPartition, []
        def outside(*args, **kwargs):
            free = []
            def probe():
                acquired = self.store._lock.acquire(blocking=False)
                if acquired:
                    self.store._lock.release()
                free.append(acquired)
            worker = threading.Thread(target=probe)
            worker.start(); worker.join()
            seen.append((self.store._db.in_transaction, free[0]))
            return original(*args, **kwargs)
        with patch.object(PS, 'CompactPartition', outside):
            view = self.adapter.open(ref, expected_partition_id=pid)
        self.assertEqual(seen, [(False, True)])
        self.assertIs(type(view), P.CompactPartition)
        del view
        forged = self.forged(ref, dict(PRODUCER, role='held failure'),
                             lambda codec, arrays: codec.__setitem__('body_node', codec['body_node']-1))
        gc.collect()
        baseline = self.budget.reserved_bytes
        failure = caught(lambda: self.adapter.open(forged, expected_partition_id=pid), P.PartitionTablesRefused)
        held = failure.__traceback__
        failure.__traceback__ = None
        del failure
        gc.collect()
        total = sum(a.nbytes for a in self.view._arrays.values())
        self.assertGreaterEqual(self.budget.statistics()['categories']['partition-store-arrays'], total)
        self.assertGreater(self.budget.reserved_bytes, baseline)
        del held
        gc.collect()
        self.assertEqual(self.budget.reserved_bytes, baseline)

    def test_independent_process_reopen(self):
        ref = self.adapter.publish(self.view, source_producer=PRODUCER)
        expected = observed(self.view)
        self.store.close()
        completed = subprocess.run([sys.executable, '-B', str(Path(__file__).resolve()), '--child', str(self.path),
            json.dumps(ref, sort_keys=True), self.view.partition_id], capture_output=True, text=True, timeout=120)
        self.assertEqual(completed.returncode, 0, completed.stdout+completed.stderr)
        data = json.loads(completed.stdout)
        self.assertEqual(data['result'], json.loads(json.dumps(expected)))
        self.assertEqual(data['reserved_after_close'], 0)
        self.store = ArrayStore(self.path, limits(), budget=self.budget)


if __name__ == '__main__':
    if len(sys.argv) == 5 and sys.argv[1] == '--child':
        child(*sys.argv[2:])
    else:
        unittest.main(verbosity=2)
