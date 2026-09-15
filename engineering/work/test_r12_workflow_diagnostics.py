"""Focused ready-wave and restart diagnostics checks, using integer fixtures."""
from copy import deepcopy
import unittest

from work.generator_runtime_r12 import executor
from work.generator_runtime_r12.test_executor import Backend, Store, fixture, s


def legacy_frontiers(nodes, order, completed):
    """Pre-change scan, retained only as a tiny scheduling oracle/benchmark."""
    rows, pending = set(completed), list(order)
    while pending:
        ready = [ident for ident in pending if all(
            dep['stage_id'] in rows for dep in nodes[ident]['dependencies'].values())]
        if not ready:
            raise ValueError('no executable graph frontier')
        yield ready
        rows.update(ready)
        pending = [ident for ident in pending if ident not in rows]


def graph(parents):
    return {ident: {'dependencies': {str(i): {'stage_id': parent}
            for i, parent in enumerate(deps)}} for ident, deps in parents.items()}


class ReadyQueueTests(unittest.TestCase):
    def test_exact_legacy_waves_with_duplicate_ports_and_reordered_release(self):
        nodes = graph({'a': [], 'b': [], 'c': ['b', 'b'], 'd': ['a'],
                       'e': ['c', 'd'], 'f': ['a']})
        order = list(nodes)
        for count in range(len(order) + 1):
            with self.subTest(prefix=count):
                completed, pending = order[:count], order[count:]
                self.assertEqual(list(executor._frontiers(nodes, pending, completed)),
                                 list(legacy_frontiers(nodes, pending, completed)))
        self.assertEqual(list(executor._frontiers(nodes, order, {})),
                         [['a', 'b'], ['c', 'd', 'f'], ['e']])

    def test_deep_chain_and_wide_layer(self):
        for nodes in (graph({str(i): [] if i == 0 else [str(i - 1)] for i in range(200)}),
                      graph({str(i): [] for i in range(200)})):
            self.assertEqual(list(executor._frontiers(nodes, list(nodes), {})),
                             list(legacy_frontiers(nodes, list(nodes), {})))

    def test_unavailable_parent_still_fails_closed(self):
        with self.assertRaisesRegex(ValueError, 'no executable graph frontier'):
            list(executor._frontiers(graph({'a': ['outside-prefix']}), ['a'], {}))

    def test_duplicate_parent_ports_backend_and_resume_preserve_exact_result(self):
        recipe, registry, calls = fixture()
        stage = recipe['stages'][2]
        stage['dependencies']['a_again'] = deepcopy(stage['dependencies']['a'])
        expected = s.run(recipe, registry)
        cache, backend = Store(), Backend(registry)
        result = executor.run(s, recipe, registry, store=cache, backend=backend)
        self.assertEqual(s.encoded(result), s.encoded(expected))
        self.assertEqual(backend.batches, [['a', 'b'], ['c'], ['d']])
        stopped = executor.run(s, recipe, registry, store=cache, stop_after=2)
        calls.clear()
        resumed = executor.run(s, recipe, registry, store=cache,
                               resume=s.checkpoint(stopped), backend=backend)
        self.assertEqual(s.encoded(resumed), s.encoded(expected))
        self.assertEqual(calls, [])


class RecoveryDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.recipe, self.registry, self.calls = fixture()
        self.cache = Store()
        self.checkpoint = s.checkpoint(executor.run(s, self.recipe, self.registry,
                                                   store=self.cache, stop_after=2))
        self.calls.clear()

    def failure(self, checkpoint):
        with self.assertRaises(ValueError) as caught:
            executor.run(s, self.recipe, self.registry, store=self.cache, resume=checkpoint)
        self.assertEqual(self.calls, [])
        return str(caught.exception)

    def test_binding_names_and_full_digests(self):
        for field in ('schema', 'recipe_sha256', 'state_sha256'):
            with self.subTest(field=field):
                checkpoint = deepcopy(self.checkpoint)
                checkpoint[field] = 'wrong' if field == 'schema' else '0' * 64
                message = self.failure(checkpoint)
                self.assertIn(field, message)
                self.assertIn(str(checkpoint[field]), message)
                self.assertIn(self.checkpoint[field], message)

    def test_missing_entry_identifies_stage_and_full_invocation(self):
        invocation = self.checkpoint['state']['rows']['b']['invocation_sha256']
        del self.cache.records[invocation]
        message = self.failure(self.checkpoint)
        self.assertIn('stage b', message)
        self.assertIn(invocation, message)
        self.assertIn('no authenticated cache entry', message)

    def test_corrupt_entry_keeps_cause_and_stage_without_recomputing(self):
        invocation = self.checkpoint['state']['rows']['a']['invocation_sha256']
        self.cache.records[invocation]['row']['product_sha256'] = '0' * 64
        message = self.failure(self.checkpoint)
        self.assertIn('stage a', message)
        self.assertIn(invocation, message)
        self.assertIn('cached product hash differs', message)
        self.assertEqual(self.cache.records[invocation]['row']['product_sha256'], '0' * 64)

    def test_prefix_inventory_and_cursor_are_explained(self):
        checkpoint = deepcopy(self.checkpoint)
        checkpoint['state']['rows']['unexpected'] = checkpoint['state']['rows'].pop('a')
        checkpoint['state_sha256'] = s.sha(checkpoint['state'])
        message = self.failure(checkpoint)
        self.assertIn("missing 1 ['a']", message)
        self.assertIn("extra 1 ['unexpected']", message)
        checkpoint = deepcopy(self.checkpoint)
        checkpoint['state']['completed_stages'] = 9
        checkpoint['state_sha256'] = s.sha(checkpoint['state'])
        message = self.failure(checkpoint)
        self.assertIn('completed_stages=9', message)
        self.assertIn('0..4', message)


if __name__ == '__main__':
    unittest.main()
