"""Exact-output checks for bounded terrain algorithm accelerators."""

from __future__ import annotations

import unittest
from unittest import mock

import numpy as np

import algorithm_policy
import stage6c5_fast_terrain as terrain
import stage6c5r_physical as physical
from ten_m_tile_engine import engine as reference


class _AlgorithmTestCase(unittest.TestCase):
    def setUp(self):
        self.previous_mode = algorithm_policy.snapshot()["mode"]
        algorithm_policy.configure("auto")

    def tearDown(self):
        algorithm_policy.configure(self.previous_mode)


class ChamferWavefrontTests(_AlgorithmTestCase):
    def assert_exact(self, mask: np.ndarray) -> None:
        expected = physical._chamfer_distance_reference(mask)
        actual = physical._chamfer_distance_wavefront(mask)
        for left, right in zip(expected, actual):
            self.assertEqual(left.dtype, right.dtype)
            self.assertEqual(left.shape, right.shape)
            self.assertEqual(left.tobytes(), right.tobytes())

    def test_random_sparse_dense_and_noncontiguous(self):
        rng = np.random.default_rng(13072)
        for rows, cols, density in ((64, 65, .01), (65, 64, .2), (77, 93, .8)):
            mask = rng.random((rows, cols)) < density
            with self.subTest(shape=mask.shape, density=density):
                self.assert_exact(mask)
                self.assert_exact(mask[::-1, ::-1])

    def test_equal_distance_ties_and_edge_sources(self):
        mask = np.zeros((64, 67), dtype=bool)
        mask[0, 0] = mask[-1, -1] = mask[0, -1] = mask[-1, 0] = True
        mask[32, 24] = mask[32, 40] = True
        self.assert_exact(mask)

    def test_empty_full_and_narrow_shapes(self):
        for shape in ((64, 64), (0, 4), (1, 9), (9, 1), (2, 3)):
            for state in (False, True):
                with self.subTest(shape=shape, state=state):
                    self.assert_exact(np.full(shape, state, dtype=bool))

    def test_large_window_really_uses_wavefront(self):
        mask = np.zeros((256, 256), dtype=bool)
        mask[17, 23] = True
        expected = physical._chamfer_distance_reference(mask)
        with mock.patch.object(physical, "_chamfer_distance_reference", side_effect=AssertionError):
            actual = physical._chamfer_distance(mask)
        self.assertEqual(expected[0].tobytes(), actual[0].tobytes())
        self.assertEqual(expected[1].tobytes(), actual[1].tobytes())

    def test_reference_mode_retains_original_dispatch(self):
        mask = np.zeros((256, 256), dtype=bool)
        mask[17, 23] = True
        algorithm_policy.configure("reference")
        with mock.patch.object(physical, "_chamfer_distance_reference", wraps=physical._chamfer_distance_reference) as scalar:
            physical._chamfer_distance(mask)
            self.assertEqual(scalar.call_count, 1)

    def test_small_or_narrow_windows_keep_low_overhead_path(self):
        for shape in ((64, 64), (200, 200), (128, 500)):
            with mock.patch.object(physical, "_chamfer_distance_wavefront", side_effect=AssertionError):
                physical._chamfer_distance(np.eye(*shape, dtype=bool))


class QuantizationBatchTests(_AlgorithmTestCase):
    @staticmethod
    def original(blocks, scale=.01, nodata=-32768):
        flat = np.asarray(blocks).reshape(-1, 10, 10)
        return np.asarray([
            reference._quantize_zero_mean(block, scale, nodata) for block in flat
        ], dtype=np.int16).reshape(blocks.shape)

    def test_random_blocks_across_batch_boundary(self):
        rng = np.random.default_rng(22147)
        blocks = rng.normal(19, 6, (27, 13, 10, 10))
        expected = self.original(blocks)
        actual = terrain._quantize_zero_mean_blocks(blocks, .01, -32768)
        self.assertEqual(expected.tobytes(), actual.tobytes())
        self.assertTrue(np.all(actual.sum(axis=(-2, -1)) == 0))

    def test_zero_and_repeated_ties(self):
        blocks = np.zeros((9, 10, 10), dtype=np.float64)
        blocks[1] = np.tile(np.arange(10, dtype=np.float64) * .005, (10, 1))
        blocks[2] = blocks[1].T
        blocks[3] = -blocks[1]
        blocks[4] = .005
        blocks[5:, :, :33 % 10] = .0041
        expected = self.original(blocks)
        with mock.patch.object(reference, "_quantize_zero_mean", side_effect=AssertionError):
            actual = terrain._quantize_zero_mean_blocks(blocks, .01, -32768)
        self.assertEqual(expected.tobytes(), actual.tobytes())

    def test_saturated_blocks_keep_reference_fallback(self):
        blocks = np.zeros((3, 10, 10), dtype=np.float64)
        blocks[1] = np.tile(np.asarray([-1000., 1000.]), (10, 5))
        blocks[2] = np.tile(np.asarray([-327.67, 327.67]), (10, 5))
        expected = self.original(blocks)
        with mock.patch.object(reference, "_quantize_zero_mean", wraps=reference._quantize_zero_mean) as scalar:
            actual = terrain._quantize_zero_mean_blocks(blocks, .01, -32768)
            self.assertEqual(scalar.call_count, 2)
        self.assertEqual(expected.tobytes(), actual.tobytes())

    def test_nodata_collision_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "nodata sentinel"):
            terrain._quantize_zero_mean_blocks(np.zeros((2, 10, 10)), .01, 0)

    def test_noncontiguous_and_negative_scale(self):
        rng = np.random.default_rng(32)
        blocks = rng.normal(size=(3, 4, 10, 10)).transpose(1, 0, 3, 2)
        for scale in (.003, -.01):
            expected = self.original(blocks, scale)
            actual = terrain._quantize_zero_mean_blocks(blocks, scale, -32768)
            self.assertEqual(expected.tobytes(), actual.tobytes())

    def test_complete_fast_terrain_matches_original_quantizer(self):
        rows, cols = np.indices((14, 15), dtype=np.float64)
        data = 120.0 + rows * .38 - cols * .27 + .025 * np.sin(rows * cols)
        parent = reference.ParentRasterWindow(data, -5, -6, reference.GridSpec(0, 0))
        spec = reference.TileSpec("algorithm-parity", -1, -2, 5, 6, halo_cells=10)
        recipe = reference.TerrainRecipe(effective_resolution_m=100)
        actual = terrain._refine_vectorised(parent, spec, recipe, {"terrain": "fixed"})
        with mock.patch.object(terrain, "_quantize_zero_mean_blocks", side_effect=self.original):
            expected = terrain._refine_vectorised(parent, spec, recipe, {"terrain": "fixed"})
        self.assertEqual(actual.metadata, expected.metadata)
        self.assertEqual(set(actual.arrays), set(expected.arrays))
        for name in actual.arrays:
            self.assertEqual(actual.arrays[name].dtype, expected.arrays[name].dtype, name)
            self.assertEqual(actual.arrays[name].tobytes(), expected.arrays[name].tobytes(), name)

    def test_reference_mode_retains_original_dispatch(self):
        blocks = np.zeros((3, 10, 10), dtype=np.float64)
        algorithm_policy.configure("reference")
        with mock.patch.object(reference, "_quantize_zero_mean", wraps=reference._quantize_zero_mean) as scalar:
            terrain._quantize_zero_mean_blocks(blocks, .01, -32768)
            self.assertEqual(scalar.call_count, 3)


class ChannelProximityTests(_AlgorithmTestCase):
    def assert_exact(self, mask):
        expected = physical._chamfer_distance_reference(mask)[0] <= 1.5
        actual = physical._channel_proximity_mask(mask)
        self.assertEqual(expected.tobytes(), actual.tobytes())

    def test_every_tiny_mask(self):
        for number in range(64):
            mask = np.asarray([(number >> bit) & 1 for bit in range(6)], dtype=bool).reshape(2, 3)
            self.assert_exact(mask)

    def test_large_and_boundary_masks(self):
        rng = np.random.default_rng(517)
        for shape in ((0, 5), (5, 0), (1, 123), (125, 1), (64, 71)):
            for density in (0, .02, .8, 1):
                with self.subTest(shape=shape, density=density):
                    self.assert_exact(rng.random(shape) < density)

    def test_classification_arrays_and_metrics_unchanged(self):
        rng = np.random.default_rng(8743)
        classes = (rng.random((70, 70)) < .02).astype(np.uint8) * 5
        args = (
            classes, rng.random(classes.shape), rng.random((12, *classes.shape)),
            rng.random(classes.shape) * 1000, rng.random(classes.shape) > .1,
            rng.random(classes.shape) < .03, physical.PhysicalRecipe(),
        )
        actual = physical.classify_channels(*args)
        with mock.patch.object(physical, "_channel_proximity_mask", side_effect=lambda mask: physical._chamfer_distance_reference(mask)[0] <= 1.5):
            expected = physical.classify_channels(*args)
        self.assertEqual(actual[0].tobytes(), expected[0].tobytes())
        self.assertEqual(actual[1].tobytes(), expected[1].tobytes())
        self.assertEqual(actual[2], expected[2])

    def test_reference_mode_retains_original_dispatch(self):
        algorithm_policy.configure("reference")
        with mock.patch.object(physical, "_chamfer_distance_reference", wraps=physical._chamfer_distance_reference) as scalar:
            self.assert_exact(np.eye(4, dtype=bool))
            self.assertEqual(scalar.call_count, 2)


class ScenarioAccumulationTests(_AlgorithmTestCase):
    @staticmethod
    def fixture():
        rr, cc = np.indices((7, 9), dtype=np.float64)
        routing = 200 - .38 * rr - .27 * cc
        sink = np.zeros(routing.shape, dtype=bool)
        receiver, weights, _ = physical.mfd_receivers(routing, sink)
        rng = np.random.default_rng(911)
        low = rng.uniform(0, 40, (12, *routing.shape)).astype(np.float32)
        high = rng.uniform(40, 500, (12, *routing.shape)).astype(np.float32)
        seeds = {1: 1.25, "1": 3.7, -1: 20, 1000: 2, 5: 0, 8: -.1, 11: .005}
        return routing, receiver, weights, (low, high), seeds

    def assert_outputs(self, expected, actual):
        self.assertEqual(len(expected), len(actual))
        for expected_scenario, actual_scenario in zip(expected, actual):
            for expected_array, actual_array in zip(expected_scenario[:3], actual_scenario[:3]):
                self.assertEqual(expected_array.dtype, actual_array.dtype)
                self.assertEqual(expected_array.shape, actual_array.shape)
                self.assertEqual(expected_array.tobytes(), actual_array.tobytes())
            self.assertEqual(expected_scenario[3], actual_scenario[3])

    def test_two_scenarios_match_separate_reference_and_do_not_alias(self):
        routing, receiver, weights, scenarios, seeds = self.fixture()
        snapshots = [array.copy() for array in (routing, receiver, weights, *scenarios)]
        expected = tuple(physical.accumulate_flow_mfd(routing, receiver, weights, runoff, seeds) for runoff in scenarios)
        with mock.patch.object(physical, "accumulate_flow_mfd", side_effect=AssertionError):
            actual = physical.accumulate_flow_mfd_scenarios(routing, receiver, weights, scenarios, seeds)
        self.assert_outputs(expected, actual)
        for first, second in zip(actual[0][:3], actual[1][:3]):
            self.assertFalse(np.shares_memory(first, second))
        for before, after in zip(snapshots, (routing, receiver, weights, *scenarios)):
            self.assertEqual(before.tobytes(), after.tobytes())

    def test_noncontiguous_and_nonfinite_runoff_matches_reference(self):
        routing, receiver, weights, scenarios, seeds = self.fixture()
        scenarios = tuple(runoff[:, ::-1, ::-1] for runoff in scenarios)
        scenarios[0][0, 0, 0] = np.nan
        expected = tuple(physical.accumulate_flow_mfd(routing, receiver, weights, runoff, seeds) for runoff in scenarios)
        actual = physical.accumulate_flow_mfd_scenarios(routing, receiver, weights, scenarios, seeds)
        for expected_scenario, actual_scenario in zip(expected, actual):
            for left, right in zip(expected_scenario[:3], actual_scenario[:3]):
                self.assertEqual(left.tobytes(), right.tobytes())
            self.assertEqual(expected_scenario[3]["receiver_graph_sha256"], actual_scenario[3]["receiver_graph_sha256"])
            self.assertEqual(np.isnan(expected_scenario[3]["accumulated_runoff_proxy_max_mm_km2_y"]),
                             np.isnan(actual_scenario[3]["accumulated_runoff_proxy_max_mm_km2_y"]))

    def test_reference_mode_and_other_scenario_counts_keep_scalar_path(self):
        routing, receiver, weights, scenarios, seeds = self.fixture()
        for mode, selected in (("reference", scenarios), ("auto", scenarios[:1]), ("auto", scenarios + scenarios[:1])):
            algorithm_policy.configure(mode)
            expected = tuple(physical.accumulate_flow_mfd(routing, receiver, weights, runoff, seeds) for runoff in selected)
            with mock.patch.object(physical, "accumulate_flow_mfd", wraps=physical.accumulate_flow_mfd) as scalar:
                actual = physical.accumulate_flow_mfd_scenarios(routing, receiver, weights, selected, seeds)
                self.assertEqual(scalar.call_count, len(selected))
            self.assert_outputs(expected, actual)

    def test_large_window_falls_back_before_allocating_batch(self):
        routing = np.broadcast_to(np.float32(1), (513, 512))
        scenarios = tuple(np.broadcast_to(np.float32(0), (12, *routing.shape)) for _ in range(2))
        with mock.patch.object(physical, "accumulate_flow_mfd", return_value=(None, None, None, {})) as scalar:
            physical.accumulate_flow_mfd_scenarios(routing, np.empty((0, 0)), np.empty((0, 0)), scenarios, {})
            self.assertEqual(scalar.call_count, 2)

    def test_graph_validation_and_cycle_errors_match(self):
        routing, receiver, weights, scenarios, seeds = self.fixture()
        invalid_cases = []
        bad_weight = weights.copy()
        bad_weight[:, 0] *= 2
        invalid_cases.append((routing, receiver, bad_weight, scenarios, seeds))
        invalid_cases.append((np.zeros_like(routing), receiver, weights, scenarios, seeds))
        cycle_receiver = np.full((8, 2), -1, dtype=np.int64)
        cycle_receiver[0] = (1, 0)
        cycle_weight = np.zeros((8, 2), dtype=np.float32)
        cycle_weight[0] = 1
        invalid_cases.append((np.full((1, 2), np.nan), cycle_receiver, cycle_weight,
                              (np.zeros((12, 1, 2)), np.ones((12, 1, 2))), {}))
        for args in invalid_cases:
            with self.subTest(shape=args[0].shape):
                with self.assertRaises(physical.PhysicalReconstructionError) as expected:
                    physical.accumulate_flow_mfd(args[0], args[1], args[2], args[3][0], args[4])
                with self.assertRaises(physical.PhysicalReconstructionError) as actual:
                    physical.accumulate_flow_mfd_scenarios(*args)
                self.assertEqual(str(expected.exception), str(actual.exception))


if __name__ == "__main__":
    unittest.main()
