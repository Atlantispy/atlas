"""Focused I01 D6 transition-control guards; no world generation or native import.
SPDX-License-Identifier: AGPL-3.0-only
"""
import itertools
import math
from pathlib import Path
import sys
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"tools"))
import check_i01_transitions as c

TOL = dict(lipschitz=1.0, tolerance=1e-10, resolution=1e-8, budget=100000)


class BracketingTests(unittest.TestCase):
    def test_first_of_two_crossings_in_one_step(self):
        g = lambda t: (t-0.3)*(t-0.7)
        self.assertGreater(g(0.0)*g(1.0), 0)          # a one-step sign test sees nothing
        out = c.first_crossing(g, 0.0, 1.0, **TOL)
        self.assertEqual(out["status"], "EVENT")
        self.assertAlmostEqual(out["time"], 0.3, delta=2e-10)

    def test_tangency_is_refused_not_ignored(self):
        out = c.first_crossing(lambda t: (t-0.5)**2, 0.0, 1.0, **TOL)
        self.assertTrue(out["status"].startswith("UNRESOLVED"))

    def test_zero_at_start_and_no_event(self):
        self.assertEqual(c.first_crossing(lambda t: t-1.0, 1.0, 2.0, **TOL)["status"], "DUE_AT_START")
        self.assertEqual(c.first_crossing(lambda t: 2.0+t, 0.0, 1.0, **TOL)["status"], "NO_EVENT")

    def test_invalid_certificate_or_trigger(self):
        bad = (dict(TOL, lipschitz=0.0), dict(TOL, tolerance=-1.0), dict(TOL, budget=1.5))
        for kwargs in bad:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                c.first_crossing(lambda t: t-0.5, 0.0, 1.0, **kwargs)
        with self.assertRaises(ValueError):
            c.first_crossing(lambda t: t-0.5, 1.0, 0.0, **TOL)
        with self.assertRaises(ValueError):
            c.first_crossing(lambda t: float("nan"), 0.0, 1.0, **TOL)

    def test_sub_tolerance_double_crossing_is_not_no_event(self):
        h = 2.0**-30
        g = lambda t: (t-h/4)*(t-3*h/4)/h  # |g'| <= 1, equal positive endpoints
        out = c.first_crossing(g, 0., h, **dict(TOL, tolerance=h))
        self.assertEqual(out["status"], "UNRESOLVED_CROSSINGS")

    def test_sampled_touch_and_endpoint_zero_are_not_crossings(self):
        touch = c.first_crossing(lambda t: abs(t-.5), 0., 1., **TOL)
        self.assertEqual(touch["status"], "UNRESOLVED_TANGENCY")
        crossing = c.first_crossing(lambda t: t-.5, 0., 1., **TOL)
        self.assertEqual((crossing["status"], crossing["time"]), ("EVENT", .5))
        endpoint = c.first_crossing(lambda t: t-1., 0., 1., **TOL)
        self.assertEqual(endpoint["status"], "UNRESOLVED_ENDPOINT_ZERO")

    def test_finite_times_progress_and_total_evaluation_budget(self):
        for t0, t1 in ((0., math.inf), (-math.inf, 1.)):
            with self.assertRaises(ValueError):
                c.first_crossing(lambda t: 1., t0, t1, **TOL)
        stuck = c.first_crossing(lambda t: 1., 1e20, 1e20+1e6, **TOL)
        self.assertEqual(stuck["status"], "UNRESOLVED_TIME_RESOLUTION")
        seen = []
        def g(t):
            seen.append(t)
            return t-.5
        out = c.first_crossing(g, 0., 1., **dict(TOL, budget=2))
        self.assertEqual(out["status"], "UNRESOLVED_BUDGET")
        self.assertEqual(out["samples"], len(seen))
        self.assertLessEqual(len(seen), 2)


class SimultaneityTests(unittest.TestCase):
    stocks = {"melt": 1.0, "source": 1.0}

    def test_transaction_refusals_leave_inputs_unchanged(self):
        original = dict(self.stocks)
        for tx in ({"debits": {"melt": 2.0}, "credits": {"crust": 2.0}},
                   {"debits": {"melt": 0.5}, "credits": {"crust": 0.25}},
                   {"debits": {"melt": -0.5}, "credits": {"crust": -0.5}},
                   {"debits": {"absent": 0.5}, "credits": {"crust": 0.5}}):
            with self.subTest(tx=tx), self.assertRaises(ValueError):
                c.apply_transaction(self.stocks, tx)
        self.assertEqual(self.stocks, original)

    def test_joint_conflict_refused_atomically_in_every_order(self):
        a = {"event_id": "a", "debits": {"melt": 0.75}, "credits": {"north": 0.75}}
        b = {"event_id": "b", "debits": {"melt": 0.5}, "credits": {"south": 0.5}}
        for order in itertools.permutations([a, b]):
            out = c.commit_simultaneous(self.stocks, list(order))
            self.assertEqual(out["status"], "REFUSED_JOINT")
            self.assertEqual(out["state"], self.stocks)

    def test_disjoint_commute_and_duplicate_ids_refused(self):
        a = {"event_id": "a", "debits": {"melt": 0.25}, "credits": {"x": 0.25}}
        b = {"event_id": "b", "debits": {"source": 0.5}, "credits": {"y": 0.5}}
        states = [c.commit_simultaneous(self.stocks, list(p))["state"] for p in itertools.permutations([a, b])]
        self.assertEqual(states[0], states[1])
        with self.assertRaises(ValueError):
            c.commit_simultaneous(self.stocks, [a, dict(b, event_id="a")])

    def test_control(self):
        self.assertTrue(c.simultaneity_control()["passed"])

    def test_invalid_individual_transfers_cannot_cancel(self):
        a = {"event_id": "a", "debits": {"melt": .5}, "credits": {"x": .25}}
        b = {"event_id": "b", "debits": {"melt": .5}, "credits": {"x": .75}}
        for order in itertools.permutations([a, b]):
            with self.assertRaises(ValueError):
                c.commit_simultaneous(self.stocks, list(order))
        a = dict(a, debits={"melt": -.25}, credits={"x": -.25})
        b = dict(b, debits={"melt": .75}, credits={"x": .75})
        with self.assertRaises(ValueError):
            c.commit_simultaneous(self.stocks, [a, b])

    def test_invalid_parent_and_output_accounts_refused(self):
        tx = {"debits": {"melt": .5}, "credits": {"x": .5}}
        for bad in (math.inf, math.nan, -1.):
            with self.assertRaises(ValueError):
                c.apply_transaction(dict(self.stocks, unrelated=bad), tx)
        with self.assertRaisesRegex(ValueError, "overflow"):
            c.apply_transaction({"melt": 1e308, "x": 1e308},
                                {"debits": {"melt": 1e308}, "credits": {"x": 1e308}})


class SeparationTests(unittest.TestCase):
    p = c.PARAMETERS["separation"]

    def test_closed_form_derivative_matches_thinning_law(self):
        # Independent oracle: dt/dh from central differences equals -1/(dh/dt).
        for h in (9e4, 1e4, 500.0):
            step = 1e-6*h
            slope = (c.rift_time(h+step, self.p)-c.rift_time(h-step, self.p))/(2*step)
            rate = -2*c.rift_velocity(h, self.p)*h/self.p["active_width_m"]
            self.assertAlmostEqual(slope*rate, 1.0, places=6)

    def test_decoupling_bounds_velocity_change(self):
        for h in (1e5, 7031.25, 70.3125):
            ratio = c.rift_ratio(h, self.p)
            limit = self.p["driving_force_N_per_m"]/(self.p["basal_drag_Pa_s_per_m"]*self.p["plate_width_m"])
            change = (limit-c.rift_velocity(h, self.p))/limit
            self.assertAlmostEqual(change, ratio/(1+ratio), places=12)

    def test_invalid_thickness_or_parameters(self):
        for h in (0.0, -1.0, 2e5):
            with self.assertRaises(ValueError):
                c.rift_time(h, self.p)
        with self.assertRaises(ValueError):
            c.rift_velocity(1e3, dict(self.p, rift_viscosity_Pa_s=-1.0))

    def test_control(self):
        out = c.separation_control()
        self.assertTrue(out["passed"], out["criteria"])
        self.assertEqual(out["at_handoff"]["ocean_area_created_m2_per_m"], 0.0)


class SupplyTests(unittest.TestCase):
    s = c.PARAMETERS["supply"]

    def test_quoted_polynomials_and_branch_limits(self):
        self.assertEqual(c.solidus_C(0.0), 1085.7)
        self.assertEqual(c.liquidus_C(0.0), 1475.0)
        self.assertEqual(c.melt_fraction(1000.0, 1.0), 0.0)
        with self.assertRaises(ValueError):
            c.melt_fraction(1600.0, 0.0)

    def test_latent_root_satisfies_quoted_relation(self):
        t, x = c.latent_state(1320.0, 0.5, self.s)
        self.assertGreater(x, 0.0)
        self.assertAlmostEqual(1320.0-t, x*300.0/1200.0*(t+273.0), places=9)
        self.assertEqual(c.latent_state(1000.0, 1.0, self.s), (1000.0, 0.0))

    def test_deep_lid_exhumes_mantle_and_cold_mantle_refused(self):
        self.assertEqual(c.melt_column(1300.0, 60000.0, self.s)["H_m"], 0.0)
        with self.assertRaises(ValueError):
            c.melt_column(1000.0, 0.0, self.s)
        with self.assertRaises(ValueError):
            c.melt_column(1300.0, -1.0, self.s)


class MigrationTests(unittest.TestCase):
    def test_rrr_circumcentre_independent_oracle(self):
        v = {"A": np.array([0.0, 0.0]), "B": np.array([2.0, 0.0]), "C": np.array([0.0, 2.0])}
        lines = [c.boundary_line("ridge", c.perpendicular(v[b]-v[a]), v, left=a, right=b)
                 for a, b in (("A", "B"), ("B", "C"), ("C", "A"))]
        j, residual = c.junction(lines)
        np.testing.assert_allclose(j, [1.0, 1.0], atol=1e-14)
        self.assertLess(residual, 1e-14)

    def test_boundary_rules_refuse_unsupported_input(self):
        v = {"A": np.array([0.0, 0.0]), "B": np.array([1.0, 1.0])}
        with self.assertRaises(ValueError):          # oblique relative motion is not a transform
            c.boundary_line("transform", np.array([1.0, 0.0]), v, left="A", right="B")
        with self.assertRaises(ValueError):          # polarity must name one side
            c.boundary_line("trench", np.array([1.0, 0.0]), v, left="A", right="B", overriding="C")
        with self.assertRaises(ValueError):
            c.boundary_line("ridge", np.array([1.0, 0.0]), v, left="A", right="B", accretion_fraction=1.5)
        with self.assertRaises(ValueError):
            c.boundary_line("suture", np.array([1.0, 0.0]), v, left="A", right="B")

    def test_full_vector_decomposition(self):
        opening, slip = c.decompose([0.0, 0.0], [3.0, 4.0], [1.0, 0.0])
        self.assertEqual((opening, slip), (3.0, 4.0))
        self.assertEqual(c.decompose([0.0, 0.0], [0.0, 5.0], [1.0, 0.0])[0], 0.0)

    def test_control(self):
        self.assertTrue(c.migration_control()["passed"])

    def test_incompatible_junction_cannot_pass_by_changing_frame(self):
        normals = [np.array([1., 0.]), np.array([0., 1.]), np.array([1., 1.])/math.sqrt(2)]
        points = [np.array([0., 0.]), np.array([0., 0.]), np.array([1., 1.])]
        residuals = [c.junction([(n, p+shift) for n, p in zip(normals, points)])[1]
                     for shift in (0., 1e14)]
        self.assertGreater(residuals[0], .1)
        self.assertAlmostEqual(residuals[0], residuals[1], places=14)
        for order in itertools.permutations(zip(normals, points)):
            self.assertAlmostEqual(c.junction(order)[1], residuals[0], places=14)

    def test_stationary_degenerate_and_invalid_junctions(self):
        normals = [np.array([1., 0.]), np.array([0., 1.])]
        result, residual = c.junction([(n, np.zeros(2)) for n in normals])
        np.testing.assert_array_equal(result, [0., 0.])
        self.assertEqual(residual, 0.)
        with self.assertRaisesRegex(ValueError, "underdetermined"):
            c.junction([(normals[0], np.zeros(2)), (normals[0], np.ones(2))])
        for bad in ([0., 0.], [math.nan, 1.], [1., 2., 3.]):
            with self.assertRaises(ValueError):
                c.perpendicular(bad)


class SlabTests(unittest.TestCase):
    s = c.PARAMETERS["slab"]

    def test_theta_limits(self):
        thick = self.s["plate_thickness_m"]
        self.assertEqual(c.theta_integral(thick, 0.0, self.s), 0.0)
        self.assertEqual(c.theta_integral(thick, None, self.s), thick/2)
        age = 2*c.MYR_S
        expected = 2*math.sqrt(self.s["diffusivity_m2_s"]*age/math.pi)
        self.assertAlmostEqual(c.theta_integral(thick, age, self.s)/expected, 1.0, places=12)
        old = c.theta_integral(thick, 2000*c.MYR_S, self.s)
        self.assertAlmostEqual(old/(thick/2), 1.0, places=12)

    def test_buoyancy_sign_and_invalid_inputs(self):
        young = c.column_excess(2*c.MYR_S, 6000.0, 2900.0, self.s)
        old = c.column_excess(100*c.MYR_S, 6000.0, 2900.0, self.s)
        self.assertLess(young, 0.0)
        self.assertGreater(old, 0.0)
        with self.assertRaises(ValueError):
            c.theta_integral(1000.0, -1.0, self.s)
        with self.assertRaises(ValueError):
            c.theta_integral(2*self.s["plate_thickness_m"], None, self.s)

    def test_attached_window_first_in_first_out(self):
        s = dict(self.s, transmission_C=1.0, gravity_m_s2=1.0, initial_slab_m=100.0,
                 attached_limit_m=150.0, ocean_ahead_m=80.0)
        self.assertEqual(c.slab_force(0.0, 2.0, -1.0, s), 200.0)          # 100 m of initial ocean
        self.assertEqual(c.slab_force(40.0, 2.0, -1.0, s), 280.0)         # window grows to 140 m
        self.assertEqual(c.slab_force(100.0, 2.0, -1.0, s), 2.0*130.0-20.0)  # 20 m of continent entered

    def test_young_ocean_forced_convergence_creates_no_slab(self):
        out = c.forced_initiation(5.0, 2.0, self.s)
        self.assertEqual(out["state"], "stalled_incipient_underthrust")
        self.assertGreater(out["convergence_m"], 0.0)
        self.assertIsNone(out["critical_attached_length_m"])

    def test_control(self):
        out = c.slab_control()
        self.assertTrue(out["passed"], out["criteria"])


class BindingTests(unittest.TestCase):
    def test_case_record_matches_executable(self):
        import json
        spec = json.loads(c.CASE.read_text(encoding="utf-8"))
        self.assertEqual(spec["control_policy"], c.POLICY)
        self.assertEqual(spec["control_parameters"], c.PARAMETERS)
        self.assertEqual(spec["contract_document"], "docs/I01_TRANSITIONS.md")


if __name__ == "__main__":
    unittest.main()
