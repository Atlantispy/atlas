"""Independent local-law values, limits and SI contracts; no solver benchmark.
SPDX-License-Identifier: AGPL-3.0-only
"""
from dataclasses import replace, FrozenInstanceError
from decimal import Decimal, localcontext
import math
import unittest
from unittest import mock
import threading
from concurrent.futures import CancelledError

import numpy as np
from numpy.testing import assert_allclose, assert_array_equal

from atlas_tectonics import (ConstitutiveLimits, DiffusiveScales, RheologyProfile,
    reference_rheology, evaluate_rheology, advance_memory, strain_rate_invariant,
    BoussinesqMaterial, boussinesq_response, stress_and_dissipation, TectonicsError)
from atlas_tectonics.resources import WorkBudget, MemoryLimitError


def variant(profile,**updates):
    return replace(profile,name='authored-unit-test-variant',source='test analytical case',
                   parameters=tuple((k,updates.get(k,v)) for k,v in profile.parameters))


def tosi_decimal(case,T,z,e):
    """80-digit direct published equation, deliberately not production algebra."""
    with localcontext() as ctx:
        ctx.prec=80
        D=lambda x:Decimal(str(x))
        L=(-D(1e5).ln()*D(T)+D(10 if case in (3,4,5) else 1).ln()*D(z)).exp()
        if case in (1,3):return float(L)
        if not e:return float(2*L)
        P=D('.001')+D(4 if case==5 else 1)/(D(2).sqrt()*D(e))
        return float(2/(1/L+1/P))


class TosiTests(unittest.TestCase):
    def test_published_table_parameters(self):
        for i,name in ((1,'tosi-1'),(2,'tosi-2'),(3,'tosi-3'),(4,'tosi-4'),(5,'tosi-5a')):
            with self.subTest(name=name):
                p=reference_rheology(name); a=dict(p.parameters)
                self.assertEqual(a['contrast_T'],1e5)
                self.assertEqual(a['contrast_z'],10 if i>=3 else 1)
                self.assertEqual(p.family,'tosi-linear' if i in (1,3) else 'tosi-plastic')
                if i in (2,4,5):self.assertEqual((a['eta_star'],a['sigma_y']),(.001,4 if i==5 else 1))
    def test_all_five_cases_against_decimal(self):
        for i,name in ((1,'tosi-1'),(2,'tosi-2'),(3,'tosi-3'),(4,'tosi-4'),(5,'tosi-5a')):
            for T,z,e in ((0,0,0),(1,1,1),(.5,.5,1),(.123,.789,100),(.9,.2,1e12)):
                with self.subTest(case=name,T=T,z=z,e=e):
                    r=evaluate_rheology(reference_rheology(name),T,z,e)
                    assert_allclose(r['viscosity'],tosi_decimal(i,T,z,e),rtol=3e-15,atol=0)
    def test_zero_rate_nonlinear_is_twice_linear(self):
        for a,b in (('tosi-1','tosi-2'),('tosi-3','tosi-4')):
            assert_allclose(evaluate_rheology(reference_rheology(b),[0,.5,1],.7,0)['viscosity'],
                            2*evaluate_rheology(reference_rheology(a),[0,.5,1],.7,0)['viscosity'],rtol=0,atol=0)
    def test_no_hidden_rate_epsilon(self):
        p=reference_rheology('tosi-2')
        a=evaluate_rheology(p,0,0,0)['viscosity']
        b=evaluate_rheology(p,0,0,1e-300)['viscosity']
        self.assertEqual(float(a),2.); self.assertEqual(float(b),2.)
    def test_frobenius_denominator_not_second_invariant(self):
        actual=float(evaluate_rheology(reference_rheology('tosi-2'),0,0,1)['viscosity'])
        correct=2/(1+1/(.001+1/math.sqrt(2)))
        wrong=2/(1+1/(.001+1))
        self.assertAlmostEqual(actual,correct,15); self.assertGreater(abs(actual-wrong),.1)
    def test_zero_yield_valid_limit(self):
        p=variant(reference_rheology('tosi-2'),sigma_y=0)
        expected=2/(1+1/.001)
        assert_allclose(evaluate_rheology(p,0,0,[0,1,1e16])['viscosity'],expected,rtol=2e-16)
    def test_temperature_monotonicity(self):
        a=evaluate_rheology(reference_rheology('tosi-4'),np.linspace(0,1,100),.5,1)['viscosity']
        self.assertTrue(np.all(np.diff(a)<0))
    def test_depth_dependence_and_constant_control(self):
        p=reference_rheology('tosi-3')
        r=evaluate_rheology(p,.5,[0,1],1)
        self.assertAlmostEqual(r['viscosity'][1]/r['viscosity'][0],10.)
        assert_array_equal(evaluate_rheology(reference_rheology('constant'),[0,.5,1],0,[0,1,100])['viscosity'],[1,1,1])
    def test_damage_not_silently_ignored(self):
        with self.assertRaises(TectonicsError):evaluate_rheology(reference_rheology('tosi-1'),.5,.5,1,1)
    def test_linear_yield_not_fabricated(self):
        self.assertNotIn('yield_parameter',evaluate_rheology(reference_rheology('tosi-1'),.5,.5,1))
    def test_viscosity_bound_reports_floor_and_ceiling(self):
        p=replace(reference_rheology('tosi-1'),name='explicit-bounds-test',viscosity_bounds=(.001,.1))
        r=evaluate_rheology(p,[0,.5,1],0,1)
        assert_array_equal(r['viscosity_bound_code'],[2,0,1])
        assert_allclose(r['viscosity'],[.1,math.sqrt(1e-5),.001],rtol=2e-15)
    def test_bound_changes_profile_identity(self):
        p=reference_rheology('tosi-1')
        self.assertNotEqual(p.profile_id,replace(p,viscosity_bounds=(1e-6,1.)).profile_id)


class MemoryTests(unittest.TestCase):
    def setUp(self):self.p=reference_rheology('bf23-memory')
    def test_model19_source_parameters(self):
        self.assertEqual(dict(self.p.parameters),dict(E=40,eta0=1,a=1e6,b=1.51e7,dcrit=10,weakening=.9,B=2.44e9,Ed=46.1))
    def test_equation6_temperature_values(self):
        T=np.array([0,.25,.5,.75,1.])
        r=evaluate_rheology(self.p,T,0,0,0)
        assert_allclose(r['viscosity'],[math.exp(40/(x+1)-20) for x in T],rtol=2e-15)
    def test_yield_stress_invariant(self):
        r=evaluate_rheology(self.p,0,[0,.5,1],1e8,[0,5,10])
        expected=(1e6+1.51e7*np.array([0,.5,1]))*np.array([1,.55,.1])
        assert_allclose(r['stress_ii'],expected,rtol=3e-15)
    def test_strength_saturates_but_history_not_clipped(self):
        r=evaluate_rheology(self.p,0,0,1,[0,5,10,20,100])
        assert_allclose(r['weakening_factor'],[1,.55,.1,.1,.1],rtol=2e-15)
        self.assertGreater(float(advance_memory(self.p,100,0,0,1)),10)
    def test_damage_free_control(self):
        p=reference_rheology('bf23-no-damage')
        a=evaluate_rheology(p,0,.3,1e5,0)
        b=evaluate_rheology(p,0,.3,1e5,100)
        assert_array_equal(a['viscosity'],b['viscosity'])
        assert_array_equal(b['weakening_factor'],1.)
    def test_healing_exponent_not_2022_half_factor(self):
        r=evaluate_rheology(self.p,[0,.5,1],0,0,0)
        expected=[2.44e9*math.exp(-46.1/(T+1)+23.05) for T in (0,.5,1)]
        assert_allclose(r['healing_rate'],expected,rtol=2e-15)
        self.assertGreater(abs(r['healing_rate'][0]-2.44e9*math.exp(-46.1/4)),1e4)
    def test_healing_only_analytic(self):
        for T,dt in ((0,1),(.5,1e-6),(1,1e-9)):
            with self.subTest(T=T):
                h=2.44e9*math.exp(-46.1/(T+1)+23.05)
                expected=12*math.exp(-h*dt)
                assert_allclose(advance_memory(self.p,12,0,T,dt),expected,rtol=2e-15)
    def test_loading_healing_equilibrium(self):
        T=.5;h=2.44e9*math.exp(-46.1/(T+1)+23.05);eq=3/h
        assert_allclose(advance_memory(self.p,eq,3,T,1),eq,rtol=2e-15)
    def test_zero_healing_linear_strain(self):
        p=variant(self.p,B=0)
        assert_array_equal(advance_memory(p,[1,20],[2,3],[0,1],.5),[2,21.5])
    def test_zero_time_exact(self):
        assert_array_equal(advance_memory(self.p,[1,20,300],1,[0,.5,1],0),[1,20,300])
    def test_constant_coefficients_semigroup(self):
        T=np.array([0,.2,.5,1]);dt=1e-8
        a=advance_memory(self.p,[1,3,10,20],5,T,2*dt)
        b=advance_memory(self.p,advance_memory(self.p,[1,3,10,20],5,T,dt),5,T,dt)
        assert_allclose(a,b,rtol=6e-15,atol=1e-24)
    def test_tiny_healing_gain_no_cancellation(self):
        p=variant(self.p,B=1e-100)
        assert_allclose(advance_memory(p,0,2,0,1e-10),2e-10,rtol=0,atol=0)
    def test_large_time_relaxes_without_negative_values(self):
        a=advance_memory(self.p,[0,100],1,1,1e12)
        assert_allclose(a,1/2.44e9,rtol=0,atol=0)
    def test_memory_output_envelope_fails_not_clips(self):
        with self.assertRaises(TectonicsError):advance_memory(variant(self.p,B=0),9,10,0,1,limits=ConstitutiveLimits(max_damage=10))
    def test_wrong_family_refused(self):
        with self.assertRaises(TectonicsError):advance_memory(reference_rheology('constant'),0,0,0,1)
    def test_unknown_initial_damage_refused(self):
        with self.assertRaises(TectonicsError):evaluate_rheology(self.p,.5,.5,1)
    def test_negative_time_refused(self):
        with self.assertRaises(TectonicsError):advance_memory(self.p,0,0,0,-1)
    def test_elapsed_cap_refused(self):
        with self.assertRaises(TectonicsError):advance_memory(self.p,0,0,0,2,limits=ConstitutiveLimits(max_elapsed=1))


class InputAndResourceTests(unittest.TestCase):
    def setUp(self):self.p=reference_rheology('tosi-2')
    def test_immutable_profile(self):
        with self.assertRaises(FrozenInstanceError):self.p.family='constant'
    def test_parameter_order_and_unknown_family(self):
        for bad in ({'family':'unknown'},{'parameters':(('bad',1.),)}):
            with self.subTest(bad=bad),self.assertRaises(TectonicsError):replace(self.p,**bad)
    def test_invalid_parameters(self):
        for changes in ({'contrast_T':.5},{'contrast_z':1e31},{'eta_star':0},{'sigma_y':-1}):
            with self.subTest(changes=changes),self.assertRaises(TectonicsError):variant(self.p,**changes)
    def test_invalid_memory_parameters(self):
        for changes in ({'weakening':1},{'a':0},{'dcrit':0},{'E':101},{'Ed':101},{'B':-1}):
            with self.subTest(changes=changes),self.assertRaises(TectonicsError):variant(reference_rheology('bf23-memory'),**changes)
    def test_bad_bounds(self):
        for b in ((0,1),(2,1),(1e-101,1),(1,1e101),[1,2]):
            with self.subTest(b=b),self.assertRaises(TectonicsError):replace(self.p,viscosity_bounds=b)
    def test_unknown_profile(self):
        with self.assertRaises(TectonicsError):reference_rheology('earth-default')
    def test_nonfinite_mask_string_bool(self):
        for T in (float('nan'),float('inf'),True,'0.5',np.ma.array([.5],mask=[True])):
            with self.subTest(T=str(T)),self.assertRaises(TectonicsError):evaluate_rheology(self.p,T,0,1)
    def test_temperature_depth_rate_damage_envelopes(self):
        for args in ((-1,0,1,0),(2,0,1,0),(.5,-1,1,0),(.5,2,1,0),(.5,0,-1,0),(.5,0,1,-1),(.5,0,1e17,0)):
            with self.subTest(args=args),self.assertRaises(TectonicsError):evaluate_rheology(self.p,*args)
    def test_unbroadcastable(self):
        with self.assertRaises(TectonicsError):evaluate_rheology(self.p,[0,1],[0,.5,1],1)
    def test_empty_array(self):
        with self.assertRaises(TectonicsError):evaluate_rheology(self.p,np.empty(0),0,1)
    def test_before_allocation_memory_refusal(self):
        b=WorkBudget(1)
        with mock.patch('atlas_tectonics.constitutive.read_array',side_effect=AssertionError('converted too early')):
            with self.assertRaises(MemoryLimitError):evaluate_rheology(self.p,np.zeros(20),0,1,budget=b)
        self.assertEqual(b.reserved_bytes,0)
    def test_point_limit_before_allocation(self):
        with self.assertRaises(TectonicsError):evaluate_rheology(self.p,np.zeros(10),0,1,limits=ConstitutiveLimits(max_points=9))
    def test_budget_released_after_success_and_failure(self):
        b=WorkBudget(4<<20)
        evaluate_rheology(self.p,np.zeros(100),0,1,budget=b)
        self.assertEqual(b.reserved_bytes,0)
        with self.assertRaises(TectonicsError):evaluate_rheology(self.p,np.zeros(100),-1,1,budget=b)
        self.assertEqual(b.reserved_bytes,0)
    def test_batching_exact(self):
        x=np.linspace(0,1,101)
        a=evaluate_rheology(self.p,x,.5,1,limits=ConstitutiveLimits(batch_points=1))
        b=evaluate_rheology(self.p,x,.5,1,limits=ConstitutiveLimits(batch_points=37))
        for k in a:assert_array_equal(a[k],b[k])
    def test_broadcast_strides(self):
        T=np.linspace(0,1,10)[::2,None];z=np.array([0,.5,1])[None,:]
        r=evaluate_rheology(self.p,T,z,1)
        expected=np.array([[tosi_decimal(2,t,x,1) for x in z[0]] for t in T[:,0]])
        assert_allclose(r['viscosity'],expected,rtol=3e-15)
    def test_output_bytes_immutable_and_detached(self):
        T=np.array([0,.5,1]);r=evaluate_rheology(self.p,T,0,1);old=r['viscosity'].copy();T[:]=0
        assert_array_equal(r['viscosity'],old)
        with self.assertRaises(ValueError):r['viscosity'].setflags(write=True)
    def test_cancellation(self):
        e=threading.Event();e.set();b=WorkBudget(1<<20)
        with self.assertRaises(CancelledError):evaluate_rheology(self.p,[0,1],0,1,cancel=e,budget=b)
        self.assertEqual(b.reserved_bytes,0)
    def test_mid_call_cancellation_releases_budget(self):
        class Token:
            n=0
            def is_set(self):self.n+=1;return self.n>=4
        b=WorkBudget(4<<20)
        with self.assertRaises(CancelledError):evaluate_rheology(self.p,np.zeros(100),0,1,limits=ConstitutiveLimits(batch_points=10),cancel=Token(),budget=b)
        self.assertEqual(b.reserved_bytes,0)


class InvariantAndUnitsTests(unittest.TestCase):
    def test_pure_shear(self):self.assertEqual(float(strain_rate_invariant([[3,0],[0,-3]])),3.)
    def test_simple_shear(self):self.assertEqual(float(strain_rate_invariant([[0,2],[2,0]])),2.)
    def test_uniaxial_3d(self):self.assertAlmostEqual(float(strain_rate_invariant(np.diag([2,-1,-1]))),math.sqrt(3))
    def test_zero_invariant(self):self.assertEqual(float(strain_rate_invariant(np.zeros((3,3)))),0.)
    def test_rotation_invariance(self):
        a=np.array([[2,3,4],[3,-1,5],[4,5,-1.]])
        q,_=np.linalg.qr(np.random.default_rng(17).normal(size=(3,3)))
        assert_allclose(strain_rate_invariant(q@a@q.T),strain_rate_invariant(a),rtol=1e-15)
    def test_nonsymmetric_velocity_gradient_rejected(self):
        with self.assertRaises(TectonicsError):strain_rate_invariant([[0,4],[0,0]])
    def test_extreme_invariant_without_square_overflow(self):
        for x in (1e-250,1e250):
            assert_allclose(strain_rate_invariant([[x,0],[0,-x]]),x,rtol=2e-16,atol=0)
    def test_stress_heat_identity(self):
        e=np.array([[1.,2],[2,-1]])
        a=stress_and_dissipation(3.,e)
        assert_array_equal(a['deviatoric_stress'],6*e)
        self.assertAlmostEqual(float(a['viscous_dissipation']),float(np.sum(a['deviatoric_stress']*e)),12)
    def test_compressible_strain_not_mislabelled_deviatoric(self):
        with self.assertRaises(TectonicsError):stress_and_dissipation(3,np.eye(2))
    def test_scale_underflow_refused(self):
        with self.assertRaises(TectonicsError):DiffusiveScales('underflow',1e-200,1e100,1,300,1,1)
    def test_stress_invalid_viscosity(self):
        with self.assertRaises(TectonicsError):stress_and_dissipation(0,np.eye(2))
    def test_diffusive_scales_independent_values(self):
        s=DiffusiveScales('unit-test-not-Earth',2,4,8,300,1000,2)
        self.assertEqual(s.time_s,1);self.assertEqual(s.velocity_m_s,2);self.assertEqual(s.stress_pa,8)
        self.assertEqual(s.rayleigh(2,4,.001),2.)
    def test_scale_inputs_invalid(self):
        for v in (0,-1,True,float('inf')):
            with self.subTest(v=v),self.assertRaises(TectonicsError):DiffusiveScales('bad',v,1,1,300,1,1)
    def test_scale_overflow_refused(self):
        with self.assertRaises(TectonicsError):DiffusiveScales('bad',1e200,1e-100,1,300,1,1)


def material(**changes):
    return replace(BoussinesqMaterial('authored-analytical','unit test, not mantle measurements',
        3000,1000,3,1e-5,1000,-100,2e-6,(300,1500)),**changes)


class ThermochemicalTests(unittest.TestCase):
    def test_buoyancy_sign_and_reference_density(self):
        r=boussinesq_response(material(),[1000,1100],0,[0,-10],[0,0])
        assert_allclose(r['density_anomaly_kg_m3'],[0,-3],rtol=2e-16,atol=0)
        assert_allclose(r['body_force_n_m3'],[[0,0],[0,30]],rtol=2e-16,atol=0)
        assert_array_equal(r['heat_capacity_j_m3_k'],[3e6,3e6])
    def test_composition_buoyancy_without_renormalisation(self):
        r=boussinesq_response(material(),1000,[0,.25,1],[0,-10],[0,0])
        assert_array_equal(r['density_anomaly_kg_m3'],[0,-25,-100])
    def test_fourier_heat_flux_sign(self):
        r=boussinesq_response(material(),1000,0,[0,-10],[2,-4])
        assert_array_equal(r['conductive_flux_w_m2'],[-6,12])
    def test_heat_explicit_dissipation_once(self):
        r=boussinesq_response(material(),1000,0,[0,-10],[0,0],viscous_dissipation_w_m3=3e-6)
        self.assertAlmostEqual(float(r['heating_w_m3']),5e-6,20)
    def test_zero_heating_explicit_control(self):
        self.assertEqual(float(boussinesq_response(material(internal_heating_w_m3=0),1000,0,[0,-10],[0,0])['heating_w_m3']),0)
    def test_pressure_not_silently_consumed(self):
        with self.assertRaises(TypeError):boussinesq_response(material(),1000,0,[0,-10],[0,0],pressure_pa=1e9)
    def test_temperature_composition_invalid(self):
        for T,C in ((299,0),(1501,0),(1000,-.1),(1000,1.1)):
            with self.subTest(T=T,C=C),self.assertRaises(TectonicsError):boussinesq_response(material(),T,C,[0,-10],[0,0])
    def test_boussinesq_anomaly_envelope(self):
        with self.assertRaises(TectonicsError):boussinesq_response(material(composition_density_contrast_kg_m3=1000),1000,1,[0,-10],[0,0])
    def test_negative_dissipation_refused(self):
        with self.assertRaises(TectonicsError):boussinesq_response(material(),1000,0,[0,-10],[0,0],viscous_dissipation_w_m3=-1)
    def test_3d_vector_broadcast(self):
        r=boussinesq_response(material(),np.full((2,1),1000),0,np.ones((1,3,3)),[1,2,3])
        self.assertEqual(r['body_force_n_m3'].shape,(2,3,3))
    def test_vector_rank_refused(self):
        with self.assertRaises(TectonicsError):boussinesq_response(material(),1000,0,1,[0,0])
    def test_thermochemical_resource_refusal(self):
        with self.assertRaises(MemoryLimitError):boussinesq_response(material(),1000,0,[0,-10],[0,0],budget=WorkBudget(1))


if __name__=='__main__':unittest.main()
