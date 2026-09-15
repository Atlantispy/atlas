"""Bounded real-input adapter checks; no seasonal solver/model execution."""
from copy import deepcopy
from fractions import Fraction
import json
import unittest
from unittest.mock import patch

from work.generator_runtime_r12 import provenance as shared
from work.generator_upgrade_r13 import inputs, soil, year
from work.test_r13_soil import fixture


RESULT_SHA = 'f191389d93c411f81e7003e5edf96551b53dc945e359dc705d83d00c64a0930e'
EVIDENCE = 'SYNTHETIC TEST: explicit thermal hypotheses on exact retained initial hydraulics; not Diadem calibration.'


def arguments(unit):
    model, forcing, controls = fixture()
    water = unit['hydrology']
    layers = water['column']['layers']
    constants = deepcopy(model['constants'])
    constants['gravity_m_s2'] = 9.81  # Explicit retained R10 gravity, not the different standalone fixture value.
    thermal = {row['layer_id']: {key: deepcopy(model['layers'][0][key]) for key in inputs.THERMAL_FIELDS}
               for row in layers}
    by_event = {}
    for old in water['inputs']['events']:
        row = {key: deepcopy(forcing[key]) for key in inputs.THERMAL_EVENT_FIELDS}
        if old['boundary']['kind'] == 'fixed_head':
            row['bottom_water_temperature_k'] = 278.0
        by_event[old['event_id']] = row
    return dict(thermal_by_layer=thermal, constants=constants,
                initial_temperature_k={row['layer_id']: 278.0 for row in layers},
                thermal_forcing_by_event=by_event, controls=controls,
                context={'world_id': 'SYNTHETIC_RETAINED_REFERENCE', 'snapshot_id': 'EXPLICIT_FIXED_YEAR',
                         'calendar_id': water['inputs']['calendar']['calendar_id'],
                         'spatial_frame_id': 'EXPLICIT_NATIVE_COLUMN_DEPTH_SUPPORT',
                         'vertical_reference': 'Supplied native column depth; not an adopted geodetic datum',
                         'scenario_id': water['scenario_id']}, evidence=EVIDENCE, source_status='SYNTHETIC TEST')


class RetainedInputTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bundle = shared.load_science()
        path = shared.TASK / 'outputs/generator-upgrade-r10/seasonal-reference-01/n-worker-reference/full-result.json'
        saved = json.loads(shared.checked(path, RESULT_SHA))
        if (saved['schema'] != 'diadem.seasonal-world-result.r10'
                or saved['source_sha256'] != cls.bundle.parent.source_sha256
                or saved['status'] != 'COMPLETE_BOUNDED_SEASONAL_EXECUTION'):
            raise ValueError('complete exact retained R10 fixture required')
        codec = cls.bundle.parent.graph.load('work.generator_upgrade_r10.payloads')
        cls.unit = codec.unpack(saved['state']['results']['DIAGNOSTIC_DDF4_SIGMA4/TEMPERATE_R8_A/lower'])

    def adapt(self, unit=None, kwargs=None):
        unit = self.unit if unit is None else unit
        return inputs.from_r10_unit(self.bundle, unit, **(arguments(unit) if kwargs is None else kwargs))

    def test_actual_geometry_thin_layers_initial_heads_and_age_preserved(self):
        with patch.object(soil, 'advance', side_effect=AssertionError('adapter must never advance a model')):
            recipe = self.adapt()
        water = self.unit['hydrology']
        self.assertEqual(len(recipe['model']['layers']), 9)
        self.assertLess(min(row['thickness_m'] for row in recipe['model']['layers']), 3e-8)
        self.assertEqual([row['layer_id'] for row in recipe['model']['layers']],
                         [row['layer_id'] for row in water['column']['layers']])
        for old, new in zip(water['column']['layers'], recipe['model']['layers']):
            for key in ('thickness_m', 'theta_r', 'theta_s', 'mualem_l'):
                self.assertEqual(new[key], old[key])
            self.assertEqual(new['vg_alpha_per_m'], old['alpha_per_m'])
            self.assertEqual(new['vg_n'], old['n'])
            self.assertEqual(new['saturated_conductivity_m_s'], old['ksat_m_s'])
        self.assertEqual(recipe['initial']['head_m'], water['inputs']['initial_state']['head_m'])
        self.assertEqual(recipe['initial']['elapsed_seconds'], 30.0)
        self.assertNotEqual(recipe['initial']['head_m'], water['final_state']['head_m'])
        self.assertEqual(recipe['joins']['root_boundary_index'], 8)
        self.assertEqual(recipe['joins']['original_column_sha256'], water['original_column_sha256'])
        self.assertEqual(recipe['joins']['active_column_sha256'], water['column_sha256'])
        self.assertFalse(recipe['joins']['old_r10_computed_moisture_or_runoff_reused'])
        year.validate(recipe)

    def test_original_exact_calendar_rates_and_feddes_law_preserved(self):
        recipe = self.adapt()
        original = self.unit['hydrology']['inputs']
        self.assertEqual(recipe['calendar']['month_durations_seconds'], original['calendar']['month_durations_seconds'])
        elapsed = Fraction()
        for old, new in zip(original['events'], recipe['events']):
            self.assertEqual(Fraction(new['start_seconds_in_year']), elapsed)
            self.assertEqual(new['duration_seconds'], old['duration_seconds'])
            self.assertEqual(Fraction(new['forcing']['duration_s']), Fraction(old['duration_seconds']))
            self.assertEqual(Fraction(new['forcing']['surface_water_flux_m_s']), Fraction(old['liquid_input_m_s']))
            self.assertEqual(Fraction(new['forcing']['potential_root_demand_m_s']), Fraction(old['potential_root_demand_m_s']))
            self.assertEqual(new['forcing']['uptake'], old['uptake'])
            self.assertEqual(new['forcing']['bottom_water']['kind'], 'noflow')
            self.assertNotIn('temperature_k', new['forcing']['bottom_water'])
            elapsed += Fraction(old['duration_seconds'])
        self.assertEqual(elapsed, 31536000)

    def test_explicit_temperatures_are_not_inferred_from_cold_air(self):
        recipe = self.adapt()
        self.assertLess(self.unit['hydrology']['inputs']['events'][0]['air_temperature_c'], 0)
        self.assertEqual(recipe['initial']['temperature_k'], [278.] * 9)
        self.assertEqual(recipe['events'][0]['forcing']['surface_water_temperature_k'], 274.)
        self.assertEqual(recipe['events'][0]['forcing']['top_heat']['kind'], 'flux')

    def test_fixed_head_preserved_and_requires_explicit_inflow_temperature(self):
        # The retained fixture has only impermeable bottoms. This constructed
        # branch fixture tests schema translation, not a retained head run.
        head_unit = deepcopy(self.unit)
        water = head_unit['hydrology']
        for old_event in water['inputs']['events']:
            old_event['boundary'] = dict(old_event['boundary'], kind='fixed_head', head_m=-0.7)
        water['inputs_sha256'] = shared.sha(water['inputs'])
        water['checkpoint']['inputs_sha256'] = water['inputs_sha256']
        recipe = self.adapt(head_unit)
        old = head_unit['hydrology']['inputs']['events'][0]['boundary']
        self.assertEqual(old['kind'], 'fixed_head')
        self.assertEqual(recipe['events'][0]['forcing']['bottom_water']['head_m'], old['head_m'])
        self.assertEqual(recipe['events'][0]['forcing']['bottom_water']['temperature_k'], 278.)
        kwargs = arguments(head_unit)
        kwargs['thermal_forcing_by_event'][next(iter(kwargs['thermal_forcing_by_event']))].pop('bottom_water_temperature_k')
        with self.assertRaisesRegex(ValueError, 'thermal forcing'):
            self.adapt(head_unit, kwargs)

    def test_no_unused_bottom_temperature_accepted_on_closed_boundary(self):
        kwargs = arguments(self.unit)
        kwargs['thermal_forcing_by_event'][next(iter(kwargs['thermal_forcing_by_event']))]['bottom_water_temperature_k'] = 278.
        with self.assertRaisesRegex(ValueError, 'thermal forcing'):
            self.adapt(kwargs=kwargs)

    def test_input_checksum_mismatch_rejected(self):
        unit = deepcopy(self.unit)
        unit['hydrology']['inputs']['water_density_kg_m3'] += 1
        with self.assertRaisesRegex(ValueError, 'checksum'):
            self.adapt(unit)

    def test_native_column_or_state_drift_rejected(self):
        for key in ('column', 'initial_state'):
            unit = deepcopy(self.unit)
            if key == 'column':
                unit['hydrology'][key]['layers'][1]['thickness_m'] *= 2
            else:
                unit['hydrology'][key]['head_m'][1] -= 1
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'native geometry'):
                self.adapt(unit)

    def test_original_state_geometry_digest_rejected(self):
        unit = deepcopy(self.unit)
        unit['hydrology']['inputs']['initial_state']['column_sha256'] = 'a' * 64
        unit['hydrology']['inputs_sha256'] = shared.sha(unit['hydrology']['inputs'])
        with self.assertRaisesRegex(ValueError, 'native initial state'):
            self.adapt(unit)

    def test_source_and_scenario_bindings_rejected(self):
        for field in ('source_binding_sha256', 'scenario_id'):
            unit = deepcopy(self.unit)
            unit['hydrology'][field] = 'a' * 64
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.adapt(unit)

    def test_partial_parent_and_missing_schema_fields_rejected(self):
        for field in ('status', 'completed_months', 'completed_events', 'partial_results_only'):
            unit = deepcopy(self.unit)
            unit['hydrology'][field] = {'status': 'UNKNOWN', 'completed_months': 11,
                                        'completed_events': 1, 'partial_results_only': True}[field]
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.adapt(unit)
        unit = deepcopy(self.unit)
        unit['hydrology'].pop('annual')
        with self.assertRaisesRegex(ValueError, 'exact complete R10'):
            self.adapt(unit)

    def test_event_clock_gap_rejected(self):
        unit = deepcopy(self.unit)
        unit['hydrology']['events'][1]['start_seconds_in_year'] = '1'
        with self.assertRaisesRegex(ValueError, 'chronological event clock'):
            self.adapt(unit)

    def test_calendar_mutation_rejected(self):
        unit = deepcopy(self.unit)
        unit['hydrology']['inputs']['calendar']['month_durations_seconds'][0] = '1'
        unit['hydrology']['inputs_sha256'] = shared.sha(unit['hydrology']['inputs'])
        with self.assertRaisesRegex(ValueError, 'exact calendar month'):
            self.adapt(unit)

    def test_complete_layer_temperature_and_event_maps_required(self):
        for name in ('thermal_by_layer', 'initial_temperature_k', 'thermal_forcing_by_event'):
            for extra in (False, True):
                kwargs = arguments(self.unit)
                if extra:
                    kwargs[name]['absent-owner-input'] = deepcopy(next(iter(kwargs[name].values())))
                else:
                    kwargs[name].pop(next(iter(kwargs[name])))
                with self.subTest(name=name, extra=extra), self.assertRaisesRegex(ValueError, 'inventory'):
                    self.adapt(kwargs=kwargs)

    def test_density_and_gravity_must_equal_original_inputs(self):
        for name in ('water_density_kg_m3', 'gravity_m_s2'):
            kwargs = arguments(self.unit)
            kwargs['constants'][name] += 1
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'retained hydraulic input'):
                self.adapt(kwargs=kwargs)

    def test_context_calendar_or_scenario_mismatch_rejected(self):
        for name in ('calendar_id', 'scenario_id'):
            kwargs = arguments(self.unit)
            kwargs['context'][name] = 'different'
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'caller context'):
                self.adapt(kwargs=kwargs)

    def test_no_canon_or_synthetic_source_promotion(self):
        for status in ('CANON', 'UNKNOWN', 'WORKING NON-CANON'):
            kwargs = arguments(self.unit)
            kwargs['source_status'] = status
            with self.subTest(status=status), self.assertRaises(ValueError):
                self.adapt(kwargs=kwargs)

    def test_missing_unknown_or_invalid_thermal_inputs_rejected(self):
        for value in (None, float('nan'), False, 0.):
            kwargs = arguments(self.unit)
            kwargs['initial_temperature_k'][next(iter(kwargs['initial_temperature_k']))] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.adapt(kwargs=kwargs)
        kwargs = arguments(self.unit)
        kwargs['thermal_by_layer'][next(iter(kwargs['thermal_by_layer']))]['source_status'] = 'UNKNOWN'
        with self.assertRaises(ValueError):
            self.adapt(kwargs=kwargs)

    def test_thermal_map_cannot_override_native_thickness(self):
        kwargs = arguments(self.unit)
        kwargs['thermal_by_layer'][next(iter(kwargs['thermal_by_layer']))]['thickness_m'] = 1.
        with self.assertRaisesRegex(ValueError, 'thermal law'):
            self.adapt(kwargs=kwargs)

    def test_nonbinary_rate_is_rejected_instead_of_rounded(self):
        unit = deepcopy(self.unit)
        water = unit['hydrology']
        water['inputs']['events'][0]['liquid_input_m_s'] = '1/3'
        water['inputs_sha256'] = shared.sha(water['inputs'])
        water['checkpoint']['inputs_sha256'] = water['inputs_sha256']
        with self.assertRaisesRegex(ValueError, 'not exactly representable'):
            self.adapt(unit)

    def test_recipe_does_not_depend_on_old_runoff_or_carbon_values(self):
        original = self.adapt()
        unit = deepcopy(self.unit)
        unit['downstream'] = {'not_reused_old_runoff': 123456789.}
        unit['carbon'] = {'not_reused_old_carbon': 987654321.}
        changed = self.adapt(unit)
        for key in ('model', 'initial', 'calendar', 'events', 'controls'):
            self.assertEqual(changed[key], original[key])
        self.assertNotEqual(changed['joins']['retained_r10_unit_sha256'], original['joins']['retained_r10_unit_sha256'])

    def test_caller_objects_and_retained_inputs_remain_unchanged(self):
        kwargs = arguments(self.unit)
        before_kwargs, before_unit = deepcopy(kwargs), deepcopy(self.unit)
        recipe = self.adapt(kwargs=kwargs)
        recipe['events'][0]['forcing']['uptake']['weights'][0] = 999
        recipe['model']['layers'][0]['thickness_m'] = 10
        self.assertEqual(kwargs, before_kwargs)
        self.assertEqual(self.unit, before_unit)

    def test_painter_karra_cold_initialisation_conserves_each_native_water_stock(self):
        kwargs = arguments(self.unit)
        kwargs.update(freezing_model='PAINTER_KARRA_2014_APPARENT_PORE', clapeyron_beta=1.)
        kwargs['initial_temperature_k'] = {key: 270. for key in kwargs['initial_temperature_k']}
        with patch.object(soil, 'advance', side_effect=AssertionError('initial coordinate conversion is not an advance')):
            recipe = self.adapt(kwargs=kwargs)
        original = self.unit['hydrology']['inputs']['initial_state']['head_m']
        self.assertNotEqual(recipe['initial']['head_m'], original)
        self.assertEqual(recipe['joins']['original_native_head_sha256'], shared.sha(original))
        self.assertTrue(recipe['joins']['initial_water_preserved'])
        self.assertIn('PHYSICAL_LIQUID_PRESSURE_HEAD', recipe['joins']['initial_head_semantics'])
        state = soil.initial_state(recipe['model'], recipe['initial']['head_m'], recipe['initial']['temperature_k'])
        self.assertTrue(all(ice > 0 for ice in state['ice_water']))
        for old, new, delta, bound in zip(recipe['joins']['original_native_water_fraction'], state['total_water'],
                recipe['joins']['initial_water_conversion_residual_fraction'], recipe['joins']['initial_water_roundoff_limit_fraction']):
            self.assertLessEqual(abs(new-old), bound)
            self.assertEqual(new-old, delta)
        self.assertEqual(len(state['head_m']), 9)
        # At full saturation retain the independently supplied pressure; do not
        # invent zero pressure by inverting a stock that cannot determine it.
        sw = self.bundle.parent.parent.parent.parent.parent.solver
        column = inputs.native_column(sw, self.unit['hydrology']['column'])
        saturated = sw.initial_state(column, [.125] * 9, elapsed_seconds=30.)
        heads, joined = inputs.pk_initial_water(sw, column, saturated, recipe['model'], [270.] * 9)
        self.assertEqual(heads, [.125] * 9)
        self.assertTrue(joined['initial_water_preserved'])

    def test_explicit_freezing_model_contract_and_unchanged_warm_native_heads(self):
        defaults = self.adapt()
        self.assertNotIn('freezing_model', defaults['model'])
        self.assertNotIn('clapeyron_beta', defaults['model'])
        kwargs = arguments(self.unit)
        kwargs.update(freezing_model='PAINTER_KARRA_2014_APPARENT_PORE', clapeyron_beta=1.)
        recipe = self.adapt(kwargs=kwargs)
        self.assertEqual(recipe['model']['freezing_model'], kwargs['freezing_model'])
        self.assertEqual(recipe['model']['clapeyron_beta'], 1.)
        self.assertEqual(recipe['initial']['head_m'], defaults['initial']['head_m'])
        for options in ({'clapeyron_beta': 1.}, {'freezing_model': kwargs['freezing_model']},
                        {'freezing_model': kwargs['freezing_model'], 'clapeyron_beta': False},
                        {'freezing_model': kwargs['freezing_model'], 'clapeyron_beta': 0.},
                        {'freezing_model': 'UNSUPPORTED', 'clapeyron_beta': 1.}):
            invalid = arguments(self.unit)
            invalid.update(options)
            with self.subTest(options=options), self.assertRaises(ValueError):
                self.adapt(kwargs=invalid)


if __name__ == '__main__':
    unittest.main()
