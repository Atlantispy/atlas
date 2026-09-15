"""Focused cost-aware public integration and one small matched timing pair."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from work.test_r22_registry import recipe as reference_recipe
from work.test_r24_registry import bound
from work.test_r23_registry import science
from work.generator_upgrade_r24 import registry as previous
from work.generator_upgrade_r25 import registry


def recipes():
    old = bound(reference_recipe(),previous)
    extra = deepcopy(old['stages'][0])
    extra['stage_id'] = 'independent'
    old['stages'].append(extra)
    return old,bound(old,registry)


class RegistryTests(unittest.TestCase):
    def test_small_auto_is_serial_exact_and_cached_with_explicit_override(self):
        old_recipe,new_recipe = recipes()
        with tempfile.TemporaryDirectory(prefix='r25-g-') as directory:
            root = Path(directory)
            old = previous.run(old_recipe,cache_root=root/'old')
            automatic = registry.run(new_recipe,cache_root=root/'auto')
            serial = registry.run(new_recipe,cache_root=root/'serial',workers=1)
            explicit = registry.run(new_recipe,cache_root=root/'parallel',workers=2)
            for result in (automatic,serial,explicit):
                self.assertEqual(science(result),science(old))
            self.assertEqual(automatic['graph'],serial['graph'])
            self.assertEqual(explicit['graph'],serial['graph'])
            self.assertEqual(automatic['parallel']['worker_pids'],[])
            self.assertEqual(automatic['parallel']['effective_workers'],1)
            self.assertFalse(automatic['parallel']['selection']['promoted'])
            self.assertEqual(len(automatic['parallel']['selection']['local_executed_stage_ids']),3)
            self.assertTrue(explicit['parallel']['worker_pids'])
            self.assertEqual(explicit['parallel']['effective_workers'],2)
            warm = registry.run(new_recipe,cache_root=root/'auto')
            self.assertEqual(warm['graph'],automatic['graph'])
            self.assertEqual(warm['parallel']['worker_pids'],[])
            self.assertEqual(warm['parallel']['selection']['local_executed_stage_ids'],[])
            self.assertEqual(warm['execution']['executed_stage_ids'],[])
            resumed = registry.run(new_recipe,cache_root=root/'auto',
                resume=registry.snapshot.checkpoint(automatic['graph']))
            self.assertEqual(resumed['graph'],automatic['graph'])
            changed = deepcopy(new_recipe)
            changed['stages'][1]['inputs']['rates']['water_m3'] = '1/200'
            rerun = registry.run(changed,cache_root=root/'auto')
            self.assertEqual(rerun['execution']['computed_stage_ids'],['serve'])
            before,after = old['elapsed_seconds'],automatic['elapsed_seconds']
            print(json.dumps({'r25_timing':{'scope':'one pair; actual three-stage synthetic placement/freight; matched cold caches; startup included',
                'r24_auto_seconds':before,'r25_auto_seconds':after,
                'saved_seconds':before-after,'saved_percent':100*(before-after)/before,
                'r25_forced_serial_seconds':serial['elapsed_seconds'],
                'r25_forced_parallel_seconds':explicit['elapsed_seconds'],
                'r25_cached_seconds':warm['elapsed_seconds'],
                'scientific_products_equal':True,'whole_generator_gain_claimed':False}}))

    def test_boundaries_wave_memory_and_early_stop(self):
        old_recipe,recipe = recipes()
        with self.assertRaisesRegex(ValueError,'actual registered execution differs'):
            registry.run(old_recipe,cache=False)
        for options in ({'workers':0},{'startup_budget_s':-1},{'startup_budget_s':float('nan')},
                        {'startup_budget_s':True},{'memory_budget_mb':100}):
            with self.assertRaises(ValueError):
                registry.run(recipe,cache=False,**options)
        with mock.patch.object(registry,'AdaptiveBackend',side_effect=AssertionError('unneeded adaptive backend')):
            stopped = registry.run(recipe,cache=False,stop_after=0)
            limited = registry.run(recipe,cache=False,memory_budget_mb=512,worker_memory_mb=512)
        self.assertEqual(stopped['graph']['state']['completed_stages'],0)
        self.assertEqual(limited['parallel']['worker_pids'],[])
        self.assertEqual(limited['parallel']['effective_workers'],1)
        wave = registry.run(recipe,cache=False,scheduling='wave')
        self.assertEqual(wave['graph'],limited['graph'])
        self.assertEqual(wave['parallel']['worker_pids'],[])

    def test_failure_checkpoint_preserved_and_module_entrypoint_captured(self):
        _,recipe = recipes()
        failed_recipe = deepcopy(recipe)
        failed_recipe['stages'][1]['inputs']['rates']['water_m3'] = 'invalid rational fixture'
        with tempfile.TemporaryDirectory(prefix='r25-e-') as directory:
            root = Path(directory)
            with self.assertRaises(ValueError) as caught:
                registry.run(failed_recipe,cache_root=root/'cache')
            checkpoint = caught.exception.snapshot_checkpoint
            self.assertEqual(checkpoint['state']['completed_stages'],2)
            recovered = registry.run(recipe,cache_root=root/'cache')
            self.assertEqual(recovered['execution']['computed_stage_ids'],['serve'])
            source = root/'recipe.json'
            source.write_text(json.dumps(recipe),encoding='utf-8')
            completed = subprocess.run([sys.executable,'-B','-m','work.generator_upgrade_r25',
                str(source),'--no-cache','--workers','1'],capture_output=True,text=True,check=False)
            self.assertEqual(completed.returncode,0,completed.stderr)
            cli = json.loads(completed.stdout)
            self.assertEqual(cli['graph'],recovered['graph'])
            self.assertEqual(cli['parallel']['worker_pids'],[])


if __name__ == '__main__':
    unittest.main()
