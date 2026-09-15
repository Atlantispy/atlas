"""Small independent grid flood/connectivity and storage oracles."""
import copy
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import random
import unittest
from unittest.mock import patch

import basin_topology as b
import water


def neighbours(i, shape, connectivity):
    rows, cols = shape
    y, x = divmod(i, cols)
    return [r * cols + c for r in range(max(0, y - 1), min(rows, y + 2))
            for c in range(max(0, x - 1), min(cols, x + 2))
            if (r, c) != (y, x) and (connectivity == 8 or abs(r - y) + abs(c - x) == 1)]


def connected(bed, shape, seeds, level, connectivity=4, strict=False):
    allowed = {i for i, z in enumerate(bed) if z < level or not strict and z == level}
    seen = set(seeds) & allowed
    todo = list(seen)
    while todo:
        i = todo.pop()
        for j in neighbours(i, shape, connectivity):
            if j in allowed and j not in seen:
                seen.add(j)
                todo.append(j)
    return seen


def brute_exterior_levels(bed, shape, outlets, connectivity):
    result = [None] * len(bed)
    for level in sorted(set(bed)):
        for i in connected(bed, shape, outlets, level, connectivity):
            if result[i] is None:
                result[i] = level
    return result


def rows_and_owners(topology):
    rows = {row["id"]: row for row in topology["basins"]}
    owner = {child: row["id"] for row in rows.values() for child in row["children"]}
    return rows, owner


def root_of(leaf, owner):
    while leaf in owner:
        leaf = owner[leaf]
    return leaf


def topology_levels(bed, topology):
    rows, owner = rows_and_owners(topology)
    result = []
    for i, leaf in enumerate(topology["cell_to_leaf"]):
        if leaf is None:
            result.append(bed[i])
        else:
            sill = rows[root_of(leaf, owner)]["spill_m"]
            result.append(None if sill is None else max(bed[i], sill))
    return result


def store(bed, topology, volumes, area=None):
    return water.fill_spill_merge(bed, area or [1.] * len(bed), topology["basins"], volumes,
                                 **topology["storage_options"])


class BasinTopologyTests(unittest.TestCase):
    def near(self, actual, expected):
        self.assertLessEqual(abs(actual - expected), 1e-9 + 1e-12 * max(abs(actual), abs(expected)))

    def test_single_pit_zero_partial_overflow(self):
        bed = [9., 3., 9., 9., 0., 9., 9., 9., 9.]
        t = b.extract_basin_topology(bed, [3, 3], [1])
        self.assertEqual(t["leaf_pit_indices"], {"leaf_0004": 4})
        self.assertEqual(t["basins"][0]["spill_m"], 3.)
        for amount, depth, exported in ((0., 0., 0.), (2., 2., 0.), (4., 3., 1.)):
            r = store(bed, t, {"leaf_0004": amount})
            self.assertEqual(r["water_depth_m"][4], depth)
            self.assertEqual(r["exported_volume_m3"], exported)
            self.assertEqual(r["water_residual_m3"], 0.)

    def test_flat_floor_has_one_pit_without_epsilon_bed(self):
        bed = [3., 3., 3., 3., 0., 0., 3., 3., 3.]
        before = bed[:]
        t = b.extract_basin_topology(bed, [3, 3], [0])
        self.assertEqual(t["leaf_pit_indices"], {"leaf_0004": 4})
        self.assertEqual(t["raw_receivers"][5], 4)
        r = store(bed, t, {"leaf_0004": 1.})
        self.assertEqual(r["water_depth_m"][4:6], [.5, .5])
        self.assertEqual(bed, before)

    def test_all_flat_closed_grid(self):
        t = b.extract_basin_topology([5.] * 16, [4, 4], [])
        self.assertEqual(t["leaf_ids"], ["leaf_0000"])
        self.assertIsNone(t["basins"][0]["spill_m"])
        r = store([5.] * 16, t, {"leaf_0000": 32.})
        self.assertEqual(r["water_depth_m"], [2.] * 16)
        self.assertEqual(r["exported_volume_m3"], 0.)

    def test_all_flat_open_grid_direct_export_not_fake_basin(self):
        t = b.extract_basin_topology([5.] * 16, [4, 4], [0, 15])
        self.assertEqual(t["basins"], [])
        self.assertEqual(t["cell_to_leaf"], [None] * 16)
        self.assertEqual(set(t["terminal_indices"]), {0, 15})

    def test_nested_analytic_profile(self):
        bed = [6., 0., 2., 0., 4., 1., 6.]
        t = b.extract_basin_topology(bed, [1, 7], [0, 6])
        self.assertEqual(sorted(e["spill_m"] for e in t["saddle_events"]), [2., 4., 6.])
        cases = [(3., [0, 2, 0, 1, 0, 0, 0], 0.), (7., [0, 3, 1, 3, 0, 0, 0], 0.),
                 (12., [0, 4, 2, 4, 0, 2, 0], 0.), (18., [0, 5, 3, 5, 1, 4, 0], 0.),
                 (26., [0, 6, 4, 6, 2, 5, 0], 3.)]
        for amount, expected, exported in cases:
            supply = dict.fromkeys(t["leaf_ids"], 0.)
            supply["leaf_0001"] = amount
            r = store(bed, t, supply)
            self.assertEqual(r["water_depth_m"], expected)
            self.assertEqual(r["exported_volume_m3"], exported)

    def test_one_way_high_root_enters_lower_leaf(self):
        bed = [0., 2., 0., 5., 3., 6.]
        t = b.extract_basin_topology(bed, [1, 6], [0])
        rows, _ = rows_and_owners(t)
        self.assertEqual(rows["leaf_0004"]["spill_to_leaf"], "leaf_0002")
        self.assertEqual(rows["leaf_0004"]["spill_m"], 5.)
        self.assertEqual(rows["leaf_0002"]["spill_m"], 2.)
        r = store(bed, t, {"leaf_0002": 0., "leaf_0004": 7.})
        self.assertEqual(r["water_depth_m"], [0., 0., 2., 0., 2., 0.])
        self.assertEqual(r["exported_volume_m3"], 3.)

    def test_simultaneous_three_way_merge_uses_explicit_option(self):
        bed = [6., 0., 2., 0., 2., 0., 6.]
        t = b.extract_basin_topology(bed, [1, 7], [0, 6])
        self.assertTrue(t["storage_options"]["allow_simultaneous_merges"])
        supply = {"leaf_0001": 7., "leaf_0003": 0., "leaf_0005": 0.}
        with self.assertRaises(ValueError):
            water.fill_spill_merge(bed, [1.] * 7, t["basins"], supply)
        r = store(bed, t, supply)
        for got, expected in zip(r["water_depth_m"], [0., 2.2, .2, 2.2, .2, 2.2, 0.]):
            self.near(got, expected)
        self.near(r["stored_volume_m3"], 7.)

    def test_simultaneous_join_and_exterior_stage(self):
        bed = [2., 0., 2., 0., 2.]
        t = b.extract_basin_topology(bed, [1, 5], [0, 4])
        self.assertTrue(t["storage_options"]["allow_simultaneous_merges"])
        r = store(bed, t, {"leaf_0001": 5., "leaf_0003": 0.})
        self.assertEqual(r["water_depth_m"], [0., 2., 0., 2., 0.])
        self.assertEqual(r["exported_volume_m3"], 1.)

    def test_one_ulp_difference_is_not_collapsed(self):
        bed = [6., 0., 2., 0., math.nextafter(2., 3.), 0., 6.]
        t = b.extract_basin_topology(bed, [1, 7], [0, 6])
        self.assertFalse(t["storage_options"]["allow_simultaneous_merges"])
        self.assertEqual([e["spill_m"] for e in t["saddle_events"]][:2], [2., math.nextafter(2., 3.)])

    def test_connectivity_choice_changes_only_declared_topology(self):
        bed = [0., 9., 9., 9., 1., 9., 9., 9., 9.]
        four = b.extract_basin_topology(bed, [3, 3], [0], connectivity=4)
        eight = b.extract_basin_topology(bed, [3, 3], [0], connectivity=8)
        self.assertEqual(topology_levels(bed, four)[4], 9.)
        self.assertEqual(topology_levels(bed, eight)[4], 1.)

    def test_brute_threshold_connectivity_random_fields(self):
        rng = random.Random(82731)
        for connectivity in (4, 8):
            for trial in range(36):
                bed = [float(rng.randrange(12)) for _ in range(20)]
                outlets = [0, 19] if trial % 2 else [0]
                with self.subTest(connectivity=connectivity, trial=trial):
                    t = b.extract_basin_topology(bed, [4, 5], outlets, connectivity=connectivity)
                    self.assertEqual(topology_levels(bed, t), brute_exterior_levels(bed, [4, 5], outlets, connectivity))

    def test_brute_spill_footprints_capacities_and_saturated_storage(self):
        rng = random.Random(93)
        for trial in range(30):
            bed = [float(rng.randrange(15)) for _ in range(25)]
            t = b.extract_basin_topology(bed, [5, 5], [0, 24])
            rows, owner = rows_and_owners(t)
            area = [float(1 + i % 3) for i in range(25)]
            for row in rows.values():
                descendants = []
                for leaf, pit in t["leaf_pit_indices"].items():
                    node = leaf
                    while node != row["id"] and node in owner:
                        node = owner[node]
                    if node == row["id"]:
                        descendants.append(pit)
                sill = row["spill_m"]
                expected = connected(bed, [5, 5], descendants, sill, strict=True)
                actual = {i for i in row["cell_indices"] if bed[i] < sill}
                self.assertEqual(actual, expected)
                self.assertEqual(math.fsum((sill - bed[i]) * area[i] for i in actual),
                                 math.fsum((sill - bed[i]) * area[i] for i in expected))
            if t["basins"]:
                result = store(bed, t, dict.fromkeys(t["leaf_ids"], 10000.), area)
                expected = [0. if leaf is None else max(rows[root_of(leaf, owner)]["spill_m"] - bed[i], 0.)
                            for i, leaf in enumerate(t["cell_to_leaf"])]
                self.assertEqual(result["water_depth_m"], expected)
                self.near(result["stored_volume_m3"] + result["exported_volume_m3"], 10000. * len(t["leaf_ids"]))

    def test_variable_runoff_area_and_tree_storage_ledger(self):
        bed = [6., 0., 2., 0., 4., 1., 6.]
        t = b.extract_basin_topology(bed, [1, 7], [0, 6])
        area = [1., 2., 3., 4., 5., 6., 7.]
        runoff = [2., 1., 0., 3., 2., 1., 4.]
        edges = [[] if j is None else [[j, 1.]] for j in t["raw_receivers"]]
        flux = water.accumulate_runoff(edges, area, runoff, t["terminal_kinds"])
        supply = {leaf: flux["discharge_m3_per_year"][pit] for leaf, pit in t["leaf_pit_indices"].items()}
        direct = math.fsum(flux["discharge_m3_per_year"][i] for i in t["external_outlet_indices"])
        r = store(bed, t, supply, area)
        self.near(r["stored_volume_m3"] + r["exported_volume_m3"] + direct, math.fsum(a * q for a, q in zip(area, runoff)))
        self.assertEqual(flux["area_residual_m2"], 0.)

    def test_varied_partial_supply_and_area_with_equal_saddles(self):
        rng = random.Random(188)
        simultaneous = 0
        for _ in range(128):
            bed = [float(rng.randrange(10)) for _ in range(25)]
            t = b.extract_basin_topology(bed, [5, 5], [0, 24])
            self.assertTrue(t["basins"])
            area = [.25 + rng.random() * 5 for _ in bed]
            supply = {leaf: rng.random() * 50 for leaf in t["leaf_ids"]}
            r = store(bed, t, supply, area)
            represented = math.fsum(d * a for d, a in zip(r["water_depth_m"], area))
            self.near(represented + r["exported_volume_m3"], math.fsum(supply.values()))
            self.assertTrue(all(d >= 0. for d in r["water_depth_m"]))
            simultaneous += t["storage_options"]["allow_simultaneous_merges"]
        self.assertEqual(simultaneous, 80)

    def test_determinism_input_preservation_json_and_status(self):
        bed = [6., 0., 2., 0., 2., 0., 6.]
        original = copy.deepcopy(bed)
        a = b.extract_basin_topology(bed, [1, 7], [0, 6])
        c = b.extract_basin_topology(bed, [1, 7], [6, 0])
        self.assertEqual(a, c)
        self.assertEqual(bed, original)
        json.dumps(a, allow_nan=False)
        self.assertFalse(a["physical_bed_changed"])
        self.assertFalse(a["production_authorised"])
        self.assertEqual(a["physical_depression_origin"], "UNRESOLVED")

    def test_every_raw_receiver_is_adjacent_nonascending_and_terminates(self):
        bed = [5., 5., 5., 4., 5., 1., 5., 4., 5., 5., 5., 4.]
        t = b.extract_basin_topology(bed, [3, 4], [3, 11])
        for i, j in enumerate(t["raw_receivers"]):
            if j is not None:
                self.assertIn(j, neighbours(i, [3, 4], 4))
                self.assertLessEqual(bed[j], bed[i])
            path = set()
            while j is not None:
                self.assertNotIn(j, path)
                path.add(j)
                j = t["raw_receivers"][j]

    def test_native_edge_outlets_only(self):
        with self.assertRaisesRegex(ValueError, "native edge"):
            b.extract_basin_topology([0.] * 9, [3, 3], [4])

    def test_bad_inputs(self):
        for value in (True, None, float("nan"), float("inf"), 10**1000, "0"):
            with self.subTest(value=str(value)[:16]), self.assertRaises(ValueError):
                b.extract_basin_topology([value], [1, 1], [])
        for shape in ([1, True], [0, 1], [2, 1], [1], None):
            with self.subTest(shape=shape), self.assertRaises(ValueError):
                b.extract_basin_topology([0.], shape, [])
        for outlets in ([True], [-1], [1], [0, 0], None, (0,)):
            with self.subTest(outlets=outlets), self.assertRaises(ValueError):
                b.extract_basin_topology([0.], [1, 1], outlets)
        for connectivity in (True, 6, 4., None):
            with self.assertRaises(ValueError):
                b.extract_basin_topology([0.], [1, 1], [], connectivity=connectivity)

    def test_cell_and_materialisation_bounds(self):
        with self.assertRaises(ValueError):
            b.extract_basin_topology([0.] * 4097, [1, 4097], [])
        with patch.object(b, "MAX_FOOTPRINT_REFERENCES", 4), self.assertRaises(ValueError):
            b.extract_basin_topology([6., 0., 2., 0., 6.], [1, 5], [0, 4])

    def test_closed_nested_grid_keeps_all_volume_and_maximum_cell_bound(self):
        bed = [6., 0., 2., 0., 4., 1., 6.]
        t = b.extract_basin_topology(bed, [1, 7], [])
        supply = dict.fromkeys(t["leaf_ids"], 0.)
        supply["leaf_0001"] = 40.
        r = store(bed, t, supply)
        self.near(r["stored_volume_m3"], 40.)
        self.assertEqual(r["exported_volume_m3"], 0.)
        self.assertEqual(t["root_ids"], [t["basins"][-1]["id"]])
        bounded = b.extract_basin_topology([0.] * 4096, [64, 64], [])
        self.assertEqual(len(bounded["raw_receivers"]), 4096)
        self.assertEqual(len(bounded["basins"]), 1)

    def test_opt_in_keeps_ownership_and_decreasing_sill_rejections(self):
        bed = [6., 0., 2., 0., 2., 0., 6.]
        t = b.extract_basin_topology(bed, [1, 7], [0, 6])
        for mutation in (lambda rows: rows[-1].update(spill_m=1.),
                         lambda rows: rows[-1].update(children=[rows[-1]["id"], rows[0]["id"]]),
                         lambda rows: rows[0].update(spill_to_leaf=rows[0]["id"])):
            rows = copy.deepcopy(t["basins"])
            mutation(rows)
            with self.assertRaises(ValueError):
                water.fill_spill_merge(bed, [1.] * 7, rows, dict.fromkeys(t["leaf_ids"], 1.),
                                      allow_simultaneous_merges=True)

    def test_strict_default_unchanged_against_preserved_reference(self):
        path = Path(__file__).parent / "reference_versions" / "water_before_equal_saddles.py"
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), "82d79ebb85448a1cfe5c467fcc5e488989985e21cb625d28df60b5b734cffaeb")
        spec = importlib.util.spec_from_file_location("water_strict_reference", path)
        old = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(old)
        bed = [6., 0., 2., 0., 4., 1., 6.]
        t = b.extract_basin_topology(bed, [1, 7], [0, 6])
        for volumes in ([3., 0., 0.], [13., 2., 3.], [100., 0., 0.]):
            supply = dict(zip(t["leaf_ids"], volumes))
            self.assertEqual(water.fill_spill_merge(bed, [1.] * 7, t["basins"], supply),
                             old.fill_spill_merge(bed, [1.] * 7, t["basins"], supply))

    def test_equal_merge_option_does_not_allow_bad_root_links_or_types(self):
        rows = [{"id": "A", "cell_indices": [0], "children": [], "spill_m": 2., "spill_to_leaf": "B"},
                {"id": "B", "cell_indices": [1], "children": [], "spill_m": 2., "spill_to_leaf": "A"}]
        for option in (False, True, 1, "true", None):
            with self.subTest(option=option), self.assertRaises(ValueError):
                water.fill_spill_merge([0., 0.], [1., 1.], rows, {"A": 1., "B": 0.}, allow_simultaneous_merges=option)

    def test_peer_equal_sill_nested_sum_roundoff_and_nextafter(self):
        bed = [2., 0., 2., 0., 2., 0., 2.]
        area = [61.60283281598898, 32.14384608849953, 40.94379757496146,
                43.446177094934434, 89.30011189209158, 50.30023602935599, 35.7351305748853]
        t = b.extract_basin_topology(bed, [1, 7], [0, 6])
        capacity = math.fsum(2 * area[i] for i in (1, 3, 5))
        self.assertEqual(capacity, 251.7805184255799)
        for amount in (math.nextafter(capacity, 0.), capacity, math.nextafter(capacity, math.inf)):
            supply = dict.fromkeys(t["leaf_ids"], 0.)
            supply["leaf_0001"] = amount
            r = store(bed, t, supply, area)
            if amount <= capacity:
                self.assertEqual(r["exported_volume_m3"], 0.)
            else:
                self.assertGreater(r["exported_volume_m3"], 0.)
            self.near(r["stored_volume_m3"] + r["exported_volume_m3"], amount)
            for correction in r["simultaneous_merge_representation"]:
                self.assertLessEqual(abs(correction["adjustment_m3"]), correction["ulp_bound_m3"])
            if amount == capacity:
                self.assertEqual(r["stored_volume_m3"], capacity)
                self.assertEqual(r["merge_representation_adjustment_m3"], -2.842170943040401e-14)


if __name__ == "__main__":
    unittest.main()
