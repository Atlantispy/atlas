"""R4.2 state, source, memory, restart and atomic failure contracts.
SPDX-License-Identifier: AGPL-3.0-only
"""
from concurrent.futures import ThreadPoolExecutor,CancelledError
from dataclasses import replace,FrozenInstanceError
import hashlib,json,os,sys,tempfile,threading,subprocess
from pathlib import Path
import unittest
from unittest import mock
import numpy as np
from numpy.testing import assert_array_equal,assert_allclose
from atlas_tectonics import (ThermalBoundary2D,ThermochemicalProblem,ThermochemicalPolicy,
    ThermochemicalState,PreparedThermochemical2D,PrescribedMACVelocity,ThermochemicalStep,
    save_thermochemical_state,load_thermochemical_state,TectonicsError,reference_rheology)
from atlas_tectonics.resources import WorkBudget,MemoryLimitError
from atlas_tectonics.storage import ArrayStore,StoreLimits
from atlas_tectonics import thermochemical,thermochemical_execution as tx
from thermochemical_fixtures import problem,initial,rest,circulation
ROOT=Path(__file__).resolve().parents[1]


class Contracts(unittest.TestCase):
    def test_boundary_choices_not_invented(self):
        for kind in ('periodic','free-surface','fixed-top',None):
            with self.subTest(kind=kind),self.assertRaises(TectonicsError):ThermalBoundary2D(kind)
    def test_fixed_wall_values_required(self):
        for value in (None,0.,-1.,np.inf,np.nan,True):
            with self.subTest(value=value),self.assertRaises(TectonicsError):ThermalBoundary2D('fixed-top-bottom',value,300.)
    def test_insulation_has_no_hidden_temperature(self):
        with self.assertRaises(TectonicsError):ThermalBoundary2D('insulated',300.,300.)
    def test_wall_temperature_in_material_envelope(self):
        with self.assertRaises(TectonicsError):replace(problem(),boundary=ThermalBoundary2D('fixed-top-bottom',2000.,300.))
    def test_only_constant_unclipped_viscosity(self):
        with self.assertRaises(TectonicsError):replace(problem(),rheology=reference_rheology('tosi-1'))
    def test_named_source_frame_epoch_required(self):
        for k in ('source','epoch_id','composition_id'):
            with self.subTest(k=k),self.assertRaises(TectonicsError):replace(problem(),**{k:''})
    def test_explicit_gravity_frame(self):
        for g in ([0.,-1.],(0.,),(0.,np.nan)):
            with self.subTest(g=g),self.assertRaises(TectonicsError):replace(problem(),gravity_m_s2=g)
    def test_policy_positivity_bound(self):
        for c in (0.,-.1,.5000001,np.nan):
            with self.subTest(c=c),self.assertRaises(TectonicsError):ThermochemicalPolicy(outgoing_courant=c)
    def test_policy_finite_work_bounds(self):
        for k,v in (('max_steps',0),('max_cells',-1),('max_cells',True),('inventory_rtol',.01)):
            with self.subTest(k=k,v=v),self.assertRaises(TectonicsError):ThermochemicalPolicy(**{k:v})
    def test_problem_descriptor_canonical(self):
        p=problem(5,4);q=ThermochemicalProblem.from_descriptor(p.descriptor())
        self.assertEqual(p.problem_id,q.problem_id)
        d=p.descriptor();d['extra']='ignored?'
        with self.assertRaises(TectonicsError):ThermochemicalProblem.from_descriptor(d)
    def test_definition_frozen(self):
        p=problem()
        with self.assertRaises(FrozenInstanceError):p.source='changed'
    def test_mask_boolean_and_wrong_shape(self):
        p=problem(4)
        for a in (np.zeros((4,3)),np.ones((4,4),bool),np.ma.array(np.ones((4,4))*300)):
            with self.subTest(type=type(a)),self.assertRaises(TectonicsError):ThermochemicalState(p,a,np.zeros((4,4)),time_s=0,source='fixture')
    def test_invalid_fields(self):
        p=problem(4)
        for T,C in ((300,np.nan),(300,-.01),(300,1.01),(np.inf,.5),(450,.5)):
            with self.subTest(T=T,C=C),self.assertRaises(TectonicsError):initial(p,T=T,C=C)
    def test_roundoff_excursion_is_retained_and_reported(self):
        p=problem(4);c=-np.finfo(float).eps;s=initial(p,C=c)
        assert_array_equal(s.array('composition'),np.full((4,4),c))
        self.assertEqual(s.descriptor()['composition_bound_excursion'],-c)
    def test_initial_cannot_forge_history(self):
        p=problem(4)
        with self.assertRaises(TectonicsError):ThermochemicalState(p,np.full((4,4),305),np.full((4,4),.5),time_s=0,source='x',parent_id='0'*64)
    def test_stored_invalid_method_refused(self):
        p=problem(4)
        with self.assertRaises(TectonicsError):ThermochemicalState(p,np.full((4,4),305),np.full((4,4),.5),time_s=1,source='x',step_index=1,parent_id='0'*64,execution_id='0'*64,step_record={'method':'fake'})
    def test_velocity_walls_and_shape(self):
        p=problem(4);v=rest(p);u=v.array('u_m_s').copy();u[0,0]=.1
        with self.assertRaises(TectonicsError):PrescribedMACVelocity(p.box,u,v.array('w_m_s'),source='invalid')
        with self.assertRaises(TectonicsError):PrescribedMACVelocity(p.box,u[:,:-1],v.array('w_m_s'),source='invalid')


class Execution(unittest.TestCase):
    def setUp(self):self.p=problem(4);self.s=initial(self.p);self.v=rest(self.p)
    def step(self,p,**kw):return p.advance(self.s,.01,source='fixed experiment',velocity=self.v,**kw)
    def test_repeat_is_deterministic(self):
        with PreparedThermochemical2D(self.p) as p:a=self.step(p);b=self.step(p)
        self.assertEqual(a.result_id,b.result_id)
        assert_array_equal(a.state.array('temperature_k'),b.state.array('temperature_k'))
    def test_source_and_input_identity(self):
        with PreparedThermochemical2D(self.p) as p:
            a=self.step(p);b=p.advance(self.s,.01,source='different experiment',velocity=self.v)
        self.assertNotEqual(a.state.state_id,b.state.state_id)
    def test_source_time_parent_retained(self):
        with PreparedThermochemical2D(self.p) as p:
            a=self.step(p);b=p.advance(a.state,.02,source='next',velocity=self.v)
        d=b.state.descriptor();self.assertEqual(d['parent_id'],a.state.state_id)
        self.assertEqual(d['step_index'],2);self.assertEqual(d['time_s'],.03)
    def test_bindings_immutable(self):
        with PreparedThermochemical2D(self.p) as p:
            for k in ('problem','policy','backend','identity','budget'):
                with self.subTest(k=k),self.assertRaises(TectonicsError):setattr(p,k,None)
    def test_arrays_cannot_be_write_enabled(self):
        with PreparedThermochemical2D(self.p) as p:r=self.step(p)
        for a in (r.state.array('temperature_k'),r.state.array('composition'),*(r.array(k) for k in r.array_names)):
            with self.assertRaises(ValueError):a.setflags(write=True)
    def test_shape_and_metadata_are_private(self):
        with PreparedThermochemical2D(self.p) as p:r=self.step(p)
        v=r.state.array('temperature_k');v.shape=(16,)
        self.assertEqual(r.state.array('temperature_k').shape,(4,4))
        d=r.descriptor();d['record']['dt_s']=999
        self.assertEqual(r.descriptor()['record']['dt_s'],.01)
    def test_caller_field_capture(self):
        t=self.s.array('temperature_k').copy();c=self.s.array('composition').copy()
        s=ThermochemicalState(self.p,t,c,time_s=0,source='caller');expected=s.state_id
        t[:]=0;c[:]=9;self.assertEqual(s.state_id,expected);self.assertGreater(s.array('temperature_k').min(),300)
    def test_heating_and_velocity_capture(self):
        h=np.full((4,4),.2);u=self.v.array('u_m_s').copy();w=self.v.array('w_m_s').copy()
        v=PrescribedMACVelocity(self.p.box,u,w,source='capture');u[:]=99
        with PreparedThermochemical2D(self.p) as p:r=p.advance(self.s,.01,source='capture',velocity=v,extra_heating_w_m3=h)
        h[:]=99;assert_array_equal(r.array('total_heating_w_m3'),np.full((4,4),.2))
    def test_failed_initial_admission_released(self):
        b=WorkBudget(1)
        with self.assertRaises(MemoryLimitError):PreparedThermochemical2D(self.p,budget=b)
        self.assertEqual(b.reserved_bytes,0)
    def test_failed_step_admission_released(self):
        n=16;held=6*1024**2+128*n;b=WorkBudget(held+1024)
        with PreparedThermochemical2D(self.p,budget=b) as p:
            with self.assertRaises(MemoryLimitError):self.step(p)
            self.assertEqual(b.reserved_bytes,held)
        self.assertEqual(b.reserved_bytes,0)
    def test_cancel_at_entry_then_reuse(self):
        e=threading.Event();e.set();b=WorkBudget(64<<20)
        with PreparedThermochemical2D(self.p,budget=b) as p:
            held=b.reserved_bytes
            with self.assertRaises(CancelledError):self.step(p,cancel=e)
            self.assertEqual(b.reserved_bytes,held);e.clear();self.step(p,cancel=e)
        self.assertEqual(b.reserved_bytes,0)
    def test_cancel_mid_step_no_endpoint(self):
        class Cancel:
            def __init__(self):self.n=0
            def is_set(self):self.n+=1;return self.n>=5
        b=WorkBudget(64<<20);sid=self.s.state_id
        with PreparedThermochemical2D(self.p,budget=b) as p:
            held=b.reserved_bytes
            with self.assertRaises(CancelledError):self.step(p,cancel=Cancel())
            self.assertEqual(b.reserved_bytes,held);self.step(p)
        self.assertEqual(sid,self.s.state_id);self.assertEqual(b.reserved_bytes,0)
    def test_preparation_dependency_failure_releases(self):
        b=WorkBudget(64<<20)
        with mock.patch.object(tx,'ExecutionContext',side_effect=TectonicsError('injected')):
            with self.assertRaises(TectonicsError):PreparedThermochemical2D(self.p,budget=b)
        self.assertEqual(b.reserved_bytes,0)
    def test_wrong_thread_and_active_close_refused(self):
        with PreparedThermochemical2D(self.p) as p:
            with ThreadPoolExecutor(1) as pool:
                with self.assertRaises(TectonicsError):pool.submit(self.step,p).result()
                with self.assertRaises(TectonicsError):pool.submit(p.close).result()
            with p._operation(None):
                with self.assertRaises(TectonicsError):p.close()
            self.step(p)
    def test_closed_plan_no_reuse(self):
        p=PreparedThermochemical2D(self.p);p.close();p.close()
        with self.assertRaises(TectonicsError):self.step(p)
    def test_bad_time_intervals(self):
        with PreparedThermochemical2D(self.p) as p:
            for dt in (0.,-1.,np.nan,np.inf,True):
                with self.subTest(dt=dt),self.assertRaises(TectonicsError):p.advance(self.s,dt,source='bad',velocity=self.v)
            s=ThermochemicalState(self.p,self.s.array('temperature_k'),self.s.array('composition'),time_s=1e100,source='ancient')
            with self.assertRaises(TectonicsError):p.advance(s,1.,source='no representable time advance',velocity=self.v)
    def test_max_steps_checked(self):
        with PreparedThermochemical2D(self.p,policy=ThermochemicalPolicy(max_steps=1)) as p:
            s=self.step(p).state
            with self.assertRaises(TectonicsError):p.advance(s,.01,source='exhausted',velocity=self.v)
    def test_policy_change_cannot_rebind(self):
        with PreparedThermochemical2D(self.p) as p:s=self.step(p).state
        with PreparedThermochemical2D(self.p,policy=ThermochemicalPolicy(outgoing_courant=.4)) as p:
            with self.assertRaises(TectonicsError):p.advance(s,.01,source='mismatch',velocity=self.v)
    def test_problem_and_frame_not_renamed(self):
        with PreparedThermochemical2D(self.p) as p:
            with self.assertRaises(TectonicsError):p.advance(initial(problem(4,width=2)),.01,source='wrong')
            with self.assertRaises(TectonicsError):p.advance(self.s,.01,source='wrong',velocity=rest(problem(4,width=2)))
    def test_negative_nonfinite_heating_refused(self):
        with PreparedThermochemical2D(self.p) as p:
            for h in (-1.,np.nan,np.inf,np.ones((3,3))):
                with self.subTest(h=str(h)),self.assertRaises(TectonicsError):self.step(p,extra_heating_w_m3=h)
    def test_mutated_loaded_method_refused(self):
        with PreparedThermochemical2D(self.p) as p:
            with mock.patch.object(thermochemical._Diffusion2D,'transform',lambda self,x:x):
                with self.assertRaises(TectonicsError):self.step(p)
            self.step(p)
    def test_bound_constant_mutation_is_source_checked(self):
        with PreparedThermochemical2D(self.p) as p:
            with mock.patch.object(thermochemical,'_BOUND_TOL',1e-3):
                with self.assertRaises(TectonicsError):self.step(p)
            self.step(p)
    def test_combined_native_identity_includes_FFT(self):
        from atlas_tectonics import reuse
        record=reuse._runtime_record('numba')['binaries']
        for key in ('scipy_fft','scipy_superlu','scipy_lapack','numba_helper','llvmlite'):
            self.assertIn(key,record)
    def test_current_timestep_cache_not_scientific_identity(self):
        with PreparedThermochemical2D(self.p) as p:
            a=self.step(p);p.advance(self.s,.02,source='cache-other',velocity=self.v);b=self.step(p)
        self.assertEqual(a.result_id,b.result_id)
    def test_small_constituent_not_lost_in_domain_normalisation(self):
        p=problem(8,fixed=False);s=initial(p,T=305,C=1e-180);v=circulation(p)
        with PreparedThermochemical2D(p) as plan:r=plan.advance(s,.1,source='trace constituent',velocity=v)
        self.assertGreater(r.state.array('composition').min(),0)
        self.assertLess(r.descriptor()['record']['balances']['composition_relative_residual'],2e-14)
    def test_temperature_and_material_are_not_plate_labels(self):
        self.assertEqual(self.s.problem.composition_id,'synthetic-heavy-constituent')
        self.assertNotIn('plate',self.s.descriptor());self.assertFalse(self.s.descriptor()['R4_complete'])
    def test_stage_velocities_not_endpoint_claim(self):
        with PreparedThermochemical2D(self.p) as p:r=self.step(p)
        self.assertIn('not final-time',r.descriptor()['stage_velocity_semantics'])
    def test_no_unknown_backend_fallback(self):
        with self.assertRaises(TectonicsError):PreparedThermochemical2D(self.p,backend='auto')
    def test_invalid_decoded_balance_refused(self):
        with PreparedThermochemical2D(self.p) as p:r=self.step(p)
        d=r.state.descriptor();d['step_record']['balances']['heat_relative_residual']=.1
        with self.assertRaises(TectonicsError):ThermochemicalState.restore(d,{k:r.state.array(k) for k in ('temperature_k','composition')})
    def test_invalid_decoded_time_refused(self):
        with PreparedThermochemical2D(self.p) as p:r=self.step(p)
        d=r.state.descriptor();d['time_s']+=1
        with self.assertRaises(TectonicsError):ThermochemicalState.restore(d,{k:r.state.array(k) for k in ('temperature_k','composition')})


class Persistence(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'states.sqlite'
        self.p=problem(4);self.s=initial(self.p);self.v=rest(self.p)
    def tearDown(self):self.tmp.cleanup()
    def store(self,**kw):return ArrayStore(self.path,StoreLimits(4096,16<<20,64<<20),**kw)
    def test_reopen_and_exact_continuation(self):
        with PreparedThermochemical2D(self.p) as p:
            first=p.advance(self.s,.02,source='first',velocity=self.v).state
            expected=p.advance(first,.03,source='second',velocity=self.v)
        with self.store() as store:save_thermochemical_state(first,store)
        with self.store() as store:restored=load_thermochemical_state(store,first.state_id)
        with PreparedThermochemical2D(restored.problem) as p:actual=p.advance(restored,.03,source='second',velocity=self.v)
        self.assertEqual(expected.state.state_id,actual.state.state_id);self.assertEqual(expected.result_id,actual.result_id)
        for k in actual.array_names:assert_array_equal(actual.array(k),expected.array(k))
    def test_duplicate_state_adds_no_chunks(self):
        with self.store() as store:
            save_thermochemical_state(self.s,store);before=store.statistics()['unique_chunks']
            save_thermochemical_state(self.s,store);self.assertEqual(store.statistics()['unique_chunks'],before)
    def test_cancelled_save_not_published(self):
        e=threading.Event();e.set()
        with self.store() as store:
            with self.assertRaises(CancelledError):save_thermochemical_state(self.s,store,cancel=e)
            self.assertEqual(store.statistics()['snapshots'],0)
    def test_restore_budget_refusal_preserves_store(self):
        with self.store() as store:
            save_thermochemical_state(self.s,store)
            with self.assertRaises(MemoryLimitError):load_thermochemical_state(store,self.s.state_id,budget=WorkBudget(1))
            self.assertEqual(load_thermochemical_state(store,self.s.state_id).state_id,self.s.state_id)
    def test_wrong_state_id_or_missing_state_refused(self):
        with self.store() as store:
            for sid in ('wrong','0'*64):
                with self.subTest(sid=sid),self.assertRaises(TectonicsError):load_thermochemical_state(store,sid)
    def test_noncanonical_description_and_missing_array(self):
        d=self.s.descriptor();arrays={k:self.s.array(k) for k in ('temperature_k','composition')}
        with self.assertRaises(TectonicsError):ThermochemicalState.restore(d,{'temperature_k':arrays['temperature_k']})
        d['problem_id']='0'*64
        with self.assertRaises(TectonicsError):ThermochemicalState.restore(d,arrays)
    def test_writable_decoded_arrays_are_detached(self):
        arrays={k:self.s.array(k).copy() for k in ('temperature_k','composition')}
        restored=ThermochemicalState.restore(self.s.descriptor(),arrays)
        arrays['temperature_k'][:]=2
        assert_array_equal(restored.array('temperature_k'),self.s.array('temperature_k'))
    def test_cold_subprocess_restore_and_continue(self):
        with PreparedThermochemical2D(self.p) as p:
            s=p.advance(self.s,.01,source='first',velocity=self.v).state
            expected=p.advance(s,.02,source='second',velocity=self.v).state.state_id
        with self.store() as store:save_thermochemical_state(s,store)
        code="""
import sys,json,numpy as np
sys.path.insert(0,sys.argv[1])
from atlas_tectonics import *
from atlas_tectonics.storage import ArrayStore,StoreLimits
with ArrayStore(sys.argv[2],StoreLimits(4096,16<<20,64<<20)) as store:s=load_thermochemical_state(store,sys.argv[3])
p=s.problem;b=p.box
v=PrescribedMACVelocity(b,np.zeros((b.nz,b.nx+1)),np.zeros((b.nz+1,b.nx)),source='explicit zero velocity')
with PreparedThermochemical2D(p) as plan:r=plan.advance(s,.02,source='second',velocity=v)
print(r.state.state_id)
"""
        run=subprocess.run([sys.executable,'-I','-B','-c',code,str(ROOT/'src'),str(self.path),s.state_id],capture_output=True,text=True,timeout=45)
        self.assertEqual(run.returncode,0,run.stderr);self.assertEqual(run.stdout.strip(),expected)

if __name__=='__main__':unittest.main()
