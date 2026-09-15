"""Authenticate finite source debits before unchanged coupled-soil execution."""
from copy import deepcopy
from fractions import Fraction as F
from . import irrigation, physical, returns, provenance as p
from .quantities import exact, ident, q, plain


def run(plans, water, *, stage):
    exact(water, ('model', 'events', 'delivery_temperatures_k', 'soil_returns'), 'coupled irrigation inputs')
    model, events = water['model'], water['events']
    if type(events) is not list or not 1 <= len(events) <= 366:
        raise ValueError('1..366 supplied common water/soil intervals required')
    by_plot = {plan['support_id']: plan for plan in plans}
    if len(by_plot) != len(plans):
        raise ValueError('duplicate physical cultivated support')
    connections = {row['id']: row for row in model['connections']}
    if len(connections) != len(model['connections']):
        raise ValueError('duplicate irrigation connection')
    if set(row['plot_id'] for row in connections.values()) != set(by_plot):
        raise ValueError('source connection must identify each and only committed crop support')
    if len(connections) != len(by_plot):
        raise ValueError('bounded adapter requires one declared source connection per plot')
    event_ids = [row['event_id'] for row in events]
    if len(set(event_ids)) != len(events) or set(water['delivery_temperatures_k']) != set(event_ids):
        raise ValueError('unique complete irrigation event/temperature inventory required')
    soil_rows = {}
    for support, plan in by_plot.items():
        if model['scenario_id'] != plan['context']['scenario_id'] or len(plan['events']) != len(events):
            raise ValueError('common water/soil scenario and interval coverage required')
        for index, (supplied, soil_event) in enumerate(zip(events, plan['events'])):
            start, end = q(supplied['start_seconds']), q(supplied['start_seconds'])+q(supplied['duration_seconds'], positive=True)
            if q(soil_event['start_seconds']) != start or q(soil_event['end_seconds']) != end:
                raise ValueError('water/soil event boundaries differ; supply explicit split, not guessed disaggregation')
            soil_rows[support, index] = soil_event
    state = irrigation.initial_state(model)
    initial_water = deepcopy(state)
    records, deliveries = [], {support: [] for support in by_plot}
    for index, event in enumerate(events):
        if {row['connection_id'] for row in event['requests']} != set(connections):
            raise ValueError('all competing plots must request together, including explicit zero')
        temperatures = water['delivery_temperatures_k'][event['event_id']]
        if type(temperatures) is not dict or set(temperatures) != set(connections):
            raise ValueError('explicit liquid temperature for each connection/event required')
        invocation = {'model': model, 'state': state, 'event': event}
        value = stage('water', invocation, lambda invocation=invocation: irrigation.advance(**invocation))
        if (value.get('model_sha256') != p.sha(model) or value.get('initial_state_sha256') != p.sha(state)
                or value.get('event_sha256') != p.sha(event)) and value['status'] == 'MODELLED':
            raise ValueError('accepted source transition differs from invoked model/state/event')
        records.append(value)
        if value['status'] != 'MODELLED':
            return {'status': value['status'], 'water_events': records, 'crops': [], 'joined_water': None}
        state = value['state']
        for allocation in value['allocations']:
            support = allocation['plot_id']; plan = by_plot[support]
            soil_event = soil_rows[support, index]
            temperature = q(temperatures[allocation['connection_id']], 'declared incoming liquid K', positive=True)
            delivery = {'event_id': soil_event['event_id'], 'support_id': support,
                'receiving_sink_id': plan['irrigation_sink_id'], 'start_seconds': soil_event['start_seconds'],
                'end_seconds': soil_event['end_seconds'], 'soil_boundary_m3': allocation['soil_boundary_m3'],
                'temperature_k': str(temperature), 'delivery_boundary': 'SURFACE_APPLICATION',
                'delivery_id': 'delivery:'+allocation['transaction_id'],
                'source_use_id': allocation['transaction_id'],
                'evidence': model['evidence']+'; executed finite source debit '+p.sha(value),
                'source_status': model['source_status']}
            # Zero delivered input has no physical water/energy parcel. Its
            # unmet request remains in the exact source allocation receipt.
            if q(allocation['soil_boundary_m3']):
                deliveries[support].append(delivery)
    results = [physical.run(plan, deliveries[plan['support_id']], cache_step=stage) for plan in plans]
    base = {'status': 'MODELLED', 'water_initial_state': initial_water, 'water_final_state': state,
        'water_events': records, 'crops': results, 'actual_deliveries': deliveries,
        'allocation_policy': model['priority_policy'], 'source_thermal_evolution_modelled': False,
        'source_temperature_role': 'EXPLICIT_ENERGY_BOUNDARY_SCENARIO_NOT_A_RESERVOIR_HEAT_SOLUTION'}
    if any(result.get('soil_status') != 'MODELLED' for result in results):
        return {**base, 'status': 'INCOMPLETE', 'joined_water': None, 'soil_returns': None}
    policy = water['soil_returns']
    exact(policy, ('receiver_id', 'capacity_m3', 'delay_seconds', 'overflow_destination', 'evidence', 'source_status'), 'soil return route')
    if policy['receiver_id'] in (model['source']['id'], model['receiver']['id']):
        raise ValueError('soil returns require their separate named downstream receiver; no double receiver inventory')
    parcels, unresolved, representation, energy_imports = [], [], [], []
    soil_initial = soil_final = baseline = upward = roots = exported = F(0)
    tolerance = F(0)
    for plan, result in zip(plans, results):
        area = q(plan['area_m2'], positive=True)
        rows = result['events']
        soil_initial += F(rows[0]['result']['ledger']['initial_storage_m'])*area
        soil_final += F(rows[-1]['result']['ledger']['final_storage_m'])*area
        for supplied, row in zip(plan['events'], rows):
            native = row['result']['ledger']; exports = row['actual_exports']
            baseline += F(supplied['soil_event']['surface_water_flux_m_s'])*F(supplied['soil_event']['duration_s'])*area
            upward += F(exports['bottom_upward_m3']); roots += F(exports['root_withdrawal_m3'])
            tolerance += F(plan['controls']['water_atol_m'])*area
            parent = p.sha({'source_input_sha256': result['source_input_sha256'], 'event': row})
            for kind, volume, heat in (
                ('surface', F(exports['surface_runoff_m3']), F(exports['surface_export_enthalpy_j'])),
                ('bottom', F(exports['bottom_downward_m3']), F(exports['bottom_net_advective_enthalpy_j']))):
                if not volume:
                    if kind == 'bottom' and F(exports['bottom_upward_m3']):
                        energy_imports.append({'support_id': plan['support_id'], 'event_id': row['event_id'],
                            'water_m3': exports['bottom_upward_m3'], 'enthalpy_j': str(-heat),
                            'boundary': 'SUPPLIED_LOWER_BOUNDARY_INFLOW_NOT_A_RETURN_EXPORT'})
                        continue
                    if heat:
                        representation.append({'support_id': plan['support_id'], 'event_id': row['event_id'],
                            'port': kind, 'zero_water_enthalpy_residual_j': str(heat)})
                        if abs(heat) > F(plan['controls']['energy_atol_j_m2'])*area:
                            raise ValueError('zero-water boundary energy exceeds unchanged native tolerance')
                    continue
                if heat < 0 or kind == 'bottom' and F(exports['bottom_upward_m3']):
                    unresolved.append({'support_id': plan['support_id'], 'event_id': row['event_id'],
                        'port': kind, 'water_m3': str(volume), 'enthalpy_j': None,
                        'reason': 'gross export enthalpy unresolved; no reusable parcel inferred'})
                    exported += volume
                    continue
                parcels.append({'id': 'soil-return:'+parent+':'+kind, 'source_use_id': parent+':'+kind,
                    'source_input_sha256': parent, 'created_at_seconds': row['end_seconds'],
                    'water_m3': str(volume), 'enthalpy_j': str(heat)})
    horizon = state['elapsed_seconds']
    args = dict(policy, parcels=parcels, horizon_seconds=horizon)
    collection = stage('soil-returns', args, lambda: returns.route(**args))
    water_initial = q(initial_water['source_m3'])+q(initial_water['receiver_m3'])
    water_final = q(state['source_m3'])+q(state['receiver_m3'])+sum((q(row['volume_m3']) for row in state['pending_returns']), F(0))
    external_in = sum((q(row['ledger']['external_arrival_m3']) for row in records), F(0))
    external_out = sum((q(row['ledger']['external_export_m3'])-q(row['ledger']['soil_boundary_delivery_m3']) for row in records), F(0))
    collected = q(collection['receiver_m3'])+q(collection['pending_m3'])
    outgoing = external_out+roots+q(collection['overflow_m3'])+exported
    incoming = water_initial+soil_initial+external_in+baseline+upward
    final = water_final+soil_final+collected
    residual = incoming-final-outgoing
    tolerance += sum((F(result['input_representation_absolute_bound_m3']) for result in results), F(0))
    if abs(residual) > tolerance:
        raise ValueError('joined source/soil/return water account exceeds unchanged native per-event tolerances')
    statuses = {result['status'] for result in results}
    status = 'MODELLED' if statuses == {'MODELLED'} else 'OUTSIDE_REGIME' if 'OUTSIDE_REGIME' in statuses else 'UNKNOWN'
    return plain({**base, 'status': status, 'soil_returns': collection, 'unrouted_actual_exports': unresolved,
        'boundary_energy_representation': representation,
        'bottom_boundary_energy_imports': energy_imports,
        'joined_water': {'initial_plus_external_in_m3': incoming, 'final_inventory_m3': final,
            'external_out_m3': outgoing, 'residual_m3': residual, 'native_error_budget_m3': tolerance,
            'nested_irrigation_counted_as_new_water': False,
            'soil_irrigation_delivery_is_internal_transfer': True},
        'downstream_reuse_allowed': False, 'source_or_return_thermal_evolution_modelled': False})
