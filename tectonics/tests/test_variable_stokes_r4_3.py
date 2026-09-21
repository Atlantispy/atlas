"""Independent variable-stress/constitutive verification, not a convection benchmark.
SPDX-License-Identifier: AGPL-3.0-only
"""
from dataclasses import replace
import math
import unittest
from unittest import mock
import numpy as np
from atlas_tectonics import (PreparedVariableStokes2D, NonlinearStokesPolicy,
    PreparedStokes2D, reference_rheology, RheologyProfile, TectonicsError)
from atlas_tectonics.variable_stokes import _StressMACOperator, _stress_residuals, check_variable_support
from atlas_tectonics.constitutive import _native_law
from variable_stokes_fixtures import *


class VariableOperatorTests(unittest.TestCase):
    def setUp(self):
        self.b=unit_box(7,5,2.,1.);hx,hz=check_variable_support(self.b,unit_scales())
        self.op=_StressMACOperator(self.b,hx,hz);rng=np.random.default_rng(4203)
        self.c=np.exp(rng.uniform(-2,2,(5,7)));self.v=np.exp(rng.uniform(-2,2,(4,6)))
        self.op.set_viscosity(self.c,self.v);self.x=rng.normal(size=self.op.n)
    def test_sparse_derivatives_match_independent_stress_stencil(self):
        np.testing.assert_allclose(self.op.matvec(self.x),self.op.sparse_reference()@self.x,rtol=2e-14,atol=2e-12)
    def test_direct_wall_differences_match_padded_reference_exactly(self):
        u,w,_,_=self.op.split(self.x)
        got=self.op.strains(u,w)
        expected=(np.diff(np.pad(u,((0,0),(1,1))),axis=1)/self.op.hx,
                  np.diff(np.pad(w,((1,1),(0,0))),axis=0)/self.op.hz,
                  np.diff(u,axis=0)/self.op.hz+np.diff(w,axis=1)/self.op.hx)
        for a,b in zip(got,expected):np.testing.assert_array_equal(a,b)
        a,b,gamma=expected;xx=2*self.c*a;zz=2*self.c*b;shear=self.v*gamma
        expected_velocity=(-np.diff(xx,axis=1)/self.op.hx-
                           np.diff(np.pad(shear,((1,1),(0,0))),axis=0)/self.op.hz,
                           -np.diff(zz,axis=0)/self.op.hz-
                           np.diff(np.pad(shear,((0,0),(1,1))),axis=1)/self.op.hx)
        for a,b in zip(self.op.velocity(u,w),expected_velocity):np.testing.assert_array_equal(a,b)
    def test_sparse_assembly_matches_diagonal_reference_to_roundoff(self):
        from scipy.sparse import diags
        centre=diags(2*self.c.ravel(),format='csr')
        vertex=diags(self.v.ravel(),format='csr')
        expected=(self.op.bx.T@centre@self.op.bx+self.op.bz.T@centre@self.op.bz+
                  self.op.shear.T@vertex@self.op.shear).tocsc()
        actual=self.op.velocity_matrix()
        np.testing.assert_allclose(actual.toarray(),expected.toarray(),rtol=3e-16,atol=2e-14)
    def test_operator_is_symmetric(self):
        a=self.op.sparse_reference();np.testing.assert_allclose((a-a.T).data,0.,atol=2e-12)
    def test_velocity_energy_is_positive(self):
        x=self.x[:self.op.nv];self.assertGreater(x@(self.op.velocity_matrix()@x),0.)
    def test_independent_tensor_work(self):
        u,w,_,_=self.op.split(self.x);a,b,g=self.op.strains(u,w)
        expected=(np.sum(2*self.c*(a*a+b*b))+np.sum(self.v*g*g))*self.op.hx*self.op.hz
        self.assertAlmostEqual(self.op.energy(u,w),expected,places=10)
    def test_pressure_constant_has_no_force(self):
        x=np.zeros(self.op.n);x[self.op.nv:-1]=7
        np.testing.assert_array_equal(self.op.matvec(x)[:self.op.nv],0.)
    def test_divergence_telescopes(self):
        u,w,_,_=self.op.split(self.x)
        self.assertLess(abs(self.op.divergence(u,w).sum()),1e-13)
    def test_gradient_is_negative_divergence_adjoint(self):
        np.testing.assert_array_equal((self.op.g+self.op.d.T).toarray(),0.)
    def test_checkerboard_pressure_not_null(self):
        p=(-1.)**np.indices((self.op.nz,self.op.nx)).sum(axis=0)
        self.assertGreater(np.linalg.norm(self.op.g@p.ravel()),1.)
    def test_normal_wall_reconstruction_is_exact_zero(self):
        u,w,_,_=self.op.split(self.x);a,b,g=self.op.strains(u,w)
        self.assertEqual(a.shape,(5,7));self.assertEqual(b.shape,(5,7));self.assertEqual(g.shape,(4,6))
    def test_independent_diagnostics_do_not_call_operator_velocity(self):
        u,w,p,_=self.op.split(self.x)
        with mock.patch.object(self.op,'velocity',side_effect=AssertionError):
            ru,rw,d,e=_stress_residuals(self.op,u,w,p,np.zeros_like(u),np.zeros_like(w))
        self.assertTrue(np.isfinite(e));self.assertEqual(d.shape,(5,7))
    def test_wrong_eta_laplacian_is_distinguishable(self):
        u,w,_,_=self.op.split(self.x);au,aw=self.op.velocity(u,w)
        from atlas_tectonics.stokes import _MACOperator
        op=_MACOperator(self.b,self.op.hx,self.op.hz);lu,lw=op.velocity(u,w)
        bad=.5*(self.c[:,:-1]+self.c[:,1:])*lu
        self.assertGreater(np.max(abs(au-bad)),1.)
    def test_stress_site_constant_invariant(self):
        # Two-cell divergence-free circulation; exact eII = 2a, corner shear zero.
        b=unit_box(2);op=_StressMACOperator(b,.5,.5)
        c,v=op.invariant_sites(np.array([[1.],[-1.]]),np.array([[-1.,1.]]))
        np.testing.assert_array_equal(c,2.)
        np.testing.assert_array_equal(v,0.)  # normal-strain averages cancel at centre vertex


class VariableSolveTests(unittest.TestCase):
    def test_manufactured_variable_stress_second_order(self):
        records=[refinement(n) for n in (8,16,32)]
        for a,b in zip(records,records[1:]):
            for k in ('u_l2','w_l2','p_l2'):
                ratio=a[k]/b[k];self.assertGreater(ratio,3.7);self.assertLess(ratio,4.5)
    def test_constant_viscosity_recovers_r4_1(self):
        b=unit_box(8);from stokes_fixtures import analytic
        fx,fz,*_=analytic(b)
        with PreparedStokes2D(b,reference_rheology('constant'),unit_scales()) as old:
            expected=old.solve(fx,fz,**request(b))
        with PreparedVariableStokes2D(b,unit_scales()) as new:
            r=new.solve(fx,fz,np.ones((8,8)),np.ones((7,7)),**request(b))
        for k in ('u_m_s','w_m_s','pressure_pa'):
            np.testing.assert_allclose(r.array(k),expected.array(k),rtol=1e-9,atol=1e-11)
    def test_direct_and_gmres_different_assemblies_agree(self):
        b=unit_box(9,6,1.5,1.);a=analytic_variable(b);out=[]
        for method in ('direct','gmres'):
            with PreparedVariableStokes2D(b,unit_scales(),policy=NonlinearStokesPolicy(method=method)) as s:
                out.append(s.solve(*a[:4],**request(b)))
        for k in ('u_m_s','w_m_s','pressure_pa'):
            np.testing.assert_allclose(out[0].array(k),out[1].array(k),rtol=2e-9,atol=1e-11)
    def test_coordinate_transposition(self):
        b=unit_box(7,5,2.,1.);a=analytic_variable(b);bt=replace(b,nx=b.nz,nz=b.nx,width_m=b.height_m,height_m=b.width_m)
        with PreparedVariableStokes2D(b,unit_scales()) as s:r=s.solve(*a[:4],**request(b))
        with PreparedVariableStokes2D(bt,unit_scales()) as s:
            t=s.solve(a[1].T,a[0].T,a[2].T,a[3].T,**request(bt))
        np.testing.assert_allclose(t.array('u_m_s'),r.array('w_m_s').T,atol=1e-11)
        np.testing.assert_allclose(t.array('pressure_pa'),r.array('pressure_pa').T,atol=1e-11)
    def test_hydrostatic_pressure_with_strong_variable_eta(self):
        b=unit_box(8);x,z=np.meshgrid(*b.axes());p=z*z-.5*np.mean(z*z)*2
        fx=np.zeros((8,7));fz=np.diff(p,axis=0)/(1/8)
        with PreparedVariableStokes2D(b,unit_scales()) as s:
            r=s.solve(fx,fz,np.exp(5*x),np.exp(5*np.arange(1,8)[None,:]/8)*np.ones((7,1)),**request(b))
        self.assertLess(np.max(abs(r.array('u_m_s'))),1e-10)
        np.testing.assert_allclose(r.array('pressure_pa'),p,atol=1e-10)
    def test_sharp_contrast_work_and_no_material_smoothing(self):
        b=unit_box(12);a=analytic_variable(b);c=np.ones((12,12));c[:,6:]=1000
        v=np.ones((11,11));v[:,5:]=1000
        with PreparedVariableStokes2D(b,unit_scales()) as s:r=s.solve(a[0],a[1],c,v,**request(b))
        np.testing.assert_allclose(r.array('viscosity_cell_pa_s'),c,rtol=1e-15)
        self.assertLess(r.descriptor()['diagnostics']['work_balance_relative'],1e-9)
    def test_zero_force_preserves_positive_coefficients(self):
        b=unit_box(5)
        with PreparedVariableStokes2D(b,unit_scales()) as s:
            r=s.solve(np.zeros((5,4)),np.zeros((4,5)),np.full((5,5),2.),np.full((4,4),3.),**request(b))
            self.assertEqual(s.statistics()['factor_builds'],0)
        np.testing.assert_array_equal(r.array('u_m_s'),0.)
    def test_fixed_eta_does_not_depend_on_reference_diffusivity(self):
        b=unit_box(5);a=analytic_variable(b);out=[]
        for k in (1.,1e22):
            sc=replace(unit_scales(),diffusivity_m2_s=k)
            with PreparedVariableStokes2D(b,sc) as s:out.append(s.solve(*a[:4],**request(b)))
        for k in ('u_m_s','w_m_s','pressure_pa'):np.testing.assert_array_equal(out[0].array(k),out[1].array(k))
    def test_unit_scaling_preserves_given_si_problem(self):
        b=unit_box(6);a=analytic_variable(b);out=[]
        for L in (1.,100.):
            sc=replace(unit_scales(),length_m=L)
            with PreparedVariableStokes2D(b,sc) as s:out.append(s.solve(*a[:4],**request(b)))
        for k in ('u_m_s','w_m_s','pressure_pa'):np.testing.assert_allclose(out[0].array(k),out[1].array(k),atol=1e-10)
    def test_pressure_gauge_and_free_slip_normal_walls(self):
        b=unit_box(6);a=analytic_variable(b)
        with PreparedVariableStokes2D(b,unit_scales()) as s:r=s.solve(*a[:4],**request(b))
        self.assertLess(abs(r.array('pressure_pa').mean()),1e-12)
        np.testing.assert_array_equal(r.array('u_m_s')[:,[0,-1]],0.)
        np.testing.assert_array_equal(r.array('w_m_s')[[0,-1]],0.)


class NonlinearLawTests(unittest.TestCase):
    def test_two_by_two_independent_scalar_root(self):
        for f in (.01,1.,5.,-1.):
            with self.subTest(force=f):
                r=two_cell_solution(f);exact=independent_two_cell_amplitude(f,1.6)
                self.assertLess(abs(r.array('u_m_s')[0,1]/exact-1),3e-9)
    def test_relaxed_picard_same_physical_answer(self):
        a=two_cell_solution(1.);b=two_cell_solution(1.,relaxation=.5)
        np.testing.assert_allclose(a.array('u_m_s'),b.array('u_m_s'),rtol=3e-9,atol=1e-11)
    def test_nonlinear_uses_updated_rheology(self):
        b,sc,fx,fz,T,p=forcing(8)
        with PreparedVariableStokes2D(b,sc) as s:r=s.solve_rheology(fx,fz,T,p,**request(b))
        h=r.descriptor()['nonlinear_history'];self.assertGreater(h[0]['momentum_linf'],1e-7)
        self.assertLess(h[-1]['momentum_linf'],1e-9);self.assertGreater(len(h),1)
    def test_returned_eta_matches_returned_strain_not_lagged_guess(self):
        b,sc,fx,fz,T,p=forcing(8)
        with PreparedVariableStokes2D(b,sc) as s:r=s.solve_rheology(fx,fz,T,p,**request(b))
        x,z=np.meshgrid(*b.axes());rate=r.array('strain_rate_cell_s_1')*sc.time_s
        expected=_native_law(p,T-1,1-z,rate,np.zeros_like(T))[0]
        np.testing.assert_allclose(r.array('viscosity_cell_pa_s'),expected,rtol=5e-14)
    def test_all_registered_tosi_controls(self):
        for key in ('tosi-1','tosi-2','tosi-3','tosi-4','tosi-5a'):
            with self.subTest(key=key):
                b,sc,fx,fz,T,p=forcing(6,key=key)
                with PreparedVariableStokes2D(b,sc) as s:r=s.solve_rheology(fx,fz,T,p,**request(b))
                self.assertLess(r.descriptor()['diagnostics']['momentum_linf'],1e-9)
                if p.family=='tosi-linear':self.assertEqual(len(r.descriptor()['nonlinear_history']),1)
    def test_dynamic_pressure_not_rheology_input(self):
        b,sc,fx,fz,T,p=forcing(6,key='tosi-1');xp,zp=np.meshgrid(*b.axes());extra=.3*np.cos(np.pi*xp)
        with PreparedVariableStokes2D(b,sc) as s:
            a=s.solve_rheology(fx,fz,T,p,**request(b))
            c=s.solve_rheology(fx+np.diff(extra,axis=1)*b.nx,fz,T,p,**request(b))
        np.testing.assert_allclose(a.array('u_m_s'),c.array('u_m_s'),rtol=1e-8,atol=1e-8)
        np.testing.assert_array_equal(a.array('viscosity_cell_pa_s'),c.array('viscosity_cell_pa_s'))
    def test_depth_normalisation_is_down_from_top(self):
        b,sc,fx,fz,T,p=forcing(6,key='tosi-3')
        with PreparedVariableStokes2D(b,sc) as s:r=s.solve_rheology(fx*0,fz*0,np.ones_like(T),p,**request(b))
        expected=10**(1-(np.arange(6)+.5)/6)
        np.testing.assert_allclose(r.array('viscosity_cell_pa_s')[:,0],expected,rtol=1e-14)
    def test_zero_strain_uses_exact_tosi_limit(self):
        b,sc,fx,fz,T,p=forcing(6)
        with PreparedVariableStokes2D(b,sc) as s:r=s.solve_rheology(fx*0,fz*0,T,p,**request(b))
        np.testing.assert_allclose(r.array('viscosity_cell_pa_s'),2*np.exp(-math.log(1e5)*(T-1)),rtol=1e-14)
    def test_bf_frozen_damage_is_explicit_and_preserved(self):
        b,sc,fx,fz,T,p=forcing(4,key='bf23-memory');d=np.full((4,4),4.)
        with PreparedVariableStokes2D(b,sc) as s:r=s.solve_rheology(fx*0,fz*0,T,p,frozen_damage=d,**request(b))
        np.testing.assert_array_equal(r.array('frozen_damage'),d)
        self.assertTrue(np.isfinite(r.array('viscosity_cell_pa_s')).all())
    def test_bf_missing_damage_refused(self):
        b,sc,fx,fz,T,p=forcing(4,key='bf23-memory')
        with PreparedVariableStokes2D(b,sc) as s:
            with self.assertRaises(TectonicsError):s.solve_rheology(fx,fz,T,p,**request(b))
    def test_unrelated_damage_not_ignored(self):
        b,sc,fx,fz,T,p=forcing(4)
        with PreparedVariableStokes2D(b,sc) as s:
            with self.assertRaises(TectonicsError):s.solve_rheology(fx,fz,T,p,frozen_damage=np.zeros_like(T),**request(b))
    def test_picard_limit_is_failure_not_a_lagged_success(self):
        b,sc,fx,fz,T,p=forcing(8)
        with PreparedVariableStokes2D(b,sc,policy=NonlinearStokesPolicy(max_picard_iterations=1)) as s:
            with self.assertRaisesRegex(TectonicsError,'Picard'):s.solve_rheology(fx,fz,T,p,**request(b))
    def test_gmres_limit_is_failure_not_direct_fallback(self):
        b=unit_box(8);a=analytic_variable(b)
        with PreparedVariableStokes2D(b,unit_scales(),policy=NonlinearStokesPolicy(restart=1,max_cycles=1)) as s:
            with self.assertRaisesRegex(TectonicsError,'GMRES'):s.solve(*a[:4],**request(b))
    def test_temperature_outside_existing_law_envelope_refused(self):
        b,sc,fx,fz,T,p=forcing(4);T[0,0]=3
        with PreparedVariableStokes2D(b,sc) as s:
            with self.assertRaises(TectonicsError):s.solve_rheology(fx,fz,T,p,**request(b))
    def test_depth_outside_existing_law_envelope_refused(self):
        b,sc,fx,fz,T,p=forcing(4);sc=replace(sc,depth_scale_m=.5)
        with PreparedVariableStokes2D(b,sc) as s:
            with self.assertRaises(TectonicsError):s.solve_rheology(fx,fz,T,p,**request(b))
    def test_explicit_viscosity_bounds_are_reported(self):
        b,sc,fx,fz,T,p=forcing(6,key='tosi-1');p=replace(p,viscosity_bounds=(.01,1.))
        with PreparedVariableStokes2D(b,sc) as s:r=s.solve_rheology(fx,fz,T,p,**request(b))
        self.assertTrue(np.any(r.array('clipped_cell')))
        self.assertGreaterEqual(r.array('viscosity_cell_pa_s').min(),.01)
