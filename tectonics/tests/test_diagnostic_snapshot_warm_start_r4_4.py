"""Diagnostic-only seed reuse: current equations, immutable inputs and recovery.

SPDX-License-Identifier: AGPL-3.0-only
R4.4 remains IN_PROGRESS / WORKING NON-CANON. These are bounded regressions,
not a mature convection campaign or permission to rebind historical sources.
"""
from concurrent.futures import CancelledError, ThreadPoolExecutor
from dataclasses import asdict, replace
import inspect
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import numpy as np
import atlas_tectonics as at
from atlas_tectonics import thermochemical_execution as tx
from atlas_tectonics.resources import MemoryLimitError, WorkBudget
from atlas_tectonics.stokes import face_force_from_density


def fixture(n=4):
    """Authored non-unit-temperature, composition-dependent numerical control."""
    box = at.StokesBox2D(n, n, 1., 1., 'snapshot-synthetic-cartesian')
    material = at.BoussinesqMaterial(
        'snapshot-synthetic-material', 'Numerical control, not Earth calibration',
        1., 1., .01, .001, 300., .01, 0., (1., 1000.))
    p = at.ThermochemicalProblem(
        box, material, at.ThermalBoundary2D('fixed-top-bottom', 310., 300.),
        at.reference_rheology('tosi-2'),
        at.DiffusiveScales('snapshot-scales', 1., .01, 1., 300., 10., 1.),
        (0., -1.), 'snapshot-epoch', 'synthetic-heavy-constituent',
        'Diagnostic-path regression fixture', mechanical_mode='variable-r4.3')
    x, z = np.meshgrid(*box.axes())
    T = 310. - 10*z + np.sin(np.pi*z)*np.cos(np.pi*x)
    C = .4 + .1*np.cos(np.pi*x)*np.cos(np.pi*z)
    return p, at.ThermochemicalState(p, T, C, time_s=0., source='synthetic initial fields')


def plan(p, **kwargs):
    return at.PreparedThermochemical2D(p, nonlinear_start='previous-stage1', **kwargs)


def capture(s):
    return s.descriptor(), {k: s.array(k).copy() for k in s.array_names}


def cold_snapshot(q, s, source):
    """Explicit control through the same validated current mechanical solver."""
    p = s.problem
    T, C = s.array('temperature_k'), s.array('composition')
    rho, _ = tx._check_fields(p, T, C)
    fx, fz = face_force_from_density(p.box, rho, p.gravity_m_s2, budget=q.budget)
    return q._mechanics_plan(None).solve_rheology(
        fx, fz, T, p.rheology, frame_id=p.box.frame_id, epoch_id=p.epoch_id,
        time_s=s.time_s, source=source)


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.p, self.s = fixture()

    def assert_unchanged(self, s, saved):
        self.assertEqual(s.descriptor(), saved[0])
        for key, value in saved[1].items():
            np.testing.assert_array_equal(s.array(key), value)
            self.assertFalse(s.array(key).flags.writeable)

    def assert_gates(self, result, policy):
        d = result.descriptor()['diagnostics']
        for key, limit in (
            ('momentum_linf', policy.momentum_tolerance),
            ('divergence_linf', policy.divergence_tolerance),
            ('pressure_gauge_relative', policy.gauge_tolerance),
            ('gauge_multiplier_abs', policy.gauge_tolerance),
            ('work_balance_relative', policy.work_balance_tolerance)):
            self.assertLessEqual(d[key], limit)
        self.assertEqual(result.descriptor()['policy'], asdict(policy))
        rows = result.descriptor()['nonlinear_history']
        self.assertLessEqual(len(rows), policy.max_picard_iterations)
        self.assertLessEqual(sum(r['linear_iterations'] for r in rows),
                             len(rows)*policy.restart*policy.max_cycles)
        adaptive = result.descriptor().get('adaptive_inner')
        if adaptive and adaptive['active']:
            cert = adaptive['final_certification']
            self.assertLessEqual(cert['returned_residual_l2'], cert['target_l2'])
            self.assertEqual(cert['target_l2'], policy.linear_rtol*cert['rhs_l2'])

    def test_initial_and_accepted_no_seed_states_stay_cold(self):
        for mode in ('zero-rate', 'rk-stage0', 'previous-stage1'):
            with self.subTest(mode=mode), at.PreparedThermochemical2D(
                    self.p, nonlinear_start=mode) as q:
                r = q.mechanical_snapshot(self.s, source='initial control')
                self.assertNotIn('initial_guess', r.descriptor())
                self.assertIsNone(self.s.next_initial_guess)
                if mode != 'previous-stage1':
                    s = q.advance(self.s, .001, source='no cross-step seed').state
                    r = q.mechanical_snapshot(s, source='accepted control')
                    self.assertNotIn('initial_guess', r.descriptor())
                    self.assertIsNone(s.next_initial_guess)

    def test_current_fields_and_exact_seed_not_old_flow_are_published(self):
        with plan(self.p, anderson_policy=at.AndersonPolicy()) as q:
            s = q.advance(self.s, .001, source='physical').state
            saved = capture(s)
            seed = s.next_initial_guess
            stages = json.loads(json.dumps(q._stage_mechanics))
            mechanical_plan = q._mechanics
            # A later unrelated request must not become this earlier state's seed.
            q.advance(s, .001, source='later request')
            stages = json.loads(json.dumps(q._stage_mechanics))
            warm = q.mechanical_snapshot(s, source='current-state diagnostic')
            cold = cold_snapshot(q, s, 'current-state diagnostic')
            m = warm.descriptor()
            self.assertIs(q._mechanics, mechanical_plan)
            self.assertEqual(q._stage_mechanics, stages)
            self.assertIs(s.next_initial_guess, seed)
            self.assertEqual(m['initial_guess'], {
                'guess_id': seed.guess_id, 'descriptor': seed.descriptor()})
            self.assertEqual(m['plan_id'], seed.descriptor()['plan_id'])
            self.assertEqual((m['epoch_id'], m['time_s'], m['source']),
                             (self.p.epoch_id, s.time_s, 'current-state diagnostic'))
            np.testing.assert_array_equal(warm.array('temperature_k'), s.array('temperature_k'))
            rho, _ = tx._check_fields(self.p, s.array('temperature_k'), s.array('composition'))
            fx, fz = face_force_from_density(self.p.box, rho, self.p.gravity_m_s2)
            np.testing.assert_array_equal(warm.array('force_x_n_m3'), fx)
            np.testing.assert_array_equal(warm.array('force_z_n_m3'), fz)
            self.assertNotEqual(warm.result_id, seed.descriptor()['source_result_id'])
            self.assertGreater(float(np.max(np.abs(warm.array('u_m_s') - seed.array('u_m_s')))), 1e-10)
            for key in ('u_m_s', 'w_m_s', 'pressure_pa'):
                np.testing.assert_allclose(warm.array(key), cold.array(key), rtol=1e-7, atol=1e-10)
                np.testing.assert_array_equal(warm.array('initial_guess_'+key), seed.array(key))
            self.assert_gates(warm, q.nonlinear_policy)
            self.assert_gates(cold, q.nonlinear_policy)
            self.assert_unchanged(s, saved)

    def test_sampling_frequency_preserves_entire_physical_trajectory(self):
        for accelerated in (False, True):
            kwargs = (dict(anderson_policy=at.AndersonPolicy(),
                           adaptive_inner_policy=at.AdaptiveInnerPolicy(),
                           preconditioner_reuse_policy=at.PreconditionerReusePolicy())
                      if accelerated else {})
            histories = []
            for samples in (0, 1, 3):
                with self.subTest(accelerated=accelerated, samples=samples), plan(self.p, **kwargs) as q:
                    s = self.s
                    ids = []
                    for _ in range(3):
                        saved = capture(s)
                        for i in range(samples):
                            q.mechanical_snapshot(s, source='diagnostic '+str(i))
                        self.assert_unchanged(s, saved)
                        r = q.advance(s, .001, source='same physical step')
                        s = r.state
                        ids.append((r.result_id, s.state_id))
                    histories.append((ids, capture(s)))
            for ids, saved in histories[1:]:
                self.assertEqual(ids, histories[0][0])
                self.assertEqual(saved[0], histories[0][1][0])
                for key in saved[1]:
                    np.testing.assert_array_equal(saved[1][key], histories[0][1][1][key])

    def test_self_contained_restart_in_new_plan(self):
        kwargs = dict(anderson_policy=at.AndersonPolicy(), adaptive_inner_policy=at.AdaptiveInnerPolicy(),
                      preconditioner_reuse_policy=at.PreconditionerReusePolicy())
        with plan(self.p, **kwargs) as q:
            s = q.advance(self.s, .001, source='physical').state
            expected = q.mechanical_snapshot(s, source='restart diagnostic')
            following = q.advance(s, .001, source='following step')
        restored = at.ThermochemicalState.restore(*capture(s))
        with plan(restored.problem, **kwargs) as q:
            actual = q.mechanical_snapshot(restored, source='restart diagnostic')
            resumed = q.advance(restored, .001, source='following step')
        self.assertEqual(actual.result_id, expected.result_id)
        self.assertEqual(resumed.result_id, following.result_id)
        self.assertEqual(restored.next_initial_guess.guess_id, s.next_initial_guess.guess_id)

    def test_fresh_process_restart(self):
        with plan(self.p) as q:
            s = q.advance(self.s, .001, source='physical').state
            expected = q.mechanical_snapshot(s, source='fresh-process diagnostic')
            following = q.advance(s, .001, source='following step')
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            meta, arrays = capture(s)
            (root/'state.json').write_text(json.dumps(meta), encoding='utf-8')
            np.savez(root/'state.npz', **arrays)
            code = '''import json,sys,numpy as np
from pathlib import Path
import atlas_tectonics as at
from atlas_tectonics.resources import WorkBudget
p=Path(sys.argv[1]); budget=WorkBudget(128<<20)
with np.load(p/'state.npz',allow_pickle=False) as data:
    s=at.ThermochemicalState.restore(json.loads((p/'state.json').read_text()),dict(data),budget=budget)
with at.PreparedThermochemical2D(s.problem,nonlinear_start='previous-stage1',budget=budget) as q:
    r=q.mechanical_snapshot(s,source='fresh-process diagnostic')
    n=q.advance(s,.001,source='following step')
assert budget.reserved_bytes==0
print(json.dumps([r.result_id,n.result_id,s.next_initial_guess.guess_id]))
'''
            env = dict(os.environ, PYTHONPATH=str(Path(at.__file__).resolve().parents[1]))
            for key in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMBA_NUM_THREADS'):
                env[key] = '1'
            run = subprocess.run([sys.executable, '-B', '-c', code, str(root)], env=env,
                                 capture_output=True, text=True, timeout=45, check=True)
        self.assertEqual(json.loads(run.stdout),
                         [expected.result_id, following.result_id, s.next_initial_guess.guess_id])

    def test_incompatible_mechanical_plan_refuses_without_cold_fallback(self):
        with plan(self.p) as q:
            s = q.advance(self.s, .001, source='physical').state
        saved = capture(s)
        budget = WorkBudget(128 << 20)
        with plan(self.p, anderson_policy=at.AndersonPolicy(), budget=budget) as q:
            with self.assertRaisesRegex(at.TectonicsError, 'initial-guess source/plan'):
                q.mechanical_snapshot(s, source='incompatible plan')
            self.assertFalse(q._active)
        self.assertEqual(budget.reserved_bytes, 0)
        self.assert_unchanged(s, saved)

    def test_thermal_only_policy_change_does_not_rebind_continuation(self):
        with plan(self.p) as q:
            s = q.advance(self.s, .001, source='physical').state
        thermal = replace(at.ThermochemicalPolicy(), max_steps=20)
        with plan(self.p, policy=thermal) as q:
            r = q.mechanical_snapshot(s, source='same mechanical contract')
            self.assertEqual(r.descriptor()['initial_guess']['guess_id'], s.next_initial_guess.guess_id)
            with self.assertRaisesRegex(at.TectonicsError, 'no automatic rebind'):
                q.advance(s, .001, source='forbidden continuation')

    def test_restore_rejects_wrong_seed_plan_epoch_time_and_bytes(self):
        with plan(self.p) as q:
            s = q.advance(self.s, .001, source='physical').state
        for key, value in (('plan_id', '0'*64), ('epoch_id', 'foreign-epoch'),
                           ('time_s', s.time_s+1), ('source_result_id', '0'*64)):
            with self.subTest(key=key):
                meta, arrays = capture(s)
                meta['next_initial_guess']['descriptor'][key] = value
                with self.assertRaises(at.TectonicsError):
                    at.ThermochemicalState.restore(meta, arrays)
        meta, arrays = capture(s)
        arrays['next_guess_u_m_s'][1, 1] += 1
        with self.assertRaises(at.TectonicsError):
            at.ThermochemicalState.restore(meta, arrays)

    def test_source_mutation_refused_and_plan_recovers_after_restoration(self):
        with plan(self.p) as q:
            s = q.advance(self.s, .001, source='physical').state
            saved = capture(s)
            with mock.patch.object(tx, '_check_step_record', lambda *args: None):
                with self.assertRaises(at.TectonicsError):
                    q.mechanical_snapshot(s, source='changed loaded source')
            q.mechanical_snapshot(s, source='restored source')
            self.assert_unchanged(s, saved)

    def test_cancellation_and_faults_do_not_publish_or_poison(self):
        class Interrupt:
            def __init__(self, target, fault):
                self.target, self.fault, self.hit = target, fault, False
            def is_set(self):
                frame = inspect.currentframe().f_back
                try:
                    while frame is not None:
                        if frame.f_code.co_name == self.target:
                            self.hit = True
                            if self.fault:
                                raise at.TectonicsError('injected diagnostic failure')
                            return True
                        frame = frame.f_back
                    return False
                finally:
                    del frame
        kwargs = dict(anderson_policy=at.AndersonPolicy(), adaptive_inner_policy=at.AdaptiveInnerPolicy(),
                      preconditioner_reuse_policy=at.PreconditionerReusePolicy())
        budget = WorkBudget(128 << 20)
        with plan(self.p, budget=budget, **kwargs) as q:
            s = q.advance(self.s, .001, source='physical').state
            saved = capture(s)
            expected = q.advance(s, .001, source='following step')
            for target in ('mechanical_snapshot', '_linear_impl', '_publish'):
                for fault in (False, True):
                    with self.subTest(target=target, fault=fault):
                        token = Interrupt(target, fault)
                        retained = budget.reserved_bytes
                        with self.assertRaises(at.TectonicsError if fault else CancelledError):
                            q.mechanical_snapshot(s, source='interrupted diagnostic', cancel=token)
                        self.assertTrue(token.hit)
                        self.assertEqual(budget.reserved_bytes, retained)
                        self.assertFalse(q._active)
                        self.assertFalse(q._mechanics._active)
                        self.assertIsNone(q._mechanics._reuse_request)
                        self.assertIsNone(q._mechanics._adaptive_request)
                        self.assertIsNone(q._mechanics._preconditioner_workload)
                        self.assert_unchanged(s, saved)
                        self.assertEqual(q.advance(s, .001, source='following step').result_id, expected.result_id)
            self.assert_gates(q.mechanical_snapshot(s, source='successful retry'), q.nonlinear_policy)
        self.assertEqual(budget.reserved_bytes, 0)

    def test_cancellation_after_mechanical_return_still_refuses_publication(self):
        budget = WorkBudget(128 << 20)
        with plan(self.p, budget=budget) as q:
            s = q.advance(self.s, .001, source='physical').state
            saved = capture(s)
            class LateCancel:
                seen_active = False
                hit = False
                def is_set(self):
                    if q._mechanics._active:
                        self.seen_active = True
                    elif self.seen_active and q._active:
                        self.hit = True
                        return True
                    return False
            token = LateCancel()
            retained = budget.reserved_bytes
            with self.assertRaises(CancelledError):
                q.mechanical_snapshot(s, source='late cancellation', cancel=token)
            self.assertTrue(token.hit)
            self.assertEqual(budget.reserved_bytes, retained)
            self.assert_unchanged(s, saved)
            q.mechanical_snapshot(s, source='recovery')
        self.assertEqual(budget.reserved_bytes, 0)

    def test_seed_workspace_is_admitted_and_refusal_is_atomic(self):
        budget = WorkBudget(128 << 20)
        with plan(self.p, budget=budget) as q:
            s = q.advance(self.s, .001, source='physical').state
            saved = capture(s)
            scratch = q._mechanics._scratch_bytes()
            required = scratch + 8*s.next_initial_guess.nbytes + 131072
            retained = budget.reserved_bytes
            # Leave enough for forcing and the original cold solve, but one byte
            # less than the seed-inclusive solver reservation. Never edit limits.
            with budget.reserve(budget.available_bytes-required+1, category='test-competing-reservation'):
                with self.assertRaises(MemoryLimitError):
                    q.mechanical_snapshot(s, source='admission must refuse')
                self.assertFalse(q._active)
                self.assertFalse(q._mechanics._active)
            self.assertEqual(budget.reserved_bytes, retained)
            self.assert_unchanged(s, saved)
            q.mechanical_snapshot(s, source='admission recovered')
            self.assertGreaterEqual(budget.statistics()['category_peaks']['variable-stokes-solve'], required)
        self.assertEqual(budget.reserved_bytes, 0)

    def test_nonconvergence_has_no_published_answer(self):
        budget = WorkBudget(128 << 20)
        with plan(self.p, nonlinear_policy=at.NonlinearStokesPolicy(max_picard_iterations=1), budget=budget) as q:
            with self.assertRaisesRegex(at.TectonicsError, 'fixed Picard envelope'):
                q.mechanical_snapshot(self.s, source='deliberately insufficient work envelope')
            self.assertFalse(q._active)
        self.assertEqual(budget.reserved_bytes, 0)

    def test_constant_mechanics_remains_unseeded(self):
        p = replace(self.p, rheology=at.reference_rheology('constant'), mechanical_mode='constant-r4.2')
        s = at.ThermochemicalState(p, self.s.array('temperature_k'), self.s.array('composition'),
                                  time_s=0., source='constant control')
        with at.PreparedThermochemical2D(p) as q:
            a = q.advance(s, .001, source='constant physical').state
            r = q.mechanical_snapshot(a, source='constant diagnostic')
        self.assertIsNone(a.next_initial_guess)
        self.assertNotIn('initial_guess', r.descriptor())

    def test_zero_force_seed_does_not_invent_motion(self):
        p = replace(self.p, boundary=at.ThermalBoundary2D('insulated'))
        s = at.ThermochemicalState(p, np.full((4, 4), 300.), np.zeros((4, 4)),
                                  time_s=0., source='zero forcing control')
        with plan(p) as q:
            a = q.advance(s, .001, source='rest').state
            r = q.mechanical_snapshot(a, source='rest diagnostic')
            self.assert_gates(r, q.nonlinear_policy)
        for key in ('u_m_s', 'w_m_s', 'pressure_pa'):
            self.assertFalse(np.any(r.array(key)))
        self.assertEqual(r.descriptor()['initial_guess']['guess_id'], a.next_initial_guess.guess_id)

    def test_direct_reference_transport_and_nonunit_geometry(self):
        p = replace(self.p, box=replace(self.p.box, width_m=2., height_m=.75),
                    scales=replace(self.p.scales, length_m=3., viscosity_pa_s=7.))
        s = at.ThermochemicalState(p, self.s.array('temperature_k'), self.s.array('composition'),
                                  time_s=0., source='nonunit control')
        with plan(p, backend='reference', nonlinear_policy=at.NonlinearStokesPolicy(method='direct')) as q:
            a = q.advance(s, .001, source='physical').state
            r = q.mechanical_snapshot(a, source='nonunit diagnostic')
            cold = cold_snapshot(q, a, 'nonunit diagnostic')
            self.assert_gates(r, q.nonlinear_policy)
            for key in ('u_m_s', 'w_m_s', 'pressure_pa'):
                np.testing.assert_allclose(r.array(key), cold.array(key), rtol=1e-7, atol=1e-10)

    def test_problem_provenance_and_lifecycle_guards(self):
        with plan(self.p) as q:
            with self.assertRaises(at.TectonicsError):
                q.mechanical_snapshot(self.s, source='')
            with self.assertRaises(at.TectonicsError):
                q.mechanical_snapshot(self.s, source='x'*2049)
            foreign = replace(self.p, epoch_id='other epoch')
            s = at.ThermochemicalState(foreign, self.s.array('temperature_k'), self.s.array('composition'),
                                      time_s=0., source='foreign')
            with self.assertRaisesRegex(at.TectonicsError, 'state/problem mismatch'):
                q.mechanical_snapshot(s, source='wrong problem')
            with ThreadPoolExecutor(max_workers=1) as pool:
                with self.assertRaisesRegex(at.TectonicsError, 'wrong driving thread'):
                    pool.submit(q.mechanical_snapshot, self.s, source='wrong thread').result()
        with self.assertRaisesRegex(at.TectonicsError, 'closed/active'):
            q.mechanical_snapshot(self.s, source='closed plan')


if __name__ == '__main__':
    unittest.main()
