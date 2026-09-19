"""Two-stage nonlinear Tosi coupling; thermal/composition kernels remain retained.
SPDX-License-Identifier: AGPL-3.0-only
"""
from dataclasses import replace
from pathlib import Path
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock
from concurrent.futures import CancelledError
import numpy as np
from atlas_tectonics import (PreparedThermochemical2D,ThermochemicalProblem,ThermochemicalState,
    NonlinearStokesPolicy,StokesSolvePolicy,reference_rheology,save_thermochemical_state,
    load_thermochemical_state,TectonicsError)
from atlas_tectonics.resources import WorkBudget,MemoryLimitError
from atlas_tectonics.storage import ArrayStore,StoreLimits
from atlas_tectonics import thermochemical_execution as tx, variable_stokes_execution as vx
from variable_stokes_fixtures import coupled_problem,independent_nonlinear_two_cell_rhs
from thermochemical_fixtures import problem,initial,rest
ROOT=Path(__file__).resolve().parents[1]


class NonlinearCoupling(unittest.TestCase):
    def test_legacy_contract_still_rejects_implicit_variable_rheology(self):
        with self.assertRaises(TectonicsError):replace(problem(),rheology=reference_rheology('tosi-1'))
    def test_explicit_mode_roundtrips_canonical_descriptor(self):
        p=coupled_problem();r=ThermochemicalProblem.from_descriptor(p.descriptor())
        self.assertEqual(p.problem_id,r.problem_id);self.assertEqual(r.mechanical_mode,'variable-r4.3')
    def test_default_descriptor_has_no_new_implicit_mode(self):
        p=problem();self.assertNotIn('mechanical_mode',p.descriptor())
        self.assertEqual(ThermochemicalProblem.from_descriptor(p.descriptor()).descriptor(),p.descriptor())
    def test_unknown_mode_refused(self):
        with self.assertRaises(TectonicsError):replace(problem(),mechanical_mode='pretend-planetary')
    def test_bf_coupling_not_silently_zero_damage(self):
        with self.assertRaisesRegex(TectonicsError,'damage'):
            replace(problem(),rheology=reference_rheology('bf23-memory'),mechanical_mode='variable-r4.3')
    def test_explicit_nonlinear_policy_not_ignored_by_constant_route(self):
        with self.assertRaises(TectonicsError):PreparedThermochemical2D(problem(),nonlinear_policy=NonlinearStokesPolicy())
    def test_explicit_constant_policy_not_ignored_by_variable_route(self):
        with self.assertRaises(TectonicsError):PreparedThermochemical2D(coupled_problem(),stokes_policy=StokesSolvePolicy())
    def test_both_stage_mechanical_solutions_converged(self):
        p=coupled_problem(6);s=initial(p)
        with PreparedThermochemical2D(p) as q:r=q.advance(s,.001,source='nonlinear-step')
        m=r.descriptor()['record'];self.assertEqual(m['velocity_mode'],'buoyancy-coupled-variable-viscosity')
        self.assertEqual(len(m['nonlinear_mechanics']['stages']),2)
        self.assertNotEqual(*m['stage_flow_ids'])
        for row in m['nonlinear_mechanics']['stages']:
            self.assertLess(row['diagnostics']['momentum_linf'],1e-9)
            self.assertGreater(row['nonlinear_iterations'],1)
    def test_step_preserves_heat_and_composition_accounts(self):
        p=coupled_problem(6);s=initial(p)
        with PreparedThermochemical2D(p) as q:r=q.advance(s,.002,source='balances')
        b=r.descriptor()['record']['balances']
        for k in ('heat_relative_residual','composition_relative_residual','advective_local_residual'):
            self.assertLess(b[k],1e-11)
        self.assertGreaterEqual(r.state.array('composition').min(),0)
        self.assertLessEqual(r.state.array('composition').max(),1)
    def test_constant_mode_control_matches_existing_mechanics(self):
        p=problem(6);v=replace(p,mechanical_mode='variable-r4.3')
        with PreparedThermochemical2D(p) as q:a=q.advance(initial(p),.001,source='constant-control')
        with PreparedThermochemical2D(v) as q:b=q.advance(initial(v),.001,source='constant-control')
        for k in ('temperature_k','composition'):
            np.testing.assert_allclose(a.state.array(k),b.state.array(k),rtol=1e-12,atol=1e-12)
        self.assertNotEqual(a.state.state_id,b.state.state_id)
    def test_nonlinear_time_coupling_against_independent_eight_variable_ode(self):
        from scipy.integrate import solve_ivp
        p=coupled_problem(2);s=initial(p);y=np.r_[s.array('temperature_k').ravel(),s.array('composition').ravel()]
        duration=.5
        oracle=solve_ivp(lambda t,y:independent_nonlinear_two_cell_rhs(p,y),(0.,duration),y,method='DOP853',rtol=1e-12,atol=1e-13)
        self.assertTrue(oracle.success);error=[]
        for n in (2,4,8):
            st=s
            with PreparedThermochemical2D(p) as q:
                for i in range(n):st=q.advance(st,duration/n,source='independent temporal reference').state
            value=np.r_[st.array('temperature_k').ravel(),st.array('composition').ravel()]
            error.append(float(np.max(abs(value-oracle.y[:,-1]))))
        self.assertLess(error[-1],1e-8)
        for a,b in zip(error,error[1:]):self.assertGreater(a/b,3.5);self.assertLess(a/b,4.5)
    def test_nonlinear_failure_never_publishes_an_endpoint(self):
        p=coupled_problem(6);s=initial(p);sid=s.state_id;b=WorkBudget(128<<20)
        with PreparedThermochemical2D(p,nonlinear_policy=NonlinearStokesPolicy(max_picard_iterations=1),budget=b) as q:
            with self.assertRaisesRegex(TectonicsError,'Picard'):q.advance(s,.001,source='should fail')
        self.assertEqual(s.state_id,sid);self.assertEqual(b.reserved_bytes,0)
    def test_cancel_during_mechanics_keeps_initial_state(self):
        class Cancel:
            def __init__(self):self.n=0
            def is_set(self):self.n+=1;return self.n>=20
        p=coupled_problem(6);s=initial(p);b=WorkBudget(128<<20)
        with PreparedThermochemical2D(p,budget=b) as q:
            with self.assertRaises(CancelledError):q.advance(s,.001,source='cancelled',cancel=Cancel())
            q.advance(s,.001,source='after cancellation')
        self.assertEqual(s.descriptor()['step_index'],0);self.assertEqual(b.reserved_bytes,0)
    def test_updated_temperature_range_not_extrapolated(self):
        p=coupled_problem(6)
        with self.assertRaises(TectonicsError):initial(p,T=320)
    def test_material_fields_are_not_implicit_strength_parameters(self):
        p=coupled_problem(6);s=initial(p);v=rest(p)
        # Prescribed zero velocity still leaves the explicitly named local law;
        # it is not relabelled as a solved variable-viscosity force response.
        with PreparedThermochemical2D(p) as q:r=q.advance(s,.001,source='prescribed control',velocity=v)
        self.assertEqual(r.descriptor()['record']['velocity_mode'],'prescribed-frozen-MAC')
        self.assertNotIn('nonlinear_mechanics',r.descriptor()['record'])
    def test_solved_endpoint_state_is_not_stage_velocity(self):
        p=coupled_problem(5)
        with PreparedThermochemical2D(p) as q:r=q.advance(initial(p),.001,source='time semantics')
        self.assertIn('not final-time',r.descriptor()['stage_velocity_semantics'])
    def test_changed_nonlinear_policy_cannot_rebind_continuation(self):
        p=coupled_problem(5)
        with PreparedThermochemical2D(p) as q:s=q.advance(initial(p),.001,source='first').state
        with PreparedThermochemical2D(p,nonlinear_policy=NonlinearStokesPolicy(relaxation=.5)) as q:
            with self.assertRaises(TectonicsError):q.advance(s,.001,source='wrong policy')
    def test_native_and_numpy_transport_keep_numerical_results(self):
        p=coupled_problem(5);out=[]
        for backend in ('numba','reference'):
            with PreparedThermochemical2D(p,backend=backend) as q:out.append(q.advance(initial(p),.001,source='backend'))
        for k in ('temperature_k','composition'):np.testing.assert_array_equal(out[0].state.array(k),out[1].state.array(k))
    def test_old_thermal_and_flux_policies_not_silently_changed(self):
        p=coupled_problem(5)
        with PreparedThermochemical2D(p) as q:r=q.advance(initial(p),.001,source='policy')
        from atlas_tectonics import ThermochemicalPolicy
        from dataclasses import asdict
        self.assertEqual(r.descriptor()['record']['policy'],asdict(ThermochemicalPolicy()))
    def test_loaded_nonlinear_law_method_mutation_invalidates_preparation(self):
        p=coupled_problem(5)
        with PreparedThermochemical2D(p) as q:
            with mock.patch.object(vx.PreparedVariableStokes2D,'solve_rheology',lambda *a:None):
                with self.assertRaises(TectonicsError):q.advance(initial(p),.001,source='mutation')
    def test_decoded_unconverged_stage_refused(self):
        p=coupled_problem(5)
        with PreparedThermochemical2D(p) as q:r=q.advance(initial(p),.001,source='decode')
        d=r.state.descriptor();d['step_record']['nonlinear_mechanics']['stages'][1]['diagnostics']['momentum_linf']=1
        with self.assertRaises(TectonicsError):ThermochemicalState.restore(d,{k:r.state.array(k) for k in ('temperature_k','composition')})
    def test_decoded_wrong_profile_refused(self):
        p=coupled_problem(5)
        with PreparedThermochemical2D(p) as q:r=q.advance(initial(p),.001,source='decode')
        d=r.state.descriptor();d['step_record']['nonlinear_mechanics']['profile_id']='0'*64
        with self.assertRaises(TectonicsError):ThermochemicalState.restore(d,{k:r.state.array(k) for k in ('temperature_k','composition')})
    def test_stage_diagnostics_are_detached(self):
        p=coupled_problem(5)
        with PreparedThermochemical2D(p) as q:r=q.advance(initial(p),.001,source='detach')
        d=r.state.descriptor();d['step_record']['nonlinear_mechanics']['stages'].clear()
        self.assertEqual(len(r.state.descriptor()['step_record']['nonlinear_mechanics']['stages']),2)


class CoupledPersistence(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'states.sqlite';self.p=coupled_problem(4)
        with PreparedThermochemical2D(self.p) as q:
            self.s=q.advance(initial(self.p),.001,source='first').state
            self.expected=q.advance(self.s,.001,source='second').state
    def tearDown(self):self.tmp.cleanup()
    def store(self):return ArrayStore(self.path,StoreLimits(4096,16<<20,64<<20))
    def test_reopen_and_exact_continuation(self):
        with self.store() as store:save_thermochemical_state(self.s,store)
        with self.store() as store:s=load_thermochemical_state(store,self.s.state_id)
        with PreparedThermochemical2D(s.problem) as q:r=q.advance(s,.001,source='second').state
        self.assertEqual(r.state_id,self.expected.state_id)
        self.assertEqual(r.descriptor()['problem']['mechanical_mode'],'variable-r4.3')
    def test_duplicate_state_adds_no_chunks(self):
        with self.store() as store:
            save_thermochemical_state(self.s,store);n=store.statistics()['unique_chunks']
            save_thermochemical_state(self.s,store);self.assertEqual(store.statistics()['unique_chunks'],n)
    def test_fresh_process_continuation(self):
        with self.store() as store:save_thermochemical_state(self.s,store)
        code='''import sys
sys.dont_write_bytecode=True
sys.path.insert(0,sys.argv[1])
from atlas_tectonics import *
from atlas_tectonics.storage import ArrayStore,StoreLimits
with ArrayStore(sys.argv[2],StoreLimits(4096,16<<20,64<<20)) as s:r=load_thermochemical_state(s,sys.argv[3])
with PreparedThermochemical2D(r.problem) as p:r=p.advance(r,.001,source='second').state
print(r.state_id)
'''
        env=dict(os.environ,OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1',MKL_NUM_THREADS='1',PYTHONDONTWRITEBYTECODE='1')
        result=subprocess.run([sys.executable,'-I','-B','-c',code,str(ROOT/'src'),str(self.path),self.s.state_id],env=env,capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stderr);self.assertEqual(result.stdout.strip(),self.expected.state_id)
