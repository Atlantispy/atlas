"""Bounded layout evidence, separate from geological/morphological acceptance.

One real N=6/support192 fixture is shared by replay and native-store checks.
There is no seed/resolution search or tolerance tuning in this test module.
"""
import copy
import math
from pathlib import Path
import random
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest import mock

import numpy as np
from numpy.testing import assert_array_equal

TECTONICS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TECTONICS / 'tools'))
sys.path.insert(0, str(TECTONICS / 'src'))

import new_world_contract as contract
import new_world_layout as layout
from atlas_tectonics import GeometryError, save_spherical_atlas, load_spherical_atlas
import atlas_tectonics.planetary_generation as planetary
from atlas_tectonics.plate_reference import reference_area_fractions
from atlas_tectonics.storage import ArrayStore, StoreLimits


def plan(seed=41, *, memory=128 << 20, seconds=30.):
    settings = dict(
        radius_m=dict(mode='fixed', value=6371000.),
        gravity_m_s2=dict(mode='fixed', value=9.81),
        plate_count=dict(mode='fixed', value=6),
        continental_fraction=dict(mode='fixed', value=.3),
    )
    return contract.resolve_request(contract.new_request(
        f'{seed:032x}', settings=settings, support_cells=192,
        resources=dict(max_work_bytes=memory, max_wall_seconds=seconds)))


class SpectrumTests(unittest.TestCase):
    def test_zero_spread_preserves_exact_reference_bytes(self):
        expected = reference_area_fractions(6)
        for seed in ('0' * 32, 'f' * 32):
            result = layout.sample_area_spectrum(6, seed, spread=0.)
            self.assertEqual(np.asarray(result['target_fractions'], dtype='f8').tobytes(),
                             expected.tobytes())
            self.assertEqual(result['baseline_fractions'], expected.tolist())
            self.assertTrue(all(value == 0 for value in result['log_perturbations']))

    def test_distinct_seeds_change_sorted_sizes_not_only_labels_or_rotation(self):
        spectra = []
        for seed in (40, 41, 42):
            stream = contract.stream_seed(f'{seed:032x}', 'plate_sizes')
            result = layout.sample_area_spectrum(6, stream)
            values = result['target_fractions']
            self.assertEqual(values, sorted(values, reverse=True))
            self.assertTrue(all(math.isfinite(x) and x > 0 for x in values))
            self.assertAlmostEqual(math.fsum(values), 1., delta=2e-16)
            self.assertEqual(result['status'], 'UNCALIBRATED_ENGINEERING_PRIOR')
            self.assertEqual(result['sizes_seed'], stream)
            spectra.append(values)
        # Sorted area multisets are invariant under rigid rotation and relabelling.
        for i, first in enumerate(spectra):
            for second in spectra[i + 1:]:
                self.assertGreater(sum(abs(a - b) for a, b in zip(first, second)), 1e-3)

    def test_deterministic_detached_spectrum_and_global_rng_independence(self):
        seed = contract.stream_seed('0' * 31 + '1', 'plate_sizes')
        first = layout.sample_area_spectrum(6, seed)
        before_python, before_numpy = random.getstate(), np.random.get_state()
        try:
            random.seed(919); random.random()
            np.random.seed(812); np.random.random(15)
            python_state, numpy_state = random.getstate(), np.random.get_state()
            second = layout.sample_area_spectrum(6, seed)
            self.assertEqual(first, second)
            self.assertEqual(random.getstate(), python_state)
            after_numpy = np.random.get_state()
            self.assertEqual(after_numpy[0], numpy_state[0])
            assert_array_equal(after_numpy[1], numpy_state[1])
            self.assertEqual(after_numpy[2:], numpy_state[2:])
            second['target_fractions'][0] = -1
            self.assertEqual(layout.sample_area_spectrum(6, seed), first)
        finally:
            random.setstate(before_python); np.random.set_state(before_numpy)

    def test_invalid_seeds_counts_and_policy_values_refuse(self):
        for seed in ('0', 'A' * 32, 'x' * 32, 1, None):
            with self.subTest(seed=seed), self.assertRaises(contract.ContractError) as raised:
                layout.sample_area_spectrum(6, seed)
            self.assertEqual(raised.exception.code, 'INVALID_LAYOUT_SEED')
        for count in (True, 1, 53, 6.):
            with self.subTest(count=count), self.assertRaises(GeometryError):
                layout.sample_area_spectrum(count, '0' * 32)
        for name, values in (
            ('size_log_spread', (True, -1., 1.01, float('nan'), float('inf'), '.3')),
            ('max_area_l1_error', (0., -.1, .041, True)),
            ('max_relative_area_error', (0., -.1, .251, True)),
        ):
            for value in values:
                with self.subTest(name=name, value=value), self.assertRaises(contract.ContractError) as raised:
                    layout.LayoutPolicy(**{name: value})
                self.assertEqual(raised.exception.code, 'INVALID_LAYOUT_POLICY')


class BoundedRefusalTests(unittest.TestCase):
    def setUp(self):
        self.plan = plan()

    def assert_rejected(self, result, code, prepared=None):
        prepared = self.plan if prepared is None else prepared
        self.assertIsNone(result.atlas)
        report = result.report
        self.assertEqual(report['status'], 'REJECTED')
        self.assertEqual(report['attempt'], 1)
        self.assertEqual(report['plan_id'], prepared['plan_id'])
        self.assertEqual(report['rejection']['code'], code)
        self.assertIsNone(report['atlas_id'])
        self.assertIsNone(report['geometry_id'])
        self.assertEqual(report['specification']['geometry_seed'], prepared['streams']['plate_layout'])
        self.assertEqual(report['specification']['area_spectrum']['sizes_seed'], prepared['streams']['plate_sizes'])
        self.assertEqual(report['specification']['acceptance']['geometry'], 'NOT_PUBLISHED')
        self.assertEqual(report['resources']['reserved_bytes'], 0)
        self.assertTrue(math.isfinite(report['elapsed_seconds']))
        self.assertGreaterEqual(report['elapsed_seconds'], 0.)
        return report

    def test_invalid_plan_policy_and_cancel_refuse_before_native_work(self):
        invalid = copy.deepcopy(self.plan)
        invalid['resolved_settings']['plate_count'] = 7
        with mock.patch.object(planetary, 'generate_planetary_partition',
                               side_effect=AssertionError('no native work')):
            for kwargs, expected in (({'plan': invalid}, 'INVALID_PLAN'),
                                     ({'plan': self.plan, 'policy': {}}, 'INVALID_LAYOUT_POLICY'),
                                     ({'plan': self.plan, 'cancel': object()}, 'INVALID_CANCEL')):
                with self.subTest(expected=expected), self.assertRaises(contract.ContractError) as raised:
                    layout.generate_layout_candidate(**kwargs)
                self.assertEqual(raised.exception.code, expected)

    def test_pre_cancel_preserves_one_attempt_and_never_generates_support(self):
        cancel = threading.Event(); cancel.set()
        with mock.patch.object(planetary, 'generate_planetary_partition') as generate:
            result = layout.generate_layout_candidate(self.plan, cancel=cancel)
        generate.assert_not_called()
        self.assert_rejected(result, 'CANCELLED')

    def test_finite_wall_budget_is_recorded_without_real_sleep(self):
        prepared = plan(seconds=1.)
        clock = SimpleNamespace(perf_counter=mock.Mock(side_effect=(0., 0., 2., 2.1)))
        with mock.patch.object(layout, 'time', clock), \
             mock.patch.object(planetary, 'generate_planetary_partition') as generate:
            result = layout.generate_layout_candidate(prepared)
        generate.assert_not_called()
        self.assert_rejected(result, 'TIME_LIMIT', prepared)

    def test_work_budget_refusal_is_finite_and_releases_all_reservations(self):
        prepared = plan(memory=1 << 20)
        with mock.patch.object(planetary, 'generate_planetary_partition') as generate:
            result = layout.generate_layout_candidate(prepared)
        generate.assert_not_called()
        report = self.assert_rejected(result, 'MEMORY_LIMIT', prepared)
        self.assertGreater(report['resources']['refusals'], 0)
        self.assertEqual(report['resources']['max_bytes'], 1 << 20)

    def test_native_geometry_rejection_retains_attempt_count_and_reasons(self):
        rejection = planetary.PartitionGenerationError(3, {'synthetic-degenerate': 3})
        with mock.patch.object(planetary, 'generate_planetary_partition',
                               side_effect=rejection) as generate:
            result = layout.generate_layout_candidate(self.plan)
        self.assertEqual(generate.call_count, 1)
        settings = generate.call_args.args[1]
        self.assertEqual(settings.plate_count, 192)
        self.assertEqual(settings.seed, int(self.plan['streams']['plate_layout'], 16))
        self.assertEqual(settings.max_attempts, 128)
        report = self.assert_rejected(result, 'GEOMETRY_REFUSED')
        self.assertEqual(report['rejection']['support_attempts'], 3)
        self.assertEqual(report['rejection']['support_rejections'], {'synthetic-degenerate': 3})
        self.assertEqual(report['rejection']['message'], str(rejection))
        self.assertIn('3 candidates', report['rejection']['message'])
        self.assertIn("'synthetic-degenerate': 3", report['rejection']['message'])

    def test_native_cancellation_is_recorded_without_retry(self):
        event = threading.Event()
        def cancel_during_support(*args, **kwargs):
            event.set()
            from atlas_tectonics.geometry import _check_cancel
            _check_cancel(kwargs['cancel'])
        with mock.patch.object(planetary, 'generate_planetary_partition',
                               side_effect=cancel_during_support) as generate:
            result = layout.generate_layout_candidate(self.plan, cancel=event)
        self.assertEqual(generate.call_count, 1)
        self.assert_rejected(result, 'CANCELLED')

    def test_full_scientific_plan_changes_identity_even_without_geometry_effect(self):
        event = threading.Event(); event.set()
        first = layout.generate_layout_candidate(self.plan, cancel=event).report
        for setting, value in (('gravity_m_s2', 8.), ('continental_fraction', .4)):
            request = copy.deepcopy(self.plan['request'])
            request['settings'][setting]['value'] = value
            changed = contract.resolve_request(request)
            result = layout.generate_layout_candidate(changed, cancel=event).report
            self.assertNotEqual(result['candidate_request_id'], first['candidate_request_id'])
            self.assertNotEqual(result['plan_id'], first['plan_id'])
            self.assertNotEqual(result['specification']['scientific_id'],
                                first['specification']['scientific_id'])
            self.assertEqual(result['specification']['geometry_seed'],
                             first['specification']['geometry_seed'])
            self.assertEqual(result['specification']['area_spectrum'],
                             first['specification']['area_spectrum'])
        request = copy.deepcopy(self.plan['request'])
        request['resources']['max_wall_seconds'] += 1
        resource_plan = contract.resolve_request(request)
        result = layout.generate_layout_candidate(resource_plan, cancel=event).report
        self.assertNotEqual(result['plan_id'], first['plan_id'])
        self.assertEqual(result['candidate_request_id'], first['candidate_request_id'])

    def test_adapter_drift_before_and_during_attempt_refuses_without_repinning(self):
        with mock.patch.object(layout, '_LOADED_HASH', '0' * 64), \
             self.assertRaises(contract.ContractError) as raised:
            layout.generate_layout_candidate(self.plan)
        self.assertEqual(raised.exception.code, 'SOURCE_MISMATCH')
        event = threading.Event(); event.set()
        with mock.patch.object(layout, '_source_hash', side_effect=(
            layout._LOADED_HASH, contract.ContractError('SOURCE_MISMATCH', 'changed'))), \
             self.assertRaises(contract.ContractError) as raised:
            layout.generate_layout_candidate(self.plan, cancel=event)
        self.assertEqual(raised.exception.code, 'SOURCE_MISMATCH')
        stale = copy.deepcopy(self.plan)
        stale['binding']['contract_sha256'] = '0' * 64
        with self.assertRaises(contract.ContractError) as raised:
            layout.generate_layout_candidate(stale)
        self.assertEqual(raised.exception.code, 'SOURCE_MISMATCH')


class NativeFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.prepared = plan()
        cls.candidate = layout.generate_layout_candidate(cls.prepared)

    def test_real_bounded_candidate_exact_replay_and_global_rng_independence(self):
        prepared = self.prepared
        first = self.candidate
        python_state, numpy_state = random.getstate(), np.random.get_state()
        try:
            random.seed(971); random.random()
            np.random.seed(879); np.random.random(12)
            second = layout.generate_layout_candidate(prepared)
        finally:
            random.setstate(python_state); np.random.set_state(numpy_state)
        one, two = copy.deepcopy(first.report), copy.deepcopy(second.report)
        one.pop('elapsed_seconds'); two.pop('elapsed_seconds')
        self.assertEqual(one, two)
        self.assertEqual(first.report['attempt'], 1)
        self.assertIn(first.report['status'], ('REJECTED', 'CANDIDATE_NOT_GEOLOGICALLY_ACCEPTED'))
        if first.atlas is None:
            self.assertIsNone(second.atlas)
            self.assertEqual(first.report['rejection']['code'], 'GEOMETRY_REFUSED')
            print('Real N6/support192 seed41 fixture refused:', first.report['rejection']['message'])
        else:
            self.assertEqual(first.atlas.atlas_id, second.atlas.atlas_id)
            self.assertEqual(first.atlas.geometry_id, second.atlas.geometry_id)
            self.assertEqual(first.atlas.descriptor(), second.atlas.descriptor())
            self.assertEqual(len(first.atlas.plate_ids), 6)
            assert_array_equal(first.atlas.vertex_directions, second.atlas.vertex_directions)
            assert_array_equal(first.atlas.edge_vertices, second.atlas.edge_vertices)
            assert_array_equal(first.atlas.side_patches, second.atlas.side_patches)
            assert_array_equal(first.atlas.patch_areas_sr, second.atlas.patch_areas_sr)
            self.assertAlmostEqual(math.fsum(first.atlas.patch_areas_sr), 4 * math.pi, delta=2e-11)
            generation = first.report['specification']['support_generation']['partition_generation']['generation']
            self.assertGreaterEqual(generation['accepted_attempt'], 0)
            self.assertLess(generation['accepted_attempt'], 128)
            self.assertIn('rejections', generation)

    def test_candidate_roundtrip_uses_actual_native_store(self):
        result = self.candidate
        self.assertEqual(result.report['status'], 'CANDIDATE_NOT_GEOLOGICALLY_ACCEPTED', result.report)
        self.assertIsNotNone(result.atlas)
        self.assertEqual(result.report['specification']['area_spectrum']['prior'], layout.SIZE_PRIOR)
        self.assertFalse(result.report['specification']['acceptance']['geological_validation'])
        self.assertFalse(result.report['specification']['capabilities']['generate_world'])
        self.assertEqual(result.report['resources']['reserved_bytes'], 0)
        self.assertFalse(result.report['request_id_is_cache_key'])
        atlas = result.atlas
        limits = StoreLimits(65536, 16 << 20, 64 << 20)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'candidate.sqlite'
            with ArrayStore(path, limits) as store:
                key = save_spherical_atlas(atlas, store)
                self.assertEqual(key, atlas.atlas_id)
                count = store.statistics()['unique_chunks']
                save_spherical_atlas(atlas, store)
                self.assertEqual(store.statistics()['unique_chunks'], count)
            with ArrayStore(path, limits) as store:
                restored = load_spherical_atlas(store, key)
            self.assertEqual(restored.descriptor(), atlas.descriptor())
            self.assertEqual(restored.atlas_id, atlas.atlas_id)
            self.assertEqual(restored.geometry_id, atlas.geometry_id)
            assert_array_equal(restored.vertex_directions, atlas.vertex_directions)
            assert_array_equal(restored.edge_vertices, atlas.edge_vertices)
            assert_array_equal(restored.side_patches, atlas.side_patches)
            assert_array_equal(restored.patch_areas_sr, atlas.patch_areas_sr)
            with self.assertRaises(ValueError):
                restored.vertex_directions.setflags(write=True)


if __name__ == '__main__':
    unittest.main()
