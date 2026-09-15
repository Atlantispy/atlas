"""Two tiny physical columns sharing a scarce declared irrigation source.

The 200-second numerical test is NOT a real crop season or a Diadem calibration.
The separate Water-owner oracle retains its original three daily volumes.
"""
from copy import deepcopy
from . import physical, irrigation_reference, irrigation


def scenario():
    template, _ = physical.reference_plan()
    model, water_events = irrigation_reference.fixture()
    evidence = 'SYNTHETIC TEST: two 1m2 fixed columns, 200-second numerical crop, scarce finite water; not agronomic calibration'
    status = 'SYNTHETIC TEST'
    context = dict(template['context'], world_id='SYNTHETIC_COLUMNS_NOT_DIADEM',
        snapshot_id='NUMERICAL_200_SECOND_CROP', scenario_id='R21-COUPLED-REFERENCE')
    plans, plots = [], []
    def rectangle(a, b):
        return {'type': 'Polygon', 'coordinates': [[[a, 0], [b, 0], [b, 1], [a, 1], [a, 0]]]}
    for n, identity in enumerate(('A', 'B')):
        plan = deepcopy(template)
        plan.update(plan_id='crop-'+identity, support_id=identity, irrigation_sink_id='surface-'+identity,
                    context=context, evidence=evidence)
        plans.append(plan)
        plots.append({'id': identity, 'geometry': rectangle(n, n+1), 'crop_ids': ['test-grain'],
            'management_permission': 'ALLOWED', 'evidence': evidence, 'source_status': status,
            'source_role': 'EXPLICIT_SYNTHETIC_FIXED_PLOT'})
    model.update(scenario_id=context['scenario_id'], evidence=evidence)
    model['source'].update(initial_m3='1/32768', capacity_m3='1', protected_m3='0')
    model['receiver'].update(initial_m3='0', capacity_m3='1')
    for connection, plan in zip(model['connections'], plans):
        connection.update(id='connection-'+plan['support_id'], plot_id=plan['support_id'],
                          seep_delay_seconds='200', bypass_delay_seconds='100', evidence=evidence)
    events, temperatures = [], {}
    for n in range(2):
        event = deepcopy(water_events[n])
        event.update(event_id='water-'+str(n), start_seconds=str(100*n), duration_seconds='100',
            arrivals=[], evaporation_request_m3='0', environment_request_m3='0', other_request_m3='0',
            source_period_cap_m3=irrigation.NO_CAP, evidence=evidence)
        for request, connection in zip(event['requests'], model['connections']):
            request.update(id='request-'+str(n)+'-'+connection['id'], connection_id=connection['id'],
                           soil_request_m3='1/100000', permit_cap_m3=irrigation.NO_CAP)
        events.append(event)
        temperatures[event['event_id']] = {row['id']: '281' for row in model['connections']}
    windows = []
    for identity, start, end in [('growing', 0, 200), ('after-harvest', 200, 300)]:
        claim = identity+'-consumption'
        windows.append({'id': identity, 'start_seconds': str(start), 'end_seconds': str(end),
            'obligations': [{'obligation_id': claim, 'node_id': 'test-settlement', 'bundle_id': 'grain-diet',
                'kind': 'recurring_consumption', 'recurrence': 'per_year', 'amount_unit': 'kcal',
                'amount': '1000', 'component_claim_ids': ['claim-'+claim], 'evidence': evidence, 'source_status': status}],
            'policies': [{'node_id': 'test-settlement', 'protected_order': ['recurring_consumption'],
                'obligation_order': [claim], 'block_export_on_shortfall': True, 'evidence': evidence}]})
    return {'context': context, 'terrain_generation': template['terrain_generation'],
        'source_status': status, 'evidence': evidence, 'engine': 'COUPLED_SOIL', 'plans': plans,
        'land': {'plots': plots, 'land_geometry': rectangle(0, 2),
            'exclusions': [{'id': 'explicit-empty-exclusion', 'geometries': [], 'rule': 'SYNTHETIC_EXCLUSION',
                'evidence': evidence, 'source_status': status}],
            'admission': {'scenario_id': context['scenario_id'], 'source_status': status, 'evidence': evidence,
                'land_complete': True, 'exclusions_complete': True,
                'required_exclusion_rules': ['SYNTHETIC_EXCLUSION'], 'forbidden_source_roles': []}},
        'water': {'model': model, 'events': events, 'delivery_temperatures_k': temperatures,
            'soil_returns': {'receiver_id': 'SEPARATE_SOIL_DOWNSTREAM', 'capacity_m3': '1',
                'delay_seconds': '100', 'overflow_destination': 'EXTERNAL_SOIL_RETURN_OVERFLOW',
                'evidence': evidence, 'source_status': status}},
        'food': {'windows': windows, 'bundles': [{'bundle_id': 'grain-diet',
            'components': [{'commodity_id': 'test-grain', 'energy_share': '1', 'edible_energy_kcal_kg': '3000',
                'composition_evidence': evidence}], 'energy_kcal_person_day': '1000', 'diet_evidence': evidence,
            'source_status': status}], 'calendar': {'days_per_year': '365', 'day_duration_seconds': '100', 'evidence': evidence},
            'evidence': evidence, 'source_status': status}}
