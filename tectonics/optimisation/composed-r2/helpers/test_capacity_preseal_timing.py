"""Half 2: the capacity harness's opt-in pre-seal timing (coordinator, 16 Oct 2026).

measure_live_capacity --preseal-timing runs bounded_preseal's chunk read-and-hash
and G8 comparison on the capacity candidate just before its seal, with the same
throttle check_candidate uses, and records the time and process samples. Off by
default; the source it runs is pinned at launch; a stored-hash mismatch refuses.
"""
import ast
import gc
import tempfile
import unittest
from pathlib import Path

import measure_live_capacity as CAP
from atlas_tectonics.resources import WorkBudget
from content_cache import create_retained_scope
from interval_store_set import IntervalStoreSet
from record_tables import RecordCodec


class PresealTimingTests(unittest.TestCase):
    def setUp(self):
        # Cleanups run last-registered first, also after a failed setUp.
        temp = tempfile.TemporaryDirectory(prefix='cap-preseal-')
        self.addCleanup(temp.cleanup)
        self.budget = WorkBudget(1 << 30)
        self.addCleanup(lambda: self.assertEqual(self.budget.reserved_bytes, 0, self.budget.statistics()))
        self.scope = create_retained_scope(self.budget, process_epoch='capacity-preseal-timing')
        self.addCleanup(self.scope.close)
        self.addCleanup(gc.collect)
        self.stores = IntervalStoreSet.create_migration(Path(temp.name)/'catalog.json',
                                                        workflow_id='a'*64, scope=self.scope)
        self.addCleanup(self.stores.close)
        self.candidate = self.stores.begin_interval(None, producer_identity='b'*64, runtime_identity='c'*64)
        self.addCleanup(self.candidate.close)
        self.token = CAP.CheckToken(lambda: None)
        # Over several 64 KiB chunks, so the hash pass reads more than one row.
        record = RecordCodec().pack_record({'schema': 'atlas.capacity-preseal-test.v1', 'blob': 'q'*300000,
                                            'values': list(range(4096))},
                                           record_schema='atlas.capacity-preseal-test.v1', scope=self.scope,
                                           check=lambda: None)
        self.addCleanup(record.close)
        CAP.publish_record(self.candidate, record, self.scope, 'd'*64, self.token)

    def test_times_the_bounded_hash_pass_on_the_candidate(self):
        phases = []
        result = CAP.preseal_timing(CAP.preseal_plan(), self.candidate, self.token, phases.append)
        stats = self.candidate.local_statistics()
        self.assertGreater(result['chunks'], 1)
        self.assertEqual((result['chunks'], result['encoded_payload_bytes']),
                         (stats['local_chunks'], stats['encoded_payload_bytes']))
        self.assertEqual(result['chunk_binding'], 'storage-accumulator')
        self.assertGreaterEqual(result['seconds'], 0)
        self.assertEqual(phases, ['preseal-chunk-hash', 'preseal-chunk-hash-done'])
        self.assertEqual(result['sha256'], CAP.file_hash(CAP.PRESEAL))
        self.assertEqual(set(result['process_before']), {'rss_bytes', 'private_bytes', 'os_peak_rss_bytes',
                                                         'available_bytes'})

    def test_a_stored_hash_mismatch_refuses(self):
        import bounded_preseal as P  # R is on sys.path once measure_live_capacity is imported
        cid = self.candidate._db.execute('SELECT id FROM chunks ORDER BY id LIMIT 1').fetchone()[0]
        self.candidate._db.execute("UPDATE chunks SET payload=CAST('tampered' AS BLOB) WHERE id=?", (cid,))
        with self.assertRaisesRegex(P.PresealRefused, 'stored hash mismatch'):
            CAP.preseal_timing(CAP.preseal_plan(), self.candidate, self.token, lambda name: None)

    def test_the_pinned_source_must_be_the_one_run(self):
        with self.assertRaisesRegex(ValueError, 'bounded_preseal changed after launch'):
            CAP.preseal_timing(dict(CAP.preseal_plan(), sha256='0'*64), self.candidate, self.token,
                               lambda name: None)


class OptInTests(unittest.TestCase):
    def test_off_by_default_and_only_just_before_the_seal(self):
        tree = ast.parse(Path(CAP.__file__).read_text(encoding='utf8'))
        workload = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'workload')
        calls = [n for n in ast.walk(workload) if isinstance(n, ast.Call) and
                 getattr(n.func, 'id', None) == 'preseal_timing']
        seals = [n for n in ast.walk(workload) if isinstance(n, ast.Call) and
                 getattr(n.func, 'attr', None) == 'seal']
        self.assertEqual((len(calls), len(seals)), (1, 1))
        guards = [n for n in ast.walk(workload) if isinstance(n, ast.If) and calls[0] in ast.walk(n)]
        self.assertEqual(ast.unparse(guards[-1].test), "plan.get('preseal_timing') is not None")
        self.assertLess(calls[0].lineno, seals[0].lineno)
        self.assertEqual(CAP.preseal_plan()['source'], 'bounded_preseal.py')


if __name__ == '__main__':
    unittest.main()
