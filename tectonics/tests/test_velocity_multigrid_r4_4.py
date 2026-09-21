"""Focused GMG integration checks, not mature convection acceptance.
SPDX-License-Identifier: AGPL-3.0-only
"""
from pathlib import Path
import sys
import unittest
from types import SimpleNamespace
from unittest import mock
from concurrent.futures import CancelledError
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'src'), str(ROOT/'tests'), str(ROOT/'tools')]
import atlas_tectonics as at
from atlas_tectonics import _velocity_multigrid as mg
from atlas_tectonics.variable_stokes import _StressMACOperator
from atlas_tectonics.variable_stokes_execution import _diagnostics
from atlas_tectonics.resources import WorkBudget, MemoryLimitError
from stokes_fixtures import unit_box, unit_scales, request
from variable_stokes_fixtures import analytic_variable


class MultigridTests(unittest.TestCase):
    def test_zero_start_smoother_matches_original_and_skips_one_product(self):
        def original(matrix, inverse, upper, rhs, x):
            lower=upper/20; theta=(upper+lower)/2; delta=(upper-lower)/2
            sigma=theta/delta; rho=1/sigma
            direction=inverse*(rhs-matrix@x)/theta; x=x+direction
            for _ in range(3):
                next_rho=1/(2*sigma-rho)
                direction=(next_rho*rho)*direction+(2*next_rho/delta)*inverse*(rhs-matrix@x)
                x=x+direction; rho=next_rho
            return x
        class Counted:
            def __init__(self, matrix): self.matrix=matrix; self.calls=0
            def __matmul__(self, x): self.calls+=1; return self.matrix@x
        op=_StressMACOperator(unit_box(8),1/8,1/8)
        op.set_viscosity(*analytic_variable(unit_box(8))[2:4])
        matrix=op.velocity_matrix().tocsr(); inverse=1/matrix.diagonal()
        upper=float(np.max(np.asarray(abs(matrix).sum(axis=1)).ravel()*inverse))
        rng=np.random.default_rng(21)
        for rhs in (rng.normal(size=2*op.nv)[::2], np.zeros(op.nv)):
            rhs.setflags(write=False)
            counted=Counted(matrix)
            expected=original(counted,inverse,upper,rhs,np.zeros_like(rhs))
            self.assertEqual(counted.calls,4); counted.calls=0
            result=mg.GeometricVcycle.smooth(counted,inverse,upper,rhs,None)
            self.assertEqual(counted.calls,3)
            self.assertEqual(expected.tobytes(),result.tobytes())
            self.assertFalse(np.shares_memory(result,rhs))
            start=rng.normal(size=op.nv); saved=start.copy(); counted.calls=0
            expected=original(matrix,inverse,upper,rhs,start)
            result=mg.GeometricVcycle.smooth(counted,inverse,upper,rhs,start)
            self.assertEqual(counted.calls,4)
            self.assertEqual(expected.tobytes(),result.tobytes())
            np.testing.assert_array_equal(start,saved)

    def test_zero_start_cycles_match_explicit_zero_and_own_results(self):
        class ExplicitZero(mg.GeometricVcycle):
            @staticmethod
            def smooth(matrix,inverse,upper,rhs,x):
                return mg.GeometricVcycle.smooth(matrix,inverse,upper,rhs,
                    np.zeros_like(rhs) if x is None else x)
        op=_StressMACOperator(unit_box(16),1/16,1/16)
        op.set_viscosity(*analytic_variable(unit_box(16))[2:4])
        transfers=mg.hierarchy_transfers(16,lambda:None)
        new=mg.GeometricVcycle(op.velocity_matrix(),transfers,lambda:None)
        old=ExplicitZero(op.velocity_matrix(),transfers,lambda:None)
        rng=np.random.default_rng(22); rhs=rng.normal(size=op.nv)
        first=new.solve(rhs); saved=first.copy()
        self.assertEqual(first.tobytes(),old.solve(rhs).tobytes())
        second=new.solve(2*rhs)
        self.assertFalse(np.shares_memory(first,second))
        self.assertEqual(first.tobytes(),saved.tobytes())
        self.assertEqual(new.solve(rhs).tobytes(),saved.tobytes())
        self.assertEqual(new.nbytes,old.nbytes)

    def test_transfer_walls_and_fixed_linearity(self):
        np.testing.assert_array_equal(mg.prolongation_1d(8, True) @ np.ones(4), np.ones(8))
        np.testing.assert_array_equal(mg.prolongation_1d(8, False) @ np.ones(3), [.5,1,1,1,1,1,.5])
        op = _StressMACOperator(unit_box(8), 1/8, 1/8)
        op.set_viscosity(*analytic_variable(unit_box(8))[2:4])
        cycle = mg.GeometricVcycle(op.velocity_matrix(), mg.hierarchy_transfers(8, lambda: None), lambda: None)
        rng = np.random.default_rng(20260921); x = rng.normal(size=op.nv); y = rng.normal(size=op.nv)
        np.testing.assert_allclose(cycle.solve(2*x-y), 2*cycle.solve(x)-cycle.solve(y), rtol=2e-12, atol=1e-12)

    def test_solution_matches_direct_and_reuses_geometry_not_coefficients(self):
        box = unit_box(8); inputs = analytic_variable(box)[:4]; results = []
        for method, velocity in [('direct', 'auto'), ('gmres', 'gmg')]:
            policy = at.NonlinearStokesPolicy(method=method, velocity_preconditioner=velocity)
            budget = WorkBudget(1 << 28)
            with at.PreparedVariableStokes2D(box, unit_scales(), policy=policy, budget=budget) as plan:
                result = plan.solve(*inputs, **request(box)); results.append(result)
                if velocity == 'gmg':
                    transfer = plan._gmg_transfers
                    repeat = plan.solve(*inputs, **request(box))
                    self.assertEqual(result.result_id, repeat.result_id)
                    self.assertEqual(plan.statistics()['factor_builds'], 1)
                    changed = plan.solve(inputs[0], inputs[1], 1.2*inputs[2], 1.2*inputs[3], **request(box))
                    self.assertIs(plan._gmg_transfers, transfer)
                    self.assertEqual(plan.statistics()['multigrid_builds'], 2)
                    np.testing.assert_allclose(changed.array('u_m_s'), result.array('u_m_s')/1.2, atol=1e-10)
            self.assertEqual(budget.reserved_bytes, 0)
        for key in ('u_m_s', 'w_m_s', 'pressure_pa'):
            np.testing.assert_allclose(results[0].array(key), results[1].array(key), rtol=1e-8, atol=1e-10)

    def test_auto_rule_is_size_geometry_and_workload_aware(self):
        for n, family, expected in [(32,'tosi-linear','ilu'), (64,'tosi-linear','ilu'),
                                    (128,'tosi-linear','gmg'), (128,'tosi-plastic','ilu'),
                                    (128,None,'ilu'), (96,'tosi-linear','ilu'), (128,'constant','ilu')]:
            fake = SimpleNamespace(box=unit_box(n), policy=at.NonlinearStokesPolicy(),
                _preconditioner_workload=family, _reuse_request=None, anderson_policy=None, adaptive_inner_policy=None)
            self.assertEqual(at.PreparedVariableStokes2D._velocity_method(fake), expected)
        fake._preconditioner_workload='tosi-plastic';fake._reuse_request=object()
        fake.anderson_policy=at.AndersonPolicy();fake.adaptive_inner_policy=at.AdaptiveInnerPolicy()
        self.assertEqual(at.PreparedVariableStokes2D._velocity_method(fake), 'gmg')
        fake.adaptive_inner_policy=None
        self.assertEqual(at.PreparedVariableStokes2D._velocity_method(fake), 'ilu')
        self.assertFalse(mg.supported(unit_box(64, 32)))
        self.assertFalse(mg.supported(unit_box(64, width=2)))

    def test_invalid_policy_and_explicit_unsupported_shape_refused(self):
        for value in ('unknown', None, True):
            with self.assertRaises(at.TectonicsError): at.NonlinearStokesPolicy(velocity_preconditioner=value)
        with self.assertRaises(at.TectonicsError): at.NonlinearStokesPolicy(method='direct', velocity_preconditioner='gmg')
        for box in (unit_box(7), unit_box(8, 4), unit_box(8, width=2)):
            with self.assertRaises(at.TectonicsError):
                at.PreparedVariableStokes2D(box, unit_scales(), policy=at.NonlinearStokesPolicy(velocity_preconditioner='gmg'))

    def test_admission_cancel_failure_and_binding(self):
        policy = at.NonlinearStokesPolicy(velocity_preconditioner='gmg')
        budget = WorkBudget(1)
        with self.assertRaises(MemoryLimitError): at.PreparedVariableStokes2D(unit_box(8), unit_scales(), policy=policy, budget=budget)
        self.assertEqual(budget.reserved_bytes, 0)
        budget = WorkBudget(1 << 28)
        with at.PreparedVariableStokes2D(unit_box(8), unit_scales(), policy=policy, budget=budget) as plan:
            with at.PreparedVariableStokes2D(unit_box(8), unit_scales(), policy=at.NonlinearStokesPolicy(velocity_preconditioner='ilu')) as other:
                self.assertNotEqual(plan.identity, other.identity)
            import threading
            cancelled=threading.Event();cancelled.set()
            with self.assertRaises(CancelledError):
                plan.solve(*analytic_variable(unit_box(8))[:4], **request(plan.box), cancel=cancelled)
            self.assertFalse(plan._active); self.assertIsNone(plan._factor)
            # Loaded-callable mutation is refused by the real source guard.
            with mock.patch.object(mg.GeometricVcycle, 'solve', lambda self,x:x), self.assertRaises(at.TectonicsError):
                plan.solve(*analytic_variable(unit_box(8))[:4], **request(plan.box))
            self.assertEqual(plan.statistics()['factor_builds'], 0)
        self.assertEqual(budget.reserved_bytes, 0)

    def test_guarded_gmg_reuse_keeps_current_operator(self):
        policy = at.NonlinearStokesPolicy(velocity_preconditioner='gmg')
        with at.PreparedVariableStokes2D(unit_box(8), unit_scales(), policy=policy,
                preconditioner_reuse_policy=at.PreconditionerReusePolicy()) as plan:
            with plan._operation(None), plan._preconditioner_request(at.reference_rheology('tosi-2')):
                plan._coefficients(np.ones((8,8)), np.ones((7,7)))
                rhs = np.r_[analytic_variable(unit_box(8))[0].ravel(), analytic_variable(unit_box(8))[1].ravel(), np.zeros(65)]
                x, _ = plan._linear(rhs, None, None)
                factor = plan._factor
                plan._coefficients(np.full((8,8),1.01), np.full((7,7),1.01))
                y, _ = plan._linear(rhs, x, None)
                self.assertIs(plan._factor, factor)
                self.assertEqual(plan._reuse_request.rows[-1]['decision'], 'bounded_reuse')
                independent = _StressMACOperator(unit_box(8), 1/8, 1/8)
                independent.set_viscosity(plan._op.eta_c, plan._op.eta_v)
                _diagnostics(independent, y, rhs, policy)
                self.assertLessEqual(np.linalg.norm(independent.matvec(y)-rhs), policy.linear_rtol*np.linalg.norm(rhs))
            self.assertIsNone(plan._preconditioner_workload)

    def test_cli_selection_is_explicit_and_default_auto(self):
        from run_convection_r4_4 import parser
        self.assertIsNone(parser().parse_args(['--output','unused']).velocity_preconditioner)
        self.assertEqual(parser().parse_args(['--output','unused','--velocity-preconditioner','gmg']).velocity_preconditioner, 'gmg')

    def test_gmg_cli_restart_matches_uninterrupted_and_rejects_policy_change(self):
        import tempfile, subprocess, os
        import analyse_convection_r4_4 as audit
        env={**os.environ, 'OPENBLAS_NUM_THREADS':'1', 'OMP_NUM_THREADS':'1',
             'MKL_NUM_THREADS':'1', 'NUMBA_NUM_THREADS':'1'}
        flags=['--case','tosi-2','--cells','8','--dt','0.0000001','--max-steps','3',
               '--save-every','1','--sample-every','1','--nonlinear-solver','anderson',
               '--nonlinear-start','previous-stage1','--preconditioner-max-uses','4',
               '--adaptive-inner','--velocity-preconditioner','gmg']
        def call(out, extra):
            return subprocess.run([sys.executable,'-I','-B',str(ROOT/'tools/run_convection_r4_4.py'),
                '--output',str(out),'--budget-mib','256',*extra],env=env,capture_output=True,text=True,timeout=45)
        with tempfile.TemporaryDirectory() as temp:
            full=Path(temp)/'full';split=Path(temp)/'split'
            for out, extra in ((full,[*flags,'--segment-steps','2']),
                               (split,[*flags,'--segment-steps','1']),
                               (split,['--resume','--segment-steps','1'])):
                result=call(out,extra)
                self.assertEqual(result.returncode,0,result.stderr[-2000:]+result.stdout[-1000:])
            a=audit.read_run(full);b=audit.read_run(split)
            self.assertEqual(a[1][-1]['state_id'],b[1][-1]['state_id'])
            for x,y in zip(a[4],b[4]):np.testing.assert_array_equal(x[1],y[1])
            refused=call(split,['--resume','--segment-steps','1','--velocity-preconditioner','ilu'])
            self.assertNotEqual(refused.returncode,0)
            self.assertIn('frozen inputs/policies',refused.stderr)


if __name__ == '__main__': unittest.main(verbosity=2)
