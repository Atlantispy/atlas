"""Independent quadrature, published-input, screening and source-guard tests.
SPDX-License-Identifier: AGPL-3.0-only
These tests do not claim a mature published convection benchmark result.
"""
from dataclasses import replace
from decimal import Decimal
import math
from pathlib import Path
import json
import unittest
from unittest import mock
import numpy as np
import atlas_tectonics as a
from atlas_tectonics.convection_benchmark import _METRICS
from atlas_tectonics.resources import WorkBudget, MemoryLimitError
from atlas_tectonics.reuse import ExecutionContext


def fields(n):
    xc=(np.arange(n)+.5)/n
    xf=np.arange(n+1)/n
    T=a.tosi_initial_temperature(n)-1
    u=-math.pi*np.sin(math.pi*xf)[None,:]*np.cos(math.pi*xc)[:,None]
    w=math.pi*np.cos(math.pi*xc)[None,:]*np.sin(math.pi*xf)[:,None]
    u[:,[0,-1]]=0; w[[0,-1]]=0
    return T,u,w,np.ones((n,n)),np.ones((n-1,n-1))


def diagnostic(n):
    return a.convection_diagnostics(*fields(n),a.reference_rheology('tosi-1'))


class PublishedCaseTests(unittest.TestCase):
    def test_all_four_steady_and_periodic_profiles(self):
        for name in ('tosi-1','tosi-2','tosi-3','tosi-4','tosi-5a'):
            with self.subTest(name=name):
                self.assertEqual(a.TosiCase(name).rheology(),a.reference_rheology(name))
    def test_complete_case5b_yield_sweep(self):
        for i in range(21):
            x=3+i/10
            p=a.TosiCase('tosi-5b',x).rheology()
            self.assertEqual(dict(p.parameters)['sigma_y'],x)
            self.assertEqual(dict(p.parameters)['contrast_z'],10)
    def test_bad_case5b_yields(self):
        for x in (None,True,2.9,5.1,3.01,float('nan'),float('inf'),'4'):
            with self.subTest(x=x),self.assertRaises(a.TectonicsError): a.TosiCase('tosi-5b',x)
    def test_case_misidentification_refused(self):
        for name,y in [('tosi-6',None),('tosi-1',4.)]:
            with self.assertRaises(a.TectonicsError): a.TosiCase(name,y)
    def test_grid_validation(self):
        for n in (True,1,257,8.,'8'):
            with self.subTest(n=n),self.assertRaises(a.TectonicsError): a.TosiCase('tosi-1').problem(n)
    def test_exact_rayleigh_embedding(self):
        p=a.TosiCase('tosi-1').problem(16)
        self.assertEqual(p.scales.rayleigh(p.material.density_kg_m3,10000.,p.material.expansion_per_k),100.)
        self.assertEqual(p.diffusivity_m2_s,1.)
        self.assertEqual(p.mechanical_mode,'variable-r4.3')
    def test_initial_cell_integrals(self):
        n=7; h=1/n; x=np.arange(n)*h; z=x[:,None]
        c=(np.sin(np.pi*(x+h))-np.sin(np.pi*x))/(np.pi*h)
        s=(np.cos(np.pi*z)-np.cos(np.pi*(z+h)))/(np.pi*h)
        expected=2-(z+h/2)+.01*c*s
        np.testing.assert_allclose(a.tosi_initial_temperature(n),expected,rtol=0,atol=5e-16)
    def test_initial_mean_exact_to_roundoff(self):
        for n in (2,7,16,32): self.assertAlmostEqual(float(a.tosi_initial_temperature(n).mean()),1.5,places=14)
    def test_initial_material_bounds(self):
        for n in (2,8,256):
            T=a.tosi_initial_temperature(n);self.assertGreater(T.min(),1);self.assertLess(T.max(),2)
    def test_initial_resource_refusal(self):
        b=WorkBudget(1024)
        with self.assertRaises(MemoryLimitError): a.tosi_initial_temperature(16,budget=b)
        self.assertEqual(b.statistics()['reserved_bytes'],0)
    def test_reference_values_are_populated(self):
        ref=json.loads((Path(__file__).parents[1]/'cases/convection_r4_4.json').read_bytes())
        self.assertEqual(len(ref['included_codes']),10)
        for name in ('tosi-1','tosi-2','tosi-3','tosi-4'):
            self.assertEqual(set(ref['reported_values'][name]),set(_METRICS))
        self.assertEqual(ref['reported_values']['tosi-1']['temperature_mean']['ASPECT'],.7768)
        self.assertEqual(ref['reported_values']['tosi-5a']['period']['ASPECT'],.0768)
        self.assertEqual(ref['cases']['case5b_numerical_targets']['schema'],'atlas.tosi-case5b-reference.v1')
        self.assertFalse(ref['benchmark_accepted'])
    def test_case5a_dissipation_interpretation_preserves_printed_source(self):
        ref=json.loads((Path(__file__).parents[1]/'cases/convection_r4_4.json').read_bytes())
        self.assertIn('printed_Phi_min',ref['reported_values']['tosi-5a'])
        self.assertNotIn('dissipation_over_Ra_min',ref['reported_values']['tosi-5a'])
        mapping=ref['reference_policy']['case5a_dissipation']
        self.assertEqual(mapping['status'],'ADOPTED_DERIVED_INTERPRETATION')
        self.assertFalse(mapping['author_confirmed'])
        self.assertEqual(mapping['diagnostics']['printed_Phi_min'],'dissipation_over_Ra_min')
        self.assertIn('not an author-confirmed erratum',ref['conventions']['case5a_Phi'])
    def test_case5a_inferred_scaling_arithmetic_without_promoting_acceptance(self):
        ref=json.loads((Path(__file__).parents[1]/'cases/convection_r4_4.json').read_text(),parse_float=Decimal)
        case=ref['reported_values']['tosi-5a'];margin=ref['predeclared_acceptance']['table_relative_margin']
        for key,expected in [('printed_Phi_min',('1.3238855','1.3697145')),
                             ('printed_Phi_max',('9.0923','9.5877'))]:
            values=list(case[key].values());lo=min(values);hi=max(values);m=margin*max(abs(lo),abs(hi))
            self.assertEqual((lo-m,hi+m),tuple(map(Decimal,expected)))
        for code in ref['included_codes']:
            # Wbar >= minimum(Nu_top)-1, whereas raw-Phi reading gives a
            # contradictory upper bound Wbar <= maximum(printed Phi)/Ra.
            self.assertGreater(case['Nu_top_min'][code]-1,case['printed_Phi_max'][code]/100)
        self.assertEqual(ref['reference_review_2026_09_22']['case5a_scaling_status'],
                         'ADOPTED_DERIVED_INTERPRETATION')
        self.assertFalse(ref['benchmark_accepted'])
        self.assertEqual(ref['cases']['case5b_numerical_targets']['selection'],'finest-published-column-no-fallback.v1')


class QuadratureTests(unittest.TestCase):
    def test_constant_viscosity_buoyancy_solution_and_work_sign(self):
        from stokes_fixtures import unit_box,unit_scales,request
        # Independent continuum Stokes solution (not a thermal steady state).
        # eta=1, Ra=100, A=.01; C=Ra*A/(4*eta*pi^2).
        C=1/(4*math.pi**2);errors=[]
        for n in (8,16,32):
            box=unit_box(n);xw,yw=np.meshgrid(*box.axes('force_z'))
            force=100*(1-yw+.01*np.cos(math.pi*xw)*np.sin(math.pi*yw))
            with a.PreparedStokes2D(box,a.reference_rheology('constant'),unit_scales()) as plan:
                result=plan.solve(np.zeros((n,n-1)),force,**request(box))
            x,y=np.meshgrid(*box.axes('pressure'))
            temperature=1-y+.01*np.cos(math.pi*x)*np.sin(math.pi*y)
            u=result.array('u_m_s');w=result.array('w_m_s')
            exact_w=C*np.cos(math.pi*xw)*np.sin(math.pi*yw)
            self.assertGreater(float(np.sum(exact_w*w[1:-1])),0.)
            expected_p=100*(y-y*y/2)-.5/math.pi*np.cos(math.pi*x)*np.cos(math.pi*y)
            expected_p-=expected_p.mean()
            d=a.convection_diagnostics(temperature,u,w,np.ones((n,n)),np.ones((n-1,n-1)),a.reference_rheology('tosi-1'))
            self.assertGreater(d['work'],0.)
            self.assertEqual(d['dissipation_over_Ra'],d['dissipation']/100)
            errors.append([float(np.sqrt(np.mean((w[1:-1]-exact_w)**2))),
                           float(np.sqrt(np.mean((result.array('pressure_pa')-expected_p)**2))),
                           abs(d['work']-.01*C/4),abs(d['dissipation']-C*C*math.pi**2)])
        # Same existing second-order refinement criterion, no fitted tolerance.
        for coarse,fine in zip(errors,errors[1:]):
            self.assertTrue(all(3.7<c/f<4.6 for c,f in zip(coarse,fine)),errors)
    def test_conductive_flux_mean_and_zero_work(self):
        n=12;T=np.broadcast_to(1-(np.arange(n)+.5)[:,None]/n,(n,n)).copy()
        u=np.zeros((n,n+1));w=np.zeros((n+1,n))
        d=a.convection_diagnostics(T,u,w,np.ones((n,n)),np.ones((n-1,n-1)),a.reference_rheology('tosi-1'))
        for k in ('Nu_top','Nu_bottom'): self.assertAlmostEqual(d[k],1.,places=14)
        self.assertAlmostEqual(d['temperature_mean'],.5,places=14)
        for k in ('work','dissipation','work_dissipation_percent','velocity_rms'): self.assertEqual(d[k],0.)
    def test_domain_rms_integral(self):
        for n in (8,16,32):self.assertAlmostEqual(diagnostic(n)['velocity_rms'],math.pi/math.sqrt(2),places=13)
    def test_surface_rms_disclosed_nearest_row(self):
        for n in (8,16):
            self.assertAlmostEqual(diagnostic(n)['surface_velocity_rms'],math.pi/math.sqrt(2)*math.cos(math.pi/(2*n)),places=13)
    def test_surface_maximum_is_signed(self):
        T,u,w,c,v=fields(16)
        d=a.convection_diagnostics(T,-u,-w,c,v,a.reference_rheology('tosi-1'))
        self.assertEqual(d['surface_velocity_max'],0.)
        self.assertGreater(d['surface_speed_max'],3.)
    def test_work_continuum_limit_and_sign(self):
        target=.01*math.pi/4
        errors=[abs(diagnostic(n)['work']-target) for n in (8,16,32)]
        self.assertGreater(errors[0]/errors[1],3.9);self.assertGreater(errors[1]/errors[2],3.9)
    def test_dissipation_continuum_limit(self):
        errors=[abs(diagnostic(n)['dissipation']-math.pi**4) for n in (8,16,32)]
        self.assertGreater(errors[0]/errors[1],3.9);self.assertGreater(errors[1]/errors[2],3.9)
    def test_exact_discrete_dissipation_formula(self):
        n=16;self.assertAlmostEqual(diagnostic(n)['dissipation'],(2*math.pi*n*math.sin(math.pi/(2*n)))**2,places=11)
    def test_dissipation_two_normal_and_shear_terms(self):
        n=6;T,u,w,c,v=fields(n);u[2,3]+=.17
        ex=np.diff(u,axis=1)*n;ez=np.diff(w,axis=0)*n
        g=(np.diff(u[:,1:-1],axis=0)+np.diff(w[1:-1],axis=1))*n
        direct=0.
        for j in range(n):
            for i in range(n):direct+=2*(ex[j,i]**2+ez[j,i]**2)/n**2
        for j in range(n-1):
            for i in range(n-1):direct+=g[j,i]**2/n**2
        self.assertAlmostEqual(a.convection_diagnostics(T,u,w,c,v,a.reference_rheology('tosi-1'))['dissipation'],direct,places=11)
    def test_dissipation_normalisation_explicit(self):
        d=diagnostic(16);self.assertEqual(d['dissipation_over_Ra'],d['dissipation']/100)
    def test_incompressibility_reconstructed(self):
        self.assertLess(diagnostic(16)['divergence_linf'],1e-13)
    def test_boundary_inclusive_extrema(self):
        n=16;T,u,w,_,_=fields(n);u[:]=0;w[:]=0
        c=np.exp(-math.log(1e5)*T);v=.25*(c[:-1,:-1]+c[1:,:-1]+c[:-1,1:]+c[1:,1:])
        d=a.convection_diagnostics(T,u,w,c,v,a.reference_rheology('tosi-1'))
        self.assertAlmostEqual(d['viscosity_min'],1e-5,places=18)
        self.assertEqual(d['viscosity_max'],1)
        self.assertGreater(d['stress_support_viscosity_min'],d['viscosity_min'])
        self.assertLess(d['stress_support_viscosity_max'],d['viscosity_max'])
    def test_plastic_zero_rate_retains_factor_two_at_wall(self):
        n=8;T,u,w,c,v=fields(n);u[:]=0;w[:]=0
        d=a.convection_diagnostics(T,u,w,c,v,a.reference_rheology('tosi-2'))
        self.assertEqual(d['viscosity_max'],2.)
    def test_read_only_noncontiguous_inputs_are_not_mutated(self):
        vals=[]
        for x in fields(8):
            backing=np.zeros((x.shape[0],x.shape[1]*2));backing[:,::2]=x
            vals.append(backing[:,::2])
        orig=[x.copy() for x in vals]
        for x in vals:x.flags.writeable=False
        self.assertTrue(all(not x.flags.c_contiguous for x in vals))
        a.convection_diagnostics(*vals,a.reference_rheology('tosi-1'))
        for x,y in zip(vals,orig):np.testing.assert_array_equal(x,y)
    def test_invalid_shapes_nonfinite_and_wall_flux_refused(self):
        for index,change in [(0,'shape'),(1,'nan'),(2,'wall'),(3,'negative'),(4,'shape')]:
            vals=list(fields(8))
            if change=='shape':vals[index]=vals[index][:-1]
            elif change=='nan':vals[index][1,1]=np.nan
            elif change=='wall':vals[index][0,1]=.1
            else:vals[index][1,1]=-1
            with self.subTest(index=index),self.assertRaises(a.TectonicsError):
                a.convection_diagnostics(*vals,a.reference_rheology('tosi-1'))
    def test_temperature_not_clipped(self):
        vals=list(fields(8));vals[0][1,1]=-1e-15
        with self.assertRaises(a.TectonicsError):a.convection_diagnostics(*vals,a.reference_rheology('tosi-1'))
    def test_clipped_profile_refused(self):
        p=replace(a.reference_rheology('tosi-1'),viscosity_bounds=(1e-4,1))
        with self.assertRaises(a.TectonicsError):a.convection_diagnostics(*fields(8),p)
    def test_resource_release_and_refusal(self):
        b=WorkBudget(1<<20);a.convection_diagnostics(*fields(8),a.reference_rheology('tosi-1'),budget=b)
        self.assertEqual(b.statistics()['reserved_bytes'],0)
        with self.assertRaises(MemoryLimitError):a.convection_diagnostics(*fields(8),a.reference_rheology('tosi-1'),budget=WorkBudget(1))


class TemporalScreeningTests(unittest.TestCase):
    def constant(self):
        t=np.linspace(0,.2,801);return t,{k:np.ones_like(t) for k in _METRICS}
    def test_steady_complete_window(self):
        t,m=self.constant();d=a.steady_window(t,m);self.assertTrue(d['steady_samples']);self.assertFalse(d['full_benchmark_accepted'])
    def test_coincident_period_endpoints_are_not_steady(self):
        t,m=self.constant();m['Nu_top']=1+.1*np.sin(2*np.pi*t/.05)
        self.assertFalse(a.steady_window(t,m)['steady_samples'])
    def test_short_initial_segment_not_steady(self):
        t=np.linspace(0,.0001,201);m={k:np.ones_like(t) for k in _METRICS}
        self.assertFalse(a.steady_window(t,m)['steady_samples'])
    def test_missing_diagnostic_refused(self):
        t,m=self.constant();del m['work']
        with self.assertRaises(a.TectonicsError):a.steady_window(t,m)
    def test_insufficient_sampling_not_steady(self):
        t=np.linspace(0,.2,9);m={k:np.ones_like(t) for k in _METRICS}
        self.assertFalse(a.steady_window(t,m)['steady_samples'])
    def test_nonfinite_or_reversed_time_refused(self):
        t,m=self.constant()
        with self.assertRaises(a.TectonicsError):a.steady_window(t[::-1],m)
        m['work'][10]=np.nan
        with self.assertRaises(a.TectonicsError):a.steady_window(t,m)
    def test_resolved_periodic_signal(self):
        t=np.arange(0,15,.002);x=4+np.sin(2*np.pi*(t+.113))
        d=a.periodic_window(t,x);self.assertTrue(d['periodic_samples'])
        self.assertAlmostEqual(d['period'],1.,places=10);self.assertEqual(d['complete_cycles'],10)
        self.assertAlmostEqual(d['mean_cycle_peak'],5,places=4);self.assertFalse(d['full_benchmark_accepted'])
    def test_resolved_cycles_allow_current_partial_cycle(self):
        for stop in (12.7,13.25,13.2505):
            with self.subTest(stop=stop):
                t=np.arange(0,stop,.0005);x=4+np.sin(2*np.pi*t)
                d=a.periodic_window(t,x)
                self.assertTrue(d['periodic_samples'])
                self.assertTrue(d['endpoint_cycle_gate']['passed'])
    def test_old_stable_cycles_with_long_unresolved_tail_not_periodic(self):
        t=np.arange(0,16,.002)
        for slope in (0.,-.02):
            with self.subTest(tail='constant' if slope==0 else 'drifting'):
                x=np.where(t<=12.25,4+np.sin(2*np.pi*t),5+slope*(t-12.25))
                d=a.periodic_window(t,x)
                self.assertEqual(d['complete_cycles'],10)
                self.assertFalse(d['periodic_samples'])
                self.assertFalse(d['endpoint_cycle_gate']['passed'])
    def test_constant_is_not_periodic(self):
        t=np.linspace(0,20,2001);self.assertFalse(a.periodic_window(t,np.ones_like(t))['periodic_samples'])
    def test_fewer_than_ten_cycles_not_accepted(self):
        t=np.linspace(0,5,1001);self.assertFalse(a.periodic_window(t,4+np.sin(2*np.pi*t))['periodic_samples'])
    def test_low_amplitude_noise_not_periodic(self):
        t=np.linspace(0,20,10001);self.assertFalse(a.periodic_window(t,4+1e-5*np.sin(2*np.pi*t))['periodic_samples'])
    def test_periodic_with_drift_not_accepted(self):
        t=np.linspace(0,20,10001);self.assertFalse(a.periodic_window(t,4+.2*t+np.sin(2*np.pi*t))['periodic_samples'])
    def test_underresolved_cycles_not_accepted(self):
        t=np.linspace(0,20,501);self.assertFalse(a.periodic_window(t,4+np.sin(2*np.pi*t))['periodic_samples'])
    def test_irregular_times_refused(self):
        t=np.linspace(0,20,10001);x=4+np.sin(2*np.pi*t);t[20]+=.0001
        with self.assertRaises(a.TectonicsError):a.periodic_window(t,x)
    def test_invalid_period_policy_refused(self):
        t=np.linspace(0,2,201)
        for kwargs in ({'cycles':1},{'samples_per_period':1},{'period_relative_range':0}):
            with self.assertRaises(a.TectonicsError):a.periodic_window(t,np.sin(t),**kwargs)
    def test_known_second_order_refinement(self):
        d=a.refinement_differences({'x':1.04},{'x':1.01},{'x':1.0025})['x']
        self.assertAlmostEqual(d['observed_order_if_ratio_two'],2,places=12)
    def test_nonmonotone_refinement_not_given_order(self):
        self.assertIsNone(a.refinement_differences({'x':1.04},{'x':1.01},{'x':1.02})['x']['observed_order_if_ratio_two'])
    def test_exact_or_missing_refinement(self):
        self.assertIsNone(a.refinement_differences({'x':1},{'x':1},{'x':1})['x']['observed_order_if_ratio_two'])
        with self.assertRaises(a.TectonicsError):a.refinement_differences({'x':1},{},{'x':1})


class EndpointAndIdentityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p=a.TosiCase('tosi-1').problem(4)
        cls.s=a.ThermochemicalState(cls.p,a.tosi_initial_temperature(4),np.zeros((4,4)),time_s=0.,source='independent endpoint test')
        with a.PreparedVariableStokes2D(cls.p.box,cls.p.scales) as m:cls.f=a.tosi_endpoint_flow(cls.s,m)
        cls.small_p=a.TosiCase('tosi-1').problem(2)
        cls.small_s=a.ThermochemicalState(cls.small_p,a.tosi_initial_temperature(2),np.zeros((2,2)),time_s=0.,source='two-cell endpoint binding test')
        with a.PreparedVariableStokes2D(cls.small_p.box,cls.small_p.scales,policy=a.NonlinearStokesPolicy(method='direct')) as m:
            cls.small_f=a.tosi_endpoint_flow(cls.small_s,m)
    def test_endpoint_identity_and_independent_work(self):
        d=a.tosi_state_diagnostics(self.s,self.f)
        self.assertEqual(d['state_id'],self.s.state_id);self.assertEqual(d['flow_id'],self.f.result_id)
        self.assertLess(d['diagnostics']['work_dissipation_percent'],1e-5)
    def test_different_time_not_simultaneous(self):
        s=a.ThermochemicalState(self.p,self.s.array('temperature_k'),np.zeros((4,4)),time_s=1.,source='another time')
        with self.assertRaises(a.TectonicsError):a.tosi_state_diagnostics(s,self.f)
    def test_different_temperature_not_simultaneous(self):
        s=a.ThermochemicalState(self.p,np.full((4,4),1.5),np.zeros((4,4)),time_s=0.,source='another temperature')
        with self.assertRaises(a.TectonicsError):a.tosi_state_diagnostics(s,self.f)
    def test_nonzero_composition_not_published_case(self):
        s=a.ThermochemicalState(self.p,self.s.array('temperature_k'),np.ones((4,4)),time_s=0.,source='composition')
        with self.assertRaises(a.TectonicsError):a.tosi_state_diagnostics(s,self.f)
    def test_wrong_material_embedding_refused(self):
        p=replace(self.p,material=replace(self.p.material,conductivity_w_m_k=2.))
        s=a.ThermochemicalState(p,self.s.array('temperature_k'),np.zeros((4,4)),time_s=0.,source='different diffusivity')
        with self.assertRaises(a.TectonicsError):a.tosi_state_diagnostics(s,self.f)
    def test_two_cell_valid_embedding_retains_unaccepted_status(self):
        d=a.tosi_state_diagnostics(self.small_s,self.small_f)
        self.assertEqual(d['state_id'],self.small_s.state_id)
        self.assertEqual(d['flow_id'],self.small_f.result_id)
        self.assertFalse(d['full_benchmark_accepted'])
    def test_different_flow_scales_refused(self):
        p=self.small_p;s=self.small_s
        scales=replace(p.scales,viscosity_pa_s=2.)
        with a.PreparedVariableStokes2D(p.box,scales,policy=a.NonlinearStokesPolicy(method='direct')) as m:
            flow=m.solve_rheology(self.small_f.array('force_x_n_m3'),self.small_f.array('force_z_n_m3'),
                s.array('temperature_k'),p.rheology,frame_id=p.box.frame_id,epoch_id=p.epoch_id,
                time_s=s.time_s,source='valid mechanics with different viscosity scale')
        self.assertGreater(float(np.max(np.abs(flow.array('u_m_s')-self.small_f.array('u_m_s')))),0.)
        with self.assertRaisesRegex(a.TectonicsError,'not the simultaneous'):
            a.tosi_state_diagnostics(s,flow)
    def test_internal_heating_not_published_case(self):
        p=replace(self.small_p,material=replace(self.small_p.material,internal_heating_w_m3=1.))
        s=a.ThermochemicalState(p,self.small_s.array('temperature_k'),np.zeros((2,2)),time_s=0.,source='internally heated case')
        with self.assertRaisesRegex(a.TectonicsError,'declared unit numerical embedding'):
            a.tosi_state_diagnostics(s,self.small_f)
    def test_new_module_callable_identity_is_guarded(self):
        with ExecutionContext('scipy') as context:
            with mock.patch('atlas_tectonics.convection_benchmark.tosi_initial_temperature',lambda n:None):
                with self.assertRaises(a.TectonicsError):context.verify()
            context.verify()
    def test_new_module_constant_identity_is_guarded(self):
        with ExecutionContext('scipy') as context:
            with mock.patch('atlas_tectonics.convection_benchmark._DOI','different'):
                with self.assertRaises(a.TectonicsError):context.verify()
            context.verify()


if __name__ == '__main__':unittest.main()
