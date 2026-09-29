"""Focused seam checks for motion admission on the evolving finite-strain column; no native import.
SPDX-License-Identifier: AGPL-3.0-only
"""
from concurrent.futures import CancelledError
import copy
import dataclasses
from fractions import Fraction
import math
from pathlib import Path
import sys
import threading
import time
import unittest

import numpy as np
from threadpoolctl import threadpool_limits

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"tools"))
import check_i01_finite_admission as f

w, tm, motion = f.w, f.tm, f.motion
SPEC, CTX = f.load_case()
FC = CTX["fs_ctx"]
LAW, DRIVE = FC["law"], FC["drive"]
SCOPE = f.scope_of(SPEC)
HORIZON = SPEC["contract"]["horizon_s"]
# The same controls on a small campaign: the accepted physics with coarser authored sampling (16 steps per horizon).
SMALL = copy.deepcopy(SPEC)
SMALL["campaign"].update(layered_order=8, homogeneous_order=4, steps_per_horizon=16, committed_steps=[4, 12, 16])
DT = f.step_s(SMALL)
SETTINGS = f.settings(SMALL, CTX)
UNISSUED = "not issued"
FIX = {}


def setUpModule():
    with threadpool_limits(limits=1, user_api="blas"):
        FIX.update(f.fixtures(SMALL, CTX))


class Limited(unittest.TestCase):
    def setUp(self):
        lease = threadpool_limits(limits=1, user_api="blas")
        self.addCleanup(lease.restore_original_limits)


class CaseTests(unittest.TestCase):
    def test_case_refuses_unadmitted_inputs(self):
        for name, path, value in f.CASE_MUTATIONS:
            with self.subTest(name), self.assertRaises(ValueError):
                f.validate_case(tm.mutated(SPEC, path, value))

    def test_contract_is_the_accepted_finite_strain_scope(self):
        rep = CTX["fs"]["representation"]
        self.assertEqual(SPEC["contract"]["stretch_window"], rep["stretch_window"])
        self.assertEqual(SPEC["contract"]["temperature_window_k"], rep["temperature_window_k"])
        self.assertEqual(HORIZON, CTX["fs"]["drive"]["duration_s"])
        self.assertIn(CTX["retained"]["relative_tolerance"], SPEC["campaign"]["relative_tolerances"])


class EnvelopeTests(Limited):
    def test_linear_layer_closed_form_threshold_and_current_geometry(self):
        base, thermal, key = f.single_layer(CTX, f.ca.analytic_layer(), 2)
        zero = np.zeros(base.size)
        lam, g = Fraction(5, 4), f.DERIVED_ROUNDING
        b = f.envelope_balance(base, w.OFF, DRIVE, 1.25, zero)          # the formula at an authored floor: no state
        self.assertEqual(b.yield_force, 0)                                 # no cohesion, friction or overburden
        self.assertEqual(b.coefficient, 4*g*Fraction(10**19)*1000/(Fraction(10**5)*lam*lam))
        # The retained stage at the current geometry: e = (A + 1/(2 eta)) s, R = 2 (h0/lam) s and e = v/(w0 lam).
        s = f.fs.stage(base, f.fs.coefficients(base), w.OFF, 1.25, np.asarray(thermal.steady_k), zero, DRIVE, (1., 1.))
        k = 2*1000/(1e5*(1e-20+1/(2e19)))
        exact = DRIVE.force_n_m/(DRIVE.drag_pa_s+k/1.25**2)
        self.assertLess(abs(s["velocity_m_s"]-exact)/exact, 1e-8)
        self.assertLessEqual(Fraction(s["force"]), b.coefficient*Fraction(s["velocity_m_s"]))
        # The exact threshold through the public route, from the layer's own issued reference state.
        origin = f.reference_state(f.Evolution(base, thermal, w.OFF, DRIVE, key, zero, **SETTINGS))
        env = f.prepare(base, thermal, w.OFF, DRIVE, key, origin, **SCOPE)
        self.assertEqual(env.balance, f.envelope_balance(base, w.OFF, DRIVE, 1., zero))
        self.assertEqual(env.balance.coefficient, 4*g*Fraction(10**19)*1000/Fraction(10**5))
        edge = env.balance.coefficient/(env.balance.drag+env.balance.coefficient)
        kw = dict(duration_s=2.5e13, displacement_limit_m=1e4)
        equality = f.admit(env, base, thermal, w.OFF, DRIVE, origin, relative_tolerance=edge, **kw)
        self.assertEqual(equality["status"], f.CERTIFIED)
        tighter = f.admit(env, base, thermal, w.OFF, DRIVE, origin, relative_tolerance=edge-Fraction(1, 10**30), **kw)
        self.assertEqual(tighter["status"], f.NOT_CERTIFIED)
        self.assertNotIn("speed_error_bound_m_s", tighter)

    def test_weakened_pressure_state_uses_the_represented_overburden(self):
        base, thermal, h = tm.homogeneous_setup(FC, 2)
        self.assertEqual((LAW.start, LAW.end, LAW.cohesion_factor, LAW.friction_factor), (1., 3., .25, .25))
        kappa = np.full(base.size, 2.)
        b = f.envelope_balance(base, LAW, DRIVE, 1.25, kappa)
        lam, g, factor = Fraction(5, 4), f.DERIVED_ROUNDING, Fraction(5, 8)          # 1 - 0.75 (2 - 1)/(3 - 1)
        phi = Fraction(h["layer"]["friction_rad"])*factor
        loads = sum(Fraction(q)*Fraction(p) for q, p in zip(base.weight, base.reference_pa))
        self.assertEqual(b.yield_force, 2*g*(Fraction(10**4)*Fraction(2*10**7)*factor+loads*phi/lam)/lam)
        self.assertEqual(b.coefficient, 4*g*Fraction(10**4)*Fraction(10**21)/(Fraction(10**5)*lam*lam))
        weaker = f.envelope_balance(base, LAW, DRIVE, 1.25, np.full(base.size, 3.))
        reference = f.envelope_balance(base, LAW, DRIVE, 1., kappa)
        self.assertLess(weaker.yield_force, b.yield_force)
        self.assertLess(b.yield_force, reference.yield_force)
        self.assertLess(b.coefficient, reference.coefficient)
        for history in (kappa, np.full(base.size, 3.)):             # at and above the floor, any later temperature
            s = f.fs.stage(base, f.fs.coefficients(base), LAW, 1.25, np.asarray(thermal.steady_k)+40., history, DRIVE,
                           (1., 1.))
            self.assertLessEqual(Fraction(s["force"]), b.yield_force+b.coefficient*Fraction(s["velocity_m_s"]))

    def test_realistic_layered_column_is_genuinely_uncertifiable(self):
        fx = FIX["layered"]
        args = (fx["base"], fx["thermal"], LAW, DRIVE)
        env = f.prepare(*args, fx["key"], fx["states"][0], **SCOPE)
        self.assertGreater(env.balance.yield_force, env.balance.force)
        out = f.admit(env, *args, fx["states"][0], duration_s=4*DT, relative_tolerance=1-2.**-20,
                      displacement_limit_m=1e9)
        self.assertEqual(out["status"], f.NOT_CERTIFIED)
        self.assertEqual(out["speed_lower_bound_m_s"], 0.)
        self.assertNotIn("speed_error_bound_m_s", out)
        self.assertFalse(out["generated_separation_authorised"])

    def test_old_fixed_column_guard_is_unchanged(self):
        fx = FIX["layered"]
        kappa = fx["states"][0].kappa
        old = f.ca.prepare(fx["base"], LAW, kappa, DRIVE)
        with self.assertRaisesRegex(ValueError, "small-strain"):
            f.ca.admit(old, fx["base"], LAW, kappa, DRIVE, duration_s=4*DT, used_strain=0., relative_tolerance=.01,
                       displacement_limit_m=1e4)


class WindowTests(Limited):
    def setUp(self):
        super().setUp()
        self.fx = FIX["homogeneous"]
        self.args = (self.fx["base"], self.fx["thermal"], LAW, DRIVE)
        self.origin, self.start, self.later = (self.fx["states"][n] for n in (0, 4, 12))
        self.env = f.prepare(*self.args, self.fx["key"], self.start, **SCOPE)
        self.window = dict(duration_s=8*DT, relative_tolerance=.1, displacement_limit_m=1e4)

    def admit(self, state, env=None, **kw):
        return f.admit(self.env if env is None else env, *self.args, state, **dict(self.window, **kw))

    def test_certificate_bounds_the_numerical_continuation(self):
        out = self.admit(self.start)
        self.assertEqual(out["status"], f.CERTIFIED)
        seen = f.observed(self.fx, 4, 12, DT)
        checks, _ = f.compare(self.env, out, seen, self.start, SPEC["policy"]["numerical_allowance_relative"])
        self.assertTrue(all(checks.values()), checks)
        self.assertGreater(math.log(seen["stretch_end"]), .05)                # beyond the old small-strain guard
        self.assertGreater(float(np.abs(seen["theta_end"]-self.start.theta).max()), 0.)     # temperatures evolve
        self.assertEqual(self.admit(self.start, relative_tolerance=.01)["status"], f.NOT_CERTIFIED)

    def test_repeated_admission_carries_floors_horizon_and_evolution(self):
        remaining = HORIZON-self.later.elapsed_s
        again = self.admit(self.later, duration_s=remaining)
        self.assertEqual(again["status"], f.CERTIFIED)
        self.assertEqual((again["window_start_s"], again["window_end_s"]), (self.later.elapsed_s, HORIZON))
        with self.assertRaisesRegex(ValueError, "cumulative horizon"):
            self.admit(self.later, duration_s=remaining+DT)
        with self.assertRaisesRegex(ValueError, "below the prepared floor|stretch lies outside"):
            self.admit(self.origin, duration_s=DT)                    # an earlier state of the same evolution
        renewed = f.prepare(*self.args, self.fx["key"], self.later, **SCOPE)
        self.assertIs(renewed.evolution, self.env.evolution)
        self.assertLess(renewed.balance.yield_force, self.env.balance.yield_force)
        self.assertLess(renewed.balance.coefficient, self.env.balance.coefficient)

    def test_full_horizon_from_the_reference_is_refused_in_exact_arithmetic(self):
        # float(5e22) and float(1.4) both round down: the represented drag-only reach passes the represented ceiling.
        reach = 1+Fraction(DRIVE.force_n_m)/Fraction(DRIVE.drag_pa_s)*Fraction(HORIZON)/Fraction(DRIVE.width_m)
        self.assertTrue(0 < reach-Fraction(1.4) < Fraction(1, 10**15))
        whole = f.prepare(*self.args, self.fx["key"], self.origin, **SCOPE)
        with self.assertRaisesRegex(ValueError, "drag-only reach"):
            self.admit(self.origin, env=whole, duration_s=HORIZON)

    def test_changed_identity_and_scope_refuse_without_mutation(self):
        before = copy.deepcopy(self.fx["runs"])
        baseline = self.admit(self.start)
        base, thermal = self.fx["base"], self.fx["thermal"]
        changed = "changed preparation, support, law or drive"
        for name, call in (
                ("law", lambda: f.admit(self.env, base, thermal, w.WeakeningLaw(1., 3., .5, .25), DRIVE, self.start,
                                        **self.window)),
                ("force", lambda: f.admit(self.env, base, thermal, LAW, motion.Drive(3e13, DRIVE.drag_pa_s,
                                                                                    DRIVE.width_m), self.start,
                                          **self.window)),
                ("width", lambda: f.admit(self.env, base, thermal, LAW, motion.Drive(DRIVE.force_n_m, DRIVE.drag_pa_s,
                                                                                    2e5), self.start, **self.window)),
                ("copy", lambda: f.admit(self.env, dataclasses.replace(base), thermal, LAW, DRIVE, self.start,
                                         **self.window))):
            with self.subTest(name), self.assertRaisesRegex(ValueError, changed):
                call()
        # Scope refusals of genuine issued states: an earlier state, or a later one outside a tighter admitted window.
        steady = np.asarray(thermal.steady_k)
        warmest = float((steady+self.start.theta).max())
        self.assertGreater(float((steady+self.later.theta).max()), warmest)          # the belt heats in between
        self.assertGreater(self.later.stretch, 1.2)
        capped = f.prepare(*self.args, self.fx["key"], self.start,
                           window=dict(SCOPE["window"], temperature_k=[273., warmest]), horizon_s=HORIZON)
        tight = f.prepare(*self.args, self.fx["key"], self.start, window=dict(SCOPE["window"], stretch=[.6, 1.2]),
                          horizon_s=HORIZON)
        for name, env, state, reason in (
                ("history", None, self.origin, "below the prepared floor|stretch lies outside"),
                ("temperature", capped, self.later, "temperature"),
                ("stretch", tight, self.later, "stretch lies outside")):
            with self.subTest(name), self.assertRaisesRegex(ValueError, reason):
                self.admit(state, env=env, duration_s=DT)
        with self.assertRaisesRegex(ValueError, "positive extension"):
            f.prepare(base, thermal, LAW, motion.Drive(-DRIVE.force_n_m, DRIVE.drag_pa_s, DRIVE.width_m),
                      self.fx["key"], self.origin, **SCOPE)
        stretched = f.fs.column_at(base, f.fs.coefficients(base), self.start.stretch, steady+self.start.theta)
        with self.assertRaisesRegex(ValueError, "thermal support"):
            f.prepare(stretched, thermal, LAW, DRIVE, self.fx["key"], self.start, **SCOPE)
        brief = dataclasses.replace(self.fx["evolution"], window=dict(SCOPE["window"], stretch=[.6, 1.01]))
        with self.assertRaisesRegex(ValueError, "complete retained"):
            f.evolved(brief, 4)                                        # the run leaves its window: nothing issued
        for x in (0., math.nan, True, "1e13"):
            with self.subTest(duration=x), self.assertRaisesRegex(ValueError, "duration"):
                self.admit(self.start, duration_s=x)
        with self.assertRaisesRegex(ValueError, "relative tolerance"):
            self.admit(self.start, relative_tolerance=1.)
        self.assertTrue(f.unchanged(before, self.fx["runs"]))
        self.assertEqual(self.admit(self.start), baseline)
        self.assertFalse(any(s.kappa.flags.writeable or s.theta.flags.writeable for s in self.fx["states"].values()))
        self.assertFalse(self.env.history_floor.flags.writeable)

    def test_cancel_and_deadline_publish_nothing(self):
        cancelled = threading.Event()
        cancelled.set()
        with self.assertRaises(CancelledError):
            f.prepare(*self.args, self.fx["key"], self.start, **SCOPE, cancel=cancelled)
        with self.assertRaises(CancelledError):
            self.admit(self.start, cancel=cancelled)
        with self.assertRaises(RuntimeError):
            self.admit(self.start, deadline=time.perf_counter()-1.)
        with self.assertRaises(RuntimeError):
            f.evolved(self.fx["evolution"], 4, deadline=time.perf_counter()-1.)

    def test_reused_envelope_matches_cold_construction(self):
        cold = f.prepare(*self.args, self.fx["key"], self.start, **SCOPE)
        self.assertIsNot(cold, self.env)
        self.assertEqual(cold.balance, self.env.balance)
        self.assertEqual(self.admit(self.later, env=cold, duration_s=4*DT), self.admit(self.later, duration_s=4*DT))


class ProvenanceTests(Limited):
    """Only this module issues states, from its own run of one evolution, and envelopes: the review regressions."""

    def setUp(self):
        super().setUp()
        self.fx = FIX["homogeneous"]
        self.args = (self.fx["base"], self.fx["thermal"], LAW, DRIVE)
        self.origin, self.start, self.later = (self.fx["states"][n] for n in (0, 4, 12))
        self.env = f.prepare(*self.args, self.fx["key"], self.start, **SCOPE)
        self.remaining = HORIZON-self.later.elapsed_s

    def admit(self, state, env=None, **kw):
        kw = dict(dict(duration_s=DT, relative_tolerance=.1, displacement_limit_m=1e4), **kw)
        return f.admit(self.env if env is None else env, *self.args, state, **kw)

    def rolled_back(self, state):
        """The reviewed reproduction: a clock half-way between the true one and the earliest reachable time."""
        earliest = f.earliest(state, DRIVE)
        changed = dataclasses.replace(state, elapsed_s=(state.elapsed_s+earliest)/2)
        self.assertTrue(earliest < changed.elapsed_s < state.elapsed_s)    # the reachability inequality has slack
        return changed

    def test_partial_clock_rollback_is_refused(self):
        changed = self.rolled_back(self.later)
        self.assertIsNone(changed.evolution)                              # replace() never copies the issue mark
        with self.assertRaisesRegex(ValueError, UNISSUED):
            f.admit(self.env, *self.args, changed, duration_s=HORIZON-changed.elapsed_s, relative_tolerance=.1,
                    displacement_limit_m=1e4)
        built = f.State(self.later.stretch, changed.elapsed_s, self.later.width_m, self.later.thickness_m,
                        self.later.kappa, self.later.theta, self.later.reference)
        with self.assertRaisesRegex(ValueError, UNISSUED):
            self.admit(built, duration_s=HORIZON-changed.elapsed_s)
        # The issued state certifies only what remains of its own cumulative horizon.
        again = self.admit(self.later, duration_s=self.remaining)
        self.assertEqual((again["status"], again["window_end_s"]), (f.CERTIFIED, HORIZON))
        with self.assertRaisesRegex(ValueError, "cumulative horizon"):
            self.admit(self.later, duration_s=HORIZON-changed.elapsed_s)

    def test_renewed_envelope_from_an_edited_state_is_refused(self):
        changed = self.rolled_back(self.later)
        with self.assertRaisesRegex(ValueError, UNISSUED):
            f.prepare(*self.args, self.fx["key"], changed, **SCOPE)
        e, free = self.env, f.d.Balance(DRIVE.force_n_m, DRIVE.drag_pa_s, 0, 0, 1)
        for name, forged in (
                ("horizon", dataclasses.replace(e, horizon_s=2*HORIZON)),
                ("floors", dataclasses.replace(e, stretch_floor=1., elapsed_floor_s=0.)),
                ("bound", dataclasses.replace(e, balance=free)),
                ("built", f.FiniteEnvelope(e.base, e.thermal, e.law, e.drive, e.window, e.horizon_s, e.stretch_floor,
                                           e.elapsed_floor_s, e.history_floor, free))):
            with self.subTest(name), self.assertRaisesRegex(ValueError, "envelope issued by prepare"):
                self.admit(self.later, env=forged)

    def test_relabelled_reference_or_history_is_refused(self):
        base, layer = self.fx["base"], self.fx["key"][0][0]
        other, other_thermal, other_key = f.single_layer(CTX, dict(layer, cohesion_pa=layer["cohesion_pa"]/2),
                                                         self.fx["key"][1])
        for name, state in (
                ("reference", dataclasses.replace(self.later, reference=other.fingerprint)),
                ("history", dataclasses.replace(self.start, kappa=self.later.kappa)),
                ("temperature", dataclasses.replace(self.later, theta=self.start.theta)),
                ("reference_geometry", dataclasses.replace(self.later, stretch=1., width_m=DRIVE.width_m*1.,
                                                           thickness_m=base.thickness_m/1.))):
            with self.subTest(name), self.assertRaisesRegex(ValueError, UNISSUED):
                self.admit(state)
        # Genuine states of other evolutions stay theirs, even inside every floor of this evolution's envelope.
        whole = f.prepare(*self.args, self.fx["key"], self.origin, **SCOPE)
        weaker = f.reference_state(dataclasses.replace(self.fx["evolution"], kappa0=np.full(base.size, 3.)))
        self.assertTrue(np.all(weaker.kappa >= whole.history_floor))
        with self.assertRaisesRegex(ValueError, "different evolution"):
            self.admit(weaker, env=whole)
        self.assertIs(f.prepare(*self.args, self.fx["key"], weaker, **SCOPE).evolution, weaker.evolution)
        foreign = f.reference_state(f.Evolution(other, other_thermal, LAW, DRIVE, other_key, self.origin.kappa,
                                                **SETTINGS))
        with self.assertRaisesRegex(ValueError, "different preparation"):
            self.admit(foreign, env=whole)

    def test_raw_outputs_are_not_evolution_evidence(self):
        out = self.fx["runs"][12]
        with self.assertRaisesRegex(ValueError, "committed finite-strain state"):
            self.admit(out)
        with self.assertRaisesRegex(ValueError, "committed finite-strain state"):
            f.prepare(*self.args, self.fx["key"], out, **SCOPE)
        built = f.State(out["stretch"], out["elapsed_s"], out["width_m"], out["thickness_m"], out["kappa"],
                        out["theta"], self.fx["base"].fingerprint)       # every value from a genuine retained run
        with self.assertRaisesRegex(ValueError, UNISSUED):
            self.admit(built)
        with self.assertRaisesRegex(ValueError, UNISSUED):
            f.prepare(*self.args, self.fx["key"], built, **SCOPE)

    def test_evolution_owns_immutable_thermal_modes(self):
        ev = self.fx["evolution"]
        writable = dataclasses.replace(ev.modes, source_modal=ev.modes.source_modal.copy())
        writable.source_modal[:] = 0.
        with self.assertRaises(TypeError):
            f.Evolution(ev.base, ev.thermal, ev.law, ev.drive, ev.key, ev.kappa0,
                        **SETTINGS, modes=writable)
        # replace() refuses the init=False field: ValueError on Python 3.12, TypeError on 3.13.
        with self.assertRaises((TypeError, ValueError)):
            dataclasses.replace(ev, modes=writable)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            ev.modes = writable
        self.assertIsNot(ev.modes, writable)
        for name in ("lam", "to_modal", "source_modal", "from_modal", "e", "p1", "p2", "p3"):
            values = getattr(ev.modes, name)
            with self.subTest(name), self.assertRaises(ValueError):
                values.flat[0] = 0.
            with self.subTest(name=name+"_write_flag"), self.assertRaises(ValueError):
                values.setflags(write=True)
        self.assertIs(self.later.evolution.modes, ev.modes)

    def test_valid_repeated_admission_and_reuse(self):
        first = self.admit(self.later, duration_s=self.remaining)
        self.assertEqual(first["status"], f.CERTIFIED)
        self.assertEqual(self.admit(self.later, duration_s=self.remaining), first)       # the envelope is reused
        self.assertEqual(self.admit(copy.copy(self.later), duration_s=self.remaining), first)    # the same state
        renewed = f.prepare(*self.args, self.fx["key"], self.later, **SCOPE)
        self.assertIs(renewed.evolution, self.fx["evolution"])
        self.assertEqual(self.admit(self.later, env=renewed, duration_s=self.remaining)["status"], f.CERTIFIED)
        # The same evolution run again issues a new state at the same cumulative clock; the carried envelope admits it.
        _, again = f.evolved(self.fx["evolution"], 12)
        self.assertIsNot(again, self.later)
        self.assertEqual(again.elapsed_s, self.later.elapsed_s)
        out = self.admit(again, duration_s=self.remaining)
        self.assertEqual((out["status"], out["window_end_s"]), (f.CERTIFIED, HORIZON))


class ControlTests(Limited):
    def test_bounded_controls_pass_on_a_small_campaign(self):
        for name, control in f.CONTROLS:
            with self.subTest(name):
                out = control(SMALL, CTX, FIX)
                self.assertTrue(out["passed"], {k: v for k, v in out["checks"].items() if not v})


if __name__ == "__main__":
    unittest.main()
