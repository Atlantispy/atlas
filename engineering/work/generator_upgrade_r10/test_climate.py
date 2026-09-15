"""Exact saved-R8 projections; tiny synthetic wind and climatic-index probes."""
from copy import deepcopy
from fractions import Fraction as F
import hashlib
import json
import math
from pathlib import Path
import unittest

from . import binding, climate as c

FIXTURE = Path(__file__).resolve().parents[2]/'outputs/generator-upgrade-r8/biomes-reference-01/n-worker-reference/full-result.json'
FIXTURE_SHA256 = '19a0975d09d1571e68ed510421b085675753b64ddfba316c8e8e2d68662cb000'


def test_data_bindings():
    return {str(FIXTURE): FIXTURE_SHA256}


def saved_parent():
    if FIXTURE.is_symlink() or not FIXTURE.is_file() or FIXTURE.stat().st_size > 8*1024*1024:
        raise ValueError('bounded actual saved R8 fixture required')
    raw = FIXTURE.read_bytes()
    if hashlib.sha256(raw).hexdigest() != FIXTURE_SHA256:
        raise ValueError('saved R8 fixture bytes changed')
    return json.loads(raw)


class ClimateTests(unittest.TestCase):
    actual_projection = None

    @classmethod
    def setUpClass(cls):
        cls.bundle = binding.load()
        cls.actual_parent = saved_parent()
        cls.expected_source = cls.bundle.parent.parent.source_sha256
        if cls.actual_parent['source_sha256'] != cls.expected_source:
            raise ValueError('saved fixture is not the current pinned R8 source')
        cls.actual_projection = c.project(cls.actual_parent, cls.expected_source)
        cls.member = next(iter(cls.actual_parent['seasonal']['members']))
        cls.cell = next(iter(cls.actual_parent['seasonal']['members'][cls.member]['cells']))

    def first(self, parent=None):
        return (self.actual_parent if parent is None else parent)['seasonal']['members'][self.member]['cells'][self.cell]

    def regimes(self):
        return deepcopy(self.actual_parent['seasonal']['members'][self.member]['atmosphere'][0]['regimes'])

    def rehash_seasonal(self, value):
        # For reduced-model mutation tests only. This does not claim fresh R8 production.
        value['state']['seasonal_sha256'] = c.digest(value['seasonal'])
        return value

    def test_exact_saved_source_and_all_coequal_members(self):
        output = self.actual_projection
        self.assertEqual(output['parent_result_sha256'], c.digest(self.actual_parent))
        self.assertEqual(set(output['members']), set(self.actual_parent['seasonal']['members']))
        self.assertEqual(len(output['members']), 3)
        self.assertEqual(output, json.loads(json.dumps(output,allow_nan=False)))

    def test_independent_duration_weighted_vs_month_arithmetic_temperature(self):
        for member_id, member in self.actual_projection['members'].items():
            for cell_id, cell in member['cells'].items():
                actual = self.actual_parent['seasonal']['members'][member_id]
                temperatures=[]; durations=[]
                for month, air in zip(actual['cells'][cell_id]['months'],actual['atmosphere']):
                    temperatures.append(sum((F(r['weight'])*F(r['products'][cell_id]['air']['temperature_c']) for r in air['regimes']), F()))
                    durations.append(F(month['duration_seconds']))
                weighted=sum((t*d for t,d in zip(temperatures,durations)),F())/sum(durations,F())
                arithmetic=sum(temperatures,F())/12
                self.assertEqual(F(cell['annual']['duration_weighted_temperature_c']['exact']),weighted)
                self.assertEqual(F(cell['annual']['arithmetic_mean_of_monthly_means_temperature_c']['exact']),arithmetic)
                self.assertNotEqual(weighted,arithmetic)

    def test_once_only_rain_plus_melt_and_representation_residual(self):
        for member in self.actual_projection['members'].values():
            for cell in member['cells'].values():
                annual=cell['annual']
                self.assertEqual(F(annual['liquid_to_soil_m']['exact']),F(annual['rain_m']['exact'])+F(annual['melt_m']['exact']))
                self.assertEqual(F(annual['precipitation_m']['exact']),F(annual['rain_m']['exact'])+F(annual['snowfall_swe_m']['exact']))
                for month in cell['months']:
                    selected=[e for e in cell['events'] if e['month_id']==month['month_id']]
                    represented=sum((F(e['represented_liquid_m']['exact']) for e in selected),F())
                    error=sum((F(e['representation_error_m']['exact']) for e in selected),F())
                    exact=F(month['liquid_to_soil_m']['exact'])
                    self.assertEqual(represented-error,exact)

    def test_exact_contiguous_event_and_month_clocks(self):
        for member in self.actual_projection['members'].values():
            for cell in member['cells'].values():
                for key in ('months','events'):
                    prior=F()
                    for row in cell[key]:
                        self.assertEqual(F(row['start_seconds']),prior)
                        self.assertEqual(F(row['end_seconds'])-prior,F(row['duration_seconds']))
                        prior=F(row['end_seconds'])
                    self.assertEqual(prior,F(365*86400))

    def test_annual_fluxes_are_sums_not_mean_months(self):
        cell=self.actual_projection['members'][self.member]['cells'][self.cell]
        for key in ('precipitation_m','reference_potential_evaporation_m','potential_condensation_m'):
            self.assertEqual(F(cell['annual'][key]['exact']),sum((F(m[key]['exact']) for m in cell['months']),F()))
        self.assertEqual(F(cell['annual']['snow_water_residual_m']['exact']),0)

    def test_warm_cool_calendar_selection_explicit_and_weighted(self):
        cell=self.actual_projection['members'][self.member]['cells'][self.cell]
        for name,months in (('warm',[4,5,6,7,8,9]),('cool',[10,11,12,1,2,3])):
            result=cell['seasonal_summaries'][name]
            self.assertEqual(result['month_ids'],months)
            selected=[m for m in cell['months'] if m['month_id'] in months]
            duration=sum((F(m['duration_seconds']) for m in selected),F())
            self.assertEqual(F(result['duration_seconds']),duration)
            for key in ('wind_east_10m_m_s','wind_north_10m_m_s','mean_scalar_speed_10m_m_s'):
                expected=sum((F(m['air'][key]['exact'])*F(m['duration_seconds']) for m in selected),F())/duration
                self.assertEqual(F(result['duration_weighted_air'][key]['exact']),expected)

    def wind_case(self, vectors, weights):
        exemplar=self.regimes()[0]; output=[]
        for i,((east,north),weight) in enumerate(zip(vectors,weights)):
            row=deepcopy(exemplar);row['regime_id']='synthetic-wind-'+str(i);row['weight']=str(weight)
            air=row['products'][self.cell]['air'];air['wind_east_10m_m_s']=east;air['wind_north_10m_m_s']=north
            air['mean_scalar_speed_10m_m_s']=math.hypot(east,north)
            air['resultant_speed_10m_m_s']=math.hypot(east,north)
            output.append(row)
        return output

    def test_equal_opposite_winds_zero_vector_not_zero_scalar(self):
        result=c.wind_summary(self.wind_case([(8.,0.),(-8.,0.)],[F(1,2),F(1,2)]),self.cell)
        self.assertEqual(result['resultant_speed_10m_m_s'],0.)
        self.assertEqual(F(result['mean_scalar_speed_10m_m_s']['exact']),8)
        self.assertIsNone(result['wind_from_degrees'])
        self.assertEqual(result['wind_direction_status'],'UNDEFINED_ZERO_RESULTANT')

    def test_wind_from_direction_and_weighted_components_oracle(self):
        result=c.wind_summary(self.wind_case([(4.,0.),(0.,-2.)],[F(1,4),F(3,4)]),self.cell)
        self.assertEqual(F(result['wind_east_10m_m_s']['exact']),1)
        self.assertEqual(F(result['wind_north_10m_m_s']['exact']),F(-3,2))
        self.assertAlmostEqual(result['resultant_speed_10m_m_s'],math.sqrt(3.25),places=14)
        self.assertAlmostEqual(result['wind_from_degrees'],math.degrees(math.atan2(-1.,1.5))%360,places=14)
        self.assertEqual(F(result['mean_scalar_speed_10m_m_s']['exact']),F(5,2))

    def test_bad_regime_weights_or_identity_rejected(self):
        for weights in ([F(1,2),F(1,3)],[F(0),F(1)]):
            with self.assertRaises(ValueError):c.wind_summary(self.wind_case([(1.,0.),(1.,0.)],weights),self.cell)
        rows=self.wind_case([(1.,0.),(1.,0.)],[F(1,2),F(1,2)]);rows[1]['regime_id']=rows[0]['regime_id']
        with self.assertRaises(ValueError):c.wind_summary(rows,self.cell)

    def test_negative_or_physically_impossible_child_scalar_speed_rejected(self):
        for scalar in (-2.,1.):
            rows=self.wind_case([(8.,0.),(-8.,0.)],[F(1,2),F(1,2)])
            rows[0]['products'][self.cell]['air']['mean_scalar_speed_10m_m_s']=scalar
            with self.subTest(scalar=scalar),self.assertRaises(ValueError):c.wind_summary(rows,self.cell)

    def test_positive_tiny_vector_cannot_have_exact_zero_scalar_speed(self):
        rows=self.wind_case([(1e-20,0.)],[F(1)])
        rows[0]['products'][self.cell]['air']['mean_scalar_speed_10m_m_s']=0.
        with self.assertRaises(ValueError):c.wind_summary(rows,self.cell)

    def test_unknown_month_preserves_coequal_missing_member_cells(self):
        parent=deepcopy(self.actual_parent)
        cell=self.first(parent);cell.update(status='UNKNOWN',months=None,events=None,reason='explicit missing monthly forcing')
        out=c.project(self.rehash_seasonal(parent),self.expected_source)
        result=out['members'][self.member]['cells'][self.cell]
        self.assertEqual(result['status'],'UNKNOWN');self.assertIsNone(result['annual']);self.assertIsNone(result['events'])
        self.assertEqual(len(out['members']),3)

    def test_source_and_stale_nested_parent_binding_rejected(self):
        with self.assertRaises(ValueError):c.project(self.actual_parent,'0'*64)
        for key in ('seasonal_sha256','soil_result_sha256'):
            parent=deepcopy(self.actual_parent);parent['state'][key]='0'*64
            with self.subTest(key=key),self.assertRaises(ValueError):c.project(parent,self.expected_source)

    def test_event_temperature_or_demand_must_match_month_after_rehash(self):
        for field in ('temperature_c','potential_evaporation_m_s'):
            parent=deepcopy(self.actual_parent)
            self.first(parent)['events'][0][field]+=1
            with self.subTest(field=field),self.assertRaises(ValueError):c.project(self.rehash_seasonal(parent),self.expected_source)

    def test_event_rainmelt_duration_duplicate_mutations_rejected(self):
        for mutate in (lambda cell:cell['events'][0].update(liquid_input_m_s=1.),
                       lambda cell:cell['events'][0].update(duration_seconds='1'),
                       lambda cell:cell['events'].append(deepcopy(cell['events'][0]))):
            parent=deepcopy(self.actual_parent);mutate(self.first(parent))
            with self.assertRaises(ValueError):c.project(self.rehash_seasonal(parent),self.expected_source)

    def test_negative_or_duplicated_snow_flux_cannot_hide_in_ledger(self):
        parent=deepcopy(self.actual_parent);row=self.first(parent)['months'][0]
        row['snow']['ledger']['liquid_to_soil_m']=str(F(row['snow']['ledger']['liquid_to_soil_m'])+F(1))
        with self.assertRaises(ValueError):c.project(self.rehash_seasonal(parent),self.expected_source)

    def test_no_soil_temperature_flood_or_growth_promoted(self):
        for member in self.actual_projection['members'].values():
            for cell in member['cells'].values():
                for month in cell['months']:
                    for key in ('soil_temperature_c','soil_freeze_fraction','river_flow_m3_s','lake_level_m'):
                        self.assertIsNone(month[key])
                self.assertIn('not daily drought',cell['monthly_climatic_support']['meaning'])

    def test_circular_dry_month_index_independent_bruteforce(self):
        for member in self.actual_projection['members'].values():
            for cell in member['cells'].values():
                dry=set(cell['monthly_climatic_support']['strongly_dry_month_ids'])
                lengths=[]
                for start in range(1,13):
                    n=0
                    while n<12 and (start+n-1)%12+1 in dry:n+=1
                    lengths.append(n)
                self.assertEqual(cell['monthly_climatic_support']['longest_circular_strongly_dry_run_months'],max(lengths))

    def test_synthetic_climatic_mask_wrap_and_all_or_none(self):
        # Only a climatic-index oracle: explicit rate overrides are not new R8
        # climate generation, PM-energy validation or evidence of a real season.
        for dry,expected in (({1,12},2),({1,2,11,12},4),(set(range(1,13)),12),(set(),0)):
            parent=deepcopy(self.actual_parent);member=parent['seasonal']['members'][self.member]
            cell=member['cells'][self.cell]
            for month,atmosphere in zip(cell['months'],member['atmosphere']):
                rate=max(1e-8,4*float(F(month['precipitation_m_s']))) if month['month_id'] in dry else 0.
                month['potential_evaporation_m_s']=rate
                for regime in atmosphere['regimes']:
                    regime['products'][self.cell]['demand']['potential_evaporation_m_s']=rate
            for event in cell['events']:
                event['potential_evaporation_m_s']=cell['months'][event['month_id']-1]['potential_evaporation_m_s']
            projected=c.project(self.rehash_seasonal(parent),self.expected_source)['members'][self.member]['cells'][self.cell]
            self.assertEqual(set(projected['monthly_climatic_support']['strongly_dry_month_ids']),dry)
            self.assertEqual(projected['monthly_climatic_support']['longest_circular_strongly_dry_run_months'],expected)

    def test_inputs_unchanged(self):
        self.assertEqual(c.digest(self.actual_parent),c.digest(saved_parent()))


if __name__=='__main__':unittest.main()
