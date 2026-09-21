"""Explicit intra-step guesses: independent equations, provenance and recovery.
SPDX-License-Identifier: AGPL-3.0-only
"""
from concurrent.futures import CancelledError
from dataclasses import asdict, replace
from pathlib import Path
import inspect
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import numpy as np
import atlas_tectonics as at
from atlas_tectonics.resources import WorkBudget, MemoryLimitError
from atlas_tectonics.storage import ArrayStore, StoreLimits
from atlas_tectonics.variable_stokes_execution import VariableStokesSolution
from variable_stokes_fixtures import (forcing, independent_two_cell_amplitude,
    coupled_problem, independent_nonlinear_two_cell_rhs)
from stokes_fixtures import unit_box, unit_scales, request
from thermochemical_fixtures import initial, problem, rest
ROOT=Path(__file__).resolve().parents[1]
ENV={**os.environ,'OPENBLAS_NUM_THREADS':'1','OMP_NUM_THREADS':'1','MKL_NUM_THREADS':'1'}
FIELDS=('u_m_s','w_m_s','pressure_pa')


def scalar_inputs(force=1.,temperature=1.6):
    return (force*np.array([[1.],[-1.]]),force*np.array([[-1.,1.]]),
            np.full((2,2),temperature),at.reference_rheology('tosi-2'))


class ExplicitGuessTests(unittest.TestCase):
    def setUp(self):
        self.b=unit_box(2);self.sc=unit_scales()
        self.plan=at.PreparedVariableStokes2D(self.b,self.sc);self.addCleanup(self.plan.close)
        self.seed=self.plan.solve_rheology(*scalar_inputs(),**request(self.b))
        self.guess=at.NonlinearStokesGuess(self.seed)
    def solve(self,*args,guess=True,**kwargs):
        return self.plan.solve_rheology(*(args or scalar_inputs()),
            initial_guess=self.guess if guess else None,**{**request(self.b),**kwargs})
    def test_cold_default_record_and_fields_unchanged(self):
        cold=self.solve(guess=False);self.assertEqual(cold.result_id,self.seed.result_id)
        self.assertNotIn('initial_guess',cold.descriptor())
    def test_typed_guess_required(self):
        with self.assertRaises(at.TectonicsError):at.NonlinearStokesGuess({})
        with self.assertRaises(at.TectonicsError):self.plan.solve_rheology(*scalar_inputs(),initial_guess=self.seed,**request(self.b))
    def test_arrays_are_immutable_and_descriptor_detached(self):
        for key in FIELDS:
            with self.assertRaises(ValueError):self.guess.array(key).flat[0]=0
        with self.assertRaises(at.TectonicsError):self.guess.guess_id='0'*64
        d=self.guess.descriptor();d['box']['nx']=20
        self.assertEqual(self.guess.descriptor()['box']['nx'],2)
        with self.assertRaises(at.TectonicsError):self.guess.array('unknown')
    def test_self_contained_roundtrip(self):
        d=json.loads(json.dumps(self.guess.descriptor()))
        out=at.NonlinearStokesGuess.restore(d,{k:self.guess.array(k) for k in FIELDS},self.guess.guess_id)
        self.assertEqual(out.guess_id,self.guess.guess_id)
        result=self.plan.solve_rheology(*scalar_inputs(),initial_guess=out,**request(self.b))
        self.assertEqual(result.result_id,self.solve().result_id)
    def test_guess_hash_detects_changed_input(self):
        arrays={k:self.guess.array(k).copy() for k in FIELDS};arrays['u_m_s'][0,1]+=.01
        with self.assertRaises(at.TectonicsError):at.NonlinearStokesGuess.restore(self.guess.descriptor(),arrays,self.guess.guess_id)
    def test_malformed_or_nonfinite_guess_refused(self):
        for key in FIELDS:
            arrays={k:self.guess.array(k).copy() for k in FIELDS};arrays[key].flat[0]=np.nan
            with self.assertRaises(at.TectonicsError):at.NonlinearStokesGuess.restore(self.guess.descriptor(),arrays,self.guess.guess_id)
        for meta in ({},{**self.guess.descriptor(),'schema':'other'}):
            with self.assertRaises(at.TectonicsError):at.NonlinearStokesGuess.restore(meta,{k:self.guess.array(k) for k in FIELDS},self.guess.guess_id)
    def test_incomplete_and_wrong_shape_guess_refused(self):
        arrays={k:self.guess.array(k) for k in FIELDS};arrays.pop('pressure_pa')
        with self.assertRaises(at.TectonicsError):at.NonlinearStokesGuess.restore(self.guess.descriptor(),arrays,self.guess.guess_id)
        arrays={k:self.guess.array(k) for k in FIELDS};arrays['pressure_pa']=np.zeros((1,2))
        with self.assertRaises(at.TectonicsError):at.NonlinearStokesGuess.restore(self.guess.descriptor(),arrays,self.guess.guess_id)
    def test_nonzero_wall_input_refused(self):
        arrays={k:self.guess.array(k).copy() for k in FIELDS};arrays['u_m_s'][0,0]=1.
        with self.assertRaises(at.TectonicsError):at.NonlinearStokesGuess.restore(self.guess.descriptor(),arrays,self.guess.guess_id)
    def test_initial_guess_publication_is_complete(self):
        warm=self.solve();d=warm.descriptor();self.assertEqual(d['initial_guess']['guess_id'],self.guess.guess_id)
        self.assertEqual(d['initial_guess']['descriptor']['source_result_id'],self.seed.result_id)
        for k in FIELDS:np.testing.assert_array_equal(warm.array('initial_guess_'+k),self.guess.array(k))
        rebuilt=VariableStokesSolution(d,{k:warm.array(k) for k in warm.array_names});self.assertEqual(rebuilt.result_id,warm.result_id)
    def test_missing_stored_initial_guess_arrays_refused(self):
        warm=self.solve();arr={k:warm.array(k) for k in warm.array_names};arr.pop('initial_guess_u_m_s')
        with self.assertRaises(at.TectonicsError):VariableStokesSolution(warm.descriptor(),arr)
    def test_stored_guess_descriptor_tampering_refused(self):
        warm=self.solve();d=warm.descriptor();d['initial_guess']['guess_id']='0'*64
        with self.assertRaises(at.TectonicsError):VariableStokesSolution(d,{k:warm.array(k) for k in warm.array_names})
    def test_different_policy_refused(self):
        with at.PreparedVariableStokes2D(self.b,self.sc,policy=at.NonlinearStokesPolicy(ilu_fill_factor=17.)) as plan:
            with self.assertRaisesRegex(at.TectonicsError,'source/plan'):plan.solve_rheology(*scalar_inputs(),initial_guess=self.guess,**request(self.b))
    def test_different_geometry_refused(self):
        b=unit_box(3)
        with at.PreparedVariableStokes2D(b,self.sc) as plan:
            with self.assertRaisesRegex(at.TectonicsError,'source/plan'):
                plan.solve_rheology(np.zeros((3,2)),np.zeros((2,3)),np.ones((3,3))*1.6,
                    at.reference_rheology('tosi-2'),initial_guess=self.guess,**request(b))
    def test_different_epoch_refused(self):
        with self.assertRaisesRegex(at.TectonicsError,'epoch/time'):self.solve(epoch_id='other-epoch')
    def test_future_guess_refused(self):
        future=self.plan.solve_rheology(*scalar_inputs(),**{**request(self.b),'time_s':10.})
        with self.assertRaisesRegex(at.TectonicsError,'epoch/time'):
            self.plan.solve_rheology(*scalar_inputs(),initial_guess=at.NonlinearStokesGuess(future),**request(self.b))
    def test_different_rheology_refused(self):
        inputs=scalar_inputs()
        with self.assertRaisesRegex(at.TectonicsError,'rheology'):self.solve(*inputs[:3],at.reference_rheology('tosi-1'))
    def test_bf_initialisation_explicitly_out_of_scope(self):
        with self.assertRaisesRegex(at.TectonicsError,'BF warm'):
            self.plan.solve_rheology(*scalar_inputs()[:3],at.reference_rheology('bf23-memory'),
                frozen_damage=np.zeros((2,2)),initial_guess=self.guess,**request(self.b))
    def test_changed_forcing_and_temperature_against_independent_root(self):
        for force,temperature in ((.25,1.4),(2.,1.61),(-1.3,1.5),(0.,1.7)):
            warm=self.solve(*scalar_inputs(force,temperature));expected=independent_two_cell_amplitude(force,temperature)
            self.assertAlmostEqual(warm.array('u_m_s')[0,1],expected,delta=1e-7*max(1.,abs(expected)))
            cold=self.solve(*scalar_inputs(force,temperature),guess=False)
            for key in FIELDS:np.testing.assert_allclose(warm.array(key),cold.array(key),rtol=1e-7,atol=1e-9)
            self.assertLessEqual(warm.descriptor()['diagnostics']['momentum_linf'],1e-9)
    def test_zero_forcing_has_zero_velocity_despite_nonzero_seed(self):
        warm=self.solve(*scalar_inputs(0.))
        for k in FIELDS:np.testing.assert_array_equal(warm.array(k),np.zeros_like(warm.array(k)))
    def test_nonunit_geometry_scales_and_force_amplitude(self):
        b,sc,fx,fz,T,rp=forcing(4);b=replace(b,width_m=2.,height_m=.75);sc=replace(sc,length_m=3.,viscosity_pa_s=7.)
        with at.PreparedVariableStokes2D(b,sc) as p:
            first=p.solve_rheology(fx,fz,T,rp,**request(b));g=at.NonlinearStokesGuess(first)
            warm=p.solve_rheology(1.2*fx,1.2*fz,T+.01,rp,initial_guess=g,**request(b))
            cold=p.solve_rheology(1.2*fx,1.2*fz,T+.01,rp,**request(b))
        for k in FIELDS:np.testing.assert_allclose(warm.array(k),cold.array(k),rtol=1e-7,atol=1e-9)
    def test_explicit_direct_reference_still_independent(self):
        with at.PreparedVariableStokes2D(self.b,self.sc,policy=at.NonlinearStokesPolicy(method='direct')) as p:
            seed=p.solve_rheology(*scalar_inputs(),**request(self.b))
            warm=p.solve_rheology(*scalar_inputs(1.1),initial_guess=at.NonlinearStokesGuess(seed),**request(self.b))
        self.assertAlmostEqual(warm.array('u_m_s')[0,1],independent_two_cell_amplitude(1.1,1.6),delta=1e-6)
    def test_cold_request_independent_of_previous_warm_requests(self):
        self.solve(*scalar_inputs(1.3));self.assertEqual(self.solve(guess=False).result_id,self.seed.result_id)
    def test_repeated_explicit_guess_is_history_independent(self):
        a=self.solve();self.solve(*scalar_inputs(.8));b=self.solve();self.assertEqual(a.result_id,b.result_id)
    def test_saved_warm_result_replays_without_original_seed_result(self):
        warm=self.solve();d=warm.descriptor()
        with tempfile.TemporaryDirectory() as tmp:
            with ArrayStore(Path(tmp)/'s.sqlite',StoreLimits(4096,16<<20,64<<20)) as store:at.save_variable_stokes_solution(warm,store)
            with ArrayStore(Path(tmp)/'s.sqlite',StoreLimits(4096,16<<20,64<<20)) as store:
                loaded=at.load_variable_stokes_solution(store,warm.result_id);self.assertIsNone(store.metadata(self.seed.result_id))
        restored=at.NonlinearStokesGuess.restore(d['initial_guess']['descriptor'],
            {k:loaded.array('initial_guess_'+k) for k in FIELDS},d['initial_guess']['guess_id'])
        replay=self.plan.solve_rheology(*scalar_inputs(),initial_guess=restored,**request(self.b));self.assertEqual(replay.result_id,warm.result_id)
    def test_guess_capture_budget_refusal_and_release(self):
        budget=WorkBudget(1024)
        with self.assertRaises(MemoryLimitError):at.NonlinearStokesGuess(self.seed,budget=budget)
        self.assertEqual(budget.reserved_bytes,0)

    def test_restored_guess_owns_input_bytes(self):
        arrays={k:self.guess.array(k).copy() for k in FIELDS}
        out=at.NonlinearStokesGuess.restore(self.guess.descriptor(),arrays,self.guess.guess_id)
        arrays['u_m_s'][:]=0
        np.testing.assert_array_equal(out.array('u_m_s'),self.guess.array('u_m_s'))
    def test_changed_guess_callable_invalidates_prepared_source(self):
        from atlas_tectonics import variable_stokes_execution as vx
        with mock.patch.object(vx,'_check_guess_binding',lambda *a,**kw:None):
            with self.assertRaises(at.TectonicsError):self.solve()
    def test_initial_guess_from_prescribed_viscosity_is_refused(self):
        r=self.plan.solve(*scalar_inputs()[:2],np.ones((2,2)),np.ones((1,1)),**request(self.b))
        with self.assertRaises(at.TectonicsError):at.NonlinearStokesGuess(r)


class WarmCouplingTests(unittest.TestCase):
    def setUp(self):self.p=coupled_problem(4);self.s=initial(self.p)
    def run_step(self,mode='rk-stage0',**kwargs):
        with at.PreparedThermochemical2D(self.p,nonlinear_start=mode,**kwargs) as q:return q.advance(self.s,.001,source='warm coupling check')
    def test_flow_callback_keeps_three_values_unless_capture_requested(self):
        with at.PreparedThermochemical2D(self.p,nonlinear_start='rk-stage0') as q:
            args=(self.s.array('temperature_k'),self.s.array('composition'),self.s.time_s,'test stage','callback shape',None)
            legacy=q._flow(*args);self.assertEqual(len(legacy),3)
            captured=q._flow(*args,capture_solution=True);self.assertEqual(len(captured),4)
            self.assertEqual(captured[2],captured[3].result_id)
            self.assertIsInstance(captured[3],at.VariableStokesSolution)
            for k in (0,1):np.testing.assert_array_equal(legacy[k],captured[k])
    def test_explicit_start_policy_bound_and_frozen(self):
        with at.PreparedThermochemical2D(self.p) as cold,at.PreparedThermochemical2D(self.p,nonlinear_start='rk-stage0') as warm:
            self.assertNotEqual(cold.identity,warm.identity)
            with self.assertRaises(at.TectonicsError):warm.nonlinear_start='zero-rate'
    def test_unsupported_and_ignored_policies_refused(self):
        for mode in (None,True,'automatic'):
            with self.assertRaises(at.TectonicsError):at.PreparedThermochemical2D(self.p,nonlinear_start=mode)
        with self.assertRaises(at.TectonicsError):at.PreparedThermochemical2D(problem(),nonlinear_start='rk-stage0')
        with at.PreparedThermochemical2D(self.p,nonlinear_start='rk-stage0') as q:
            with self.assertRaises(at.TectonicsError):q.advance(self.s,.001,source='unused',velocity=rest(self.p))
    def test_stage0_is_cold_and_stage1_binds_only_current_stage(self):
        r=self.run_step();m=r.descriptor()['record']['nonlinear_mechanics'];a,b=m['stages']
        self.assertEqual(m['nonlinear_start'],'rk-stage0');self.assertIsNone(a['initial_guess_id']);self.assertIsNone(a['initial_guess_result_id'])
        self.assertEqual(b['initial_guess_result_id'],a['result_id']);self.assertEqual(len(b['initial_guess_id']),64)
    def test_same_stage0_fields_and_close_final_fields(self):
        a=self.run_step('zero-rate');b=self.run_step()
        for k in ('u_stage0_m_s','w_stage0_m_s'):np.testing.assert_array_equal(a.array(k),b.array(k))
        for k in ('temperature_k','composition'):np.testing.assert_allclose(a.state.array(k),b.state.array(k),rtol=0,atol=1e-9)
        for k in ('u_stage1_m_s','w_stage1_m_s'):np.testing.assert_allclose(a.array(k),b.array(k),rtol=1e-7,atol=1e-9)
    def test_heat_composition_and_true_stage_gates_remain(self):
        r=self.run_step();d=r.descriptor()['record'];b=d['balances']
        for k in ('heat_relative_residual','composition_relative_residual','advective_local_residual'):self.assertLessEqual(b[k],1e-11)
        for row in d['nonlinear_mechanics']['stages']:
            self.assertLessEqual(row['diagnostics']['momentum_linf'],1e-9);self.assertLessEqual(row['diagnostics']['divergence_linf'],1e-10)
        self.assertEqual(d['nonlinear_mechanics']['policy'],asdict(at.NonlinearStokesPolicy()))
    def test_independent_coupled_ode_retains_second_order(self):
        from scipy.integrate import solve_ivp
        p=coupled_problem(2);s=initial(p);y=np.r_[s.array('temperature_k').ravel(),s.array('composition').ravel()];end=.5
        oracle=solve_ivp(lambda t,y:independent_nonlinear_two_cell_rhs(p,y),(0.,end),y,method='DOP853',rtol=1e-12,atol=1e-13)
        self.assertTrue(oracle.success);errors=[]
        for n in (2,4,8):
            st=s
            with at.PreparedThermochemical2D(p,nonlinear_start='rk-stage0') as q:
                for _ in range(n):st=q.advance(st,end/n,source='independent ODE').state
            errors.append(float(np.max(np.abs(np.r_[st.array('temperature_k').ravel(),st.array('composition').ravel()]-oracle.y[:,-1]))))
        self.assertLess(errors[-1],1e-8)
        for a,b in zip(errors,errors[1:]):self.assertGreater(a/b,3.5);self.assertLess(a/b,4.5)
    def test_snapshot_stays_cold_and_does_not_pollute_next_step(self):
        with at.PreparedThermochemical2D(self.p,nonlinear_start='rk-stage0') as q:
            a=q.advance(self.s,.001,source='repeat');snapshot=q.mechanical_snapshot(a.state,source='independent endpoint')
            self.assertNotIn('initial_guess',snapshot.descriptor());b=q.advance(self.s,.001,source='repeat')
        self.assertEqual(a.result_id,b.result_id)
    def test_second_stage_cancellation_keeps_state_and_next_request_clean(self):
        class Cancel:
            def is_set(self):
                frame=inspect.currentframe().f_back
                try:
                    while frame:
                        if frame.f_code.co_name=='solve_rheology' and frame.f_locals.get('initial_guess') is not None and frame.f_locals.get('history'):return True
                        frame=frame.f_back
                    return False
                finally:del frame
        budget=WorkBudget(256<<20);sid=self.s.state_id
        with at.PreparedThermochemical2D(self.p,nonlinear_start='rk-stage0',budget=budget) as q:
            with self.assertRaises(CancelledError):q.advance(self.s,.001,source='recover',cancel=Cancel())
            recovered=q.advance(self.s,.001,source='recover')
        with at.PreparedThermochemical2D(self.p,nonlinear_start='rk-stage0') as q:clean=q.advance(self.s,.001,source='recover')
        self.assertEqual(clean.result_id,recovered.result_id);self.assertEqual(self.s.state_id,sid);self.assertEqual(budget.reserved_bytes,0)
    def test_failed_nonlinear_request_has_no_endpoint_or_budget_leak(self):
        budget=WorkBudget(256<<20);sid=self.s.state_id
        with at.PreparedThermochemical2D(self.p,nonlinear_start='rk-stage0',nonlinear_policy=at.NonlinearStokesPolicy(max_picard_iterations=1),budget=budget) as q:
            with self.assertRaisesRegex(at.TectonicsError,'Picard'):q.advance(self.s,.001,source='fails')
        self.assertEqual(self.s.state_id,sid);self.assertEqual(budget.reserved_bytes,0)
    def test_wrong_start_policy_cannot_resume(self):
        warm=self.run_step().state
        with at.PreparedThermochemical2D(self.p) as q:
            with self.assertRaisesRegex(at.TectonicsError,'source/policy'):q.advance(warm,.001,source='wrong')
    def test_restore_rejects_incorrect_seed_link_and_policy(self):
        state=self.run_step().state
        for mutate in ('mode','id','first','missing'):
            d=state.descriptor();m=d['step_record']['nonlinear_mechanics']
            if mutate=='mode':m['nonlinear_start']='previous-step'
            if mutate=='id':m['stages'][1]['initial_guess_result_id']='0'*64
            if mutate=='first':m['stages'][0]['initial_guess_result_id']='0'*64
            if mutate=='missing':m.pop('nonlinear_start')
            with self.assertRaises(at.TectonicsError):at.ThermochemicalState.restore(d,{k:state.array(k) for k in ('temperature_k','composition')})
    def test_same_source_store_reopen_and_exact_continuation(self):
        with at.PreparedThermochemical2D(self.p,nonlinear_start='rk-stage0') as q:
            first=q.advance(self.s,.001,source='first').state;expected=q.advance(first,.001,source='second').state
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'state.sqlite'
            with ArrayStore(path,StoreLimits(4096,16<<20,64<<20)) as store:at.save_thermochemical_state(first,store)
            with ArrayStore(path,StoreLimits(4096,16<<20,64<<20)) as store:loaded=at.load_thermochemical_state(store,first.state_id)
        with at.PreparedThermochemical2D(self.p,nonlinear_start='rk-stage0') as q:actual=q.advance(loaded,.001,source='second').state
        self.assertEqual(actual.state_id,expected.state_id)

    def test_second_stage_error_is_not_retried_as_a_cold_solve(self):
        class Fault:
            def is_set(self):
                frame=inspect.currentframe().f_back
                try:
                    while frame:
                        if frame.f_code.co_name=='solve_rheology' and frame.f_locals.get('initial_guess') is not None and frame.f_locals.get('history'):
                            raise at.TectonicsError('injected second-stage fault')
                        frame=frame.f_back
                    return False
                finally:del frame
        budget=WorkBudget(256<<20);sid=self.s.state_id
        with at.PreparedThermochemical2D(self.p,nonlinear_start='rk-stage0',budget=budget) as q:
            with self.assertRaisesRegex(at.TectonicsError,'injected second-stage fault'):
                q.advance(self.s,.001,source='fault',cancel=Fault())
            recovered=q.advance(self.s,.001,source='fault')
        with at.PreparedThermochemical2D(self.p,nonlinear_start='rk-stage0') as q:clean=q.advance(self.s,.001,source='fault')
        self.assertEqual(recovered.result_id,clean.result_id);self.assertEqual(self.s.state_id,sid);self.assertEqual(budget.reserved_bytes,0)
    def test_native_and_reference_transport_agree_for_warm_mode(self):
        a=self.run_step(backend='numba');b=self.run_step(backend='reference')
        for key in ('temperature_k','composition'):np.testing.assert_array_equal(a.state.array(key),b.state.array(key))
    def test_cold_state_cannot_resume_as_warm(self):
        cold=self.run_step('zero-rate').state
        with at.PreparedThermochemical2D(self.p,nonlinear_start='rk-stage0') as q:
            with self.assertRaisesRegex(at.TectonicsError,'source/policy'):q.advance(cold,.001,source='wrong')


class WarmRunnerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory(prefix='atlas-warm-runner-');cls.base=Path(cls.tmp.name);cls.ref=cls.base/'reference'
        result=cls.execute(cls.ref,False,4)
        if result.returncode:raise RuntimeError(result.stdout+result.stderr)
        cls.expected=json.loads(result.stdout.splitlines()[-1])['last_state_id']
    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()
    @staticmethod
    def execute(output,resume,steps,*extra):
        args=['--resume'] if resume else ['--case','tosi-2','--cells','4','--dt','1e-5','--max-steps','4','--sample-every','1','--save-every','2','--nonlinear-start','rk-stage0']
        return subprocess.run([sys.executable,'-I','-B',str(ROOT/'tools/run_convection_r4_4.py'),'--output',str(output),'--segment-steps',str(steps),*args,*extra],env=ENV,capture_output=True,text=True,timeout=120)
    def test_fresh_process_recovery_matches_uninterrupted(self):
        out=self.base/'split';a=self.execute(out,False,2);self.assertEqual(a.returncode,0,a.stdout+a.stderr)
        b=self.execute(out,True,2);self.assertEqual(b.returncode,0,b.stdout+b.stderr)
        d=json.loads(b.stdout.splitlines()[-1]);self.assertEqual(d['last_state_id'],self.expected);self.assertEqual(d['budget_after_close']['reserved_bytes'],0)
    def test_runner_records_opt_in_and_audits_links(self):
        sys.path.insert(0,str(ROOT/'tools'));import analyse_convection_r4_4 as audit
        result=audit.analyse_run(self.ref);self.assertEqual(result['configuration']['nonlinear_start'],'rk-stage0');self.assertFalse(result['full_benchmark_accepted'])
    def test_resume_rejects_resupplied_start_policy(self):
        result=self.execute(self.ref,True,1,'--nonlinear-start','zero-rate');self.assertNotEqual(result.returncode,0);self.assertIn('do not resupply',result.stderr)

if __name__=='__main__':unittest.main()
