"""Source-bound seasonal PFT activity projection, not species phenology.

All water quantities are the retained R8 *available-water* counterfactual
reservoir, not measured pore water, Richards pressure, growth or food biomass.
"""
from copy import deepcopy
from fractions import Fraction as F
import hashlib
import json
import math
import re

KNOWN = {'CANON', 'WORKING NON-CANON', 'MODELLED', 'SYNTHETIC TEST'}
SOURCE_STATUSES = KNOWN | {'UNKNOWN', 'CONFLICT', 'INCOMPLETE'}
SCHEMA = 'diadem.pft-seasonal-activity.r10'
WATER_SCOPE = ('Numerical periodic-initial-state bracket of the retained linear '
               'available-water reservoir; not actual porewater or pressure. '
               'Different PFT/family experiments cannot be summed as simultaneous water use.')


def _text(value, name):
    if type(value) is not str or not value.strip() or len(value) > 4096:
        raise ValueError(name + ' requires bounded explicit text')
    return value


def _number(value, name, *, positive=False):
    if type(value) not in (int, float):
        raise ValueError(name + ' requires finite numeric input, not bool')
    try:
        value = float(value)
    except OverflowError as exc:
        raise ValueError(name + ' is unrepresentable') from exc
    if not math.isfinite(value) or value < 0 or (positive and value == 0):
        raise ValueError(name + ' requires a finite nonnegative value')
    return value


def _fraction(value, name, *, positive=False):
    if type(value) not in (str, int, float, F) or (type(value) is str and len(value) > 4096):
        raise ValueError(name + ' requires a bounded rational quantity')
    try:
        q = F(value)
    except (ValueError, ZeroDivisionError, OverflowError) as exc:
        raise ValueError(name + ' is not finite rational data') from exc
    if max(q.numerator.bit_length(), q.denominator.bit_length()) > 4096 or (positive and q <= 0):
        raise ValueError(name + ' outside supported rational range')
    return q


def digest(value):
    """Exact canonical JSON identity of the supplied actual producer record."""
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                    ensure_ascii=True, allow_nan=False).encode()).hexdigest()


def _bracket(a, b):
    return {'lower': min(a, b), 'upper': max(a, b)}


def _sum(rows, key):
    value = math.fsum(row[key] for row in rows)
    if not math.isfinite(value):
        raise ValueError('unrepresentable aggregate ' + key)
    return value


def _calendar(pft, supplied):
    inputs = pft.get('inputs')
    if type(inputs) is not dict or type(inputs.get('calendar')) is not dict:
        raise ValueError('actual R8 inputs/calendar required')
    calendar = inputs['calendar']
    _text(calendar.get('calendar_id'), 'calendar identity')
    _text(calendar.get('evidence'), 'calendar evidence')
    values = calendar.get('month_durations_seconds')
    if type(values) is not list or len(values) != 12:
        raise ValueError('twelve embedded exact month durations required')
    months = tuple(_fraction(v, 'month duration', positive=True) for v in values)
    day = _fraction(calendar.get('day_seconds'), 'day duration', positive=True)
    if sum(months, F()) != 365 * day:
        raise ValueError('retained reference calendar must have exactly365 supplied days')
    if supplied is not None:
        if type(supplied) not in (tuple, list) or len(supplied) != 12:
            raise ValueError('twelve supplied month durations required')
        if tuple(_fraction(v, 'supplied duration', positive=True) for v in supplied) != months:
            raise ValueError('external month calendar disagrees with actual producer')
    events = inputs.get('events')
    if type(events) is not list or not 12 <= len(events) <= 8192:
        raise ValueError('bounded complete actual R8 events required')
    seen = set(); last = 1; durations = [F() for _ in months]
    for row in events:
        if type(row) is not dict:
            raise ValueError('event must be an object')
        identity = _text(row.get('event_id'), 'event identity')
        month = row.get('month_id')
        if identity in seen or type(month) is not int or not last <= month <= 12:
            raise ValueError('event identities/chronology must be unique and calendar ordered')
        seen.add(identity); last = month
        durations[month-1] += _fraction(row.get('duration_seconds'), 'event duration', positive=True)
        if row.get('active') is not None and type(row['active']) is not bool:
            raise ValueError('activity requires an explicit bool or UNKNOWN')
        if row.get('source_status') not in SOURCE_STATUSES:
            raise ValueError('explicit event source status required')
        _text(row.get('evidence'), 'event evidence')
    if tuple(durations) != months:
        raise ValueError('event coverage must equal each complete exact month')
    return inputs, calendar, months, events


def _validate_water(pft, inputs, events):
    water = pft.get('water')
    if type(water) is not dict or water.get('status') not in {
            'MODELLED_PERIODIC_BRACKET', 'UNKNOWN', 'OUTSIDE_REGIME', 'NUMERICAL_FAILURE'}:
        raise ValueError('actual R8 water status required')
    if water['status'] != 'MODELLED_PERIODIC_BRACKET':
        return water, None
    capacity = inputs.get('capacity')
    if type(capacity) is not dict or capacity.get('source_status') not in KNOWN:
        raise ValueError('modelled water cannot have unresolved capacity evidence')
    if pft.get('source_status') not in KNOWN:
        raise ValueError('modelled water cannot have unresolved producer provenance')
    cap = _number(water.get('capacity_m'), 'water capacity', positive=True)
    if _number(capacity.get('capacity_m'), 'input capacity', positive=True) != cap:
        raise ValueError('water/input capacity mismatch')
    _text(capacity.get('support_id'), 'physical support identity')
    n = water.get('numerics')
    if type(n) is not dict:
        raise ValueError('actual solver numerical bounds required')
    atol = _number(n.get('flux_atol_m'), 'flux tolerance', positive=True)
    rtol = _number(n.get('relative_tolerance'), 'relative tolerance', positive=True)
    duration_atol = _number(n.get('duration_atol_s'), 'duration tolerance', positive=True)
    storage_atol = _number(n.get('storage_atol_m'), 'storage tolerance', positive=True)
    if rtol > .1 or max(atol, duration_atol, storage_atol) > 1e6:
        raise ValueError('numerical controls outside retained supported bounds')
    output = []
    for side in ('lower', 'upper'):
        cycle = water.get(side)
        if type(cycle) is not dict or type(cycle.get('events')) is not list or len(cycle['events']) != len(events):
            raise ValueError('complete lower and upper event trajectories required')
        rows = cycle['events']; previous = _number(cycle.get('initial_m'), 'cycle initial')
        residual = F(); duration_residual = F()
        for row, event in zip(rows, events):
            if event['source_status'] not in KNOWN or type(event['active']) is not bool:
                raise ValueError('modelled water cannot promote unknown forcing/activity')
            if type(row) is not dict or any(row.get(k) != event[k] for k in ('event_id', 'month_id', 'active')):
                raise ValueError('water event identity does not match actual forcing')
            exact_dt = _fraction(event['duration_seconds'], 'duration', positive=True)
            dt = _number(row.get('duration_seconds'), 'represented duration', positive=True)
            if _fraction(row.get('supplied_duration_seconds'), 'supplied duration', positive=True) != exact_dt:
                raise ValueError('water event duration changed support')
            dr = _fraction(row.get('duration_conversion_residual_s'), 'duration conversion residual')
            if F(dt)-exact_dt != dr or abs(float(dr)) > duration_atol+rtol*dt:
                raise ValueError('unreported or excessive duration representation change')
            for key in ('liquid_input_m_s', 'potential_transpiration_m_s'):
                if _number(row.get(key), key) != _number(event.get(key), 'forcing ' + key):
                    raise ValueError('water and input forcing disagree')
            for key in ('initial_m', 'final_m', 'input_m', 'potential_transpiration_m',
                        'actual_transpiration_m', 'overflow_m', 'capacity_m'):
                _number(row.get(key), key)
            if row['capacity_m'] != cap or row['initial_m'] != previous or max(row['initial_m'], row['final_m']) > cap:
                raise ValueError('storage chain/capacity mismatch')
            tolerance = atol+rtol*max(cap, row['input_m'], row['potential_transpiration_m'])
            if row['actual_transpiration_m'] > row['potential_transpiration_m']+tolerance:
                raise ValueError('actual transpiration exceeds supported demand')
            if row['input_m'] != row['liquid_input_m_s']*dt or row['potential_transpiration_m'] != row['potential_transpiration_m_s']*dt:
                raise ValueError('rate/integral identity mismatch')
            exact_residual = F(row['initial_m'])+F(row['liquid_input_m_s'])*F(dt)-F(row['final_m'])-F(row['actual_transpiration_m'])-F(row['overflow_m'])
            if exact_residual != _fraction(row.get('numerical_residual_m'), 'water residual') or abs(float(exact_residual)) > tolerance:
                raise ValueError('water ledger/residual mismatch')
            previous = row['final_m']; residual += exact_residual; duration_residual += dr
        if previous != cycle.get('final_m') or residual != _fraction(cycle.get('numerical_residual_m'), 'cycle residual'):
            raise ValueError('cycle water chain/ledger mismatch')
        if duration_residual != _fraction(cycle.get('duration_conversion_residual_s'), 'cycle duration residual'):
            raise ValueError('cycle duration ledger mismatch')
        for name, rowkey, selected in (
                ('input_m', 'input_m', rows), ('overflow_m', 'overflow_m', rows),
                ('all_potential_transpiration_m', 'potential_transpiration_m', rows),
                ('all_actual_transpiration_m', 'actual_transpiration_m', rows),
                ('active_potential_transpiration_m', 'potential_transpiration_m', [r for r in rows if r['active']]),
                ('active_actual_transpiration_m', 'actual_transpiration_m', [r for r in rows if r['active']])):
            if _number(cycle.get(name), name) != _sum(selected, rowkey):
                raise ValueError('cycle aggregate changed: '+name)
        output.append(rows)
    for a, b in zip(*output):
        if a['initial_m'] > b['initial_m']+storage_atol or a['final_m'] > b['final_m']+storage_atol:
            raise ValueError('inverted numerical initial-state bracket')
    return water, output


def seasonal_activity(pft_result, month_durations_seconds=None, *, source_id, source_sha256):
    """Project ONE actual R8 PFT/family/snow-member experiment into twelve months.

    source_sha256 is digest(pft_result), not a vague parent/package identifier.
    Source identity/pins and ecological family selection remain caller-owned.
    """
    if type(pft_result) is not dict or pft_result.get('schema') != 'diadem.pft-seasonal-admissibility.r8':
        raise ValueError('actual R8 seasonal PFT result required')
    _text(source_id, 'source context')
    if type(source_sha256) is not str or not re.fullmatch('[0-9a-f]{64}', source_sha256) or digest(pft_result) != source_sha256:
        raise ValueError('actual PFT payload identity mismatch')
    pft_id = _text(pft_result.get('pft_id'), 'PFT identity')
    if pft_result.get('status') not in {'PASS', 'FAIL', 'UNKNOWN', 'NUMERICAL_FAILURE'}:
        raise ValueError('ecological admissibility status required')
    if pft_result.get('source_status') not in SOURCE_STATUSES:
        raise ValueError('explicit producer source status required')
    inputs, calendar, durations, events = _calendar(pft_result, month_durations_seconds)
    if type(inputs.get('constraints')) is not dict or inputs['constraints'].get('pft_id') != pft_id:
        raise ValueError('PFT result/trait identity mismatch')
    water, trajectories = _validate_water(pft_result, inputs, events)
    if pft_result['status'] == 'NUMERICAL_FAILURE' and trajectories is not None:
        raise ValueError('contradictory numerical failure/modelled water status')
    months = []
    for month_id, duration in enumerate(durations, 1):
        selected = [e for e in events if e['month_id'] == month_id]
        known_activity = all(e['source_status'] in KNOWN and type(e['active']) is bool for e in selected)
        active = sum((_fraction(e['duration_seconds'], 'duration', positive=True) for e in selected if e['active'] is True), F()) if known_activity else None
        row = {'month_id': month_id, 'duration_seconds': str(duration),
               'activity_status': 'MODELLED_HYPOTHESIS' if known_activity else 'UNKNOWN',
               'physiological_active_duration_seconds': None if active is None else str(active),
               'physiological_active_fraction': None if active is None else float(active/duration),
               'event_ids': [e['event_id'] for e in selected],
               'water_status': water['status'], 'available_water': None,
               'dry_active_duration_s': None,
               'dry_duration_reason': 'UNKNOWN: actual R8 stores whole-cycle crossing summaries, not event/month dry intervals; no thresholding of average storage',
               'leaf_on': None, 'dormancy': None, 'flowering': None, 'growth_biomass_kg': None}
        if trajectories is not None:
            low, high = ([r for r in trajectory if r['month_id'] == month_id] for trajectory in trajectories)
            a = {'initial_storage_m': _bracket(low[0]['initial_m'], high[0]['initial_m']),
                 'final_storage_m': _bracket(low[-1]['final_m'], high[-1]['final_m']),
                 'capacity_m': water['capacity_m'],
                 'minimum_storage_m': _bracket(min(min(r['initial_m'], r['final_m']) for r in low), min(min(r['initial_m'], r['final_m']) for r in high)),
                 'maximum_storage_m': _bracket(max(max(r['initial_m'], r['final_m']) for r in low), max(max(r['initial_m'], r['final_m']) for r in high))}
            for key in ('input_m', 'potential_transpiration_m', 'actual_transpiration_m', 'overflow_m'):
                a[key] = _bracket(_sum(low, key), _sum(high, key))
            for key in ('potential_transpiration_m', 'actual_transpiration_m'):
                a['active_'+key] = _bracket(_sum([r for r in low if r['active']], key), _sum([r for r in high if r['active']], key))
            demand_low = a['active_potential_transpiration_m']['lower']; demand_high = a['active_potential_transpiration_m']['upper']
            if demand_low != demand_high:
                raise ValueError('numerical bracket changed supplied demand')
            a['active_actual_to_potential_transpiration_ratio'] = None if demand_low == 0 else _bracket(
                a['active_actual_transpiration_m']['lower']/demand_low,
                a['active_actual_transpiration_m']['upper']/demand_low)
            a['represented_demand_minus_actual_m'] = _bracket(
                float(sum((F(r['potential_transpiration_m'])-F(r['actual_transpiration_m']) for r in low), F())),
                float(sum((F(r['potential_transpiration_m'])-F(r['actual_transpiration_m']) for r in high), F())))
            a['numerical_residual_m'] = {side: str(sum((F(r['numerical_residual_m']) for r in rs), F())) for side, rs in (('lower_trajectory', low), ('upper_trajectory', high))}
            row['available_water'] = a
        months.append(row)
    cyclic = {'dry_active_duration_s': None, 'longest_cyclic_dry_active_spell_s': None,
              'threshold_fraction': inputs.get('constraints', {}).get('dry_stress_fraction'),
              'status': 'UNKNOWN', 'method': 'retained actual R8 active dry-crossing and circular-boundary diagnostics; not reclassified average stress'}
    if trajectories is not None:
        for source, target in (('dry_active_duration_s', 'dry_active_duration_s'),
                               ('longest_dry_active_spell_s', 'longest_cyclic_dry_active_spell_s')):
            values = [water[side].get(source) for side in ('lower', 'upper')]
            if any(v is None for v in values):
                if not all(v is None for v in values):
                    raise ValueError('inconsistent missing dry diagnostics')
                continue
            values = [_number(v, source) for v in values]
            if max(values) > float(sum(durations, F()))+water['numerics']['duration_atol_s']:
                raise ValueError('dry duration exceeds complete cycle')
            cyclic[target] = _bracket(*values)
        if cyclic['dry_active_duration_s'] is not None and cyclic['longest_cyclic_dry_active_spell_s'] is not None:
            if cyclic['threshold_fraction'] is None:
                raise ValueError('dry diagnostics need an explicit threshold')
            threshold = _number(cyclic['threshold_fraction'], 'dry threshold')
            if threshold > 1:
                raise ValueError('dry threshold exceeds storage fraction')
            for side in ('lower', 'upper'):
                if water[side]['longest_dry_active_spell_s'] > water[side]['dry_active_duration_s']+water['numerics']['duration_atol_s']:
                    raise ValueError('longest dry spell cannot exceed total dry-active duration')
            cyclic['status'] = 'MODELLED_RETAINED_DIAGNOSTIC'
    result = {'schema': SCHEMA, 'status': 'MODELLED_CONDITIONAL_ACTIVITY' if trajectories is not None else water['status'],
              'pft_id': pft_id, 'ecological_admissibility': pft_result['status'],
              'source_status': pft_result.get('source_status'),
              'source': {'context_id': source_id, 'pft_payload_sha256': source_sha256,
                         'producer_binding': deepcopy(pft_result.get('source_binding'))},
              'calendar': deepcopy(calendar), 'months': months, 'cyclic_drought': cyclic,
              'units': {'storage_and_water_integrals': 'm water depth over the same PFT support',
                        'duration': 's', 'fractions_and_ratios': '1'},
              'activity_semantics': 'Supplied physiological activation hypothesis, not leaf-on, dormancy, occurrence or growth',
              'water_semantics': WATER_SCOPE,
              'overflow_semantics': 'Unpartitioned available-water surplus; not routed runoff or recharge',
              'uncalculated': ['monthly dry-crossing duration', 'species leaf-on and dormancy',
                               'flowering, fruiting and reproduction', 'NPP, biomass and food supply',
                               'new thermal-time calculation from monthly means']}
    digest(result)  # no NaN or non-JSON quantities may escape
    return result


def species_phenology(roster):
    """Preserve actual owner plant constraints without inventing numerical traits."""
    if type(roster) is not dict or not 1 <= len(roster) <= 256:
        raise ValueError('bounded keyed biological roster required')
    rows = {}
    for key, row in sorted(roster.items()):
        if type(row) is not dict or row.get('organism_id') != key:
            raise ValueError('roster stable identity mismatch')
        _text(key, 'organism identity')
        if row.get('kind') != 'PLANT':
            continue
        _text(row.get('name'), 'plant name')
        if row.get('source_status') not in SOURCE_STATUSES or type(row.get('source_binding')) is not dict:
            raise ValueError('plant source status and exact owner binding required')
        if type(row.get('evidence')) not in (str, dict, list) or type(row.get('special_details')) is not dict:
            raise ValueError('actual owner evidence and qualitative details required')
        rows[key] = {'organism_id': key, 'name': row['name'], 'status': 'UNKNOWN',
                     'source_status': row['source_status'], 'source_binding': deepcopy(row['source_binding']),
                     'evidence': deepcopy(row['evidence']), 'qualitative_constraints': deepcopy(row['special_details']),
                     'leaf_on_windows': None, 'dormancy_windows': None, 'flowering_windows': None,
                     'fruiting_windows': None, 'seed_or_spore_release_windows': None,
                     'growth_or_reproduction_rates': None,
                     'reason': 'Qualitative owner constraints retained; numerical species phenology laws/parameters not supplied. No universal winter dormancy or reproductive season inferred.'}
    result = {'schema': 'diadem.plant-owner-phenology-status.r10', 'status': 'UNKNOWN',
              'roster_payload_sha256': digest(roster), 'plants': rows}
    digest(result)
    return result
