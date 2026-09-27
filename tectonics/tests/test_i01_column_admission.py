"""Focused layered motion-admission checks. SPDX-License-Identifier: AGPL-3.0-only"""
from concurrent.futures import CancelledError
import copy
from dataclasses import replace
from fractions import Fraction
from pathlib import Path
import sys
import threading
import time
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"tools"))
import check_i01_column_admission as a


class AdmissionTests(unittest.TestCase):
    def setUp(self):
        self.layer = a.analytic_layer()
        self.prep = a.w.prepare([self.layer], 4, closure=a.w.SUPPLIED)
        self.history = np.zeros(self.prep.size)
        self.drive = a.m.Drive(2e13, 5e22, 1e5)
        self.envelope = a.prepare(self.prep, a.w.OFF, self.history, self.drive)

    def check(self, **kwargs):
        defaults = dict(duration_s=1e12, used_strain=0., relative_tolerance=1e-5,
                        displacement_limit_m=100.)
        defaults.update(kwargs)
        return a.admit(self.envelope, self.prep, a.w.OFF, self.history, self.drive, **defaults)

    def test_analytical_actual_motion_and_whole_window_bounds(self):
        actual = a.m.solve(self.prep, a.w.OFF, self.history, self.drive)
        k = 2*self.layer["thickness_m"]/(self.drive.width_m*(1e-20+1/(2e19)))
        exact = self.drive.force_n_m/(self.drive.drag_pa_s+k)
        self.assertLess(abs(actual["velocity_m_s"]-exact)/exact, 1e-8)
        out = self.check()
        error = self.drive.force_n_m/self.drive.drag_pa_s-actual["velocity_m_s"]
        self.assertTrue(out["numerical_admissible"])
        self.assertLess(error, out["speed_error_bound_m_s"])
        self.assertLess(error*1e12, out["displacement_error_bound_m"])
        self.assertFalse(out["generated_separation_authorised"])

    def test_exact_equality_and_stricter_neighbour(self):
        b = self.envelope.balance
        edge = b.coefficient/(b.drag+b.coefficient)
        self.assertTrue(self.check(relative_tolerance=edge)["numerical_admissible"])
        self.assertFalse(self.check(relative_tolerance=edge-Fraction(1, 10**20))["numerical_admissible"])
        self.assertFalse(self.check(displacement_limit_m=0.)["numerical_admissible"])

    def test_cannot_reset_strain_budget(self):
        with self.assertRaisesRegex(ValueError, "remaining"):
            self.check(used_strain=.049)
        for used in (-.1, float("nan"), True):
            with self.assertRaises(ValueError):
                self.check(used_strain=used)

    def test_changed_preparation_force_and_law_refused(self):
        changed = a.w.prepare([dict(self.layer, temperature_k=[601., 601.])], 4, closure=a.w.SUPPLIED)
        for prep, law, drive in ((changed, a.w.OFF, self.drive),
                (self.prep, a.w.OFF, replace(self.drive, width_m=2e5)),
                (self.prep, a.w.WeakeningLaw(0., 1., .5, 1.), self.drive)):
            with self.assertRaisesRegex(ValueError, "changed"):
                a.admit(self.envelope, prep, law, self.history, drive, duration_s=1.,
                        used_strain=0., relative_tolerance=.01, displacement_limit_m=1.)

    def test_missing_plastic_branch_and_compression_refused(self):
        no_plastic = a.w.prepare([dict(self.layer, plastic_viscosity_pa_s=None)], 4, closure=a.w.SUPPLIED)
        with self.assertRaisesRegex(ValueError, "plastic"):
            a.prepare(no_plastic, a.w.OFF, self.history, self.drive)
        for f in (-1e13, 0.):
            with self.assertRaisesRegex(ValueError, "extension"):
                a.prepare(self.prep, a.w.OFF, self.history, replace(self.drive, force_n_m=f))

    def test_history_floors_copied_and_decreasing_history_refused(self):
        history = np.full(self.prep.size, 2.)
        envelope = a.prepare(self.prep, a.w.OFF, history, self.drive)
        history[:] = 1.
        self.assertEqual(envelope.history_floor, (Fraction(2),)*self.prep.size)
        with self.assertRaisesRegex(ValueError, "history"):
            a.admit(envelope, self.prep, a.w.OFF, history, self.drive, duration_s=1.,
                    used_strain=0., relative_tolerance=.01, displacement_limit_m=1.)

    def test_current_weakening_tightens_a_valid_bound(self):
        layer = dict(self.layer, cohesion_pa=2e7, friction_rad=.5, mean_pressure_pa=[2e8, 2e8])
        prep = a.w.prepare([layer], 4, closure=a.w.SUPPLIED)
        law = a.w.WeakeningLaw(1., 3., .25, .25)
        strong = a.prepare(prep, law, np.zeros(prep.size), self.drive)
        weak = a.prepare(prep, law, np.full(prep.size, 3.), self.drive)
        self.assertLess(weak.balance.yield_force, strong.balance.yield_force)
        actual = a.m.solve(prep, law, np.full(prep.size, 4.), self.drive)
        upper = weak.balance.yield_force+weak.balance.coefficient*a.fraction(actual["velocity_m_s"])
        self.assertLess(actual["force"], float(upper))

    def test_large_near_flat_resistance_not_omitted(self):
        layer = dict(self.layer, cohesion_pa=1e11, plastic_viscosity_pa_s=1e10,
                     creep=[dict(a=1e-60, n=1., energy_j_mol=0.)])
        prep = a.w.prepare([layer], 4, closure=a.w.SUPPLIED)
        env = a.prepare(prep, a.w.OFF, self.history, self.drive)
        out = a.admit(env, prep, a.w.OFF, self.history, self.drive, duration_s=1e12,
                      used_strain=0., relative_tolerance=.01, displacement_limit_m=100.)
        self.assertEqual(out["status"], "NOT_CERTIFIED_BY_BOUND")

    def test_noninteger_mixed_exponents_need_no_fit(self):
        layer = dict(self.layer, creep=self.layer["creep"]+[dict(a=1e-45, n=3.5, energy_j_mol=0.)])
        prep = a.w.prepare([layer], 4, closure=a.w.SUPPLIED)
        env = a.prepare(prep, a.w.OFF, self.history, self.drive)
        self.assertEqual(env.balance, self.envelope.balance)
        actual = a.m.solve(prep, a.w.OFF, self.history, self.drive)
        self.assertLess(actual["force"], float(env.balance.coefficient)*actual["velocity_m_s"])

    def test_cancel_deadline_and_inputs_untouched(self):
        cancelled = threading.Event()
        cancelled.set()
        with self.assertRaises(CancelledError):
            self.check(cancel=cancelled)
        with self.assertRaises(RuntimeError):
            self.check(deadline=time.perf_counter()-1)
        before = self.history.copy()
        self.check()
        np.testing.assert_array_equal(self.history, before)


if __name__ == "__main__":
    unittest.main()
