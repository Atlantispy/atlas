"""Regressions for the September 2026 audit; no weakened scientific gates."""
from copy import deepcopy
from fractions import Fraction
import json
import unittest
from unittest.mock import patch

import capture
from capture_fixtures import suite
import continuous_pool
import forced_drying
import phase_storage
import event_settling
import shoreline
import shoreline_driver
import shoreline_network
from test_forced_drying import convex_case, constant_case


class MaterialGeometryRepairs(unittest.TestCase):
    def recipe(self):
        return deepcopy(next(r for r in suite() if r['scenario_id']=='bed_only_displacement'))

    def test_bed_displacement_conserves_exact_liquid_without_changing_geometry(self):
        r=self.recipe()
        final, report=capture.advance(capture.CaptureState(**r['state']),**r['forcing'])
        self.assertEqual(final.liquid_m3,(0.,49.,0.))
        self.assertEqual(final.bed_solid_m3,(0.,1.,0.))
        self.assertEqual(report['steps'][0]['exported_liquid_m3'],1.)
        capacity=10*(Fraction(5)-Fraction(final.bed_m[1]))
        self.assertEqual(capture.exact_liquid(final),capacity)
        self.assertEqual(Fraction(*final.liquid_remainder_m3[1]),capacity-49)
        exported=report['steps'][0]
        self.assertEqual(Fraction(exported['exported_liquid_m3'])+Fraction(*exported['exported_liquid_remainder_m3']),50-capacity)
        self.assertEqual(report['exact_liquid_ledger'],{'checked':True,'residual_m3':[0,1]})
        self.assertNotEqual(Fraction(final.bed_m[1]),Fraction(1,10))
        routed=capture.route(final,[0,2],4)
        self.assertEqual(routed['exported_liquid_m3'],0.)
        self.assertEqual(routed['liquid_m3'],[0.,49.,0.])
        self.assertEqual(routed['ledger']['exact_mixture_routing_residual_m3'],0.)
        self.assertEqual(routed['exported_liquid_remainder_m3'],[0,1])
        self.assertEqual(capture.from_route(final,routed),final)

    def test_repeat_loading_and_json_restart_preserve_results(self):
        r=self.recipe(); initial=capture.CaptureState(**r['state'])
        first,_=capture.advance(initial,**r['forcing'])
        direct,rd=capture.advance(first,**r['forcing'])
        restored=capture.CaptureState(**json.loads(json.dumps(first.as_dict())))
        resumed,rr=capture.advance(restored,**r['forcing'])
        self.assertEqual((direct,rd),(resumed,rr))
        whole,_=capture.advance(initial,**{**r['forcing'],'steps':2})
        self.assertEqual(whole,resumed)
        self.assertEqual(resumed.liquid_m3,(0.,48.,0.))

    def test_network_consumes_same_liquid_remainder_and_binary64_geometry(self):
        r=self.recipe(); state,_=capture.advance(capture.CaptureState(**r['state']),**r['forcing'])
        network=shoreline_network.build_network(state,dx_m=1.,dy_m=10.,external_outlets=[0,2],
                                              runoff_m_year=[0.]*3,connectivity=4)
        pool=network['pools'][0]
        self.assertTrue(pool['spill']['at_exact_spill'])
        self.assertEqual(pool['exact_stage_m'],{'numerator':5,'denominator':1})
        self.assertEqual(shoreline_driver._external_boundary_representation(state,pool,1.)['capacity_deficit_m3'],0.)

    def test_rounded_bed_ties_are_not_reinterpreted_as_exact_material_geometry(self):
        state=capture.CaptureState([1,4],[10.]*4,[5.,0.,.1,5.],[0.,1.,0.,0.],
                                   [0.,60.,0.,0.],[0.]*4)
        routed=capture.route(state,[0,3],4)
        modules,_=phase_storage._bound_sources()
        expected=modules['basin_topology.py'].extract_basin_topology(list(state.bed_m),[1,4],[0,3],connectivity=4)
        self.assertEqual(routed['topology'],expected)

    def test_remainder_requires_canonical_bounded_pairs_and_positive_carrier(self):
        for pair in ([1,0],[1,-1],[0,2],[2,4],[True,1],[1.,2],[1,2**9000],[1,1]):
            with self.subTest(pair=str(pair)[:30]),self.assertRaises(ValueError):
                phase_storage.liquid_remainders([1.],[pair])
        with self.assertRaises(ValueError):phase_storage.liquid_remainders([0.],[[1,2**1075]])
        self.assertEqual(phase_storage.liquid_remainders([1.],[[1,2**53]]),(Fraction(1,2**53),))

    def test_float_only_geometry_does_not_acquire_invented_material_authority(self):
        with self.assertRaisesRegex(ValueError,'binary64 representation'):
            phase_storage.route_phases([5.,.1,5.],[10.]*3,[1,3],[0,2],[0.,50.,0.],[0.]*3)

    def test_multicell_exact_projection_and_export_account_every_remainder(self):
        bed=[5.,.1,2.,.2,5.];area=[10.]*5;water=[0.,200.,0.,0.,0.]
        routed=phase_storage.route_phases(bed,area,[1,5],[0,4],water,[0.]*5,
                                         liquid_remainder_m3=[[0,1]]*5,exact_liquid=True)
        residuals=phase_storage.liquid_remainders(routed['liquid_m3'],routed['liquid_remainder_m3'])
        stored=sum((Fraction(w)+r for w,r in zip(routed['liquid_m3'],residuals)),Fraction())
        exported=Fraction(routed['exported_liquid_m3'])+Fraction(*routed['exported_liquid_remainder_m3'])
        self.assertEqual(stored+exported,200)
        self.assertEqual(stored,sum((10*(Fraction(5)-Fraction(v)) for v in bed[1:4]),Fraction()))
        rerouted=phase_storage.route_phases(bed,area,[1,5],[0,4],routed['liquid_m3'],[0.]*5,
                                           liquid_remainder_m3=routed['liquid_remainder_m3'])
        self.assertEqual(rerouted['liquid_m3'],routed['liquid_m3'])
        self.assertEqual(rerouted['liquid_remainder_m3'],routed['liquid_remainder_m3'])
        self.assertEqual(rerouted['exported_liquid_m3'],0.)

    def test_pure_liquid_no_settling_preserves_nonzero_remainder(self):
        r=self.recipe();state,_=capture.advance(capture.CaptureState(**r['state']),**r['forcing'])
        result,report=event_settling.settle_components(state,settling_m_year=3.,elapsed_years=2.)
        self.assertEqual(result,state)
        self.assertEqual(report['solver_calls'],0)

    def test_suspended_inlet_into_residual_state_fails_before_mutation(self):
        r=self.recipe();state,_=capture.advance(capture.CaptureState(**r['state']),**r['forcing'])
        before=state.as_dict()
        with self.assertRaisesRegex(ValueError,'exact phase transport'):
            capture.step(state,outlets=[0,2],connectivity=4,liquid_input_m3=[0.,1.,0.],
                         suspended_input_m3=[0.,.1,0.],bed_input_solid_m3=[0.]*3,
                         settling_m_year=1.,elapsed_years=1.,source_label='SYNTHETIC rejection')
        self.assertEqual(state.as_dict(),before)

    def test_dynamic_shoreline_primitive_rejects_residual_before_work(self):
        r=self.recipe();state,_=capture.advance(capture.CaptureState(**r['state']),**r['forcing'])
        with self.assertRaisesRegex(shoreline.ShorelineError,'exact shoreline transport'):
            shoreline.channel_trial(state,receivers=None,link_lengths_m=None,contributing_area_m2=None,
                pool_owner=None,pool_stages_m=None,incipient_pool_cells=None,external_outlets=None,
                runoff_m_year=None,sediment_k_per_year=None,rock_k_per_year=None,cover_scale_m=None,
                settling_m_year=None,dt_years=None)

    def test_underfull_residual_routing_does_not_lose_exact_stock(self):
        residual=Fraction(1,2**54)
        state=capture.CaptureState([1,3],[1.]*3,[5.,0.,5.],[0.]*3,[0.,1.,0.],[0.]*3,
                                  liquid_remainder_m3=[[0,1],phase_storage.ratio(residual),[0,1]])
        result=capture.from_route(state,capture.route(state,[0,2],4))
        self.assertEqual(capture.exact_liquid(result),1+residual)
        self.assertEqual(result.liquid_remainder_m3,state.liquid_remainder_m3)

    def test_direct_export_transports_exact_residual(self):
        residual=Fraction(1,2**54)
        result=phase_storage.route_phases([0.],[1.],[1,1],[0],[1.],[0.],
                                          liquid_remainder_m3=[phase_storage.ratio(residual)])
        self.assertEqual(result['liquid_m3'],[0.])
        self.assertEqual(result['exported_liquid_m3'],1.)
        self.assertEqual(Fraction(*result['exported_liquid_remainder_m3']),residual)

    def test_exact_pure_inlet_addition_is_accounted(self):
        state=capture.CaptureState([1,1],[1.],[0.],[0.],[1.],[0.])
        final,report=capture.step(state,outlets=[],connectivity=4,liquid_input_m3=[2.**-54],
            suspended_input_m3=[0.],bed_input_solid_m3=[0.],settling_m_year=0.,elapsed_years=1.,
            source_label='SYNTHETIC sub-ULP inlet')
        self.assertEqual(capture.exact_liquid(final),1+Fraction(1,2**54))
        self.assertEqual(report['exact_liquid_ledger'],{'checked':True,'residual_m3':[0,1]})

    def test_aggregate_remainders_include_rounded_sum_not_only_cell_corrections(self):
        result=phase_storage.route_phases([0.,0.],[1.,1.],[1,2],[],[1.,2.**-54],[0.,0.],
                                          liquid_remainder_m3=[[0,1]]*2,exact_liquid=True)
        logical=1+Fraction(1,2**54)
        for name in ('input','stored'):
            ledger=result['ledger']
            self.assertEqual(Fraction(ledger[name+'_liquid_m3'])+Fraction(*ledger[name+'_liquid_remainder_m3']),logical)
        pool=result['active_pools'][0]
        self.assertEqual(Fraction(pool['liquid_m3'])+Fraction(*pool['liquid_remainder_m3']),logical)


class ResourceAccountingRepairs(unittest.TestCase):
    def test_one_rhs_aggregate_budget_is_enforced_and_reported(self):
        with self.assertRaisesRegex(forced_drying.ForcedDryingError,'scalar-evaluation') as caught:
            forced_drying.first_event(**convex_case(max_scalar_evaluations=1))
        self.assertEqual(caught.exception.scalar_rhs_evaluations,1)
        self.assertEqual(caught.exception.scalar_calls,2)

    def test_zero_work_validation_error_is_accounted(self):
        with self.assertRaises(forced_drying.ForcedDryingError) as caught:
            forced_drying.first_event(**constant_case(liquid_m3=True))
        self.assertEqual(caught.exception.scalar_rhs_evaluations,0)
        self.assertEqual(caught.exception.scalar_calls,0)

    def test_caller_cannot_supply_private_work_tracker(self):
        with self.assertRaisesRegex(forced_drying.ForcedDryingError,'private work'):
            forced_drying.first_event(**constant_case(),_work={})

    def test_driver_accounts_failed_work_without_advancing_checkpoint(self):
        counts={'scalar_rhs_evaluations':7}
        state=capture.CaptureState([1,1],[1.],[0.],[0.],[1.],[0.])
        before=state.as_dict()
        with self.assertRaises(forced_drying.ForcedDryingError) as caught:
            shoreline_driver._detect_forced_event(counts,state,**convex_case(max_scalar_evaluations=1))
        self.assertEqual(counts['scalar_rhs_evaluations'],8)
        self.assertEqual(caught.exception.driver_counts,counts)
        self.assertEqual(caught.exception.unchanged_driver_checkpoint,before)
        self.assertEqual(state.as_dict(),before)

    def test_completed_probe_work_survives_post_call_source_failure(self):
        real=continuous_pool.advance_pool
        def completed(*args,**kwargs):
            result=real(*args,**kwargs)
            if result['evaluations']:
                forced_drying._source_snapshot=lambda *a,**k: (_ for _ in ()).throw(
                    forced_drying.ForcedDryingError('injected post-probe source failure'))
            return result
        with patch.object(forced_drying,'_source_snapshot',wraps=forced_drying._source_snapshot), \
                patch.object(continuous_pool,'advance_pool',side_effect=completed):
            with self.assertRaisesRegex(forced_drying.ForcedDryingError,'source failure') as caught:
                forced_drying.first_event(**convex_case())
        self.assertGreater(caught.exception.scalar_rhs_evaluations,0)

    def test_scalar_caller_budget_is_strict_and_can_stop_before_any_rhs(self):
        for budget in (True,-1,65537,1.5):
            with self.assertRaises(continuous_pool.ContinuousPoolError):
                continuous_pool.advance_pool(.2,.8,1.,.2,0.,0.,1.,4.,max_evaluations=budget)
        with self.assertRaises(continuous_pool.ContinuousPoolError) as caught:
            continuous_pool.advance_pool(.2,.8,1.,.2,0.,0.,1.,4.,max_evaluations=0)
        self.assertEqual(caught.exception.evaluations,0)


if __name__=='__main__':unittest.main()
