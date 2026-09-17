"""W02 synthetic mathematics plus resource, cache and independent-job integration.

Expected fluxes use rational arithmetic and exact cell integrals. These tests do
not calibrate real geology, retune preceding tests or include timing thresholds.
"""
from concurrent.futures import CancelledError
from dataclasses import replace, FrozenInstanceError
from fractions import Fraction
import copy
import math
import os
from pathlib import Path
import pickle
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock
import numpy as np
from numpy.testing import assert_allclose, assert_array_equal
from atlas_tectonics import (RegionalGrid1D,TransportBoundary,advect_regional,
    transport_timestep_limit,PeriodicGrid1D,advect_thickness,TectonicsError)
from atlas_tectonics.regional import pack_regional_result,unpack_regional_result
from atlas_tectonics.resources import WorkBudget,MemoryLimitError
from atlas_tectonics.execution import KernelExecutor,ExecutionPolicy
from atlas_tectonics.storage import ArrayStore,StoreLimits,StoreError
from atlas_tectonics.reuse import (cached_regional_transport,CachePolicy,ExecutionContext,
                                  PreparedInput)
OPEN=TransportBoundary('open')
CLOSED=TransportBoundary('closed')


def assert_result(test,a,b):
    test.assertEqual(pack_regional_result(a).tobytes(),pack_regional_result(b).tobytes())


def cell_average_bump(n,shift=0.):
    """Exact translated averages of a compact sin^4 profile plus background."""
    faces=np.linspace(0.,1.,n+1)-shift
    z=np.clip((faces-.2)/.4,0,1)*math.pi
    primitive=.4/math.pi*(3*z/8-np.sin(2*z)/4+np.sin(4*z)/32)
    return .2+np.diff(primitive)*n


class RegionalDefinitionTests(unittest.TestCase):
    def test_grid_and_boundary_are_immutable(self):
        g=RegionalGrid1D(1,2,-3);self.assertEqual(g.spacing_m,2)
        with self.assertRaises(FrozenInstanceError):g.length_m=3
        with self.assertRaises(FrozenInstanceError):OPEN.mode='closed'

    def test_invalid_grid_definitions(self):
        for args in ((True,1),(0,1),(-1,1),(3.,1),(1,0),(1,np.inf),(2,float(np.nextafter(0,1)))):
            with self.subTest(args=args),self.assertRaises((TectonicsError,ValueError)):RegionalGrid1D(*args)

    def test_invalid_boundary_definitions(self):
        for args in [('periodic',),('closed',0),('closed',None,'source'),('open',-1),('open',np.nan),('open',True),('open',None,'')]:
            with self.subTest(args=args),self.assertRaises(TectonicsError):TransportBoundary(*args)

    def test_shape_and_budget_checked_before_conversion(self):
        g=RegionalGrid1D(8,8)
        with mock.patch('atlas_tectonics.regional.read_array',side_effect=AssertionError('copied')):
            with self.assertRaises(TectonicsError):advect_regional(np.ones(8),np.ones(8),g,.1,left=OPEN,right=OPEN)
            with self.assertRaises(MemoryLimitError):advect_regional(np.ones(8),np.ones(9),g,.1,left=OPEN,right=OPEN,budget=WorkBudget(1))

    def test_masks_invalid_values_and_backends(self):
        g=RegionalGrid1D(8,8)
        for h in (np.ma.array(np.ones(8)),np.full(8,np.nan),np.full(8,-1),np.ones(8,dtype=bool)):
            with self.assertRaises(TectonicsError):advect_regional(h,np.zeros(9),g,1,left=CLOSED,right=CLOSED)
        for kw in ({'scheme':'unknown'},{'backend':'gpu'}):
            with self.assertRaises(TectonicsError):advect_regional(np.ones(8),np.zeros(9),g,1,left=CLOSED,right=CLOSED,**kw)

    def test_inflow_missing_and_outflow_without_external_data(self):
        g=RegionalGrid1D(8,8)
        for speed in (1.,-1.):
            with self.assertRaisesRegex(TectonicsError,'incoming'):advect_regional(np.ones(8),np.full(9,speed),g,.1,left=OPEN,right=OPEN)
        r=advect_regional(np.ones(8),np.linspace(-1,1,9),g,.1,left=OPEN,right=OPEN)
        self.assertEqual(r.inflow_m2,0);self.assertGreater(r.outflow_m2,0)

    def test_reversing_flow_demands_new_boundary_data(self):
        g=RegionalGrid1D(4,4);h=np.ones(4);b=TransportBoundary('open',2)
        advect_regional(h,np.ones(5),g,.1,left=b,right=OPEN)
        with self.assertRaises(TectonicsError):advect_regional(h,-np.ones(5),g,.1,left=b,right=OPEN)

    def test_closed_boundary_rejects_nonzero_velocity(self):
        for side in (0,-1):
            u=np.zeros(5);u[side]=1
            with self.assertRaisesRegex(TectonicsError,'closed'):advect_regional(np.ones(4),u,RegionalGrid1D(4,4),.1,left=CLOSED,right=CLOSED)

    def test_default_is_native_higher_order(self):
        r=advect_regional(np.ones(4),np.zeros(5),RegionalGrid1D(4,4),1,left=CLOSED,right=CLOSED)
        self.assertEqual((r.scheme,r.backend),('muscl','numba'))

    def test_explicit_reference_does_not_import_numba(self):
        import builtins
        imp=builtins.__import__
        def block(name,*a,**k):
            if name=='_regional_native' or name.startswith('numba'):raise AssertionError('native import')
            return imp(name,*a,**k)
        with mock.patch('builtins.__import__',side_effect=block):advect_regional(np.ones(4),np.zeros(5),RegionalGrid1D(4,4),1,left=CLOSED,right=CLOSED,backend='reference')


class RegionalMathematicsTests(unittest.TestCase):
    def test_one_cell_both_sides(self):
        g=RegionalGrid1D(1,2);b=TransportBoundary('open',5)
        for backend in ('reference','numba'):
            r=advect_regional([3.],[1,-1],g,.5,left=b,right=b,scheme='upwind',backend=backend)
            self.assertEqual(r.thickness_m[0],5.5);self.assertEqual(r.inflow_m2,5)
            self.assertEqual(r.outflow_m2,0);self.assertEqual(r.balance_residual_m2,0)

    def test_unit_courant_shifts_both_directions(self):
        g=RegionalGrid1D(8,8);h=np.arange(8.)
        for s in (1.,-1.):
            a=advect_regional(h,np.full(9,s),g,1,left=TransportBoundary('open',10),right=TransportBoundary('open',20),scheme='upwind')
            assert_array_equal(a.thickness_m,np.r_[10,h[:-1]] if s>0 else np.r_[h[1:],20]);self.assertEqual(a.balance_residual_m2,0)

    def test_fraction_oracle_shared_flux_and_external_account(self):
        h=np.array([1.,3.,2.,7.]);u=np.array([.5,-.25,.75,.5,-.5]);g=RegionalGrid1D(4,8)
        dt=Fraction(1,4);dx=Fraction(2);l=Fraction(5);r=Fraction(6)
        hf=list(map(Fraction,h));uf=list(map(Fraction,u))
        f=[uf[j]*((l if j==0 else hf[j-1]) if uf[j]>=0 else (r if j==4 else hf[j])) for j in range(5)]
        expected=[hf[i]-dt/dx*(f[i+1]-f[i]) for i in range(4)]
        a=advect_regional(h,u,g,float(dt),left=TransportBoundary('open',5),right=TransportBoundary('open',6),scheme='upwind')
        assert_array_equal(a.thickness_m,list(map(float,expected)));assert_array_equal(a.face_flux_m2_s,list(map(float,f)))
        self.assertEqual(a.left_exchange_m2,float(dt*f[0]));self.assertEqual(a.right_exchange_m2,float(-dt*f[-1]))

    def test_native_reference_identical_varied_cases(self):
        rng=np.random.default_rng(20260917)
        for scheme in ('upwind','muscl'):
            for n in (1,2,3,17,128):
                for k in range(8):
                    h=rng.uniform(.01,10,n);u=rng.uniform(-1,1,n+1)
                    b=TransportBoundary('open',.7);g=RegionalGrid1D(n,float(n));args=(h,u,g,.2)
                    a=advect_regional(*args,left=b,right=b,scheme=scheme)
                    c=advect_regional(*args,left=b,right=b,scheme=scheme,backend='reference');assert_result(self,a,c)

    def test_zero_movement_and_zero_time_preserve_tiny_values(self):
        h=np.array([np.nextafter(0,1),0.,1e-200,1.])
        for backend in ('reference','numba'):
            for scheme in ('upwind','muscl'):
                for dt,u,b in ((1,np.zeros(5),CLOSED),(0,np.ones(5),TransportBoundary('open',1))):
                    r=advect_regional(h,u,RegionalGrid1D(4,4),dt,left=b,right=b,scheme=scheme,backend=backend)
                    assert_array_equal(r.thickness_m,h);self.assertEqual(r.balance_residual_m2,0)

    def test_two_outgoing_faces_not_just_max_speed(self):
        u=np.zeros(5);u[1]=-1;u[2]=1
        for scheme,dt in (('upwind',.6),('muscl',.3)):
            with self.assertRaisesRegex(TectonicsError,'Courant'):advect_regional(np.ones(4),u,RegionalGrid1D(4,4),dt,left=CLOSED,right=CLOSED,scheme=scheme)

    def test_admission_before_candidate_allocation(self):
        from atlas_tectonics._regional_native import admission
        with self.assertRaises(ValueError):admission(np.array([-1.,1.]),1.,.5)

    def test_timestep_advice_matches_and_is_safe(self):
        rng=np.random.default_rng(781)
        for scheme in ('upwind','muscl'):
            for _ in range(12):
                u=rng.uniform(-2,2,40);g=RegionalGrid1D(39,27);b=TransportBoundary('open',1)
                a=transport_timestep_limit(u,g,left=b,right=b,scheme=scheme)
                c=transport_timestep_limit(u,g,left=b,right=b,scheme=scheme,backend='reference');self.assertEqual(a,c)
                advect_regional(np.ones(39),u,g,a.maximum_duration_s,left=b,right=b,scheme=scheme)

    def test_timestep_stationary_and_extreme(self):
        a=transport_timestep_limit(np.zeros(3),RegionalGrid1D(2,2),left=CLOSED,right=CLOSED);self.assertIsNone(a.maximum_duration_s)
        for backend in ('reference','numba'):
            a=transport_timestep_limit(np.array([-1.,1.]),RegionalGrid1D(1,1.7e308),left=OPEN,right=OPEN,backend=backend,scheme='upwind')
            self.assertTrue(math.isfinite(a.maximum_duration_s));self.assertAlmostEqual(a.maximum_duration_s/8.5e307,1)

    def test_closed_nonuniform_multiple_steps(self):
        n=32;g=RegionalGrid1D(n,n);h=np.linspace(.2,2,n);u=np.sin(np.linspace(0,2*np.pi,n+1));u[[0,-1]]=0;start=math.fsum(h)
        for _ in range(20):
            r=advect_regional(h,u,g,.1,left=CLOSED,right=CLOSED);h=r.thickness_m;self.assertEqual(r.inflow_m2+r.outflow_m2,0)
        self.assertAlmostEqual(math.fsum(h),start,places=11);self.assertTrue(np.all(h>=0))

    def test_rk_boundary_account_uses_interval_mean_flux(self):
        r=advect_regional([1.],[0,1],RegionalGrid1D(1,1),.5,left=CLOSED,right=OPEN)
        self.assertEqual(r.thickness_m[0],.625);self.assertEqual(r.face_flux_m2_s[-1],.75)
        self.assertEqual(r.outflow_m2,.375);self.assertEqual(r.balance_residual_m2,0)

    def test_variable_velocity_uniform_extensional_thinning(self):
        n=16;g=RegionalGrid1D(n,1,-.5);u=.2*np.linspace(-.5,.5,n+1);errors=[]
        for steps in (4,8,16):
            h=np.ones(n)
            for _ in range(steps):h=advect_regional(h,u,g,1/steps,left=OPEN,right=OPEN).thickness_m
            errors.append(float(np.max(abs(h-math.exp(-.2)))))
        self.assertGreater(errors[0]/errors[1],3.8);self.assertGreater(errors[1]/errors[2],3.8)

    def test_converging_velocity_thickens(self):
        n=16;g=RegionalGrid1D(n,1,-.5);u=-.2*np.linspace(-.5,.5,n+1);b=TransportBoundary('open',1)
        r=advect_regional(np.ones(n),u,g,.1,left=b,right=b)
        self.assertTrue(np.all(r.thickness_m>1));self.assertGreater(r.inflow_m2,0);self.assertEqual(r.outflow_m2,0)

    def test_smooth_advection_refinement_and_error_order(self):
        errors={}
        for scheme in ('upwind','muscl'):
            errs=[]
            for n in (32,64,128):
                g=RegionalGrid1D(n,1);h=cell_average_bump(n);u=np.ones(n+1);b=TransportBoundary('open',.2)
                steps=math.ceil(.1*n/.4);dt=.1/steps
                for _ in range(steps):h=advect_regional(h,u,g,dt,left=b,right=b,scheme=scheme).thickness_m
                errs.append(float(np.mean(abs(h-cell_average_bump(n,.1)))))
            errors[scheme]=errs
        self.assertGreater(errors['upwind'][1]/errors['upwind'][2],1.65)
        self.assertGreater(errors['muscl'][1]/errors['muscl'][2],3.)
        self.assertLess(errors['muscl'][-1],errors['upwind'][-1]/4)

    def test_discontinuous_positive_front_no_overshoot(self):
        n=64;h=np.zeros(n);h[15:25]=1;g=RegionalGrid1D(n,n);b=TransportBoundary('open',0)
        for _ in range(40):h=advect_regional(h,np.ones(n+1),g,.4,left=b,right=b).thickness_m
        self.assertGreaterEqual(h.min(),0);self.assertLessEqual(h.max(),1+1e-14)

    def test_periodic_compatibility_remains_separate(self):
        h=np.arange(8.);u=np.linspace(-.7,.6,8);g=RegionalGrid1D(8,8);faces=np.r_[u[-1],u]
        r=advect_regional(h,faces,g,.2,left=TransportBoundary('open',h[-1]),right=TransportBoundary('open',h[0]),scheme='upwind')
        p=advect_thickness(h,u,PeriodicGrid1D(8,8),.2)
        assert_array_equal(r.thickness_m,p.thickness_m);assert_array_equal(r.face_flux_m2_s[1:],p.face_flux_m2_s)
        self.assertEqual(r.left_exchange_m2+r.right_exchange_m2,0)

    def test_scale_extreme_flux_refusal_and_budget_release(self):
        b=WorkBudget(1<<20)
        with self.assertRaises(TectonicsError):advect_regional([1e308],[1e308,1e308],RegionalGrid1D(1,1),0,left=TransportBoundary('open',1e308),right=OPEN,budget=b)
        self.assertEqual(b.reserved_bytes,0)


class RegionalIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.g=RegionalGrid1D(16,16);self.h=np.linspace(1,2,16);self.u=np.full(17,.2)
        self.left=TransportBoundary('open',2,'synthetic-source');self.right=OPEN
    def call(self,**kw):
        return advect_regional(self.h,self.u,self.g,.5,left=self.left,right=self.right,**kw)

    def test_input_aliases_and_pickle_restore(self):
        a=self.call();original=a.thickness_m.copy();self.h[:]=90;assert_array_equal(a.thickness_m,original)
        for b in (a,copy.deepcopy(a),pickle.loads(pickle.dumps(a))):
            for v in (b.thickness_m,b.face_flux_m2_s):
                with self.assertRaises(ValueError):v.setflags(write=True)
            assert_result(self,a,b)

    def test_packed_result_validation(self):
        a=self.call();p=pack_regional_result(a)
        with self.assertRaises(TectonicsError):unpack_regional_result(p[:-1],16,'muscl','numba')
        q=p.copy();q[0]=-1
        with self.assertRaises(TectonicsError):unpack_regional_result(q,16,'muscl','numba')

    def test_cancel_before_and_during_native_call(self):
        e=threading.Event();e.set()
        with self.assertRaises(CancelledError):self.call(cancel=e)
        e.clear()
        from atlas_tectonics import _regional_native as rn
        original=rn.advance_regional
        def finish(*a):
            value=original(*a);e.set();return value
        budget=WorkBudget(1<<20)
        with mock.patch.object(rn,'advance_regional',side_effect=finish):
            with self.assertRaises(CancelledError):self.call(cancel=e,budget=budget)
        self.assertEqual(budget.reserved_bytes,0)

    def test_executors_serial_threads_spawn(self):
        expected=self.call()
        for mode in ('serial','threads','processes'):
            with KernelExecutor(ExecutionPolicy(mode=mode,max_workers=2,max_inflight=2),budget=WorkBudget(512<<20)) as ex:
                for result in ex.regional_transports([(self.h,self.u)]*3,self.g,.5,left=self.left,right=self.right):assert_result(self,expected,result)
            self.assertEqual(ex.statistics()['reserved_bytes'],0)

    def test_executor_is_lazy_and_closes(self):
        def cases():
            yield self.h,self.u
            raise AssertionError('prefetched')
        with KernelExecutor(ExecutionPolicy(mode='serial')) as ex:
            stream=ex.regional_transports(cases(),self.g,.5,left=self.left,right=self.right)
            next(stream);stream.close();self.assertEqual(ex.statistics()['reserved_bytes'],0)

    def test_executor_memory_refusal_and_bad_shape(self):
        with KernelExecutor(ExecutionPolicy(mode='serial',max_work_bytes=100)) as ex:
            with self.assertRaises(MemoryLimitError):next(ex.regional_transports([(self.h,self.u)],self.g,.5,left=self.left,right=self.right))
        with KernelExecutor(ExecutionPolicy(mode='serial')) as ex:
            with self.assertRaises(TectonicsError):next(ex.regional_transports([(self.h,self.u[:-1])],self.g,.5,left=self.left,right=self.right))

    def test_cache_changes_every_required_boundary_identity(self):
        with tempfile.TemporaryDirectory() as tmp,ArrayStore(Path(tmp)/'x.db',StoreLimits(1024,1<<20,8<<20)) as store:
            base=dict(store=store,cache_policy=CachePolicy(mode='always'))
            first=cached_regional_transport(self.h,self.u,self.g,.5,left=self.left,right=self.right,**base)
            repeated=cached_regional_transport(self.h,self.u,self.g,.5,left=self.left,right=self.right,**base);assert_result(self,first,repeated)
            for left,dt,g,scheme,backend in ((replace(self.left,exterior_thickness_m=3),.5,self.g,'muscl','numba'),
                    (replace(self.left,material_id='other'),.5,self.g,'muscl','numba'),(self.left,.25,self.g,'muscl','numba'),
                    (self.left,.5,replace(self.g,origin_m=1),'muscl','numba'),(self.left,.5,self.g,'upwind','numba'),(self.left,.5,self.g,'muscl','reference')):
                cached_regional_transport(self.h,self.u,g,dt,left=left,right=OPEN,scheme=scheme,backend=backend,**base)
            self.assertEqual(store.statistics()['snapshots'],7)

    def test_prepared_cache_inputs_and_cheap_auto_bypass(self):
        h,u=PreparedInput(self.h),PreparedInput(self.u)
        with tempfile.TemporaryDirectory() as tmp,ArrayStore(Path(tmp)/'x.db',StoreLimits(1024,1<<20,8<<20)) as store:
            a=cached_regional_transport(h,u,self.g,.5,left=self.left,right=OPEN,store=store)
            assert_result(self,a,self.call());self.assertEqual(store.statistics()['snapshots'],0)
            cached_regional_transport(h,u,self.g,.5,left=self.left,right=OPEN,store=store,cache_policy=CachePolicy(mode='always'))
            self.assertEqual(store.statistics()['snapshots'],1)

    def test_cache_uses_same_shared_budget_and_refuses_masks(self):
        budget=WorkBudget(32<<20)
        with tempfile.TemporaryDirectory() as tmp,ArrayStore(Path(tmp)/'x.db',StoreLimits(1024,1<<20,8<<20),budget=budget) as store:
            cached_regional_transport(self.h,self.u,self.g,.5,left=self.left,right=OPEN,store=store)
            with self.assertRaises(TectonicsError):cached_regional_transport(np.ma.array(self.h),self.u,self.g,.5,left=self.left,right=OPEN,store=store)
        self.assertEqual(budget.reserved_bytes,0)

    def test_native_code_mutation_invalidates_context(self):
        from atlas_tectonics import _regional_native as rn
        ctx=ExecutionContext('numba')
        with mock.patch.object(rn,'advance_regional',lambda *a:None):
            with self.assertRaises(TectonicsError):ctx.verify()
        ctx.verify()

    def test_unchanged_compilation_does_not_invalidate_context(self):
        ctx=ExecutionContext('numba');a=self.call();ctx.verify();assert_result(self,a,self.call(backend='reference'))

    def test_cache_fresh_process_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'x.db'
            with ArrayStore(path,StoreLimits(1024,1<<20,8<<20)) as store:
                cached_regional_transport(self.h,self.u,self.g,.5,left=self.left,right=OPEN,store=store,cache_policy=CachePolicy(mode='always'))
            script='''import sys,numpy as np
from atlas_tectonics import *
from atlas_tectonics.storage import *
from atlas_tectonics.reuse import *
with ArrayStore(sys.argv[1],StoreLimits(1024,1<<20,8<<20)) as s:
 r=cached_regional_transport(np.linspace(1,2,16),np.full(17,.2),RegionalGrid1D(16,16),.5,left=TransportBoundary('open',2,'synthetic-source'),right=TransportBoundary('open'),store=s,cache_policy=CachePolicy(mode='always'))
 print(s.statistics()['snapshots'])
'''
            env=dict(os.environ,PYTHONPATH=str(Path(__file__).resolve().parents[1]/'src'),PYTHONDONTWRITEBYTECODE='1')
            p=subprocess.run([sys.executable,'-B','-c',script,str(path)],env=env,capture_output=True,text=True,timeout=30)
            self.assertEqual(p.returncode,0,p.stderr);self.assertEqual(p.stdout.strip(),'1')

    def test_cached_corruption_is_error_not_miss(self):
        with tempfile.TemporaryDirectory() as tmp,ArrayStore(Path(tmp)/'x.db',StoreLimits(1024,1<<20,8<<20)) as store:
            args=dict(left=self.left,right=OPEN,store=store,cache_policy=CachePolicy(mode='always'))
            cached_regional_transport(self.h,self.u,self.g,.5,**args)
            c=sqlite3.connect(store.path);c.execute('UPDATE chunks SET payload=?',(b'bad',));c.commit();c.close()
            with self.assertRaises(StoreError):cached_regional_transport(self.h,self.u,self.g,.5,**args)

    def test_missing_native_dependency_never_falls_back(self):
        import builtins
        original=builtins.__import__
        def guarded(name,*a,**k):
            if name=='_regional_native':raise ImportError('deliberate')
            return original(name,*a,**k)
        with mock.patch('builtins.__import__',side_effect=guarded):
            with self.assertRaisesRegex(TectonicsError,'unavailable'):self.call()


class RegionalBoundaryAccuracyTests(unittest.TestCase):
    def test_linear_outflow_face_is_reconstructed_not_cell_centre(self):
        from atlas_tectonics._regional_native import fluxes
        h=np.array([1.,2.,3.,4.]);u=np.ones(5);f=np.empty(5)
        fluxes(h,u,.5,0.,True,f)
        assert_array_equal(f,[.5,1.5,2.5,3.5,4.5])
        fluxes(h,-u,0.,4.5,True,f)
        assert_array_equal(f,-np.array([.5,1.5,2.5,3.5,4.5]))

    def test_boundary_reconstruction_does_not_create_negative_face_state(self):
        from atlas_tectonics._regional_native import fluxes
        for h in (np.array([0.,1.,10.]),np.array([10.,1.,0.]),np.array([0.,100.])):
            n=len(h);u=np.ones(n+1);f=np.empty(n+1)
            for sign in (-1,1):
                fluxes(h,sign*u,0.,0.,True,f)
                self.assertTrue(np.all(sign*f>=0))

    def test_positive_sparse_random_states_both_schemes(self):
        rng=np.random.default_rng(612)
        g=RegionalGrid1D(32,32);b=TransportBoundary('open',0)
        for scheme in ('upwind','muscl'):
            for _ in range(30):
                h=rng.uniform(0,1,32);h[rng.random(32)<.4]=0
                u=rng.uniform(-1,1,33)
                r=advect_regional(h,u,g,.2,left=b,right=b,scheme=scheme)
                self.assertTrue(np.all(r.thickness_m>=0))

    def test_scheme_switch_is_an_explicit_numerical_identity(self):
        g=RegionalGrid1D(4,4);b=TransportBoundary('open',0)
        a=advect_regional([0,1,2,0],np.ones(5),g,.2,left=b,right=b)
        c=advect_regional([0,1,2,0],np.ones(5),g,.2,left=b,right=b,scheme='upwind')
        self.assertNotEqual(a.numerical_method,c.numerical_method)
        self.assertNotEqual(a.thickness_m.tobytes(),c.thickness_m.tobytes())


class RegionalAdditionalIntegrationTests(unittest.TestCase):
    def test_reflection_swaps_boundaries_and_flux_sign(self):
        h=np.array([1.,2.,4.,3.,.1]);u=np.array([.3,-.2,.5,.1,-.3,.1]);g=RegionalGrid1D(5,5)
        left,right=TransportBoundary('open',2),TransportBoundary('open',3)
        for scheme in ('upwind','muscl'):
            a=advect_regional(h,u,g,.2,left=left,right=right,scheme=scheme)
            b=advect_regional(h[::-1],-u[::-1],g,.2,left=right,right=left,scheme=scheme)
            assert_allclose(a.thickness_m,b.thickness_m[::-1],rtol=1e-12,atol=1e-12)
            assert_allclose(a.face_flux_m2_s,-b.face_flux_m2_s[::-1],rtol=1e-12,atol=1e-12)

    def test_negative_duration_refused_without_output(self):
        with self.assertRaises(TectonicsError):advect_regional([1.],[0.,0.],RegionalGrid1D(1,1),-1,left=CLOSED,right=CLOSED)

    def test_accounting_payload_cannot_contradict_itself(self):
        r=advect_regional([1.],[0.,0.],RegionalGrid1D(1,1),1,left=CLOSED,right=CLOSED)
        data=pack_regional_result(r).copy();data[-8]=2.
        with self.assertRaises(TectonicsError):unpack_regional_result(data,1,'muscl','numba')

    def test_cancel_during_encoding_rolls_back(self):
        with tempfile.TemporaryDirectory() as tmp,ArrayStore(Path(tmp)/'x.db',StoreLimits(1024,1<<20,8<<20)) as store:
            stop=threading.Event();encode=store._encode
            def signal(*a):
                result=encode(*a);stop.set();return result
            with mock.patch.object(store,'_encode',side_effect=signal):
                with self.assertRaises(CancelledError):
                    cached_regional_transport(np.arange(8.),np.ones(9),RegionalGrid1D(8,8),.2,
                        left=TransportBoundary('open',1),right=OPEN,store=store,
                        cache_policy=CachePolicy(mode='always'),cancel=stop)
            self.assertEqual(store.statistics()['snapshots'],0)

    def test_shared_unchanged_snapshot_deduplicates_regional_payload(self):
        with tempfile.TemporaryDirectory() as tmp,ArrayStore(Path(tmp)/'x.db',StoreLimits(1024,1<<20,8<<20)) as store:
            g=RegionalGrid1D(8,8);kw=dict(right=OPEN,store=store,cache_policy=CachePolicy(mode='always'))
            cached_regional_transport(np.arange(8.),np.ones(9),g,.2,left=TransportBoundary('open',1,'a'),**kw)
            count=store.statistics()['unique_chunks']
            cached_regional_transport(np.arange(8.),np.ones(9),g,.2,left=TransportBoundary('open',1,'b'),**kw)
            self.assertEqual(store.statistics()['unique_chunks'],count)
            self.assertEqual(store.statistics()['snapshots'],2)

    def test_auto_parallel_disposition_is_explicit(self):
        with KernelExecutor(ExecutionPolicy(mode='auto',min_parallel_elements=1)) as ex:
            results=list(ex.regional_transports([([1.],[0.,0.])]*2,RegionalGrid1D(1,1),1,left=CLOSED,right=CLOSED))
            self.assertEqual(ex.statistics()['parallel_jobs'],0)
            self.assertEqual(len(results),2)


if __name__=='__main__':unittest.main()
