"""Small native/adapter/cache/forecast-region integration; no full region."""
from copy import deepcopy
import json
from pathlib import Path
from statistics import median
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from work.generator_upgrade_r18 import working as old_working
from work.geology_r1 import working
from work.generator_upgrade_r29 import registry as old_registry
from work.generator_upgrade_r30 import registry, region
from work.test_r22_registry import recipe as social_recipe
from work.test_r24_registry import bound

RECORD = {}


def science(value):
    result = deepcopy(value['scientific'])
    result.pop('source_sha256', None)
    result['regional_input'].pop('execution_binding_sha256', None)
    return result


def compare(before, after):
    return dict(before_seconds=before,after_seconds=after,saved_seconds=before-after,
                saved_percent=100*(before-after)/before)


def context(spec):
    return {**{key:spec['context'][key] for key in
        ('world_id','snapshot_id','spatial_frame_id','vertical_reference')},
        'calendar_id':'SYNTHETIC TEST fixed snapshot calendar label',
        'scenario_id':'SYNTHETIC TEST geology optimisation integration'}


class Integration(unittest.TestCase):
    def test_bounded_pool_history_and_cancel_cleanup(self):
        from types import SimpleNamespace
        owner = region._Pool()
        owner.pool = SimpleNamespace(_pending={},_seen={'one'},_job_timings=[{}],
                                     _execute_timings=[{}],_peak_in_flight=2)
        owner.finish_window()
        self.assertFalse(owner.pool._seen)
        self.assertFalse(owner.pool._job_timings)
        fake = {'stages':[]}
        def execute(*args, **kwargs): return {'graph':{}}
        with patch.object(region, 'recipes', return_value=iter([fake])), \
             patch.object(region, 'clone', return_value=execute), \
             patch.object(region.p, 'sources', return_value={}), \
             patch.object(region.p, 'verify'), \
             patch.object(region._Pool, 'close', side_effect=ValueError('close failure')):
            iterator = region.iter_region({})
            next(iterator)
            with self.assertRaisesRegex(ValueError, 'close failure'):
                iterator.close()

    def test_native_combined_measurement(self):
        spec = working.inputs()
        points = dict(list(working.case_supports(spec).items())[:13])
        # Initialise the unchanged native runtime outside paired measurements.
        registry.geology.native.identity()
        pairs = []
        for n in range(3):
            times, results = {}, {}
            for label, module in ((('old',old_working),('new',working)) if n%2 == 0
                                  else (('new',working),('old',old_working))):
                start = time.perf_counter(); results[label] = module.build(points)
                times[label] = time.perf_counter()-start
            self.assertEqual(science(results['old']), science(results['new']))
            pairs.append(times)
        RECORD['native_combined'] = dict(compare(median(p['old'] for p in pairs),
            median(p['new'] for p in pairs)),pairs=pairs,supports=13,
            scope='Complete native build with all source guards and one-use prepared setup; runtime imports excluded')

    def test_shared_pin_cache_and_cli(self):
        old = bound(social_recipe(), old_registry)
        spec = working.inputs(); points = working.case_supports(spec)
        port = deepcopy(old['stages'][0]['outputs']['result'])
        for index, point in enumerate(list(points.items())[:2]):
            old['stages'].append(dict(stage_id='geo-'+str(index),category='geology',
                producer_id='regional_geology',producer_sha256=old_registry.registration('regional_geology',port)['sha256'],
                inputs=dict(supports=dict([point]),alternative='DEFAULT',owner_input_sha256=working.INPUT_SHA),
                dependencies={},outputs={'result':port},missing_inputs=[],mode='GENERATED',
                acceptance=dict(status='PENDING',evidence='SYNTHETIC TEST optimiser integration')))
        old['required_categories'].append('geology')
        new = deepcopy(old)
        for stage in new['stages'][2:]:
            stage['producer_sha256'] = registry.registration('regional_geology',port)['sha256']
        self.assertNotEqual(old['stages'][2]['producer_sha256'],new['stages'][2]['producer_sha256'])
        for stage in old['stages'][:2]:
            self.assertEqual(stage['producer_sha256'],registry.registration(stage['producer_id'],port)['sha256'])
        sources = registry.p.sources(); altered = dict(sources)
        altered[next(iter(altered))] = '0'*64
        with self.assertRaises(ValueError): registry.worker_init({},False,'.',altered)
        with tempfile.TemporaryDirectory(prefix='r30-') as tmp:
            root = Path(tmp)
            a = old_registry.run(old,cache_root=root/'old',workers=1)
            b = registry.run(new,cache_root=root/'new',workers=1)
            for key in ('geo-0','geo-1'):
                self.assertEqual(science(a['graph']['state']['rows'][key]['product']['values']['result']),
                                 science(b['graph']['state']['rows'][key]['product']['values']['result']))
            reused = registry.run(new,cache_root=root/'old',workers=1)
            self.assertEqual(reused['execution']['reused_stage_ids'],['place','serve'])
            with patch.object(working, 'Prepared', side_effect=AssertionError('cached run decoded inputs')):
                start = time.perf_counter()
                warm = registry.run(new,cache_root=root/'old',expected_seconds=180)
                warm_seconds = time.perf_counter()-start
                resumed = registry.run(new,cache_root=root/'old',resume=registry.snapshot.checkpoint(warm['graph']))
            self.assertEqual(warm['graph'],b['graph'])
            self.assertEqual(resumed['graph'],b['graph'])
            self.assertEqual(warm['execution']['computed_stage_ids'],[])
            with self.assertRaises(ValueError): registry.run(old,cache_root=root/'old',workers=1)
            with patch.object(working, 'validate_sources', side_effect=ValueError('external input drift')):
                # The adapter captures its validation callable; patch the bound
                # name in that private method's globals to simulate a fresh failure.
                with patch.dict(registry.geology.Adapter.prepare.__globals__,
                                {'_regional_sources':working.validate_sources}):
                    with self.assertRaisesRegex(ValueError,'external input drift'):
                        registry.run(new,cache_root=root/'old',workers=1)
            plan = root/'plan.json'; plan.write_text(json.dumps(new),encoding='utf-8')
            cli = subprocess.run([sys.executable,'-B','-m','work.generator_upgrade_r30',str(plan),
                                  '--cache-root',str(root/'old'),'--workers','1'],capture_output=True,text=True)
            self.assertEqual(cli.returncode,0,cli.stderr)
            self.assertEqual(json.loads(cli.stdout)['graph'],b['graph'])
            RECORD['shared_cold_single_pair'] = dict(compare(a['elapsed_seconds'],b['elapsed_seconds']),
                scope='Two one-support geology jobs plus retained placement/freight; imports warm, empty result caches')
            RECORD['shared_warm_seconds'] = warm_seconds
            RECORD['shared_cache_restart_cli_and_drift_checks'] = True

    def test_region_windows_reuse_workers_and_authenticated_cache(self):
        spec = working.inputs(); ctx = context(spec)
        with self.assertRaises(ValueError):
            next(region.recipes(dict(ctx,world_id='wrong'),stop_after_batches=1))
        with self.assertRaises(ValueError):
            next(region.recipes(ctx,window_batches=129,stop_after_batches=1))
        with tempfile.TemporaryDirectory(prefix='g1-region-') as tmp:
            root = Path(tmp)
            start = time.perf_counter()
            serial = list(region.iter_region(ctx,batch_size=1,window_batches=2,
                stop_after_batches=4,cache_root=root/'serial',workers=1))
            serial_s = time.perf_counter()-start
            start = time.perf_counter()
            parallel = list(region.iter_region(ctx,batch_size=1,window_batches=2,
                stop_after_batches=4,cache_root=root/'parallel',expected_seconds=180))
            parallel_s = time.perf_counter()-start
            self.assertEqual([r['graph'] for r in serial],[r['graph'] for r in parallel])
            first = parallel[0]['parallel']['worker_pids']
            self.assertTrue(first)
            self.assertEqual(first,parallel[1]['parallel']['worker_pids'])
            self.assertEqual(parallel[0]['parallel']['effective_workers'],2)
            warm = list(region.iter_region(ctx,batch_size=1,window_batches=2,
                stop_after_batches=4,cache_root=root/'parallel',expected_seconds=180))
            self.assertTrue(all(not r['parallel']['worker_pids'] for r in warm))
            self.assertTrue(all(not r['execution']['computed_stage_ids'] for r in warm))
            RECORD['tiny_region_serial_parallel'] = dict(compare(serial_s,parallel_s),
                scope='Four one-support batches in two windows; cold worker startup included;180s is a forecast-policy fixture, not measured runtime',
                persistent_worker_pids=first,cache_restart_reuses_all=True)


if __name__ == '__main__':
    result = unittest.main(exit=False)
    if result.result.wasSuccessful():
        import hashlib
        paths = [path for root in ('work/geology_r1','work/generator_upgrade_r30')
                 for path in Path(root).glob('*.py')]
        RECORD['source_files'] = {str(path.resolve()):hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
        RECORD['focused_integration_tests_passed'] = result.result.testsRun
        print(json.dumps(RECORD))
    else:
        raise SystemExit(1)
