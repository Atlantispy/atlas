"""Focused native parity, isolated imports and authenticated inner-cache checks."""
from copy import deepcopy
from fractions import Fraction as F
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from work.generator_upgrade_r20 import cache as old_cache
from work.generator_upgrade_r22 import placement, crop_development as crop, provenance as native_p
from work.generator_upgrade_r24 import inner
from work.generator_upgrade_r24.storage import Store
from work.test_r22_placement import fixture
from work.test_r22_crops import profile_fixture, evaporation_fixture, SOURCE
from work.test_r22_moving_roots import recipe as roots_recipe


class InnerTests(unittest.TestCase):
    def test_private_placement_native_parity_and_cache_readback(self):
        population, candidates, geography, policy = fixture(23)
        population['evidence_id'] += ' — é漢字'
        arguments = dict(population=population, candidates=candidates, geography=geography, policy=policy)
        expected = placement.place(**arguments, cache=False)
        original = placement.place.__globals__['StageCache']
        adapter = inner.Adapter('population_scenario')
        with tempfile.TemporaryDirectory(prefix='r24-inner-place-') as root:
            cold = adapter.invoke(arguments, cache_root=root)
            warm = adapter.invoke(arguments, cache_root=root)
            self.assertEqual(cold, expected)
            self.assertEqual(warm, expected)
            private = adapter._modules['ordinary']
            self.assertIs(private.__code__, placement.place.__code__)
            self.assertIsNot(private.__globals__, placement.place.__globals__)
            self.assertIs(placement.place.__globals__['StageCache'], original)
            self.assertEqual(native_p.sha(cold), native_p.sha(expected))

    def test_native_stage_validator_runs_on_hit_and_sources_are_distinct(self):
        adapter = inner.Adapter('population_scenario')
        with tempfile.TemporaryDirectory(prefix='r24-inner-cache-') as root:
            stage = adapter.StageCache('focused-check', {'input': 'é'}, root)
            self.assertIsInstance(stage._store, Store)
            self.assertEqual(stage._closure['binding']['r24_inner_sources'], adapter.adapter_sources)
            self.assertIs(stage.reuse.__code__, old_cache.StageCache.reuse.__code__)
            producer, validator = mock.Mock(return_value={'value': '漢字'}), mock.Mock()
            self.assertEqual(stage.reuse({'id': 1}, producer, validator), ({'value': '漢字'}, False))
            self.assertEqual(stage.reuse({'id': 1}, producer, validator), ({'value': '漢字'}, True))
            self.assertEqual(producer.call_count, 1)
            self.assertEqual(validator.call_count, 2)
            with self.assertRaisesRegex(ValueError, 'validator rejected'):
                stage.reuse({'id': 1}, producer, lambda value: False)
            adapter._native_check = mock.Mock(side_effect=ValueError('changed source fixture'))
            with self.assertRaisesRegex(ValueError, 'changed source'):
                stage.reuse({'id': 1}, producer, validator)

    def test_crop_relative_import_is_private_and_actual_soil_is_identical(self):
        profile, forcing, _ = profile_fixture()
        model, state, event, controls = evaporation_fixture()
        layers = [{'layer_id': model['layers'][0]['layer_id'],
            'thickness_m': str(F(model['layers'][0]['thickness_m'])),
            'root_accessibility': 'ACCESSIBLE', **SOURCE}]
        forcing.update(end_seconds='100', reference_et_m='1/100000')
        arguments = dict(profile=profile,
            crop_state=crop.initial_state(profile, elapsed_seconds='0', thermal_time_cd='0'),
            forcing_windows=[{'forcing': forcing, 'soil_event': event}], layers=layers,
            model=model, soil_state=state, controls=controls)
        expected = crop.run(**arguments, cache=False)
        original_import = crop.run.__builtins__['__import__']
        adapter = inner.Adapter('crop_soil')
        with tempfile.TemporaryDirectory(prefix='r24-inner-crop-') as root:
            cold = adapter.invoke(arguments, cache_root=root)
            warm = adapter.invoke(arguments, cache_root=root)
        self.assertTrue(all(row['cache_hit'] for row in warm['execution']['events']))
        self.assertEqual(warm['execution']['stats']['writes'], 0)
        for result in (expected, cold, warm):
            result.pop('execution')
        self.assertEqual(cold, expected)
        self.assertEqual(warm, expected)
        self.assertIs(crop.run.__builtins__['__import__'], original_import)
        self.assertIs(adapter._modules['ordinary'].__code__, crop.run.__code__)

    def test_exact_native_store_view_has_source_bound_actual_namespace(self):
        adapter = inner.Adapter('population_scenario')
        namespace = 'a'*64
        with tempfile.TemporaryDirectory(prefix='r24-inner-bound-') as root:
            store = adapter.BoundStore(Path(root), namespace)
            self.assertIs(type(store), adapter.BoundStore)
            self.assertEqual(store.namespace, namespace)
            self.assertNotEqual(store._store.namespace, namespace)
            self.assertEqual(store._store.namespace, native_p.sha({
                'native_namespace': namespace, 'r24_inner_sources': adapter.adapter_sources}))
            store.put('b'*64, {'verified': True})
            self.assertEqual(store.get('b'*64), {'verified': True})

    def test_moving_root_checkpoint_keeps_native_science_and_explicit_adapter(self):
        from work.generator_upgrade_r22 import moving_roots
        spec = roots_recipe()
        expected = moving_roots.run(spec, stop_after=0)
        adapter = inner.Adapter('moving_roots')
        with tempfile.TemporaryDirectory(prefix='r24-inner-moving-') as root:
            actual = adapter.invoke({'spec': spec, 'soil_engine': 'R13', 'stop_after': 0}, cache_root=root)
            resumed = adapter.invoke({'spec': spec, 'soil_engine': 'R13', 'stop_after': 0,
                'resume': actual['scientific']['checkpoint']}, cache_root=root)
        self.assertEqual(actual['scientific'], expected['scientific'])
        self.assertEqual(resumed['scientific'], expected['scientific'])
        self.assertEqual(actual['execution']['r24_inner_sources'], adapter.adapter_sources)
        self.assertIs(moving_roots.run.__globals__['Store'], native_store_type())

    def test_terrain_body_native_parity_cache_and_stale_adapter_rejection(self):
        from work.generator_upgrade_r18 import consumer, working
        from work.generator_upgrade_r22 import terrain
        from work.test_r22_terrain import clock, forcing
        seed = working.build({'r120_c80': {'xy_m': [2000, 2000], 'area_m2': 16000000}}, alternative='DEFAULT')
        expected_initial = terrain.from_seed(seed, clock())
        initial = inner.invoke('terrain_from_seed', {'snapshot': seed, 'clock': clock()}, cache=False)
        self.assertEqual(initial['body'], expected_initial['body'])
        self.assertEqual(initial['binding'], expected_initial['binding'])
        supplied = forcing(expected_initial)
        expected = terrain.advance(expected_initial, supplied)
        adapter = inner.Adapter('terrain_advance')
        with tempfile.TemporaryDirectory(prefix='r24-inner-terrain-') as root:
            cold = adapter.invoke({'envelope': initial, 'forcing': supplied}, cache_root=root)
            warm = adapter.invoke({'envelope': initial, 'forcing': supplied}, cache_root=root)
            self.assertEqual(cold['body'], expected['body'])
            self.assertEqual(warm['body'], expected['body'])
            self.assertTrue(warm['execution']['cache_hit'])
            self.assertEqual(terrain.verify(warm), expected['body'])
            stale = deepcopy(initial)
            stale['execution']['r24_inner_sources'] = {'stale': 'a'*64}
            with self.assertRaisesRegex(ValueError, 'inner source binding changed'):
                adapter.invoke({'envelope': stale, 'forcing': supplied}, cache_root=root)
        self.assertIs(consumer.terrain_step.__globals__['verify'], consumer.verify)


def native_store_type():
    from work.generator_runtime_r12.store import Store as NativeStore
    return NativeStore


if __name__ == '__main__':
    unittest.main()
