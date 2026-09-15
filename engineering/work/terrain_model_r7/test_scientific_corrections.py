"""R6 physical-law, exact-bound, failed-work and continuation regressions.

All fixtures are tiny synthetic numerical checks, not physical validation.
"""
from copy import deepcopy
from fractions import Fraction as F
import hashlib
import json
import math
from pathlib import Path
import unittest
from unittest.mock import patch

import capture
import continuous_pool
import event_bounds
import event_settling as events
import forced_drying as forced
import hillslope_binding
import r4_io
import shoreline
import shoreline_driver as driver
from shoreline_materials import hillslope_trial
from test_event_settling import initial as settling_initial
from test_forced_drying import convex_case,constant_case
from test_shoreline import native,controls
from test_shoreline_driver import arguments,forced_existing_pool


def rational(record):return F(record['numerator'],record['denominator'])


def bounded(**changes):
    values=dict(liquid=.75,solid=.25,area=1.,qw=45/128,qs=19/128,qo=.5,
                velocity=.125,duration=.25,depth=1/64)
    values.update(changes)
    return event_bounds.no_drying_bound(**values)


class IndependentBoundTests(unittest.TestCase):
    def test_constant_concentration_exact_affine_oracle(self):
        result=bounded()
        # c=1/4 is a literal exact equilibrium; h(t)=1/64-t/32.
        self.assertEqual(result['status'],'PROVED_POSITIVE_DEPTH')
        self.assertEqual(rational(result['minimum_depth_lower_m']),F(1,128))
        self.assertEqual(rational(result['concentration_lower']),F(1,4))
        self.assertEqual(rational(result['concentration_upper']),F(1,4))
        self.assertFalse(result['uses_numerical_trajectory_or_error_estimate'])

    def test_touching_or_beyond_endpoint_is_not_positive_proof(self):
        for duration in (.5,math.nextafter(.5,math.inf),1.):
            with self.subTest(duration=duration):
                self.assertEqual(bounded(duration=duration)['status'],'NOT_PROVED')
        self.assertEqual(bounded(duration=math.nextafter(.5,0.))['status'],'PROVED_POSITIVE_DEPTH')

    def test_declining_concentration_closed_column_bound_is_conservative(self):
        result=bounded(qw=0.,qs=0.,qo=0.,velocity=1.,depth=.3,duration=1.)
        self.assertEqual(result['status'],'PROVED_POSITIVE_DEPTH')
        self.assertEqual(rational(result['concentration_upper']),F(1,4))
        # Settling only reduces c, so actual deposit < initial c*A*T.
        scalar=continuous_pool.advance_pool(.75,.25,1.,0.,0.,0.,1.,1.)
        actual_depth=.3-scalar['deposited_solid_m3']
        self.assertGreater(actual_depth,float(rational(result['minimum_depth_lower_m'])))

    def test_increasing_concentration_root_is_enclosed_by_polynomial_sign(self):
        result=bounded(liquid=.9,solid=.1,qw=.125,qs=.5,qo=0.,velocity=.125,depth=.25)
        c0=F(.1)/(F(.9)+F(.1));hi=rational(result['concentration_upper'])
        polynomial=lambda c:F(.5)-(F(.625)+F(.125))*c+F(.125)*c*c
        self.assertGreater(polynomial(c0),0)
        self.assertLessEqual(polynomial(hi),0)
        self.assertGreaterEqual(hi,c0)
        self.assertLess(hi,1)

    def test_safe_interior_dip_is_estimated_not_promoted(self):
        result=forced.first_event(**convex_case(shallowest_depth_m=.6,shallowest_cell_depths_m=[.6]))
        self.assertEqual(result['status'],'NO_DRYING_ESTIMATED')
        self.assertFalse(result['remaining_interval_completed'])
        self.assertEqual(result['independent_no_drying_certificate']['status'],'NOT_PROVED')
        self.assertNotIn('minimum_certificate',result)
        # The independent Decimal dip oracle is safely positive at h0=.6.
        self.assertGreater(result['minimum_estimate']['conservative_height_lower_m'],0.)
        self.assertTrue(all(p.get('interval_semantics')=='HEURISTIC_NOT_VALIDATED_ENCLOSURE'
                            for p in result['probes'] if p['status']=='PASS'))

    def test_no_event_proof_does_not_depend_on_rk_tolerance(self):
        with patch.object(continuous_pool,'SOLVER_ATOL_M3',.01):
            result=forced.first_event(**constant_case(settling_m_year=0.,mixture_export_m3_year=.4))
        self.assertEqual(result['status'],'NO_DRYING_CERTIFIED')
        self.assertFalse(result['independent_no_drying_certificate']['uses_numerical_trajectory_or_error_estimate'])

    def test_declared_ode_invalid_carrier_or_depth_rejects(self):
        for changes in ({'liquid':0.},{'qw':0.},{'depth':0.},{'area':0.}):
            with self.subTest(changes=changes),self.assertRaises(ValueError):bounded(**changes)


class FailureWorkTests(unittest.TestCase):
    def test_real_resource_failure_does_not_retry_as_depletion(self):
        with patch.object(continuous_pool,'MAX_EVALUATIONS',1):
            with self.assertRaises(forced.ForcedDryingError) as caught:
                forced.first_event(**convex_case())
        self.assertEqual(caught.exception.failure_kind,'RESOURCE_EXHAUSTED')
        self.assertEqual(caught.exception.scalar_calls,2)
        self.assertEqual(caught.exception.scalar_rhs_evaluations,2)

    def test_invalid_error_text_is_not_used_as_phase_taxonomy(self):
        real=continuous_pool.advance_pool
        def injected(*args,**kwargs):
            if args[-1]>0:
                error=continuous_pool.ContinuousPoolError('drying phase depletion evaluation envelope')
                error.evaluations=3
                raise error
            return real(*args,**kwargs)
        with patch.object(continuous_pool,'advance_pool',side_effect=injected):
            with self.assertRaises(forced.ForcedDryingError) as caught:forced.first_event(**convex_case())
        self.assertEqual(caught.exception.failure_kind,'INVALID_INPUT')
        self.assertEqual(caught.exception.scalar_rhs_evaluations,3)
        self.assertEqual(caught.exception.scalar_calls,2)

    def test_real_pure_liquid_domain_and_attempt_resource_differ(self):
        with self.assertRaises(continuous_pool.ContinuousPoolError) as caught:
            continuous_pool.advance_pool(1.,0.,1.,0.,0.,2.,0.,1.)
        self.assertEqual(caught.exception.failure_kind,'PHASE_DOMAIN_FAILURE')
        with patch.object(continuous_pool,'MAX_ATTEMPTS',0):
            with self.assertRaises(continuous_pool.ContinuousPoolError) as caught:
                continuous_pool.advance_pool(.2,.8,1.,.2,0.,0.,1.,4.)
        self.assertEqual(caught.exception.failure_kind,'RESOURCE_EXHAUSTED')

    def test_failed_closed_solve_retains_completed_work_and_input(self):
        state=settling_initial();before=state.as_dict();clock=[0.];calls=[]
        real=events.settling.settle_pool
        def delayed(*a,**k):
            result=real(*a,**k);calls.append(1);clock[0]=121.;return result
        with patch.object(events.time,'monotonic',side_effect=lambda:clock[0]),patch.object(events.settling,'settle_pool',side_effect=delayed):
            with self.assertRaises(ValueError) as caught:
                events.settle_components(state,settling_m_year=1.,elapsed_years=.1)
        self.assertEqual(len(calls),1)
        self.assertEqual(caught.exception.solver_calls,1)
        self.assertEqual(caught.exception.cell_visits,3)
        self.assertEqual(caught.exception.failure_kind,'RESOURCE_EXHAUSTED')
        self.assertEqual(state.as_dict(),before)

    def test_zero_call_or_too_small_cell_allowance_prevents_work(self):
        state=settling_initial()
        for budget in ({'max_solver_calls':0},{'max_cell_visits':2}):
            with self.subTest(budget=budget),patch.object(events.settling,'settle_pool',side_effect=AssertionError('must not execute')):
                with self.assertRaises(events.EventSettlingError) as caught:
                    events.settle_components(state,settling_m_year=1.,elapsed_years=.1,**budget)
                self.assertEqual((caught.exception.solver_calls,caught.exception.cell_visits),(0,0))

    def test_driver_counts_failed_closed_work_once(self):
        state=capture.CaptureState((1,1),(1.,),(0.,),(0.,),(.75,),(.25,))
        kwargs=arguments(1,dt=.01,steps=1);kwargs.update(runoff_m_year=[0.],basin_settling_m_year=.125)
        real=events.settling.settle_pool;calls=[]
        def after_actual(*a,**k):
            real(*a,**k);calls.append(1);raise ValueError('after actual tiny solve')
        with patch.object(events.settling,'settle_pool',side_effect=after_actual):
            with self.assertRaisesRegex(ValueError,'after actual') as caught:driver.advance(state,**kwargs)
        self.assertEqual(calls,[1])
        self.assertEqual(caught.exception.coupling_counts['closed_event_solver_calls'],1)
        self.assertEqual(caught.exception.coupling_counts['accepted_substeps'],0)
        self.assertEqual(caught.exception.last_valid_state,state.as_dict())


class ContinuationTests(unittest.TestCase):
    def test_estimated_no_event_is_not_safety_permission(self):
        state,kwargs=forced_existing_pool(drying=False)
        real=driver._detect_forced_event
        def estimated(*a,**k):
            result=real(*a,**k);result['status']='NO_DRYING_ESTIMATED';return result
        with patch.object(driver,'_detect_forced_event',side_effect=estimated):
            with self.assertRaisesRegex(driver.CouplingError,'NO_DRYING_ESTIMATED') as caught:driver.advance(state,**kwargs)
        self.assertEqual(caught.exception.last_valid_state,state.as_dict())
        self.assertEqual(caught.exception.coupling_counts['accepted_substeps'],0)

    def test_certified_label_without_independent_proof_is_blocked(self):
        state,kwargs=forced_existing_pool(drying=False);real=driver._detect_forced_event
        def stripped(*a,**k):
            result=real(*a,**k);result.pop('independent_no_drying_certificate');return result
        with patch.object(driver,'_detect_forced_event',side_effect=stripped):
            with self.assertRaisesRegex(driver.CouplingError,'BLOCKED_UNCERTIFIED_CONTINUATION') as caught:driver.advance(state,**kwargs)
        self.assertEqual(caught.exception.coupling_counts['accepted_substeps'],0)

    def test_positive_cells_do_not_authorise_negative_zero_margin(self):
        pool={'id':'synthetic','liquid_m3':.75,'suspended_solid_m3':.25}
        tie={'excluded_zero_depth_right_limit_cell_indices':[1]}
        # A positive-cell proof can be valid although a zero-depth fringe dries.
        self.assertEqual(bounded(qw=.1,qs=0.,qo=0.,area=2.,velocity=1.,duration=.01,depth=1.)['status'],'PROVED_POSITIVE_DEPTH')
        with self.assertRaisesRegex(driver.CouplingError,'lacks positive right-limit'):
            driver._activated_margin_invariant(pool,{'qw':.1,'qs':0.,'qo':0.},1.,2.,tie)
        with self.assertRaisesRegex(driver.CouplingError,'overflow activation'):
            driver._activated_margin_invariant(pool,{'qw':1.,'qs':0.,'qo':.1},1.,2.,tie)


class PhysicalBridgeTests(unittest.TestCase):
    def test_nonlinear_hillslope_uses_closed_form_flux_and_preserves_phases(self):
        state=capture.CaptureState((2,2),(1.,)*4,(0.,)*4,(2.,1.,1.,1.),(.5,)*4,(.01,)*4)
        linear,lr=hillslope_trial(state,dx_m=1.,dy_m=1.,diffusivity_m2_year=[.1]*4,dt_years=.1)
        nonlinear,nr=hillslope_trial(state,dx_m=1.,dy_m=1.,diffusivity_m2_year=[.1]*4,dt_years=.1,critical_gradient=[2.]*4)
        # Normal slope 1, transverse face-average .5: norm^2=5/4,
        # denominator=1-(5/4)/4=11/16; each flux .01*16/11.
        self.assertAlmostEqual(nonlinear.bed_solid_m3[0],2-2*.01*16/11,places=14)
        self.assertLess(nonlinear.bed_solid_m3[0],linear.bed_solid_m3[0])
        self.assertEqual(nr['hillslope_law'],'ROERING_NONLINEAR')
        self.assertEqual(nonlinear.liquid_m3,state.liquid_m3)
        self.assertEqual(nonlinear.suspended_solid_m3,state.suspended_solid_m3)
        self.assertEqual(nr['executed_kernel_source'],hillslope_binding.verify())

    def test_nonlinear_critical_domain_cfl_and_zero_diffusivity_validation(self):
        state=capture.CaptureState((2,2),(1.,)*4,(0.,)*4,(2.,1.,1.,1.),(0.,)*4,(0.,)*4)
        for k,critical,dt in ((.1,1.,.1),(1.,2.,1.),(0.,0.,.1)):
            with self.subTest(k=k,critical=critical),self.assertRaises(ValueError):
                hillslope_trial(state,dx_m=1.,dy_m=1.,diffusivity_m2_year=[k]*4,dt_years=dt,critical_gradient=[critical]*4)

    def test_uniform_explicit_runoff_matches_legacy_law(self):
        state=native();kwargs=controls(rock_k_per_year=.01,runoff_m_year=[4.,4.])
        old,oldreport=shoreline.channel_trial(state,**kwargs)
        new,newreport=shoreline.channel_trial(state,**kwargs,erosion_reference_runoff_m_year=4.)
        self.assertEqual(new,old)
        self.assertEqual(oldreport['erosion_forcing_model'],'LEGACY_CONTRIBUTING_AREA_FIXED_RUNOFF_PROXY')
        self.assertEqual(newreport['erosion_reference_runoff_m_year'],4.)

    def test_fourfold_water_doubles_incision_at_fixed_reference(self):
        state=native();kwargs=controls(rock_k_per_year=.01)
        _,one=shoreline.channel_trial(state,**kwargs,erosion_reference_runoff_m_year=1.)
        _,four=shoreline.channel_trial(state,**dict(kwargs,runoff_m_year=[4.,0.]),erosion_reference_runoff_m_year=1.)
        self.assertAlmostEqual(four['rock_debit_solid_m3'][0]/one['rock_debit_solid_m3'][0],2.)

    def test_supplied_liquid_and_solid_are_in_actual_mixed_forcing(self):
        state=native(cover=[.3,0.]);kwargs=controls(rock_k_per_year=.005,sediment_k_per_year=.01,
            settling_m_year=5.,incoming_liquid_m3_year=[300.,0.],incoming_solid_m3_year=[.25,0.])
        _,new=shoreline.channel_trial(state,**kwargs,erosion_reference_runoff_m_year=1.)
        _,old=shoreline.channel_trial(state,**kwargs)
        self.assertEqual(new['water_discharge_m3_year'][0],400.)
        self.assertAlmostEqual(new['rock_debit_solid_m3'][0]/old['rock_debit_solid_m3'][0],2.)
        self.assertAlmostEqual(new['cover_debit_solid_m3'][0]/old['cover_debit_solid_m3'][0],2.)
        self.assertLess(abs(new['solid_volume_residual_m3']),new['solid_volume_tolerance_m3'])

    def test_explicit_reference_never_invents_default_or_accepts_invalid(self):
        for value in (0.,-1.,True,float('inf'),float('nan')):
            with self.subTest(value=value),self.assertRaises(ValueError):
                shoreline.channel_trial(native(),**controls(),erosion_reference_runoff_m_year=value)
        unchanged,report=shoreline.channel_trial(native(),**controls(runoff_m_year=[0.,0.],rock_k_per_year=.01),erosion_reference_runoff_m_year=1.)
        self.assertEqual(unchanged.bedrock_m,native().bedrock_m)
        self.assertEqual(report['rock_debit_solid_m3'],[0.,0.])

    def test_quotient_range_does_not_destroy_representable_intensity(self):
        # Q/ref underflows to zero, while sqrt(Q)/sqrt(ref) is representable.
        state=native(area=[1.,1.]);kwargs=controls(contributing_area_m2=[1.,2.],runoff_m_year=[1e-200,0.],
            rock_k_per_year=1e190,dt_years=.001)
        _,report=shoreline.channel_trial(state,**kwargs,erosion_reference_runoff_m_year=1e200)
        self.assertGreater(report['rock_debit_solid_m3'][0],0.)


class PreservationTests(unittest.TestCase):
    def test_entire_frozen_r5_inventory_and_release_unchanged(self):
        here=Path(__file__).resolve().parent
        manifest=json.loads((here/'R5_PREDECESSOR.json').read_text())
        directory=here/manifest['source_directory']
        self.assertEqual(len(manifest['files']),45)
        self.assertEqual(sorted(p.name for p in directory.iterdir() if p.is_file()),sorted(r['name'] for r in manifest['files']))
        for row in manifest['files']:
            raw=(directory/row['name']).read_bytes()
            self.assertEqual((len(raw),hashlib.sha256(raw).hexdigest()),(row['bytes'],row['sha256']))
        self.assertEqual(hashlib.sha256((here/manifest['receipt_path']).read_bytes()).hexdigest(),manifest['receipt_sha256'])
        self.assertTrue(any(p['name']=='R5/RECEIPT.json' for p in r4_io.verify_dependencies()))

    def test_executed_hillslope_is_exact_repaired_source_not_old_global(self):
        self.assertEqual(Path(hillslope_binding.kernel.__file__).parent.name,'terrain_model_r7')
        self.assertIsNot(hillslope_binding.kernel,r4_io.io)
        self.assertEqual(next(r['sha256'] for r in hillslope_binding.verify() if r['name'].endswith('/hillslope_kernel.py')),
                         '2b003cfdbbf4b59df9a8b731cad57ffb643aabafa86c0cdf9ac2892f60bbad9e')


if __name__=='__main__':unittest.main()
