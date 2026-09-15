"""Independent saturation-branch and actual seasonal pressure-resolution oracles."""
from copy import deepcopy
from dataclasses import replace
from decimal import Decimal, localcontext
from fractions import Fraction as F
from pathlib import Path
import hashlib
import json
import math
from tempfile import TemporaryDirectory
import unittest
import numpy as np

from . import binding, hydraulics as h, richards_numerics as n

E = 'SYNTHETIC TEST: finite-volume saturation branch oracle, not Diadem calibration'
S = 'SYNTHETIC TEST'
ACTUAL_NUMERICAL_RECEIPTS = {}
_ACTUAL_SOURCE = None


def independent_n2_deficit(layer, head):
    if layer.n != 2.: raise ValueError('this independent closed-form oracle is n=2 only')
    if head >= 0: return Decimal(0)
    with localcontext() as context:
        context.prec = 100
        alpha = Decimal.from_float(layer.alpha_per_m)
        pressure = Decimal.from_float(float(head))
        span = Decimal.from_float(layer.theta_s-layer.theta_r)
        return +(span*(1-1/(1+(alpha*pressure)**2).sqrt())*Decimal.from_float(layer.thickness_m))


def actual_inputs(snow='DIAGNOSTIC_DDF4_SIGMA4', cell='upper'):
    global _ACTUAL_SOURCE
    if _ACTUAL_SOURCE is None:
        bundle = binding.load()
        recipe = bundle.reference.recipe(bundle)
        path = Path(__file__).resolve().parents[2]/'outputs/generator-upgrade-r8/biomes-reference-01/n-worker-reference/full-result.json'
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != '19a0975d09d1571e68ed510421b085675753b64ddfba316c8e8e2d68662cb000':
            raise ValueError('sealed R8 physical fixture changed')
        physical = json.loads(raw)
        if physical['source_sha256'] != bundle.parent.parent.source_sha256:
            raise ValueError('actual R8 source identity differs')
        _ACTUAL_SOURCE = bundle, recipe, physical
    bundle, recipe, physical = _ACTUAL_SOURCE
    solver, column, initial, calendar, events, face = bundle.pipeline.hydraulic_inputs(bundle, recipe, physical, snow, 'TEMPERATE_R8_A', cell)
    return bundle, recipe, solver, column, initial, calendar, events, face


def saturation_fixture():
    bundle, recipe, solver, column, _, _, events, face = actual_inputs()
    column = solver.Column(column.column_id, column.layers, face, column.evidence, column.source_status)
    event = events[3]
    forcing = solver.Forcing(float(event.duration_seconds), float(event.liquid_input_m_s),
        float(event.potential_root_demand_m_s), event.uptake, event.evidence, event.source_status)
    heads = np.asarray([-.24925600681089063, -.24912911368925106, -9.794753943082428e-8,
                        .25742632463878046, .2671645364428734, .5141902995880028])
    return solver, n.Adapter(solver), column, heads, forcing, event.boundary, solver.Controls(**recipe['hydraulic_controls'])


def seasonal(case, *, maximum_step=None, original=False, **kw):
    bundle, recipe, solver, column, initial, calendar, events, face = case
    controls = solver.Controls(**recipe['hydraulic_controls'])
    if maximum_step is not None: controls = replace(controls, max_dt_s=maximum_step)
    return bundle.pipeline.hydraulics.run_year(solver if original else n.Adapter(solver), column, initial, calendar, events, controls,
        root_boundary_index=face, water_density_kg_m3=recipe['water_density_kg_m3'], gravity_m_s2=recipe['gravity_m_s2'],
        duration_atol_s=recipe['duration_atol_s'], budget_atol_m=recipe['budget_atol_m'],
        evidence=E, source_status=S, source_binding_sha256=bundle.source_sha256,
        scenario_id=events[0].vegetation_hypothesis_id+'/'+column.column_id, **kw)


class SaturationResolutionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.solver, cls.adapter, cls.column, cls.heads, cls.forcing, cls.boundary, cls.controls = saturation_fixture()

    def test_actual_reproduced_tiny_steps_no_longer_freeze_heads(self):
        s, a, c, old, f, b, ctl = self.solver, self.adapter, self.column, self.heads, self.forcing, self.boundary, self.controls
        dt = 5.029141902923584e-6
        predecessor = s._step(c, old, dt/2, f, b, ctl)
        self.assertIsNotNone(predecessor); np.testing.assert_array_equal(predecessor['head'], old)
        for seconds in (dt, dt/2, dt/4):
            result = a._step(c, old, seconds, f, b, ctl)
            self.assertIsNotNone(result)
            self.assertGreater(result['head'][2], 0.)
            self.assertGreater(np.max(np.abs(result['head']-old)), .001)
            self.assertLess(np.max(np.abs(result['residual_m'])), ctl.nonlinear_mass_atol_m)

    def test_actual_stage_has_insufficient_remaining_storage(self):
        s, c, old, f, b = self.solver, self.column, self.heads, self.forcing, self.boundary
        theta, q, sink = s._fluxes(c, old, f, b)
        deficit = (c.layers[2].theta_s-theta[2])*c.layers[2].thickness_m
        required = 2.514570951461792e-6*(q[2]-q[3]-sink[2])
        self.assertGreater(required, deficit*10)
        self.assertLess(deficit, 3e-15)

    def test_analytical_one_cell_storage_overfill_without_newton_sign_crossing(self):
        s = self.solver
        layer = s.HydraulicLayer('near-saturation', 1., .02, .25, 2., 2., .5, 1e-6, E, S)
        col = s.Column('one-cell-exact', (layer,), 1, E, S)
        old = np.asarray([-1e-7]); theta, _ = s._arrays(col, old)
        deficit = float(independent_n2_deficit(layer, old[0]))
        dt = 1.; rain = float(1.5*deficit/dt)
        forcing = s.Forcing(dt, rain, 0., None, E, S); boundary = s.Boundary('no_flow', None, E, S)
        ctl = replace(self.controls, initial_dt_s=1., max_dt_s=1.)
        kernel = s.hj.prepare(col, forcing, boundary)
        residual, jac = kernel.residual_and_jacobian(old, theta, dt)
        correction = np.linalg.solve(jac, residual)
        self.assertLess((old-correction)[0], 0.)
        expected = layer.thickness_m/2*(1-deficit/(dt*layer.ksat_m_s))
        result = self.adapter._stage(col, old, dt, forcing, boundary, ctl, kernel=kernel)
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result['head'][0], expected, places=9)
        self.assertAlmostEqual(result['q_m'][0], deficit, places=18)

    def test_actual_types_laws_and_no_predecessor_mutation(self):
        self.assertIs(self.adapter.Column, self.solver.Column)
        self.assertIs(self.adapter.State, self.solver.State)
        self.assertIs(self.adapter.hydraulic_properties, self.solver.hydraulic_properties)
        self.assertEqual(self.adapter.numerical_binding()['retained_solver']['sha256'], n.RETAINED_SOLVER_SHA256)
        self.assertEqual(self.adapter.numerical_binding()['implementation'], n.IMPLEMENTATION)
        self.assertEqual(n.original_numerical_binding(self.solver)['implementation'], 'R6_RETAINED_NUMERICAL_EXECUTION')

    def test_independent_surface_cap_restart_can_temporarily_increase_residual(self):
        s = self.solver
        layer = s.HydraulicLayer('cap-restart', 1., .05, .45, 2., 2., .5, 1e-6, E, S)
        col = s.Column('one-cell-cap-restart', (layer,), 1, E, S)
        old = np.asarray([-1e-7]); theta, _ = s._arrays(col, old)
        deficit = float(independent_n2_deficit(layer, old[0]))
        rain = 1e-8; dt = 1.5*deficit/rain
        forcing = s.Forcing(dt, rain, 0., None, E, S); boundary = s.Boundary('no_flow', None, E, S)
        result = self.adapter._stage(col, old, dt, forcing, boundary, self.controls,
            kernel=s.hj.prepare(col, forcing, boundary))
        self.assertIsNotNone(result)
        expected = .5*(1-deficit/(dt*layer.ksat_m_s))
        self.assertAlmostEqual(result['head'][0], expected, places=12)
        self.assertLess(abs(float(result['q_m'][0])-deficit), 1e-25)

    def test_small_head_capacity_and_signed_changes_match_decimal_oracle(self):
        s = self.solver
        layer = s.HydraulicLayer('decimal-oracle', .5049681216425833, .02, .25, 2., 2., .5, 1e-6, E, S)
        col = s.Column('decimal-oracle', (layer,), 1, E, S)
        for old, new in ((-8.502448631645938e-9, -4.749297860597875e-9), (-1e-10, -2e-10),
                         (-1e-7, .01), (.01, -1e-7), (.1, .2), (-.7, -.70000000001)):
            with self.subTest(old=old, new=new), localcontext() as context:
                context.prec = 100
                before = independent_n2_deficit(layer, old); after = independent_n2_deficit(layer, new)
                expected = before-after
                change = n.storage_change_m(col, (old,), (new,))[0]
                capacity = n.remaining_capacity_m(col, (old,))[0]
                allowance = max(abs(expected)*Decimal('2e-14'), Decimal('1e-40'))
                if old < -1e-6 and new < -1e-6:
                    # Independent absolute roundoff allowance for subtracting
                    # two ordinary, nearly equal log-Se evaluations: four ULPs
                    # per evaluated log, propagated through exp (derivative
                    # <=1), then scaled by the finite storage span. This is
                    # not a general relative relaxation at saturation.
                    a = n._log_effective_saturation(layer, old)
                    b = n._log_effective_saturation(layer, new)
                    allowance += Decimal.from_float(4*(math.ulp(a)+math.ulp(b))*(layer.theta_s-layer.theta_r)*layer.thickness_m)
                self.assertLessEqual(abs(Decimal.from_float(float(change))-expected), allowance)
                self.assertLessEqual(abs(Decimal.from_float(float(capacity))-before), max(abs(before)*Decimal('2e-14'), Decimal('1e-40')))
        old, new = -1e-10, -2e-10
        self.assertEqual(s.hydraulic_properties(layer, old)[0], s.hydraulic_properties(layer, new)[0])
        self.assertLess(n.storage_change_m(col, (old,), (new,))[0], 0.)

    def test_stable_storage_ordinary_range_matches_retained_law(self):
        s = self.solver
        for layer in self.column.layers:
            col = s.Column('one-law', (layer,), 1, E, S)
            for a, b in ((-10., -1.), (-1., -.1), (-.1, .2), (.2, -.1), (-.2, -4.)):
                expected = (s.hydraulic_properties(layer, b)[0]-s.hydraulic_properties(layer, a)[0])*layer.thickness_m
                self.assertAlmostEqual(n.storage_change_m(col, (a,), (b,))[0], expected, places=15)

    def test_saturated_unanchored_compartment_still_fails_closed(self):
        s = self.solver
        layer = s.HydraulicLayer('isolated', 1., .02, .25, 2., 2., .5, 0., E, S)
        col = s.Column('isolated-saturated', (layer,), 1, E, S)
        forcing = s.Forcing(1., 0., 0., None, E, S); boundary = s.Boundary('no_flow', None, E, S)
        self.assertIsNone(self.adapter._step(col, np.asarray([.1]), 1., forcing, boundary, self.controls))

    def test_unchanged_unknown_failure_and_controls_contract(self):
        s, c, f, b, ctl = self.solver, self.column, self.forcing, self.boundary, self.controls
        state = s.initial_state(c, tuple(float(x) for x in self.heads))
        missing = replace(f, surface_input_m_s=None)
        result = self.adapter.advance(c, state, missing, b, ctl, water_density_kg_m3=1000., gravity_m_s2=9.81)
        self.assertEqual(result['status'], 'UNKNOWN'); self.assertIsNone(result['state'])
        self.assertEqual(result['numerical_implementation'], n.IMPLEMENTATION)
        before = deepcopy(ctl)
        result = self.adapter.advance(c, state, replace(f, duration_seconds=1.), b, replace(ctl, max_steps=1, initial_dt_s=.1, max_dt_s=.1), water_density_kg_m3=1000., gravity_m_s2=9.81)
        self.assertEqual(result['status'], 'NUMERICAL_FAILURE'); self.assertEqual(ctl, before)

    def test_unsaturated_sealed_equilibrium_is_unchanged(self):
        s = self.solver
        layer = s.HydraulicLayer('sealed', 1., .02, .25, 2., 2., .5, 0., E, S)
        col = s.Column('sealed-equilibrium', (layer,), 1, E, S)
        old = np.asarray([-1.]); forcing = s.Forcing(1., 0., 0., None, E, S)
        boundary = s.Boundary('no_flow', None, E, S)
        for method in ('SDIRK2', 'BACKWARD_EULER'):
            ctl = replace(self.controls, integration_method=method)
            original = s._step(col, old, 1., forcing, boundary, ctl)
            corrected = self.adapter._step(col, old, 1., forcing, boundary, ctl)
            np.testing.assert_array_equal(corrected['head'], original['head'])
            np.testing.assert_array_equal(corrected['q_m'], original['q_m'])
            np.testing.assert_array_equal(corrected['residual_m'], original['residual_m'])

    def test_unknown_method_and_stale_kernel_are_not_accepted(self):
        with self.assertRaises(ValueError): replace(self.controls, integration_method='implicit-default')
        kernel = self.solver.hj.prepare(self.column, self.forcing, self.boundary)
        with self.assertRaises(ValueError):
            self.adapter._step(self.column, self.heads, 1., replace(self.forcing, duration_seconds=1.), self.boundary, self.controls, kernel=kernel)

    def jump_case(self, rain=1e-8):
        s = self.solver
        layer = s.HydraulicLayer('jump', 1., .05, .45, 2., 2., .5, 1e-6, E, S)
        col = s.Column('independent-pressure-jump', (layer,), 1, E, S)
        old = np.asarray([-1e-7]); deficit = float(independent_n2_deficit(layer, old[0]))
        fill = deficit/rain
        forcing = s.Forcing(16*fill, rain, 0., None, E, S)
        boundary = s.Boundary('no_flow', None, E, S)
        return col, old, deficit, fill, forcing, boundary

    def jump_trial(self, col, old, forcing, boundary, dt, controls):
        steps = [self.adapter._step(col, old, dt, forcing, boundary, controls),
                 self.adapter._step(col, old, dt/2, forcing, boundary, controls)]
        self.assertTrue(all(x is not None for x in steps))
        steps.append(self.adapter._step(col, steps[1]['head'], dt/2, forcing, boundary, controls))
        self.assertIsNotNone(steps[2])
        return steps, self.solver._temporal_errors(col, *steps, controls)

    def test_independent_pressure_jump_has_nonmonotone_local_error(self):
        col, old, deficit, fill, forcing, boundary = self.jump_case()
        _, smaller = self.jump_trial(col, old, forcing, boundary, 8*fill, self.controls)
        steps, larger = self.jump_trial(col, old, forcing, boundary, 16*fill, self.controls)
        self.assertGreater(smaller[0], 1); self.assertLess(larger[0], 1)
        self.assertEqual(steps[2]['head'][0], .5)
        down = sum(float(np.maximum(q, 0)[0]) for step in steps[1:] for _, q, _ in step['quadrature'])
        up = sum(float(np.maximum(-q, 0)[0]) for step in steps[1:] for _, q, _ in step['quadrature'])
        self.assertLess(abs((down-up)-deficit), 1e-27)
        # True gross values are D and zero. Numerical positive quadrature
        # contains a small artificial reversal: quantify, do not call exact.
        self.assertGreater(up, 0)
        self.assertLess(abs(down-deficit), self.controls.flux_integral_atol_m)
        self.assertLess(up, self.controls.flux_integral_atol_m)

    def test_independent_doubled_rain_shifts_pressure_jump_gate(self):
        col, old, _, fill, forcing, boundary = self.jump_case(2e-8)
        _, small = self.jump_trial(col, old, forcing, boundary, 16*fill, self.controls)
        _, large = self.jump_trial(col, old, forcing, boundary, 64*fill, self.controls)
        self.assertGreater(small[0], 1); self.assertLess(large[0], 1)

    def test_tight_gross_tolerance_rejects_jump_even_when_head_passes(self):
        col, old, _, fill, forcing, boundary = self.jump_case()
        ctl = replace(self.controls, flux_integral_atol_m=1e-18)
        _, errors = self.jump_trial(col, old, forcing, boundary, 16*fill, ctl)
        self.assertLess(errors[1]['head_m']['error_ratio'], 1)
        self.assertEqual(errors[2], 'unresolved_flow_reversal')
        self.assertGreater(errors[0], 100)

    def test_floor_recovery_retains_analytic_endpoint_budget_and_exact_clock(self):
        col, old, deficit, fill, forcing, boundary = self.jump_case()
        ctl = replace(self.controls, initial_dt_s=8*fill, min_dt_s=8*fill, max_dt_s=16*fill)
        state = self.solver.initial_state(col, tuple(float(x) for x in old))
        out = self.adapter.advance(col, state, forcing, boundary, ctl, water_density_kg_m3=1000., gravity_m_s2=9.81)
        self.assertEqual(out['status'], 'MODELLED', out.get('reason'))
        self.assertEqual(out['state'].head_m, (.5,))
        self.assertEqual(out['numerics']['ascending_recovery_sequences'], 1)
        self.assertEqual(out['numerics']['ascending_recovery_trials'], 1)
        self.assertEqual(out['numerics']['attempts'], 2)
        ledger = out['ledger']
        self.assertLess(abs(ledger['infiltration_m']-ledger['surface_exfiltration_m']-deficit), 1e-27)
        self.assertLess(abs(ledger['surface_runoff_m']-(forcing.surface_input_m_s*forcing.duration_seconds-deficit)), 1e-27)
        elapsed = F(0)
        for step in out['numerics']['accepted_steps_detail']:
            self.assertEqual(F(step['dt_seconds_exact']), F(step['dt_seconds']))
            elapsed += F(step['dt_seconds_exact'])
            self.assertEqual(F(step['end_seconds_exact']), elapsed)
        self.assertEqual(elapsed, F(forcing.duration_seconds))
        self.assertEqual(F(out['numerics']['elapsed_seconds_exact']), elapsed)
        self.assertEqual(out['numerics']['controls'], self.solver.asdict(ctl))

    def test_floor_recovery_maximum_failure_retains_both_gate_contexts(self):
        col, old, _, fill, forcing, boundary = self.jump_case()
        ctl = replace(self.controls, initial_dt_s=8*fill, min_dt_s=8*fill, max_dt_s=16*fill,
                      flux_integral_atol_m=1e-18)
        out = self.adapter.advance(col, self.solver.initial_state(col, tuple(float(x) for x in old)), forcing, boundary, ctl,
            water_density_kg_m3=1000., gravity_m_s2=9.81)
        self.assertEqual(out['status'], 'NUMERICAL_FAILURE'); self.assertIsNone(out['state'])
        self.assertIn('ascending recovery exhausted after floor failure', out['reason'])
        self.assertEqual(out['attempts'], 2)
        self.assertEqual(out['diagnostics']['floor_trial']['dt_seconds'], 8*fill)
        self.assertEqual(out['diagnostics']['last_trial']['dt_seconds'], 16*fill)
        self.assertEqual(out['diagnostics']['last_trial']['worst_component'], 'unresolved_flow_reversal')

    def test_floor_recovery_cannot_escape_shared_work_budget(self):
        col, old, _, fill, forcing, boundary = self.jump_case()
        ctl = replace(self.controls, initial_dt_s=8*fill, min_dt_s=8*fill, max_dt_s=16*fill, max_steps=1)
        out = self.adapter.advance(col, self.solver.initial_state(col, tuple(float(x) for x in old)), forcing, boundary, ctl,
            water_density_kg_m3=1000., gravity_m_s2=9.81)
        self.assertEqual(out['status'], 'NUMERICAL_FAILURE'); self.assertIsNone(out['state'])
        self.assertEqual(out['reason'], 'adaptive work budget exceeded')
        self.assertEqual(out['diagnostics']['last_trial']['dt_seconds'], 8*fill)


class ActualSeasonalResolutionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases = {snow: actual_inputs(snow) for snow in ('DIAGNOSTIC_DDF4_SIGMA4', 'HIGH_DDF5_SIGMA6', 'LOW_DDF3_SIGMA2')}
        cls.results = {snow: seasonal(case) for snow, case in cls.cases.items()}
        ACTUAL_NUMERICAL_RECEIPTS.update({snow+'/upper': result for snow, result in cls.results.items()})

    def assert_complete(self, snow):
        out = self.results[snow]
        self.assertEqual(out['status'], 'MODELLED_SEASONAL_HYDRAULICS', out.get('reason'))
        self.assertEqual(out['completed_months'], 12)
        self.assertEqual(out['final_state']['elapsed_seconds'], 31536030.)
        self.assertEqual(out['inputs']['numerical_binding']['implementation'], n.IMPLEMENTATION)
        for event in out['events']:
            self.assertEqual(event['solver_result']['numerical_implementation'], n.IMPLEMENTATION)
            self.assertEqual(event['solver_result']['numerical_binding'], out['inputs']['numerical_binding'])
        ledger = out['annual']['ledger_m']
        self.assertLess(abs(F(ledger['water_residual_m'])), F(1, 10**8))
        self.assertEqual(F(ledger['bottom_downward_m']), 0); self.assertEqual(F(ledger['bottom_upward_m']), 0)
        self.assertEqual(out['inputs']['controls'], self.cases[snow][1]['hydraulic_controls'])

    def test_diagnostic_upper_actual_full_year(self): self.assert_complete('DIAGNOSTIC_DDF4_SIGMA4')
    def test_high_upper_actual_full_year(self): self.assert_complete('HIGH_DDF5_SIGMA6')
    def test_low_upper_actual_full_year(self): self.assert_complete('LOW_DDF3_SIGMA2')

    def test_actual_upper_half_daily_step_refinement(self):
        case = self.cases['DIAGNOSTIC_DDF4_SIGMA4']; coarse = self.results['DIAGNOSTIC_DDF4_SIGMA4']
        fine = seasonal(case, maximum_step=43200.)
        ACTUAL_NUMERICAL_RECEIPTS['DIAGNOSTIC_DDF4_SIGMA4/upper/half_daily'] = fine
        self.assertEqual(fine['status'], 'MODELLED_SEASONAL_HYDRAULICS')
        ctl = case[1]['hydraulic_controls']
        for a, b in zip(coarse['final_state']['head_m'], fine['final_state']['head_m']):
            self.assertLessEqual(abs(a-b), ctl['head_atol_m']+ctl['relative_tolerance']*max(abs(a), abs(b)))
        for key in ('surface_runoff_m', 'actual_et_m', 'root_zone_gross_downward_m', 'root_zone_upward_capillary_m'):
            a = float(F(coarse['annual']['ledger_m'][key])); b = float(F(fine['annual']['ledger_m'][key]))
            self.assertLessEqual(abs(a-b), ctl['flux_integral_atol_m']+ctl['relative_tolerance']*max(abs(a), abs(b)))

    def test_actual_lower_predecessor_parity_with_same_physics_and_controls(self):
        case = actual_inputs('DIAGNOSTIC_DDF4_SIGMA4', 'lower')
        original = seasonal(case, original=True); corrected = seasonal(case)
        ACTUAL_NUMERICAL_RECEIPTS.update(lower_original=original, lower_corrected=corrected)
        self.assertEqual(original['status'], 'MODELLED_SEASONAL_HYDRAULICS')
        self.assertEqual(corrected['status'], 'MODELLED_SEASONAL_HYDRAULICS')
        self.assertNotEqual(original['inputs_sha256'], corrected['inputs_sha256'])
        self.assertEqual(original['inputs']['numerical_binding']['implementation'], 'R6_RETAINED_NUMERICAL_EXECUTION')
        ctl = case[1]['hydraulic_controls']
        for a, b in zip(original['final_state']['head_m'], corrected['final_state']['head_m']):
            self.assertLessEqual(abs(a-b), ctl['head_atol_m']+ctl['relative_tolerance']*max(abs(a), abs(b)))
        for key in ('surface_runoff_m', 'actual_et_m', 'root_zone_gross_downward_m', 'root_zone_upward_capillary_m'):
            a = float(F(original['annual']['ledger_m'][key])); b = float(F(corrected['annual']['ledger_m'][key]))
            self.assertLessEqual(abs(a-b), ctl['flux_integral_atol_m']+ctl['relative_tolerance']*max(abs(a), abs(b)))

    def test_original_numerical_checkpoint_cannot_be_relabelled_as_adapter(self):
        case = actual_inputs('DIAGNOSTIC_DDF4_SIGMA4', 'lower')
        original = seasonal(case, original=True, stop_after=1)
        with self.assertRaises(ValueError): seasonal(case, resume=original['checkpoint'])

    def test_corrected_upper_actual_depletion_file_restart(self):
        case = self.cases['DIAGNOSTIC_DDF4_SIGMA4']
        self.assertEqual(case[6][2].month_id, case[6][3].month_id)
        stopped = seasonal(case, stop_after=3)
        raw = json.dumps(stopped['checkpoint'], sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
        with TemporaryDirectory(prefix='r10-upper-numerical-checkpoint-') as folder:
            path = Path(folder)/'checkpoint.json'; path.write_bytes(raw)
            readback = path.read_bytes(); self.assertEqual(readback, raw)
            resumed = seasonal(case, resume=json.loads(readback))
        ACTUAL_NUMERICAL_RECEIPTS.update(upper_depletion_stop=stopped, upper_depletion_resume=resumed)
        self.assertEqual(resumed, self.results['DIAGNOSTIC_DDF4_SIGMA4'])


if __name__ == '__main__': unittest.main()
