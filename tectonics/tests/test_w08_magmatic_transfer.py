"""Frozen A04-A06 network and independent physical-control integration gates."""
from concurrent.futures import CancelledError
import gc
import hashlib
import json
import math
from pathlib import Path
import threading
import unittest

import numpy as np

from atlas_tectonics._validation import TectonicsError
from atlas_tectonics.resources import WorkBudget, MemoryLimitError
from atlas_tectonics.reuse import ExecutionContext
from atlas_tectonics.magmatic_transfer import (
    MagmaticInventory, PreparedMagmaticTransfer, MagmaticExhaustionError)
from atlas_tectonics.magmatic_thermodynamics import (
    MagmaticThermodynamics, invert_enthalpy, reheat)
from atlas_tectonics.magmatic_emplacement import (
    MagmaticPayload, EmplacementTarget, HostStock, emplace_magma, accounting_entries)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = json.loads((ROOT/'cases/w08_magmatism_r1.json').read_text())


def mixing_case(outflow=1., *, enthalpy_source='synthetic-specific-J-per-kg'):
    inv = MagmaticInventory(('export','reservoir','source'),
        ('export','reservoir','source-melt'),('initial','recharge'),
        [[0,0],[2,0],[0,10]],[0,0,100],source_id='A05-initial',
        enthalpy_source=enthalpy_source)
    q = np.zeros((3,3)); q[2,1] = 1.; q[1,0] = outflow
    return inv,q


def source_case(kind, enthalpy_j, law, *, rate=0.):
    """One 2 kg declared source of the first component beside a 2000 J reservoir."""
    row = [2.]+[0.]*(len(law.component_ids)-1)
    inv = MagmaticInventory(('a','b'),(kind,'reservoir'),law.component_ids,[row,row],
        [enthalpy_j,2000.],source_id='declared-source',enthalpy_source=law.thermodynamics_id)
    return inv,[[0.,rate],[0.,0.]]


class MagmaticTransferTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.context = ExecutionContext('scipy')
    @classmethod
    def tearDownClass(cls): cls.context.close()

    def plan(self, inv, q, **kwargs):
        return PreparedMagmaticTransfer(inv,q,source_id='frozen-A04-A05',
            context=self.context,**kwargs)

    def test_frozen_design_and_resource_scope(self):
        self.assertEqual(hashlib.sha256((ROOT/'docs/W08_REGIMES.md').read_bytes()).hexdigest(),
                         FIXTURE['design_sha256'])
        self.assertEqual(FIXTURE['max_work_bytes'],128*1024**2)
        self.assertEqual(FIXTURE['native_threads'],1)

    def test_A04_finite_throughflow_and_competing_outlets(self):
        ids = ('eruption','export','intrusion','reservoir','source')
        inv = MagmaticInventory(ids,('extrusion','export','intrusion','reservoir','source-melt'),
            ('magma',),[[0],[0],[0],[2],[10]],[0,0,0,20,100],
            source_id='A04',enthalpy_source='h10')
        q = np.zeros((5,5)); q[4,3]=2.; q[3,:3]=[1,.5,.5]
        with self.plan(inv,q) as plan:
            result=plan.evaluate(3.)
            np.testing.assert_allclose(result.remaining.mass_kg,[3,1.5,1.5,2,4],rtol=1e-14)
            np.testing.assert_allclose(result.remaining.enthalpy_j,10*result.remaining.mass_kg,rtol=1e-14)
        inv=MagmaticInventory(('a','b','source'),('intrusion','extrusion','source-melt'),
            ('magma',),[[0],[0],[10]],[0,0,100],source_id='competition',enthalpy_source='h10')
        q=np.zeros((3,3)); q[2,:2]=[2,3]
        with self.plan(inv,q) as plan:
            self.assertEqual(plan.exhaustion_duration_s,2.)
            r=plan.evaluate(2.)
            np.testing.assert_allclose(r.remaining.mass_kg,[4,6,0],rtol=2e-15,atol=0)
            self.assertEqual(r.remaining.enthalpy_j[-1],0.)
            with self.assertRaises(MagmaticExhaustionError) as err: plan.evaluate(2.001)
            self.assertEqual(err.exception.exhausted_node_ids,('source',))
        q[2,:2]=[3,2]
        with self.plan(inv,q) as plan:
            np.testing.assert_allclose(plan.evaluate(2.).remaining.mass_kg,[6,4,0],rtol=2e-15,atol=0)

    def test_A05_coupled_mixing_and_cumulative_export(self):
        inv,q=mixing_case()
        with self.plan(inv,q) as plan:
            r=plan.evaluate(3.)
            h=10*(-math.expm1(-1.5))
            self.assertAlmostEqual(r.remaining.enthalpy_j[1],2*h,places=12)
            self.assertAlmostEqual(r.remaining.enthalpy_j[0],30-2*h,places=12)
            self.assertAlmostEqual(r.remaining.component_mass_kg[1,0],2*math.exp(-1.5),places=13)
            np.testing.assert_allclose(r.remaining.component_mass_kg.sum(axis=0),[2,10],rtol=2e-15)
            # A frozen starting mixture would give zero export heat: not admitted.
            self.assertGreater(r.remaining.enthalpy_j[0],14.)

    def test_partition_invariance_fixed_and_variable_mass(self):
        for out in (1.,.5):
            results=[]
            for parts in FIXTURE['event_partitions']:
                inv,q=mixing_case(out)
                for _ in range(parts):
                    with self.plan(inv,q) as p: inv=p.evaluate(3./parts).remaining
                results.append(inv)
            for r in results[1:]:
                np.testing.assert_allclose(r.component_mass_kg,results[0].component_mass_kg,
                    atol=1e-10,rtol=0)
                np.testing.assert_allclose(r.enthalpy_j,results[0].enthalpy_j,atol=1e-9,rtol=0)
            self.assertEqual(results[-1].time_s,3.)

    def test_variable_mass_independent_analytic_oracle(self):
        inv,q=mixing_case(.5)
        with self.plan(inv,q) as p:
            self.assertFalse(p.exact)
            r=p.evaluate(3.)
            m=3.5; h=10*(1-(2/m)**2)
            self.assertLess(abs(r.remaining.enthalpy_j[1]-m*h)/30,1e-10)
            self.assertLess(abs(r.remaining.enthalpy_j[0]-(30-m*h))/30,1e-10)
            self.assertLessEqual(r.descriptor()['accepted_intervals'],256)
            self.assertTrue(np.all(r.remaining.component_mass_kg>=0))

    def test_signed_heat_and_no_second_latent_charge(self):
        inv,q=mixing_case()
        with self.plan(inv,q,heat_w=[0,-2,0]) as p:
            r=p.evaluate(3.)
            self.assertAlmostEqual(math.fsum(r.remaining.enthalpy_j),94.,places=12)
            np.testing.assert_array_equal(r.external_heat_j,[0,-6,0])
        with self.plan(inv,q) as p:
            r=p.evaluate(3.)
            self.assertAlmostEqual(math.fsum(r.remaining.enthalpy_j),100.,places=12)

    def test_reuse_identity_immutability_and_no_empty_throughflow(self):
        inv,q=mixing_case()
        with self.plan(inv,q) as p:
            r=p.evaluate(3.)
            self.assertIs(r,p.evaluate(3.))
            with self.assertRaises(ValueError): r.remaining.component_mass_kg[0,0]=9
            with self.assertRaises(ValueError): p.feed[0]=True
            with self.assertRaises(AttributeError): p.rates=q
            with self.assertRaises(TectonicsError): r.payload(0,3.)
            first=p.plan_id
        with self.plan(inv,q*2) as p: self.assertNotEqual(first,p.plan_id)
        q[0,1]=.1
        with self.assertRaises(TectonicsError): self.plan(inv,q)

    def test_declared_end_time_is_published_and_not_served_from_cache(self):
        # R1 (s16 missed #0): the kernel stamped start+duration, which can fall
        # one ulp short of the declared interval end.
        start, end = 0.020301896609317943, 0.3
        self.assertNotEqual(start+(end-start), end)
        inv = MagmaticInventory(('export','reservoir','source'),('export','reservoir','source-melt'),
            ('initial','recharge'),[[0,0],[2,0],[0,10]],[0,0,100],source_id='A05-initial',
            enthalpy_source='synthetic-specific-J-per-kg',time_s=start)
        q = np.zeros((3,3)); q[2,1] = 1.; q[1,0] = 1.
        with self.plan(inv,q) as plan:
            resummed = plan.evaluate(end-start)
            declared = plan.evaluate(end-start,end_time_s=end)
            self.assertEqual(resummed.remaining.time_s,start+(end-start))
            self.assertEqual(declared.remaining.time_s,end)
            np.testing.assert_array_equal(declared.remaining.component_mass_kg,resummed.remaining.component_mass_kg)
            with self.assertRaises(TectonicsError):
                plan.evaluate(.1,end_time_s=end)

    def test_zero_duration_and_no_transfers(self):
        inv,q=mixing_case()
        with self.plan(inv,q) as p:
            r=p.evaluate(0.)
            np.testing.assert_array_equal(r.remaining.component_mass_kg,inv.component_mass_kg)
            np.testing.assert_array_equal(r.transferred_mass_kg,[0,0])
        with self.plan(inv,np.zeros_like(q)) as p:
            np.testing.assert_array_equal(p.evaluate(5.).remaining.component_mass_kg,inv.component_mass_kg)

    def test_cancellation_and_retained_budget_lifetime(self):
        inv,q=mixing_case(); cancel=threading.Event(); cancel.set()
        with self.assertRaises(CancelledError): self.plan(inv,q,cancel=cancel)
        with self.assertRaises(MemoryLimitError): self.plan(inv,q,budget=WorkBudget(100))
        owner=WorkBudget(128*1024**2)
        with self.plan(inv,q,budget=owner) as p:
            r=p.evaluate(3.); view=r.transferred_mass_kg
            with self.assertRaises(CancelledError): p.evaluate(3.,cancel=cancel)
        del r; gc.collect()
        self.assertGreater(owner.reserved_bytes,0)
        del view; gc.collect()
        self.assertEqual(owner.reserved_bytes,0)

    def test_inventory_rebuilt_from_public_arrays_owns_its_lease(self):
        # R7 (s14 missed #2): a rebuilt inventory borrowed the first one's bytes,
        # so its reservation stayed charged until the first one was released.
        owner=WorkBudget(128*1024**2)
        def rebuilt(source):
            return MagmaticInventory(source.node_ids,source.node_kinds,source.component_ids,
                source.component_mass_kg,source.enthalpy_j,source_id='rebuilt',
                enthalpy_source=source.enthalpy_source,budget=owner)
        first=MagmaticInventory(('a','b'),('reservoir','source-melt'),('x','y'),
            [[1.,2.],[3.,4.]],[5.,6.],source_id='first',enthalpy_source='h',budget=owner)
        gc.collect(); held=owner.reserved_bytes
        self.assertGreater(held,0)
        for _ in range(3):
            again=rebuilt(first)
            self.assertEqual(owner.reserved_bytes,2*held)
            del again; gc.collect()
            self.assertEqual(owner.reserved_bytes,held)
        # A copy that outlives its source keeps its values and only its own lease.
        again=rebuilt(first)
        del first; gc.collect()
        self.assertEqual(owner.reserved_bytes,held)
        np.testing.assert_array_equal(again.component_mass_kg,[[1.,2.],[3.,4.]])
        np.testing.assert_array_equal(again.enthalpy_j,[5.,6.])
        del again; gc.collect()
        self.assertEqual(owner.reserved_bytes,0)

    def test_thermodynamic_reference_binding(self):
        # R7 3e: a zero-latent source kind is judged by temperature, so the
        # synthetic melting point lies below every stock here (300 K and above).
        law=MagmaticThermodynamics(('initial','recharge'),[10,20],[0,0],
            melting_temperature_k=290,reference_temperature_k=300,
            source_id='synthetic',provenance='A05')
        inv,q=mixing_case()
        with self.assertRaises(TectonicsError): self.plan(inv,q,thermodynamics=law)
        inv,q=mixing_case(enthalpy_source=law.thermodynamics_id)
        with self.plan(inv,q,thermodynamics=law) as p:
            state=invert_enthalpy(p.evaluate(3.).remaining.component_mass_kg,
                                 p.evaluate(3.).remaining.enthalpy_j,law)
            self.assertTrue(all(t>300 for t in state.temperature_k))

    def test_zero_latent_source_kinds_are_classified_by_temperature(self):
        # R7 3e (s14 missed #1): without latent heat the inversion gives T but no
        # liquid fraction, and either source kind used to pass at any temperature.
        zero=MagmaticThermodynamics(('x',),[10.],[0.],melting_temperature_k=350.,
            reference_temperature_k=300.,source_id='zero-latent',provenance='R7 3e')
        # Only the absent component carries latent heat: the node still has none.
        mixed=MagmaticThermodynamics(('x','y'),[10.,10.],[0.,100.],melting_temperature_k=350.,
            reference_temperature_k=300.,source_id='mixed-latent',provenance='R7 3e')
        # Cp is 20 J/K: 10/990/1000/1010/2000 J are 300.5/349.5/350/350.5/400 K.
        admitted={'source-melt':(False,False,False,True,True),
                  'source-solid':(True,True,False,False,False)}
        for law in (zero,mixed):
            at_tm=invert_enthalpy([[2.]+[0.]*(len(law.component_ids)-1)],[1000.],law)
            self.assertEqual((at_tm.temperature_k,at_tm.phase),((350.,),('single_phase',)))
            for kind,expected in admitted.items():
                for enthalpy,accept in zip((10.,990.,1000.,1010.,2000.),expected):
                    inv,q=source_case(kind,enthalpy,law)
                    with self.subTest(law=law.source_id,kind=kind,enthalpy_j=enthalpy):
                        if accept:
                            with self.plan(inv,q,thermodynamics=law): pass
                        else:
                            with self.assertRaises(TectonicsError): self.plan(inv,q,thermodynamics=law)
        # Zero-latent laws stay usable: melt above Tm still feeds the reservoir.
        inv,q=source_case('source-melt',2000.,zero,rate=.5)
        with self.plan(inv,q,thermodynamics=zero) as p:
            r=p.evaluate(2.)
            np.testing.assert_allclose(r.remaining.mass_kg,[1.,3.],rtol=1e-14)
            np.testing.assert_allclose(r.transferred_enthalpy_j,[1000.],rtol=1e-14)

    def test_reviewed_zero_latent_sources_are_refused(self):
        # The reproduced cases: Tm 1473.15 K, melt at 300.5 K, idle solid at 3000 K.
        law=MagmaticThermodynamics(('x',),[1000.],[0.],melting_temperature_k=1473.15,
            reference_temperature_k=300.,source_id='s',provenance='p')
        cold=1000.*(300.5-300.); hot=1000.*(3000.-300.); q=np.zeros((3,3)); q[1,2]=.1
        def network(solid_j,melt_j):
            return MagmaticInventory(('a','b','c'),('source-solid','source-melt','reservoir'),
                ('x',),[[1.],[1.],[1.]],[solid_j,melt_j,hot],source_id='i',
                enthalpy_source=law.thermodynamics_id)
        with self.assertRaises(TectonicsError): self.plan(network(hot,hot),q,thermodynamics=law)
        with self.assertRaises(TectonicsError): self.plan(network(cold,cold),q,thermodynamics=law)
        with self.plan(network(cold,hot),q,thermodynamics=law) as p:
            self.assertEqual(p.evaluate(1.).transferred_mass_kg[0],.1)

    def test_zero_latent_source_kind_is_checked_on_the_published_remainder(self):
        law=MagmaticThermodynamics(('x',),[10.],[0.],melting_temperature_k=350.,
            reference_temperature_k=300.,source_id='zero-latent',provenance='R7 3e')
        # An idle 350.5 K melt source losing 10 W: 350.3 K after 0.4 s, 349.5 K after 2 s.
        inv,q=source_case('source-melt',1010.,law)
        with self.plan(inv,q,heat_w=[-10.,0.],thermodynamics=law) as p:
            self.assertAlmostEqual(p.evaluate(.4).remaining.enthalpy_j[0],1006.,places=9)
            with self.assertRaises(TectonicsError): p.evaluate(2.)

    def test_physical_calorimetric_density_and_host_control(self):
        f=FIXTURE['physical_control']; s=f['scenario_not_paper_parameters']
        law=MagmaticThermodynamics(('basalt','granitoid'),
            [f['basalt_cp_j_kg_k'],f['host_cp_j_kg_k']],[400000,270000],
            melting_temperature_k=s['common_melting_temperature_k'],
            reference_temperature_k=s['reference_temperature_k'],source_id=f['source'],
            provenance=f['locator']+'; declared common-Tm surrogate')
        m=f['expected_mass_kg']; e=m*(1480*(1423.15-300)+400000)
        inv=MagmaticInventory(('intrusion','source'),('intrusion','source-melt'),law.component_ids,
            [[0,0],[m,0]],[0,e],source_id='physical-control',enthalpy_source=law.thermodynamics_id)
        with self.plan(inv,[[0,0],[m,0]],thermodynamics=law) as p:
            result=p.evaluate(1.)
            raw=result.payload(0,f['melt_density_kg_m3'])
            cooled=reheat([raw.component_mass_kg],[raw.enthalpy_j],
                [-f['expected_released_heat_j']],law)
            self.assertAlmostEqual(cooled.state.temperature_k[0],s['final_temperature_k'],places=10)
            self.assertEqual(cooled.state.liquid_fraction,(0.,))
            payload=MagmaticPayload(law.component_ids,cooled.state.component_mass_kg[0],
                cooled.state.enthalpy_j[0],f['melt_density_kg_m3'],source_id=result.result_id,
                transfer_id=raw.transfer_id,enthalpy_source=law.thermodynamics_id)
            for n in FIXTURE['space_cells']:
                target=EmplacementTarget(tuple('c'+str(i) for i in range(n)),np.full(n,2/n),
                    np.full(n,3100.),np.full(n,1/n),geometry_source='normalised-1m3-control',
                    frame_id='planar',datum_id='fixed',epoch_id='event1')
                host=HostStock(law.component_ids,np.tile([0.,2650/n],(n,1)),np.zeros(n),
                    np.full(n,2650.),source_id='finite-granitoid',target=target,
                    enthalpy_source=law.thermodynamics_id)
                placed=emplace_magma(payload,target,mode='replacement',source_id='physical-control',
                    host=host,host_destination_id='displaced-host-reservoir')
                self.assertAlmostEqual(math.fsum(placed.incoming[:,0]),m,places=10)
                self.assertAlmostEqual(math.fsum(placed.incoming[:,2]),m/3100,places=14)
                self.assertAlmostEqual(math.fsum(placed.outgoing_host[:,0]),m/3100*2650,places=10)
                self.assertAlmostEqual(math.fsum(placed.geometry[:,4]*target.area_m2),m-m/3100*2650,places=10)
                self.assertEqual(accounting_entries((placed,))[0]['heat_source_j'],0.)
                with self.assertRaises(TectonicsError): accounting_entries((placed,placed))


if __name__=='__main__': unittest.main()
