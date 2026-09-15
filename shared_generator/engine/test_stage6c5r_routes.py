"""Synthetic, bounded tests for the Stage 6C.5R route module."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest

import numpy as np


ENGINE = Path(__file__).resolve().parent
sys.path.insert(0, str(ENGINE / "generator_deps"))
sys.path.insert(0, str(ENGINE))

from shapely.geometry import LineString, MultiLineString  # noqa: E402

from stage6c5r_routes import (  # noqa: E402
    GridWindow,
    RouteReconstructionError,
    build_route_candidate,
    corridor_mask_from_cells,
    corridor_radius_m,
    export_candidate_route_coordinates,
    monotonic_astar_route,
    orient_cells_downstream,
    sample_geometry_to_grid,
)


class Stage6C5RRouteTests(unittest.TestCase):
    def test_clip_and_sample_line_in_three_kilometre_window(self) -> None:
        grid = GridWindow(10.0, 20.0)
        geometry = LineString([(9.5, 20.5), (11.5, 21.5), (13.5, 22.5)])
        sampled = sample_geometry_to_grid(geometry, grid)
        self.assertEqual(sampled.source_geometry_type, "LineString")
        self.assertEqual(len(sampled.parts), 1)
        path = sampled.parts[0]
        self.assertEqual(path[0][1], 0)
        self.assertEqual(path[-1][1], 299)
        self.assertTrue(sampled.boundary_runs)
        for first, second in zip(path[:-1], path[1:]):
            self.assertLessEqual(max(abs(first[0] - second[0]), abs(first[1] - second[1])), 1)

    def test_multiline_preserves_component_order_without_bridging(self) -> None:
        grid = GridWindow(0.0, 0.0)
        geometry = MultiLineString(
            [
                [(0.1, 0.1), (0.5, 0.5)],
                [(2.5, 2.5), (2.9, 2.9)],
            ]
        )
        sampled = sample_geometry_to_grid(geometry, grid)
        self.assertEqual(len(sampled.parts), 2)
        self.assertLess(sampled.parts[0][0][0], sampled.parts[1][0][0])
        self.assertNotEqual(sampled.parts[0][-1], sampled.parts[1][0])

    def test_orientation_is_inferred_from_endpoint_elevation(self) -> None:
        terrain = np.zeros((10, 10), dtype=np.float64)
        terrain[1, 1] = 10.0
        terrain[8, 8] = 40.0
        result = orient_cells_downstream([(1, 1), (8, 8)], terrain)
        self.assertTrue(result.reversed_from_geometry)
        self.assertEqual(result.path_cells[0], (8, 8))
        self.assertGreater(result.source_elevation_m, result.receiver_elevation_m)

    def test_equal_endpoint_elevation_fails_closed(self) -> None:
        terrain = np.zeros((10, 10), dtype=np.float64)
        with self.assertRaisesRegex(RouteReconstructionError, "Cannot infer downstream"):
            orient_cells_downstream([(1, 1), (8, 8)], terrain)

    def test_approved_corridor_radii(self) -> None:
        self.assertEqual(corridor_radius_m("Titan"), 400.0)
        self.assertEqual(corridor_radius_m("major river"), 200.0)
        self.assertEqual(corridor_radius_m("smaller river"), 100.0)
        self.assertEqual(corridor_radius_m("stream"), 50.0)
        with self.assertRaises(RouteReconstructionError):
            corridor_radius_m("unapproved-special-class")
        mask = corridor_mask_from_cells((101, 101), [(10, 50), (90, 50)], "stream")
        self.assertTrue(mask[50, 45])
        self.assertTrue(mask[50, 55])
        self.assertFalse(mask[50, 44])

    @staticmethod
    def _detour_fixture() -> tuple[np.ndarray, list[tuple[int, int]]]:
        rows = np.arange(40, dtype=np.float64)[:, None]
        terrain = np.repeat(200.0 - rows, 40, axis=1)
        inherited = [(row, 20) for row in range(2, 38)]
        # An inherited-axis bump is physically uphill; a monotonic route must
        # use terrain elsewhere in the allowed corridor.
        terrain[18:22, 20] += 20.0
        return terrain, inherited

    def test_monotonic_astar_honours_contact_and_does_not_reward_axis(self) -> None:
        terrain, inherited = self._detour_fixture()
        grid = GridWindow(0.0, 0.0, rows=40, cols=40)
        result = build_route_candidate(
            terrain,
            grid,
            inherited,
            "stream",
            ordered_contacts=[(24, 19)],
        )
        self.assertEqual(result.path_cells[0], inherited[0])
        self.assertEqual(result.path_cells[-1], inherited[-1])
        self.assertIn((24, 19), result.path_cells)
        elevations = np.asarray([terrain[cell] for cell in result.path_cells])
        self.assertLessEqual(float(np.diff(elevations).max(initial=0.0)), 0.0)
        self.assertFalse(result.lineage["inherited_axis_used_in_objective"])
        self.assertLess(float(result.metrics["candidate_exact_inherited_fraction"]), 1.0)
        self.assertGreater(float(result.metrics["candidate_max_divergence_m"]), 0.0)
        self.assertEqual(len(result.coordinates), len(result.path_cells))
        json.dumps(result.serialisable())
        feature = result.geojson_feature(feature_id="TEST-R1")
        self.assertEqual(feature["geometry"]["type"], "LineString")

        replay = build_route_candidate(
            terrain,
            grid,
            inherited,
            "stream",
            ordered_contacts=[(24, 19)],
        )
        self.assertEqual(replay.path_cells, result.path_cells)
        self.assertEqual(replay.lineage["route_cell_hash"], result.lineage["route_cell_hash"])

    def test_monotonic_barrier_fails_closed(self) -> None:
        terrain = np.repeat((100.0 - np.arange(20, dtype=np.float64))[:, None], 20, axis=1)
        terrain[10, :] += 50.0
        corridor = np.ones_like(terrain, dtype=bool)
        with self.assertRaisesRegex(RouteReconstructionError, "No monotonic route"):
            monotonic_astar_route(terrain, corridor, (1, 10), (18, 10))

    def test_boundary_and_corridor_edge_diagnostics_are_exported(self) -> None:
        rows = np.arange(30, dtype=np.float64)[:, None]
        terrain = np.repeat(100.0 - rows, 30, axis=1)
        grid = GridWindow(5.0, 7.0, rows=30, cols=30)
        inherited = [(row, 0) for row in range(30)]
        result = build_route_candidate(terrain, grid, inherited, "stream")
        self.assertTrue(result.metrics["source_on_window_boundary"])
        self.assertTrue(result.metrics["receiver_on_window_boundary"])
        self.assertGreaterEqual(int(result.metrics["window_boundary_crossing_count"]), 1)
        coordinates = export_candidate_route_coordinates(result.path_cells, grid)
        self.assertEqual(coordinates[0], grid.cell_center(result.path_cells[0]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
