from dataclasses import replace
import json
import math
import unittest
from unittest.mock import patch

from capture import CaptureState
import shoreline_driver as driver
import shoreline_fixtures
import capture_fixtures


def arguments(n, *, dt=.6, steps=2):
    return dict(steps=steps, dt_years=dt, dx_m=1., dy_m=1., external_outlets=[],
                runoff_m_year=[1.] + [0.]*(n-1), sediment_k_per_year=[0.]*n,
                rock_k_per_year=[0.]*n, cover_scale_m=1., settling_m_year=0.,
                basin_settling_m_year=0., diffusivity_m2_year=[0.]*n, connectivity=4)


def forced_existing_pool(*, ties=False, drying=True):
    if ties:
        state=CaptureState((1,4),(1.,)*4,(.984375,.984375,0.,1.),(0.,)*4,
            (.01171875,.01171875,.75,0.),(.00390625,.00390625,.25,0.))
    else:
        state=CaptureState((1,3),(1.,)*3,(.984375,0.,1.),(0.,)*3,
            (.01171875,.75,0.),(.00390625,.25,0.))
    n=state.size
    kwargs=arguments(n,dt=1. if not ties else .1,steps=1)
    kwargs.update(external_outlets=[n-1],runoff_m_year=[0.]*n,
        basin_settling_m_year=.125 if drying else .01,
        incoming_liquid_m3_year=[.328125]+[0.]*(n-1),
        incoming_solid_m3_year=[.171875]+[0.]*(n-1))
    return state,kwargs


class DriverTests(unittest.TestCase):
    def test_forced_half_year_drying_event_is_blocked_without_commit(self):
        state,kwargs=forced_existing_pool()
        saved=state.as_dict()
        with self.assertRaisesRegex(driver.CouplingError,
                                    'BLOCKED_FORCED_DAUGHTER_COUPLING') as caught:
            driver.advance(state,**kwargs)
        context=caught.exception.context
        self.assertEqual(context['status'],'BLOCKED_FORCED_DAUGHTER_COUPLING')
        self.assertEqual(context['pool_id'],'pool_0000')
        self.assertLessEqual(context['event_bracket']['relative_low_years'],.5)
        self.assertGreaterEqual(context['event_bracket']['relative_high_years'],.5)
        self.assertEqual(context['event_bracket']['simultaneous_cell_indices'],[0])
        self.assertIn('recipient ownership',context['forcing_ownership_gap']['reason'])
        self.assertEqual(context['unchanged_driver_checkpoint'],saved)
        self.assertEqual(caught.exception.last_valid_state,saved)
        self.assertEqual(caught.exception.coupling_counts['accepted_substeps'],0)
        self.assertEqual(caught.exception.coupling_counts['scalar_rhs_evaluations'],48)
        self.assertEqual(state.as_dict(),saved)

    def test_no_drying_certificate_reuses_endpoint_and_replays_exactly(self):
        state,kwargs=forced_existing_pool(drying=False)
        first=driver.advance(state,**kwargs)
        second=driver.advance(state,**kwargs)
        self.assertEqual(first,second)
        _,report=first
        row=report['steps'][0]['pool_intervals'][0]
        certificate=row['forced_drying_certificate']
        self.assertEqual(certificate['status'],'NO_DRYING_CERTIFIED')
        endpoints=[probe for probe in certificate['probes']
                   if probe['status']=='PASS' and probe['time_years']==1.]
        self.assertEqual(len(endpoints),1)
        self.assertEqual(row['continuous_phases'],endpoints[0]['scalar_result'])
        self.assertEqual(report['counts']['scalar_rhs_evaluations'],
                         2*certificate['scalar_rhs_evaluations'])
        self.assertNotIn('wall_seconds',certificate)
        self.assertEqual(report['steps'][0]['stable_recomputations'],2)

    def test_exact_shallowest_tie_is_derived_from_stage_and_all_pool_beds(self):
        state,kwargs=forced_existing_pool(ties=True,drying=False)
        _,report=driver.advance(state,**kwargs)
        certificate=report['steps'][0]['pool_intervals'][0]['forced_drying_certificate']
        tie=certificate['driver_exact_tie_derivation']
        self.assertEqual(tie['cell_indices'],[0,1])
        self.assertEqual(tie['exact_depth'],{'numerator':1,'denominator':64})
        self.assertEqual(tie['all_positive_depth_cell_indices'],[0,1,2])
        self.assertEqual(certificate['shallowest_depth_authority'],
                         'CALLER_SUPPLIED_EXACT_RATIO')

    def test_forced_detector_source_guard_propagates_without_commit(self):
        state,kwargs=forced_existing_pool(drying=False)
        saved=state.as_dict()
        with patch.dict(driver.forced_drying.SOURCE_PINS,
                        {'continuous_pool.py':'0'*64},clear=False):
            with self.assertRaisesRegex(driver.forced_drying.ForcedDryingError,
                                        'source identity mismatch') as caught:
                driver.advance(state,**kwargs)
        self.assertEqual(caught.exception.last_valid_state,saved)
        self.assertEqual(caught.exception.coupling_counts['accepted_substeps'],0)
        self.assertEqual(state.as_dict(),saved)

    def test_positive_exact_activated_margin_uses_separate_area_invariant(self):
        state=CaptureState((1,2),(1.,1.),(0.,1.),(0.,0.),(.75,0.),(.25,0.))
        kwargs=arguments(2,dt=.1,steps=1)
        kwargs.update(runoff_m_year=[0.,0.],basin_settling_m_year=1.,
            incoming_liquid_m3_year=[.0625,0.],
            incoming_solid_m3_year=[.6875,0.])
        final,report=driver.advance(state,**kwargs)
        self.assertGreater(final.liquid_m3[1]+final.suspended_solid_m3[1],0.)
        certificate=report['steps'][0]['pool_intervals'][0]['forced_drying_certificate']
        self.assertEqual(certificate['positive_depth_area_m2'],1.)
        self.assertEqual(certificate['total_wet_area_m2'],2.)
        invariant=certificate['activated_zero_depth_margin_invariant']
        self.assertEqual(invariant['status'],
                         'CERTIFIED_ZERO_MARGIN_NOT_FIRST_LATER_DRYING_EVENT')
        self.assertEqual(invariant['cell_indices'],[1])
        self.assertEqual(invariant['initial_right_depth_rate_m_year'],
                         {'numerator':1,'denominator':8})
        self.assertEqual(invariant['threshold_concentration_polynomial'],
                         {'numerator':-1,'denominator':16})

    def test_continuous_birth_and_two_cell_wetting(self):
        state = CaptureState((1,2), (1.,1.), (0.,1.), (0.,0.), (0.,0.), (0.,0.))
        result, report = driver.advance(state, **arguments(2))
        self.assertAlmostEqual(result.time_years, 1.2)
        self.assertAlmostEqual(result.liquid_m3[0], 1.1, delta=1e-9)
        self.assertAlmostEqual(result.liquid_m3[1], .1, delta=1e-9)
        event = next(e for e in report['events'] if e['kind'] == 'BRACKETED_NATIVE_CONTACT')
        self.assertLessEqual(event['lower_years'], 1.)
        self.assertGreaterEqual(event['upper_years'], 1.)
        self.assertLessEqual(event['width_years'], 1.1e-10)
        self.assertTrue(report['whole_interval_completed'])
        self.assertFalse(report['physical_acceptance'])
        self.assertFalse(any(state.liquid_m3))

    def test_solid_port_counts_towards_wetting_capacity(self):
        state = CaptureState((1,2), (1.,1.), (0.,1.), (0.,0.), (0.,0.), (0.,0.))
        kwargs = arguments(2, dt=.6, steps=2)
        kwargs.update(runoff_m_year=[0.,0.], incoming_liquid_m3_year=[1.,0.], incoming_solid_m3_year=[.1,0.])
        result, report = driver.advance(state, **kwargs)
        event = next(e for e in report['events'] if e['kind'] == 'BRACKETED_NATIVE_CONTACT')
        self.assertLessEqual(event['lower_years'], 1/1.1)
        self.assertGreaterEqual(event['upper_years'], 1/1.1)
        self.assertAlmostEqual(math.fsum(result.liquid_m3), 1.2, delta=1e-12)
        self.assertAlmostEqual(math.fsum(result.suspended_solid_m3), .12, delta=1e-12)
        self.assertAlmostEqual(result.liquid_m3[0]+result.suspended_solid_m3[0], 1.16, delta=1e-9)

    def test_exact_dry_birth_settling_is_continuous_not_initial_dump(self):
        state = CaptureState((1,1), (1.,), (0.,), (0.,), (0.,), (0.,))
        kwargs = arguments(1, dt=1., steps=1)
        kwargs.update(runoff_m_year=[0.], incoming_liquid_m3_year=[1.],
                      incoming_solid_m3_year=[1.], basin_settling_m_year=1.)
        result, report = driver.advance(state, **kwargs)
        s = (math.sqrt(5)-1)/2
        self.assertAlmostEqual(result.liquid_m3[0], 1., delta=1e-12)
        self.assertAlmostEqual(result.suspended_solid_m3[0], s, delta=1e-12)
        self.assertAlmostEqual(result.bed_solid_m3[0], 1-s, delta=1e-12)
        self.assertAlmostEqual(result.bed_m[0]+result.liquid_m3[0]+result.suspended_solid_m3[0], 2., delta=1e-12)

    def test_zero_forcing_lake_at_rest_and_json_restart(self):
        state = CaptureState((1,2), (1.,1.), (0.,1.), (0.,0.), (1.5,.5), (0.,0.))
        kwargs = arguments(2); kwargs['runoff_m_year'] = [0.,0.]
        result, _ = driver.advance(state, **kwargs)
        self.assertEqual(replace(result,time_years=0.), state)
        first, _ = driver.advance(state, **{**kwargs,'steps':1})
        restored = CaptureState(**json.loads(json.dumps(first.as_dict())))
        resumed, _ = driver.advance(restored, **{**kwargs,'steps':1})
        self.assertEqual(resumed,result)

    def test_time_underflow_cannot_report_false_completion(self):
        state = CaptureState((1,1), (1.,), (0.,), (0.,), (0.,), (0.,), time_years=1e20)
        with self.assertRaisesRegex(ValueError, 'represented outer target'):
            driver.advance(state, **arguments(1,dt=1.,steps=1))

    def test_quantised_exterior_deficit_is_logged_not_applied_to_native_wetting(self):
        state = CaptureState((1,2), (1.,1.), (0.,1.), (0.,0.), (.7,0.), (.3,0.))
        pool = {'cell_indices':[0], 'spill':{'spill_m':1.,
                'exact_spill_m':{'numerator':1,'denominator':1}}}
        row = driver._external_boundary_representation(state,pool,1.)
        self.assertEqual(row['capacity_deficit_m3'], 2**-54)
        self.assertEqual(row['early_spill_time_bound_years'], 2**-54)
        self.assertFalse(row['inventories_adjusted'])
        self.assertFalse(row['native_wetting_authorised'])
        with self.assertRaisesRegex(ValueError, 'native contact is not exact'):
            driver.advance(state, **arguments(2,dt=.1,steps=1))
        exterior = arguments(2,dt=.1,steps=1)
        exterior.update(external_outlets=[1],runoff_m_year=[0.,0.],
                        incoming_liquid_m3_year=[1.,0.])
        final, report = driver.advance(state, **exterior)
        represented = report['steps'][0]['pool_intervals'][0]['external_boundary_representation']
        self.assertEqual(represented['closure'],'QUANTISED_EXTERNAL_BOUNDARY_ONLY')
        self.assertEqual(represented['capacity_deficit_m3'],2**-54)
        self.assertEqual(represented['early_spill_time_bound_years'],2**-54)
        self.assertFalse(represented['inventories_adjusted'])
        self.assertAlmostEqual(math.fsum(final.liquid_m3)+math.fsum(final.suspended_solid_m3),
                               math.fsum(state.liquid_m3)+math.fsum(state.suspended_solid_m3),delta=1e-12)

    def test_resting_exact_dry_margin_is_not_activated(self):
        state = CaptureState((1,2), (1.,1.), (0.,1.), (0.,0.), (1.,0.), (0.,0.))
        kwargs = arguments(2,dt=.1,steps=1); kwargs['runoff_m_year']=[0.,0.]
        result, report = driver.advance(state, **kwargs)
        self.assertEqual(replace(result,time_years=0.), state)
        self.assertFalse(report['events'])

    def test_fixed_sill_integrates_export_composition(self):
        state = CaptureState((1,2), (1.,1.), (0.,1.), (0.,0.), (.75,0.), (.25,0.))
        kwargs = arguments(2,dt=.2,steps=5); kwargs['external_outlets']=[1]
        result, report = driver.advance(state, **kwargs)
        self.assertAlmostEqual(result.suspended_solid_m3[0], .25*math.exp(-1), delta=1e-9)
        self.assertAlmostEqual(result.liquid_m3[0], 1-.25*math.exp(-1), delta=1e-9)
        export_s=math.fsum(s['exported_solid_m3'] for s in report['steps'])
        self.assertAlmostEqual(export_s,.25*(1-math.exp(-1)),delta=1e-9)

    def test_driver_retains_independent_daughter_pool_evolution(self):
        recipe = capture_fixtures.split_recipe(1)
        state = CaptureState(**recipe['state'])
        kwargs = arguments(3, dt=.8, steps=1)
        kwargs.update(runoff_m_year=[0.]*3, basin_settling_m_year=1.)
        result, report = driver.advance(state, **kwargs)
        self.assertAlmostEqual(result.suspended_solid_m3[0],.0003738854432090018,delta=1e-12)
        self.assertAlmostEqual(result.suspended_solid_m3[2],.0001497606602290342,delta=1e-12)
        splits=[e for e in report['events'] if e['kind']=='CLOSED_POOL_INTERNAL_EVENT' and e['split']]
        self.assertEqual(len(splits),1)
        self.assertAlmostEqual(splits[0]['absolute_time_years'],.3566679414555507592,delta=1e-9)

    def test_nested_bisection_budget_cannot_be_exceeded_or_commit(self):
        state = CaptureState((1,2), (1.,1.), (0.,1.), (0.,0.), (0.,0.), (0.,0.))
        saved = state.as_dict()
        with patch.object(driver,'MAX_REJECTS',1):
            with self.assertRaisesRegex(driver.CouplingError,'rejection envelope') as caught:
                driver.advance(state, **arguments(2,dt=2.,steps=1))
        self.assertEqual(caught.exception.context['counts']['rejected_proposals'],1)
        self.assertEqual(state.as_dict(),saved)

    def test_failed_trial_exposes_counts_and_unadvanced_checkpoint(self):
        state = CaptureState((1,2), (1.,1.), (0.,1.), (0.,0.), (.7,0.), (.3,0.))
        with self.assertRaises(driver.CouplingError) as caught:
            driver.advance(state, **arguments(2,dt=.1,steps=1))
        self.assertEqual(caught.exception.coupling_counts['trial_calls'],1)
        self.assertEqual(caught.exception.last_valid_state,state.as_dict())
        self.assertEqual(caught.exception.coupling_time_years,0.)

    def test_event_overshoot_cannot_bypass_an_unmodelled_dry_corridor(self):
        state = CaptureState((1,4), (1.,)*4, (0.,2.,1.,0.), (0.,)*4, (0.,)*4, (0.,)*4)
        kwargs = arguments(4,dt=3.,steps=1); kwargs['external_outlets']=[3]
        with self.assertRaisesRegex(driver.CouplingError,'downstream dry-channel') as caught:
            driver.advance(state, **kwargs)
        self.assertEqual(caught.exception.last_valid_state,state.as_dict())
        self.assertFalse(any(state.liquid_m3))


if __name__ == '__main__': unittest.main()
