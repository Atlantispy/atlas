"""Exact-output and fallback tests for bounded hydrology kernel improvements."""

from concurrent.futures import ThreadPoolExecutor
import math
from types import SimpleNamespace
from unittest import mock
import unittest

import numpy as np
from shapely.geometry import LineString

import stage6c5r_hydrology as hydrology
import stage6c5r_routes as routes


class EnabledAlgorithmsTestCase(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(hydrology.algorithm_policy, "use_optimized", return_value=True)
        patcher.start()
        self.addCleanup(patcher.stop)


class HydrologyProjectionAlgorithmTests(EnabledAlgorithmsTestCase):
    def assert_bits_equal(self, actual, expected):
        self.assertEqual(actual.dtype, expected.dtype)
        self.assertEqual(actual.shape, expected.shape)
        self.assertEqual(actual.tobytes(), expected.tobytes())

    def test_batched_projection_matches_scalar_crossings_ties_and_endpoints(self):
        line = LineString([(0, 0), (2, 2), (0, 2), (2, 0), (0, 0), (3, 0)])
        points = [(0, 0), (1, 1), (1, 2), (2, 2), (-3, 0), (5, 0), (1, 0)]
        points = points * (hydrology._PROJECTION_BLOCK_SIZE // len(points) + 3)
        self.assert_bits_equal(
            hydrology._project_chainage(line, points),
            hydrology._project_chainage_reference(line, points),
        )

    def test_projection_bounds_each_geometry_batch(self):
        line = LineString([(0, 0), (1, 0)])
        original = hydrology.shapely.points
        sizes = []

        def observe(values):
            sizes.append(len(values))
            return original(values)

        count = hydrology._PROJECTION_BLOCK_SIZE * 2 + 9
        with mock.patch.object(hydrology.shapely, "points", side_effect=observe):
            actual = hydrology._project_chainage(line, ((i / count, 0) for i in range(count)))
        self.assertEqual(sizes, [hydrology._PROJECTION_BLOCK_SIZE] * 2 + [9])
        self.assertEqual(len(actual), count)

    def test_projection_empty_and_nonfinite_semantics(self):
        line = LineString([(0, 0), (1, 0)])
        self.assert_bits_equal(hydrology._project_chainage(line, []), hydrology._project_chainage_reference(line, []))
        points = [(float("nan"), 0), (0, float("nan"))]
        with np.errstate(invalid="ignore"):
            try:
                expected = hydrology._project_chainage_reference(line, points)
            except Exception as error:
                with self.assertRaises(type(error)):
                    hydrology._project_chainage(line, points)
            else:
                self.assert_bits_equal(hydrology._project_chainage(line, points), expected)

    def test_projection_scalar_fallback_when_array_api_unavailable(self):
        line = LineString([(0, 0), (1, 0)])
        points = [(0.2, 1), (0.8, -1)]
        expected = hydrology._project_chainage_reference(line, points)
        for unavailable in ("points", "line_locate_point"):
            fake = SimpleNamespace(points=hydrology.shapely.points, line_locate_point=hydrology.shapely.line_locate_point)
            setattr(fake, unavailable, None)
            with mock.patch.object(hydrology, "shapely", fake):
                self.assert_bits_equal(hydrology._project_chainage(line, points), expected)

    def test_reference_policy_does_not_call_vector_api(self):
        line = LineString([(0, 0), (1, 0)])
        points = [(0.2, 1), (0.8, -1)]
        expected = hydrology._project_chainage_reference(line, points)
        fake = SimpleNamespace(points=mock.Mock(side_effect=AssertionError("vector path")),
                               line_locate_point=mock.Mock(side_effect=AssertionError("vector path")))
        with mock.patch.object(hydrology.algorithm_policy, "use_optimized", return_value=False), \
                mock.patch.object(hydrology, "shapely", fake):
            self.assert_bits_equal(hydrology._project_chainage(line, points), expected)
        fake.points.assert_not_called()

    def test_projection_does_not_hide_geometry_errors(self):
        with mock.patch.object(hydrology.shapely, "points", side_effect=RuntimeError("injected")):
            with self.assertRaisesRegex(RuntimeError, "injected"):
                hydrology._project_chainage(LineString([(0, 0), (1, 0)]), [(0, 0)])

    def test_profile_interpolation_exact_under_concurrent_reads(self):
        coordinates = np.array([[0, 0, 90], [1, 0, 80], [1, 2, 50], [3, 3, 1]], dtype=np.float64)
        profile = hydrology.MajorBedProfile(
            "fixture", LineString(coordinates[:, :2]),
            hydrology._chainage_xy(coordinates), coordinates[:, 2], {"status": "REVIEW_ONLY"},
        )
        profiles = hydrology.ActiveMajorBedProfiles.__new__(hydrology.ActiveMajorBedProfiles)
        profiles._profiles = {"fixture": profile}
        points = [(i / 37, i / 47) for i in range(128)]
        expected = np.interp(
            hydrology._project_chainage_reference(profile.line_2d, points),
            profile.chainage_km, profile.elevation_m,
        ).astype(np.float64)
        before = (profile.line_2d.wkb, profile.chainage_km.tobytes(), profile.elevation_m.tobytes())
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: profiles.sample_z("fixture", points), range(4)))
        for result in results:
            self.assert_bits_equal(result, expected)
        self.assertEqual(before, (profile.line_2d.wkb, profile.chainage_km.tobytes(), profile.elevation_m.tobytes()))
        with self.assertRaisesRegex(hydrology.HydrologyProfileError, "No current"):
            profiles.sample_z("missing", points)


class CorridorSpanAlgorithmTests(EnabledAlgorithmsTestCase):
    def assert_mask_equal(self, actual, expected):
        self.assertEqual(actual.dtype, np.dtype(bool))
        self.assertEqual(actual.shape, expected.shape)
        self.assertEqual(actual.tobytes(), expected.tobytes())

    def test_all_route_classes_and_fractional_cell_sizes_exact(self):
        axis = [(-4, 1), (0, 5), (14, 23), (37, 40), (53, 31)]
        dense = routes._densify_cells(routes._deduplicate_consecutive(axis))
        for route_class in routes.CORRIDOR_RADII_M:
            for cell_size in (7.0, 10.0, 13.2, 50.0, 1000.0):
                with self.subTest(route_class=route_class, cell_size=cell_size):
                    expected = routes._corridor_mask_reference(
                        (43, 47), dense, routes.corridor_radius_m(route_class) / cell_size
                    )
                    self.assert_mask_equal(
                        routes.corridor_mask_from_cells((43, 47), axis, route_class, cell_size_m=cell_size),
                        expected,
                    )

    def test_integer_circle_boundary_epsilon_and_outside_cells_exact(self):
        cells = [(-8, -8), (0, 0), (0, 22), (14, 22), (14, 0), (7, 11), (7, 11), (25, 25)]
        for radius in (0.0, 0.01, 1.0, math.sqrt(2), np.nextafter(math.sqrt(2), 0),
                       np.nextafter(math.sqrt(2), math.inf), 2.5, 5.0, 12.1, 40.0):
            self.assert_mask_equal(
                routes._corridor_mask_spans((15, 23), cells, radius),
                routes._corridor_mask_reference((15, 23), cells, radius),
            )

    def test_randomised_exact_replay_and_no_input_mutation(self):
        rng = np.random.default_rng(680032)
        for _ in range(24):
            shape = (int(rng.integers(3, 50)), int(rng.integers(3, 50)))
            cells = [tuple(int(v) for v in row) for row in rng.integers(-10, 60, size=(13, 2))]
            before = tuple(cells)
            radius = float(rng.uniform(0, 18))
            self.assert_mask_equal(
                routes._corridor_mask_spans(shape, cells, radius),
                routes._corridor_mask_reference(shape, cells, radius),
            )
            self.assertEqual(tuple(cells), before)

    def test_complete_route_candidate_metrics_lineage_and_contacts_unchanged(self):
        terrain = np.repeat((200.0 - np.arange(48))[:, None], 48, axis=1)
        terrain[22:26, 24] += 20.0
        axis = [(row, 24) for row in range(2, 46)]
        grid = routes.GridWindow(12.0, 18.0, rows=48, cols=48)
        actual = routes.build_route_candidate(terrain, grid, axis, "major", ordered_contacts=[(29, 23)])
        with mock.patch.object(routes, "_corridor_mask_spans", routes._corridor_mask_reference):
            expected = routes.build_route_candidate(terrain, grid, axis, "major", ordered_contacts=[(29, 23)])
        self.assertEqual(actual.serialisable(), expected.serialisable())
        self.assertIn((29, 23), actual.path_cells)

    def test_invalid_corridor_inputs_still_fail_closed(self):
        for shape, axis, kind, size in (
            ((0, 2), [(0, 0), (0, 1)], "stream", 10),
            ((2, 2), [(0, 0)], "stream", 10),
            ((2, 2), [(0, 0), (0, 1)], "unapproved", 10),
            ((2, 2), [(0, 0), (0, 1)], "stream", 0),
        ):
            with self.assertRaises(routes.RouteReconstructionError):
                routes.corridor_mask_from_cells(shape, axis, kind, cell_size_m=size)

    def test_reference_policy_uses_retained_disk_cell_algorithm(self):
        cells = [(1, 1), (18, 18)]
        dense = routes._densify_cells(cells)
        expected = routes._corridor_mask_reference((20, 20), dense, 5.0)
        with mock.patch.object(routes.algorithm_policy, "use_optimized", return_value=False), \
                mock.patch.object(routes, "_corridor_mask_spans", side_effect=AssertionError("span path")):
            self.assert_mask_equal(routes.corridor_mask_from_cells((20, 20), cells, "stream"), expected)


if __name__ == "__main__":
    unittest.main()
