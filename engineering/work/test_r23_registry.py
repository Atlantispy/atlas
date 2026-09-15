"""Bounded native-result parity, reuse/restart and registration regressions."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from work.test_r22_registry import recipe as reference_recipe
from work.generator_upgrade_r22 import registry as original
from work.generator_upgrade_r23 import registry
from work.generator_upgrade_r21 import _snapshot_contract as snapshot
from work.generator_runtime_r12.store import CacheError


def recipe():
    result = reference_recipe()
    for stage in result['stages']:
        # Explicit new test recipe binding, not silent production repinning.
        stage['producer_sha256'] = registry.registration(stage['producer_id'],
            stage['outputs']['result'])['sha256']
    return result


def science(result):
    graph = result['graph']
    return {'products': {key: row['product'] for key, row in graph['state']['rows'].items()},
            'category_closure': graph['category_closure'], 'status': graph['status']}


class RegistryTests(unittest.TestCase):
    def test_native_parity_cache_checkpoint_invalidation_and_corruption(self):
        before_recipe, after_recipe = reference_recipe(), recipe()
        with tempfile.TemporaryDirectory(prefix='r23-integration-') as directory:
            old_root = Path(directory)/'old'
            new_root = Path(directory)/'new'
            old_cold = original.run(before_recipe, cache_root=old_root)
            new_cold = registry.run(after_recipe, cache_root=new_root)
            old_warm = original.run(before_recipe, cache_root=old_root)
            new_warm = registry.run(after_recipe, cache_root=new_root)
            self.assertEqual(science(old_cold), science(new_cold))
            self.assertEqual(old_cold['graph'], old_warm['graph'])
            self.assertEqual(new_cold['graph'], new_warm['graph'])
            self.assertEqual(new_warm['execution']['computed_stage_ids'], [])
            self.assertEqual(new_warm['execution']['reused_stage_ids'], ['place', 'serve'])
            self.assertEqual(new_warm['optimisation']['unique_source_bindings'], 1)
            resumed = registry.run(after_recipe, cache_root=new_root,
                resume=snapshot.checkpoint(new_cold['graph']))
            self.assertEqual(resumed['graph'], new_cold['graph'])
            changed = deepcopy(after_recipe)
            changed['stages'][1]['inputs']['rates']['water_m3'] = '1/200'
            rerun = registry.run(changed, cache_root=new_root)
            self.assertEqual(rerun['execution']['computed_stage_ids'], ['serve'])
            self.assertEqual(rerun['execution']['reused_stage_ids'], ['place'])
            key = new_cold['graph']['state']['rows']['place']['invocation_sha256']
            paths = list(new_root.glob('*/'+key+'.json'))
            self.assertEqual(len(paths), 1)
            paths[0].write_bytes(b'{}')
            with self.assertRaises(CacheError):
                registry.run(after_recipe, cache_root=new_root)
            measurements = []
            for phase, old, new in [('cold', old_cold, new_cold), ('warm', old_warm, new_warm)]:
                before, after = old['elapsed_seconds'], new['elapsed_seconds']
                measurements.append({'phase': phase, 'r22_seconds': before,
                    'r23_seconds': after, 'saved_seconds': before-after,
                    'saved_percent': 100*(before-after)/before})
            print(json.dumps({'r23_measurement': 'two-stage synthetic placement/freight graph',
                'pairs_per_phase': 1, 'measurements': measurements,
                'scientific_products_equal': True, 'not_whole_world_speedup': True}))

    def test_repeated_registration_unknown_closure_and_port_conflict(self):
        graph = recipe()
        prototype = graph['stages'][0]
        graph['required_categories'] = ['populations']
        graph['stages'] = []
        for index in range(6):
            stage = deepcopy(prototype)
            stage['stage_id'] = 'missing-'+str(index)
            stage['missing_inputs'] = ['deliberate incomplete source fixture']
            graph['stages'].append(stage)
        with mock.patch.object(registry, '_registration', wraps=registry._registration) as build:
            result = registry.run(graph, cache=False)
            self.assertEqual(build.call_count, 1)
        self.assertEqual(result['optimisation']['unique_registrations'], 1)
        self.assertEqual(result['execution']['executed_stage_ids'], [])
        self.assertEqual(result['graph']['status'], 'INCOMPLETE')
        self.assertTrue(all(row['product']['status'] == 'UNKNOWN'
                            for row in result['graph']['state']['rows'].values()))
        graph['stages'][1]['outputs']['result']['support_id'] = 'different-support'
        with self.assertRaisesRegex(ValueError, 'different port binding'):
            registry.run(graph, cache=False)

    def test_old_recipe_not_silently_repinned_and_native_fallback(self):
        with self.assertRaisesRegex(ValueError, 'actual registered execution differs'):
            registry.run(reference_recipe(), cache=False)
        port = recipe()['stages'][0]['outputs']['result']
        with mock.patch.object(original, 'binding', return_value={'native-fallback': True}) as full:
            registered = registry.registration('moving_roots', port, cache=False)
            registered['verify']()
            self.assertEqual(full.call_count, 2)


if __name__ == '__main__':
    unittest.main()
