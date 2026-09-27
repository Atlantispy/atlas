"""Focused I01 column/rheology tests. SPDX-License-Identifier: AGPL-3.0-only"""
from concurrent.futures import CancelledError
from dataclasses import FrozenInstanceError
import importlib.util
import math
from pathlib import Path
import sys
import threading
import unittest

PATH = Path(__file__).resolve().parents[1]/"tools/check_i01_column.py"
SPEC = importlib.util.spec_from_file_location("i01_column", PATH)
m = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = m
SPEC.loader.exec_module(m)


class ColumnTests(unittest.TestCase):
    def law(self, laws=None, **changes):
        args = dict(temperature_k=1000., mean_pressure_pa=1e8, grain_m=.001,
            cohesion_pa=0., friction_rad=0., pore_pressure_pa=0., plastic_viscosity_pa_s=None)
        args.update(changes)
        return m.LocalLaw.prepare(laws or (m.Creep(5e-22, 1., 0.),), **args)

    def layer(self, h=10000.):
        return dict(thickness_m=h, temperature_k=[1000., 1000.],
            mean_pressure_pa=[1e8, 1e8], pore_pressure_pa=[0., 0.], grain_m=.001,
            cohesion_pa=0., friction_rad=0., plastic_viscosity_pa_s=None,
            creep=[dict(a=5e-22, n=1., energy_j_mol=0.)])

    def test_lab_invariant_and_mpa_grain_conversion(self):
        a, n, stress, rate = 1.1e5, 3.5, 100., None
        converted = m.laboratory_prefactor(a, n, stress_unit_pa=1e6)
        lab = a*stress**n
        invariant = converted*(stress*1e6/math.sqrt(3))**n
        self.assertAlmostEqual(invariant/lab, math.sqrt(3)/2, places=12)
        diffusion = m.laboratory_prefactor(1.5e9, 1., stress_unit_pa=1e6,
                                          grain_exponent=3., grain_unit_m=1e-6)
        self.assertAlmostEqual(diffusion/2.25e-15, 1., places=12)

    def test_newtonian_limit(self):
        result = self.law().solve(1e-14)
        self.assertAlmostEqual(result["stress_pa"]/2e7, 1., places=12)
        self.assertAlmostEqual(result["tangent_pa_s"]/2e21, 1., places=12)

    def test_constructed_composite_solution_real_exponent(self):
        s, e = 2.5e7, 1e-14
        law = self.law((m.Creep(.3*e/s, 1., 0.), m.Creep(.7*e/s**3.5, 3.5, 0.)))
        result = law.solve(e)
        self.assertAlmostEqual(result["stress_pa"]/s, 1., places=10)
        self.assertAlmostEqual(math.fsum(result["creep_rates_s"])/e, 1., places=10)

    def test_regularised_plasticity_matches_existing_n1_equation(self):
        # eps=tau/(2 eta_v)+(tau-Y)/(2 eta_p), active plastic branch.
        law = self.law(cohesion_pa=1e7, plastic_viscosity_pa_s=2e21)
        e, eta_v, eta_p, y = 1e-14, 1e21, 2e21, 1e7
        exact = (e+y/(2*eta_p))/(1/(2*eta_v)+1/(2*eta_p))
        result = law.solve(e)
        self.assertAlmostEqual(result["stress_pa"]/exact, 1., places=10)
        self.assertGreater(result["plastic_rate_s"], 0.)
        self.assertGreater(result["stress_pa"], y)  # not a perfect-plastic cap

    def test_yield_corner_and_zero(self):
        law = self.law(cohesion_pa=2e7, plastic_viscosity_pa_s=1e21)
        result = law.solve(1e-14)
        self.assertAlmostEqual(result["stress_pa"]/2e7, 1., places=10)
        self.assertEqual(law.solve(0.)["stress_pa"], 0.)
        self.assertIsNone(law.solve(0.)["tangent_pa_s"])

    def test_heat_and_activation_pressure_not_effective_pressure(self):
        flows = (m.Creep(6.51e-16, 3.5, 530000., 18e-6),)
        cold = self.law(flows, temperature_k=1200., mean_pressure_pa=1e9)
        warm = self.law(flows, temperature_k=1300., mean_pressure_pa=1e9)
        pressure = self.law(flows, temperature_k=1200., mean_pressure_pa=2e9)
        pore = self.law(flows, temperature_k=1200., mean_pressure_pa=1e9, pore_pressure_pa=1e9)
        self.assertLess(warm.solve(1e-15)["stress_pa"], cold.solve(1e-15)["stress_pa"])
        self.assertGreater(pressure.solve(1e-15)["stress_pa"], cold.solve(1e-15)["stress_pa"])
        self.assertEqual(cold, pore)  # no plastic branch: pore does not change creep

    def test_tangent_finite_difference(self):
        law = self.law((m.Creep(1e-40, 3.5, 0.),), cohesion_pa=1e7, plastic_viscosity_pa_s=1e21)
        e, d = 1e-14, 1e-18
        centre = law.solve(e)
        fd = (law.solve(e+d)["stress_pa"]-law.solve(e-d)["stress_pa"])/(2*d)
        self.assertLess(abs(fd/centre["tangent_pa_s"]-1), 1e-6)

    def test_constant_column_force_work_and_partition(self):
        a = m.Column([self.layer()], 8).solve(1e-14)
        b = m.Column([self.layer(2500.), self.layer(7500.)], 8).solve(1e-14)
        self.assertAlmostEqual(a["force_n_m"]/4e11, 1., places=12)
        self.assertAlmostEqual(a["work_w_m2"]/.004, 1., places=12)
        self.assertAlmostEqual(a["force_n_m"]/b["force_n_m"], 1., places=12)
        reverse = m.Column([self.layer()], 8).solve(-1e-14)
        self.assertEqual(reverse["force_n_m"], -a["force_n_m"])
        self.assertEqual(reverse["work_w_m2"], a["work_w_m2"])

    def test_bisection_parity(self):
        law = self.law((m.Creep(1e-25, 1., 0.), m.Creep(1e-40, 3.5, 0.)),
                       friction_rad=.5, plastic_viscosity_pa_s=1e21)
        for e in (1e-18, 1e-15, 1e-12):
            a, b = law.solve(e), law.solve(e, method="bisection")
            self.assertLess(abs(a["stress_pa"]/b["stress_pa"]-1), 5e-11)

    def test_invalid_and_unrepresentable_inputs(self):
        for changes in (dict(temperature_k=0.), dict(mean_pressure_pa=-1.),
                        dict(grain_m=0.), dict(friction_rad=math.pi/2),
                        dict(plastic_viscosity_pa_s=0.)):
            with self.assertRaises(ValueError):
                self.law(**changes)
        with self.assertRaises(ValueError):
            self.law().solve(-1.)
        with self.assertRaises(ValueError):
            m.Creep(1., .5, 0.)
        with self.assertRaises(ValueError):
            self.law((m.Creep(1., 1., 1e9),)).solve(1e-15)
        with self.assertRaises(ValueError):
            m.Column([self.layer()], 129)

    def test_cancel_and_prepared_immutability(self):
        event = threading.Event()
        event.set()
        column = m.Column([self.layer()], 8)
        with self.assertRaises(CancelledError):
            column.solve(1e-14, cancel=event)
        with self.assertRaises(FrozenInstanceError):
            column.order = 32


if __name__ == "__main__":
    unittest.main()
