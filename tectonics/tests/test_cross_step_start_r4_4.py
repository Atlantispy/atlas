"""Explicit accepted-state seeds: equations, immutable publication and recovery.
SPDX-License-Identifier: AGPL-3.0-only
"""
from concurrent.futures import CancelledError
from dataclasses import asdict,replace
from pathlib import Path
import inspect,json,os,shutil,subprocess,sys,tempfile,unittest
from unittest import mock
import numpy as np
import atlas_tectonics as at
from atlas_tectonics import thermochemical_execution as tx
from atlas_tectonics.resources import WorkBudget,MemoryLimitError
from atlas_tectonics.storage import ArrayStore,StoreLimits
from variable_stokes_fixtures import coupled_problem,independent_nonlinear_two_cell_rhs
from thermochemical_fixtures import initial,problem,rest
ROOT=Path(__file__).resolve().parents[1]
ENV={**os.environ,'OPENBLAS_NUM_THREADS':'1','OMP_NUM_THREADS':'1','MKL_NUM_THREADS':'1','NUMBA_NUM_THREADS':'1'}
MODE='previous-stage1'


def plan(p,**kw):return at.PreparedThermochemical2D(p,nonlinear_start=MODE,**kw)
def meta_arrays(s):return s.descriptor(),{k:s.array(k).copy() for k in s.array_names}
def records(s):return s.descriptor()['step_record']['nonlinear_mechanics']


class CrossStepTests(unittest.TestCase):
    def setUp(self):self.p=coupled_problem(4);self.s=initial(self.p)
    def first(self,**kw):
        with plan(self.p,**kw) as q:return q.advance(self.s,.001,source='cross check').state
    def two(self,**kw):
        with plan(self.p,**kw) as q:
            a=q.advance(self.s,.001,source='cross check').state
            b=q.advance(a,.001,source='cross check').state
        return a,b
    def test_initial_state_is_unseeded_and_legacy_schema(self):
        self.assertIsNone(self.s.next_initial_guess);self.assertEqual(self.s.array_names,('temperature_k','composition'))
        self.assertEqual(self.s.descriptor()['schema'],'atlas.thermochemical-state.v1')
    def test_policy_is_explicit_bound_and_immutable(self):
        with plan(self.p) as a,at.PreparedThermochemical2D(self.p,nonlinear_start='rk-stage0') as b:
            self.assertNotEqual(a.identity,b.identity)
            with self.assertRaises(at.TectonicsError):a.nonlinear_start='rk-stage0'
        self.assertEqual(inspect.signature(at.PreparedThermochemical2D).parameters['nonlinear_start'].default,'zero-rate')
    def test_first_step_is_cold_then_current_intra_step_guess(self):
        a=self.first();m=records(a);x,y=m['stages']
        self.assertIsNone(x['initial_guess_id']);self.assertIsNone(m['cross_step_start']['input_guess_id'])
        self.assertEqual(y['initial_guess_result_id'],x['result_id'])
        self.assertEqual(a.next_initial_guess.descriptor()['source_result_id'],y['result_id'])
    def test_next_step_consumes_exact_previous_second_stage(self):
        a,b=self.two();m=records(b)
        self.assertEqual(m['stages'][0]['initial_guess_id'],a.next_initial_guess.guess_id)
        self.assertEqual(m['stages'][0]['initial_guess_result_id'],records(a)['stages'][1]['result_id'])
        self.assertEqual(m['cross_step_start']['input_state_id'],a.state_id)
        self.assertEqual(m['stages'][1]['initial_guess_result_id'],m['stages'][0]['result_id'])
    def test_state_seed_velocity_is_second_stage_not_first(self):
        with plan(self.p) as q:r=q.advance(self.s,.01,source='capture')
        for component in ('u','w'):
            np.testing.assert_array_equal(r.state.next_initial_guess.array(component+'_m_s'),r.array(component+'_stage1_m_s'))
        self.assertEqual(r.state.next_initial_guess.descriptor()['time_s'],r.state.time_s)
    def test_state_seed_and_properties_are_immutable(self):
        a=self.first()
        with self.assertRaises(at.TectonicsError):a._next_initial_guess=None
        for key in a.array_names:
            with self.assertRaises(ValueError):a.array(key).flat[0]=0
        m=a.descriptor();m['next_initial_guess']['guess_id']='0'*64
        self.assertNotEqual(a.next_initial_guess.guess_id,'0'*64)
        with self.assertRaises(at.TectonicsError):a.array('next_guess_invalid')
    def test_self_contained_v2_roundtrip(self):
        a=self.first();m,arr=meta_arrays(a);b=at.ThermochemicalState.restore(m,arr)
        self.assertEqual(a.state_id,b.state_id);self.assertEqual(m['schema'],'atlas.thermochemical-state.v2')
        self.assertEqual(len(arr),5)
        for key in arr:np.testing.assert_array_equal(a.array(key),b.array(key));arr[key][:]=0
        self.assertEqual(a.next_initial_guess.guess_id,b.next_initial_guess.guess_id)
    def test_legacy_roundtrip_has_no_silent_seed(self):
        for mode in ('zero-rate','rk-stage0'):
            with at.PreparedThermochemical2D(self.p,nonlinear_start=mode) as q:a=q.advance(self.s,.001,source='old').state
            m,arr=meta_arrays(a);b=at.ThermochemicalState.restore(m,arr)
            self.assertIsNone(b.next_initial_guess);self.assertEqual(a.state_id,b.state_id)
            self.assertNotIn('next_initial_guess',m)
    def test_missing_seed_fields_refused(self):
        a=self.first()
        for key in a.array_names[2:]:
            m,arr=meta_arrays(a);del arr[key]
            with self.assertRaises(at.TectonicsError):at.ThermochemicalState.restore(m,arr)
    def test_changed_seed_bytes_refused(self):
        a=self.first()
        for key in a.array_names[2:]:
            m,arr=meta_arrays(a);arr[key][1,1]+=.01
            with self.assertRaises(at.TectonicsError):at.ThermochemicalState.restore(m,arr)
    def test_missing_descriptor_refused(self):
        m,arr=meta_arrays(self.first());del m['next_initial_guess']
        with self.assertRaises(at.TectonicsError):at.ThermochemicalState.restore(m,arr)
    def test_changed_guess_identity_refused(self):
        m,arr=meta_arrays(self.first());m['next_initial_guess']['guess_id']='0'*64
        with self.assertRaises(at.TectonicsError):at.ThermochemicalState.restore(m,arr)
    def test_schema_downgrade_and_unknown_schema_refused(self):
        a=self.first()
        for name in ('atlas.thermochemical-state.v1','unknown'):
            m,arr=meta_arrays(a);m['schema']=name
            with self.assertRaises(at.TectonicsError):at.ThermochemicalState.restore(m,arr)
    def test_v1_cannot_smuggle_next_guess(self):
        m,arr=meta_arrays(self.s);m['next_initial_guess']={'guess_id':'0'*64}
        with self.assertRaises(at.TectonicsError):at.ThermochemicalState.restore(m,arr)
    def test_stale_or_foreign_output_seed_refused(self):
        a,b=self.two();m,arr=meta_arrays(b);prior,prior_arr=meta_arrays(a)
        m['next_initial_guess']=prior['next_initial_guess']
        for k in arr:
            if k.startswith('next_guess_'):arr[k]=prior_arr[k]
        with self.assertRaises(at.TectonicsError):at.ThermochemicalState.restore(m,arr)
    def test_cross_provenance_tampering_refused(self):
        a,b=self.two()
        for key in ('input_state_id','input_guess_id','input_stage1_result_id','mechanical_plan_id','output_guess_id'):
            m,arr=meta_arrays(b);m['step_record']['nonlinear_mechanics']['cross_step_start'][key]='0'*64
            with self.assertRaises(at.TectonicsError):at.ThermochemicalState.restore(m,arr)
    def test_missing_cross_provenance_refused(self):
        m,arr=meta_arrays(self.first());del m['step_record']['nonlinear_mechanics']['cross_step_start']
        with self.assertRaises(at.TectonicsError):at.ThermochemicalState.restore(m,arr)
    def test_late_cold_first_stage_refused(self):
        a,b=self.two();m,arr=meta_arrays(b);nm=m['step_record']['nonlinear_mechanics']
        nm['stages'][0]['initial_guess_id']=None;nm['stages'][0]['initial_guess_result_id']=None
        nm['cross_step_start']['input_guess_id']=None;nm['cross_step_start']['input_stage1_result_id']=None
        with self.assertRaises(at.TectonicsError):at.ThermochemicalState.restore(m,arr)
    def test_initial_state_cannot_forge_seed(self):
        a=self.first()
        with self.assertRaises(at.TectonicsError):
            at.ThermochemicalState(self.p,self.s.array('temperature_k'),self.s.array('composition'),time_s=0.,source='bad',next_initial_guess=a.next_initial_guess)
    def test_unused_starting_mode_refused(self):
        with self.assertRaises(at.TectonicsError):plan(problem())
        with plan(self.p) as q:
            with self.assertRaises(at.TectonicsError):q.advance(self.s,.001,source='bad',velocity=rest(self.p))
    def test_modes_cannot_resume_each_other(self):
        a=self.first()
        with at.PreparedThermochemical2D(self.p,nonlinear_start='rk-stage0') as q:
            with self.assertRaisesRegex(at.TectonicsError,'source/policy'):q.advance(a,.001,source='bad')
            old=q.advance(self.s,.001,source='old').state
        with plan(self.p) as q:
            with self.assertRaisesRegex(at.TectonicsError,'source/policy'):q.advance(old,.001,source='bad')
    def test_algorithm_switch_cannot_resume(self):
        a=self.first()
        with plan(self.p,anderson_policy=at.AndersonPolicy()) as q:
            with self.assertRaises(at.TectonicsError):q.advance(a,.001,source='bad')
    def test_unrelated_requests_do_not_replace_starting_input(self):
        with plan(self.p) as q:
            a=q.advance(self.s,.001,source='repeat').state
            b=q.advance(a,.001,source='repeat')
            q.advance(self.s,.002,source='other')
            c=q.advance(a,.001,source='repeat')
        self.assertEqual(b.result_id,c.result_id)
    def test_endpoint_sampling_uses_accepted_seed_without_replacing_it(self):
        with plan(self.p,anderson_policy=at.AndersonPolicy()) as q:
            a=q.advance(self.s,.001,source='first').state
            b=q.advance(a,.001,source='second')
            f=q.mechanical_snapshot(a,source='different endpoint label')
            self.assertEqual(f.descriptor()['initial_guess']['guess_id'],a.next_initial_guess.guess_id)
            c=q.advance(a,.001,source='second')
        self.assertEqual(b.result_id,c.result_id)
    def test_saved_next_data_has_no_recursive_ancestor_arrays(self):
        with plan(self.p) as q:
            s=self.s
            for _ in range(5):s=q.advance(s,.001,source='chain').state
        self.assertEqual(len(s.array_names),5)
        gm=s.next_initial_guess.descriptor();self.assertNotIn('initial_guess',gm);self.assertNotIn('parent',gm)
        self.assertLess(len(json.dumps(s.descriptor())),16000)
    def test_direct_route_and_reference_transport(self):
        a,b=self.two(nonlinear_policy=at.NonlinearStokesPolicy(method='direct'))
        c,d=self.two(backend='reference')
        for k in ('temperature_k','composition'):np.testing.assert_allclose(b.array(k),d.array(k),rtol=0,atol=1e-9)
    def test_picard_and_anderson_unchanged_gates(self):
        for ap in (None,at.AndersonPolicy()):
            a,b=self.two(anderson_policy=ap)
            for stage in records(b)['stages']:
                self.assertLessEqual(stage['diagnostics']['momentum_linf'],1e-9)
                self.assertLessEqual(stage['diagnostics']['divergence_linf'],1e-10)
            self.assertEqual(records(b)['policy'],asdict(at.NonlinearStokesPolicy()))
            for k in ('heat_relative_residual','composition_relative_residual','advective_local_residual'):
                self.assertLessEqual(b.descriptor()['step_record']['balances'][k],1e-11)
    def test_cold_comparison_over_multiple_steps(self):
        out=[]
        for mode in ('rk-stage0',MODE):
            with at.PreparedThermochemical2D(self.p,nonlinear_start=mode,anderson_policy=at.AndersonPolicy()) as q:
                s=self.s
                for _ in range(5):s=q.advance(s,.001,source='comparison').state
                f=q.mechanical_snapshot(s,source='comparison endpoint')
                out.append((s,f))
        for k in ('temperature_k','composition'):np.testing.assert_allclose(out[0][0].array(k),out[1][0].array(k),rtol=0,atol=1e-9)
        for k in ('u_m_s','w_m_s','pressure_pa'):np.testing.assert_allclose(out[0][1].array(k),out[1][1].array(k),rtol=1e-7,atol=1e-9)
    def test_independent_ode_temporal_refinement(self):
        from scipy.integrate import solve_ivp
        p=coupled_problem(2);s=initial(p);y=np.r_[s.array('temperature_k').ravel(),s.array('composition').ravel()];end=.5
        ref=solve_ivp(lambda t,y:independent_nonlinear_two_cell_rhs(p,y),(0.,end),y,method='DOP853',rtol=1e-12,atol=1e-13)
        self.assertTrue(ref.success);err=[]
        for n in (2,4,8):
            with plan(p,anderson_policy=at.AndersonPolicy()) as q:
                st=s
                for _ in range(n):st=q.advance(st,end/n,source='independent reference').state
            err.append(float(np.max(np.abs(np.r_[st.array('temperature_k').ravel(),st.array('composition').ravel()]-ref.y[:,-1]))))
        self.assertLess(err[-1],1e-8)
        for x,y in zip(err,err[1:]):self.assertGreater(x/y,3.5);self.assertLess(x/y,4.5)
    def test_changed_heating_and_step_interval_with_same_seed(self):
        a=self.first()
        with plan(self.p) as q:
            x=q.advance(a,.002,source='new forcing',extra_heating_w_m3=.001)
            y=q.advance(a,.002,source='new forcing',extra_heating_w_m3=.001)
        self.assertEqual(x.result_id,y.result_id);self.assertEqual(records(x.state)['stages'][0]['initial_guess_id'],a.next_initial_guess.guess_id)
    def test_restore_budget_refusal_preserves_type(self):
        a=self.first();b=WorkBudget(1024)
        with self.assertRaises(MemoryLimitError):at.ThermochemicalState.restore(*meta_arrays(a),budget=b)
        self.assertEqual(b.reserved_bytes,0)
    def test_step_budget_refusal_keeps_input(self):
        b=WorkBudget(128<<20)
        with plan(self.p,budget=b) as q:
            a=q.advance(self.s,.001,source='first').state;sid=a.state_id;gid=a.next_initial_guess.guess_id
            with b.reserve(b.available_bytes-1024,category='test-hold'):
                with self.assertRaises(MemoryLimitError):q.advance(a,.001,source='next')
            actual=q.advance(a,.001,source='next')
            self.assertEqual(a.state_id,sid);self.assertEqual(a.next_initial_guess.guess_id,gid)
        self.assertEqual(b.reserved_bytes,0);self.assertEqual(actual.state.step_index,2)
    def test_pre_cancel_leaves_checkpoint_unchanged(self):
        class Cancel:
            def is_set(self):return True
        a=self.first();sid=a.state_id;gid=a.next_initial_guess.guess_id
        with plan(self.p) as q:
            with self.assertRaises(CancelledError):q.advance(a,.001,source='next',cancel=Cancel())
        self.assertEqual((a.state_id,a.next_initial_guess.guess_id),(sid,gid))
    def test_late_cancel_and_fault_do_not_publish_or_poison(self):
        # Inject through the supported cancellation protocol, not a changed callable.
        class Interrupt:
            def __init__(self,fault):self.fault=fault;self.hit=False
            def is_set(self):
                f=inspect.currentframe().f_back
                try:
                    while f:
                        if f.f_code.co_name=='advance' and 'next_guess' in f.f_locals and f.f_locals['next_guess'] is not None:
                            self.hit=True
                            if self.fault:raise at.TectonicsError('injected pre-publication fault')
                            return True
                        f=f.f_back
                    return False
                finally:del f
        a=self.first();before=meta_arrays(a)
        for fault in (False,True):
            b=WorkBudget(128<<20);cancel=Interrupt(fault)
            with plan(self.p,budget=b,anderson_policy=None) as q:
                with self.assertRaises(at.TectonicsError if fault else CancelledError):q.advance(a,.001,source='next',cancel=cancel)
                self.assertTrue(cancel.hit);actual=q.advance(a,.001,source='next')
            with plan(self.p) as q:expected=q.advance(a,.001,source='next')
            self.assertEqual(actual.result_id,expected.result_id);self.assertEqual(b.reserved_bytes,0)
        self.assertEqual(a.descriptor(),before[0])
        for k,v in before[1].items():np.testing.assert_array_equal(v,a.array(k))
    def test_source_mutation_refused(self):
        a=self.first()
        with plan(self.p) as q:
            with mock.patch.object(tx,'_check_step_record',lambda *a:None):
                with self.assertRaises(at.TectonicsError):q.advance(a,.001,source='bad')
    def test_self_contained_store_needs_no_parent_record(self):
        a,b=self.two()
        with tempfile.TemporaryDirectory() as tmp:
            with ArrayStore(Path(tmp)/'state.sqlite',StoreLimits(4096,16<<20,64<<20)) as store:
                at.save_thermochemical_state(b,store);self.assertIsNone(store.metadata(a.state_id))
                c=at.load_thermochemical_state(store,b.state_id)
        with plan(self.p) as q:expected=q.advance(b,.001,source='next')
        with plan(self.p) as q:actual=q.advance(c,.001,source='next')
        self.assertEqual(expected.result_id,actual.result_id)
    def test_nonunit_geometry_seed_and_reference(self):
        p=replace(self.p,box=replace(self.p.box,width_m=2.,height_m=.75),scales=replace(self.p.scales,length_m=3.,viscosity_pa_s=7.))
        state=initial(p);out=[]
        for mode in ('rk-stage0',MODE):
            with at.PreparedThermochemical2D(p,nonlinear_start=mode) as q:
                s=state
                for _ in range(3):s=q.advance(s,.001,source='nonunit').state
                out.append(s)
        for k in ('temperature_k','composition'):np.testing.assert_allclose(out[0].array(k),out[1].array(k),rtol=0,atol=1e-9)


    def test_second_stage_failure_keeps_checkpoint_and_does_not_retry(self):
        class Fault:
            def __init__(self):self.hits=0
            def is_set(self):
                f=inspect.currentframe().f_back
                try:
                    while f:
                        if (f.f_code.co_name=='_anderson_solve' and
                                'RK stage 1' in f.f_locals.get('source','') and
                                len(f.f_locals.get('history',[]))>=1):
                            self.hits+=1;raise at.TectonicsError('cross-stage injected failure')
                        f=f.f_back
                    return False
                finally:del f
        with plan(self.p,anderson_policy=at.AndersonPolicy()) as q:
            a=q.advance(self.s,.001,source='first').state;sid=a.state_id;gid=a.next_initial_guess.guess_id;fault=Fault()
            with self.assertRaisesRegex(at.TectonicsError,'injected failure'):q.advance(a,.001,source='next',cancel=fault)
            self.assertEqual(fault.hits,1)
            actual=q.advance(a,.001,source='next')
        with plan(self.p,anderson_policy=at.AndersonPolicy()) as q:expected=q.advance(a,.001,source='next')
        self.assertEqual(actual.result_id,expected.result_id);self.assertEqual((a.state_id,a.next_initial_guess.guess_id),(sid,gid))
    def test_rehashed_seed_still_requires_correct_time_plan_and_result(self):
        # Hash consistency alone must not evade cross-state semantic bindings.
        a=self.first();old=a.next_initial_guess
        for key,value in (('time_s',a.time_s+1.),('plan_id','0'*64),('source_result_id','0'*64),('epoch_id','different')):
            gm=old.descriptor();gm[key]=value
            guess=object.__new__(at.NonlinearStokesGuess)
            guess._capture(gm,{k:old.array(k) for k in ('u_m_s','w_m_s','pressure_pa')},None)
            m=a.descriptor();rec=m['step_record'];rec['nonlinear_mechanics']['cross_step_start']['output_guess_id']=guess.guess_id
            with self.assertRaises(at.TectonicsError):
                at.ThermochemicalState(self.p,a.array('temperature_k'),a.array('composition'),
                    time_s=a.time_s,source=m['source'],parent_id=m['parent_id'],step_index=a.step_index,
                    execution_id=m['execution_id'],step_record=rec,next_initial_guess=guess)
    def test_no_zero_filling_for_missing_pressure(self):
        m,arr=meta_arrays(self.first());del arr['next_guess_pressure_pa']
        with self.assertRaises(at.TectonicsError):at.ThermochemicalState.restore(m,arr)
    def test_new_plan_uses_checkpoint_not_prior_instance(self):
        a,b=self.two(anderson_policy=at.AndersonPolicy())
        with plan(self.p,anderson_policy=at.AndersonPolicy()) as q:c=q.advance(a,.001,source='cross check').state
        self.assertEqual(c.state_id,b.state_id)
    def test_registered_contract_matches_integration(self):
        d=json.loads((ROOT/'cases/cross_step_start_r4_4.json').read_text())
        self.assertEqual(d['mode'],MODE);self.assertEqual(d['state_schema'],'atlas.thermochemical-state.v2')
        self.assertEqual(d['seed_fields'],['u_m_s','w_m_s','pressure_pa'])
        self.assertFalse(d['hidden_plan_seed']);self.assertFalse(d['R4_complete'])


class CrossRunnerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory(prefix='atlas-cross-runner-');cls.base=Path(cls.tmp.name);cls.ref=cls.base/'reference'
        a=cls.execute(cls.ref,False,4)
        if a.returncode:raise RuntimeError(a.stdout+a.stderr)
        cls.expected=json.loads(a.stdout.splitlines()[-1])['last_state_id']
    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()
    @staticmethod
    def execute(out,resume,steps,*extra):
        args=['--resume'] if resume else ['--case','tosi-2','--cells','4','--dt','1e-5','--max-steps','6','--sample-every','1','--save-every','2','--nonlinear-start',MODE,'--nonlinear-solver','anderson']
        return subprocess.run([sys.executable,'-I','-B',str(ROOT/'tools/run_convection_r4_4.py'),'--output',str(out),'--segment-steps',str(steps),*args,*extra],capture_output=True,text=True,env=ENV,timeout=90)
    def test_fresh_process_resume_matches(self):
        out=self.base/'split';a=self.execute(out,False,2);self.assertEqual(a.returncode,0,a.stdout+a.stderr)
        b=self.execute(out,True,2);self.assertEqual(b.returncode,0,b.stdout+b.stderr)
        m=json.loads(b.stdout.splitlines()[-1]);self.assertEqual(m['last_state_id'],self.expected);self.assertEqual(m['budget_after_close']['reserved_bytes'],0)
    def test_auditor_accepts_full_chain_and_seeded_store(self):
        sys.path.insert(0,str(ROOT/'tools'));import analyse_convection_r4_4 as audit
        a=audit.analyse_run(self.ref);self.assertEqual(a['accepted_step_count'],4);self.assertFalse(a['full_benchmark_accepted'])
    def test_resume_cannot_resupply_policy(self):
        a=self.execute(self.ref,True,1,'--nonlinear-start','rk-stage0');self.assertNotEqual(a.returncode,0);self.assertIn('do not resupply',a.stderr)
    def test_rehashed_receipt_cannot_change_parent_seed(self):
        sys.path.insert(0,str(ROOT/'tools'));import analyse_convection_r4_4 as audit
        from run_convection_r4_4 import encode,digest
        out=self.base/'tampered';shutil.copytree(self.ref,out)
        previous=None
        for f in sorted(out.glob('receipt_*.json')):
            d=json.loads(f.read_bytes());d['parent_receipt']=previous
            for step in d['stage_iteration_counts']:
                if step['step']==2:step['cross_step_start']['input_guess_id']='0'*64
            f.write_bytes(encode(d));previous=digest(f.read_bytes())
        with self.assertRaises(ValueError):audit.read_run(out)

if __name__=='__main__':unittest.main()
