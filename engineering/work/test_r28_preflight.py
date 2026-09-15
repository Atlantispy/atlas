"""Tiny synthetic preflight boundary checks; no scientific generation."""
from copy import deepcopy
from types import SimpleNamespace
import unittest

from work.generator_runtime_r12.test_executor import fixture, s, Store
from work.generator_upgrade_r24 import executor
from work.generator_upgrade_r28.preflight import _InvocationSnapshot


def observed_snapshot():
    calls = []

    def parse(recipe, registry):
        calls.append(True)
        return s.parse(recipe, registry)

    return SimpleNamespace(**dict(vars(s), parse=parse)), calls


class PreflightTests(unittest.TestCase):
    def test_one_parse_cold_warm_unknown_and_detached_nodes(self):
        for unknown in (False, True):
            with self.subTest(unknown=unknown):
                recipe, registry, producers = fixture()
                if unknown:
                    recipe['stages'][0]['missing_inputs'] = ['explicit missing input']
                expected = s.run(recipe, registry)
                store = Store()
                checks = []
                registry['sum']['verify'] = lambda: checks.append(True)
                for warm in (False, True):
                    native, parses = observed_snapshot()
                    facade = _InvocationSnapshot(native)
                    nodes, order = facade.parse(recipe, registry)
                    copied = deepcopy(recipe)
                    copied_nodes, copied_order = facade.parse(copied, registry)
                    self.assertEqual(order, copied_order)
                    self.assertIs(copied_nodes['a'], copied['stages'][0])
                    self.assertIsNot(copied_nodes['a'], nodes['a'])
                    # A separate invocation is used for actual executor entry.
                    native, parses = observed_snapshot()
                    facade = _InvocationSnapshot(native)
                    facade.parse(recipe, registry)
                    count = len(checks)
                    producers.clear()
                    stats = {}
                    actual = executor.run(facade, recipe, registry, store=store, stats=stats)
                    self.assertEqual(actual, expected)
                    self.assertEqual(len(parses), 1)
                    self.assertGreater(len(checks), count)
                    self.assertEqual(facade.diagnostics['duplicate_parse_passes_avoided'], 1)
                    if warm:
                        self.assertEqual(producers, [])
                        self.assertEqual(stats['reused_stage_ids'], ['a', 'b', 'c', 'd'])
                    elif unknown:
                        self.assertEqual(producers, ['b'])
                    else:
                        self.assertEqual(producers, ['a', 'b', 'c', 'd'])

    def test_changed_recipe_registration_and_third_use_are_rejected(self):
        for change in ('recipe', 'registry_copy', 'sha', 'run', 'verify', 'fields', 'inventory'):
            with self.subTest(change=change):
                recipe, registry, _ = fixture()
                facade = _InvocationSnapshot(s)
                facade.parse(recipe, registry)
                if change == 'recipe':
                    recipe['stages'][0]['inputs']['base'] += 1
                elif change == 'registry_copy':
                    registry = dict(registry)
                elif change == 'sha':
                    registry['sum']['sha256'] = 'b' * 64
                elif change in ('run', 'verify'):
                    registry['sum'][change] = lambda *args: None
                elif change == 'fields':
                    registry['sum']['extra'] = True
                else:
                    registry['other'] = dict(registry['sum'])
                with self.assertRaisesRegex(ValueError, 'changed after authoritative preflight'):
                    facade.parse(recipe, registry)
        recipe, registry, _ = fixture()
        facade = _InvocationSnapshot(s)
        facade.parse(recipe, registry)
        facade.parse(deepcopy(recipe), registry)
        with self.assertRaisesRegex(ValueError, 'single-use'):
            facade.parse(recipe, registry)

    def test_registration_change_during_final_verification_is_rejected(self):
        recipe, registry, _ = fixture()
        calls = []

        def verify():
            calls.append(True)
            if len(calls) == len(recipe['stages']):
                registry['sum']['sha256'] = 'b' * 64

        registry['sum']['verify'] = verify
        with self.assertRaisesRegex(ValueError, 'registration.*changed|changed.*registration'):
            _InvocationSnapshot(s).parse(recipe, registry)

    def test_invalid_graph_cannot_reach_next_action(self):
        for invalid in ('dependency', 'cycle', 'pin'):
            with self.subTest(invalid=invalid):
                recipe, registry, producers = fixture()
                if invalid == 'dependency':
                    recipe['stages'][2]['dependencies']['a']['stage_id'] = 'absent'
                elif invalid == 'cycle':
                    recipe['stages'][0]['dependencies']['d'] = {
                        'stage_id': 'd', 'output': 'value',
                        'port': deepcopy(recipe['stages'][0]['outputs']['value'])}
                else:
                    recipe['stages'][-1]['producer_sha256'] = 'b' * 64
                actions = []

                def enter():
                    _InvocationSnapshot(s).parse(recipe, registry)
                    actions.append('would start workers')

                with self.assertRaises(ValueError):
                    enter()
                self.assertEqual(actions, [])
                self.assertEqual(producers, [])

    def test_source_guard_remains_fresh_on_cold_and_warm_paths(self):
        for warm in (False, True):
            with self.subTest(warm=warm):
                recipe, registry, producers = fixture()
                store = Store()
                if warm:
                    executor.run(s, recipe, registry, store=store)
                drift = []

                def verify():
                    if drift:
                        raise ValueError('controlled source drift')

                registry['sum']['verify'] = verify
                facade = _InvocationSnapshot(s)
                facade.parse(recipe, registry)
                producers.clear()
                drift.append(True)
                before = deepcopy(store.records)
                with self.assertRaisesRegex(ValueError, 'controlled source drift'):
                    executor.run(facade, recipe, registry, store=store)
                self.assertEqual(producers, [])
                self.assertEqual(store.records, before)

    def test_no_cache_semantic_restart_uses_same_single_parse(self):
        recipe, registry, _ = fixture()
        checkpoint = s.checkpoint(s.run(recipe, registry, stop_after=2))
        expected = s.run(recipe, registry, resume=checkpoint)
        native, parses = observed_snapshot()
        facade = _InvocationSnapshot(native)
        facade.parse(recipe, registry)
        stats = {}
        actual = executor.run(facade, recipe, registry, resume=checkpoint, stats=stats)
        self.assertEqual(actual, expected)
        self.assertEqual(len(parses), 1)
        self.assertTrue(stats['uncached_semantic_replay'])
        self.assertEqual(facade.diagnostics['duplicate_parse_passes_avoided'], 1)


if __name__ == '__main__':
    unittest.main()
