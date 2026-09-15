"""Persistent R7 organic pools under explicit seasonal drivers, diagnostic only.

No geometry, mineral mass, porosity, hydraulic parameter or head is updated.
R7 is injected by the caller's exact source-bound graph, never imported here.
"""
from dataclasses import asdict, dataclass, is_dataclass
from fractions import Fraction as F
import hashlib
import json
import math
import re

KNOWN = {'CANON', 'WORKING NON-CANON', 'SYNTHETIC TEST'}
STATUSES = KNOWN | {'UNKNOWN', 'CONFLICT', 'INCOMPLETE'}
HOLDS = {'EVENT_START_SAMPLE_HELD', 'EVENT_END_SAMPLE_HELD',
         'EXPLICIT_INTERVAL_VALUE_HELD', 'UNKNOWN'}
SCHEMA = 'diadem.seasonal-organic-carbon.r10'
CHECKPOINT_SCHEMA = 'diadem.seasonal-organic-carbon-checkpoint.r10'


def plain(value):
    if isinstance(value, F): return str(value)
    if is_dataclass(value): return plain(asdict(value))
    if type(value) is dict:
        if any(type(k) is not str for k in value): raise ValueError('string object keys required')
        return {k: plain(v) for k, v in value.items()}
    if type(value) in (tuple, list): return [plain(v) for v in value]
    if value is None or type(value) in (str, int, bool): return value
    if type(value) is float and math.isfinite(value): return value
    raise ValueError('unsupported/nonfinite JSON representation')


def digest(value):
    return hashlib.sha256(json.dumps(plain(value), sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def _text(value, name):
    if type(value) is not str or not value.strip() or len(value) > 4096:
        raise ValueError(name + ' requires explicit bounded text')


def _hash(value, name):
    if type(value) is not str or re.fullmatch('[0-9a-f]{64}', value) is None:
        raise ValueError(name + ' requires exact lowercase SHA256')


def _q(value, name, *, positive=False):
    if type(value) not in (int, float, F) or (type(value) is float and not math.isfinite(value)):
        raise ValueError(name + ' requires a finite represented number, not bool')
    value = F(value)
    if value < 0 or (positive and value <= 0) or max(value.numerator.bit_length(), value.denominator.bit_length()) > 8192:
        raise ValueError(name + ' outside supported exact range')
    return value


@dataclass(frozen=True)
class Calendar:
    calendar_id: str
    month_durations_seconds: tuple
    day_seconds: F
    evidence: str

    def __post_init__(self):
        _text(self.calendar_id, 'calendar identity'); _text(self.evidence, 'calendar evidence')
        if type(self.month_durations_seconds) is not tuple or len(self.month_durations_seconds) != 12:
            raise ValueError('twelve explicit month durations required')
        months = tuple(_q(v, 'month duration', positive=True) for v in self.month_durations_seconds)
        day = _q(self.day_seconds, 'day duration', positive=True)
        if sum(months, F()) != 365*day:
            raise ValueError('representative calendar must have365 explicitly sized days')
        object.__setattr__(self, 'month_durations_seconds', months)
        object.__setattr__(self, 'day_seconds', day)


@dataclass(frozen=True)
class Event:
    event_id: str
    month_id: int
    layer_id: str
    support_id: str
    forcing: object
    moisture_hold: str
    water_sample_seconds_in_year: F | None
    evidence: str

    def __post_init__(self):
        for name in ('event_id', 'layer_id', 'support_id', 'evidence'):
            _text(getattr(self, name), name)
        if type(self.month_id) is not int or not 1 <= self.month_id <= 12:
            raise ValueError('month1..12 required')
        if type(self.moisture_hold) is not str or self.moisture_hold not in HOLDS:
            raise ValueError('explicit interval-held moisture interpretation required')
        if self.water_sample_seconds_in_year is not None:
            object.__setattr__(self, 'water_sample_seconds_in_year', _q(self.water_sample_seconds_in_year, 'sample time'))
        if self.moisture_hold == 'EXPLICIT_INTERVAL_VALUE_HELD' and self.water_sample_seconds_in_year is not None:
            raise ValueError('an explicitly supplied interval value has no claimed water-sample instant')
        if self.moisture_hold in {'EVENT_START_SAMPLE_HELD', 'EVENT_END_SAMPLE_HELD'} and self.water_sample_seconds_in_year is None:
            raise ValueError('sample-hold hypothesis requires its exact timestamp')


def _inventory(organic, initial, law, calendar, events, numerics):
    if type(initial) is not organic.OrganicState or type(law) is not organic.OrganicLaw or type(numerics) is not organic.Numerics:
        raise ValueError('actual injected organic state/law/numerics types required')
    if type(calendar) is not Calendar or type(events) is not tuple or not 12 <= len(events) <= 4096 or any(type(e) is not Event for e in events):
        raise ValueError('complete typed bounded twelve-month event inventory required')
    ids = set(); months = [F() for _ in range(12)]; last = 1; cursor = F()
    for event in events:
        if type(event.forcing) is not organic.OrganicForcing:
            raise ValueError('actual source-bound R7 forcing type required')
        if event.layer_id != initial.layer_id or event.support_id != initial.support_id:
            raise ValueError('forcing layer/physical support differs from retained pools')
        if event.event_id in ids or event.month_id < last:
            raise ValueError('unique events must remain in calendar chronology')
        dt = _q(event.forcing.duration_seconds, 'event duration', positive=True)
        if event.moisture_hold == 'EVENT_START_SAMPLE_HELD' and event.water_sample_seconds_in_year != cursor:
            raise ValueError('start-held water sample is not at this event start')
        if event.moisture_hold == 'EVENT_END_SAMPLE_HELD' and event.water_sample_seconds_in_year != cursor+dt:
            raise ValueError('end-held water sample is not at this event end')
        months[event.month_id-1] += dt; cursor += dt; last = event.month_id; ids.add(event.event_id)
    if tuple(months) != calendar.month_durations_seconds:
        raise ValueError('actual events must cover each exact complete month')


def _missing(initial, law, event, source_status):
    missing = []
    if source_status not in KNOWN: missing.append('seasonal_source_status:'+source_status)
    if initial.source_status not in KNOWN: missing.append('initial_pool_source_status:'+initial.source_status)
    if law.source_status not in KNOWN: missing.append('law_source_status:'+law.source_status)
    for name in ('fast_rate_per_s', 'slow_rate_per_s', 'fast_to_slow_fraction', 'carbon_fraction_dry_matter',
                 'reference_temperature_k', 'fast_activation_energy_j_mol', 'slow_activation_energy_j_mol', 'gas_constant_j_mol_k'):
        if getattr(law, name) is None: missing.append('law.'+name)
    forcing = event.forcing
    for name in ('fast_litter_carbon_kg_m2_s', 'slow_litter_carbon_kg_m2_s', 'soil_temperature_k', 'water_filled_pore_fraction'):
        if getattr(forcing, name) is None: missing.append('forcing.'+name)
    if forcing.source_status not in KNOWN: missing.append('forcing_source_status:'+forcing.source_status)
    for name in ('redox', 'regime'):
        if getattr(forcing, name) == 'UNKNOWN': missing.append('forcing.'+name)
    if event.moisture_hold == 'UNKNOWN': missing.append('moisture_hold')
    return missing


def _validate_step(organic, before, result, event, law):
    if type(result) is not dict or result.get('schema') != 'diadem.organic-carbon-snapshot.r7':
        raise ValueError('actual R7 organic result schema required')
    if result.get('status') != 'MODELLED': return
    after = result.get('state')
    if type(after) is not organic.OrganicState or (after.layer_id, after.support_id) != (before.layer_id, before.support_id):
        raise ValueError('returned carbon state has wrong layer/support/type')
    forcing = event.forcing
    if after.elapsed_seconds != before.elapsed_seconds+forcing.duration_seconds:
        raise ValueError('retained organic age did not advance by exact supplied duration')
    initial = before.fast_carbon_kg_m2+before.slow_carbon_kg_m2
    supplied = (forcing.fast_litter_carbon_kg_m2_s+forcing.slow_litter_carbon_kg_m2_s)*forcing.duration_seconds
    final = after.fast_carbon_kg_m2+after.slow_carbon_kg_m2
    carbon = result.get('carbon'); dry = result.get('organic_dry_matter')
    if type(carbon) is not dict or type(dry) is not dict:
        raise ValueError('actual carbon and separate dry-origin ledgers required')
    export = _q(carbon.get('exported_atmospheric_carbon_kg_m2'), 'exported carbon')
    if (carbon.get('initial_kg_m2'), carbon.get('input_kg_m2'), carbon.get('final_kg_m2'), carbon.get('residual_kg_m2')) != (initial, supplied, final, F()):
        raise ValueError('returned carbon ledger disagrees with actual initial/litter/final stocks')
    if initial+supplied != final+export:
        raise ValueError('independent represented carbon conservation failed')
    fraction = law.carbon_fraction_dry_matter
    expected = {'initial_kg_m2': initial/fraction, 'input_kg_m2': supplied/fraction,
                'final_kg_m2': final/fraction, 'decomposed_dry_matter_origin_kg_m2': export/fraction,
                'residual_kg_m2': F(), 'carbon_fraction_dry_matter': fraction}
    if any(dry.get(k) != v for k, v in expected.items()):
        raise ValueError('dry-origin mass is not consistently derived from the supplied carbon fraction')
    if result.get('layer_id') != before.layer_id or result.get('support_id') != before.support_id:
        raise ValueError('returned result identity mismatch')
    if result.get('final_organic_carbon_kg_m2') != final or result.get('final_organic_dry_mass_kg_m2') != final/fraction:
        raise ValueError('returned organic totals disagree with actual state')


def _aggregate(organic, start, end, rows, duration, fraction):
    initial = start.fast_carbon_kg_m2+start.slow_carbon_kg_m2
    final = end.fast_carbon_kg_m2+end.slow_carbon_kg_m2
    supplied = sum((F(r['producer_result']['carbon']['input_kg_m2']) for r in rows), F())
    exported = sum((F(r['producer_result']['carbon']['exported_atmospheric_carbon_kg_m2']) for r in rows), F())
    if initial+supplied != final+exported or end.elapsed_seconds-start.elapsed_seconds != duration:
        raise ValueError('independent interval carbon or age closure failed')
    return {'duration_seconds': duration, 'initial_state': organic.state_to_record(start),
            'end_state': organic.state_to_record(end),
            'carbon_kg_m2': {'initial': initial, 'input': supplied, 'final': final, 'exported_carbon_origin': exported, 'residual': F()},
            'dry_origin_kg_m2': {'initial': initial/fraction, 'input': supplied/fraction,
                               'final': final/fraction, 'decomposed_origin': exported/fraction, 'residual': F()},
            'geometry_feedback': 'NOT_APPLIED_DIAGNOSTIC_ONLY'}


def _checkpoint(organic, identity, state, rows, elapsed):
    value = {'schema': CHECKPOINT_SCHEMA, 'inputs_sha256': identity, 'completed_events': len(rows),
             'elapsed_seconds_in_year': str(elapsed), 'state': organic.state_to_record(state),
             'accepted_prefix_sha256': digest(rows)}
    return {**value, 'checkpoint_sha256': digest(value)}


def run_year(organic, initial_state, law, calendar, events, *, numerics,
             geometry_sha256, source_binding_sha256, scenario_id, evidence, source_status,
             stop_after=None, resume=None):
    """Advance one layer's retained pools through one explicit initial-value year.

    The source/geometry hashes are caller-bound evidence, not auto-discovered
    or auto-repinned files. Resume replays and verifies its accepted prefix;
    checksum-only or same-ID changed-state restoration is not accepted.
    """
    _text(evidence, 'seasonal evidence'); _text(scenario_id, 'scenario identity')
    _hash(geometry_sha256, 'geometry identity'); _hash(source_binding_sha256, 'source closure identity')
    if type(source_status) is not str or source_status not in STATUSES:
        raise ValueError('explicit seasonal source status required')
    _inventory(organic, initial_state, law, calendar, events, numerics)
    count = len(events)
    if stop_after is not None and (type(stop_after) is not int or not 0 <= stop_after <= count):
        raise ValueError('stop cursor must be an exact bounded event count')
    target = count if stop_after is None else stop_after
    inputs = {'initial_state': organic.state_to_record(initial_state), 'law': law, 'calendar': calendar,
              'events': events, 'numerics': numerics, 'geometry_sha256': geometry_sha256,
              'source_binding_sha256': source_binding_sha256, 'scenario_id': scenario_id,
              'evidence': evidence, 'source_status': source_status}
    identity = digest(inputs); resume_cursor = None
    if resume is not None:
        names = {'schema', 'inputs_sha256', 'completed_events', 'elapsed_seconds_in_year',
                 'state', 'accepted_prefix_sha256', 'checkpoint_sha256'}
        if type(resume) is not dict or set(resume) != names or resume.get('schema') != CHECKPOINT_SCHEMA:
            raise ValueError('exact carbon checkpoint schema required')
        expected = digest({k: v for k, v in resume.items() if k != 'checkpoint_sha256'})
        if resume['checkpoint_sha256'] != expected or resume['inputs_sha256'] != identity:
            raise ValueError('carbon checkpoint source/geometry/scenario/input identity changed')
        resume_cursor = resume['completed_events']
        if type(resume_cursor) is not int or not 0 <= resume_cursor <= target:
            raise ValueError('checkpoint cursor exceeds requested continuation')
        organic.state_from_record(resume['state'])  # strict native schema before replay
    rows = []; state = initial_state; elapsed = F(); halt = None; reason = None; missing = []; failed_producer = None
    month_starts = {}; states_after = {}
    for index in range(target+1):
        if resume_cursor == index:
            if _checkpoint(organic, identity, state, rows, elapsed) != resume:
                raise ValueError('carbon checkpoint does not reproduce the actual accepted prefix/state')
        if index == target: break
        event = events[index]; month_starts.setdefault(event.month_id, state)
        missing = _missing(state, law, event, source_status)
        if missing:
            halt = 'UNKNOWN'; reason = 'required seasonal carbon inputs unresolved'; break
        result = organic.advance_layer(state, (event.forcing,), law, numerics=numerics)
        _validate_step(organic, state, result, event, law)
        if result.get('status') != 'MODELLED':
            if result.get('status') not in {'UNKNOWN', 'OUTSIDE_REGIME', 'NUMERICAL_FAILURE'}:
                raise ValueError('unexpected actual organic outcome')
            halt = result['status']; reason = result.get('reason', 'organic advance failed')
            failed_producer = result
            break
        row = {'event_id': event.event_id, 'month_id': event.month_id, 'status': 'MODELLED',
               'start_seconds_in_year': elapsed, 'duration_seconds': event.forcing.duration_seconds,
               'represented_duration_residual_s': F(float(event.forcing.duration_seconds))-event.forcing.duration_seconds,
               'moisture_hold': event.moisture_hold, 'water_sample_seconds_in_year': event.water_sample_seconds_in_year,
               'initial_state': organic.state_to_record(state), 'producer_result': result}
        state = result['state']; elapsed += event.forcing.duration_seconds
        rows.append(row); states_after[event.month_id] = state
    if resume_cursor is not None and resume_cursor > len(rows):
        raise ValueError('saved accepted prefix cannot be reproduced through current unresolved/failing input')
    complete = halt is None and len(rows) == count
    status = halt or ('MODELLED_SEASONAL_CARBON_DIAGNOSTIC' if complete else 'STOPPED')
    public_events = list(rows)
    for index in range(len(rows), count):
        event = events[index]
        first_failure = halt is not None and index == len(rows)
        public_events.append({'event_id': event.event_id, 'month_id': event.month_id,
            'status': halt if first_failure else 'NOT_ADVANCED_PRIOR_GAP' if halt else 'NOT_ADVANCED_STOPPED',
            'reason': reason if halt else 'requested event cursor', 'missing_inputs': missing if first_failure else [],
            'producer_result': failed_producer if first_failure else None})
    months = {}; completed_months = 0
    for m, duration in enumerate(calendar.month_durations_seconds, 1):
        selected = [r for r in rows if r['month_id'] == m]
        expected = [e for e in events if e.month_id == m]
        if len(selected) == len(expected):
            months[str(m)] = {'month_id': m, 'status': 'MODELLED', **_aggregate(organic, month_starts[m], states_after[m], selected, duration, law.carbon_fraction_dry_matter)}
            completed_months += 1
        else:
            months[str(m)] = {'month_id': m, 'status': halt or 'STOPPED',
                             'completed_event_ids': [r['event_id'] for r in selected],
                             'carbon_kg_m2': None, 'dry_origin_kg_m2': None, 'end_state': None}
    annual = _aggregate(organic, initial_state, state, rows, sum(calendar.month_durations_seconds, F()), law.carbon_fraction_dry_matter) if complete else None
    output = {'schema': SCHEMA, 'status': status, 'source_status': 'WORKING NON-CANON',
        'inputs_sha256': identity, 'inputs': inputs, 'layer_id': initial_state.layer_id, 'support_id': initial_state.support_id,
        'scenario_id': scenario_id, 'geometry_sha256': geometry_sha256, 'source_binding_sha256': source_binding_sha256,
        'calendar_start_pool_age_seconds': initial_state.elapsed_seconds,
        'completed_events': len(rows), 'completed_months': completed_months, 'events': public_events, 'months': months,
        'annual': annual, 'final_state': organic.state_to_record(state) if complete else None,
        'checkpoint': _checkpoint(organic, identity, state, rows, elapsed) if halt is None else None,
        'reason': reason or 'persistent retained pools; one initial-value representative year, not periodic soil carbon',
        'missing_inputs': missing, 'geometry_feedback': 'NOT_APPLIED_DIAGNOSTIC_ONLY',
        'physical_invalidation': 'Changed organic stocks must not be used as a changed physical column with old geometry/porosity/heads; no feedback was applied.',
        'unmodelled': ['soil heat/freezing', 'redox prediction', 'litter production', 'NPK mineralisation/uptake',
                      'CO2/CH4 speciation', 'peat compaction', 'plant growth', 'soil material/hydraulic feedback'],
        'driver_support': 'explicit interval-held soil temperature/WFPS/litter/redox hypotheses, not time means or solved intrainterval history'}
    return plain(output)
