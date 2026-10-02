"""R3 source integrity, actual threading, bounded memory and existing storage.
SPDX-License-Identifier: AGPL-3.0-only
"""
from concurrent.futures import CancelledError, ThreadPoolExecutor
from contextlib import contextmanager
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
import atlas_tectonics.execution as execution
from atlas_tectonics.execution import ExecutionPolicy, KernelExecutor
from atlas_tectonics.resources import WorkBudget, MemoryLimitError
from atlas_tectonics.storage import ArrayStore, StoreLimits


@contextmanager
def foreign_lease():
    """Hold the process-wide native-thread lease on a helper thread.

    While it is held, entering a KernelExecutor on any other thread is refused
    with the executor's own TectonicsError.
    """
    held=threading.Event();done=threading.Event();failure=[]
    def hold():
        try:
            with KernelExecutor(ExecutionPolicy(mode='serial')):
                held.set();done.wait()
        except BaseException as exc:failure.append(exc)
        finally:held.set()
    holder=threading.Thread(target=hold);holder.start();held.wait()
    try:
        if failure:raise failure[0]
        yield
    finally:done.set();holder.join()


def leases():
    """Process-wide executor claims: (native-thread lease users, CPU pool slots)."""
    return execution._LIMIT_USERS,execution._POOL_SLOTS


def native_limits():
    from threadpoolctl import threadpool_info
    import scipy.special  # the executor loads it before recording the limits it restores
    return sorted((x['filepath'],x['num_threads']) for x in threadpool_info())


class WorkerGate:
    """A cancel token that tells an evaluation's workers from the thread driving it.

    The driving thread asks first, before any worker exists, and is never held.
    Every other thread that asks is one of that evaluation's workers: it reports
    entry and waits for release. ``cancel=True`` then cancels the evaluation.
    """
    def __init__(self,cancel=False):
        self.cancel=cancel;self.driver=None
        self.entered=threading.Event();self.release=threading.Event()
    def is_set(self):
        me=threading.current_thread()
        if self.driver is None:self.driver=me
        elif me is not self.driver:
            self.entered.set();self.release.wait(30)
        return self.cancel and self.entered.is_set()


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
        # R7 (3f): the name predates the per-evaluation executor. What is reused
        # after a worker failure is the plan; the failed call's executor has gone.
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
        # R7 (3f): an executor lasts one evaluation, so no thread owns the plan. A
        # close from another thread is refused only while an evaluation is active,
        # and leaves the plan and its admission intact; an idle plan closes from
        # any thread.
        b=WorkBudget(32<<20);gate=WorkerGate()
        p=PreparedRheology(self.profile,budget=b,execution=ExecutionPolicy(mode='threads'))
        try:
            p.evaluate([0.,.5],0,1,0)
            held=b.reserved_bytes
            def close_during_evaluation():
                try:
                    self.assertTrue(gate.entered.wait(30));p.close()
                finally:gate.release.set()
            with ThreadPoolExecutor(max_workers=1) as workers:
                future=workers.submit(close_during_evaluation)
                p.evaluate([0.,.5],0,1,0,cancel=gate)
                with self.assertRaises(TectonicsError):future.result()
                self.assertFalse(p._closed)
                self.assertEqual(b.reserved_bytes,held)
                p.evaluate([0.,.5],0,1,0)
                workers.submit(p.close).result()
            self.assertTrue(p._closed)
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


T64=np.linspace(0,1,64);E64=np.logspace(-4,8,64);D64=np.linspace(0,20,64)


def threaded(budget=None,batch=16):
    """A threaded plan whose 64-point request below is four worker jobs."""
    return PreparedRheology(reference_rheology('bf23-memory'),budget=budget,
        execution=ExecutionPolicy(mode='threads',max_inflight=3),limits=ConstitutiveLimits(batch_points=batch))


class DispatchScopedExecutor(unittest.TestCase):
    """R7 (3f): each threaded evaluation owns its executor; the plan owns none.

    Where a helper thread makes a plan's first threaded call, that thread stays
    alive and the plan is closed on it in a ``finally``. Were a plan bound to its
    first caller again, that still releases the process-wide lease, so a failure
    here cannot fail every later test. A first caller that has already exited is
    exercised in a separate interpreter for the same reason.
    """
    def test_idle_plan_holds_no_pool_cpu_slots_or_native_lease(self):
        clean=leases();limits=native_limits();threads=set(threading.enumerate())
        with threaded() as p:
            p.evaluate(T64,.5,E64,D64)
            self.assertEqual(p.execution_statistics['parallel_jobs'],4)
            self.assertEqual(leases(),clean);self.assertEqual(native_limits(),limits)
            self.assertEqual(set(threading.enumerate())-threads,set())
            def unrelated():
                with KernelExecutor(ExecutionPolicy(mode='serial')):return True
            with ThreadPoolExecutor(max_workers=1) as pool:self.assertTrue(pool.submit(unrelated).result(30))

    def test_plan_is_not_bound_to_its_first_threaded_caller(self):
        b=WorkBudget(32<<20);p=threaded(b)
        call=lambda:(p.evaluate(T64,.5,E64,D64).result_id,p.execution_statistics['parallel_jobs'])
        with ThreadPoolExecutor(max_workers=1) as first:
            try:
                with ThreadPoolExecutor(max_workers=1) as second:
                    results=[first.submit(call).result(30),second.submit(call).result(30),call()]
                    self.assertEqual(len(set(results)),1);self.assertEqual(results[0][1],4)
                    second.submit(p.close).result(30)
                self.assertTrue(p._closed);self.assertEqual(b.reserved_bytes,0)
            finally:first.submit(p.close).result(30)

    def test_plan_outlives_the_thread_that_first_used_it(self):
        script='''import json,sys,threading
sys.path.insert(0,sys.argv[1])
import numpy as np
from threadpoolctl import threadpool_info
import scipy.special
import atlas_tectonics.execution as execution
from atlas_tectonics import PreparedRheology,reference_rheology,ConstitutiveLimits
from atlas_tectonics.execution import ExecutionPolicy,KernelExecutor
from atlas_tectonics.resources import WorkBudget
def native():return sorted((x['filepath'],x['num_threads']) for x in threadpool_info())
out={};b=WorkBudget(32<<20)
p=PreparedRheology(reference_rheology('bf23-memory'),budget=b,
    execution=ExecutionPolicy(mode='threads'),limits=ConstitutiveLimits(batch_points=16))
T=np.linspace(0,1,64);E=np.logspace(-4,8,64);D=np.linspace(0,20,64)
def attempt(name,call):
    try:out[name]=call()
    except Exception as exc:out[name]=type(exc).__name__+': '+str(exc)
def evaluate():return p.evaluate(T,.5,E,D).result_id
def unrelated():
    with KernelExecutor(ExecutionPolicy(mode='serial')):return 'ok'
def close():p.close();return 'ok'
before=native()
caller=threading.Thread(target=attempt,args=('first',evaluate));caller.start();caller.join()
out['leases']=[execution._LIMIT_USERS,execution._POOL_SLOTS];out['limits_restored']=native()==before
# Started once the first caller has gone: if its thread identifier is handed straight back, this thread takes it.
keep=threading.Event();spare=threading.Thread(target=keep.wait);spare.start()
caller=threading.Thread(target=attempt,args=('second',evaluate));caller.start();caller.join()
attempt('constructor',evaluate);attempt('unrelated_executor',unrelated);attempt('close',close)
out['closed']=p._closed;out['reserved']=b.reserved_bytes
keep.set();spare.join()
print(json.dumps(out))
'''
        source=Path(__file__).resolve().parents[1]/'src'
        result=subprocess.run([sys.executable,'-I','-B','-c',script,str(source)],
                              capture_output=True,text=True,timeout=120)
        self.assertEqual(result.returncode,0,result.stderr)
        out=json.loads(result.stdout.strip().splitlines()[-1]);self.maxDiff=None
        self.assertEqual(len(out['first']),64,out)
        self.assertEqual(out,{'first':out['first'],'second':out['first'],'constructor':out['first'],
            'leases':[0,0],'limits_restored':True,'unrelated_executor':'ok','close':'ok','closed':True,'reserved':0})

    def test_overlapping_evaluation_is_refused_not_queued_and_the_running_one_completes(self):
        gate=WorkerGate();b=WorkBudget(32<<20)
        with threaded(b) as p,ThreadPoolExecutor(max_workers=1) as pool:
            held=b.reserved_bytes;refusals=[]
            def overlap():
                try:
                    self.assertTrue(gate.entered.wait(30));reserved=b.reserved_bytes
                    try:p.evaluate(T64,.5,E64,D64)
                    except TectonicsError as exc:refusals.append((type(exc),b.reserved_bytes==reserved))
                finally:gate.release.set()
            other=pool.submit(overlap)
            first=p.evaluate(T64,.5,E64,D64,cancel=gate).result_id
            other.result(30)
            # The second call met an active plan: it neither waited for the first nor ran beside it.
            self.assertEqual(refusals,[(TectonicsError,True)])
            self.assertEqual(pool.submit(lambda:p.evaluate(T64,.5,E64,D64).result_id).result(30),first)
            self.assertEqual(b.reserved_bytes,held)

    def test_foreign_lease_refuses_the_call_before_any_job_and_binds_nothing(self):
        b=WorkBudget(32<<20)
        with threaded(b) as p:
            held=b.reserved_bytes;call=lambda:p.evaluate(T64,.5,E64,D64).result_id
            with foreign_lease():
                foreign=leases()
                with self.assertRaises(TectonicsError) as refused:call()
                self.assertIs(type(refused.exception),TectonicsError)
                self.assertEqual((b.reserved_bytes,leases()),(held,foreign))
                self.assertNotIn('executor-inflight',b.statistics()['category_peaks'])
                self.assertIsNone(p.execution_statistics)
            # The refusal neither bound the plan to this thread nor made it unusable.
            with ThreadPoolExecutor(max_workers=1) as other:
                self.assertEqual(call(),other.submit(call).result(30))
            self.assertEqual(b.reserved_bytes,held)
        self.assertEqual(b.reserved_bytes,0)

    def test_request_overlapping_another_plans_dispatch_is_refused_not_queued(self):
        gate=WorkerGate();b=WorkBudget(32<<20);busy=threaded()
        with threaded(b) as other,ThreadPoolExecutor(max_workers=1) as pool:
            held=b.reserved_bytes
            try:
                try:
                    running=pool.submit(lambda:busy.evaluate(T64,.5,E64,D64,cancel=gate).result_id)
                    self.assertTrue(gate.entered.wait(30))
                    with self.assertRaises(TectonicsError) as refused:other.evaluate(T64,.5,E64,D64)
                    self.assertIs(type(refused.exception),TectonicsError);self.assertEqual(b.reserved_bytes,held)
                finally:gate.release.set()
                first=running.result(30)
                # The refusal lasts for the overlap only, not for the other plan's lifetime.
                self.assertEqual(other.evaluate(T64,.5,E64,D64).result_id,first)
            finally:pool.submit(busy.close).result(30)
        self.assertTrue(busy._closed)

    def test_callers_own_executor_conflict_is_refused_and_compatible_lease_is_returned(self):
        b=WorkBudget(32<<20)
        with threaded(b) as p:
            held=b.reserved_bytes
            with KernelExecutor(ExecutionPolicy(mode='serial',max_workers=1,inner_threads=2)):
                with self.assertRaises(TectonicsError) as refused:p.evaluate(T64,.5,E64,D64)
                self.assertIs(type(refused.exception),TectonicsError)
                self.assertEqual(b.reserved_bytes,held)
                self.assertNotIn('executor-inflight',b.statistics()['category_peaks'])
            with KernelExecutor(ExecutionPolicy(mode='serial')):
                outer=leases()
                p.evaluate(T64,.5,E64,D64)
                self.assertEqual(p.execution_statistics['parallel_jobs'],4)
                self.assertEqual(leases(),outer)

    def test_failed_and_cancelled_dispatches_return_pool_and_lease(self):
        b=WorkBudget(32<<20);clean=leases();threads=set(threading.enumerate())
        with threaded(b,batch=2) as p:
            held=b.reserved_bytes
            def returned():return leases(),b.reserved_bytes,set(threading.enumerate())-threads
            with self.assertRaises(TectonicsError):p.evaluate([0,.5,2,1],0,1,0)
            self.assertIn('executor-inflight',b.statistics()['category_peaks'])
            self.assertEqual(returned(),(clean,held,set()))
            gate=WorkerGate(cancel=True);gate.release.set()
            with self.assertRaises(CancelledError):p.evaluate(np.zeros(8),0,1,0,cancel=gate)
            self.assertTrue(gate.entered.is_set());self.assertEqual(returned(),(clean,held,set()))
            p.evaluate(np.zeros(8),0,1,0)
            self.assertEqual(returned(),(clean,held,set()))

    def test_source_invalidation_during_an_evaluation_returns_pool_lease_and_admission(self):
        gate=WorkerGate();b=WorkBudget(32<<20);clean=leases();p=threaded(b)
        def invalidate():
            try:
                self.assertTrue(gate.entered.wait(30))
                p._context._sources=dict(p._context._sources)|{'absent.py':b'changed input'}
            finally:gate.release.set()
        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                changing=pool.submit(invalidate)
                # The workers finish; the check after them refuses the changed source.
                with self.assertRaises(TectonicsError):p.evaluate(T64,.5,E64,D64,cancel=gate)
                changing.result()
            self.assertEqual(p.execution_statistics['completed_jobs'],4)
            self.assertEqual(leases(),clean)
        finally:
            with self.assertRaises(TectonicsError):p.close()
        self.assertEqual(b.reserved_bytes,0)

    def test_statistics_describe_only_the_last_dispatch(self):
        own=lambda record:{k:v for k,v in record.items() if k!='shared_budget'}
        b=WorkBudget(32<<20)
        with PreparedRheology(reference_rheology('bf23-memory'),budget=b,limits=ConstitutiveLimits(batch_points=10),
                              execution=ExecutionPolicy(min_parallel_elements=20,max_inflight=3)) as p:
            self.assertIsNone(p.execution_statistics)
            p.evaluate(np.linspace(0,1,60),0,1,0);large=p.execution_statistics
            p.evaluate(np.linspace(0,1,20),0,1,0);small=p.execution_statistics
            self.assertEqual([(s['parallel_jobs'],s['completed_jobs'],s['peak_inflight'],s['reserved_bytes'])
                              for s in (large,small)],[(6,6,3,0),(2,2,2,0)])
            self.assertLess(small['peak_reserved_bytes'],large['peak_reserved_bytes'])
            # Automatic execution keeps the next request serial: the record still describes the last dispatch.
            p.evaluate([0,1],0,1,0)
            self.assertEqual(own(p.execution_statistics),own(small))
            # Each read is a detached copy, and its budget entry is the budget as it is now.
            small['parallel_jobs']=-1;small['shared_budget']['reserved_bytes']=-1
            self.assertEqual(p.execution_statistics['parallel_jobs'],2)
            self.assertEqual(p.execution_statistics['shared_budget']['reserved_bytes'],b.reserved_bytes)
        # A dispatch that fails after its executor started is described too.
        with threaded(batch=2) as p:
            with self.assertRaises(TectonicsError):p.evaluate([0,.5,2,1],0,1,0)
            failed=p.execution_statistics
            self.assertEqual((failed['parallel_jobs'],failed['completed_jobs'],failed['reserved_bytes']),(2,1,0))


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
