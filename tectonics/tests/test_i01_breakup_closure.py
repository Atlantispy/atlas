"""Focused I01 breakup-closure tests: exact invariants, analytical feasibility and its preconditions, refusals, the
regularised-plastic asymptote, retained regime, deadline and quadrature guards, and case guards.
No world generation, native import or bounded campaign run; two controls are called directly for their new records and
the CLI is exercised only for exclusive creation.
SPDX-License-Identifier: AGPL-3.0-only
"""
import copy
import json
import math
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"tools"))
import check_i01_breakup_closure as b

PAR, POL = b.PARAMETERS, b.POLICY
CHAIN = b.Chain(**PAR["chain"])
L, ELL, H = CHAIN.half_width_m, CHAIN.weakness_length_m, CHAIN.thickness_m
COARSE, FINE = POL["gauss_orders"]


def basis(n, thickness=H):
    return b.power_law_basis(n, thickness, L, ELL)


class ShareTests(unittest.TestCase):
    def test_root_residual_limits_and_scalar_parity(self):
        g = np.array([0.0, 1e-8, 0.5, 4.0, 1e6, 1e30])
        for n in (1.0, 2.0, 3.0, 3.5, 5.0):
            with self.subTest(n=n):
                phi = b.share(g, n)
                self.assertTrue(np.all((phi > 0) & (phi <= 1)))
                self.assertEqual(float(phi[0]), 1.0)
                self.assertLessEqual(float(np.max(np.abs(phi+g*phi**n-1))), 1e-14)
                for gi, pi in zip(g, phi):
                    self.assertLessEqual(b.relative(b.share1(float(gi), n), float(pi)), 1e-14)

    def test_share_falls_as_the_belt_weakens(self):
        self.assertTrue(np.all(np.diff(b.share(np.logspace(-3, 12, 200), 3.0)) < 0))

    def test_share_refusals(self):
        for g in (-1.0, math.inf, math.nan):
            with self.subTest(g=g), self.assertRaises(ValueError):
                b.share(g, 3.0)
        with self.assertRaises(ValueError):
            b.share(1.0, 0.5)


class ProfileTests(unittest.TestCase):
    def test_independent_hypergeometric_values(self):
        for n in (1.0, 2.0, 3.0, 3.5, 5.0):
            for d in PAR["hypergeometric_deltas"]:
                with self.subTest(n=n, delta=d):
                    u, du = b.profile(d, n, L, ELL, FINE)
                    uh, duh = b.hypergeometric_profile(d, n, L, ELL)
                    self.assertLessEqual(b.relative(float(u[0]), uh), 1e-10)
                    self.assertLessEqual(b.relative(float(du[0]), duh), 1e-10)

    def test_closed_forms_down_to_tiny_delta(self):
        d = 2.0**-np.arange(2.0, 60.0, 5.0)
        for n in (1.0, 2.0):
            with self.subTest(n=n):
                u, _ = b.profile(d, n, L, ELL, FINE)
                self.assertLessEqual(b.max_relative(u, b.closed_opening(d, n, L, ELL)), 1e-10)

    def test_pinch_limit_and_square_root_approach(self):
        star = b.opening_limit(3.0, L, ELL)
        self.assertAlmostEqual(star, 2*(3*ELL**(2/3)*L**(1/3)-L), delta=1e-9*star)
        for n in (1.0, 2.0):
            self.assertIsNone(b.opening_limit(n, L, ELL))
        u, _ = b.profile(np.array([1e-12, 1e-18, 1e-24]), 3.0, L, ELL, FINE)
        gaps = star-u
        self.assertTrue(np.all(gaps > 0) and np.all(np.diff(gaps) < 0))
        # U* - U ~ delta^(1/2 - 1/n) = delta^(1/6): a factor 1e-6 in delta shrinks the gap tenfold
        self.assertAlmostEqual(gaps[1]/gaps[0], 0.1, delta=1e-4)
        self.assertAlmostEqual(gaps[2]/gaps[1], 0.1, delta=1e-4)

    def test_derivative_consistency_and_rest_state(self):
        for n in (1.0, 3.0, 5.0):
            for d in (0.3, 1e-3, 1e-9):
                with self.subTest(n=n, delta=d):
                    u = float(b.profile(d, n, L, ELL, FINE)[0][0])
                    self.assertLessEqual(b.relative(b.integrated_opening(d, n, L, ELL, FINE), u), 1e-9)
        u, du = b.profile(1.0, 3.0, L, ELL, FINE)
        self.assertEqual(float(u[0]), 0.0)
        self.assertAlmostEqual(float(du[0]), CHAIN.width_scale()/3, delta=1e-9*CHAIN.width_scale())

    def test_profile_refusals(self):
        for d in (0.0, -1e-3, 1.5, math.nan):
            with self.subTest(delta=d), self.assertRaises(ValueError):
                b.profile(d, 3.0, L, ELL, FINE)
        with self.assertRaises(ValueError):
            b.profile(0.5, 3.0, ELL, L, FINE)                  # L >= ell: the weakness would change sign
        with self.assertRaises(ValueError):
            b.profile(0.5, 0.5, L, ELL, FINE)
        with self.assertRaises(ValueError):
            b.hypergeometric_profile(0.01, 3.0, L, ELL)         # |z| > 1
        with self.assertRaises(ValueError):
            b.closed_opening(0.5, 3.0, L, ELL)
        with self.assertRaises(ValueError):
            b.columns(8, L, ELL, "unknown")
        with self.assertRaises(ValueError):
            b.columns(8, L, ELL, "plateau", L)
        with self.assertRaises(ValueError):
            b.Chain(**dict(PAR["chain"], initial_belt_share=1.0))

    def test_cached_quadrature_is_immutable_and_bounded(self):
        nodes, weights = b.gauss(FINE)
        self.assertIs(b.gauss(FINE)[0], nodes)                  # served from the cache
        self.assertAlmostEqual(float(np.sum(weights)), 2.0, delta=1e-12)
        for array in (nodes, weights):
            self.assertFalse(array.flags.writeable)
            with self.assertRaises(ValueError):
                array.setflags(write=True)                      # bytes backing: the flag cannot be restored
            with self.assertRaises(ValueError):
                array[0] = 0.0
        self.assertEqual(b.gauss.cache_info().maxsize, len(POL["gauss_orders"]))
        with self.assertRaises(ValueError):
            b.gauss(7)


class ChainTests(unittest.TestCase):
    n = 3.0

    def setUp(self):
        self.g0, self.scale = CHAIN.g0(self.n), CHAIN.width_scale()

    def test_time_stepped_chain_matches_exact_discrete_solution(self):
        _, q, alpha, dx = b.columns(32, L, ELL)
        run = b.run_chain(q, alpha, dx, self.n, self.g0, self.scale, 0.2, POL)
        opening, tau = b.discrete_oracle(q, alpha, dx, self.n, self.g0, self.scale, 0.2, FINE)
        self.assertLessEqual(b.relative(run["opening_m"], opening), 1e-8)
        self.assertLessEqual(b.relative(run["tau"], tau), 1e-8)
        self.assertLessEqual(run["invariant_residual"], 1e-9)
        self.assertLessEqual(run["work_relative"], 1e-9)
        self.assertLessEqual(run["kinematic_relative"], 1e-9)
        self.assertLessEqual(run["root_residual"], 1e-14)
        self.assertAlmostEqual(run["thinnest_fraction"], 0.2, delta=1e-9)
        self.assertGreater(run["share_start"], run["share_end"])

    def test_opening_at_detection_ignores_force_history(self):
        _, q, alpha, dx = b.columns(16, L, ELL)
        steady = b.run_chain(q, alpha, dx, self.n, self.g0, self.scale, 0.25, POL)
        wavy = b.run_chain(q, alpha, dx, self.n, self.g0, self.scale, 0.25, POL,
                           prescribed=lambda t: 0.5+0.2*math.sin(40*t))
        self.assertLessEqual(b.relative(wavy["opening_m"], steady["opening_m"]), 1e-8)
        self.assertGreater(b.relative(wavy["tau"], steady["tau"]), 0.01)
        self.assertLessEqual(wavy["invariant_residual"], 1e-9)
        self.assertNotIn("work_relative", wavy)

    def test_uniform_chain_is_the_affine_strip(self):
        tau = b.affine_time(self.n, self.g0, 0.25, FINE)
        for size in (1, 4):
            with self.subTest(columns=size):
                _, q, alpha, dx = b.columns(size, L, ELL, "uniform")
                run = b.run_chain(q, alpha, dx, self.n, self.g0, 2*L, 0.25, POL)
                self.assertLessEqual(b.relative(run["opening_m"], 2*L*3.0), 1e-9)
                self.assertLessEqual(b.relative(run["tau"], tau), 1e-9)
                self.assertLessEqual(run["column_spread_relative"], 1e-12)

    def test_chain_refusals(self):
        _, q, alpha, dx = b.columns(8, L, ELL)
        with self.assertRaises(ValueError):
            b.run_chain(q, alpha+1e-3, dx, self.n, self.g0, self.scale, 0.2, POL)
        with self.assertRaises(ValueError):
            b.run_chain(q, alpha, dx, self.n, self.g0, self.scale, 0.2, POL, prescribed=lambda t: 1.5)
        with self.assertRaises(ValueError):
            b.run_chain(q, alpha, dx, self.n, self.g0, self.scale, 0.2, dict(POL, ode_span_scaled=1e-6))
        with self.assertRaises(RuntimeError):
            b.run_chain(q, alpha, dx, self.n, self.g0, self.scale, 0.2, POL, deadline=0.0)

    def test_deadline_stops_a_solve_after_entry(self):
        _, q, alpha, dx = b.columns(8, L, ELL)
        readings, loads = iter([0.0]), []

        def clock():
            return next(readings, 10.0)                         # entry reads 0 s; every later reading is past 1 s

        def load(tau):
            loads.append(tau)
            return 0.5
        with mock.patch.object(b.time, "perf_counter", clock), self.assertRaises(RuntimeError):
            b.run_chain(q, alpha, dx, self.n, self.g0, self.scale, 0.2, POL, prescribed=load, deadline=1.0)
        self.assertEqual(loads, [])                             # stopped inside the solver, before any stage load


class DeadlineTests(unittest.TestCase):
    def test_every_control_stops_at_entry_once_the_budget_is_spent(self):
        spec = b.load_case()
        started = AssertionError("control work started after the budget was spent")
        with mock.patch.object(b.time, "perf_counter", lambda: 10.0), \
                mock.patch.object(b, "Chain", side_effect=started):
            for name, control in b.CONTROLS:
                with self.subTest(control=name), self.assertRaises(RuntimeError):
                    control(spec, 1.0)


class FeasibilityTests(unittest.TestCase):
    def test_ladder_verdicts_on_known_sequences(self):
        k = np.arange(1, 13, dtype=float)
        geometric = b.ladder_verdict(10-2**(-0.5*k), POL)
        self.assertEqual(geometric["verdict"], "FINITE_LIMIT")
        self.assertAlmostEqual(geometric["exponent"], 0.5, places=10)
        self.assertAlmostEqual(geometric["limit"], 10.0, delta=1e-12)
        for divergent in (k*math.log(2), 2.0**k, np.sqrt(2.0)**k):
            self.assertEqual(b.ladder_verdict(divergent, POL)["verdict"], "NO_FINITE_LIMIT")
        self.assertEqual(b.ladder_verdict(np.array([1., 2., 3., 2.5, 4., 5.]), POL)["verdict"], b.UNRESOLVED)
        self.assertEqual(b.ladder_verdict(np.array([0., 1., 1.8, 2.3, 2.9, 3.2]), POL)["verdict"], b.UNRESOLVED)
        with self.assertRaises(ValueError):
            b.ladder_verdict(np.arange(4.0), POL)

    def test_power_law_statuses(self):
        expected = {3.0: b.FEASIBLE, 3.5: b.FEASIBLE, 2.0: b.NO_LIMIT, 1.0: b.NO_LIMIT, 5.0: b.OUTSIDE}
        for n, status in expected.items():
            with self.subTest(n=n):
                lad = b.continuum_ladder(n, CHAIN, PAR, POL)
                self.assertLessEqual(lad["quadrature"], POL["quadrature_relative"])
                result = b.feasibility(lad["opening"], lad["time"], lad["slope"], basis(n), POL)
                self.assertEqual(result["status"], status)
                self.assertEqual(result["resolved_event"], b.UNRESOLVED)
        lad = b.continuum_ladder(3.0, CHAIN, PAR, POL)
        result = b.feasibility(lad["opening"], lad["time"], lad["slope"], basis(3.0), POL)
        self.assertLessEqual(b.relative(result["opening"]["limit"], b.opening_limit(3.0, L, ELL)),
                             POL["tail_opening_relative"])
        self.assertLessEqual(b.relative(result["time"]["limit"], b.pinch_time(3.0, CHAIN, FINE)),
                             POL["tail_time_relative"])
        # the same ladder under another declared exponent disagrees with that exact solution
        other = b.feasibility(lad["opening"], lad["time"], lad["slope"], basis(3.5), POL)
        self.assertEqual(other["status"], b.UNRESOLVED)

    def test_slender_cusped_belt_is_refused_whatever_the_sampled_slopes(self):
        lad = b.continuum_ladder(5.0, CHAIN, PAR, POL)
        thin = PAR["slender_thickness_m"]
        slopes = b.max_slope(lad["delta"], 5.0, thin, L, ELL)
        self.assertLessEqual(float(np.max(slopes)), POL["slope_bound"])       # every sampled rung looks long-wave
        self.assertEqual(b.ladder_verdict(lad["opening"], POL)["verdict"], "FINITE_LIMIT")
        self.assertEqual(b.ladder_verdict(lad["time"], POL)["verdict"], "FINITE_LIMIT")
        result = b.feasibility(lad["opening"], lad["time"], slopes, basis(5.0, thin), POL)
        self.assertEqual(result["status"], b.OUTSIDE)
        self.assertIsNone(result["first_level_outside"])
        # the tip slope keeps growing as (h/H)^((4-n)/2): each halving multiplies it by 2^(1/2) for n = 5
        self.assertAlmostEqual(float(slopes[-1]/slopes[-2]), math.sqrt(2), delta=1e-3)

    def test_unsupported_basis_is_refused(self):
        lad = b.continuum_ladder(3.0, CHAIN, PAR, POL)
        args = (lad["opening"], lad["time"], lad["slope"])
        self.assertEqual(b.feasibility(*args, basis(3.0), POL)["status"], b.FEASIBLE)
        changes = (dict(law="effective_exponent_at_one_state"), dict(law="parallel_creep_and_plastic"),
                   dict(profile="smooth_minimum"), dict(profile="quartic_minimum"), dict(half_width_m=ELL),
                   dict(thickness_m=-H), dict(exponent=math.nan), dict(exponent=0.5))
        for change in changes:
            with self.subTest(change=change):
                result = b.feasibility(*args, dict(basis(3.0), **change), POL)
                self.assertEqual(result["status"], b.UNSUPPORTED)
                self.assertEqual(result["resolved_event"], b.UNRESOLVED)
        missing = {key: value for key, value in basis(3.0).items() if key != "profile"}
        for index, bad in enumerate((missing, dict(basis(3.0), provenance="n_eff"), None, [3.0])):
            with self.subTest(basis=index):
                self.assertEqual(b.feasibility(*args, bad, POL)["status"], b.UNSUPPORTED)

    def test_converging_arrays_without_the_exact_solution_are_not_feasible(self):
        k = np.arange(1, 13, dtype=float)
        tail = 2-2**(-0.5*k)                                    # geometric, with the n = 3 exponent 1/2
        result = b.feasibility(1e6*tail, 1e15*tail, np.full(k.size, 0.01), basis(3.0), POL)
        self.assertEqual(result["opening"]["verdict"], "FINITE_LIMIT")
        self.assertAlmostEqual(result["opening"]["exponent"], 0.5, places=10)
        self.assertEqual(result["status"], b.UNRESOLVED)        # its 2e6 m limit is not the basis's closed-form U*

    def test_malformed_ladders_raise_instead_of_granting_a_status(self):
        lad = b.continuum_ladder(3.0, CHAIN, PAR, POL)
        u, t, s = lad["opening"], lad["time"], lad["slope"]

        def spoil(values, index, value):
            out = np.array(values, dtype=float)
            out[index] = value
            return out
        cases = ((spoil(u, 11, math.nan), t, s), (u, spoil(t, 5, math.inf), s), (u, t, spoil(s, 3, math.nan)),
                 (u, t, spoil(s, 0, -0.01)), (spoil(u, 0, -1.0), t, s), (u, spoil(t, 0, 0.0), s),
                 (u[:-1], t, s), (u, t, s[:-1]), (u, t, np.vstack([s, s])), (u[:4], t[:4], s[:4]))
        for index, (uu, tt, ss) in enumerate(cases):
            with self.subTest(case=index), self.assertRaises(ValueError):
                b.feasibility(uu, tt, ss, basis(3.0), POL)

    def test_pinch_time_rules_agree_and_exist_only_above_two(self):
        for n in (3.0, 3.5, 5.0):
            with self.subTest(n=n):
                self.assertLessEqual(b.relative(b.pinch_time(n, CHAIN, COARSE), b.pinch_time(n, CHAIN, FINE)), 1e-10)
        with self.assertRaises(ValueError):
            b.pinch_time(2.0, CHAIN, FINE)

    def test_long_wave_slope_window(self):
        tiny = 2.0**-60
        self.assertLessEqual(float(b.max_slope(tiny, 3.0, H, L, ELL)), POL["slope_bound"])
        self.assertLessEqual(float(b.max_slope(tiny, 4.0, H, L, ELL)), POL["slope_bound"])
        self.assertGreater(float(b.max_slope(tiny, 5.0, H, L, ELL)), POL["slope_bound"])
        # for 2 <= n <= 4 the largest slope rises monotonically to 2 H (L/ell)^(4/n - 1)/(n ell) at the belt edges
        for n in (2.0, 3.0, 3.5, 4.0):
            with self.subTest(n=n):
                limit = float(b.max_slope(0.0, n, H, L, ELL))
                self.assertLessEqual(b.relative(limit, 2*H*(L/ELL)**(4/n-1)/(n*ELL)), 1e-13)
                slopes = b.max_slope(2.0**-np.arange(1.0, 41.0), n, H, L, ELL)
                self.assertTrue(np.all(np.diff(slopes) > 0) and np.all(slopes < limit))
                self.assertLessEqual(b.relative(float(slopes[-1]), limit), 1e-10)

    def test_kinematic_negatives_have_no_limit(self):
        k = np.arange(1, 13)
        delta = 2.0**(-3.0*k)
        width = 0.2*L
        plateau = 2*width*(delta**(-1/3)-1)+b.profile(delta, 3.0, L-width, ELL, FINE)[0]
        for values in (2*L*(2.0**k-1), 5000.0*k*math.log(2), plateau):
            self.assertEqual(b.ladder_verdict(values, POL)["verdict"], "NO_FINITE_LIMIT")


class DynamicsTests(unittest.TestCase):
    def test_decoupling_precedes_pinch_off_or_happens_without_it(self):
        eps = PAR["decoupling_share"]
        three = b.decoupling(3.0, CHAIN, eps, FINE)
        self.assertLessEqual(three["share_relative"], 1e-9)
        self.assertLess(three["time_s"], b.pinch_time(3.0, CHAIN, FINE))
        self.assertLess(three["opening_m"], b.opening_limit(3.0, L, ELL))
        one = b.decoupling(1.0, CHAIN, eps, FINE)
        self.assertTrue(math.isfinite(one["time_s"]) and one["thinnest_fraction"] > 0)
        self.assertIsNone(b.opening_limit(1.0, L, ELL))
        with self.assertRaises(ValueError):
            b.decoupling(3.0, CHAIN, 0.6, FINE)

    def test_discrete_chain_converges_at_second_order(self):
        u_ref = float(b.profile(0.1**3, 3.0, L, ELL, FINE)[0][0])
        errors = []
        for size in (256, 512, 1024):
            _, q, alpha, dx = b.columns(size, L, ELL)
            u, _ = b.discrete_oracle(q, alpha, dx, 3.0, CHAIN.g0(3.0), CHAIN.width_scale(), 0.1, FINE)
            errors.append(b.relative(u, u_ref))
        for coarse, fine in zip(errors, errors[1:]):
            self.assertTrue(1.8 <= math.log2(coarse/fine) <= 2.2)

    def test_rigid_plastic_opening_scales_with_column_width(self):
        rows = [b.rigid_plastic_opening(size, CHAIN, 0.1) for size in (64, 128, 256)]
        self.assertTrue(all(r["weakest_columns"] == 2 for r in rows))
        self.assertEqual(rows[0]["opening_m"], 2*rows[1]["opening_m"])
        self.assertEqual(rows[1]["opening_m"], 2*rows[2]["opening_m"])


class PlasticityTests(unittest.TestCase):
    def test_regularised_plastic_share_vanishes_at_high_stress(self):
        pp = PAR["parallel_plastic"]
        n, k, sigma = pp["exponent"], pp["scaled_creep"], np.array(pp["stress_multiples"])
        point = b.parallel_plastic(sigma, n, k)
        # r = k sigma^n + sigma - 1 at sigma = 10: plastic-dominated and nearly linear
        self.assertAlmostEqual(float(point["plastic_share"][0]), 9/(9+k*10**n), delta=1e-14)
        self.assertAlmostEqual(float(point["local_exponent"][0]), (n*k*10**n+10)/(9+k*10**n), delta=1e-12)
        self.assertLess(float(point["local_exponent"][0]), 1.2)
        # high stress: creep dominates, the share ~ sigma^(1-n)/k -> 0 and the local exponent -> n, not 1
        top, share = float(sigma[-1]), float(point["plastic_share"][-1])
        self.assertAlmostEqual(share*k*top**(n-1), 1.0, delta=1e-3)
        self.assertLess(abs(float(point["local_exponent"][-1])-n), 1e-3)
        self.assertTrue(np.all(np.diff(point["plastic_share"]) < 0))
        # the retained point kernel adds the same two rates at one stress
        kernel = b.parallel_kernel(sigma, n, k)
        self.assertLessEqual(b.max_relative(kernel["stress"], sigma), POL["parity_relative"])
        self.assertLessEqual(b.max_relative(kernel["plastic_share"], point["plastic_share"]), POL["parity_relative"])
        # the frozen rule refuses the low-stress state and admits the high-stress one: a regime, not a theorem
        rule = PAR["retained"]
        self.assertTrue(b.regime_reasons(float(point["plastic_share"][0]), 1/float(point["local_exponent"][0]), rule))
        self.assertEqual(b.regime_reasons(share, 1/float(point["local_exponent"][-1]), rule), [])
        # the hypothesis n > 1 matters: with linear creep the share tends to 1/(1 + k), not to zero
        linear = b.parallel_plastic(np.array([1e8]), 1.0, k)
        self.assertAlmostEqual(float(linear["plastic_share"][0]), 1/(1+k), delta=1e-9)

    def test_parallel_plastic_refusals(self):
        for index, sigma in enumerate((np.array([0.5, 2.0]), np.array([2.0, math.nan]), np.array([[2.0]]))):
            with self.subTest(case=index), self.assertRaises(ValueError):
                b.parallel_plastic(sigma, 3.0, 1e-4)
        with self.assertRaises(ValueError):
            b.parallel_plastic(np.array([2.0]), 3.0, 0.0)


class ControlTests(unittest.TestCase):
    def test_pinch_control_is_analytical_feasibility_not_an_event(self):
        data = b.pinch_control(b.load_case())
        self.assertTrue(data["passed"], data["checks"])
        self.assertFalse(any("certified" in name for name in data["checks"]))
        for case in data["cases"].values():
            self.assertEqual(case["feasibility"]["status"], b.FEASIBLE)
            self.assertEqual(case["feasibility"]["resolved_event"], b.UNRESOLVED)
        resolution = data["resolution"]
        self.assertEqual(resolution["resolved_event"], b.UNRESOLVED)
        self.assertEqual(resolution["refinement_detection_fraction"], PAR["detection_fraction"])
        # rung-12 material neck scales (about 2.29 m and 0.286 m) against the finest refinement column (about 293 m)
        self.assertAlmostEqual(resolution["finest_column_width_m"], 2*L/max(PAR["refinement_columns"]), delta=1e-9)
        self.assertAlmostEqual(resolution["deepest_neck_material_scale_m"]["reference"], ELL*2.0**-18, delta=1e-6)
        self.assertAlmostEqual(resolution["deepest_neck_material_scale_m"]["second"], ELL*2.0**-21, delta=1e-7)
        self.assertEqual(resolution["rungs_narrower_than_finest_column"], {"reference": 5, "second": 6})

    def test_validity_control_refusals_and_counterexample(self):
        data = b.validity_control(b.load_case())
        self.assertTrue(data["passed"], data["checks"])
        self.assertEqual(data["cusped"]["feasibility"]["status"], b.OUTSIDE)
        self.assertEqual(data["slender"]["feasibility"]["status"], b.OUTSIDE)
        self.assertIsNone(data["slender"]["feasibility"]["first_level_outside"])
        self.assertEqual(data["rigid_plastic"]["status"], b.ILL_POSED)
        self.assertTrue(data["parallel_plastic"]["regimes"][0])
        self.assertEqual(data["parallel_plastic"]["regimes"][-1], [])


class RetainedTests(unittest.TestCase):
    def test_regime_at_the_accepted_initial_state(self):
        data = b.retained_control(b.load_case())
        for name in ("same_state_as_accepted_receipt", "drive_and_thickness_match_chain", "force_rises_with_rate",
                     "force_falls_with_stretch", "rate_sensitivity_in_unit_interval", "work_partition_closes"):
            self.assertTrue(data["checks"][name], name)
        self.assertIn(data["classification"], (b.CONSISTENT, b.RESOLVED_NECK))
        self.assertEqual(data["eventual_breakup"], b.UNRESOLVED)
        self.assertFalse(data["generated_breakup_authorised"])


class CaseTests(unittest.TestCase):
    def setUp(self):
        self.raw = json.loads(b.CASE.read_text(encoding="utf-8"))

    def test_case_equals_executable(self):
        spec = b.load_case()
        self.assertEqual(spec["control_policy"], POL)
        self.assertEqual(spec["control_parameters"], PAR)
        decision = spec["decision"]
        self.assertEqual((decision["selected_law"], decision["event_record"]), (b.LAW, b.EVENT))
        self.assertTrue(decision["established"].startswith(b.FEASIBLE))
        self.assertTrue(decision["resolved_event"].startswith(b.UNRESOLVED))
        self.assertNotIn("CONNECTIVITY_LOSS_CERTIFIED", json.dumps(spec))
        self.assertLessEqual(POL["maximum_seconds"], 60)

    def test_case_mutations_refused(self):
        mutations = ((("schema",), "atlas.other"), (("status",), "CANON"),
                     (("decision", "selected_law"), "atlas.thin-crust-cutoff"),
                     (("decision", "event_record"), "atlas.other"),
                     (("control_policy", "maximum_seconds"), 61.0), (("control_policy", "slope_bound"), 0.5),
                     (("control_policy", "tail_opening_relative"), 1e-2),
                     (("control_policy", "scope"), "converged connectivity limit"),
                     (("control_parameters", "exponents", "reference"), 2.0),
                     (("control_parameters", "detection_fraction"), 0.5),
                     (("control_parameters", "slender_thickness_m"), 1e5),
                     (("control_parameters", "parallel_plastic", "exponent"), 1.0))
        for path, value in mutations:
            with self.subTest(path=path):
                spec = copy.deepcopy(self.raw)
                target = spec
                for key in path[:-1]:
                    target = target[key]
                target[path[-1]] = value
                with self.assertRaises(ValueError):
                    b.validate_case(spec)
        extra = dict(copy.deepcopy(self.raw), extra=1)
        with self.assertRaises(ValueError):
            b.validate_case(extra)

    def test_structural_parameter_refusals(self):
        cases = ((("maximum_seconds",), 61.0, True), (("gauss_orders",), [384, 192], True),
                 (("exponents", "reference"), 2.0, False), (("exponents", "second"), 4.5, False),
                 (("exponents", "subcritical"), [1.0, 2.5], False), (("exponents", "outside_validity"), 4.0, False),
                 (("ladder_levels",), 3, False), (("refinement_columns",), [256, 500, 1000], False),
                 (("rigid_plastic_columns",), [63, 126], False), (("decoupling_share",), 0.6, False),
                 (("hypergeometric_deltas",), [0.1], False), (("chain", "half_width_m"), 7e5, False),
                 (("prescribed_force", "relative_amplitude"), 1.5, False),
                 (("slender_thickness_m",), 2e5, False),
                 (("parallel_plastic", "exponent"), 1.0, False), (("parallel_plastic", "scaled_creep"), 0.0, False),
                 (("parallel_plastic", "stress_multiples"), [100.0, 10.0], False),
                 (("parallel_plastic", "stress_multiples"), [0.5, 10.0], False),
                 (("retained", "stretches"), [1.0, 1.6], False),
                 (("retained", "creep_rate_sensitivity"), [0.5, 0.25], False))
        for path, value, policy in cases:
            with self.subTest(path=path, value=value):
                par, pol = copy.deepcopy(PAR), copy.deepcopy(POL)
                target = pol if policy else par
                for key in path[:-1]:
                    target = target[key]
                target[path[-1]] = value
                with self.assertRaises(ValueError):
                    b.validate_parameters(par, pol)
        self.assertTrue(b.validate_parameters(copy.deepcopy(PAR), copy.deepcopy(POL)))


class BindingTests(unittest.TestCase):
    def test_bound_files_exist_and_imports_resolve(self):
        for name in b.NEW_FILES+b.RETAINED+(b.FAULT_CASE,)+tuple(b.ACCEPTED_RECEIPTS):
            self.assertTrue((b.ROOT/name).is_file(), name)
        self.assertTrue(all(b.evidence_match(b.bindings())["imported"].values()))

    def test_cli_refuses_to_overwrite(self):
        with tempfile.TemporaryDirectory() as folder:
            existing = Path(folder)/"receipt.json"
            existing.write_text("{}", encoding="utf-8")
            argv = ["check_i01_breakup_closure.py", "--output", str(existing)]
            with mock.patch.object(sys, "argv", argv), self.assertRaises(FileExistsError):
                b.main()
            self.assertEqual(existing.read_text(encoding="utf-8"), "{}")


if __name__ == "__main__":
    unittest.main()
