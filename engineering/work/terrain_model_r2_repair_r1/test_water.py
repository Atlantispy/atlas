"""Preregistered conservation oracles and small adversarial water fixtures."""
from copy import deepcopy
import json
import math
import random
import unittest
from unittest.mock import patch

import water as w


def nested():
    return [0., 0., 2., 1., 4.], [1.] * 5, [
        {"id": "A", "cell_indices": [0], "children": [], "spill_m": 2., "spill_to_leaf": "B"},
        {"id": "B", "cell_indices": [1], "children": [], "spill_m": 2., "spill_to_leaf": "A"},
        {"id": "AB", "cell_indices": [0, 1, 2], "children": ["A", "B"], "spill_m": 4., "spill_to_leaf": "C"},
        {"id": "C", "cell_indices": [3], "children": [], "spill_m": 4., "spill_to_leaf": "A"},
        {"id": "ABC", "cell_indices": [0, 1, 2, 3, 4], "children": ["AB", "C"], "spill_m": 6., "spill_to_leaf": None},
    ]


class WaterTests(unittest.TestCase):
    def near(self, value, expected):
        self.assertTrue(math.isfinite(value))
        self.assertLessEqual(abs(value - expected), 1e-9 + 1e-12 * max(abs(value), abs(expected)))

    def test_frozen_tolerances(self):
        self.assertEqual((w.VOLUME_ATOL, w.AREA_ATOL, w.RTOL), (1e-9, 1e-9, 1e-12))
        self.assertEqual((w.MAX_CELLS, w.MAX_EDGES), (16384, 131072))

    def test_bounded_edge_guard(self):
        # Exercise guard without allocating an intentionally huge graph.
        with patch.object(w, "MAX_EDGES", 0), self.assertRaisesRegex(ValueError, "edge count"):
            w.accumulate_runoff([[[1, 1.]], []], [1., 1.], [0., 0.], {1: "PHYSICAL_EXPORT"})

    def test_priority_flood_sill_and_immutable_bed(self):
        bed = [9., 9., 9., 9., 0., 9., 9., 3., 9.]
        original = list(bed)
        result = w.priority_flood(bed, [3, 3], [7])
        self.assertEqual(bed, original)
        self.assertEqual(result["routing_surface_m"][4], 3.)
        self.assertEqual(result["conditioning_depth_m"][4], 3.)
        self.assertEqual(result["receivers"][7], None)
        rank = {i: k for k, i in enumerate(result["pop_order"])}
        for i, receiver in enumerate(result["receivers"]):
            if receiver is not None:
                self.assertLess(rank[receiver], rank[i])
                self.assertLessEqual(result["routing_surface_m"][receiver], result["routing_surface_m"][i])

    def test_priority_independent_repeated_relaxation_oracle(self):
        # Bellman-style minimax relaxation; no heap or predecessor reuse.
        rng = random.Random(813)
        for connectivity in (4, 8):
            for _ in range(5):
                bed = [float(rng.randrange(0, 7)) for _ in range(25)]
                outlets = [0, 24]
                expected = [math.inf] * 25
                for i in outlets:
                    expected[i] = bed[i]
                for _ in range(25):
                    old = list(expected)
                    for i in range(25):
                        y, x = divmod(i, 5)
                        neighbours = [j for j in range(25) if j != i and
                                      max(abs(j // 5 - y), abs(j % 5 - x)) == 1 and
                                      (connectivity == 8 or abs(j // 5 - y) + abs(j % 5 - x) == 1)]
                        expected[i] = min([old[i]] + [max(bed[i], old[j]) for j in neighbours])
                self.assertEqual(w.priority_flood(bed, [5, 5], outlets, connectivity=connectivity)["routing_surface_m"], expected)

    def test_flat_ties_and_outlet_order_repeat_exactly(self):
        a = w.priority_flood([2.] * 16, [4, 4], [0, 15], connectivity=8)
        b = w.priority_flood([2.] * 16, [4, 4], [15, 0], connectivity=8)
        self.assertEqual(a, b)
        self.assertEqual(a["conditioning_depth_m"], [0.] * 16)
        self.assertIs(a["physical_bed_changed"], False)

    def test_priority_cell_cap_and_explicit_boundary(self):
        result = w.priority_flood([0.] * 16384, [128, 128], [0])
        self.assertEqual(len(result["pop_order"]), 16384)
        for arguments in (([0.] * 16385, [1, 16385], [0]), ([0.], [1, 1], []),
                          ([0.], [1, 2], [0]), ([0.], [1, 1], [0, 0]),
                          ([0.], [1, 1], [True]), ([float("nan")], [1, 1], [0])):
            with self.assertRaises(ValueError):
                w.priority_flood(*arguments)

    def test_variable_runoff_fractional_confluence(self):
        edges = [[[1, .25], [2, .75]], [[3, 1.]], [[3, 1.]], []]
        result = w.accumulate_runoff(edges, [1., 2., 3., 4.], [2., 3., 0., 1.], {3: "PHYSICAL_EXPORT"})
        self.assertEqual(result["contributing_area_m2"], [1., 2.25, 3.75, 10.])
        self.assertEqual(result["discharge_m3_per_year"], [2., 6.5, 1.5, 12.])
        self.assertEqual(result["water_residual_m3_per_year"], 0.)
        zero = w.accumulate_runoff(edges, [1., 2., 3., 4.], [0.] * 4, {3: "PHYSICAL_EXPORT"})
        self.assertEqual(zero["discharge_m3_per_year"], [0.] * 4)
        self.assertEqual(zero["contributing_area_m2"], result["contributing_area_m2"])
        self.assertEqual(zero["topological_order"], result["topological_order"])

    def test_terminal_status_and_multiple_outputs_are_not_conflated(self):
        result = w.accumulate_runoff([[[1, .5], [2, .5]], [], []], [1.] * 3, [2.] * 3,
                                     {1: "BASIN_STORAGE", 2: "UNRESOLVED_CROP"})
        self.assertEqual([r["discharge_m3_per_year"] for r in result["terminals"]], [3., 3.])
        self.assertEqual([r["kind"] for r in result["terminals"]], ["BASIN_STORAGE", "UNRESOLVED_CROP"])
        self.assertIs(result["terminal_authorities_independently_verified"], False)

    def test_accumulation_bad_graphs_and_forcing(self):
        invalid = [([[[1, 1.]], [[0, 1.]]], {}),
                   ([[[1, .9]], []], {1: "PHYSICAL_EXPORT"}),
                   ([[[1, .5], [1, .5]], []], {1: "PHYSICAL_EXPORT"}),
                   ([[[1, 0.]], []], {1: "PHYSICAL_EXPORT"}),
                   ([[[1, 1.]], []], {}),
                   ([[[1, 1.]], []], {1: "UNKNOWN"}),
                   ([[[1, 1.]], []], {True: "PHYSICAL_EXPORT"})]
        for edges, terminal in invalid:
            with self.subTest(edges=edges, terminal=terminal), self.assertRaises(ValueError):
                w.accumulate_runoff(edges, [1., 1.], [1., 1.], terminal)
        for bad in (None, -1., float("nan"), float("inf"), True, 10**1000):
            with self.subTest(forcing=str(bad)[:20]), self.assertRaises(ValueError):
                w.accumulate_runoff([[]], [1.], [bad], {0: "PHYSICAL_EXPORT"})

    def test_weighted_basin_zero_partial_spill_overflow(self):
        for volume, stage, stored, export in ((0., None, 0., 0.), (1., 1., 1., 0.),
                                               (5., 3., 5., 0.), (7., 3., 5., 2.)):
            result = w.basin_storage([0., 2.], [1., 2.], volume, spill_m=3.)
            self.assertEqual(result["stage_m"], stage)
            self.near(result["stored_volume_m3"], stored)
            self.near(result["exported_volume_m3"], export)
            self.near(result["water_residual_m3"], 0.)

    def test_closed_basin_and_stage_offset(self):
        a = w.basin_storage([0., 2.], [1., 2.], 7.)
        b = w.basin_storage([100., 102.], [1., 2.], 7.)
        self.near(a["stage_m"], 11 / 3)
        self.near(b["stage_m"] - a["stage_m"], 100.)
        self.near(a["stored_volume_m3"], 7.)
        self.assertEqual(a["exported_volume_m3"], 0.)

    def test_volume_preserving_cell_subdivision(self):
        a = w.basin_storage([0., 2.], [1., 2.], 5., spill_m=4.)
        b = w.basin_storage([0., 0., 2., 2.], [.5, .5, 1., 1.], 5., spill_m=4.)
        self.assertEqual(a["stage_m"], b["stage_m"])
        self.assertEqual(a["stored_volume_m3"], b["stored_volume_m3"])

    def test_nested_zero_partial_merged_overflow(self):
        bed, area, tree = nested()
        expected = [(0., [0.] * 5, 0.), (3., [2., 1., 0., 0., 0.], 0.),
                    (7., [3., 3., 1., 0., 0.], 0.), (12., [4., 4., 2., 2., 0.], 0.),
                    (18., [5., 5., 3., 4., 1.], 0.), (26., [6., 6., 4., 5., 2.], 3.)]
        for volume, depths, exported in expected:
            with self.subTest(volume=volume):
                result = w.fill_spill_merge(bed, area, tree, {"A": volume, "B": 0., "C": 0.})
                self.assertEqual(result["water_depth_m"], depths)
                self.near(result["exported_volume_m3"], exported)
                self.near(result["stored_volume_m3"], volume - exported)
                self.near(sum(p["stored_volume_m3"] for p in result["active_pools"]), volume - exported)
                self.near(result["water_residual_m3"], 0.)
                self.assertIs(result["physical_bed_changed"], False)

    def test_nested_exact_sill_and_near_tie_no_early_spill(self):
        bed, area, tree = nested()
        for volume in (23., math.nextafter(23., 0.)):
            result = w.fill_spill_merge(bed, area, tree, {"A": volume, "B": 0., "C": 0.})
            self.assertEqual(result["exported_volume_m3"], 0.)
        result = w.fill_spill_merge(bed, area, tree, {"A": math.nextafter(23., math.inf), "B": 0., "C": 0.})
        self.assertGreater(result["exported_volume_m3"], 0.)

    def test_different_leaf_supply_respects_unfilled_siblings(self):
        bed, area, tree = nested()
        result = w.fill_spill_merge(bed, area, tree, {"A": 0., "B": 0., "C": 2.})
        self.assertEqual(result["water_depth_m"], [0., 0., 0., 2., 0.])
        result = w.fill_spill_merge(bed, area, tree, {"A": 0., "B": 0., "C": 6.})
        self.assertEqual(result["water_depth_m"], [2., 1., 0., 3., 0.])

    def test_nested_input_preservation_and_order_determinism(self):
        bed, area, tree = nested()
        before = deepcopy((bed, area, tree))
        a = w.fill_spill_merge(bed, area, tree, {"A": 13., "B": 2., "C": 3.})
        b = w.fill_spill_merge(bed, area, list(reversed(tree)), {"C": 3., "B": 2., "A": 13.})
        self.assertEqual(a, b)
        self.assertEqual((bed, area, tree), before)
        json.dumps(a, allow_nan=False)

    def test_nested_many_supply_distributions_independent_global_ledger(self):
        bed, area, tree = nested()
        rng = random.Random(517)
        for _ in range(64):
            supply = {name: rng.random() * 30 for name in ("A", "B", "C")}
            result = w.fill_spill_merge(bed, area, tree, supply)
            geometric_store = math.fsum(result["water_depth_m"])
            self.near(geometric_store + result["exported_volume_m3"], math.fsum(supply.values()))
            self.assertLessEqual(geometric_store, 23.)
            for depth, z in zip(result["water_depth_m"], bed):
                self.assertGreaterEqual(depth, 0.)
                self.assertLessEqual(depth, 6. - z)
            if result["exported_volume_m3"] > 0:
                self.assertEqual(result["water_depth_m"], [6., 6., 4., 5., 2.])

    def test_closed_root_keeps_all_supplied_water(self):
        bed, area, tree = nested()
        tree[-1]["spill_m"] = None
        result = w.fill_spill_merge(bed, area, tree, {"A": 26., "B": 0., "C": 0.})
        self.near(result["stored_volume_m3"], 26.)
        self.assertEqual(result["exported_volume_m3"], 0.)
        self.near(result["active_pools"][0]["stage_m"], 6.6)

    def test_root_overflow_to_separate_lower_basin(self):
        basins = [{"id": "upper", "cell_indices": [0], "children": [], "spill_m": 5., "spill_to_leaf": "lower"},
                  {"id": "lower", "cell_indices": [1], "children": [], "spill_m": 2., "spill_to_leaf": None}]
        result = w.fill_spill_merge([3., 0.], [1., 1.], basins, {"upper": 7., "lower": 0.})
        self.assertEqual(result["water_depth_m"], [2., 2.])
        self.assertEqual(result["exported_volume_m3"], 3.)
        self.assertEqual(result["stored_volume_m3"], 4.)

    def test_bad_hierarchy_structure_and_geolinks(self):
        modifications = [lambda t: t[0].update(spill_to_leaf="C"),
                         lambda t: t[1].update(spill_m=math.nextafter(2., 3.)),
                         lambda t: t[1].update(cell_indices=[0]),
                         lambda t: t[2].update(cell_indices=[0, 1]),
                         lambda t: t[4].update(children=["ABC", "C"]),
                         lambda t: t[0].update(spill_m=None),
                         lambda t: t[0].update(extra=True),
                         lambda t: t[2].update(children=["A", "A"]),
                         lambda t: t[4].update(spill_to_leaf="A")]
        for modify in modifications:
            bed, area, tree = nested()
            modify(tree)
            # Missing marginal cell2 is not intrinsically invalid unless the
            # root treats it as below its merge; that also fails here.
            with self.subTest(tree=tree), self.assertRaises(ValueError):
                w.fill_spill_merge(bed, area, tree, {"A": 1., "B": 0., "C": 0.})

    def test_basin_invalid_inputs_and_storage_precision(self):
        for volume in (-1., float("inf"), float("nan"), True, 10**1000):
            with self.assertRaises(ValueError):
                w.basin_storage([0.], [1.], volume)
        for bed, area in (([], []), ([0.], [0.]), ([0.], [-1.]), ([0.], [1., 1.]), ([1e308, -1e308], [1., 1.])):
            with self.assertRaises(ValueError):
                w.basin_storage(bed, area, 1., spill_m=2.)
        with self.assertRaises(ValueError):
            w.basin_storage([1e20], [1.], 1.)  # Cannot represent1m depth at datum1e20.

    def sediment(self, **changes):
        parameters = dict(incoming_solid_m3_per_year=2., water_discharge_m3_per_year=10.,
                          settling_m_per_year=1., cell_area_m2=10., bed_m=0., receiving_stage_m=1.,
                          interval_years=3.)
        parameters.update(changes)
        return w.local_sediment_deposition(**parameters)

    def test_deposition_independent_column_oracle(self):
        result = self.sediment()
        self.assertEqual(result["deposited_solid_m3"], 3.)
        self.assertEqual(result["exported_solid_m3"], 3.)
        self.near(result["proposed_bed_m"], .3)
        self.near(result["solid_residual_m3"], 0.)
        self.assertIs(result["hydraulics_solved"], False)

    def test_deposition_accommodation_and_zero_supply_limits(self):
        limited = self.sediment(receiving_stage_m=.1)
        self.assertEqual(limited["deposited_solid_m3"], 1.)
        self.assertEqual(limited["exported_solid_m3"], 5.)
        for changes in ({"incoming_solid_m3_per_year": 0.}, {"settling_m_per_year": 0.},
                        {"interval_years": 0.}, {"receiving_stage_m": -1.},
                        {"incoming_solid_m3_per_year": 0., "water_discharge_m3_per_year": 0.}):
            self.assertEqual(self.sediment(**changes)["deposited_solid_m3"], 0.)

    def test_deposition_no_material_creation_at_large_settling(self):
        result = self.sediment(settling_m_per_year=1e20)
        self.assertLessEqual(result["deposited_solid_m3"], result["supplied_solid_m3"])
        self.near(result["deposited_solid_m3"] + result["exported_solid_m3"], 6.)

    def test_saturated_deposition_never_rounds_above_stage(self):
        stage = -.39707738715007823
        result = self.sediment(bed_m=-1.2844983005794042, receiving_stage_m=stage,
                               cell_area_m2=87.36896532656586,
                               incoming_solid_m3_per_year=1000.)
        self.assertEqual(result["proposed_bed_m"], stage)
        self.assertEqual(result["deposited_solid_m3"], result["accommodation_m3"])
        self.near(result["representation_residual_m3"], 0.)

    def test_deposition_invalid_regime_units_and_values(self):
        for changes in ({"porosity": .1}, {"porosity": False}, {"water_discharge_m3_per_year": 0.},
                        {"interval_years": -1.}, {"settling_m_per_year": -1.},
                        {"cell_area_m2": 0.}, {"bed_m": float("nan")},
                        {"incoming_solid_m3_per_year": float("inf")}, {"receiving_stage_m": "1m"},
                        {"settling_m_per_year": 1e308}, {"interval_years": 10**1000}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.sediment(**changes)
        with self.assertRaises(TypeError):
            self.sediment(discharge_units="m3/s")


if __name__ == "__main__":
    unittest.main()
