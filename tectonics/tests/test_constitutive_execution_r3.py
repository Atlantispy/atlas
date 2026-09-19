"""R3 source integrity, actual threading, bounded memory and existing storage.
SPDX-License-Identifier: AGPL-3.0-only
"""
from concurrent.futures import CancelledError, ThreadPoolExecutor
from dataclasses import replace
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import subprocess
import sys
import os
import threading
import unittest
from unittest import mock

import numpy as np
from numpy.testing import assert_allclose, assert_array_equal
from atlas_tectonics import (PreparedRheology, RheologyProfile, reference_rheology,
    ConstitutiveLimits, DiffusiveScales, LawResult, save_law_result, load_law_result,
    DamageLengthScale, PreparedDamageRegularisation, TectonicsError)
from atlas_tectonics.execution import ExecutionPolicy
from atlas_tectonics.resources import WorkBudget, MemoryLimitError
from atlas_tectonics.storage import ArrayStore, StoreLimits


class PreparedTests(unittest.TestCase):
    def setUp(self):self.profile=reference_rheology('bf23-memory')
    def test_serial_threads_same_scientific_identity(self):
        T=np.linspace(0,1,1024);e=np.logspace(-4,8,1024);d=np.linspace(0,20,1024)
        values=[]
        for mode in ('serial','threads'):
            with PreparedRheology(self.profile,execution=ExecutionPolicy(mode=mode),limits=ConstitutiveLimits(batch_points=127)) as p:
                values.append(p.evaluate(T,.5,e,d))
                if mode=='threads':self.assertGreater(p.execution_statistics['parallel_jobs'],0)
        self.assertEqual(values[0].result_id,values[1].result_id)
        for k in values[0].array_names:assert_array_equal(values[0].array(k),values[1].array(k))
    def test_auto_threshold_and_small_serial(self):
        with PreparedRheology(self.profile,execution=ExecutionPolicy(min_parallel_elements=20),limits=ConstitutiveLimits(batch_points=10)) as p:
            p.evaluate([0,1],0,1,0);self.assertIsNone(p.execution_statistics)
            p.evaluate(np.linspace(0,1,30),0,1,0)
            self.assertGreater(p.execution_statistics['parallel_jobs'],0)
    def test_one_worker_stays_serial(self):
        with PreparedRheology(self.profile,execution=ExecutionPolicy(mode='threads',max_workers=1)) as p:
            p.evaluate([0,1],0,1,0);self.assertIsNone(p.execution_statistics)
    def test_missing_scipy_preserves_raw_laws_and_refuses_length_solver(self):
        code = """
import builtins
real=builtins.__import__
def blocked(name,*args,**kw):
    if name=='scipy' or name.startswith('scipy.'):raise ImportError('test SciPy unavailable')
    return real(name,*args,**kw)
builtins.__import__=blocked
from atlas_tectonics import (evaluate_rheology,reference_rheology,DamageLengthScale,
    PreparedDamageRegularisation,TectonicsError)
assert float(evaluate_rheology(reference_rheology('constant'),0,0,1)['viscosity'])==1
try:PreparedDamageRegularisation(DamageLengthScale('test',1,.1,8,'analytical'))
except TectonicsError as exc:assert 'unavailable' in str(exc)
else:raise AssertionError('missing solver silently replaced')
"""
        env=dict(os.environ,PYTHONPATH=str(Path(__file__).resolve().parents[1]/'src'),PYTHONDONTWRITEBYTECODE='1')
        p=subprocess.run([sys.executable,'-B','-c',code],capture_output=True,text=True,env=env,timeout=15)
        self.assertEqual(p.returncode,0,p.stderr)
    def test_process_mode_refused(self):
        with self.assertRaises(TectonicsError):PreparedRheology(self.profile,execution=ExecutionPolicy(mode='processes'))
    def test_reuse_executor_after_worker_failure(self):
        with PreparedRheology(self.profile,execution=ExecutionPolicy(mode='threads'),limits=ConstitutiveLimits(batch_points=2)) as p:
            with self.assertRaises(TectonicsError):p.evaluate([0,.5,2,1],0,1,0)
            r=p.evaluate([0,.5,1,1],0,1,0)
            self.assertTrue(np.isfinite(r.array('viscosity')).all())
    def test_broadcast_shape_reassembled(self):
        with PreparedRheology(self.profile,execution=ExecutionPolicy(mode='threads'),limits=ConstitutiveLimits(batch_points=2)) as p:
            r=p.evaluate(np.array([0,.5,1])[:,None],np.array([0,1])[None,:],1,0)
        self.assertEqual(r.array('viscosity').shape,(3,2))
    def test_prepared_result_survives_input_mutation(self):
        T=np.array([0.,.5]);d=np.array([2.,3.])
        with PreparedRheology(self.profile) as p:r=p.evaluate(T,0,1,d)
        T[:]=1;d[:]=0
        assert_array_equal(r.array('temperature'),[0,.5]);assert_array_equal(r.array('damage'),[2,3])
    def test_result_descriptor_and_shape_private(self):
        with PreparedRheology(self.profile) as p:r=p.evaluate([0,.5],0,1,0)
        view=r.array('viscosity');view.shape=(1,2)
        self.assertEqual(r.array('viscosity').shape,(2,))
        with self.assertRaises(ValueError):view.setflags(write=True)
        md=r.descriptor();md['profile']['name']='broken'
        self.assertNotEqual(r.descriptor()['profile']['name'],'broken')
    def test_result_immutable_attribute(self):
        with PreparedRheology(self.profile) as p:r=p.evaluate(0,0,1,0)
        with self.assertRaises(TectonicsError):r.result_id='x'
    def test_plan_rebinding_refused(self):
        with PreparedRheology(self.profile) as p:
            with self.assertRaises(TectonicsError):p.profile=reference_rheology('constant')
    def test_closed_plan(self):
        p=PreparedRheology(self.profile);p.close();p.close()
        with self.assertRaises(TectonicsError):p.evaluate(0,0,1,0)
    def test_active_close_refused(self):
        with PreparedRheology(self.profile) as p:
            with p._operation(None):
                with self.assertRaises(TectonicsError):p.close()
    def test_nested_drive_refused(self):
        with PreparedRheology(self.profile) as p:
            with p._operation(None):
                with self.assertRaises(TectonicsError):p.evaluate(0,0,1,0)
    def test_wrong_thread_close_preserves_live_plan_and_admission(self):
        b=WorkBudget(32<<20)
        p=PreparedRheology(self.profile,budget=b,execution=ExecutionPolicy(mode='threads'))
        try:
            p.evaluate([0.,.5],0,1,0)
            held=b.reserved_bytes
            with ThreadPoolExecutor(max_workers=1) as workers:
                future=workers.submit(p.close)
                with self.assertRaises(TectonicsError):future.result()
            self.assertFalse(p._closed)
            self.assertEqual(b.reserved_bytes,held)
            p.evaluate([0.,.5],0,1,0)
        finally:p.close()
        self.assertEqual(b.reserved_bytes,0)
    def test_initial_damage_required(self):
        with PreparedRheology(self.profile) as p:
            with self.assertRaises(TectonicsError):p.evaluate(0,0,1)
    def test_si_conversion_not_implicit(self):
        scales=DiffusiveScales('conversion-control',2,4,8,300,1000,2)
        with PreparedRheology(self.profile,scales=scales) as p:
            a=p.evaluate([0,.5,1],[0,.5,1],2,0)
            b=p.evaluate([300,800,1300],[0,1,2],2,0,units='SI')
        self.assertEqual(a.result_id,b.result_id)
        self.assertEqual(a.descriptor()['scales']['name'],'conversion-control')
    def test_diffusive_length_and_depth_scale_separate(self):
        scales=DiffusiveScales('separate-radius-layer',10,2,8,300,1000,2)
        with PreparedRheology(self.profile,scales=scales) as p:
            a=p.evaluate(.5,.5,2,0)
            b=p.evaluate(800,1,2/scales.time_s,0,units='SI')
        self.assertEqual(a.result_id,b.result_id)
    def test_prepared_memory_retains_before_after_and_elapsed(self):
        with PreparedRheology(self.profile) as p:r=p.advance([10,20],0,[0,1],1e-9)
        assert_array_equal(r.array('damage_before'),[10,20])
        self.assertEqual(r.descriptor()['elapsed_dimensionless'],1e-9)
        self.assertGreater(r.array('damage_after')[0],9.99)
        self.assertLess(r.array('damage_after')[1],2)
    def test_prepared_memory_si_identity(self):
        scales=DiffusiveScales('scale',10,2,8,300,1000,2)
        with PreparedRheology(self.profile,scales=scales) as p:
            a=p.advance(10,2,.5,1e-8)
            b=p.advance(10,2/scales.time_s,800,1e-8*scales.time_s,units='SI')
        self.assertEqual(a.result_id,b.result_id)
    def test_si_without_scales_refused(self):
        with PreparedRheology(self.profile) as p:
            with self.assertRaises(TectonicsError):p.evaluate(300,0,1,0,units='SI')
    def test_unknown_units_refused(self):
        with PreparedRheology(self.profile) as p:
            with self.assertRaises(TectonicsError):p.evaluate(300,0,1,0,units='kelvin-ish')
    def test_wrong_scale_changes_identity(self):
        s=DiffusiveScales('control',2,4,8,300,1000,2)
        with PreparedRheology(self.profile,scales=s) as a,PreparedRheology(self.profile,scales=replace(s,length_m=3)) as b:
            self.assertNotEqual(a.identity,b.identity)
    def test_source_context_mutated_function_refused(self):
        from atlas_tectonics import constitutive
        p=PreparedRheology(self.profile)
        with mock.patch.object(constitutive,'_native_law',lambda *a:None):
            with self.assertRaises(TectonicsError):p.evaluate(0,0,1,0)
        p.close()
    def test_source_constant_mutation_refused(self):
        from atlas_tectonics import constitutive
        p=PreparedRheology(self.profile)
        with mock.patch.object(constitutive,'_METHOD','changed-without-approval'):
            with self.assertRaises(TectonicsError):p.evaluate(0,0,1,0)
        p.close()
    def test_source_membership_change_refused(self):
        from atlas_tectonics import reuse
        p=PreparedRheology(self.profile)
        old=reuse._source_bytes
        def changed():
            d=old();d['fabricated.py']=b'x';return d
        with mock.patch.object(reuse,'_source_bytes',changed):
            with self.assertRaises(TectonicsError):p.evaluate(0,0,1,0)
        p.close()
    def test_context_released_if_construction_fails(self):
        b=WorkBudget(10<<20)
        with mock.patch('atlas_tectonics.constitutive_execution.ExecutionContext',side_effect=TectonicsError('failed')):
            with self.assertRaises(TectonicsError):PreparedRheology(self.profile,budget=b)
        self.assertEqual(b.reserved_bytes,0)
    def test_budget_before_constructor_allocation(self):
        with self.assertRaises(MemoryLimitError):PreparedRheology(self.profile,budget=WorkBudget(1))
    def test_budget_released_after_request_refusal(self):
        b=WorkBudget(7<<20)
        with PreparedRheology(self.profile,budget=b) as p:
            held=b.reserved_bytes
            with self.assertRaises(MemoryLimitError):p.evaluate(np.zeros(100000),0,1,0)
            self.assertEqual(b.reserved_bytes,held)
        self.assertEqual(b.reserved_bytes,0)
    def test_global_count_not_multiplied_by_batching(self):
        with PreparedRheology(self.profile,limits=ConstitutiveLimits(max_points=20,batch_points=5),execution=ExecutionPolicy(mode='threads')) as p:
            with self.assertRaises(TectonicsError):p.evaluate(np.zeros(21),0,1,0)
    def test_cancelled_before_request(self):
        e=threading.Event();e.set();b=WorkBudget(16<<20)
        with PreparedRheology(self.profile,budget=b) as p:
            held=b.reserved_bytes
            with self.assertRaises(CancelledError):p.evaluate(0,0,1,0,cancel=e)
            self.assertEqual(b.reserved_bytes,held)
        self.assertEqual(b.reserved_bytes,0)
    def test_cancelled_thread_work_drains_and_reuses(self):
        from atlas_tectonics import constitutive_execution as ce
        original=ce.evaluate_rheology;event=threading.Event();count=[0];lock=threading.Lock()
        def wrapped(*a,**kw):
            with lock:
                count[0]+=1
                if count[0]==2:event.set()
            return original(*a,**kw)
        b=WorkBudget(32<<20)
        with mock.patch.object(ce,'evaluate_rheology',wrapped):
            with PreparedRheology(self.profile,budget=b,limits=ConstitutiveLimits(batch_points=5),execution=ExecutionPolicy(mode='threads')) as p:
                with self.assertRaises(CancelledError):p.evaluate(np.zeros(40),0,1,0,cancel=event)
                event.clear();count[0]=100
                p.evaluate(np.zeros(10),0,1,0)
        self.assertEqual(b.reserved_bytes,0)


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.budget=WorkBudget(64<<20)
        self.store=ArrayStore(Path(self.temp.name)/'law.sqlite',StoreLimits(4096,4<<20,16<<20),budget=self.budget)
        self.store.__enter__()
        with PreparedRheology(reference_rheology('bf23-memory'),budget=self.budget) as p:
            self.result=p.evaluate(np.linspace(0,1,20),.5,1,np.linspace(0,20,20))
    def tearDown(self):self.store.close();self.temp.cleanup()
    def test_exact_round_trip_profile_and_inputs(self):
        save_law_result(self.result,self.store)
        r=load_law_result(self.store,self.result.result_id)
        self.assertEqual(r.result_id,self.result.result_id);self.assertEqual(r.descriptor(),self.result.descriptor())
        for k in r.array_names:assert_array_equal(r.array(k),self.result.array(k))
    def test_memory_step_round_trip(self):
        with PreparedRheology(reference_rheology('bf23-memory')) as p:r=p.advance([10,20],1,[0,1],1e-9)
        save_law_result(r,self.store);restored=load_law_result(self.store,r.result_id)
        self.assertEqual(restored.result_id,r.result_id)
        self.assertEqual(restored.descriptor(),r.descriptor())
        assert_array_equal(restored.array('damage_before'),[10,20])
    def test_repeat_deduplicates(self):
        save_law_result(self.result,self.store);before=self.store.statistics()['unique_chunks']
        save_law_result(self.result,self.store)
        self.assertEqual(before,self.store.statistics()['unique_chunks'])
    def test_cancelled_save_no_snapshot(self):
        e=threading.Event();e.set()
        with self.assertRaises(CancelledError):save_law_result(self.result,self.store,cancel=e)
        self.assertEqual(self.store.statistics()['snapshots'],0)
    def test_restore_refusal_retains_snapshot(self):
        save_law_result(self.result,self.store)
        with self.assertRaises(MemoryLimitError):load_law_result(self.store,self.result.result_id,budget=WorkBudget(1))
        self.assertEqual(load_law_result(self.store,self.result.result_id).result_id,self.result.result_id)
    def test_record_without_profile_refused(self):
        md=self.result.descriptor();md.pop('profile')
        with self.assertRaises(TectonicsError):LawResult(md,{k:self.result.array(k) for k in self.result.array_names})
    def test_record_tampered_profile_identifier_refused(self):
        md=self.result.descriptor();md['profile']['parameters'][0][1]+=1
        with self.assertRaises(TectonicsError):LawResult(md,{k:self.result.array(k) for k in self.result.array_names})
    def test_record_wrong_units_refused(self):
        md=self.result.descriptor();md['array_units']='SI'
        with self.assertRaises(TectonicsError):LawResult(md,{k:self.result.array(k) for k in self.result.array_names})
    def test_record_invalid_scale_refused(self):
        md=self.result.descriptor();md['scales']={'length_m':1.}
        with self.assertRaises(TectonicsError):LawResult(md,{k:self.result.array(k) for k in self.result.array_names})
    def test_missing_result(self):
        with self.assertRaises(TectonicsError):load_law_result(self.store,'0'*64)
    def test_tampered_result_arrays_identity_refused(self):
        arrays={k:self.result.array(k) for k in self.result.array_names};arrays['viscosity']=arrays['viscosity']*2
        self.store.put(self.result.result_id,arrays,self.result.descriptor())
        with self.assertRaises(TectonicsError):load_law_result(self.store,self.result.result_id)
    def test_no_rebinding_historical_source(self):
        md=self.result.descriptor();md['context_id']='0'*64
        r=LawResult(md,{k:self.result.array(k) for k in self.result.array_names})
        save_law_result(r,self.store)
        restored=load_law_result(self.store,r.result_id)
        self.assertEqual(restored.descriptor()['context_id'],'0'*64)
    def test_unknown_schema_refused(self):
        with self.assertRaises(TectonicsError):LawResult({'schema':'wrong'}, {})


class RegularisationTests(unittest.TestCase):
    def params(self,n=32,ell=.1):return DamageLengthScale('authored-test-length',1.,ell,n,'analytical test, not calibrated geology')
    def test_constant_and_zero(self):
        with PreparedDamageRegularisation(self.params()) as p:
            assert_allclose(p.apply(np.ones(32)),1,rtol=4e-15)
            assert_array_equal(p.apply(np.zeros(32)),0)
    def test_integral_and_positivity(self):
        raw=np.zeros(64);raw[31:34]=10
        with PreparedDamageRegularisation(self.params(64)) as p:out=p.apply(raw)
        self.assertGreaterEqual(out.min(),0);self.assertAlmostEqual(out.sum(),raw.sum(),11)
    def test_independent_dense_operator(self):
        n=17;s=(.1*n)**2;A=np.eye(n)
        for i in range(n-1):
            A[i,i]+=s;A[i+1,i+1]+=s;A[i,i+1]-=s;A[i+1,i]-=s
        raw=np.random.default_rng(2).uniform(0,3,n)
        expected=np.linalg.solve(A,raw)
        with PreparedDamageRegularisation(self.params(n)) as p:out=p.apply(raw)
        assert_allclose(out,expected,rtol=1e-15)
    def test_exact_discrete_cosine_mode(self):
        n=64;k=3;x=(np.arange(n)+.5)/n;s=(.1*n)**2
        raw=2+np.cos(k*np.pi*x)
        expected=2+np.cos(k*np.pi*x)/(1+4*s*np.sin(k*np.pi/(2*n))**2)
        with PreparedDamageRegularisation(self.params(n)) as p:out=p.apply(raw)
        assert_allclose(out,expected,rtol=1e-14)
    def test_fixed_physical_length_second_order_convergence(self):
        errors=[]
        for n in (24,48,96):
            x=(np.arange(n)+.5)/n;raw=2+np.cos(2*np.pi*x)
            exact=2+np.cos(2*np.pi*x)/(1+(.1*2*np.pi)**2)
            with PreparedDamageRegularisation(self.params(n)) as p:out=p.apply(raw)
            errors.append(float(np.max(abs(out-exact))))
        self.assertTrue(3.8<errors[0]/errors[1]<4.2);self.assertTrue(3.8<errors[1]/errors[2]<4.2)
    def test_symmetric_impulse_not_grid_width(self):
        n=65;raw=np.zeros(n);raw[n//2]=1
        with PreparedDamageRegularisation(self.params(n)) as p:out=p.apply(raw)
        assert_allclose(out,out[::-1],rtol=1e-14)
        self.assertGreater(np.count_nonzero(out>.01),3)
    def test_does_not_mutate_raw_memory(self):
        raw=np.arange(16.);old=raw.copy()
        with PreparedDamageRegularisation(self.params(16)) as p:p.apply(raw)
        assert_array_equal(raw,old)
    def test_length_and_support_identity(self):
        with PreparedDamageRegularisation(self.params()) as a,PreparedDamageRegularisation(self.params(ell=.2)) as b:
            self.assertNotEqual(a.identity,b.identity)
    def test_invalid_length(self):
        for ell in (0,-1,float('inf')):
            with self.subTest(ell=ell),self.assertRaises(TectonicsError):self.params(ell=ell)
    def test_numeric_condition_refused_not_smaller_length(self):
        with self.assertRaises(TectonicsError):self.params(1_000_000,ell=1)
    def test_wrong_shape_negative_missing(self):
        with PreparedDamageRegularisation(self.params()) as p:
            for v in (np.ones(31),np.full(32,-1),np.full(32,np.nan)):
                with self.subTest(shape=v.shape),self.assertRaises(TectonicsError):p.apply(v)
    def test_factor_immutable(self):
        with PreparedDamageRegularisation(self.params()) as p:
            with self.assertRaises(ValueError):p._factor.setflags(write=True)
            with self.assertRaises(TectonicsError):p._s=0
    def test_cancel_and_budget_cleanup(self):
        b=WorkBudget(8<<20);e=threading.Event();e.set()
        with PreparedDamageRegularisation(self.params(),budget=b) as p:
            held=b.reserved_bytes
            with self.assertRaises(CancelledError):p.apply(np.ones(32),cancel=e)
            self.assertEqual(b.reserved_bytes,held)
        self.assertEqual(b.reserved_bytes,0)
    def test_native_factorisation_built_once(self):
        from atlas_tectonics import damage_regularisation as dr
        original=dr.cholesky_banded
        with mock.patch.object(dr,'cholesky_banded',wraps=original) as called:
            with PreparedDamageRegularisation(self.params()) as p:
                p.apply(np.ones(32));p.apply(np.ones(32))
            self.assertEqual(called.call_count,1)
    def test_closed_plan(self):
        p=PreparedDamageRegularisation(self.params());p.close()
        with self.assertRaises(TectonicsError):p.apply(np.ones(32))


if __name__=='__main__':unittest.main()
