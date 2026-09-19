"""R4.1 equations, discretisation, signs, nullspace and convergence verification.
SPDX-License-Identifier: AGPL-3.0-only
"""
from dataclasses import replace
import unittest
import numpy as np
from numpy.testing import assert_allclose, assert_array_equal
from atlas_tectonics import (StokesBox2D,StokesSolvePolicy,PreparedStokes2D,
    DiffusiveScales,reference_rheology,RheologyProfile,face_force_from_density,
    BoussinesqMaterial,boussinesq_response,TectonicsError)
from atlas_tectonics.stokes import _MACOperator,_SeparableVelocityInverse,_scaling
from atlas_tectonics.stokes_execution import _residual_fields
from atlas_tectonics.resources import WorkBudget
from stokes_fixtures import unit_box,unit_scales,request,analytic,errors


class GridAndOperatorTests(unittest.TestCase):
    def setUp(self):
        self.box=unit_box(5,4,width=2.);self.op=_MACOperator(self.box,.4,.25)
        self.rng=np.random.default_rng(918)
    def test_staggered_shapes_and_unknown_count(self):
        u,w,p,g=self.op.split(np.zeros(self.box.unknowns))
        self.assertEqual(u.shape,(4,4));self.assertEqual(w.shape,(3,5));self.assertEqual(p.shape,(4,5))
        self.assertEqual(self.box.unknowns,52)
    def test_axes_values_and_frame(self):
        b=unit_box(4,2,width=2.,height=3.)
        assert_array_equal(b.axes('pressure')[0],[.25,.75,1.25,1.75])
        assert_array_equal(b.axes('force_x')[0],[.5,1.,1.5])
        assert_array_equal(b.axes('w')[1],[0.,1.5,3.])
    def test_axes_immutable_and_independent(self):
        a=self.box.axes('pressure')[0]
        with self.assertRaises(ValueError):a.setflags(write=True)
        a.shape=(1,5)
        self.assertEqual(self.box.axes('pressure')[0].shape,(5,))
    def test_invalid_grid_sizes(self):
        for n in (0,1,-4,2.5,True,2**31):
            with self.subTest(n=n),self.assertRaises(TectonicsError):unit_box(n)
    def test_invalid_grid_lengths(self):
        for x in (0.,-1.,np.nan,np.inf,True):
            with self.subTest(x=x),self.assertRaises(TectonicsError):unit_box(width=x)
    def test_invalid_frame(self):
        with self.assertRaises(TectonicsError):StokesBox2D(4,4,1.,1.,' ')
    def test_unknown_coordinate_location_refused(self):
        with self.assertRaises(TectonicsError):self.box.axes('depth')
    def test_coordinate_budget_before_allocation(self):
        b=WorkBudget(1)
        with self.assertRaises(ValueError):self.box.axes(budget=b)
        self.assertEqual(b.reserved_bytes,0)
    def test_sparse_and_matrix_free_independently_agree(self):
        x=self.rng.standard_normal(self.op.n)
        assert_allclose(self.op.matvec(x),self.op.sparse_reference()@x,rtol=2e-15,atol=8e-14)
    def test_assembled_matrix_is_symmetric(self):
        a=self.op.sparse_reference()
        self.assertEqual((a-a.T).nnz,0)
    def test_matrix_free_bilinear_symmetry(self):
        x=self.rng.standard_normal(self.op.n);y=self.rng.standard_normal(self.op.n)
        self.assertAlmostEqual(float(x@self.op.matvec(y)),float(y@self.op.matvec(x)),places=11)
    def test_constant_pressure_null_mode_only_couples_gauge(self):
        x=np.zeros(self.op.n);x[self.op.nv:-1]=1.
        a=self.op.matvec(x)
        assert_array_equal(a[:-1],0.);self.assertAlmostEqual(a[-1],np.sqrt(self.op.np))
    def test_augmented_matrix_full_rank(self):
        a=self.op.sparse_reference().toarray()
        self.assertEqual(np.linalg.matrix_rank(a),self.op.n)
    def test_checkerboard_is_not_an_extra_pressure_nullspace(self):
        x=np.zeros(self.op.n);x[self.op.nv:-1]=((-1.)**np.indices((4,5)).sum(axis=0)).ravel()
        self.assertGreater(np.linalg.norm(self.op.matvec(x)[:self.op.nv]),10.)
    def test_all_cell_divergences_telescope(self):
        u,w,_,_=self.op.split(self.rng.standard_normal(self.op.n))
        self.assertAlmostEqual(float(np.sum(self.op.divergence(u,w))),0.,places=12)
    def test_divergence_independent_face_differences(self):
        u,w,_,_=self.op.split(self.rng.standard_normal(self.op.n))
        uf=np.pad(u,((0,0),(1,1)));wf=np.pad(w,((1,1),(0,0)))
        expected=np.diff(uf,axis=1)/self.op.hx+np.diff(wf,axis=0)/self.op.hz
        assert_allclose(self.op.divergence(u,w),expected,rtol=1e-15,atol=5e-15)
    def test_discrete_gradient_is_negative_divergence_adjoint(self):
        u,w,p,_=self.op.split(self.rng.standard_normal(self.op.n))
        left=np.sum(u*np.diff(p,axis=1)/self.op.hx)+np.sum(w*np.diff(p,axis=0)/self.op.hz)
        self.assertAlmostEqual(left,-np.sum(p*self.op.divergence(u,w)),places=12)
    def test_positive_velocity_energy(self):
        u,w,_,_=self.op.split(self.rng.standard_normal(self.op.n))
        au,aw=self.op.velocity(u,w)
        self.assertGreater(np.sum(u*au)+np.sum(w*aw),0.)
    def test_energy_matches_independent_difference_sum(self):
        u,w,_,_=self.op.split(self.rng.standard_normal(self.op.n))
        au,aw=self.op.velocity(u,w)
        assert_allclose(self.op.energy(u,w),(np.sum(u*au)+np.sum(w*aw))*self.op.hx*self.op.hz,rtol=5e-16)
    def test_neumann_tangential_constant_has_no_flux(self):
        u=np.ones((4,4));w=np.zeros((3,5));au,_=self.op.velocity(u,w)
        expected=np.zeros_like(u);expected[:,[0,-1]]=1/self.op.hx**2
        assert_allclose(au,expected,atol=1e-14)
    def test_spectral_inverse_matches_independent_dense_velocity_solve(self):
        inv=_SeparableVelocityInverse(self.op);a=self.op.sparse_reference().toarray()
        x=self.rng.standard_normal(self.op.n);y=inv.apply(x)
        exact=np.linalg.solve(a[:self.op.nv,:self.op.nv],x[:self.op.nv])
        assert_allclose(y[:self.op.nv],exact,rtol=1e-13,atol=1e-15)
        assert_array_equal(y[self.op.nv:],x[self.op.nv:])
    def test_preconditioner_symmetric_positive(self):
        inv=_SeparableVelocityInverse(self.op);x=self.rng.standard_normal(self.op.n);y=self.rng.standard_normal(self.op.n)
        self.assertGreater(float(x@inv.apply(x)),0.)
        self.assertAlmostEqual(float(x@inv.apply(y)),float(y@inv.apply(x)),places=13)
    def test_smallest_valid_two_by_two_grid(self):
        b=unit_box(2);o=_MACOperator(b,.5,.5);inv=_SeparableVelocityInverse(o)
        assert_allclose(inv.apply(o.matvec(np.zeros(o.n))),0.)
        with PreparedStokes2D(b,reference_rheology('constant'),unit_scales()) as plan:
            r=plan.solve(*analytic(b)[:2],**request(b))
        self.assertLess(r.descriptor()['diagnostics']['divergence_linf'],1e-12)
    def test_rectangular_pressure_schur_identity_on_mean_zero_modes(self):
        inv=_SeparableVelocityInverse(self.op);p=self.rng.standard_normal((4,5));p-=p.mean()
        x=np.zeros(self.op.n);x[self.op.nv:-1]=p.ravel()
        g=self.op.matvec(x);g[self.op.nv:]=0.
        u,w,_,_=self.op.split(inv.apply(g))
        assert_allclose(-self.op.divergence(u,w),p,rtol=1e-13,atol=2e-15)


class MechanicalSolutionTests(unittest.TestCase):
    def solve(self,box,fx,fz,*,profile=None,scales=None,policy=None):
        with PreparedStokes2D(box,reference_rheology('constant') if profile is None else profile,
                             unit_scales() if scales is None else scales,policy=policy) as p:
            return p.solve(fx,fz,**request(box))
    def test_zero_force_has_exact_rest_and_zero_pressure(self):
        b=unit_box();r=self.solve(b,np.zeros((12,11)),np.zeros((11,12)))
        for name in r.array_names:assert_array_equal(r.array(name),0.)
        self.assertEqual(r.descriptor()['iterations'],0)
    def test_uniform_vertical_force_is_hydrostatic_not_spurious_flow(self):
        b=unit_box(12,8,width=2.,height=3.);gz=-7.
        r=self.solve(b,np.zeros((8,11)),np.full((7,12),gz))
        assert_allclose(r.array('u_m_s'),0.,atol=2e-14);assert_allclose(r.array('w_m_s'),0.,atol=2e-14)
        z=b.axes()[1]
        assert_allclose(r.array('pressure_pa'),np.broadcast_to(gz*(z[:,None]-1.5),(8,12)),atol=2e-13)
    def test_horizontal_force_pressure_sign(self):
        b=unit_box(10);r=self.solve(b,np.full((10,9),2.),np.zeros((9,10)))
        x=b.axes()[0]
        assert_allclose(r.array('pressure_pa'),np.broadcast_to(2*(x[None,:]-.5),(10,10)),atol=2e-14)
        assert_allclose(r.array('u_m_s'),0.,atol=1e-14)
    def test_pure_discrete_checkerboard_gradient_recovers_pressure(self):
        b=unit_box(8);pressure=(-1.)**np.indices((8,8)).sum(axis=0)
        fx=np.diff(pressure,axis=1)*8;fz=np.diff(pressure,axis=0)*8
        r=self.solve(b,fx,fz)
        assert_allclose(r.array('pressure_pa'),pressure,rtol=1e-13,atol=1e-13)
        assert_allclose(r.array('u_m_s'),0.,atol=1e-13)
    def test_manufactured_velocity_and_pressure_values(self):
        b=unit_box(32);a=analytic(b);r=self.solve(b,*a[:2]);e=errors(r,a)
        self.assertLess(e['u_l2'],8e-5);self.assertLess(e['w_l2'],8e-5);self.assertLess(e['p_l2'],5e-4)
    def test_independent_continuum_second_order_refinement(self):
        result=[]
        for n in (8,16,32):
            b=unit_box(n);a=analytic(b);result.append(errors(self.solve(b,*a[:2]),a))
        for key in result[0]:
            ratios=[result[i][key]/result[i+1][key] for i in (0,1)]
            with self.subTest(field=key):
                self.assertTrue(all(3.7<r<4.6 for r in ratios),ratios)
    def test_rectangular_unequal_spacing_refinement(self):
        es=[]
        for n in (8,16,32):
            b=unit_box(2*n,n,width=3.,height=1.);a=analytic(b,m=1,n=1)
            es.append(errors(self.solve(b,*a[:2]),a))
        for key in es[0]:
            with self.subTest(field=key):self.assertGreater(es[1][key]/es[2][key],3.7)
    def test_multiple_independent_analytic_modes(self):
        b=unit_box(32);a=analytic(b);c=analytic(b,amplitude=.02,pressure=.1,m=2,n=2,pm=1,pn=2)
        combo=tuple(x+y for x,y in zip(a,c));r=self.solve(b,*combo[:2])
        self.assertLess(errors(r,combo)['u_l2'],.0003)
    def test_sparse_direct_matches_iterative_for_random_forces(self):
        b=unit_box(10,8,width=2.);rng=np.random.default_rng(19)
        fx=rng.standard_normal((8,9));fz=rng.standard_normal((7,10))
        a=self.solve(b,fx,fz);d=self.solve(b,fx,fz,policy=StokesSolvePolicy(method='direct'))
        for k in ('u_m_s','w_m_s','pressure_pa'):
            assert_allclose(a.array(k),d.array(k),rtol=3e-11,atol=2e-13)
    def test_all_cell_divergences_and_normal_walls(self):
        b=unit_box(18);a=analytic(b);r=self.solve(b,*a[:2])
        assert_array_equal(r.array('u_m_s')[:,[0,-1]],0.);assert_array_equal(r.array('w_m_s')[[0,-1]],0.)
        d=np.diff(r.array('u_m_s'),axis=1)*18+np.diff(r.array('w_m_s'),axis=0)*18
        assert_allclose(d,0.,atol=3e-13);assert_allclose(d,r.array('divergence_s_1'),atol=5e-15)
    def test_pressure_zero_domain_mean(self):
        b=unit_box(10,12);r=self.solve(b,*analytic(b)[:2])
        self.assertLess(abs(r.array('pressure_pa').mean()),1e-13)
    def test_superposition(self):
        b=unit_box(12);rng=np.random.default_rng(41)
        f1=(rng.normal(size=(12,11)),rng.normal(size=(11,12)));f2=analytic(b)[:2]
        r1=self.solve(b,*f1);r2=self.solve(b,*f2);rs=self.solve(b,*(a+b for a,b in zip(f1,f2)))
        for key in ('u_m_s','w_m_s','pressure_pa'):
            assert_allclose(rs.array(key),r1.array(key)+r2.array(key),rtol=2e-11,atol=1e-13)
    def test_force_reversal(self):
        b=unit_box();f=analytic(b)[:2];r=self.solve(b,*f);s=self.solve(b,*(-a for a in f))
        for key in ('u_m_s','w_m_s','pressure_pa'):assert_array_equal(r.array(key),-s.array(key))
    def test_viscosity_increases_reduce_velocity_not_pressure(self):
        b=unit_box();a=analytic(b);r=self.solve(b,*a[:2]);p=replace(reference_rheology('constant'),parameters=(('eta',2.),))
        s=self.solve(b,*a[:2],profile=p)
        for key in ('u_m_s','w_m_s'):assert_allclose(s.array(key),r.array(key)/2,rtol=1e-13,atol=1e-14)
        assert_allclose(s.array('pressure_pa'),r.array('pressure_pa'),rtol=1e-13,atol=1e-14)
    def test_arbitrary_reference_scales_preserve_same_si_problem(self):
        b=unit_box();f=analytic(b)[:2];r=self.solve(b,*f)
        s=self.solve(b,*f,scales=DiffusiveScales('different-arbitrary-scales',2.,.125,1.,300.,100.,3.))
        for key in ('u_m_s','w_m_s','pressure_pa'):assert_allclose(s.array(key),r.array(key),rtol=3e-12,atol=1e-14)
    def test_realistic_si_length_viscosity_have_no_unit_mixing(self):
        b=unit_box(12,width=1e6,height=1e6);s=DiffusiveScales('declared-SI',1e6,1e-6,1e21,300,1000,1e6)
        gz=-100.;r=self.solve(b,np.zeros((12,11)),np.full((11,12),gz),scales=s)
        target=np.broadcast_to(gz*(b.axes()[1][:,None]-.5e6),(12,12))
        assert_allclose(r.array('pressure_pa'),target,rtol=1e-12,atol=1e-6)
        assert_allclose(r.array('w_m_s'),0.,atol=1e-20)
    def test_force_dynamic_range_keeps_relative_gates(self):
        b=unit_box(6);f=analytic(b)[:2];r=self.solve(b,*f)
        for scale in (1e-80,1e80):
            s=self.solve(b,*(a*scale for a in f))
            for key in ('u_m_s','w_m_s','pressure_pa'):
                with self.subTest(scale=scale,key=key):assert_allclose(s.array(key)/scale,r.array(key),rtol=2e-12,atol=1e-14)
    def test_work_balance_and_positive_dissipation(self):
        b=unit_box();r=self.solve(b,*analytic(b)[:2]);d=r.descriptor()['diagnostics']
        self.assertGreater(d['viscous_gradient_work'],0.)
        self.assertLess(d['work_balance_relative'],1e-12)
        self.assertLess(abs(d['pressure_work']),1e-12)
    def test_local_buoyancy_body_force_raises_central_warm_region(self):
        b=unit_box(24);x,z=np.meshgrid(*b.axes())
        T=1000+100*np.sin(np.pi*x)*np.sin(np.pi*z)
        m=BoussinesqMaterial('test','authored SI sign check',3000,1000,3,1e-5,1000,0.,0.,(900.,1200.))
        fields=boussinesq_response(m,T,0.,[0.,-10.],[0.,0.])
        fx,fz=face_force_from_density(b,fields['density_anomaly_kg_m3'],[0.,-10.])
        r=self.solve(b,fx,fz)
        self.assertGreater(r.array('w_m_s')[12,12],0.)
        self.assertLess(r.array('w_m_s')[12,0],0.)
    def test_density_to_face_interpolation_values(self):
        b=unit_box(3,2);rho=np.array([[1.,2.,3.],[4.,5.,6.]])
        fx,fz=face_force_from_density(b,rho,[2.,-3.])
        assert_array_equal(fx,[[3.,5.],[9.,11.]])
        assert_array_equal(fz,[[-7.5,-10.5,-13.5]])
    def test_density_face_wrong_shape_mask_and_gravity_refused(self):
        b=unit_box(3,2)
        for rho,g in ((np.zeros((3,2)),[0.,-1.]),(np.ma.zeros((2,3)),[0.,-1.]),(np.zeros((2,3)),[0.,0.,-1.])):
            with self.assertRaises(TectonicsError):face_force_from_density(b,rho,g)
    def test_equal_subnormal_density_survives_face_interpolation(self):
        b=unit_box(3,2);tiny=np.nextafter(0.,1.)
        fx,fz=face_force_from_density(b,np.full((2,3),tiny),[2.,-2.])
        assert_array_equal(fx,2*tiny);assert_array_equal(fz,-2*tiny)
    def test_unrepresentable_face_force_fails_explicitly(self):
        b=unit_box(3,2)
        for density,gravity in ((np.finfo(float).max,[2.,0.]),(np.nextafter(0.,1.),[.25,0.])):
            with self.subTest(density=density),self.assertRaises(TectonicsError):
                face_force_from_density(b,np.full((2,3),density),gravity)
    def test_unrepresentable_face_midpoint_refused_in_both_orders(self):
        b=unit_box(2);tiny=np.nextafter(0.,1.)
        for pair in ((0.,tiny),(tiny,0.)):
            with self.subTest(pair=pair),self.assertRaisesRegex(TectonicsError,'mean underflows'):
                face_force_from_density(b,np.tile(pair,(2,1)),[1.,0.])
    def test_large_face_midpoint_does_not_overflow_before_halving(self):
        b=unit_box(2);high=np.finfo(float).max
        for pair in ((high,high*.5),(high*.5,high)):
            f,_=face_force_from_density(b,np.tile(pair,(2,1)),[1.,0.])
            assert_array_equal(f,high*.75)
    def test_opposite_face_anomalies_cancel_to_exact_zero(self):
        b=unit_box(2)
        for x in (np.finfo(float).max,np.nextafter(0.,1.)):
            f,_=face_force_from_density(b,np.tile((x,-x),(2,1)),[1.,0.])
            assert_array_equal(f,0.)
    def test_two_by_two_direct_reference_also_works(self):
        b=unit_box(2);a=analytic(b)
        r=self.solve(b,*a[:2],policy=StokesSolvePolicy(method='direct'))
        self.assertLess(r.descriptor()['diagnostics']['momentum_linf'],1e-12)
    def test_variable_and_yielding_rheologies_explicitly_refused(self):
        for name in ('tosi-1','tosi-2','bf23-memory'):
            with self.subTest(name=name),self.assertRaises(TectonicsError):
                PreparedStokes2D(unit_box(),reference_rheology(name),unit_scales())
    def test_constant_viscosity_clipping_is_not_silently_selected(self):
        p=replace(reference_rheology('constant'),viscosity_bounds=(.1,10.))
        with self.assertRaises(TectonicsError):PreparedStokes2D(unit_box(),p,unit_scales())
    def test_iteration_failure_not_returned_as_success(self):
        b=unit_box();p=StokesSolvePolicy(max_iterations=1)
        with self.assertRaisesRegex(TectonicsError,'converge'):self.solve(b,*analytic(b)[:2],policy=p)
    def test_zero_time_label_not_advanced(self):
        b=unit_box();r=self.solve(b,*analytic(b)[:2]);d=r.descriptor()
        self.assertEqual(d['time_s'],0.);self.assertFalse(d['R4_complete']);self.assertFalse(d['physical_validation'])


if __name__=='__main__':unittest.main()
