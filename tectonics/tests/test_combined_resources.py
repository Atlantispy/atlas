"""Item 12: combined resource/lifetime invariants, not geological acceptance.

No timing thresholds, new physics or changed tolerance. All storage is temporary;
worker tests use spawn rather than assuming POSIX fork. Explicit tiny budgets
exercise deterministic refusal without attempting enormous allocations.
"""
from concurrent.futures import CancelledError, ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
import hashlib
import multiprocessing
import os
from pathlib import Path
import sqlite3
import tempfile
import threading
import time
import unittest
from unittest import mock

import numpy as np

from atlas_tectonics import (PeriodicFlexure, PeriodicGrid1D, FlexureParameters,
                            ThermalParameters, half_space_temperature)
from atlas_tectonics.resources import (WorkBudget, MemoryLimitError, reserve_budgets,
                                      DEFAULT_BUDGET)
from atlas_tectonics.storage import ArrayStore, StoreLimits, StoreError, Compression
from atlas_tectonics.execution import KernelExecutor, ExecutionPolicy
from atlas_tectonics import execution
from atlas_tectonics.reuse import cached_temperature, PreparedInput, CachePolicy

MIB = 1024**2
THERMAL = ThermalParameters('synthetic-item12', 'not Earth calibration', 300., 1300., 1.)
ELASTIC = FlexureParameters('synthetic-item12', 'not Earth calibration', 12., 1., 0., 1., 1.)


def key(text):
    return hashlib.sha256(text.encode()).hexdigest()


def limits(**kwargs):
    base = StoreLimits(4096, 4*MIB, 8*MIB, decoded_cache_bytes=32768,
        max_manifest_bytes=32768, max_chunks=512, staging_memory_bytes=8192,
        max_staging_bytes=8*MIB, verified_cache_entries=32, insert_batch_bytes=8192,
        sqlite_cache_bytes=65536, codec_workspace_bytes=2*MIB)
    return replace(base, **kwargs)


def bytes_equal(test, left, right):
    test.assertEqual(left.shape, right.shape)
    test.assertEqual(left.dtype, right.dtype)
    test.assertEqual(left.tobytes(), right.tobytes())


class SharedBudgetTests(unittest.TestCase):
    def test_related_budgets_charge_shared_parent_once(self):
        root=WorkBudget(100); a=WorkBudget(80,parent=root); b=WorkBudget(60,parent=root)
        with reserve_budgets(40,a,b,root,category='combined'):
            self.assertEqual(root.reserved_bytes,40)
            self.assertEqual(a.reserved_bytes,40)
            self.assertEqual(b.reserved_bytes,40)
        self.assertEqual(root.reserved_bytes,0)

    def test_refusal_is_atomic_across_siblings(self):
        root=WorkBudget(100); a=WorkBudget(20,parent=root); b=WorkBudget(100,parent=root)
        with self.assertRaises(MemoryLimitError):
            with reserve_budgets(30,a,b): pass
        self.assertEqual([x.reserved_bytes for x in (root,a,b)],[0,0,0])
        self.assertGreater(root.statistics()['refusals'],0)

    def test_nested_different_work_remains_additive(self):
        root=WorkBudget(100); child=WorkBudget(90,parent=root)
        with root.reserve(20,category='retained'):
            with child.reserve(60,category='compute'):
                self.assertEqual(root.reserved_bytes,80)
                self.assertEqual(child.available_bytes,20)
                with self.assertRaises(MemoryLimitError):
                    with child.reserve(21): pass
        self.assertEqual(root.reserved_bytes,0)
        self.assertEqual(root.peak_reserved_bytes,80)

    def test_exception_and_cancellation_release_both(self):
        root=WorkBudget(100);child=WorkBudget(100,parent=root)
        with self.assertRaises(CancelledError):
            with child.reserve(50): raise CancelledError()
        self.assertEqual(root.reserved_bytes,0)
        self.assertEqual(child.reserved_bytes,0)

    def test_concurrent_total_not_individual_limit(self):
        root=WorkBudget(100); entered=threading.Event();leave=threading.Event()
        def holder():
            with WorkBudget(100,parent=root).reserve(70):
                entered.set();self.assertTrue(leave.wait(3))
        with ThreadPoolExecutor(1) as pool:
            f=pool.submit(holder);self.assertTrue(entered.wait(3))
            try:
                with self.assertRaises(MemoryLimitError):
                    with WorkBudget(100,parent=root).reserve(40):pass
            finally:leave.set()
            f.result(3)
        self.assertEqual(root.reserved_bytes,0)

    def test_invalid_and_immutable_limits(self):
        b=WorkBudget(10)
        with self.assertRaises(AttributeError):b.max_bytes=100
        for bad in (-1,True,1.2):
            with self.assertRaises(ValueError):
                with b.reserve(bad):pass
        with self.assertRaises(ValueError):
            with b.reserve(1,category=''):pass
        with self.assertRaises(TypeError):WorkBudget(10,parent=object())

    def test_category_inventory_bounded_and_snapshot_detached(self):
        b=WorkBudget(10)
        for i in range(200):
            with b.reserve(1,category=f'category-{i}'):pass
        self.assertLessEqual(len(b.statistics()['categories']),64)
        d=b.statistics();d['categories'].clear()
        self.assertTrue(b.statistics()['categories'])


class CombinedResourcesTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        self.budget=WorkBudget(64*MIB)

    def tearDown(self):
        self.tmp.cleanup()

    def test_store_reserves_retained_capacity_until_close(self):
        before=self.budget.reserved_bytes
        with ArrayStore(self.root/'a.db',limits(),budget=self.budget) as s:
            self.assertEqual(self.budget.reserved_bytes,
                             before+s.resource_requirements()['retained_ram_allowance'])
            s.put(key('x'),{'a':np.arange(4096.)})
            s.get(key('x'))
            self.assertEqual(self.budget.reserved_bytes,
                             before+s.resource_requirements()['retained_ram_allowance'])
            self.assertLessEqual(s.statistics()['decoded_cache_bytes'],limits().decoded_cache_bytes)
        self.assertEqual(self.budget.reserved_bytes,before)

    def test_connection_capacity_failure_has_no_file_or_leak(self):
        tiny=WorkBudget(1024)
        with self.assertRaises(MemoryLimitError):ArrayStore(self.root/'small.db',limits(),budget=tiny)
        self.assertEqual(tiny.reserved_bytes,0)
        self.assertFalse((self.root/'small.db').exists())
        with mock.patch('sqlite3.connect',side_effect=OSError('synthetic open failure')):
            with self.assertRaises(OSError):ArrayStore(self.root/'fail.db',limits(),budget=self.budget)
        self.assertEqual(self.budget.reserved_bytes,0)

    def test_unrelated_database_constructor_releases_capacity(self):
        p=self.root/'other.db'
        with closing(sqlite3.connect(p)) as db, db:
            db.execute('create table other(x)')
        with self.assertRaises(StoreError):ArrayStore(p,limits(),budget=self.budget)
        self.assertEqual(self.budget.reserved_bytes,0)

    def test_storage_inflight_blocks_executor_without_spinning(self):
        # A store is already using most of the SHARED envelope. An otherwise
        # locally valid executor must refuse before copying inputs, not busy-wait.
        b=WorkBudget(2*MIB)
        with ArrayStore(self.root/'a.db',limits(),budget=b) as s:
            with b.reserve(b.available_bytes-128,category='other-work'):
                with KernelExecutor(ExecutionPolicy(mode='serial'),budget=b) as ex:
                    with mock.patch.object(execution,'snapshot',side_effect=AssertionError('copied')):
                        with self.assertRaises(MemoryLimitError):
                            list(ex.temperatures([(np.arange(128.),1.)],THERMAL))
                    self.assertEqual(ex.statistics()['reserved_bytes'],0)
        self.assertEqual(b.reserved_bytes,0)

    def test_late_global_reservation_failure_drains_pending(self):
        b=WorkBudget(8*MIB)
        with KernelExecutor(ExecutionPolicy(mode='threads',max_inflight=2,max_workers=2),budget=b) as ex:
            iterator=ex.temperatures([(np.arange(16384.),1.)]*8,THERMAL)
            next(iterator)
            with b.reserve(b.available_bytes,category='consumer'):
                iterator.close()
            self.assertEqual(ex.statistics()['reserved_bytes'],0)
        self.assertEqual(b.reserved_bytes,0)

    def test_multiple_default_components_join_same_default_budget(self):
        baseline=DEFAULT_BUDGET.reserved_bytes
        with ArrayStore(self.root/'a.db',limits()) as s, KernelExecutor() as ex:
            self.assertIs(s._budget,ex._shared_budget)
            self.assertEqual(DEFAULT_BUDGET.reserved_bytes,
                             baseline+s.resource_requirements()['retained_ram_allowance'])
        self.assertEqual(DEFAULT_BUDGET.reserved_bytes,baseline)

    def test_cache_bypass_joins_store_envelope_by_default(self):
        with ArrayStore(self.root/'a.db',limits(),budget=self.budget) as s:
            with self.budget.reserve(self.budget.available_bytes-64,category='caller-retained'):
                with self.assertRaises(MemoryLimitError):
                    cached_temperature(np.arange(256.),1.,THERMAL,store=s)
            self.assertEqual(s.statistics()['snapshots'],0)
        self.assertEqual(self.budget.reserved_bytes,0)

    def test_store_and_caller_sibling_limits_charge_parent_once(self):
        root=WorkBudget(64*MIB);a=WorkBudget(32*MIB,parent=root);b=WorkBudget(32*MIB,parent=root)
        with ArrayStore(self.root/'a.db',limits(),budget=a) as s:
            observed=[]
            def checked():observed.append(root.statistics())
            s.put(key('x'),{'a':np.arange(4096.)},budget=b,publication_check=checked)
            self.assertTrue(observed)
            self.assertEqual(b.reserved_bytes,0)
            self.assertLess(root.peak_reserved_bytes,12*MIB)
        self.assertEqual(root.reserved_bytes,0)

    def test_prepared_inputs_operator_and_pending_write_are_accounted(self):
        data=PreparedInput(np.arange(4096.))
        op=PeriodicFlexure(PeriodicGrid1D(4096,4096.),ELASTIC)
        with self.budget.reserve(data.array.nbytes+op.setup_bytes,category='caller-retained'):
            with ArrayStore(self.root/'cache.db',limits(),budget=self.budget) as s:
                observed=[];original=s._encode
                def encode(*args):
                    observed.append(self.budget.statistics())
                    return original(*args)
                with mock.patch.object(s,'_encode',side_effect=encode):
                    a=cached_temperature(data,1.,THERMAL,store=s,budget=self.budget,
                                         cache_policy=CachePolicy(mode='always'))
                self.assertTrue(any(x['categories'].get('pending-result',0)>0 for x in observed))
                self.assertTrue(any(x['categories'].get('store-stage',0)>0 for x in observed))
                b=cached_temperature(data,1.,THERMAL,store=s,budget=self.budget,
                                     cache_policy=CachePolicy(mode='always'))
                bytes_equal(self,a,b)
                bytes_equal(self,a,half_space_temperature(data.array,1.,THERMAL))
        self.assertEqual(self.budget.reserved_bytes,0)

    def test_pressure_rejects_write_before_encoding_preserves_parent(self):
        with ArrayStore(self.root/'a.db',limits(),budget=self.budget) as s:
            original=np.arange(2048.)
            s.put(key('parent'),{'a':original})
            with self.budget.reserve(self.budget.available_bytes-64,category='other-work'):
                with mock.patch.object(s,'_encode',side_effect=AssertionError('encoded')):
                    with self.assertRaises(MemoryLimitError):s.put(key('rejected'),{'a':original+1})
            self.assertFalse(s.contains(key('rejected')))
            bytes_equal(self,s.get(key('parent'))['a'],original)

    def test_streamed_manifest_charge_survives_yield_then_close(self):
        with ArrayStore(self.root/'a.db',limits(),budget=self.budget) as s:
            s.put(key('parent'),{'a':np.arange(2048.)})
            retained=self.budget.reserved_bytes
            stream=s.iter_chunks(key('parent'),'a')
            next(stream)
            self.assertGreater(self.budget.reserved_bytes,retained)
            stream.close()
            self.assertEqual(self.budget.reserved_bytes,retained)

    def test_stable_combined_compute_store_incremental_restore(self):
        op=PeriodicFlexure(PeriodicGrid1D(4096,4096.),ELASTIC)
        loads=[np.sin(np.arange(4096.)/20+i) for i in range(4)]
        with self.budget.reserve(sum(x.nbytes for x in loads)+op.setup_bytes,category='caller-retained'):
            with ArrayStore(self.root/'a.db',limits(),budget=self.budget) as s:
                with KernelExecutor(ExecutionPolicy(mode='threads',max_workers=2,max_inflight=2),budget=self.budget) as ex:
                    for i,out in enumerate(ex.flexure(loads,op)):
                        with self.budget.reserve(out.nbytes,category='consumer-output'):
                            s.put(key(str(i)),{'height':out})
                            restored=s.get(key(str(i)),budget=self.budget)['height']
                            bytes_equal(self,out,restored)
                            bytes_equal(self,out,op.solve(loads[i],budget=self.budget))
                refs=s.statistics()['unique_chunks']
                s.put_incremental(key('branch'),key('0'),{},budget=self.budget)
                self.assertEqual(s.statistics()['unique_chunks'],refs)
                s.backup_to(self.root/'independent.db')
        self.assertEqual(self.budget.reserved_bytes,0)
        with ArrayStore(self.root/'independent.db',limits(),budget=self.budget) as restored:
            bytes_equal(self,restored.get(key('branch'))['height'],op.solve(loads[0]))
        self.assertEqual(self.budget.reserved_bytes,0)

    def test_encoder_cancel_with_parallel_work_leaves_no_snapshot(self):
        cancel=threading.Event()
        with ArrayStore(self.root/'a.db',limits(),budget=self.budget) as s:
            s.put(key('old'),{'a':np.arange(32.)})
            encode=s._encode
            def stopping(*args):
                answer=encode(*args);cancel.set();return answer
            with KernelExecutor(ExecutionPolicy(mode='threads',max_workers=2),budget=self.budget) as ex:
                it=ex.temperatures([(np.arange(16384.),1.)]*4,THERMAL)
                out=next(it)
                with mock.patch.object(s,'_encode',side_effect=stopping):
                    with self.assertRaises(CancelledError):s.put(key('new'),{'a':out},cancel=cancel)
                it.close()
                self.assertEqual(ex.statistics()['reserved_bytes'],0)
            self.assertFalse(s.contains(key('new')))
            bytes_equal(self,s.get(key('old'))['a'],np.arange(32.))
        self.assertEqual(self.budget.reserved_bytes,0)

    def test_active_preparation_cannot_release_connection_capacity(self):
        entered=threading.Event();leave=threading.Event()
        with ArrayStore(self.root/'a.db',limits(),budget=self.budget) as s:
            encode=s._encode
            def blocked(*args):
                entered.set()
                if not leave.wait(3):raise TimeoutError('test sync')
                return encode(*args)
            with mock.patch.object(s,'_encode',side_effect=blocked),ThreadPoolExecutor(1) as pool:
                f=pool.submit(s.put,key('x'),{'a':np.arange(128.)})
                self.assertTrue(entered.wait(3))
                try:
                    with self.assertRaises(StoreError):s.close()
                    self.assertGreater(self.budget.reserved_bytes,0)
                finally:leave.set()
                f.result(3)
        self.assertEqual(self.budget.reserved_bytes,0)

    def test_corruption_and_changed_input_after_parallel_population(self):
        with ArrayStore(self.root/'a.db',limits(),budget=self.budget) as s:
            a=cached_temperature(np.arange(512.),1.,THERMAL,store=s,budget=self.budget,cache_policy=CachePolicy(mode='always'))
            b=cached_temperature(np.arange(512.),2.,THERMAL,store=s,budget=self.budget,cache_policy=CachePolicy(mode='always'))
            self.assertFalse(np.array_equal(a,b))
            self.assertEqual(s.statistics()['snapshots'],2)
            with closing(sqlite3.connect(s.path)) as db, db:
                db.execute('UPDATE chunks SET payload=? WHERE id=(SELECT id FROM chunks LIMIT 1)',(b'broken',))
            with self.assertRaises(StoreError):
                for row in s._db.execute('SELECT id FROM snapshots').fetchall():s.get(row[0])
        self.assertEqual(self.budget.reserved_bytes,0)

    def test_initially_cancelled_stream_does_not_stick_active(self):
        with KernelExecutor(budget=self.budget) as ex:
            stream=ex.temperatures([(np.arange(8.),1.)],THERMAL)
            ex.cancel()
            with self.assertRaises(CancelledError):next(stream)
            self.assertFalse(ex._active)
        self.assertEqual(self.budget.reserved_bytes,0)

    def test_spawn_process_allowance_released_on_shutdown(self):
        b=WorkBudget(160*MIB)
        with KernelExecutor(ExecutionPolicy(mode='processes',max_workers=1),budget=b) as ex:
            values=list(ex.temperatures([(np.arange(64.),1.)]*2,THERMAL))
            # max_workers=1 intentionally stays serial; exercise explicit two-worker
            # process route with a small, explicitly selected baseline allowance.
        with KernelExecutor(ExecutionPolicy(mode='processes',max_workers=2,
                            process_baseline_bytes=48*MIB),budget=b) as ex:
            values=list(ex.temperatures([(np.arange(64.),1.)]*2,THERMAL))
            self.assertEqual(ex.statistics()['process_allowance_bytes'],96*MIB)
            self.assertGreaterEqual(b.reserved_bytes,96*MIB)
        self.assertEqual(b.reserved_bytes,0)
        bytes_equal(self,values[0],half_space_temperature(np.arange(64.),1.,THERMAL))

    def test_failed_pool_creation_releases_slots_and_memory(self):
        before=execution._POOL_SLOTS
        with KernelExecutor(ExecutionPolicy(mode='processes',max_workers=2,
                            process_baseline_bytes=MIB),budget=self.budget) as ex:
            with mock.patch.object(execution,'ProcessPoolExecutor',side_effect=RuntimeError('no pool')):
                with self.assertRaises(RuntimeError):list(ex.temperatures([(np.arange(8.),1.)],THERMAL))
            self.assertEqual(ex.statistics()['reserved_bytes'],0)
            self.assertEqual(execution._POOL_SLOTS,before)
        self.assertEqual(self.budget.reserved_bytes,0)

    def test_combined_cpu_slots_refuse_second_pool(self):
        function='process_cpu_count' if hasattr(os,'process_cpu_count') else 'cpu_count'
        with mock.patch.object(os,function,return_value=2):
            with KernelExecutor(ExecutionPolicy(mode='threads',max_workers=2),budget=self.budget) as first:
                list(first.temperatures([(np.arange(8.),1.)],THERMAL))
                with KernelExecutor(ExecutionPolicy(mode='threads',max_workers=2),budget=self.budget) as second:
                    with self.assertRaisesRegex(ValueError,'CPU slots'):
                        list(second.temperatures([(np.arange(8.),1.)],THERMAL))
        self.assertEqual(execution._POOL_SLOTS,0)
        self.assertEqual(self.budget.reserved_bytes,0)


if __name__=='__main__':unittest.main()
