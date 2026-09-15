"""R12 adapter checks on sealed R11 dispatch doubles, never full generation."""
from copy import deepcopy
import base64
import unittest

from . import executor, integration, provenance
from .test_executor import Store


class IntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sealed = provenance.load_science()
        cls.fixture_module = cls.sealed.module('test_workflow')
        cls.workflow = cls.sealed.module('workflow')
        cls.snapshot = cls.sealed.module('snapshot')

    def fixture(self, **options):
        bundle, recipe, calls, supplied, modules = self.fixture_module.fixture(**options)
        modules['workflow'] = self.workflow
        modules['snapshot'] = self.snapshot
        return bundle, recipe, calls, supplied, modules

    def adapted_run(self, bundle, recipe, *, store=None, stop_after=None,
                    resume=None, supplied_parent=None, decoded_bytes=1024 * 1024):
        built = integration.assemble(bundle, recipe, supplied_parent=supplied_parent,
                                     decoded_bytes=decoded_bytes)
        stats = {}

        def graph_run(graph_recipe, registry, **options):
            return executor.run(self.snapshot, graph_recipe, registry, store=store,
                on_computed=lambda ident, row: integration.collect(built, ident, row),
                on_restore=lambda ident, record: integration.restore(built, ident, record),
                stats=stats, **options)

        run = integration.adapted(self.workflow.run,
            assemble=lambda *args, **kwargs: built,
            s=integration.SnapshotAdapter(self.snapshot, graph_run))
        result = run(bundle, recipe, stop_after=stop_after, resume=resume,
                     supplied_parent=supplied_parent)
        return result, built, stats

    def test_adapted_assembly_no_science_and_original_globals_unchanged(self):
        bundle, recipe, calls, _, _ = self.fixture()
        original_type = self.workflow.assemble.__globals__['Artifacts']
        original_snapshot = self.workflow.run.__globals__['s']
        baseline = self.workflow.assemble(bundle, recipe)
        built = integration.assemble(bundle, recipe)
        self.assertEqual(calls, [])
        self.assertEqual(built['recipe'], baseline['recipe'])
        self.assertEqual(built['artifacts'].records, baseline['artifacts'].records)
        self.assertIs(self.workflow.assemble.__globals__['Artifacts'], original_type)
        self.assertIs(self.workflow.run.__globals__['s'], original_snapshot)
        self.assertIsNot(type(built['artifacts']), original_type)

    def test_cold_adaptation_exact_science_graph_checkpoint_and_packed_bytes(self):
        bundle, recipe, calls, _, _ = self.fixture()
        baseline = self.workflow.run(bundle, recipe)
        calls.clear()
        result, built, stats = self.adapted_run(bundle, recipe, store=Store())
        self.assertEqual(result, baseline)
        self.assertEqual(provenance.encoded(result), provenance.encoded(baseline))
        self.assertEqual(result['graph_checkpoint'], self.snapshot.checkpoint(result['graph_artifact']))
        self.assertGreater(built['artifacts'].decode_stats['hits'], 0)
        self.assertTrue(stats['completed'])
        self.assertTrue(calls)

    def test_warm_adaptation_restores_exact_artifact_inventory_without_science(self):
        bundle, recipe, calls, _, _ = self.fixture()
        store = Store()
        cold, _, _ = self.adapted_run(bundle, recipe, store=store)
        calls.clear()
        warm, _, stats = self.adapted_run(bundle, recipe, store=store)
        self.assertEqual(warm, cold)
        self.assertEqual(calls, [])
        self.assertEqual(stats['executed_stage_ids'], [])
        self.assertEqual(len(stats['reused_stage_ids']), cold['graph_artifact']['state']['completed_stages'])

    def test_prefix_restart_exact_with_no_prefix_producer_reexecution(self):
        bundle, recipe, calls, _, _ = self.fixture()
        store = Store()
        stopped, _, _ = self.adapted_run(bundle, recipe, store=store, stop_after=3)
        self.assertTrue(stopped['graph_checkpoint']['state']['rows'])
        prefix_calls = list(calls)
        calls.clear()
        resumed, _, stats = self.adapted_run(bundle, recipe, store=store,
                                            resume=stopped['graph_checkpoint'])
        suffix_calls = list(calls)
        calls.clear()
        baseline = self.workflow.run(bundle, recipe)
        self.assertEqual(resumed, baseline)
        self.assertEqual(sorted(prefix_calls + suffix_calls), sorted(calls))
        self.assertEqual(len(stats['restored_prefix_stage_ids']), 3)

    def test_zero_prefix_exact_and_no_calls(self):
        bundle, recipe, calls, _, _ = self.fixture()
        result, _, _ = self.adapted_run(bundle, recipe, store=Store(), stop_after=0)
        self.assertEqual(calls, [])
        self.assertEqual(result, self.workflow.run(bundle, recipe, stop_after=0))

    def test_supplied_parent_warm_reuse_does_not_claim_regeneration(self):
        bundle, recipe, calls, supplied, _ = self.fixture(supplied=True)
        store = Store()
        cold, _, _ = self.adapted_run(bundle, recipe, store=store, supplied_parent=supplied)
        self.assertNotIn('R10', calls)
        calls.clear()
        warm, _, _ = self.adapted_run(bundle, recipe, store=store, supplied_parent=supplied)
        self.assertEqual(calls, [])
        self.assertEqual(cold, warm)
        self.assertEqual(warm['graph_artifact']['state']['rows']['parent-r10']['product']['status'],
                         'SUPPLIED_CONSTRAINT')

    def test_downstream_recipe_change_conservatively_invalidates_r11_graph(self):
        bundle, recipe, calls, _, _ = self.fixture()
        store = Store()
        self.adapted_run(bundle, recipe, store=store)
        changed = deepcopy(recipe)
        changed['new_downstream_fixture_setting'] = 'different'
        calls.clear()
        result, _, stats = self.adapted_run(bundle, changed, store=store)
        self.assertTrue(calls)
        self.assertEqual(stats['reused_stage_ids'], [])
        self.assertEqual(result, self.workflow.run(bundle, changed))

    def test_unknown_water_diagnostic_saved_and_restored_exactly(self):
        bundle, recipe, calls, _, _ = self.fixture(water_status='UNKNOWN')
        store = Store()
        cold, _, _ = self.adapted_run(bundle, recipe, store=store)
        self.assertTrue(cold['diagnostic_artifact_refs'])
        self.assertNotIn('human', calls)
        calls.clear()
        warm, _, _ = self.adapted_run(bundle, recipe, store=store)
        self.assertEqual(warm, cold)
        self.assertEqual(calls, [])
        self.assertIsNone(warm['scenario_product_refs']['snow/held']['water'])

    def restored_example(self, *, diagnostic=False):
        bundle, recipe, _, _, _ = self.fixture(water_status='UNKNOWN' if diagnostic else 'MODELLED')
        _, built, _ = self.adapted_run(bundle, recipe)
        graph = self.snapshot.run(built['recipe'], built['registry'])
        ident = 'water--snow--held' if diagnostic else 'physical-r8'
        row = graph['state']['rows'][ident]
        record = {'row': deepcopy(row), **integration.collect(built, ident, row)}
        fresh = integration.assemble(bundle, recipe)
        return ident, record, fresh

    def test_restore_rejects_missing_extra_and_corrupt_scientific_units(self):
        for mode in ('missing', 'extra', 'corrupt', 'key', 'wrong_ref_schema', 'wrong_ref_size'):
            with self.subTest(mode=mode):
                ident, record, built = self.restored_example()
                key = next(iter(record['artifacts']))
                if mode == 'missing':
                    record['artifacts'].clear()
                elif mode == 'extra':
                    record['artifacts']['b' * 64] = deepcopy(record['artifacts'][key])
                elif mode == 'corrupt':
                    record['artifacts'][key]['bytes'] = base64.b64encode(b'{}').decode('ascii')
                elif mode == 'key':
                    record['artifacts'][key]['sha256'] = 'b' * 64
                elif mode == 'wrong_ref_schema':
                    record['row']['product']['values']['product']['schema'] = 'different'
                else:
                    record['row']['product']['values']['product']['byte_length'] += 1
                with self.assertRaises(ValueError):
                    integration.restore(built, ident, record)

    def test_restore_diagnostic_rejects_other_stage_and_collision(self):
        ident, record, built = self.restored_example(diagnostic=True)
        self.assertEqual(set(record['diagnostics']), {ident})
        foreign = deepcopy(record)
        foreign['diagnostics']['different-stage'] = foreign['diagnostics'].pop(ident)
        with self.assertRaisesRegex(ValueError, 'another stage'):
            integration.restore(built, ident, foreign)
        built['diagnostics'][ident] = {'different': 'diagnostic'}
        with self.assertRaisesRegex(ValueError, 'diagnostic collision'):
            integration.restore(built, ident, record)

    def test_restore_rejects_existing_artifact_collision(self):
        ident, record, built = self.restored_example()
        key = next(iter(record['artifacts']))
        built['artifacts'].records[key] = {'different': 'encoded record'}
        with self.assertRaisesRegex(ValueError, 'artifact collision'):
            integration.restore(built, ident, record)

    def test_restore_keeps_detached_artifact_and_diagnostic_records(self):
        ident, record, built = self.restored_example(diagnostic=True)
        expected = deepcopy(record)
        integration.restore(built, ident, record)
        record['artifacts'].clear()
        record['diagnostics'][ident]['role'] = 'mutated later'
        self.assertEqual(built['diagnostics'][ident], expected['diagnostics'][ident])
        for key, value in expected['artifacts'].items():
            self.assertEqual(built['artifacts'].records[key], value)

    def artifact_store(self, budget=1024 * 1024):
        codec = self.fixture_module.Codec()
        return integration.cached_artifacts(self.workflow.Artifacts, max_bytes=budget)(codec)

    def test_decoded_cache_hit_defends_against_returned_object_mutation(self):
        artifacts = self.artifact_store()
        original = {'schema': 'synthetic', 'values': [1, {'x': 2}]}
        ref = artifacts.put(original, 'test only')
        first = artifacts.get(ref)
        first['values'][1]['x'] = 99
        self.assertEqual(artifacts.get(ref), original)
        self.assertEqual(artifacts.decode_stats['hits'], 1)
        self.assertEqual(artifacts.decode_stats['misses'], 1)

    def test_decoded_cache_validates_schema_role_size_and_inventory_on_hit(self):
        artifacts = self.artifact_store()
        ref = artifacts.put({'schema': 'actual', 'x': 1}, 'test')
        artifacts.get(ref)
        for mode in ('schema', 'role', 'size', 'extra', 'missing'):
            with self.subTest(mode=mode):
                wrong = deepcopy(ref)
                if mode == 'schema':
                    wrong['schema'] = 'wrong'
                elif mode == 'role':
                    wrong['role'] = ''
                elif mode == 'size':
                    wrong['byte_length'] += 1
                elif mode == 'extra':
                    wrong['extra'] = None
                else:
                    del wrong['role']
                with self.assertRaises(ValueError):
                    artifacts.get(wrong)

    def test_mutated_packed_bytes_cannot_use_stale_decoded_hit(self):
        artifacts = self.artifact_store()
        ref = artifacts.put({'x': 1}, 'test')
        artifacts.get(ref)
        artifacts.records[ref['artifact_id']]['bytes'] = base64.b64encode(b'{}').decode('ascii')
        with self.assertRaisesRegex(ValueError, 'checksum'):
            artifacts.get(ref)
        self.assertEqual(artifacts.decode_stats['hits'], 0)

    def test_decoded_budget_lru_evicts_and_stays_within_accounted_limit(self):
        value = {'schema': 'fixture', 'value': 1}
        amount = 4 * len(self.snapshot.encoded(value))
        artifacts = self.artifact_store(amount)
        refs = [artifacts.put({'schema': 'fixture', 'value': x}, 'test') for x in (1, 2)]
        artifacts.get(refs[0]); artifacts.get(refs[1]); artifacts.get(refs[0])
        self.assertEqual(artifacts.decode_stats['misses'], 3)
        self.assertEqual(artifacts.decode_stats['hits'], 0)
        self.assertEqual(artifacts.decode_stats['evictions'], 2)
        self.assertLessEqual(artifacts.decode_stats['max_accounted_bytes'], amount)

    def test_zero_budget_and_oversized_decoded_values_do_not_cache(self):
        for budget in (0, 1):
            artifacts = self.artifact_store(budget)
            ref = artifacts.put({'x': 1}, 'test')
            artifacts.get(ref); artifacts.get(ref)
            self.assertEqual(artifacts.decode_stats['misses'], 2)
            self.assertEqual(artifacts.decode_stats['hits'], 0)
            self.assertEqual(artifacts.decode_stats['max_accounted_bytes'], 0)

    def test_invalid_decoded_budgets_reject(self):
        for budget in (True, -1, 1.0, '1'):
            with self.assertRaises(ValueError):
                self.artifact_store(budget)

    def test_artifact_backend_enriches_only_exact_incoming_records(self):
        bundle, recipe, _, _, _ = self.fixture()
        built = integration.assemble(bundle, recipe)
        ref = built['input_ref']
        job = {'stage_id': 'synthetic-stage', 'incoming': {'recipe': ref}}
        seen = []

        class Pool:
            def execute(self, jobs):
                seen.extend(jobs)
                return {'synthetic-stage': 'synthetic-result'}

        result = integration.ArtifactBackend(Pool(), built).execute([job])
        self.assertEqual(result, {'synthetic-stage': 'synthetic-result'})
        self.assertEqual(set(seen[0]['records']), {ref['artifact_id']})
        self.assertEqual(seen[0]['records'][ref['artifact_id']], built['artifacts'].records[ref['artifact_id']])
        self.assertNotIn('records', job)


if __name__ == '__main__':
    unittest.main()
