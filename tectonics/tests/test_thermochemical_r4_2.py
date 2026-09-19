"""Independent finite-volume, exact diffusion, time-splitting and coupling checks.
SPDX-License-Identifier: AGPL-3.0-only
"""
from dataclasses import replace
import math
import unittest
from unittest import mock
import numpy as np
from numpy.testing import assert_allclose,assert_array_equal
from scipy.linalg import expm
from atlas_tectonics import (PreparedThermochemical2D,ThermochemicalState,ThermalBoundary2D,
    ThermochemicalPolicy,PrescribedMACVelocity,CourantLimitError,TectonicsError,boussinesq_response)
from atlas_tectonics.thermochemical import _Diffusion2D,_decay_coefficients,_reference_transfers,_check_fields
from atlas_tectonics.thermochemical_execution import _courant_arrays
from atlas_tectonics import _thermochemical_native as native
from thermochemical_fixtures import problem,initial,rest,circulation,dense_diffusion,dense_upwind


class DiffusionTests(unittest.TestCase):
    def test_dense_exponential_fixed_boundaries(self):
        p=problem(5,4,width=2.,height=3.);s=initial(p)
        A,f=dense_diffusion(p);H=np.arange(20).reshape(4,5)*.01
        aug=np.zeros((21,21));aug[:20,:20]=A;aug[:20,20]=f+H.ravel()
        want=(expm(.13*aug)@np.r_[s.array('temperature_k').ravel(),1])[:-1].reshape(4,5)
        d=_Diffusion2D(p);got,_=d.advance(s.array('temperature_k'),d.transform(H),.13,None)
        assert_allclose(got,want,rtol=3e-15,atol=1e-12)
    def test_dense_exponential_insulated_boundaries(self):
        p=problem(4,3,fixed=False);s=initial(p);A,f=dense_diffusion(p)
        d=_Diffusion2D(p);got,out=d.advance(s.array('temperature_k'),d.transform(np.zeros((3,4))),.4,None)
        assert_allclose(got.ravel(),expm(.4*A)@s.array('temperature_k').ravel(),atol=1e-12,rtol=3e-15)
        self.assertEqual(out,(0.,0.))
    def test_dense_boundary_heat_integral_independent(self):
        p=problem(3,4);s=initial(p,T=302.);d=_Diffusion2D(p);dt=.3
        got,bounds=d.advance(s.array('temperature_k'),d.transform(np.ones((4,3))*.2),dt,None)
        A,f=dense_diffusion(p);n=12
        # Additional ODE states integrate independently assembled wall outflows.
        aug=np.zeros((n+3,n+3));aug[:n,:n]=A;aug[:n,n]=f+.2
        factor=2*p.material.conductivity_w_m_k*(1/3)/(1/4)
        aug[n+1,:3]=factor;aug[n+1,n]=-factor*3*310.
        aug[n+2,n-3:n]=factor;aug[n+2,n]=-factor*3*300.
        y=expm(dt*aug)@np.r_[s.array('temperature_k').ravel(),1.,0.,0.]
        assert_allclose(bounds,y[-2:],atol=2e-14,rtol=3e-13)
    def test_insulated_uniform_heating_is_exact(self):
        p=problem(9,fixed=False);d=_Diffusion2D(p);T=np.full((9,9),300.);Q=np.full_like(T,.125)
        a,heat=d.advance(T,d.transform(Q),2.,None)
        assert_array_equal(a,300.25);self.assertEqual(heat,(0.,0.))
    def test_linear_conduction_state_stationary(self):
        p=problem(8,12);_,z=np.meshgrid(*p.box.axes());T=310.-10*z
        d=_Diffusion2D(p);out,flux=d.advance(T,d.transform(np.zeros_like(T)),20.,None)
        assert_allclose(out,T,atol=6e-14,rtol=0);assert_allclose(flux,[-2.,2.],atol=1e-14)
    def test_long_diffusion_step_no_explicit_diffusion_CFL(self):
        p=problem(16);s=initial(p);d=_Diffusion2D(p)
        out,flux=d.advance(s.array('temperature_k'),d.transform(np.zeros((16,16))),1000.,None)
        assert_allclose(out,d.lift+np.zeros((16,16)),atol=6e-14,rtol=0)
    def test_fixed_diffusion_monotonicity(self):
        p=problem(16);T=np.random.default_rng(44).uniform(300,310,(16,16));d=_Diffusion2D(p)
        out,_=d.advance(T,d.transform(np.zeros_like(T)),.1,None)
        self.assertGreaterEqual(out.min(),300.);self.assertLessEqual(out.max(),310.)
    def test_insulated_diffusion_integral_preserved(self):
        p=problem(13,7,fixed=False);T=300+np.random.default_rng(49).random((7,13));d=_Diffusion2D(p)
        out,_=d.advance(T,d.transform(np.zeros_like(T)),5.,None)
        self.assertAlmostEqual(math.fsum(out.flat),math.fsum(T.flat),places=10)
    def test_semigroup_with_spatial_source(self):
        p=problem(5,7);s=initial(p);d=_Diffusion2D(p);Q=d.transform(np.random.default_rng(3).random((7,5)))
        one,_=d.advance(s.array('temperature_k'),Q,.2,None)
        half,_=d.advance(s.array('temperature_k'),Q,.1,None);two,_=d.advance(half,Q,.1,None)
        assert_allclose(one,two,atol=1.2e-13,rtol=0)
    def test_phi_coefficients_zero_and_tiny(self):
        x=np.array([0.,1e-20,1e-10,1e-4,1.,100.,10000.]);e,p,s=_decay_coefficients(x)
        self.assertEqual(p[0],1.);self.assertEqual(s[0],.5);self.assertEqual(e[-1],0.)
        from decimal import Decimal,localcontext
        with localcontext() as c:
            c.prec=75
            for k,value in enumerate(x[:-1]):
                if not value:continue
                z=Decimal.from_float(float(value));ep=(-z).exp();a=(1-ep)/z;b=(1-a)/z
                self.assertLess(abs(p[k]/float(a)-1),3e-15);self.assertLess(abs(s[k]/float(b)-1),3e-15)
    def test_phi_rejects_invalid(self):
        for v in (-1.,np.inf,np.nan):
            with self.assertRaises(TectonicsError):_decay_coefficients(np.array([v]))
    def test_diffusion_space_convergence(self):
        errors=[]
        for n in (8,16,32):
            p=problem(n);x,z=np.meshgrid(*p.box.axes());h=1/n
            factor=np.sinc(h/2)**2;mode=np.cos(np.pi*x)*np.sin(np.pi*z)*factor
            T=310.-10*z+mode;d=_Diffusion2D(p)
            out,_=d.advance(T,d.transform(np.zeros_like(T)),.2,None)
            exact=310.-10*z+mode*np.exp(-.01*2*np.pi**2*.2)
            errors.append(float(np.sqrt(np.mean((out-exact)**2))))
        for a,b in zip(errors,errors[1:]):self.assertGreater(a/b,3.9)
    def test_coefficient_cache_reused_and_replaced(self):
        p=problem(4);d=_Diffusion2D(p);T=initial(p).array('temperature_k');Q=d.transform(np.zeros_like(T))
        d.advance(T,Q,.1,None);a=d._coeff;d.advance(T,Q,.1,None);self.assertIs(a,d._coeff)
        d.advance(T,Q,.2,None);self.assertIsNot(a,d._coeff)
    def test_rectangular_axis_swap_insulated(self):
        p=problem(6,4,width=2.,height=1.,fixed=False);p2=problem(4,6,width=1.,height=2.,fixed=False)
        T=300+np.arange(24).reshape(4,6)*.1;d=_Diffusion2D(p);d2=_Diffusion2D(p2)
        a,_=d.advance(T,d.transform(np.zeros_like(T)),.4,None)
        b,_=d2.advance(T.T,d2.transform(np.zeros_like(T.T)),.4,None)
        assert_allclose(a,b.T,atol=1e-13,rtol=0)


class TransportTests(unittest.TestCase):
    def test_native_numpy_face_transfer_parity(self):
        p=problem(9,6);v=circulation(p,.1);cx,cz,*_=_courant_arrays(p.box,v.array('u_m_s'),v.array('w_m_s'),.02,ThermochemicalPolicy())
        q=np.random.default_rng(11).uniform(.1,.9,(2,6,9));a=np.empty((2,6,10));b=np.empty((2,7,9));c=a.copy();d=b.copy()
        native.face_transfers(q,cx,cz,a,b);_reference_transfers(q,cx,cz,c,d)
        assert_array_equal(a,c);assert_array_equal(b,d)
    def test_independent_face_loop_budget(self):
        p=problem(2);v=circulation(p,.1);q=np.array([[[.1,.8],[.5,.9]],[[.2,.4],[.6,.8]]])
        cx,cz,*_=_courant_arrays(p.box,v.array('u_m_s'),v.array('w_m_s'),.03,ThermochemicalPolicy())
        f=np.empty((2,2,3));g=np.empty((2,3,2));native.face_transfers(q,cx,cz,f,g);out=np.empty_like(q)
        native.euler_update(q,f,g,out)
        A=dense_upwind(p,v)
        for k in range(2):assert_allclose(out[k].ravel(),q[k].ravel()+.03*A@q[k].ravel(),atol=2e-16,rtol=0)
    def test_shared_face_sums_cancel(self):
        p=problem(7);v=circulation(p,.3);q=np.random.default_rng(19).uniform(0,1,(2,7,7))
        cx,cz,*_=_courant_arrays(p.box,v.array('u_m_s'),v.array('w_m_s'),.01,ThermochemicalPolicy())
        f=np.empty((2,7,8));g=np.empty((2,8,7));out=np.empty_like(q)
        native.face_transfers(q,cx,cz,f,g);native.euler_update(q,f,g,out)
        for k in range(2):self.assertLess(abs(math.fsum((out[k]-q[k]).flat)),8e-16)
    def test_contact_bounded_without_clipping(self):
        p=problem(16,fixed=False);v=circulation(p,.1);q=np.zeros((2,16,16));q[:,:,8:]=1.
        cx,cz,*_=_courant_arrays(p.box,v.array('u_m_s'),v.array('w_m_s'),.02,ThermochemicalPolicy())
        f=np.empty((2,16,17));g=np.empty((2,17,16));out=np.empty_like(q)
        for _ in range(40):
            native.face_transfers(q,cx,cz,f,g);native.euler_update(q,f,g,out)
            self.assertGreaterEqual(out.min(),-2e-15);self.assertLessEqual(out.max(),1+2e-15)
            q[:]=out
        self.assertLess(abs(q[0].sum()-128.),1e-12)
    def test_courant_sum_not_axiswise_max(self):
        p=problem(4);v=circulation(p,1.)
        with self.assertRaises(CourantLimitError):_courant_arrays(p.box,v.array('u_m_s'),v.array('w_m_s'),1.,ThermochemicalPolicy())
    def test_divergent_velocity_refused(self):
        p=problem(4);u=np.zeros((4,5));w=np.zeros((5,4));u[1,2]=.1
        with self.assertRaises(TectonicsError):_courant_arrays(p.box,u,w,.01,ThermochemicalPolicy())
    def test_zero_velocity_is_valid(self):
        p=problem(2);v=rest(p);a,b,c,d=_courant_arrays(p.box,v.array('u_m_s'),v.array('w_m_s'),1.,ThermochemicalPolicy())
        self.assertEqual(c,0);self.assertEqual(d,0)
    def test_mc_linear_reconstruction(self):
        q=np.broadcast_to(np.arange(5)[None,None,:],(2,4,5)).copy().astype(float);cx=np.ones((4,6))*.01;cz=np.zeros((5,5))
        a=np.empty((2,4,6));b=np.empty((2,5,5));native.face_transfers(q,cx,cz,a,b)
        self.assertEqual(a[0,0,3],.025)
    def test_compensated_sum_matches_fsum(self):
        a=np.array([1e16,1.,-1e16]*50).reshape(5,30)
        self.assertEqual(native.sum_compensated(a),math.fsum(a.flat))
    def test_unsplit_axes_transpose(self):
        p=problem(7,5,width=2.,height=1.);v=circulation(p,.1)
        q=np.random.default_rng(15).random((2,5,7));cx,cz,*_=_courant_arrays(p.box,v.array('u_m_s'),v.array('w_m_s'),.02,ThermochemicalPolicy())
        a=np.empty((2,5,8));b=np.empty((2,6,7));out=np.empty_like(q)
        native.face_transfers(q,cx,cz,a,b);native.euler_update(q,a,b,out)
        qt=q.transpose(0,2,1).copy();aa=np.empty((2,7,6));bb=np.empty((2,8,5));oo=np.empty_like(qt)
        native.face_transfers(qt,cz.T.copy(),cx.T.copy(),aa,bb);native.euler_update(qt,aa,bb,oo)
        assert_allclose(out,oo.transpose(0,2,1),rtol=0,atol=3e-16)


class EvolutionTests(unittest.TestCase):
    def test_pure_diffusion_matches_exact_discrete_flow(self):
        p=problem(6);s=initial(p);d=_Diffusion2D(p)
        expected,_=d.advance(s.array('temperature_k'),d.transform(np.zeros((6,6))),.2,None)
        with PreparedThermochemical2D(p) as plan:r=plan.advance(s,.2,source='diffusion',velocity=rest(p))
        assert_allclose(r.state.array('temperature_k'),expected,atol=1.2e-13,rtol=0)
        assert_array_equal(r.state.array('composition'),s.array('composition'))
    def test_source_added_once_not_per_split_stage(self):
        p=problem(5,fixed=False,heating=.25);s=initial(p,T=300.,C=.5)
        with PreparedThermochemical2D(p) as plan:r=plan.advance(s,.5,source='source control',extra_heating_w_m3=.5,velocity=rest(p))
        assert_array_equal(r.state.array('temperature_k'),300.375)
        # Cell-area multiplication is rounded in binary64; compare the physical total.
        self.assertAlmostEqual(r.descriptor()['record']['balances']['source_heat_j'],.375,places=15)
    def test_boundary_and_material_budgets(self):
        p=problem(8);s=initial(p,T=301.)
        with PreparedThermochemical2D(p) as plan:r=plan.advance(s,.1,source='boundary control',velocity=rest(p))
        a=r.descriptor()['record']['balances'];self.assertLess(a['bottom_outward_heat_j'],0.)
        self.assertLess(a['heat_relative_residual'],1e-13);self.assertEqual(a['composition_change_m3'],0.)
    def test_split_and_rk_second_order_against_dense_exponential(self):
        p=problem(2,fixed=False,k=.08);v=circulation(p,.2);s=initial(p,T=np.array([[303.,305.],[302.,304.]]))
        D,_=dense_diffusion(p);A=dense_upwind(p,v);duration=.2
        exact=(expm(duration*(A+D))@s.array('temperature_k').ravel()).reshape(2,2)
        errors=[]
        with PreparedThermochemical2D(p) as plan:
            for count in (4,8,16):
                state=s
                for _ in range(count):state=plan.advance(state,duration/count,source='time order',velocity=v).state
                errors.append(float(np.linalg.norm(state.array('temperature_k')-exact)))
        for a,b in zip(errors,errors[1:]):self.assertGreater(a/b,3.5)
    def test_composition_second_order_time_against_expm(self):
        p=problem(2,fixed=False);v=circulation(p,.2);s=initial(p);A=dense_upwind(p,v);duration=.2
        want=expm(duration*A)@s.array('composition').ravel();errors=[]
        with PreparedThermochemical2D(p) as plan:
            for count in (4,8,16):
                state=s
                for _ in range(count):state=plan.advance(state,duration/count,source='C temporal',velocity=v).state
                errors.append(float(np.linalg.norm(state.array('composition').ravel()-want)))
        for a,b in zip(errors,errors[1:]):self.assertGreater(a/b,3.7)
    def test_buoyancy_recomputed_both_rk_stages(self):
        p=problem(8,heating=.01);s=initial(p)
        with PreparedThermochemical2D(p) as plan:r=plan.advance(s,.05,source='coupled')
        record=r.descriptor()['record'];self.assertNotEqual(*record['stage_flow_ids'])
        self.assertGreater(np.max(np.abs(r.array('u_stage1_m_s')-r.array('u_stage0_m_s'))),0.)
        self.assertIn('intermediate',r.descriptor()['stage_velocity_semantics'])
    def test_buoyancy_thermal_and_composition_formula_matches_R3(self):
        p=problem(8);s=initial(p)
        a,_=_check_fields(p,s.array('temperature_k'),s.array('composition'))
        r=boussinesq_response(p.material,s.array('temperature_k'),s.array('composition'),p.gravity_m_s2,[0.,0.])
        assert_array_equal(a,r['density_anomaly_kg_m3'])
    def test_constant_C_remains_constant_to_roundoff_in_solved_flow(self):
        p=problem(8);s=initial(p,C=1.)
        with PreparedThermochemical2D(p) as plan:
            for _ in range(3):s=plan.advance(s,.01,source='constant fraction').state
        assert_allclose(s.array('composition'),1.,atol=2e-15,rtol=0)
    def test_zero_gravity_coupling_reduces_to_rest(self):
        p=problem(6,gravity=(0.,0.));s=initial(p)
        with PreparedThermochemical2D(p) as plan:
            a=plan.advance(s,.1,source='zero gravity');b=plan.advance(s,.1,source='rest',velocity=rest(p))
        for k in ('temperature_k','composition'):assert_array_equal(a.state.array(k),b.state.array(k))
    def test_native_reference_complete_step_close_agreement(self):
        p=problem(8);s=initial(p);v=circulation(p,.1)
        with PreparedThermochemical2D(p) as a,PreparedThermochemical2D(p,backend='reference') as b:
            x=a.advance(s,.05,source='comparison',velocity=v);y=b.advance(s,.05,source='comparison',velocity=v)
        for k in ('temperature_k','composition'):assert_array_equal(x.state.array(k),y.state.array(k))
    def test_flux_arrays_reconstruct_composition_delta(self):
        p=problem(8);s=initial(p)
        with PreparedThermochemical2D(p) as plan:r=plan.advance(s,.05,source='flux check',velocity=circulation(p,.1))
        f=r.array('flux_x_increment')[1];g=r.array('flux_z_increment')[1]
        delta=f[:,:-1]-f[:,1:]+g[:-1]-g[1:]
        assert_allclose(r.state.array('composition')-s.array('composition'),delta,atol=2e-16,rtol=0)
    def test_timestep_failure_does_not_change_input(self):
        p=problem(6);s=initial(p);old=s.state_id
        with PreparedThermochemical2D(p) as plan:
            with self.assertRaises(CourantLimitError):plan.advance(s,5.,source='too large',velocity=circulation(p,1.))
            r=plan.advance(s,.001,source='smaller',velocity=circulation(p,1.))
        self.assertEqual(s.state_id,old);self.assertEqual(r.state.step_index,1)
    def test_missing_temperature_physics_not_silently_extrapolated(self):
        p=problem(4);p=replace(p,material=replace(p.material,expansion_per_k=0.));s=initial(p,T=999.)
        with PreparedThermochemical2D(p) as plan:
            with self.assertRaises(TectonicsError):plan.advance(s,1.,source='invalid heat',velocity=rest(p),extra_heating_w_m3=1e7)
    def test_signed_diffusion_flux_heat_budget_rectangular_SI(self):
        p=problem(7,5,width=2000.,height=800.,k=3.)
        m=replace(p.material,density_kg_m3=3300.,heat_capacity_j_kg_k=1250.,expansion_per_k=1e-5)
        p=replace(p,material=m);s=initial(p,T=303.)
        with PreparedThermochemical2D(p) as plan:r=plan.advance(s,1e8,source='SI heat',velocity=rest(p),extra_heating_w_m3=1e-8)
        b=r.descriptor()['record']['balances'];self.assertLess(b['heat_relative_residual'],2e-13)
        self.assertGreater(b['heat_change_j'],0.)


if __name__=='__main__':unittest.main()
