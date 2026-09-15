"""Small actual tectonic/shared-runner parity, reuse and source-change checks."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
from statistics import median
import subprocess
import sys
import tempfile
import unittest
from work.test_r22_registry import recipe as reference
from work.test_r24_registry import bound
from work.generator_upgrade_r28 import registry as previous
from work.generator_upgrade_r29 import registry
from work.diadem_tectonics_r3 import snapshot

RECORD = {}
PACKAGE = Path(__file__).resolve().parents[1]/'outputs/diadem-tectonics-review-r1/verified-02/sandbox/work/stage4-rebuild'

def recipes(package):
    old = bound(reference(),previous)
    port = deepcopy(old['stages'][0]['outputs']['result'])
    pins = {name:hashlib.sha256((package/name).read_bytes()).hexdigest()
        for name in (snapshot.MANIFEST,*snapshot.FILES.values())}
    stage = dict(stage_id='tectonic',category='plate_tectonics',producer_id='tectonic_snapshot',
        producer_sha256=previous.registration('tectonic_snapshot',port)['sha256'],
        inputs=dict(package_dir=str(package),package_pins=pins,domain_decisions=None),
        dependencies={},outputs={'result':port},missing_inputs=[],mode='GENERATED',
        acceptance=dict(status='PENDING',evidence='Engineering parity, not domain acceptance'))
    old['stages'].append(stage)
    old['required_categories'].append('plate_tectonics')
    new = deepcopy(old)
    new['stages'][-1]['producer_sha256'] = registry.registration('tectonic_snapshot',port)['sha256']
    return old,new

def compare(before,after):
    return dict(before_s=before,after_s=after,saved_s=before-after,saved_percent=100*(before-after)/before)

def products(result):
    return {key:row['product'] for key,row in result['graph']['state']['rows'].items()}

class RegistryTests(unittest.TestCase):
    def test_workers_reject_different_orchestration_sources(self):
        sources = registry.p.sources()
        changed = dict(sources)
        changed[next(iter(changed))] = '0'*64
        with self.assertRaisesRegex(ValueError,'R29 source changed'):
            registry.worker_init({},False,str(PACKAGE),changed)

    def test_actual_runner_versions_cache_parallel_recovery_and_cli(self):
        old,new = recipes(PACKAGE)
        self.assertNotEqual(old['stages'][-1]['producer_sha256'],new['stages'][-1]['producer_sha256'])
        for stage in old['stages'][:2]:
            self.assertEqual(stage['producer_sha256'],registry.registration(
                stage['producer_id'],stage['outputs']['result'])['sha256'])
        with tempfile.TemporaryDirectory(prefix='r29-') as directory:
            root = Path(directory)
            before = previous.run(old,cache_root=root/'old',workers=1)
            after = registry.run(new,cache_root=root/'new',workers=1)
            self.assertEqual(products(before),products(after))
            self.assertEqual(after['preflight']['authoritative_parse_passes'],1)
            adopted = registry.run(new,cache_root=root/'old',workers=1)
            self.assertEqual(adopted['execution']['computed_stage_ids'],['tectonic'])
            self.assertEqual(adopted['execution']['reused_stage_ids'],['place','serve'])
            timings = {'r28':[],'r29':[]}
            for trial in range(3):
                cases = [('r28',previous,old),('r29',registry,new)]
                if trial%2: cases.reverse()
                for label,module,recipe in cases:
                    warm = module.run(recipe,cache_root=root/'old',expected_seconds=180)
                    self.assertEqual(products(warm),products(before))
                    self.assertEqual(warm['execution']['computed_stage_ids'],[])
                    self.assertEqual(warm['parallel']['worker_pids'],[])
                    timings[label].append(warm['elapsed_seconds'])
            resumed = registry.run(new,cache_root=root/'old',resume=registry.snapshot.checkpoint(after['graph']))
            self.assertEqual(resumed['graph'],after['graph'])
            self.assertEqual(resumed['execution']['computed_stage_ids'],[])
            parallel = registry.run(new,cache_root=root/'parallel',expected_seconds=180)
            self.assertEqual(parallel['graph'],after['graph'])
            self.assertEqual(parallel['parallel']['effective_workers'],2)
            self.assertTrue(parallel['parallel']['worker_pids'])
            self.assertEqual(parallel['parallel']['selection']['local_executed_stage_ids'],[])
            with self.assertRaisesRegex(ValueError,'registered execution differs'):
                registry.run(old,cache_root=root/'old',workers=2)
            plan = root/'plan.json'
            plan.write_text(json.dumps(registry.plan(new,180)),encoding='utf-8')
            cli = subprocess.run([sys.executable,'-B','-m','work.generator_upgrade_r29',str(plan),
                '--cache-root',str(root/'new'),'--workers','1'],capture_output=True,text=True)
            self.assertEqual(cli.returncode,0,cli.stderr)
            result = json.loads(cli.stdout)
            self.assertEqual(result['graph'],after['graph'])
            self.assertEqual(result['execution']['computed_stage_ids'],[])
            RECORD.update(cold_single_pair=compare(before['elapsed_seconds'],after['elapsed_seconds']),
                warm_samples=timings,warm_medians=compare(median(timings['r28']),median(timings['r29'])),
                scope='Three-stage population/freight plus fixed tectonic snapshot; not a full-world timing',
                scientific_products_equal=True,unrelated_stage_cache_reused=True,
                changed_tectonic_pin_required=True,restart_pass=True,real_forecast_workers_pass=True,
                cli_pass=True)

    def test_warm_result_cannot_hide_external_package_drift(self):
        with tempfile.TemporaryDirectory(prefix='r29-drift-') as directory:
            root = Path(directory)
            package = root/'p'
            package.mkdir()
            for name in (snapshot.MANIFEST,*snapshot.FILES.values()):
                shutil.copyfile(PACKAGE/name,package/name)
            _,new = recipes(package)
            # Isolate this one source-change guard from unrelated computations.
            new['stages'] = [new['stages'][-1]]
            new['required_categories'] = ['plate_tectonics']
            registry.run(new,cache_root=root/'cache',workers=1)
            changed = package/snapshot.FILES['events']
            changed.write_bytes(changed.read_bytes()+b' ')
            with self.assertRaises(ValueError):
                registry.run(new,cache_root=root/'cache',workers=1)

if __name__ == '__main__':
    result = unittest.main(exit=False).result
    if result.wasSuccessful():
        paths = sorted(Path('work/generator_upgrade_r29').glob('*.py'))
        paths += sorted(Path('work/diadem_tectonics_r3').glob('*.py'))
        RECORD['source_files'] = {str(path.resolve()):hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
        output = Path('outputs/tectonics-r3/integration-measurement.json')
        output.parent.mkdir(parents=True,exist_ok=True)
        output.write_text(json.dumps(RECORD,indent=2,sort_keys=True)+'\n',encoding='utf-8')
        print(json.dumps(RECORD,sort_keys=True))
    sys.exit(0 if result.wasSuccessful() else 1)
