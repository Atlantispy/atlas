"""Integrated Anderson: independent numerical, policy, ownership and recovery checks.
SPDX-License-Identifier: AGPL-3.0-only
"""
from __future__ import annotations
from pathlib import Path
from dataclasses import asdict, replace
from concurrent.futures import CancelledError
import inspect, json, os, shutil, subprocess, sys, tempfile, threading, unittest
from unittest import mock
import numpy as np
import atlas_tectonics as at
from atlas_tectonics import anderson as aa, variable_stokes_execution as vx
from atlas_tectonics.resources import WorkBudget, MemoryLimitError
from atlas_tectonics.storage import ArrayStore, StoreLimits
from stokes_fixtures import unit_box,unit_scales,request
from variable_stokes_fixtures import forcing,independent_two_cell_amplitude,coupled_problem,independent_nonlinear_two_cell_rhs
from thermochemical_fixtures import initial
ROOT=Path(__file__).resolve().parents[1]
ENV={**os.environ,'OPENBLAS_NUM_THREADS':'1','MKL_NUM_THREADS':'1','OMP_NUM_THREADS':'1','NUMBA_NUM_THREADS':'1'}
FIELDS=('u_m_s','w_m_s','pressure_pa','viscosity_cell_pa_s','viscosity_vertex_pa_s')


def solve(plan, inputs=None, **kwargs):
    b,sc,fx,fz,temp,rp=forcing(4) if inputs is None else inputs
    return plan.solve_rheology(fx,fz,temp,rp,**request(b),**kwargs)


def assert_fields(test,a,b):
    for k in FIELDS:
        x=a.array(k);y=b.array(k)
        test.assertLessEqual(float(np.max(np.abs(x-y))),1e-9+1e-7*float(np.max(np.abs(x))),k)


class ProposalTests(unittest.TestCase):
    def test_package_metadata_matches_runtime_version(self):
        import tomllib
        metadata=tomllib.loads((ROOT/'pyproject.toml').read_text())
        self.assertEqual(metadata['project']['version'],at.__version__)

    def test_scalar_linear_map_matches_analytic_fixed_point(self):
        images=[np.array([1.]),np.array([1.8])]
        errors=[np.array([1.]),np.array([.8])]
        result,details=aa._propose(images,errors,1,aa.AndersonPolicy())
        self.assertAlmostEqual(result[0],5.,places=13)
        self.assertAlmostEqual(details['coefficient_sum'],1.)
    def test_full_vector_uses_velocity_fitted_affine_coefficients(self):
        images=[np.array([1.,3.]),np.array([1.8,7.])]
        errors=[np.array([1.,9000.]),np.array([.8,-8000.])]
        result,details=aa._propose(images,errors,1,aa.AndersonPolicy())
        np.testing.assert_allclose(result,[5.,23.],rtol=1e-14,atol=1e-14)
    def test_rank_deficiency_drops_oldest_differences(self):
        images=[np.array([float(i),2.*i]) for i in range(3)]
        errors=[np.array([float(i+1),2.*(i+1)]) for i in range(3)]
        result,d=aa._propose(images,errors,2,aa.AndersonPolicy())
        self.assertIsNotNone(result);self.assertEqual(d['depth_used'],1);self.assertEqual(d['rank_drops'],1)
    def test_zero_history_is_refused(self):
        result,d=aa._propose([np.ones(2),np.ones(2)],[np.zeros(2),np.zeros(2)],2,aa.AndersonPolicy())
        self.assertIsNone(result)
    def test_repeated_nonzero_residual_is_rank_deficient(self):
        result,d=aa._propose([np.ones(2),np.zeros(2)],[np.ones(2),np.ones(2)],2,aa.AndersonPolicy())
        self.assertIsNone(result);self.assertEqual(d['reason'],'rank_deficient')
    def test_large_mixing_coefficients_are_rejected(self):
        result,d=aa._propose([np.ones(1),np.ones(1)*2],[np.ones(1),np.ones(1)*1.001],1,aa.AndersonPolicy())
        self.assertIsNone(result);self.assertEqual(d['reason'],'coefficient_bound')
    def test_nonfinite_history_is_rejected(self):
        result,d=aa._propose([np.ones(2),np.ones(2)],[np.ones(2),np.full(2,np.nan)],2,aa.AndersonPolicy())
        self.assertIsNone(result)
    def test_lstsq_failure_is_an_explicit_proposal_rejection(self):
        with mock.patch.object(aa,'_least_squares',side_effect=np.linalg.LinAlgError('injected')):
            result,d=aa._propose([np.ones(1),np.ones(1)*2],[np.ones(1),np.ones(1)*.8],1,aa.AndersonPolicy())
        self.assertIsNone(result);self.assertEqual(d['reason'],'least_squares_failure')
    def test_input_vectors_unchanged_and_result_owned(self):
        images=[np.array([1.,2.]),np.array([1.8,3.6])]
        errors=[np.array([1.,2.]),np.array([.8,1.6])]
        before=[a.copy() for a in images+errors]
        for a in images+errors:a.flags.writeable=False
        result,d=aa._propose(images,errors,2,aa.AndersonPolicy())
        for a,b in zip(images+errors,before):np.testing.assert_array_equal(a,b)
        self.assertFalse(any(np.shares_memory(result,x) for x in images+errors))
    def test_maximum_history_depth_is_respected(self):
        rng=np.random.default_rng(3)
        images=[rng.normal(size=10) for _ in range(8)];errors=[rng.normal(size=10) for _ in range(8)]
        result,d=aa._propose(images,errors,10,aa.AndersonPolicy(depth=3))
        self.assertLessEqual(d.get('depth_used',0),3)
    def test_policy_invalid_depths(self):
        for value in (-1,0,11,True,1.2):
            with self.subTest(value=value),self.assertRaises(ValueError):aa.AndersonPolicy(depth=value)
    def test_policy_invalid_limits(self):
        for kw in ({'rcond':0.},{'rcond':1.},{'rcond':float('nan')},{'coefficient_l1_limit':.9},{'coefficient_l1_limit':float('inf')},{'warmup_maps':1}):
            with self.subTest(kw=kw),self.assertRaises(ValueError):aa.AndersonPolicy(**kw)
    def test_policy_is_immutable(self):
        p=aa.AndersonPolicy()
        with self.assertRaises(AttributeError):p.depth=1
    def test_diagnostics_merit_accounts_for_each_physical_gate(self):
        pol=at.NonlinearStokesPolicy()
        d={'momentum_linf':0.,'divergence_linf':0.,'pressure_gauge_relative':0.,'gauge_multiplier_abs':0.,'work_balance_relative':0.}
        for k,limit in [('momentum_linf',pol.momentum_tolerance),('divergence_linf',pol.divergence_tolerance),('pressure_gauge_relative',pol.gauge_tolerance),('gauge_multiplier_abs',pol.divergence_tolerance),('work_balance_relative',pol.work_balance_tolerance)]:
            x=dict(d);x[k]=2*limit;self.assertEqual(aa._merit(x,pol),2.)


class IntegratedAndersonTests(unittest.TestCase):
    def plan(self,**kwargs):
        b,sc,*_=forcing(4)
        p=at.PreparedVariableStokes2D(b,sc,anderson_policy=at.AndersonPolicy(),**kwargs)
        self.addCleanup(p.close);return p
    def test_explicit_policy_is_in_plan_identity(self):
        p=self.plan()
        with at.PreparedVariableStokes2D(p.box,p.scales) as q:self.assertNotEqual(p.identity,q.identity)
    def test_policy_is_immutable_on_plan(self):
        p=self.plan()
        with self.assertRaises(at.TectonicsError):p.anderson_policy=None
    def test_unused_prescribed_viscosity_policy_refused(self):
        p=self.plan();b=p.box
        with self.assertRaisesRegex(at.TectonicsError,'unused'):
            p.solve(np.zeros((4,3)),np.zeros((3,4)),np.ones((4,4)),np.ones((3,3)),**request(b))
    def test_nonfull_relaxation_refused_before_reservation(self):
        budget=WorkBudget(256<<20)
        with self.assertRaisesRegex(at.TectonicsError,'relaxation'):
            self.plan(policy=at.NonlinearStokesPolicy(relaxation=.5),budget=budget)
        self.assertEqual(budget.reserved_bytes,0)
    def test_untyped_policy_refused(self):
        with self.assertRaises(at.TectonicsError):at.PreparedVariableStokes2D(unit_box(2),unit_scales(),anderson_policy={})
    def test_accelerated_matches_independent_direct(self):
        p=self.plan();a=solve(p)
        with at.PreparedVariableStokes2D(p.box,p.scales,policy=at.NonlinearStokesPolicy(method='direct')) as q:b=solve(q)
        assert_fields(self,b,a)
    def test_picard_metadata_stays_without_acceleration(self):
        p=self.plan()
        with at.PreparedVariableStokes2D(p.box,p.scales) as q:r=solve(q)
        self.assertNotIn('nonlinear_acceleration',r.descriptor())
        self.assertTrue(all('anderson' not in v for v in r.descriptor()['nonlinear_history']))
    def test_result_has_valid_algorithm_policy_and_history(self):
        r=solve(self.plan());m=r.descriptor();aa.check_history(m['nonlinear_history'],m['nonlinear_acceleration'])
        self.assertEqual(m['nonlinear_acceleration']['policy'],asdict(at.AndersonPolicy()))
        self.assertGreater(m['nonlinear_acceleration']['accepted_mixed_updates'],0)
    def test_acceptance_requires_unmixed_final_image(self):
        r=solve(self.plan());m=r.descriptor()
        self.assertEqual(m['nonlinear_history'][-1]['anderson']['action'],'not_proposed')
        self.assertLessEqual(m['diagnostics']['momentum_linf'],1e-9)
        self.assertLessEqual(m['nonlinear_history'][-1]['viscosity_log_change'],1e-8)
    def test_typed_result_reconstruction_exact(self):
        r=solve(self.plan());q=at.VariableStokesSolution(r.descriptor(),{k:r.array(k) for k in r.array_names})
        self.assertEqual(r.result_id,q.result_id)
    def test_result_arrays_and_metadata_detached(self):
        r=solve(self.plan())
        with self.assertRaises(ValueError):r.array('u_m_s')[0,1]=42
        m=r.descriptor();m['nonlinear_acceleration']['policy']['depth']=8
        self.assertEqual(r.descriptor()['nonlinear_acceleration']['policy']['depth'],5)
    def test_corrupt_algorithm_record_refused(self):
        r=solve(self.plan());a={k:r.array(k) for k in r.array_names}
        for change in ('method','count','policy','final','remove'):
            with self.subTest(change=change):
                m=r.descriptor();rec=m['nonlinear_acceleration']
                if change=='method':rec['method']='picard'
                if change=='count':rec['accepted_mixed_updates']+=1
                if change=='policy':rec['policy']['depth']=0
                if change=='final':rec['final_acceptance']='small-update'
                if change=='remove':m.pop('nonlinear_acceleration')
                with self.assertRaises(at.TectonicsError):at.VariableStokesSolution(m,a)
    def test_corrupt_accepted_merit_refused(self):
        r=solve(self.plan());m=r.descriptor()
        row=next(x['anderson'] for x in m['nonlinear_history'] if x['anderson']['action']=='accepted')
        row['trial_merit']=row['picard_merit']+1
        with self.assertRaises(at.TectonicsError):at.VariableStokesSolution(m,{k:r.array(k) for k in r.array_names})
    def test_same_request_after_different_request_repeats_exactly(self):
        p=self.plan();a=solve(p);solve(p,initial_guess=at.NonlinearStokesGuess(a));b=solve(p)
        self.assertEqual(a.result_id,b.result_id)
    def test_source_mutation_is_refused(self):
        p=self.plan()
        with mock.patch.object(aa,'_merit',lambda *a:0):
            with self.assertRaises(at.TectonicsError):solve(p)
    def test_least_squares_callable_mutation_is_refused(self):
        p=self.plan()
        with mock.patch.object(aa,'_least_squares',lambda *a,**k:None):
            with self.assertRaises(at.TectonicsError):solve(p)
    def test_policy_constant_mutation_is_refused(self):
        p=self.plan()
        with mock.patch.object(aa,'_FINAL','unchecked'):
            with self.assertRaises(at.TectonicsError):solve(p)
    def test_request_inputs_unchanged(self):
        args=forcing(4);before=[a.copy() for a in args[2:5]]
        solve(self.plan(),args)
        for a,b in zip(args[2:5],before):np.testing.assert_array_equal(a,b)
    def test_empty_history_rejection_preserves_picard_fields(self):
        with mock.patch.object(aa,'_propose',return_value=(None,{'reason':'injected'})):
            p=self.plan();r=solve(p)
            with at.PreparedVariableStokes2D(p.box,p.scales) as q:ref=solve(q)
            p.close()
        for k in FIELDS:np.testing.assert_array_equal(r.array(k),ref.array(k))
        self.assertEqual(r.descriptor()['nonlinear_acceleration']['accepted_mixed_updates'],0)
        self.assertGreater(r.descriptor()['nonlinear_acceleration']['rejected_proposals'],0)
    def test_nonfinite_trial_rejected(self):
        with mock.patch.object(aa,'_propose',return_value=(np.full(unit_box(4).unknowns,np.inf),{'depth_used':1})):
            p=self.plan();r=solve(p);p.close()
        self.assertEqual(r.descriptor()['nonlinear_acceleration']['accepted_mixed_updates'],0)
    def test_memory_error_is_not_swallowed_as_rejected_trial(self):
        with mock.patch.object(aa,'_propose',side_effect=MemoryLimitError('injected memory')):
            p=self.plan()
            with self.assertRaises(MemoryLimitError):solve(p)
            p.close()
        self.assertFalse(p._active)
    def test_failed_linear_is_not_retried_or_replaced(self):
        with mock.patch.object(vx.PreparedVariableStokes2D,'_linear',side_effect=at.TectonicsError('injected linear')) as f:
            p=self.plan()
            with self.assertRaisesRegex(at.TectonicsError,'injected linear'):solve(p)
            self.assertEqual(f.call_count,1);p.close()
    def test_iteration_limit_refuses_publication(self):
        p=self.plan(policy=at.NonlinearStokesPolicy(max_picard_iterations=1))
        with self.assertRaisesRegex(at.TectonicsError,'envelope'):solve(p)
        self.assertFalse(p._active)
    def test_precancellation_releases_active_flag(self):
        p=self.plan();e=threading.Event();e.set()
        with self.assertRaises(CancelledError):solve(p,cancel=e)
        self.assertFalse(p._active)
    def test_miditeration_cancel_then_reuse(self):
        class Cancel:
            def __init__(self):self.n=0
            def is_set(self):self.n+=1;return self.n>30
        p=self.plan()
        with self.assertRaises(CancelledError):solve(p,cancel=Cancel())
        a=solve(p);b=solve(self.plan());self.assertEqual(a.result_id,b.result_id)
    def test_history_admission_refusal_releases_budget(self):
        budget=WorkBudget(256<<20);p=self.plan(budget=budget);before=budget.reserved_bytes
        with budget.reserve(budget.available_bytes-p._scratch_bytes()-10000,category='test-hold'):
            with self.assertRaises(MemoryLimitError):solve(p)
        self.assertEqual(budget.reserved_bytes,before);self.assertFalse(p._active)
        p.close();self.assertEqual(budget.reserved_bytes,0)
    def test_foreign_picard_guess_is_not_rebound(self):
        p=self.plan()
        with at.PreparedVariableStokes2D(p.box,p.scales) as q:g=at.NonlinearStokesGuess(solve(q))
        with self.assertRaisesRegex(at.TectonicsError,'policy'):solve(p,initial_guess=g)
    def test_standalone_seeded_store_roundtrip(self):
        p=self.plan();g=at.NonlinearStokesGuess(solve(p));r=solve(p,initial_guess=g)
        with tempfile.TemporaryDirectory() as t:
            path=Path(t)/'s.sqlite'
            with ArrayStore(path,StoreLimits(4096,16<<20,64<<20)) as store:at.save_variable_stokes_solution(r,store)
            with ArrayStore(path,StoreLimits(4096,16<<20,64<<20)) as store:q=at.load_variable_stokes_solution(store,r.result_id)
        self.assertEqual(q.result_id,r.result_id)
    def test_zero_force_produces_exact_zero_and_one_image(self):
        b,sc,fx,fz,T,rp=forcing(4)
        r=solve(self.plan(),(b,sc,fx*0,fz*0,T,rp))
        for k in FIELDS[:3]:np.testing.assert_array_equal(r.array(k),np.zeros_like(r.array(k)))
        self.assertEqual(len(r.descriptor()['nonlinear_history']),1)
    def test_linear_rheology_is_same_single_image(self):
        args=list(forcing(4));args[-1]=at.reference_rheology('tosi-1');p=self.plan();a=solve(p,args)
        with at.PreparedVariableStokes2D(p.box,p.scales) as q:b=solve(q,args)
        for k in FIELDS:np.testing.assert_array_equal(a.array(k),b.array(k))
        self.assertEqual(len(a.descriptor()['nonlinear_history']),1)
    def test_nonunit_scales_rectangular_control(self):
        args=list(forcing(4));args[0]=replace(args[0],width_m=2.,height_m=.75);args[1]=replace(args[1],length_m=3.,viscosity_pa_s=7.)
        with at.PreparedVariableStokes2D(*args[:2],anderson_policy=at.AndersonPolicy()) as p:a=solve(p,args)
        with at.PreparedVariableStokes2D(*args[:2],policy=at.NonlinearStokesPolicy(method='direct')) as p:b=solve(p,args)
        assert_fields(self,b,a)
    def test_independent_scalar_root_under_multiple_forcings(self):
        for force,temp in ((1.,1.6),(-1.3,1.5),(0.,1.6),(.25,1.4)):
            with self.subTest(force=force):
                b=unit_box(2);sc=unit_scales();fx=force*np.array([[1.],[-1.]]);fz=force*np.array([[-1.,1.]])
                with at.PreparedVariableStokes2D(b,sc,anderson_policy=at.AndersonPolicy()) as p:
                    r=p.solve_rheology(fx,fz,np.full((2,2),temp),at.reference_rheology('tosi-2'),**request(b))
                exp=independent_two_cell_amplitude(force,temp)
                self.assertAlmostEqual(r.array('u_m_s')[0,1],exp,delta=1e-7*max(1.,abs(exp)))


class CoupledAndersonTests(unittest.TestCase):
    def setUp(self):
        self.p=coupled_problem(4);self.s=initial(self.p)
    def step(self,**kwargs):
        with at.PreparedThermochemical2D(self.p,anderson_policy=at.AndersonPolicy(),**kwargs) as p:return p.advance(self.s,.001,source='one')
    def test_both_stages_record_same_acceleration_policy(self):
        r=self.step(nonlinear_start='rk-stage0');m=r.state.descriptor()['step_record']['nonlinear_mechanics']
        self.assertEqual(m['anderson_policy'],asdict(at.AndersonPolicy()))
        for st in m['stages']:aa.check_summary(st['nonlinear_acceleration'],st['nonlinear_iterations'],at.AndersonPolicy())
    def test_cold_and_intrastep_modes_pass(self):
        a=self.step();b=self.step(nonlinear_start='rk-stage0')
        for k in ('temperature_k','composition'):np.testing.assert_allclose(a.state.array(k),b.state.array(k),atol=1e-9,rtol=0)
    def test_snapshot_stays_cold_and_preserves_repeat(self):
        with at.PreparedThermochemical2D(self.p,anderson_policy=at.AndersonPolicy(),nonlinear_start='rk-stage0') as p:
            a=p.advance(self.s,.001,source='repeat');f=p.mechanical_snapshot(a.state,source='snapshot')
            self.assertNotIn('initial_guess',f.descriptor());self.assertIn('nonlinear_acceleration',f.descriptor())
            b=p.advance(self.s,.001,source='repeat')
        self.assertEqual(a.result_id,b.result_id)
    def test_wrong_acceleration_policy_cannot_resume(self):
        s=self.step().state
        for ap in (None,at.AndersonPolicy(depth=3)):
            with at.PreparedThermochemical2D(self.p,anderson_policy=ap) as p:
                with self.assertRaisesRegex(at.TectonicsError,'source/policy'):p.advance(s,.001,source='bad')
    def test_store_reopen_continuation_exact(self):
        with at.PreparedThermochemical2D(self.p,anderson_policy=at.AndersonPolicy(),nonlinear_start='rk-stage0') as p:
            a=p.advance(self.s,.001,source='one').state;b=p.advance(a,.001,source='two').state
        with tempfile.TemporaryDirectory() as t:
            path=Path(t)/'s.sqlite'
            with ArrayStore(path,StoreLimits(4096,16<<20,64<<20)) as store:at.save_thermochemical_state(a,store)
            with ArrayStore(path,StoreLimits(4096,16<<20,64<<20)) as store:loaded=at.load_thermochemical_state(store,a.state_id)
        with at.PreparedThermochemical2D(self.p,anderson_policy=at.AndersonPolicy(),nonlinear_start='rk-stage0') as p:c=p.advance(loaded,.001,source='two').state
        self.assertEqual(b.state_id,c.state_id)
    def test_corrupt_stored_policy_and_counts_refused(self):
        s=self.step().state
        for change in ('missing','policy','counts','stage'):
            m=s.descriptor();nm=m['step_record']['nonlinear_mechanics']
            if change=='missing':nm.pop('anderson_policy')
            if change=='policy':nm['anderson_policy']['depth']=4
            if change=='counts':nm['stages'][0]['nonlinear_acceleration']['nonlinear_iterations']+=1
            if change=='stage':nm['stages'][1].pop('nonlinear_acceleration')
            with self.assertRaises(at.TectonicsError):at.ThermochemicalState.restore(m,{k:s.array(k) for k in ('temperature_k','composition')})
    def test_second_stage_cancel_leaves_next_request_clean(self):
        class Cancel:
            def is_set(self):
                frame=inspect.currentframe().f_back
                try:
                    while frame:
                        if frame.f_code.co_name=='_anderson_solve' and frame.f_locals.get('initial_guess') is not None and frame.f_locals.get('history'):return True
                        frame=frame.f_back
                    return False
                finally:del frame
        budget=WorkBudget(256<<20)
        with at.PreparedThermochemical2D(self.p,anderson_policy=at.AndersonPolicy(),nonlinear_start='rk-stage0',budget=budget) as p:
            with self.assertRaises(CancelledError):p.advance(self.s,.001,source='one',cancel=Cancel())
            a=p.advance(self.s,.001,source='one')
        b=self.step(nonlinear_start='rk-stage0');self.assertEqual(a.result_id,b.result_id);self.assertEqual(budget.reserved_bytes,0)
    def test_unused_constant_mode_refused(self):
        from thermochemical_fixtures import problem
        with self.assertRaises(at.TectonicsError):at.PreparedThermochemical2D(problem(4),anderson_policy=at.AndersonPolicy())
    def test_independent_coupled_ode_temporal_order(self):
        from scipy.integrate import solve_ivp
        p=coupled_problem(2);s=initial(p);T=s.array('temperature_k');C=s.array('composition')
        y=np.r_[T.ravel(),C.ravel()];end=.5
        ref=solve_ivp(lambda t,y:independent_nonlinear_two_cell_rhs(p,y),(0,end),y,method='DOP853',rtol=1e-12,atol=1e-13).y[:,-1]
        errors=[]
        for n in (2,4,8):
            state=s
            with at.PreparedThermochemical2D(p,anderson_policy=at.AndersonPolicy(),nonlinear_start='rk-stage0') as q:
                for _ in range(n):state=q.advance(state,end/n,source='ode').state
            errors.append(float(np.max(np.abs(np.r_[state.array('temperature_k').ravel(),state.array('composition').ravel()]-ref))))
        self.assertLess(errors[-1],1e-8)
        for a,b in zip(errors,errors[1:]):self.assertGreater(a/b,3.5);self.assertLess(a/b,4.5)


class AndersonRunnerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.base=Path(cls.temp.name);cls.ref=cls.base/'ref'
        r=cls.execute(cls.ref,False,4)
        if r.returncode:raise RuntimeError(r.stdout+r.stderr)
        cls.expected=json.loads(r.stdout.splitlines()[-1])['last_state_id']
    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()
    @staticmethod
    def execute(output,resume,steps,*extra):
        args=['--resume'] if resume else ['--case','tosi-2','--cells','4','--dt','1e-5','--max-steps','4','--sample-every','1','--save-every','2','--nonlinear-start','rk-stage0','--nonlinear-solver','anderson']
        return subprocess.run([sys.executable,'-I','-B',str(ROOT/'tools/run_convection_r4_4.py'),'--output',str(output),'--segment-steps',str(steps),*args,*extra],env=ENV,capture_output=True,text=True,timeout=120)
    def test_fresh_process_split_equals_uninterrupted(self):
        out=self.base/'split';r=self.execute(out,False,2);self.assertEqual(r.returncode,0,r.stderr)
        r=self.execute(out,True,2);self.assertEqual(r.returncode,0,r.stderr)
        self.assertEqual(json.loads(r.stdout.splitlines()[-1])['last_state_id'],self.expected)
    def test_saved_run_anderson_audits(self):
        sys.path.insert(0,str(ROOT/'tools'));import analyse_convection_r4_4 as audit
        r=audit.analyse_run(self.ref);self.assertFalse(r['full_benchmark_accepted'])
        self.assertEqual(r['configuration']['anderson_policy'],asdict(at.AndersonPolicy()))
    def test_resupplied_algorithm_refused(self):
        r=self.execute(self.ref,True,1,'--nonlinear-solver','picard');self.assertNotEqual(r.returncode,0);self.assertIn('do not resupply',r.stderr)
    def test_source_relocation_copy_matches(self):
        relocated=self.base/'relocated';relocated.mkdir()
        for folder in ('src','tools','cases'):shutil.copytree(ROOT/folder,relocated/folder)
        out=self.base/'relocated_run';r=self.execute(out,False,2);self.assertEqual(r.returncode,0,r.stderr)
        copy=self.base/'copied';shutil.copytree(out,copy)
        r=subprocess.run([sys.executable,'-I','-B',str(relocated/'tools/run_convection_r4_4.py'),'--output',str(copy),'--resume','--segment-steps','2'],env=ENV,capture_output=True,text=True,timeout=120)
        self.assertEqual(r.returncode,0,r.stderr);self.assertEqual(json.loads(r.stdout.splitlines()[-1])['last_state_id'],self.expected)

if __name__=='__main__':unittest.main()
