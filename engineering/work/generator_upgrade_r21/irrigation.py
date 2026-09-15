"""Exact equal-priority rationing of contemporaneous, fixed-area requests.

This allocation decision is not a routed delivery, a permission, or a reservoir
model. The caller supplies one common-source stock and already-admitted requests
in source-debit gross m3, executes the withdrawals, and carries remaining stock.
Conveyance/application efficiencies and any connection limits are not invented
here. Native R11 withdrawals alone are sequential, not this rationing policy.
"""
from copy import deepcopy
from hashlib import sha256
import json

from .quantities import exact, ident, plain, q


SCHEMA = 'diadem.agriculture-proportional-ration.r21'
REQUEST_FIELDS = {
    'request_id', 'plot_id', 'source_id', 'connection_id', 'requested_m3',
}


def ration(stock, requests):
    """Allocate min(stock, sum(requests)) by exact contemporaneous proportions.

    Requests are explicit rows with REQUEST_FIELDS. All requests must draw from
    the same source; zero requests receive zero. Canonical ordering affects only
    the receipt, never priority. Unknown quantities fail closed. Conserved
    quantities, intermediate totals, and output shares retain the 8192-bit cap.
    """
    initial = q(stock, 'available source stock m3')
    if type(requests) is not list or len(requests) > 4096:
        raise ValueError('bounded explicit contemporaneous request list required')
    rows, seen, source, total = [], set(), None, q(0)
    for row in requests:
        exact(row, REQUEST_FIELDS, 'irrigation request')
        copied = {key: ident(row[key], key) for key in REQUEST_FIELDS - {'requested_m3'}}
        if copied['request_id'] in seen:
            raise ValueError('duplicate irrigation request_id')
        seen.add(copied['request_id'])
        if source is not None and copied['source_id'] != source:
            raise ValueError('one common source required per rationing call')
        source = copied['source_id']
        copied['requested_m3'] = q(row['requested_m3'], 'gross source request m3')
        total = q(total + copied['requested_m3'], 'total source request m3')
        rows.append(copied)
    ratio = q(min(initial, total) / total if total else 1, 'allocation ratio')
    allocated, unmet = q(0), q(0)
    for row in rows:
        row['allocated_m3'] = q(row['requested_m3'] * ratio, 'allocated source m3')
        row['unmet_m3'] = q(row['requested_m3'] - row['allocated_m3'], 'unmet source m3')
        allocated = q(allocated + row['allocated_m3'], 'total allocation m3')
        unmet = q(unmet + row['unmet_m3'], 'total unmet source m3')
    remaining = q(initial - allocated, 'remaining source stock m3')
    if allocated != min(initial, total) or total != allocated + unmet:
        raise ValueError('exact proportional allocation account failed')
    return plain({
        'schema': SCHEMA,
        'status': 'RATIONED_REQUESTS_NOT_ROUTED_DELIVERIES',
        'policy': 'CONTEMPORANEOUS_EQUAL_PRIORITY_GROSS_VOLUME',
        'volume_basis': 'SOURCE_DEBIT_M3',
        'source_id': source,
        'allocation_ratio': ratio,
        'allocations': sorted(rows, key=lambda row: row['request_id']),
        'ledger': {
            'initial_stock_m3': initial, 'requested_m3': total,
            'allocated_m3': allocated, 'unmet_m3': unmet,
            'remaining_stock_m3': remaining,
            'stock_residual_m3': initial - allocated - remaining,
            'request_residual_m3': total - allocated - unmet,
        },
        'scope': 'No area reselection, refill, return-flow credit, implicit storage, '
                 'permission inference, or claim of executed physical delivery.',
    })


# This explicit reduced transition is separate from the request-only primitive.
# It owns its finite scalar-water stores; it cannot import an unverified native
# output as new stock. The caller must bind/accept actual producer debit evidence.
TRANSITION_SCHEMA = 'diadem.finite-irrigation-transition.r21'
STATE_SCHEMA = 'diadem.finite-irrigation-state.r21'
NO_CAP = 'NO_ADDITIONAL_CAP'
POLICY = 'ENVIRONMENT_THEN_OTHER_THEN_CAPPED_PROPORTIONAL_IRRIGATION'
MODEL_FIELDS = {'scenario_id', 'source_status', 'evidence', 'priority_policy',
                'source', 'receiver', 'connections', 'shared_groups'}
SOURCE_FIELDS = {'id', 'initial_m3', 'capacity_m3', 'protected_m3',
                 'cumulative_cap_m3', 'overflow_destination',
                 'evaporation_destination', 'other_receiver'}
RECEIVER_FIELDS = {'id', 'initial_m3', 'capacity_m3', 'overflow_destination'}
FRACTIONS = ('field_gate', 'soil_boundary', 'conveyance_evap', 'conveyance_seep',
             'pre_soil_evap', 'pre_soil_bypass')
CONNECTION_FIELDS = {'id', 'plot_id', 'source_id', 'permission', 'source_status',
                    'evidence', 'cumulative_cap_m3', 'shared_groups',
                    'return_receiver_id', 'seep_delay_seconds', 'bypass_delay_seconds',
                    'conveyance_evap_destination', 'pre_soil_evap_destination'} | {
                    name + '_fraction' for name in FRACTIONS}
EVENT_FIELDS = {'event_id', 'start_seconds', 'duration_seconds', 'arrivals',
                'evaporation_request_m3', 'environment_request_m3', 'other_request_m3',
                'source_period_cap_m3', 'source_rate_cap_m3_s', 'shared_caps',
                'requests', 'source_status', 'evidence'}
EVENT_REQUEST_FIELDS = {'id', 'connection_id', 'soil_request_m3', 'permit_cap_m3',
                        'period_cap_m3', 'rate_cap_m3_s'}
ARRIVAL_FIELDS = {'id', 'source_id', 'donor_id', 'donor_debit_id',
                  'available_at_seconds', 'volume_m3', 'source_status', 'evidence'}
RETURN_FIELDS = {'id', 'source_event_id', 'connection_id', 'kind', 'receiver_id',
                 'volume_m3', 'created_at_seconds', 'arrival_at_seconds'}
STATE_FIELDS = {'schema', 'model_sha256', 'elapsed_seconds', 'source_m3',
                'receiver_m3', 'pending_returns', 'consumed_event_ids',
                'consumed_arrival_ids', 'consumed_return_ids', 'source_used_m3',
                'connection_used_m3', 'shared_used_m3'}
KNOWN_STATUS = {'CANON', 'WORKING NON-CANON', 'SYNTHETIC TEST'}


def _sha(value):
    return sha256(json.dumps(plain(value), sort_keys=True, separators=(',', ':'),
                            allow_nan=False).encode('utf-8')).hexdigest()


def _sum(values):
    result = q(0)
    for value in values:
        result = q(result + value, 'aggregate m3')
    return result


def _missing(value, path='input'):
    if value is None or (type(value) is str and value in {'UNKNOWN', 'INCOMPLETE', 'CONFLICT'}):
        return [path]
    if type(value) is dict:
        return [p for key, item in value.items() for p in _missing(item, path + '.' + str(key))]
    if type(value) is list:
        return [p for i, item in enumerate(value) for p in _missing(item, path + '[' + str(i) + ']')]
    return []


def _rows(rows, fields, label, maximum=256):
    if type(rows) is not list or len(rows) > maximum:
        raise ValueError('bounded explicit ' + label + ' list required')
    result = {}
    for row in rows:
        exact(row, fields, label)
        key = ident(row['id'], label + ' id')
        if key in result:
            raise ValueError('duplicate ' + label + ' id')
        result[key] = deepcopy(row)
    return result


def _status(row):
    if row['source_status'] not in KNOWN_STATUS:
        raise ValueError('unresolved or unsupported source status')
    ident(row['evidence'], 'source evidence')


def _cap(value, label, used=0):
    if value == NO_CAP:
        return None
    cap = q(value, label)
    if used > cap:
        raise ValueError('accepted cumulative use exceeds ' + label)
    return q(cap - used, label + ' remaining')


def _limit(*values):
    bounded = [value for value in values if value is not None]
    if not bounded:
        return None
    return min(bounded)


def _rate(value, duration):
    rate = _cap(value, 'rate cap m3/s')
    return None if rate is None else q(rate * duration, 'rate-duration cap m3')


def _model(model):
    missing = _missing(model, 'model')
    if missing:
        raise ValueError('INPUT_INCOMPLETE: ' + ', '.join(missing))
    exact(model, MODEL_FIELDS, 'irrigation model')
    _status(model)
    ident(model['scenario_id'], 'scenario id')
    if model['priority_policy'] != POLICY:
        raise ValueError('explicit supported allocation priority policy required')
    source, receiver = deepcopy(model['source']), deepcopy(model['receiver'])
    for row, fields, label in [(source, SOURCE_FIELDS, 'source'),
                               (receiver, RECEIVER_FIELDS, 'receiver')]:
        exact(row, fields, label)
        ident(row['id'], label + ' id')
        for key in fields - {'initial_m3', 'capacity_m3', 'protected_m3', 'cumulative_cap_m3'}:
            ident(row[key], label + ' ' + key)
        row['initial_m3'], row['capacity_m3'] = q(row['initial_m3']), q(row['capacity_m3'])
        if row['initial_m3'] > row['capacity_m3']:
            raise ValueError(label + ' initial stock exceeds capacity')
    if source['id'] == receiver['id']:
        raise ValueError('downstream receiver must be separate; no upstream return reuse')
    internal = {source['id'], receiver['id']}
    if any(source[key] in internal for key in
           ('overflow_destination', 'evaporation_destination', 'other_receiver')) or receiver['overflow_destination'] in internal:
        raise ValueError('external loss/service ports cannot alias internal stores')
    source['protected_m3'] = q(source['protected_m3'], 'protected stock')
    if source['protected_m3'] > source['capacity_m3']:
        raise ValueError('protected stock exceeds source capacity')
    _cap(source['cumulative_cap_m3'], 'source cumulative irrigation cap')
    groups = _rows(model['shared_groups'], {'id', 'cumulative_cap_m3'}, 'shared group')
    for group in groups.values():
        _cap(group['cumulative_cap_m3'], 'shared cumulative cap')
    connections = _rows(model['connections'], CONNECTION_FIELDS, 'connection')
    for row in connections.values():
        _status(row)
        for key in ('plot_id', 'source_id', 'return_receiver_id',
                    'conveyance_evap_destination', 'pre_soil_evap_destination'):
            ident(row[key], 'connection ' + key)
        if row['source_id'] != source['id'] or row['return_receiver_id'] != receiver['id']:
            raise ValueError('connection source/downstream receiver mismatch')
        if any(row[key] in internal for key in ('conveyance_evap_destination', 'pre_soil_evap_destination')):
            raise ValueError('evaporation port cannot alias internal storage')
        if row['permission'] not in {'PERMITTED', 'PROHIBITED'}:
            raise ValueError('explicit connection permission required')
        if type(row['shared_groups']) is not list or len(row['shared_groups']) > 256 or any(
                type(key) is not str for key in row['shared_groups']):
            raise ValueError('bounded explicit connection shared groups required')
        if len(set(row['shared_groups'])) != len(row['shared_groups']):
            raise ValueError('distinct explicit connection shared groups required')
        if not set(row['shared_groups']) <= set(groups):
            raise ValueError('unknown shared capacity group')
        _cap(row['cumulative_cap_m3'], 'connection cumulative cap')
        for name in FRACTIONS:
            key = name + '_fraction'
            row[key] = q(row[key], key)
            if row[key] > 1:
                raise ValueError('delivery fraction exceeds one')
        if _sum(row[name + '_fraction'] for name in FRACTIONS[1:]) != 1:
            raise ValueError('soil and separate infrastructure fractions must sum to one')
        if row['field_gate_fraction'] != _sum(row[name + '_fraction'] for name in
                                             ('soil_boundary', 'pre_soil_evap', 'pre_soil_bypass')):
            raise ValueError('field gate must equal its nested components')
        for key in ('seep_delay_seconds', 'bypass_delay_seconds'):
            row[key] = q(row[key], key, positive=True)
    return source, receiver, connections, groups


def initial_state(model):
    """Create declared initial stores; no native import, hidden stock or refill."""
    source, receiver, connections, groups = _model(model)
    return plain({'schema': STATE_SCHEMA, 'model_sha256': _sha(model),
        'elapsed_seconds': q(0), 'source_m3': source['initial_m3'],
        'receiver_m3': receiver['initial_m3'], 'pending_returns': [],
        'consumed_event_ids': [], 'consumed_arrival_ids': [], 'consumed_return_ids': [],
        'source_used_m3': q(0), 'connection_used_m3': {key: q(0) for key in connections},
        'shared_used_m3': {key: q(0) for key in groups}})


def _state(model, state, source, receiver, connections, groups):
    exact(state, STATE_FIELDS, 'irrigation state')
    if state['schema'] != STATE_SCHEMA or state['model_sha256'] != _sha(model):
        raise ValueError('irrigation state model binding mismatch')
    result = deepcopy(state)
    for key in ('elapsed_seconds', 'source_m3', 'receiver_m3', 'source_used_m3'):
        result[key] = q(result[key], key)
    if result['source_m3'] > source['capacity_m3'] or result['receiver_m3'] > receiver['capacity_m3']:
        raise ValueError('irrigation state exceeds finite capacity')
    for key in ('consumed_event_ids', 'consumed_arrival_ids', 'consumed_return_ids'):
        ids = result[key]
        if type(ids) is not list or len(ids) > 16384 or any(type(item) is not str for item in ids):
            raise ValueError('bounded explicit consumed identity list required')
        if len(set(ids)) != len(ids):
            raise ValueError('duplicate consumed identity')
        for item in ids:
            ident(item)
    for key, known in [('connection_used_m3', connections), ('shared_used_m3', groups)]:
        if type(result[key]) is not dict or set(result[key]) != set(known):
            raise ValueError('complete cumulative-use state required')
        result[key] = {k: q(v, key) for k, v in result[key].items()}
        for k, row in known.items():
            _cap(row['cumulative_cap_m3'], key, result[key][k])
    if result['source_used_m3'] != _sum(result['connection_used_m3'].values()):
        raise ValueError('source/connection cumulative-use mismatch')
    for key in groups:
        if result['shared_used_m3'][key] != _sum(result['connection_used_m3'][k]
                for k, row in connections.items() if key in row['shared_groups']):
            raise ValueError('shared cumulative-use mismatch')
    _cap(source['cumulative_cap_m3'], 'source cumulative cap', result['source_used_m3'])
    pending = _rows(result['pending_returns'], RETURN_FIELDS, 'pending return', 16384)
    for row in pending.values():
        if row['receiver_id'] != receiver['id'] or row['connection_id'] not in connections:
            raise ValueError('unbound pending return route')
        if row['source_event_id'] not in result['consumed_event_ids'] or row['id'] in result['consumed_return_ids']:
            raise ValueError('unbound or already-consumed pending return')
        if row['kind'] not in {'CONVEYANCE_SEEP', 'PRE_SOIL_BYPASS'}:
            raise ValueError('unsupported pending return kind')
        for key in ('volume_m3', 'created_at_seconds', 'arrival_at_seconds'):
            row[key] = q(row[key], key)
        if not row['volume_m3'] or row['created_at_seconds'] >= row['arrival_at_seconds']:
            raise ValueError('positive delayed return required')
        if row['created_at_seconds'] > result['elapsed_seconds'] or row['arrival_at_seconds'] < result['elapsed_seconds']:
            raise ValueError('pending return clock mismatch')
    result['pending_returns'] = list(pending.values())
    return result


def _joint(weights, constraints):
    """Equal fractions of individually capped gross requests, not raw demands.

    Freeze members of binding shared groups; other requests continue filling.
    """
    allocations = {key: q(0) for key in weights}
    active = {key for key in weights if weights[key]}
    for _ in range(len(weights) + len(constraints) + 1):
        if not active:
            return allocations
        candidates = [(weights[k] - allocations[k]) / weights[k] for k in active]
        for members, cap in constraints:
            denominator = _sum(weights[k] for k in members & active)
            if denominator:
                candidates.append((cap - _sum(allocations[k] for k in members)) / denominator)
        delta = q(min(candidates), 'joint allocation increment')
        for key in active:
            allocations[key] = q(allocations[key] + delta * weights[key], 'joint allocation')
        frozen = {key for key in active if allocations[key] == weights[key]}
        for members, cap in constraints:
            used = _sum(allocations[k] for k in members)
            if used > cap:
                raise ValueError('shared allocation cap exceeded')
            if used == cap:
                frozen |= members & active
        if not frozen:
            raise ValueError('joint allocation made no bounded progress')
        active -= frozen
    raise ValueError('joint allocation iteration bound exceeded')


def advance(model, state, event):
    """Pure boundary-lumped finite-water transition under the explicit policy.

    Exactly one event/cursor is consumed. Arrivals require paired donor-debit
    identities, whose source authenticity is an integrating-owner responsibility.
    Due returns cannot travel upstream. Soil-boundary exports are neither root
    entry nor crop consumption, and this scalar oracle makes no energy claim.
    """
    missing = _missing(model, 'model') + _missing(event, 'event')
    if missing:
        return {'schema': TRANSITION_SCHEMA, 'status': 'INPUT_INCOMPLETE',
                'missing': missing, 'state': deepcopy(state), 'allocations': [], 'ledger': None}
    source, receiver, connections, groups = _model(model)
    current = _state(model, state, source, receiver, connections, groups)
    exact(event, EVENT_FIELDS, 'irrigation event')
    _status(event)
    event_id = ident(event['event_id'], 'event id')
    if event_id in current['consumed_event_ids']:
        raise ValueError('duplicate irrigation event; cached outputs are not new supply')
    start, duration = q(event['start_seconds']), q(event['duration_seconds'], positive=True)
    if start != current['elapsed_seconds']:
        raise ValueError('irrigation event must continue accepted clock')
    end = q(start + duration, 'event end')
    initial = _sum([current['source_m3'], current['receiver_m3']] +
                   [row['volume_m3'] for row in current['pending_returns']])
    due, pending = [], []
    for row in current['pending_returns']:
        if row['arrival_at_seconds'] <= start:
            due.append(row)
        else:
            if row['arrival_at_seconds'] < end:
                raise ValueError('split interval at pending return arrival; no delayed borrowing')
            pending.append(row)
    returned = _sum(row['volume_m3'] for row in due)
    downstream = q(current['receiver_m3'] + returned)
    receiver_spill = max(q(0), downstream - receiver['capacity_m3'])
    downstream -= receiver_spill
    arrivals = _rows(event['arrivals'], ARRIVAL_FIELDS, 'external arrival', 4096)
    arrival_tokens = []
    incoming = q(0)
    for row in arrivals.values():
        _status(row)
        for key in ('source_id', 'donor_id', 'donor_debit_id'):
            ident(row[key], key)
        if row['source_id'] != source['id'] or row['donor_id'] in {source['id'], receiver['id']}:
            raise ValueError('external source arrival mapping invalid; no upstream return reuse')
        if q(row['available_at_seconds']) != start:
            raise ValueError('external arrival must be available at this boundary')
        # Bind both the producer transaction and arrival identity: renaming an
        # imported parcel cannot make the same donor debit spendable twice.
        token = 'arrival:' + _sha([row['donor_id'], row['donor_debit_id']])
        id_token = 'id:' + row['id']
        if any(t in current['consumed_arrival_ids'] or t in arrival_tokens for t in (token, id_token)):
            raise ValueError('duplicate producer arrival/debit')
        arrival_tokens.extend((token, id_token))
        incoming = q(incoming + q(row['volume_m3']), 'external arrivals')
    stock = q(current['source_m3'] + incoming)
    source_spill = max(q(0), stock - source['capacity_m3'])
    stock -= source_spill
    evaporation_request = q(event['evaporation_request_m3'])
    evaporation = min(stock, evaporation_request)
    stock -= evaporation
    environment_request, other_request = q(event['environment_request_m3']), q(event['other_request_m3'])
    environment = min(max(q(0), stock - source['protected_m3']), environment_request)
    stock -= environment
    downstream = q(downstream + environment)
    extra_spill = max(q(0), downstream - receiver['capacity_m3'])
    receiver_spill = q(receiver_spill + extra_spill)
    downstream -= extra_spill
    other = min(max(q(0), stock - source['protected_m3']), other_request)
    stock -= other
    shared = _rows(event['shared_caps'], {'id', 'period_cap_m3', 'rate_cap_m3_s'}, 'shared period cap')
    if set(shared) != set(groups):
        raise ValueError('complete shared period/rate caps required')
    requests = _rows(event['requests'], EVENT_REQUEST_FIELDS, 'irrigation event request')
    for row in requests.values():
        ident(row['connection_id'], 'request connection id')
    if len({row['connection_id'] for row in requests.values()}) != len(requests):
        raise ValueError('one contemporaneous request per connection required')
    weights, details = {}, {}
    for key, row in requests.items():
        if row['connection_id'] not in connections:
            raise ValueError('unknown irrigation connection')
        connection = connections[row['connection_id']]
        requested = q(row['soil_request_m3'])
        fraction = connection['soil_boundary_fraction']
        gross = q(requested / fraction, 'gross request') if fraction else (q(0) if not requested else None)
        cap = _limit(_cap(row['permit_cap_m3'], 'permitted gross cap'),
                     _cap(row['period_cap_m3'], 'individual period cap'),
                     _rate(row['rate_cap_m3_s'], duration),
                     _cap(connection['cumulative_cap_m3'], 'individual cumulative cap',
                          current['connection_used_m3'][connection['id']]))
        eligible = gross if gross is not None else q(0)
        if connection['permission'] == 'PROHIBITED':
            eligible = q(0)
        if cap is not None:
            eligible = min(eligible, cap)
        weights[key] = eligible
        details[key] = {'request_id': key, 'connection_id': connection['id'],
            'plot_id': connection['plot_id'], 'source_id': source['id'],
            'soil_request_m3': requested, 'requested_gross_m3': gross,
            'capped_gross_request_m3': eligible, 'permission': connection['permission'],
            'request_basis': 'SOIL_SURFACE_NOT_ROOT_ZONE',
            'zero_delivery_fraction': not bool(fraction)}
    source_cap = _limit(max(q(0), stock - source['protected_m3']),
        _cap(event['source_period_cap_m3'], 'source period cap'),
        _rate(event['source_rate_cap_m3_s'], duration),
        _cap(source['cumulative_cap_m3'], 'source cumulative cap', current['source_used_m3']))
    constraints = [(set(weights), source_cap)]
    for key, group in groups.items():
        cap = _limit(_cap(shared[key]['period_cap_m3'], 'shared period cap'),
                     _rate(shared[key]['rate_cap_m3_s'], duration),
                     _cap(group['cumulative_cap_m3'], 'shared cumulative cap', current['shared_used_m3'][key]))
        if cap is not None:
            members = {k for k, row in requests.items() if key in connections[row['connection_id']]['shared_groups']}
            constraints.append((members, cap))
    allocated = _joint(weights, constraints)
    gross_total, soil_total, infrastructure_evap = q(0), q(0), q(0)
    ports = []
    for key in sorted(requests):
        connection = connections[requests[key]['connection_id']]
        gross = allocated[key]
        row = details[key]
        row['gross_withdrawal_m3'] = gross
        for name in FRACTIONS:
            row[name + '_m3'] = q(gross * connection[name + '_fraction'], name)
        row['unmet_soil_request_m3'] = q(row['soil_request_m3'] - row['soil_boundary_m3'])
        row['transaction_id'] = 'irrigation:' + _sha([_sha(model), event_id, key, plain(row)])
        gross_total = q(gross_total + gross)
        soil_total = q(soil_total + row['soil_boundary_m3'])
        infrastructure_evap = q(infrastructure_evap + row['conveyance_evap_m3'] + row['pre_soil_evap_m3'])
        for kind, prefix, delay_key in [('CONVEYANCE_SEEP', 'conveyance_seep', 'seep_delay_seconds'),
                                         ('PRE_SOIL_BYPASS', 'pre_soil_bypass', 'bypass_delay_seconds')]:
            volume = row[prefix + '_m3']
            if volume:
                arrival = q(start + connection[delay_key], 'return arrival')
                if arrival < end:
                    raise ValueError('split event at generated return arrival; no same-period reuse')
                pending.append({'id': 'return:' + _sha([row['transaction_id'], kind]),
                    'source_event_id': event_id, 'connection_id': connection['id'],
                    'kind': kind, 'receiver_id': receiver['id'], 'volume_m3': volume,
                    'created_at_seconds': start, 'arrival_at_seconds': arrival})
        current['connection_used_m3'][connection['id']] = q(
            current['connection_used_m3'][connection['id']] + gross)
        for group in connection['shared_groups']:
            current['shared_used_m3'][group] = q(current['shared_used_m3'][group] + gross)
        for kind in ('conveyance_evap', 'pre_soil_evap'):
            ports.append({'kind': kind.upper(), 'destination': connection[kind + '_destination'],
                          'volume_m3': row[kind + '_m3'], 'transaction_id': row['transaction_id']})
    stock = q(stock - gross_total, 'source after withdrawal')
    current.update({'source_m3': stock, 'receiver_m3': downstream, 'elapsed_seconds': end,
        'source_used_m3': q(current['source_used_m3'] + gross_total),
        'pending_returns': sorted(pending, key=lambda row: (row['arrival_at_seconds'], row['id'])),
        'consumed_event_ids': current['consumed_event_ids'] + [event_id],
        'consumed_arrival_ids': sorted(current['consumed_arrival_ids'] + arrival_tokens),
        'consumed_return_ids': sorted(current['consumed_return_ids'] + [row['id'] for row in due])})
    final = _sum([stock, downstream] + [row['volume_m3'] for row in pending])
    exports = _sum([source_spill, receiver_spill, evaporation, other, soil_total, infrastructure_evap])
    if initial + incoming != final + exports:
        raise ValueError('finite irrigation system exact water account failed')
    # Revalidate every persisted number and resource/lineage bound before return.
    current = _state(model, plain(current), source, receiver, connections, groups)
    return plain({'schema': TRANSITION_SCHEMA, 'status': 'MODELLED',
        'scenario_id': model['scenario_id'], 'source_status': model['source_status'],
        'event_id': event_id, 'initial_state_sha256': _sha(state), 'event_sha256': _sha(event),
        'model_sha256': _sha(model), 'state': current,
        'allocations': [details[key] for key in sorted(details)],
        'arrivals': list(arrivals.values()), 'returns_arrived': due,
        'ports': ports + [
            {'kind': kind, 'destination': destination, 'volume_m3': amount}
            for kind, destination, amount in [
                ('SOURCE_OVERFLOW', source['overflow_destination'], source_spill),
                ('RECEIVER_OVERFLOW', receiver['overflow_destination'], receiver_spill),
                ('SOURCE_EVAP', source['evaporation_destination'], evaporation),
                ('OTHER_SERVICE', source['other_receiver'], other),
                ('ENVIRONMENT_INTERNAL_TRANSFER', receiver['id'], environment)]],
        'ledger': {'initial_inventory_m3': initial, 'external_arrival_m3': incoming,
            'final_inventory_m3': final, 'external_export_m3': exports, 'residual_m3': q(0),
            'source_end_m3': stock, 'receiver_end_m3': downstream,
            'pending_return_m3': _sum(row['volume_m3'] for row in pending),
            'returns_arriving_m3': returned, 'gross_withdrawal_m3': gross_total,
            'soil_boundary_delivery_m3': soil_total, 'infrastructure_evap_m3': infrastructure_evap,
            'source_evap_m3': evaporation, 'source_evap_unmet_m3': evaporation_request - evaporation,
            'environment_actual_m3': environment, 'environment_unmet_m3': environment_request - environment,
            'other_actual_m3': other, 'other_unmet_m3': other_request - other,
            'source_overflow_m3': source_spill, 'receiver_overflow_m3': receiver_spill},
        'scope': 'Exact scalar-liquid boundary allocation with finite downstream-only returns; '
            'not canal hydraulics, source energy, root-zone receipt, crop consumption or native producer authentication.'})
