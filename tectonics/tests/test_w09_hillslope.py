"""Independent H1/H2 controls, finite soil and shared-face provenance accounts."""
from concurrent.futures import CancelledError
from dataclasses import replace
import json
import math
from pathlib import Path
from threading import Event
import unittest
from unittest.mock import patch

import numpy as np

from atlas_tectonics._validation import TectonicsError
from atlas_tectonics.resources import MemoryLimitError, WorkBudget
from atlas_tectonics.w09_hillslope import PreparedHillslope, SoilTag, roering_flux


CASES = json.loads((Path(__file__).parents[1]/'cases/w09_surface_processes_r1.json').read_text(encoding='utf8'))
H1 = next(c for c in CASES['controls'] if c['id'].startswith('W09-H1-'))
H2 = next(c for c in CASES['controls'] if c['id'].startswith('W09-H2-'))
CAP = 128*1024**2
MEASUREMENTS = {}


def tag(name='A', rho=2500., heat=-100.):
    return SoilTag(name,rho,heat,-1000.,'synthetic-origin-'+name,'synthetic-signed-reference')


def model(areas,faces,distances,widths,**kw):
    return PreparedHillslope(areas,faces,distances,widths,
        diffusivity_m2_s=kw.pop('diffusivity_m2_s',0.03),
        critical_slope=kw.pop('critical_slope',1.),
        frame_id='synthetic-orthogonal-SI',datum_id='synthetic-z-up',
        source_id='synthetic-H1-H2',**kw)


def sinusoid(n):
    edges = np.linspace(0.,1.,n+1)
    means = (np.cos(math.pi*edges[:-1])-np.cos(math.pi*edges[1:]))/(math.pi/n)
    faces = [[i,i+1] for i in range(n-1)]+[[0,-1],[n-1,-1]]
    return model(np.full(n,1/n),faces,[1/n]*(n-1)+[0.5/n]*2,np.ones(n+1),
        diffusivity_m2_s=H2['diffusivity_m2_s'],critical_slope=1e6,
        boundary_elevations_m=np.full(n+1,10.)),means


class HillslopeTests(unittest.TestCase):
    def assert_balance(self,state):
        for k,t in enumerate(state.tags):
            for multiplier in (1.,t.specific_enthalpy_J_kg):
                terms = [float(state.initial_mass_kg[k])*multiplier,
                         -float(state.exported_mass_kg[k])*multiplier,
                         *(-float(x)*multiplier for x in state.mass_kg[:,k])]
                self.assertLessEqual(abs(math.fsum(terms)),
                    128*np.finfo(float).eps*math.fsum(abs(x) for x in terms))

    def test_h1_exact_nonlinear_flux_and_solid_conversion(self):
        q = roering_flux(H1['slope'],H1['diffusivity_m2_s'],H1['critical_slope'])
        self.assertAlmostEqual(q,H1['expected_downslope_bulk_flux_m2_s'],places=14)
        self.assertAlmostEqual(q*(1-H1['donor_porosity']),H1['expected_downslope_solid_flux_m2_s'],places=14)
        self.assertEqual(roering_flux(0.,0.03,1.),0.)
        self.assertEqual(roering_flux(40.,0.03,1.,mobile=False),0.)
        with self.assertRaisesRegex(TectonicsError,'failure law'):
            roering_flux(1.,0.03,1.)
        with model([1.,1.],[[0,1]],[1.],[2.]) as p:
            s = p.initial_state([0.5,0.],[[1500.],[1500.]],[tag()])
            self.assertAlmostEqual(p.face_bulk_flux_m2_s(s)[0],q,places=14)

    def test_bare_cliff_unchanged_and_mobile_critical_refused(self):
        with model([1.,1.],[[0,1]],[1.],[1.]) as p:
            bare = p.initial_state([40.,0.],[[0.],[0.]],[tag()])
            result = p.advance(bare,10.)
            np.testing.assert_array_equal(p.heights(result.state),[40.,0.])
            np.testing.assert_array_equal(result.face_tag_mass_kg,[[0.]])
            covered = p.initial_state([1.,0.],[[1500.],[1500.]],[tag()])
            before = covered.state_id
            with self.assertRaisesRegex(TectonicsError,'failure law'):
                p.advance(covered,1.)
            self.assertEqual(covered.state_id,before)

    def test_finite_event_constrained_endpoint_and_no_double_payment(self):
        # At exhaustion z=base=0.5, bulk q=.02 and solid q=.012.
        # One BE interval's independent event equation is t=V0/q(base).
        with model([1.],[[0,-1]],[1.],[1.],boundary_elevations_m=[0.]) as p:
            s = p.initial_state([0.5],[[3.]],[tag()])
            r = p.advance(s,1.)
            self.assertEqual(r.status,'DEPLETED')
            self.assertAlmostEqual(r.state.time_s,0.1,places=12)
            self.assertEqual(r.depletion_events[0].cell_ids,(0,))
            self.assertEqual(r.state.mass_kg[0,0],0.)
            self.assertAlmostEqual(r.exported_mass_kg[0],3.,places=12)
            self.assertAlmostEqual(r.exported_enthalpy_J[0],-300.,places=10)
            again = p.advance(r.state,0.9)
            self.assertEqual(again.status,'COMPLETE')
            self.assertEqual(again.exported_mass_kg[0],0.)
            np.testing.assert_array_equal(again.state.exported_mass_kg,r.state.exported_mass_kg)
            self.assertEqual(again.state.tags,s.tags)
            self.assert_balance(r.state); self.assert_balance(again.state)

    def test_evolving_flux_is_implicit_and_time_refines(self):
        # Two equal cells, phi=.4: ds/dt=-2 D s/(1-s^2).
        # Its independent implicit analytic solution obeys log(s)-s^2/2=C-2Dt.
        initial = 0.5
        lo,hi = 0.,initial
        target = math.log(initial)-initial**2/2-0.06
        for _ in range(80):
            mid = (lo+hi)/2
            if math.log(mid)-mid**2/2 > target: hi=mid
            else: lo=mid
        exact = (lo+hi)/2
        errors=[]
        with model([1.,1.],[[0,1]],[1.],[1.]) as p:
            s = p.initial_state([0.,0.],[[2250.],[1500.]],[tag()])
            one=p.advance(s,1.)
            heights=p.heights(one.state)
            snew=heights[0]-heights[1]
            qend=roering_flux(snew,0.03,1.)
            self.assertAlmostEqual(one.face_tag_mass_kg[0,0],qend*1500.,places=10)
            self.assertGreater(abs(one.face_tag_mass_kg[0,0]-30.),0.1)
            for parts in (16,32,64):
                result=p.advance(s,1.,partitions=parts)
                z=p.heights(result.state)
                errors.append(abs(z[0]-z[1]-exact)/exact)
                self.assert_balance(result.state)
        self.assertLess(errors[-1],0.01)
        self.assertGreater(errors[0]/errors[1],1.5)
        self.assertGreater(errors[1]/errors[2],1.5)
        MEASUREMENTS['nonlinear_temporal_relative_errors_16_32_64'] = errors

    def test_closed_unequal_geometry_mixture_signed_enthalpy_conserves(self):
        tags=(tag('A',2500.,-100.),tag('B',3000.,200.))
        with model([2.,1.,3.],[[0,1],[1,2]],[2.,1.],[3.,2.]) as p:
            s=p.initial_state([0.8,0.5,0.],[[1000.,1200.],[500.,600.],[1500.,1800.]],tags,porosity=[0.4,0.3,0.2])
            result=p.advance(s,1.,partitions=8)
            self.assert_balance(result.state)
            np.testing.assert_array_equal(result.exported_mass_kg,[0.,0.])
            np.testing.assert_array_equal(result.state.base_m,s.base_m)
            self.assertEqual(result.state.tags,tags)
            self.assertTrue(np.any(result.face_tag_mass_kg))
            for i in range(3):
                delta=np.zeros(2)
                for j,(a,b) in enumerate(p.faces):
                    if i==a: delta-=result.face_tag_mass_kg[j]
                    if i==b: delta+=result.face_tag_mass_kg[j]
                np.testing.assert_allclose(result.state.mass_kg[i],s.mass_kg[i]+delta,rtol=1e-13,atol=1e-12)

    def test_open_faces_export_without_invented_supply(self):
        with model([1.],[[0,-1],[0,-1]],[1.,1.],[1.,2.],boundary_elevations_m=[0.,3.]) as p:
            s=p.initial_state([0.],[[300.]],[tag()])
            r=p.advance(s,1.)
            self.assertGreater(r.exported_mass_kg[0],0.)
            self.assertEqual(r.face_tag_mass_kg[1,0],0.)
            self.assert_balance(r.state)

    def test_h2_cell_mean_spatial_refinement(self):
        errors=[]
        for n in (8,16,32):
            p,means=sinusoid(n)
            with p:
                z0=10.+0.01*means
                s=p.initial_state(np.zeros(n),(z0*0.6*2500/n)[:,None],[tag()])
                r=p.advance(s,1.,partitions=256)
                exact=H2['final_amplitude_m']*means
                errors.append(float(np.linalg.norm(p.heights(r.state)-10.-exact)/np.linalg.norm(exact)))
                self.assert_balance(r.state)
                self.assertGreater(r.exported_mass_kg[0],0.)
        self.assertLess(errors[-1],0.01)
        self.assertGreater(errors[0]/errors[1],1.5)
        self.assertGreater(errors[1]/errors[2],1.5)
        MEASUREMENTS['H2_spatial_relative_errors_8_16_32'] = errors

    def test_h2_time_refinement_separates_spatial_error(self):
        n=32
        p,means=sinusoid(n)
        errors=[]
        with p:
            z0=10.+0.01*means
            s=p.initial_state(np.zeros(n),(z0*0.6*2500/n)[:,None],[tag()])
            # Exact semidiscrete FV eigenmode isolates time error at fixed mesh.
            # This is separate from H2's continuum cell-mean comparison above.
            eigenvalue=4*n*n*math.sin(math.pi/(2*n))**2
            semidiscrete=0.01*math.exp(-0.01*eigenvalue)*means
            for parts in (16,32,64):
                r=p.advance(s,1.,partitions=parts)
                evolved=p.heights(r.state)-10.
                errors.append(float(np.linalg.norm(evolved-semidiscrete)/np.linalg.norm(semidiscrete)))
                continuum=H2['final_amplitude_m']*means
                self.assertLess(np.linalg.norm(evolved-continuum)/np.linalg.norm(continuum),0.01)
                self.assert_balance(r.state)
        self.assertGreater(errors[0]/errors[1],1.5)
        self.assertGreater(errors[1]/errors[2],1.5)
        MEASUREMENTS['H2_temporal_relative_errors_16_32_64'] = errors

    def test_immutable_prepared_inputs_latest_reuse_and_cumulative_bound(self):
        areas=np.ones(2)
        with model(areas,[[0,1]],[1.],[1.]) as p:
            areas[0]=4.
            self.assertEqual(p.areas_m2[0],1.)
            s=p.initial_state([0.2,0.],[[1500.],[1500.]],[tag()],accepted_intervals=254)
            r=p.advance(s,1.,partitions=2)
            self.assertIs(r,p.advance(s,1.,partitions=2))
            self.assertEqual(p.statistics()['latest_hits'],1)
            self.assertEqual(r.state.accepted_intervals,256)
            with self.assertRaises(TectonicsError):p.advance(r.state,1.)
            with self.assertRaises(ValueError):r.state.mass_kg.flags.writeable=True
            with self.assertRaises(AttributeError):p.critical_slope=2.
            with self.assertRaises(TectonicsError):p.advance(s,1.,partitions=True)

    def test_cancellation_is_atomic_and_accounted_memory_released(self):
        budget=WorkBudget(CAP)
        p=model([1.,1.],[[0,1]],[1.],[1.],budget=budget)
        s=p.initial_state([0.2,0.],[[1500.],[1500.]],[tag()])
        before=s.state_id
        cancel=Event();cancel.set()
        with self.assertRaises(CancelledError):p.advance(s,1.,cancel=cancel)
        self.assertEqual(s.state_id,before)
        self.assertEqual(p.statistics()['computed_intervals'],0)
        p.close()
        self.assertEqual(budget.reserved_bytes,0)
        with self.assertRaises(TectonicsError):p.advance(s,1.)
        with self.assertRaises(MemoryLimitError):
            model([1.],[[0,-1]],[1.],[1.],boundary_elevations_m=[0.],budget=WorkBudget(1024))

    def test_near_critical_evolution_and_inflight_cancellation(self):
        with model([1.,1.],[[0,1]],[1.],[1.]) as p:
            s=p.initial_state([0.,0.],[[2985.],[1500.]],[tag()])
            r=p.advance(s,1.)
            self.assertLess(p.heights(r.state)[0]-p.heights(r.state)[1],0.99)
            self.assert_balance(r.state)
            cancel=Event()
            previous=p._solve
            def cancelled(*args,**kwargs):
                cancel.set()
                return previous(*args,**kwargs)
            before=s.state_id
            with patch.object(p,'_solve',side_effect=cancelled):
                with self.assertRaises(CancelledError):p.advance(s,2.,cancel=cancel)
            self.assertEqual(s.state_id,before)
            cancel.clear()
            self.assertIs(r,p.advance(s,1.))

    def test_source_drift_refuses_cache_and_wrong_model_refuses_state(self):
        with model([1.,1.],[[0,1]],[1.],[1.]) as p:
            s=p.initial_state([0.2,0.],[[1500.],[1500.]],[tag()])
            p.advance(s,1.)
            from atlas_tectonics import reuse
            with patch.object(reuse,'_source_bytes',return_value={}):
                with self.assertRaisesRegex(TectonicsError,'source changed'):
                    p.advance(s,1.)
            with model([1.,1.],[[0,1]],[2.],[1.]) as changed:
                with self.assertRaisesRegex(TectonicsError,'mismatch'):changed.advance(s,1.)

    def test_invalid_geometry_and_material_metadata(self):
        for faces in ([[0,0]],[[0,2]],[[0,1],[1,0]],[[0,0.5]],[[0.,1.]],[[False,True]]):
            with self.assertRaises(TectonicsError):model([1.,1.],faces,np.ones(len(faces)),np.ones(len(faces)))
        with self.assertRaises(TectonicsError):model(np.ones(257),[[0,1]],[1.],[1.])
        with model([1.,1.],[[0,1]],[1.],[1.]) as p:
            with self.assertRaises(TectonicsError):p.initial_state([0.,0.],[[1.],[1.]],[tag()],porosity=1.)
            with self.assertRaises(TectonicsError):p.initial_state([0.,0.],[[1.,1.],[1.,1.]],[tag(),tag()])
            with self.assertRaises(TectonicsError):p.initial_state([0.,0.],[[1.,1.],[1.,1.]],[tag(),replace(tag('B'),enthalpy_reference='different')])
            with self.assertRaises(TectonicsError):p.initial_state([0.,0.],[[1.],[1.]],[replace(tag(),formation_time_s=1.)])

    def test_branching_support_refuses_unimplemented_full_2d_gradient(self):
        with self.assertRaisesRegex(TectonicsError,'branching/2D slope unsupported'):
            model(np.ones(4),[[0,1],[0,2],[0,3]],np.ones(3),np.ones(3))


if __name__ == '__main__':
    unittest.main()
