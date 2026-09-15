"""Read the exact pinned Water-owner allocation oracle; no coefficients invented."""
import json
from . import irrigation as i, owner, provenance as p
from .quantities import q


def fixture():
    path = owner.WATER/'REFERENCE_R1.json'
    source = json.loads(p.checked(path, owner.PINS[path]))
    evidence, status = 'Pinned Water R21 declared numerical fixture, not Diadem grants', 'SYNTHETIC TEST'
    src, rec, clock = source['source'], source['returns'], source['clock']
    duration = q(clock['duration_seconds'])
    model = {'scenario_id': 'R21-WATER-REFERENCE', 'source_status': status, 'evidence': evidence,
        'priority_policy': i.POLICY, 'source': {'id': src['id'], 'initial_m3': src['initial_liquid_m3'],
            'capacity_m3': src['capacity_m3'], 'protected_m3': src['protected_nonwithdrawable_liquid_m3'],
            'cumulative_cap_m3': i.NO_CAP, 'overflow_destination': 'EXTERNAL_SOURCE_OVERFLOW',
            'evaporation_destination': 'EXTERNAL_ATMOSPHERE', 'other_receiver': src['other_receiver']},
        'receiver': {'id': rec['receiver_id'], 'initial_m3': rec['receiver_initial_m3'],
            'capacity_m3': rec['receiver_capacity_m3'], 'overflow_destination': 'EXTERNAL_DOWNSTREAM_OVERFLOW'},
        'connections': [], 'shared_groups': []}
    fractions = source['split_of_each_gross']
    for farm in source['farms']:
        model['connections'].append({'id': 'connection-'+farm['id'], 'plot_id': farm['id'],
            'source_id': src['id'], 'permission': 'PERMITTED', 'source_status': status, 'evidence': evidence,
            'cumulative_cap_m3': i.NO_CAP, 'shared_groups': [], 'return_receiver_id': rec['receiver_id'],
            'seep_delay_seconds': str(2*duration), 'bypass_delay_seconds': str(duration),
            'conveyance_evap_destination': 'EXTERNAL_ATMOSPHERE', 'pre_soil_evap_destination': 'EXTERNAL_ATMOSPHERE',
            **{name+'_fraction': fractions[name+'_fraction'] for name in i.FRACTIONS}})
    events = []
    for n in range(clock['periods']):
        events.append({'event_id': 'period-'+str(n), 'start_seconds': str(n*duration),
            'duration_seconds': str(duration), 'source_status': status, 'evidence': evidence,
            'arrivals': [{'id': 'arrival-'+str(n), 'source_id': src['id'], 'donor_id': 'EXPLICIT_EXTERNAL_BOUNDARY',
                'donor_debit_id': 'external-debit-'+str(n), 'available_at_seconds': str(n*duration),
                'volume_m3': src['incoming_m3'][n], 'source_status': status, 'evidence': evidence}],
            'evaporation_request_m3': src['evaporation_request_m3'][n],
            'environment_request_m3': src['environment_release_request_m3'][n],
            'other_request_m3': src['other_service_request_m3'][n],
            'source_period_cap_m3': src['irrigation_shared_cap_m3_per_period'],
            'source_rate_cap_m3_s': i.NO_CAP, 'shared_caps': [],
            'requests': [{'id': farm['id']+'-request-'+str(n), 'connection_id': 'connection-'+farm['id'],
                'soil_request_m3': farm['soil_input_request_m3'][n],
                'permit_cap_m3': farm['permitted_gross_cap_m3_per_period'],
                'period_cap_m3': i.NO_CAP, 'rate_cap_m3_s': i.NO_CAP} for farm in source['farms']]})
    return model, events
