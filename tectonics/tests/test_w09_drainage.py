"""Synthetic graph controls for W09, not empirical watershed validation."""
from dataclasses import FrozenInstanceError
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import numpy as np
from numpy.testing import assert_array_equal

from atlas_tectonics._validation import TectonicsError
from atlas_tectonics.resources import MemoryLimitError, WorkBudget
from atlas_tectonics.w09_drainage import prepare_drainage


def prepare(bed, areas, links, lengths, outlets=(), **kwargs):
    return prepare_drainage(bed, areas, links, lengths, outlets,
                            frame_id=kwargs.pop("frame_id", "synthetic-frame"),
                            datum_id=kwargs.pop("datum_id", "synthetic-datum"),
                            source_id=kwargs.pop("source_id", "synthetic-case"), **kwargs)


class DrainageTests(unittest.TestCase):
    def assert_upstream_order(self, result):
        positions = {int(node): i for i, node in enumerate(result.order)}
        self.assertEqual(len(positions), len(result.bed_m))
        for node, receiver in enumerate(result.receivers):
            if node != receiver:
                self.assertLess(positions[node], positions[int(receiver)])

    def test_frozen_w1_receiver_change_and_physical_bed(self):
        register = json.loads((Path(__file__).parents[1] / "cases" /
                              "w09_surface_processes_r1.json").read_text(encoding="utf-8"))
        case = next(c for c in register["controls"] if c["id"] == "W09-W1-receiver-change")
        ids = {name: i for i, name in enumerate(case["nodes"])}
        links = [[ids[a], ids[b]] for a, b in case["links"]]
        bed = np.asarray(case["elevation_m"], dtype=float)
        original = prepare(bed, case["areas_m2"], links, case["link_lengths_m"], [ids["O"]])
        self.assertEqual(original.receivers[ids["B"]], ids[case["expected_initial_receiver_of_B"]])
        assert_array_equal(original.receivers, [1, 2, 2, 3])
        assert_array_equal(original.basin_of, [-3, -3, -3, 0])
        self.assertEqual(original.saddles, ((0, -3, 2.0),))
        assert_array_equal(original.spill_elevations_m, [3, 2, 0, 2])
        bed[ids["O"]] = case["independent_dry_restart_changed_O_elevation_m"]
        changed = prepare(bed, case["areas_m2"], links, case["link_lengths_m"], [ids["O"]])
        self.assertEqual(changed.receivers[ids["B"]], ids[case["expected_changed_receiver_of_B"]])
        assert_array_equal(changed.basin_cells[0], [0, 1, 3])
        assert_array_equal(changed.bed_m, bed)
        assert_array_equal(original.bed_m, case["elevation_m"])
        self.assertEqual(changed.saddles, ((0, -3, 3.0),))
        self.assertNotEqual(changed.signature, original.signature)
        self.assert_upstream_order(original)
        self.assert_upstream_order(changed)

    def test_flat_bfs_outlet_and_closed_pit_are_acyclic(self):
        flat = prepare([2, 2, 2, 1, 1], [1, 1, 1, 0, 0],
                       [[0, 1], [1, 2], [0, 3], [2, 4]], [1, 1, 1, 1], [3, 4])
        assert_array_equal(flat.receivers, [3, 0, 4, 3, 4])
        self.assert_upstream_order(flat)
        closed = prepare([1, 1, 1, 1], [0, 1, 1, 1],
                         [[0, 1], [0, 2], [1, 3], [2, 3]], [1, 1, 1, 1])
        assert_array_equal(closed.receivers, [0, 0, 0, 1])
        assert_array_equal(closed.basin_of, [0, 0, 0, 0])
        self.assertTrue(np.all(np.isposinf(closed.spill_elevations_m)))
        assert_array_equal(closed.spill_parents, [-1] * 4)
        self.assertEqual(closed.saddles, ())
        self.assert_upstream_order(closed)
        tie = prepare([3, 1, 2], [1, 0, 0], [[0, 2], [0, 1]], [1, 2], [1, 2])
        self.assertEqual(tie.receivers[0], 1)

    def test_nested_zero_area_saddles_and_complete_adjacency(self):
        # W3: two physical storage cells, a zero-area internal saddle, an outlet.
        nested = prepare([0, -1, 1, 3], [1, 1, 0, 0],
                         [[0, 2], [1, 2], [2, 3]], [1, 1, 1], [3])
        assert_array_equal(nested.basin_cells[0], [0])
        assert_array_equal(nested.basin_cells[1], [1, 2])
        self.assertEqual(nested.saddles, ((0, 1, 1.0), (1, -4, 3.0)))
        assert_array_equal(nested.spill_elevations_m, [3, 3, 3, 3])
        # Three pits have all three links, including a connection above either
        # child's lowest sill, plus two alternatives for the 0-to-1 boundary.
        complete = prepare([0, 0, 0, 1, 2, 4, 5, 6], [1, 1, 1, 0, 0, 0, 0, 0],
                           [[0, 3], [1, 3], [1, 4], [2, 4], [0, 5], [2, 5],
                            [0, 6], [1, 6], [2, 7]], [1] * 9, [7])
        self.assertEqual(complete.saddles,
                         ((0, 1, 1.0), (0, 2, 4.0), (1, 2, 2.0), (2, -8, 6.0)))
        assert_array_equal(complete.spill_elevations_m, [6] * 8)
        self.assert_upstream_order(complete)
        # W2's area-weighted bathymetry is kept exactly for the water solver.
        weighted = prepare([0, 1, 2], [2, 1, 0], [[0, 1], [1, 2]], [1, 1], [2])
        assert_array_equal(weighted.basin_cells[0], [0, 1])
        assert_array_equal(weighted.areas_m2, [2, 1, 0])
        self.assertEqual(weighted.saddles, ((0, -3, 2.0),))

    def test_immutable_detached_inputs_identity_and_permuted_links(self):
        bed, areas = np.array([3., 2., 0.]), np.array([1., 1., 0.])
        links, lengths = np.array([[0, 1], [1, 2]]), np.array([2., 1.])
        result = prepare(bed, areas, links, lengths, [2])
        equivalent = prepare([3, 2, 0], [1, 1, 0], [[2, 1], [1, 0]], [1, 2], [2])
        self.assertEqual(result.signature, equivalent.signature)
        bed[0], areas[0], links[0, 0], lengths[0] = 100, 100, 2, 100
        assert_array_equal(result.bed_m, [3, 2, 0])
        assert_array_equal(result.areas_m2, [1, 1, 0])
        assert_array_equal(result.links, [[0, 1], [1, 2]])
        assert_array_equal(result.link_lengths_m, [2, 1])
        arrays = (result.bed_m, result.areas_m2, result.links, result.link_lengths_m,
                  result.receivers, result.order, result.basin_of,
                  result.spill_elevations_m, result.spill_parents, *result.basin_cells)
        self.assertEqual(result.nbytes, sum(a.nbytes for a in arrays))
        for array in arrays:
            with self.assertRaises(ValueError):
                array.setflags(write=True)
        with self.assertRaises(FrozenInstanceError):
            result.frame_id = "other"
        self.assertEqual(result.outlet_nodes, (2,))
        self.assertEqual(result.frame_id, "synthetic-frame")
        for field in ("frame_id", "datum_id", "source_id"):
            other = prepare([3, 2, 0], [1, 1, 0], [[0, 1], [1, 2]], [2, 1], [2],
                            **{field: "different"})
            self.assertNotEqual(result.signature, other.signature)
            with self.assertRaises(TectonicsError):
                prepare([0], [1], [], [], **{field: " "})

    def test_validation_bounds_indices_and_storage_minimum(self):
        invalid = [
            ([0], [1], [[0, 0]], [1], []),
            ([1, 0], [1, 0], [[0, 1], [1, 0]], [1, 1], [1]),
            ([1, 0], [1, 0], [[False, 1]], [1], [1]),
            ([1, 0], [1, 0], [[0.0, 1.0]], [1], [1]),
            ([1, 0], [1, 0], [[0, 2]], [1], [1]),
            ([1, 0], [1, 0], [[0, 1]], [0], [1]),
            ([1, 0], [1, 0], [[0, 1]], [float("inf")], [1]),
            ([1, float("nan")], [1, 0], [[0, 1]], [1], [1]),
            ([1, 0], [-1, 0], [[0, 1]], [1], [1]),
            ([1, 0], [1, 1], [[0, 1]], [1], [1]),
            ([1, 0], [1, 0], [[0, 1]], [1], [True]),
            ([1, 0], [1, 0], [[0, 1]], [1], [1, 1]),
            ([0, 1], [0, 1], [[0, 1]], [1], []),
            ([0] * 257, [1] * 257, [], [], []),
            ([0], [1], [[0, 0]] * 2049, [1] * 2049, []),
        ]
        for values in invalid:
            with self.subTest(values=values[:2]), self.assertRaises(TectonicsError):
                prepare(*values)
        isolated = prepare([0, -2], [1, 1], [], [])
        self.assertEqual(len(isolated.basin_cells), 2)
        self.assertEqual(isolated.saddles, ())
        assert_array_equal(isolated.receivers, [0, 1])

    def test_budget_admission_precedes_materialisation_and_releases(self):
        tiny = WorkBudget(1)
        with patch("atlas_tectonics.w09_drainage.snapshot", side_effect=AssertionError("allocated")):
            with self.assertRaises(MemoryLimitError):
                prepare([0], [1], [], [], budget=tiny)
        self.assertEqual(tiny.reserved_bytes, 0)
        budget = WorkBudget(128 * 1024 * 1024)
        result = prepare([0], [1], [], [], budget=budget)
        self.assertGreater(budget.peak_reserved_bytes, result.nbytes)
        self.assertEqual(budget.reserved_bytes, 0)
        with self.assertRaises(TectonicsError):
            prepare([0], [0], [], [], budget=budget)
        self.assertEqual(budget.reserved_bytes, 0)


if __name__ == "__main__":
    unittest.main()
