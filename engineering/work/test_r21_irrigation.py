"""One bounded arithmetic oracle; no water network or seasonal run."""
from copy import deepcopy
from fractions import Fraction as F
from itertools import permutations
import unittest

from work.generator_upgrade_r21 import irrigation


def water_reference():
    """Water REFERENCE_R1 assigned scalar oracle, not actual farms or grants."""
    model = {'scenario_id': 'water-owner-r21-three-period-synthetic',
        'source_status': 'WORKING NON-CANON', 'evidence': 'Irrigation_Water_R21/REFERENCE_R1.json',
        'priority_policy': irrigation.POLICY,
        'source': {'id': 'REF_SOURCE', 'initial_m3': '40', 'capacity_m3': '100',
            'protected_m3': '10', 'cumulative_cap_m3': irrigation.NO_CAP,
            'overflow_destination': 'EXTERNAL_SOURCE_OVERFLOW',
            'evaporation_destination': 'ATMOSPHERE', 'other_receiver': 'REF_OTHER_SERVICE_EXTERNAL'},
        'receiver': {'id': 'REF_DOWNSTREAM', 'initial_m3': '0', 'capacity_m3': '100',
            'overflow_destination': 'EXTERNAL_DOWNSTREAM_OVERFLOW'},
        'connections': [], 'shared_groups': [{'id': 'shared-conveyance',
                                            'cumulative_cap_m3': irrigation.NO_CAP}]}
    for key in ('A', 'B'):
        model['connections'].append({'id': 'connection-' + key, 'plot_id': 'REF_FARM_' + key,
            'source_id': 'REF_SOURCE', 'permission': 'PERMITTED', 'source_status': 'SYNTHETIC TEST',
            'evidence': 'REFERENCE_R1 explicit scenario permission and fractions',
            'cumulative_cap_m3': irrigation.NO_CAP, 'shared_groups': ['shared-conveyance'],
            'return_receiver_id': 'REF_DOWNSTREAM', 'seep_delay_seconds': '172800',
            'bypass_delay_seconds': '86400', 'conveyance_evap_destination': 'ATMOSPHERE',
            'pre_soil_evap_destination': 'ATMOSPHERE', 'field_gate_fraction': '4/5',
            'soil_boundary_fraction': '3/5', 'conveyance_evap_fraction': '1/20',
            'conveyance_seep_fraction': '3/20', 'pre_soil_evap_fraction': '1/25',
            'pre_soil_bypass_fraction': '4/25'})
    events = []
    for day, incoming in enumerate(('20', '0', '9')):
        start = str(day * 86400)
        events.append({'event_id': 'period-' + str(day + 1), 'start_seconds': start,
            'duration_seconds': '86400', 'source_status': 'SYNTHETIC TEST',
            'evidence': 'REFERENCE_R1 boundary-lumped scalar oracle',
            'arrivals': [{'id': 'arrival-' + str(day), 'source_id': 'REF_SOURCE',
                'donor_id': 'EXPLICIT_EXTERNAL_PULSE', 'donor_debit_id': 'pulse-' + str(day),
                'available_at_seconds': start, 'volume_m3': incoming,
                'source_status': 'SYNTHETIC TEST', 'evidence': 'REFERENCE_R1 prescribed external arrival'}],
            'evaporation_request_m3': '1', 'environment_request_m3': '5', 'other_request_m3': '3',
            'source_period_cap_m3': '30', 'source_rate_cap_m3_s': irrigation.NO_CAP,
            'shared_caps': [{'id': 'shared-conveyance', 'period_cap_m3': '30',
                             'rate_cap_m3_s': irrigation.NO_CAP}],
            'requests': [{'id': 'request-' + key, 'connection_id': 'connection-' + key,
                'soil_request_m3': '12', 'permit_cap_m3': '20',
                'period_cap_m3': irrigation.NO_CAP, 'rate_cap_m3_s': irrigation.NO_CAP}
                for key in ('A', 'B')]})
    return model, events


class IrrigationRationTests(unittest.TestCase):
    def test_proportional_ration_conservation_permutation_and_unknowns(self):
        rows = [
            {'request_id': key, 'plot_id': plot, 'source_id': 'finite-pool',
             'connection_id': 'connection-' + plot, 'requested_m3': amount}
            for key, plot, amount in [('request-A', 'A', '3'),
                                      ('request-B', 'B', '1'),
                                      ('request-zero', 'C', '0')]
        ]
        saved = deepcopy(rows)
        expected = irrigation.ration('2', rows)
        self.assertEqual(expected['allocation_ratio'], '1/2')
        self.assertEqual([row['allocated_m3'] for row in expected['allocations']],
                         ['3/2', '1/2', '0'])
        for ordered in permutations(rows):
            self.assertEqual(irrigation.ration('2', list(ordered)), expected)
        self.assertEqual(rows, saved)
        for stock in ['0', '2', '5']:
            with self.subTest(stock=stock):
                result = irrigation.ration(stock, rows)
                ledger = result['ledger']
                self.assertEqual(F(stock), F(ledger['allocated_m3']) +
                                 F(ledger['remaining_stock_m3']))
                self.assertEqual(F(ledger['requested_m3']), F(ledger['allocated_m3']) +
                                 F(ledger['unmet_m3']))
                self.assertEqual(ledger['stock_residual_m3'], '0')
                self.assertEqual(ledger['request_residual_m3'], '0')
                self.assertEqual([r['plot_id'] for r in result['allocations']], ['A', 'B', 'C'])
        first = irrigation.ration('5', rows)
        next_day = irrigation.ration(first['ledger']['remaining_stock_m3'], rows)
        self.assertEqual(next_day['allocation_ratio'], '1/4')
        self.assertEqual(irrigation.ration('2', [])['ledger']['remaining_stock_m3'], '2')
        self.assertEqual(irrigation.ration('0', [rows[-1]])['allocations'][0]['allocated_m3'], '0')
        for stock, bad in [(None, rows), ('-1', rows), ('2', rows + [rows[0]]),
                           ('2', [dict(rows[0], requested_m3='UNKNOWN')]),
                           ('2', [rows[0], dict(rows[1], source_id='other-pool')])]:
            with self.subTest(stock=stock, bad=bad):
                with self.assertRaises(ValueError):
                    irrigation.ration(stock, bad)

    def test_owner_finite_source_returns_caps_restart_and_missing_inputs(self):
        model, events = water_reference()
        initial = irrigation.initial_state(model)
        saved = deepcopy((model, events, initial))
        state, results = initial, []
        for event in events:
            result = irrigation.advance(model, state, event)
            self.assertEqual(result['status'], 'MODELLED')
            self.assertEqual(result['ledger']['residual_m3'], '0')
            results.append(result)
            state = result['state']
        self.assertEqual((model, events, initial), saved)
        for key, expected in [
                ('gross_withdrawal_m3', ['30', '2', '0']),
                ('source_end_m3', ['21', '10', '10']),
                ('receiver_end_m3', ['5', '74/5', '1231/50']),
                ('pending_return_m3', ['93/10', '128/25', '3/10']),
                ('soil_boundary_delivery_m3', ['18', '6/5', '0']),
                ('returns_arriving_m3', ['0', '24/5', '241/50'])]:
            self.assertEqual([row['ledger'][key] for row in results], expected, key)
        self.assertEqual(sum(F(row['ledger']['infrastructure_evap_m3']) for row in results), F('72/25'))
        # Production adapter reads the pinned owner fixture, whose superficial
        # IDs/status descriptions need not match this independent literal oracle.
        from work.generator_upgrade_r21.irrigation_reference import fixture
        actual_model, actual_events = fixture()
        actual_state = irrigation.initial_state(actual_model)
        for actual_event, expected in zip(actual_events, results):
            actual = irrigation.advance(actual_model, actual_state, actual_event)
            self.assertEqual(actual['ledger'], expected['ledger'])
            actual_state = actual['state']
        self.assertEqual(len(actual_events), len(results))
        restored = deepcopy(results[0]['state'])
        for event in events[1:]:
            resumed = irrigation.advance(model, restored, event)
            restored = resumed['state']
        self.assertEqual(resumed, results[-1])
        reversed_event = deepcopy(events[0])
        reversed_event['requests'].reverse()
        reversed_result = irrigation.advance(model, initial, reversed_event)
        self.assertEqual(reversed_result['allocations'], results[0]['allocations'])
        self.assertEqual(reversed_result['state'], results[0]['state'])
        with self.assertRaisesRegex(ValueError, 'duplicate irrigation event'):
            irrigation.advance(model, results[0]['state'], events[0])
        repeated = deepcopy(events[1])
        repeated['arrivals'][0]['donor_debit_id'] = events[0]['arrivals'][0]['donor_debit_id']
        with self.assertRaisesRegex(ValueError, 'duplicate producer'):
            irrigation.advance(model, results[0]['state'], repeated)
        asymmetric = deepcopy(events[0])
        asymmetric['requests'][0]['permit_cap_m3'] = '5'
        self.assertEqual([row['gross_withdrawal_m3'] for row in
                         irrigation.advance(model, initial, asymmetric)['allocations']], ['5', '20'])
        capped = deepcopy(events[0])
        capped['shared_caps'][0]['rate_cap_m3_s'] = '1/8640'
        self.assertEqual(irrigation.advance(model, initial, capped)['ledger']['gross_withdrawal_m3'], '10')
        capped['requests'][0]['rate_cap_m3_s'] = '1/86400'
        allocated = irrigation.advance(model, initial, capped)['allocations']
        self.assertEqual([row['gross_withdrawal_m3'] for row in allocated], ['10/21', '200/21'])
        for variant in ('PROHIBITED', 'UNKNOWN', 'ZERO_SOURCE'):
            changed, event = deepcopy(model), deepcopy(events[0])
            if variant == 'ZERO_SOURCE':
                changed['source']['initial_m3'] = '0'
                event['arrivals'] = []
            else:
                for row in changed['connections']:
                    row['permission'] = variant
            if variant == 'UNKNOWN':
                result = irrigation.advance(changed, initial, event)
                self.assertEqual(result['status'], 'INPUT_INCOMPLETE')
                self.assertEqual(result['state'], initial)
            else:
                result = irrigation.advance(changed, irrigation.initial_state(changed), event)
                self.assertEqual(result['ledger']['gross_withdrawal_m3'], '0')
                if variant == 'ZERO_SOURCE':
                    self.assertEqual(result['ledger']['source_end_m3'], '0')
                    self.assertEqual(result['ledger']['environment_unmet_m3'], '5')
        malformed = deepcopy(model)
        malformed['connections'][0]['soil_boundary_fraction'] = '1'
        with self.assertRaises(ValueError):
            irrigation.initial_state(malformed)


if __name__ == '__main__':
    unittest.main()
