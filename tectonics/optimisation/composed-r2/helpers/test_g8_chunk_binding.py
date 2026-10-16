"""G8: order-independent (chunk id, stored checksum) binding kept by the candidate.

Synthetic data only, real native SQLite candidates under the tree's _t folder.
"""
import gc
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
RUNTIME = HERE.parents[1] / 'runtime-integration-r1' / 'runtime-src'
sys.path[:0] = [str(HERE), str(RUNTIME), str(HERE.parent)]
TEMP = HERE.parents[4] / '_t'

import interval_store_set as I
from compact_contracts import ContractError
from interval_catalog import canonical, digest
from interval_store_set import IntervalStoreSet
from test_interval_store_set import WORKFLOW, add_interval, finish, scope

FORMER_KEYS = {'encodes', 'local_chunks', 'manifests', 'manifest_bytes',
               'encoded_payload_bytes', 'retained_record_bytes', 'state'}


def descriptor(raw):
    return canonical({'dtype': '|u1', 'count': len(raw)})


class ChunkBindingTests(unittest.TestCase):
    def setUp(self):
        TEMP.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='g8-', dir=TEMP)
        self.root = Path(self.temp.name)
        self.sc = scope()
        self.sets = []

    def tearDown(self):
        for stores in self.sets:
            stores.close()
        gc.collect()
        self.sc.close()
        for path in self.root.rglob('*'):
            if path.is_file():
                os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
        self.temp.cleanup()

    def candidate(self, name):
        directory = self.root / name
        directory.mkdir()
        stores = IntervalStoreSet.create_migration(str(directory / 'catalog.json'),
                                                  workflow_id=WORKFLOW, scope=self.sc)
        self.sets.append(stores)
        return stores, stores.begin_interval(None, producer_identity='b' * 64, runtime_identity='c' * 64)

    def test_accumulator_equals_recomputation_in_any_put_order(self):
        values = [b'alpha', b'bravo', b'charlie-delta', bytes(range(200))]
        _, first = self.candidate('forward')
        _, second = self.candidate('reverse')
        for raw in values:
            first.put_chunk(descriptor(raw), raw)
        for raw in reversed(values):
            second.put_chunk(descriptor(raw), raw)
        self.assertEqual(first.local_chunk_binding_digest(), second.local_chunk_binding_digest())
        self.assertEqual(first.local_chunk_binding_digest(), first.recompute_local_chunk_binding_digest())
        self.assertEqual(second.local_chunk_binding_digest(), second.recompute_local_chunk_binding_digest())
        self.assertTrue(first.local_chunk_binding_digest().startswith(I.CHUNK_BINDING_SCHEMA + ':4:'))
        _, empty = self.candidate('empty')
        self.assertEqual(empty.local_chunk_binding_digest(), I.chunk_binding_digest(0, 0))
        self.assertEqual(empty.recompute_local_chunk_binding_digest(), I.chunk_binding_digest(0, 0))

    def test_swap_of_codec_stored_sha_and_payload_between_same_descriptor_rows_is_detected(self):
        _, candidate = self.candidate('swap')
        a, b = b'aaaaaaaa-one', b'bbbbbbbb-two'
        self.assertEqual(descriptor(a), descriptor(b))
        _, key_a = candidate.put_chunk(descriptor(a), a)
        _, key_b = candidate.put_chunk(descriptor(b), b)
        written = candidate.local_chunk_binding_digest()
        counters = candidate.local_statistics()
        rows = {cid: (codec, stored, payload) for cid, codec, stored, payload in
                candidate._db.execute('SELECT id,codec,stored_sha,payload FROM chunks')}
        for target, source in ((key_a, key_b), (key_b, key_a)):
            candidate._db.execute('UPDATE chunks SET codec=?,stored_sha=?,payload=? WHERE id=?',
                                  (*rows[source], target))
        # Every row still passes read-and-hash, and the counters still match:
        # the per-row checks alone cannot see this swap without a decode.
        for desc, codec, stored, payload in candidate._db.execute(
                'SELECT descriptor,codec,stored_sha,payload FROM chunks'):
            self.assertEqual(digest(desc + b'\0' + codec.encode() + b'\0' + payload), stored)
        self.assertEqual(candidate.local_statistics(), counters)
        # The writer's binding is unchanged; the recomputation detects the swap.
        self.assertEqual(candidate.local_chunk_binding_digest(), written)
        self.assertNotEqual(candidate.recompute_local_chunk_binding_digest(), written)
        # Only a decode found it before G8.
        with self.assertRaisesRegex(ContractError, 'typed chunk checksum mismatch'), \
                candidate.resolve_chunk(candidate.interval, key_a, descriptor(a)):
            pass
        # Swapping back restores agreement.
        for target in (key_a, key_b):
            candidate._db.execute('UPDATE chunks SET codec=?,stored_sha=?,payload=? WHERE id=?',
                                  (*rows[target], target))
        self.assertEqual(candidate.recompute_local_chunk_binding_digest(), written)

    def test_savepoint_rollback_with_restored_statistics_restores_binding(self):
        _, candidate = self.candidate('rollback')
        candidate.put_chunk(descriptor(b'kept'), b'kept')
        kept = candidate.local_chunk_binding_digest()
        # The compact_restart_store put path: copy _stats, SAVEPOINT, roll back
        # to it on failure and restore the copied statistics.
        before = dict(candidate._stats)
        candidate._db.execute('SAVEPOINT g8_put')
        candidate.put_chunk(descriptor(b'rolled back'), b'rolled back')
        self.assertNotEqual(candidate.local_chunk_binding_digest(), kept)
        self.assertEqual(candidate.local_chunk_binding_digest(), candidate.recompute_local_chunk_binding_digest())
        candidate._db.execute('ROLLBACK TO g8_put')
        candidate._db.execute('RELEASE g8_put')
        candidate._stats = before
        self.assertEqual(candidate.local_chunk_binding_digest(), kept)
        self.assertEqual(candidate.recompute_local_chunk_binding_digest(), kept)
        # The same put afterwards gives the same binding as without the rollback.
        candidate.put_chunk(descriptor(b'rolled back'), b'rolled back')
        self.assertEqual(candidate.local_chunk_binding_digest(), candidate.recompute_local_chunk_binding_digest())

    def test_reused_and_ancestor_chunks_add_no_term(self):
        directory = self.root / 'chain'
        directory.mkdir()
        stores = IntervalStoreSet.create_migration(str(directory / 'catalog.json'),
                                                  workflow_id=WORKFLOW, scope=self.sc)
        self.sets.append(stores)
        shared = b'shared' * 40
        candidate, ref, _ = add_interval(stores, [shared])
        once = candidate.local_chunk_binding_digest()
        candidate.put_chunk(descriptor(shared), shared)
        self.assertEqual(candidate.local_chunk_binding_digest(), once)
        finish(stores, candidate, ref)
        successor, _, chunks = add_interval(stores, [b'fresh'], share=(shared,))
        self.assertEqual([row['owner'] for row in chunks], [0, 1])
        self.assertTrue(successor.local_chunk_binding_digest().startswith(I.CHUNK_BINDING_SCHEMA + ':1:'))
        self.assertEqual(successor.local_chunk_binding_digest(), successor.recompute_local_chunk_binding_digest())
        successor.close()

    def test_statistics_keep_their_former_keys(self):
        _, candidate = self.candidate('keys')
        candidate.put_chunk(descriptor(b'x'), b'x')
        self.assertEqual(set(candidate.local_statistics()), FORMER_KEYS)
        self.assertEqual(candidate.local_statistics()['local_chunks'], 1)

    def test_malformed_stored_checksum_refuses_recomputation(self):
        _, candidate = self.candidate('malformed')
        _, key = candidate.put_chunk(descriptor(b'y'), b'y')
        candidate._db.execute('UPDATE chunks SET stored_sha=? WHERE id=?', ('Z' * 64, key))
        with self.assertRaisesRegex(ContractError, 'stored chunk checksum'):
            candidate.recompute_local_chunk_binding_digest()
        with self.assertRaises(ContractError):
            I.chunk_binding_digest(-1, 0)


if __name__ == '__main__':
    unittest.main()
