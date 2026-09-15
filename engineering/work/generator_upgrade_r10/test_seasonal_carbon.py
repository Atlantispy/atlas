"""Actual pinned R7 seasonal continuation and independent carbon/time oracles."""
from copy import deepcopy
from dataclasses import replace
from fractions import Fraction as F
import json
import math
import unittest
from unittest.mock import patch

from . import binding, seasonal_carbon as c

E = 'SYNTHETIC TEST: explicit prescribed seasonal drivers, not Diadem soil or litter calibration'
S = 'SYNTHETIC TEST'
DAYS = (31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)


class SeasonalCarbonTests(unittest.TestCase):
    refinement_products = None

    @classmethod
    def setUpClass(cls):
        cls.bundle = binding.load()
        cls.o = cls.bundle.parent.parent.parent.graph.load('work.generator_upgrade_r7.organic')

    def law(self, **kw):
        values = dict(fast_rate_per_s=.002, slow_rate_per_s=.0005, fast_to_slow_fraction=F(3,10),
            carbon_fraction_dry_matter=F(2,5), reference_temperature_k=300.,
            fast_activation_energy_j_mol=0., slow_activation_energy_j_mol=0., gas_constant_j_mol_k=8.314,
            minimum_temperature_k=270., maximum_temperature_k=330., moisture_curve=((0.,0.), (.5,1.), (1.,1.)),
            redox_factors=(('OXIC',1.,1.), ('ANOXIC',.1,.2)),
            regimes=('AERATED_MINERAL',), evidence=E, source_status=S)
        values.update(kw)
        return self.o.OrganicLaw(**values)

    def initial(self, fast=F(2), slow=F(3), age=F(1000)):
        return self.o.OrganicState('layer-a', 'physical-column-support', fast, slow, age, E, S)

    def calendar(self):
        return c.Calendar('SYNTHETIC_365_ONE_SECOND_DAYS', tuple(F(d) for d in DAYS), F(1), E)

    def forcing(self, dt, **kw):
        values = dict(duration_seconds=dt, fast_litter_carbon_kg_m2_s=F(1,2000),
            slow_litter_carbon_kg_m2_s=F(1,10000), soil_temperature_k=300., water_filled_pore_fraction=.5,
            redox='OXIC', regime='AERATED_MINERAL', climate_state_id='explicit-layer-soil-temperature-scenario',
            water_state_id='actual-water-sample', temperature_evidence=E, litter_evidence=E, evidence=E, source_status=S)
        values.update(kw)
        return self.o.OrganicForcing(**values)

    def events(self, *, split=1, hold='EVENT_START_SAMPLE_HELD', varying=False, **forcing):
        output = []; cursor = F()
        for month, duration in enumerate(DAYS, 1):
            for part in range(split):
                dt = F(duration, split); values = dict(forcing)
                if varying: values['water_filled_pore_fraction'] = float(F(1,5)+F(3,5)*cursor/365)
                sample = cursor if hold == 'EVENT_START_SAMPLE_HELD' else cursor+dt if hold == 'EVENT_END_SAMPLE_HELD' else None
                output.append(c.Event('m%d-%d' % (month, part), month, 'layer-a', 'physical-column-support',
                    self.forcing(dt, **values), hold, sample, E))
                cursor += dt
        return tuple(output)

    def run_case(self, *, initial=None, law=None, events=None, calendar=None, **kw):
        args = dict(numerics=self.o.Numerics(), geometry_sha256='a'*64,
                    source_binding_sha256=self.bundle.source_sha256, scenario_id='synthetic-member-layer',
                    evidence=E, source_status=S)
        args.update(kw)
        return c.run_year(self.o, initial or self.initial(), law or self.law(), calendar or self.calendar(),
                          events or self.events(), **args)

    def test_nonzero_actual_producer_continuation_complete(self):
        output = self.run_case()
        self.assertEqual(output['status'], 'MODELLED_SEASONAL_CARBON_DIAGNOSTIC')
        self.assertEqual((output['completed_events'], output['completed_months']), (12,12))
        self.assertEqual(self.o.state_from_record(output['final_state']).elapsed_seconds, 1365)
        self.assertGreater(F(output['annual']['carbon_kg_m2']['input']), 0)
        self.assertGreater(F(output['annual']['carbon_kg_m2']['exported_carbon_origin']), 0)

    def test_independent_unequal_rate_continuous_litter_closed_form(self):
        output = self.run_case(); final = self.o.state_from_record(output['final_state'])
        a, b, dt, u, v, transfer = .002, .0005, 365., .0005, .0001, .3
        A, B = math.exp(-a*dt), math.exp(-b*dt)
        La, Lb = -math.expm1(-a*dt)/a, -math.expm1(-b*dt)/b
        cross = (A-B)/(b-a)
        fast = 2*A+u*La
        slow = 3*B+v*Lb+transfer*(a*2*cross+u*(Lb-cross))
        exported = 5+(u+v)*dt-fast-slow
        self.assertAlmostEqual(float(final.fast_carbon_kg_m2), fast, places=12)
        self.assertAlmostEqual(float(final.slow_carbon_kg_m2), slow, places=12)
        self.assertAlmostEqual(float(F(output['annual']['carbon_kg_m2']['exported_carbon_origin'])), exported, places=12)

    def test_exact_carbon_and_dry_origin_annual_budget(self):
        output = self.run_case(); carbon = {k:F(v) for k,v in output['annual']['carbon_kg_m2'].items()}
        self.assertEqual(carbon['initial']+carbon['input'], carbon['final']+carbon['exported_carbon_origin'])
        self.assertEqual(carbon['input'], F(365)*F(3,5000))
        dry = {k:F(v) for k,v in output['annual']['dry_origin_kg_m2'].items()}
        self.assertEqual(dry['initial']+dry['input'], dry['final']+dry['decomposed_origin'])
        self.assertEqual(dry['final'], carbon['final']/F(2,5))
        self.assertEqual(carbon['residual'], 0)

    def test_month_fluxes_add_but_stocks_not_repeated(self):
        output = self.run_case()
        for key in ('input', 'exported_carbon_origin'):
            self.assertEqual(F(output['annual']['carbon_kg_m2'][key]), sum((F(m['carbon_kg_m2'][key]) for m in output['months'].values()), F()))
        self.assertEqual(output['annual']['carbon_kg_m2']['initial'], output['months']['1']['carbon_kg_m2']['initial'])
        self.assertEqual(output['annual']['carbon_kg_m2']['final'], output['months']['12']['carbon_kg_m2']['final'])
        for first, second in zip(list(output['months'].values()), list(output['months'].values())[1:]):
            self.assertEqual(first['end_state'], second['initial_state'])

    def test_zero_rates_exact_litter_accumulation(self):
        output = self.run_case(law=self.law(fast_rate_per_s=0., slow_rate_per_s=0.))
        final = self.o.state_from_record(output['final_state'])
        self.assertEqual(final.fast_carbon_kg_m2, F(2)+F(365,2000))
        self.assertEqual(final.slow_carbon_kg_m2, F(3)+F(365,10000))
        self.assertEqual(F(output['annual']['carbon_kg_m2']['exported_carbon_origin']), 0)

    def test_zero_stocks_and_zero_litter_known_zero(self):
        output = self.run_case(initial=self.initial(F(), F()), events=self.events(fast_litter_carbon_kg_m2_s=F(), slow_litter_carbon_kg_m2_s=F()))
        self.assertEqual(output['status'], 'MODELLED_SEASONAL_CARBON_DIAGNOSTIC')
        self.assertEqual(F(output['annual']['carbon_kg_m2']['final']), 0)

    def test_no_geometry_or_water_feedback(self):
        output = self.run_case()
        self.assertEqual(output['geometry_feedback'], 'NOT_APPLIED_DIAGNOSTIC_ONLY')
        self.assertEqual(output['geometry_sha256'], 'a'*64)
        self.assertNotIn('porosity', output); self.assertNotIn('head_m', output)
        self.assertIn('old geometry', output['physical_invalidation'])

    def test_original_organic_age_is_not_month_or_water_clock(self):
        output = self.run_case(initial=self.initial(age=F(777,3)))
        self.assertEqual(F(output['calendar_start_pool_age_seconds']), F(777,3))
        self.assertEqual(F(output['events'][0]['start_seconds_in_year']), 0)
        self.assertEqual(self.o.state_from_record(output['final_state']).elapsed_seconds, F(777,3)+365)

    def test_source_support_and_sample_time_joins(self):
        actual = self.events()
        for broken in (replace(actual[0], layer_id='other'), replace(actual[0], support_id='other'),
                       replace(actual[0], water_sample_seconds_in_year=F(1))):
            with self.assertRaises(ValueError): self.run_case(events=(broken,)+actual[1:])
        self.assertEqual(self.run_case(events=self.events(hold='EVENT_END_SAMPLE_HELD'))['completed_events'],12)
        self.assertEqual(self.run_case(events=self.events(hold='EXPLICIT_INTERVAL_VALUE_HELD'))['completed_events'],12)

    def test_unknown_soil_temperature_preserves_prior_months_and_suffix(self):
        events = list(self.events()); events[4] = replace(events[4], forcing=replace(events[4].forcing, soil_temperature_k=None))
        output = self.run_case(events=tuple(events))
        self.assertEqual(output['status'], 'UNKNOWN'); self.assertEqual(output['completed_months'],4)
        self.assertIn('forcing.soil_temperature_k', output['missing_inputs'])
        self.assertIsNone(output['annual']); self.assertIsNone(output['final_state']); self.assertIsNone(output['checkpoint'])
        self.assertEqual(output['events'][5]['status'], 'NOT_ADVANCED_PRIOR_GAP')
        self.assertIsNone(output['months']['5']['carbon_kg_m2'])

    def test_missing_litter_wfps_redox_regime_and_hold_never_inferred(self):
        for key, value in (('fast_litter_carbon_kg_m2_s',None), ('slow_litter_carbon_kg_m2_s',None),
                           ('water_filled_pore_fraction',None), ('redox','UNKNOWN'), ('regime','UNKNOWN')):
            output = self.run_case(events=self.events(**{key:value}))
            self.assertEqual(output['status'],'UNKNOWN'); self.assertEqual(output['completed_events'],0)
            self.assertIn('forcing.'+key, output['missing_inputs'])
        output = self.run_case(events=self.events(hold='UNKNOWN'))
        self.assertIn('moisture_hold',output['missing_inputs'])

    def test_unknown_law_or_initial_source_does_not_use_numeric_values(self):
        for kw in ({'law':self.law(fast_rate_per_s=None)},
                   {'initial':replace(self.initial(),source_status='CONFLICT')}, {'source_status':'INCOMPLETE'}):
            output=self.run_case(**kw)
            self.assertEqual(output['status'],'UNKNOWN'); self.assertEqual(output['completed_events'],0)

    def test_outside_regime_temperature_or_redox_not_zero_decomposition(self):
        for kw in ({'soil_temperature_k':400.}, {'regime':'ORGANIC_DOMINATED'}):
            output=self.run_case(events=self.events(**kw))
            self.assertEqual(output['status'],'OUTSIDE_REGIME'); self.assertIsNone(output['annual'])
        output=self.run_case(law=self.law(redox_factors=(('OXIC',1.,1.),)), events=self.events(redox='ANOXIC'))
        self.assertEqual(output['status'],'OUTSIDE_REGIME')

    def test_actual_numerical_regime_guard_preserved(self):
        output=self.run_case(numerics=self.o.Numerics(max_rate_duration=.00001))
        self.assertEqual(output['status'],'NUMERICAL_FAILURE'); self.assertIsNone(output['final_state'])
        self.assertIn('rate-duration',output['reason'])
        self.assertEqual(output['events'][0]['producer_result']['status'],'NUMERICAL_FAILURE')
        self.assertIsNone(output['events'][0]['producer_result']['state'])

    def test_partial_month_never_reported_complete(self):
        ev=list(self.events(split=2)); ev[1]=replace(ev[1],forcing=replace(ev[1].forcing,soil_temperature_k=None))
        output=self.run_case(events=tuple(ev))
        self.assertEqual(output['completed_events'],1); self.assertEqual(output['completed_months'],0)
        self.assertIsNone(output['months']['1']['end_state'])

    def test_actual_continuation_restart_matches_full_result(self):
        full=self.run_case(); stopped=self.run_case(stop_after=5)
        self.assertEqual(stopped['status'],'STOPPED'); self.assertIsNone(stopped['annual'])
        resumed=self.run_case(resume=json.loads(json.dumps(stopped['checkpoint'])))
        self.assertEqual(full,resumed)

    def test_zero_cursor_restart(self):
        stopped=self.run_case(stop_after=0)
        self.assertEqual(stopped['completed_events'],0)
        self.assertEqual(self.run_case(resume=stopped['checkpoint']),self.run_case())

    def test_checkpoint_source_geometry_scenario_or_driver_change_rejected(self):
        saved=self.run_case(stop_after=3)['checkpoint']
        for kw in ({'source_binding_sha256':'b'*64}, {'geometry_sha256':'b'*64}, {'scenario_id':'another'},
                   {'events':self.events(fast_litter_carbon_kg_m2_s=F(1,1000))}):
            with self.assertRaises(ValueError): self.run_case(resume=saved,**kw)

    def test_rehashed_forged_checkpoint_state_rejected_by_actual_replay(self):
        saved=deepcopy(self.run_case(stop_after=3)['checkpoint'])
        saved['state']['fast_carbon_kg_m2']=[0,1]
        saved['checkpoint_sha256']=c.digest({k:v for k,v in saved.items() if k!='checkpoint_sha256'})
        with self.assertRaisesRegex(ValueError,'actual accepted prefix'): self.run_case(resume=saved)

    def test_checkpoint_unknown_causal_prefix_cannot_restore(self):
        saved=self.run_case(stop_after=3)['checkpoint']
        with self.assertRaises(ValueError): self.run_case(resume=saved,stop_after=2)

    def test_schema_clock_and_identity_mutations_reject(self):
        original=self.events()
        for ev in (original[:-1],original[1:]+original[:1],(original[0],)+original):
            with self.assertRaises(ValueError):self.run_case(events=ev)
        with self.assertRaises(ValueError):c.Calendar('wrong',(F(1),)*12,F(1),E)
        for bad in (True,float('nan'),-1):
            with self.assertRaises(ValueError):replace(self.calendar(),day_seconds=bad)
        with self.assertRaises(ValueError):self.run_case(stop_after=True)

    def test_returned_false_pass_carbon_dry_and_clock_rejected(self):
        original=self.o.advance_layer
        for mode in ('carbon','dry','clock'):
            def wrong(*args,**kwargs):
                result=deepcopy(original(*args,**kwargs))
                if mode=='carbon':result['carbon']['input_kg_m2']+=1
                elif mode=='dry':result['organic_dry_matter']['final_kg_m2']+=1
                else:result['state']=replace(result['state'],elapsed_seconds=result['state'].elapsed_seconds+1)
                return result
            with patch.object(self.o,'advance_layer',side_effect=wrong),self.assertRaises(ValueError):self.run_case()

    def test_constant_driver_subdivision_preserves_solution(self):
        full=self.run_case(); split=self.run_case(events=self.events(split=2))
        a=self.o.state_from_record(full['final_state']);b=self.o.state_from_record(split['final_state'])
        self.assertEqual(a.elapsed_seconds,b.elapsed_seconds)
        self.assertAlmostEqual(float(a.fast_carbon_kg_m2),float(b.fast_carbon_kg_m2),places=12)
        self.assertAlmostEqual(float(a.slow_carbon_kg_m2),float(b.slow_carbon_kg_m2),places=12)

    def test_varying_wfps_left_hold_first_order_independent_oracle(self):
        law=self.law(fast_rate_per_s=.001,slow_rate_per_s=0.,fast_to_slow_fraction=F(),moisture_curve=((0.,0.),(1.,1.)))
        exact=2*math.exp(-.001*(.2*365+.6*365/2))
        errors=[];observed=[]
        for split in (1,2,4):
            out=self.run_case(initial=self.initial(F(2),F()),law=law,
                events=self.events(split=split,varying=True,fast_litter_carbon_kg_m2_s=F(),slow_litter_carbon_kg_m2_s=F()))
            self.assertEqual(out['status'],'MODELLED_SEASONAL_CARBON_DIAGNOSTIC')
            value=float(self.o.state_from_record(out['final_state']).fast_carbon_kg_m2)
            errors.append(abs(value-exact));observed.append(value)
        ratios=[errors[i]/errors[i+1] for i in (0,1)]
        self.assertTrue(all(1.95<ratio<2.05 for ratio in ratios),ratios)
        self.__class__.refinement_products={'scope':'synthetic fixed-column first-order left-held WFPS; analytic scalar time-varying decay',
            'subdivisions_per_month':[1,2,4],'independent_exact_fast_carbon_kg_m2':exact,
            'actual_fast_carbon_kg_m2':observed,'absolute_errors_kg_m2':errors,'error_ratios':ratios,
            'predeclared_first_order_band':[1.95,2.05]}

    def test_input_objects_unchanged_and_plain_output(self):
        state=self.initial();law=self.law();events=self.events();before=c.digest((state,law,events))
        output=self.run_case(initial=state,law=law,events=events)
        self.assertEqual(before,c.digest((state,law,events)))
        self.assertEqual(output,json.loads(json.dumps(output,allow_nan=False)))
        self.assertEqual(output['inputs_sha256'],c.digest(output['inputs']))


if __name__=='__main__':unittest.main()
