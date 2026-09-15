"""Independent wet-connectivity regressions for the R3 coupled step.

Synthetic dilute suspension only. No terrain or file writes. These distinguish
positive-depth hydraulic components from full-child geometric FSM promotion.
"""
import copy
import math
import unittest
from unittest.mock import patch

import capture as c


def components(wet, shape, connectivity):
    """Independent exhaustive adjacency, not the producer's topology helper."""
    rows, cols = shape
    remaining = set(wet)
    answer = []
    while remaining:
        connected = {min(remaining)}
        queue = list(connected)
        remaining -= connected
        while queue:
            i = queue.pop()
            yi, xi = divmod(i, cols)
            for j in sorted(remaining):
                yj, xj = divmod(j, cols)
                dy, dx = abs(yi - yj), abs(xi - xj)
                if max(dy, dx) == 1 and (connectivity == 8 or dy + dx == 1):
                    remaining.remove(j)
                    connected.add(j)
                    queue.append(j)
        answer.append(sorted(connected))
    return answer


def state_for(bed, *, shape=None):
    n = len(bed)
    # Concentration is about 0.000333; the positive-depth saddle is shallow,
    # rather than requiring an unrealistically concentrated solid slurry.
    return c.CaptureState(shape or [1, n], [1.] * n, bed, [0.] * n,
                          [2.9991] + [0.] * (n - 1), [.001] + [0.] * (n - 1))


def one_step(state, *, elapsed=.8, connectivity=4):
    return c.step(state, outlets=[], connectivity=connectivity,
                  liquid_input_m3=[0.] * state.size,
                  suspended_input_m3=[0.] * state.size,
                  bed_input_solid_m3=[0.] * state.size,
                  settling_m_year=1., elapsed_years=elapsed,
                  source_label="SYNTHETIC dilute drying topology regression")


class CaptureTopologyTests(unittest.TestCase):
    def assert_conserved(self, initial, result, report):
        self.assertAlmostEqual(math.fsum(result.liquid_m3), math.fsum(initial.liquid_m3), places=11)
        self.assertAlmostEqual(math.fsum(result.bed_solid_m3) + math.fsum(result.suspended_solid_m3),
                               math.fsum(initial.bed_solid_m3) + math.fsum(initial.suspended_solid_m3), places=11)
        self.assertEqual(report["exported_liquid_m3"], 0.)
        self.assertEqual(report["exported_suspended_solid_m3"], 0.)
        self.assertFalse(report["production_authorised"])

    def test_independent_geometry_oracle_distinguishes_saddle_and_margin(self):
        self.assertEqual(components([0, 1, 2], [1, 3], 4), [[0, 1, 2]])
        self.assertEqual(components([0, 2], [1, 3], 4), [[0], [2]])
        self.assertEqual(components([0, 1], [1, 3], 4), [[0, 1]])
        self.assertEqual(components([0, 3], [2, 2], 4), [[0], [3]])
        self.assertEqual(components([0, 3], [2, 2], 8), [[0, 3]])

    def test_actual_drying_saddle_rejects_without_mutating_initial_state(self):
        state = state_for([0., 1.9999, 1.])
        before = copy.deepcopy(state.as_dict())
        with self.assertRaisesRegex(ValueError, "(?i)split|disconnect|connectivity"):
            one_step(state)
        self.assertEqual(state.as_dict(), before)

    def test_rejected_saddle_stops_before_any_post_split_settling(self):
        calls = []
        original = c.settling.settle_pool
        def observed(*args, **kwargs):
            result = original(*args, **kwargs)
            calls.append((kwargs.copy(), result))
            return result
        with patch.object(c.settling, "settle_pool", observed):
            with self.assertRaisesRegex(ValueError, "(?i)split|disconnect|connectivity"):
                one_step(state_for([0., 1.9999, 1.]))
        self.assertEqual(len(calls), 1, "a rejected split must not advance another mixed substep")
        controls, event = calls[0]
        self.assertIs(controls.get("stop_at_first_drying_event"), True)
        self.assertTrue(event["stopped_at_drying_event"])
        self.assertGreater(event["remaining_years"], 0.)
        self.assertEqual(event["final_wet_cells"], [0, 2])
        expected_time = (2.9991 * math.log(10 / 7) + .0003) / 3
        self.assertAlmostEqual(event["elapsed_years"], expected_time, places=11)
        self.assertAlmostEqual(event["total_deposited_solid_m3"], .0003, places=13)

    def test_before_saddle_event_remains_valid_connected_state(self):
        state = state_for([0., 1.9999, 1.])
        result, report = one_step(state, elapsed=.1)
        routing = report["routing_after_settling"]
        wet = [i for i, depth in enumerate(routing["mixture_depth_m"]) if depth > 0]
        self.assertEqual(components(wet, result.shape, 4), [[0, 1, 2]])
        self.assertGreater(routing["mixture_depth_m"][1], 0.)
        self.assert_conserved(state, result, report)

    def test_marginal_drying_without_disconnection_is_allowed(self):
        state = state_for([0., 1., 1.9999])
        result, report = one_step(state)
        routing = report["routing_after_settling"]
        wet = [i for i, depth in enumerate(routing["mixture_depth_m"]) if depth > 0]
        self.assertEqual(components(wet, result.shape, 4), [[0, 1]])
        self.assertEqual(result.liquid_m3[2], 0.)
        self.assertEqual(result.suspended_solid_m3[2], 0.)
        self.assertGreater(result.bed_solid_m3[2], 0.)
        self.assertAlmostEqual(result.time_years, .8)
        self.assert_conserved(state, result, report)

    def test_diagonal_connection_is_not_allowed_in_four_neighbour_grid(self):
        with self.assertRaisesRegex(ValueError, "(?i)split|disconnect|connectivity"):
            one_step(state_for([0., 1.9999, 3., 1.], shape=[2, 2]), connectivity=4)

    def test_explicit_eight_neighbour_diagonal_connection_remains_valid(self):
        state = state_for([0., 1.9999, 3., 1.], shape=[2, 2])
        result, report = one_step(state, connectivity=8)
        wet = [i for i, d in enumerate(report["routing_after_settling"]["mixture_depth_m"]) if d > 0]
        self.assertEqual(wet, [0, 3])
        self.assertEqual(components(wet, result.shape, 8), [[0, 3]])
        self.assert_conserved(state, result, report)

    def test_advance_cannot_emit_success_for_drying_split(self):
        state = state_for([0., 1.9999, 1.])
        with self.assertRaisesRegex(ValueError, "(?i)split|disconnect|connectivity"):
            c.advance(state, steps=2, dt_years=.4, outlets=[], connectivity=4,
                      liquid_input_m3_year=[0.] * 3, suspended_input_m3_year=[0.] * 3,
                      bed_input_solid_m3_year=[0.] * 3, settling_m_year=1.,
                      source_label="SYNTHETIC split must remain incomplete")


if __name__ == "__main__":
    unittest.main()
