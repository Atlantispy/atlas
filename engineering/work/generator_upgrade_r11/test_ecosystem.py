"""Independent budgets/oracles using actual fresh-bound R7 operators."""
from copy import deepcopy
from dataclasses import replace
from fractions import Fraction as F
import hashlib
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from . import binding, ecosystem as e

S = 'SYNTHETIC TEST'
E = 'SYNTHETIC TEST: no Diadem biological calibration; explicit bounded finite-stock experiment'
DAYS = (31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)


def tri(n, p=None, k=None):
    return (('N', n), ('P', n if p is None else p), ('K', n if k is None else k))


class EcosystemTests(unittest.TestCase):
    refinement_products = None
    actual_reference_products = None

    @classmethod
    def setUpClass(cls):
        cls.parent = binding.load().parent
        r7 = cls.parent.parent.parent.parent
        cls.o = r7.graph.load('work.generator_upgrade_r7.organic')
        cls.f = r7.graph.load('work.generator_upgrade_r7.fertility')

    def organic_law(self, **kw):
        row = dict(fast_rate_per_s=.001, slow_rate_per_s=.0002, fast_to_slow_fraction=F(1,5),
            carbon_fraction_dry_matter=F(1,2), reference_temperature_k=300., fast_activation_energy_j_mol=0.,
            slow_activation_energy_j_mol=0., gas_constant_j_mol_k=8.314, minimum_temperature_k=250., maximum_temperature_k=340.,
            moisture_curve=((0., 0.), (1., 1.)), redox_factors=(('OXIC', 1., 1.), ('ANOXIC', .1, .2)),
            regimes=('AERATED_MINERAL',), evidence=E, source_status=S)
        row.update(kw)
        return self.o.OrganicLaw(**row)

    def plant_law(self, **kw):
        row = dict(law_id='EXPLICIT_TEST_PLANT', net_light_use_efficiency_kg_c_j=F(1,1000),
            nutrient_kg_per_kg_c=tri(F(1,10), F(1,50), F(1,20)), uptake_rate_per_s=tri(F(10)), carbon_fraction_dry_matter=F(2,5),
            turnover_per_s=F(1,2000), litter_fast_fraction=F(3,4),
            temperature_curve_k=((F(270), F()), (F(290), F(1)), (F(310), F(1)), (F(330), F())), evidence=E, source_status=S)
        row.update(kw)
        return e.PlantLaw(**row)

    def context(self, **kw):
        chemistry = self.f.Chemistry('synthetic-chemistry', 6.5, .1, 'EXPLICIT_TEST', E)
        laws = tuple(self.f.NutrientLaw(n, .0003, .01, 1., 300., 0., 8.314,
            chemistry.chemistry_id, 'EXPLICIT_NET_'+n, E) for n in e.NUTRIENTS)
        row = dict(chemistry=chemistry, laws=laws, sorbent_mass_kg_m2=F(10), evidence=E, source_status=S)
        row.update(kw)
        return e.NutrientContext(**row)

    def initial(self, **kw):
        organic = self.o.OrganicState('layer-a', 'support-a', F(2), F(3), F(1000), E, S)
        row = dict(organic_state=organic, live_carbon_kg_m2=F(1), live_nutrients_kg_m2=tri(F(1,10), F(1,50), F(1,20)),
            reserve_nutrients_kg_m2=tri(F(1)), labile_nutrients_kg_m2=tri(F(1,10)), elapsed_seconds=F(100), evidence=E, source_status=S)
        row.update(kw)
        return e.State(**row)

    def calendar(self):
        return e.Calendar('365_TEST_SECOND_DAYS', tuple(F(d) for d in DAYS), F(1), E)

    def events(self, *, split=1, water_stress=F(1), activity=F(1), harvest=F(), par_rate=F(1), downward=.0001, upward=0., concentration=0., turnover_source=None):
        output = []
        for month, days in enumerate(DAYS, 1):
            for part in range(split):
                dt = F(days, split)
                forcing = self.o.OrganicForcing(dt, F(), F(), 300., .5, 'OXIC', 'AERATED_MINERAL',
                    'soil-temperature', 'actual-water-'+str(month)+'-'+str(part), E, E, E, S)
                exposure = self.f.WaterExposure(float(dt), 300., .5, .2, downward, upward, concentration, E)
                output.append(e.Event('m%d-%d' % (month, part), month, 'layer-a', 'support-a', forcing,
                    (exposure,)*3, dt*par_rate, F(300), water_stress, activity,
                    harvest if month == 12 and part == split-1 else F(), forcing.water_state_id, 'thermal-state', E, E, S))
        return tuple(output)

    def run_case(self, **kw):
        args = dict(initial_state=self.initial(), plant_law=self.plant_law(), organic_law=self.organic_law(),
            nutrient_context=self.context(), calendar=self.calendar(), events=self.events(), numerics=self.o.Numerics(),
            geometry_sha256='a'*64, source_binding_sha256=self.parent.source_sha256,
            scenario_id='bounded-ecosystem', evidence=E, source_status=S)
        args.update(kw)
        return e.run_year(self.o, self.f, **args)

    def test_actual_r7_producers_are_executed(self):
        out = self.run_case()
        self.assertEqual(out['status'], 'MODELLED_SEASONAL_ECOSYSTEM')
        self.assertEqual((out['completed_events'], out['completed_months']), (12,12))
        self.assertEqual(out['events'][0]['organic_producer']['schema'], 'diadem.organic-carbon-snapshot.r7')
        self.assertEqual(out['events'][0]['nutrient_producers']['N']['schema'], 'diadem.nutrient-reference.r7')

    def test_independent_exact_carbon_budget(self):
        out = self.run_case(events=self.events(harvest=F(1,3)))
        b = {k:F(v) for k,v in out['annual_budgets_kg_m2']['C'].items()}
        self.assertEqual(b['initial']+b['net_atmospheric_input']+b['external_litter_input'], b['final']+b['heterotrophic_export']+b['harvest_export'])
        self.assertEqual(b['numerical_residual'], 0)
        self.assertGreater(b['heterotrophic_export'], 0); self.assertGreater(b['harvest_export'], 0)

    def test_independent_element_budgets_keep_numeric_residual(self):
        out = self.run_case(events=self.events(harvest=F(1,3), upward=.00001, concentration=.02))
        for n in e.NUTRIENTS:
            b = {k:F(v) for k,v in out['annual_budgets_kg_m2'][n].items()}
            self.assertEqual(b['initial']+b['external_input'], b['final']+b['water_export']+b['harvest_export']+b['numerical_residual'])
            self.assertLess(abs(float(b['numerical_residual'])), 1e-9)
            self.assertGreater(b['external_input'], 0); self.assertGreater(b['water_export'], 0)

    def test_existing_stock_turnover_closed_form_no_new_production(self):
        out = self.run_case(events=self.events(par_rate=F(), downward=0.))
        live = F(out['final_state']['live_carbon_kg_m2'])
        self.assertAlmostEqual(float(live), math.exp(-.0005*365), places=13)
        litter = sum((F(r['litter_carbon_kg_m2']) for r in out['events']), F())
        self.assertEqual(live+litter, 1)

    def test_unlimited_growth_apar_oracle_no_turnover(self):
        out = self.run_case(plant_law=self.plant_law(turnover_per_s=F()), events=self.events(downward=0.))
        total = sum((F(r['net_production_kg_c_m2']) for r in out['events']), F())
        self.assertEqual(total, F(365,1000))
        self.assertEqual(F(out['final_state']['live_carbon_kg_m2']), 1+total)

    def test_finite_nutrient_limitation_depletes_labile_once(self):
        context = self.context(); context = replace(context, laws=tuple(replace(law, release_per_s=0.) for law in context.laws))
        state = self.initial(labile_nutrients_kg_m2=tri(F(1,1000), F(1), F(1)), reserve_nutrients_kg_m2=tri(F()))
        out = self.run_case(initial_state=state, plant_law=self.plant_law(turnover_per_s=F()), nutrient_context=context, events=self.events(downward=0.))
        self.assertEqual(F(out['events'][0]['net_production_kg_c_m2']), F(float(F(1,1000)))*10)
        self.assertIn('N', out['events'][0]['limiting_nutrients'])
        self.assertEqual(F(out['events'][1]['net_production_kg_c_m2']), 0)
        self.assertEqual(dict(out['final_state']['labile_nutrients_kg_m2'])['N'], '0')

    def test_finite_p_and_k_can_each_limit_not_just_n(self):
        for n in ('P', 'K'):
            labs = tuple((key, F(1,10000) if key == n else F(1)) for key in e.NUTRIENTS)
            context = self.context(); context = replace(context, laws=tuple(replace(law, release_per_s=0.) for law in context.laws))
            out = self.run_case(initial_state=self.initial(labile_nutrients_kg_m2=labs, reserve_nutrients_kg_m2=tri(F())),
                nutrient_context=context, plant_law=self.plant_law(turnover_per_s=F()), events=self.events(downward=0.))
            self.assertIn(n, out['events'][0]['limiting_nutrients'])

    def test_explicit_uptake_kinetics_partition_independent_without_competing_fluxes(self):
        context = self.context(); context = replace(context, laws=tuple(replace(law, release_per_s=0., available_fraction=.5) for law in context.laws))
        law = self.plant_law(turnover_per_s=F(), uptake_rate_per_s=tri(F(1,1000)))
        initial = self.initial(reserve_nutrients_kg_m2=tri(F()), labile_nutrients_kg_m2=tri(F(1,1000), F(1), F(1)))
        expected_n = .001*math.exp(-.001*.5*365)
        for split in (1, 2, 4):
            out = self.run_case(initial_state=initial, plant_law=law, nutrient_context=context,
                organic_law=self.organic_law(fast_rate_per_s=0., slow_rate_per_s=0.), events=self.events(split=split, downward=0.))
            actual = float(F(dict(out['final_state']['labile_nutrients_kg_m2'])['N']))
            self.assertAlmostEqual(actual, expected_n, places=14)

    def test_unknown_uptake_rate_does_not_become_infinite_access(self):
        out = self.run_case(plant_law=self.plant_law(uptake_rate_per_s=(('N', None), ('P', F(1)), ('K', F(1)))))
        self.assertEqual(out['status'], 'UNKNOWN'); self.assertIn('plant_law.uptake_rate_per_s.N', out['missing_inputs'])

    def test_litter_nutrients_return_to_next_event_reserve(self):
        out = self.run_case(events=self.events(par_rate=F(), downward=0.))
        row = out['events'][0]
        for n in e.NUTRIENTS:
            before_return = F(row['nutrient_producers'][n]['reserve_kg_m2'])
            after_return = F(dict(row['end_state']['reserve_nutrients_kg_m2'])[n])
            self.assertEqual(after_return, before_return+F(row['litter_nutrients_kg_m2'][n]))
            self.assertEqual(row['end_state'], out['events'][1]['initial_state'])

    def test_seasonal_water_and_activity_constraints(self):
        drought = self.run_case(events=self.events(water_stress=F()))
        dormant = self.run_case(events=self.events(activity=F()))
        for out in (drought, dormant):
            self.assertTrue(all(F(r['net_production_kg_c_m2']) == 0 for r in out['events']))
            self.assertTrue(any(F(r['litter_carbon_kg_m2']) > 0 for r in out['events']))

    def test_temperature_piecewise_response_and_no_extrapolation(self):
        events = list(self.events()); events[0] = replace(events[0], canopy_temperature_k=F(280))
        out = self.run_case(events=tuple(events))
        self.assertEqual(F(out['events'][0]['temperature_response']), F(1,2))
        events[0] = replace(events[0], canopy_temperature_k=F(350))
        self.assertEqual(self.run_case(events=tuple(events))['status'], 'OUTSIDE_REGIME')

    def test_zero_vegetation_not_established_from_climate(self):
        out = self.run_case(initial_state=self.initial(live_carbon_kg_m2=F(), live_nutrients_kg_m2=tri(F())))
        self.assertTrue(all(F(r['net_production_kg_c_m2']) == 0 for r in out['events']))

    def test_harvest_is_endpoint_finite_stock_not_food(self):
        out = self.run_case(events=self.events(harvest=F(1)))
        self.assertEqual(F(out['final_state']['live_carbon_kg_m2']), 0)
        self.assertTrue(all(F(r['harvested_carbon_kg_m2']) == 0 for r in out['events'][:-1]))
        last = out['events'][-1]
        self.assertEqual(F(last['harvested_dry_matter_kg_m2']), F(last['harvested_carbon_kg_m2'])/F(2,5))
        self.assertIn('automatic food or crop-yield conversion', out['unmodelled'])

    def test_c_and_nutrient_initial_ages_are_not_reset(self):
        out = self.run_case()
        self.assertEqual(F(out['final_state']['elapsed_seconds']), 465)
        self.assertEqual(self.o.state_from_record(out['final_state']['organic_state']).elapsed_seconds, 1365)

    def test_monthly_fluxes_sum_initial_stock_does_not(self):
        out = self.run_case()
        for element in ('C',)+e.NUTRIENTS:
            annual = out['annual_budgets_kg_m2'][element]
            for field in annual:
                if field in ('initial', 'final'): continue
                self.assertEqual(F(annual[field]), sum((F(m['budgets_kg_m2'][element][field]) for m in out['months'].values()), F()))
            self.assertEqual(annual['initial'], out['months']['1']['budgets_kg_m2'][element]['initial'])

    def test_unknown_biological_law_not_zero_or_default(self):
        for name in ('net_light_use_efficiency_kg_c_j', 'turnover_per_s', 'carbon_fraction_dry_matter', 'litter_fast_fraction', 'temperature_curve_k'):
            out = self.run_case(plant_law=replace(self.plant_law(), **{name: None}))
            self.assertEqual(out['status'], 'UNKNOWN'); self.assertIsNone(out['annual_budgets_kg_m2'])
            self.assertIn('plant_law.'+name, out['missing_inputs'])

    def test_unknown_npk_stock_blocks_dependent_suffix(self):
        out = self.run_case(initial_state=self.initial(labile_nutrients_kg_m2=(('N', None), ('P', F(1)), ('K', F(1)))))
        self.assertEqual(out['status'], 'UNKNOWN'); self.assertEqual(out['completed_events'], 0)
        self.assertIn('state.labile_nutrients_kg_m2.N', out['missing_inputs'])

    def test_unknown_midyear_preserves_prior_only(self):
        events = list(self.events()); events[5] = replace(events[5], absorbed_par_j_m2=None)
        out = self.run_case(events=tuple(events))
        self.assertEqual(out['completed_months'], 5); self.assertIsNone(out['months']['6']['end_state'])
        self.assertIsNone(out['final_state']); self.assertIsNone(out['checkpoint'])

    def test_source_conflict_blocks_even_numerical_values(self):
        out = self.run_case(plant_law=replace(self.plant_law(), source_status='CONFLICT'))
        self.assertEqual(out['status'], 'UNKNOWN')
        self.assertIn('plant_law.source_status:CONFLICT', out['missing_inputs'])

    def test_actual_carbon_unknown_is_retained(self):
        out = self.run_case(organic_law=self.organic_law(fast_rate_per_s=None))
        self.assertEqual(out['status'], 'UNKNOWN'); self.assertIsNone(out['final_state'])
        self.assertEqual(out['failed_producer']['organic_producer']['status'], 'UNKNOWN')

    def test_native_numeric_failure_not_partial_commit(self):
        out = self.run_case(numerics=self.o.Numerics(max_rate_duration=.00001))
        self.assertEqual(out['status'], 'NUMERICAL_FAILURE'); self.assertEqual(out['completed_events'], 0)
        self.assertIsNone(out['checkpoint'])

    def test_source_geometry_scenario_restart_binding(self):
        cp = self.run_case(stop_after=3)['checkpoint']
        for kw in ({'source_binding_sha256': 'b'*64}, {'geometry_sha256': 'b'*64}, {'scenario_id': 'changed'}):
            with self.assertRaises(ValueError): self.run_case(resume=cp, **kw)

    def test_actual_disk_checkpoint_restart_exact(self):
        full = self.run_case(); stopped = self.run_case(stop_after=4)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'checkpoint.json'; path.write_text(json.dumps(stopped['checkpoint']), encoding='utf-8')
            readback = json.loads(path.read_text(encoding='utf-8'))
        self.assertEqual(full, self.run_case(resume=readback))

    def test_rehashed_false_state_rejected_by_replay(self):
        cp = deepcopy(self.run_case(stop_after=2)['checkpoint']); cp['state']['live_carbon_kg_m2'] = '999'
        cp['checkpoint_sha256'] = e.digest({k:v for k,v in cp.items() if k != 'checkpoint_sha256'})
        with self.assertRaisesRegex(ValueError, 'actual accepted prefix'): self.run_case(resume=cp)

    def test_zero_cursor_and_complete_cursor_restart(self):
        full = self.run_case()
        for cursor in (0, 12): self.assertEqual(full, self.run_case(resume=self.run_case(stop_after=cursor)['checkpoint']))

    def test_partial_month_checkpoint(self):
        out = self.run_case(events=self.events(split=2), stop_after=1)
        self.assertEqual(out['completed_months'], 0); self.assertIsNone(out['months']['1']['budgets_kg_m2'])
        self.assertEqual(self.run_case(events=self.events(split=2)), self.run_case(events=self.events(split=2), resume=out['checkpoint']))

    def test_exact_native_environment_and_duration_joins(self):
        events = self.events()
        for bad in (replace(events[0], layer_id='wrong'), replace(events[0], water_state_id='wrong'),
                    replace(events[0], nutrient_exposures=(replace(events[0].nutrient_exposures[0], duration_s=1.),)*3),
                    replace(events[0], nutrient_exposures=(replace(events[0].nutrient_exposures[0], temperature_k=301.),)*3)):
            with self.assertRaises(ValueError): self.run_case(events=(bad,)+events[1:])

    def test_chronology_calendar_and_count_guards(self):
        events = self.events()
        for values in (events[:-1], events[1:]+events[:1], events+(events[-1],)):
            with self.assertRaises(ValueError): self.run_case(events=values)
        with self.assertRaises(ValueError): self.run_case(stop_after=True)
        with self.assertRaises(ValueError): e.Calendar('bad', (F(1),)*12, F(1), E)

    def test_invalid_element_mass_and_finite_numeric_values(self):
        for value in (True, -1, float('nan'), float('inf')):
            with self.assertRaises(ValueError): self.plant_law(turnover_per_s=value)
        with self.assertRaises(ValueError): self.plant_law(carbon_fraction_dry_matter=F(1))
        with self.assertRaises(ValueError): self.initial(live_nutrients_kg_m2=(('P', F()), ('N', F()), ('K', F())))

    def test_existing_biological_element_mass_cannot_exceed_dry_mass(self):
        with self.assertRaises(ValueError): self.run_case(initial_state=self.initial(live_carbon_kg_m2=F(), live_nutrients_kg_m2=tri(F(1))))

    def test_positive_turnover_underflow_is_numeric_failure(self):
        out = self.run_case(plant_law=self.plant_law(turnover_per_s=F(1, 10**400)))
        self.assertEqual(out['status'], 'NUMERICAL_FAILURE'); self.assertIn('underflow', out['reason'])
        self.assertIsNone(out['final_state'])

    def test_fake_pass_nutrient_budget_rejected(self):
        original = self.f.advance_nutrient
        def wrong(*args, **kw):
            out = original(*args, **kw); out['labile_kg_m2'] += 1; return out
        with patch.object(self.f, 'advance_nutrient', side_effect=wrong), self.assertRaisesRegex(ValueError, 'conservation'):
            self.run_case()

    def test_fake_pass_carbon_budget_rejected(self):
        original = self.o.advance_layer
        def wrong(*args, **kw):
            out = original(*args, **kw); out['state'] = replace(out['state'], fast_carbon_kg_m2=out['state'].fast_carbon_kg_m2+1); return out
        with patch.object(self.o, 'advance_layer', side_effect=wrong), self.assertRaisesRegex(ValueError, 'conservation'):
            self.run_case()

    def test_soil_feedback_not_stale_geometry_claim(self):
        out = self.run_case()
        self.assertIn('FINITE_UPTAKE', out['nutrient_feedback'])
        self.assertEqual(out['physical_geometry_feedback'], 'REQUIRES_CONSERVATIVE_GEOMETRY_WATER_REBIND')
        self.assertNotIn('head_m', out['events'][0]['soil_material_change'])

    def test_input_objects_unchanged_and_strict_plain_output(self):
        state = self.initial(); law = self.plant_law(); events = self.events(); before = e.digest((state, law, events))
        out = self.run_case(initial_state=state, plant_law=law, events=events)
        self.assertEqual(e.digest((state, law, events)), before)
        self.assertEqual(out, json.loads(json.dumps(out, allow_nan=False)))
        self.assertEqual(out['inputs_sha256'], e.digest(out['inputs']))

    def test_split_growth_turnover_first_order_oracle(self):
        # Constant production at interval end and exact old-stock decay.
        # Continuous limit dB/dt=p-kB has a separate closed form.
        k, p, duration = .0005, .001, 365
        expected = math.exp(-k*duration)+(p/k)*(-math.expm1(-k*duration))
        errors = []; values = []
        for split in (1,2,4):
            out = self.run_case(events=self.events(split=split, downward=0.),
                organic_law=self.organic_law(fast_rate_per_s=0., slow_rate_per_s=0.))
            actual = float(F(out['final_state']['live_carbon_kg_m2'])); values.append(actual); errors.append(abs(actual-expected))
        ratios = [errors[i]/errors[i+1] for i in (0,1)]
        self.assertTrue(all(1.98 < ratio < 2.03 for ratio in ratios), ratios)
        self.__class__.refinement_products = {'scope':'explicit split plant growth/turnover; not empirical calibration',
            'subdivisions_per_month':[1,2,4], 'analytic_live_carbon_kg_m2': expected,
            'actual_live_carbon_kg_m2':values, 'absolute_errors_kg_m2':errors, 'error_ratios':ratios, 'predeclared_ratio_band':[1.98,2.03]}

    def actual_units(self):
        path = Path(__file__).resolve().parents[2]/'outputs/generator-upgrade-r10/seasonal-reference-01/n-worker-reference/full-result.json'
        raw = path.read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), 'f191389d93c411f81e7003e5edf96551b53dc945e359dc705d83d00c64a0930e')
        parent = json.loads(raw)
        payloads = self.parent.graph.load('work.generator_upgrade_r10.payloads')
        return {key: payloads.unpack(value) for key,value in parent['state']['results'].items()}

    def actual_spec(self, unit):
        spec = e.reference_spec(self.o, self.f, unit)
        joins = spec.pop('reference_join')
        return spec, joins

    def test_all_18_actual_r10_parent_units_have_complete_budgets(self):
        units = self.actual_units(); self.assertEqual(len(units), 18)
        receipt = {}
        for key, unit in units.items():
            spec, joins = self.actual_spec(unit)
            out = e.run_year(self.o, self.f, **spec, source_binding_sha256=self.parent.source_sha256,
                scenario_id=key, evidence=E, source_status=S)
            self.assertEqual(out['status'], 'MODELLED_SEASONAL_ECOSYSTEM', (key, out['reason']))
            self.assertEqual(out['completed_months'], 12)
            self.assertEqual(out['inputs']['initial_state']['organic_state'], unit['carbon']['layers'][unit['cell_id']+'-mineral']['diagnostic']['inputs']['initial_state'])
            self.assertTrue(all(F(event['organic_forcing']['fast_litter_carbon_kg_m2_s']) == 0 and F(event['organic_forcing']['slow_litter_carbon_kg_m2_s']) == 0 for event in out['inputs']['events']))
            for element, budget in out['annual_budgets_kg_m2'].items():
                b = {field:F(value) for field,value in budget.items()}
                if element == 'C': self.assertEqual(b['initial']+b['net_atmospheric_input']+b['external_litter_input'], b['final']+b['heterotrophic_export']+b['harvest_export'])
                else: self.assertEqual(b['initial']+b['external_input'], b['final']+b['water_export']+b['harvest_export']+b['numerical_residual'])
            receipt[key] = {'result_sha256': e.digest(out), 'parent_unit_sha256': joins['actual_r10_unit_sha256'],
                'completed_events': out['completed_events'], 'completed_months': out['completed_months'], 'annual_budgets_kg_m2': out['annual_budgets_kg_m2']}
        self.__class__.actual_reference_products = receipt

    def test_reference_joins_each_face_once(self):
        unit = next(iter(self.actual_units().values())); spec, joins = self.actual_spec(unit)
        layers = unit['hydrology']['column']['layers']; index = next(i for i,v in enumerate(layers) if v['layer_id'] == unit['cell_id']+'-mineral')
        for wrow, join in zip(unit['hydrology']['events'], joins['event_joins']):
            ledger = wrow['solver_result']['ledger']
            self.assertEqual(F(join['gross_outgoing_m']), F(ledger['face_downward_m'][index+1])+F(ledger['face_upward_m'][index]))
            self.assertEqual(F(join['gross_incoming_m']), F(ledger['face_downward_m'][index])+F(ledger['face_upward_m'][index+1]))
        self.assertIn('REPLACED', joins['legacy_external_litter'])
        self.assertEqual(spec['initial_state'].source_status, S)

    def test_actual_reference_restart_same_saved_values(self):
        unit = next(iter(self.actual_units().values())); spec, joins = self.actual_spec(unit)
        args = dict(source_binding_sha256=self.parent.source_sha256, scenario_id='actual-restart', evidence=E, source_status=S)
        full = e.run_year(self.o, self.f, **spec, **args)
        stopped = e.run_year(self.o, self.f, **spec, **args, stop_after=4)
        restored = e.run_year(self.o, self.f, **spec, **args, resume=json.loads(json.dumps(stopped['checkpoint'])))
        self.assertEqual(full, restored)

    def test_actual_reference_tampered_parent_join_rejected(self):
        original = next(iter(self.actual_units().values()))
        for mode in ('water_hash', 'source_hash', 'event', 'layer'):
            unit = deepcopy(original)
            if mode == 'water_hash': unit['carbon']['water_product_sha256'] = '0'*64
            elif mode == 'source_hash': unit['carbon']['layers']['lower-mineral']['diagnostic']['inputs_sha256'] = '0'*64
            elif mode == 'event': unit['hydrology']['events'][0]['event_id'] = 'changed'
            else: unit['hydrology']['column']['layers'][5]['layer_id'] = 'changed'
            with self.assertRaises(ValueError): self.actual_spec(unit)


if __name__ == '__main__': unittest.main()
