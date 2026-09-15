"""One tiny actual worker run; no long computation, probes or whole-world run."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from work.test_r22_registry import recipe as reference
from work.test_r24_registry import bound
from work.generator_upgrade_r26 import registry as previous
from work.generator_upgrade_r27 import registry


def recipe():
    value = bound(reference(),previous)
    independent = deepcopy(value['stages'][0])
    independent['stage_id'] = 'independent'
    value['stages'].append(independent)
    return value


class RegistryTests(unittest.TestCase):
    def test_first_jobs_are_parallel_native_parity_r26_reuse_and_cli(self):
        value = recipe()
        with tempfile.TemporaryDirectory(prefix='r27-') as directory:
            root = Path(directory)
            old = previous.run(value,cache_root=root/'old',workers=1)
            actual = registry.run(registry.plan(value,180),cache_root=root/'new')
            self.assertEqual(actual['graph'],old['graph'])
            self.assertEqual(actual['parallel']['effective_workers'],2)
            self.assertTrue(actual['parallel']['worker_pids'])
            self.assertEqual(actual['parallel']['selection']['local_executed_stage_ids'],[])
            self.assertEqual(actual['execution_policy']['required_prerequisite_runs'],0)
            warm = registry.run(value,expected_seconds=180,cache_root=root/'new')
            reused_prior = registry.run(value,expected_seconds=180,cache_root=root/'old')
            for result in (warm,reused_prior):
                self.assertEqual(result['graph'],old['graph'])
                self.assertEqual(result['execution']['computed_stage_ids'],[])
                self.assertEqual(result['parallel']['worker_pids'],[])
            resumed = registry.run(value,expected_seconds=121,cache_root=root/'old',
                resume=registry.snapshot.checkpoint(old['graph']))
            self.assertEqual(resumed['graph'],old['graph'])
            path = root/'p.json'
            path.write_text(json.dumps(registry.plan(value,180)),encoding='utf-8')
            cli = subprocess.run([sys.executable,'-B','-m','work.generator_upgrade_r27',str(path),
                '--workers','1','--no-cache'],capture_output=True,text=True)
            self.assertEqual(cli.returncode,0,cli.stderr)
            result = json.loads(cli.stdout)
            self.assertEqual(result['graph'],old['graph'])
            self.assertEqual(result['parallel']['effective_workers'],1)
            self.assertEqual(result['execution_policy']['expected_seconds'],180)
            print(json.dumps({'r27_policy_check':{'graph_stage_count':3,
                'forecast_seconds_for_branch_test_only':180,'prior_r26_serial_s':old['elapsed_seconds'],
                'forecast_parallel_s':actual['elapsed_seconds'],'warm_s':warm['elapsed_seconds'],
                'actual_parallel_before_any_local_job':True,'native_graph_equal':True,
                'speedup_claimed':False}}))

    def test_bad_forecasts_rejected_without_generation(self):
        for amount in (True,-1,float('inf'),float('nan'),'180',10**400):
            with self.assertRaises(ValueError): registry.plan({},amount)
        with self.assertRaisesRegex(ValueError,'twice'):
            registry.run(registry.plan({},180),expected_seconds=180)
        with self.assertRaisesRegex(ValueError,'exact R27 execution plan'):
            registry.run({'schema':registry.PLAN_SCHEMA,'recipe':{},'expected_seconds':180,'extra':True})
        with self.assertRaises(ValueError): registry.run({},parallel_threshold_s=0)


if __name__ == '__main__': unittest.main()
