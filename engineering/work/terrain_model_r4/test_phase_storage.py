"""R4 analytical hydraulic-component tests; R3 numerical regressions retained."""
import copy
from concurrent.futures import ThreadPoolExecutor
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

    def assert_compound_zero_head(self, error, bed, shape, connectivity):
        self.assertIn("compound zero-head throughflow", str(error))
        wet = {i for i in error.context["cell_indices"] if bed[i] < error.context["spill_m"]}
        self.assertTrue(wet)
        rows, cols = shape
        seen, todo = {min(wet)}, [min(wet)]
        while todo:
            i = todo.pop()
            ri, ci = divmod(i, cols)
            for j in wet - seen:
                rj, cj = divmod(j, cols)
                dr, dc = abs(ri-rj), abs(ci-cj)
                if max(dr, dc) == 1 and (connectivity == 8 or dr+dc == 1):
                    seen.add(j)
                    todo.append(j)
        self.assertNotEqual(seen, wet, "a rejected compound root must actually lack a positive-depth connection")

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

    def test_three_way_equal_sill_ready_cascades_without_phase_mixing(self):
        bed = [2., 0., 2., 0., 2., 0., 2.]
        w, s = [0., 1.5, 0., 1., 0., .5, 0.], [0., .5, 0., 1., 0., 1.5, 0.]
        r = route(bed, w, s)
        self.assertEqual(len(r["active_pools"]), 3)
        self.assertEqual([x["solid_volume_fraction"] for x in r["active_pools"]], [.25, .5, .75])
        self.assertEqual(r["liquid_m3"], w)
        self.assertEqual(r["suspended_solid_m3"], s)
        self.assertEqual(r["exported_liquid_m3"], 0.)
        self.assertEqual(len([e for e in r["events"] if e["kind"] == "geometric_ready_no_mixing"]), 2)
        self.assertFalse(any(e["kind"] == "positive_depth_join" for e in r["events"]))

    def test_exact_sill_unequal_daughters_survive_ten_json_restarts(self):
        bed, w, s = [0., 2., 1.], [1.5, 0., .5], [.5, 0., .5]
        for _ in range(10):
            r = json.loads(json.dumps(route(bed, w, s, outlets=[]), allow_nan=False))
            self.assertEqual([q["wet_cell_indices"] for q in r["active_pools"]], [[0], [2]])
            self.assertEqual([q["stage_m"] for q in r["active_pools"]], [2., 2.])
            self.assertEqual([q["solid_volume_fraction"] for q in r["active_pools"]], [.25, .5])
            self.assertEqual(r["liquid_m3"], w)
            self.assertEqual(r["suspended_solid_m3"], s)
            self.conserved(r, w, s)
            w, s = r["liquid_m3"], r["suspended_solid_m3"]

    def test_positive_input_rejoins_daughters_above_saddle(self):
        w, s = [2.5, 0., .5], [.5, 0., .5]
        r = route([0., 2., 1.], w, s, outlets=[])
        self.assertEqual(len(r["active_pools"]), 1)
        pool = r["active_pools"][0]
        self.assertEqual(pool["wet_cell_indices"], [0, 1, 2])
        self.assertEqual(pool["stage_m"], 7 / 3)
        self.assertEqual(pool["solid_volume_fraction"], .25)
        self.assertEqual(len([e for e in r["events"] if e["kind"] == "positive_depth_join"]), 1)
        self.conserved(r, w, s)

    def test_three_way_equal_saddles_rejoin_only_with_positive_head(self):
        bed = [6., 0., 2., 0., 2., 0., 6.]
        w, s = [0., 2.5, 0., 1., 0., .5, 0.], [0., .5, 0., 1., 0., 1.5, 0.]
        r = route(bed, w, s)
        self.assertEqual(len(r["active_pools"]), 1)
        self.assertEqual(r["active_pools"][0]["wet_cell_indices"], [1, 2, 3, 4, 5])
        self.assertEqual(r["active_pools"][0]["stage_m"], 2.2)
        self.near(r["active_pools"][0]["solid_volume_fraction"], 3 / 7)
        self.conserved(r, w, s)

    def test_compound_zero_head_overflow_fails_without_choosing_flux_path(self):
        bed = [2., 0., 2., 0., 2.]
        with self.assertRaises(p.UnsupportedPhaseRouting) as rejected:
            route(bed, [0., 4., 0., .5, 0.], [0., .5, 0., 1.5, 0.])
        self.assert_compound_zero_head(rejected.exception, bed, [1, 5], 4)

    def test_unrepresentable_positive_head_never_becomes_epsilon_connection(self):
        w, s = [math.nextafter(1.5, math.inf), 0., .5], [.5, 0., .5]
        exact_head = (Fraction(w[0]) + Fraction(w[2]) + Fraction(1) - 3) / 3
        self.assertGreater(exact_head, 0)
        self.assertEqual(float(Fraction(2) + exact_head), 2.)
        with self.assertRaisesRegex(p.UnsupportedPhaseRouting, "connection is not representable"):
            route([0., 2., 1.], w, s, outlets=[])

    def test_negative_bed_sill_separation_is_translation_invariant(self):
        r = route([-3., -1., -2.], [1.5, 0., .5], [.5, 0., .5], outlets=[])
        self.assertEqual([q["stage_m"] for q in r["active_pools"]], [-1., -1.])
        self.assertEqual([q["solid_volume_fraction"] for q in r["active_pools"]], [.25, .5])

    def test_four_vs_eight_native_positive_depth_connections(self):
        bed, w, s = [0., 2., 3., 1.], [1.5, 0., 0., .5], [.5, 0., 0., .5]
        four = route(bed, w, s, outlets=[], shape=[2, 2], connectivity=4)
        eight = route(bed, w, s, outlets=[], shape=[2, 2], connectivity=8)
        self.assertEqual([q["wet_cell_indices"] for q in four["active_pools"]], [[0], [3]])
        self.assertEqual([q["solid_volume_fraction"] for q in four["active_pools"]], [.25, .5])
        self.assertEqual([q["wet_cell_indices"] for q in eight["active_pools"]], [[0, 3]])
        self.assertEqual(eight["active_pools"][0]["solid_volume_fraction"], 1 / 3)
        self.conserved(four, w, s)
        self.conserved(eight, w, s)

    def test_independent_decimal_oracle_daughters_remain_separate(self):
        # O01's independently derived rounded final column states, not values
        # generated by the production settling or phase-routing functions.
        bed = [.0001927890017539957, 2., 1.0001835648948079683]
        w = [1.9994333255550370025, 0., .9996666744449629975]
        s = [.0003738854432090018, 0., .0001497606602290342]
        for _ in range(2):
            r = route(bed, w, s, outlets=[])
            self.assertEqual([q["wet_cell_indices"] for q in r["active_pools"]], [[0], [2]])
            self.near(r["active_pools"][0]["solid_volume_fraction"], .0001869607435920631, 1e-16)
            self.near(r["active_pools"][1]["solid_volume_fraction"], .0001497881560761478, 1e-16)
            self.assertEqual(r["liquid_m3"], w)
            self.assertEqual(r["suspended_solid_m3"], s)
            w, s = r["liquid_m3"], r["suspended_solid_m3"]

    def test_raw_accumulated_event_bed_has_explicit_representability_failure(self):
        # Preserved first root-integration state before a complete route/settle
        # handoff. No implicit adjustment of water, solids or bed is permitted.
        base = [0., 1.9999, 1.]
        deposited = [.00019278900175404205, 9.999999999976694e-05, .00018356489480796827]
        bed = [z + b for z, b in zip(base, deposited)]
        w = [1.9994333255550367, 0., .9996666744449628]
        s = [.0003738854432091884, 0., .00014976066022903413]
        self.assertEqual(bed[1], math.nextafter(2., 0.))
        residue = [Fraction(w[i]) + Fraction(s[i]) - (Fraction(bed[1]) - Fraction(bed[i])) for i in (0, 2)]
        self.assertGreater(residue[0], 0)
        self.assertLess(residue[1], 0)
        with self.assertRaisesRegex(p.UnsupportedPhaseRouting, "connection is not representable"):
            route(bed, w, s, outlets=[])

    def test_predecessor_release_and_source_pins_fail_closed(self):
        for name in ("R3_RELEASE_SHA256", "R3_PHASE_SHA256", "DESIGN_SHA256"):
            with self.subTest(name=name), patch.object(p, name, "0" * 64):
                with self.assertRaisesRegex(ValueError, "identity mismatch"):
                    route([0.], [1.], [0.], outlets=[])

    def test_full_sill_tracer_representation_is_exact_and_json_idempotent(self):
        bed = [0., 1.]
        w, s = [.8324199885056033, 0.], [.16758001149439675, 0.]
        first = route(bed, w, s, outlets=[1])
        certificate = first['active_pools'][0]['full_sill_representation']
        self.assertTrue(certificate['exact_capacity_matched'])
        self.assertFalse(certificate['physical_transfer'])
        self.assertEqual(certificate['adjustment_suspended_solid_m3'], -2.**-55)
        self.assertLessEqual(abs(certificate['adjustment_suspended_solid_m3']), certificate['arithmetic_bound_m3'])
        self.assertEqual(Fraction(first['liquid_m3'][0])+Fraction(first['suspended_solid_m3'][0]), 1)
        expected = first['liquid_m3'], first['suspended_solid_m3']
        for _ in range(10):
            w, s = json.loads(json.dumps(expected))
            again = route(bed, w, s, outlets=[1])
            self.assertEqual((again['liquid_m3'], again['suspended_solid_m3']), expected)
            self.assertEqual(again['exported_liquid_m3'], 0.)
            self.assertEqual(again['exported_suspended_solid_m3'], 0.)

    def test_retained_time_point_three_output_defect_and_canonical_replay(self):
        # Captured at t=.30000000000000004 by disabling only the new output
        # correction in the retained 16-cell driver. This is an output-contract
        # regression, not a Diadem input or a modified terrain scenario.
        bed = [21.320748700872553,20.23852350361715,20.23869485406048,21.321018073156736,
               21.96569550734938,19.354046940921585,19.354018357014628,21.966201477364407,
               21.845695508795014,19.23404229268219,19.23404229561821,21.846201481377953,
               20.96118961446474,19.878805032036933,19.878805032036947,20.96118961772098]
        w = [0.,0.,0.,0.,0.,52.45607281848941,52.45893013413667,0.,0.,64.45202423530932,64.45202394181781,0.,0.,0.,0.,0.]
        s = [0.,0.,0.,0.,0.,.019736293045437663,.01973736809387167,0.,0.,.02424970016496074,.024249700054536256,0.,0.,0.,0.,0.]
        area, outlets = [100.] * 16, [12,13,14,15]
        capacity = sum(((Fraction(bed[13])-Fraction(bed[i]))*100 for i in (5,6,9,10)), Fraction())
        self.assertGreater(sum((Fraction(a)+Fraction(b) for a,b in zip(w,s)), Fraction()), capacity)
        first = route(bed, w, s, area=area, shape=[4,4], outlets=outlets, connectivity=8)
        self.assertEqual(sum((Fraction(a)+Fraction(b) for a,b in zip(first['liquid_m3'],first['suspended_solid_m3'])), Fraction()), capacity)
        expected = first['liquid_m3'], first['suspended_solid_m3']
        for _ in range(10):
            copy_w, copy_s = json.loads(json.dumps(expected))
            again = route(bed, copy_w, copy_s, area=area, shape=[4,4], outlets=outlets, connectivity=8)
            self.assertEqual((again['liquid_m3'], again['suspended_solid_m3']), expected)
            self.assertEqual(again['exported_liquid_m3'], 0.)
            self.assertEqual(again['exported_suspended_solid_m3'], 0.)

    def test_arbitrary_rounded_near_sill_input_is_never_promoted_to_capacity(self):
        w, s = [.7, 0.], [.3, 0.]
        exact = Fraction(w[0])+Fraction(s[0])
        self.assertEqual(Fraction(1)-exact, Fraction(1,2**54))
        r = route([0., 1.], w, s, outlets=[1])
        self.assertEqual(r['liquid_m3'], w)
        self.assertEqual(r['suspended_solid_m3'], s)
        self.assertIsNone(r['active_pools'][0]['full_sill_representation'])
        self.assertEqual(r['active_pools'][0]['stage_m'], 1.)
        self.assertEqual(r['exported_liquid_m3'], 0.)

    def test_balanced_phases_cannot_exactly_represent_finer_sill_capacity(self):
        # C=1+2^-55 is finer than the ULP of either retained ~0.5 phase.
        # No tiny head, field precision change or below-capacity clamp is used.
        w, s = [1., 0.], [1., 0.]
        with self.assertRaisesRegex(p.UnsupportedPhaseRouting, 'no bounded exact binary64 representation'):
            route([-2.**-55, 1.], w, s, outlets=[1])
        self.assertEqual(w, [1., 0.])
        self.assertEqual(s, [1., 0.])

    def test_correction_budget_is_not_fitted_to_observed_residual(self):
        w, s = [.75], [.25]
        with self.assertRaisesRegex(ValueError, 'arithmetic ULP certificate'):
            p._exact_capacity_allocation(w, s, [1.], Fraction(1)+Fraction(1,2**55), Fraction(), .75)
        self.assertEqual(w, [.75])
        self.assertEqual(s, [.25])

    def test_split_roundoff_certificate_bounds_exact_independent_errors(self):
        rng = random.Random(9081)
        for _ in range(60):
            pair = (rng.random()*30+.1, rng.random()*2+.01)
            total = Fraction(pair[0])+Fraction(pair[1])
            retained = total*Fraction(rng.randrange(1,999),1000)
            keep, leave = p._split(pair, retained, total)
            ke, le = p._split_bounds(pair, retained, total, keep, leave, Fraction())
            self.assertLessEqual(abs(sum(map(Fraction,keep),Fraction())-retained),ke)
            self.assertLessEqual(abs(sum(map(Fraction,leave),Fraction())-(total-retained)),le)

    def test_pool_report_uses_actual_corrected_phase_concentration(self):
        r = route([0.,1.], [.8324199885056033,0.], [.16758001149439675,0.], outlets=[1])
        pool = r['active_pools'][0]
        self.assertEqual(pool['liquid_m3'], math.fsum(r['liquid_m3']))
        self.assertEqual(pool['suspended_solid_m3'], math.fsum(r['suspended_solid_m3']))
        self.assertEqual(pool['solid_volume_fraction'], pool['suspended_solid_m3']/(pool['liquid_m3']+pool['suspended_solid_m3']))

    def test_equal_sill_fractional_areas_roundoff_has_explicit_geometry_residual(self):
        bed = [2., 0., 2., 0., 2., 0., 2.]
        area = [61.60283281598898, 32.14384608849953, 40.94379757496146,
                43.446177094934434, 89.30011189209158, 50.30023602935599, 35.7351305748853]
        capacity = math.fsum(2 * area[i] for i in (1, 3, 5))
        for supplied in (math.nextafter(capacity, 0.), capacity, math.nextafter(capacity, math.inf)):
            w, s = [0., supplied, 0., 0., 0., 0., 0.], [0.] * 7
            exact = sum((Fraction(2) * Fraction(area[i]) for i in (1, 3, 5)), Fraction())
            if Fraction(supplied) > exact:
                with self.assertRaises(p.UnsupportedPhaseRouting) as rejected:
                    route(bed, w, s, area=area)
                self.assert_compound_zero_head(rejected.exception, bed, [1, 7], 4)
            else:
                r = route(bed, w, s, area=area)
                self.assertEqual(r["exported_liquid_m3"], 0.)
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
        accepted = rejected = 0
        for connectivity in (4, 8):
            for _ in range(12):
                bed = [float(rng.randrange(10)) for _ in range(20)]
                area = [float(rng.randrange(1, 4)) for _ in bed]
                w, s = [10000.] * 20, [rng.random() * 100 for _ in bed]
                try:
                    r = route(bed, w, s, shape=[4, 5], area=area, outlets=[0, 19], connectivity=connectivity)
                except p.UnsupportedPhaseRouting as error:
                    self.assert_compound_zero_head(error, bed, [4, 5], connectivity)
                    rejected += 1
                    continue
                accepted += 1
                levels = brute_escape_levels(bed, [4, 5], [0, 19], connectivity)
                self.assertEqual(r["mixture_depth_m"], [level - z for level, z in zip(levels, bed)])
                self.conserved(r, w, s)
        self.assertGreater(accepted, 0)
        self.assertGreater(rejected, 0)

    def test_random_partial_unequal_concentration_conservation_and_cell_geometry(self):
        rng = random.Random(711)
        accepted = rejected = 0
        for _ in range(32):
            bed = [float(rng.randrange(12)) for _ in range(25)]
            area = [.5 + rng.random() * 4 for _ in bed]
            w, s = [rng.random() * 8 for _ in bed], [rng.random() for _ in bed]
            try:
                r = route(bed, w, s, shape=[5, 5], area=area, outlets=[0, 24])
            except p.UnsupportedPhaseRouting as error:
                self.assert_compound_zero_head(error, bed, [5, 5], 4)
                rejected += 1
                continue
            accepted += 1
            self.conserved(r, w, s)
            for wi, si, a, d in zip(r["liquid_m3"], r["suspended_solid_m3"], area, r["mixture_depth_m"]):
                self.near(wi + si, a * d)
        self.assertGreater(accepted, 0)
        self.assertGreater(rejected, 0)

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


class SourceCacheTests(unittest.TestCase):
    def setUp(self):
        p.configure_source_cache(enabled=True, reset=True)

    def tearDown(self):
        p.configure_source_cache(enabled=True, reset=True)

    def simple_route(self):
        return route([2., 0., 2.], [0., 3., 0.], [0., 1., 0.])

    def test_default_cache_hit_miss_reset_and_no_scientific_stats(self):
        self.assertEqual(p.source_cache_info(), {"enabled": True, "hits": 0, "misses": 0, "entries": 0})
        first = self.simple_route()
        second = self.simple_route()
        self.assertEqual(p.source_cache_info(), {"enabled": True, "hits": 1, "misses": 1, "entries": 1})
        self.assertEqual(first, second)
        self.assertNotIn("cache", json.dumps(first, sort_keys=True))
        p.configure_source_cache(reset=True)
        self.assertEqual(p.source_cache_info(), {"enabled": True, "hits": 0, "misses": 0, "entries": 0})

    def test_disabled_compiles_each_call_and_results_are_exact(self):
        cached = json.dumps(self.simple_route(), sort_keys=True, allow_nan=False)
        p.configure_source_cache(enabled=False, reset=True)
        for _ in range(3):
            self.assertEqual(json.dumps(self.simple_route(), sort_keys=True, allow_nan=False), cached)
        self.assertEqual(p.source_cache_info(), {"enabled": False, "hits": 0, "misses": 3, "entries": 0})

    def test_all_five_source_files_read_before_and_after_each_hit(self):
        original = Path.read_bytes
        paths = []
        def counted(path):
            paths.append(str(path))
            return original(path)
        with patch.object(Path, "read_bytes", counted):
            first = self.simple_route()
            self.simple_route()
        expected = [row["path"] for row in first["source_binding"].values()]
        self.assertEqual(len(expected), 5)
        self.assertEqual(len(paths), 20)
        self.assertEqual({name: paths.count(name) for name in expected}, {name: 4 for name in expected})

    def test_warm_cache_still_rejects_changed_source_and_expected_pin(self):
        self.simple_route()
        original = Path.read_bytes
        def changed(path):
            return original(path) + (b"\n# simulated source drift" if path.name == "water.py" else b"")
        with patch.object(Path, "read_bytes", changed), self.assertRaisesRegex(ValueError, "identity mismatch"):
            self.simple_route()
        with patch.dict(p.SOURCE_PINS, {"water.py": "0" * 64}), self.assertRaisesRegex(ValueError, "identity mismatch"):
            self.simple_route()
        self.assertEqual(p.source_cache_info()["hits"], 0)

    def test_warm_cache_still_rejects_post_execution_source_change(self):
        self.simple_route()
        original = Path.read_bytes
        reads = 0
        def changed(path):
            nonlocal reads
            data = original(path)
            if path.name == "water.py":
                reads += 1
                if reads == 2:
                    return data + b"\n# simulated post-execution source drift"
            return data
        with patch.object(Path, "read_bytes", changed), self.assertRaisesRegex(ValueError, "changed during"):
            self.simple_route()

    def test_threaded_calls_share_one_compilation_not_scientific_state(self):
        with ThreadPoolExecutor(max_workers=4) as executor:
            results = list(executor.map(lambda _: self.simple_route(), range(16)))
        self.assertTrue(all(value == results[0] for value in results))
        self.assertEqual(p.source_cache_info(), {"enabled": True, "hits": 15, "misses": 1, "entries": 1})
        results[0]["liquid_m3"][1] = 99.
        self.assertEqual(results[1]["liquid_m3"][1], 1.5)

    def test_returned_module_and_receipt_mappings_are_not_shared(self):
        modules, binding = p._bound_sources()
        modules.clear()
        binding["water.py"]["sha256"] = "bad"
        again, receipt = p._bound_sources()
        self.assertEqual(set(again), set(p.SOURCE_PINS))
        self.assertEqual(receipt["water.py"]["sha256"], p.SOURCE_PINS["water.py"])

    def test_cached_constant_and_function_default_mutation_fail_closed(self):
        modules, _ = p._bound_sources()
        modules["water.py"].MAX_CELLS = 1
        with self.assertRaisesRegex(ValueError, "cached private source globals changed"):
            self.simple_route()
        p.configure_source_cache(reset=True)
        modules, _ = p._bound_sources()
        modules["water.py"]._num.__kwdefaults__["positive"] = True
        with self.assertRaisesRegex(ValueError, "cached private source globals changed"):
            self.simple_route()

    def test_cached_private_mutation_during_call_fails_postcheck(self):
        modules, _ = p._bound_sources()
        original = p._exact_stage
        def mutate(*args, **kwargs):
            result = original(*args, **kwargs)
            modules["water.py"].MAX_CELLS = 1
            return result
        with patch.object(p, "_exact_stage", mutate), self.assertRaisesRegex(ValueError, "cached private source globals changed"):
            route([0.], [1.], [0.], outlets=[])

    def test_cache_configuration_is_strict_and_disabled_drops_entry(self):
        self.simple_route()
        for bad in (0, 1, None, "true", []):
            with self.assertRaisesRegex(ValueError, "Boolean"):
                p.configure_source_cache(enabled=bad)
            with self.assertRaisesRegex(ValueError, "Boolean"):
                p.configure_source_cache(reset=bad)
        p.configure_source_cache(enabled=False)
        self.assertEqual(p.source_cache_info()["entries"], 0)
        self.assertEqual(p.source_cache_info()["misses"], 1)


if __name__ == "__main__":
    unittest.main()
