"""Items 6-8: bounded concurrency, byte-verified reuse, and admission contracts.

Synthetic arrays, local temporary stores only. No performance thresholds, changed
physical tolerances, historical rebindings, network calls or installation.
"""
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor, CancelledError, Future
from dataclasses import replace
import errno
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import pickle
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

import numpy as np
from numpy.testing import assert_array_equal, assert_allclose

from atlas_tectonics import Rotation, ThermalParameters, FlexureParameters, PeriodicGrid1D, PeriodicFlexure, half_space_temperature, TectonicsError
from atlas_tectonics._validation import frozen
from atlas_tectonics.resources import MemoryLimitError, WorkBudget
from atlas_tectonics.storage import ArrayStore, StoreLimits, StoreError
from atlas_tectonics.execution import KernelExecutor, ExecutionPolicy, _LIMIT_LOCK
from atlas_tectonics import reuse
from atlas_tectonics.reuse import ExecutionContext, PreparedInput, CachePolicy, ReuseController, cached_temperature, cached_flexure

THERMAL=ThermalParameters('synthetic','execution checks',300.,1300.,1.)
ELASTIC=FlexureParameters('synthetic','execution checks',12.,1.,0.,1.,1.)
ALWAYS=CachePolicy(mode='always')


def _process_cache(path):
    with ArrayStore(path,StoreLimits(1024,1<<20,4<<20)) as store:
        value=cached_temperature(np.arange(512.),1.,THERMAL,store=store,cache_policy=ALWAYS)
        return value.tobytes(),store.statistics()['snapshots']


def _process_lock_probe(path,marker):
    with ArrayStore(path,StoreLimits(1024,1<<20,4<<20)) as store:
        with reuse._process_claim(store,'a'*64,None,10.):
            Path(marker).write_text('locked')
            time.sleep(60)


def _await(predicate, seconds=3.):
    deadline=time.monotonic()+seconds
    while not predicate():
        if time.monotonic()>deadline: raise AssertionError('bounded wait expired')
        time.sleep(.005)


class ExecutionTests(unittest.TestCase):
    def test_default_is_auto_and_small_jobs_are_serial(self):
        with KernelExecutor() as ex:
            actual=list(ex.temperatures([(np.arange(16.),1.)]*3,THERMAL))
            self.assertEqual(ex.statistics()['serial_jobs'],3)
            self.assertEqual(ex.statistics()['parallel_jobs'],0)
            self.assertEqual(ex.statistics()['reserved_bytes'],0)
        for a in actual: assert_array_equal(a,half_space_temperature(np.arange(16.),1.,THERMAL))

    def test_parallel_all_kernels_match_serial(self):
        rotation=Rotation.from_axis_angle([1.,2.,3.],.3)
        operator=PeriodicFlexure(PeriodicGrid1D(128,128.),ELASTIC)
        points=[np.arange(384.).reshape(-1,3)+i for i in range(5)]
        loads=[np.arange(128.)+i for i in range(5)]
        temperatures=[(np.arange(256.)[:,None],np.array([[0.,1.,4.]]))]*5
        with KernelExecutor(ExecutionPolicy(mode='threads',max_workers=2,max_inflight=3)) as ex:
            outputs=list(ex.rotations(points,rotation))
            for a,b in zip(outputs,points): assert_array_equal(a,rotation.apply(b))
            outputs=list(ex.flexure(loads,operator))
            for a,b in zip(outputs,loads): assert_array_equal(a,operator.solve(b))
            outputs=list(ex.temperatures(temperatures,THERMAL))
            for a,b in zip(outputs,temperatures): assert_array_equal(a,half_space_temperature(*b,THERMAL))
            self.assertLessEqual(ex.statistics()['peak_inflight'],3)
            self.assertEqual(ex.statistics()['parallel_jobs'],15)
            self.assertEqual(ex.statistics()['reserved_bytes'],0)

    def test_auto_uses_large_batches_but_not_gil_reference(self):
        p=ExecutionPolicy(min_parallel_elements=64,max_workers=2)
        with KernelExecutor(p) as ex:
            list(ex.temperatures([(np.arange(64.),1.)]*2,THERMAL))
            self.assertEqual(ex.statistics()['parallel_jobs'],2)
            list(ex.temperatures([(np.arange(64.),1.)],THERMAL,backend='reference'))
            self.assertEqual(ex.statistics()['serial_jobs'],1)

    def test_outputs_and_submitted_inputs_are_detached(self):
        source=np.arange(192.).reshape(-1,3)
        expected=source.copy()
        with KernelExecutor(ExecutionPolicy(mode='threads')) as ex:
            it=ex.rotations([source],Rotation((1,0,0,0)))
            result=next(it);source[:]=900
            assert_array_equal(result,expected)
            with self.assertRaises(ValueError):result.setflags(write=True)
            it.close()

    def test_source_is_lazy_and_close_releases_queued_work(self):
        seen=[]
        def inputs():
            for i in range(100):
                seen.append(i)
                yield np.full((8,3),i,dtype=float)
        with KernelExecutor(ExecutionPolicy(mode='threads',max_inflight=2)) as ex:
            iterator=ex.rotations(inputs(),Rotation((1,0,0,0)))
            first=next(iterator)
            self.assertLessEqual(len(seen),2)
            iterator.close()
            self.assertEqual(ex.statistics()['reserved_bytes'],0)
            assert_array_equal(first,np.zeros((8,3)))

    def test_byte_budget_applies_before_snapshot(self):
        from atlas_tectonics import execution
        with KernelExecutor(ExecutionPolicy(max_work_bytes=8192)) as ex:
            with mock.patch.object(execution,'snapshot',side_effect=AssertionError('allocated')):
                with self.assertRaises(MemoryLimitError):list(ex.rotations([np.ones((100,3))],Rotation((1,0,0,0))))
            self.assertEqual(ex.statistics()['reserved_bytes'],0)

    def test_byte_budget_reduces_parallel_inflight(self):
        with KernelExecutor(ExecutionPolicy(mode='threads',max_inflight=4,max_work_bytes=150000)) as ex:
            values=list(ex.temperatures([(np.arange(512.),1.)]*8,THERMAL))
            self.assertEqual(len(values),8)
            self.assertLessEqual(ex.statistics()['peak_reserved_bytes'],150000)
            self.assertEqual(ex.statistics()['reserved_bytes'],0)

    def test_worker_error_and_following_new_stream(self):
        with KernelExecutor(ExecutionPolicy(mode='threads')) as ex:
            with self.assertRaises(TectonicsError):list(ex.temperatures([(np.arange(16.),1.),(np.array([-1.]),1.)],THERMAL))
            self.assertEqual(ex.statistics()['reserved_bytes'],0)
            self.assertEqual(len(list(ex.temperatures([(np.arange(8.),1.)],THERMAL))),1)

    def test_cancellation_before_and_during_consumption(self):
        cancelled=threading.Event()
        with KernelExecutor(ExecutionPolicy(mode='threads')) as ex:
            iterator=ex.temperatures([(np.arange(32.),1.)]*8,THERMAL,cancel=cancelled)
            next(iterator);cancelled.set()
            with self.assertRaises(CancelledError):next(iterator)
            self.assertEqual(ex.statistics()['reserved_bytes'],0)
        with KernelExecutor() as ex:
            ex.cancel()
            with self.assertRaises(CancelledError):ex.temperatures([],THERMAL)

    def test_no_nested_stream_or_use_after_close(self):
        ex=KernelExecutor()
        with self.assertRaises(TectonicsError):ex.temperatures([],THERMAL)
        with ex:
            it=ex.temperatures([(np.arange(4.),1.)]*2,THERMAL)
            next(it)
            with self.assertRaises(TectonicsError):ex.temperatures([],THERMAL)
            it.close()
        with self.assertRaises(TectonicsError):ex.temperatures([],THERMAL)
        ex.close()

    def test_thread_limits_are_shared_and_restored(self):
        from threadpoolctl import threadpool_info
        def current():return sorted((x['filepath'],x['num_threads']) for x in threadpool_info())
        before=current()
        with KernelExecutor() as ex:
            with KernelExecutor():
                self.assertTrue(all(n==1 for _,n in current()))
            with self.assertRaises(TectonicsError):
                with KernelExecutor(ExecutionPolicy(max_workers=1,inner_threads=2)):pass
        self.assertEqual(current(),before)

    def test_native_control_has_one_driving_thread(self):
        with KernelExecutor() as ex:
            def other():
                with KernelExecutor():pass
            with ThreadPoolExecutor(1) as pool:
                with self.assertRaises(TectonicsError):pool.submit(other).result(timeout=3)
                with self.assertRaises(TectonicsError):pool.submit(ex.close).result(timeout=3)
            self.assertEqual(len(list(ex.temperatures([(np.arange(4.),1.)],THERMAL))),1)

    def test_unverified_threaded_blas_is_refused_not_silently_changed(self):
        with KernelExecutor(ExecutionPolicy(mode='threads')) as ex:
            with mock.patch('threadpoolctl.threadpool_info',return_value=[{'user_api':'blas','internal_api':'mkl','num_threads':1}]):
                with self.assertRaises(TectonicsError):list(ex.rotations([np.ones((8,3))],Rotation((1,0,0,0))))
            self.assertEqual(ex.statistics()['reserved_bytes'],0)

    def test_invalid_policy_and_inputs(self):
        for kw in ({'max_workers':0},{'mode':'gpu'},{'max_inflight':1000},{'max_work_bytes':0},{'inner_threads':True}):
            with self.assertRaises(TectonicsError):ExecutionPolicy(**kw)
        with KernelExecutor() as ex:
            with self.assertRaises(TectonicsError):list(ex.temperatures([np.ones(4)],THERMAL))
            with self.assertRaises(TectonicsError):list(ex.rotations([np.ones((2,2))],Rotation((1,0,0,0))))
            with self.assertRaises(TectonicsError):list(ex.flexure([np.ones(7)],PeriodicFlexure(PeriodicGrid1D(8,8),ELASTIC)))

    def test_unstarted_stream_can_be_closed_and_replaced(self):
        with KernelExecutor() as ex:
            iterator=ex.temperatures([],THERMAL)
            with self.assertRaises(TectonicsError):ex.temperatures([],THERMAL)
            iterator.close()
            self.assertEqual(list(ex.temperatures([],THERMAL)),[])

    def test_auto_keeps_large_rotation_on_measured_serial_path(self):
        with KernelExecutor(ExecutionPolicy(min_parallel_elements=1)) as ex:
            list(ex.rotations([np.ones((100,3))]*2,Rotation((1,0,0,0))))
            self.assertEqual(ex.statistics()['serial_jobs'],2)
            self.assertEqual(ex.statistics()['parallel_jobs'],0)

    def test_process_spawn_results_refrozen_and_pool_reused(self):
        with KernelExecutor(ExecutionPolicy(mode='processes',max_workers=2,max_inflight=2)) as ex:
            a=list(ex.temperatures([(np.arange(64.),1.)]*3,THERMAL))
            pool=ex._pool
            b=list(ex.temperatures([(np.arange(64.),1.)]*2,THERMAL))
            self.assertIs(ex._pool,pool)
            for r in a+b:
                assert_array_equal(r,half_space_temperature(np.arange(64.),1.,THERMAL))
                with self.assertRaises(ValueError):r.setflags(write=True)
            self.assertEqual(ex.statistics()['reserved_bytes'],0)


_LEASE_OWNER_PRELUDE='''import gc,json,sys,threading
sys.path.insert(0,sys.argv[1])
import numpy as np
from threadpoolctl import threadpool_info
import scipy.special
import atlas_tectonics.execution as execution
from atlas_tectonics import ThermalParameters
from atlas_tectonics.execution import ExecutionPolicy,KernelExecutor
THERMAL=ThermalParameters('synthetic','lease owner checks',300.,1300.,1.)
THREADS=ExecutionPolicy(mode='threads',max_workers=2)
def native():return sorted((x['filepath'],x['num_threads']) for x in threadpool_info())
def leases():return [execution._LIMIT_USERS,execution._POOL_SLOTS]
def limited():return all(n==1 for _,n in native())
def workers():return sum(t.name.startswith('atlas-kernel') for t in threading.enumerate())
def drive(executor):return len(list(executor.temperatures([(np.arange(8.),1.)]*3,THERMAL)))
out={};box={}
def attempt(name,call):
    try:out[name]=call()
    except Exception as exc:out[name]=type(exc).__name__
def abandon(policy=THREADS,first=lambda:None):
    # A thread enters an executor, uses it and ends without closing it.
    def run():
        box['identifier']=threading.get_ident();first()
        box['executor']=KernelExecutor(policy);box['executor'].__enter__();drive(box['executor'])
    box['owner']=threading.Thread(target=run);box['owner'].start();box['owner'].join()
def mine():
    with KernelExecutor(THREADS) as executor:return [drive(executor),leases(),limited()]
before=native()
'''


class LeaseOwnerTests(unittest.TestCase):
    """R7 (3f): a Thread object owns the native-thread lease, and an ended owner's lease is recovered.

    An executor left open by a thread that has ended cannot be cleaned up by the
    unrepaired code. Every case here therefore runs in its own interpreter, where
    a regression cannot leave the lease held for every later test in this process.
    Refusals are compared by exception type, never by message.
    """
    def scenario(self,body):
        source=Path(__file__).resolve().parents[1]/'src'
        result=subprocess.run([sys.executable,'-I','-B','-c',_LEASE_OWNER_PRELUDE+body+'\nprint(json.dumps(out))\n',
                               str(source)],capture_output=True,text=True,timeout=120)
        self.assertEqual(result.returncode,0,result.stderr)
        self.maxDiff=None
        return json.loads(result.stdout.strip().splitlines()[-1])

    def test_ended_owners_share_and_cpu_slots_are_reclaimed_by_the_next_executor(self):
        out=self.scenario('''abandon();out['abandoned']=leases()
def next_executor():
    with KernelExecutor(THREADS) as executor:
        first=[drive(executor),leases(),limited()]
        box['executor'].close()   # late: its share and CPU slots were reclaimed when this executor was entered
        return first+[leases(),limited(),drive(executor)]
attempt('next_executor',next_executor)
out['after']=[leases(),native()==before,workers()]''')
        self.assertEqual(out,{'abandoned':[1,2],'next_executor':[3,[1,2],True,[1,2],True,3],'after':[[0,0],True,0]})

    def test_executor_of_an_ended_thread_is_closed_from_another_thread_but_never_driven(self):
        out=self.scenario('''abandon()
attempt('drive',lambda:drive(box['executor']))
attempt('close',lambda:box['executor'].close())
out['after_close']=[leases(),native()==before,workers()]
attempt('next_executor',mine);out['after']=[leases(),native()==before,workers()]''')
        self.assertEqual(out,{'drive':'TectonicsError','close':None,'after_close':[[0,0],True,0],
                              'next_executor':[3,[1,2],True],'after':[[0,0],True,0]})

    def test_collected_executor_with_another_limit_does_not_refuse_the_next(self):
        out=self.scenario('''two=ExecutionPolicy(mode='serial',max_workers=1,inner_threads=2)
def collected():
    abandon(two);held=[leases(),execution._LIMIT_VALUE]
    del box['executor'];gc.collect();return held
def plain_share():   # the share a solver plan takes around one operation
    execution._acquire_native_limit(1);held=[leases(),execution._LIMIT_VALUE,limited()]
    execution._release_native_limit();return held+[leases(),native()==before]
out['abandoned']=collected();attempt('plain_share',plain_share)
out['abandoned_again']=collected();attempt('next_executor',mine)
out['after']=[leases(),native()==before,workers()]''')
        self.assertEqual(out,{'abandoned':[[1,0],2],'plain_share':[[1,0],1,True,[0,0],True],
                              'abandoned_again':[[1,0],2],'next_executor':[3,[1,2],True],'after':[[0,0],True,0]})

    def test_later_thread_with_the_ended_owners_identifier_is_not_the_owner(self):
        out=self.scenario('''abandon();found={}
def later():
    if threading.get_ident()!=box['identifier']:return
    found['same_thread_object']=threading.current_thread() is box['owner']
    try:found['drive']=drive(box['executor'])
    except Exception as exc:found['drive']=type(exc).__name__
    try:
        with KernelExecutor(ExecutionPolicy(mode='serial')):found['users_in_its_own_executor']=execution._LIMIT_USERS
    except Exception as exc:found['users_in_its_own_executor']=type(exc).__name__
for _ in range(20000):
    thread=threading.Thread(target=later);thread.start();thread.join()
    if found:break
out.update(found)''')
        if not out:self.skipTest('no later thread was handed the ended thread\'s identifier in 20000 attempts')
        # Before the repair this thread passed as the owner: it drove the ended thread's executor and shared its lease.
        self.assertEqual(out,{'same_thread_object':False,'drive':'TectonicsError','users_in_its_own_executor':1})

    def test_plain_share_of_an_ended_thread_is_not_reclaimed_until_it_is_returned(self):
        out=self.scenario('''abandon(first=lambda:box.update(plain=execution._acquire_native_limit(1)))
out['abandoned']=[leases(),box['plain'] is None]   # a plain share carries no owner record
attempt('refused',mine);out['still_held']=leases()
execution._release_native_limit()   # what closing the plain share's holder does, from any thread
attempt('next_executor',mine);out['after']=[leases(),native()==before]''')
        self.assertEqual(out,{'abandoned':[[2,2],True],'refused':'TectonicsError','still_held':[2,2],
                              'next_executor':[3,[1,2],True],'after':[[0,0],True]})

    def test_executor_whose_lease_was_reclaimed_is_never_driven_again(self):
        # During interpreter shutdown the main thread reports itself ended while code still runs on it.
        # A thread that does the same stands in for it: its lease is reclaimed although it can still call its executor.
        out=self.scenario('''class ReportsEnded(threading.Thread):
    def is_alive(self):return False
entered=threading.Event();reclaimed=threading.Event()
def run():
    with KernelExecutor(THREADS) as stale:
        drive(stale);entered.set();reclaimed.wait(30)
        attempt('drive_after_reclaim',lambda:drive(stale))
thread=ReportsEnded(target=run);thread.start();entered.wait(30)
def next_executor():
    with KernelExecutor(THREADS) as executor:
        first=[drive(executor),leases()]
        reclaimed.set();thread.join(30)   # the stale executor is refused, then closed by its own thread
        return first+[leases(),drive(executor)]
attempt('next_executor',next_executor)
reclaimed.set();thread.join(30)
out['after']=[leases(),native()==before,workers()]''')
        self.assertEqual(out,{'drive_after_reclaim':'TectonicsError','next_executor':[3,[1,2],[1,2],3],
                              'after':[[0,0],True,0]})

    def test_owner_not_known_to_have_ended_keeps_its_lease(self):
        # The interpreter gives no definite answer for a thread it did not start. One that refuses to answer stands
        # in for it: its lease is not reclaimed, and the refusal stays the executor's own error.
        out=self.scenario('''class Unanswerable(threading.Thread):
    def is_alive(self):raise RuntimeError('no answer')
entered=threading.Event();leave=threading.Event()
def run():
    with KernelExecutor(THREADS) as executor:
        box['executor']=executor;drive(executor);entered.set();leave.wait(30)
thread=Unanswerable(target=run);thread.start();entered.wait(30)
attempt('next_executor',mine);attempt('close',lambda:box['executor'].close());out['held']=leases()
leave.set();thread.join(30)
out['after']=[leases(),native()==before,workers()]''')
        self.assertEqual(out,{'next_executor':'TectonicsError','close':'TectonicsError','held':[1,2],
                              'after':[[0,0],True,0]})

    def test_ended_owners_lease_is_not_reclaimed_while_a_job_it_submitted_still_runs(self):
        # The owner ends in the middle of a stream: a job it submitted is still running in its pool. Its CPU slots
        # stay counted and its limit stays applied until that job is done; only then is the lease reclaimed.
        out=self.scenario('''import time
from atlas_tectonics.execution import _AdmittedCall
started=threading.Event();finish=threading.Event()
def slow(budget):started.set();finish.wait(30);return 1
def calls():
    yield _AdmittedCall(lambda budget:0,lambda result:result,lambda:None,1,1024)
    yield _AdmittedCall(slow,lambda result:result,lambda:None,1,1024)
def run():
    box['executor']=KernelExecutor(THREADS);box['executor'].__enter__()
    box['stream']=box['executor']._admitted_calls(calls());next(box['stream'])   # submits both, returns the first
owner=threading.Thread(target=run);owner.start();owner.join();out['job_running']=started.wait(30)
out['abandoned']=leases()
attempt('while_it_runs',mine);out['still_held']=[leases(),limited()]
finish.set();deadline=time.monotonic()+10
while True:   # the job is done a moment after it is told to finish
    attempt('once_it_is_done',mine)
    if out['once_it_is_done']!='TectonicsError' or time.monotonic()>deadline:break
    time.sleep(.005)
box['executor'].close();out['after']=[leases(),native()==before,workers()]''')
        self.assertEqual(out,{'job_running':True,'abandoned':[1,2],'while_it_runs':'TectonicsError',
                              'still_held':[[1,2],True],'once_it_is_done':[3,[1,2],True],'after':[[0,0],True,0]})

    def test_ended_owners_executor_closed_by_two_threads_at_once_is_closed_once(self):
        # Any thread may close an ended thread's executor, so two may try together. The first is held inside its
        # pool shutdown, before anything is returned. The second must wait for it, not run the close as well:
        # two closes side by side return the executor's CPU slots, or its share, a second time.
        out=self.scenario('''abandon();pool=box['executor']._pool;shutdown=pool.shutdown
inside=threading.Event();release=threading.Event();shutdowns=[]
def held(**options):
    shutdowns.append(threading.current_thread().name)
    if len(shutdowns)==1:inside.set();release.wait(30)
    return shutdown(**options)
pool.shutdown=held
def close(name):attempt(name,lambda:box['executor'].close())
first=threading.Thread(target=close,args=('first',));first.start();out['first_inside']=inside.wait(30)
second=threading.Thread(target=close,args=('second',));second.start();second.join(.5)
out['second_waits']=second.is_alive();out['held']=leases()
release.set();first.join(30);second.join(30)
out['pool_shutdowns']=len(shutdowns);out['after']=[leases(),native()==before,workers()]
attempt('next_executor',mine);out['finally']=leases()''')
        self.assertEqual(out,{'first_inside':True,'second_waits':True,'held':[1,2],'first':None,'second':None,
                              'pool_shutdowns':1,'after':[[0,0],True,0],'next_executor':[3,[1,2],True],
                              'finally':[0,0]})


class IdentityTests(unittest.TestCase):
    def test_checkpoint_dtype_change_invalidates_existing_and_fresh_identity(self):
        from atlas_tectonics import regional_checkpoint
        with ExecutionContext('scipy') as context:
            original = context.identity
            for dtype in (np.dtype('f4'), np.dtype('>f8')):
                with self.subTest(dtype=dtype), mock.patch.object(regional_checkpoint, '_DTYPE', dtype):
                    with self.assertRaisesRegex(TectonicsError, 'loaded implementation changed'):
                        context.verify()
                    self.assertNotEqual(reuse.execution_identity('scipy'), original)
            context.verify()
            self.assertEqual(reuse.execution_identity('scipy'), original)

    def test_dtype_layout_is_captured_without_lossy_str_or_descr_shortcuts(self):
        encode = lambda value: reuse._json(reuse._constant(value))
        layouts = [np.dtype('<f8'), np.dtype('>f8'), np.dtype('<i8'),
            np.dtype([('a', '<f8')]), np.dtype([('b', '<f8')]),
            np.dtype([('a', '<i8')]), np.dtype([(('title', 'a'), '<f8')]),
            np.dtype([('a', '<f8')], align=True),
            np.dtype(('<f8', (2, 3))), np.dtype(('<f8', (3, 2))),
            np.dtype({'names': ['a','b'], 'formats': ['<i4','<i4'], 'offsets': [0,0], 'itemsize': 8}),
            np.dtype({'names': ['a','b'], 'formats': ['<i4','<i4'], 'offsets': [0,4], 'itemsize': 8}),
            np.dtype({'names': ['b','a'], 'formats': ['<i4','<i4'], 'offsets': [4,0], 'itemsize': 8}),
            np.dtype({'names': ['a','b'], 'formats': ['<i4','<i4'], 'offsets': [0,4], 'itemsize': 12})]
        self.assertEqual(len(set(map(encode, layouts))), len(layouts))
        for dtype in layouts:
            self.assertTrue(reuse._captured(dtype))
            self.assertEqual(encode(dtype), encode(pickle.loads(pickle.dumps(dtype))))

    def test_dtype_metadata_is_detached_ordered_and_checked_on_every_verify(self):
        from atlas_tectonics import regional_checkpoint
        metadata = {'units': ['m'], 'revision': 1}
        dtype = np.dtype('f8', metadata=metadata)
        self.assertEqual(dtype, np.dtype('f8'))  # NumPy equality ignores metadata.
        self.assertNotEqual(reuse._constant(dtype), reuse._constant(np.dtype('f8')))
        self.assertNotEqual(reuse._constant(np.dtype('f8', metadata={})), reuse._constant(np.dtype('f8')))
        self.assertEqual(reuse._constant(dtype), reuse._constant(np.dtype('f8',
            metadata={'revision': 1, 'units': ['m']})))
        nested = np.dtype('f8', metadata={'count': np.int64(2), 'z': np.complex128(1+2j),
            'layout': np.dtype([('value', '<f8', (2,))]), 'raw': b'\x01'})
        self.assertEqual(reuse._constant(nested), reuse._constant(pickle.loads(pickle.dumps(nested))))
        with mock.patch.object(regional_checkpoint, '_DTYPE', dtype), ExecutionContext('scipy') as context:
            original = context.identity
            metadata['units'][0] = 'km'
            with self.assertRaisesRegex(TectonicsError, 'loaded implementation changed'):
                context.verify()
            self.assertNotEqual(reuse.execution_identity('scipy'), original)
            metadata['units'][0] = 'm'
            context.verify()

    def test_uninspectable_dtype_metadata_refuses_instead_of_type_only_binding(self):
        cyclic = []
        cyclic.append(cyclic)
        for value, message in ((cyclic, 'cyclic'), (object(), 'unsupported')):
            with self.subTest(message=message), self.assertRaisesRegex(TectonicsError, message):
                reuse._constant(np.dtype('f8', metadata={'value': value}))

    def test_context_equals_fresh_identity(self):
        for backend in ('reference','scipy'):
            with ExecutionContext(backend) as ctx:
                self.assertEqual(ctx.identity,reuse.execution_identity(backend))
                self.assertEqual(ctx.identity,ctx.identity)
            with self.assertRaises(TectonicsError):ctx.verify()

    def test_source_bytes_changes_without_metadata_shortcuts(self):
        ctx=ExecutionContext()
        original=reuse._source_bytes
        altered=original();name=next(iter(altered));altered[name]+=b' '
        with mock.patch.object(reuse,'_source_bytes',return_value=altered):
            with self.assertRaises(TectonicsError):ctx.verify()
        ctx.verify()

    def test_membership_change_is_not_hidden(self):
        ctx=ExecutionContext();altered=reuse._source_bytes();altered['extra.py']=b''
        with mock.patch.object(reuse,'_source_bytes',return_value=altered):
            with self.assertRaises(TectonicsError):ctx.verify()

    def test_loaded_function_and_alias_change_refused(self):
        import atlas_tectonics.thermal as thermal
        ctx=ExecutionContext('scipy')
        with mock.patch.object(thermal,'half_space_temperature',lambda *a,**kw:np.array([0.])):
            with self.assertRaises(TectonicsError):ctx.verify()
        with mock.patch.object(thermal,'array',lambda x,*a,**kw:x):
            with self.assertRaises(TectonicsError):ctx.verify()
        ctx.verify()

    def test_default_change_and_constant_change_refused(self):
        import atlas_tectonics.thermal as thermal
        ctx=ExecutionContext('scipy');fn=thermal.half_space_temperature
        old=fn.__kwdefaults__
        try:
            fn.__kwdefaults__=dict(old,backend='reference')
            with self.assertRaises(TectonicsError):ctx.verify()
        finally:fn.__kwdefaults__=old
        with mock.patch.object(thermal,'DEFAULT_COOLING_BATCH_ELEMENTS',1):
            with self.assertRaises(TectonicsError):ctx.verify()
        ctx.verify()

    def test_context_does_not_repeat_normalisation(self):
        with mock.patch.object(reuse,'_normal_code',wraps=reuse._normal_code) as spy:
            ctx=ExecutionContext();count=spy.call_count
            for _ in range(3):ctx.verify()
            self.assertEqual(spy.call_count,count)
            self.assertGreater(count,0)

    def test_prepared_input_identity_reuses_only_immutable_snapshot(self):
        original=np.arange(32.);prepared=PreparedInput(original)
        digest=prepared.digest;original[:]=900
        assert_array_equal(prepared.array,np.arange(32.))
        self.assertEqual(digest,reuse._array_identity(prepared.array))
        a=prepared.array;a.shape=(8,4)
        self.assertEqual(prepared.array.shape,(32,))
        with self.assertRaises(ValueError):prepared.array.setflags(write=True)
        again=pickle.loads(pickle.dumps(prepared))
        self.assertEqual(again.digest,digest)
        with self.assertRaises(ValueError):again.array.setflags(write=True)

    def test_prepared_invalid_and_memory_refusal(self):
        from atlas_tectonics.resources import WorkBudget
        for bad in (np.ma.array([1.]),[np.nan],[],[True,1.]):
            with self.assertRaises(TectonicsError):PreparedInput(bad)
        with self.assertRaises(MemoryLimitError):PreparedInput(np.arange(100.),budget=WorkBudget(8))

    def test_unrelated_import_does_not_change_identity(self):
        ctx=ExecutionContext()
        import atlas_tectonics._transport_native
        ctx.verify()
        self.assertEqual(ctx.identity,reuse.execution_identity())

    def test_identity_binds_every_module_in_the_source_membership(self):
        # R1 (s01-1): a fixed list omitted 3D, integration, assembly, ports,
        # plate-reference and (outside numba) native modules.
        import atlas_tectonics
        root=Path(atlas_tectonics.__file__).parent
        members=sorted(p.stem for p in root.glob('*.py') if p.stem!='__init__')
        with ExecutionContext('scipy') as ctx:
            self.assertEqual(list(ctx._modules),members)  # numba is installed in the tested environment
        for name in ('regional_heat3d','regional_execution3d','workflow_ports','assembly','_integration_heat',
                     'integration_evolution','plate_reference_use','_regional_native'):
            self.assertIn(name,members)

    def test_stale_loaded_code_of_formerly_omitted_modules_changes_identity(self):
        # Same source bytes, different loaded code: the identity must not claim
        # the fresh source (a long-lived process after a checkout update).
        from atlas_tectonics import workflow_ports,assembly,regional_heat3d,_integration_heat
        fresh=reuse.execution_identity('scipy')
        for module,name in ((workflow_ports,'_public'),(assembly,'_canonical'),
                            (regional_heat3d,'_sum'),(_integration_heat,'valid_thermal')):
            with self.subTest(module=module.__name__):
                with ExecutionContext('scipy') as ctx:
                    original=getattr(module,name)
                    stale=lambda *args,_original=original,**kwargs:_original(*args,**kwargs)
                    with mock.patch.object(module,name,stale):
                        with self.assertRaisesRegex(TectonicsError,'loaded implementation changed'):ctx.verify()
                        self.assertNotEqual(reuse.execution_identity('scipy'),fresh)
                self.assertEqual(reuse.execution_identity('scipy'),fresh)

    def test_stale_module_data_and_numpy_defaults_are_bound(self):
        # Verification finding: upper-case dicts, sets and numpy scalars (and
        # numpy function defaults) were not captured, so stale data in a
        # formerly omitted module still received the fresh-source identity.
        import numpy as np
        from atlas_tectonics import _integration_column, _integration_heat, spherical_geometry
        fresh = reuse.execution_identity('scipy')
        edits = ((_integration_column, 'POLICY', dict(_integration_column.POLICY, iterations=4)),
                 (_integration_heat, 'THERMAL_KEYS', set(_integration_heat.THERMAL_KEYS)|{'r1-extra'}),
                 (_integration_heat, 'UNIT_ROUNDOFF', np.float64(8.881784197001252e-16)),
                 (spherical_geometry, '_DEFAULT_ANGULAR_BAND', np.float64(1.4551915228366852e-11)))
        for module, name, stale in edits:
            with self.subTest(name=module.__name__+'.'+name):
                with ExecutionContext('scipy') as ctx:
                    with mock.patch.object(module, name, stale):
                        with self.assertRaisesRegex(TectonicsError, 'loaded implementation changed'):ctx.verify()
                        self.assertNotEqual(reuse.execution_identity('scipy'), fresh)
        self.assertEqual(reuse.execution_identity('scipy'), fresh)
        # Functions held in tables and compiled patterns are bound by content.
        import re
        from atlas_tectonics import integration_state, storage
        key = next(iter(integration_state._PRESENCE))
        with ExecutionContext('scipy') as ctx:
            with mock.patch.dict(integration_state._PRESENCE, {key: lambda state: None}):
                with self.assertRaisesRegex(TectonicsError, 'loaded implementation changed'):ctx.verify()
                self.assertNotEqual(reuse.execution_identity('scipy'), fresh)
            with mock.patch.object(storage, '_SHA', re.compile(r'[0-9a-f]{40}\Z')):
                with self.assertRaisesRegex(TectonicsError, 'loaded implementation changed'):ctx.verify()
        self.assertEqual(reuse.execution_identity('scipy'), fresh)
        self.assertEqual(reuse._constant(float('inf')), {'float': 'inf'})
        with self.assertRaisesRegex(TectonicsError, 'ambiguous'):reuse._constant({1: 'a', 'int:1': 'b'})
        self.assertEqual(reuse._constant(np.float64(.1)), {'numpy': '<f8', 'repr': '0.1'})
        self.assertEqual(reuse._constant(frozenset({'b', 'a'})), {'set': ['a', 'b']})

    def test_unimportable_native_module_is_skipped_only_outside_numba(self):
        real = reuse.importlib.import_module
        def broken(name, *args):
            if name == 'atlas_tectonics._mesh_native':
                raise ImportError('simulated broken optional runtime')
            return real(name, *args)
        with mock.patch.object(reuse.importlib, 'import_module', broken):
            with ExecutionContext('scipy') as ctx:
                self.assertNotIn('_mesh_native', ctx._modules)
                self.assertIn('_transport_native', ctx._modules)
            with self.assertRaisesRegex(TectonicsError, 'cannot be imported.*_mesh_native'):
                ExecutionContext('numba')
        def broken_core(name, *args):
            if name == 'atlas_tectonics.assembly':
                raise RuntimeError('simulated import-time failure')
            return real(name, *args)
        with mock.patch.object(reuse.importlib, 'import_module', broken_core):
            with self.assertRaisesRegex(TectonicsError, 'cannot be imported.*assembly'):
                ExecutionContext('scipy')

    def test_membership_identity_is_independent_of_import_history(self):
        code=('import sys,importlib\n'
              'for n in sys.argv[1:]: importlib.import_module("atlas_tectonics."+n)\n'
              'from atlas_tectonics.reuse import ExecutionContext\n'
              'print(ExecutionContext("scipy").identity)')
        import atlas_tectonics
        env=dict(os.environ,PYTHONPATH=os.pathsep.join([str(Path(atlas_tectonics.__file__).resolve().parents[1]),
                                                         os.environ.get('PYTHONPATH','')]))
        run=lambda *names:subprocess.run([sys.executable,'-B','-c',code,*names],capture_output=True,text=True,
                                         env=env,timeout=300,check=True).stdout.strip()
        minimal=run()
        self.assertEqual(len(minimal),64)
        self.assertEqual(run('assembly','regional_evolution3d','_mesh_native','geometry_index'),minimal)


class CacheExecutionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.path=Path(self.tmp.name)/'cache.db'
        self.store=ArrayStore(self.path,StoreLimits(1024,1<<20,4<<20,4096))
        self.control=ReuseController()
        self.addCleanup(self.tmp.cleanup);self.addCleanup(self.store.close)

    def test_default_auto_skips_cheap_results_and_no_identity_work(self):
        with mock.patch.object(reuse,'_invocation_record',side_effect=AssertionError('unneeded identity')):
            a=cached_temperature(np.arange(64.),1.,THERMAL,store=self.store,controller=self.control)
        assert_array_equal(a,half_space_temperature(np.arange(64.),1.,THERMAL))
        self.assertEqual(self.store.statistics()['snapshots'],0)
        self.assertEqual(self.control.statistics()['bypasses'],1)

    def test_explicit_always_preserves_persistent_reuse(self):
        for _ in range(2):cached_temperature(np.arange(64.),1.,THERMAL,store=self.store,cache_policy=ALWAYS,controller=self.control)
        self.assertEqual(self.control.statistics()['writes'],1)
        self.assertEqual(self.control.statistics()['hits'],1)
        self.assertEqual(self.control.statistics()['contexts'],1)

    def test_off_never_reads_or_writes_store(self):
        with mock.patch.object(self.store,'get',side_effect=AssertionError('read')):
            r=cached_temperature(np.arange(64.),1.,THERMAL,store=self.store,cache_policy=CachePolicy(mode='off'))
        assert_array_equal(r,half_space_temperature(np.arange(64.),1.,THERMAL))
        self.assertEqual(self.store.statistics()['snapshots'],0)

    def test_auto_threshold_admission_and_skip(self):
        admit=CachePolicy(min_result_bytes=0,min_compute_seconds=0.)
        skip=CachePolicy(min_result_bytes=0,min_compute_seconds=100.)
        # Automatic admission observes one direct calculation before paying for
        # verification/persistence. An explicit zero threshold permits the next.
        cached_temperature(np.arange(64.),1.,THERMAL,store=self.store,cache_policy=admit)
        cached_temperature(np.arange(64.),1.,THERMAL,store=self.store,cache_policy=admit)
        self.assertEqual(self.store.statistics()['snapshots'],1)
        cached_temperature(np.arange(64.),2.,THERMAL,store=self.store,cache_policy=skip)
        self.assertEqual(self.store.statistics()['snapshots'],1)

    def test_auto_learning_skips_identity_for_known_cheap_large_result(self):
        value=np.arange(65536.)
        cached_temperature(value,1.,THERMAL,store=self.store,controller=self.control,cache_policy=CachePolicy(min_compute_seconds=100.))
        with mock.patch.object(reuse,'_invocation_record',side_effect=AssertionError('unneeded identity')):
            result=cached_temperature(value,1.,THERMAL,store=self.store,controller=self.control,cache_policy=CachePolicy(min_compute_seconds=100.))
        assert_array_equal(result,half_space_temperature(value,1.,THERMAL))
        self.assertEqual(self.store.statistics()['snapshots'],0)
        self.assertEqual(self.control.statistics()['contexts'],0)

    def test_prepared_and_plain_same_cache_identity(self):
        d=np.arange(64.);age=np.array(1.)
        cached_temperature(d,age,THERMAL,store=self.store,cache_policy=ALWAYS)
        cached_temperature(PreparedInput(d),PreparedInput(age),THERMAL,store=self.store,cache_policy=ALWAYS)
        self.assertEqual(self.store.statistics()['snapshots'],1)

    def test_prepared_digests_are_not_recomputed(self):
        d=PreparedInput(np.arange(64.));t=PreparedInput(np.array(1.))
        with mock.patch.object(reuse,'_array_identity',side_effect=AssertionError('rehash')):
            cached_temperature(d,t,THERMAL,store=self.store,cache_policy=ALWAYS)
        self.assertEqual(self.store.statistics()['snapshots'],1)

    def test_changed_inputs_parameters_backend_change_identity(self):
        args=[(1.,THERMAL,'scipy'),(2.,THERMAL,'scipy'),(1.,replace(THERMAL,diffusivity_m2_s=2),'scipy'),(1.,THERMAL,'reference')]
        for age,param,backend in args:cached_temperature(np.arange(64.),age,param,backend=backend,store=self.store,cache_policy=ALWAYS)
        self.assertEqual(self.store.statistics()['snapshots'],4)

    def test_flexure_context_and_output_contract(self):
        op=PeriodicFlexure(PeriodicGrid1D(64,64.),ELASTIC);ctx=ExecutionContext()
        load=PreparedInput(np.arange(64.))
        r=cached_flexure(op,load,store=self.store,context=ctx,cache_policy=ALWAYS)
        assert_array_equal(r,op.solve(load.array))
        r2=cached_flexure(op,load,store=self.store,context=ctx,cache_policy=ALWAYS)
        assert_array_equal(r2,r)
        with self.assertRaises(ValueError):r2.setflags(write=True)

    def test_concurrent_same_request_computes_and_writes_once(self):
        started=threading.Event();release=threading.Event();calls=[]
        original=reuse.half_space_temperature
        def slower(*a,**kw):
            calls.append(1);started.set()
            if not release.wait(5):raise TimeoutError('test release missing')
            return original(*a,**kw)
        with mock.patch.object(reuse,'half_space_temperature',side_effect=slower):
            with ThreadPoolExecutor(4) as pool:
                def call():return cached_temperature(np.arange(64.),1.,THERMAL,store=self.store,cache_policy=ALWAYS)
                futures=[pool.submit(call) for _ in range(4)]
                self.assertTrue(started.wait(3))
                _await(lambda:reuse._FLIGHTS._waiters>=3)
                release.set();values=[f.result(timeout=10) for f in futures]
        self.assertEqual(len(calls),1)
        self.assertEqual(self.store.statistics()['snapshots'],1)
        for v in values[1:]:
            self.assertIsNot(v,values[0]);assert_array_equal(v,values[0])
        values[0].shape=(8,8)
        self.assertEqual(values[1].shape,(64,))

    def test_creator_failure_releases_waiters_and_allows_retry(self):
        flights=reuse._Flights();start=threading.Event();release=threading.Event()
        def fail():start.set();release.wait(3);raise RuntimeError('creator failed')
        with ThreadPoolExecutor(2) as pool:
            a=pool.submit(flights.run,'key',fail);self.assertTrue(start.wait(2))
            b=pool.submit(flights.run,'key',fail);_await(lambda:flights._waiters==1);release.set()
            for f in (a,b):
                with self.assertRaisesRegex(RuntimeError,'creator failed'):f.result(timeout=3)
        self.assertEqual(len(flights._entries),0)
        assert_array_equal(flights.run('key',lambda:frozen([1.])),[1.])

    def test_follower_cancellation_does_not_cancel_creator(self):
        flights=reuse._Flights();start=threading.Event();release=threading.Event();cancel=threading.Event()
        def make():start.set();release.wait(3);return frozen([7.])
        with ThreadPoolExecutor(2) as pool:
            a=pool.submit(flights.run,'k',make);start.wait(2)
            b=pool.submit(flights.run,'k',make,cancel=cancel)
            _await(lambda:flights._waiters==1);cancel.set()
            with self.assertRaises(CancelledError):b.result(timeout=3)
            release.set();assert_array_equal(a.result(timeout=3),[7.])

    def test_creator_cancellation_does_not_cancel_uncancelled_waiters(self):
        flights=reuse._Flights();start=threading.Event();release=threading.Event();leader=threading.Event();calls=[]
        def make(cancel):
            def produce():
                calls.append(cancel);start.set();release.wait(3)
                reuse._cancelled(cancel)          # a producer checks its own caller's cancellation after work
                return frozen([7.])
            return produce
        with ThreadPoolExecutor(2) as pool:
            a=pool.submit(flights.run,'k',make(leader),cancel=leader);self.assertTrue(start.wait(2))
            b=pool.submit(flights.run,'k',make(None))
            _await(lambda:flights._waiters==1);leader.set();release.set()
            with self.assertRaises(CancelledError):a.result(timeout=3)
            assert_array_equal(b.result(timeout=3),[7.])
        self.assertEqual(calls,[leader,None])        # the waiter became the next owner and computed once
        self.assertEqual((len(flights._entries),flights._waiters),(0,0))

    def test_a_finished_cancelled_owner_is_not_waited_on_again(self):
        # An owner resolves its future before it removes its entry: a waiter must not spend its retries on it.
        flights=reuse._Flights();cancelled=Future();cancelled.set_exception(CancelledError('owner cancelled'))
        flights._entries['k']=(-1,cancelled)
        assert_array_equal(flights.run('k',lambda:frozen([2.])),[2.])
        self.assertEqual((flights._entries,flights._waiters),({},0))

    def test_waiter_retries_after_other_cancellations_are_bounded(self):
        # Every registration meets a different, already cancelled owner: the waiter gives up after its bounded
        # retries with an error that is not its own cancellation.
        class Owners(dict):
            def get(self,key,default=None):
                future=Future();future.set_exception(CancelledError('owner cancelled'));return (-1,future)
        flights=reuse._Flights();flights._entries=Owners()
        with self.assertRaisesRegex(TectonicsError,'cancelled by its other callers'):
            flights.run('k',lambda:frozen([1.]))
        self.assertEqual(flights._waiters,0)

    def test_one_deadline_covers_flight_and_process_claim_waits(self):
        # The owner waits on a process claim another caller holds; it is cancelled, and the waiter that takes over
        # must not start a second full wait_timeout on that claim.
        ctx=ExecutionContext('reference');self.addCleanup(ctx.close)
        record={'schema':'deadline-probe'};key=reuse._digest(reuse._json(record))
        held=threading.Event();release=threading.Event();owner_cancel=threading.Event()
        def hold():
            with reuse._process_claim(self.store,key,None,5.):held.set();release.wait(10)
        def run(cancel):
            return reuse._evaluate(self.store,record,lambda:np.ones(4),(4,),WorkBudget(1<<24),context=ctx,
                                   controller=self.control,cache_policy=ALWAYS,cancel=cancel,wait_timeout=1.)
        with ThreadPoolExecutor(2) as pool:
            holder=pool.submit(hold);self.assertTrue(held.wait(3))
            try:
                owner=pool.submit(run,owner_cancel);_await(lambda:len(reuse._FLIGHTS._entries)>0)
                start=time.monotonic();threading.Timer(.4,owner_cancel.set).start()
                with self.assertRaises(TimeoutError):run(None)
                self.assertLess(time.monotonic()-start,1.3)
                with self.assertRaises(CancelledError):owner.result(timeout=5)
            finally:
                release.set()
            holder.result(timeout=5)

    def test_unrelated_key_on_a_busy_stripe_neither_waits_nor_times_out(self):
        # 'a'*64 and 'a'*63+'b' share a stripe (it is taken from the first 8 hex digits).
        other='a'*63+'b';held=threading.Event();release=threading.Event()
        def hold():
            with reuse._process_claim(self.store,'a'*64,None,5.) as claimed:
                held.set();release.wait(5);return claimed
        with ThreadPoolExecutor(1) as pool:
            holder=pool.submit(hold);self.assertTrue(held.wait(3))
            try:
                start=time.monotonic()
                with reuse._process_claim(self.store,other,None,.5) as claimed:self.assertFalse(claimed)
                self.assertLess(time.monotonic()-start,.4)
                with self.assertRaises(TimeoutError):   # the same identity still waits for its holder
                    with reuse._process_claim(self.store,'a'*64,None,.1):pass
            finally:
                release.set()
            self.assertTrue(holder.result(timeout=5))
        with reuse._process_claim(self.store,other,None,1.) as claimed:self.assertTrue(claimed)

    @unittest.skipUnless(os.name == 'nt', 'Windows byte-lock initialisation')
    def test_first_lock_byte_contention_retries_within_the_claim_deadline(self):
        write = os.write
        attempts = []
        def raced(fd, data):
            if data == b'0':
                attempts.append(data)
                if len(attempts) == 1:
                    raise PermissionError(errno.EACCES, 'rival owns the first byte')
            return write(fd, data)
        with mock.patch.object(reuse.os, 'write', side_effect=raced):
            with reuse._process_claim(self.store, 'd'*64, None, 1.) as claimed:
                self.assertTrue(claimed)
        self.assertEqual(len(attempts), 2)

    @unittest.skipUnless(os.name == 'nt', 'Windows byte-lock initialisation')
    def test_first_lock_byte_contention_obeys_timeout_and_releases_handle(self):
        with mock.patch.object(reuse.os, 'write', side_effect=PermissionError(errno.EACCES, 'busy')):
            with self.assertRaises(TimeoutError):
                with reuse._process_claim(self.store, 'e'*64, None, 0.):
                    self.fail('a busy initial byte must not be claimed')
        with reuse._process_claim(self.store, 'e'*64, None, 1.) as claimed:
            self.assertTrue(claimed)

    def test_cached_requests_sharing_a_stripe_do_not_time_out_behind_each_other(self):
        ctx=ExecutionContext('reference');self.addCleanup(ctx.close)
        def key(record):return reuse._digest(reuse._json(record))
        first={'schema':'stripe-probe','tag':'A'};i=0
        while True:
            second={'schema':'stripe-probe','tag':'B%d'%i};i+=1
            if int(key(second)[:8],16)%16==int(key(first)[:8],16)%16:break
        started=threading.Event();release=threading.Event()
        def slow():started.set();release.wait(5);return np.zeros(4)
        def run(record,compute,timeout):
            return reuse._evaluate(self.store,record,compute,(4,),WorkBudget(1<<24),context=ctx,controller=self.control,
                                   cache_policy=ALWAYS,wait_timeout=timeout)
        with ThreadPoolExecutor(1) as pool:
            a=pool.submit(run,first,slow,5.);self.assertTrue(started.wait(3))
            try:
                start=time.monotonic()
                assert_array_equal(run(second,lambda:np.ones(4),.5),np.ones(4))
                self.assertLess(time.monotonic()-start,.5)
            finally:
                release.set()
            assert_array_equal(a.result(timeout=5),np.zeros(4))
        self.assertEqual(self.store.statistics()['snapshots'],2)

    def test_unrelated_key_does_not_wait_for_another_process_holding_its_stripe(self):
        marker=Path(self.tmp.name)/'locked'
        proc=multiprocessing.get_context('spawn').Process(target=_process_lock_probe,args=(str(self.path),str(marker)))
        proc.start()
        try:
            _await(marker.exists,10.)
            start=time.monotonic()
            with reuse._process_claim(self.store,'a'*63+'b',None,2.) as claimed:self.assertFalse(claimed)
            self.assertLess(time.monotonic()-start,1.)
            with self.assertRaises(TimeoutError):
                with reuse._process_claim(self.store,'a'*64,None,.2):pass
        finally:
            proc.terminate();proc.join(5)
        self.assertFalse(proc.is_alive())

    def test_wait_timeout_recursive_call_and_saturation(self):
        flights=reuse._Flights(max_entries=1,max_waiters=1)
        with self.assertRaises(TectonicsError):flights.run('k',lambda:flights.run('k',lambda:frozen([1.])))
        start=threading.Event();release=threading.Event()
        def hold():start.set();release.wait(3);return frozen([1.])
        with ThreadPoolExecutor(1) as pool:
            a=pool.submit(flights.run,'k',hold);start.wait(2)
            with self.assertRaises(MemoryLimitError):flights.run('other',lambda:frozen([1.]))
            with self.assertRaises(TimeoutError):flights.run('k',lambda:frozen([1.]),timeout=.02)
            release.set();a.result(timeout=3)
        self.assertEqual(flights._waiters,0)

    def test_cancellation_during_compute_publishes_nothing(self):
        cancel=threading.Event();original=reuse.half_space_temperature
        def cancel_after(*args,**kw):
            r=original(*args,**kw);cancel.set();return r
        with mock.patch.object(reuse,'half_space_temperature',side_effect=cancel_after):
            with self.assertRaises(CancelledError):cached_temperature(np.arange(64.),1.,THERMAL,store=self.store,cache_policy=ALWAYS,cancel=cancel)
        self.assertEqual(self.store.statistics()['snapshots'],0)

    def test_cancellation_during_encoding_rolls_back_candidate(self):
        cancel=threading.Event();encode=self.store._encode
        def stop(*a,**kw):
            encoded=encode(*a,**kw);cancel.set();return encoded
        with mock.patch.object(self.store,'_encode',side_effect=stop):
            with self.assertRaises(CancelledError):
                cached_temperature(np.arange(512.),1.,THERMAL,store=self.store,
                                   cache_policy=ALWAYS,cancel=cancel)
        self.assertEqual(self.store.statistics()['snapshots'],0)
        self.assertEqual(self.store.statistics()['unique_chunks'],0)

    def test_explicit_closed_context_is_not_ignored_on_auto_bypass(self):
        ctx=ExecutionContext('scipy');ctx.close()
        with self.assertRaises(TectonicsError):
            cached_temperature(np.arange(8.),1.,THERMAL,store=self.store,context=ctx)

    def test_corruption_stays_an_error(self):
        cached_temperature(np.arange(64.),1.,THERMAL,store=self.store,cache_policy=ALWAYS)
        self.store._db.execute('UPDATE chunks SET payload=?',(b'bad',))
        with self.assertRaises(StoreError):cached_temperature(np.arange(64.),1.,THERMAL,store=self.store,cache_policy=ALWAYS)

    def test_invalid_policy_context_and_timeout(self):
        for kw in ({'mode':'silent'},{'min_result_bytes':-1},{'max_result_bytes':1},{'min_compute_seconds':float('nan')}):
            with self.assertRaises(TectonicsError):CachePolicy(**kw)
        with self.assertRaises(TectonicsError):cached_temperature(np.arange(64.),1.,THERMAL,store=self.store,cache_policy=ALWAYS,context=ExecutionContext())
        with self.assertRaises(TectonicsError):cached_temperature([1.],1.,THERMAL,wait_timeout=-1)
        with self.assertRaises(TectonicsError):cached_temperature(PreparedInput([-1.]),1.,THERMAL,store=self.store,cache_policy=ALWAYS)

    def test_finite_cost_record_retention(self):
        controller=ReuseController(max_cost_records=3)
        for i in range(20):controller.cost(str(i),compute=float(i))
        self.assertEqual(controller.statistics()['cost_records'],3)
        self.assertEqual(controller.cost('0'),{})

    def test_independent_spawn_requests_share_persistent_result(self):
        with ProcessPoolExecutor(2,mp_context=multiprocessing.get_context('spawn')) as pool:
            values=list(pool.map(_process_cache,[str(self.path)]*4))
        self.assertEqual(self.store.statistics()['snapshots'],1)
        for raw,count in values:
            self.assertEqual(raw,values[0][0]);self.assertEqual(count,1)
        self.assertLessEqual(len(list(Path(self.tmp.name).glob('*.lock'))),16)

    def test_crashed_lock_owner_does_not_leave_stale_lease(self):
        marker=Path(self.tmp.name)/'locked'
        proc=multiprocessing.get_context('spawn').Process(target=_process_lock_probe,args=(str(self.path),str(marker)))
        proc.start()
        try:
            _await(marker.exists,5.)
        finally:
            proc.terminate();proc.join(5)
        self.assertFalse(proc.is_alive())
        with reuse._process_claim(self.store,'a'*64,None,1.):pass


if __name__=='__main__':unittest.main()
