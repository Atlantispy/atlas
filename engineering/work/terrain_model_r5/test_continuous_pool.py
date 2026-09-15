"""Independent analytical/Decimal control volumes; not physical acceptance.

Oracle tolerances: Decimal 512/1024 RK4 refinement <1e-12 m3; production
phase errors <2e-10 m3; self-similar/linear exact limits <2e-13 m3. These
limits and oracle equations were declared before the first test execution.
"""
from decimal import Decimal, localcontext
import json
import math
import random
import unittest
from unittest.mock import patch

import continuous_pool as p


KEYS = ('liquid_m3', 'suspended_solid_m3', 'deposited_solid_m3',
        'exported_liquid_m3', 'exported_suspended_solid_m3')


def values(result):
    return tuple(result[key] for key in KEYS)


def request(**updates):
    result = dict(liquid_m3=4., suspended_solid_m3=.4, area_m2=2.,
                  liquid_input_m3_year=.8, solid_input_m3_year=.2,
                  mixture_export_m3_year=0., settling_m_year=.7, dt_years=1.)
    result.update(updates)
    return result


def decimal_reference(parameters, count):
    """Decimal60 RK4 of all five ODEs; no production helpers/control code."""
    with localcontext() as context:
        context.prec = 60
        D = lambda value: Decimal(str(value))
        w, s = D(parameters['liquid_m3']), D(parameters['suspended_solid_m3'])
        area, v = D(parameters['area_m2']), D(parameters['settling_m_year'])
        qw, qs, qo = (D(parameters[key]) for key in
                      ('liquid_input_m3_year', 'solid_input_m3_year', 'mixture_export_m3_year'))
        step = D(parameters['dt_years'])/count
        y = (w, s, Decimal(0), Decimal(0), Decimal(0))
        def rhs(y):
            w, s = y[:2]
            volume = w+s
            ew, es, deposited = qo*w/volume, qo*s/volume, v*area*s/volume
            return qw-ew, qs-es-deposited, deposited, ew, es
        def shifted(y, derivative, factor):
            return tuple(value+step*factor*rate for value, rate in zip(y, derivative))
        for _ in range(count):
            a = rhs(y)
            b = rhs(shifted(y, a, Decimal('.5')))
            c = rhs(shifted(y, b, Decimal('.5')))
            d = rhs(shifted(y, c, Decimal(1)))
            y = tuple(value+step*(aa+2*bb+2*cc+dd)/6
                      for value, aa, bb, cc, dd in zip(y, a, b, c, d))
        return tuple(float(value) for value in y)


def birth_reference(qw, qs, k, t):
    with localcontext() as context:
        context.prec = 70
        w, s, rate, duration = map(lambda value: Decimal(str(value)), (qw, qs, k, t))
        coefficient = w+rate-s
        r = ((coefficient*coefficient+4*w*s).sqrt()-coefficient)/2
        return float(w*duration), float(r*duration), float((s-r)*duration), 0., 0.


def composed(parameters, count):
    state = (parameters['liquid_m3'], parameters['suspended_solid_m3'])
    deposits, exported_w, exported_s = [], [], []
    for _ in range(count):
        r = p.advance_pool(**{**parameters, 'liquid_m3':state[0], 'suspended_solid_m3':state[1],
                              'dt_years':parameters['dt_years']/count})
        state = r['liquid_m3'], r['suspended_solid_m3']
        deposits.append(r['deposited_solid_m3'])
        exported_w.append(r['exported_liquid_m3'])
        exported_s.append(r['exported_suspended_solid_m3'])
    return *state, math.fsum(deposits), math.fsum(exported_w), math.fsum(exported_s)


class ContinuousPoolTests(unittest.TestCase):
    def assert_close(self, actual, expected, tolerance=2e-10):
        for index, (a, b) in enumerate(zip(actual, expected)):
            self.assertLessEqual(abs(a-b), tolerance, (index, a, b, abs(a-b)))

    def assert_ledgers(self, result):
        for ledger in result['ledgers'].values():
            self.assertLessEqual(abs(ledger['residual_m3']), ledger['tolerance_m3'])
        self.assertIs(result['physical_acceptance'], False)
        self.assertIs(result['production_authorised'], False)
        self.assertIs(result['geometry_or_wet_events_solved'], False)
        self.assertIs(result['hydraulics_solved'], False)

    def test_zero_duration_exact_and_unforced_inventory_preserved(self):
        r = p.advance_pool(**request(dt_years=0.))
        self.assertEqual(values(r), (4., .4, 0., 0., 0.))
        r = p.advance_pool(**request(liquid_input_m3_year=0., solid_input_m3_year=0., settling_m_year=0.))
        self.assertEqual(values(r), (4., .4, 0., 0., 0.))
        self.assertEqual(r['evaluations'], 0)

    def test_empty_pool_pure_liquid_birth_and_empty_unforced_limit(self):
        r = p.advance_pool(**request(liquid_m3=0., suspended_solid_m3=0.,
                                     solid_input_m3_year=0., dt_years=2.))
        self.assertEqual(values(r), (1.6, 0., 0., 0., 0.))
        r = p.advance_pool(**request(liquid_m3=0., suspended_solid_m3=0.,
                                     liquid_input_m3_year=0., solid_input_m3_year=0.))
        self.assertEqual(values(r), (0., 0., 0., 0., 0.))

    def test_empty_pool_quadratic_oracle_across_settling_and_source_regimes(self):
        for qw, qs, k in ((1., .1, 2.), (.1, 2., .1), (4., .2, 0.),
                          (1., .1, 100000.), (1., .1, 1e-12)):
            with self.subTest(qw=qw, qs=qs, k=k):
                args = request(liquid_m3=0., suspended_solid_m3=0., area_m2=1.,
                               liquid_input_m3_year=qw, solid_input_m3_year=qs, settling_m_year=k, dt_years=.8)
                r = p.advance_pool(**args)
                self.assert_close(values(r), birth_reference(qw, qs, k, .8), 2e-13)
                self.assertEqual(r['evaluations'], 0)
                if k:
                    self.assertGreater(r['deposited_solid_m3'], 0.)
                self.assert_ledgers(r)

    def test_birth_then_resumption_matches_one_self_similar_interval(self):
        args = request(liquid_m3=0., suspended_solid_m3=0., area_m2=1.,
                       liquid_input_m3_year=1., solid_input_m3_year=.1, settling_m_year=2.)
        target = birth_reference(1., .1, 2., 1.)
        for count in (2, 4, 8):
            self.assert_close(composed(args, count), target)

    def test_empty_pool_cannot_have_prescribed_positive_export(self):
        with self.assertRaisesRegex(p.ContinuousPoolError, 'export from empty pool'):
            p.advance_pool(**request(liquid_m3=0., suspended_solid_m3=0., mixture_export_m3_year=.1))

    def test_pure_liquid_drying_endpoint_and_beyond(self):
        args = request(liquid_m3=1., suspended_solid_m3=0., liquid_input_m3_year=.5,
                       solid_input_m3_year=0., mixture_export_m3_year=1.5)
        r = p.advance_pool(**args)
        self.assertEqual(values(r), (0., 0., 0., 1.5, 0.))
        self.assert_ledgers(r)
        with self.assertRaisesRegex(p.ContinuousPoolError, 'drying event'):
            p.advance_pool(**{**args, 'dt_years':1.01})

    def test_no_settling_no_export_linear_supplies(self):
        r = p.advance_pool(**request(settling_m_year=0., dt_years=2.))
        self.assert_close(values(r), (5.6, .8, 0., 0., 0.), 2e-13)

    def test_no_settling_fixed_volume_exponential_mixing(self):
        args = request(liquid_m3=9., suspended_solid_m3=1., liquid_input_m3_year=3.,
                       solid_input_m3_year=1., mixture_export_m3_year=4., settling_m_year=0., dt_years=2.)
        w = 7.5+1.5*math.exp(-.8)
        s = 10.-w
        expected = w, s, 0., 15.-w, 3.-s
        self.assert_close(values(p.advance_pool(**args)), expected)

    def test_constant_concentration_analytical_family_including_spill(self):
        # c=.2, qW=.8,qS=.4,k=1 gives c'=0; V'=1-qO.
        for qo in (0., .5, 1.2):
            args = request(liquid_m3=8., suspended_solid_m3=2., area_m2=1.,
                           liquid_input_m3_year=.8, solid_input_m3_year=.4,
                           mixture_export_m3_year=qo, settling_m_year=1., dt_years=2.)
            volume = 10.+(1.-qo)*2.
            expected = .8*volume, .2*volume, .4, .8*qo*2., .2*qo*2.
            r = p.advance_pool(**args)
            self.assert_close(values(r), expected, 2e-13)
            self.assert_ledgers(r)

    def test_closed_settling_independent_implicit_equation(self):
        args = request(liquid_input_m3_year=0., solid_input_m3_year=0.)
        with localcontext() as context:
            context.prec = 70
            D = Decimal;w, s0, target = D(4), D('.4'), D('1.4')
            lo, hi = D(0), s0
            for _ in range(240):
                mid = (lo+hi)/2
                value = w*(s0/mid).ln()+s0-mid
                if value > target:lo = mid
                else:hi = mid
            s = float((lo+hi)/2)
        self.assert_close(values(p.advance_pool(**args)), (4., s, .4-s, 0., 0.))

    def test_decimal_refined_oracles_for_growing_spilling_and_draining(self):
        for qo in (0., 1., 1.5):
            args = request(mixture_export_m3_year=qo)
            with self.subTest(export=qo):
                fine = decimal_reference(args, 1024)
                self.assert_close(fine, decimal_reference(args, 512), 1e-12)
                r = p.advance_pool(**args)
                self.assert_close(values(r), fine)
                self.assert_ledgers(r)

    def test_partitioned_intervals_agree_with_frozen_accuracy_and_decimal(self):
        args = request(mixture_export_m3_year=1.)
        expected = decimal_reference(args, 1024)
        for count in (1, 2, 4, 8):
            self.assert_close(composed(args, count), expected)

    def test_seeded_varied_positive_regimes_against_independent_decimal(self):
        rng = random.Random(314159)
        for index in range(24):
            w, s = 1+rng.random()*5, .001+rng.random()
            qw, qs = .2+rng.random(), .001+rng.random()*.2
            args = request(liquid_m3=w, suspended_solid_m3=s, area_m2=.5+rng.random()*2,
                           liquid_input_m3_year=qw, solid_input_m3_year=qs,
                           mixture_export_m3_year=rng.random()*(qw+qs),
                           settling_m_year=rng.random()*2, dt_years=.1+rng.random())
            with self.subTest(index=index):
                r = p.advance_pool(**args)
                self.assert_close(values(r), decimal_reference(args, 1024))
                self.assert_ledgers(r)

    def test_final_state_guard_rejects_carrier_loss_not_residual_repair(self):
        with patch.object(p, '_birth', return_value=(0., .1, 0., 0., 0.)):
            with self.assertRaisesRegex(p.ContinuousPoolError, 'no represented liquid carrier'):
                p.advance_pool(**request(liquid_m3=0., suspended_solid_m3=0.))

    def test_fourth_order_refinement_with_controller_disabled_only_in_diagnostic(self):
        # Exposes accepted RK4 discretisation order. Only the error controller
        # is made permissive in this test; phase positivity/conservation gates
        # remain frozen. All ordinary oracle tests use production settings.
        args = request(liquid_m3=2., suspended_solid_m3=.8, area_m2=1.,
                       settling_m_year=2., mixture_export_m3_year=1.)
        expected = decimal_reference(args, 2048)
        with patch.object(p, 'SOLVER_ATOL_M3', 1.):
            errors = [max(abs(a-b) for a, b in zip(composed(args, count), expected))
                      for count in (1, 2, 4)]
        self.assertTrue(all(e > 0 for e in errors))
        for a, b in zip(errors, errors[1:]):
            self.assertGreater(math.log2(a/b), 3.5, errors)

    def test_initial_zero_suspension_can_acquire_supplied_solid(self):
        args = request(suspended_solid_m3=0., mixture_export_m3_year=1.)
        r = p.advance_pool(**args)
        self.assertGreater(r['suspended_solid_m3'], 0.)
        self.assertGreater(r['deposited_solid_m3'], 0.)
        self.assert_close(values(r), decimal_reference(args, 1024))

    def test_stiff_settling_rejects_negative_trials_without_clipping(self):
        args = request(liquid_m3=10., suspended_solid_m3=1., area_m2=1.,
                       liquid_input_m3_year=0., solid_input_m3_year=0., settling_m_year=100.)
        r = p.advance_pool(**args)
        self.assertGreater(r['rejected_steps'], 0)
        self.assertGreater(r['suspended_solid_m3'], 0.)
        self.assertGreater(r['deposited_solid_m3'], 0.)
        self.assertEqual(r['liquid_m3'], 10.)
        self.assert_ledgers(r)

    def test_depletion_outside_fixed_set_fails_explicitly(self):
        args = request(liquid_m3=.1, suspended_solid_m3=.001, liquid_input_m3_year=0.,
                       solid_input_m3_year=0., mixture_export_m3_year=2.)
        with patch.object(p, 'MAX_EVALUATIONS', 1024):
            with self.assertRaises(p.ContinuousPoolError):
                p.advance_pool(**args)

    def test_json_repeat_determinism_and_no_algorithm_filesystem_io(self):
        args = request(mixture_export_m3_year=1.)
        with patch('builtins.open', side_effect=AssertionError('pure algorithm must not open files')):
            first = p.advance_pool(**args)
            second = p.advance_pool(**args)
        self.assertEqual(first, second)
        self.assertEqual(json.loads(json.dumps(first, allow_nan=False)), first)
        self.assertLessEqual(first['evaluations'], first['bounds']['evaluations'])

    def test_invalid_types_ranges_and_nonfinite_values_are_controlled(self):
        for key in request():
            for bad in (True, None, '1', math.nan, math.inf, -1., 10**1000):
                with self.subTest(key=key, bad=str(bad)[:10]), self.assertRaises(p.ContinuousPoolError):
                    p.advance_pool(**request(**{key:bad}))
        with self.assertRaises(p.ContinuousPoolError):
            p.advance_pool(**request(area_m2=0.))

    def test_suspension_requires_initial_and_supplied_carrier_water(self):
        for update in ({'liquid_m3':0.}, {'liquid_input_m3_year':0.}):
            with self.assertRaisesRegex(p.ContinuousPoolError, 'carrier'):
                p.advance_pool(**request(**update))

    def test_derived_overflow_and_positive_underflow_fail(self):
        cases = ({'area_m2':1e308, 'settling_m_year':1e308},
                 {'area_m2':1e-308, 'settling_m_year':1e-308},
                 {'liquid_input_m3_year':1e308, 'dt_years':1e308},
                 {'solid_input_m3_year':1e-308, 'dt_years':1e-308},
                 {'liquid_m3':1e308, 'suspended_solid_m3':1e308})
        for update in cases:
            with self.subTest(update=update), self.assertRaises(p.ContinuousPoolError):
                p.advance_pool(**request(**update))

    def test_evaluation_attempt_and_cooperative_wall_bounds(self):
        for name in ('MAX_EVALUATIONS', 'MAX_ATTEMPTS'):
            with patch.object(p, name, 0), self.assertRaisesRegex(p.ContinuousPoolError, 'envelope'):
                p.advance_pool(**request())
        with patch.object(p.time, 'monotonic', side_effect=[0., 31.]):
            with self.assertRaisesRegex(p.ContinuousPoolError, 'wall-time'):
                p.advance_pool(**request())

    def test_every_controlled_error_attaches_accurate_work_counts(self):
        with self.assertRaises(p.ContinuousPoolError) as caught:
            p.advance_pool(**request(liquid_m3=True))
        self.assertEqual(caught.exception.evaluations, 0)
        self.assertEqual(caught.exception.attempts, 0)
        with patch.object(p, 'MAX_EVALUATIONS', 1):
            with self.assertRaisesRegex(p.ContinuousPoolError, 'evaluation envelope') as caught:
                p.advance_pool(**request())
        self.assertEqual(caught.exception.evaluations, 2)
        self.assertEqual(caught.exception.attempts, 1)
        with patch.object(p, 'MAX_ATTEMPTS', 0):
            with self.assertRaisesRegex(p.ContinuousPoolError, 'attempt envelope') as caught:
                p.advance_pool(**request())
        self.assertEqual(caught.exception.evaluations, 0)
        self.assertEqual(caught.exception.attempts, 1)

    def test_signed_ledger_retains_sub_ulp_component_residual(self):
        # Rounded final S+D equals S, but this must not conceal the separate D.
        large = float(2**54)
        self.assertEqual(large+1., large)
        result = p._balance((large, 1.), large, 0., 0.)
        self.assertEqual(result['residual_m3'], 1.)
        self.assertEqual(result['final_components_m3'], [large, 1.])


if __name__ == '__main__':
    unittest.main()
