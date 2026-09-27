"""Focused guards for the I01 material-following finite-strain column; no native import.
SPDX-License-Identifier: AGPL-3.0-only
"""
import dataclasses
import math
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

import numpy as np
from scipy.linalg import expm
from threadpoolctl import threadpool_limits

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"tools"))
import check_i01_finite_strain as f

tm, heat, motion, w = f.tm, f.heat, f.motion, f.weakening
SPEC, CTX = f.load_case()
LAW, DRIVE = CTX["law"], CTX["drive"]
REP, POLICY = SPEC["representation"], SPEC["policy"]
DURATION = SPEC["drive"]["duration_s"]
WINDOW = f.declared_window(SPEC)
REST = motion.Drive(0., DRIVE.drag_pa_s, DRIVE.width_m)
SQUEEZE = motion.Drive(-DRIVE.force_n_m, DRIVE.drag_pa_s, DRIVE.width_m)
SMALL = CTX["heat"]["representation"]["max_axial_strain"]          # the retained small-strain allowance, 0.05


class Base(unittest.TestCase):
    def setUp(self):
        lease = threadpool_limits(limits=1, user_api="blas")
        self.addCleanup(lease.restore_original_limits)
        self.base, self.thermal, self.key, self.rebuild = f.layered(CTX, 8)
        self.kappa0 = w.initial_history(self.base, CTX["weak"])
        self.modes = f.eigensystem(self.thermal)
        self.steady = np.array(self.thermal.steady_k)

    def call(self, steps=16, **kw):
        if "thermal" not in kw and "rebuild" not in kw and kw.get("conduction", True):
            kw.setdefault("modes", self.modes)
        for name, value in (("duration_s", DURATION), ("window", WINDOW), ("fractions", (1., 1.)),
                            ("temperature_step_k", REP["max_temperature_step_k"])):
            kw.setdefault(name, value)
        return f.evolve(kw.pop("base", self.base), kw.pop("thermal", self.thermal), LAW, kw.pop("kappa0", self.kappa0),
                        kw.pop("drive", DRIVE), steps=steps, policy=POLICY, **kw)

    def homogeneous(self, order=4):
        base, thermal, h = tm.homogeneous_setup(CTX, order)
        return base, thermal, h, np.full(base.size, float(h["initial_history"]))


class CaseTests(unittest.TestCase):
    def test_case_refuses_unadmitted_inputs(self):
        for name, path, value in f.CASE_MUTATIONS:
            with self.subTest(name), self.assertRaises(ValueError):
                f.validate_case(f.mutated(SPEC, path, value))

    def test_drag_bound_fills_exactly_the_frozen_window(self):
        bound = abs(DRIVE.force_n_m)/DRIVE.drag_pa_s/DRIVE.width_m*DURATION      # |lam - 1| <= |F| t/(D w0)
        self.assertLess(abs(bound-.4), 1e-12)
        self.assertEqual(tuple(REP["stretch_window"]), f.STRETCH_CEILING)
        ends = CTX["heat"]["boundaries"]
        self.assertEqual(tuple(REP["temperature_window_k"]), f.TEMPERATURE_CEILING_K)
        self.assertEqual((ends["top"]["value_k"], ends["bottom"]["value_k"]), f.TEMPERATURE_CEILING_K)


class DerivationTests(Base):
    def test_whole_strip_operator_is_lam_squared_reference_including_boundaries(self):
        for lam in (.6, 1.4):
            d = f.scaling(self.thermal, self.rebuild, lam)
            self.assertLess(max(d["capacity_relative"], d["conductance_relative"], d["boundary_relative"]), 1e-9)
            self.assertNotEqual(d["reset_heat_j_m2"], 0.)          # a geotherm reset would inject or remove heat

    def test_clock_weights_integrate_constants_exactly_and_the_clock_to_second_order(self):
        self.assertEqual(f.clock(1., 1., 3.), (3., .5, .5))
        dtau, wn, wa = f.clock(1.1, 1.2, 3.)
        self.assertLess(abs(wn+wa-1.), 1e-15)
        self.assertLess(abs(dtau/2*(1/(1.1*1.1)+1/(1.2*1.2))-3.)/3., 4e-15)       # the clock spans exactly dt
        slope, errors = .4, []
        exact = 1+slope+slope*slope/3                              # int_0^1 (1 + slope t)^2 dt
        for n in (8, 16, 32):
            h = 1./n
            clock = math.fsum(f.clock(1+slope*i*h, 1+slope*(i+1)*h, h)[0] for i in range(n))
            errors.append(abs(clock-exact))
        for order in w.order(errors):
            self.assertTrue(1.8 <= order <= 2.2, order)

    def test_zero_deformation_recovers_the_retained_responses_bitwise(self):
        dt = DURATION/256
        theirs = heat.prepare_propagator(self.thermal, dt)
        ours = f.clock_propagator(f.eigensystem(self.thermal, theirs), dt)
        for name in ("e", "p1", "p2", "p3"):
            np.testing.assert_array_equal(getattr(ours, name), getattr(theirs, name))
        coeffs = f.coefficients(self.base)
        mine = f.column_at(self.base, coeffs, 1., self.steady)
        reviewed = heat.ArrheniusUpdate.of(self.base).at(self.steady)
        for name in ("log_c", "volume_rt", "weight", "depth_m", "reference_pa", "temperature_k"):
            np.testing.assert_array_equal(getattr(mine, name), getattr(reviewed, name))
        a = f.stage(self.base, coeffs, LAW, 1., self.steady, self.kappa0, DRIVE, (1., 1.))
        b = tm.stage(reviewed, LAW, self.kappa0, DRIVE, (1., 1.))
        self.assertEqual((a["rate"], a["velocity_m_s"], a["force"], a["heat"]),
                         (b["rate"], b["velocity_m_s"], b["force"], b["heat"]))
        np.testing.assert_array_equal(a["source"], b["source"])
        np.testing.assert_array_equal(a["msource"], b["source"])
        bump = 2.*np.sin(math.pi*np.asarray(self.base.depth_m)/self.thermal.thickness_m)
        mine_rest = self.call(4, duration_s=4*dt, drive=REST, theta0=bump, modes=theirs)
        retained = tm.evolve(self.base, self.thermal, LAW, self.kappa0, REST, duration_s=4*dt, steps=4, strain_bound=.05,
                             temperature_step_k=5., fractions=(1., 1.), policy=POLICY, theta0=bump, propagator=theirs)
        np.testing.assert_array_equal(mine_rest["theta"], retained["theta"])
        self.assertEqual(mine_rest["stretch"], 1.)

    def test_current_geometry_is_the_retained_preparation_at_the_current_thickness(self):
        lam = 1.2
        coeffs = f.coefficients(self.base)
        ours = f.column_at(self.base, coeffs, lam, self.steady)
        layers, order, closure, gravity = self.key
        again = w.prepare([dict(layer, thickness_m=layer["thickness_m"]/lam) for layer in layers], order,
                          closure=closure, gravity=gravity)
        again = heat.ArrheniusUpdate.of(again).at(self.steady)
        for name in ("depth_m", "weight", "reference_pa"):
            self.assertLess(f.relmax(getattr(ours, name), getattr(again, name)), 1e-10, name)
        active = np.asarray(self.base.active)
        self.assertLess(f.relmax(np.asarray(ours.log_c)[active], np.asarray(again.log_c)[active]), 1e-10)
        self.assertNotEqual(ours.fingerprint, self.base.fingerprint)
        np.testing.assert_allclose(ours.reference_pa, np.asarray(self.base.reference_pa)/lam, rtol=1e-15, atol=0.)


class KinematicsTests(Base):
    def test_conduction_off_carries_nonuniform_temperature_through_finite_stretch(self):
        layers = self.key[0]
        still = heat.prepare_thermal(self.base.layer, self.base.depth_m, self.base.weight,
                                     [layer["thickness_m"] for layer in layers],
                                     [dict(p, radiogenic_w_m3=0.) for p in CTX["heat"]["thermal_layers"]],
                                     [layer["density_kg_m3"] for layer in layers],
                                     dict(top=dict(type="insulated"), bottom=dict(type="insulated")),
                                     reference_temperature=273., mechanical_fingerprint=self.base.fingerprint)
        theta0 = self.steady-273.
        out = self.call(8, thermal=still, conduction=False, fractions=(0., 0.), theta0=theta0, inputs=self.key)
        self.assertEqual(out["status"], "COMPLETE")
        self.assertGreater(out["log_strain"], SMALL)
        np.testing.assert_array_equal(out["theta"], theta0)
        self.assertTrue(f.conserved(out))
        self.assertEqual((out["final"]["width_m"], out["final"]["thickness_m"]), (out["width_m"], out["thickness_m"]))
        never = ~out["yielded"]
        np.testing.assert_array_equal(out["kappa"][never], out["kappa0"][never])
        self.assertTrue(np.any(out["kappa"] > out["kappa0"]))
        for name in f.THERMAL_ACCOUNTS+("heat_j_m",):
            self.assertEqual(out["accounts"][name], 0., name)

    def test_uniform_insulated_departure_survives_conduction_and_stretch(self):
        base, thermal, h, kappa0 = self.homogeneous()
        level = np.full(base.size, 25.)
        out = f.evolve(base, thermal, LAW, kappa0, DRIVE, duration_s=DURATION, steps=8, window=WINDOW,
                       temperature_step_k=5., fractions=(0., 0.), policy=POLICY, theta0=level)
        self.assertEqual(out["status"], "COMPLETE")
        self.assertGreater(out["log_strain"], SMALL)
        self.assertLess(float(np.abs(out["theta"]-level).max())/25., 1e-13)
        self.assertEqual(out["accounts"]["heat_j_m"], 0.)


class EvolutionTests(Base):
    def test_extension_thins_and_closes_every_account(self):
        out = self.call(inputs=self.key)
        acc = out["accounts"]
        self.assertTrue(f.closed(out, POLICY))
        self.assertGreater(out["log_strain"], SMALL)
        self.assertLess(out["thickness_m"], self.base.thickness_m)
        self.assertEqual(out["width_m"], DRIVE.width_m*out["stretch"])
        self.assertLess(abs(out["log_strain_quadrature"]-out["log_strain"])/out["log_strain"], 1e-3)
        produced = DRIVE.width_m*math.fsum(self.thermal.radiogenic)*out["elapsed_s"]      # constant whole-strip power
        self.assertLess(abs(acc["radiogenic_j_m"]-produced)/produced, 1e-13)
        self.assertGreater(acc["reference_outflow_j_m"], acc["radiogenic_j_m"])   # the stretched reference loses heat
        self.assertGreater(out["clock_s"], out["elapsed_s"])                      # conduction runs faster when thinned
        self.assertGreaterEqual(min(out["min_source_w_m2"], out["min_dissipation_w_m"]), 0.)
        self.assertGreater(out["velocity_end_m_s"], out["velocity_start_m_s"])

    def test_compression_thickens_with_positive_drive_work(self):
        out = self.call(drive=SQUEEZE)
        self.assertTrue(f.closed(out, POLICY))
        self.assertLess(out["stretch"], 1.)
        self.assertGreater(out["thickness_m"], self.base.thickness_m)
        self.assertLess(max(out["velocity_end_m_s"], out["displacement_m"]), 0.)
        self.assertGreater(out["accounts"]["drive_work_j_m"], 0.)

    def test_rest_conducts_only_an_existing_departure(self):
        bump = 2.*np.sin(math.pi*np.asarray(self.base.depth_m)/self.thermal.thickness_m)
        supplied = bump.copy()
        out = self.call(4, drive=REST, theta0=supplied)
        acc = out["accounts"]
        np.testing.assert_array_equal(supplied, bump)
        self.assertEqual((out["stretch"], out["displacement_m"], out["velocity_end_m_s"]), (1., 0., 0.))
        for name in f.MECHANICAL:
            self.assertEqual(acc[name], 0., name)
        self.assertEqual(acc["radiogenic_j_m"], acc["reference_outflow_j_m"])
        self.assertLess(acc["thermal_change_j_m"], 0.)
        self.assertLess(acc["energy_relative"], 1e-10)
        still = self.call(4, drive=REST)
        self.assertFalse(np.any(still["theta"]))

    def test_geometric_feedback_speeds_extension(self):
        on, off = self.call(), self.call(geometry_feedback=False)
        self.assertEqual(on["velocity_start_m_s"], off["velocity_start_m_s"])
        self.assertGreater(on["velocity_end_m_s"], off["velocity_end_m_s"])
        self.assertGreater(on["stretch"], off["stretch"])
        self.assertTrue(f.closed(off, POLICY))

    def test_reusable_eigensystem_matches_the_rebuilt_cold_comparator(self):
        warm = self.call()
        cold = self.call(warm_start=False, rebuild=self.rebuild)
        self.assertLess(w.relative_change(warm["velocity_end_m_s"], cold["velocity_end_m_s"]), 1e-8)
        self.assertLess(w.relative_change(warm["log_strain"], cold["log_strain"]), 1e-8)
        self.assertLess(float(np.abs(warm["theta"]-cold["theta"]).max())/float(np.abs(cold["theta"]).max()), 1e-8)
        self.assertTrue(f.closed(cold, POLICY))

    def test_endpoint_is_fresh_against_an_independent_current_state_preparation(self):
        for drive in (DRIVE, SQUEEZE, REST):
            with self.subTest(force=drive.force_n_m):
                out = self.call(drive=drive)
                fresh = f.freshness(CTX, self.base, self.thermal, self.key, out, drive=drive)
                self.assertLess(fresh["geometry_relative"], 1e-10)
                self.assertLess(fresh["stage_relative"], 1e-8)


class OracleTests(Base):
    def test_prescribed_clock_is_second_order_against_the_semi_discrete_solution(self):
        em = CTX["heat"]["campaign"]["eigenmode"]
        h1, h2 = em["thickness_m"]
        mu, mode = heat.two_layer_mode(h1, h2, *em["conductivity_w_m_k"],
                                       *(d*c for d, c in zip(em["density_kg_m3"], em["heat_capacity_j_kg_k"])))
        props = [dict(name=n, conductivity_w_m_k=k, heat_capacity_j_kg_k=c, radiogenic_w_m3=0.)
                 for n, k, c in zip(("a", "b"), em["conductivity_w_m_k"], em["heat_capacity_j_kg_k"])]
        ends = dict(top=dict(type="temperature", value_k=em["boundary_k"]),
                    bottom=dict(type="temperature", value_k=em["boundary_k"]))
        lay, dep, wt = heat.geometry([h1, h2], 16)
        slab = heat.prepare_thermal(lay, dep, wt, [h1, h2], props, em["density_kg_m3"], ends)
        theta0 = em["amplitude_k"]*mode(dep)
        final = 1.375
        duration = 1./(mu*(1+final+final*final)/3)
        slope = (final-1)/duration
        tau = duration*(1+slope*duration+(slope*duration)**2/3)
        half = np.sqrt(np.asarray(slab.capacity))
        exact = (expm(-tau*slab.operator()/half[:, None]/half[None, :])@(half*theta0))/half
        errors = []
        for n in (16, 32, 64):
            out = f.conduct_history(slab, lambda t: 1.+slope*t, duration_s=duration, steps=n, window=WINDOW,
                                    theta0=theta0)
            self.assertEqual(out["status"], "COMPLETE")
            self.assertLess(out["max_step_energy_relative"], 1e-10)
            errors.append(float(np.abs(out["theta"]-exact).max())/float(np.abs(exact).max()))
        for order in w.order(errors):
            self.assertTrue(1.8 <= order <= 2.2, order)

    def test_homogeneous_finite_strain_oracle_is_second_order(self):
        base, thermal, h, kappa0 = self.homogeneous()
        duration = 2.5e13
        oracle = f.stretch_oracle(h["layer"], h["thermal"], LAW, DRIVE, h["initial_history"], duration, (1., 1.))
        self.assertTrue(oracle["always_yielding"])
        errors = []
        for n in (16, 32, 64):
            out = f.evolve(base, thermal, LAW, kappa0, DRIVE, duration_s=duration, steps=n, window=WINDOW,
                           temperature_step_k=5., fractions=(1., 1.), policy=POLICY)
            self.assertTrue(f.closed(out, POLICY))
            errors.append((w.relative_change(float(out["theta"][0]), oracle["temperature_rise"]),
                           w.relative_change(float(out["kappa"][0])-h["initial_history"], oracle["history_gain"]),
                           w.relative_change(out["log_strain"], oracle["log_stretch"])))
        for series in list(zip(*errors))[:2]:
            for order in w.order(list(series)):
                self.assertTrue(1.8 <= order <= 2.2, order)
        start = f.stretch_balance(h["layer"], LAW, DRIVE, h["layer"]["temperature_k"][0], h["initial_history"], 1.)
        self.assertLess(w.relative_change(out["velocity_start_m_s"], start["velocity_m_s"]), 1e-8)
        self.assertGreater(out["stretch"], 1.)


class RefusalTests(Base):
    def test_expiry_during_final_endpoint_cannot_commit_the_trial(self):
        dt = DURATION/16
        prefix = self.call(1, duration_s=dt)
        deadline = f.CountdownDeadline(10**9)
        original, calls = f.stage, 0

        def finish_then_expire(*args, **kwargs):
            nonlocal calls
            result = original(*args, **kwargs)
            calls += 1
            if calls == 5:                          # initial + two predictor/endpoint pairs
                deadline.remaining = 0
            return result
        with mock.patch.object(f, "stage", side_effect=finish_then_expire):
            out = self.call(2, duration_s=2*dt, deadline=deadline)
        self.assert_same_prefix(out, prefix, "REFUSED_DEADLINE")

    def test_prescribed_control_checks_deadline_and_temperature_before_commit(self):
        dt = DURATION/16
        stretch = lambda t: 1.+.2*t/DURATION
        kw = dict(window=WINDOW, modes=self.modes)
        prefix = f.conduct_history(self.thermal, stretch, duration_s=dt, steps=1, **kw)
        deadline = f.CountdownDeadline(10**9)
        original, calls = f.advance_map, 0

        def advancing(*args, **kwargs):
            advance = original(*args, **kwargs)

            def finish_then_expire(*values):
                nonlocal calls
                result = advance(*values)
                calls += 1
                if calls == 2:
                    deadline.remaining = 0
                return result
            return finish_then_expire
        with mock.patch.object(f, "advance_map", side_effect=advancing):
            out = f.conduct_history(self.thermal, stretch, duration_s=2*dt, steps=2, deadline=deadline, **kw)
        self.assertEqual(out["status"], "REFUSED_DEADLINE")
        for name in ("accepted_steps", "elapsed_s", "clock_s", "stretch", "accounts"):
            self.assertEqual(out[name], prefix[name], name)
        np.testing.assert_array_equal(out["theta"], prefix["theta"])
        with self.assertRaisesRegex(ValueError, "initial material temperatures"):
            f.conduct_history(self.thermal, stretch, duration_s=dt, steps=1,
                              theta0=np.full(self.base.size, 2000.), **kw)
        with mock.patch.object(f, "advance_map", return_value=lambda *args: (
                np.full(self.base.size, 2000.), np.zeros(self.base.size))):
            invalid = f.conduct_history(self.thermal, stretch, duration_s=dt, steps=1, **kw)
        self.assertEqual(invalid["status"], "REFUSED_TEMPERATURE_WINDOW")
        self.assertEqual(invalid["accepted_steps"], 0)
        self.assertTrue(all(value == 0 for value in invalid["accounts"].values()))
        self.assertFalse(np.any(invalid["theta"]))

    def assert_same_prefix(self, refused, prefix, status):
        self.assertEqual(refused["status"], status)
        self.assertTrue(f.same_prefix(refused, prefix))
        self.assertTrue(f.nothing_lost(refused, POLICY))

    def test_window_step_and_deadline_refusals_are_atomic(self):
        dt = DURATION/16

        def prefix(k, **kw):
            return self.call(k, duration_s=dt*k, **kw)
        full, last_but_one, third = prefix(8), prefix(7), prefix(3)
        euler_last = last_but_one["stretch"]+dt*last_but_one["velocity_end_m_s"]/DRIVE.width_m
        euler_fourth = third["stretch"]+dt*third["velocity_end_m_s"]/DRIVE.width_m
        self.assertTrue(last_but_one["stretch"] < euler_last < full["stretch"])
        low = WINDOW["stretch"][0]
        self.assert_same_prefix(prefix(8, window=dict(WINDOW, stretch=[low, (third["stretch"]+euler_fourth)/2])),
                                third, "REFUSED_STRETCH_WINDOW")
        self.assert_same_prefix(prefix(8, window=dict(WINDOW, stretch=[low, (euler_last+full["stretch"])/2])),
                                last_but_one, "REFUSED_STRETCH_WINDOW")
        hot = prefix(2, temperature_step_k=1e-3)
        self.assertEqual((hot["status"], hot["accepted_steps"], hot["stretch"]), ("REFUSED_TEMPERATURE_STEP", 0, 1.))
        self.assertFalse(np.any(hot["theta"]))
        probe = f.CountdownDeadline(10**9)
        prefix(8, deadline=probe)
        used = 10**9-probe.remaining
        cut = prefix(8, deadline=f.CountdownDeadline(used//2))
        self.assertTrue(0 < cut["accepted_steps"] < 8, cut["accepted_steps"])
        self.assert_same_prefix(cut, prefix(cut["accepted_steps"]), "REFUSED_DEADLINE")
        self.assert_same_prefix(prefix(8, deadline=f.CountdownDeadline(used-1)), last_but_one, "REFUSED_DEADLINE")
        with self.assertRaises(RuntimeError):
            prefix(2, deadline=0.)

    def test_temperature_window_refusal_is_atomic(self):
        base, thermal, h, kappa0 = self.homogeneous()
        dt = DURATION/8
        window = dict(WINDOW, temperature_k=[273., float(thermal.steady_k[0])+10.])

        def prefix(k):
            return f.evolve(base, thermal, LAW, kappa0, DRIVE, duration_s=dt*k, steps=k, window=window,
                            temperature_step_k=5., fractions=(1., 1.), policy=POLICY)
        capped = prefix(8)
        k = capped["accepted_steps"]
        self.assertTrue(0 < k < 8, k)
        self.assert_same_prefix(capped, prefix(k), "REFUSED_TEMPERATURE_WINDOW")

    def test_direct_api_guards(self):
        other, _ = w.base_prepare(CTX["weak"], order=8, offset_k=1.)
        stale = [dict(layer) for layer in self.key[0]]
        stale[0]["temperature_k"] = [x+1e-9 for x in stale[0]["temperature_k"]]
        thick = [layer["thickness_m"] for layer in self.key[0]]
        dens = [layer["density_kg_m3"] for layer in self.key[0]]
        foreign = heat.prepare_thermal(*heat.geometry(thick[::-1], 8), thick[::-1], CTX["heat"]["thermal_layers"], dens,
                                       CTX["heat"]["boundaries"], mechanical_fingerprint=self.base.fingerprint)
        cases = dict(
            no_steps=dict(steps=0), too_many_steps=dict(steps=257), float_steps=dict(steps=2.),
            wide_stretch=dict(window=dict(WINDOW, stretch=[.5, 1.4])),
            wide_temperature=dict(window=dict(WINDOW, temperature_k=[273., 1700.])),
            window_without_reference=dict(window=dict(WINDOW, stretch=[1.1, 1.4])),
            guard=dict(temperature_step_k=6.), untyped_drive=dict(drive=(2e13, 5e22, 1e5)),
            amplified_heat=dict(fractions=(1.5, 1.)), theta_shape=dict(theta0=np.zeros(3)),
            initial_outside_window=dict(theta0=np.full(self.base.size, 1000.)),
            negative_history=dict(kappa0=-self.kappa0), warm_flag=dict(warm_start=1),
            geometry_flag=dict(geometry_feedback=1), conduction_flag=dict(conduction=1),
            other_column=dict(base=other, modes=None),
            temperature_prepared_base=dict(base=heat.ArrheniusUpdate.of(self.base).at(self.steady)),
            stretched_base=dict(base=f.column_at(self.base, f.coefficients(self.base), 1.1, self.steady)),
            stale_inputs=dict(inputs=(stale, *self.key[1:])), foreign_support=dict(thermal=foreign),
            replaced_support=dict(thermal=dataclasses.replace(self.thermal, depth_m=w.frozen(self.thermal.depth_m+1.))),
            foreign_modes=dict(modes=f.eigensystem(foreign)),
            conduction_off_with_fixed_temperatures=dict(conduction=False),
            rebuild_with_modes=dict(rebuild=self.rebuild, modes=self.modes),
            rebuild_not_reproducing=dict(rebuild=dict(self.rebuild, props=[
                dict(p, conductivity_w_m_k=3.) for p in self.rebuild["props"]])))
        for name, kw in cases.items():
            with self.subTest(name), self.assertRaises(ValueError):
                self.call(**dict(dict(steps=2), **kw))
        tiny, tiny_thermal = tm.compressive_column(CTX, 1e-3)
        with self.assertRaisesRegex(ValueError, "not monotone"):
            self.call(2, base=tiny, thermal=tiny_thermal, kappa0=np.zeros(tiny.size), drive=SQUEEZE)
        for history in (lambda t: 1.1, lambda t: 1.+t/DURATION):
            with self.assertRaises(ValueError):
                f.conduct_history(self.thermal, history, duration_s=DURATION, steps=2, window=WINDOW)


class EvidenceTests(unittest.TestCase):
    def test_accepted_receipts_and_recorded_sources_match(self):
        match = f.evidence_match(f.bindings())
        for group, values in match.items():
            for name, ok in values.items():
                with self.subTest(group=group, name=name):
                    self.assertTrue(ok)

    def test_cli_refuses_to_overwrite_an_existing_receipt(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder)/"existing.json"
            target.write_text("{}\n", encoding="utf-8")
            with mock.patch.object(sys, "argv", ["check_i01_finite_strain.py", "--output", str(target)]):
                with self.assertRaises(FileExistsError):
                    f.main()
            self.assertEqual(target.read_text(encoding="utf-8"), "{}\n")


if __name__ == "__main__":
    unittest.main()
