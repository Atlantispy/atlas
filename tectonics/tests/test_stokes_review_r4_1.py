"""R4.1 review: published SI accuracy, scaling and independent physical controls.

SPDX-License-Identifier: AGPL-3.0-only
The two small-range counterexamples are arithmetic stress tests, not mantle
conditions. Every old test/case is retained. No new physical law is selected.
"""
from dataclasses import replace
from decimal import Decimal, localcontext
from pathlib import Path
import json
import tempfile
import unittest
from unittest import mock

import numpy as np
from numpy.testing import assert_allclose, assert_array_equal

from atlas_tectonics import (
    DiffusiveScales, PreparedStokes2D, StokesSolvePolicy, StokesSolution,
    reference_rheology, TectonicsError, save_stokes_solution, load_stokes_solution, face_force_from_density,
)
from atlas_tectonics.resources import WorkBudget
from atlas_tectonics.storage import ArrayStore, StoreLimits
from atlas_tectonics.stokes_execution import _factored_scale
from stokes_fixtures import unit_box, unit_scales, request, analytic


def circulation(amplitude):
    """2x2 pure circulation: A v = 16 v; p = 0, div(v)=0."""
    return (np.array([[amplitude], [-amplitude]]),
            np.array([[-amplitude, amplitude]]))


def polynomial(box):
    """Continuous quartic streamfunction, unrelated to spectral eigenmodes.

    F(t)=t-2t^3+t^4 has F=F''=0 at both ends, giving zero normal
    velocity and zero tangential normal derivative. p=P(2X-1)(Z^2-1/3).
    Exact continuous derivatives produce forces, not an operator-generated RHS.
    """
    L, H = box.width_m, box.height_m
    A, P = .2, .3
    def F(t): return t-2*t**3+t**4
    def F1(t): return 1-6*t**2+4*t**3
    def F2(t): return -12*t+12*t**2
    def F3(t): return -12+24*t
    x,z=np.meshgrid(*box.axes('force_x')); X,Z=x/L,z/H
    u=A/H*F(X)*F1(Z)
    fx=-A*(F2(X)*F1(Z)/(L*L*H)+F(X)*F3(Z)/H**3) + 2*P/L*(Z**2-1/3)
    x,z=np.meshgrid(*box.axes('force_z')); X,Z=x/L,z/H
    w=-A/L*F1(X)*F(Z)
    fz=A*(F3(X)*F(Z)/L**3+F1(X)*F2(Z)/(L*H*H)) + 2*P/H*(2*X-1)*Z
    x,z=np.meshgrid(*box.axes()); X,Z=x/L,z/H
    p=P*(2*X-1)*(Z**2-1/3)
    return fx,fz,u,w,p


class PublishedAccuracyTests(unittest.TestCase):
    def solve(self, forces, *, method='minres', scales=None, box=None, budget=None):
        box = unit_box(2) if box is None else box
        with PreparedStokes2D(box,reference_rheology('constant'),unit_scales() if scales is None else scales,
                              policy=StokesSolvePolicy(method=method),budget=budget) as p:
            return p.solve(*forces,**request(box))

    def test_minres_cannot_publish_twenty_percent_force_error(self):
        with self.assertRaisesRegex(TectonicsError,'residual gate'):
            self.solve(circulation(20*np.nextafter(0.,1.)))

    def test_direct_cannot_publish_twenty_percent_force_error(self):
        with self.assertRaisesRegex(TectonicsError,'residual gate'):
            self.solve(circulation(20*np.nextafter(0.,1.)),method='direct')

    def test_exactly_representable_subnormal_solution_is_not_banned(self):
        tiny=np.nextafter(0.,1.)
        for method in ('minres','direct'):
            with self.subTest(method=method):
                r=self.solve(circulation(32*tiny),method=method)
                assert_array_equal(r.array('u_m_s')[:,1:-1],[[2*tiny],[-2*tiny]])
                self.assertEqual(r.descriptor()['diagnostics']['momentum_linf'],0.)

    def test_small_nonzero_published_residual_is_recorded_not_internal_zero(self):
        a=1e-310;r=self.solve(circulation(a));u=r.array('u_m_s')[0,1]
        expected=abs(16*(u/a)-1)
        self.assertGreater(expected,0.)
        actual=r.descriptor()['diagnostics']['momentum_linf']
        self.assertGreater(actual,0.)
        # Independent scalar arithmetic and the ghost stencil sum in a different
        # order; compare at their binary64 cancellation error, not bit identity.
        self.assertLessEqual(abs(actual-expected),4*np.finfo(float).eps)

    def test_subnormal_reference_amplitude_does_not_change_normal_velocity(self):
        scales=DiffusiveScales('extreme-reference-only',1.,1e22,1e100,1.,1.,1.)
        r=self.solve(circulation(1e-200),scales=scales)
        self.assertEqual(r.array('u_m_s')[0,1],6.25e-302)
        self.assertEqual(r.descriptor()['diagnostics']['momentum_linf'],0.)

    def test_diffusivity_does_not_enter_this_steady_physical_problem(self):
        for method in ('minres','direct'):
            results=[]
            for k in (1.,1e10,1e22):
                s=DiffusiveScales('arbitrary-reference',1.,k,1e100,1.,1.,1.)
                results.append(self.solve(circulation(1e-200),scales=s,method=method))
            for r in results[1:]:
                for name in results[0].array_names:
                    assert_array_equal(r.array(name),results[0].array(name))

    def test_failed_publication_releases_scratch_and_plan_is_reusable(self):
        budget=WorkBudget(32<<20);box=unit_box(2)
        with PreparedStokes2D(box,reference_rheology('constant'),unit_scales(),budget=budget) as p:
            held=budget.reserved_bytes
            with self.assertRaises(TectonicsError):
                p.solve(*circulation(20*np.nextafter(0.,1.)),**request(box))
            self.assertEqual(budget.reserved_bytes,held)
            self.assertEqual(p.solve(*circulation(1.),**request(box)).array('u_m_s')[0,1],.0625)
        self.assertEqual(budget.reserved_bytes,0)

    def test_normalized_pressure_gradient_uses_original_si_forces(self):
        # Exact pure gradient with representable SI pressure; the arbitrary
        # force-reference scale must not change its magnitude.
        b=unit_box(2);s=DiffusiveScales('gradient-reference',1.,1e22,1e100,1.,1.,1.)
        r=self.solve((np.full((2,1),1e-200),np.zeros((1,2))),scales=s)
        assert_allclose(r.array('pressure_pa')/1e-200,[[-.25,.25],[-.25,.25]],atol=3e-15,rtol=0.)

    def test_subnormal_pressure_rounding_fails_publication_gate(self):
        tiny=np.nextafter(0.,1.)
        with self.assertRaisesRegex(TectonicsError,'residual gate'):
            self.solve((np.full((2,1),6*tiny),np.zeros((1,2))))

    def test_exact_subnormal_pressure_survives(self):
        tiny=np.nextafter(0.,1.)
        r=self.solve((np.full((2,1),8*tiny),np.zeros((1,2))))
        assert_array_equal(r.array('pressure_pa'),np.array([[-2,2],[-2,2]])*tiny)

    def test_zero_problem_needs_no_division_by_zero(self):
        r=self.solve(circulation(0.))
        for name in r.array_names:assert_array_equal(r.array(name),0.)
        self.assertEqual(r.descriptor()['force_amplitude_n_m3'],0.)

    def test_current_metadata_identifies_published_field_checks(self):
        r=self.solve(circulation(1.));m=r.descriptor()
        self.assertEqual(m['publication_contract'],'atlas.stokes-published-si-gates.v1')
        self.assertIn('returned SI',m['diagnostic_basis'])
        self.assertFalse(m['R4_complete']);self.assertFalse(m['physical_validation'])

    def test_unknown_publication_contract_is_not_accepted_on_restore(self):
        r=self.solve(circulation(1.));m=r.descriptor();m['publication_contract']='other'
        with self.assertRaises(TectonicsError):
            StokesSolution(m,{n:r.array(n) for n in r.array_names})

    def test_legacy_metadata_restores_without_new_acceptance_claim(self):
        r=self.solve(circulation(1.));m=r.descriptor()
        for n in ('publication_contract','diagnostic_basis','force_amplitude_n_m3'):m.pop(n)
        old=StokesSolution(m,{n:r.array(n) for n in r.array_names})
        with tempfile.TemporaryDirectory() as td:
            with ArrayStore(Path(td)/'legacy.db',StoreLimits(1024,4<<20,16<<20)) as store:
                save_stokes_solution(old,store)
                restored=load_stokes_solution(store,old.result_id)
        self.assertEqual(restored.result_id,old.result_id)
        self.assertNotIn('publication_contract',restored.descriptor())

    def test_corrected_subnormal_snapshot_round_trips_exactly(self):
        r=self.solve(circulation(32*np.nextafter(0.,1.)))
        with tempfile.TemporaryDirectory() as td:
            with ArrayStore(Path(td)/'new.db',StoreLimits(1024,4<<20,16<<20)) as store:
                save_stokes_solution(r,store);n=store.statistics()['unique_chunks']
                save_stokes_solution(r,store);self.assertEqual(store.statistics()['unique_chunks'],n)
                restored=load_stokes_solution(store,r.result_id)
        for name in r.array_names:assert_array_equal(restored.array(name),r.array(name))


class FactoredScaleTests(unittest.TestCase):
    def test_scalar_product_underflow_does_not_erase_recoverable_field(self):
        # prod(1e-200,1e-200) is not representable, but the full result is.
        assert_allclose(_factored_scale(np.array([1e200]),(1e-200,1e-200),(),'check'),[1e-200],rtol=3e-16,atol=0.)

    def test_scalar_product_overflow_does_not_destroy_finite_field(self):
        assert_allclose(_factored_scale(np.array([1e-200]),(1e200,1e200),(),'check'),[1e200],rtol=3e-16,atol=0.)

    def test_decimal_products_and_ratios_across_extremes(self):
        cases=[(1e-300,(1e-200,1e200),(1e-100,)),
               (1e200,(1e200,),(1e100,1e100)),
               (-.037,(1e-200,1e180,3.7),(1e-80,)),
               (np.nextafter(0.,1.),(2.**500,),(2.**-500,))]
        with localcontext() as c:
            c.prec=100
            for x,num,den in cases:
                expected=Decimal.from_float(float(x))
                for f in num:expected*=Decimal.from_float(f)
                for f in den:expected/=Decimal.from_float(f)
                actual=_factored_scale(np.array([x]),num,den,'decimal')[0]
                assert_allclose(actual,float(expected),rtol=6e-16,atol=0.)

    def test_exact_powers_of_two_round_trip(self):
        values=np.array([-.125,0.,.5,2.])
        a=_factored_scale(values,(2.**300,),(2.**100,),'forward')
        assert_array_equal(_factored_scale(a,(2.**100,),(2.**300,),'inverse'),values)

    def test_final_nonzero_underflow_refused(self):
        with self.assertRaisesRegex(TectonicsError,'underflows'):
            _factored_scale(np.array([np.nextafter(0.,1.)]),(.25,),(),'underflow')

    def test_final_overflow_refused(self):
        with self.assertRaisesRegex(TectonicsError,'outside finite'):
            _factored_scale(np.array([np.finfo(float).max]),(2.,),(),'overflow')

    def test_exact_zero_allowed_with_extreme_factors(self):
        assert_array_equal(_factored_scale(np.zeros(2),(1e300,1e300),(),'zero'),0.)

    def test_normal_scalar_factor_uses_bulk_multiplication(self):
        from atlas_tectonics import stokes_execution
        with mock.patch.object(stokes_execution.np,'frexp',side_effect=AssertionError('unneeded array decomposition')):
            assert_array_equal(_factored_scale(np.array([.5,-2.]),(8.,),(2.,),'normal'),[2.,-8.])

    def test_subnormal_combined_factor_avoids_scalar_multiplication(self):
        from atlas_tectonics import stokes_execution
        with mock.patch.object(stokes_execution,'_checked_scale',side_effect=AssertionError('lossy scalar scale')):
            assert_allclose(_factored_scale(np.array([1e200]),(1e-200,1e-200),(),'extreme'),[1e-200],rtol=3e-16,atol=0.)

    def test_factoring_does_not_mutate_input(self):
        a=np.array([1.,-2.]);old=a.copy()
        _factored_scale(a,(3.,),(7.,),'owned')
        assert_array_equal(a,old)


class FaceForceRangeTests(unittest.TestCase):
    def expected(self,a,b,g):
        with localcontext() as ctx:
            ctx.prec=1100
            return float((Decimal.from_float(a)+Decimal.from_float(b))*Decimal.from_float(g)/2)

    def test_unequal_subnormal_mean_does_not_round_before_gravity(self):
        t=np.nextafter(0.,1.);b=unit_box(2)
        fx,_=face_force_from_density(b,np.tile([t,2*t],(2,1)),[2.,0.])
        assert_array_equal(fx,3*t)

    def test_normal_final_force_is_not_spoiled_by_tiny_mean(self):
        t=np.nextafter(0.,1.);b=unit_box(2);g=1e100
        fx,_=face_force_from_density(b,np.tile([t,2*t],(2,1)),[g,0.])
        assert_array_equal(fx,self.expected(t,2*t,g))

    def test_large_gravity_rescues_unrepresentable_intermediate_mean(self):
        t=np.nextafter(0.,1.);b=unit_box(2)
        fx,_=face_force_from_density(b,np.tile([0.,t],(2,1)),[2.,0.])
        assert_array_equal(fx,t)

    def test_subnormal_endpoint_order_does_not_change_force(self):
        t=np.nextafter(0.,1.);b=unit_box(2)
        f,_=face_force_from_density(b,np.tile([t,2*t],(2,1)),[-1e100,0.])
        r,_=face_force_from_density(b,np.tile([2*t,t],(2,1)),[-1e100,0.])
        assert_array_equal(f,r);assert_array_equal(f,self.expected(t,2*t,-1e100))

    def test_vertical_faces_have_the_same_range_safe_interpolation(self):
        t=np.nextafter(0.,1.);b=unit_box(2)
        _,fz=face_force_from_density(b,np.array([[t,t],[2*t,2*t]]),[0.,2.])
        assert_array_equal(fz,3*t)

    def test_no_final_overflow_or_erased_force_is_returned(self):
        b=unit_box(2)
        for rho,g in [(np.finfo(float).max,2.),(np.nextafter(0.,1.),.25)]:
            with self.subTest(rho=rho),self.assertRaises(TectonicsError):
                face_force_from_density(b,np.full((2,2),rho),[g,0.])


class IndependentMechanicsTests(unittest.TestCase):
    def solve(self,b,fx,fz,scales=None):
        with PreparedStokes2D(b,reference_rheology('constant'),unit_scales() if scales is None else scales) as p:
            return p.solve(fx,fz,**request(b))

    def test_polynomial_non_spectral_manufactured_refinement(self):
        errors=[]
        for n in (8,16,32):
            b=unit_box(2*n,n,width=3.,height=1.);fx,fz,u,w,p=polynomial(b)
            r=self.solve(b,fx,fz)
            errors.append([float(np.sqrt(np.mean((r.array(key)[sl]-v)**2)))
                           for key,sl,v in [('u_m_s',(slice(None),slice(1,-1)),u),
                                           ('w_m_s',(slice(1,-1),slice(None)),w),
                                           ('pressure_pa',(slice(None),slice(None)),p)]])
        for field in range(3):
            self.assertTrue(3.6<errors[1][field]/errors[2][field]<4.5,errors)

    def test_polynomial_si_pressure_velocity_values(self):
        b=unit_box(48,24,width=3.,height=1.);fx,fz,u,w,p=polynomial(b);r=self.solve(b,fx,fz)
        assert_allclose(r.array('u_m_s')[:,1:-1],u,atol=6e-5,rtol=0.)
        assert_allclose(r.array('w_m_s')[1:-1],w,atol=6e-5,rtol=0.)
        assert_allclose(r.array('pressure_pa'),p,atol=3e-4,rtol=0.)

    def test_swap_axes_preserves_vector_pressure_solution(self):
        a=unit_box(7,9,width=2.,height=3.);b=unit_box(9,7,width=3.,height=2.)
        rng=np.random.default_rng(402);fx=rng.normal(size=(9,6));fz=rng.normal(size=(8,7))
        r=self.solve(a,fx,fz);s=self.solve(b,fz.T,fx.T)
        assert_allclose(r.array('u_m_s'),s.array('w_m_s').T,atol=3e-14,rtol=3e-12)
        assert_allclose(r.array('w_m_s'),s.array('u_m_s').T,atol=3e-14,rtol=3e-12)
        assert_allclose(r.array('pressure_pa'),s.array('pressure_pa').T,atol=3e-14,rtol=3e-12)

    def test_discrete_stress_dissipation_matches_force_work(self):
        b=unit_box(24);fx,fz,*_=polynomial(b);r=self.solve(b,fx,fz)
        u,w=r.array('u_m_s'),r.array('w_m_s');h=1/24
        exx=np.diff(u,axis=1)/h;ezz=np.diff(w,axis=0)/h
        shear=.5*(np.diff(u,axis=0)[:,1:-1]/h+np.diff(w,axis=1)[1:-1]/h)
        heat=2*(np.sum(exx**2)+np.sum(ezz**2)+2*np.sum(shear**2))*h*h
        work=(np.sum(u[:,1:-1]*fx)+np.sum(w[1:-1]*fz))*h*h
        assert_allclose(heat,work,rtol=2e-12,atol=1e-15)

    def test_published_divergence_matches_staggered_velocities(self):
        b=unit_box(15,11,width=2.,height=1.);fx,fz,*_=polynomial(b);r=self.solve(b,fx,fz)
        expected=np.diff(r.array('u_m_s'),axis=1)/(2/15)+np.diff(r.array('w_m_s'),axis=0)/(1/11)
        assert_allclose(r.array('divergence_s_1'),expected,rtol=0.,atol=1e-15)

    def test_nonuniform_vertical_force_is_balanced_by_pressure(self):
        b=unit_box(12,8,width=2.,height=3.)
        z=b.axes()[1];expected=np.broadcast_to((z*z-np.mean(z*z))[:,None],(8,12))
        fz=np.diff(expected,axis=0)/(3/8)
        r=self.solve(b,np.zeros((8,11)),fz)
        assert_allclose(r.array('pressure_pa'),expected,rtol=3e-12,atol=3e-13)
        assert_allclose(r.array('u_m_s'),0.,rtol=0.,atol=1e-13)
        assert_allclose(r.array('w_m_s'),0.,rtol=0.,atol=1e-13)

    def test_fixed_forcing_problem_is_independent_of_reference_length(self):
        b=unit_box(9,5,width=2.,height=1.);fx,fz,*_=polynomial(b);r=self.solve(b,fx,fz)
        for L in (.01,100.):
            s=self.solve(b,fx,fz,DiffusiveScales('ref',L,1.,1.,1.,1.,1.))
            for name in ('u_m_s','w_m_s','pressure_pa'):
                assert_allclose(s.array(name),r.array(name),rtol=2e-11,atol=2e-13)


if __name__=='__main__':unittest.main()
