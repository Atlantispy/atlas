"""Items 6-8: bounded concurrency, byte-verified reuse, and admission contracts.

Synthetic arrays, local temporary stores only. No performance thresholds, changed
physical tolerances, historical rebindings, network calls or installation.
"""
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor, CancelledError
from dataclasses import replace
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
from atlas_tectonics.resources import MemoryLimitError
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


class IdentityTests(unittest.TestCase):
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
