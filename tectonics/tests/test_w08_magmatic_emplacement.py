"""Focused candidate tests: frozen W08 A06 plus finite accounting/refusal."""
from concurrent.futures import CancelledError
from dataclasses import FrozenInstanceError
import math
import threading
import unittest

import numpy as np

from atlas_tectonics._validation import TectonicsError
from atlas_tectonics.resources import WorkBudget, MemoryLimitError
from atlas_tectonics.magmatic_emplacement import (MagmaticPayload, EmplacementTarget, HostStock,
                                 emplace_magma, accounting_entries)


def payload(**kwargs):
    values = dict(component_ids=('a','b'),component_mass_kg=[3.,9.],enthalpy_j=-120.,
                  source_density_kg_m3=4.,source_id='supplied-thermodynamics',transfer_id='transfer-1',
                  enthalpy_source='shared-thermodynamic-closure')
    values.update(kwargs)
    return MagmaticPayload(**values)


def target(n=1, **kwargs):
    values = dict(column_ids=tuple('cell-'+str(i) for i in range(n)),area_m2=np.full(n,2./n),
                  receiving_density_kg_m3=np.full(n,3.),mass_weights=np.full(n,1./n),
                  geometry_source='supplied-footprint',frame_id='f',datum_id='d',epoch_id='e')
    values.update(kwargs)
    return EmplacementTarget(**values)


def host(t, **kwargs):
    n = len(t.column_ids)
    values = dict(component_ids=('a','b'),component_mass_kg=np.tile([5.,15.],(n,1)),
                  enthalpy_j=np.full(n,-200.),density_kg_m3=np.full(n,5.),
                  source_id='finite-host',target=t,enthalpy_source='shared-thermodynamic-closure')
    values.update(kwargs)
    return HostStock(**values)


def place(p=None,t=None,**kwargs):
    args=dict(mode='extrusive',source_id='placement-rule')
    args.update(kwargs)
    return emplace_magma(payload() if p is None else p,target() if t is None else t,**args)


class EmplacementTests(unittest.TestCase):
    def test_a06_density_volume_and_uniform_thickness(self):
        r=place()
        self.assertEqual(r.payload.mass_kg,12.)
        self.assertEqual(r.payload.source_volume_m3,3.)
        np.testing.assert_array_equal(r.incoming,[[12.,-120.,4.]])
        np.testing.assert_array_equal(r.geometry,[[2.,0.,4.,4.,6.]])
        self.assertEqual(r.descriptor()['receiving_volume_m3'],4.)

    def test_a06_spatial_levels_preserve_extensive_accounts(self):
        for n in (8,16,32):
            with self.subTest(n=n):
                r=place(t=target(n))
                self.assertEqual(math.fsum(r.incoming[:,0]),12.)
                self.assertEqual(math.fsum(r.incoming[:,1]),-120.)
                self.assertEqual(math.fsum(r.incoming[:,2]),4.)
                self.assertEqual(math.fsum(r.geometry[:,0]*r.target.area_m2),4.)
                np.testing.assert_array_equal(r.geometry[:,0],np.full(n,2.))
                self.assertEqual(math.fsum(r.incoming_component_mass_kg[:,0]),3.)
                self.assertEqual(math.fsum(r.incoming_component_mass_kg[:,1]),9.)

    def test_nonuniform_weights_and_variable_density_use_mass_not_volume(self):
        t=target(3,area_m2=[1.,2.,4.],receiving_density_kg_m3=[2.,3.,6.],mass_weights=[.25,.25,.5])
        r=place(t=t)
        np.testing.assert_array_equal(r.incoming[:,0],[3.,3.,6.])
        np.testing.assert_array_equal(r.incoming[:,2],[1.5,1.,1.])
        np.testing.assert_array_equal(r.geometry[:,0],[1.5,.5,.25])
        self.assertEqual(math.fsum(r.incoming[:,2]),3.5)

    def test_underplating_is_explicit_basal_volume(self):
        r=place(mode='underplating')
        np.testing.assert_array_equal(r.geometry,[[2.,4.,0.,4.,6.]])
        self.assertNotEqual(r.result_id,place().result_id)

    def test_replacement_removes_finite_host_mass_components_and_signed_enthalpy(self):
        t=target()
        h=host(t,component_mass_kg=[[10.,30.]],enthalpy_j=[-400.])
        r=place(t=t,mode='replacement',host=h,host_destination_id='host-export')
        np.testing.assert_array_equal(r.outgoing_host,[[20.,-200.,4.]])
        np.testing.assert_array_equal(r.outgoing_host_component_mass_kg,[[5.,15.]])
        np.testing.assert_array_equal(r.remaining_host,[[20.,-200.,4.]])
        np.testing.assert_array_equal(r.remaining_host_component_mass_kg,[[5.,15.]])
        # New12 minus outgoing20, not the sum of both accounts.
        np.testing.assert_array_equal(r.geometry,[[2.,0.,0.,0.,-4.]])
        np.testing.assert_array_equal(h.component_mass_kg,[[10.,30.]])
        self.assertEqual(r.descriptor()['heat_source_j'],0.)

    def test_displacement_pays_equal_volume_and_names_destination(self):
        t=target(); r=place(t=t,mode='host-displacement',host=host(t),host_destination_id='displaced-rock')
        np.testing.assert_array_equal(r.outgoing_host,[[20.,-200.,4.]])
        np.testing.assert_array_equal(r.remaining_host,[[0.,0.,0.]])
        self.assertEqual(r.host_destination_id,'displaced-rock')
        self.assertEqual(r.descriptor()['thermal_owner'],'advected-isobaric-enthalpy-inventory-only')

    def test_host_full_exhaustion_rounding_keeps_nonnegative_stock(self):
        t=target(receiving_density_kg_m3=[7.])
        h=host(t,component_mass_kg=[[3.,9.]],density_kg_m3=[7.])
        r=place(t=t,mode='replacement',host=h,host_destination_id='outside')
        np.testing.assert_array_equal(r.remaining_host,[[0.,0.,0.]])
        self.assertEqual(r.outgoing_host[0,0],12.)

    def test_replacement_combined_mass_components_and_enthalpy_close(self):
        for n in (8,16,32):
            with self.subTest(n=n):
                w=np.arange(1.,n+1); w/=math.fsum(w)
                t=target(n,mass_weights=w)
                h=host(t,enthalpy_j=np.linspace(-3.,7.,n))
                p=payload(enthalpy_j=100.)
                r=place(p,t,mode='replacement',host=h,host_destination_id='outgoing')
                for j in (0,1):
                    initial=math.fsum(h.fields[:,j])+((p.mass_kg,p.enthalpy_j)[j])
                    final=math.fsum(np.concatenate((r.incoming[:,j],r.outgoing_host[:,j],r.remaining_host[:,j])))
                    self.assertAlmostEqual(initial,final,places=11)
                for j in range(2):
                    initial=math.fsum(h.component_mass_kg[:,j])+p.component_mass_kg[j]
                    final=math.fsum(np.concatenate((r.incoming_component_mass_kg[:,j],
                        r.outgoing_host_component_mass_kg[:,j],r.remaining_host_component_mass_kg[:,j])))
                    self.assertAlmostEqual(initial,final,places=11)
                np.testing.assert_array_equal(r.geometry[:,3],np.zeros(n))

    def test_long_identity_text_is_admitted_before_serialisation(self):
        p=payload(source_id='x'*4000)
        budget=WorkBudget(100000)
        with self.assertRaises(MemoryLimitError):
            place(p,budget=budget)
        self.assertEqual(budget.reserved_bytes,0)

    def test_host_accommodation_refusals(self):
        t=target()
        for options in (dict(mode='intrusive'),dict(mode='replacement'),
                        dict(mode='host-displacement',host=host(t)),
                        dict(mode='replacement',host=host(t),host_destination_id='cell-0'),
                        dict(mode='replacement',host=host(t,component_mass_kg=[[1.,2.]]),host_destination_id='x'),
                        dict(mode='underplating',host=host(t)),
                        dict(mode='extrusive',host_destination_id='unused')):
            with self.subTest(options=options),self.assertRaises(TectonicsError):
                place(t=t,**options)

    def test_host_target_and_component_catalogue_must_match(self):
        t=target()
        for h in (host(target(geometry_source='changed')),
                  host(t,component_ids=('b','a'))):
            with self.assertRaises(TectonicsError):
                place(t=t,mode='replacement',host=h,host_destination_id='x')

    def test_enthalpy_convention_mismatch_refused_and_identity_bound(self):
        t=target(); p=payload(); h=host(t)
        other_p=payload(enthalpy_source='other-thermodynamic-closure')
        other_h=host(t,enthalpy_source='other-thermodynamic-closure')
        self.assertNotEqual(p.payload_id,other_p.payload_id)
        self.assertNotEqual(h.stock_id,other_h.stock_id)
        with self.assertRaisesRegex(TectonicsError,'enthalpy source'):
            place(p,t,mode='replacement',host=other_h,host_destination_id='x')
        base=place(p,t,mode='replacement',host=h,host_destination_id='x')
        compatible=place(other_p,t,mode='replacement',host=other_h,host_destination_id='x')
        self.assertNotEqual(base.result_id,compatible.result_id)
        self.assertEqual(compatible.descriptor()['enthalpy_source'],'other-thermodynamic-closure')
        for constructor in (lambda: payload(enthalpy_source=''),lambda: host(t,enthalpy_source='')):
            with self.assertRaises(TectonicsError): constructor()

    def test_exact_nonbinary_partition_totals(self):
        t=target(3,mass_weights=[.1,.2,.7])
        p=payload(component_mass_kg=[.2,.3],enthalpy_j=-.7)
        r=place(p,t)
        self.assertEqual(math.fsum(r.incoming[:,0]),p.mass_kg)
        self.assertEqual(math.fsum(r.incoming[:,1]),p.enthalpy_j)
        for j in range(2):
            self.assertEqual(math.fsum(r.incoming_component_mass_kg[:,j]),p.component_mass_kg[j])

    def test_zero_weight_and_empty_payload(self):
        t=target(2,mass_weights=[1.,0.])
        np.testing.assert_array_equal(place(t=t).incoming[1],np.zeros(3))
        r=place(payload(component_mass_kg=[0.,0.],enthalpy_j=0.),t)
        np.testing.assert_array_equal(r.incoming,np.zeros((2,3)))
        with self.assertRaises(TectonicsError):
            payload(component_mass_kg=[0.,0.],enthalpy_j=1.)

    def test_invalid_weights_area_density_and_nonfinite_payload_refused(self):
        for args in (dict(mass_weights=[-1.]),dict(mass_weights=[.5]),dict(mass_weights=[np.nan]),
                     dict(area_m2=[0.]),dict(receiving_density_kg_m3=[0.])):
            with self.subTest(args=args),self.assertRaises(TectonicsError): target(**args)
        for args in (dict(component_mass_kg=[-1.,2.]),dict(enthalpy_j=np.inf),
                     dict(source_density_kg_m3=0.),dict(component_mass_kg=[np.nan,2.])):
            with self.subTest(args=args),self.assertRaises(TectonicsError): payload(**args)

    def test_detached_immutable_inputs_outputs_and_descriptors(self):
        c=np.array([3.,9.]); w=np.array([.25,.75]); a=np.array([1.,1.])
        p=payload(component_mass_kg=c); t=target(2,mass_weights=w,area_m2=a)
        c[:]=99.; w[:]=.5; a[:]=20.
        r=place(p,t)
        np.testing.assert_array_equal(r.incoming[:,0],[3.,9.])
        self.assertEqual(p.mass_kg,12.)
        for arr in (p.component_mass_kg,t.mass_weights,r.incoming,r.geometry,r.incoming_component_mass_kg):
            with self.assertRaises(ValueError): arr.setflags(write=True)
        with self.assertRaises(FrozenInstanceError): r.mode='changed'
        d=r.descriptor(); d['mode']='changed'
        self.assertEqual(r.mode,'extrusive')
        view=r.incoming; view.shape=(6,)
        self.assertEqual(r.incoming.shape,(2,3))

    def test_changed_density_geometry_source_and_mode_change_identity(self):
        base=place()
        alternatives=(place(payload(source_density_kg_m3=5.)),
            place(t=target(receiving_density_kg_m3=[4.])),
            place(t=target(geometry_source='new')),place(source_id='new-rule'),
            place(mode='underplating'),place(payload(transfer_id='other-transfer')))
        for other in alternatives: self.assertNotEqual(base.result_id,other.result_id)
        a=place(t=target(2,mass_weights=[.25,.75]))
        b=place(t=target(2,mass_weights=[.75,.25]))
        self.assertNotEqual(a.result_id,b.result_id)

    def test_single_owner_accounts_refuse_replayed_transfer_and_host(self):
        a=place(); b=place(mode='underplating')
        with self.assertRaisesRegex(TectonicsError,'transfer'): accounting_entries((a,b))
        t=target(); h=host(t,component_mass_kg=[[10.,30.]])
        a=place(t=t,mode='replacement',host=h,host_destination_id='x')
        b=place(payload(transfer_id='second'),t,mode='replacement',host=h,host_destination_id='x')
        with self.assertRaisesRegex(TectonicsError,'host stock'): accounting_entries((a,b))
        entries=accounting_entries((a,))
        self.assertEqual(entries[0]['entry_id'],a.result_id)
        self.assertEqual(entries[0]['transfer_id'],'transfer-1')

    def test_budget_cap_refusal_and_release_after_success_failure_cancellation(self):
        with self.assertRaises(TectonicsError): place(budget=WorkBudget(129*1024*1024))
        with self.assertRaises(MemoryLimitError): place(budget=WorkBudget(1))
        budget=WorkBudget(128*1024*1024)
        place(budget=budget)
        self.assertEqual(budget.reserved_bytes,0)
        t=target()
        with self.assertRaises(TectonicsError):
            place(t=t,mode='replacement',host=host(t,component_mass_kg=[[0.,0.]],enthalpy_j=[0.]),
                  host_destination_id='x',budget=budget)
        self.assertEqual(budget.reserved_bytes,0)
        event=threading.Event(); event.set()
        with self.assertRaises(CancelledError): place(budget=budget,cancel=event)
        self.assertEqual(budget.reserved_bytes,0)
        self.assertLessEqual(budget.peak_reserved_bytes,128*1024*1024)

    def test_parent_budget_charged_and_released(self):
        parent=WorkBudget(128*1024*1024); child=WorkBudget(1*1024*1024,parent=parent)
        place(budget=child)
        self.assertEqual(child.peak_reserved_bytes,parent.peak_reserved_bytes)
        self.assertEqual(parent.reserved_bytes,0)

    def test_numerical_underflow_overflow_refused(self):
        with self.assertRaises(TectonicsError):
            payload(component_mass_kg=[1e308,1e308])
        with self.assertRaises(TectonicsError):
            place(payload(component_mass_kg=[1e-300,0.],enthalpy_j=0.),
                  target(receiving_density_kg_m3=[1e300]))


if __name__=='__main__':
    unittest.main()
