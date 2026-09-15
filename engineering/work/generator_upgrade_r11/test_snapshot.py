"""Independent graph, source, conservation-boundary and continuation tests."""
from copy import deepcopy
import unittest
from . import snapshot as s

H = 'a'*64
E = 'SYNTHETIC TEST; integer dependency oracle, not geographic acceptance'


def fixture():
    ctx = dict(zip(s.FRAME_FIELDS, ('Diadem-reference', 'snapshot-1', 'year-1', 'grid-1', 'datum-1', 'coequal-A')))
    port = {'quantity': 'finite water volume', 'unit': 'm3', 'support_id': 'cell-1', 'temporal_support': 'year-1'}
    calls = []
    def producer(context, inputs, dependencies):
        calls.append(inputs['tag'])
        value = inputs['base']+sum(dependencies.values())
        return s.emission(context, {'water': port}, {'water': value}, evidence=E,
            status='SUPPLIED_CONSTRAINT' if inputs.get('constraint') else 'MODELLED')
    registry = {'sum': {'sha256': H, 'run': producer, 'verify': lambda: None}}
    stages = []
    for ident, category, parent in (('rain', 'precipitation', None), ('river', 'hydrology', 'rain'), ('supply', 'settlements', 'river'), ('independent', 'geology', None)):
        stages.append({'stage_id': ident, 'category': category, 'producer_id': 'sum', 'producer_sha256': H,
            'inputs': {'base': 1, 'tag': ident}, 'dependencies': {} if parent is None else {'inflow': {'stage_id': parent, 'output': 'water', 'port': deepcopy(port)}},
            'outputs': {'water': deepcopy(port)}, 'missing_inputs': [], 'mode': 'GENERATED',
            'acceptance': {'status': 'BOUNDED_REFERENCE_VERIFIED', 'evidence': E}})
    recipe = {'schema': 'diadem.snapshot-graph-recipe.r11', 'context': ctx, 'stages': stages,
        'required_categories': ['precipitation', 'hydrology', 'settlements', 'geology'], 'evidence': E}
    return recipe, registry, calls


class SnapshotTests(unittest.TestCase):
    def test_actual_dependency_execution(self):
        recipe, registry, calls = fixture()
        result = s.run(recipe, registry)
        self.assertEqual(result['state']['rows']['supply']['product']['values']['water'], 3)
        self.assertEqual(len(calls), 4)
        self.assertEqual(result['status'], 'EXECUTED')

    def test_all_eighteen_have_explicit_closure(self):
        recipe, registry, _ = fixture(); result = s.run(recipe, registry)
        self.assertEqual(set(result['category_closure']), set(s.CATEGORIES))
        self.assertEqual(len(s.CATEGORIES), 18)
        self.assertFalse(result['whole_generator_implemented_claim'])
        self.assertFalse(result['category_closure']['plate_tectonics']['execution_complete'])

    def test_required_absent_category_incomplete(self):
        recipe, registry, _ = fixture(); recipe['required_categories'].append('plate_tectonics')
        self.assertEqual(s.run(recipe, registry)['status'], 'INCOMPLETE')

    def test_unknown_only_blocks_descendants(self):
        recipe, registry, calls = fixture(); recipe['stages'][0]['missing_inputs'] = ['rain boundary']
        result = s.run(recipe, registry)
        self.assertEqual(calls, ['independent'])
        self.assertEqual(result['state']['rows']['supply']['product']['status'], 'UNKNOWN')
        self.assertIsNone(result['state']['rows']['supply']['product']['values']['water'])

    def test_unknown_is_not_evaluated_zero(self):
        recipe, registry, _ = fixture(); recipe['stages'][0]['inputs']['base'] = 0
        result = s.run(recipe, registry)
        self.assertEqual(result['state']['rows']['rain']['product']['values']['water'], 0)
        self.assertEqual(result['state']['rows']['rain']['product']['status'], 'MODELLED')

    def test_restart_exact(self):
        recipe, registry, _ = fixture(); stopped = s.run(recipe, registry, stop_after=2)
        self.assertEqual(s.run(recipe, registry), s.run(recipe, registry, resume=s.checkpoint(stopped)))

    def test_checksum_forgery_does_not_replace_semantic_replay(self):
        recipe, registry, _ = fixture(); checkpoint = s.checkpoint(s.run(recipe, registry, stop_after=2))
        checkpoint['state']['rows']['rain']['product']['values']['water'] = 20
        checkpoint['state_sha256'] = s.sha(checkpoint['state'])
        with self.assertRaisesRegex(ValueError, 'semantic'):
            s.run(recipe, registry, resume=checkpoint)

    def test_checkpoint_wrong_recipe(self):
        recipe, registry, _ = fixture(); checkpoint = s.checkpoint(s.run(recipe, registry, stop_after=1))
        recipe['stages'][0]['inputs']['base'] += 1
        with self.assertRaisesRegex(ValueError, 'binding'):
            s.run(recipe, registry, resume=checkpoint)

    def test_changed_input_invalidates_only_causal_suffix(self):
        old, registry, _ = fixture(); new = deepcopy(old); new['stages'][0]['inputs']['base'] = 9
        self.assertEqual(s.invalidated(old, new, registry), ['rain', 'river', 'supply'])

    def test_changed_context_invalidates_every_stage(self):
        old, registry, _ = fixture(); new = deepcopy(old); new['context']['snapshot_id'] = 'other'
        self.assertEqual(s.invalidated(old, new, registry), ['independent', 'rain', 'river', 'supply'])

    def test_input_output_hash_changes(self):
        recipe, registry, _ = fixture(); a = s.run(recipe, registry)
        recipe['stages'][0]['inputs']['base'] = 7; b = s.run(recipe, registry)
        self.assertNotEqual(a['state']['rows']['supply']['invocation_sha256'], b['state']['rows']['supply']['invocation_sha256'])
        self.assertEqual(a['state']['rows']['independent'], b['state']['rows']['independent'])

    def test_cycle_rejects(self):
        recipe, registry, _ = fixture()
        recipe['stages'][0]['dependencies'] = {'cycle': {'stage_id': 'supply', 'output': 'water', 'port': recipe['stages'][0]['outputs']['water']}}
        with self.assertRaisesRegex(ValueError, 'cyclic'):
            s.run(recipe, registry)

    def test_duplicate_stage_rejects(self):
        recipe, registry, _ = fixture(); recipe['stages'].append(deepcopy(recipe['stages'][0]))
        with self.assertRaisesRegex(ValueError, 'unique'):
            s.run(recipe, registry)

    def test_unknown_producer_rejects(self):
        recipe, registry, _ = fixture(); recipe['stages'][0]['producer_id'] = 'unimplemented'
        with self.assertRaisesRegex(ValueError, 'registered'):
            s.run(recipe, registry)

    def test_wrong_producer_source_rejects(self):
        recipe, registry, _ = fixture(); recipe['stages'][0]['producer_sha256'] = 'b'*64
        with self.assertRaisesRegex(ValueError, 'execution'):
            s.run(recipe, registry)

    def test_live_source_verifier_used(self):
        recipe, registry, calls = fixture()
        def drift():
            raise ValueError('actual source changed')
        registry['sum']['verify'] = drift
        with self.assertRaisesRegex(ValueError, 'source changed'):
            s.run(recipe, registry)
        self.assertEqual(calls, [])

    def test_source_rechecked_after_execution(self):
        recipe, registry, _ = fixture(); state = [False]; original = registry['sum']['run']
        def run(*args):
            result = original(*args); state[0] = True; return result
        def verify():
            if state[0]:
                raise ValueError('source changed mid-call')
        registry['sum'].update(run=run, verify=verify)
        with self.assertRaisesRegex(ValueError, 'mid-call'):
            s.run(recipe, registry)

    def test_unit_mismatch_rejects(self):
        recipe, registry, _ = fixture(); recipe['stages'][1]['dependencies']['inflow']['port']['unit'] = 'mm'
        with self.assertRaisesRegex(ValueError, 'quantity'):
            s.run(recipe, registry)

    def test_spatial_support_mismatch_rejects(self):
        recipe, registry, _ = fixture(); recipe['stages'][1]['dependencies']['inflow']['port']['support_id'] = 'another-cell'
        with self.assertRaises(ValueError):
            s.run(recipe, registry)

    def test_temporal_support_mismatch_rejects(self):
        recipe, registry, _ = fixture(); recipe['stages'][1]['dependencies']['inflow']['port']['temporal_support'] = 'ten-years'
        with self.assertRaises(ValueError):
            s.run(recipe, registry)

    def test_producer_wrong_world_rejects(self):
        recipe, registry, _ = fixture(); original = registry['sum']['run']
        def wrong(*args):
            result = original(*args); result['context']['world_id'] = 'different'; return result
        registry['sum']['run'] = wrong
        with self.assertRaisesRegex(ValueError, 'world'):
            s.run(recipe, registry)

    def test_supplied_constraint_not_regeneration(self):
        recipe, registry, _ = fixture(); recipe['stages'][0]['inputs']['constraint'] = True
        with self.assertRaisesRegex(ValueError, 'regeneration'):
            s.run(recipe, registry)
        recipe['stages'][0]['mode'] = 'SUPPLIED_CONSTRAINT'
        result = s.run(recipe, registry)
        self.assertEqual(result['category_closure']['precipitation']['supplied_constraint_stage_ids'], ['rain'])
        self.assertEqual(result['category_closure']['precipitation']['generated_stage_ids'], [])

    def test_false_constraint_mode_rejects(self):
        recipe, registry, _ = fixture(); recipe['stages'][0]['mode'] = 'SUPPLIED_CONSTRAINT'
        with self.assertRaisesRegex(ValueError, 'regeneration'):
            s.run(recipe, registry)

    def test_acceptance_declaration_cannot_authorise_production(self):
        recipe, registry, _ = fixture()
        for row in recipe['stages']:
            row['acceptance']['status'] = 'DOMAIN_ACCEPTED'
        result = s.run(recipe, registry)
        self.assertFalse(result['production_authorised'])
        self.assertTrue(result['acceptance_declarations_are_not_verified_authority'])

    def test_mutating_producer_does_not_mutate_recipe(self):
        recipe, registry, _ = fixture(); preserved = deepcopy(recipe); original = registry['sum']['run']
        def mutator(context, inputs, dependencies):
            result = original(context, inputs, dependencies); inputs.clear(); dependencies.clear(); context.clear(); return result
        registry['sum']['run'] = mutator; s.run(recipe, registry)
        self.assertEqual(recipe, preserved)

    def test_reused_producer_output_cannot_mutate_accepted_product(self):
        recipe, registry, _ = fixture(); original = registry['sum']['run']; retained = []
        def producer(*args):
            result = original(*args)
            if retained:
                retained[0]['values']['water'] = 999
            else:
                retained.append(result)
            return result
        registry['sum']['run'] = producer
        result = s.run(recipe, registry)
        self.assertEqual(result['state']['rows']['independent']['product']['values']['water'], 1)
        for row in result['state']['rows'].values():
            self.assertEqual(row['product_sha256'], s.sha(row['product']))
        retained[0]['values']['water'] = 1000
        self.assertEqual(result['state']['rows']['independent']['product']['values']['water'], 1)

    def test_bool_cursor_rejects(self):
        recipe, registry, _ = fixture()
        with self.assertRaises(ValueError):
            s.run(recipe, registry, stop_after=True)

    def test_zero_cursor_safe(self):
        recipe, registry, calls = fixture(); result = s.run(recipe, registry, stop_after=0)
        self.assertEqual(result['state']['rows'], {}); self.assertEqual(calls, [])

    def test_nonfinite_and_non_json_refused(self):
        for value in (float('inf'), float('nan'), {'tuple': (1, 2)}, {1: 'bad'}):
            with self.assertRaises(ValueError):
                s.encoded(value)

    def test_nonempty_unknown_explanation_required(self):
        recipe, _, _ = fixture()
        with self.assertRaises(ValueError):
            s.emission(recipe['context'], recipe['stages'][0]['outputs'], {'water': None},
                evidence=E, source_status='UNKNOWN', status='UNKNOWN')

    def test_unknown_cannot_hide_nonnull_quantity(self):
        recipe, _, _ = fixture()
        with self.assertRaises(ValueError):
            s.emission(recipe['context'], recipe['stages'][0]['outputs'], {'water': 0},
                evidence=E, source_status='UNKNOWN', status='UNKNOWN', unresolved=['missing'])

    def test_unchanged_graph_no_invalidations(self):
        recipe, registry, _ = fixture(); self.assertEqual(s.invalidated(recipe, deepcopy(recipe), registry), [])


if __name__ == '__main__':
    unittest.main()
