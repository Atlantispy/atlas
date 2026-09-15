"""Verifier logic and tiny synthetic integration; no retained full-case run."""
from copy import deepcopy
from dataclasses import replace
import math
import unittest
from unittest.mock import patch

import shoreline_verification as v


def tiny_prepared():
    return {'initial_state':v.driver.capture.CaptureState((1,1),(1.,),(0.,),(0.,),(0.,),(0.,)),
            'grid':{'rows':1,'cols':1,'dx_m':1.,'dy_m':1.},
            'forcing':{'external_outlets':[],'runoff_m_year':[1.],
                       'sediment_k_per_year':[0.],'rock_k_per_year':[0.],
                       'cover_scale_m':1.,'settling_m_year':0.,'diffusivity_m2_year':[0.]},
            'basin_settling_m_year':0.,'coupled_duration_years':.8,
            'soil_dissolved_rock_export_kg':0.,'physical_acceptance':False,'production_authorised':False}


def cases_with_errors(errors):
    rows = []
    for index,error in enumerate(errors):
        rows.append({'status':'PASS','dt_years':.1/(2**index),
                     'final_state':{key:[error,2*error] for key,unit in v.FIELDS.values()}})
    return rows


def recipient_case(dt, destination=0):
    return {'status':'PASS','dt_years':dt,'events':[],
            'recipient_intervals':[{'from_years':0.,'to_years':.8,'destinations':['POOL'],
                                   'destination_cell_indices':[destination],
                                   'pools':[{'id':0,'cell_indices':[0]}],'pool_cells':[[0]],'ports':[]}]}


class MetricTests(unittest.TestCase):
    def certificate(self,adjustment=0.,bound=0.):
        exact=v.Fraction(adjustment)
        return {'records':[{'routing_position':0,'pool_id':0,'exact_capacity_matched':True,
                 'adjustment_liquid_m3':adjustment,'adjustment_suspended_solid_m3':0.,
                 'exact_adjustment':{'numerator':exact.numerator,'denominator':exact.denominator},
                 'arithmetic_bound_m3':bound,'cell_offset':0 if adjustment else None,
                 'physical_transfer':False,'adjustment_liquid_bound_m3':bound,
                 'adjustment_suspended_solid_bound_m3':bound,'canonical_anchor':'liquid',
                 'canonical_remainder_bound_m3':bound,
                 'cell_adjustments':([{'phase':'liquid','cell_offset':0,'before_m3':.25,
                                      'after_m3':.25+adjustment,'adjustment_m3':adjustment}] if adjustment else [])}],
                'liquid_adjustment_m3':adjustment,'suspended_solid_adjustment_m3':0.,
                'liquid_adjustment_bound_m3':bound,'suspended_solid_adjustment_bound_m3':bound,
                'arithmetic_bound_m3':bound,'physical_transfer':False}

    def test_phase_representation_records_are_disclosed_and_strict(self):
        report=v.representation_summary([{'phase_representation':self.certificate(2**-54,2**-53)}])
        self.assertEqual(report['liquid_adjustment_m3'],2**-54)
        self.assertFalse(report['physical_transfer'])
        self.assertEqual(report['records'][0]['accepted_step_index'],0)
        with self.assertRaises(v.VerificationError):v.representation_summary([{}])
        for mutation in ('physical','bound','exact','aggregate','aggregate_bound','boolean'):
            row=self.certificate(2**-54,2**-53)
            if mutation=='physical':row['records'][0]['physical_transfer']=True
            elif mutation=='bound':row['records'][0]['arithmetic_bound_m3']=0.
            elif mutation=='exact':row['records'][0]['exact_adjustment']['numerator']=2
            elif mutation=='aggregate':row['liquid_adjustment_m3']=0.
            elif mutation=='aggregate_bound':row['liquid_adjustment_bound_m3']=0.
            else:row['records'][0]['adjustment_liquid_m3']=True
            with self.subTest(mutation=mutation),self.assertRaises(v.VerificationError):
                v.representation_summary([{'phase_representation':row}])

    def test_raw_and_representation_explained_ledgers_remain_separate(self):
        raw=2**-54;explained=raw-2**-54
        result=v._ledger(raw,1.)
        result['representation_explained_residual']=explained
        result['explained_check']=v._ledger(explained,1.)
        self.assertEqual(result['residual'],raw)
        self.assertEqual(result['representation_explained_residual'],0.)

    def test_known_max_rms_bias_and_exact_zero_errors(self):
        result = v.error_metrics([1.,2.,3.],[2.,0.,6.])
        self.assertEqual(result['max_abs'],3.)
        self.assertAlmostEqual(result['rms'],math.sqrt(14/3))
        self.assertAlmostEqual(result['bias'],2/3)
        self.assertEqual(v.error_metrics([1.,2.],[1.,2.]),{'count':2,'max_abs':0.,'rms':0.,'bias':0.})

    def test_rms_avoids_squaring_overflow(self):
        result = v.error_metrics([0.,0.],[1e200,-1e200])
        self.assertEqual(result['rms'],1e200)
        self.assertEqual(result['bias'],0.)

    def test_invalid_field_types_shapes_and_overflow_reject(self):
        for before,after in (([],[]),([0.],[0.,1.]),([True],[0.]),([math.nan],[0.]),
                             ([0.],[math.inf]),([1e308],[-1e308]),([10**1000],[0.])):
            with self.subTest(before=str(before)[:20]),self.assertRaises(v.VerificationError):
                v.error_metrics(before,after)

    def test_first_order_requires_two_usable_pairs(self):
        result = v.observed_orders([.1,.05,.025],[.01,.005,.0025],[1e-9]*3)
        self.assertEqual(result['status'],'PASS')
        self.assertEqual(result['usable_orders'],2)
        self.assertTrue(result['convergence_order_demonstrated'])
        self.assertTrue(all(abs(row['order']-1)<1e-14 for row in result['pairs']))
        self.assertEqual(v.observed_orders([.1,.05],[.01,.005],[1e-9]*2)['status'],'INCOMPLETE')

    def test_zero_error_is_not_an_infinite_or_fabricated_convergence_order(self):
        result = v.observed_orders([.1,.05,.025],[0.,0.,0.],[1e-9]*3)
        self.assertEqual(result['status'],'CONSISTENT_AT_NUMERICAL_FLOOR')
        self.assertFalse(result['convergence_order_demonstrated'])
        self.assertTrue(all(row['order'] is None for row in result['pairs']))

    def test_stagnation_worsening_and_low_order_fail(self):
        for errors in ([1.,1.,1.],[1.,2.,3.],[1.,.9,.8]):
            with self.subTest(errors=errors):
                self.assertEqual(v.observed_orders([.1,.05,.025],errors,[1e-9]*3)['status'],'FAIL')

    def test_mixed_resolved_and_unresolved_error_is_incomplete_not_pass(self):
        self.assertEqual(v.observed_orders([.1,.05,.025],[1e-6,1e-10,0.],[1e-9]*3)['status'],'INCOMPLETE')

    def test_nonfinite_boolean_negative_and_unordered_order_inputs_reject(self):
        for dts,errors,floors in (([.1,.1,.025],[1.,.5,.25],[1e-9]*3),
                                  ([.1,.05,.025],[math.nan,.5,.25],[1e-9]*3),
                                  ([.1,.05,.025],[True,.5,.25],[1e-9]*3),
                                  ([.1,.05,.025],[1.,.5,.25],[-1.]*3),
                                  ([.1,.05],[1.],[0.])):
            with self.assertRaises(v.VerificationError):v.observed_orders(dts,errors,floors)

    def test_failed_finest_or_other_case_never_substitutes_a_successful_reference(self):
        for index in (0,3):
            cases = cases_with_errors([.1,.05,.025,0.]);cases[index]['status']='FAIL'
            result = v.compare_refinement(cases)
            self.assertEqual(result['status'],'FAIL')
            self.assertFalse(result['fields'])

    def test_field_errors_and_reference_order_are_explicit(self):
        result = v.compare_refinement(cases_with_errors([.1,.05,.025,0.]))
        self.assertEqual(result['status'],'PASS')
        self.assertEqual(result['numerical_reference_dt'],.0125)
        self.assertTrue(result['orders_are_finite_reference_biased'])
        self.assertEqual(set(result['fields']),{'b','B','W','S'})
        self.assertEqual(result['fields']['b']['unit'],'m')
        self.assertEqual(result['fields']['W']['unit'],'m3')

    def test_recipient_mismatch_outside_brackets_is_a_failure(self):
        cases = [recipient_case(.2),recipient_case(.1),recipient_case(.05)]
        self.assertEqual(v.compare_recipients(cases,0.,.8)['status'],'PASS')
        cases[0]['recipient_intervals'][0]['destination_cell_indices']=[1]
        self.assertEqual(v.compare_recipients(cases,0.,.8)['status'],'FAIL')

    def test_recipient_uncertainty_and_missing_intervals_do_not_count_as_matches(self):
        cases = [recipient_case(.2),recipient_case(.1),recipient_case(.05)]
        for case in cases:
            case['events']=[{'kind':'BRACKETED_NATIVE_CONTACT','lower_years':0.,'upper_years':.8}]
        result = v.compare_recipients(cases,0.,.8)
        self.assertEqual(result['status'],'INCOMPLETE')
        self.assertTrue(all(row['status']=='EVENT_BRACKET_UNRESOLVED' for row in result['samples']))
        cases = [recipient_case(.2),recipient_case(.1),recipient_case(.05)]
        cases[0]['recipient_intervals']=[]
        with self.assertRaises(v.VerificationError):v.compare_recipients(cases,0.,.8)


class HarnessTests(unittest.TestCase):
    def run_tiny(self, **kwargs):
        return v.verify_prepared(tiny_prepared(),dts=(.2,.1,.05),repeat_dt=.1,**kwargs)

    def test_tiny_real_driver_refinement_repeat_and_json_restart(self):
        prepared = tiny_prepared();before = v.canonical(prepared['initial_state'].as_dict())
        result = v.verify_prepared(prepared,dts=(.2,.1,.05),repeat_dt=.1)
        self.assertEqual(result['status'],'PASS',result)
        self.assertEqual(result['identical_repeat']['status'],'PASS')
        self.assertEqual(result['json_checkpoint_restart']['status'],'PASS')
        self.assertEqual(v.canonical(prepared['initial_state'].as_dict()),before)
        self.assertEqual(len({row['prepared_state_sha256'] for row in result['cases']}),1)
        for row in result['cases']:
            self.assertAlmostEqual(row['final_state']['liquid_m3'][0],.8,delta=1e-12)
            self.assertEqual(row['counts']['scalar_rhs_evaluations'],0)
            self.assertGreater(row['counts']['trial_calls'],0)
            self.assertGreater(row['driver_and_validation_wall_seconds'],0.)
            self.assertIs(row['phase_representation']['physical_transfer'],False)
            for name in ('liquid_m3','solid_m3','rock_derived_kg'):
                self.assertIn('representation_explained_residual',row['ledgers'][name])
        self.assertIs(result['physical_acceptance'],False)
        self.assertIs(result['workflow_adoption'],False)
        self.assertIsNone(result['optimisation_speedup_percent'])

    def test_nonzero_time_restart_does_not_reapply_soil_prefix_ledger(self):
        prepared=tiny_prepared()
        prepared['initial_state']=v.driver.capture.CaptureState((1,1),(1.,),(.9,),(.09,),(0.,),(0.,))
        prepared['forcing']['incoming_liquid_m3_year']=[1.]
        prepared['forcing']['incoming_solid_m3_year']=[1.]
        prepared['soil_dissolved_rock_export_kg']=27.
        prepared['original_recipe']={'initial':{'bedrock_m':[1.],'mobile_solid_m3':[0.]}}
        result=v.verify_prepared(prepared,dts=(.2,.1,.05),repeat_dt=.1)
        self.assertEqual(result['status'],'PASS',result)
        for row in result['cases']:
            self.assertIn('soil_plus_coupled_rock_derived_kg',row['ledgers'])
            self.assertEqual(row['totals']['soil_dissolved_export_kg'],27.)
        restart=result['json_checkpoint_restart']
        self.assertEqual(restart['status'],'PASS')
        self.assertFalse(restart['soil_prefix_reapplied'])
        self.assertIn('soil_plus_coupled_rock_derived_kg',restart['first']['ledgers'])
        self.assertNotIn('soil_plus_coupled_rock_derived_kg',restart['second']['ledgers'])
        self.assertEqual(restart['second']['totals']['soil_dissolved_export_kg'],0.)
        self.assertTrue(v._exact_state(result['cases'][1]['final_state'],restart['second']['final_state']))

    def test_extra_reference_keeps_initial_refinement_evidence(self):
        result = self.run_tiny(extra_finer=True)
        self.assertEqual(len(result['cases']),4)
        self.assertEqual(result['initial_refinement']['numerical_reference_dt'],.05)
        self.assertEqual(result['refinement']['numerical_reference_dt'],.025)

    def test_failure_counts_and_last_valid_state_preserved_not_zeroed(self):
        error = v.driver.CouplingError('synthetic incomplete trial')
        error.coupling_counts={'trial_calls':3,'scalar_rhs_evaluations':17}
        error.coupling_time_years=0.;error.coupling_trial_years=.1
        error.last_valid_state=tiny_prepared()['initial_state']
        with patch.object(v.driver,'advance',side_effect=error):result=self.run_tiny()
        self.assertEqual(result['status'],'FAIL')
        self.assertEqual(result['cases'][0]['counts']['scalar_rhs_evaluations'],17)
        self.assertEqual(result['cases'][0]['last_valid_state']['time_years'],0.)
        self.assertEqual(result['refinement']['status'],'FAIL')
        self.assertEqual(result['identical_repeat']['status'],'FAIL')

    def test_pretrial_error_counts_stay_explicitly_unavailable(self):
        with patch.object(v.driver,'advance',side_effect=ValueError('not entered')):result=self.run_tiny()
        self.assertIsNone(result['cases'][0]['counts'])
        self.assertEqual(result['cases'][0]['error']['message'],'not entered')

    def test_false_completion_flag_and_short_interval_never_pass(self):
        advance = v.driver.advance
        def dishonest(state,**kwargs):
            final,report=advance(state,**kwargs);report['whole_interval_completed']=False
            return final,report
        with patch.object(v.driver,'advance',dishonest):result=self.run_tiny()
        self.assertEqual(result['status'],'FAIL')
        self.assertIn('completion',result['cases'][0]['error']['message'])
        def short(state,**kwargs):
            final,report=advance(state,**kwargs)
            return replace(final,time_years=final.time_years-.001),report
        with patch.object(v.driver,'advance',short):result=self.run_tiny()
        self.assertEqual(result['status'],'FAIL')

    def test_ledger_corruption_cannot_be_hidden_by_pass_flags(self):
        advance = v.driver.advance
        def corrupt(state,**kwargs):
            final,report=advance(state,**kwargs)
            report['steps'][0]['exported_liquid_m3']+=1.
            return final,report
        with patch.object(v.driver,'advance',corrupt):result=self.run_tiny()
        self.assertEqual(result['status'],'FAIL')
        self.assertIn('ledger',result['cases'][0]['error']['message'])

    def test_source_drift_during_integration_fails_and_rechecks(self):
        pins=v.source_snapshot();calls=[]
        def snapshot():
            calls.append(1)
            return pins if len(calls)<3 else [*pins,{'name':'synthetic drift'}]
        with patch.object(v,'source_snapshot',snapshot):result=self.run_tiny()
        self.assertEqual(result['status'],'FAIL')
        self.assertFalse(result['cases'][0]['sources_unchanged'])
        self.assertGreater(len(calls),3)

    def test_retained_rejection_is_exact_not_any_exception_or_success(self):
        recipe={'synthetic':'fixture'}
        expected='channel timestep consumes relative link relief excessively; reduce dt'
        with patch.object(v.io,'execute',side_effect=ValueError(expected)):
            result=v.retained_rejection(recipe)
        self.assertEqual(result['status'],'PASS_RETAINED_REJECTION')
        self.assertFalse(result['valid_final_terrain_exists'])
        with patch.object(v.io,'execute',side_effect=RuntimeError(expected)):
            self.assertEqual(v.retained_rejection(recipe)['status'],'FAIL')
        with patch.object(v.io,'execute',return_value={}):
            self.assertEqual(v.retained_rejection(recipe)['status'],'FAIL')

    def test_envelope_and_authority_inputs_fail_before_any_driver_run(self):
        for kwargs in ({'wall_seconds':601.},{'wall_seconds':True},
                       {'dts':(.2,.1),'repeat_dt':.1},{'dts':(.1,.1,.05),'repeat_dt':.1},
                       {'dts':(.2,.1,.05),'repeat_dt':.03}):
            with self.assertRaises(v.VerificationError):v.verify_prepared(tiny_prepared(),**kwargs)
        prepared=tiny_prepared();prepared['production_authorised']=True
        with self.assertRaises(v.VerificationError):
            v.verify_prepared(prepared,dts=(.2,.1,.05),repeat_dt=.1)


if __name__ == '__main__':unittest.main()
