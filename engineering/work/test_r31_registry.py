"""Focused changed-route/source/cache/worker integration, no world/year run."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from work.generator_upgrade_r26 import physical
from work.generator_upgrade_r30 import registry as previous
from work.generator_upgrade_r31 import registry, topography, region
from work.topography_r1 import terrain
from work.topography_r1_fixture import fixture
from work.test_r22_moving_roots import recipe as rooted_recipe

PORT = {'quantity':'BOUND_COMPONENT_RECEIPT','unit':'1',
        'support_id':'SYNTHETIC TEST shared topography interfaces',
        'temporal_support':'SYNTHETIC TEST bounded interval'}
CONTEXT = {'world_id':'SYNTHETIC_NOT_DIADEM', 'snapshot_id':'R31_INTERFACE_ONLY',
           'spatial_frame_id':'LOCAL_METRES_EAST_SOUTH','vertical_reference':'LOCAL_METRES_UP',
           'calendar_id':'SYNTHETIC TEST interface calendar',
           'scenario_id':'SYNTHETIC TEST no physical acceptance'}


def stage(identity, operation, inputs, dependencies=None, module=registry):
    return {'stage_id':identity,'category':registry.OPERATIONS[operation][0],
        'producer_id':operation,'producer_sha256':module.registration(operation,PORT)['sha256'],
        'inputs':deepcopy(inputs),'dependencies':{} if dependencies is None else deepcopy(dependencies),
        'outputs':{'result':deepcopy(PORT)},'missing_inputs':[], 'mode':'GENERATED',
        'acceptance':{'status':'PENDING','evidence':'Synthetic engineering integration only'}}


def recipe(stages, context=None):
    return {'schema':'diadem.snapshot-graph-recipe.r11',
        'context':deepcopy(CONTEXT if context is None else context),
        'required_categories':sorted({item['category'] for item in stages}),
        'stages':stages,'evidence':'Bounded source-bound optimisation verification only'}


def value(result, name):
    return result['graph']['state']['rows'][name]['product']['values']['result']


def normal(value):
    """Only an explicit numerical-composition description changes, not physics."""
    if isinstance(value, dict):
        return {key:normal(item) for key,item in value.items() if key != 'numerical_composition'}
    if isinstance(value, list):
        return [normal(item) for item in value]
    return value


class Integration(unittest.TestCase):
    def test_exact_changed_inventory_and_unchanged_pins(self):
        expected = {'terrain_from_seed','terrain_advance','terrain_view','moving_roots',
                    'geological_terrain_step','surface_water_route'}
        self.assertEqual(set(topography.OPERATIONS), expected)
        changed = {op for op in registry.OPERATIONS if
            registry.registration(op,PORT)['sha256'] != previous.registration(op,PORT)['sha256']}
        self.assertEqual(changed, expected)
        self.assertEqual(len(registry.OPERATIONS)-len(changed),26)
        from work.generator_upgrade_r30 import region as old_region
        self.assertIs(region.iter_region,old_region.iter_region)
        sources = registry.p.sources()
        altered = deepcopy(sources)
        altered['sources'][next(iter(altered['sources']))] = '0'*64
        with self.assertRaises(ValueError):
            registry.worker_init({},False,'.',altered)

    def test_surface_and_geological_step_parity_cache_and_source_guard(self):
        samples = physical.fixtures()
        names = ('surface_water_route','geological_terrain_step')
        plan = recipe([stage(op,op,samples[op]) for op in names])
        with tempfile.TemporaryDirectory(prefix='r31-phys-') as tmp:
            cold = registry.run(plan,cache_root=tmp,workers=1)
            for op in names:
                direct = physical.baseline(op,samples[op])
                self.assertEqual(normal(value(cold,op)),normal(direct))
            with patch.object(topography.Adapter,'run',side_effect=AssertionError('warm compute')):
                warm = registry.run(plan,cache_root=tmp,workers=1)
            self.assertEqual(cold['graph'],warm['graph'])
            self.assertEqual(warm['execution']['computed_stage_ids'],[])
            with patch.object(topography.consumer,'verify',side_effect=ValueError('external input drift')):
                with self.assertRaisesRegex(ValueError,'external input drift'):
                    registry.run(plan,cache_root=tmp,workers=1)
            obsolete = deepcopy(plan)
            obsolete['stages'][0]['producer_sha256'] = previous.registration(names[0],PORT)['sha256']
            with self.assertRaises(ValueError):
                registry.run(obsolete,cache_root=tmp,workers=1)

    def test_terrain_connection_explicit_import_and_warm_resume(self):
        seed, old_initial, new_initial, forcing = fixture()
        clock = new_initial['body']['clock']
        edge = lambda ident:{'envelope':{'stage_id':ident,'output':'result','port':deepcopy(PORT)}}
        stages = [stage('seed','terrain_from_seed',{'snapshot':seed,'clock':clock}),
                  stage('advance','terrain_advance',{'forcing':forcing},edge('seed')),
                  stage('view','terrain_view',{},edge('advance'))]
        plan = recipe(stages)
        direct = terrain.advance(new_initial,forcing)
        with tempfile.TemporaryDirectory(prefix='r31-terr-') as tmp:
            result = registry.run(plan,cache_root=tmp,workers=1)
            self.assertEqual(value(result,'advance')['body'],direct['body'])
            self.assertEqual(value(result,'view'),terrain.view(direct))
            with patch.object(topography.Adapter,'run',side_effect=AssertionError('warm compute')), \
                 patch.object(terrain,'verify',side_effect=AssertionError('cached history replay')):
                warm = registry.run(plan,cache_root=tmp,workers=1,
                    resume=registry.snapshot.checkpoint(result['graph']))
            self.assertEqual(warm['graph'],result['graph'])
            self.assertEqual(warm['execution']['computed_stage_ids'],[])
            with patch.object(terrain,'_decision',side_effect=ValueError('physical decision drift')):
                with self.assertRaisesRegex(ValueError,'physical decision drift'):
                    registry.run(plan,cache_root=tmp,workers=1)
            adapter = topography.Adapter('terrain_advance',cache=False)
            changed = deepcopy(value(result,'advance'))
            changed['body']['elapsed_seconds'] = '0'
            with self.assertRaisesRegex(ValueError,'envelope/source/namespace'):
                adapter.validate_result(changed,{'forcing':forcing},{'envelope':value(result,'seed')})
            wrong_forcing = deepcopy(forcing)
            wrong_forcing['duration_years'] = '1/2000'
            with self.assertRaisesRegex(ValueError,'forcing/state/clock'):
                adapter.validate_result(value(result,'advance'),{'forcing':wrong_forcing},
                                        {'envelope':value(result,'seed')})
            invalid = recipe([stage('old','terrain_advance',{'envelope':old_initial,'forcing':forcing})])
            with self.assertRaises(ValueError):
                registry.run(invalid,cache_root=tmp,workers=1)
            imported = terrain.import_r22(old_initial)
            terrain.verify(imported)

    def test_moving_roots_uses_exact_transport_with_retained_physics(self):
        spec = rooted_recipe()
        inputs = {'spec':spec,'soil_engine':'R13'}
        module = topography.moving_roots
        before_raw = module.run(spec)['scientific']
        with tempfile.TemporaryDirectory(prefix='r31-root-') as tmp:
            plan = recipe([stage('roots','moving_roots',inputs)])
            result = registry.run(plan,cache_root=tmp,workers=1)
            after_raw = value(result,'roots')['scientific']
            for raw in (before_raw,after_raw):
                cp = raw['checkpoint']
                self.assertEqual(cp['state_sha256'],topography.native.sha(cp['state']))
            before, after = normal(before_raw), normal(after_raw)
            self.assertEqual(after['status'],'MODELLED_ROOTED_GROUND_FEEDBACK')
            self.assertNotEqual(before['source_sha256'],after['source_sha256'])
            for science in (before,after):
                science.pop('source_sha256')
                science['checkpoint'].pop('source_sha256')
                # The state contains the explicitly changed kernel-composition
                # description; authenticate its own digest before comparison.
                science['checkpoint'].pop('state_sha256')
            self.assertEqual(before,after)
            warm = registry.run(plan,cache_root=tmp,workers=1)
            self.assertEqual(warm['execution']['computed_stage_ids'],[])

    def test_forward_forecast_real_workers_and_resource_bounds(self):
        sample = physical.fixtures()['surface_water_route']
        plan = recipe([stage('a','surface_water_route',sample),stage('b','surface_water_route',sample)])
        with tempfile.TemporaryDirectory(prefix='r31-pool-') as tmp:
            with self.assertRaises(ValueError):
                registry.run(plan,cache=False,memory_budget_mb=100,worker_memory_mb=512)
            serial = registry.run(plan,cache_root=Path(tmp)/'s',workers=1)
            parallel = registry.run(plan,cache_root=Path(tmp)/'p',expected_seconds=180)
            self.assertEqual(serial['graph'],parallel['graph'])
            self.assertEqual(parallel['parallel']['effective_workers'],2)
            self.assertTrue(parallel['parallel']['worker_pids'])
            warm = registry.run(plan,cache_root=Path(tmp)/'p',expected_seconds=180)
            self.assertEqual(warm['parallel']['worker_pids'],[])
            self.assertEqual(warm['execution']['computed_stage_ids'],[])


if __name__ == '__main__':
    unittest.main()
