"""Independent seasonal joins; one actual formed R7 fixture per process.

No saved reference is repinned and no historical test suite is rerun. Analytical
expectations below use the stated retention, PM and snow accounting equations,
not another call to the production function under test.
"""
from copy import deepcopy
from dataclasses import dataclass
from fractions import Fraction as F
import json
import math
import unittest

from . import binding

E = 'SYNTHETIC TEST: independent seasonal accounting and supplied calendar'
DAYS = (31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)


class SeasonalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.b = binding.load()
        cls.s = cls.b.graph.load('work.generator_upgrade_r8.seasonal')
        cls.recipe = cls.b.reference.recipe(cls.b)
        cls.config = cls.recipe['seasonal']
        cls.soil = cls.b.parent.run(cls.recipe['soil_recipe'])
        cls.product = cls.s.build(cls.b, cls.soil, cls.config)
        cls.member = 'HIGH_DDF5_SIGMA6'
        cls.cell_id = 'upper'
        cls.cell = cls.soil['state']['members'][cls.member][cls.cell_id]
        cls.hm = cls.b.parent.parent.pipeline.hm
        cls.scenario = cls.hm.snow_scenarios()[0]

    def capacity(self, *, cell=None, **changes):
        spec = deepcopy(self.recipe['pfts']['grass']['rooting'])
        spec.update(changes)
        return self.s.rooted_capacity(self.b, self.cell if cell is None else cell,
                                      spec, support_id='independent-formed-support')

    def snow_months(self, day=86400):
        # January accumulates snow; February depletes it part-way through the
        # month. Warmer remaining months contain neither new rain nor snow.
        return [{'month_id': m, 'duration_seconds': str(F(days)*day),
                 'temperature_c': -20. if m == 1 else 15.,
                 'precipitation_m_s': str(F(1, 10_000_000) if m == 1 else F()),
                 'snowfall_m_s': str(F(1, 10_000_000) if m == 1 else F()),
                 'potential_evaporation_m_s': 1e-8, 'evidence': E}
                for m, days in enumerate(DAYS, 1)]

    def snow(self, monthly=None, **changes):
        config = deepcopy(self.config)
        config.update(changes)
        return self.s.snow_cycle(self.hm, self.scenario,
            self.snow_months() if monthly is None else monthly, config,
            'independent-snow-cell', '0'*64)

    def test_all_three_coequal_members_and_six_actual_cells(self):
        expected = {s.scenario_id for s in self.hm.snow_scenarios()}
        self.assertEqual(set(self.product['members']), expected)
        self.assertEqual(len(expected), 3)
        for member in self.product['members'].values():
            self.assertEqual(set(member['cells']), {'upper', 'lower'})
            self.assertEqual({v['status'] for v in member['cells'].values()},
                             {'MODELLED_PERIODIC_SNOW'})

    def test_actual_source_and_configuration_binding(self):
        self.assertEqual(self.soil['source_sha256'], self.b.parent.source_sha256)
        self.assertEqual(self.product['soil_result_sha256'], self.s.digest(self.soil))
        self.assertEqual(self.product['configuration_sha256'], self.s.digest(self.config))
        expected = self.s.digest({'soil_result_sha256': self.s.digest(self.soil),
                                  'configuration': self.config})
        self.assertEqual(self.product['binding_sha256'], expected)

    def test_current_formed_height_not_parent_height(self):
        for sid, member in self.product['members'].items():
            for terrain in member['formed_terrain']:
                cell = self.soil['state']['members'][sid][terrain['cell_id']]
                expected = F(cell['formation_state']['base_elevation_m']) + sum(
                    (F(row['thickness_m']) for row in cell['geometry']), F())
                self.assertEqual(terrain['elevation_m'], float(expected))
                for month in member['atmosphere']:
                    for regime in month['regimes']:
                        # Actual generated thermal lapse uses this exact current
                        # surface, not the old R6 240-second temperature record.
                        air = regime['products'][terrain['cell_id']]['air']
                        cfg = self.config['months'][month['month_id']-1]['regimes']
                        supplied = next(r['atmosphere'] for r in cfg
                                        if r['regime_id'] == regime['regime_id'])
                        lapse = supplied['lapse_k_m']
                        t = supplied['reference_temperature_c'] - lapse*(float(expected)-supplied['reference_elevation_m'])
                        self.assertAlmostEqual(air['temperature_c'], t, places=12)

    def test_horizontal_area_and_completed_source_guards(self):
        bad = deepcopy(self.config)
        bad['transect'][0]['length_m'] += 1
        with self.assertRaisesRegex(ValueError, 'horizontal area'):
            self.s.build(self.b, self.soil, bad)
        for field, value in (('source_sha256', '0'*64), ('completed_exposures', 0)):
            altered = deepcopy(self.soil)
            (altered if field == 'source_sha256' else altered['state'])[field] = value
            with self.assertRaisesRegex(ValueError, 'completed source-bound'):
                self.s.build(self.b, altered, self.config)

    def test_available_capacity_independent_van_genuchten_integral(self):
        cap = self.capacity()
        remaining = .5
        expected = 0.
        laws = self.cell['formed_soil_water']['column']['layers']
        for geom, law in zip(self.cell['geometry'], laws):
            if remaining <= 0 or geom['phase'] == 'bedrock':
                break
            dz = min(remaining, float(F(geom['thickness_m'])))
            m = 1-1/law['n']
            def theta(head):
                return law['theta_r'] + (law['theta_s']-law['theta_r']) * (
                    1+(law['alpha_per_m']*abs(head))**law['n'])**(-m)
            expected += dz*(theta(-.1)-theta(-100.))
            remaining -= dz
        self.assertAlmostEqual(cap['capacity_m'], expected, places=14)
        self.assertEqual(cap['rooted_depth_exact_m'], '1/2')
        self.assertEqual(cap['geometry_sha256'], self.s.digest(self.cell['geometry']))
        self.assertEqual(cap['hydraulic_material_sha256'], self.s.digest(self.cell['formed_soil_water']['column']))

    def test_partial_first_layer_has_exact_physical_support(self):
        depth = float(F(self.cell['geometry'][0]['thickness_m'])/3)
        cap = self.capacity(maximum_root_depth_m=depth)
        self.assertEqual(len(cap['layers']), 1)
        self.assertEqual(F(cap['layers'][0]['rooted_thickness_m']), F(depth))
        row = cap['layers'][0]
        self.assertEqual(F(cap['capacity_exact_m']),
                         (F(row['theta_upper'])-F(row['theta_lower']))*F(depth))

    def test_excluded_surface_layer_prevents_root_tunnelling(self):
        self.assertEqual(self.cell['geometry'][0]['phase'], 'organic_mantle')
        cap = self.capacity(allowed_phases=['mobile_sediment', 'immobile_regolith'])
        self.assertEqual(cap['capacity_m'], 0.)
        self.assertEqual(cap['rooted_depth_m'], 0.)
        self.assertEqual(cap['layers'], [])

    def test_roots_stop_at_actual_bedrock_not_requested_depth(self):
        cap = self.capacity(maximum_root_depth_m=10.)
        expected = F()
        for row in self.cell['geometry']:
            if row['phase'] == 'bedrock':
                break
            expected += F(row['thickness_m'])
        self.assertEqual(F(cap['rooted_depth_exact_m']), expected)
        self.assertLess(cap['rooted_depth_m'], 10.)
        self.assertNotIn(self.cell['geometry'][-1]['layer_id'], [v['layer_id'] for v in cap['layers']])

    def test_missing_new_geometry_water_is_unknown_not_zero(self):
        cell = deepcopy(self.cell)
        cell['formed_soil_water']['status'] = 'UNKNOWN'
        cap = self.capacity(cell=cell)
        self.assertEqual(cap['status'], 'UNKNOWN')
        self.assertIsNone(cap['capacity_m'])
        self.assertIsNone(cap['rooted_depth_m'])

    def test_stale_geometry_and_layer_identity_reject(self):
        cell = deepcopy(self.cell)
        cell['formed_soil_water']['geometry_sha256'] = '0'*64
        with self.assertRaisesRegex(ValueError, 'stale'):
            self.capacity(cell=cell)
        cell = deepcopy(self.cell)
        cell['formed_soil_water']['column']['layers'].reverse()
        with self.assertRaisesRegex(ValueError, 'identities'):
            self.capacity(cell=cell)

    def test_hydraulic_dimension_and_endpoint_guards(self):
        for key in ('thickness_m', 'theta_s'):
            cell = deepcopy(self.cell)
            cell['formed_soil_water']['column']['layers'][0][key] *= .9
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'dimensions'):
                self.capacity(cell=cell)
        for upper, lower in ((0, -100), (-100, -.1), (-1, -1)):
            with self.subTest(heads=(upper, lower)), self.assertRaises(ValueError):
                self.capacity(upper_head_m=upper, lower_head_m=lower)
        with self.assertRaises(ValueError):
            self.capacity(allowed_phases=['bedrock'])

    def test_monthly_pm_is_weighted_actual_regime_demand(self):
        member = self.product['members'][self.member]
        for month, row in zip(member['atmosphere'], member['cells'][self.cell_id]['months']):
            for key in ('potential_evaporation_m_s', 'potential_condensation_m_s'):
                expected = sum((F(r['weight'])*F(r['products'][self.cell_id]['demand'][key])
                                for r in month['regimes']), F())
                self.assertEqual(row[key], float(expected))
            demands = [r['products'][self.cell_id]['demand']['potential_evaporation_m_s'] for r in month['regimes']]
            self.assertNotEqual(demands[0], demands[1])

    def test_actual_pm_independent_resistance_equation(self):
        regime = self.product['members'][self.member]['atmosphere'][6]['regimes'][0]
        air = regime['products'][self.cell_id]['air']
        got = regime['products'][self.cell_id]['demand']
        constants = self.config['demand_constants']
        surface = self.config['months'][6]['regimes'][0]['surfaces'][self.cell_id]
        cp = constants['cp_air_j_kg_k']; latent = constants['latent_heat_j_kg']
        eps = constants['molecular_mass_ratio']; q = air['specific_humidity_kg_kg']
        vapour = air['pressure_pa']*q/(eps+(1-eps)*q)
        gamma = cp*air['pressure_pa']/(eps*latent)
        ra = surface['aerodynamic_resistance_s_m']; rs = surface['surface_resistance_s_m']
        delta = air['saturation_slope_pa_k']
        expected = (delta*(surface['net_radiation_w_m2']-surface['ground_heat_flux_w_m2'])
                    + air['moist_air_density_kg_m3']*cp*(air['saturation_vapour_pressure_pa']-vapour)/ra
                   )/(delta+gamma*(1+rs/ra))/(latent*constants['water_density_kg_m3'])
        self.assertAlmostEqual(got['signed_potential_water_flux_m_s'], expected, places=20)
        self.assertIsNone(got['actual_et_m_s'])
        self.assertIsNone(got['actual_condensation_m_s'])

    def test_phase_partition_precedes_monthly_weighting(self):
        member = self.product['members'][self.member]
        for month, row in zip(member['atmosphere'], member['cells'][self.cell_id]['months']):
            snowfall = sum((F(r['weight'])*F(r['products'][self.cell_id]['phase']['snowfall_m_s'])
                            for r in month['regimes']), F())
            precipitation = sum((F(r['weight'])*F(r['products'][self.cell_id]['air']['precipitation_m_s'])
                                 for r in month['regimes']), F())
            self.assertEqual(F(row['snowfall_m_s']), snowfall)
            self.assertEqual(F(row['precipitation_m_s']), precipitation)
            self.assertLessEqual(snowfall, precipitation)

    def test_actual_twelve_month_thermal_seasonality(self):
        months = self.product['members'][self.member]['cells'][self.cell_id]['months']
        temperatures = [row['temperature_c'] for row in months]
        # February/December and March/November are equal by the supplied cycle;
        # twelve months does not mean twelve distinct thermal values.
        supplied = [m['regimes'][0]['atmosphere']['reference_temperature_c']
                    for m in self.config['months']]
        self.assertEqual(len(set(temperatures)), len(set(supplied)))
        self.assertEqual(temperatures.index(min(temperatures)), 0)
        self.assertEqual(temperatures.index(max(temperatures)), 6)
        self.assertAlmostEqual(max(temperatures)-min(temperatures), 22., places=12)
        self.assertEqual([F(r['duration_seconds']) for r in months], [F(d*86400) for d in DAYS])

    def test_unknown_month_never_creates_dry_annual_forcing(self):
        config = deepcopy(self.config)
        config['months'][4]['regimes'] = None
        result = self.s.build(self.b, self.soil, config)
        for member in result['members'].values():
            self.assertEqual(member['atmosphere'], [])
            self.assertEqual(len(member['formed_terrain']), 2)
            for cell in member['cells'].values():
                self.assertEqual(cell['status'], 'UNKNOWN')
                self.assertIsNone(cell['months'])
                self.assertIsNone(cell['events'])

    def test_fluid_constants_must_match_actual_atmosphere(self):
        for key in ('water_density_kg_m3', 'molecular_mass_ratio'):
            config = deepcopy(self.config)
            config['demand_constants'][key] *= .99
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'fluid constants'):
                self.s.build(self.b, self.soil, config)

    def test_snow_depletion_time_independent_constant_flux(self):
        result = self.snow()
        self.assertEqual(result['status'], 'MODELLED_PERIODIC_SNOW')
        self.assertEqual(len(result['events']), 13)
        january, february = result['months'][:2]
        initial = F(january['snow']['ledger']['final_swe_m'])
        dt = F(february['duration_seconds'])
        melt_rate = F(february['snow']['ledger']['potential_melt_m'])/dt
        expected = initial/melt_rate
        events = [e for e in result['events'] if e['month_id'] == 2]
        self.assertEqual(F(events[0]['duration_seconds']), expected)
        self.assertEqual(F(events[1]['duration_seconds']), dt-expected)
        self.assertGreater(events[0]['liquid_input_m_s'], 0)
        self.assertEqual(events[1]['liquid_input_m_s'], 0)

    def test_snow_mass_once_only_with_exact_conversion_residuals(self):
        result = self.snow()
        represented = sum((F(e['liquid_input_m_s'])*F(e['duration_seconds']) for e in result['events']), F())
        conversion = sum((F(e['liquid_conversion_error_m']) for e in result['events']), F())
        input_water = sum((F(m['precipitation_m_s'])*F(m['duration_seconds']) for m in self.snow_months()), F())
        expected = input_water+F(result['initial_swe_m'])-F(result['final_swe_m'])
        self.assertEqual(represented-conversion, expected)
        self.assertEqual(F(result['annual_water_residual_m']), 0)
        self.assertEqual(F(result['annual_snowfall_m']), F(26784, 100000))

    def test_snow_events_preserve_month_cursor_and_exact_calendar(self):
        result = self.snow()
        ids = [row['event_id'] for row in result['events']]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual([r['month_id'] for r in result['events']], sorted(r['month_id'] for r in result['events']))
        for month, days in enumerate(DAYS, 1):
            events = [e for e in result['events'] if e['month_id'] == month]
            self.assertTrue(all(F(e['duration_seconds']) > 0 for e in events))
            self.assertEqual(sum((F(e['duration_seconds']) for e in events), F()), F(days*86400))

    def test_accumulating_snow_is_unknown_not_annual_reset(self):
        months = self.snow_months()
        for month in months:
            month['temperature_c'] = -20.
        result = self.snow(months)
        self.assertEqual(result['status'], 'UNKNOWN')
        self.assertIsNone(result['events'])
        self.assertIn('accumulation', result['reason'])
        self.assertGreater(F(result['annual_snowfall_m']), F(result['annual_melt_capacity_m']))

    def test_unconverged_snow_bracket_remains_unknown(self):
        result = self.snow(snow_max_cycles=1)
        self.assertEqual(result['status'], 'UNKNOWN')
        self.assertIsNone(result['events'])
        self.assertIn('brackets', result['reason'])

    def test_non_earth_day_changes_physical_duration_explicitly(self):
        config = deepcopy(self.config)
        config['calendar']['day_seconds'] = 90000
        months = self.snow_months(90000)
        # Fixed daily precipitation, same temperatures and days: the seasonal
        # water totals are invariant, while all melt timestamps scale with day.
        for row in months:
            row['precipitation_m_s'] = str(F(row['precipitation_m_s'])*F(86400, 90000))
            row['snowfall_m_s'] = str(F(row['snowfall_m_s'])*F(86400, 90000))
        changed = self.s.snow_cycle(self.hm, self.scenario, months, config,
                                   'independent-snow-cell', '0'*64)
        original = self.snow()
        self.assertEqual(changed['annual_snowfall_m'], original['annual_snowfall_m'])
        self.assertEqual(changed['annual_melt_capacity_m'], original['annual_melt_capacity_m'])
        before = next(e for e in original['events'] if e['month_id'] == 2)
        after = next(e for e in changed['events'] if e['month_id'] == 2)
        self.assertEqual(F(after['duration_seconds']), F(before['duration_seconds'])*F(90000, 86400))

    def test_calendar_shape_days_and_day_unit_reject(self):
        changes = [('calendar_id', 'GUESSED_YEAR'), ('month_days', [30]*12),
                   ('month_days', [31., *DAYS[1:]]), ('day_seconds', 0),
                   ('day_seconds', True), ('day_seconds', float('inf'))]
        for key, value in changes:
            config = deepcopy(self.config); config['calendar'][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                self.s.configuration(config)

    def test_missing_duplicate_and_boolean_month_ids_reject(self):
        for mode in ('missing', 'duplicate', 'boolean'):
            config = deepcopy(self.config)
            if mode == 'missing': config['months'].pop()
            elif mode == 'duplicate': config['months'][1]['month_id'] = 1
            else: config['months'][0]['month_id'] = True
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                self.s.configuration(config)

    def test_exact_mixture_weight_and_unique_regime_guards(self):
        for mode in ('nonclosure', 'boolean', 'duplicate', 'empty'):
            config = deepcopy(self.config); regimes = config['months'][0]['regimes']
            if mode == 'nonclosure': regimes[0]['weight'] = .2
            elif mode == 'boolean': regimes[0]['weight'] = True
            elif mode == 'duplicate': regimes[0]['regime_id'] = regimes[1]['regime_id']
            else: config['months'][0]['regimes'] = []
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                self.s.configuration(config)

    def test_surface_inventory_transect_and_schema_guards(self):
        for mode in ('surface', 'duplicate_cell', 'unknown_field'):
            config = deepcopy(self.config)
            if mode == 'surface': config['months'][0]['regimes'][0]['surfaces'].pop('upper')
            elif mode == 'duplicate_cell': config['transect'][1]['cell_id'] = 'upper'
            else: config['silent_default'] = 1
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                self.s.configuration(config)

    def test_snow_work_tolerance_and_evidence_guards(self):
        for key, value in (('snow_max_cycles', True), ('snow_max_cycles', 0),
                           ('snow_atol_m', 0), ('snow_atol_m', float('nan')),
                           ('temperature_distribution_evidence', ''), ('evidence', '')):
            config = deepcopy(self.config); config[key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                self.s.configuration(config)

    def test_plain_nested_dataclass_fraction_and_integer_class_keys(self):
        @dataclass
        class Example:
            amount: F
            classes: dict
        result = self.s.plain(Example(F(2, 3), {1: (F(1, 7), {'10': 'retained'})}))
        self.assertEqual(result, {'amount': '2/3', 'classes': {'1': ['1/7', {'10': 'retained'}]}})
        self.assertEqual(json.loads(json.dumps(result)), result)

    def test_plain_integer_string_class_collision_rejects(self):
        with self.assertRaisesRegex(ValueError, 'collision'):
            self.s.plain({1: 'first', '1': 'second'})

    def test_plain_boolean_float_and_tuple_class_keys_reject(self):
        for key in (True, 1., (1,), None):
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.s.plain({key: 'unsupported'})

    def test_digest_finite_deterministic_and_number_underflow_guards(self):
        self.assertEqual(self.s.digest({'b': F(1, 3), 'a': {2: 'x'}}),
                         self.s.digest({'a': {'2': 'x'}, 'b': F(1, 3)}))
        for value in (float('nan'), float('inf'), -float('inf')):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.s.digest({'value': value})
        with self.assertRaises(ValueError):
            self.s.number(F(1, 10**1000), 'unrepresentable positive', positive=True)


if __name__ == '__main__':
    unittest.main()
