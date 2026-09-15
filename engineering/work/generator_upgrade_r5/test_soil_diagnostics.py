"""Independent diagnostics/parity checks; no changed physics or relaxed gates."""
from dataclasses import asdict, replace
import ast
import inspect
import json
import math
import unittest
from unittest.mock import patch

import numpy as np

from . import soil_water as w
from work.generator_upgrade_r3 import soil_water as predecessor

E = 'EXPLICIT SYNTHETIC NUMERICAL DIAGNOSTIC; NO DIADEM SOIL CALIBRATION'
S = 'SYNTHETIC TEST'


def fixture(module=w, *, thin=False, duration=1., min_dt=1e-4, max_steps=1000):
    layers = tuple(module.HydraulicLayer(str(i), dz, .03125, .25, 2., 2., .5,
                                        2e-6, E, S)
                   for i, dz in enumerate((1e-8 if thin else .1, .5)))
    column = module.Column('two-cell-diagnostic', layers, 2, E, S)
    state = module.initial_state(column, (-.25, -.25))
    forcing = module.Forcing(duration, 2e-9, 0., None, E, S)
    boundary = module.Boundary('fixed_head', .1, E, S)
    controls = module.Controls(1., min_dt, 1., 1e-8, 1e-8, 1e-10, 1e-6,
                               1e-12, 1e-10, -1e5, 10., max_steps, 300)
    return column, state, forcing, boundary, controls


def advance(args, module=w):
    return module.advance(*args, water_density_kg_m3=1000., gravity_m_s2=9.81)


def records():
    def row():
        return {'head': np.array([-.25, -.25]), 'theta': np.array([.2, .2]),
                'q_m': np.zeros(3), 'et_m': np.zeros(2)}
    return row(), row(), row()


def scalar_components(full, first, second, controls):
    """Separately expressed scalar oracle for all four retained error tests."""
    pairs = {
        'head_m': (second['head'], full['head'], controls.head_atol_m),
        'theta_m3_m3': (second['theta'], full['theta'], controls.theta_atol),
        'face_flux_integral_m': ([float(a)+float(b) for a, b in zip(first['q_m'], second['q_m'])],
                                 full['q_m'], controls.flux_integral_atol_m),
        'root_uptake_integral_m': ([float(a)+float(b) for a, b in zip(first['et_m'], second['et_m'])],
                                  full['et_m'], controls.flux_integral_atol_m)}
    return {name: [abs(float(a)-float(b))/(atol+controls.relative_tolerance*max(abs(float(a)), abs(float(b))))
                   for a, b in zip(fine, coarse)] for name, (fine, coarse, atol) in pairs.items()}


class SoilDiagnosticsTests(unittest.TestCase):
    def assert_null_failure(self, result):
        self.assertEqual(result['status'], 'NUMERICAL_FAILURE', result)
        for field in ('state', 'layers', 'ledger'):
            self.assertIsNone(result[field])
        self.assertFalse(result['physical_acceptance'])
        json.dumps(result, allow_nan=False)

    def test_preserved_nonlinear_and_physical_algorithms_are_ast_identical(self):
        for name in ('_step', '_fluxes', '_arrays', '_stress', 'hydraulic_properties', 'head_from_theta'):
            with self.subTest(function=name):
                a = ast.dump(ast.parse(inspect.getsource(getattr(w, name))), include_attributes=False)
                b = ast.dump(ast.parse(inspect.getsource(getattr(predecessor, name))), include_attributes=False)
                self.assertEqual(a, b)

    def test_factored_temporal_errors_equal_independent_scalar_old_equations(self):
        column, _, _, _, controls = fixture()
        rng = np.random.default_rng(90405)
        for _ in range(40):
            full, first, second = records()
            for row in (full, first, second):
                for name, scale in (('head', 1.), ('theta', .1), ('q_m', 1e-5), ('et_m', 1e-7)):
                    row[name] = rng.normal(size=len(row[name]))*scale
            expected = scalar_components(full, first, second, controls)
            error, details, worst = w._temporal_errors(column, full, first, second, controls)
            for name, ratios in expected.items():
                self.assertEqual(details[name]['error_ratio'], max(ratios))
                self.assertEqual(details[name]['support_index'], ratios.index(max(ratios)))
            self.assertEqual(error, max(max(v) for v in expected.values()))
            self.assertEqual(worst, max(expected, key=lambda k: max(expected[k])))

    def test_head_worst_support_reports_exact_thin_layer(self):
        column, _, _, _, controls = fixture(thin=True)
        full, first, second = records(); second['head'][0] -= .001
        error, details, worst = w._temporal_errors(column, full, first, second, controls)
        self.assertGreater(error, 1); self.assertEqual(worst, 'head_m')
        row = details[worst]
        self.assertEqual((row['support_kind'], row['support_index'], row['layer_id']), ('cell', 0, '0'))
        self.assertEqual(row['thickness_m'], 1e-8)
        self.assertEqual(row['absolute_difference'], abs(float(second['head'][0])-float(full['head'][0])))

    def test_theta_worst_support_and_ties_are_deterministic(self):
        column, _, _, _, controls = fixture()
        full, first, second = records(); second['theta'] += .001
        _, details, worst = w._temporal_errors(column, full, first, second, controls)
        self.assertEqual(worst, 'theta_m3_m3')
        self.assertEqual(details[worst]['support_index'], 0)
        self.assertEqual(details[worst]['layer_id'], column.layers[0].layer_id)

    def test_face_flux_reports_bottom_face_not_invented_layer(self):
        column, _, _, _, controls = fixture()
        full, first, second = records(); first['q_m'][-1] = -1e-5; second['q_m'][-1] = 3e-5
        _, details, worst = w._temporal_errors(column, full, first, second, controls)
        self.assertEqual(worst, 'face_flux_integral_m')
        self.assertEqual(details[worst]['support_kind'], 'face')
        self.assertEqual(details[worst]['support_index'], len(column.layers))
        self.assertNotIn('layer_id', details[worst]); self.assertNotIn('thickness_m', details[worst])

    def test_uptake_error_uses_sum_of_both_half_steps(self):
        column, _, _, _, controls = fixture()
        full, first, second = records(); first['et_m'][1] = 2e-6; second['et_m'][1] = 3e-6
        _, details, worst = w._temporal_errors(column, full, first, second, controls)
        self.assertEqual(worst, 'root_uptake_integral_m')
        self.assertEqual(details[worst]['layer_id'], '1')
        self.assertEqual(details[worst]['absolute_difference'], 2e-6+3e-6)

    def test_nonfinite_error_cannot_be_small_or_non_json_diagnostic(self):
        column, _, _, _, controls = fixture()
        for value in (float('nan'), float('inf'), 1e308):
            full, first, second = records(); second['head'][0] = value; full['head'][0] = -1e308
            with np.errstate(all='ignore'):
                error, details, worst = w._temporal_errors(column, full, first, second, controls)
            self.assertEqual(error, math.inf); self.assertEqual(worst, 'head_m')
            self.assertIsNone(details[worst]['error_ratio'])
            json.dumps(details, allow_nan=False)

    def test_each_nonlinear_failure_is_identified_without_partial_state(self):
        args = fixture(min_dt=1.)
        full, first, second = records()
        for outputs, flags, calls in (
            ([None, first, second], (False, True, True), 3),
            ([full, None], (True, False, False), 2),
            ([full, first, None], (True, True, False), 3)):
            with self.subTest(flags=flags), patch.object(w, '_step', side_effect=outputs) as step:
                result = advance(args)
            self.assert_null_failure(result); self.assertEqual(step.call_count, calls)
            trial = result['diagnostics']['last_trial']
            self.assertEqual(tuple(trial['nonlinear_solutions_accepted'].values()), flags)
            self.assertEqual(trial['gate'], 'nonlinear_solution')
            self.assertIsNone(trial['error_components']); self.assertIsNone(trial['worst_component'])
            self.assertEqual(result['diagnostics']['rejected_trials'], {'nonlinear_solution': 1, 'temporal_accuracy': 0})

    def test_actual_thin_cell_is_temporal_failure_not_nonlinear_failure(self):
        args = fixture(thin=True); before = tuple(asdict(v) for v in args)
        result = advance(args); self.assert_null_failure(result)
        self.assertEqual(tuple(asdict(v) for v in args), before)
        trial = result['diagnostics']['last_trial']
        self.assertEqual(trial['gate'], 'temporal_accuracy')
        self.assertTrue(all(trial['nonlinear_solutions_accepted'].values()))
        self.assertEqual(trial['worst_component'], 'head_m')
        self.assertEqual(trial['error_components']['head_m']['layer_id'], '0')
        self.assertEqual(trial['minimum_layer_thickness_m'], 1e-8)
        self.assertEqual(trial['minimum_permitted_dt_seconds'], args[-1].min_dt_s)
        self.assertGreaterEqual(trial['dt_seconds'], args[-1].min_dt_s)
        self.assertEqual(result['diagnostics']['rejected_trials']['nonlinear_solution'], 0)
        self.assertGreater(result['diagnostics']['rejected_trials']['temporal_accuracy'], 0)

    def test_successful_actual_solution_is_numerically_identical_to_r3(self):
        new = advance(fixture(duration=1.)); old = advance(fixture(predecessor, duration=1.), predecessor)
        self.assertEqual(new['status'], 'MODELLED', new); self.assertEqual(old['status'], 'MODELLED', old)
        self.assertEqual(asdict(new['state']), asdict(old['state']))
        for key in ('layers', 'ledger', 'forcing', 'lower_boundary', 'fluid', 'column_sha256'):
            self.assertEqual(new[key], old[key], key)
        for key, value in old['numerics'].items():
            self.assertEqual(new['numerics'][key], value, key)
        self.assertEqual(new['numerics']['controls'], asdict(fixture()[-1]))

    def test_work_budget_exhaustion_never_exposes_last_accepted_state(self):
        args = list(fixture(duration=3., max_steps=1))
        args[-1] = replace(args[-1], relative_tolerance=.01, head_atol_m=1e-4)
        result = advance(tuple(args)); self.assert_null_failure(result)
        self.assertEqual(result['reason'], 'adaptive work budget exceeded')
        self.assertEqual(result['attempts'], 2)
        self.assertIsNotNone(result['diagnostics']['last_trial'])

    def test_unknown_inputs_are_not_misdiagnosed_as_numerical_failure(self):
        args = list(fixture()); args[2] = replace(args[2], surface_input_m_s=None)
        result = advance(tuple(args))
        self.assertEqual(result['status'], 'UNKNOWN')
        self.assertNotIn('diagnostics', result)
        self.assertIsNone(result['state']); self.assertIsNone(result['ledger'])

    def test_r5_checkpoint_roundtrip_does_not_silently_accept_r3_schema(self):
        column, state, *_ = fixture()
        self.assertEqual(w.state_from_json(w.state_to_json(state), column), state)
        raw = json.loads(w.state_to_json(state)); raw['schema'] = 'diadem.richards-state.r3'
        with self.assertRaises(ValueError): w.state_from_json(json.dumps(raw), column)

    def test_zero_interval_does_not_fabricate_pressure_diagnostics(self):
        args = list(fixture()); args[2] = replace(args[2], duration_seconds=0.)
        result = advance(tuple(args))
        self.assertEqual(result['status'], 'NO_ADVANCE'); self.assertEqual(result['state'], args[1])
        self.assertIsNone(result['layers']); self.assertIsNone(result['ledger'])
        self.assertNotIn('diagnostics', result)


if __name__ == '__main__':
    unittest.main()
