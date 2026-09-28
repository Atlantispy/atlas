"""Independent pressure-work controls. SPDX-License-Identifier: AGPL-3.0-only"""
from concurrent.futures import CancelledError
from dataclasses import FrozenInstanceError, replace
import json
import math
from pathlib import Path
import sys
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
import check_i01_phase_pressure as m
import check_i01_magma_receiver as receiver
e = m.energy


class PressureTests(unittest.TestCase):
    def setUp(self):
        self.source = m.setup()
        self.model = self.source.law.model
        self.case = json.loads((m.ROOT/'cases/i01_phase_pressure_v1.json').read_text(encoding='utf-8'))
        self.pure = m.pure_fixture(self.case['pure'])

    def test_independent_pure_entropy_and_two_work_integrals(self):
        a = self.pure
        b = m.adiabatic_move(a, 0.)
        t1, t2 = 1720., 1600.
        ratio = math.log(t2/t1)
        f = .5-4*ratio
        dh = -3.15e9-1e7*(t2*ratio-t2+t1)
        work = 1e7*((t2-t1)-1600.*ratio)
        self.assertEqual(b.state.temperature_k, t2)
        self.assertAlmostEqual(sum(b.state.liquid_mass_kg)/10000, f, delta=1e-12)
        self.assertAlmostEqual(b.enthalpy_pressure_change_j, dh, delta=.0001)
        self.assertAlmostEqual(b.compression_work_j, work, delta=.0001)
        self.assertGreater(abs(dh-work), 3e9)
        self.assertLess(abs(b.entropy_residual_j_k), 1e-8)
        self.assertLess(b.work_uncertainty_j, .01)

    def test_pure_complete_freezing_and_single_phase_segments(self):
        a = self.pure
        frozen = m.adiabatic_move(a, 3e9)
        expected_t = 1720.*math.exp(.5*250/1000)
        self.assertEqual(frozen.state.liquid_mass_kg, (0.,))
        self.assertAlmostEqual(frozen.state.temperature_k, expected_t, delta=1e-9)
        returned = m.adiabatic_move(frozen.state, 0.)
        direct = m.adiabatic_move(a, 0.)
        self.assertAlmostEqual(returned.state.liquid_mass_kg[0], direct.state.liquid_mass_kg[0], delta=1e-7)
        # Heating at initial P produces a path that finishes entirely liquid.
        hot = m.flash_s(a.law, (10000.,), a.entropy_j_k+1.5e6)
        final = m.adiabatic_move(hot, 0.)
        self.assertEqual(final.state.solid_mass_kg, (0.,))
        extra = m.adiabatic_move(final.state, 1e8)
        self.assertAlmostEqual(extra.state.temperature_k, final.state.temperature_k, delta=1e-9)
        self.assertAlmostEqual(extra.compression_work_j, 0., delta=.001)

    def test_plateau_endpoints_and_congruent_mixture(self):
        pure = self.pure.law
        for fraction in (0., 1.):
            entropy = 1e7*math.log(1720/1000)+fraction*2.5e6
            state = m.flash_s(pure, (10000.,), entropy)
            self.assertAlmostEqual(sum(state.liquid_mass_kg), fraction*10000, delta=1e-8)
            self.assertAlmostEqual(state.temperature_k, 1720., delta=1e-9)
        model = replace(self.model, melting_k=(1500.,1500.))
        law = e.PressureLaw(model, 1e9)
        a = e._state(law,1500.,(3000.,4500.),(1000.,1500.))
        b = m.flash_s(law,a.component_mass_kg,a.entropy_j_k)
        self.assertEqual(b.temperature_k,1500.)
        self.assertAlmostEqual(sum(b.liquid_mass_kg),2500.,delta=1e-8)
        # Congruent at initial P is not generally congruent at the new P.
        out = m.adiabatic_move(a, .5e9)
        self.assertIsNone(e._coexistence(out.state.law,out.state.component_mass_kg))
        self.assertLess(abs(out.entropy_residual_j_k), .001)

    def test_binary_newton_bisection_reversal_and_sampled_path(self):
        a = self.source
        law = e.PressureLaw(self.model,.5e9)
        fast, nf = m._flash_s(law,a.component_mass_kg,a.entropy_j_k,newton=True)
        slow, ns = m._flash_s(law,a.component_mass_kg,a.entropy_j_k,newton=False)
        self.assertLess(nf,ns)
        self.assertAlmostEqual(fast.temperature_k,slow.temperature_k,delta=2e-7)
        out = m.adiabatic_move(a,.5e9)
        self.assertLess(out.state.temperature_k,a.temperature_k)
        self.assertGreater(sum(out.state.liquid_mass_kg),sum(a.liquid_mass_kg))
        back = m.adiabatic_move(out.state,1e9)
        self.assertAlmostEqual(back.state.temperature_k,a.temperature_k,delta=3e-7)
        # Every sample refers to the original entropy, not its previous endpoint.
        for p in (0., .5e9, 1.5e9, 3e9):
            state = m.adiabatic_move(a,p).state
            self.assertLess(abs(state.entropy_j_k-a.entropy_j_k), .001)

    def test_single_phase_and_constant_enthalpy_counterexample(self):
        a = e.equilibrate(self.source.law,(4000.,6000.),900.)
        out = m.adiabatic_move(a,.5e9)
        self.assertAlmostEqual(out.state.temperature_k,900.,delta=1e-7)
        self.assertAlmostEqual(out.enthalpy_pressure_change_j,a.volume_m3*(-.5e9),delta=.1)
        self.assertAlmostEqual(out.compression_work_j,0.,delta=.1)
        wrong = e.flash(out.state.law,a.component_mass_kg,a.enthalpy_j)
        self.assertGreater(abs(wrong.entropy_j_k-a.entropy_j_k),1e5)

    def test_equal_volume_pressure_invariance(self):
        model = replace(self.model,liquid_volume_m3_kg=self.model.solid_volume_m3_kg)
        a = e.equilibrate(e.PressureLaw(model,1e9),(4000.,6000.),1500.)
        out = m.adiabatic_move(a,0.)
        self.assertAlmostEqual(out.state.temperature_k,a.temperature_k,delta=1e-7)
        self.assertAlmostEqual(sum(out.state.liquid_mass_kg),sum(a.liquid_mass_kg),delta=1e-5)
        self.assertAlmostEqual(out.enthalpy_pressure_change_j,-a.volume_m3*1e9,delta=.1)
        self.assertAlmostEqual(out.compression_work_j,0.,delta=.1)

    def test_signed_entropy_and_energy_gauge_invariance(self):
        base = m.adiabatic_move(self.source,.5e9)
        model = replace(self.model,energy_offset_j_kg=(-2e5,1e5))
        a = e.equilibrate(e.PressureLaw(model,1e9),(4000.,6000.),1500.)
        out = m.adiabatic_move(a,.5e9)
        self.assertEqual(out.state.temperature_k,base.state.temperature_k)
        self.assertAlmostEqual(out.compression_work_j,base.compression_work_j,delta=.0001)
        negative = e.equilibrate(e.PressureLaw(replace(self.model,reference_temperature_k=2500.),1e9),
                                 (4000.,6000.),900.)
        self.assertLess(negative.entropy_j_k,0.)
        self.assertAlmostEqual(m.adiabatic_move(negative,0.).state.temperature_k,900.,delta=1e-7)

    def test_permutation_scaling_and_trace_component(self):
        base = m.adiabatic_move(self.source,.5e9)
        keys = ('component_ids','latent_j_kg','melting_k','solid_volume_m3_kg',
                'liquid_volume_m3_kg','energy_offset_j_kg')
        reverse = replace(self.model,**{k:tuple(reversed(getattr(self.model,k))) for k in keys})
        a = e.equilibrate(e.PressureLaw(reverse,1e9),(6000.,4000.),1500.)
        self.assertAlmostEqual(m.adiabatic_move(a,.5e9).state.temperature_k,base.state.temperature_k,delta=1e-7)
        a = e.equilibrate(self.source.law,(40.,60.),1500.)
        scaled = m.adiabatic_move(a,.5e9)
        self.assertAlmostEqual(scaled.compression_work_j*100,base.compression_work_j,delta=.1)
        trace = e.equilibrate(self.source.law,(1e-7,10000.),900.)
        end = m.adiabatic_move(trace,0.).state
        self.assertAlmostEqual(end.component_mass_kg[0],1e-7,delta=1e-20)

    def test_receiver_connection_and_no_solid_discard(self):
        a = e.equilibrate(self.source.law,(4000.,6000.),2100.)
        out = m.adiabatic_move(a,.5e9)
        cold = e.equilibrate(out.state.law,(2000.,3000.),1000.)
        result = receiver.receive_many(cold,(out.state,))
        before_u = a.enthalpy_j-a.law.pressure_pa*a.volume_m3
        before_u += cold.enthalpy_j-cold.law.pressure_pa*cold.volume_m3
        after_u = result.state.enthalpy_j-result.state.law.pressure_pa*result.state.volume_m3
        self.assertAlmostEqual(after_u-before_u,
            out.compression_work_j-result.boundary_work_j,delta=2.)
        mixed = m.adiabatic_move(self.source,.5e9).state
        with self.assertRaisesRegex(ValueError,'only existing liquid'):
            receiver.receive_many(cold,(mixed,))
        residue,parcel = e.extract(mixed,.5)
        delivered = receiver.receive_many(cold,(parcel,))
        self.assertAlmostEqual(sum(residue.component_mass_kg)+sum(delivered.state.component_mass_kg),15000.,delta=1e-7)

    def test_entropy_uncertainty_near_phase_disappearance(self):
        # Approach the binary solidus/liquidus from the mixed side by solving
        # K sums analytically with bisection in T, independent of the phase root.
        for solidus in (True,False):
            lo,hi = self.model.temperature_bounds_k
            for _ in range(60):
                t = (lo+hi)/2
                k = self.source.law.terms(t)[3]
                value = sum(b/ki if solidus else b*ki for b,ki in zip((.4,.6),k))
                if (value < 1) == solidus:
                    lo=t
                else:
                    hi=t
            edge = (lo+hi)/2
            # The minority component inventory is evaluated directly, avoiding
            # cancellation near either phase boundary without changing tolerances.
            t = edge+(1e-6 if solidus else -1e-6)
            state = e.equilibrate(self.source.law,(4000.,6000.),t)
            self.assertGreater(sum(state.liquid_mass_kg),0.)
            self.assertGreater(sum(state.solid_mass_kg),0.)
            self.assertTrue(math.isfinite(m.entropy_uncertainty(state)))
            recovered = m.flash_s(state.law,state.component_mass_kg,state.entropy_j_k)
            self.assertAlmostEqual(recovered.temperature_k,t,delta=1e-7)
            heat = e.flash(state.law,state.component_mass_kg,state.enthalpy_j)
            self.assertAlmostEqual(heat.temperature_k,t,delta=1e-7)

    def test_empty_same_pressure_and_immutability(self):
        same = m.adiabatic_move(self.source,1e9)
        self.assertIs(same.state,self.source)
        self.assertEqual(same.compression_work_j,0.)
        empty = e._state(self.source.law,None,(0.,0.),(0.,0.))
        out = m.adiabatic_move(empty,0.)
        self.assertIsNone(out.state.temperature_k)
        self.assertEqual(out.compression_work_j,0.)
        with self.assertRaises(FrozenInstanceError):
            same.compression_work_j=1.
        with self.assertRaises(ValueError):
            m.flash_s(empty.law,(0.,0.),1.)

    def test_forged_support_invalid_numbers_and_unresolvable_gauge(self):
        with self.assertRaisesRegex(ValueError,'state accounts'):
            m.adiabatic_move(replace(self.source,entropy_j_k=self.source.entropy_j_k+1),0.)
        for p in (-1.,4e9,math.nan,True,'0'):
            with self.assertRaises((ValueError,TypeError)):
                m.adiabatic_move(self.source,p)
        with self.assertRaisesRegex(ValueError,'outside declared'):
            m.flash_s(self.source.law,(4000.,6000.),1e20)
        huge = replace(self.model,energy_offset_j_kg=(1e30,1e30))
        a = e.equilibrate(e.PressureLaw(huge,1e9),(4000.,6000.),1500.)
        with self.assertRaisesRegex(ValueError,'energy reference'):
            m.adiabatic_move(a,.5e9)

    def test_cancellation_deadline_and_iteration_budget(self):
        event=threading.Event()
        event.set()
        with self.assertRaises(CancelledError):
            m.adiabatic_move(self.source,.5e9,cancel=event)
        with self.assertRaises(TimeoutError):
            m.adiabatic_move(self.source,.5e9,deadline=time.perf_counter()-1)
        with patch.dict(m.POLICY,max_iterations=0):
            with self.assertRaisesRegex(ValueError,'budget exhausted'):
                m.adiabatic_move(self.source,.5e9)


if __name__ == '__main__':
    unittest.main()
