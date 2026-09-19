"""R4.1 ownership, source checks, admission, cancellation and steady snapshots.
SPDX-License-Identifier: AGPL-3.0-only
"""
from concurrent.futures import ThreadPoolExecutor,CancelledError
from dataclasses import replace,FrozenInstanceError
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock
import numpy as np
from numpy.testing import assert_array_equal
from atlas_tectonics import (PreparedStokes2D,StokesSolvePolicy,StokesSolution,
    reference_rheology,save_stokes_solution,load_stokes_solution,TectonicsError)
from atlas_tectonics.resources import WorkBudget,MemoryLimitError
from atlas_tectonics.storage import ArrayStore,StoreLimits
from atlas_tectonics import reuse,stokes,stokes_execution
from stokes_fixtures import unit_box,unit_scales,request,analytic
ROOT=Path(__file__).resolve().parents[1]


class CountedCancel:
    def __init__(self,n):self.n=n;self.count=0
    def is_set(self):self.count+=1;return self.count>=self.n


class PreparedExecutionTests(unittest.TestCase):
    def setUp(self):self.box=unit_box(8);self.f=analytic(self.box)[:2]
    def plan(self,**kw):return PreparedStokes2D(self.box,reference_rheology('constant'),unit_scales(),**kw)
    def solve(self,p,**kw):return p.solve(*self.f,**request(self.box),**kw)
    def test_repeated_prepared_solve_has_exact_result_identity(self):
        with self.plan() as p:a=self.solve(p);b=self.solve(p)
        self.assertEqual(a.result_id,b.result_id)
        for name in a.array_names:assert_array_equal(a.array(name),b.array(name))
    def test_changed_force_has_new_result_identity(self):
        with self.plan() as p:
            a=self.solve(p);b=p.solve(self.f[0]*2,self.f[1],**request(self.box))
        self.assertNotEqual(a.result_id,b.result_id)
    def test_time_and_provenance_enter_result_identity(self):
        with self.plan() as p:
            a=self.solve(p)
            rq=request(self.box);rq['time_s']=10.
            b=p.solve(*self.f,**rq)
            rq['source']='separate author';c=p.solve(*self.f,**rq)
        self.assertNotEqual(a.result_id,b.result_id);self.assertNotEqual(b.result_id,c.result_id)
    def test_grid_and_viscosity_enter_plan_identity(self):
        with self.plan() as a,PreparedStokes2D(unit_box(8,width=2.),reference_rheology('constant'),unit_scales()) as b:
            self.assertNotEqual(a.identity,b.identity)
        p=replace(reference_rheology('constant'),parameters=(('eta',2.),))
        with self.plan() as a,PreparedStokes2D(self.box,p,unit_scales()) as b:self.assertNotEqual(a.identity,b.identity)
    def test_solver_policy_enters_record(self):
        with self.plan() as a,self.plan(policy=StokesSolvePolicy(method='direct')) as b:
            self.assertNotEqual(a.identity,b.identity)
            self.assertEqual(self.solve(b).descriptor()['policy']['method'],'direct')
    def test_plan_public_bindings_immutable(self):
        with self.plan() as p:
            for key in ('box','profile','scales','policy','budget','identity'):
                with self.subTest(key=key),self.assertRaises(TectonicsError):setattr(p,key,None)
    def test_result_bindings_immutable(self):
        with self.plan() as p:r=self.solve(p)
        with self.assertRaises(TectonicsError):r.result_id='0'*64
    def test_result_array_backing_is_immutable(self):
        with self.plan() as p:r=self.solve(p)
        for key in r.array_names:
            with self.subTest(key=key),self.assertRaises(ValueError):r.array(key).setflags(write=True)
    def test_result_shapes_are_private_descriptors(self):
        with self.plan() as p:r=self.solve(p)
        v=r.array('u_m_s');shape=v.shape;v.shape=(v.size,)
        self.assertEqual(r.array('u_m_s').shape,shape)
    def test_caller_mutation_cannot_change_stored_force(self):
        with self.plan() as p:r=self.solve(p)
        expected=self.f[0].copy();self.f[0][:]=999.
        assert_array_equal(r.array('force_x_n_m3'),expected)
    def test_descriptor_is_detached(self):
        with self.plan() as p:r=self.solve(p)
        d=r.descriptor();d['box']['nx']=100
        self.assertEqual(r.descriptor()['box']['nx'],8)
    def test_unknown_array_refused(self):
        with self.plan() as p:r=self.solve(p)
        with self.assertRaises(TectonicsError):r.array('temperature')
    def test_bad_frame_and_epoch_refused(self):
        with self.plan() as p:
            rq=request(self.box);rq['frame_id']='wrong'
            with self.assertRaises(TectonicsError):p.solve(*self.f,**rq)
            rq=request(self.box);rq['epoch_id']=''
            with self.assertRaises(TectonicsError):p.solve(*self.f,**rq)
    def test_bad_force_shapes_refused(self):
        with self.plan() as p:
            with self.assertRaises(TectonicsError):p.solve(np.zeros((8,8)),self.f[1],**request(self.box))
    def test_bad_force_values_refused(self):
        with self.plan() as p:
            for val in (np.nan,np.inf):
                f=self.f[0].copy();f[0,0]=val
                with self.assertRaises(TectonicsError):p.solve(f,self.f[1],**request(self.box))
    def test_masks_and_boolean_forces_refused(self):
        with self.plan() as p:
            for f in (np.ma.array(self.f[0]),self.f[0]>0):
                with self.assertRaises(TectonicsError):p.solve(f,self.f[1],**request(self.box))
    def test_construction_memory_refusal_leaves_no_reservation(self):
        b=WorkBudget(1)
        with self.assertRaises(MemoryLimitError):self.plan(budget=b)
        self.assertEqual(b.reserved_bytes,0)
    def test_solve_memory_refusal_does_not_destroy_preparation(self):
        held=5*1024**2+160*self.box.unknowns;b=WorkBudget(held+1024)
        with self.plan(budget=b) as p:
            with self.assertRaises(MemoryLimitError):self.solve(p)
            self.assertEqual(b.reserved_bytes,held)
        self.assertEqual(b.reserved_bytes,0)
    def test_preparation_failure_releases_admission(self):
        b=WorkBudget(16<<20)
        with mock.patch.object(stokes_execution,'ExecutionContext',side_effect=TectonicsError('injected')):
            with self.assertRaises(TectonicsError):self.plan(budget=b)
        self.assertEqual(b.reserved_bytes,0)
    def test_sparse_factorisation_failure_releases_admission(self):
        b=WorkBudget(64<<20)
        with mock.patch.object(stokes_execution,'splu',side_effect=RuntimeError('factor failure')):
            with self.assertRaises(RuntimeError):self.plan(budget=b,policy=StokesSolvePolicy(method='direct'))
        self.assertEqual(b.reserved_bytes,0)
    def test_work_count_and_direct_limits_refused_before_solving(self):
        with self.assertRaises(TectonicsError):self.plan(policy=StokesSolvePolicy(max_unknowns=2))
        with self.assertRaises(TectonicsError):self.plan(policy=StokesSolvePolicy(method='direct',direct_max_unknowns=2))
    def test_solve_cancellation_drains_and_plan_remains_reusable(self):
        b=WorkBudget(32<<20)
        with self.plan(budget=b) as p:
            held=b.reserved_bytes
            with self.assertRaises(CancelledError):self.solve(p,cancel=CountedCancel(6))
            self.assertEqual(b.reserved_bytes,held)
            r=self.solve(p);self.assertLess(r.descriptor()['diagnostics']['momentum_linf'],1e-10)
        self.assertEqual(b.reserved_bytes,0)
    def test_pre_cancelled_preparation_releases_admission(self):
        b=WorkBudget(32<<20);event=threading.Event();event.set()
        with self.assertRaises(CancelledError):self.plan(budget=b,cancel=event)
        self.assertEqual(b.reserved_bytes,0)
    def test_pre_cancelled_request_allocates_no_work(self):
        with self.plan() as p:
            event=threading.Event();event.set()
            with self.assertRaises(CancelledError):self.solve(p,cancel=event)
    def test_closed_plan_refused_and_double_close_safe(self):
        p=self.plan();p.close();p.close()
        with self.assertRaises(TectonicsError):self.solve(p)
    def test_close_while_active_refused(self):
        with self.plan() as p:
            with p._operation(None):
                with self.assertRaises(TectonicsError):p.close()
            self.solve(p)
    def test_wrong_driver_thread_refused_not_fake_parallel_tiling(self):
        with self.plan() as p:
            with ThreadPoolExecutor(max_workers=1) as e:
                with self.assertRaises(TectonicsError):e.submit(self.solve,p).result()
            self.solve(p)
    def test_retained_admission_released_after_normal_close(self):
        b=WorkBudget(32<<20)
        with self.plan(budget=b) as p:
            self.solve(p);self.assertEqual(b.reserved_bytes,p.retained_bytes_estimate)
        self.assertEqual(b.reserved_bytes,0)
    def test_loaded_operator_mutation_detected(self):
        with self.plan() as p:
            with mock.patch.object(stokes._MACOperator,'matvec',lambda s,x:x):
                with self.assertRaisesRegex(TectonicsError,'changed'):self.solve(p)
    def test_loaded_minres_alias_mutation_detected(self):
        with self.plan() as p:
            with mock.patch.object(stokes_execution,'minres',lambda *a,**k:None):
                with self.assertRaisesRegex(TectonicsError,'changed'):self.solve(p)
    def test_scientific_constant_mutation_detected(self):
        with self.plan() as p:
            with mock.patch.object(stokes,'_BOUNDARY','no-slip'):
                with self.assertRaisesRegex(TectonicsError,'changed'):self.solve(p)
    def test_source_membership_mutation_detected(self):
        with self.plan() as p:
            original=reuse._source_bytes
            def other():
                x=original();x['unexpected.py']=b'changed';return x
            with mock.patch.object(reuse,'_source_bytes',other):
                with self.assertRaises(TectonicsError):self.solve(p)
    def test_context_includes_new_modules_and_native_backends(self):
        for n in ('stokes','stokes_execution'):self.assertIn(n,reuse._IDENTITY_MODULES)
        r=reuse._runtime_record('scipy')['binaries']
        self.assertIn('scipy_superlu',r);self.assertIn('scipy_fft',r)
    def test_invalid_policy_cannot_hide_failure(self):
        for kwargs in ({'method':'fallback'},{'max_iterations':0},{'momentum_tolerance':np.inf},
                       {'divergence_tolerance':-1.},{'krylov_rtol':True}):
            with self.subTest(kwargs=kwargs),self.assertRaises(TectonicsError):StokesSolvePolicy(**kwargs)
    def test_independent_residual_rejects_a_fabricated_zero_solver(self):
        # Patch before preparation so source identity registers this explicit test
        # implementation. A claimed info=0 cannot bypass the equation residual.
        with mock.patch.object(stokes_execution,'minres',lambda A,b,**kw:(np.zeros_like(b),0)):
            with self.plan() as p:
                with self.assertRaisesRegex(TectonicsError,'residual'):self.solve(p)
    def test_numpy_only_reference_import_still_works(self):
        code=f'''import sys
sys.path.insert(0,{str(ROOT/'src')!r})
sys.modules['scipy']=None
import atlas_tectonics
from atlas_tectonics import StokesBox2D,PreparedStokes2D,DiffusiveScales,reference_rheology,TectonicsError
try:
 PreparedStokes2D(StokesBox2D(2,2,1.,1.,'x'),reference_rheology('constant'),DiffusiveScales('u',1.,1.,1.,1.,1.,1.))
except TectonicsError as e:
 assert 'unavailable' in str(e)
else: raise AssertionError('missing solver should fail')
'''
        r=subprocess.run([sys.executable,'-I','-B','-c',code],capture_output=True,text=True,timeout=30)
        self.assertEqual(r.returncode,0,r.stderr)


class SteadySnapshotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.box=unit_box(8)
        with PreparedStokes2D(cls.box,reference_rheology('constant'),unit_scales()) as p:
            cls.result=p.solve(*analytic(cls.box)[:2],**request(cls.box))
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.budget=WorkBudget(64<<20)
        self.store=ArrayStore(Path(self.temp.name)/'steady.db',StoreLimits(1024,4<<20,16<<20),budget=self.budget)
    def tearDown(self):self.store.close();self.temp.cleanup()
    def test_self_contained_exact_restore(self):
        save_stokes_solution(self.result,self.store)
        r=load_stokes_solution(self.store,self.result.result_id)
        self.assertEqual(r.result_id,self.result.result_id)
        self.assertEqual(r.descriptor(),self.result.descriptor())
        for name in r.array_names:assert_array_equal(r.array(name),self.result.array(name))
    def test_duplicate_write_adds_no_chunks(self):
        save_stokes_solution(self.result,self.store);n=self.store.statistics()['unique_chunks']
        save_stokes_solution(self.result,self.store)
        self.assertEqual(self.store.statistics()['unique_chunks'],n)
    def test_cold_restore_after_store_reopen(self):
        save_stokes_solution(self.result,self.store);self.store.close()
        self.store=ArrayStore(Path(self.temp.name)/'steady.db',StoreLimits(1024,4<<20,16<<20),budget=self.budget)
        self.assertEqual(load_stokes_solution(self.store,self.result.result_id).result_id,self.result.result_id)
    def test_cancelled_save_does_not_publish(self):
        e=threading.Event();e.set()
        with self.assertRaises(CancelledError):save_stokes_solution(self.result,self.store,cancel=e)
        self.assertEqual(self.store.statistics()['snapshots'],0)
    def test_restore_budget_refusal_keeps_store(self):
        save_stokes_solution(self.result,self.store)
        with self.assertRaises(MemoryLimitError):load_stokes_solution(self.store,self.result.result_id,budget=WorkBudget(1))
        self.assertEqual(load_stokes_solution(self.store,self.result.result_id).result_id,self.result.result_id)
    def test_changed_array_cannot_match_original_record_hash(self):
        d=self.result.descriptor();a={k:self.result.array(k).copy() for k in self.result.array_names}
        a['pressure_pa'][0,0]+=1.
        r=StokesSolution(d,a);self.assertNotEqual(r.result_id,self.result.result_id)
    def test_unknown_schema_and_false_completion_claim_refused(self):
        a={k:self.result.array(k) for k in self.result.array_names}
        for key,value in (('schema','other'),('R4_complete',True),('physical_validation',True),('units','nondimensional')):
            d=self.result.descriptor();d[key]=value
            with self.subTest(key=key),self.assertRaises(TectonicsError):StokesSolution(d,a)
    def test_missing_or_wrong_shaped_arrays_refused(self):
        a={k:self.result.array(k) for k in self.result.array_names};a.pop('divergence_s_1')
        with self.assertRaises(TectonicsError):StokesSolution(self.result.descriptor(),a)
    def test_nonzero_normal_wall_on_restore_refused(self):
        a={k:self.result.array(k).copy() for k in self.result.array_names};a['u_m_s'][0,0]=1.
        with self.assertRaises(TectonicsError):StokesSolution(self.result.descriptor(),a)
    def test_recorded_failed_residual_refused(self):
        a={k:self.result.array(k) for k in self.result.array_names};d=self.result.descriptor();d['diagnostics']['momentum_linf']=1.
        with self.assertRaises(TectonicsError):StokesSolution(d,a)
    def test_unknown_and_malformed_snapshot_id_refused(self):
        for identifier in ('x','0'*64):
            with self.subTest(id=identifier),self.assertRaises(TectonicsError):load_stokes_solution(self.store,identifier)
    def test_restoration_does_not_call_or_rebind_solver(self):
        save_stokes_solution(self.result,self.store)
        with mock.patch.object(PreparedStokes2D,'solve',side_effect=AssertionError('must not solve')):
            r=load_stokes_solution(self.store,self.result.result_id)
        self.assertEqual(r.descriptor()['context_id'],self.result.descriptor()['context_id'])


if __name__=='__main__':unittest.main()
