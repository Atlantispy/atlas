"""Analytical seasonal state/conservation tests using the actual R6 solver."""
from copy import deepcopy
from dataclasses import asdict, replace
from fractions import Fraction as F
import json
import hashlib
import math
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from work.generator_upgrade_r9 import binding as parent_binding
from . import hydraulics as h

_PARENT = parent_binding.load()
w = _PARENT.parent.parent.parent.solver
SOURCE = h.digest({'parent': _PARENT.source_sha256, 'hydraulics_sha256': hashlib.sha256(Path(h.__file__).read_bytes()).hexdigest()})

E = 'SYNTHETIC TEST: twelve short laboratory forcing intervals, not a Diadem calendar or biology'
S = 'SYNTHETIC TEST'


def controls(**kw):
    values = dict(initial_dt_s=.25, min_dt_s=1e-6, max_dt_s=1., theta_atol=1e-7,
        head_atol_m=1e-6, flux_integral_atol_m=1e-10, relative_tolerance=1e-6,
        nonlinear_mass_atol_m=1e-12, total_mass_atol_m=1e-9, min_head_m=-1e5,
        max_head_m=10., max_steps=1000, max_nfev=300, integration_method='SDIRK2')
    values.update(kw)
    return w.Controls(**values)


def calendar(duration=F(1)):
    return h.Calendar('LAB_TWELVE_INTERVALS_NOT_AN_EARTH_YEAR', (duration,)*12, F(1), E)


def column(n=1, k=0., root=None):
    layers = tuple(w.HydraulicLayer('layer-'+str(i), 1., .05, .4, 2., 2., .5, k, E, S) for i in range(n))
    return w.Column('fixed-formed-test-column', layers, n if root is None else root, E, S)


def uptake(n=1):
    return w.Uptake((1.,)+(0.,)*(n-1), -100., -2., -.5, 0., E, S)


def events(duration=F(1), rain=F(0), demand=F(0), root=None, boundary=None):
    b = w.Boundary('no_flow', None, E, S) if boundary is None else boundary
    return tuple(h.Event('interval-'+str(m), m, duration, rain, demand, root, b,
        'explicit-lab-vegetation-case', 'UNFROZEN_CONDITIONAL', E, 10., E, S) for m in range(1, 13))


def run(col=None, ev=None, cal=None, initial=None, ctl=None, numerical_solver=None, **kw):
    col = column() if col is None else col
    ev = events() if ev is None else ev
    cal = calendar() if cal is None else cal
    initial = w.initial_state(col, (-1.,)*len(col.layers)) if initial is None else initial
    args = dict(root_boundary_index=col.root_boundary_index, water_density_kg_m3=1000.,
        gravity_m_s2=9.81, duration_atol_s=1e-9, budget_atol_m=1e-8, evidence=E, source_status=S,
        source_binding_sha256=SOURCE, scenario_id='LAB/explicit-root-case/one-column')
    args.update(kw)
    return h.run_year(w if numerical_solver is None else numerical_solver, col, initial, cal, ev, controls() if ctl is None else ctl, **args)


ACTUAL_YEAR_RECEIPTS = {}


def actual_formed_fixture():
    """Pinned actual R8 forcing/R7 thin layers, with explicit new root/bottom law."""
    folder = Path(__file__).resolve().parents[2]/'outputs/generator-upgrade-r8/biomes-reference-01/n-worker-reference'
    pins = {'full-result.json': '19a0975d09d1571e68ed510421b085675753b64ddfba316c8e8e2d68662cb000',
            'recipe.json': '5c2e34ae5c25872bda1f5afb8e160ebf7f3da8390d940a4f4fa1f5f66b38fd32'}
    loaded = {}
    for filename, expected in pins.items():
        raw = (folder/filename).read_bytes()
        if hashlib.sha256(raw).hexdigest() != expected: raise ValueError('actual retained fixture changed')
        loaded[filename] = json.loads(raw)
    data = loaded['full-result.json']; recipe = loaded['recipe.json']; member = 'LOW_DDF3_SIGMA2'; cell = 'lower'
    if data['source_sha256'] != _PARENT.parent.source_sha256: raise ValueError('actual fixture/R8 source identity mismatch')
    formed = data['soil_result']['state']['members'][member][cell]; probe = formed['formed_soil_water']
    col = w.Column(probe['column']['column_id'], tuple(w.HydraulicLayer(**x) for x in probe['column']['layers']),
        probe['column']['root_boundary_index'], probe['column']['evidence'], probe['column']['source_status'])
    state = w.State(tuple(probe['result']['state']['head_m']), probe['result']['state']['elapsed_seconds'], probe['result']['state']['column_sha256'])
    face = 8; pft = recipe['pfts']['temperate']; rooting = pft['rooting']
    if (len(col.layers) != 9 or col.layers[-1].layer_id != 'lower-substrate'
            or any(g['phase'] not in rooting['allowed_phases'] for g in formed['geometry'][:face])
            or sum(x.thickness_m for x in col.layers[:face]) > rooting['maximum_root_depth_m']):
        raise ValueError('actual nonrock root-face support changed')
    evd = 'SYNTHETIC TEST: actual formed lower column/R8 representative year; R7 30s endpoint explicitly aligned to Jan1; concentrated mineral-layer root uptake, unfrozen/no-flow diagnostic, not observed cover'
    root = w.Uptake(tuple(1. if layer.layer_id == 'lower-mineral' else 0. for layer in col.layers), -100., -2., -.1, 0., evd, S)
    calrow = data['seasonal']['calendar']
    cal = h.Calendar(calrow['calendar_id'], tuple(F(v)*F(calrow['day_seconds']) for v in calrow['month_days']), F(calrow['day_seconds']), calrow['evidence'])
    ev = tuple(h.Event(x['event_id'], x['month_id'], F(x['duration_seconds']), F(x['liquid_input_m_s']),
        F(x['potential_evaporation_m_s']*pft['reference_transpiration_fraction']*recipe['family_demand_multipliers']['R8_B']) if x['temperature_c'] > pft['active_above_temperature_c'] else F(),
        root, w.Boundary('no_flow', None, evd, S), 'R8_B/temperate-concentrated-mineral-uptake',
        'UNFROZEN_CONDITIONAL', evd, x['temperature_c'], evd, S)
        for x in data['seasonal']['members'][member]['cells'][cell]['events'])
    ctl = w.Controls(**{**probe['inputs']['controls'], 'max_dt_s': 86400.})
    from .richards_numerics import Adapter
    return dict(col=col, initial=state, ev=ev, cal=cal, ctl=ctl, root_boundary_index=face, numerical_solver=Adapter(w),
        duration_atol_s=1e-6, budget_atol_m=1e-6, evidence=evd,
        source_binding_sha256=h.digest({'kernel': SOURCE, 'actual_parents': pins}),
        scenario_id='LOW_DDF3_SIGMA2/R8_B-temperate/lower')


class SeasonalPhysicalTests(unittest.TestCase):
    def test_sealed_no_flow_no_demand_retains_every_month_state(self):
        out = run()
        self.assertEqual(out['status'], 'MODELLED_SEASONAL_HYDRAULICS')
        self.assertEqual(out['completed_events'], 12); self.assertEqual(out['completed_months'], 12)
        for row in out['months'].values():
            self.assertAlmostEqual(row['end_layers'][0]['head_m'], -1., places=14)
            self.assertEqual(F(row['ledger_m']['surface_input_m']), 0)
            self.assertLess(abs(F(row['ledger_m']['water_residual_m'])), F(1, 10**12))
        self.assertEqual(out['final_state']['elapsed_seconds'], 12.)

    def test_impermeable_column_exact_rain_runoff_not_rain_equals_infiltration(self):
        out = run(ev=events(rain=F(1, 1000000)))
        ledger = out['annual']['ledger_m']
        self.assertAlmostEqual(float(F(ledger['surface_runoff_m'])), 12e-6, places=18)
        self.assertEqual(F(ledger['infiltration_m']), 0)
        self.assertAlmostEqual(out['final_state']['head_m'][0], -1., places=14)

    def test_actual_root_uptake_matches_independent_closed_storage_oracle(self):
        out = run(ev=events(demand=F(1, 1000000), root=uptake()))
        initial_theta = .05+.35/math.sqrt(5.)
        expected_final_theta = initial_theta-12e-6
        self.assertAlmostEqual(out['annual']['end_layers'][0]['theta_m3_m3'], expected_final_theta, places=12)
        self.assertAlmostEqual(float(F(out['annual']['ledger_m']['actual_et_m'])), 12e-6, places=17)
        self.assertLess(out['final_state']['head_m'][0], -1.)
        self.assertGreater(out['months']['1']['end_layers'][0]['theta_m3_m3'], out['months']['12']['end_layers'][0]['theta_m3_m3'])

    def test_steady_uniform_gravity_flow_independent_conductivity_oracle(self):
        col = column(2, k=1e-5)
        se = 1/math.sqrt(5.)
        conductivity = 1e-5*math.sqrt(se)*(1-math.sqrt(1-se*se))**2
        out = run(col, ev=events(rain=F(conductivity), boundary=w.Boundary('free_drainage', None, E, S)))
        self.assertEqual(out['status'], 'MODELLED_SEASONAL_HYDRAULICS')
        self.assertAlmostEqual(float(F(out['annual']['ledger_m']['bottom_downward_m'])), conductivity*12, places=14)
        self.assertEqual(F(out['annual']['ledger_m']['bottom_upward_m']), 0)
        for head in out['final_state']['head_m']: self.assertAlmostEqual(head, -1., places=10)

    def test_gross_reversed_lower_boundary_exchange_not_cancelled(self):
        col = column(k=1e-5)
        ev = tuple(replace(e, boundary=w.Boundary('fixed_head', 0. if e.month_id <= 6 else -2., E, S)) for e in events())
        out = run(col, ev=ev)
        self.assertEqual(out['status'], 'MODELLED_SEASONAL_HYDRAULICS')
        ledger = out['annual']['ledger_m']
        self.assertGreater(F(ledger['bottom_downward_m']), 0); self.assertGreater(F(ledger['bottom_upward_m']), 0)
        self.assertGreater(F(out['months']['1']['root_zone_upward_capillary_mm']), 0)
        self.assertGreater(F(out['months']['12']['root_zone_gross_downward_mm']), 0)
        self.assertEqual(F(out['annual']['root_zone_upward_capillary_mm']), 1000*F(ledger['bottom_upward_m']))

    def test_actual_root_face_rebind_keeps_geometry_and_head_values(self):
        col = column(3); initial = w.initial_state(col, (-1., -1.5, -2.), elapsed_seconds=30.)
        out = run(col, initial=initial, root_boundary_index=1)
        self.assertEqual(out['initial_state']['head_m'], list(initial.head_m))
        self.assertEqual(out['column']['layers'], h.plain(col.layers))
        self.assertNotEqual(out['column_sha256'], out['original_column_sha256'])
        self.assertEqual(F(out['root_boundary_depth_m']), 1)
        self.assertEqual(out['final_state']['elapsed_seconds'], 42.)
        self.assertEqual(col.root_boundary_index, 3)

    def test_split_event_replay_preserves_state_and_integrated_transfers(self):
        ev = events(demand=F(1, 1000000), root=uptake())
        split = tuple(replace(e, event_id=e.event_id+'-'+str(i), duration_seconds=F(1, 2)) for e in ev for i in range(2))
        whole = run(ev=ev); divided = run(ev=split)
        self.assertAlmostEqual(whole['final_state']['head_m'][0], divided['final_state']['head_m'][0], places=11)
        self.assertAlmostEqual(float(F(whole['annual']['ledger_m']['actual_et_m'])), float(F(divided['annual']['ledger_m']['actual_et_m'])), places=16)
        self.assertEqual(divided['completed_events'], 24)

    def test_manual_restart_halfway_matches_wrapper_continuation(self):
        col = column(); initial = w.initial_state(col, (-1.,)); root = uptake()
        ev = events(demand=F(1, 1000000), root=root); ctl = controls()
        out = run(col, ev=ev, initial=initial, ctl=ctl)
        current = initial
        for index, event in enumerate(ev):
            if index == 6:
                current = w.state_from_json(w.state_to_json(current), col)
            result = w.advance(col, current, w.Forcing(1., 0., 1e-6, root, E, S), event.boundary, ctl,
                water_density_kg_m3=1000., gravity_m_s2=9.81)
            self.assertEqual(result['status'], 'MODELLED'); current = result['state']
        self.assertEqual(out['final_state'], h.plain(current))

    def test_month_ledgers_add_to_year_without_reusing_storage(self):
        out = run(ev=events(rain=F(1, 10000), demand=F(1, 1000000), root=uptake()))
        for key in h.LEDGER:
            self.assertEqual(F(out['annual']['ledger_m'][key]), sum((F(m['ledger_m'][key]) for m in out['months'].values()), F()))
        self.assertEqual(out['annual']['ledger_m']['initial_storage_m'], out['months']['1']['ledger_m']['initial_storage_m'])
        self.assertEqual(out['annual']['ledger_m']['final_storage_m'], out['months']['12']['ledger_m']['final_storage_m'])
        self.assertNotIn('et_m', out['annual']['end_layers'][0])
        self.assertNotIn('water_residual_m', out['annual']['end_layers'][0])
        self.assertEqual(F(out['annual']['ledger_m']['layer_actual_et_m'][0]), F(out['annual']['ledger_m']['actual_et_m']))

    def test_soil_pressure_retains_negative_sign_and_cell_centre_support(self):
        out = run(); layer = out['months']['1']['end_layers'][0]
        self.assertAlmostEqual(layer['signed_pore_pressure_pa'], -9810., places=8)
        self.assertEqual(layer['positive_pore_pressure_pa'], 0.)
        self.assertEqual(layer['centre_depth_m'], .5)
        self.assertIn('not time means', out['months']['1']['state_support'])

    def test_cold_air_requires_named_unfrozen_hypothesis_not_inferred_temperature(self):
        out = run(ev=tuple(replace(e, air_temperature_c=-20.) for e in events()))
        self.assertEqual(out['status'], 'MODELLED_SEASONAL_HYDRAULICS')
        self.assertEqual(len(out['cold_air_event_ids']), 12)
        self.assertTrue(all(e['soil_thermal_regime'] == 'UNFROZEN_CONDITIONAL' for e in out['events']))
        self.assertIn('soil heat and freeze/thaw', out['unmodelled'])

    def test_unknown_air_can_remain_diagnostic_when_soil_regime_independent(self):
        out = run(ev=tuple(replace(e, air_temperature_c=None) for e in events()))
        self.assertEqual(out['status'], 'MODELLED_SEASONAL_HYDRAULICS')
        self.assertEqual(len(out['unknown_air_temperature_event_ids']), 12)


class SeasonalUnknownAndFailureTests(unittest.TestCase):
    def test_unknown_freeze_state_halts_causal_suffix_without_reset(self):
        ev = list(events()); ev[4] = replace(ev[4], soil_thermal_regime='UNKNOWN')
        out = run(ev=tuple(ev))
        self.assertEqual(out['status'], 'UNKNOWN'); self.assertEqual(out['completed_months'], 4)
        self.assertIsNone(out['annual']); self.assertIsNone(out['final_state'])
        self.assertEqual(out['events'][5]['status'], 'NOT_ADVANCED_PRIOR_GAP')
        self.assertIsNone(out['months']['5']['ledger_m']); self.assertIsNone(out['months']['12']['end_layers'])

    def test_missing_liquid_or_demand_never_zero_filled(self):
        for field in ('liquid_input_m_s', 'potential_root_demand_m_s'):
            out = run(ev=(replace(events()[0], **{field: None}),)+events()[1:])
            self.assertEqual(out['status'], 'UNKNOWN'); self.assertEqual(out['completed_events'], 0)
            self.assertIsNone(out['annual'])

    def test_unknown_boundary_or_hydraulic_source_never_assumed_closed(self):
        unknown_boundary = w.Boundary('fixed_head', None, E, 'UNKNOWN')
        out = run(ev=events(boundary=unknown_boundary))
        self.assertEqual(out['status'], 'UNKNOWN')
        col = column(); col = replace(col, layers=(replace(col.layers[0], source_status='UNKNOWN'),))
        out = run(col)
        self.assertEqual(out['status'], 'UNKNOWN'); self.assertEqual(out['completed_events'], 0)

    def test_unknown_global_source_stops_even_numerically_zero_forcing(self):
        out = run(source_status='UNKNOWN')
        self.assertEqual(out['status'], 'UNKNOWN'); self.assertEqual(out['completed_events'], 0)

    def test_actual_solver_budget_failure_not_relaxed_or_partial_state_promoted(self):
        ctl = controls(max_steps=1, initial_dt_s=.1, max_dt_s=.1)
        out = run(ctl=ctl)
        self.assertEqual(out['status'], 'NUMERICAL_FAILURE'); self.assertEqual(out['completed_events'], 0)
        self.assertIsNone(out['final_state']); self.assertIsNone(out['annual'])
        self.assertEqual(out['inputs']['controls']['max_steps'], 1)

    def test_duration_conversion_too_tight_fails_closed(self):
        out = run(ev=events(duration=F(1, 3)), cal=calendar(F(1, 3)), duration_atol_s=F(1, 10**20))
        self.assertEqual(out['status'], 'NUMERICAL_FAILURE')
        self.assertIn('duration conversion', out['reason']); self.assertEqual(out['completed_events'], 0)

    def test_represented_duration_error_reported_when_within_supplied_bound(self):
        out = run(ev=events(duration=F(1, 3)), cal=calendar(F(1, 3)))
        self.assertEqual(out['status'], 'MODELLED_SEASONAL_HYDRAULICS')
        self.assertEqual(F(out['events'][0]['duration_conversion_residual_s']), F(float(F(1, 3)))-F(1, 3))
        self.assertEqual(F(out['annual']['duration_seconds']), 4)

    def test_independent_balance_rejects_solver_false_pass(self):
        original = w.advance
        def wrong(*args, **kw):
            result = deepcopy(original(*args, **kw)); result['ledger']['bottom_upward_m'] += .001
            return result
        with patch.object(w, 'advance', side_effect=wrong): out = run()
        self.assertEqual(out['status'], 'NUMERICAL_FAILURE')
        self.assertIn('water balance', out['reason']); self.assertIsNone(out['final_state'])

    def test_solver_wrong_schema_is_not_accepted(self):
        original = w.advance
        def wrong(*args, **kw):
            result = original(*args, **kw); result['schema'] = 'old-unbound-water'
            return result
        with patch.object(w, 'advance', side_effect=wrong), self.assertRaisesRegex(ValueError, 'schema'):
            run()

    def test_unknown_part_month_does_not_present_partial_month_total(self):
        ev = list(events()); first = ev.pop(0)
        ev[:0] = [replace(first, event_id='first-half', duration_seconds=F(1, 2)),
            replace(first, event_id='unknown-half', duration_seconds=F(1, 2), liquid_input_m_s=None)]
        out = run(ev=tuple(ev))
        self.assertEqual(out['completed_events'], 1); self.assertEqual(out['completed_months'], 0)
        self.assertEqual(out['months']['1']['completed_event_ids'], ['first-half'])
        self.assertIsNone(out['months']['1']['ledger_m'])


class SeasonalSchemaTests(unittest.TestCase):
    def test_missing_repeated_or_unordered_months_reject_before_solver(self):
        for ev in (events()[:-1], events()[1:]+events()[:1], (events()[0],)+events()):
            with patch.object(w, 'advance') as mocked, self.assertRaises(ValueError): run(ev=ev)
            mocked.assert_not_called()

    def test_month_duration_mismatch_rejects(self):
        with self.assertRaisesRegex(ValueError, 'exact duration'): run(cal=calendar(F(2)))

    def test_stale_initial_column_cannot_reuse_pressure(self):
        first = column(); other = replace(first, layers=(replace(first.layers[0], thickness_m=2.),))
        with self.assertRaisesRegex(ValueError, 'exact physical column'):
            run(other, initial=w.initial_state(first, (-1.,)))

    def test_root_boundary_and_uptake_support_guards(self):
        for face in (0, 2, True):
            with self.subTest(face=face), self.assertRaises(ValueError): run(root_boundary_index=face)
        col = column(2)
        bad = w.Uptake((0., 1.), -100., -2., -.5, 0., E, S)
        with self.assertRaisesRegex(ValueError, 'root weights'):
            run(col, ev=events(demand=F(1, 1000000), root=bad), root_boundary_index=1)

    def test_positive_demand_requires_actual_root_law_and_boundary_types(self):
        with self.assertRaisesRegex(ValueError, 'positive root demand'): run(ev=events(demand=F(1, 1000000)))
        with self.assertRaisesRegex(ValueError, 'actual bound solver types'):
            run(ev=tuple(replace(e, boundary=asdict(e.boundary)) for e in events()))

    def test_boolean_nonfinite_negative_and_unknown_regime_guards(self):
        for value in (True, float('nan'), float('inf'), -1):
            with self.subTest(value=str(value)), self.assertRaises(ValueError): events(rain=value)
        for regime in ('FROZEN_SOLVED', None, True):
            with self.assertRaises(ValueError): replace(events()[0], soil_thermal_regime=regime)
        with self.assertRaises(ValueError): replace(calendar(), month_durations_seconds=(F(1),)*11)
        with self.assertRaises(ValueError): replace(events()[0], month_id=True)
        with self.assertRaises(ValueError): run(budget_atol_m=0)

    def test_inputs_are_unchanged_and_output_json_safe(self):
        col = column(); initial = w.initial_state(col, (-1.,)); ev = events(); ctl = controls()
        before = deepcopy((asdict(col), asdict(initial), [asdict(e) for e in ev], asdict(ctl)))
        out = run(col, ev=ev, initial=initial, ctl=ctl)
        self.assertEqual(before, (asdict(col), asdict(initial), [asdict(e) for e in ev], asdict(ctl)))
        json.dumps(out, allow_nan=False)

    def test_input_identity_changes_for_biological_or_thermal_hypothesis(self):
        one = run(); two = run(ev=tuple(replace(e, vegetation_hypothesis_id='different-explicit-cover') for e in events()))
        self.assertNotEqual(one['inputs_sha256'], two['inputs_sha256'])
        self.assertEqual(one['final_state'], two['final_state'])


class SeasonalCheckpointTests(unittest.TestCase):
    def test_zero_stop_is_explicit_no_advance_and_retains_initial_checkpoint(self):
        with patch.object(w, 'advance') as mocked: out = run(stop_after=0)
        mocked.assert_not_called()
        self.assertEqual(out['status'], 'NO_ADVANCE'); self.assertIsNone(out['annual'])
        self.assertEqual(out['checkpoint']['state']['completed_events'], 0)
        self.assertEqual(out['checkpoint']['state']['continuing_state'], out['initial_state'])

    def test_month_boundary_serialised_restart_equals_uninterrupted_exactly(self):
        ev = events(demand=F(1, 1000000), root=uptake())
        full = run(ev=ev); part = run(ev=ev, stop_after=6)
        saved = json.loads(json.dumps(part['checkpoint'], allow_nan=False))
        self.assertEqual(part['status'], 'PARTIAL_SEASONAL_HYDRAULICS')
        self.assertEqual(part['checkpoint']['state']['completed_months'], 6)
        self.assertEqual(run(ev=ev, resume=saved), full)

    def test_intra_month_depletion_style_split_restart_is_exact(self):
        ev = list(events()); first = ev.pop(0)
        ev[:0] = [replace(first, event_id='snow-before-depletion', duration_seconds=F(1, 3), liquid_input_m_s=F(3, 1000000)),
            replace(first, event_id='snow-after-depletion', duration_seconds=F(2, 3))]
        full = run(ev=tuple(ev)); part = run(ev=tuple(ev), stop_after=1)
        self.assertEqual(part['checkpoint']['state']['completed_months'], 0)
        self.assertEqual(part['checkpoint']['state']['next_event_id'], 'snow-after-depletion')
        self.assertIsNone(part['months']['1']['ledger_m'])
        self.assertEqual(run(ev=tuple(ev), resume=part['checkpoint']), full)

    def test_restart_at_end_is_identical_and_does_not_duplicate_flow(self):
        out = run(ev=events(rain=F(1, 1000000)))
        replay = run(ev=events(rain=F(1, 1000000)), resume=out['checkpoint'])
        self.assertEqual(replay, out)

    def test_source_scenario_and_changed_forcing_reject(self):
        saved = run(stop_after=2)['checkpoint']
        for kw in ({'source_binding_sha256': 'f'*64}, {'scenario_id': 'other/scenario'},
                   {'ev': events(rain=F(1, 1000000))}, {'root_boundary_index': 1, 'evidence': E+' changed'}):
            with self.subTest(keys=list(kw)), self.assertRaises(ValueError): run(resume=saved, **kw)

    def test_rehashed_forged_head_clock_or_ledger_fails_actual_replay(self):
        saved = run(stop_after=2)['checkpoint']
        for kind in ('head', 'clock', 'ledger', 'events'):
            altered = deepcopy(saved)
            if kind == 'head': altered['state']['continuing_state']['head_m'][0] = -.5
            if kind == 'clock': altered['state']['elapsed_seconds_in_year'] = '4'
            if kind == 'ledger': altered['state']['accumulated_ledger_m']['surface_runoff_m'] = '1'
            if kind == 'events': altered['state']['accepted_event_rows'][0]['event_id'] = 'another-event'
            altered['state_sha256'] = h.digest(altered['state'])
            with self.subTest(kind=kind), self.assertRaisesRegex(ValueError, 'actual source-bound event replay'):
                run(resume=altered)

    def test_cursor_skip_duplicate_extra_fields_and_backwards_stop_reject(self):
        saved = run(stop_after=2)['checkpoint']
        for cursor in (True, -1, 3, 13):
            altered = deepcopy(saved); altered['state']['completed_events'] = cursor
            altered['state_sha256'] = h.digest(altered['state'])
            with self.assertRaises(ValueError): run(resume=altered)
        altered = deepcopy(saved); altered['state']['extra'] = 1
        with self.assertRaises(ValueError): run(resume=altered)
        with self.assertRaises(ValueError): run(resume=saved, stop_after=1)
        for stop in (True, -1, 13):
            with self.assertRaises(ValueError): run(stop_after=stop)

    def test_failure_preserves_whole_event_not_unavailable_internal_state(self):
        ev = list(events()); first = ev.pop(0)
        ev[:0] = [replace(first, event_id='complete-short', duration_seconds=F(1, 20)),
            replace(first, event_id='failing-long', duration_seconds=F(19, 20))]
        out = run(ev=tuple(ev), ctl=controls(max_steps=1, initial_dt_s=.1, max_dt_s=.1))
        self.assertEqual(out['status'], 'NUMERICAL_FAILURE'); self.assertEqual(out['completed_events'], 1)
        progress = out['failure_progress']; saved = out['checkpoint']['state']
        self.assertEqual(progress['last_completed_event_cursor'], 1)
        self.assertFalse(progress['in_event_resumable']); self.assertFalse(progress['internal_state_available'])
        self.assertIsNone(progress['internal_accepted_step_count'])
        self.assertEqual(F(saved['elapsed_seconds_in_year']), F(1, 20))
        self.assertEqual(saved['continuing_state']['elapsed_seconds'], .05)
        self.assertEqual(saved['next_event_id'], 'failing-long'); self.assertIsNone(out['annual'])
        again = run(ev=tuple(ev), ctl=controls(max_steps=1, initial_dt_s=.1, max_dt_s=.1), resume=out['checkpoint'])
        self.assertEqual(again, out)


class ActualFormedYearTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = actual_formed_fixture()
        cls.full = run(**cls.fixture)
        ACTUAL_YEAR_RECEIPTS['full'] = cls.full

    def readback_checkpoint(self, checkpoint):
        raw = json.dumps(checkpoint, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')
        with TemporaryDirectory(prefix='r10-hydraulic-checkpoint-') as folder:
            path = Path(folder)/'checkpoint.json'
            path.write_bytes(raw)
            restored = path.read_bytes()
            self.assertEqual(restored, raw)
            return json.loads(restored)

    def test_actual_formed_thin_column_full_year_conservation_and_support(self):
        out = self.full
        self.assertEqual(out['status'], 'MODELLED_SEASONAL_HYDRAULICS')
        self.assertEqual(out['completed_months'], 12); self.assertEqual(out['completed_events'], 13)
        self.assertEqual(out['final_state']['elapsed_seconds'], 31536030.)
        self.assertEqual(out['column']['root_boundary_index'], 8)
        self.assertLess(min(layer['thickness_m'] for layer in out['column']['layers']), 3e-8)
        ledger = out['annual']['ledger_m']
        self.assertLess(abs(float(F(ledger['water_residual_m']))), 1e-8)
        self.assertGreater(F(ledger['root_zone_gross_downward_m']), 0)
        self.assertGreater(F(ledger['root_zone_upward_capillary_m']), 0)
        self.assertEqual(F(ledger['bottom_net_downward_m']), 0)
        self.assertLess(F(ledger['storage_change_m']), 0)
        self.assertEqual(F(ledger['layer_actual_et_m'][-1]), 0)

    def test_actual_month_boundary_restart_matches_full_state_and_ledgers_exactly(self):
        part = run(**self.fixture, stop_after=1)
        saved = self.readback_checkpoint(part['checkpoint'])
        continued = run(**self.fixture, resume=saved)
        ACTUAL_YEAR_RECEIPTS.update(month_boundary_stop=part, month_boundary_resume=continued)
        self.assertEqual(continued, self.full)

    def test_actual_swe_depletion_boundary_restart_matches_full_exactly(self):
        self.assertEqual(self.fixture['ev'][1].month_id, self.fixture['ev'][2].month_id)
        self.assertIn('part-0', self.fixture['ev'][1].event_id)
        self.assertIn('part-1', self.fixture['ev'][2].event_id)
        part = run(**self.fixture, stop_after=2)
        saved = self.readback_checkpoint(part['checkpoint'])
        continued = run(**self.fixture, resume=saved)
        ACTUAL_YEAR_RECEIPTS.update(swe_depletion_stop=part, swe_depletion_resume=continued)
        self.assertEqual(part['completed_months'], 1)
        self.assertEqual(continued, self.full)

    def test_actual_daily_vs_half_daily_maximum_step_refinement(self):
        fixture = dict(self.fixture); fixture['ctl'] = replace(fixture['ctl'], max_dt_s=43200.)
        fine = run(**fixture); ACTUAL_YEAR_RECEIPTS['half_daily_maximum_step'] = fine
        self.assertEqual(fine['status'], 'MODELLED_SEASONAL_HYDRAULICS')
        for left, right in zip(self.full['final_state']['head_m'], fine['final_state']['head_m']):
            tolerance = self.fixture['ctl'].head_atol_m+self.fixture['ctl'].relative_tolerance*max(abs(left), abs(right))
            self.assertLessEqual(abs(left-right), tolerance)
        for key in ('actual_et_m', 'surface_runoff_m', 'root_zone_gross_downward_m', 'root_zone_upward_capillary_m'):
            left = float(F(self.full['annual']['ledger_m'][key])); right = float(F(fine['annual']['ledger_m'][key]))
            tolerance = self.fixture['ctl'].flux_integral_atol_m+self.fixture['ctl'].relative_tolerance*max(abs(left), abs(right))
            self.assertLessEqual(abs(left-right), tolerance)


if __name__ == '__main__': unittest.main()
