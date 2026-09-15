"""One tiny native DAG, bounded before/after timings; no world or annual run."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from statistics import median
import subprocess
import sys
import tempfile
import unittest
from work.test_r27_registry import recipe
from work.generator_upgrade_r27 import registry as previous
from work.generator_upgrade_r28 import registry

RECORD = {}


def comparison(before,after):
    return {'before_s':before,'after_s':after,'saved_s':before-after,
        'saved_percent':100*(before-after)/before}


class RegistryTests(unittest.TestCase):
    def test_native_parity_cache_recovery_parallel_and_timing(self):
        value = recipe()
        with tempfile.TemporaryDirectory(prefix='r28-') as directory:
            root = Path(directory)
            before = previous.run(value,cache_root=root/'old',workers=1)
            after = registry.run(value,cache_root=root/'new',workers=1)
            self.assertEqual(before['graph'],after['graph'])
            self.assertEqual(after['preflight']['authoritative_parse_passes'],1)
            self.assertEqual(after['preflight']['duplicate_parse_passes_avoided'],1)
            timings = {'r27':[], 'r28':[]}
            # Three alternating warm pairs reduce order noise without more science.
            for trial in range(3):
                modules = [('r27',previous),('r28',registry)]
                if trial % 2: modules.reverse()
                for label,module in modules:
                    result = module.run(value,cache_root=root/'old',expected_seconds=180)
                    self.assertEqual(result['graph'],before['graph'])
                    self.assertEqual(result['execution']['computed_stage_ids'],[])
                    self.assertEqual(result['parallel']['worker_pids'],[])
                    timings[label].append(result['elapsed_seconds'])
            resumed = registry.run(value,cache_root=root/'old',
                resume=registry.snapshot.checkpoint(before['graph']))
            self.assertEqual(resumed['graph'],before['graph'])
            self.assertEqual(resumed['execution']['computed_stage_ids'],[])
            changed = deepcopy(value)
            changed['stages'][1]['inputs']['rates']['water_m3'] = '1/200'
            rerun = registry.run(changed,cache_root=root/'old',workers=1)
            self.assertEqual(rerun['execution']['computed_stage_ids'],['serve'])
            self.assertEqual(set(rerun['execution']['reused_stage_ids']),{'place','independent'})
            # Actual native workers, first ready pair, no preliminary local jobs.
            parallel = registry.run(value,cache_root=root/'parallel',expected_seconds=180)
            self.assertEqual(parallel['graph'],before['graph'])
            self.assertEqual(parallel['parallel']['effective_workers'],2)
            self.assertTrue(parallel['parallel']['worker_pids'])
            self.assertEqual(parallel['parallel']['selection']['local_executed_stage_ids'],[])
            # Original semantic replay remains intact and shares the same parse.
            replay = registry.run(value,cache=False,resume=registry.snapshot.checkpoint(before['graph']))
            self.assertEqual(replay['graph'],before['graph'])
            self.assertTrue(replay['execution']['uncached_semantic_replay'])
            self.assertEqual(replay['preflight']['duplicate_parse_passes_avoided'],1)
            path = root/'p.json'
            path.write_text(json.dumps(registry.plan(value,180)),encoding='utf-8')
            cli = subprocess.run([sys.executable,'-B','-m','work.generator_upgrade_r28',str(path),
                '--cache-root',str(root/'new'),'--workers','1'],capture_output=True,text=True)
            self.assertEqual(cli.returncode,0,cli.stderr)
            cli_result = json.loads(cli.stdout)
            self.assertEqual(cli_result['graph'],before['graph'])
            self.assertEqual(cli_result['execution']['computed_stage_ids'],[])
            RECORD.update(cold_single_pair=comparison(before['elapsed_seconds'],after['elapsed_seconds']),
                warm_three_alternating_pairs=timings,
                warm_medians=comparison(median(timings['r27']),median(timings['r28'])),
                stage_count=3,scope='Small population placement/freight DAG; not whole-Diadem savings',
                native_graph_equal=True,prior_cache_reused=True,selective_invalidation=True,
                forecast_parallel_first_jobs=True,authenticated_restart=True,uncached_semantic_replay=True,
                cli_pass=True,authoritative_parses_per_run=1)


if __name__ == '__main__':
    result = unittest.main(exit=False).result
    if result.wasSuccessful():
        # Machine-generated evidence, including actual source bytes used in this run.
        paths = sorted(Path('work/generator_upgrade_r28').glob('*.py'))
        RECORD['source_files'] = {str(path.resolve()):hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
        output = Path('outputs/generator-upgrade-r28/measurement.json')
        output.parent.mkdir(parents=True,exist_ok=True)
        output.write_text(json.dumps(RECORD,indent=2,sort_keys=True)+'\n',encoding='utf-8')
        print(json.dumps(RECORD,sort_keys=True))
    sys.exit(0 if result.wasSuccessful() else 1)
