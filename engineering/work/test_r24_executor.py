"""Bounded integer DAG checks; no numerical model or whole-world execution."""
from copy import deepcopy
import json
from time import perf_counter
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from work.generator_runtime_r12 import executor as original
from work.generator_runtime_r12.test_executor import Backend, Store, fixture, s
from work.generator_upgrade_r24 import executor


class StreamingBackend:
    """Two slots, with controlled completion order; no threads or science."""
    capacity = 2

    def __init__(self, registry, *, fail=None):
        self.registry = registry
        self.pending = {}
        self.events = []
        self.fail = fail
        self.restored = set()
        self.max_pending = 0

    def submit(self, jobs):
        if len(self.pending) + len(jobs) > self.capacity:
            raise ValueError('backend capacity exceeded')
        for job in jobs:
            ident = job['stage_id']
            if ident in self.pending:
                raise ValueError('duplicate backend submission')
            required = {'c': {'a'}, 'd': {'b', 'c'}}.get(ident, set())
            if not required <= self.restored:
                raise ValueError('dependent submitted before parent restoration')
            self.pending[ident] = job
            self.events.append(('submit', ident))
        self.max_pending = max(self.max_pending, len(self.pending))

    def receive(self):
        ident = next(ident for ident in ('a', 'c', 'b', 'd') if ident in self.pending)
        self.events.append(('receive', ident))
        if ident == self.fail:
            raise RuntimeError('controlled worker failure: ' + ident)
        job = self.pending.pop(ident)
        product = self.registry[job['producer_id']]['run'](
            job['context'], job['inputs'], job['incoming'])
        return {ident: {'product': product, 'artifacts': {ident: {'valid': True}},
                        'diagnostics': {ident: 'synthetic'}}}

    def restore(self, ident, record):
        if record['artifacts'].get(ident) != {'valid': True}:
            raise ValueError('unexpected artifact')
        self.restored.add(ident)
        self.events.append(('restore', ident))
        # Exercise alias isolation from records cached or used downstream.
        record['row']['product']['values']['value'] = 123456
        record['artifacts'].clear()


class ExecutorTests(unittest.TestCase):
    def test_serial_unused_payload_copy_removed_with_exact_result(self):
        recipe, registry, _ = fixture()
        recipe['stages'][0]['inputs']['payload'] = list(range(10000))
        counts, results = [], []
        for module in (original, executor):
            count = []

            def copy(value):
                if type(value) is dict and 'payload' in value:
                    count.append(1)
                return deepcopy(value)

            with patch.object(module, 'deepcopy', copy):
                results.append(module.run(s, recipe, registry))
            counts.append(len(count))
        self.assertEqual(results[0], results[1])
        self.assertEqual(counts, [2, 1])

    def test_stream_releases_child_before_slow_sibling_and_matches_science(self):
        recipe, registry, _ = fixture()
        expected = s.run(recipe, registry)
        backend, store, stats = StreamingBackend(registry), Store(), {}
        actual = executor.run(s, recipe, registry, backend=backend,
            on_restore=backend.restore, store=store, stats=stats)
        self.assertEqual(actual, expected)
        self.assertEqual(s.encoded(actual), s.encoded(expected))
        self.assertLess(backend.events.index(('submit', 'c')),
                        backend.events.index(('receive', 'b')))
        self.assertLess(backend.events.index(('restore', 'a')),
                        backend.events.index(('submit', 'c')))
        self.assertEqual(backend.max_pending, 2)
        self.assertEqual(stats['executed_stage_ids'], ['a', 'b', 'c', 'd'])
        self.assertTrue(stats['completed'])

    def test_failure_checkpoint_excludes_holes_and_resume_reuses_speculation(self):
        recipe, registry, calls = fixture()
        store, stats = Store(), {}
        backend = StreamingBackend(registry, fail='b')
        with self.assertRaisesRegex(RuntimeError, 'worker failure') as caught:
            executor.run(s, recipe, registry, backend=backend, store=store,
                         on_restore=backend.restore, stats=stats)
        checkpoint = caught.exception.snapshot_checkpoint
        self.assertEqual(checkpoint, s.checkpoint(s.run(recipe, registry, stop_after=1)))
        self.assertFalse(stats['completed'])
        self.assertEqual(len(store.records), 2)  # a and speculative c, not b or d
        calls.clear()
        resumed_backend, resumed_stats = StreamingBackend(registry), {}
        result = executor.run(s, recipe, registry, backend=resumed_backend, store=store,
            on_restore=resumed_backend.restore, resume=checkpoint, stats=resumed_stats)
        self.assertEqual(calls, ['b', 'd'])
        self.assertEqual(resumed_stats['reused_stage_ids'], ['a', 'c'])
        self.assertEqual(result, s.run(recipe, registry))
        # Checkpoint bytes cannot authorise a prefix when its cache entry is lost.
        del store.records[checkpoint['state']['rows']['a']['invocation_sha256']]
        calls.clear()
        with self.assertRaisesRegex(ValueError, 'no authenticated'):
            executor.run(s, recipe, registry, store=store, resume=checkpoint,
                         backend=StreamingBackend(registry))
        self.assertEqual(calls, [])

    def test_stream_stops_at_exact_prefix_and_warm_cache_never_submits(self):
        for count in range(5):
            with self.subTest(count=count):
                recipe, registry, calls = fixture()
                backend, store = StreamingBackend(registry), Store()
                cold = executor.run(s, recipe, registry, backend=backend, store=store,
                    on_restore=backend.restore, stop_after=count)
                self.assertEqual(cold, s.run(recipe, registry, stop_after=count))
                self.assertEqual({ident for event, ident in backend.events if event == 'submit'},
                                 set(['a', 'b', 'c', 'd'][:count]))
                warm_backend = StreamingBackend(registry)
                calls.clear()
                warm = executor.run(s, recipe, registry, backend=warm_backend, store=store,
                    on_restore=warm_backend.restore, stop_after=count)
                self.assertEqual(warm, cold)
                self.assertEqual(calls, [])
                self.assertFalse(any(event == 'submit' for event, _ in warm_backend.events))

    def test_stream_unknown_supplied_and_repeated_parent_ports(self):
        for variant in ('unknown', 'supplied', 'repeated_parent'):
            recipe, registry, _ = fixture()
            if variant == 'unknown':
                recipe['stages'][0]['missing_inputs'] = ['explicit unknown boundary']
            elif variant == 'supplied':
                recipe['stages'][0]['inputs']['constraint'] = True
                recipe['stages'][0]['mode'] = 'SUPPLIED_CONSTRAINT'
            else:
                recipe['stages'][2]['dependencies']['another_a'] = deepcopy(
                    recipe['stages'][2]['dependencies']['a'])
            backend = StreamingBackend(registry)
            restored = lambda ident, record: backend.restored.add(ident)
            actual = executor.run(s, recipe, registry, backend=backend, on_restore=restored)
            self.assertEqual(actual, s.run(recipe, registry))
            if variant == 'unknown':
                self.assertEqual([ident for event, ident in backend.events if event == 'submit'],
                                 ['b'])

    def test_stream_invalid_completion_inventory_and_duplicate_fail_closed(self):
        for mode in ('empty', 'extra', 'duplicate'):
            with self.subTest(mode=mode):
                recipe, registry, _ = fixture()
                backend, store, stats = StreamingBackend(registry), Store(), {}
                receive = backend.receive
                seen = []

                def malformed():
                    if mode == 'empty':
                        return {}
                    if mode == 'extra':
                        return {'unexpected': {}}
                    if seen:
                        return deepcopy(seen[0])
                    completed = receive()
                    seen.append(deepcopy(completed))
                    return completed

                backend.receive = malformed
                with self.assertRaisesRegex(ValueError, 'inventory') as caught:
                    executor.run(s, recipe, registry, backend=backend, store=store,
                                 on_restore=backend.restore, stats=stats)
                self.assertFalse(stats['completed'])
                expected_count = 1 if mode == 'duplicate' else 0
                self.assertEqual(caught.exception.snapshot_checkpoint['state']['completed_stages'],
                                 expected_count)
                self.assertEqual(len(store.records), expected_count)

    def test_stream_malformed_result_or_source_drift_cannot_release_or_cache(self):
        for mode in ('context', 'mode', 'extras', 'source', 'restore'):
            with self.subTest(mode=mode):
                recipe, registry, _ = fixture()
                backend, store = StreamingBackend(registry), Store()
                receive = backend.receive
                drifted = []

                def malformed():
                    batch = receive()
                    value = batch['a']
                    if mode == 'context':
                        value['product']['context']['world_id'] = 'wrong'
                    elif mode == 'mode':
                        value['product']['status'] = 'SUPPLIED_CONSTRAINT'
                    elif mode == 'extras':
                        value['artifacts'] = []
                    elif mode == 'source':
                        drifted.append(True)
                    return batch

                def verify():
                    if drifted:
                        raise ValueError('source drift')

                def restore(ident, record):
                    if mode == 'restore':
                        raise ValueError('restore rejected')
                    backend.restore(ident, record)

                backend.receive = malformed
                registry['sum']['verify'] = verify
                with self.assertRaises(ValueError):
                    executor.run(s, recipe, registry, backend=backend, store=store,
                                 on_restore=restore)
                self.assertEqual(store.records, {})
                self.assertNotIn(('submit', 'c'), backend.events)

    def test_legacy_wave_and_serial_resume_semantics_remain_exact(self):
        recipe, registry, _ = fixture()
        backend = Backend(registry)
        self.assertEqual(executor.run(s, recipe, registry, backend=backend), s.run(recipe, registry))
        self.assertEqual(backend.batches, [['a', 'b'], ['c'], ['d']])
        checkpoint = s.checkpoint(s.run(recipe, registry, stop_after=2))
        self.assertEqual(executor.run(s, recipe, registry, resume=checkpoint),
                         original.run(s, recipe, registry, resume=checkpoint))

    def test_completed_subset_is_detached_before_callbacks_and_malformed_subset_rejected(self):
        for malformed in (False, True):
            recipe, registry, _ = fixture()
            backend, store = StreamingBackend(registry), Store()
            wave, retained = Backend(registry), []

            def receive():
                jobs = list(backend.pending.values())
                backend.pending.clear()
                batch = wave.execute(jobs)
                retained.append(batch)
                if malformed and 'b' in batch:
                    batch['b']['artifacts'] = []
                return batch

            def restore(ident, record):
                backend.restored.add(ident)
                if ident == 'a' and 'b' in retained[-1]:
                    retained[-1]['b']['product']['values']['value'] = 98765

            backend.receive = receive
            if malformed:
                with self.assertRaises(ValueError):
                    executor.run(s, recipe, registry, backend=backend, store=store,
                                 on_restore=restore)
                self.assertEqual(store.records, {})
            else:
                self.assertEqual(executor.run(s, recipe, registry, backend=backend,
                    store=store, on_restore=restore), s.run(recipe, registry))

    def test_final_common_source_failure_retains_checkpoint_and_failed_status(self):
        recipe, registry, _ = fixture()
        backend, store, stats = StreamingBackend(registry), Store(), {}

        class ChangedAtClosure(list):
            def __iter__(self):
                registry['sum']['sha256'] = 'b' * 64
                return super().__iter__()

        snapshot = SimpleNamespace(**vars(s))
        snapshot.CATEGORIES = ChangedAtClosure(s.CATEGORIES)
        with self.assertRaisesRegex(ValueError, 'execution differs') as caught:
            executor.run(snapshot, recipe, registry, backend=backend, store=store,
                         on_restore=backend.restore, stats=stats)
        self.assertFalse(stats['completed'])
        self.assertEqual(caught.exception.snapshot_checkpoint['state']['completed_stages'], 4)


def copy_benchmark():
    recipe, registry, _ = fixture()
    recipe['stages'][0]['inputs']['payload'] = list(range(80000))
    values, elapsed = [], []
    for module in (original, executor):
        start = perf_counter()
        values.append(module.run(s, recipe, registry))
        elapsed.append(perf_counter() - start)
    if values[0] != values[1]:
        raise ValueError('serial copy benchmark scientific result differs')
    return {'fixture': 'SYNTHETIC TEST, four integer stages; 80000-value unused input',
            'old_seconds': elapsed[0], 'new_seconds': elapsed[1],
            'saved_seconds': elapsed[0] - elapsed[1],
            'saved_percent': (elapsed[0] - elapsed[1]) / elapsed[0] * 100,
            'exact_scientific_result': True}


if __name__ == '__main__':
    import sys
    if sys.argv[1:] == ['--benchmark']:
        print(json.dumps(copy_benchmark()))
    else:
        unittest.main()
