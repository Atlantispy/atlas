"""Independent integration, policy, resource and provenance checks for dev39.
SPDX-License-Identifier: AGPL-3.0-only
"""
from pathlib import Path
import sys, json, unittest, threading
from dataclasses import FrozenInstanceError, asdict
from concurrent.futures import CancelledError
from unittest import mock
import numpy as np
sys.dont_write_bytecode=True
R=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(R/'src'),str(R/'tests'),str(R/'tools')]
import atlas_tectonics as at
from atlas_tectonics import preconditioner_reuse as pr
from atlas_tectonics.variable_stokes_execution import PreparedVariableStokes2D, VariableStokesSolution, _diagnostics
from atlas_tectonics.resources import WorkBudget, MemoryLimitError
from stokes_fixtures import unit_box, unit_scales, request
from variable_stokes_fixtures import independent_two_cell_amplitude

class PolicyTests(unittest.TestCase):
    def test_invalid_ages(self):
        for v in (0,9,-1,1.5,True):
            with self.subTest(v=v),self.assertRaises(at.TectonicsError):pr.PreconditionerReusePolicy(v)
    def test_invalid_change(self):
        for v in (0.,-1.,float('nan'),float('inf'),True,10.):
            with self.subTest(v=v),self.assertRaises(at.TectonicsError):pr.PreconditionerReusePolicy(maximum_log_change=v)
    def test_invalid_growth(self):
        for v in (.5,float('nan'),float('inf'),True,1001):
            with self.subTest(v=v),self.assertRaises(at.TectonicsError):pr.PreconditionerReusePolicy(iteration_growth=v)
    def test_invalid_floor(self):
        for v in (0,-1,1.5,True,1000001):
            with self.subTest(v=v),self.assertRaises(at.TectonicsError):pr.PreconditionerReusePolicy(iteration_floor=v)
    def test_frozen_policy(self):
        with self.assertRaises(FrozenInstanceError):pr.PreconditionerReusePolicy().max_uses=7
    def test_roundtrip_policy(self):
        p=pr.PreconditionerReusePolicy();self.assertEqual(pr.PreconditionerReusePolicy(**asdict(p)),p)
    def test_default_is_four(self):self.assertEqual(pr.PreconditionerReusePolicy().max_uses,4)
    def test_bad_typed_policy(self):
        with self.assertRaises(at.TectonicsError):PreparedVariableStokes2D(unit_box(2),unit_scales(),preconditioner_reuse_policy={})
    def test_direct_refused(self):
        with self.assertRaises(at.TectonicsError):PreparedVariableStokes2D(unit_box(2),unit_scales(),policy=at.NonlinearStokesPolicy(method='direct'),preconditioner_reuse_policy=pr.PreconditionerReusePolicy())

class ReuseTests(unittest.TestCase):
    def plan(self,age=4,n=4,**kw):
        return PreparedVariableStokes2D(unit_box(n),unit_scales(),preconditioner_reuse_policy=pr.PreconditionerReusePolicy(age),**kw)
    def set_coefficients(self,q,value):
        q._coefficients(np.full((q.box.nz,q.box.nx),value),np.full((q.box.nz-1,q.box.nx-1),value))
    def context(self,q):return q._preconditioner_request(at.reference_rheology('tosi-2'))
    def solve(self,q):
        n=q.box.nx
        return q.solve_rheology(np.ones((n,n-1)),np.ones((n-1,n)),np.full((n,n),1.6),at.reference_rheology('tosi-2'),**request(q.box))
    def test_plan_policy_bound(self):
        with self.plan(2) as a,self.plan(4) as b: self.assertNotEqual(a.identity,b.identity)
    def test_binding_immutable(self):
        with self.plan() as p:
            with self.assertRaises(at.TectonicsError):p.preconditioner_reuse_policy=pr.PreconditionerReusePolicy(2)
    def test_first_factor_current(self):
        with self.plan() as q,q._operation(None),self.context(q):
            self.set_coefficients(q,1.);q._factorise(None)
            self.assertEqual(q._factor_key,pr.coefficient_key(q._op));self.assertEqual(q._reuse_request.pending['decision'],'request_start')
    def test_changed_helper_keeps_current_operator(self):
        from scipy.sparse.linalg import splu
        with self.plan() as q,q._operation(None),self.context(q):
            self.set_coefficients(q,1.)
            rhs=np.zeros(q._op.n);rhs[:q._op.nv]=np.random.default_rng(74).normal(size=q._op.nv)
            x,_=q._linear(rhs,None,None);origin=q._factor_key
            self.set_coefficients(q,1.05)
            with self.assertRaises(at.TectonicsError):_diagnostics(q._op,x,rhs,q.policy)
            y,_=q._linear(rhs,x,None)
            self.assertEqual(origin,q._factor_key);self.assertNotEqual(pr.coefficient_key(q._op),origin)
            ref=splu(q._op.sparse_reference()).solve(rhs)
            np.testing.assert_allclose(y,ref,rtol=1e-9,atol=1e-10)
            self.assertEqual(q._reuse_request.rows[-1]['decision'],'bounded_reuse')
    def test_age_rebuild(self):
        with self.plan(2) as q,q._operation(None),self.context(q):
            for v in (1.,1.05,1.10):self.set_coefficients(q,v);q._factorise(None)
            self.assertEqual(q._factor_builds,2);self.assertEqual(q._reuse_request.pending['decision'],'age_limit')
    def test_change_rebuild(self):
        with self.plan() as q,q._operation(None),self.context(q):
            self.set_coefficients(q,1.);q._factorise(None);self.set_coefficients(q,3.);q._factorise(None)
            self.assertEqual(q._reuse_request.pending['decision'],'viscosity_change')
    def test_iteration_growth_rebuild(self):
        with self.plan() as q,q._operation(None),self.context(q):
            self.set_coefficients(q,1.);q._factorise(None)
            q._reuse_request.build_iterations=10;q._reuse_request.last_iterations=41
            self.set_coefficients(q,1.05);q._factorise(None)
            self.assertEqual(q._reuse_request.pending['decision'],'linear_work_growth')
    def test_exact_factor_reuse(self):
        with self.plan() as q,q._operation(None),self.context(q):
            self.set_coefficients(q,1.);q._factorise(None);q._factorise(None)
            self.assertEqual(q._factor_builds,1);self.assertEqual(q._factor_reuses,1)
            self.assertEqual(q._reuse_request.pending['decision'],'exact_match')
    def test_no_cross_request_approximation(self):
        with self.plan() as q,q._operation(None):
            with self.context(q):
                self.set_coefficients(q,1.);q._factorise(None);self.set_coefficients(q,1.05);q._factorise(None)
            self.assertIsNone(q._reuse_request)
            with self.context(q):
                self.set_coefficients(q,1.06);q._factorise(None)
                self.assertEqual(q._factor_key,pr.coefficient_key(q._op));self.assertEqual(q._reuse_request.pending['decision'],'request_start')
    def test_cancel_clears_request(self):
        b=WorkBudget(1<<28)
        with self.plan(budget=b) as q:
            with self.assertRaises(CancelledError),q._operation(None),self.context(q):raise CancelledError('test')
            self.assertIsNone(q._reuse_request)
        self.assertEqual(b.reserved_bytes,0)
    def test_budget_refusal(self):
        b=WorkBudget(1<<28)
        with self.plan(budget=b) as q:
            with b.reserve(b.available_bytes-10,category='test-exhaustion'):
                with self.assertRaises(MemoryLimitError),q._operation(None),self.context(q):pass
            self.assertIsNone(q._reuse_request)
        self.assertEqual(b.reserved_bytes,0)
    def test_fault_not_retried(self):
        class Fault(PreparedVariableStokes2D):
            def _factorise_current(self,cancel):
                self.attempts+=1;raise at.TectonicsError('injected fault')
        b=WorkBudget(1<<28)
        with Fault(unit_box(4),unit_scales(),preconditioner_reuse_policy=pr.PreconditionerReusePolicy(),budget=b) as q:
            q.attempts=0
            with self.assertRaises(at.TectonicsError):self.solve(q)
            self.assertEqual(q.attempts,1);self.assertIsNone(q._reuse_request)
        self.assertEqual(b.reserved_bytes,0)
    def test_gmres_mutation_refused(self):
        import atlas_tectonics.variable_stokes_execution as v
        with self.plan() as q:
            with mock.patch.object(v,'gmres',lambda *a,**kw:None):
                with self.assertRaises(at.TectonicsError):self.solve(q)
    def test_policy_module_mutation_refused(self):
        with self.plan() as q:
            with mock.patch.object(pr,'_METHOD','tampered'):
                with self.assertRaises(at.TectonicsError):self.solve(q)
    def test_default_path_no_metadata(self):
        with PreparedVariableStokes2D(unit_box(4),unit_scales()) as q:
            m=self.solve(q).descriptor();self.assertNotIn('preconditioner_reuse',m)
    def test_identity_independent_of_cached_factor(self):
        with self.plan() as q:
            a=self.solve(q);b=self.solve(q);self.assertEqual(a.result_id,b.result_id)
    def test_zero_rhs_no_factor(self):
        with self.plan() as q:
            r=q.solve_rheology(np.zeros((4,3)),np.zeros((3,4)),np.full((4,4),1.5),at.reference_rheology('tosi-2'),**request(q.box))
            self.assertEqual(q._factor_builds,0);self.assertEqual(r.descriptor()['preconditioner_reuse']['decisions']['zero_rhs'],1)
    def test_strain_independent_bypass(self):
        with self.plan() as q:
            r=q.solve_rheology(np.ones((4,3)),np.ones((3,4)),np.full((4,4),1.5),at.reference_rheology('tosi-1'),**request(q.box))
            self.assertFalse(r.descriptor()['preconditioner_reuse']['active']);self.assertEqual(r.descriptor()['preconditioner_history'],[])
    def test_prescribed_viscosity_refused(self):
        with self.plan() as q:
            with self.assertRaises(at.TectonicsError):q.solve(np.ones((4,3)),np.ones((3,4)),np.ones((4,4)),np.ones((3,3)),**request(q.box))
    def test_independent_scalar_roots(self):
        for f,T in ((1.,1.6),(-1.,1.6),(.2,1.3),(0.,1.5)):
            with self.subTest(f=f,T=T),self.plan(n=2,anderson_policy=at.AndersonPolicy()) as q:
                r=q.solve_rheology(f*np.array([[1.],[-1.]]),f*np.array([[-1.,1.]]),np.full((2,2),T),at.reference_rheology('tosi-2'),**request(q.box))
                expected=independent_two_cell_amplitude(f,T)
                self.assertAlmostEqual(r.array('u_m_s')[0,1],expected,delta=1e-9+1e-7*abs(expected))
    def test_typed_roundtrip(self):
        with self.plan() as q:r=self.solve(q)
        x=VariableStokesSolution(r.descriptor(),{k:r.array(k) for k in r.array_names});self.assertEqual(r.result_id,x.result_id)
    def test_history_corruption_refused(self):
        with self.plan() as q:r=self.solve(q)
        m=r.descriptor();m['preconditioner_history'][0]['factor_coefficient_sha256']='0'*64
        with self.assertRaises(at.TectonicsError):VariableStokesSolution(m,{k:r.array(k) for k in r.array_names})
    def test_summary_corruption_refused(self):
        with self.plan() as q:r=self.solve(q)
        m=r.descriptor();m['preconditioner_reuse']['linear_calls']+=1
        with self.assertRaises(at.TectonicsError):VariableStokesSolution(m,{k:r.array(k) for k in r.array_names})
    def test_missing_history_refused(self):
        with self.plan() as q:r=self.solve(q)
        m=r.descriptor();del m['preconditioner_history']
        with self.assertRaises(at.TectonicsError):VariableStokesSolution(m,{k:r.array(k) for k in r.array_names})
    def test_immutable_output(self):
        with self.plan() as q:r=self.solve(q)
        with self.assertRaises(ValueError):r.array('u_m_s')[0,1]=7.

class CouplingTests(unittest.TestCase):
    def initial(self):
        p=at.TosiCase('tosi-2').problem(4)
        return p,at.ThermochemicalState(p,at.tosi_initial_temperature(4),np.zeros((4,4)),time_s=0.,source='reuse test')
    def plan(self,p,age=4,**kw):
        return at.PreparedThermochemical2D(p,anderson_policy=at.AndersonPolicy(),nonlinear_start='previous-stage1',preconditioner_reuse_policy=pr.PreconditionerReusePolicy(age),**kw)
    def test_stage_summaries(self):
        p,s=self.initial()
        with self.plan(p) as q:r=q.advance(s,1e-6,source='same')
        rec=r.state.descriptor()['step_record']['nonlinear_mechanics']
        self.assertEqual(rec['preconditioner_reuse_policy']['max_uses'],4)
        for stage in rec['stages']:pr.check_summary(stage['preconditioner_reuse'],stage['nonlinear_iterations'],pr.PreconditionerReusePolicy())
    def test_same_request_no_hidden_history(self):
        p,s=self.initial()
        with self.plan(p) as q:
            a=q.advance(s,1e-6,source='same');q.advance(a.state,1e-6,source='other');b=q.advance(s,1e-6,source='same')
            self.assertEqual(a.result_id,b.result_id)
    def test_parent_free_state_reconstruction(self):
        p,s=self.initial()
        with self.plan(p) as q:a=q.advance(s,1e-6,source='same').state;b=q.advance(a,1e-6,source='same').state
        restored=at.ThermochemicalState.restore(a.descriptor(),{k:a.array(k) for k in a.array_names})
        with self.plan(p) as q:c=q.advance(restored,1e-6,source='same').state
        self.assertEqual(b.state_id,c.state_id)
    def test_seed_policy_change_refused(self):
        p,s=self.initial()
        with self.plan(p,2) as q:a=q.advance(s,1e-6,source='same').state
        with self.plan(p,4) as q:
            with self.assertRaises(at.TectonicsError):q.advance(a,1e-6,source='same')
    def test_state_stage_summary_corruption(self):
        p,s=self.initial()
        with self.plan(p) as q:a=q.advance(s,1e-6,source='same').state
        m=a.descriptor();m['step_record']['nonlinear_mechanics']['stages'][0]['preconditioner_reuse']['policy']['max_uses']=2
        with self.assertRaises(at.TectonicsError):at.ThermochemicalState.restore(m,{k:a.array(k) for k in a.array_names})
    def test_endpoint_cannot_change_next_seed(self):
        p,s=self.initial()
        with self.plan(p) as q:
            a=q.advance(s,1e-6,source='same').state;b=q.advance(a,1e-6,source='same').state
            q.mechanical_snapshot(a,source='extra endpoint')
            c=q.advance(a,1e-6,source='same').state
            self.assertEqual(b.state_id,c.state_id)
    def test_cancel_preserves_state_seed(self):
        p,s=self.initial();event=threading.Event()
        with self.plan(p) as q:
            a=q.advance(s,1e-6,source='same').state;before=a.state_id;seed=a.next_initial_guess.guess_id;event.set()
            with self.assertRaises(CancelledError):q.advance(a,1e-6,source='same',cancel=event)
            self.assertEqual(a.state_id,before);self.assertEqual(a.next_initial_guess.guess_id,seed)
    def test_cli_option(self):
        import run_convection_r4_4 as runner
        args=runner.parser().parse_args(['--output','/tmp/unused','--preconditioner-max-uses','4'])
        self.assertEqual(args.preconditioner_max_uses,4)
    def test_bounded_request_memory(self):
        self.assertGreater(pr.request_bytes(128**2,400),32*128**2)
    def test_archive_version_consistent(self):
        import tomllib
        self.assertEqual(tomllib.loads((R/'pyproject.toml').read_text())['project']['version'],at.__version__)

if __name__=='__main__':unittest.main()
