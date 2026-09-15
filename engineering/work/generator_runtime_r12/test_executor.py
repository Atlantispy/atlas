"""Pure-graph oracles for incremental reuse, continuation and ready-node batches."""
from copy import deepcopy
import importlib.util
from pathlib import Path
import unittest

from . import executor

_spec = importlib.util.spec_from_file_location('_r12_executor_snapshot_oracle',
    Path(__file__).resolve().parents[1] / 'generator_upgrade_r11' / 'snapshot.py')
s = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(s)
H = 'a' * 64
E = 'SYNTHETIC TEST; exact integer graph oracle, not world validation'


def fixture():
    ctx = dict(zip(s.FRAME_FIELDS, ('world', 'snapshot', 'calendar', 'frame', 'datum', 'scenario')))
    port = {'quantity': 'integer test quantity', 'unit': 'count',
            'support_id': 'cell', 'temporal_support': 'calendar'}
    calls = []

    def producer(context, inputs, incoming):
        calls.append(inputs['tag'])
        return s.emission(context, {'value': port},
            {'value': inputs['base'] + sum(incoming.values())}, evidence=E,
            status='SUPPLIED_CONSTRAINT' if inputs.get('constraint') else 'MODELLED')

    registry = {'sum': {'sha256': H, 'run': producer, 'verify': lambda: None}}
    stages = []
    for ident, category, parents in (
            ('a', 'precipitation', ()), ('b', 'geology', ()),
            ('c', 'hydrology', ('a',)), ('d', 'settlements', ('b', 'c'))):
        stages.append({'stage_id': ident, 'category': category, 'producer_id': 'sum',
            'producer_sha256': H, 'inputs': {'base': 1, 'tag': ident},
            'dependencies': {parent: {'stage_id': parent, 'output': 'value',
                                     'port': deepcopy(port)} for parent in parents},
            'outputs': {'value': deepcopy(port)}, 'missing_inputs': [], 'mode': 'GENERATED',
            'acceptance': {'status': 'BOUNDED_REFERENCE_VERIFIED', 'evidence': E}})
    return {'schema': 'diadem.snapshot-graph-recipe.r11', 'context': ctx,
        'stages': stages, 'required_categories': ['precipitation', 'hydrology',
        'settlements', 'geology'], 'evidence': E}, registry, calls


class Store:
    """Trusted-store protocol double; real persistence authenticates its reads."""
    def __init__(self):
        self.records = {}

    def get(self, key):
        return deepcopy(self.records.get(key))

    def put(self, key, value):
        if key in self.records and self.records[key] != value:
            raise ValueError('immutable cache conflict')
        self.records[key] = deepcopy(value)


class Backend:
    def __init__(self, registry):
        self.registry = registry
        self.batches = []

    def execute(self, jobs):
        self.batches.append([job['stage_id'] for job in jobs])
        result = {}
        # Complete independent jobs in reverse order to expose ordering bugs.
        for job in reversed(jobs):
            product = self.registry[job['producer_id']]['run'](
                job['context'], job['inputs'], job['incoming'])
            result[job['stage_id']] = {'product': deepcopy(product),
                                      'artifacts': {}, 'diagnostics': {}}
        return result


class ExecutorTests(unittest.TestCase):
    def test_no_store_exact_original_scientific_result(self):
        recipe, registry, calls = fixture()
        baseline = s.run(recipe, registry)
        calls.clear()
        stats = {}
        result = executor.run(s, recipe, registry, stats=stats)
        self.assertEqual(result, baseline)
        self.assertEqual(s.encoded(result), s.encoded(baseline))
        self.assertEqual(calls, ['a', 'b', 'c', 'd'])
        self.assertEqual(stats['executed_stage_ids'], calls)
        self.assertTrue(stats['completed'])

    def test_cold_then_warm_exact_without_any_producer_execution(self):
        recipe, registry, calls = fixture()
        store = Store()
        cold = executor.run(s, recipe, registry, store=store)
        calls.clear()
        stats = {}
        warm = executor.run(s, recipe, registry, store=store, stats=stats)
        self.assertEqual(cold, warm)
        self.assertEqual(calls, [])
        self.assertEqual(stats['executed_stage_ids'], [])
        self.assertEqual(stats['reused_stage_ids'], ['a', 'b', 'c', 'd'])
        self.assertTrue(all(row['producer_executed'] for row in warm['state']['rows'].values()))

    def test_changed_input_recomputes_only_affected_descendants(self):
        recipe, registry, calls = fixture()
        store = Store()
        executor.run(s, recipe, registry, store=store)
        recipe['stages'][0]['inputs']['base'] = 4
        calls.clear()
        stats = {}
        changed = executor.run(s, recipe, registry, store=store, stats=stats)
        self.assertEqual(calls, ['a', 'c', 'd'])
        self.assertEqual(stats['reused_stage_ids'], ['b'])
        self.assertEqual(changed, s.run(recipe, registry))

    def test_each_context_field_invalidates_every_node(self):
        for field in s.FRAME_FIELDS:
            with self.subTest(field=field):
                recipe, registry, calls = fixture()
                store = Store()
                executor.run(s, recipe, registry, store=store)
                recipe['context'][field] += '-changed'
                calls.clear()
                executor.run(s, recipe, registry, store=store)
                self.assertEqual(calls, ['a', 'b', 'c', 'd'])

    def test_recipe_evidence_changes_identity_but_reuses_unaffected_invocations(self):
        recipe, registry, calls = fixture()
        store = Store()
        old = executor.run(s, recipe, registry, store=store)
        recipe['evidence'] += '; changed wrapper evidence'
        calls.clear()
        new = executor.run(s, recipe, registry, store=store)
        self.assertEqual(calls, [])
        self.assertNotEqual(old['recipe_sha256'], new['recipe_sha256'])
        self.assertEqual(new, s.run(recipe, registry))

    def test_producer_digest_changes_invalidate(self):
        recipe, registry, calls = fixture()
        store = Store()
        executor.run(s, recipe, registry, store=store)
        for stage in recipe['stages']:
            stage['producer_sha256'] = 'b' * 64
        registry['sum']['sha256'] = 'b' * 64
        calls.clear()
        executor.run(s, recipe, registry, store=store)
        self.assertEqual(calls, ['a', 'b', 'c', 'd'])

    def test_unknown_closure_exact_warm_and_cold(self):
        recipe, registry, calls = fixture()
        recipe['stages'][0]['missing_inputs'] = ['explicit unresolved boundary']
        baseline = s.run(recipe, registry)
        store = Store()
        calls.clear()
        cold = executor.run(s, recipe, registry, store=store)
        self.assertEqual(calls, ['b'])
        self.assertEqual(cold, baseline)
        calls.clear()
        self.assertEqual(executor.run(s, recipe, registry, store=store), baseline)
        self.assertEqual(calls, [])
        self.assertIsNone(cold['state']['rows']['d']['product']['values']['value'])
        self.assertFalse(cold['state']['rows']['a']['producer_executed'])

    def test_producer_returning_unknown_is_still_original_executed_semantics(self):
        recipe, registry, _ = fixture()
        port = recipe['stages'][0]['outputs']
        registry['sum']['run'] = lambda ctx, inputs, incoming: s.emission(ctx, port,
            {'value': None}, evidence=E, source_status='UNKNOWN', status='UNKNOWN',
            unresolved=['producer diagnostic'])
        store = Store()
        cold = executor.run(s, recipe, registry, store=store)
        self.assertTrue(cold['state']['rows']['a']['producer_executed'])
        self.assertFalse(cold['state']['rows']['c']['producer_executed'])
        self.assertEqual(cold, executor.run(s, recipe, registry, store=store))

    def test_supplied_constraints_preserved(self):
        recipe, registry, _ = fixture()
        recipe['stages'][0]['inputs']['constraint'] = True
        recipe['stages'][0]['mode'] = 'SUPPLIED_CONSTRAINT'
        store = Store()
        baseline = s.run(recipe, registry)
        self.assertEqual(executor.run(s, recipe, registry, store=store), baseline)
        self.assertEqual(executor.run(s, recipe, registry, store=store), baseline)

    def test_false_generation_mode_never_commits(self):
        recipe, registry, _ = fixture()
        recipe['stages'][0]['inputs']['constraint'] = True
        store = Store()
        with self.assertRaisesRegex(ValueError, 'regeneration'):
            executor.run(s, recipe, registry, store=store)
        self.assertEqual(store.records, {})

    def test_exact_stop_and_fast_resume_without_prefix_calculation(self):
        for count in range(5):
            with self.subTest(count=count):
                recipe, registry, calls = fixture()
                store = Store()
                stopped = executor.run(s, recipe, registry, store=store, stop_after=count)
                self.assertEqual(stopped, s.run(recipe, registry, stop_after=count))
                calls.clear()
                stats = {}
                resumed = executor.run(s, recipe, registry, store=store,
                    resume=s.checkpoint(stopped), stats=stats)
                self.assertEqual(calls, ['a', 'b', 'c', 'd'][count:])
                self.assertEqual(stats['restored_prefix_stage_ids'], ['a', 'b', 'c', 'd'][:count])
                self.assertEqual(resumed, s.run(recipe, registry))

    def test_original_checkpoint_accepted_only_against_cached_prefix(self):
        recipe, registry, calls = fixture()
        original = s.checkpoint(s.run(recipe, registry, stop_after=2))
        store = Store()
        executor.run(s, recipe, registry, store=store, stop_after=2)
        calls.clear()
        executor.run(s, recipe, registry, store=store, resume=original)
        self.assertEqual(calls, ['c', 'd'])

    def test_no_cache_resume_retains_original_full_semantic_replay(self):
        recipe, registry, calls = fixture()
        checkpoint = s.checkpoint(s.run(recipe, registry, stop_after=2))
        calls.clear()
        stats = {}
        result = executor.run(s, recipe, registry, resume=checkpoint, stats=stats)
        self.assertEqual(calls, ['a', 'b', 'a', 'b', 'c', 'd'])
        self.assertTrue(stats['uncached_semantic_replay'])
        self.assertEqual(result, s.run(recipe, registry))

    def test_resume_missing_prefix_entry_fails_without_any_producer(self):
        recipe, registry, calls = fixture()
        store = Store()
        stopped = executor.run(s, recipe, registry, store=store, stop_after=2)
        del store.records[stopped['state']['rows']['b']['invocation_sha256']]
        calls.clear()
        with self.assertRaisesRegex(ValueError, 'no authenticated'):
            executor.run(s, recipe, registry, store=store, resume=s.checkpoint(stopped))
        self.assertEqual(calls, [])

    def test_rehashed_forged_checkpoint_fails_against_independent_store(self):
        recipe, registry, calls = fixture()
        store = Store()
        checkpoint = s.checkpoint(executor.run(s, recipe, registry, store=store, stop_after=2))
        row = checkpoint['state']['rows']['a']
        row['product']['values']['value'] = 100
        row['product_sha256'] = s.sha(row['product'])
        checkpoint['state_sha256'] = s.sha(checkpoint['state'])
        calls.clear()
        with self.assertRaisesRegex(ValueError, 'differs from authenticated'):
            executor.run(s, recipe, registry, store=store, resume=checkpoint)
        self.assertEqual(calls, [])

    def test_checkpoint_exact_inventory_and_binding(self):
        recipe, registry, _ = fixture()
        store = Store()
        original = s.checkpoint(executor.run(s, recipe, registry, store=store, stop_after=2))
        for mutation in ('recipe', 'statehash', 'count', 'row', 'extra'):
            with self.subTest(mutation=mutation):
                checkpoint = deepcopy(original)
                if mutation == 'recipe':
                    checkpoint['recipe_sha256'] = '0' * 64
                elif mutation == 'statehash':
                    checkpoint['state_sha256'] = '0' * 64
                elif mutation == 'count':
                    checkpoint['state']['completed_stages'] = True
                    checkpoint['state_sha256'] = s.sha(checkpoint['state'])
                elif mutation == 'row':
                    del checkpoint['state']['rows']['a']
                    checkpoint['state_sha256'] = s.sha(checkpoint['state'])
                else:
                    checkpoint['state']['extra'] = None
                    checkpoint['state_sha256'] = s.sha(checkpoint['state'])
                with self.assertRaises(ValueError):
                    executor.run(s, recipe, registry, store=store, resume=checkpoint)

    def test_corrupt_cached_rows_are_never_silently_recomputed(self):
        for field in ('invocation_sha256', 'product_sha256', 'producer_executed',
                      'extra', 'context', 'mode', 'row_extra', 'extras_type'):
            with self.subTest(field=field):
                recipe, registry, calls = fixture()
                store = Store()
                first = executor.run(s, recipe, registry, store=store)
                record = store.records[first['state']['rows']['a']['invocation_sha256']]
                if field in ('invocation_sha256', 'product_sha256'):
                    record['row'][field] = '0' * 64
                elif field == 'producer_executed':
                    record['row'][field] = 1
                elif field == 'extra':
                    record['extra'] = None
                elif field == 'row_extra':
                    record['row']['extra'] = None
                elif field == 'extras_type':
                    record['artifacts'] = []
                elif field == 'context':
                    record['row']['product']['context']['world_id'] = 'wrong'
                    record['row']['product_sha256'] = s.sha(record['row']['product'])
                else:
                    record['row']['product']['status'] = 'SUPPLIED_CONSTRAINT'
                    record['row']['product_sha256'] = s.sha(record['row']['product'])
                calls.clear()
                stats = {}
                with self.assertRaises(ValueError):
                    executor.run(s, recipe, registry, store=store, stats=stats)
                self.assertEqual(calls, [])
                self.assertFalse(stats['completed'])

    def test_unknown_explanation_and_execution_flag_validated_on_reuse(self):
        for mutation in ('explanation', 'execution'):
            recipe, registry, calls = fixture()
            recipe['stages'][0]['missing_inputs'] = ['actual gap']
            store = Store()
            result = executor.run(s, recipe, registry, store=store)
            record = store.records[result['state']['rows']['a']['invocation_sha256']]
            if mutation == 'explanation':
                record['row']['product']['unresolved'] = ['invented gap']
                record['row']['product_sha256'] = s.sha(record['row']['product'])
            else:
                record['row']['producer_executed'] = True
            calls.clear()
            with self.assertRaises(ValueError):
                executor.run(s, recipe, registry, store=store)
            self.assertEqual(calls, [])

    def test_live_source_drift_checked_on_cache_hit(self):
        recipe, registry, calls = fixture()
        store = Store()
        executor.run(s, recipe, registry, store=store)
        calls.clear()
        original_get = store.get
        drifted = [False]

        def get(key):
            value = original_get(key)
            drifted[0] = True
            return value

        def verify():
            if drifted[0]:
                raise ValueError('live source drift')

        store.get = get
        registry['sum']['verify'] = verify
        with self.assertRaisesRegex(ValueError, 'live source drift'):
            executor.run(s, recipe, registry, store=store)
        self.assertEqual(calls, [])

    def test_producer_source_drift_does_not_commit(self):
        recipe, registry, _ = fixture()
        store = Store()
        original = registry['sum']['run']
        drifted = [False]

        def producer(*args):
            value = original(*args)
            drifted[0] = True
            return value

        def verify():
            if drifted[0]:
                raise ValueError('source changed mid-call')

        registry['sum'].update(run=producer, verify=verify)
        with self.assertRaisesRegex(ValueError, 'mid-call'):
            executor.run(s, recipe, registry, store=store)
        self.assertEqual(store.records, {})

    def test_registry_digest_mutation_detected_after_run(self):
        recipe, registry, _ = fixture()
        original = registry['sum']['run']

        def producer(*args):
            value = original(*args)
            registry['sum']['sha256'] = 'b' * 64
            return value

        registry['sum']['run'] = producer
        store = Store()
        with self.assertRaisesRegex(ValueError, 'execution differs'):
            executor.run(s, recipe, registry, store=store)
        self.assertEqual(store.records, {})

    def test_retained_output_alias_and_callback_mutations_cannot_change_rows(self):
        recipe, registry, _ = fixture()
        original = registry['sum']['run']
        retained = []

        def producer(*args):
            value = original(*args)
            if retained:
                retained[0]['values']['value'] = 999
            retained.append(value)
            return value

        def capture(ident, row):
            row['product']['values']['value'] = 777
            return {'artifacts': {}, 'diagnostics': {}}

        registry['sum']['run'] = producer
        result = executor.run(s, recipe, registry, on_computed=capture)
        self.assertEqual(result['state']['rows']['a']['product']['values']['value'], 1)
        for row in result['state']['rows'].values():
            self.assertEqual(row['product_sha256'], s.sha(row['product']))
        retained[-1]['values']['value'] = 555
        self.assertEqual(result['state']['rows']['d']['product']['values']['value'], 4)

    def test_mutating_input_producer_cannot_change_recipe_or_dependency_rows(self):
        recipe, registry, _ = fixture()
        original = registry['sum']['run']
        before = deepcopy(recipe)

        def producer(ctx, inputs, incoming):
            value = original(ctx, inputs, incoming)
            ctx.clear(); inputs.clear(); incoming.clear()
            return value

        registry['sum']['run'] = producer
        executor.run(s, recipe, registry)
        self.assertEqual(recipe, before)

    def test_restore_hook_receives_exact_extras_and_detached_record(self):
        recipe, registry, calls = fixture()
        store = Store()

        def computed(ident, row):
            return {'artifacts': {ident: {'saved_value': row['product']['values']['value']}},
                    'diagnostics': {ident: 'bounded diagnostic'}}

        baseline = executor.run(s, recipe, registry, store=store, on_computed=computed)
        restored = []

        def restore(ident, record):
            self.assertEqual(record['artifacts'][ident]['saved_value'],
                             record['row']['product']['values']['value'])
            self.assertEqual(record['diagnostics'], {ident: 'bounded diagnostic'})
            restored.append(ident)
            record['row']['product']['values']['value'] = 999
            record['artifacts'].clear()

        calls.clear()
        warm = executor.run(s, recipe, registry, store=store, on_restore=restore)
        self.assertEqual(warm, baseline)
        self.assertEqual(restored, ['a', 'b', 'c', 'd'])
        self.assertEqual(calls, [])

    def test_artifact_cache_requires_restore_hook(self):
        recipe, registry, _ = fixture()
        store = Store()
        executor.run(s, recipe, registry, store=store,
            on_computed=lambda ident, row: {'artifacts': {ident: {}}, 'diagnostics': {}})
        with self.assertRaisesRegex(ValueError, 'restore hook'):
            executor.run(s, recipe, registry, store=store)

    def test_restore_failure_prevents_suffix_and_success(self):
        recipe, registry, calls = fixture()
        store = Store()
        stopped = executor.run(s, recipe, registry, store=store, stop_after=2)
        calls.clear()
        stats = {}

        def fail(*args):
            raise ValueError('artifact corrupt')

        with self.assertRaisesRegex(ValueError, 'artifact corrupt'):
            executor.run(s, recipe, registry, store=store, resume=s.checkpoint(stopped),
                         on_restore=fail, stats=stats)
        self.assertFalse(stats['completed'])
        self.assertEqual(calls, [])

    def test_backend_only_independent_ready_batches_and_order_exact(self):
        recipe, registry, _ = fixture()
        baseline = s.run(recipe, registry)
        backend = Backend(registry)
        stats = {}
        result = executor.run(s, recipe, registry, backend=backend, stats=stats)
        self.assertEqual(backend.batches, [['a', 'b'], ['c'], ['d']])
        self.assertEqual(result, baseline)
        self.assertEqual(list(result['state']['rows']), ['a', 'b', 'c', 'd'])
        self.assertEqual(stats['executed_stage_ids'], ['a', 'b', 'c', 'd'])

    def test_backend_never_runs_beyond_requested_prefix(self):
        for count, batches in ((0, []), (1, [['a']]), (2, [['a', 'b']]),
                               (3, [['a', 'b'], ['c']])):
            recipe, registry, _ = fixture()
            backend = Backend(registry)
            result = executor.run(s, recipe, registry, backend=backend, stop_after=count)
            self.assertEqual(backend.batches, batches)
            self.assertEqual(result, s.run(recipe, registry, stop_after=count))

    def test_backend_cache_hits_not_dispatched_and_incremental_outputs_match(self):
        recipe, registry, _ = fixture()
        store = Store()
        executor.run(s, recipe, registry, store=store)
        recipe['stages'][0]['inputs']['base'] = 9
        backend = Backend(registry)
        result = executor.run(s, recipe, registry, store=store, backend=backend)
        self.assertEqual(backend.batches, [['a'], ['c'], ['d']])
        self.assertEqual(result, s.run(recipe, registry))

    def test_backend_unknown_nodes_are_not_dispatched(self):
        recipe, registry, _ = fixture()
        recipe['stages'][0]['missing_inputs'] = ['unresolved rain']
        backend = Backend(registry)
        result = executor.run(s, recipe, registry, backend=backend)
        self.assertEqual(backend.batches, [['b']])
        self.assertEqual(result, s.run(recipe, registry))

    def test_backend_artifacts_restored_before_next_dependent_batch(self):
        recipe, registry, _ = fixture()
        restored = set()
        base = Backend(registry)

        class ArtifactBackend:
            def execute(self, jobs):
                for job in jobs:
                    if job['stage_id'] == 'c':
                        self_case.assertIn('a', restored)
                    if job['stage_id'] == 'd':
                        self_case.assertTrue({'b', 'c'} <= restored)
                result = base.execute(jobs)
                for ident, value in result.items():
                    value['artifacts'] = {ident: {'result': value['product']['values']['value']}}
                return result

        self_case = self
        result = executor.run(s, recipe, registry, backend=ArtifactBackend(),
            on_restore=lambda ident, record: restored.add(ident))
        self.assertEqual(restored, {'a', 'b', 'c', 'd'})
        self.assertEqual(result, s.run(recipe, registry))

    def test_malformed_backend_batch_never_commits_any_stage(self):
        for mode in ('missing', 'extra', 'direct_product', 'wrong_product', 'bad_extras'):
            with self.subTest(mode=mode):
                recipe, registry, _ = fixture()
                original = Backend(registry)

                class Malformed:
                    def execute(self, jobs):
                        result = original.execute(jobs)
                        if mode == 'missing':
                            del result['a']
                        elif mode == 'extra':
                            result['unexpected'] = deepcopy(result['a'])
                        elif mode == 'direct_product':
                            result['b'] = result['b']['product']
                        elif mode == 'wrong_product':
                            result['b']['product']['context']['world_id'] = 'wrong'
                        else:
                            result['b']['diagnostics'] = []
                        return result

                store, stats = Store(), {}
                with self.assertRaises(ValueError):
                    executor.run(s, recipe, registry, store=store, backend=Malformed(), stats=stats)
                self.assertEqual(store.records, {})
                self.assertFalse(stats['completed'])

    def test_backend_failure_never_masks_failure_or_commits_batch(self):
        recipe, registry, _ = fixture()

        class Failed:
            def execute(self, jobs):
                raise RuntimeError('worker failed')

        store, stats = Store(), {}
        with self.assertRaisesRegex(RuntimeError, 'worker failed'):
            executor.run(s, recipe, registry, store=store, backend=Failed(), stats=stats)
        self.assertEqual(store.records, {})
        self.assertFalse(stats['completed'])

    def test_invalid_cursor_and_cycle_reject_before_execution(self):
        for cursor in (True, -1, 5, 1.0):
            recipe, registry, calls = fixture()
            with self.assertRaises(ValueError):
                executor.run(s, recipe, registry, stop_after=cursor)
            self.assertEqual(calls, [])
        recipe, registry, calls = fixture()
        recipe['stages'][0]['dependencies'] = {'loop': {'stage_id': 'd', 'output': 'value',
                                                      'port': recipe['stages'][3]['outputs']['value']}}
        with self.assertRaisesRegex(ValueError, 'cyclic'):
            executor.run(s, recipe, registry)
        self.assertEqual(calls, [])

    def test_malformed_computed_extras_fail_before_cache_commit(self):
        for bad in (None, {}, {'artifacts': [], 'diagnostics': {}},
                    {'artifacts': {}, 'diagnostics': {}, 'extra': 1}):
            recipe, registry, _ = fixture()
            store = Store()
            with self.assertRaises(ValueError):
                executor.run(s, recipe, registry, store=store,
                             on_computed=lambda ident, row: bad)
            self.assertEqual(store.records, {})


if __name__ == '__main__':
    unittest.main()
