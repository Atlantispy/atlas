"""Independent tiny-grid review of extraction and equal-sill storage.

No source writes, terrain generation or physical acceptance claims. The exact
capacity regression was found before its implementation repair. Comparisons
retain the existing water ledger tolerance; topology uses exact comparisons.
"""
from copy import deepcopy
import hashlib
import heapq
import importlib.util
import math
from pathlib import Path
import unittest

import basin_topology as topology
import water


def neighbour_ids(i, shape, eight=False):
    rows, cols = shape
    row, col = divmod(i, cols)
    result = []
    for j in range(rows * cols):
        other_row, other_col = divmod(j, cols)
        dy, dx = abs(row - other_row), abs(col - other_col)
        if max(dx, dy) == 1 and (eight or dx + dy == 1):
            result.append(j)
    return result


def minimax_escape(bed, shape, outlets, eight=False):
    """Independent all-cell minimax search, without labels or catchment edges."""
    costs = [math.inf] * len(bed)
    queue = []
    for outlet in outlets:
        costs[outlet] = bed[outlet]
        heapq.heappush(queue, (bed[outlet], outlet))
    while queue:
        cost, i = heapq.heappop(queue)
        if cost != costs[i]:
            continue
        for j in neighbour_ids(i, shape, eight):
            proposed = max(cost, bed[j])
            if proposed < costs[j]:
                costs[j] = proposed
                heapq.heappush(queue, (proposed, j))
    return costs


def storage(bed, area, result, supply):
    return water.fill_spill_merge(bed, area, result["basins"], supply,
                                 **result["storage_options"])


class BasinPeerTests(unittest.TestCase):
    def near_volume(self, got, expected):
        self.assertLessEqual(abs(got - expected),
                             water.VOLUME_ATOL + water.RTOL * max(abs(got), abs(expected)))

    def test_equal_sill_geometric_capacity_not_rejected_by_nested_rounding(self):
        bed = [2., 0., 2., 0., 2., 0., 2.]
        area = [61.60283281598898, 32.14384608849953, 40.94379757496146,
                43.446177094934434, 89.30011189209158, 50.30023602935599,
                35.7351305748853]
        graph = topology.extract_basin_topology(bed, [1, 7], [0, 6])
        self.assertTrue(graph["storage_options"]["allow_simultaneous_merges"])
        capacity = math.fsum((2. - z) * a for z, a in zip(bed, area))
        self.assertEqual(capacity, 251.7805184255799)
        supply = dict.fromkeys(graph["leaf_ids"], 0.)
        supply[graph["leaf_ids"][0]] = capacity
        previous = Path(__file__).parent / "reference_versions" / "water_equal_saddles_before_roundoff.py"
        self.assertEqual(hashlib.sha256(previous.read_bytes()).hexdigest(),
                         "b3b21906fb3b9da95a111959edd4d9f3c3d0e64b3bc4d9ce449bf014b6a53f5d")
        spec = importlib.util.spec_from_file_location("peer_pre_roundoff_water", previous)
        old = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(old)
        with self.assertRaisesRegex(ValueError, "active pool still contains unhandled overflow"):
            old.fill_spill_merge(bed, area, graph["basins"], supply, **graph["storage_options"])
        result = storage(bed, area, graph, supply)
        self.near_volume(result["stored_volume_m3"], capacity)
        self.near_volume(result["exported_volume_m3"], 0.)
        for got, expected in zip(result["water_depth_m"], [0., 2., 0., 2., 0., 2., 0.]):
            self.assertAlmostEqual(got, expected, places=12)
        self.near_volume(math.fsum(d * a for d, a in zip(result["water_depth_m"], area)) +
                         result["exported_volume_m3"], capacity)

    def test_equal_sill_one_ulp_below_and_above_capacity_preserve_ledgers(self):
        bed = [2., 0., 2., 0., 2., 0., 2.]
        area = [1., 32.14384608849953, 1., 43.446177094934434, 1., 50.30023602935599, 1.]
        graph = topology.extract_basin_topology(bed, [1, 7], [0, 6])
        capacity = math.fsum((2. - z) * a for z, a in zip(bed, area))
        for supplied in (math.nextafter(capacity, 0.), capacity, math.nextafter(capacity, math.inf)):
            with self.subTest(supplied=supplied):
                supply = dict.fromkeys(graph["leaf_ids"], 0.)
                supply[graph["leaf_ids"][0]] = supplied
                result = storage(bed, area, graph, supply)
                self.near_volume(result["stored_volume_m3"] + result["exported_volume_m3"], supplied)
                self.assertGreaterEqual(min(result["water_depth_m"]), 0.)
                self.assertLessEqual(max(result["water_depth_m"]), 2.)
                if supplied <= capacity:
                    self.assertEqual(result["exported_volume_m3"], 0.)
                else:
                    self.assertGreater(result["exported_volume_m3"], 0.)
                for record in result["simultaneous_merge_representation"]:
                    self.assertLessEqual(abs(record["adjustment_m3"]), record["ulp_bound_m3"])

    def test_multiple_tied_closed_components_attach_to_existing_exterior(self):
        cases = [([0., 2., 0., 2., 0., 2., 0.], [1, 7], [0, 6]),
                 ([0., 3., 0., 3., 0., 3., 0., 3., 0.], [3, 3], [0, 8]),
                 ([1., 5., 2., 5., 0., 5., 3., 5., 1.], [3, 3], [0, 8])]
        for bed, shape, outlets in cases:
            for connectivity in (4, 8):
                with self.subTest(bed=bed, connectivity=connectivity):
                    graph = topology.extract_basin_topology(bed, shape, outlets, connectivity=connectivity)
                    rows = {row["id"]: row for row in graph["basins"]}
                    parent = {child: row["id"] for row in rows.values() for child in row["children"]}
                    expected = minimax_escape(bed, shape, outlets, connectivity == 8)
                    for i, leaf in enumerate(graph["cell_to_leaf"]):
                        if leaf is None:
                            actual = bed[i]
                        else:
                            while leaf in parent:
                                leaf = parent[leaf]
                            actual = max(bed[i], rows[leaf]["spill_m"])
                        self.assertEqual(actual, expected[i])
                    self.assertEqual(graph, topology.extract_basin_topology(bed, shape, list(reversed(outlets)), connectivity=connectivity))

    def test_nested_unequal_supply_matches_independent_volume_stage_solution(self):
        bed = [6., 0., 2., 0., 4., 1., 6.]
        graph = topology.extract_basin_topology(bed, [1, 7], [0, 6])
        supply = {"leaf_0001": 1., "leaf_0003": 5., "leaf_0005": .5}
        result = storage(bed, [1.] * 7, graph, supply)
        expected = [0., 8. / 3., 2. / 3., 8. / 3., 0., .5, 0.]
        for got, wanted in zip(result["water_depth_m"], expected):
            self.assertAlmostEqual(got, wanted, places=13)
        self.near_volume(result["stored_volume_m3"], 6.5)
        self.assertEqual(result["exported_volume_m3"], 0.)
        self.assertEqual(result, storage(bed, [1.] * 7, graph, dict(reversed(list(supply.items())))))

    def test_high_root_link_fills_lower_root_once_then_exports(self):
        bed = [0., 2., 0., 5., 3., 6.]
        graph = topology.extract_basin_topology(bed, [1, 6], [0])
        rows = {row["id"]: row for row in graph["basins"]}
        self.assertEqual(rows["leaf_0004"]["spill_to_leaf"], "leaf_0002")
        self.assertGreater(rows["leaf_0004"]["spill_m"], rows["leaf_0002"]["spill_m"])
        result = storage(bed, [1.] * 6, graph, {"leaf_0002": 1., "leaf_0004": 7.})
        self.assertEqual(result["water_depth_m"], [0., 0., 2., 0., 2., 0.])
        self.assertEqual(result["stored_volume_m3"], 4.)
        self.assertEqual(result["exported_volume_m3"], 4.)

    def test_plateau_paths_are_shortest_to_declared_seeds_and_do_not_ascend(self):
        bed = [2., 2., 2., 2., 2., 2., 2., 2., 2.]
        before = deepcopy(bed)
        graph = topology.extract_basin_topology(bed, [3, 3], [0, 8])
        self.assertEqual(graph["basins"], [])
        for first, receiver in enumerate(graph["raw_receivers"]):
            seen = {first}
            while receiver is not None:
                self.assertNotIn(receiver, seen)
                self.assertIn(receiver, neighbour_ids(first, [3, 3]))
                self.assertLessEqual(bed[receiver], bed[first])
                seen.add(receiver); first = receiver
                receiver = graph["raw_receivers"][receiver]
            self.assertIn(first, [0, 8])
        # Distances can be recomputed directly on this unobstructed square.
        for i in range(9):
            length = 0; j = i
            while graph["raw_receivers"][j] is not None:
                j = graph["raw_receivers"][j]; length += 1
            row, col = divmod(i, 3)
            self.assertEqual(length, min(row + col, 4 - row - col))
        self.assertEqual(bed, before)


if __name__ == "__main__":
    unittest.main()
