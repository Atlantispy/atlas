"""Independent closed-pool numerical tests; no terrain or output writes."""
from decimal import Decimal, localcontext
import math
import unittest
from unittest.mock import patch

import settling
from settling import settle_pool, SettlingError


def decimal_rk4(water, suspension, rate_area, elapsed, steps):
    """Independent high-precision time ODE, not the production integral/root."""
    with localcontext() as context:
        context.prec = 60
        w, s, k, time = map(lambda x: Decimal(str(x)), (water, suspension, rate_area, elapsed))
        h = time / steps
        def rate(value):
            return -k * value / (w + value)
        for _ in range(steps):
            a = rate(s)
            b = rate(s + h * a / 2)
            c = rate(s + h * b / 2)
            d = rate(s + h * c)
            s += h * (a + 2 * b + 2 * c + d) / 6
        return s


class SettlingTests(unittest.TestCase):
    def assert_budget(self, result, bed, area, water, suspended):
        deposits = result["deposited_solid_m3"]
        self.assertEqual(result["liquid_m3"], water)
        self.assertAlmostEqual(math.fsum(deposits) + result["suspended_solid_m3"], suspended, places=11)
        self.assertAlmostEqual(math.fsum(result["liquid_by_cell_m3"]), water, places=11)
        self.assertAlmostEqual(math.fsum(result["suspended_by_cell_m3"]), result["suspended_solid_m3"], places=11)
        represented = math.fsum(a * (new - old) for a, new, old in zip(area, result["bed_m"], bed))
        self.assertAlmostEqual(represented, math.fsum(deposits), places=11)
        geometric = math.fsum(a * h for a, h in zip(area, result["depth_m"]))
        self.assertAlmostEqual(geometric, water + result["suspended_solid_m3"], places=11)
        self.assertEqual(result["external_liquid_export_m3"], 0.)
        self.assertEqual(result["external_solid_export_m3"], 0.)
        self.assertFalse(result["physical_validation_passed"])
        self.assertFalse(result["shoreline_transition_implemented"])
        self.assertFalse(result["production_authorised"])

    def test_design_closed_column_half_life(self):
        elapsed = (100 * math.log(2) + .05) / 10
        result = settle_pool([0.], [10.], 100., .1, 1., elapsed)
        self.assertEqual(result["stage_m"], 10.01)
        self.assertAlmostEqual(result["suspended_solid_m3"], .05, places=14)
        self.assertAlmostEqual(result["deposited_solid_m3"][0], .05, places=14)
        self.assertAlmostEqual(result["bed_m"][0], .005, places=14)
        self.assertAlmostEqual(result["depth_m"][0], 10.005, places=13)
        self.assertEqual(result["events"], 0)
        self.assert_budget(result, [0.], [10.], 100., .1)

    def test_heterogeneous_event_has_independent_piecewise_oracle(self):
        first = (2 * math.log(3) + 4) / 4
        after = (2 * math.log(2) + 1) / 3
        result = settle_pool([0., 1., 2.], [1., 2., 1.], 2., 6., 1., first + after)
        self.assertEqual(result["stage_m"], 3.)
        self.assertEqual(result["events"], 1)
        self.assertEqual(result["event_records"][0]["dried_cells"], [2])
        self.assertAlmostEqual(result["event_records"][0]["time_years"], first, places=14)
        for got, expected in zip(result["deposited_solid_m3"], (4 / 3, 8 / 3, 1.)):
            self.assertAlmostEqual(got, expected, places=13)
        self.assertAlmostEqual(result["suspended_solid_m3"], 1., places=13)
        self.assertEqual(result["final_wet_cells"], [0, 1])
        self.assertEqual(result["liquid_by_cell_m3"][2], 0.)
        self.assertEqual(result["suspended_by_cell_m3"][2], 0.)
        self.assert_budget(result, [0., 1., 2.], [1., 2., 1.], 2., 6.)

    def test_exact_event_and_equal_depths_are_atomic(self):
        event = (math.log(5) + 4) / 4
        result = settle_pool([0., 2., 2.], [1., 1., 2.], 1., 5., 1., event)
        self.assertEqual(result["events"], 1)
        self.assertEqual(result["event_records"][0]["dried_cells"], [1, 2])
        self.assertEqual(result["bed_m"], [1., 3., 3.])
        self.assertEqual(result["deposited_solid_m3"], [1., 1., 2.])
        self.assertEqual(result["suspended_solid_m3"], 1.)
        self.assert_budget(result, [0., 2., 2.], [1., 1., 2.], 1., 5.)

    def test_after_tied_event_retains_positive_water_in_remaining_cell(self):
        elapsed = (math.log(5) + 4) / 4 + math.log(2) + .5
        result = settle_pool([0., 2., 2.], [1., 1., 2.], 1., 5., 1., elapsed)
        self.assertEqual(result["events"], 1)
        self.assertEqual(result["final_wet_cells"], [0])
        self.assertAlmostEqual(result["bed_m"][0], 1.5, places=13)
        self.assertAlmostEqual(result["suspended_solid_m3"], .5, places=13)
        self.assertEqual(result["liquid_by_cell_m3"], [1., 0., 0.])

    def test_first_event_return_contains_no_later_settling(self):
        event = (math.log(5) + 4) / 4
        result = settle_pool([0., 2., 2.], [1., 1., 2.], 1., 5., 1., event + 1.,
                             stop_at_first_drying_event=True)
        self.assertEqual(result["bed_m"], [1., 3., 3.])
        self.assertEqual(result["deposited_solid_m3"], [1., 1., 2.])
        self.assertEqual(result["suspended_solid_m3"], 1.)
        self.assertEqual(result["events"], 1)
        self.assertTrue(result["stopped_at_drying_event"])
        self.assertFalse(result["completed_requested_interval"])
        self.assertEqual(result["elapsed_years"], event)
        self.assertAlmostEqual(result["remaining_years"], 1., places=14)
        self.assertEqual(result["solver_iterations"], 0)
        self.assert_budget(result, [0., 2., 2.], [1., 1., 2.], 1., 5.)

    def test_dilute_drying_saddle_returns_state_for_external_connectivity_check(self):
        bed, area = [0., 1.9999, 1.], [1., 1., 1.]
        event = settle_pool(bed, area, 2.9991, .001, 1., 1.,
                            stop_at_first_drying_event=True)
        self.assertTrue(event["stopped_at_drying_event"])
        self.assertEqual(event["event_records"][0]["dried_cells"], [1])
        self.assertEqual(event["final_wet_cells"], [0, 2])
        self.assertEqual(event["bed_m"][1], event["stage_m"])
        self.assertEqual(event["depth_m"][1], 0.)
        self.assertGreater(event["elapsed_years"], 0.)
        self.assertGreater(event["remaining_years"], 0.)
        self.assertEqual(event["solver_iterations"], 0)
        self.assertAlmostEqual(event["total_deposited_solid_m3"], .0003, places=14)
        self.assertTrue(event["connected_pool_assumed"])
        self.assertFalse(event["wet_connectivity_checked"])
        # Native 1-D adjacency, independently: positive-depth cells 0 and 2
        # are now disconnected. The list-only kernel must not claim to know it.
        self.assertNotIn(1, event["final_wet_cells"])
        self.assert_budget(event, bed, area, 2.9991, .001)

    def test_event_stop_option_exact_endpoint_no_event_and_zero_limits(self):
        event = (math.log(5) + 4) / 4
        endpoint = settle_pool([0., 2., 2.], [1., 1., 2.], 1., 5., 1., event,
                               stop_at_first_drying_event=True)
        self.assertTrue(endpoint["stopped_at_drying_event"])
        self.assertTrue(endpoint["completed_requested_interval"])
        self.assertEqual(endpoint["remaining_years"], 0.)
        for suspended, velocity, elapsed in ((.1, 1., .1), (0., 1., 1.), (.1, 0., 1.), (.1, 1., 0.)):
            result = settle_pool([0.], [1.], 1., suspended, velocity, elapsed,
                                 stop_at_first_drying_event=True)
            self.assertFalse(result["stopped_at_drying_event"])
            self.assertTrue(result["completed_requested_interval"])
            self.assertEqual(result["elapsed_years"], elapsed)
            self.assertEqual(result["remaining_years"], 0.)
        with self.assertRaisesRegex(SettlingError, "boolean"):
            settle_pool([0.], [1.], 1., .1, 1., 1., stop_at_first_drying_event=1)

    def test_high_precision_ode_and_fourth_order_refinement(self):
        result = settle_pool([0.], [2.], 3., 1., 1., 1.)
        reference = decimal_rk4(3, 1, 2, 1, 1024)
        self.assertLess(abs(Decimal.from_float(result["suspended_solid_m3"]) - reference), Decimal("1e-13"))
        errors = [abs(decimal_rk4(3, 1, 2, 1, steps) - reference) for steps in (4, 8, 16, 32, 64)]
        for a, b in zip(errors, errors[1:]):
            self.assertGreater(a / b, Decimal(12))
        self.assertLess(errors[-1], Decimal("1e-10"))

    def test_high_precision_ode_other_concentration_and_velocity(self):
        for water, suspended, velocity, elapsed in ((100., .1, 5., 1.), (1., 3., .2, 2.), (.1, .5, .3, .1)):
            with self.subTest(water=water, suspended=suspended):
                result = settle_pool([0.], [1.], water, suspended, velocity, elapsed)
                expected = decimal_rk4(water, suspended, velocity, elapsed, 2048)
                self.assertLess(abs(Decimal.from_float(result["suspended_solid_m3"]) - expected), Decimal("1e-12"))

    def test_empty_and_zero_forcing_limits_preserve_exact_bed(self):
        bed = [-0., 1., 3.]
        area = [1., 2., 1.]
        empty = settle_pool(bed, area, 0., 0., 10., 10.)
        self.assertIsNone(empty["stage_m"])
        self.assertEqual(empty["depth_m"], [0.] * 3)
        self.assertEqual(math.copysign(1., empty["bed_m"][0]), -1.)
        for water, suspended, velocity, elapsed in ((10., 0., 10., 10.), (10., 1., 0., 10.), (10., 1., 10., 0.)):
            result = settle_pool(bed, area, water, suspended, velocity, elapsed)
            self.assertEqual(result["bed_m"], bed)
            self.assertEqual(result["suspended_solid_m3"], suspended)
            self.assertEqual(result["deposited_solid_m3"], [0.] * 3)
            self.assertEqual(result["solver_iterations"], 0)
            self.assertEqual(result["events"], 0)

    def test_initial_dry_cells_never_receive_closed_settling(self):
        result = settle_pool([0., 100.], [1., 1.], 1., .1, 1., .2)
        self.assertEqual(result["initial_wet_cells"], [0])
        self.assertEqual(result["bed_m"][1], 100.)
        self.assertEqual(result["deposited_solid_m3"][1], 0.)

    def test_restart_matches_whole_interval_including_event(self):
        bed, area = [0., 1., 2.], [1., 2., 1.]
        whole = settle_pool(bed, area, 2., 6., 1., 2.4)
        first = settle_pool(bed, area, 2., 6., 1., 1.)
        second = settle_pool(first["bed_m"], area, first["liquid_m3"], first["suspended_solid_m3"], 1., 1.4)
        for a, b in zip(whole["bed_m"], second["bed_m"]):
            self.assertAlmostEqual(a, b, places=12)
        self.assertAlmostEqual(whole["suspended_solid_m3"], second["suspended_solid_m3"], places=12)
        self.assertEqual(whole["final_wet_cells"], second["final_wet_cells"])
        self.assertEqual(whole["events"], first["events"] + second["events"])

    def test_permutation_and_input_ownership(self):
        bed, area = [0., 1., 2.], [1., 2., 1.]
        original = (bed.copy(), area.copy())
        a = settle_pool(bed, area, 2., 6., 1., 2.4)
        order = [2, 0, 1]
        b = settle_pool([bed[i] for i in order], [area[i] for i in order], 2., 6., 1., 2.4)
        for key in ("bed_m", "depth_m", "deposited_solid_m3", "liquid_by_cell_m3", "suspended_by_cell_m3"):
            for index, old in enumerate(order):
                self.assertAlmostEqual(a[key][old], b[key][index], places=13)
        self.assertEqual(b["event_records"][0]["dried_cells"], [0])
        self.assertEqual((bed, area), original)

    def test_common_volume_area_scaling_and_velocity_time_units(self):
        a = settle_pool([0., 1., 2.], [1., 2., 1.], 2., 6., 1., 2.4)
        b = settle_pool([0., 1., 2.], [7., 14., 7.], 14., 42., 1., 2.4)
        c = settle_pool([0., 1., 2.], [1., 2., 1.], 2., 6., 10., .24)
        for x, y, z in zip(a["bed_m"], b["bed_m"], c["bed_m"]):
            self.assertAlmostEqual(x, y, places=12)
            self.assertAlmostEqual(x, z, places=12)
        self.assertAlmostEqual(a["suspended_solid_m3"] * 7, b["suspended_solid_m3"], places=12)

    def test_asymptotic_drying_is_not_a_finite_event(self):
        result = settle_pool([0., 1.], [1., 1.], 1., 2., 1., 2.)
        self.assertEqual(result["events"], 0)
        self.assertEqual(result["final_wet_cells"], [0, 1])
        self.assertGreater(result["suspended_solid_m3"], 0.)
        with self.assertRaises(SettlingError):
            settle_pool([0., 1.], [1., 1.], 1., 2., 1., 1000.)

    def test_exact_repeated_call(self):
        args = ([0., 1., 2.], [1., 2., 1.], 2., 6., 1., 2.4)
        self.assertEqual(settle_pool(*args), settle_pool(*args))

    def test_dry_suspension_rejects_even_if_no_settling_requested(self):
        for velocity, elapsed in ((0., 1.), (1., 0.), (1., 1.)):
            with self.assertRaisesRegex(SettlingError, "dry suspension"):
                settle_pool([0.], [1.], 0., 1., velocity, elapsed)

    def test_invalid_fields_shapes_and_numbers(self):
        for bed, area in (([], []), ([0.], []), ([0.], [0.]), ([0.], [-1.]), ([math.nan], [1.]), ([0.], [math.inf]), ([True], [1.])):
            with self.subTest(bed=bed, area=area), self.assertRaises(SettlingError):
                settle_pool(bed, area, 1., .1, 1., 1.)
        for value in (-1., math.nan, math.inf, True, 10 ** 1000, "1"):
            for slot in range(2, 6):
                args = [[0.], [1.], 1., .1, 1., 1.]
                args[slot] = value
                with self.subTest(slot=slot, value=str(value)[:12]), self.assertRaises(SettlingError):
                    settle_pool(*args)

    def test_positive_unrepresentable_geometry_and_deposition_reject(self):
        with self.assertRaisesRegex(SettlingError, "representable wet"):
            settle_pool([1e20], [1.], 1., 0., 0., 0.)
        with self.assertRaisesRegex(SettlingError, "vertical datum"):
            settle_pool([20.], [100.], 100., .1, 1e-18, 1.)
        with self.assertRaises(SettlingError):
            settle_pool([0.], [1e-300], 1e300, 1., 1., 1.)
        with self.assertRaises(SettlingError):
            settle_pool([0.], [1.], 1., .1, 1e-300, 1e-300)

    def test_solver_resource_caps_fail_closed(self):
        with patch.object(settling, "MAX_BISECTIONS", 1), self.assertRaisesRegex(SettlingError, "budget"):
            settle_pool([0.], [1.], 1., 1., 1., .1)
        with patch.object(settling, "MAX_BRACKET_STEPS", 0), self.assertRaisesRegex(SettlingError, "budget"):
            settle_pool([0.], [1.], 1., 100., 1., 100.)
        with self.assertRaises(SettlingError):
            settle_pool([0.] * 4097, [1.] * 4097, 1., 0., 0., 0.)

    def test_unrepresentable_event_fraction_is_not_treated_as_zero_log(self):
        with self.assertRaisesRegex(SettlingError, "event depleted fraction"):
            settling._event_time(1e308, 1e308, math.ulp(0.), 1.)

    def test_maximum_supported_cells_zero_limit(self):
        n = 4096
        result = settle_pool([0.] * n, [1.] * n, float(n), 0., 1., 1.)
        self.assertEqual(result["bed_m"], [0.] * n)
        self.assertEqual(result["depth_m"], [1.] * n)
        self.assertEqual(result["liquid_by_cell_m3"], [1.] * n)
        self.assertEqual(result["stage_m"], 1.)


if __name__ == "__main__":
    unittest.main()
