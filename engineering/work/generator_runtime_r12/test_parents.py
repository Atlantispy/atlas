"""Exact parent-boundary cache behaviour with explicit non-scientific doubles."""
from copy import deepcopy
import json
from types import SimpleNamespace
import unittest

from . import parents, provenance
from .test_executor import Store

SCHEMAS = {8: 'diadem.biomes-vegetation-result.r8',
           9: 'diadem.species-spatial-result.r9',
           10: 'diadem.seasonal-world-result.r10'}


class Parent:
    def __init__(self, version, child=None):
        self.version = version
        self.parent = child
        self.source_sha256 = str(version % 10) * 64
        self.storage = SimpleNamespace(encoded=provenance.encoded, decoded=json.loads)
        self.calls = []
        self.verifications = 0
        self.drift = False
        self.after_run = None

    def verify(self):
        self.verifications += 1
        if self.drift:
            raise ValueError('explicit parent source drift')

    def run(self, recipe, *, stop_after=None, resume=None):
        self.verify()
        self.calls.append({'recipe': deepcopy(recipe), 'stop_after': stop_after, 'resume': deepcopy(resume)})
        result = {'schema': SCHEMAS[self.version], 'source_sha256': self.source_sha256,
                  'recipe_sha256': provenance.sha(recipe), 'synthetic_value': recipe['value'],
                  'stop_after': stop_after, 'resume': deepcopy(resume)}
        if self.parent is not None and 'parent_recipe' in recipe:
            result['parent_result'] = self.parent.run(recipe['parent_recipe'])
        if self.after_run is not None:
            self.after_run(result)
        self.verify()
        return result


def fixture():
    r8 = Parent(8)
    r9 = Parent(9, r8)
    r10 = Parent(10, r9)
    recipe8 = {'value': 8}
    recipe9 = {'value': 9, 'parent_recipe': recipe8}
    recipe10 = {'value': 10, 'parent_recipe': recipe9}
    return SimpleNamespace(parent=r10), recipe10, (r10, r9, r8)


class ParentReuseTests(unittest.TestCase):
    def test_complete_nested_parent_runs_cold_then_reuse_exactly(self):
        bundle, recipe, chain = fixture()
        store, stats = Store(), {}
        with parents.reuse(bundle, store, stats):
            first = bundle.parent.run(recipe)
            second = bundle.parent.run(recipe)
        self.assertEqual(first, second)
        self.assertEqual([len(parent.calls) for parent in chain], [1, 1, 1])
        self.assertEqual([row['version'] for row in stats['executed']], [8, 9, 10])
        self.assertEqual([row['version'] for row in stats['reused']], [10])
        self.assertEqual(len(store.records), 3)

    def test_unchanged_r8_r9_inputs_reused_after_downstream_r10_edit(self):
        bundle, recipe, chain = fixture()
        store, stats = Store(), {}
        with parents.reuse(bundle, store, stats):
            original = bundle.parent.run(recipe)
            changed = deepcopy(recipe)
            changed['value'] = 11
            second = bundle.parent.run(changed)
        self.assertEqual([len(parent.calls) for parent in chain], [2, 1, 1])
        self.assertEqual(original['parent_result'], second['parent_result'])
        self.assertEqual(stats['reused'][-1]['version'], 9)
        self.assertNotEqual(original['recipe_sha256'], second['recipe_sha256'])

    def test_changed_r8_recipe_invalidates_all_causal_parent_results(self):
        bundle, recipe, chain = fixture()
        store = Store()
        with parents.reuse(bundle, store, {}):
            bundle.parent.run(recipe)
            changed = deepcopy(recipe)
            changed['parent_recipe']['parent_recipe']['value'] = 80
            bundle.parent.run(changed)
        self.assertEqual([len(parent.calls) for parent in chain], [2, 2, 2])

    def test_changed_source_identity_invalidates_that_parent(self):
        bundle, recipe, chain = fixture()
        store = Store()
        with parents.reuse(bundle, store, {}):
            bundle.parent.run(recipe)
            chain[0].source_sha256 = 'a' * 64
            bundle.parent.run(recipe)
        self.assertEqual([len(parent.calls) for parent in chain], [2, 1, 1])

    def test_stop_and_resume_kwargs_bypass_complete_result_cache(self):
        for options in ({'stop_after': 0}, {'stop_after': 1}, {'resume': {'state': 'synthetic'}}):
            with self.subTest(options=options):
                bundle, recipe, chain = fixture()
                # Exercise direct R8 so no independently eligible nested full call obscures bypass.
                store, stats = Store(), {}
                with parents.reuse(bundle, store, stats):
                    first = chain[2].run({'value': 8}, **options)
                    second = chain[2].run({'value': 8}, **options)
                self.assertEqual(first, second)
                self.assertEqual(len(chain[2].calls), 2)
                self.assertEqual(store.records, {})
                self.assertEqual(stats, {'executed': [], 'reused': [],
                    'accounting': 'COMPLETE_FULL_PARENT_CALLS_ONLY; resumed/stopped calls bypass cache'})
                self.assertEqual(chain[2].calls[0]['stop_after'], options.get('stop_after'))
                self.assertEqual(chain[2].calls[0]['resume'], options.get('resume'))

    def test_explicit_none_kwargs_are_eligible_for_full_run_reuse(self):
        bundle, _, chain = fixture()
        stats = {}
        with parents.reuse(bundle, Store(), stats):
            chain[2].run({'value': 8}, stop_after=None, resume=None)
            chain[2].run({'value': 8}, stop_after=None, resume=None)
        self.assertEqual(len(chain[2].calls), 1)
        self.assertEqual(len(stats['reused']), 1)

    def test_no_store_leaves_methods_untouched_and_runs_normally(self):
        bundle, recipe, chain = fixture()
        stats = {}
        with parents.reuse(bundle, None, stats):
            self.assertTrue(all('run' not in vars(parent) for parent in chain))
            bundle.parent.run(recipe)
            bundle.parent.run(recipe)
        self.assertEqual([len(parent.calls) for parent in chain], [2, 2, 2])
        self.assertEqual(stats, {'executed': [], 'reused': [],
                                'accounting': 'NOT_COLLECTED_UNCACHED_REFERENCE'})

    def test_class_methods_restored_on_normal_exit(self):
        bundle, recipe, chain = fixture()
        originals = [parent.run for parent in chain]
        with parents.reuse(bundle, Store(), {}):
            self.assertTrue(all('run' in vars(parent) for parent in chain))
            bundle.parent.run(recipe)
        self.assertTrue(all('run' not in vars(parent) for parent in chain))
        self.assertEqual([parent.run for parent in chain], originals)

    def test_preexisting_instance_method_restored_exactly(self):
        bundle, recipe, chain = fixture()
        original = chain[1].run

        def override(recipe, **kwargs):
            return original(recipe, **kwargs)

        chain[1].run = override
        with parents.reuse(bundle, Store(), {}):
            self.assertIsNot(chain[1].run, override)
            bundle.parent.run(recipe)
        self.assertIs(chain[1].run, override)
        self.assertNotIn('run', vars(chain[0]))
        self.assertNotIn('run', vars(chain[2]))

    def test_body_failure_restores_every_original_method(self):
        bundle, recipe, chain = fixture()
        with self.assertRaisesRegex(RuntimeError, 'explicit body failure'):
            with parents.reuse(bundle, Store(), {}):
                bundle.parent.run(recipe)
                raise RuntimeError('explicit body failure')
        self.assertTrue(all('run' not in vars(parent) for parent in chain))

    def test_setup_failure_restores_any_already_wrapped_parent(self):
        bundle, _, chain = fixture()
        chain[0].parent = None
        with self.assertRaises((AttributeError, TypeError, ValueError)):
            with parents.reuse(bundle, Store(), {}):
                self.fail('malformed chain must not enter the context')
        self.assertNotIn('run', vars(chain[0]))

    def test_store_read_write_failures_restore_methods_without_success_stats(self):
        for operation in ('get', 'put'):
            with self.subTest(operation=operation):
                bundle, _, chain = fixture()
                store, stats = Store(), {}

                def fail(*args):
                    raise RuntimeError('explicit store failure')

                setattr(store, operation, fail)
                with self.assertRaisesRegex(RuntimeError, 'store failure'):
                    with parents.reuse(bundle, store, stats):
                        chain[2].run({'value': 8})
                self.assertTrue(all('run' not in vars(parent) for parent in chain))
                self.assertEqual(stats, {'executed': [], 'reused': [],
                    'accounting': 'COMPLETE_FULL_PARENT_CALLS_ONLY; resumed/stopped calls bypass cache'})

    def test_nested_contexts_restore_outer_wrappers_then_original_methods(self):
        bundle, _, chain = fixture()
        store = Store()
        with parents.reuse(bundle, store, {}):
            outer = [parent.run for parent in chain]
            with parents.reuse(bundle, store, {}):
                chain[2].run({'value': 8})
            self.assertEqual([parent.run for parent in chain], outer)
        self.assertTrue(all('run' not in vars(parent) for parent in chain))

    def test_source_verified_on_warm_hit_before_and_after_store_read(self):
        bundle, _, chain = fixture()
        store = Store()
        with parents.reuse(bundle, store, {}):
            chain[2].run({'value': 8})
            before = chain[2].verifications
            chain[2].run({'value': 8})
            self.assertGreaterEqual(chain[2].verifications - before, 2)
            original_get = store.get

            def drift(key):
                value = original_get(key)
                chain[2].drift = True
                return value

            store.get = drift
            with self.assertRaisesRegex(ValueError, 'source drift'):
                chain[2].run({'value': 8})
        self.assertEqual(len(chain[2].calls), 1)
        self.assertTrue(all('run' not in vars(parent) for parent in chain))

    def test_source_drift_during_actual_execution_never_commits(self):
        bundle, _, chain = fixture()
        store, stats = Store(), {}
        chain[2].after_run = lambda result: setattr(chain[2], 'drift', True)
        with self.assertRaisesRegex(ValueError, 'source drift'):
            with parents.reuse(bundle, store, stats):
                chain[2].run({'value': 8})
        self.assertEqual(store.records, {})
        self.assertEqual(stats['executed'], [])
        self.assertTrue(all('run' not in vars(parent) for parent in chain))

    def test_warm_result_mutation_cannot_modify_stored_parent(self):
        bundle, _, chain = fixture()
        with parents.reuse(bundle, Store(), {}):
            first = chain[2].run({'value': 8})
            first['synthetic_value'] = 888
            second = chain[2].run({'value': 8})
            second['synthetic_value'] = 999
            third = chain[2].run({'value': 8})
        self.assertEqual(third['synthetic_value'], 8)

    def test_cached_parent_request_and_scientific_bindings_are_checked(self):
        for mode in ('request', 'extra', 'schema', 'source_sha256', 'recipe_sha256'):
            with self.subTest(mode=mode):
                bundle, _, chain = fixture()
                store = Store()
                with parents.reuse(bundle, store, {}):
                    chain[2].run({'value': 8})
                    entry = next(iter(store.records.values()))
                    if mode == 'request':
                        entry['request']['version'] = 9
                    elif mode == 'extra':
                        entry['extra'] = None
                    else:
                        entry['result'][mode] = 'different'
                    with self.assertRaises(ValueError):
                        chain[2].run({'value': 8})
                self.assertEqual(len(chain[2].calls), 1)

    def test_computed_parent_wrong_schema_source_or_recipe_not_committed(self):
        for field in ('schema', 'source_sha256', 'recipe_sha256'):
            with self.subTest(field=field):
                bundle, _, chain = fixture()
                store = Store()
                chain[2].after_run = lambda result: result.update({field: 'wrong'})
                with self.assertRaisesRegex(ValueError, 'scientific binding'):
                    with parents.reuse(bundle, store, {}):
                        chain[2].run({'value': 8})
                self.assertEqual(store.records, {})


if __name__ == '__main__':
    unittest.main()
