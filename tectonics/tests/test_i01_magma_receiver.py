"""Focused I01 receiver seam checks. SPDX-License-Identifier: AGPL-3.0-only"""
from concurrent.futures import CancelledError
from dataclasses import replace
import math
from pathlib import Path
import sys
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import check_i01_magma_receiver as m
e=m.energy


class ReceiverTests(unittest.TestCase):
    def setUp(self):
        self.model,self.law=m.setup()
        self.donor=e.equilibrate(self.law,(4000.,6000.),1500.)
        self.receiver=e.equilibrate(self.law,(2000.,3000.),1000.)

    def test_pure_plateau_crystallisation_and_internal_energy(self):
        law=e.PressureLaw(replace(self.model,melting_k=(1500.,1500.)),1e9)
        donor=e.equilibrate(law,(1000.,0.),1800.)
        for cold_t,liquid in ((1000.,1000/3),(1200.,1000.)):
            receiver=e.equilibrate(law,(1000.,0.),cold_t)
            result=m.transfer(donor,receiver,1.)
            self.assertEqual(result.receiver.state.temperature_k,1500.)
            self.assertAlmostEqual(sum(result.receiver.state.liquid_mass_kg),liquid,delta=1e-7)
            self.assertAlmostEqual(result.receiver.net_crystallised_kg,1000-liquid,delta=1e-7)
            entropy=(2e6*math.log(1.5)+liquid*200-1e6*math.log(1.8)-200000
                     -1e6*math.log(cold_t/1000))
            self.assertAlmostEqual(result.receiver.entropy_production_j_k,entropy,delta=1e-7)
            self.assertAlmostEqual(result.receiver.internal_energy_residual_j,0.,delta=1e-6)
            self.assertAlmostEqual(result.receiver.boundary_work_j,
                -1e9*(1000-liquid)*(1/2900-1/3300),delta=1e-6)

    def test_exact_all_solid_final_state(self):
        law=e.PressureLaw(replace(self.model,melting_k=(1500.,1500.)),1e9)
        donor=e.equilibrate(law,(1000.,0.),1800.)
        receiver=e.equilibrate(law,(3000.,0.),1000.)
        result=m.transfer(donor,receiver,1.)
        self.assertEqual(result.receiver.state.temperature_k,1275.)
        self.assertEqual(sum(result.receiver.state.liquid_mass_kg),0.)

    def test_component_energy_and_depleted_donor(self):
        out=m.transfer(self.donor,self.receiver,.5)
        self.assertAlmostEqual(out.receiver.incoming_mass_kg,1000.,delta=1e-7)
        self.assertAlmostEqual(out.receiver.incoming_enthalpy_j,9e8,delta=.01)
        self.assertAlmostEqual(sum(out.donor.liquid_mass_kg),1000.,delta=1e-7)
        for a,b,c,d in zip(self.donor.component_mass_kg,self.receiver.component_mass_kg,
                           out.donor.component_mass_kg,out.receiver.state.component_mass_kg):
            self.assertAlmostEqual(a+b,c+d,delta=1e-8)
        self.assertLess(abs(out.donor.enthalpy_j+out.receiver.state.enthalpy_j
                            -self.donor.enthalpy_j-self.receiver.enthalpy_j),out.receiver.energy_allowance_j+.01)
        self.assertGreaterEqual(out.receiver.entropy_production_j_k,-out.receiver.entropy_allowance_j_k)

    def test_independent_binary_mixing_entropy_and_work(self):
        receiver=e.equilibrate(self.law,(0.,8000.),1000.)
        out=m.transfer(self.donor,receiver,.5).receiver
        self.assertAlmostEqual(out.state.temperature_k,1100.,delta=1e-7)
        self.assertEqual(sum(out.state.liquid_mass_kg),0.)
        self.assertAlmostEqual(out.state.component_mass_kg[0],2000/3,delta=1e-7)
        self.assertAlmostEqual(out.state.component_mass_kg[1],25000/3,delta=1e-7)
        self.assertAlmostEqual(out.entropy_production_j_k,336550.367259013,delta=.01)
        self.assertAlmostEqual(out.boundary_work_j,-40153641.9334,delta=.01)

    def test_receiving_hot_liquid_can_melt_original_solid(self):
        law=e.PressureLaw(replace(self.model,melting_k=(1500.,1500.)),1e9)
        hot=e.equilibrate(law,(1000.,0.),2500.)
        warm=e.equilibrate(law,(1000.,0.),1490.)
        out=m.transfer(hot,warm,1.).receiver
        self.assertEqual(out.state.temperature_k,1845.)
        self.assertEqual(out.net_crystallised_kg,-1000.)

    def test_unrepresentable_pv_work_refuses(self):
        law=e.PressureLaw(replace(self.model,solid_volume_m3_kg=(1e300,1e300),
            liquid_volume_m3_kg=(1e300,1e300)),1e9)
        receiver=e.equilibrate(law,(1.,1.),1000.)
        with self.assertRaises((ValueError,OverflowError)):
            m.receive_many(receiver,())

    def test_empty_and_zero_receipts_do_not_resolve_again(self):
        empty=e.flash(self.law,(0.,0.),0.)
        _,parcel=e.extract(self.donor,.5)
        with patch.object(e,'flash',side_effect=AssertionError('unnecessary inversion')):
            self.assertIs(m.receive_many(empty,(parcel,)).state,parcel)
            self.assertIs(m.receive_many(self.receiver,()).state,self.receiver)
            self.assertIs(m.transfer(self.donor,self.receiver,0.).receiver.state,self.receiver)

    def test_bulk_matches_sequential_and_permutation(self):
        parcels=tuple(e.equilibrate(self.law,(50.+i,60.),2000.+i*10) for i in range(4))
        batch=m.receive_many(self.receiver,parcels)
        sequential=self.receiver
        for p in parcels:
            sequential=m.receive_many(sequential,(p,)).state
        reverse=m.receive_many(self.receiver,parcels[::-1])
        self.assertEqual(reverse.state,batch.state)
        self.assertAlmostEqual(batch.state.temperature_k,sequential.temperature_k,delta=4e-7)
        for a,b in zip(batch.state.component_mass_kg,sequential.component_mass_kg):
            self.assertAlmostEqual(a,b,delta=1e-8)

    def test_repeated_transfer_preserves_finite_stocks(self):
        first=m.transfer(self.donor,self.receiver,.5)
        second=m.transfer(first.donor,first.receiver.state,.5)
        direct=m.transfer(self.donor,self.receiver,.75)
        self.assertEqual(second.donor,direct.donor)
        self.assertAlmostEqual(second.receiver.state.temperature_k,direct.receiver.state.temperature_k,delta=2e-7)

    def test_signed_reference_and_offsets_travel_consistently(self):
        law=e.PressureLaw(replace(self.model,reference_temperature_k=2000.,
                                 energy_offset_j_kg=(-200000.,100000.)),1e9)
        donor=e.equilibrate(law,(4000.,6000.),1500.)
        receiver=e.equilibrate(law,(2000.,3000.),1000.)
        actual=m.transfer(donor,receiver,.5)
        baseline=m.transfer(self.donor,self.receiver,.5)
        self.assertLess(actual.receiver.incoming_enthalpy_j,0.)
        self.assertAlmostEqual(actual.receiver.state.temperature_k,baseline.receiver.state.temperature_k,delta=2e-7)

    def test_changed_law_pressure_order_or_parcel_refused(self):
        _,parcel=e.extract(self.donor,.5)
        for model,p in ((replace(self.model,source_id='other'),1e9),
                        (replace(self.model,energy_offset_j_kg=(1.,0.)),1e9),
                        (replace(self.model,component_ids=self.model.component_ids[::-1]),1e9),
                        (self.model,1e9+1)):
            with self.subTest(model=model.source_id,pressure=p):
                foreign=e.equilibrate(e.PressureLaw(model,p),(100.,100.),2400.)
                with self.assertRaisesRegex(ValueError,'same pressure'):
                    m.receive_many(self.receiver,(foreign,))
        with self.assertRaisesRegex(ValueError,'only existing liquid'):
            m.receive_many(self.receiver,(self.donor,))
        for bad in (replace(parcel,enthalpy_j=parcel.enthalpy_j+1.),replace(parcel,volume_m3=0.)):
            with self.assertRaises(ValueError):
                m.receive_many(self.receiver,(bad,))

    def test_bounds_and_lost_credit_refused(self):
        parcel=e.equilibrate(self.law,(1e-20,1e-20),2400.)
        with self.assertRaisesRegex(ValueError,'resolution'):
            m.receive_many(self.receiver,(parcel,))
        for parcels in ([],(parcel,)*65,None):
            with self.assertRaises(ValueError):
                m.receive_many(self.receiver,parcels)
        with self.assertRaisesRegex(ValueError,'distinct'):
            m.transfer(self.donor,self.donor,.5)

    def test_failure_and_cancellation_leave_inputs_unchanged(self):
        before=(self.donor,self.receiver)
        with patch.object(e,'flash',side_effect=ValueError('receiver failure')):
            with self.assertRaisesRegex(ValueError,'receiver failure'):
                m.transfer(*before,.5)
        self.assertEqual(before,(self.donor,self.receiver))
        event=threading.Event(); event.set()
        with self.assertRaises(CancelledError):
            m.transfer(*before,.5,cancel=event)
        with self.assertRaises(TimeoutError):
            m.transfer(*before,.5,deadline=time.perf_counter()-1.)


if __name__=='__main__':
    unittest.main()
