"""Focused public integration; no full-world or full-year generation."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
from work.test_r22_registry import recipe as reference_recipe
from work.test_r23_registry import science
from work.generator_upgrade_r23 import registry as previous
from work.generator_upgrade_r24 import registry
from work.generator_upgrade_r21 import _snapshot_contract as snapshot


def bound(recipe, module=registry):
    result = deepcopy(recipe)
    pins = {}
    for stage in result['stages']:
        key = stage['producer_id'], snapshot.sha(stage['outputs']['result'])
        if key not in pins:
            pins[key] = module.registration(key[0], stage['outputs']['result'])['sha256']
        stage['producer_sha256'] = pins[key]
    return result


class RegistryTests(unittest.TestCase):
    def test_parity_reuse_restart_changed_demand_and_unrelated_producer(self):
        base = reference_recipe()
        old_recipe, new_recipe = bound(base, previous), bound(base)
        with tempfile.TemporaryDirectory(prefix='r24-g-') as directory:
            old_root, new_root = Path(directory)/'a', Path(directory)/'b'
            old_cold = previous.run(old_recipe, cache_root=old_root)
            new_cold = registry.run(new_recipe, cache_root=new_root)
            with mock.patch.object(registry,'Adapter',side_effect=AssertionError('warm hit built an inner adapter')):
                new_warm = registry.run(new_recipe, cache_root=new_root)
            old_warm = previous.run(old_recipe, cache_root=old_root)
            self.assertEqual(science(old_cold), science(new_cold))
            self.assertEqual(new_cold['graph'], new_warm['graph'])
            self.assertEqual(new_warm['execution']['computed_stage_ids'], [])
            resumed = registry.run(new_recipe, cache_root=new_root,
                resume=snapshot.checkpoint(new_cold['graph']))
            self.assertEqual(resumed['graph'], new_cold['graph'])
            changed = deepcopy(new_recipe)
            changed['stages'][1]['inputs']['rates']['water_m3'] = '1/200'
            rerun = registry.run(changed, cache_root=new_root)
            self.assertEqual(rerun['execution']['computed_stage_ids'], ['serve'])
            self.assertEqual(rerun['execution']['reused_stage_ids'], ['place'])
            extra = deepcopy(new_recipe['stages'][0])
            extra.update(stage_id='unrelated',producer_id='species_density',inputs={},
                dependencies={},missing_inputs=['explicit synthetic missing species register'])
            expanded = deepcopy(new_recipe)
            expanded['stages'].append(extra)
            expanded = bound(expanded)
            added = registry.run(expanded, cache_root=new_root, workers=1)
            self.assertEqual(added['execution']['reused_stage_ids'], ['place','serve'])
            self.assertEqual(added['execution']['computed_stage_ids'], ['unrelated'])
            self.assertEqual(added['graph']['state']['rows']['unrelated']['product']['status'],'UNKNOWN')
            changed_port = deepcopy(new_recipe)
            # The inherited fixture deliberately aliases its receipt port;
            # detach this one output so the parent really remains unchanged.
            changed_port['stages'][1]['outputs']['result'] = deepcopy(changed_port['stages'][1]['outputs']['result'])
            changed_port['stages'][1]['outputs']['result']['support_id'] = 'unrelated-output-change'
            changed_port = bound(changed_port)
            repinned = registry.run(changed_port, cache_root=new_root)
            self.assertEqual(repinned['execution']['reused_stage_ids'], ['place'])
            self.assertEqual(repinned['execution']['computed_stage_ids'], ['serve'])
            for phase, old, new in [('cold',old_cold,new_cold),('warm',old_warm,new_warm)]:
                before, after = old['elapsed_seconds'],new['elapsed_seconds']
                print(json.dumps({'r24_connected_measurement':phase,'baseline':'R23',
                    'before_seconds':before,'after_seconds':after,'saved_seconds':before-after,
                    'saved_percent':100*(before-after)/before,'scientific_products_equal':True,
                    'scope':'one pair: two-stage synthetic placement/freight; not whole-world'}))

    def test_actual_automatic_spawn_connections_and_warm_no_dispatch(self):
        recipe = bound(reference_recipe())
        extra = deepcopy(recipe['stages'][0])
        extra['stage_id'] = 'independent'
        recipe['stages'].append(extra)
        with tempfile.TemporaryDirectory(prefix='r24-p-') as directory:
            serial = registry.run(recipe,cache_root=Path(directory)/'s',workers=1)
            root = Path(directory)/'p'
            parallel = registry.run(recipe,cache_root=root)
            self.assertEqual(parallel['parallel']['effective_workers'],2)
            self.assertTrue(parallel['parallel']['worker_pids'])
            self.assertEqual(parallel['parallel']['timings']['peak_in_flight'],2)
            self.assertEqual(serial['graph'],parallel['graph'])
            warm = registry.run(recipe,cache_root=root)
            self.assertEqual(warm['graph'],serial['graph'])
            self.assertEqual(warm['parallel']['worker_pids'],[])
            self.assertEqual(warm['execution']['executed_stage_ids'],[])
            print(json.dumps({'r24_actual_spawn':{'serial_seconds':serial['elapsed_seconds'],
                'parallel_cold_seconds':parallel['elapsed_seconds'],
                'parallel_warm_seconds':warm['elapsed_seconds'],
                'scientific_products_equal':True,'scope':'tiny graph; matched fresh caches; process startup included'}}))

    def test_cleanup_drift_preserves_primary_error_and_final_checkpoint(self):
        recipe = bound(reference_recipe())
        native_verify, execute = registry.p.verify, registry.executor.run
        for primary in (True,False):
            state = {'failed':False}
            error = RuntimeError('original worker failure')
            error.snapshot_checkpoint = {'preserve':'original authenticated-prefix fixture'}
            def verify(sources):
                if state['failed']:
                    raise ValueError('final source drift')
                return native_verify(sources)
            def run(*args,**kwargs):
                if primary:
                    state['failed'] = True
                    raise error
                result = execute(*args,**kwargs)
                state['failed'] = True
                return result
            with mock.patch.object(registry.p,'verify',side_effect=verify), mock.patch.object(
                    registry.executor,'run',side_effect=run):
                with self.assertRaises(RuntimeError if primary else ValueError) as caught:
                    registry.run(recipe,cache=False,workers=1,stop_after=0)
            self.assertTrue(caught.exception.r24_cleanup_errors)
            if primary:
                self.assertIs(caught.exception,error)
                self.assertEqual(error.snapshot_checkpoint,{'preserve':'original authenticated-prefix fixture'})
            else:
                self.assertEqual(caught.exception.snapshot_checkpoint['state']['completed_stages'],0)

    def test_old_recipe_and_invalid_resource_options_rejected(self):
        recipe = reference_recipe()
        with self.assertRaisesRegex(ValueError,'actual registered execution differs'):
            registry.run(recipe,cache=False,workers=1)
        for options in ({'workers':0},{'memory_budget_mb':0},{'worker_memory_mb':True},
                        {'memory_budget_mb':100,'worker_memory_mb':512},{'scheduling':'invented'}):
            with self.assertRaises(ValueError):
                registry.run(recipe,cache=False,**options)


if __name__ == '__main__':
    unittest.main()
