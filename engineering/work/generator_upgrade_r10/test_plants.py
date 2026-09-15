"""Actual fresh-bound R8 trajectory projections, independent aggregate oracles."""
from copy import deepcopy
from fractions import Fraction as F
import json
import math
import unittest

from . import binding, plants as p

E = 'SYNTHETIC TEST: explicit activity and available-water law, not species biology'
S = 'SYNTHETIC TEST'
DAYS = (31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)


class PlantTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bundle = binding.load()
        cls.v = cls.bundle.parent.parent.graph.load('work.generator_upgrade_r8.vegetation')

    def actual(self, *, active=None, unknown=None, split=False, threshold=.4,
               inactive_demand=False, ecological_fail=False):
        v = self.v
        cal = v.Calendar('explicit365-second-test-year', tuple(F(x) for x in DAYS), F(1), E)
        cap = v.WaterCapacity(1., 2., 'physical-support-test', E, S)
        active = [True]*12 if active is None else active
        rows = []
        for m, dt in enumerate(DAYS, 1):
            on = active[m-1]
            parts = 2 if split and m == 1 else 1
            for part in range(parts):
                rows.append(v.Event('m%d-%d' % (m, part), m, F(dt, parts), 10.,
                    None if unknown == m else .002 if on or inactive_demand else 0.,
                    .01 if on or inactive_demand else 0., on,
                    E, 'UNKNOWN' if unknown == m else S))
        constraints = v.PFTConstraints('explicit-test-PFT', None, threshold,
            (v.Limit('rooted_depth_m', 3. if ecological_fail else 0., None, E, S),), (), E, S)
        return v.evaluate(cap, cal, tuple(rows), constraints, {})

    def project(self, result, **kw):
        return p.seasonal_activity(result, source_id='actual-test-R8-PFT', source_sha256=p.digest(result), **kw)

    def test_actual_source_bound_result_and_json(self):
        result = self.actual(); projected = self.project(result)
        self.assertEqual(projected['status'], 'MODELLED_CONDITIONAL_ACTIVITY')
        self.assertEqual(len(projected['months']), 12)
        self.assertEqual(projected, json.loads(json.dumps(projected, allow_nan=False)))

    def test_independent_exact_calendar_activity(self):
        projected = self.project(self.actual(active=[False]+[True]*11))
        durations = [F(row['physiological_active_duration_seconds']) for row in projected['months']]
        self.assertEqual(sum(durations, F()), 334)
        self.assertEqual(projected['months'][0]['physiological_active_fraction'], 0.)
        self.assertTrue(all(row['physiological_active_fraction'] == 1 for row in projected['months'][1:]))

    def test_monthly_activity_fraction_is_duration_not_event_count(self):
        result = self.actual(split=True)
        v = self.v; inputs = result['inputs']
        events = []
        for row in inputs['events']:
            row = dict(row); row['duration_seconds'] = F(row['duration_seconds'])
            if row['event_id'] == 'm1-0': row.update(active=False, liquid_input_m_s=0., potential_transpiration_m_s=0.)
            events.append(v.Event(**row))
        cal = v.Calendar('test', tuple(F(d) for d in DAYS), F(1), E)
        con = v.PFTConstraints('test', None, .4, (v.Limit('rooted_depth_m', 0., None, E, S),), (), E, S)
        actual = v.evaluate(v.WaterCapacity(1., 2., 's', E, S), cal, tuple(events), con, {})
        first = self.project(actual)['months'][0]
        self.assertEqual(first['physiological_active_duration_seconds'], '31/2')
        self.assertEqual(first['physiological_active_fraction'], .5)

    def test_independent_month_flux_sums(self):
        actual = self.actual(split=True); result = self.project(actual)
        for month in result['months']:
            for side in ('lower', 'upper'):
                rows = [r for r in actual['water'][side]['events'] if r['month_id'] == month['month_id']]
                exact = sum((F(r['actual_transpiration_m']) for r in rows), F())
                interval = month['available_water']['actual_transpiration_m']
                self.assertLessEqual(interval['lower'], float(exact))
                self.assertGreaterEqual(interval['upper'], float(exact))

    def test_preserved_month_residuals_sum_to_cycle_exactly(self):
        actual = self.actual(split=True); result = self.project(actual)
        for side in ('lower', 'upper'):
            observed = sum((F(m['available_water']['numerical_residual_m'][side+'_trajectory']) for m in result['months']), F())
            self.assertEqual(observed, F(actual['water'][side]['numerical_residual_m']))

    def test_monotone_event_storage_bounds(self):
        actual = self.actual(); result = self.project(actual)
        for month in result['months']:
            water = month['available_water']
            self.assertLessEqual(water['minimum_storage_m']['lower'], water['maximum_storage_m']['upper'])
            self.assertGreaterEqual(water['minimum_storage_m']['lower'], 0)
            self.assertLessEqual(water['maximum_storage_m']['upper'], 1)

    def test_cyclic_drought_wrap_independent_62_second_oracle(self):
        actual = self.actual(active=[True]+[False]*10+[True]); result = self.project(actual)
        drought = result['cyclic_drought']
        # Equilibrium S=.002/.01=.2 < .4; only first and last31 seconds active.
        for key in ('dry_active_duration_s', 'longest_cyclic_dry_active_spell_s'):
            self.assertEqual(drought[key], {'lower': 62., 'upper': 62.})

    def test_all_cycle_dry_not_counted_twice(self):
        result = self.project(self.actual())
        self.assertEqual(result['cyclic_drought']['longest_cyclic_dry_active_spell_s'], {'lower':365., 'upper':365.})

    def test_missing_dry_threshold_remains_unknown(self):
        result = self.project(self.actual(threshold=None))
        self.assertIsNone(result['cyclic_drought']['dry_active_duration_s'])
        self.assertEqual(result['cyclic_drought']['status'], 'UNKNOWN')

    def test_month_dry_is_not_invented_from_average_water(self):
        result = self.project(self.actual())
        self.assertTrue(all(m['dry_active_duration_s'] is None for m in result['months']))
        self.assertTrue(all('UNKNOWN' in m['dry_duration_reason'] for m in result['months']))

    def test_unknown_forcing_does_not_become_dry_or_inactive(self):
        result = self.project(self.actual(unknown=2))
        self.assertEqual(result['status'], 'UNKNOWN')
        self.assertIsNone(result['months'][1]['physiological_active_fraction'])
        self.assertIsNone(result['months'][0]['available_water'])
        self.assertEqual(result['months'][0]['physiological_active_fraction'], 1.)

    def test_known_zero_demand_not_perfect_water_adequacy(self):
        result = self.project(self.actual(active=[True]+[False]*10+[True]))
        water = result['months'][1]['available_water']
        self.assertEqual(water['potential_transpiration_m'], {'lower':0., 'upper':0.})
        self.assertIsNone(water['active_actual_to_potential_transpiration_ratio'])

    def test_inactive_supplied_demand_not_silently_deleted(self):
        result = self.project(self.actual(active=[False]+[True]*11, inactive_demand=True))
        water = result['months'][0]['available_water']
        self.assertGreater(water['actual_transpiration_m']['lower'], 0)
        self.assertEqual(water['active_actual_transpiration_m'], {'lower':0., 'upper':0.})

    def test_ecological_failure_is_preserved_not_occurrence(self):
        result = self.project(self.actual(ecological_fail=True))
        self.assertEqual(result['ecological_admissibility'], 'FAIL')
        self.assertEqual(result['status'], 'MODELLED_CONDITIONAL_ACTIVITY')
        self.assertIn('occurrence', result['activity_semantics'])

    def test_no_leaf_growth_reproduction_or_new_gdd(self):
        result = self.project(self.actual())
        for month in result['months']:
            for key in ('leaf_on', 'dormancy', 'flowering', 'growth_biomass_kg'):
                self.assertIsNone(month[key])
            self.assertNotIn('growing_degree_days', month)

    def test_external_calendar_must_match_exactly(self):
        actual = self.actual()
        self.project(actual, month_durations_seconds=DAYS)
        with self.assertRaises(ValueError): self.project(actual, month_durations_seconds=(30,)+DAYS[1:])

    def test_digest_and_original_not_mutated(self):
        actual = self.actual(); saved = deepcopy(actual)
        output = self.project(actual)
        self.assertEqual(actual, saved)
        self.assertEqual(output['source']['pft_payload_sha256'], p.digest(saved))
        with self.assertRaises(ValueError): p.seasonal_activity(actual, source_id='s', source_sha256='0'*64)

    def test_malformed_event_contracts_failclosed(self):
        actual = self.actual()
        for key, value in (('event_id', actual['inputs']['events'][1]['event_id']),
                           ('duration_seconds', '30'), ('month_id', True), ('active', 1)):
            broken = deepcopy(actual); broken['inputs']['events'][0][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError): self.project(broken)

    def test_event_reordering_rejected(self):
        actual = self.actual(); actual['inputs']['events'].reverse()
        with self.assertRaises(ValueError): self.project(actual)

    def test_water_identity_and_ledger_mutations_rejected(self):
        actual = self.actual()
        for key, value in (('month_id', 2), ('active', False), ('capacity_m', .5),
                           ('input_m', .9), ('initial_m', .8), ('numerical_residual_m', '0'),
                           ('supplied_duration_seconds', '30'), ('duration_conversion_residual_s', '1')):
            broken = deepcopy(actual); broken['water']['lower']['events'][0][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError): self.project(broken)

    def test_nonfinite_and_boolean_water_rejected(self):
        for bad in (float('nan'), float('inf'), True, -1.):
            actual = self.actual(); actual['water']['lower']['events'][0]['final_m'] = bad
            with self.subTest(bad=bad), self.assertRaises(ValueError): self.project(actual)

    def test_incomplete_or_unbound_source_rejected(self):
        actual = self.actual()
        for mutate in (lambda r: r['water']['upper']['events'].pop(),
                       lambda r: r['inputs']['capacity'].update(source_status='UNKNOWN'),
                       lambda r: r.update(source_status='CONFLICT'),
                       lambda r: r['water']['lower'].update(all_actual_transpiration_m=0.)):
            broken = deepcopy(actual); mutate(broken)
            with self.assertRaises(ValueError): self.project(broken)

    def test_unknown_and_numerical_failure_not_relabelled(self):
        for status in ('UNKNOWN', 'OUTSIDE_REGIME', 'NUMERICAL_FAILURE'):
            actual = self.actual(); actual['water'] = {'status':status, 'lower':None, 'upper':None}
            result = self.project(actual)
            self.assertEqual(result['status'], status)
            self.assertIsNone(result['months'][0]['available_water'])

    def test_contradictory_status_identity_and_dry_diagnostics_reject(self):
        for mutate in (lambda r: r.update(status='NUMERICAL_FAILURE'),
                       lambda r: r.update(source_status=None),
                       lambda r: r['inputs']['constraints'].update(pft_id='wrong'),
                       lambda r: r['water']['lower'].update(dry_active_duration_s=1.)):
            actual = self.actual(); mutate(actual)
            with self.assertRaises(ValueError): self.project(actual)

    def test_partition_invariance_for_same_physical_forcing(self):
        a = self.project(self.actual()); b = self.project(self.actual(split=True))
        for left, right in zip(a['months'], b['months']):
            self.assertEqual(left['physiological_active_fraction'], right['physiological_active_fraction'])
            for field in ('input_m', 'actual_transpiration_m', 'potential_transpiration_m'):
                for side in ('lower', 'upper'):
                    self.assertAlmostEqual(left['available_water'][field][side], right['available_water'][field][side], places=11)

    def test_full_actual_owner_roster_preserves17_plants(self):
        owner = self.bundle.parent.graph.load('work.generator_upgrade_r9.owner_inputs')
        roster = owner.biological_roster(); result = p.species_phenology(roster)
        self.assertEqual(len(result['plants']), 17)
        for key, row in result['plants'].items():
            self.assertEqual(row['status'], 'UNKNOWN')
            self.assertEqual(row['qualitative_constraints'], roster[key]['special_details'])
            self.assertEqual(row['source_binding'], roster[key]['source_binding'])
            self.assertIsNone(row['flowering_windows'])
        vine = result['plants']['bannerhaus_periwinkle_vine']['qualitative_constraints']
        self.assertIn('no obligatory winter dormancy', vine['qualitative_constraint_readback'])
        fruit = result['plants']['bannerhaus_mistleholly_berries']['qualitative_constraints']
        self.assertIn('year-round cultivated fruit', fruit['qualitative_constraint_readback'])

    def test_roster_identity_and_binding_failclosed(self):
        row = {'organism_id':'p', 'name':'p', 'kind':'PLANT', 'source_status':S,
               'source_binding':{'raw_status':'explicit'}, 'evidence':E, 'special_details':{}}
        with self.assertRaises(ValueError): p.species_phenology({'wrong':row})
        row['source_binding'] = None
        with self.assertRaises(ValueError): p.species_phenology({'p':row})


if __name__ == '__main__':
    unittest.main()
