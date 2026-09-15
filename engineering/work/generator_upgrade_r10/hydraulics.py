"""Actual R6 Richards states through explicit seasonal liquid/uptake events.

This is a fixed-geometry, unfrozen matrix-flow scenario. Monthly end states are
not monthly means, an aquifer, realised vegetation or resolved flood hydroperiod.
The caller supplies the exact source-bound R6 module; no legacy source is edited.
"""
from dataclasses import asdict, dataclass, is_dataclass
from fractions import Fraction as F
import hashlib
import json
import math

KNOWN = frozenset(('CANON', 'WORKING NON-CANON', 'SYNTHETIC TEST'))
STATUSES = KNOWN | {'UNKNOWN'}
LEDGER = ('surface_input_m', 'infiltration_m', 'rain_excess_runoff_m',
          'surface_exfiltration_m', 'surface_runoff_m', 'actual_et_m', 'potential_et_m',
          'bottom_downward_m', 'bottom_upward_m', 'root_zone_gross_downward_m',
          'root_zone_upward_capillary_m')


def plain(value):
    if isinstance(value, F): return str(value)
    if is_dataclass(value): return plain(asdict(value))
    if type(value) is dict:
        if any(type(k) is not str for k in value): raise ValueError('explicit string JSON keys required')
        return {k: plain(v) for k, v in value.items()}
    if type(value) in (tuple, list): return [plain(v) for v in value]
    if value is None or type(value) in (str, bool, int): return value
    if type(value) is float and math.isfinite(value): return value
    raise ValueError('unsupported/nonfinite JSON value')


def digest(value):
    return hashlib.sha256(json.dumps(plain(value), sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def text(value, name):
    if type(value) is not str or not value.strip() or len(value) > 4096:
        raise ValueError(name + ': explicit bounded text required')


def number(value, name, *, positive=False, signed=False, nullable=False, maximum=F(10**18)):
    if value is None and nullable: return None
    if type(value) not in (int, float, F) or (type(value) is float and not math.isfinite(value)):
        raise ValueError(name + ': finite explicit numeric value required')
    f = F(value)
    if max(f.numerator.bit_length(), f.denominator.bit_length()) > 4096 or abs(f) > maximum:
        raise ValueError(name + ': bounded represented number required')
    if (not signed and f < 0) or (positive and f <= 0) or (f and float(f) == 0):
        raise ValueError(name + ': outside supported range')
    return f


def provenance(evidence, status):
    text(evidence, 'evidence')
    if type(status) is not str or status not in STATUSES: raise ValueError('recognised source status required')


def _hash(value, name):
    if type(value) is not str or len(value) != 64 or any(c not in '0123456789abcdef' for c in value):
        raise ValueError(name + ': exact lowercase SHA256 required')


def _fields(value, keys, name):
    if type(value) is not dict or set(value) != set(keys): raise ValueError(name + ': exact fields required')


def _restore_state(solver, value):
    _fields(value, ('head_m', 'elapsed_seconds', 'column_sha256'), 'continuing state')
    if type(value['head_m']) is not list: raise ValueError('serialized head list required')
    return solver.State(tuple(value['head_m']), value['elapsed_seconds'], value['column_sha256'])


@dataclass(frozen=True)
class Calendar:
    calendar_id: str
    month_durations_seconds: tuple
    day_seconds: F
    evidence: str

    def __post_init__(self):
        text(self.calendar_id, 'calendar identity'); text(self.evidence, 'calendar evidence')
        if type(self.month_durations_seconds) is not tuple or len(self.month_durations_seconds) != 12:
            raise ValueError('twelve explicit ordered month durations required')
        durations = tuple(number(v, 'month duration', positive=True, maximum=F(10**9)) for v in self.month_durations_seconds)
        object.__setattr__(self, 'month_durations_seconds', durations)
        object.__setattr__(self, 'day_seconds', number(self.day_seconds, 'day duration', positive=True, maximum=F(10**7)))


@dataclass(frozen=True)
class Event:
    event_id: str
    month_id: int
    duration_seconds: F
    liquid_input_m_s: F | None
    potential_root_demand_m_s: F | None
    uptake: object
    boundary: object
    vegetation_hypothesis_id: str
    soil_thermal_regime: str
    thermal_evidence: str
    air_temperature_c: float | None
    evidence: str
    source_status: str

    def __post_init__(self):
        for name in ('event_id', 'vegetation_hypothesis_id', 'thermal_evidence'): text(getattr(self, name), name)
        provenance(self.evidence, self.source_status)
        if type(self.month_id) is not int or not 1 <= self.month_id <= 12: raise ValueError('explicit month 1..12 required')
        object.__setattr__(self, 'duration_seconds', number(self.duration_seconds, 'event duration', positive=True, maximum=F(10**9)))
        for name in ('liquid_input_m_s', 'potential_root_demand_m_s'):
            object.__setattr__(self, name, number(getattr(self, name), name, nullable=True, maximum=F(1)))
        if type(self.soil_thermal_regime) is not str or self.soil_thermal_regime not in {'UNFROZEN_CONDITIONAL', 'UNKNOWN'}:
            raise ValueError('explicit unfrozen conditional regime or UNKNOWN required; freeze/thaw is not modelled')
        temperature = number(self.air_temperature_c, 'air temperature', nullable=True, signed=True, maximum=F(200))
        object.__setattr__(self, 'air_temperature_c', None if temperature is None else float(temperature))


def _state_storage(solver, column, state):
    return sum((F(solver.hydraulic_properties(layer, head)[0])*F(layer.thickness_m)
                for layer, head in zip(column.layers, state.head_m)), F())


def _sum(rows, name):
    return sum((F(row['solver_result']['ledger'][name]) for row in rows), F())


def _aggregate(solver, column, start_state, end_state, rows, duration, budget_atol_m):
    ledger = {name: _sum(rows, name) for name in LEDGER}
    initial = _state_storage(solver, column, start_state); final = _state_storage(solver, column, end_state)
    supplied = sum((F(row['supplied_liquid_input_m']) for row in rows), F())
    supplied_demand = sum((F(row['supplied_potential_root_demand_m']) for row in rows), F())
    residual = initial+supplied+ledger['bottom_upward_m']-final-ledger['bottom_downward_m']-ledger['actual_et_m']-ledger['surface_runoff_m']
    if abs(residual) > F(budget_atol_m): raise ArithmeticError('independent accumulated physical water balance failed')
    n = len(column.layers)
    down = [sum((F(row['solver_result']['ledger']['face_downward_m'][i]) for row in rows), F()) for i in range(n+1)]
    up = [sum((F(row['solver_result']['ledger']['face_upward_m'][i]) for row in rows), F()) for i in range(n+1)]
    uptake = [sum((F(row['solver_result']['layers'][i]['et_m']) for row in rows), F()) for i in range(n)]
    layer_residuals = []
    for i, layer in enumerate(column.layers):
        a = F(solver.hydraulic_properties(layer, start_state.head_m[i])[0])*F(layer.thickness_m)
        b = F(solver.hydraulic_properties(layer, end_state.head_m[i])[0])*F(layer.thickness_m)
        residual_i = b-a-(down[i]-up[i])+(down[i+1]-up[i+1])+uptake[i]
        if abs(residual_i) > F(budget_atol_m): raise ArithmeticError('independent accumulated layer balance failed')
        layer_residuals.append(residual_i)
    ledger.update(initial_storage_m=initial, final_storage_m=final, supplied_liquid_input_m=supplied,
        supplied_potential_root_demand_m=supplied_demand, water_residual_m=residual,
        face_downward_m=down, face_upward_m=up, layer_actual_et_m=uptake, layer_water_residual_m=layer_residuals,
        liquid_representation_residual_m=ledger['surface_input_m']-supplied,
        demand_representation_residual_m=ledger['potential_et_m']-supplied_demand)
    ledger['bottom_net_downward_m'] = ledger['bottom_downward_m']-ledger['bottom_upward_m']
    ledger['storage_change_m'] = final-initial
    return {'duration_seconds': duration, 'ledger_m': ledger,
        'root_zone_gross_downward_mm': 1000*ledger['root_zone_gross_downward_m'],
        'root_zone_upward_capillary_mm': 1000*ledger['root_zone_upward_capillary_m'],
        'end_layers': [{k: v for k, v in layer.items() if k not in {'et_m', 'water_residual_m'}}
                       for layer in rows[-1]['solver_result']['layers']], 'end_state': end_state,
        'state_support': 'interval-end cell-centre heads and layer water contents; not time means or hydroperiod'}


def run_year(solver, column, initial_state, calendar, events, controls, *, root_boundary_index,
             water_density_kg_m3, gravity_m_s2, duration_atol_s, budget_atol_m, evidence, source_status,
             source_binding_sha256, scenario_id, stop_after=None, resume=None):
    """One explicitly supported representative year; persistent state, no resets.

    A required UNKNOWN interval halts its causal suffix. Complete prior months
    remain labelled, but no final annual state or totals are fabricated. Numerical
    failures similarly expose diagnostics without treating rejected states as real.
    """
    provenance(evidence, source_status)
    _hash(source_binding_sha256, 'source binding'); text(scenario_id, 'joint scenario identity')
    if type(column) is not solver.Column or type(initial_state) is not solver.State or type(controls) is not solver.Controls:
        raise ValueError('actual source-bound solver Column, State and Controls required')
    if type(calendar) is not Calendar or type(events) is not tuple or not 12 <= len(events) <= 8192 or any(type(e) is not Event for e in events):
        raise ValueError('typed complete bounded calendar/event inventory required')
    if len({e.event_id for e in events}) != len(events) or [e.month_id for e in events] != sorted(e.month_id for e in events):
        raise ValueError('unique events must preserve calendar chronology')
    for m, duration in enumerate(calendar.month_durations_seconds, 1):
        if sum((e.duration_seconds for e in events if e.month_id == m), F()) != duration:
            raise ValueError('complete exact duration in each month required')
    limit = len(events) if stop_after is None else stop_after
    if type(limit) is not int or not 0 <= limit <= len(events): raise ValueError('absolute complete-event stop cursor required')
    if initial_state.column_sha256 != solver.column_digest(column) or len(initial_state.head_m) != len(column.layers):
        raise ValueError('initial heads are not bound to this exact physical column')
    number(water_density_kg_m3, 'water density', positive=True); number(gravity_m_s2, 'gravity', positive=True)
    duration_tol = number(duration_atol_s, 'duration tolerance', positive=True)
    budget_tol = number(budget_atol_m, 'water budget tolerance', positive=True)
    active_column = solver.Column(column.column_id, column.layers, root_boundary_index, column.evidence, column.source_status)
    active_state = solver.initial_state(active_column, initial_state.head_m, elapsed_seconds=initial_state.elapsed_seconds)
    for event in events:
        if type(event.boundary) is not solver.Boundary or (event.uptake is not None and type(event.uptake) is not solver.Uptake):
            raise ValueError('event boundary/root law must use the actual bound solver types')
        if event.potential_root_demand_m_s is not None and event.potential_root_demand_m_s > 0 and event.uptake is None:
            raise ValueError('positive root demand requires supplied uptake weights and head response')
        if event.uptake is not None and (len(event.uptake.weights) != len(column.layers) or any(v > 0 for v in event.uptake.weights[root_boundary_index:])):
            raise ValueError('root weights must match actual layers and stay above declared root face')
    from .richards_numerics import original_numerical_binding
    numerical_binding = solver.numerical_binding() if hasattr(solver, 'numerical_binding') else original_numerical_binding(solver)
    inputs = dict(column=column, initial_state=initial_state, calendar=calendar, events=events,
        controls=controls, root_boundary_index=root_boundary_index, water_density_kg_m3=water_density_kg_m3,
        gravity_m_s2=gravity_m_s2, duration_atol_s=duration_atol_s, budget_atol_m=budget_atol_m,
        evidence=evidence, source_status=source_status, source_binding_sha256=source_binding_sha256, scenario_id=scenario_id,
        numerical_binding=numerical_binding)
    restored_rows = []
    if resume is not None:
        _fields(resume, ('schema', 'source_binding_sha256', 'inputs_sha256', 'state_sha256', 'state'), 'seasonal checkpoint')
        saved = resume['state']
        _fields(saved, ('completed_events', 'elapsed_seconds_in_year', 'continuing_state', 'accepted_event_rows',
                        'completed_months', 'month_summaries', 'accumulated_ledger_m', 'last_completed_event_id', 'next_event_id'), 'checkpoint state')
        cursor = saved['completed_events']
        if type(cursor) is not int or not 0 <= cursor <= limit or type(saved['accepted_event_rows']) is not list or len(saved['accepted_event_rows']) != cursor:
            raise ValueError('checkpoint event cursor/accepted inventory invalid or beyond requested stop')
        if (resume['schema'] != 'diadem.seasonal-layered-water-checkpoint.r10'
                or resume['source_binding_sha256'] != source_binding_sha256 or resume['inputs_sha256'] != digest(inputs)
                or resume['state_sha256'] != digest(saved)):
            raise ValueError('checkpoint source, input or state binding differs')
        replay = run_year(solver, column, initial_state, calendar, events, controls,
            root_boundary_index=root_boundary_index, water_density_kg_m3=water_density_kg_m3,
            gravity_m_s2=gravity_m_s2, duration_atol_s=duration_atol_s, budget_atol_m=budget_atol_m,
            evidence=evidence, source_status=source_status, source_binding_sha256=source_binding_sha256,
            scenario_id=scenario_id, stop_after=cursor)
        if replay['checkpoint'] != resume:
            raise ValueError('checkpoint accepted state/ledger differs from actual source-bound event replay')
        for item in saved['accepted_event_rows']:
            row = dict(item); solved = dict(row['solver_result'])
            solved['state'] = _restore_state(solver, solved['state']); row['solver_result'] = solved
            restored_rows.append(row)
    base = {'schema': 'diadem.seasonal-layered-water.r10', 'status': 'MODELLED_SEASONAL_HYDRAULICS',
        'source_status': 'WORKING NON-CANON', 'inputs_sha256': digest(inputs), 'inputs': inputs,
        'source_binding_sha256': source_binding_sha256, 'scenario_id': scenario_id,
        'column': active_column, 'original_column_sha256': solver.column_digest(column),
        'column_sha256': solver.column_digest(active_column), 'initial_state': active_state,
        'root_boundary_depth_m': sum((F(x.thickness_m) for x in column.layers[:root_boundary_index]), F()),
        'root_boundary_interpretation': 'supplied existing physical layer face; never inherited as biological rooting by default',
        'calendar_start_elapsed_seconds': F(initial_state.elapsed_seconds), 'events': [], 'months': {},
        'annual': None, 'final_state': None, 'completed_events': 0, 'completed_months': 0,
        'cold_air_event_ids': [e.event_id for e in events if e.air_temperature_c is not None and e.air_temperature_c <= 0],
        'unknown_air_temperature_event_ids': [e.event_id for e in events if e.air_temperature_c is None],
        'unmodelled': ['soil heat and freeze/thaw', 'monthly mean saturation and daily hydroperiod',
            'groundwater head/storage or finite aquifer', 'routed river discharge/flooding',
            'bare-soil evaporation', 'realised vegetation or summed PFT water use'],
        'scope': 'fixed formed geometry, explicitly unfrozen conditional matrix flow and root uptake; atmospheric demand is not actual ET'}
    state = active_state; elapsed = F(); rows = []; halted = None; halt_reason = None; global_failure = False
    paused = False; position = 0
    for month, duration in enumerate(calendar.month_durations_seconds, 1):
        selected = [e for e in events if e.month_id == month]; month_start = state; month_rows = []
        for event in selected:
            index = position; position += 1
            if halted is not None:
                base['events'].append({'event_id': event.event_id, 'month_id': month, 'status': 'NOT_ADVANCED_PRIOR_GAP', 'reason': halt_reason})
                continue
            if index >= limit:
                paused = True
                base['events'].append({'event_id': event.event_id, 'month_id': month, 'status': 'NOT_ADVANCED_REQUESTED_STOP',
                    'reason': 'explicit complete-event checkpoint boundary'})
                continue
            if index < len(restored_rows):
                row = restored_rows[index]; state = row['solver_result']['state']
                elapsed += event.duration_seconds; rows.append(row); month_rows.append(row)
                base['events'].append(row); base['completed_events'] += 1
                continue
            if source_status not in KNOWN or event.source_status not in KNOWN or event.soil_thermal_regime != 'UNFROZEN_CONDITIONAL':
                halted = 'UNKNOWN'; halt_reason = 'required source or unfrozen-soil applicability is UNKNOWN; cold air is not a soil-temperature model'
                base['events'].append({'event_id': event.event_id, 'month_id': month, 'status': halted, 'reason': halt_reason})
                continue
            dt = float(event.duration_seconds)
            rate = None if event.liquid_input_m_s is None else float(event.liquid_input_m_s)
            demand = None if event.potential_root_demand_m_s is None else float(event.potential_root_demand_m_s)
            forcing = solver.Forcing(dt, rate, demand, event.uptake, event.evidence, event.source_status)
            if abs(F(dt)-event.duration_seconds) > duration_tol:
                halted = 'NUMERICAL_FAILURE'; halt_reason = 'duration conversion exceeds explicit tolerance'
                base['events'].append({'event_id': event.event_id, 'month_id': month, 'status': halted, 'reason': halt_reason})
                continue
            solved = solver.advance(active_column, state, forcing, event.boundary, controls,
                water_density_kg_m3=float(water_density_kg_m3), gravity_m_s2=float(gravity_m_s2))
            if solved.get('schema') != 'diadem.layered-richards.r6': raise ValueError('unexpected actual solver result schema')
            if solved['status'] != 'MODELLED':
                if solved['status'] not in {'UNKNOWN', 'NUMERICAL_FAILURE'}: raise ValueError('unexpected seasonal solver outcome')
                halted = solved['status']; halt_reason = solved['reason']
                base['events'].append({'event_id': event.event_id, 'month_id': month, 'status': halted, 'reason': halt_reason, 'solver_result': solved})
                if halted == 'NUMERICAL_FAILURE':
                    trial = solved.get('diagnostics', {}).get('last_trial') or {}
                    base['failure_progress'] = {'failed_event_id': event.event_id,
                        'last_completed_event_cursor': base['completed_events'],
                        'last_completed_elapsed_seconds_in_year': elapsed,
                        'last_internal_trial_start_seconds': trial.get('start_seconds'),
                        'last_internal_trial_duration_seconds': trial.get('dt_seconds'),
                        'internal_accepted_step_count': None, 'internal_state_available': False,
                        'in_event_resumable': False,
                        'meaning': 'R6 may have advanced internal steps but exposes no resumable partial state; only completed seasonal events are committed'}
                continue
            following = solved['state']
            expected_elapsed = F(initial_state.elapsed_seconds)+elapsed+event.duration_seconds
            if type(following) is not solver.State or following.column_sha256 != solver.column_digest(active_column):
                raise ValueError('solver returned an incompatible continuing state')
            if abs(F(following.elapsed_seconds)-expected_elapsed) > duration_tol:
                halted = 'NUMERICAL_FAILURE'; halt_reason = 'cumulative solver time differs from exact calendar support'
                base['events'].append({'event_id': event.event_id, 'month_id': month, 'status': halted, 'reason': halt_reason})
                continue
            row = {'event_id': event.event_id, 'month_id': month, 'status': 'MODELLED',
                'start_seconds_in_year': elapsed, 'duration_seconds': event.duration_seconds,
                'duration_conversion_residual_s': F(dt)-event.duration_seconds,
                'cumulative_elapsed_residual_s': F(following.elapsed_seconds)-expected_elapsed,
                'supplied_liquid_input_m': event.liquid_input_m_s*event.duration_seconds,
                'supplied_potential_root_demand_m': event.potential_root_demand_m_s*event.duration_seconds,
                'vegetation_hypothesis_id': event.vegetation_hypothesis_id,
                'soil_thermal_regime': event.soil_thermal_regime, 'thermal_evidence': event.thermal_evidence,
                'air_temperature_c': event.air_temperature_c, 'solver_result': solved}
            try:
                _aggregate(solver, active_column, state, following, [row], event.duration_seconds, budget_tol)
                _aggregate(solver, active_column, month_start, following, month_rows+[row],
                    sum((F(r['duration_seconds']) for r in month_rows), F())+event.duration_seconds, budget_tol)
                _aggregate(solver, active_column, active_state, following, rows+[row], elapsed+event.duration_seconds, budget_tol)
            except ArithmeticError as exc:
                halted = 'NUMERICAL_FAILURE'; halt_reason = str(exc)
                base['events'].append({'event_id': event.event_id, 'month_id': month, 'status': halted, 'reason': halt_reason})
                continue
            state = following; elapsed += event.duration_seconds; rows.append(row); month_rows.append(row)
            base['events'].append(row); base['completed_events'] += 1
        if len(month_rows) == len(selected):
            try:
                aggregate = _aggregate(solver, active_column, month_start, state, month_rows, duration, budget_tol)
                base['months'][str(month)] = {'month_id': month, 'status': 'MODELLED', **aggregate}
                base['completed_months'] += 1
            except ArithmeticError as exc:
                halted = 'NUMERICAL_FAILURE'; halt_reason = str(exc); global_failure = True
                base['months'][str(month)] = {'month_id': month, 'status': halted, 'reason': halt_reason, 'ledger_m': None, 'end_layers': None, 'end_state': None}
        else:
            base['months'][str(month)] = {'month_id': month, 'status': halted or 'NOT_COMPLETED_REQUESTED_STOP',
                'reason': halt_reason or 'explicit complete-event checkpoint boundary',
                'completed_event_ids': [r['event_id'] for r in month_rows], 'ledger_m': None, 'end_layers': None, 'end_state': None}
    if halted is None and not paused:
        try:
            base['annual'] = _aggregate(solver, active_column, active_state, state, rows, sum(calendar.month_durations_seconds, F()), budget_tol)
            base['final_state'] = state
        except ArithmeticError as exc:
            halted = 'NUMERICAL_FAILURE'; halt_reason = str(exc); global_failure = True
    if halted is not None:
        base['status'] = halted; base['reason'] = halt_reason
        base['partial_results_only'] = True; base['accumulated_budget_failure'] = global_failure
        if halted == 'NUMERICAL_FAILURE' and 'failure_progress' not in base:
            base['failure_progress'] = {'failed_event_id': next((r['event_id'] for r in base['events'] if r['status'] == 'NUMERICAL_FAILURE'), None),
                'last_completed_event_cursor': base['completed_events'], 'last_completed_elapsed_seconds_in_year': elapsed,
                'last_internal_trial_start_seconds': None, 'last_internal_trial_duration_seconds': None,
                'internal_accepted_step_count': None, 'internal_state_available': False, 'in_event_resumable': False,
                'meaning': 'wrapper rejected the attempted event/aggregate; only the accepted complete-event prefix is resumable'}
    elif paused:
        base['status'] = 'PARTIAL_SEASONAL_HYDRAULICS' if base['completed_events'] else 'NO_ADVANCE'
        base['reason'] = 'requested complete-event stop; persistent prefix retained, no accepted annual state'
        base['partial_results_only'] = True; base['accumulated_budget_failure'] = False
    else:
        base['reason'] = 'complete ordered forcing advanced without resetting soil storage; no periodic-state claim'
        base['partial_results_only'] = False; base['accumulated_budget_failure'] = False
    accumulated = None if not rows else _aggregate(solver, active_column, active_state, state, rows, elapsed, budget_tol)['ledger_m']
    count = base['completed_events']
    saved = plain({'completed_events': count, 'elapsed_seconds_in_year': elapsed, 'continuing_state': state,
        'accepted_event_rows': rows, 'completed_months': base['completed_months'],
        'month_summaries': {k: v for k, v in base['months'].items() if v['status'] == 'MODELLED'},
        'accumulated_ledger_m': accumulated,
        'last_completed_event_id': None if not count else events[count-1].event_id,
        'next_event_id': events[count].event_id if count < len(events) else None})
    base['checkpoint'] = {'schema': 'diadem.seasonal-layered-water-checkpoint.r10',
        'source_binding_sha256': source_binding_sha256, 'inputs_sha256': base['inputs_sha256'],
        'state_sha256': digest(saved), 'state': saved}
    return plain(base)
