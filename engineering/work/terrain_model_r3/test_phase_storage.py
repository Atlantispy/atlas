"""Independent tiny analytical and grid-connectivity tests; no terrain replay."""
import copy
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import random
import sys
import unittest
from unittest.mock import patch

import phase_storage as p


def route(bed, w, s, *, area=None, outlets=None, shape=None, connectivity=4):
    return p.route_phases(bed, area or [1.] * len(bed), shape or [1, len(bed)],
                          [0, len(bed) - 1] if outlets is None else outlets,
                          w, s, connectivity=connectivity)


def brute_escape_levels(bed, shape, outlets, connectivity):
    # Enumerate threshold-connected cells directly; no catchments/union tree.
    rows, cols = shape
    result = [None] * len(bed)
    for level in sorted(set(bed)):
        seen = {i for i in outlets if bed[i] <= level}
        todo = list(seen)
        while todo:
            i = todo.pop()
            y, x = divmod(i, cols)
            for j, z in enumerate(bed):
                yy, xx = divmod(j, cols)
                dy, dx = abs(y - yy), abs(x - xx)
                adjacent = max(dy, dx) == 1 and (connectivity == 8 or dx + dy == 1)
                if adjacent and z <= level and j not in seen:
                    seen.add(j)
                    todo.append(j)
        for i in seen:
            if result[i] is None:
                result[i] = level
    return result


class PhaseStorageTests(unittest.TestCase):
    def near(self, got, expected, atol=1e-9):
        self.assertLessEqual(abs(got - expected), atol + 1e-12 * max(abs(got), abs(expected)))

    def conserved(self, result, w, s):
        self.near(math.fsum(result["liquid_m3"]) + result["exported_liquid_m3"], math.fsum(w))
        self.near(math.fsum(result["suspended_solid_m3"]) + result["exported_suspended_solid_m3"], math.fsum(s))
        self.assertEqual(result["ledger"]["exact_mixture_routing_residual_m3"], 0.)
        self.assertTrue(all(v >= 0 and math.isfinite(v) for key in ("liquid_m3", "suspended_solid_m3", "mixture_depth_m") for v in result[key]))

    def test_zero_storage_does_not_create_water_or_lake(self):
        r = route([3., 0., 3.], [0.] * 3, [0.] * 3)
        self.assertEqual(r["liquid_m3"], [0.] * 3)
        self.assertEqual(r["water_surface_m"], [None] * 3)
        self.assertEqual(r["active_pools"][0]["solid_volume_fraction"], 0.)
        self.assertEqual(r["assumptions"]["physical_depression_origin"], "UNRESOLVED")

    def test_single_pool_analytic_partial_and_no_second_surface(self):
        r = route([5., 0., 5.], [0., 1.5, 0.], [0., .5, 0.])
        self.assertEqual(r["mixture_depth_m"], [0., 2., 0.])
        self.assertEqual(r["water_surface_m"], [None, 2., None])
        self.assertEqual(r["liquid_equivalent_depth_m"], [0., 1.5, 0.])
        self.assertEqual(r["active_pools"][0]["solid_volume_fraction"], .25)

    def test_design_mixed_overflow_analytic(self):
        w, s = [0., 99.9, 0.], [0., .1, 0.]
        r = route([50., 0., 50.], w, s)
        self.near(r["liquid_m3"][1], 49.95)
        self.near(r["suspended_solid_m3"][1], .05)
        self.near(r["exported_liquid_m3"], 49.95)
        self.near(r["exported_suspended_solid_m3"], .05)
        self.conserved(r, w, s)

    def test_exact_binary_fraction_overflow(self):
        r = route([2., 0., 2.], [0., 3., 0.], [0., 1., 0.])
        self.assertEqual(r["liquid_m3"][1], 1.5)
        self.assertEqual(r["suspended_solid_m3"][1], .5)
        self.assertEqual(r["exported_liquid_m3"], 1.5)
        self.assertEqual(r["exported_suspended_solid_m3"], .5)

    def test_exact_cap_and_adjacent_float_pulses(self):
        for w in (math.nextafter(1.5, 0.), 1.5, math.nextafter(1.5, math.inf)):
            r = route([2., 0., 2.], [0., w, 0.], [0., .5, 0.])
            if w <= 1.5:
                self.assertEqual(r["exported_liquid_m3"], 0.)
            else:
                self.assertGreater(r["exported_liquid_m3"], 0.)
                self.assertGreater(r["exported_suspended_solid_m3"], 0.)
            self.conserved(r, [0., w, 0.], [0., .5, 0.])

    def test_separate_leaves_keep_unequal_concentrations(self):
        r = route([6., 0., 2., 0., 6.], [0., 1., 0., .75, 0.], [0., .5, 0., .25, 0.])
        pools = r["active_pools"]
        self.assertEqual(len(pools), 2)
        self.near(pools[0]["solid_volume_fraction"], 1 / 3)
        self.assertEqual(pools[1]["solid_volume_fraction"], .25)
        self.assertNotEqual(pools[0]["solid_volume_fraction"], pools[1]["solid_volume_fraction"])

    def test_local_high_root_spill_mixes_with_lower_existing_storage(self):
        # Higher root: retain (1.5,.5), send (4.5,1.5). Lower (1,1)
        # mixes to (5.5,2.5), retains 1/4 and exports the other 3/4.
        w, s = [0., 0., 1., 0., 6., 0.], [0., 0., 1., 0., 2., 0.]
        r = route([0., 2., 0., 5., 3., 6.], w, s, outlets=[0])
        self.assertEqual(r["liquid_m3"][2], 1.375)
        self.assertEqual(r["suspended_solid_m3"][2], .625)
        self.assertEqual(r["liquid_m3"][4], 1.5)
        self.assertEqual(r["suspended_solid_m3"][4], .5)
        self.assertEqual(r["exported_liquid_m3"], 4.125)
        self.assertEqual(r["exported_suspended_solid_m3"], 1.875)
        self.conserved(r, w, s)

    def test_existing_lower_root_is_loaded_before_upstream_spill_regardless_of_ids(self):
        # Reflection puts the upstream leaf first. The lower pre-existing
        # inventory must be present before its incoming parcel is mixed.
        r = route([6., 3., 5., 0., 2., 0.], [0., 6., 0., 1., 0., 0.],
                  [0., 2., 0., 1., 0., 0.], outlets=[5])
        self.assertEqual(r["liquid_m3"][3], 1.375)
        self.assertEqual(r["suspended_solid_m3"][3], .625)
        self.assertEqual(r["exported_liquid_m3"], 4.125)
        self.assertEqual(r["exported_suspended_solid_m3"], 1.875)

    def test_nested_join_volume_and_phase_analytic(self):
        bed = [6., 0., 2., 0., 4., 1., 6.]
        w, s = [0., 10., 0., 1., 0., 2., 0.], [0., 2., 0., 1., 0., 1., 0.]
        r = route(bed, w, s)
        self.assertEqual(len(r["active_pools"]), 1)
        self.near(r["active_pools"][0]["stage_m"], 4.8)
        for i in (1, 2, 3, 4, 5):
            self.near(r["suspended_solid_m3"][i] / (r["liquid_m3"][i] + r["suspended_solid_m3"][i]), 4 / 17)
        self.conserved(r, w, s)

    def test_three_way_equal_sill_mix_cascades_with_zero_overflow(self):
        bed = [2., 0., 2., 0., 2., 0., 2.]
        r = route(bed, [0., 1.5, 0., 1., 0., .5, 0.], [0., .5, 0., 1., 0., 1.5, 0.])
        self.assertEqual(len(r["active_pools"]), 1)
        self.assertEqual(r["active_pools"][0]["solid_volume_fraction"], .5)
        self.assertEqual(r["liquid_m3"], [0., 1., 0., 1., 0., 1., 0.])
        self.assertEqual(r["suspended_solid_m3"], r["liquid_m3"])
        self.assertEqual(r["exported_liquid_m3"], 0.)
        self.assertEqual(len([e for e in r["events"] if e["kind"] == "merge"]), 2)

    def test_equal_sill_fractional_areas_roundoff_has_explicit_geometry_residual(self):
        bed = [2., 0., 2., 0., 2., 0., 2.]
        area = [61.60283281598898, 32.14384608849953, 40.94379757496146,
                43.446177094934434, 89.30011189209158, 50.30023602935599, 35.7351305748853]
        capacity = math.fsum(2 * area[i] for i in (1, 3, 5))
        for supplied in (math.nextafter(capacity, 0.), capacity, math.nextafter(capacity, math.inf)):
            w, s = [0., supplied, 0., 0., 0., 0., 0.], [0.] * 7
            r = route(bed, w, s, area=area)
            exact = sum((Fraction(2) * Fraction(area[i]) for i in (1, 3, 5)), Fraction())
            self.near(r["exported_liquid_m3"], float(max(Fraction(supplied) - exact, 0)), atol=1e-25)
            self.conserved(r, w, s)

    def test_coupled_overflow_settling_partial_stage_first_failure(self):
        # Captured from the independent coupled ODE's 20-step refinement.
        # Exact V is below capacity, but old R2 float inversion gave eta>5.
        bed = [5., .0006534607301867122, 5.]
        w, s = [0., 49.94995673061804, 0.], [0., .04350866208009101, 0.]
        exact_volume = Fraction(w[1]) + Fraction(s[1])
        exact_stage = Fraction(bed[1]) + exact_volume / 10
        self.assertLess(exact_stage, Fraction(5))
        r = route(bed, w, s, area=[10.] * 3)
        self.assertEqual(r["active_pools"][0]["stage_m"], float(exact_stage))
        self.assertLessEqual(r["active_pools"][0]["stage_m"], 5.)
        self.assertEqual(r["exported_liquid_m3"], 0.)
        self.assertEqual(r["exported_suspended_solid_m3"], 0.)
        self.conserved(r, w, s)

    def test_exact_piecewise_area_depth_with_negative_bed_and_breakpoints(self):
        # Independent two-segment inverse: A=2 below z1, then A=5.
        for volume in (1., 5., 6., 7., 16., math.nextafter(26., 0.), 26.):
            expected = (Fraction(-2) + Fraction(volume) / 2 if volume <= 6 else
                        Fraction(1) + (Fraction(volume) - 6) / 5)
            r = route([5., -2., 1., 5.], [0., volume, 0., 0.], [0.] * 4,
                      area=[1., 2., 3., 1.])
            self.assertEqual(r["active_pools"][0]["stage_m"], float(expected))
            self.assertLessEqual(r["active_pools"][0]["stage_m"], 5.)

    def test_partial_stage_is_monotone_at_sill_adjacent_float_volumes(self):
        volume = 26.
        amounts = [volume]
        for _ in range(24):
            volume = math.nextafter(volume, 0.)
            amounts.append(volume)
        stages = []
        for volume in reversed(amounts):
            r = route([5., -2., 1., 5.], [0., volume, 0., 0.], [0.] * 4,
                      area=[1., 2., 3., 1.])
            stages.append(r["active_pools"][0]["stage_m"])
            self.assertEqual(r["exported_liquid_m3"], 0.)
        self.assertEqual(stages, sorted(stages))
        self.assertLessEqual(max(stages), 5.)

    def test_closed_flat_pool_variable_areas(self):
        w, s = [1., 2., 3., 4.], [.25, .5, .75, 1.]
        r = route([5.] * 4, w, s, area=[1., 2., 3., 4.], outlets=[])
        self.assertEqual(r["mixture_depth_m"], [1.25] * 4)
        self.assertEqual(r["water_surface_m"], [6.25] * 4)
        self.assertEqual(r["liquid_m3"], w)
        self.assertEqual(r["suspended_solid_m3"], s)
        self.conserved(r, w, s)

    def test_closed_nonflat_stage_independent_weighted_sum(self):
        r = route([5., 0., 1., 5.], [0., 10., 0., 0.], [0., 3., 0., 0.],
                  area=[1., 2., 3., 4.], outlets=[])
        self.near(r["active_pools"][0]["stage_m"], 3.2)
        self.near(r["liquid_m3"][1], 10 * 6.4 / 13)
        self.near(r["suspended_solid_m3"][2], 3 * 6.6 / 13)
        self.assertEqual(r["exported_liquid_m3"], 0.)

    def test_all_direct_export_keeps_both_phases(self):
        w, s = [1., 2., 3., 4.], [.1, .2, .3, .4]
        r = route([5.] * 4, w, s, outlets=[0, 3])
        self.assertEqual(r["active_pools"], [])
        self.assertEqual(r["exported_liquid_m3"], 10.)
        self.assertEqual(r["exported_suspended_solid_m3"], 1.)
        self.assertEqual(r["liquid_m3"], [0.] * 4)

    def test_saturation_matches_brute_threshold_connectivity(self):
        rng = random.Random(81137)
        for connectivity in (4, 8):
            for _ in range(12):
                bed = [float(rng.randrange(10)) for _ in range(20)]
                area = [float(rng.randrange(1, 4)) for _ in bed]
                w, s = [10000.] * 20, [rng.random() * 100 for _ in bed]
                r = route(bed, w, s, shape=[4, 5], area=area, outlets=[0, 19], connectivity=connectivity)
                levels = brute_escape_levels(bed, [4, 5], [0, 19], connectivity)
                self.assertEqual(r["mixture_depth_m"], [level - z for level, z in zip(levels, bed)])
                self.conserved(r, w, s)

    def test_random_partial_unequal_concentration_conservation_and_cell_geometry(self):
        rng = random.Random(711)
        for _ in range(32):
            bed = [float(rng.randrange(12)) for _ in range(25)]
            area = [.5 + rng.random() * 4 for _ in bed]
            w, s = [rng.random() * 8 for _ in bed], [rng.random() for _ in bed]
            r = route(bed, w, s, shape=[5, 5], area=area, outlets=[0, 24])
            self.conserved(r, w, s)
            for wi, si, a, d in zip(r["liquid_m3"], r["suspended_solid_m3"], area, r["mixture_depth_m"]):
                self.near(wi + si, a * d)

    def test_output_stores_can_be_reused_without_phase_loss(self):
        bed, area = [6., 0., 2., 0., 4., 1., 6.], [1.] * 7
        a = route(bed, [0., 10., 0., 1., 0., 2., 0.], [0., 2., 0., 1., 0., 1., 0.])
        b = route(bed, a["liquid_m3"], a["suspended_solid_m3"], area=area)
        for key in ("liquid_m3", "suspended_solid_m3", "mixture_depth_m"):
            for x, y in zip(a[key], b[key]):
                self.near(x, y)
        self.assertEqual(b["exported_liquid_m3"], 0.)
        self.assertEqual(b["exported_suspended_solid_m3"], 0.)

    def test_inputs_preserved_outputs_independent_and_json_finite(self):
        args = [[3., 0., 3.], [1., 1., 1.], [1, 3], [0, 2], [0., 1., 0.], [0., .5, 0.]]
        before = copy.deepcopy(args)
        r = p.route_phases(*args)
        self.assertEqual(args, before)
        r["liquid_m3"][1] = 8.
        self.assertEqual(args, before)
        json.dumps(r, allow_nan=False)
        self.assertFalse(r["assumptions"]["production_authorised"])

    def test_repeated_calls_and_outlet_order_are_deterministic(self):
        args = ([6., 0., 2., 0., 6.], [0., 3., 0., 1., 0.], [0., 1., 0., 1., 0.])
        self.assertEqual(route(*args), route(*args, outlets=[4, 0]))
        self.assertEqual(route(*args), route(*args))

    def test_dry_solids_rejected_even_if_other_cells_have_water(self):
        with self.assertRaisesRegex(ValueError, "dry suspended"):
            route([3., 0., 3.], [1., 0., 0.], [0., 1., 0.])

    def test_invalid_phase_area_and_bed_types_fail_controlled(self):
        for bad in (True, None, "1", float("nan"), float("inf"), 10**1000):
            for which in (0, 1, 4, 5):
                args = [[0.], [1.], [1, 1], [], [1.], [0.]]
                args[which] = [bad]
                with self.subTest(which=which, bad=str(bad)[:20]), self.assertRaises(ValueError):
                    p.route_phases(*args)
        for which in (1, 4, 5):
            args = [[0.], [1.], [1, 1], [], [1.], [0.]]
            args[which] = [-1.]
            with self.assertRaises(ValueError):
                p.route_phases(*args)

    def test_shape_lengths_outlets_and_connectivity_validation(self):
        for change in ((1, [1., 1.]), (2, [1, True]), (2, [1, 2]), (3, [True]), (3, [0, 0])):
            args = [[0.], [1.], [1, 1], [], [1.], [0.]]
            args[change[0]] = change[1]
            with self.assertRaises(ValueError):
                p.route_phases(*args)
        with self.assertRaisesRegex(ValueError, "native edge"):
            route([0.] * 9, [0.] * 9, [0.] * 9, shape=[3, 3], outlets=[4])
        with self.assertRaises(ValueError):
            route([0.], [0.], [0.], outlets=[], connectivity=True)

    def test_bound_and_positive_but_unrepresentable_stage(self):
        with self.assertRaises(ValueError):
            route([0.] * 4097, [0.] * 4097, [0.] * 4097, outlets=[])
        with self.assertRaises(ValueError):
            route([1e20], [1.], [0.], outlets=[])
        with self.assertRaises(ValueError):
            route([0.], [1e308], [1e308], outlets=[])
        with self.assertRaises(ValueError):
            route([1e308, -1e308, 1e308], [0.] * 3, [0.] * 3)

    def test_full_cell_bound_closed_flat(self):
        r = route([0.] * 4096, [1.] * 4096, [.25] * 4096, shape=[64, 64], outlets=[])
        self.assertEqual(r["mixture_depth_m"], [1.25] * 4096)
        self.assertEqual(r["exported_liquid_m3"], 0.)

    def test_positive_unrepresentable_phase_split_or_allocation_rejects(self):
        with self.assertRaisesRegex(ValueError, "underflows"):
            p._split((1., 1.), Fraction(1, 10**1000), Fraction(2))
        with self.assertRaisesRegex(ValueError, "underflows"):
            p._distribute(1e-300, [1e-100, 1.])
        with self.assertRaisesRegex(ValueError, "underflows"):
            p._float(Fraction(1, 10**1000))

    def test_geometric_allocation_adjustment_is_explicit(self):
        r = route([0., 0., 0.], [10., 0., 0.], [3., 0., 0.], outlets=[], area=[1., 2., 4.])
        pool = r["active_pools"][0]
        for prefix in ("liquid", "solid"):
            self.assertIn(prefix + "_allocation_adjustment_m3", pool)
            self.near(pool[prefix + "_allocation_residual_m3"], 0.)

    def test_pinned_sources_and_no_named_module_mutation(self):
        markers = {name: sys.modules.get(name) for name in ("water", "basin_topology")}
        r = route([2., 0., 2.], [0., 1., 0.], [0., 0., 0.])
        self.assertEqual(markers, {name: sys.modules.get(name) for name in markers})
        for row in r["source_binding"].values():
            self.assertEqual(hashlib.sha256(Path(row["path"]).read_bytes()).hexdigest(), row["sha256"])

    def test_source_pin_failure_before_loading(self):
        with patch.dict(p.SOURCE_PINS, {"water.py": "0" * 64}), self.assertRaisesRegex(ValueError, "identity mismatch"):
            route([0.], [1.], [0.], outlets=[])

    def test_changed_source_after_computation_fails_instead_of_returning_pass(self):
        original = Path.read_bytes
        reads = 0
        def changed(path):
            nonlocal reads
            data = original(path)
            if path.name == "water.py":
                reads += 1
                if reads == 2:
                    return data + b"\n# mocked changed bytes"
            return data
        with patch.object(Path, "read_bytes", changed), self.assertRaisesRegex(ValueError, "changed during"):
            route([0.], [1.], [0.], outlets=[])


if __name__ == "__main__":
    unittest.main()
