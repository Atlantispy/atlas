"""Focused connected reduced reference/cache and finite delayed-return checks."""
from copy import deepcopy
from fractions import Fraction as F
from pathlib import Path
import tempfile
import time
import unittest

from work.generator_upgrade_r21 import pipeline, reduced_reference, returns


class PipelineTests(unittest.TestCase):
    measurement = None

    def test_source_bound_reuse_food_only_invalidation_and_common_guards(self):
        scenario = reduced_reference.scenario('seasonal')
        untouched = deepcopy(scenario)
        parent = Path(__file__).resolve().parents[1]/'c21-tests'
        parent.mkdir(exist_ok=True)
        # Explicitly short, new, isolated root. Never uses the user's live cache.
        with tempfile.TemporaryDirectory(prefix='', dir=parent) as temporary:
            root = Path(temporary)
            self.assertEqual(list(root.iterdir()), [])
            begun = time.perf_counter()
            cold = pipeline.run(scenario, cache_root=root)
            cold_seconds = time.perf_counter()-begun
            begun = time.perf_counter()
            warm = pipeline.run(scenario, cache_root=root)
            warm_seconds = time.perf_counter()-begun
            self.assertEqual(scenario, untouched)
            self.assertEqual(cold['scientific']['status'], 'MODELLED')
            self.assertEqual(cold['scientific'], warm['scientific'])
            self.assertEqual(cold['scientific_sha256'], warm['scientific_sha256'])
            self.assertEqual([row['stage'] for row in cold['reporting']], ['land', 'reduced-season', 'food'])
            self.assertTrue(all(row['hit'] is False for row in cold['reporting']))
            self.assertTrue(all(row['hit'] is True for row in warm['reporting']))
            self.assertTrue(all(not row['warnings'] for run in (cold, warm) for row in run['reporting']))

            changed = deepcopy(scenario)
            changed['food']['windows'][-1]['obligations'][0]['amount'] = '3000'
            food_only = pipeline.run(changed, cache_root=root)
            self.assertEqual(food_only['scientific']['status'], 'MODELLED')
            self.assertEqual({row['stage']: row['hit'] for row in food_only['reporting']},
                             {'land': True, 'reduced-season': True, 'food': False})
            self.assertEqual(cold['scientific']['land'], food_only['scientific']['land'])
            self.assertEqual(cold['scientific']['production'], food_only['scientific']['production'])
            self.assertNotEqual(cold['scientific']['food'], food_only['scientific']['food'])
            self.assertNotEqual(cold['scientific_sha256'], food_only['scientific_sha256'])
            self.assertTrue(all(not row['warnings'] for row in food_only['reporting']))

            bad = deepcopy(scenario)
            bad['context']['scenario_id'] = 'different-scenario'
            with self.assertRaisesRegex(ValueError, 'scenario mismatch'):
                pipeline.run(bad, cache_root=root)
            bad = deepcopy(scenario)
            bad['plans'][0]['area_m2'] = '4'
            with self.assertRaisesRegex(ValueError, 'planted area differs'):
                pipeline.run(bad, cache_root=root)

            # Raw single matched pair; no timing threshold or claimed guaranteed
            # improvement. Root's verifier may persist this separate from science.
            type(self).measurement = {
                'scope': 'ONE_FRESH_REDUCED_REFERENCE_COLD_WARM_PAIR_IN_NEW_ISOLATED_CACHE',
                'cold_seconds': cold_seconds, 'warm_seconds': warm_seconds,
                'seconds_saved': cold_seconds-warm_seconds,
                'percent_saved': 100*(cold_seconds-warm_seconds)/cold_seconds,
                'cold_stage_hits': sum(row['hit'] for row in cold['reporting']),
                'warm_stage_hits': sum(row['hit'] for row in warm['reporting']),
                'cold_stage_count': len(cold['reporting']), 'warm_stage_count': len(warm['reporting']),
                'cold_reporting': deepcopy(cold['reporting']),
                'warm_reporting': deepcopy(warm['reporting']),
                'food_change_reporting': deepcopy(food_only['reporting']),
                'scientific_sha256': cold['scientific_sha256'],
                'scientific_equal': True,
            }

    def test_finite_delayed_returns_keep_water_heat_and_horizon_inventory(self):
        def parcel(ident, created, water, heat):
            return {'id': ident, 'source_use_id': 'use-'+ident, 'source_input_sha256': 'a'*64,
                    'created_at_seconds': str(created), 'water_m3': str(water), 'enthalpy_j': str(heat)}

        parcels = [parcel('first', 0, 2, 20), parcel('second', 1, 2, 40), parcel('pending', 4, 1, 50)]
        untouched = deepcopy(parcels)
        arguments = {'receiver_id': 'downstream-only', 'capacity_m3': '3', 'delay_seconds': '2',
                     'overflow_destination': 'external-overflow',
                     'horizon_seconds': '4', 'evidence': 'explicit synthetic finite adiabatic return parcels',
                     'source_status': 'SYNTHETIC TEST'}
        result = returns.route(parcels, **arguments)
        self.assertEqual(parcels, untouched)
        self.assertEqual(result['status'], 'COLLECTED')
        self.assertEqual(result['delivered_ids'], ['first', 'second'])
        self.assertEqual(result['receiver_m3'], '3')
        self.assertEqual(result['receiver_enthalpy_j'], '45')
        self.assertEqual(result['overflow_m3'], '1')
        self.assertEqual(result['overflow_enthalpy_j'], '15')
        self.assertEqual(result['pending_m3'], '1')
        self.assertEqual(result['pending_enthalpy_j'], '50')
        self.assertEqual(result['pending_returns'][0]['arrival_at_seconds'], '6')
        self.assertEqual(F(result['receiver_m3'])+F(result['overflow_m3'])+F(result['pending_m3']), 5)
        self.assertEqual(F(result['receiver_enthalpy_j'])+F(result['overflow_enthalpy_j'])+F(result['pending_enthalpy_j']), 110)
        self.assertEqual(result['water_residual_m3'], '0')
        self.assertEqual(result['enthalpy_residual_j'], '0')
        self.assertIs(result['upstream_reuse_allowed'], False)
        self.assertIs(result['thermal_evolution_modelled'], False)

        early = returns.route(parcels[:1], **dict(arguments, horizon_seconds='1'))
        self.assertEqual(early['delivered_ids'], [])
        self.assertEqual((early['pending_m3'], early['pending_enthalpy_j']), ('2', '20'))
        later = returns.route(parcels, **dict(arguments, horizon_seconds='6'))
        self.assertEqual(later['pending_returns'], [])
        self.assertEqual(F(later['receiver_enthalpy_j']), F(285, 4))
        self.assertEqual(F(later['overflow_enthalpy_j']), F(155, 4))
        for extra in (deepcopy(parcels[0]), dict(parcels[0], id='renamed')):
            with self.subTest(duplicate=extra['id']), self.assertRaisesRegex(ValueError, 'already collected'):
                returns.route(parcels+[extra], **arguments)
        with self.assertRaisesRegex(ValueError, 'future'):
            returns.route(parcels, **dict(arguments, horizon_seconds='3'))
        with self.assertRaisesRegex(ValueError, 'without a water parcel'):
            returns.route([parcel('empty', 0, 0, 1)], **arguments)


if __name__ == '__main__':
    unittest.main()
