"""R4.3 admission, reuse, real nonlinear refusal and exact persistence contracts.
SPDX-License-Identifier: AGPL-3.0-only
"""
from concurrent.futures import ThreadPoolExecutor,CancelledError
from dataclasses import replace
from pathlib import Path
import tempfile
import threading
import unittest
from unittest import mock
import numpy as np
from atlas_tectonics import (PreparedVariableStokes2D,VariableStokesSolution,NonlinearStokesPolicy,
    save_variable_stokes_solution,load_variable_stokes_solution,TectonicsError)
from atlas_tectonics.resources import WorkBudget,MemoryLimitError
from atlas_tectonics.storage import ArrayStore,StoreLimits
from atlas_tectonics import variable_stokes as vs, variable_stokes_execution as ve,reuse
from variable_stokes_fixtures import *

class CountedCancel:
    def __init__(self,n):self.n=n;self.count=0
    def is_set(self):self.count+=1;return self.count>=self.n


class Execution(unittest.TestCase):
    def setUp(self):self.b=unit_box(6);self.a=analytic_variable(self.b)
    def plan(self,**kw):return PreparedVariableStokes2D(self.b,unit_scales(),**kw)
    def solve(self,p,**kw):return p.solve(*self.a[:4],**request(self.b),**kw)
    def test_exact_factor_reuse_without_hidden_result_change(self):
        with self.plan() as p:
            a=self.solve(p);stats=p.statistics();b=self.solve(p)
            self.assertEqual(p.statistics()['factor_builds'],stats['factor_builds'])
            self.assertEqual(p.statistics()['factor_reuses'],stats['factor_reuses']+1)
            self.assertEqual(a.result_id,b.result_id)
    def test_changed_eta_rebuilds_numeric_factor_not_derivatives(self):
        with self.plan() as p:
            self.solve(p);builds=p.statistics()['factor_builds'];bx=p._op.bx
            c=self.a[2].copy();c[0,0]*=2
            p.solve(self.a[0],self.a[1],c,self.a[3],**request(self.b))
            self.assertEqual(p.statistics()['factor_builds'],builds+1)
            self.assertIs(p._op.bx,bx)
    def test_changed_force_reuses_unchanged_coefficient_factor(self):
        with self.plan() as p:
            a=self.solve(p);b=p.solve(2*self.a[0],self.a[1],*self.a[2:4],**request(self.b))
            self.assertEqual(p.statistics()['factor_builds'],1);self.assertNotEqual(a.result_id,b.result_id)
    def test_work_history_does_not_enter_snapshot_identity(self):
        with self.plan() as p:
            a=self.solve(p);p.solve(self.a[0]*2,self.a[1],*self.a[2:4],**request(self.b));b=self.solve(p)
        self.assertEqual(a.result_id,b.result_id)
    def test_source_time_epoch_affect_identity(self):
        with self.plan() as p:
            a=self.solve(p);rq=request(self.b);rq.update(time_s=1.)
            b=p.solve(*self.a[:4],**rq);rq['epoch_id']='different-epoch';c=p.solve(*self.a[:4],**rq)
        self.assertNotEqual(a.result_id,b.result_id);self.assertNotEqual(b.result_id,c.result_id)
    def test_caller_arrays_detached(self):
        with self.plan() as p:r=self.solve(p)
        before=r.array('viscosity_cell_pa_s').copy();self.a[2][:]=99
        np.testing.assert_array_equal(r.array('viscosity_cell_pa_s'),before)
    def test_result_shapes_and_metadata_private(self):
        with self.plan() as p:r=self.solve(p)
        a=r.array('u_m_s');a.shape=(a.size,)
        self.assertEqual(r.array('u_m_s').shape,(6,7))
        d=r.descriptor();d['diagnostics']['momentum_linf']=999
        self.assertLess(r.descriptor()['diagnostics']['momentum_linf'],1e-9)
    def test_all_result_arrays_immutable(self):
        with self.plan() as p:r=self.solve(p)
        for k in r.array_names:
            with self.subTest(k=k),self.assertRaises(ValueError):r.array(k).setflags(write=True)
    def test_plan_bindings_immutable(self):
        with self.plan() as p:
            for k in ('box','scales','policy','identity','budget'):
                with self.subTest(k=k),self.assertRaises(TectonicsError):setattr(p,k,None)
    def test_result_id_immutable(self):
        with self.plan() as p:r=self.solve(p)
        with self.assertRaises(TectonicsError):r.result_id='a'*64
    def test_retained_admission_released(self):
        b=WorkBudget(64<<20)
        with self.plan(budget=b) as p:self.solve(p);self.assertEqual(b.reserved_bytes,p.statistics()['retained_admitted_bytes'])
        self.assertEqual(b.reserved_bytes,0)
    def test_initial_admission_before_native_preparation(self):
        b=WorkBudget(1)
        with mock.patch.object(ve,'_StressMACOperator',side_effect=AssertionError):
            with self.assertRaises(MemoryLimitError):self.plan(budget=b)
        self.assertEqual(b.reserved_bytes,0)
    def test_scratch_refusal_releases_without_destroying_plan(self):
        pol=NonlinearStokesPolicy();held=6*1024**2+(768*self.b.nx*self.b.nz+8)+int((640+640*pol.ilu_fill_factor)*self.b.unknowns)
        template_build=4096*self.b.nx*self.b.nz+65536
        b=WorkBudget(held+template_build+100)
        with self.plan(budget=b) as p:
            with self.assertRaises(MemoryLimitError):self.solve(p)
            self.assertEqual(b.reserved_bytes,held)
        self.assertEqual(b.reserved_bytes,0)
    def test_setup_failure_releases(self):
        b=WorkBudget(64<<20)
        with mock.patch.object(ve,'ExecutionContext',side_effect=TectonicsError('injected')):
            with self.assertRaises(TectonicsError):self.plan(budget=b)
        self.assertEqual(b.reserved_bytes,0)
    def test_factor_failure_no_fallback_and_reusable(self):
        b=WorkBudget(64<<20)
        with mock.patch.object(ve,'spilu',side_effect=RuntimeError('injected')):
            with self.plan(budget=b) as p:
                with self.assertRaisesRegex(TectonicsError,'no direct fallback'):self.solve(p)
                self.assertIsNone(p._factor_key)
        self.assertEqual(b.reserved_bytes,0)
    def test_cancel_mid_iteration_releases_then_reuses(self):
        b=WorkBudget(64<<20)
        with self.plan(budget=b) as p:
            held=b.reserved_bytes
            with self.assertRaises(CancelledError):self.solve(p,cancel=CountedCancel(9))
            self.assertEqual(b.reserved_bytes,held);self.solve(p)
        self.assertEqual(b.reserved_bytes,0)
    def test_pre_cancelled_setup_releases(self):
        b=WorkBudget(64<<20);e=threading.Event();e.set()
        with self.assertRaises(CancelledError):self.plan(budget=b,cancel=e)
        self.assertEqual(b.reserved_bytes,0)
    def test_wrong_thread_driving_or_close_refused(self):
        with self.plan() as p:
            with ThreadPoolExecutor(1) as pool:
                with self.assertRaises(TectonicsError):pool.submit(self.solve,p).result()
                with self.assertRaises(TectonicsError):pool.submit(p.close).result()
            self.solve(p)
    def test_active_close_refused(self):
        with self.plan() as p:
            with p._operation(None):
                with self.assertRaises(TectonicsError):p.close()
    def test_closed_plan_and_double_close(self):
        p=self.plan();p.close();p.close()
        with self.assertRaises(TectonicsError):self.solve(p)
    def test_loaded_operator_mutation_is_checked(self):
        with self.plan() as p:
            with mock.patch.object(vs._StressMACOperator,'velocity',lambda *a:None):
                with self.assertRaises(TectonicsError):self.solve(p)
    def test_loaded_solver_alias_mutation_is_checked(self):
        with self.plan() as p:
            with mock.patch.object(ve,'gmres',lambda *a:None):
                with self.assertRaises(TectonicsError):self.solve(p)
    def test_source_membership_drift_refused(self):
        with self.plan() as p:
            orig=reuse._source_bytes
            def drift():d=orig();d['unknown.py']=b'new';return d
            with mock.patch.object(reuse,'_source_bytes',drift):
                with self.assertRaises(TectonicsError):self.solve(p)
    def test_unknowns_limit_checked(self):
        with self.assertRaises(TectonicsError):self.plan(policy=NonlinearStokesPolicy(max_unknowns=3))
        with self.assertRaises(TectonicsError):self.plan(policy=NonlinearStokesPolicy(method='direct',direct_max_unknowns=3))
    def test_invalid_policies_refused(self):
        for k,v in (('method','minres'),('restart',True),('max_cycles',0),('relaxation',0),('linear_rtol',np.nan),('ilu_fill_factor',.1)):
            with self.subTest(k=k),self.assertRaises(TectonicsError):NonlinearStokesPolicy(**{k:v})
    def test_bad_frames_shapes_and_nonfinite_inputs(self):
        with self.plan() as p:
            rq=request(self.b);rq['frame_id']='other'
            with self.assertRaises(TectonicsError):p.solve(*self.a[:4],**rq)
            with self.assertRaises(TectonicsError):p.solve(self.a[0],self.a[1],np.ones((3,3)),self.a[3],**request(self.b))
            for v in (0.,-1.,np.nan,np.inf):
                c=self.a[2].copy();c[0,0]=v
                with self.subTest(v=v),self.assertRaises(TectonicsError):p.solve(*self.a[:2],c,self.a[3],**request(self.b))
    def test_viscosity_contrast_not_silently_capped(self):
        with self.plan(policy=NonlinearStokesPolicy(max_viscosity_contrast=2)) as p:
            with self.assertRaisesRegex(TectonicsError,'contrast'):self.solve(p)
    def test_source_and_native_dependencies_retained(self):
        for k in ('variable_stokes','variable_stokes_execution'):self.assertIn(k,reuse._IDENTITY_MODULES)
        for k in ('scipy_superlu','scipy_fft'):self.assertIn(k,reuse._runtime_record('scipy')['binaries'])
    def test_extreme_publication_rejects_wrong_returned_answer(self):
        b=unit_box(2);small=np.nextafter(0.,1.)
        with PreparedVariableStokes2D(b,unit_scales()) as p:
            f=20*small
            with self.assertRaises(TectonicsError):
                p.solve(f*np.array([[1.],[-1.]]),f*np.array([[-1.,1.]]),np.ones((2,2)),np.ones((1,1)),**request(b))
    def test_constant_rheology_result_identity_repeatable(self):
        b,sc,fx,fz,T,p=forcing(6)
        with PreparedVariableStokes2D(b,sc) as s:
            a=s.solve_rheology(fx,fz,T,p,**request(b));c=s.solve_rheology(fx,fz,T,p,**request(b))
        self.assertEqual(a.result_id,c.result_id)


class Persistence(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'variable.sqlite'
        b,sc,fx,fz,T,p=forcing(5)
        with PreparedVariableStokes2D(b,sc) as s:self.r=s.solve_rheology(fx,fz,T,p,**request(b))
    def tearDown(self):self.tmp.cleanup()
    def store(self):return ArrayStore(self.path,StoreLimits(4096,8<<20,32<<20))
    def test_exact_reopen_roundtrip(self):
        with self.store() as s:save_variable_stokes_solution(self.r,s)
        with self.store() as s:r=load_variable_stokes_solution(s,self.r.result_id)
        self.assertEqual(r.descriptor(),self.r.descriptor())
        for k in r.array_names:np.testing.assert_array_equal(r.array(k),self.r.array(k))
    def test_duplicate_adds_no_chunks(self):
        with self.store() as s:
            save_variable_stokes_solution(self.r,s);before=s.statistics()['unique_chunks']
            save_variable_stokes_solution(self.r,s);self.assertEqual(s.statistics()['unique_chunks'],before)
    def test_cancelled_save_publishes_nothing(self):
        e=threading.Event();e.set()
        with self.store() as s:
            with self.assertRaises(CancelledError):save_variable_stokes_solution(self.r,s,cancel=e)
            self.assertEqual(s.statistics()['snapshots'],0)
    def test_corrupt_diagnostic_rejected(self):
        d=self.r.descriptor();d['diagnostics']['momentum_linf']=1
        with self.assertRaises(TectonicsError):VariableStokesSolution(d,{k:self.r.array(k) for k in self.r.array_names})
    def test_lagged_unconverged_history_rejected(self):
        d=self.r.descriptor();d['nonlinear_history'][-1]['viscosity_log_change']=1
        with self.assertRaises(TectonicsError):VariableStokesSolution(d,{k:self.r.array(k) for k in self.r.array_names})
    def test_unknown_snapshot_refused(self):
        with self.store() as s:
            with self.assertRaises(TectonicsError):load_variable_stokes_solution(s,'0'*64)
    def test_missing_array_refused(self):
        a={k:self.r.array(k) for k in self.r.array_names};del a['temperature_k']
        with self.assertRaises(TectonicsError):VariableStokesSolution(self.r.descriptor(),a)

class SourceIdentityRegression(unittest.TestCase):
    def test_holding_profile_constants_does_not_change_execution_identity(self):
        from atlas_tectonics import reference_rheology
        with reuse.ExecutionContext('scipy') as a:first=a.identity
        held=[reference_rheology(k) for k in ('constant','tosi-1','tosi-2','bf23-memory')]
        with reuse.ExecutionContext('scipy') as b:second=b.identity
        self.assertEqual(first,second);self.assertEqual(len(held),4)
    def test_actual_loaded_instruction_changes_still_invalidate(self):
        import atlas_tectonics.constitutive as c
        with reuse.ExecutionContext('scipy') as ctx:
            old=c.reference_rheology.__code__
            try:
                c.reference_rheology.__code__=(lambda name:None).__code__
                with self.assertRaises(TectonicsError):ctx.verify()
            finally:c.reference_rheology.__code__=old
            ctx.verify()
    def test_new_aliases_registered_for_source_verification(self):
        sigs,_,_=reuse._callable_inventory('scipy')
        for k in ('gmres','spilu','_native_law'):
            self.assertIn('atlas_tectonics.variable_stokes_execution.'+k,sigs)
