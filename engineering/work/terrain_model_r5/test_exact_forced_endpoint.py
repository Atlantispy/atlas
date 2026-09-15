from copy import deepcopy
from dataclasses import replace
from fractions import Fraction as F
import json
import math
import unittest
from unittest.mock import patch

from capture import CaptureState
import exact_forced_endpoint as exact
import shoreline_driver as driver
from test_shoreline_driver import arguments, forced_existing_pool


def split_fixture(*, ties=False, inlet=0):
    bed = (0., .984375, .5, .984375, 1.) if ties else (0., .984375, .5, 1.)
    n = len(bed)
    depths = [1.-b for b in bed]
    state = CaptureState((1,n), (1.,)*n, bed, (0.,)*n,
                         tuple(.75*h for h in depths), tuple(.25*h for h in depths))
    k = .125*(n-1)
    qs = (.5+k)*.25-k*.0625
    kwargs = arguments(n, dt=.5, steps=1)
    qw, ss = [0.]*n, [0.]*n
    qw[inlet], ss[inlet] = .5-qs, qs
    kwargs.update(external_outlets=[n-1], runoff_m_year=[0.]*n,
                  incoming_liquid_m3_year=qw, incoming_solid_m3_year=ss,
                  basin_settling_m_year=.125)
    return state, kwargs


class ExactEndpointTests(unittest.TestCase):
    def test_exact_half_year_endpoint_and_independent_phase_ledgers(self):
        state, kwargs = forced_existing_pool()
        kwargs['dt_years'] = .5
        final, report = driver.advance(state, **kwargs)
        self.assertEqual(final.liquid_m3, (0.,189/256,0.))
        self.assertEqual(final.suspended_solid_m3, (0.,63/256,0.))
        self.assertEqual(final.bed_solid_m3, (1/64,1/64,0.))
        self.assertEqual(final.time_years, .5)
        row = report['steps'][0]
        total = lambda values: sum(map(F, values), F())
        self.assertEqual(total(final.liquid_m3)+F(row['exported_liquid_m3']),
                         total(state.liquid_m3)+F(row['imported_liquid_m3']))
        self.assertEqual(total(final.suspended_solid_m3)+total(final.bed_solid_m3)+F(row['exported_solid_m3']),
                         total(state.suspended_solid_m3)+F(row['imported_solid_m3']))
        self.assertEqual(report['events'][0]['dried_cells'], [0])
        self.assertEqual(report['counts']['scalar_rhs_evaluations'], 24)
        self.assertFalse(report['events'][0]['post_event_hydraulics_solved'])

    def test_unequal_actual_daughters_and_native_forcing_tags(self):
        state, kwargs = split_fixture()
        final, report = driver.advance(state, **kwargs)
        event = report['events'][0]
        self.assertTrue(event['split'])
        self.assertEqual([row['cell_indices'] for row in event['daughters']], [[0],[2]])
        self.assertEqual(final.liquid_m3, (.73828125,0.,.36328125,0.))
        self.assertEqual(final.suspended_solid_m3, (.24609375,0.,.12109375,0.))
        other_state, other_kwargs = split_fixture(inlet=2)
        other, other_report = driver.advance(other_state, **other_kwargs)
        self.assertEqual(final, other)
        self.assertNotEqual(event['native_forcing'], other_report['events'][0]['native_forcing'])
        self.assertEqual(event['native_forcing'][0]['incoming_liquid_m3_year'], kwargs['incoming_liquid_m3_year'][0])

    def test_complete_simultaneous_tie_is_dry(self):
        state, kwargs = split_fixture(ties=True)
        final, report = driver.advance(state, **kwargs)
        self.assertEqual(report['events'][0]['dried_cells'], [1,3])
        for i in (1,3):
            self.assertEqual((final.liquid_m3[i],final.suspended_solid_m3[i],final.bed_m[i]),(0.,0.,1.))

    def test_json_restart_and_split_interval_identity(self):
        state, kwargs = forced_existing_pool()
        kwargs['dt_years'] = .5
        expected, _ = driver.advance(state, **kwargs)
        kwargs['dt_years'] = .25
        middle, _ = driver.advance(state, **kwargs)
        restored = CaptureState(**json.loads(json.dumps(middle.as_dict())))
        final, _ = driver.advance(restored, **kwargs)
        self.assertEqual(final, expected)

    def test_earlier_endpoint_does_not_dry(self):
        state, kwargs = forced_existing_pool()
        kwargs['dt_years'] = .25
        final, report = driver.advance(state, **kwargs)
        self.assertGreater(final.liquid_m3[0],0.)
        self.assertFalse(report['events'])

    def test_one_ulp_near_endpoint_is_not_promoted_to_exact(self):
        state, kwargs = forced_existing_pool()
        kwargs['dt_years'] = math.nextafter(.5,0.)
        with self.assertRaisesRegex(driver.CouplingError,'BLOCKED_NUMERICAL_EVENT_SIGN'):
            driver.advance(state, **kwargs)

    def test_exact_endpoint_cannot_round_its_durable_absolute_clock(self):
        state, kwargs = forced_existing_pool()
        kwargs['dt_years'] = .5
        state = replace(state,time_years=.1)
        with self.assertRaisesRegex(ValueError,'absolute endpoint time is not exactly representable') as caught:
            driver.advance(state,**kwargs)
        self.assertEqual(caught.exception.last_valid_state,state.as_dict())

    def test_longer_interval_remains_blocked_without_claiming_completion(self):
        state, kwargs = forced_existing_pool()
        with self.assertRaisesRegex(driver.CouplingError,'BLOCKED_FORCED_DAUGHTER_COUPLING') as caught:
            driver.advance(state, **kwargs)
        self.assertEqual(caught.exception.last_valid_state, state.as_dict())
        self.assertEqual(caught.exception.coupling_counts['accepted_substeps'],0)

    def test_tampered_numerical_endpoint_cannot_borrow_exact_certificate(self):
        state, kwargs = forced_existing_pool()
        kwargs['dt_years'] = .5
        original = driver._detect_forced_event
        def changed(*args, **kw):
            result = deepcopy(original(*args, **kw))
            result['probes'][-1]['scalar_result']['deposited_solid_m3'] += 2**-40
            return result
        with patch.object(driver,'_detect_forced_event',side_effect=changed):
            with self.assertRaisesRegex(ValueError,'disagrees with exact deposited') as caught:
                driver.advance(state, **kwargs)
        self.assertEqual(caught.exception.last_valid_state,state.as_dict())
        self.assertEqual(caught.exception.coupling_counts['accepted_substeps'],0)

    def test_non_equilibrium_forcing_is_not_certified(self):
        state, kwargs = forced_existing_pool()
        kwargs['dt_years'] = .5
        kwargs['incoming_solid_m3_year'][0] -= 2**-10
        final, report = driver.advance(state, **kwargs)
        self.assertGreater(final.liquid_m3[0],0.)
        self.assertFalse(any(e['kind']=='EXACT_FORCED_DRYING_ENDPOINT' for e in report['events']))

    def test_no_rounding_or_epsilon_in_exact_encoding(self):
        with self.assertRaisesRegex(ValueError,'not exactly representable'):
            exact.represented(F(1,3),'test phase')
        with self.assertRaisesRegex(ValueError,'not representable'):
            exact.represented(F(2)**2048,'test phase')

    def test_exact_routed_equilibrium_is_not_perturbed_by_ratio_rounding(self):
        state, kwargs = split_fixture(ties=True)
        routed = driver.capture.route(state,kwargs['external_outlets'],4)
        self.assertEqual(tuple(routed['liquid_m3']),state.liquid_m3)
        self.assertEqual(tuple(routed['suspended_solid_m3']),state.suspended_solid_m3)

    def test_rerouting_must_not_change_certified_phase_stocks(self):
        state, kwargs = forced_existing_pool()
        kwargs['dt_years'] = .5
        original = driver.capture.from_route
        def changed(previous, routed):
            result = original(previous,routed)
            if previous.bed_solid_m3[0] == 1/64:
                result = replace(result,liquid_m3=(0.,math.nextafter(result.liquid_m3[1],0.),0.))
            return result
        with patch.object(driver.capture,'from_route',side_effect=changed):
            with self.assertRaisesRegex(driver.CouplingError,'routing changed the exact'):
                driver.advance(state,**kwargs)


if __name__ == '__main__':
    unittest.main()
