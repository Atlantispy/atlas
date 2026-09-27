"""Focused guards for I01 force-driven motion with thermal/weakening feedback; no native import.
SPDX-License-Identifier: AGPL-3.0-only
"""
import dataclasses
import math
from pathlib import Path
import sys
import unittest

import numpy as np
from threadpoolctl import threadpool_limits

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"tools"))
import check_i01_thermomechanical_motion as t

heat, motion, w = t.heat, t.motion, t.weakening
SPEC, CTX = t.load_case()
LAW, DRIVE = CTX["law"], CTX["drive"]
REP, POLICY = SPEC["representation"], SPEC["policy"]
DURATION = SPEC["drive"]["duration_s"]
REST = motion.Drive(0., DRIVE.drag_pa_s, DRIVE.width_m)
SQUEEZE = motion.Drive(-DRIVE.force_n_m, DRIVE.drag_pa_s, DRIVE.width_m)


class Base(unittest.TestCase):
    def setUp(self):
        lease = threadpool_limits(limits=1, user_api="blas")
        self.addCleanup(lease.restore_original_limits)
        self.base, self.thermal, self.key = t.layered(CTX, 8)
        self.kappa0 = w.initial_history(self.base, CTX["weak"])
        self.reference = heat.ArrheniusUpdate.of(self.base).at(np.array(self.thermal.steady_k))

    def run_case(self, steps=4, **kw):
        kw.setdefault("duration_s", DURATION)
        kw.setdefault("fractions", (1., 1.))
        kw.setdefault("strain_bound", REP["max_axial_strain"])
        kw.setdefault("temperature_step_k", REP["max_temperature_step_k"])
        return t.evolve(kw.pop("base", self.base), kw.pop("thermal", self.thermal), LAW, kw.pop("kappa0", self.kappa0),
                        kw.pop("drive", DRIVE), steps=steps, policy=POLICY, **kw)

    def assert_same_prefix(self, a, b):
        np.testing.assert_array_equal(a["theta"], b["theta"])
        np.testing.assert_array_equal(a["kappa"], b["kappa"])
        self.assertEqual((a["accepted_steps"], a["strain"], a["displacement_m"], a["velocity_end_m_s"]),
                         (b["accepted_steps"], b["strain"], b["displacement_m"], b["velocity_end_m_s"]))
        self.assertEqual(a["accounts"], b["accounts"])


class StageTests(Base):
    def test_stage_is_the_motion_root_with_column_heat_counted_once(self):
        root = motion.solve(self.reference, LAW, self.kappa0, DRIVE)
        s = t.stage(self.reference, LAW, self.kappa0, DRIVE, (1., 1.))
        self.assertEqual((s["rate"], s["velocity_m_s"], s["force"]), (root["rate"], root["velocity_m_s"], root["force"]))
        self.assertTrue(s["same_stress"])
        self.assertLessEqual(s["force_relative"], motion.FORCE_TOL)
        self.assertLess(abs(s["rate"]*DRIVE.width_m/s["velocity_m_s"]-1), 1e-14)          # a = v/width
        column_heat = math.fsum(s["source"])                  # W/m^2: widths already inside each source
        self.assertLess(abs(column_heat-s["work"])/s["work"], 1e-10)
        self.assertLess(abs(DRIVE.width_m*column_heat-(s["drive_power_w_m"]-s["drag_power_w_m"]))
                        / s["drive_power_w_m"], 2e-10)
        self.assertLess(s["power_relative"], 2e-10)

    def test_drag_dissipation_never_heats_the_column(self):
        rate = 1e-15
        column = w.respond(self.reference, LAW, self.kappa0, rate)
        a, b = (t.stage(self.reference, LAW, self.kappa0,
                        motion.Drive(column["force"]+drag*DRIVE.width_m*rate, drag, DRIVE.width_m), (1., 1.))
                for drag in (5e22, 5e23))
        self.assertLess(w.relative_change(a["rate"], b["rate"]), 1e-8)
        np.testing.assert_allclose(a["source"], b["source"], rtol=1e-6, atol=0.)
        self.assertGreater(b["drag_power_w_m"], 9*a["drag_power_w_m"])
        for s in (a, b):
            self.assertLess(abs(DRIVE.width_m*math.fsum(s["source"])-(s["drive_power_w_m"]-s["drag_power_w_m"]))
                            / s["drive_power_w_m"], 2e-10)


class EvolutionTests(Base):
    def test_no_heating_and_no_feedback_reproduce_retained_motion(self):
        reviewed = motion.evolve(self.reference, LAW, self.kappa0, DRIVE, duration_s=DURATION, steps=4)
        cold, frozen = self.run_case(fractions=(0., 0.)), self.run_case(feedback=False)
        self.assertFalse(np.any(cold["theta"]))
        for out in (cold, frozen):
            np.testing.assert_array_equal(out["kappa"], reviewed["kappa"])
            self.assertEqual((out["strain"], out["velocity_end_m_s"]), (reviewed["strain"], reviewed["velocity_end_m_s"]))
            for ours, theirs in (("drive_work_j_m", "drive"), ("drag_work_j_m", "drag"),
                                 ("column_creep_work_j_m", "creep"), ("column_plastic_work_j_m", "plastic")):
                self.assertEqual(out["accounts"][ours], reviewed["energy_j_m"][theirs])
        self.assertGreater(float(frozen["theta"].max()), 0.)
        self.assertLess(frozen["accounts"]["energy_relative"], 1e-10)

    def test_feedback_speeds_motion_with_closed_accounts(self):
        on, off = self.run_case(inputs=self.key), self.run_case(feedback=False)
        self.assertEqual(on["velocity_start_m_s"], off["velocity_start_m_s"])
        self.assertGreater(on["velocity_end_m_s"], off["velocity_end_m_s"])
        for out in (on, off):
            acc = out["accounts"]
            self.assertEqual((out["status"], out["restress_mismatches"]), ("COMPLETE", 0))
            self.assertLess(max(acc["motion_work_relative"], acc["drag_excluded_relative"]), 2e-10)
            self.assertLess(acc["drive_displacement_relative"], 1e-12)
            self.assertLess(max(acc["work_to_heat_relative"], acc["energy_relative"]), 1e-10)
            self.assertGreater(acc["drag_work_j_m"], 0.)
            self.assertGreaterEqual(min(out["min_source_w_m2"], out["min_dissipation_w_m"]), 0.)
        self.assertLess(on["reference"]["balance_relative"], 1e-9)

    def test_warm_guesses_do_not_change_the_answer(self):
        warm = self.run_case()
        cold = self.run_case(warm_start=False, provider=lambda: heat.prepare_propagator(self.thermal, DURATION/4))
        for key in ("velocity_end_m_s", "strain"):
            self.assertLess(w.relative_change(warm[key], cold[key]), 1e-8)
        np.testing.assert_allclose(warm["theta"], cold["theta"], rtol=0., atol=1e-8)
        np.testing.assert_allclose(warm["kappa"], cold["kappa"], rtol=0., atol=1e-9)

    def test_rest_conducts_an_existing_departure_only(self):
        bump = 2.*np.sin(math.pi*np.asarray(self.base.depth_m)/self.thermal.thickness_m)
        out = self.run_case(drive=REST, theta0=bump)
        acc = out["accounts"]
        self.assertEqual((out["strain"], out["displacement_m"], out["velocity_end_m_s"]), (0., 0., 0.))
        np.testing.assert_array_equal(out["kappa"], self.kappa0)
        for key in ("drive_work_j_m", "drag_work_j_m", "column_work_j_m2", "heat_j_m2", "stored_j_m2"):
            self.assertEqual(acc[key], 0.)
        self.assertLess(acc["thermal_change_j_m2"], 0.)
        self.assertLess(float(np.abs(out["theta"]).max()), float(np.abs(bump).max()))
        self.assertLess(acc["energy_relative"], 1e-10)
        self.assertFalse(np.any(self.run_case(drive=REST)["theta"]))

    def test_compression_dissipates_nonnegatively(self):
        out = self.run_case(drive=SQUEEZE)
        self.assertEqual(out["status"], "COMPLETE")
        self.assertLess(max(out["strain"], out["velocity_end_m_s"]), 0.)
        self.assertGreater(out["accounts"]["drive_work_j_m"], 0.)
        self.assertGreaterEqual(min(out["min_source_w_m2"], out["min_dissipation_w_m"]), 0.)
        self.assertGreater(float(out["theta"].max()), 0.)
        self.assertLess(out["accounts"]["energy_relative"], 1e-10)

    def test_homogeneous_force_oracle_second_order(self):
        base, thermal, h = t.homogeneous_setup(CTX, 4)
        layer, k0 = h["layer"], float(h["initial_history"])
        oracle = t.force_oracle(layer, h["thermal"], LAW, DRIVE, k0, DURATION, (1., 1.))
        self.assertTrue(oracle["always_yielding"])
        errors = []
        for n in (8, 16, 32):
            out = self.run_case(n, base=base, thermal=thermal, kappa0=np.full(base.size, k0))
            errors.append((w.relative_change(float(out["theta"][0]), oracle["temperature_rise"]),
                           w.relative_change(float(out["kappa"][0])-k0, oracle["history_gain"])))
            self.assertEqual(out["accounts"]["surface_loss_j_m2"], 0.)
        for series in zip(*errors):
            for o in w.order(list(series)):
                self.assertTrue(1.8 <= o <= 2.2, o)
        start = t.scalar_balance(layer, LAW, DRIVE, layer["temperature_k"][0], k0)
        self.assertLess(w.relative_change(out["velocity_start_m_s"], start["velocity_m_s"]), 1e-8)


class RefusalTests(Base):
    def test_strain_temperature_and_deadline_refusals_are_atomic(self):
        first = self.run_case(1, duration_s=1e13)
        strained = self.run_case(4, duration_s=4e13, strain_bound=1.1*abs(first["strain"]))
        self.assertEqual(strained["status"], "REFUSED_SMALL_STRAIN")
        self.assert_same_prefix(strained, first)
        hot = self.run_case(2, temperature_step_k=1e-3)
        self.assertEqual((hot["status"], hot["accepted_steps"]), ("REFUSED_TEMPERATURE_STEP", 0))
        self.assertFalse(np.any(hot["theta"]))
        self.assertEqual(hot["accounts"]["heat_j_m2"], 0.)
        probe = t.CountdownDeadline(10**9)
        self.run_case(8, deadline=probe)
        cut = self.run_case(8, deadline=t.CountdownDeadline((10**9-probe.remaining)//2))
        k = cut["accepted_steps"]
        self.assertEqual(cut["status"], "REFUSED_DEADLINE")
        self.assertTrue(0 < k < 8, k)
        self.assert_same_prefix(cut, self.run_case(k, duration_s=DURATION/8*k))
        with self.assertRaises(RuntimeError):
            self.run_case(2, deadline=0.)

    def test_direct_api_guards(self):
        other, _ = w.base_prepare(CTX["weak"], order=8, offset_k=1.)
        stale = [dict(layer) for layer in self.key[0]]
        stale[0]["temperature_k"] = [x+1e-9 for x in stale[0]["temperature_k"]]
        thick = [layer["thickness_m"] for layer in CTX["weak"]["layers"]]
        foreign = heat.prepare_thermal(*heat.geometry(thick[::-1], 8), thick[::-1], CTX["heat"]["thermal_layers"],
                                       [layer["density_kg_m3"] for layer in CTX["weak"]["layers"]],
                                       CTX["heat"]["boundaries"], mechanical_fingerprint=self.base.fingerprint)
        cases = dict(
            no_steps=dict(steps=0), too_many_steps=dict(steps=257), float_steps=dict(steps=2.),
            strain_allowance=dict(strain_bound=.051), guard=dict(temperature_step_k=6.),
            untyped_drive=dict(drive=(2e13, 5e22, 1e5)), amplified_heat=dict(fractions=(1.5, 1.)),
            theta_shape=dict(theta0=np.zeros(3)), nonpositive_temperature=dict(theta0=-np.asarray(self.thermal.steady_k)),
            negative_history=dict(kappa0=-self.kappa0), warm_flag=dict(warm_start=1), feedback_flag=dict(feedback=0),
            other_column=dict(base=other), temperature_prepared_base=dict(base=self.reference),
            stale_inputs=dict(inputs=(stale, *self.key[1:])), foreign_support=dict(thermal=foreign),
            replaced_support=dict(thermal=dataclasses.replace(self.thermal, depth_m=w.frozen(self.thermal.depth_m+1.))),
            propagator_step=dict(propagator=heat.prepare_propagator(self.thermal, DURATION)),
            provider_step=dict(provider=lambda: heat.prepare_propagator(self.thermal, DURATION)))
        for name, kw in cases.items():
            with self.subTest(name), self.assertRaises(ValueError):
                self.run_case(**dict(dict(steps=2), **kw))
        with self.assertRaises(ValueError):
            motion.Drive(DRIVE.force_n_m, 0., DRIVE.width_m)
        tiny, tiny_thermal = t.compressive_column(CTX, 1e-3)
        with self.assertRaisesRegex(ValueError, "not monotone"):
            self.run_case(2, base=tiny, thermal=tiny_thermal, kappa0=np.zeros(tiny.size), drive=SQUEEZE)

    def test_case_refuses_unadmitted_inputs_and_confirms_the_drag_bound(self):
        for name, path, value in t.CASE_MUTATIONS:
            with self.subTest(name), self.assertRaises(ValueError):
                t.validate_case(t.mutated(SPEC, path, value))
        case = motion.load_case()
        bound = abs(case["drive_n_m"])/case["drag_pa_s"]/case["width_m"]
        self.assertLess(abs(bound-4e-15)/4e-15, 1e-12)
        self.assertLess(abs(bound*DURATION-.04), 1e-15)


class EvidenceTests(unittest.TestCase):
    def test_accepted_receipts_and_retained_sources_match(self):
        match = t.evidence_match(t.bindings())
        for group, values in match.items():
            for name, ok in values.items():
                with self.subTest(group=group, name=name):
                    self.assertTrue(ok)


if __name__ == "__main__":
    unittest.main()
