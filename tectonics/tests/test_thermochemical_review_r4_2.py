"""R4.2 independent conditioning, clock, source-product and physical controls.

SPDX-License-Identifier: AGPL-3.0-only
No change to retained cases, tolerances, physical equations or old test sources.
"""
from concurrent.futures import CancelledError
from dataclasses import replace
from decimal import Decimal, localcontext
import math
import threading
import unittest
from unittest import mock
import numpy as np
from numpy.testing import assert_allclose, assert_array_equal
from scipy.linalg import expm
from atlas_tectonics import (PreparedThermochemical2D, ThermochemicalState,
    ThermochemicalPolicy, TectonicsError, ThermalBoundary2D)
from atlas_tectonics import thermochemical as tc
from atlas_tectonics.thermochemical import _Diffusion2D, _weighted_source
from atlas_tectonics.thermochemical_execution import _endpoint_time
from atlas_tectonics.resources import WorkBudget
from thermochemical_fixtures import problem, initial, rest, circulation, dense_diffusion


def passive(p, tref):
    # Zero expansivity isolates thermal conditioning: changing Tref cannot change
    # this physical problem. A nonzero expansivity would change buoyancy inputs.
    return replace(p, material=replace(p.material, expansion_per_k=0.,
                                      reference_temperature_k=tref))


def dense_response(p, T, Q, dt):
    A, b = dense_diffusion(p)
    n = T.size
    block = np.zeros((n+1, n+1))
    block[:n, :n] = A
    block[:n, n] = b+Q.ravel()
    return (expm(block*dt) @ np.r_[T.ravel(), 1.])[:-1].reshape(T.shape)


class DiffusionConditioning(unittest.TestCase):
    def test_insulated_reference_temperature_is_not_a_boundary(self):
        T=np.array([[300.,302.],[304.,306.]])
        outputs=[]
        for ref in (1.,300.,1e12,1e16):
            p=passive(problem(2,fixed=False),ref);d=_Diffusion2D(p)
            a,_=d.advance(T,d.transform(np.zeros_like(T)),1e-12,None)
            outputs.append(a)
        for a in outputs[1:]:assert_array_equal(a,outputs[0])
        assert_allclose(outputs[0],dense_response(p,T,np.zeros_like(T),1e-12),rtol=0,atol=1.2e-13)

    def test_reference_independence_survives_complete_step(self):
        out=[]
        for ref in (300.,1e16):
            p=passive(problem(2,fixed=False,gravity=(0.,0.)),ref)
            s=initial(p,T=np.array([[300.,302.],[304.,306.]]),C=.25)
            with PreparedThermochemical2D(p) as plan:
                r=plan.advance(s,1e-12,source='reference independence',velocity=rest(p))
            out.append(r.state.array('temperature_k'))
            self.assertLess(r.descriptor()['record']['balances']['heat_relative_residual'],1e-14)
        assert_array_equal(*out)

    def test_large_interval_reference_independence_with_source(self):
        T=np.array([[302.,306.],[305.,301.]]);Q=np.array([[.1,.2],[.3,.4]])
        results=[]
        for ref in (1.,300.,1e16):
            p=passive(problem(2,fixed=False),ref);d=_Diffusion2D(p)
            a,_=d.advance(T,d.transform(Q),15.,None);results.append(a)
        for a in results[1:]:assert_array_equal(a,results[0])
        assert_allclose(a,dense_response(p,T,Q,15.),rtol=4e-15,atol=2e-13)

    def test_short_fixed_step_avoids_boundary_lift_cancellation(self):
        p=passive(problem(2),1.)
        p=replace(p,material=replace(p.material,temperature_range_k=(1.,2e16)),
                  boundary=ThermalBoundary2D('fixed-top-bottom',1e16,1e16))
        T=np.array([[300.,302.],[304.,306.]]);Q=np.zeros_like(T);dt=1e-14
        d=_Diffusion2D(p);a,_=d.advance(T,d.transform(Q),dt,None)
        # To binary64 accuracy the exact response is T+8K here. The dense ODE
        # still includes every diffusion and wall term, not a patched endpoint.
        assert_allclose(a,dense_response(p,T,Q,dt),rtol=0,atol=2e-13)

    def test_conditioning_switch_matches_independent_exponential(self):
        p=problem(4,3);T=initial(p).array('temperature_k');Q=np.arange(12).reshape(3,4)*.03
        d=_Diffusion2D(p);threshold=.5/float(d.rates.max())
        for dt in (threshold*(1-1e-9),threshold*(1+1e-9)):
            with self.subTest(dt=dt):
                a,_=d.advance(T,d.transform(Q),dt,None)
                assert_allclose(a,dense_response(p,T,Q,dt),rtol=3e-15,atol=3e-13)

    def test_insulated_needs_only_one_inverse_transform(self):
        p=problem(8,fixed=False);T=initial(p).array('temperature_k');d=_Diffusion2D(p);Q=d.transform(np.zeros_like(T))
        with mock.patch.object(d,'inverse',wraps=d.inverse) as call:
            _,walls=d.advance(T,Q,.1,None)
        self.assertEqual(call.call_count,1);self.assertEqual(walls,(0.,0.))

    def test_fixed_wall_time_integral_still_evaluated(self):
        p=problem(8);T=initial(p).array('temperature_k');d=_Diffusion2D(p);Q=d.transform(np.zeros_like(T))
        with mock.patch.object(d,'inverse',wraps=d.inverse) as call:
            _,walls=d.advance(T,Q,.1,None)
        self.assertEqual(call.call_count,2);self.assertNotEqual(walls,(0.,0.))

    def test_short_interval_does_not_redraw_constant_temperature(self):
        for fixed in (False,True):
            p=passive(problem(7,fixed=fixed),1e15)
            if fixed:p=replace(p,boundary=ThermalBoundary2D('fixed-top-bottom',303.,303.))
            d=_Diffusion2D(p);T=np.full((7,7),303.);Q=d.transform(np.zeros_like(T))
            a,_=d.advance(T,Q,1e-30,None)
            assert_array_equal(a,T)

    def test_insulated_offset_not_retained_between_different_fields(self):
        p=passive(problem(4,fixed=False),1e16);d=_Diffusion2D(p);Q=d.transform(np.zeros((4,4)))
        for T in (np.full((4,4),5.),np.full((4,4),305.),np.full((4,4),10.)):
            a,_=d.advance(T,Q,.1,None);assert_array_equal(a,T)

    def test_changed_dt_cache_retains_scientific_result(self):
        p=problem(6,fixed=False);T=initial(p).array('temperature_k');d=_Diffusion2D(p);Q=d.transform(np.zeros_like(T))
        a,_=d.advance(T,Q,.01,None);d.advance(T,Q,40.,None);b,_=d.advance(T,Q,.01,None)
        assert_array_equal(a,b)

    def test_semigroup_across_conditioning_routes(self):
        p=problem(4);T=initial(p).array('temperature_k');d=_Diffusion2D(p);Q=d.transform(np.full_like(T,.1))
        t=.2/float(d.rates.max());one,_=d.advance(T,Q,4*t,None)
        many=T
        for _ in range(4):many,_=d.advance(many,Q,t,None)
        assert_allclose(one,many,rtol=0,atol=2e-13)


class WeightedSourceProducts(unittest.TestCase):
    def reference(self,a,w,t):
        with localcontext() as c:
            c.prec=100
            return float(Decimal.from_float(a)*Decimal.from_float(w)*Decimal.from_float(t))

    def test_nonzero_subnormal_factor_is_not_pre_rounded(self):
        tiny=float(np.nextafter(0.,1.));dt=3*tiny
        a=1e200;w=.5
        got=float(_weighted_source(np.array([[a]]),np.array([[w]]),dt)[0,0])
        self.assertLess(abs(got/self.reference(a,w,dt)-1),4e-16)

    def test_subnormal_weight_times_dt_final_normal(self):
        a=1e200;w=1e-200;dt=1e-120
        got=float(_weighted_source(np.array([[a]]),np.array([[w]]),dt)[0,0])
        self.assertLess(abs(got/self.reference(a,w,dt)-1),4e-16)

    def test_signed_source_modes_and_zeros(self):
        dt=3*float(np.nextafter(0.,1.));a=np.array([[-1e200,0.,1e200]]);w=np.full_like(a,.5)
        got=_weighted_source(a,w,dt)
        for j in range(3):self.assertEqual(got[0,j],self.reference(float(a[0,j]),.5,dt))

    def test_mixed_normal_subnormal_source_factors(self):
        a=np.array([[1e200,1e100,0.,-1e200]]);w=np.array([[1e-200,1.,0.,1e-200]]);dt=1e-120
        expected=np.array([[self.reference(float(v),float(f),dt) for v,f in zip(a[0],w[0])]])
        assert_allclose(_weighted_source(a,w,dt),expected,rtol=4e-16,atol=0)

    def test_prepared_weight_matches_uncached_for_both_ranges(self):
        a=np.array([[1e200,-1e200,0.]])
        for w,dt in ((np.full_like(a,.5),3*float(np.nextafter(0.,1.))),
                     (np.full_like(a,1e-200),.1)):
            fast=_weighted_source(a,w,dt,prepared=tc._source_weight(w,dt))
            assert_array_equal(fast,_weighted_source(a,w,dt))

    def test_inputs_not_modified(self):
        a=np.array([[1e200]]);w=np.array([[.5]]);ac=a.copy();wc=w.copy()
        _weighted_source(a,w,3*float(np.nextafter(0.,1.)))
        assert_array_equal(a,ac);assert_array_equal(w,wc)


class ClockAndPublication(unittest.TestCase):
    def test_increasing_but_wrong_duration_refused(self):
        with self.assertRaises(TectonicsError):_endpoint_time(1e16,3.,ThermochemicalPolicy())

    def test_negative_epoch_wrong_duration_refused(self):
        with self.assertRaises(TectonicsError):_endpoint_time(-1e16,3.,ThermochemicalPolicy())

    def test_exact_large_epoch_interval_allowed(self):
        self.assertEqual(_endpoint_time(1e16,4.,ThermochemicalPolicy()),1e16+4.)

    def test_odd_subnormal_half_interval_refused(self):
        tiny=float(np.nextafter(0.,1.))
        with self.assertRaises(TectonicsError):_endpoint_time(0.,3*tiny,ThermochemicalPolicy())

    def test_exact_subnormal_half_interval_allowed(self):
        dt=4*float(np.nextafter(0.,1.))
        self.assertEqual(_endpoint_time(0.,dt,ThermochemicalPolicy()),dt)

    def test_long_sequence_not_arbitrarily_required_bit_exact(self):
        time=0.;policy=ThermochemicalPolicy()
        for _ in range(4096):time=_endpoint_time(time,.1,policy)
        self.assertAlmostEqual(time,409.6,places=8)

    def test_large_time_failure_is_before_evolution_and_recoverable(self):
        p=problem(2,fixed=False);base=initial(p,T=300.,C=.25)
        s=ThermochemicalState(p,base.array('temperature_k'),base.array('composition'),time_s=1e16,source='named epoch')
        budget=WorkBudget(64<<20)
        with PreparedThermochemical2D(p,budget=budget) as plan:
            held=budget.reserved_bytes
            with mock.patch.object(plan._diffusion,'advance',wraps=plan._diffusion.advance) as d:
                with self.assertRaises(TectonicsError):plan.advance(s,3.,source='invalid duration',velocity=rest(p))
                self.assertEqual(d.call_count,0)
            self.assertEqual(budget.reserved_bytes,held)
            r=plan.advance(s,4.,source='exact duration',extra_heating_w_m3=.125,velocity=rest(p))
            assert_array_equal(r.state.array('temperature_k'),300.5)
            self.assertEqual(r.state.time_s-s.time_s,4.)
        self.assertEqual(budget.reserved_bytes,0)

    def test_new_step_records_precision_contract(self):
        p=problem(2);s=initial(p)
        with PreparedThermochemical2D(p) as plan:r=plan.advance(s,.01,source='publication',velocity=rest(p))
        self.assertEqual(r.state.descriptor()['step_record']['publication_contract'],tc._PUBLICATION_CONTRACT)

    def test_current_snapshot_bad_clock_refused(self):
        p=problem(2);s=initial(p)
        with PreparedThermochemical2D(p) as plan:r=plan.advance(s,.01,source='publication',velocity=rest(p))
        meta=r.state.descriptor();meta['time_s']=1e16+4.;meta['step_record']['input_time_s']=1e16;meta['step_record']['dt_s']=3.
        with self.assertRaises(TectonicsError):ThermochemicalState.restore(meta,{k:r.state.array(k) for k in ('temperature_k','composition')})

    def test_legacy_record_decodes_without_new_guarantee(self):
        # Construct a legacy-shaped record only to check schema compatibility;
        # this is not asserted to be a historic run. Separate delivery evidence
        # restores a snapshot actually created by the original dev28 interpreter.
        p=problem(2);s=initial(p)
        with PreparedThermochemical2D(p) as plan:r=plan.advance(s,.01,source='publication',velocity=rest(p))
        meta=r.state.descriptor();del meta['step_record']['publication_contract']
        a=ThermochemicalState.restore(meta,{k:r.state.array(k) for k in ('temperature_k','composition')})
        self.assertNotIn('publication_contract',a.descriptor()['step_record'])
        self.assertEqual(a.descriptor(),meta)

    def test_unknown_publication_contract_refused(self):
        p=problem(2);s=initial(p)
        with PreparedThermochemical2D(p) as plan:r=plan.advance(s,.01,source='publication',velocity=rest(p))
        meta=r.state.descriptor();meta['step_record']['publication_contract']='unverified'
        with self.assertRaises(TectonicsError):ThermochemicalState.restore(meta,{k:r.state.array(k) for k in ('temperature_k','composition')})

    def test_clock_constant_mutation_is_source_checked(self):
        p=problem(2);s=initial(p)
        with PreparedThermochemical2D(p) as plan:
            with mock.patch.object(tc,'_TIME_RTOL',.1):
                with self.assertRaises(TectonicsError):plan.advance(s,.01,source='mutated',velocity=rest(p))
            plan.advance(s,.01,source='recovered',velocity=rest(p))

    def test_conditioned_diffusion_cancellation_releases_admission(self):
        p=problem(4,fixed=False);s=initial(p);budget=WorkBudget(64<<20);event=threading.Event()
        with PreparedThermochemical2D(p,budget=budget) as plan:
            held=budget.reserved_bytes;event.set()
            with self.assertRaises(CancelledError):plan.advance(s,.01,source='cancelled',velocity=rest(p),cancel=event)
            self.assertEqual(budget.reserved_bytes,held);event.clear()
            plan.advance(s,.01,source='continued',velocity=rest(p))
        self.assertEqual(budget.reserved_bytes,0)


class IndependentPhysicalControls(unittest.TestCase):
    def test_heated_steady_parabola_refines(self):
        # Exact continuum cell averages include the h^2/12 correction. This is
        # not a discrete operator used to invent its own manufactured source.
        errors=[]
        for n in (8,16,32):
            p=problem(3,n,height=1.,k=.2);d=_Diffusion2D(p)
            z=(np.arange(n)+.5)/n
            exact=310.-10*z+.3/(2*.2)*(z*(1-z)-1/(12*n*n))
            initial_T=np.broadcast_to((310.-10*z)[:,None],(n,3)).copy()
            out,flux=d.advance(initial_T,d.transform(np.full((n,3),.3)),100.,None)
            errors.append(float(np.max(np.abs(out-exact[:,None]))))
        for a,b in zip(errors,errors[1:]):self.assertGreater(a/b,3.98);self.assertLess(a/b,4.02)

    def test_source_free_insulated_diffusion_reduces_variance(self):
        p=problem(11,7,fixed=False);T=300+np.random.default_rng(71).uniform(-10,10,(7,11));d=_Diffusion2D(p)
        mean=math.fsum(T.flat)/T.size
        out,flux=d.advance(T,d.transform(np.zeros_like(T)),1.,None)
        self.assertLess(np.mean((out-mean)**2),np.mean((T-mean)**2))
        self.assertAlmostEqual(math.fsum(out.flat),math.fsum(T.flat),places=10)
        self.assertEqual(flux,(0.,0.))

    def test_closed_composition_complement_covariance(self):
        p=problem(7,fixed=False);s=initial(p,T=305.);C=s.array('composition')
        reverse=initial(p,T=305.,C=1-C);v=circulation(p,.1)
        with PreparedThermochemical2D(p) as plan:
            a=plan.advance(s,.02,source='C',velocity=v)
            b=plan.advance(reverse,.02,source='complement',velocity=v)
        assert_allclose(a.state.array('composition'),1-b.state.array('composition'),rtol=0,atol=4e-16)

    def test_insulated_axis_transpose_whole_step(self):
        p=problem(5,3,width=2.,height=1.,fixed=False);q=problem(3,5,width=1.,height=2.,fixed=False)
        T=300+np.arange(15).reshape(3,5)*.1;C=np.full((3,5),.25)
        with PreparedThermochemical2D(p) as a,PreparedThermochemical2D(q) as b:
            x=a.advance(initial(p,T=T,C=C),.2,source='transpose',velocity=rest(p))
            y=b.advance(initial(q,T=T.T,C=C.T),.2,source='transpose',velocity=rest(q))
        assert_allclose(x.state.array('temperature_k'),y.state.array('temperature_k').T,rtol=0,atol=1.2e-13)

    def test_energy_includes_each_source_and_boundary_once(self):
        p=problem(4,3,k=.2,heating=.25);s=initial(p)
        with PreparedThermochemical2D(p) as plan:r=plan.advance(s,.1,source='heat audit',extra_heating_w_m3=.5,velocity=rest(p))
        b=r.state.descriptor()['step_record']['balances']
        self.assertAlmostEqual(b['source_heat_j'],.075,places=15)
        self.assertLess(abs(math.fsum((b['heat_change_j'],-b['source_heat_j'],b['top_outward_heat_j'],b['bottom_outward_heat_j']))),1e-12)


if __name__=='__main__':unittest.main()
