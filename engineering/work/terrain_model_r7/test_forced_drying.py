"""Independent numerical and fail-closed tests for the first-event solver."""
from copy import deepcopy
from decimal import Decimal, getcontext
import hashlib
import json
import math
from pathlib import Path
import unittest
from unittest.mock import patch

import continuous_pool
import forced_drying as f


def constant_case(**changes):
    values=dict(liquid_m3=.8,suspended_solid_m3=.2,total_wet_area_m2=1.,
        shallowest_depth_m=.025,shallowest_cell_indices=[3],
        shallowest_cell_depths_m=[.025],native_cell_count=10,
        liquid_input_m3_year=.4,
        solid_input_m3_year=.14,mixture_export_m3_year=.55,
        settling_m_year=.2,duration_years=1.)
    values.update(changes)
    return values


def convex_case(**changes):
    values=dict(liquid_m3=.2,suspended_solid_m3=.8,total_wet_area_m2=1.,
        shallowest_depth_m=.1,shallowest_cell_indices=[0],
        shallowest_cell_depths_m=[.1],native_cell_count=2,
        liquid_input_m3_year=.2,
        solid_input_m3_year=0.,mixture_export_m3_year=0.,
        settling_m_year=1.,duration_years=4.)
    values.update(changes)
    return values


def stripped(value):
    value=deepcopy(value);value.pop('wall_seconds',None)
    return value


class OracleTests(unittest.TestCase):
    def test_constant_concentration_event_and_phase_oracle(self):
        result=f.first_event(**constant_case())
        self.assertEqual(result['status'],'FIRST_DRYING_ESTIMATED')
        self.assertFalse(result['remaining_interval_completed'])
        event=result['event']
        self.assertLess(event['low']['time_years'],.5)
        self.assertGreater(event['high']['time_years'],.5)
        self.assertLessEqual(event['width_years'],1.1e-10)
        exact=continuous_pool.advance_pool(.8,.2,1.,.4,.14,.55,.2,.5)
        for name,expected in (('liquid_m3',.78),('suspended_solid_m3',.195),
                              ('deposited_solid_m3',.02),('exported_liquid_m3',.22),
                              ('exported_suspended_solid_m3',.055)):
            self.assertAlmostEqual(exact[name],expected,delta=2e-12)
        self.assertEqual(result['remaining_interval_status'],'BLOCKED_FORCED_DAUGHTER_COUPLING')

    def test_convex_interior_dip_hidden_by_positive_endpoint(self):
        result=f.first_event(**convex_case())
        oracle=Decimal('0.1753579621396637040154925268163027118712753684757623')
        self.assertEqual(result['status'],'FIRST_DRYING_ESTIMATED')
        self.assertLessEqual(Decimal.from_float(result['event']['low']['time_years']),oracle)
        self.assertGreaterEqual(Decimal.from_float(result['event']['high']['time_years']),oracle)
        endpoint=next(row for row in result['probes'] if row.get('time_years')==4.)
        self.assertGreater(endpoint['height_lower_m'],.103283188-2e-9)
        self.assertEqual(result['mathematical_branch'],'DECREASING_CONCENTRATION')
        self.assertLess(result['event']['width_years'],1.4e-10)
        self.assertLessEqual(result['scalar_calls'],128)
        self.assertLessEqual(result['scalar_rhs_evaluations'],1_048_576)

    def test_deterministic_replay_excluding_measured_wall(self):
        first=f.first_event(**constant_case())
        second=f.first_event(**constant_case())
        self.assertEqual(stripped(first),stripped(second))

    def test_exact_ties_are_all_retained_without_lowest_id_rule(self):
        result=f.first_event(**constant_case(shallowest_cell_indices=[7,2],
            shallowest_cell_depths_m=[.025,.025]))
        self.assertEqual(result['event']['simultaneous_cell_indices'],[7,2])
        with self.assertRaisesRegex(f.ForcedDryingError,'tie is not exact'):
            f.first_event(**constant_case(shallowest_cell_indices=[7,2],
                shallowest_cell_depths_m=[.025,math.nextafter(.025,math.inf)]))


class BranchTests(unittest.TestCase):
    def test_zero_settling_affine_no_event(self):
        result=f.first_event(**constant_case(settling_m_year=0.,mixture_export_m3_year=.4))
        self.assertEqual(result['status'],'NO_DRYING_CERTIFIED')
        self.assertEqual(result['independent_no_drying_certificate']['status'],'PROVED_POSITIVE_DEPTH')

    def test_unforced_equilibrium_and_concave_positive_endpoint(self):
        unforced=f.first_event(**constant_case(liquid_input_m3_year=0.,solid_input_m3_year=0.,
            mixture_export_m3_year=0.,settling_m_year=0.))
        self.assertEqual(unforced['status'],'NO_DRYING_CERTIFIED')
        concave=f.first_event(**constant_case(liquid_input_m3_year=.1,solid_input_m3_year=.9,
            mixture_export_m3_year=0.,settling_m_year=.2))
        self.assertEqual(concave['mathematical_branch'],'INCREASING_CONCENTRATION')
        self.assertEqual(concave['status'],'NO_DRYING_CERTIFIED')

    def test_convex_nonnegative_initial_slope_no_event(self):
        result=f.first_event(**convex_case(liquid_input_m3_year=2.,duration_years=.5))
        self.assertEqual(result['status'],'NO_DRYING_CERTIFIED')
        self.assertEqual(result['independent_no_drying_certificate']['status'],'PROVED_POSITIVE_DEPTH')

    def test_phase_failure_is_not_relabelled_drying(self):
        real=continuous_pool.advance_pool
        def fail_after_zero(*args):
            if args[-1] > 0:raise continuous_pool.ContinuousPoolError('synthetic phase depletion',failure_kind='PHASE_DOMAIN_FAILURE')
            return real(*args)
        with patch.object(f.continuous_pool,'advance_pool',side_effect=fail_after_zero):
            result=f.first_event(**constant_case())
        self.assertEqual(result['status'],'BLOCKED_PHASE_DEPLETION')
        self.assertNotIn('event',result)
        self.assertEqual(result['scalar_calls'],2)
        self.assertEqual(result['source_rechecks'],7)

    def test_counted_pure_liquid_limit_can_bracket_earlier_cell_event(self):
        result=f.first_event(**constant_case(liquid_m3=1.,suspended_solid_m3=0.,
            shallowest_depth_m=.1,shallowest_cell_depths_m=[.1],
            liquid_input_m3_year=0.,solid_input_m3_year=0.,
            mixture_export_m3_year=2.,settling_m_year=0.))
        self.assertEqual(result['status'],'FIRST_DRYING_ESTIMATED')
        self.assertLessEqual(result['event']['low']['time_years'],.05)
        self.assertGreaterEqual(result['event']['high']['time_years'],.05)
        failures=[row for row in result['probes'] if row['status']!='PASS']
        self.assertTrue(failures)
        self.assertTrue(all(row['failed_rhs_evaluations_counted'] for row in failures))

    def test_known_failed_rhs_work_is_counted_and_enforced(self):
        real=continuous_pool.advance_pool
        def counted_failure(*args, **kwargs):
            if args[-1] == 0:return real(*args, **kwargs)
            exc=continuous_pool.ContinuousPoolError('counted synthetic failure')
            exc.evaluations=5
            raise exc
        with patch.object(f.continuous_pool,'advance_pool',side_effect=counted_failure):
            with self.assertRaisesRegex(f.ForcedDryingError,'evaluation envelope'):
                f.first_event(**constant_case(max_scalar_evaluations=4))

    def test_real_scalar_failure_work_is_charged_and_bounded(self):
        with patch.object(f.continuous_pool,'MAX_EVALUATIONS',1):
            with self.assertRaises(f.ForcedDryingError) as caught:
                f.first_event(**convex_case())
            self.assertEqual(caught.exception.failure_kind,'RESOURCE_EXHAUSTED')
            self.assertEqual(caught.exception.scalar_calls,2)
            self.assertEqual(caught.exception.scalar_rhs_evaluations,2)
            with self.assertRaisesRegex(f.ForcedDryingError,'evaluation envelope'):
                f.first_event(**convex_case(max_scalar_evaluations=1))

    def test_numerical_sign_band_fails_closed(self):
        with patch.object(f.continuous_pool,'SOLVER_ATOL_M3',.01):
            result=f.first_event(**constant_case())
        self.assertEqual(result['status'],'BLOCKED_NUMERICAL_EVENT_SIGN')

    def test_exact_mock_grazing_is_named_and_not_crossed(self):
        def grazing(w,s,a,qw,qs,qo,v,t):
            deposited=.75*t-.25*t*t
            concentration=.75-.5*t
            row={'status':'PASS_FIXED_WET_SET_NUMERICAL_REFERENCE','method':'EXACT_TEST',
                 'liquid_m3':1-concentration,'suspended_solid_m3':concentration,
                 'deposited_solid_m3':deposited,'exported_liquid_m3':0.,
                 'exported_suspended_solid_m3':0.,'imported_liquid_m3':qw*t,
                 'imported_suspended_solid_m3':0.,'evaluations':0,'elapsed_years':t,
                 'ledgers':{}}
            return row
        request=convex_case(liquid_m3=.25,suspended_solid_m3=.75,
            shallowest_depth_m=.0625,shallowest_cell_depths_m=[.0625],
            liquid_input_m3_year=.5,duration_years=1.)
        with patch.object(f.continuous_pool,'advance_pool',side_effect=grazing):
            result=f.first_event(**request)
        self.assertEqual(result['status'],'BLOCKED_GRAZING_TANGENT',result)

    def test_endpoint_derivative_straddle_is_not_resolved_by_centre(self):
        def near_stationary(w,s,a,qw,qs,qo,v,t):
            ww,ss=(w,s) if t == 0 else (.8,.2)
            return {'status':'PASS_FIXED_WET_SET_NUMERICAL_REFERENCE',
                'method':'POSITIVE_STAGE_RK4_STEP_DOUBLING','liquid_m3':ww,
                'suspended_solid_m3':ss,'deposited_solid_m3':0.,
                'exported_liquid_m3':0.,'exported_suspended_solid_m3':0.,
                'imported_liquid_m3':qw*t,'imported_suspended_solid_m3':qs*t,
                'evaluations':8,'elapsed_years':t,'ledgers':{}}
        with patch.object(f.continuous_pool,'advance_pool',side_effect=near_stationary):
            result=f.first_event(**convex_case())
        self.assertEqual(result['status'],'BLOCKED_NUMERICAL_EVENT_SIGN',result)
        self.assertIn('derivative band',result['reason'])
        self.assertEqual(result['scalar_calls'],2)

    def test_exact_supplied_product_controls_branch_sign(self):
        result=f.first_event(liquid_m3=1.,suspended_solid_m3=1.,
            total_wet_area_m2=.9999999999999999,shallowest_depth_m=1.,
            shallowest_cell_indices=[0],shallowest_cell_depths_m=[1.],
            native_cell_count=1,liquid_input_m3_year=8.900295434028806e-308,
            solid_input_m3_year=8.900295434028808e-308,
            mixture_export_m3_year=0.,settling_m_year=4e-323,duration_years=0.)
        self.assertEqual(result['mathematical_branch'],'INCREASING_CONCENTRATION')
        self.assertEqual(result['initial_polynomial_sign'],1)

    def test_exact_affine_height_avoids_rounded_false_event(self):
        depth=90.58904361152055
        area=.015353336695016265
        result=f.first_event(liquid_m3=2*depth*area,suspended_solid_m3=0.,
            total_wet_area_m2=area,shallowest_depth_m=depth,
            shallowest_cell_indices=[0],shallowest_cell_depths_m=[depth],
            native_cell_count=1,liquid_input_m3_year=0.,solid_input_m3_year=0.,
            mixture_export_m3_year=4.834299689525642,settling_m_year=0.,
            duration_years=.2877033234949614)
        self.assertEqual(result['status'],'NO_DRYING_CERTIFIED',result)
        final=result['minimum_estimate']['final']
        self.assertGreater(final['height_lower_m'],0.)


class ScopeAndSafetyTests(unittest.TestCase):
    def test_post_event_schedule_is_rejected_until_hash_bound(self):
        for schedule in ({'liquid_input_m3_year':.1,'solid_input_m3_year':0.,
                          'mixture_export_m3_year':0.},
                         {'liquid_input_m3_year':0.,'solid_input_m3_year':0.,
                          'mixture_export_m3_year':0.}):
            with self.subTest(schedule=schedule),self.assertRaisesRegex(
                    f.ForcedDryingError,'hash-bound piecewise'):
                f.first_event(**constant_case(post_event_schedule=schedule))

    def test_only_constant_zero_forcing_allows_closed_daughter_label(self):
        zero=f.first_event(**constant_case(liquid_input_m3_year=0.,
            solid_input_m3_year=0.,mixture_export_m3_year=0.))
        self.assertEqual(zero['status'],'FIRST_DRYING_ESTIMATED')
        self.assertEqual(zero['remaining_interval_status'],
                         'CLOSED_DAUGHTER_SETTLING_AVAILABLE_NOT_EXECUTED')
        self.assertFalse(zero['daughter_geometry_solved'])

    def test_unrepresentable_absolute_time_and_zero_duration(self):
        result=f.first_event(**constant_case(start_time_years=1e300,duration_years=1.))
        self.assertEqual(result['status'],'BLOCKED_UNREPRESENTABLE_EVENT')
        zero=f.first_event(**constant_case(duration_years=0.))
        self.assertEqual(zero['status'],'NO_DRYING_CERTIFIED')
        self.assertEqual(zero['scalar_calls'],1)
        local=f.first_event(**constant_case(start_time_years=1e16,duration_years=4.))
        self.assertEqual(local['status'],'BLOCKED_UNREPRESENTABLE_EVENT',local)
        self.assertIn('absolute binary64',local['reason'])

    def test_resource_envelopes_and_invalid_scalars_reject(self):
        with self.assertRaisesRegex(f.ForcedDryingError,'scalar-call'):
            f.first_event(**constant_case(max_scalar_calls=1))
        for change in ({'wall_seconds':61.},{'max_scalar_evaluations':1_048_577},
                       {'liquid_m3':True},{'duration_years':math.nan},
                       {'shallowest_depth_m':2.},{'native_cell_count':1_000_000},
                       {'native_cell_count':3}):
            with self.subTest(change=change),self.assertRaises(f.ForcedDryingError):
                f.first_event(**constant_case(**change))
        with self.assertRaisesRegex(f.ForcedDryingError,'product overflow'):
            f.first_event(**constant_case(total_wet_area_m2=1e308,
                shallowest_depth_m=1e-309,shallowest_cell_depths_m=[1e-309],
                settling_m_year=1e308))
        with self.assertRaisesRegex(f.ForcedDryingError,'product overflow/underflow'):
            f.first_event(**constant_case(total_wet_area_m2=.1,
                shallowest_depth_m=.01,shallowest_cell_depths_m=[.01],
                settling_m_year=5e-324))
        with self.assertRaisesRegex(f.ForcedDryingError,'equilibrium underflows'):
            f.first_event(**constant_case(liquid_input_m3_year=1.,
                solid_input_m3_year=5e-324,settling_m_year=1.))

    def test_tie_and_schedule_inventory_fail_closed(self):
        for change in ({'shallowest_cell_indices':[1,1],'shallowest_cell_depths_m':[.025,.025]},
                       {'shallowest_cell_indices':[True]},
                       {'post_event_schedule':{'liquid_input_m3_year':0.}}):
            with self.subTest(change=change),self.assertRaises(f.ForcedDryingError):
                f.first_event(**constant_case(**change))

    def test_native_count_and_external_tie_precondition_are_reported(self):
        result=f.first_event(**constant_case())
        self.assertEqual(result['native_cell_count'],10)
        self.assertEqual(result['resource_bounds']['native_cell_count_enforced'],10)
        self.assertEqual(result['resource_bounds']['maximum_native_cells'],4096)
        self.assertIn('CALLER_SUPPLIED',result['shallowest_tie_certificate'])

    def test_exact_depth_ratio_is_authoritative_without_float_substitution(self):
        result=f.first_event(**constant_case(duration_years=0.,
            shallowest_depth_ratio={'numerator':1,'denominator':40}))
        self.assertEqual(result['shallowest_depth_exact'],{'numerator':1,'denominator':40})
        self.assertEqual(result['shallowest_depth_authority'],'CALLER_SUPPLIED_EXACT_RATIO')
        with self.assertRaisesRegex(f.ForcedDryingError,'does not match exact ratio'):
            f.first_event(**constant_case(duration_years=0.,
                shallowest_depth_ratio={'numerator':1,'denominator':41}))

    def test_positive_depth_area_is_distinct_from_total_margin_area(self):
        request=dict(liquid_m3=.75,suspended_solid_m3=.25,
            total_wet_area_m2=2.,positive_depth_area_m2=1.,
            shallowest_depth_m=1.,shallowest_depth_ratio={'numerator':1,'denominator':1},
            shallowest_cell_indices=[0],shallowest_cell_depths_m=[1.],
            native_cell_count=2,liquid_input_m3_year=.0625,
            solid_input_m3_year=.6875,mixture_export_m3_year=0.,
            settling_m_year=1.,duration_years=0.)
        result=f.first_event(**request)
        self.assertEqual(result['status'],'NO_DRYING_CERTIFIED')
        self.assertEqual(result['positive_depth_area_m2'],1.)
        without=dict(request);without.pop('positive_depth_area_m2')
        with self.assertRaisesRegex(f.ForcedDryingError,'inconsistent'):
            f.first_event(**without)
        for area in (0.,True,2.0000000000000004):
            with self.subTest(area=area),self.assertRaises(f.ForcedDryingError):
                f.first_event(**{**request,'positive_depth_area_m2':area})

    def test_every_probe_restarts_same_checkpoint(self):
        result=f.first_event(**constant_case())
        for row in result['probes']:
            if row['status']=='PASS':
                scalar=row['scalar_result'];t=row['time_years']
                self.assertEqual(scalar['elapsed_years'],t)
                self.assertAlmostEqual(scalar['imported_liquid_m3'],.4*t,delta=2e-15)
                self.assertAlmostEqual(scalar['imported_suspended_solid_m3'],.14*t,delta=2e-15)
        self.assertEqual(result['source_rechecks'],2*result['scalar_calls']+3)
        self.assertEqual([row['name'] for row in result['source_identity']],
                         ['continuous_pool.py','event_bounds.py','FORCED_DRYING_DESIGN.md','forced_drying.py'])

    def test_bound_source_drift_during_scalar_call_fails_closed(self):
        real_read=Path.read_bytes
        target=(Path(f.__file__).parent/'continuous_pool.py').resolve()
        seen={'target':0}
        def drifting(path):
            data=real_read(path)
            if path.resolve() == target:
                seen['target']+=1
                if seen['target'] == 4:
                    return data+b'\n# synthetic drift\n'
            return data
        with patch.object(Path,'read_bytes',new=drifting):
            with self.assertRaisesRegex(f.ForcedDryingError,'source identity mismatch'):
                f.first_event(**constant_case(duration_years=0.))

    def test_source_drift_activated_during_result_processing_is_caught(self):
        real_read=Path.read_bytes
        real_advance=f.continuous_pool.advance_pool
        target=(Path(f.__file__).parent/'continuous_pool.py').resolve()
        active={'value':False}
        class ActivatingResult(dict):
            def __getitem__(self,key):
                value=super().__getitem__(key)
                if key == 'method':active['value']=True
                return value
        def result(*args):
            return ActivatingResult(real_advance(*args))
        def drifting(path):
            data=real_read(path)
            return data+b'\n# synthetic processing drift\n' if (
                active['value'] and path.resolve() == target) else data
        with patch.object(f.continuous_pool,'advance_pool',side_effect=result), \
             patch.object(Path,'read_bytes',new=drifting):
            with self.assertRaisesRegex(f.ForcedDryingError,'source identity mismatch'):
                f.first_event(**constant_case(duration_years=0.))

    def test_r3_numerical_source_is_unchanged(self):
        source=Path(__file__).parent.parent/'terrain_model_r3'/'phase_storage.py'
        before=hashlib.sha256(source.read_bytes()).hexdigest()
        f.first_event(**constant_case())
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(),before)


if __name__=='__main__':unittest.main()
