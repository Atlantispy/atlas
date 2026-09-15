"""Independent SDIRK2 method, conservation, physical guard and restart tests.

Linear-storage mocks validate the integrator algebra only, not a new soil law.
Actual unsaturated tests use an independently coded retained theta-state ODE
oracle; neither this nor a conservation PASS constitutes field validation.
"""
from contextlib import contextmanager
from dataclasses import asdict, replace
import hashlib
import json
import math
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np

from . import soil_water as w
from . import hydraulic_jacobian as hj
from work.generator_upgrade_r3.test_soil_water import independent_theta_solution

E = 'SYNTHETIC NUMERICAL METHOD ORACLE; NO DIADEM OR AGRONOMIC DEFAULT'
S = 'SYNTHETIC TEST'
GAMMA = 1-1/math.sqrt(2)


def controls(method='SDIRK2', **changes):
    args = dict(initial_dt_s=5., min_dt_s=1e-6, max_dt_s=10., theta_atol=1e-6,
                head_atol_m=1e-5, flux_integral_atol_m=1e-8, relative_tolerance=1e-5,
                nonlinear_mass_atol_m=1e-11, total_mass_atol_m=1e-8,
                min_head_m=-1e5, max_head_m=10., max_steps=1000, max_nfev=300)
    if method is not None:
        args['integration_method'] = method
    args.update(changes)
    return w.Controls(**args)


def fixture(n=4, *, duration=60., rain=3e-6, heads=None, k=1e-5, boundary='free_drainage', lower_head=None):
    layers = tuple(w.HydraulicLayer(str(i), .1, .05, .4, 2., 2., .5, k, E, S) for i in range(n))
    column = w.Column('method-reference', layers, n, E, S)
    state = w.initial_state(column, tuple(heads) if heads is not None else (-1.,)*n)
    forcing = w.Forcing(duration, rain, 0., None, E, S)
    lower = w.Boundary(boundary, lower_head, E, S)
    return column, state, forcing, lower


def advance(args, ctl=None):
    return w.advance(*args, ctl or controls(), water_density_kg_m3=1000., gravity_m_s2=9.81)


class LinearKernel:
    """Independent method-only theta=h, dh/dt=-rate*(h-equilibrium)."""
    def __init__(self, column, forcing, boundary, rate=1., equilibrium=0., offset=0., through_flow=0.):
        self.column, self.forcing, self.boundary = column, forcing, boundary
        self.rate, self.equilibrium = rate, equilibrium
        self.offset, self.through_flow = offset, through_flow
        self.dz = np.ones(1)

    def arrays(self, column, head):
        return np.asarray(head)+self.offset, np.ones(1)

    def raw_fluxes(self, column, head, forcing, boundary):
        return np.asarray(head)+self.offset, np.array([self.through_flow, self.through_flow+self.rate*(head[0]-self.equilibrium)]), np.zeros(1)

    def residual_and_jacobian(self, head, theta_old, dt):
        # Reject an attempted fictitious stage-2 water state in this oracle too.
        if np.any(theta_old < 0) or np.any(theta_old > 1):
            raise ValueError('stage theta_old must remain the actual physical state')
        value = head+self.offset-theta_old+dt*self.rate*(head-self.equilibrium)
        return value, np.array([[1+dt*self.rate]])

    def fluxes(self, head):
        theta, q, sink = self.raw_fluxes(self.column, head, self.forcing, self.boundary)
        return SimpleNamespace(theta=theta, q=q, sink=sink)


@contextmanager
def linear_case(*, initial=.3, rate=1., equilibrium=0., duration=1., offset=0., through_flow=0.):
    layer = w.HydraulicLayer('method-only', 1., 0., 1., 2., 2., .5, 1., E, S)
    column = w.Column('LINEAR METHOD MOCK, NOT RICHARDS PHYSICS', (layer,), 1, E, S)
    forcing = w.Forcing(duration, through_flow, 0., None, E, S)
    boundary = w.Boundary('fixed_head', 0., E, S)
    kernel = LinearKernel(column, forcing, boundary, rate, equilibrium, offset, through_flow)
    state = w.initial_state(column, (initial,))
    with patch.object(w, '_arrays', side_effect=kernel.arrays), \
         patch.object(w, '_fluxes', side_effect=kernel.raw_fluxes), \
         patch.object(w.hj, 'prepare', return_value=kernel):
        yield column, state, forcing, boundary, kernel


def scalar_stage(initial, dt, rate=1., equilibrium=0.):
    first = equilibrium+(initial-equilibrium)/(1+GAMMA*dt*rate)
    known = -(1-GAMMA)*dt*rate*(first-equilibrium)
    second = (initial+known+GAMMA*dt*rate*equilibrium)/(1+GAMMA*dt*rate)
    transfers = ((1-GAMMA)*dt*rate*(first-equilibrium), GAMMA*dt*rate*(second-equilibrium))
    return first, second, known, transfers


class SoilIntegrationTests(unittest.TestCase):
    def modelled(self, result):
        self.assertEqual(result['status'], 'MODELLED', result)
        self.assertLessEqual(abs(result['ledger']['water_residual_m']), 1e-8)

    def test_default_remains_backward_euler_and_method_is_explicit(self):
        self.assertEqual(controls(None).integration_method, 'BACKWARD_EULER')
        self.assertEqual(controls().integration_method, 'SDIRK2')
        self.assertEqual(asdict(controls())['integration_method'], 'SDIRK2')

    def test_invalid_method_values_reject(self):
        for invalid in ('SDIRK', 'sdirk2', 'UNKNOWN', '', None, True, 1):
            with self.subTest(value=invalid), self.assertRaises(ValueError):
                replace(controls(), integration_method=invalid)

    def test_sdirk_linear_scalar_matches_independent_stability_function(self):
        with linear_case() as (column, state, forcing, boundary, kernel):
            for dt in (.01, .2, 1.):
                result = w._step(column, np.array(state.head_m), dt, forcing, boundary, controls(), kernel=kernel)
                self.assertIsNotNone(result)
                factor = (1-(1-2*GAMMA)*dt)/(1+GAMMA*dt)**2
                self.assertAlmostEqual(result['head'][0], .3*factor, delta=2e-14)
                self.assertAlmostEqual(result['q_m'][-1], .3-result['head'][0], delta=2e-14)
                self.assertEqual(len(result['quadrature']), 2)

    def test_backward_euler_linear_scalar_is_unchanged(self):
        with linear_case() as (column, state, forcing, boundary, kernel):
            result = w._step(column, np.array(state.head_m), .5, forcing, boundary, controls('BACKWARD_EULER'), kernel=kernel)
            self.assertIsNotNone(result)
            self.assertAlmostEqual(result['head'][0], .3/1.5, places=14)
            self.assertEqual(len(result['quadrature']), 1)

    def test_second_stage_uses_actual_old_state_and_separate_known_flux(self):
        with linear_case(initial=.8, equilibrium=.2, duration=8.) as (column, state, forcing, boundary, kernel):
            actual = w._stage
            with patch.object(w, '_stage', wraps=actual) as traced:
                result = w._step(column, np.array(state.head_m), 8., forcing, boundary, controls(), kernel=kernel)
            self.assertIsNotNone(result)
            first, expected, known, transfers = scalar_stage(.8, 8., equilibrium=.2)
            self.assertLess(.8+known, 0.)  # a pseudo old theta would be unphysical
            self.assertGreater(expected, 0.)
            self.assertEqual(len(traced.call_args_list), 2)
            np.testing.assert_array_equal(traced.call_args_list[1].args[1], state.head_m)
            self.assertAlmostEqual(traced.call_args_list[1].kwargs['known_source_m'][0], known, delta=2e-14)
            self.assertAlmostEqual(result['head'][0], expected, delta=2e-14)

    def test_stage_quadrature_weights_positive_and_accounted_once(self):
        with linear_case(initial=.8, equilibrium=.2, duration=4.) as (column, state, forcing, boundary, kernel):
            result = w._step(column, np.array(state.head_m), 4., forcing, boundary, controls(), kernel=kernel)
            _, expected, _, transfers = scalar_stage(.8, 4., equilibrium=.2)
            self.assertIsNotNone(result)
            weights = [v[0] for v in result['quadrature']]
            self.assertTrue(all(v > 0 for v in weights)); self.assertAlmostEqual(sum(weights), 4., places=14)
            self.assertGreater(transfers[0], 0.); self.assertLess(transfers[1], 0.)
            for row, quantity in zip(result['quadrature'], transfers):
                self.assertAlmostEqual(row[1][-1], quantity, delta=2e-14)
            self.assertAlmostEqual(sum(row[1][-1] for row in result['quadrature']), result['q_m'][-1], delta=2e-14)
            self.assertAlmostEqual(.8-expected, result['q_m'][-1], delta=2e-14)

    def test_public_ledger_preserves_opposing_stage_fluxes_not_only_net(self):
        with linear_case(initial=.8, equilibrium=.2, duration=8.) as (column, state, forcing, boundary, kernel):
            ctl = controls(initial_dt_s=8., max_dt_s=8., theta_atol=1., head_atol_m=1., flux_integral_atol_m=1.)
            result = advance((column, state, forcing, boundary), ctl)
            self.modelled(result)
            _, midway, _, first_fluxes = scalar_stage(.8, 4., equilibrium=.2)
            _, final, _, second_fluxes = scalar_stage(midway, 4., equilibrium=.2)
            all_fluxes = first_fluxes+second_fluxes
            expected_down = sum(max(0., v) for v in all_fluxes)
            expected_up = sum(max(0., -v) for v in all_fluxes)
            self.assertGreater(expected_down, 0.); self.assertGreater(expected_up, 0.)
            self.assertAlmostEqual(result['ledger']['bottom_downward_m'], expected_down, delta=3e-14)
            self.assertAlmostEqual(result['ledger']['bottom_upward_m'], expected_up, delta=3e-14)
            self.assertAlmostEqual(result['ledger']['root_zone_gross_downward_m'], expected_down, delta=3e-14)
            self.assertAlmostEqual(result['ledger']['root_zone_upward_capillary_m'], expected_up, delta=3e-14)
            self.assertAlmostEqual(result['state'].head_m[0], final, delta=3e-14)

    def test_stiff_stage_overshoot_cannot_false_pass_gross_flux_accuracy(self):
        # Exact h=.3 exp(-1e10*t), theta=.5+h stays in [.5,.8]. All actual
        # bottomflow is downward: .3m total. A merely L-stable SDIRK endpoint
        # can nevertheless produce spurious opposing stage integrals .724/.424.
        with linear_case(initial=.3, rate=1e10, offset=.5, duration=60.) as (column, state, forcing, boundary, kernel):
            ctl = controls(initial_dt_s=60., max_dt_s=60., theta_atol=1e-8,
                           head_atol_m=1e-8, flux_integral_atol_m=1e-10, relative_tolerance=1e-6)
            result = advance((column, state, forcing, boundary), ctl)
        if result['status'] == 'NUMERICAL_FAILURE':
            self.assertIsNone(result['state']); self.assertIsNone(result['ledger'])
        else:
            self.modelled(result)
            allowance = ctl.flux_integral_atol_m+ctl.relative_tolerance*.3
            self.assertAlmostEqual(result['ledger']['bottom_downward_m'], .3, delta=allowance)
            self.assertLessEqual(result['ledger']['bottom_upward_m'], allowance)

    def test_initial_reversal_not_hidden_by_positive_stage_fluxes(self):
        # qtop=.1, qbottom=.1+1e10*h, h0=-.3: initial upflow transfers ~.3m
        # before bottomflow turns downward. All long-step SDIRK sample stages
        # can lie AFTER that crossing, despite the exact nonzero upward stock.
        rate, initial, supply, duration = 1e10, -.3, .1, 60.
        crossing = math.log(-rate*initial/supply)/rate
        expected_up = -initial-supply/rate-supply*crossing
        expected_down = supply*duration+initial+expected_up
        with linear_case(initial=initial, rate=rate, offset=.5, through_flow=supply, duration=duration) as (column, state, forcing, boundary, kernel):
            ctl = controls(initial_dt_s=60., max_dt_s=60., theta_atol=1e-8,
                           head_atol_m=1e-8, flux_integral_atol_m=1e-10, relative_tolerance=1e-6)
            result = advance((column, state, forcing, boundary), ctl)
        if result['status'] == 'NUMERICAL_FAILURE':
            self.assertIsNone(result['state']); self.assertIsNone(result['ledger'])
        else:
            self.modelled(result)
            allowance = ctl.flux_integral_atol_m+ctl.relative_tolerance*max(expected_down, expected_up)
            self.assertAlmostEqual(result['ledger']['bottom_downward_m'], expected_down, delta=allowance)
            self.assertAlmostEqual(result['ledger']['bottom_upward_m'], expected_up, delta=allowance)

    def test_resolved_stiff_relaxation_models_correct_monotone_gross_flux(self):
        with linear_case(initial=.3, rate=1e10, offset=.5, duration=60.) as (column, state, forcing, boundary, kernel):
            ctl = controls(initial_dt_s=60., max_dt_s=60., min_dt_s=1e-14, max_steps=10000,
                           theta_atol=1e-8, head_atol_m=1e-8, flux_integral_atol_m=1e-10, relative_tolerance=1e-6)
            result = advance((column, state, forcing, boundary), ctl)
        self.modelled(result)
        allowance = ctl.flux_integral_atol_m+ctl.relative_tolerance*.3
        self.assertAlmostEqual(result['ledger']['bottom_downward_m'], .3, delta=allowance)
        self.assertLessEqual(result['ledger']['bottom_upward_m'], allowance)
        self.assertAlmostEqual(result['ledger']['final_storage_m'], .5, delta=1e-8)

    def test_resolved_initial_reversal_matches_exact_crossing_integrals(self):
        rate, initial, supply, duration = 1e10, -.3, .1, 60.
        crossing = math.log(-rate*initial/supply)/rate
        expected_up = -initial-supply/rate-supply*crossing
        expected_down = supply*duration+initial+expected_up
        with linear_case(initial=initial, rate=rate, offset=.5, through_flow=supply, duration=duration) as (column, state, forcing, boundary, kernel):
            ctl = controls(initial_dt_s=60., max_dt_s=60., min_dt_s=1e-14, max_steps=10000,
                           theta_atol=1e-8, head_atol_m=1e-8, flux_integral_atol_m=1e-10, relative_tolerance=1e-6)
            result = advance((column, state, forcing, boundary), ctl)
        self.modelled(result)
        allowance = ctl.flux_integral_atol_m+ctl.relative_tolerance*max(expected_down, expected_up)
        self.assertAlmostEqual(result['ledger']['bottom_downward_m'], expected_down, delta=allowance)
        self.assertAlmostEqual(result['ledger']['bottom_upward_m'], expected_up, delta=allowance)
        self.assertAlmostEqual(result['ledger']['final_storage_m'], .5, delta=1e-8)

    def test_actual_smooth_unsaturated_time_error_is_second_order(self):
        column, state, forcing, boundary = fixture(duration=300.)
        expected = independent_theta_solution(column, state.head_m, 300., forcing.surface_input_m_s)
        kernel = hj.prepare(column, forcing, boundary); errors = []
        for dt in (30., 15., 7.5):
            head = np.array(state.head_m)
            for _ in range(round(forcing.duration_seconds/dt)):
                result = w._step(column, head, dt, forcing, boundary, controls(), kernel=kernel)
                self.assertIsNotNone(result)
                head = result['head']
            theta, _ = w._arrays(column, head)
            errors.append(float(np.max(np.abs(theta-expected))))
        self.assertGreater(min(errors), 1e-11)
        for a, b in zip(errors, errors[1:]):
            self.assertGreater(a/b, 3.3, errors); self.assertLess(a/b, 4.8, errors)

    def test_actual_adaptive_sdirk_matches_independent_unsaturated_oracle(self):
        args = fixture(duration=120.)
        result = advance(args); self.modelled(result)
        expected = independent_theta_solution(args[0], args[1].head_m, 120., args[2].surface_input_m_s)
        np.testing.assert_allclose([r['theta_m3_m3'] for r in result['layers']], expected, rtol=0, atol=5e-7)
        self.assertIn('SDIRK2', result['model'])

    def test_saturated_darcy_runoff_and_pressure_guards_remain(self):
        args = fixture(duration=20., rain=2e-5, heads=(0.,)*4)
        result = advance(args); self.modelled(result)
        self.assertAlmostEqual(result['ledger']['bottom_downward_m'], 20e-5, delta=1e-12)
        self.assertAlmostEqual(result['ledger']['surface_runoff_m'], 20e-5, delta=1e-12)
        self.assertAlmostEqual(result['ledger']['initial_storage_m'], result['ledger']['final_storage_m'], delta=1e-12)

    def test_indeterminate_saturated_pressure_still_fails_closed(self):
        args = fixture(1, duration=1., rain=0., heads=(1.,), k=0., boundary='no_flow')
        result = advance(args, controls(initial_dt_s=1., min_dt_s=1., max_dt_s=1.))
        self.assertEqual(result['status'], 'NUMERICAL_FAILURE'); self.assertIsNone(result['state'])
        self.assertIsNone(result['layers']); self.assertIsNone(result['ledger'])

    def test_short_saturated_interval_does_not_certify_wrong_head(self):
        args = fixture(1, duration=1e-6, rain=0., heads=(0.,), boundary='fixed_head', lower_head=.2)
        result = advance(args, controls(initial_dt_s=1e-6, min_dt_s=1e-8, max_dt_s=1e-6))
        self.modelled(result)
        self.assertAlmostEqual(result['state'].head_m[0], .1, delta=1e-8)

    def test_second_stage_failure_does_not_publish_first_stage_state(self):
        args = fixture(1, duration=1.)
        kernel = hj.prepare(args[0], args[2], args[3])
        actual = w._stage(args[0], np.array(args[1].head_m), GAMMA, args[2], args[3], controls(), kernel=kernel)
        self.assertIsNotNone(actual)
        with patch.object(w, '_stage', side_effect=[actual, None]):
            result = w._step(args[0], np.array(args[1].head_m), 1., args[2], args[3], controls(), kernel=kernel)
        self.assertIsNone(result)

    def test_restart_is_exact_for_identical_sdirk_continuation(self):
        args = fixture(duration=20.); ctl = controls()
        first = advance(args, ctl); self.modelled(first)
        restored = w.state_from_json(w.state_to_json(first['state']), args[0])
        a = advance((args[0], first['state'], args[2], args[3]), ctl)
        b = advance((args[0], restored, args[2], args[3]), ctl)
        self.modelled(a); self.assertEqual(a, b)

    def test_unknown_forcing_does_not_create_sdirk_state_or_flux(self):
        args = list(fixture()); args[2] = replace(args[2], surface_input_m_s=None)
        result = advance(tuple(args))
        self.assertEqual(result['status'], 'UNKNOWN'); self.assertIsNone(result['state']); self.assertIsNone(result['ledger'])

    def test_numerical_method_does_not_modify_controls_or_physical_inputs(self):
        args = fixture(duration=10.); ctl = controls(); before = [asdict(v) for v in (*args, ctl)]
        result = advance(args, ctl); self.modelled(result)
        self.assertEqual(before, [asdict(v) for v in (*args, ctl)])
        self.assertEqual(result['numerics']['controls'], asdict(ctl))


class NonlinearStrategyTests(unittest.TestCase):
    """Nonlinear strategy tests; constitutive mocks are algebraic oracles only."""

    def test_newton_solves_exact_stage_without_least_squares(self):
        with linear_case() as (column, state, forcing, boundary, kernel), \
             patch.object(w, 'least_squares', side_effect=AssertionError('unexpected fallback')):
            ctl = controls()
            before = [asdict(v) for v in (column, state, forcing, boundary, ctl)]
            result = w._stage(column, np.array(state.head_m), .5, forcing, boundary, ctl, kernel=kernel)
            self.assertIsNotNone(result)
            self.assertAlmostEqual(result['head'][0], .2, delta=2e-15)
            self.assertLessEqual(result['nfev'], 40)
            self.assertEqual(before, [asdict(v) for v in (column, state, forcing, boundary, ctl)])

    def test_newton_physical_residual_is_authority_not_helper_roundoff(self):
        with linear_case() as (column, state, forcing, boundary, kernel):
            original = kernel.residual_and_jacobian
            def shifted(head, old_theta, dt):
                r, jac = original(head, old_theta, dt)
                return r+1e-4, jac  # controlled mismatch, not a proposed soil law
            with patch.object(kernel, 'residual_and_jacobian', side_effect=shifted), \
                 patch.object(w, 'least_squares', side_effect=AssertionError('unexpected fallback')):
                result = w._stage(column, np.array(state.head_m), .5, forcing, boundary, controls(), kernel=kernel)
            self.assertIsNotNone(result)
            self.assertAlmostEqual(result['head'][0], .2, delta=2e-15)
            self.assertLessEqual(max(abs(result['residual_m'])), 1e-15)

    def test_backward_euler_still_uses_retained_least_squares_strategy(self):
        actual = w.least_squares
        with linear_case() as (column, state, forcing, boundary, kernel), \
             patch.object(w, 'least_squares', wraps=actual) as fallback:
            result = w._stage(column, np.array(state.head_m), .5, forcing, boundary,
                              controls('BACKWARD_EULER'), kernel=kernel)
            self.assertIsNotNone(result)
            self.assertEqual(fallback.call_count, 1)
            np.testing.assert_array_equal(fallback.call_args.args[1], state.head_m)
            self.assertEqual(fallback.call_args.kwargs['max_nfev'], 300)

    def test_single_evaluation_budget_bypasses_newton_without_extra_work(self):
        actual = w.least_squares
        with linear_case() as (column, state, forcing, boundary, kernel), \
             patch.object(w, 'least_squares', wraps=actual) as fallback:
            result = w._stage(column, np.array(state.head_m), .5, forcing, boundary,
                              controls(max_nfev=1), kernel=kernel)
            self.assertIsNone(result)
            self.assertEqual(fallback.call_count, 1)
            self.assertEqual(fallback.call_args.kwargs['max_nfev'], 1)
            np.testing.assert_array_equal(fallback.call_args.args[1], state.head_m)

    def test_newton_linear_failure_falls_back_with_remaining_budget(self):
        actual_solve, actual_ls = np.linalg.solve, w.least_squares
        count = 0
        def fail_once(jac, residual):
            nonlocal count
            count += 1
            if count == 1:
                raise np.linalg.LinAlgError('injected first Newton linear failure')
            return actual_solve(jac, residual)
        with linear_case() as (column, state, forcing, boundary, kernel), \
             patch.object(np.linalg, 'solve', side_effect=fail_once), \
             patch.object(w, 'least_squares', wraps=actual_ls) as fallback:
            result = w._stage(column, np.array(state.head_m), .5, forcing, boundary,
                              controls(max_nfev=20), kernel=kernel)
            self.assertIsNotNone(result)
            self.assertAlmostEqual(result['head'][0], .2, delta=2e-14)
            self.assertEqual(fallback.call_args.kwargs['max_nfev'], 19)
            self.assertLessEqual(result['nfev'], 20)

    def test_damped_newton_never_evaluates_outside_pressure_bounds(self):
        # theta=h**3, zero flux: exact root is unchanged h0=.3. At guess .01,
        # the undamped Newton candidate is ~90m, outside the supplied 10m bound.
        with linear_case() as (column, state, forcing, boundary, kernel):
            inspected = []
            def arrays(c, h):
                return h**3, np.ones(1)
            def fluxes(c, h, f, b):
                return h**3, np.zeros(2), np.zeros(1)
            def equation(h, old_theta, dt):
                inspected.append(h.copy())
                return h**3-old_theta, np.array([[3*h[0]**2]])
            with patch.object(w, '_arrays', side_effect=arrays), \
                 patch.object(w, '_fluxes', side_effect=fluxes), \
                 patch.object(kernel, 'residual_and_jacobian', side_effect=equation), \
                 patch.object(w, 'least_squares', side_effect=AssertionError('unexpected fallback')):
                result = w._stage(column, np.array(state.head_m), .5, forcing, boundary,
                                  controls(), kernel=kernel, guess=np.array([.01]))
            self.assertIsNotNone(result)
            self.assertAlmostEqual(result['head'][0], .3, delta=1e-13)
            self.assertTrue(all(-1e5 < row[0] < 10. for row in inspected))
            self.assertGreater(len(inspected), 2)
            self.assertLessEqual(result['nfev'], 40)

    def test_exhausted_newton_budget_preserves_bounded_failed_fallback(self):
        actual_ls = w.least_squares
        with linear_case() as (column, state, forcing, boundary, kernel):
            original = kernel.residual_and_jacobian
            def slow_jacobian(head, old_theta, dt):
                r, jac = original(head, old_theta, dt)
                return r, 2*jac  # controlled slow convergence/work-limit injection
            with patch.object(kernel, 'residual_and_jacobian', side_effect=slow_jacobian), \
                 patch.object(w, 'least_squares', wraps=actual_ls) as fallback:
                result = w._stage(column, np.array(state.head_m), .5, forcing, boundary,
                                  controls(max_nfev=4), kernel=kernel)
            self.assertIsNone(result)
            self.assertEqual(fallback.call_count, 1)
            self.assertEqual(fallback.call_args.kwargs['max_nfev'], 1)

    def test_backend_success_and_small_mass_do_not_bypass_pressure_gate(self):
        column, state, forcing, boundary = fixture(1, duration=1e-6, rain=0., heads=(0.,),
                                                  boundary='fixed_head', lower_head=.2)
        kernel = hj.prepare(column, forcing, boundary)
        ctl = controls(max_nfev=1)
        def incorrect_success(fun, x0, *, jac, **kwargs):
            return SimpleNamespace(x=x0.copy(), jac=jac(x0), success=True, nfev=1)
        with patch.object(w, 'least_squares', side_effect=incorrect_success):
            result = w._stage(column, np.array(state.head_m), 1e-9, forcing, boundary, ctl, kernel=kernel)
        self.assertIsNone(result)

    def test_actual_eleven_cell_first_rejected_stage_now_resolves_same_gates(self):
        # Exact captured numerical test fixture, not located production authority.
        path = Path(__file__).resolve().parents[2]/'outputs/generator-upgrade-r6/later-failure-cap30-01/fixture-025.json'
        raw = path.read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(),
                         '23c79171630a15563e1f65416aab5a10b5055bcc75ac500baa529504d856c211')
        record = json.loads(raw)
        c = dict(record['column']); c['layers'] = tuple(w.HydraulicLayer(**row) for row in c['layers'])
        column = w.Column(**c)
        f = dict(record['forcing']); u = dict(f['uptake']); u['weights'] = tuple(u['weights'])
        f['uptake'] = w.Uptake(**u); forcing = w.Forcing(**f)
        boundary, ctl = w.Boundary(**record['boundary']), w.Controls(**record['controls'])
        old = np.asarray(record['state']['head_m']); dt = GAMMA*forcing.duration_seconds
        kernel = hj.prepare(column, forcing, boundary)
        before = [asdict(v) for v in (column, forcing, boundary, ctl)]
        with patch.object(w, 'least_squares', side_effect=AssertionError('unexpected fallback')):
            result = w._stage(column, old, dt, forcing, boundary, ctl, kernel=kernel)
        self.assertIsNotNone(result)
        self.assertLessEqual(result['nfev'], 40)
        theta_old, _ = w._arrays(column, old)
        theta, q, et = w._fluxes(column, result['head'], forcing, boundary)
        residual = (theta-theta_old)*kernel.dz-dt*(q[:-1]-q[1:]-et)
        jac = kernel.residual_and_jacobian(result['head'], theta_old, dt)[1]
        correction = np.linalg.solve(jac, residual)
        self.assertLessEqual(max(abs(residual)), ctl.nonlinear_mass_atol_m)
        self.assertLessEqual(max(abs(correction)/(ctl.head_atol_m+ctl.relative_tolerance*abs(result['head']))), .01)
        self.assertEqual(np.linalg.matrix_rank(jac), 11)
        self.assertEqual(before, [asdict(v) for v in (column, forcing, boundary, ctl)])


if __name__ == '__main__':
    unittest.main()
