"""Focused WORKING NON-CANON adaptive-inner integration checks.
SPDX-License-Identifier: AGPL-3.0-only
No mature campaign or full-suite qualification is implied.
"""
from pathlib import Path
import copy
from concurrent.futures import CancelledError
from dataclasses import FrozenInstanceError, asdict
import hashlib
import inspect
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import numpy as np

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'src'), str(ROOT/'tests'), str(ROOT/'tools')]
import atlas_tectonics as at
from atlas_tectonics import adaptive_inner as ai
from atlas_tectonics.variable_stokes import _StressMACOperator
from atlas_tectonics.variable_stokes_execution import VariableStokesSolution, _diagnostics
from atlas_tectonics.resources import WorkBudget, MemoryLimitError
from stokes_fixtures import unit_box, unit_scales, request
from variable_stokes_fixtures import independent_two_cell_amplitude
import analyse_convection_r4_4 as audit

ENV = {**os.environ, 'OPENBLAS_NUM_THREADS':'1', 'OMP_NUM_THREADS':'1',
       'MKL_NUM_THREADS':'1', 'NUMBA_NUM_THREADS':'1'}


def mechanical(cls=at.PreparedVariableStokes2D, *, adaptive=True, anderson=True, **kw):
    return cls(unit_box(4), unit_scales(),
        policy=at.NonlinearStokesPolicy(max_picard_iterations=400, ilu_fill_factor=17),
        adaptive_inner_policy=at.AdaptiveInnerPolicy() if adaptive else None,
        anderson_policy=at.AndersonPolicy() if anderson else None,
        preconditioner_reuse_policy=at.PreconditionerReusePolicy(), **kw)


def solve(q, family='tosi-2', zero=False):
    n=q.box.nx
    # A non-gradient force, not a hydrostatic-only convergence test.
    fx=np.broadcast_to(np.cos(np.pi*(np.arange(n)+.5)/n)[:,None], (n,n-1)).copy()
    fz=np.broadcast_to(-np.cos(np.pi*(np.arange(n)+.5)/n)[None,:], (n-1,n)).copy()
    if zero:fx[:]=0;fz[:]=0
    return q.solve_rheology(fx,fz,np.full((n,n),1.6),at.reference_rheology(family),**request(q.box))


def initial(case='tosi-2', n=4):
    p=at.TosiCase(case).problem(n)
    return at.ThermochemicalState(p,at.tosi_initial_temperature(n),np.zeros((n,n)),
                                 time_s=0.,source='adaptive integration test')


def coupled(p, cls=at.PreparedThermochemical2D, **kw):
    return cls(p, nonlinear_policy=at.NonlinearStokesPolicy(max_picard_iterations=400,ilu_fill_factor=17),
        anderson_policy=at.AndersonPolicy(), nonlinear_start='previous-stage1',
        preconditioner_reuse_policy=at.PreconditionerReusePolicy(),
        adaptive_inner_policy=at.AdaptiveInnerPolicy(), **kw)


def arrays(result):
    return {k:result.array(k).copy() for k in result.array_names}


class PolicyTests(unittest.TestCase):
    def test_immutable_canonical(self):
        p=at.AdaptiveInnerPolicy()
        self.assertEqual(at.AdaptiveInnerPolicy(**asdict(p)),p)
        with self.assertRaises(FrozenInstanceError):p.rhs_relative_cap=.01

    def test_malformed_parameters(self):
        for key in asdict(at.AdaptiveInnerPolicy()):
            for value in (0.,-1.,float('nan'),float('inf'),True,2.,'0.1'):
                with self.subTest(key=key,value=value), self.assertRaises(at.TectonicsError):
                    at.AdaptiveInnerPolicy(**{key:value})
        for kw in ({'defect_fraction':.2},{'rhs_relative_cap':.001},{'strict_defect_relative':1e-7}):
            with self.assertRaises(at.TectonicsError):at.AdaptiveInnerPolicy(**kw)

    def test_exact_assessed_schedule_and_tighter_final(self):
        p=at.AdaptiveInnerPolicy()
        self.assertEqual(ai.target(p,1e-12,10.,1.,False),(1e-3,False))
        self.assertEqual(ai.target(p,1e-12,10.,1e-4,False),(1e-5,False))
        self.assertEqual(ai.target(p,5e-13,10.,1e-6,False),(5e-12,True))
        self.assertEqual(ai.target(p,5e-13,10.,1.,True),(5e-12,True))

    def test_bad_combinations_before_allocation(self):
        for pol in (at.NonlinearStokesPolicy(method='direct'),at.NonlinearStokesPolicy(relaxation=.5)):
            with self.assertRaises(at.TectonicsError):
                at.PreparedVariableStokes2D(unit_box(4),unit_scales(),policy=pol,adaptive_inner_policy=at.AdaptiveInnerPolicy())
        with self.assertRaises(at.TectonicsError):
            at.PreparedVariableStokes2D(unit_box(4),unit_scales(),adaptive_inner_policy={})

    def test_defaults_are_unchanged(self):
        for cls in (at.PreparedVariableStokes2D,at.PreparedThermochemical2D):
            self.assertIsNone(inspect.signature(cls).parameters['adaptive_inner_policy'].default)
        with mechanical(adaptive=False) as q:
            r=solve(q)
            self.assertNotIn('adaptive_inner',r.descriptor())
            self.assertIsNone(q._adaptive_request)

    def test_policy_binding_changes_identity(self):
        with mechanical() as a, mechanical(adaptive=False) as b:
            self.assertNotEqual(a.identity,b.identity)
            with self.assertRaises(at.TectonicsError):a.adaptive_inner_policy=None


class MechanicalTests(unittest.TestCase):
    def test_fresh_linear_and_updated_law_checks(self):
        class Independent(at.PreparedVariableStokes2D):
            def _publish(self,vector,rhs,*args,**kwargs):
                result=super()._publish(vector,rhs,*args,**kwargs)
                req=self._adaptive_request
                op=_StressMACOperator(self.box,self._op.hx,self._op.hz,compiled=False)
                op.set_viscosity(req.cert_c,req.cert_v)
                # Independent NumPy operator checks the actual rounded return vector.
                error=float(np.linalg.norm(op.matvec(vector)-rhs))
                if error>self.policy.linear_rtol*np.linalg.norm(rhs):
                    raise AssertionError('independent strict linear certification failed')
                op.set_viscosity(self._op.eta_c,self._op.eta_v)
                _diagnostics(op,vector,rhs,self.policy)
                return result
        with mechanical(cls=Independent) as q:
            r=solve(q);m=r.descriptor()
            self.assertLess(m['adaptive_inner']['strict_calls'],m['adaptive_inner']['linear_calls'])
            self.assertIsNone(q._adaptive_request)
            ai.check_history(m['adaptive_inner'],m['adaptive_inner_history'],m['nonlinear_history'],q.policy)
            self.assertEqual(sum(x['history_reset'] for x in m['adaptive_inner_history']),1)

    def test_independent_direct_reference(self):
        with mechanical() as q, at.PreparedVariableStokes2D(unit_box(4),unit_scales(),
                policy=at.NonlinearStokesPolicy(method='direct',max_picard_iterations=400)) as direct:
            accelerated=solve(q);reference=solve(direct)
            for key in ('u_m_s','w_m_s','pressure_pa','viscosity_cell_pa_s','viscosity_vertex_pa_s'):
                expected=reference.array(key)
                self.assertLessEqual(float(np.max(np.abs(accelerated.array(key)-expected))),
                                     1e-9+1e-7*float(np.max(np.abs(expected))))

    def test_nonunit_si_return_against_independent_operator_and_root(self):
        scales=at.DiffusiveScales('nonunit adaptive verification',3.7e5,1.3e-6,
                                  2.7e21,273.15,1300.,3.7e5)
        box=unit_box(2,width=scales.length_m,height=scales.length_m)
        force=scales.stress_pa/scales.length_m
        class Capture(at.PreparedVariableStokes2D):
            def _publish(self,vector,rhs,*args,**kw):
                self.frozen=(self._adaptive_request.cert_c.copy(),
                             self._adaptive_request.cert_v.copy(),rhs.copy())
                return super()._publish(vector,rhs,*args,**kw)
        with Capture(box,scales,adaptive_inner_policy=at.AdaptiveInnerPolicy(),
                anderson_policy=at.AndersonPolicy(),
                policy=at.NonlinearStokesPolicy(max_picard_iterations=400)) as q:
            result=q.solve_rheology(force*np.array([[1.],[-1.]]),
                force*np.array([[-1.,1.]]),np.full((2,2),273.15+.6*1300.),
                at.reference_rheology('tosi-2'),**request(box))
            op=_StressMACOperator(box,.5,.5,compiled=False)
            op.set_viscosity(*q.frozen[:2])
            vector=np.zeros(op.n);u,w,p,_=op.split(vector)
            u[:]=result.array('u_m_s')[:,1:-1]/scales.velocity_m_s
            w[:]=result.array('w_m_s')[1:-1]/scales.velocity_m_s
            p[:]=result.array('pressure_pa')/scales.stress_pa
            residual=float(np.linalg.norm(op.matvec(vector)-q.frozen[2]))
            certificate=result.descriptor()['adaptive_inner']['final_certification']
            self.assertLessEqual(residual,certificate['target_l2'])
            expected=independent_two_cell_amplitude(1.,1.6)
            self.assertAlmostEqual(u[0,0],expected,delta=1e-9+1e-7*abs(expected))

    def test_picard_and_anderson_supported(self):
        for enabled in (False,True):
            with self.subTest(anderson=enabled),mechanical(anderson=enabled) as q:
                m=solve(q).descriptor();f=m['adaptive_inner']['final_certification']
                self.assertLessEqual(f['returned_residual_l2'],f['target_l2'])
                self.assertTrue(m['adaptive_inner_history'][-1]['strict_certified'])

    def test_requested_stricter_policy_used(self):
        pol=at.NonlinearStokesPolicy(linear_rtol=5e-13,momentum_tolerance=5e-10,
            divergence_tolerance=5e-11,gauge_tolerance=5e-13,work_balance_tolerance=5e-10,
            viscosity_rtol=5e-9,max_picard_iterations=400,ilu_fill_factor=17)
        with at.PreparedVariableStokes2D(unit_box(4),unit_scales(),policy=pol,
                adaptive_inner_policy=at.AdaptiveInnerPolicy(),anderson_policy=at.AndersonPolicy()) as q:
            m=solve(q).descriptor();f=m['adaptive_inner']['final_certification']
            self.assertEqual(f['linear_rtol'],5e-13)
            self.assertEqual(f['target_l2'],5e-13*f['rhs_l2'])
            self.assertLessEqual(f['returned_residual_l2'],f['target_l2'])

    def test_zero_force_certified_without_factor(self):
        with mechanical() as q:
            m=solve(q,zero=True).descriptor()
            self.assertEqual(m['adaptive_inner']['final_certification']['returned_residual_l2'],0.)
            self.assertEqual(q.statistics()['factor_builds'],0)

    def test_strain_independent_bypass_exact_fields(self):
        with mechanical() as a,mechanical(adaptive=False) as b:
            x=solve(a,'tosi-1');y=solve(b,'tosi-1')
            self.assertFalse(x.descriptor()['adaptive_inner']['active'])
            self.assertEqual(x.descriptor()['adaptive_inner_history'],[])
            for k in x.array_names:np.testing.assert_array_equal(x.array(k),y.array(k))

    def test_prescribed_and_damage_refused(self):
        with mechanical() as q:
            with self.assertRaises(at.TectonicsError):
                q.solve(np.ones((4,3)),np.ones((3,4)),np.ones((4,4)),np.ones((3,3)),**request(q.box))
            from atlas_tectonics.constitutive import RheologyProfile
            # Use a registered BF profile, not a synthetic unrecognised law.
            bf=at.reference_rheology('bf23-memory')
            with self.assertRaises(at.TectonicsError):
                q.solve_rheology(np.ones((4,3)),np.ones((3,4)),np.full((4,4),1.6),bf,
                    frozen_damage=np.zeros((4,4)),**request(q.box))

    def test_provisional_not_publishable(self):
        class Limited(at.PreparedVariableStokes2D):
            def _certify_adaptive_publication(self,vector,rhs,cancel):
                self._adaptive_request.rows[-1]['strict_certified']=False
                return super()._certify_adaptive_publication(vector,rhs,cancel)
        with mechanical(cls=Limited) as q:
            with self.assertRaisesRegex(at.TectonicsError,'provisional'):solve(q)
            self.assertIsNone(q._adaptive_request)

    def test_strict_failure_not_retried(self):
        class Fail(at.PreparedVariableStokes2D):
            def _adaptive_linear(self,rhs,guess,cancel):
                if self._adaptive_request.strict_phase:
                    self.failures+=1
                    raise at.TectonicsError('injected strict failure')
                return super()._adaptive_linear(rhs,guess,cancel)
        with mechanical(cls=Fail) as q:
            q.failures=0
            with self.assertRaises(at.TectonicsError):solve(q)
            self.assertEqual(q.failures,1);self.assertIsNone(q._adaptive_request)

    def test_roundtrip_corruption_is_not_accepted(self):
        class Corrupt(at.PreparedVariableStokes2D):
            def _publish(self,vector,*args,**kw):
                vector=vector.copy();vector[0]+=.1
                return super()._publish(vector,*args,**kw)
        with mechanical(cls=Corrupt) as q:
            with self.assertRaisesRegex(at.TectonicsError,'strict linear'):solve(q)

    def test_metadata_tampering_rejected(self):
        with mechanical() as q:r=solve(q)
        for mutation in ('policy','final','history','missing'):
            m=r.descriptor()
            if mutation=='policy':m['adaptive_inner']['policy']['rhs_relative_cap']=1e-5
            elif mutation=='final':m['adaptive_inner']['final_certification']['returned_residual_l2']=1.
            elif mutation=='history':m['adaptive_inner_history'][-1]['strict_certified']=False
            else:del m['adaptive_inner']
            with self.subTest(mutation=mutation),self.assertRaises(at.TectonicsError):VariableStokesSolution(m,arrays(r))
        self.assertEqual(VariableStokesSolution(r.descriptor(),arrays(r)).result_id,r.result_id)

    def test_interleaved_requests_do_not_keep_adaptive_history(self):
        with mechanical() as q:
            a=solve(q);solve(q,'tosi-1');b=solve(q)
            self.assertEqual(a.result_id,b.result_id)
            self.assertIsNone(q._adaptive_request)

    def test_source_change_refused(self):
        with mechanical() as q:
            with mock.patch.object(ai,'_METHOD','changed'):
                with self.assertRaises(at.TectonicsError):solve(q)

    def test_budget_and_cancel_release(self):
        budget=WorkBudget(1<<28)
        with mechanical(budget=budget) as q:
            with budget.reserve(budget.available_bytes-100,category='test-exhaustion'):
                with self.assertRaises(MemoryLimitError):solve(q)
            with self.assertRaises(CancelledError),q._adaptive_operation(at.reference_rheology('tosi-2')):
                raise CancelledError('injected')
            self.assertIsNone(q._adaptive_request)
        self.assertEqual(budget.reserved_bytes,0)

    def test_independent_two_cell_root(self):
        for f,T in ((1.,1.6),(-1.,1.6),(.2,1.3),(0.,1.5)):
            with self.subTest(f=f),at.PreparedVariableStokes2D(unit_box(2),unit_scales(),
                adaptive_inner_policy=at.AdaptiveInnerPolicy(),anderson_policy=at.AndersonPolicy(),
                policy=at.NonlinearStokesPolicy(max_picard_iterations=400)) as q:
                result=q.solve_rheology(f*np.array([[1.],[-1.]]),f*np.array([[-1.,1.]]),
                    np.full((2,2),T),at.reference_rheology('tosi-2'),**request(q.box))
                expected=independent_two_cell_amplitude(f,T)
                self.assertAlmostEqual(result.array('u_m_s')[0,1],expected,delta=1e-9+1e-7*abs(expected))


class CouplingTests(unittest.TestCase):
    def test_actual_stage_tolerances_survive_and_tampering_is_refused(self):
        with coupled(initial().problem) as q:
            state=q.advance(initial(),1e-6,source='ledger').state
        original=state.descriptor()
        nm=original['step_record']['nonlinear_mechanics']
        for stage in nm['stages']:
            self.assertEqual(len(stage['adaptive_inner_history']), stage['nonlinear_iterations'])
            ai.check_stage(stage['adaptive_inner'],stage['adaptive_inner_history'],
                stage['nonlinear_iterations'],stage['linear_iterations'],
                at.NonlinearStokesPolicy(**nm['policy']),at.AdaptiveInnerPolicy())
        for mutation in ('missing','target','count','unbound_hash'):
            metadata=state.descriptor()
            stage=metadata['step_record']['nonlinear_mechanics']['stages'][0]
            if mutation=='missing':del stage['adaptive_inner_history']
            elif mutation=='target':stage['adaptive_inner_history'][0]['target_l2']*=2
            elif mutation=='count':stage['adaptive_inner_history'][0]['iterations']+=1
            else:stage['adaptive_inner']['history_sha256']='0'*64
            with self.subTest(mutation=mutation),self.assertRaises(at.TectonicsError):
                at.ThermochemicalState.restore(metadata,arrays(state))

    def test_two_stages_and_endpoint_certified_with_seed_roundtrip(self):
        s=initial()
        with coupled(s.problem) as q:
            for i in range(3):s=q.advance(s,1e-6,source='three').state
            m=s.descriptor()['step_record']['nonlinear_mechanics']
            self.assertEqual(m['adaptive_inner_policy'],asdict(at.AdaptiveInnerPolicy()))
            for stage in m['stages']:
                self.assertIsNotNone(stage['adaptive_inner']['final_certification'])
            endpoint=q.mechanical_snapshot(s,source='endpoint')
            self.assertIsNotNone(endpoint.descriptor()['adaptive_inner']['final_certification'])
            restored=at.ThermochemicalState.restore(s.descriptor(),arrays(s))
            self.assertEqual(s.state_id,restored.state_id)
            a=q.advance(s,1e-6,source='same').state
            b=q.advance(restored,1e-6,source='same').state
            self.assertEqual(a.state_id,b.state_id)

    def test_changed_policy_continuation_refused(self):
        s=initial()
        with coupled(s.problem) as q:s=q.advance(s,1e-6,source='first').state
        for ip in (None,at.AdaptiveInnerPolicy(rhs_relative_cap=1e-5)):
            with at.PreparedThermochemical2D(s.problem,nonlinear_start='previous-stage1',
                    anderson_policy=at.AndersonPolicy(),adaptive_inner_policy=ip) as q:
                with self.assertRaisesRegex(at.TectonicsError,'source/policy'):q.advance(s,1e-6,source='wrong')

    def test_second_stage_cancellation_preserves_input_and_seed(self):
        class CancelStage(at.PreparedThermochemical2D):
            cancel_second=False
            def _flow(self,T,C,time,stage,source,cancel,**kw):
                if self.cancel_second and 'stage 1' in stage:raise CancelledError('second stage')
                return super()._flow(T,C,time,stage,source,cancel,**kw)
        budget=WorkBudget(1<<28);s=initial()
        with coupled(s.problem,cls=CancelStage,budget=budget) as q:
            s=q.advance(s,1e-6,source='one').state
            before=s.state_id;seed=s.next_initial_guess.guess_id;saved=arrays(s)
            q.cancel_second=True
            with self.assertRaises(CancelledError):q.advance(s,1e-6,source='two')
            self.assertEqual(before,s.state_id);self.assertEqual(seed,s.next_initial_guess.guess_id)
            for k,v in saved.items():np.testing.assert_array_equal(v,s.array(k))
            self.assertIsNone(q._mechanics._adaptive_request)
            q.cancel_second=False;a=q.advance(s,1e-6,source='two').state
        with coupled(s.problem,cls=CancelStage,budget=budget) as q:b=q.advance(s,1e-6,source='two').state
        self.assertEqual(a.state_id,b.state_id);self.assertEqual(budget.reserved_bytes,0)

    def test_prescribed_velocity_rejects_unused_policy(self):
        s=initial()
        velocity=at.PrescribedMACVelocity(s.problem.box,np.zeros((4,5)),np.zeros((5,4)),source='rest')
        with at.PreparedThermochemical2D(s.problem,adaptive_inner_policy=at.AdaptiveInnerPolicy()) as q:
            with self.assertRaisesRegex(at.TectonicsError,'unused'):q.advance(s,1e-6,source='bad',velocity=velocity)

    def test_stage_summary_tampering_refused(self):
        s=initial()
        with coupled(s.problem) as q:s=q.advance(s,1e-6,source='one').state
        m=s.descriptor();nm=m['step_record']['nonlinear_mechanics']
        nm['stages'][0]['adaptive_inner']['final_certification']['returned_residual_l2']=1.
        with self.assertRaises(at.TectonicsError):at.ThermochemicalState.restore(m,arrays(s))

    def test_saved_state_cannot_bypass_adaptive_certification(self):
        with coupled(initial().problem) as q:s=q.advance(initial(),1e-6,source='one').state
        m=s.descriptor();nm=m['step_record']['nonlinear_mechanics']
        for stage in nm['stages']:
            stage['adaptive_inner']=ai.summary(at.AdaptiveInnerPolicy(),None,
                stage['nonlinear_iterations'],at.NonlinearStokesPolicy(**nm['policy']))
            stage['adaptive_inner_history']=[]
        with self.assertRaises(at.TectonicsError) as error:
            at.ThermochemicalState.restore(m,arrays(s))
        self.assertIn('activation differs',str(error.exception.__cause__))

    def test_cli_fresh_process_restart_and_audit(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp);full=base/'full';partial=base/'partial';split=base/'split'
            runner=ROOT/'tools/run_convection_r4_4.py'
            flags=['--case','tosi-2','--cells','4','--dt','0.000001','--max-steps','8',
                '--save-every','1','--sample-every','1','--nonlinear-solver','anderson',
                '--nonlinear-start','previous-stage1','--preconditioner-max-uses','4','--adaptive-inner']
            def call(out,extra,ok=True):
                result=subprocess.run([sys.executable,'-I','-B',str(runner),'--output',str(out),
                    '--budget-mib','256',*extra],env=ENV,capture_output=True,text=True,timeout=45)
                if ok:self.assertEqual(result.returncode,0,result.stderr[-2000:]+result.stdout[-1000:])
                else:self.assertNotEqual(result.returncode,0)
                return result
            call(full,[*flags,'--segment-steps','3'])
            call(partial,[*flags,'--segment-steps','1']);shutil.copytree(partial,split)
            call(split,['--resume','--segment-steps','2'])
            a=audit.read_run(full);b=audit.read_run(split)
            self.assertEqual(a[1][-1]['state_id'],b[1][-1]['state_id'])
            self.assertEqual(a[1][-1]['step'],3)
            for x,y in zip(a[4],b[4]):np.testing.assert_array_equal(x[1],y[1])
            saved={p.relative_to(split):hashlib.sha256(p.read_bytes()).hexdigest() for p in split.rglob('*') if p.is_file()}
            call(split,['--resume','--segment-steps','1','--adaptive-inner'],ok=False)
            self.assertEqual(saved,{p.relative_to(split):hashlib.sha256(p.read_bytes()).hexdigest() for p in split.rglob('*') if p.is_file()})


if __name__=='__main__':
    unittest.main(verbosity=2)
