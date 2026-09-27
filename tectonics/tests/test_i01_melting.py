"""Focused dry melting controls. SPDX-License-Identifier: AGPL-3.0-only"""
from concurrent.futures import CancelledError
from dataclasses import FrozenInstanceError
import importlib.util
import math
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import patch

PATH = Path(__file__).resolve().parents[1]/"tools/check_i01_melting.py"
SPEC = importlib.util.spec_from_file_location("i01_melting", PATH)
m = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = m
SPEC.loader.exec_module(m)


class MeltingTests(unittest.TestCase):
    def test_known_solidus_fraction_and_kelvin_units(self):
        law = m.Model()
        p = 2.
        s = 1085.7+132.9*p-5.1*p*p+273.15
        b = 1475+80*p-3.2*p*p+273.15
        self.assertEqual(law.phase(p, s)[0], 0.)
        self.assertAlmostEqual(law.phase(p, s+.2*(b-s))[0], .2**1.5, places=14)
        self.assertEqual(law.phase(p, 2500.)[0], 1.)

    def test_cpx_fraction_continuous_both_sides(self):
        law, p = m.Model(), 1.
        s, b = 1085.7+132.9-5.1+273.15, 1475+80-3.2+273.15
        fc = .15/(.5+.08*p)
        c = s+fc**(2/3)*(b-s)
        self.assertAlmostEqual(law.phase(p, c-1e-7)[0], fc, places=8)
        self.assertAlmostEqual(law.phase(p, c+1e-7)[0], fc, places=8)

    def test_derivatives_on_both_branches(self):
        law = m.Model()
        for p, t, branch in ((2., 1700., "cpx_present"), (1., 1870., "cpx_exhausted")):
            f, ft, fp, name = law.phase(p, t)
            self.assertEqual(name, branch)
            self.assertGreater(f, 0)
            dt, dp = .001, .00001
            numeric_t = (law.phase(p, t+dt)[0]-law.phase(p, t-dt)[0])/(2*dt)
            numeric_p = (law.phase(p+dp, t)[0]-law.phase(p-dp, t)[0])/(2*dp)
            self.assertAlmostEqual(ft/numeric_t, 1., places=7)
            self.assertAlmostEqual(fp/numeric_p, 1., places=7)

    def test_exact_unmelted_adiabat(self):
        law = m.Model()
        r = m.decompress(law, 3.5, .1, 1250., mass_kg=10000.)
        exact = 1250*math.exp(law.expansion(0)*(-3.4e9)/law.cp_j_kg_k)
        self.assertAlmostEqual(r["temperature_k"], exact, places=6)
        self.assertEqual(r["retained_melt_mass_kg"], 0.)

    def test_constant_expansion_independent_root_and_cpx_crossing(self):
        law = m.Model(alpha_f_k=40e-6, rho_f_kg_m3=3300.)
        r = m.decompress(law, 3.5, .1, 1780., mass_kg=10000.)
        oracle = m.constant_expansion_oracle(law, 3.5, .1, 1780.)
        self.assertLess(abs(r["temperature_k"]-oracle), .002)
        self.assertEqual(r["final_branch"], "cpx_exhausted")
        with self.assertRaises(ValueError):
            m.constant_expansion_oracle(m.Model(), 3.5, .1, 1780.)

    def test_coupled_cooling_mass_account_and_strict_reference(self):
        law = m.Model()
        r = m.decompress(law, 3.5, .1, 1693., mass_kg=10000.)
        ref = m._trajectory(law, 3.5, .1, 1693., reference=True)
        self.assertLess(abs(r["temperature_k"]-ref["temperature_k"]), .002)
        self.assertLess(abs(r["final_fraction"]-ref["final_fraction"]), 2e-6)
        self.assertLess(r["temperature_k"], 1693*math.exp(law.expansion(0)*(-3.4e9)/1000))
        self.assertGreater(r["net_produced_melt_kg"], 0.)
        self.assertEqual(r["solid_mass_kg"]+r["retained_melt_mass_kg"], 10000.)
        self.assertLess(abs(r["thermal_equation_residual_j_kg"]), .01)
        self.assertLess(abs(r["path_residual_j_kg_k"]), .003)

    def test_restart_and_reuse_no_hidden_state(self):
        law = m.Model()
        full = m.decompress(law, 3.5, .1, 1693., mass_kg=10.)
        first = m.decompress(law, 3.5, 1.5, 1693., mass_kg=10.)
        last = m.decompress(law, 1.5, .1, first["temperature_k"], mass_kg=10.)
        self.assertLess(abs(full["temperature_k"]-last["temperature_k"]), .002)
        self.assertLess(abs(full["net_produced_melt_kg"]-first["net_produced_melt_kg"]
                            -last["net_produced_melt_kg"]), 2e-5)
        self.assertEqual(full, m.decompress(law, 3.5, .1, 1693., mass_kg=10.))
        self.assertEqual(full, m.decompress(m.Model(), 3.5, .1, 1693., mass_kg=10.))
        with self.assertRaises(FrozenInstanceError):
            law.modal_cpx = .1

    def test_invalid_inputs_and_unsupported_fraction_refused(self):
        for value in (True, "300", float("nan"), -1.):
            with self.assertRaises(ValueError):
                m.Model(cp_j_kg_k=value)
        for p0, p1, t, mass in ((3.6, .1, 1693., 10.), (1., 2., 1693., 10.),
                               (1., 1., 1693., 10.), (3.5, .1, 1693., 0.),
                               (3.5, .1, 2500., 10.), (3.5, .1, True, 10.)):
            with self.assertRaises(ValueError):
                m.decompress(m.Model(), p0, p1, t, mass_kg=mass)
        with self.assertRaises(ValueError):
            m.Model(modal_cpx=.3)

    def test_cancellation_and_budgets(self):
        event = threading.Event()
        event.set()
        with self.assertRaises(CancelledError):
            m.decompress(m.Model(), 3.5, .1, 1693., mass_kg=10., cancel=event)
        for budget in ("max_steps", "max_evaluations"):
            with patch.dict(m.POLICY, {budget: 1}):
                with self.assertRaises(ValueError):
                    m.decompress(m.Model(), 3.5, .1, 1693., mass_kg=10.)


if __name__ == "__main__":
    unittest.main()
