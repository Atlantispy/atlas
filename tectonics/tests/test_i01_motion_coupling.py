"""Focused I01 force/motion seam checks. SPDX-License-Identifier: AGPL-3.0-only"""
import dataclasses
from pathlib import Path
import sys
import unittest

import numpy as np
from threadpoolctl import threadpool_limits

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import check_i01_motion_coupling as m

w = m.w


class MotionTests(unittest.TestCase):
    def setUp(self):
        lease = threadpool_limits(limits=1, user_api="blas")
        self.addCleanup(lease.restore_original_limits)
        self.spec = w.load_case()
        self.prep, _ = w.base_prepare(self.spec, order=8)
        self.law = w.law_of(self.spec)
        self.history = w.initial_history(self.prep, self.spec)
        self.drive = m.Drive(2e13, 5e22, 1e5)

    def run_case(self, **kwargs):
        defaults = dict(duration_s=1e13, steps=4)
        defaults.update(kwargs)
        return m.evolve(self.prep, self.law, self.history, self.drive, **defaults)

    def test_linear_oracle_both_signs_and_drag_scaling(self):
        layer = dict(self.spec["campaign"]["homogeneous"]["layer"],
                     mean_pressure_pa=[0., 0.], cohesion_pa=1e30, friction_rad=0.,
                     creep=[dict(a=1e-22, n=1., energy_j_mol=0.)])
        prep = w.prepare([layer], 4, closure=w.SUPPLIED)
        history = np.zeros(prep.size)
        for sign in (1, -1):
            for drag in (1e22, 1e24):
                drive = m.Drive(sign * 1e12, drag, 1e5)
                out = m.solve(prep, w.OFF, history, drive)
                exact = drive.force_n_m / (drag + 2 * layer["thickness_m"] / 1e-22 / drive.width_m)
                self.assertLess(w.relative_change(out["velocity_m_s"], exact), 1e-10)
                np.testing.assert_array_equal(out["kdot"], 0.)
                self.assertLess(out["power_relative"], 2e-10)

    def test_manufactured_inverse_and_independent_root(self):
        for sign in (1, -1):
            rate = sign * 1e-15
            col = w.respond(self.prep, self.law, self.history, rate)
            total = col["force"] + self.drive.drag_pa_s * self.drive.width_m * rate
            drive = dataclasses.replace(self.drive, force_n_m=total)
            for method in ("newton", "brent"):
                out = m.solve(self.prep, self.law, self.history, drive, method=method)
                self.assertLess(w.relative_change(out["rate"], rate), 1e-8)
                self.assertLess(out["force_relative"], m.FORCE_TOL)

    def test_zero_drive_is_exact_rest(self):
        drive = dataclasses.replace(self.drive, force_n_m=0.)
        out = m.evolve(self.prep, self.law, self.history, drive, duration_s=1e13, steps=3)
        self.assertEqual(out["displacement_m"], 0.)
        self.assertEqual(sum(out["energy_j_m"].values()), 0.)
        np.testing.assert_array_equal(out["kappa"], self.history)

    def test_history_force_and_integrated_work_accounts(self):
        original = self.history.copy()
        out = self.run_case()
        self.assertEqual(out["status"], "COMPLETE")
        self.assertGreater(out["velocity_end_m_s"], out["velocity_start_m_s"])
        self.assertLess(out["work_relative"], 2e-10)
        exact_work = self.drive.force_n_m * out["displacement_m"]
        self.assertLess(w.relative_change(out["energy_j_m"]["drive"], exact_work), 1e-14)
        np.testing.assert_array_equal(self.history, original)
        self.assertTrue(np.all(out["kappa"] - original <= 2 * abs(out["strain"]) * (1 + 1e-10)))

    def test_compressive_evolution_keeps_work_positive(self):
        out = m.evolve(self.prep, self.law, self.history,
                       dataclasses.replace(self.drive, force_n_m=-2e13), duration_s=1e13, steps=4)
        self.assertLess(out["strain"], 0)
        self.assertTrue(all(v >= 0 for v in out["energy_j_m"].values()))
        self.assertLess(out["work_relative"], 2e-10)

    def test_refusal_does_not_book_trial(self):
        first = self.run_case(duration_s=1e13, steps=1)
        out = self.run_case(duration_s=4e13, steps=4, strain_bound=abs(first["strain"]) * 1.1)
        self.assertEqual((out["status"], out["accepted_steps"]), ("REFUSED_SMALL_STRAIN", 1))
        np.testing.assert_array_equal(out["kappa"], first["kappa"])
        self.assertEqual(out["energy_j_m"], first["energy_j_m"])
        self.assertEqual(out["velocity_end_m_s"], first["velocity_end_m_s"])

    def test_warm_guess_does_not_reuse_changed_state(self):
        cold = self.run_case(warm_start=False)
        warm = self.run_case(warm_start=True)
        self.assertLess(w.relative_change(warm["strain"], cold["strain"]), 1e-8)
        np.testing.assert_allclose(warm["kappa"], cold["kappa"], atol=1e-9, rtol=0.)
        guess = m.solve(self.prep, self.law, self.history, self.drive)
        changed = self.history + .05
        a = m.solve(self.prep, self.law, changed, self.drive, warm=guess)
        b = m.solve(self.prep, self.law, changed, self.drive)
        self.assertLess(w.relative_change(a["rate"], b["rate"]), 1e-8)
        self.assertGreater(a["rate"], guess["rate"])

    def test_deadline_and_invalid_arguments(self):
        for key, values in (("force_n_m", [True, float("nan")]),
                            ("drag_pa_s", [0., -1., float("inf")]),
                            ("width_m", [0., True])):
            for value in values:
                with self.assertRaises(ValueError):
                    dataclasses.replace(self.drive, **{key: value})
        for kwargs in (dict(steps=257), dict(steps=True), dict(strain_bound=.051),
                       dict(duration_s=-1), dict(warm_start=1), dict(method="unknown")):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.run_case(**kwargs)
        with self.assertRaises(RuntimeError):
            self.run_case(deadline=0.)
        for history in (np.ones(self.prep.size, bool), self.history[:-1], -np.ones(self.prep.size)):
            with self.assertRaises(ValueError):
                m.solve(self.prep, self.law, history, self.drive)


if __name__ == "__main__":
    unittest.main()
