"""Analytical I01 caloric-law checks. SPDX-License-Identifier: AGPL-3.0-only"""
from concurrent.futures import CancelledError
from dataclasses import FrozenInstanceError, replace
import importlib.util
import math
from pathlib import Path
import sys
import threading
import time
import unittest
from unittest.mock import patch

PATH = Path(__file__).resolve().parents[1]/'tools/check_i01_phase_energy.py'
SPEC = importlib.util.spec_from_file_location('i01_phase_energy_tested', PATH)
m = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = m
SPEC.loader.exec_module(m)


def model():
    # Choose melting points from a declared analytical K=(1/2,2) at 1500 K.
    tm = tuple(1/(1/1500-100/l*math.log(k)) for l, k in ((300000., .5), (600000., 2.)))
    return m.Model(('fusible', 'refractory'), (300000., 600000.), tm,
        (1/3300, 1/3500), (1/2900, 1/3100), (0., 0.), 1000., 100.,
        1000., 1e9, (600., 2600.), (0., 3.5e9), 'analytical-ideal-mixture')


class PhaseEnergyTests(unittest.TestCase):
    def setUp(self):
        self.model = model()
        self.law = m.PressureLaw(self.model, 1e9)
        self.mass = (4000., 6000.)

    def test_independent_binary_energy_and_extraction(self):
        a = m.equilibrate(self.law, self.mass, 1500.)
        self.assertAlmostEqual(sum(a.liquid_mass_kg), 2000., places=7)
        self.assertAlmostEqual(a.enthalpy_j, 5.8e9, delta=.01)
        left, payload = m.extract(a, .5)
        self.assertAlmostEqual(payload.enthalpy_j, 9e8, delta=.01)
        self.assertAlmostEqual(left.enthalpy_j, 4.9e9, delta=.01)
        self.assertAlmostEqual(sum(payload.component_mass_kg), 1000., places=7)
        recovered = m.flash(self.law, left.component_mass_kg, left.enthalpy_j)
        self.assertAlmostEqual(recovered.temperature_k, 1500., delta=1e-7)
        self.assertAlmostEqual(sum(recovered.liquid_mass_kg), 1000., delta=1e-5)
        cold = m.flash(self.law, payload.component_mass_kg, 0.)
        self.assertAlmostEqual(cold.temperature_k, 1000., delta=1e-7)
        self.assertEqual(sum(cold.liquid_mass_kg), 0.)
        self.assertAlmostEqual(a.enthalpy_j-left.enthalpy_j-cold.enthalpy_j-
            (payload.enthalpy_j-cold.enthalpy_j), 0., delta=.01)

    def test_signed_energy_datum_and_component_gauge(self):
        law = m.PressureLaw(replace(self.model, reference_temperature_k=2000.), 1e9)
        a = m.equilibrate(law, self.mass, 1500.)
        left, payload = m.extract(a, .5)
        self.assertAlmostEqual(a.enthalpy_j, -4.2e9, delta=.01)
        self.assertAlmostEqual(payload.enthalpy_j, -1e8, delta=.01)
        self.assertAlmostEqual(left.enthalpy_j, -4.1e9, delta=.01)
        self.assertAlmostEqual(m.flash(law, left.component_mass_kg, left.enthalpy_j).temperature_k, 1500., delta=1e-7)
        other = m.PressureLaw(replace(self.model, energy_offset_j_kg=(-2e5, 1e5)), 1e9)
        b = m.equilibrate(other, self.mass, 1500.)
        baseline = m.equilibrate(self.law, self.mass, 1500.)
        self.assertEqual(b.liquid_mass_kg, baseline.liquid_mass_kg)
        self.assertAlmostEqual(b.enthalpy_j-baseline.enthalpy_j, -2e8, delta=.01)

    def test_pure_latent_plateau_and_pressure_shift(self):
        law = m.PressureLaw(self.model, 2e9)
        dp = 1e9
        latent = 300000+(1/2900-1/3300)*dp
        tm = latent/(300000/self.model.melting_k[0])
        mass = (100., 0.)
        hsolid = 100*(1000*(tm-1000)+dp/3300)
        with self.assertRaisesRegex(ValueError, 'coexistence'):
            m.equilibrate(law, mass, tm)
        for f in (0., .1, .5, 1.):
            state = m.flash(law, mass, hsolid+f*100*latent)
            self.assertAlmostEqual(state.temperature_k, tm, places=10)
            self.assertAlmostEqual(sum(state.liquid_mass_kg), 100*f, places=9)
        for t in (tm-100, tm+100):
            state = m.equilibrate(law, mass, t)
            self.assertAlmostEqual(m.flash(law, mass, state.enthalpy_j).temperature_k, t, places=10)

    def test_congruent_multicomponent_plateau(self):
        mod = replace(self.model, melting_k=(1500., 1500.),
            solid_volume_m3_kg=(.0003, .0003), liquid_volume_m3_kg=(.0003, .0003))
        law = m.PressureLaw(mod, 1e9)
        latent = 4000*300000+6000*600000
        a = m.flash(law, self.mass, 5e9+.3*latent)
        self.assertEqual(a.temperature_k, 1500.)
        self.assertAlmostEqual(sum(a.liquid_mass_kg), 3000., places=8)
        self.assertIsNone(a.heat_capacity_j_k)
        left, _ = m.extract(a, .5)
        b = m.flash(law, left.component_mass_kg, left.enthalpy_j)
        self.assertAlmostEqual(sum(b.liquid_mass_kg), 1500., places=8)

    def test_chemical_equilibrium_and_heat_derivative(self):
        a = m.equilibrate(self.law, self.mass, 1500.)
        _, dh, ds, _, _ = self.law.terms(1500.)
        sm, lm = sum(a.solid_mass_kg), sum(a.liquid_mass_kg)
        for h, s, ms, ml in zip(dh, ds, a.solid_mass_kg, a.liquid_mass_kg):
            difference = h-1500*s+100*1500*math.log((ml/lm)/(ms/sm))
            self.assertAlmostEqual(difference, 0., delta=1e-6)
        dt = .01
        high = m.equilibrate(self.law, self.mass, 1500+dt)
        low = m.equilibrate(self.law, self.mass, 1500-dt)
        derivative = (high.enthalpy_j-low.enthalpy_j)/(2*dt)
        self.assertLess(abs(derivative/a.heat_capacity_j_k-1), 1e-7)
        self.assertGreaterEqual(a.heat_capacity_j_k, 1e7)
        # At fixed P, equilibrium dH=T dS, including ideal-mixing entropy.
        self.assertLess(abs((high.entropy_j_k-low.entropy_j_k)*1500/
                            (high.enthalpy_j-low.enthalpy_j)-1), 1e-7)

    def test_pressure_maxwell_identity_and_clapeyron_sign(self):
        t, dt, dp = 1500., .01, 1000.
        a = m.equilibrate(self.law, self.mass, t)
        high = m.equilibrate(m.PressureLaw(self.model, 1e9+dp), self.mass, t)
        low = m.equilibrate(m.PressureLaw(self.model, 1e9-dp), self.mass, t)
        hp = (high.enthalpy_j-low.enthalpy_j)/(2*dp)
        vt = (m.equilibrate(self.law, self.mass, t+dt).volume_m3-
              m.equilibrate(self.law, self.mass, t-dt).volume_m3)/(2*dt)
        self.assertAlmostEqual(hp, a.volume_m3-t*vt, delta=2e-7)
        self.assertLess(sum(high.liquid_mass_kg), sum(low.liquid_mass_kg))

    def test_equal_volumes_keep_partition_pressure_independent(self):
        mod = replace(self.model, liquid_volume_m3_kg=self.model.solid_volume_m3_kg)
        a = m.equilibrate(m.PressureLaw(mod, 1e9), self.mass, 1500.)
        b = m.equilibrate(m.PressureLaw(mod, 2e9), self.mass, 1500.)
        self.assertEqual(a.liquid_mass_kg, b.liquid_mass_kg)
        self.assertAlmostEqual(b.enthalpy_j-a.enthalpy_j, 1e9*a.volume_m3, delta=.01)

    def test_inversion_across_phases_and_bisection_parity(self):
        for t in (650., 1000., 1450., 1500., 1750., 2200., 2590.):
            a = m.equilibrate(self.law, self.mass, t)
            fast, _ = m._flash(self.law, self.mass, a.enthalpy_j, newton=True)
            slow, _ = m._flash(self.law, self.mass, a.enthalpy_j, newton=False)
            self.assertAlmostEqual(fast.temperature_k, t, delta=1e-7)
            self.assertAlmostEqual(slow.temperature_k, t, delta=1e-7)

    def test_empty_full_and_repeated_extraction_immutable(self):
        a = m.equilibrate(self.law, self.mass, 1500.)
        half, first = m.extract(a, .5)
        quarter, second = m.extract(half, .5)
        direct, taken = m.extract(a, .75)
        self.assertAlmostEqual(quarter.enthalpy_j, direct.enthalpy_j, delta=.01)
        self.assertAlmostEqual(first.enthalpy_j+second.enthalpy_j, taken.enthalpy_j, delta=.01)
        for actual, expected in zip(quarter.component_mass_kg, direct.component_mass_kg):
            self.assertAlmostEqual(actual, expected, places=9)
        self.assertEqual(m.extract(a, 0.)[0], a)
        hot = m.equilibrate(self.law, self.mass, 2500.)
        empty, taken = m.extract(hot, 1.)
        self.assertIsNone(empty.temperature_k)
        self.assertEqual(empty.enthalpy_j, 0.)
        self.assertEqual(taken, hot)
        self.assertEqual(m.flash(self.law, (0., 0.), 0.), empty)
        with self.assertRaises(FrozenInstanceError):
            a.enthalpy_j = 0.
        with self.assertRaises(ValueError):
            m.extract(replace(a, enthalpy_j=a.enthalpy_j+1.), .5)

    def test_scaling_and_permutation(self):
        a = m.equilibrate(self.law, self.mass, 1500.)
        b = m.equilibrate(self.law, tuple(x*10 for x in self.mass), 1500.)
        self.assertAlmostEqual(b.enthalpy_j/10, a.enthalpy_j, delta=.01)
        changes = {key:getattr(self.model, key)[::-1] for key in ('component_ids',
            'latent_j_kg', 'melting_k', 'solid_volume_m3_kg', 'liquid_volume_m3_kg', 'energy_offset_j_kg')}
        c = m.equilibrate(m.PressureLaw(replace(self.model, **changes), 1e9), self.mass[::-1], 1500.)
        self.assertEqual(c.enthalpy_j, a.enthalpy_j)
        self.assertEqual(c.liquid_mass_kg[::-1], a.liquid_mass_kg)

    def test_invalid_unsupported_and_unresolved_inputs(self):
        for kwargs in ({'cp_j_kg_k':True}, {'mixing_r_j_kg_k':0.},
                       {'latent_j_kg':(0., 1.)}, {'temperature_bounds_k':(0., 3000.)},
                       {'solid_volume_m3_kg':[.0003, .0003]}, {'source_id':''}):
            with self.assertRaises(ValueError):
                replace(self.model, **kwargs)
        with self.assertRaises(ValueError):
            m.PressureLaw(self.model, -1.)
        for t in (0., 599., 2601., float('nan'), True):
            with self.assertRaises(ValueError):
                m.equilibrate(self.law, self.mass, t)
        for amount, h in (((0.,0.), 1.), (self.mass, 1e100), (self.mass, float('inf'))):
            with self.assertRaises(ValueError):
                m.flash(self.law, amount, h)
        a = m.equilibrate(self.law, self.mass, 1500.)
        for fraction in (True, -1., 1.01, 1e-30):
            with self.assertRaises(ValueError):
                m.extract(a, fraction)

    def test_cancellation_deadline_and_exhaustion(self):
        event = threading.Event(); event.set()
        for operation in (lambda **kw:m.equilibrate(self.law,self.mass,1500.,**kw),
                          lambda **kw:m.flash(self.law,self.mass,5.8e9,**kw)):
            with self.assertRaises(CancelledError):
                operation(cancel=event)
            with self.assertRaises(TimeoutError):
                operation(deadline=time.perf_counter()-1)
        a = m.equilibrate(self.law, self.mass, 1500.)
        with self.assertRaises(CancelledError):
            m.extract(a, .5, cancel=event)
        with patch.dict(m.POLICY, {'max_iterations':1}):
            with self.assertRaisesRegex(ValueError, 'budget'):
                m.flash(self.law, self.mass, 5.8e9)


if __name__ == '__main__':
    unittest.main()
