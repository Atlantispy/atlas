"""Focused guards for the I01 column-weakening adapter; no native import.
SPDX-License-Identifier: AGPL-3.0-only
"""
import copy
import json
from pathlib import Path
import sys
import unittest

import numpy as np
from threadpoolctl import threadpool_limits

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"tools"))
import check_i01_weakening as w

SPEC = w.load_case()
LAW = w.law_of(SPEC)
POLICY = SPEC["policy"]
RATE = SPEC["campaign"]["rate_s"]
BOUND = SPEC["representation"]["max_axial_strain"]


class Base(unittest.TestCase):
    def setUp(self):
        self.lease = threadpool_limits(limits=1, user_api="blas")
        self.addCleanup(self.lease.restore_original_limits)
        self.prep, self.layers = w.base_prepare(SPEC, order=8)
        self.kappa0 = w.initial_history(self.prep, SPEC)

    def evolve(self, law, kappa0, steps, strain, prep=None, **kw):
        kw.setdefault("control", "rate")
        kw.setdefault("value", RATE)
        return w.evolve(self.prep if prep is None else prep, law, kappa0, duration_s=strain/RATE,
                        steps=steps, strain_bound=BOUND, policy=POLICY, **kw)


class LawAndClosureTests(Base):
    def test_aspect_interval_transcription_and_exact_off(self):
        kappa = np.array([0., 1., 1.7, 2., 3., 5.])
        lam_c, lam_f = LAW.factors(kappa)
        np.testing.assert_array_equal(lam_c[[0, 1, 3, 4, 5]], [1., 1., .625, .25, .25])
        for k, c, f in zip(kappa, lam_c, lam_f):
            ref = w.aspect_factors(float(k), LAW)
            self.assertAlmostEqual(c, ref[0], places=15)
            self.assertAlmostEqual(f, ref[1], places=15)
        off = w.OFF.factors(kappa)
        np.testing.assert_array_equal(off[0], np.ones(6))
        np.testing.assert_array_equal(off[1], np.ones(6))

    def test_history_monotonicity_certificate(self):
        self.assertTrue(LAW.certify(self.prep))
        with self.assertRaisesRegex(ValueError, "monotonicity"):
            w.WeakeningLaw(1., 3., 1., .25).certify(self.prep)
        cohesionless = [dict(layer, cohesion_pa=0.) for layer in self.layers]
        prep = w.prepare(cohesionless, 4, closure=w.LITHOSTATIC, gravity=9.81)
        self.assertTrue(w.WeakeningLaw(1., 3., 1., .25).certify(prep))

    def test_plastic_closed_forms_both_signs_and_clamp(self):
        pl = SPEC["campaign"]["plastic"]
        base = dict(SPEC["layers"][0], creep=[pl["negligible_creep"]], density_kg_m3=pl["density_kg_m3"])
        for thickness in (pl["deep_thickness_m"], pl["shallow_thickness_m"]):
            prep = w.prepare([dict(base, thickness_m=thickness)], 2, closure=w.LITHOSTATIC, gravity=9.81)
            for k in (0., 2.):
                for sign in (1., -1.):
                    res = w.respond(prep, LAW, np.full(2, k), sign*RATE)
                    for i in range(2):
                        exact = w.closed_form(base, float(prep.reference_pa[i]), sign*RATE, w.aspect_factors(k, LAW))
                        self.assertLess(w.relative_change(res["stress"][i], exact), 1e-10)

    def test_kernel_parity_fixed_point_and_pressure_asymmetry(self):
        reviewed = json.loads(w.COLUMN_CASE.read_text(encoding="utf-8"))
        supplied = w.prepare(reviewed["layers"], 8, closure=w.SUPPLIED)
        kernel = w.column.Column(reviewed["layers"], 8).solve(reviewed["axial_rate_s"])
        ours = w.respond(supplied, w.OFF, np.zeros(supplied.size), reviewed["axial_rate_s"])
        self.assertLess(w.relative_change(ours["force"], kernel["force_n_m"]), 1e-10)
        ext = w.respond(self.prep, LAW, self.kappa0, RATE)
        comp = w.respond(self.prep, LAW, self.kappa0, -RATE)
        for res in (ext, comp):
            fp = w.fixed_point_parity(self.prep, LAW, self.kappa0, res)
            self.assertEqual(fp["skipped"], 0)
            self.assertLess(fp["max_relative"], 1e-9)
        legacy = w.vertical_load_as_mean_pressure(self.layers, SPEC["campaign"]["initial_history_by_layer"],
                                                  LAW, 9.81, 8, RATE)
        self.assertLess(ext["force"], legacy)
        self.assertLess(legacy, -comp["force"])
        self.assertEqual(w.vertical_load_as_mean_pressure(self.layers, [2.]*4, LAW, 9.81, 8, -RATE), -legacy)
        self.assertGreater(ext["dforce"], 0.)


class EvolutionTests(Base):
    def test_raw_history_is_never_written_back(self):
        kappa = self.kappa0.copy()
        w.respond(self.prep, LAW, kappa, RATE)
        out = self.evolve(LAW, kappa, 4, .02)
        np.testing.assert_array_equal(kappa, self.kappa0)
        self.assertIsNot(out["kappa"], kappa)

    def test_accounts_and_history_bounds(self):
        out = self.evolve(LAW, self.kappa0, 8, .03)
        self.assertEqual(out["status"], "COMPLETE")
        self.assertLess(out["accounts"]["partition_relative"], 1e-10)
        gain = out["kappa"]-self.kappa0
        self.assertTrue(np.all(gain >= 0))
        self.assertLessEqual(float(gain.max()), 2*out["strain"]*(1+1e-10))
        never = out["yield_stages"] == 0
        self.assertTrue(never.any())
        np.testing.assert_array_equal(out["kappa"][never], self.kappa0[never])
        self.assertLessEqual(out["max_step_force_rise_relative"], 0.)

    def test_small_strain_refusal_is_atomic(self):
        refused = self.evolve(LAW, self.kappa0, 4, .08)      # 0.02 per step; third step exceeds 0.05
        exact = self.evolve(LAW, self.kappa0, 2, .04)
        self.assertEqual((refused["status"], refused["accepted_steps"]), ("REFUSED_SMALL_STRAIN", 2))
        np.testing.assert_array_equal(refused["kappa"], exact["kappa"])
        self.assertEqual(refused["accounts"], exact["accounts"])
        self.assertEqual(refused["force_end"], exact["force_end"])

    def test_force_inverse_and_constant_force_limits(self):
        force = w.respond(self.prep, LAW, self.kappa0, RATE)["force"]
        back = w.respond_force(self.prep, LAW, self.kappa0, force, rate_guess=3*RATE, policy=POLICY)
        self.assertLess(w.relative_change(back["rate"], RATE), 1e-8)
        off_force = w.respond(self.prep, w.OFF, self.kappa0, RATE)["force"]
        off = self.evolve(w.OFF, self.kappa0, 4, .02, control="force", value=off_force, rate_guess=RATE)
        self.assertTrue(all(w.relative_change(r, RATE) < 1e-8 for r in off["rate_magnitude_range"]))
        on = self.evolve(LAW, self.kappa0, 4, .02, control="force", value=force, rate_guess=RATE)
        self.assertGreater(on["rate_end"], on["rate_start"])
        self.assertLess(w.relative_change(on["accounts"]["external_work_j_m2"], force*on["strain"]), 1e-9)
        env = w.rate_envelope(self.prep, LAW, self.kappa0, force, BOUND, rate_guess=RATE, policy=POLICY)
        self.assertLessEqual(env["minimum"]*(1-1e-8), on["rate_magnitude_range"][0])
        self.assertLessEqual(on["rate_magnitude_range"][1], env["maximum"]*(1+1e-8))

    def test_force_envelope_contains_rate_controlled_window(self):
        out = self.evolve(LAW, self.kappa0, 8, .03)
        env = w.force_envelope(self.prep, LAW, self.kappa0, (RATE, RATE), .03/RATE, BOUND)
        self.assertLessEqual(env["minimum"], out["force_magnitude_range"][0])
        self.assertEqual(env["maximum"], out["force_magnitude_range"][1])

    def test_local_independence_and_unreachable_interval(self):
        other = copy.deepcopy(self.layers)
        for layer in other[1:]:
            layer["temperature_k"] = [t+100. for t in layer["temperature_k"]]
        prep_b = w.prepare(other, 8, closure=w.LITHOSTATIC, gravity=9.81)
        a, b = self.evolve(LAW, self.kappa0, 4, .02), self.evolve(LAW, self.kappa0, 4, .02, prep=prep_b)
        top = self.prep.layer == 0
        np.testing.assert_array_equal(a["kappa"][top], b["kappa"][top])
        off = self.evolve(w.OFF, self.kappa0, 4, .02)
        zero = self.evolve(LAW, np.zeros(self.prep.size), 4, .02)
        self.assertEqual(off["force_magnitude_range"][0], off["force_magnitude_range"][1])
        self.assertEqual((zero["force_start"], zero["force_end"]), (off["force_start"], off["force_end"]))
        self.assertLess(float(zero["kappa"].max()), LAW.start)

    def test_homogeneous_oracle_second_order(self):
        h = SPEC["campaign"]["homogeneous"]
        prep = w.prepare([h["layer"]], 4, closure=w.SUPPLIED)
        duration = h["total_strain"]/RATE
        oracle = w.homogeneous_oracle(h["layer"], LAW, RATE, h["initial_history"], duration)
        errors = []
        for n in (8, 16, 32):
            out = w.evolve(prep, LAW, np.full(prep.size, 2.), control="rate", value=RATE, duration_s=duration,
                           steps=n, strain_bound=BOUND, policy=POLICY)
            self.assertLessEqual(float(np.ptp(out["kappa"])), 1e-13*float(out["kappa"].max()))
            errors.append(w.relative_change(out["kappa"][0]-2., oracle["history_gain"]))
        for o in w.order(errors):
            self.assertTrue(1.8 <= o <= 2.2, o)


class RefusalTests(Base):
    def test_preparation_cannot_be_made_writable(self):
        for key in self.prep.__dataclass_fields__:
            value = getattr(self.prep, key)
            if isinstance(value, np.ndarray):
                with self.subTest(key=key), self.assertRaises(ValueError):
                    value.setflags(write=True)

    def test_changed_provider_is_refused_before_booking(self):
        changed, _ = w.base_prepare(SPEC, order=8, offset_k=100.)
        original = self.kappa0.copy()
        with self.assertRaisesRegex(ValueError, "replacement preparation"):
            self.evolve(LAW, self.kappa0, 2, .01, provider=lambda: changed)
        np.testing.assert_array_equal(self.kappa0, original)

    def test_window_and_direct_execution_guards(self):
        kappa = np.full(self.prep.size, 2.)
        force = w.respond(self.prep, LAW, kappa, RATE)["force"]
        for allowance in (-.01, .051, np.nan, True):
            with self.subTest(allowance=allowance), self.assertRaises(ValueError):
                w.rate_envelope(self.prep, LAW, kappa, force, allowance,
                                rate_guess=RATE, policy=POLICY)
        zero = w.rate_envelope(self.prep, LAW, kappa, force, 0., rate_guess=RATE, policy=POLICY)
        self.assertEqual(zero["minimum"], zero["maximum"])
        for bound in (.051, np.inf, True):
            with self.assertRaises(ValueError):
                w.force_envelope(self.prep, LAW, kappa, (RATE, RATE), 1e12, bound)
            with self.assertRaises(ValueError):
                w.evolve(self.prep, LAW, kappa, control="rate", value=RATE,
                         duration_s=1e12, steps=1, strain_bound=bound, policy=POLICY)
        for key, value in (("max_steps", 257), ("force_iterations", 97),
                           ("force_relative", 1.), ("history_bound_relative", 1.)):
            policy = dict(POLICY, **{key: value})
            with self.subTest(key=key), self.assertRaises(ValueError):
                w.evolve(self.prep, LAW, kappa, control="rate", value=RATE,
                         duration_s=1e12, steps=1, strain_bound=BOUND, policy=policy)
            with self.assertRaises(ValueError):
                w.respond_force(self.prep, LAW, kappa, force, rate_guess=RATE, policy=policy)
        for history in (np.ones(self.prep.size, bool), np.full(self.prep.size, 2.+1j)):
            with self.assertRaises(ValueError):
                w.respond(self.prep, LAW, history, RATE)

    def test_reuse_parity_and_stale_preparation(self):
        key = (self.layers, 8, w.LITHOSTATIC, 9.81)
        a = self.evolve(LAW, self.kappa0, 3, .015)
        b = self.evolve(LAW, self.kappa0, 3, .015,
                        provider=lambda: w.prepare(self.layers, 8, closure=w.LITHOSTATIC, gravity=9.81))
        np.testing.assert_array_equal(a["kappa"], b["kappa"])
        self.assertEqual(a["accounts"], b["accounts"])
        self.evolve(LAW, self.kappa0, 1, .005, inputs=key)
        with self.assertRaisesRegex(ValueError, "stale"):
            self.evolve(LAW, self.kappa0, 1, .005, inputs=(w._warmed(self.layers),)+key[1:])

    def test_case_refuses_unadmitted_laws(self):
        for path, value in ((("representation", "healing_per_s"), 1e-15),
                            (("representation", "nonlocal_depth_length_m"), 5e3),
                            (("representation", "max_axial_strain"), .2),
                            (("representation", "temperature"), "Eulerian geotherm"),
                            (("representation", "elastic_modulus_pa"), 1e11),
                            (("weakening", "cohesion_factor"), 0.),
                            (("weakening", "friction_factor"), 1.5),
                            (("policy", "max_steps"), 257)):
            bad = copy.deepcopy(SPEC)
            bad[path[0]][path[1]] = value
            with self.subTest(path=path), self.assertRaises(ValueError):
                w.validate_case(bad)
        extra = copy.deepcopy(SPEC)
        extra["pore_pressure_law"] = "drained"
        with self.assertRaises(ValueError):
            w.validate_case(extra)

    def test_direct_input_refusals(self):
        for steps in (0, 257, 2.):
            with self.subTest(steps=steps), self.assertRaises(ValueError):
                self.evolve(LAW, self.kappa0, steps, .01)
        for kappa in (-self.kappa0, self.kappa0[:3], np.full(self.prep.size, np.nan)):
            with self.assertRaises(ValueError):
                self.evolve(LAW, kappa, 2, .01)
        with self.assertRaises(ValueError):
            self.evolve(LAW, self.kappa0, 2, .01, value=0.)
        with self.assertRaises(ValueError):
            self.evolve(LAW, self.kappa0, 2, .01, control="force", value=1e13)
        with self.assertRaises(ValueError):
            w.force_envelope(self.prep, LAW, self.kappa0, (RATE, RATE), 1e15, BOUND)
        r = SPEC["campaign"]["refusal"]
        single = dict(SPEC["layers"][2], thickness_m=1000.,
                      creep=[dict(SPEC["layers"][2]["creep"][0], volume_m3_mol=r["compressive_volume_m3_mol"])])
        tiny = w.prepare([single], 2, closure=w.LITHOSTATIC, gravity=9.81)
        with self.assertRaisesRegex(ValueError, "not monotone"):
            w.respond(tiny, w.OFF, np.zeros(2), -1e-12)


if __name__ == "__main__":
    unittest.main()
