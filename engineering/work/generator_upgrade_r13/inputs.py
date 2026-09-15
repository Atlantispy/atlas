"""Explicit retained initial-water/geometry/forcing adapter; never old outcomes.

Thermal properties and temperatures have no defaults and are not inferred from
air, layer names, Ksat, or the old unfrozen water trajectory.
"""
from copy import deepcopy
from dataclasses import asdict, fields
from fractions import Fraction
import math
from . import provenance as p


UNIT_FIELDS = {'carbon', 'cell_id', 'downstream', 'formed_soil_sha256',
               'hydraulic_hypothesis_id', 'hydrology', 'initial_condition',
               'initial_water_source_sha256', 'physical_cell_sha256', 'snow_id'}
WATER_FIELDS = {'accumulated_budget_failure', 'annual', 'calendar_start_elapsed_seconds',
    'checkpoint', 'cold_air_event_ids', 'column', 'column_sha256', 'completed_events',
    'completed_months', 'events', 'final_state', 'initial_state', 'inputs', 'inputs_sha256',
    'months', 'original_column_sha256', 'partial_results_only', 'reason', 'root_boundary_depth_m',
    'root_boundary_interpretation', 'scenario_id', 'schema', 'scope', 'source_binding_sha256',
    'source_status', 'status', 'unknown_air_temperature_event_ids', 'unmodelled'}
INPUT_FIELDS = {'budget_atol_m', 'calendar', 'column', 'controls', 'duration_atol_s', 'events',
    'evidence', 'gravity_m_s2', 'initial_state', 'numerical_binding', 'root_boundary_index',
    'scenario_id', 'source_binding_sha256', 'source_status', 'water_density_kg_m3'}
THERMAL_FIELDS = {'ice_impedance', 'dry_heat_capacity_j_m3_k', 'conductivity_dry_w_m_k',
    'conductivity_saturated_unfrozen_w_m_k', 'conductivity_saturated_frozen_w_m_k',
    'evidence', 'source_status'}
THERMAL_EVENT_FIELDS = {'surface_water_temperature_k', 'top_heat', 'bottom_heat', 'evidence', 'source_status'}


def exact(value, expected, name):
    if type(value) is not dict or set(value) != set(expected):
        raise ValueError('exact ' + name + ' fields required')
    return value


def text(value, name):
    if type(value) is not str or not value.strip() or len(value) > 4096:
        raise ValueError('explicit bounded ' + name + ' required')
    return value


def rational(value, name, *, positive=False, nonnegative=False):
    if type(value) not in (int, float, str):
        raise ValueError('explicit finite ' + name + ' required')
    try:
        result = Fraction(value)
        if not math.isfinite(float(result)) or abs(result) > 10**18:
            raise ValueError('bounded ' + name + ' required')
    except (OverflowError, ZeroDivisionError) as error:
        raise ValueError('invalid ' + name) from error
    if (positive and result <= 0) or (nonnegative and result < 0):
        raise ValueError('positive/nonnegative ' + name + ' required')
    return result


def hash_value(value, name):
    if type(value) is not str or len(value) != 64 or any(c not in '0123456789abcdef' for c in value):
        raise ValueError('exact lowercase SHA256 for ' + name + ' required')
    return value


def native_column(sw, record):
    values = dict(exact(record, (f.name for f in fields(sw.Column)), 'native column'))
    if type(values['layers']) is not list:
        raise ValueError('ordered complete native layers required')
    values['layers'] = tuple(sw.HydraulicLayer(**exact(row, (f.name for f in fields(sw.HydraulicLayer)),
                                                   'native hydraulic layer')) for row in values['layers'])
    column = sw.Column(**values)
    if any(not layer.known for layer in column.layers):
        raise ValueError('complete retained hydraulic laws required')
    return column


def native_state(sw, column, record):
    exact(record, ('head_m', 'elapsed_seconds', 'column_sha256'), 'native initial water state')
    if type(record['head_m']) is not list:
        raise ValueError('ordered complete initial heads required')
    state = sw.State(tuple(record['head_m']), record['elapsed_seconds'], record['column_sha256'])
    if state.column_sha256 != sw.column_digest(column) or len(state.head_m) != len(column.layers):
        raise ValueError('native initial state/column binding differs')
    return state


def retained_inputs(bundle, unit):
    """Check retained input/source/clock bindings, without replaying any model."""
    exact(unit, UNIT_FIELDS, 'R10 unit')
    water = exact(unit['hydrology'], WATER_FIELDS, 'complete R10 hydraulic product')
    incoming = exact(water['inputs'], INPUT_FIELDS, 'R10 hydraulic inputs')
    if (bundle.source_sha256 != p.shared.SCIENCE_SHA or p.sha(bundle.identity) != p.shared.SCIENCE_SHA
            or incoming['source_binding_sha256'] != bundle.parent.source_sha256
            or water['source_binding_sha256'] != incoming['source_binding_sha256']):
        raise ValueError('retained sealed scientific source binding differs')
    if hash_value(water['inputs_sha256'], 'hydraulic inputs') != p.sha(incoming):
        raise ValueError('hydraulic input checksum differs')
    for key in ('physical_cell_sha256', 'formed_soil_sha256', 'initial_water_source_sha256'):
        hash_value(unit[key], key)
    scenario = '/'.join(text(unit[key], key) for key in ('snow_id', 'hydraulic_hypothesis_id', 'cell_id'))
    if water['scenario_id'] != scenario or incoming['scenario_id'] != scenario:
        raise ValueError('retained hydraulic scenario/unit binding differs')
    if (water['schema'] != 'diadem.seasonal-layered-water.r10'
            or water['status'] != 'MODELLED_SEASONAL_HYDRAULICS'
            or water['completed_months'] != 12 or type(water['completed_months']) is not int
            or water['partial_results_only'] is not False or water['accumulated_budget_failure'] is not False
            or water['annual'] is None or water['final_state'] is None
            or water['reason'] != 'complete ordered forcing advanced without resetting soil storage; no periodic-state claim'):
        raise ValueError('complete retained hydraulic year required')
    sw = bundle.parent.parent.parent.parent.parent.solver
    original = native_column(sw, incoming['column'])
    original_initial = native_state(sw, original, incoming['initial_state'])
    active = sw.Column(original.column_id, original.layers, incoming['root_boundary_index'],
                       original.evidence, original.source_status)
    initial = sw.initial_state(active, original_initial.head_m, elapsed_seconds=original_initial.elapsed_seconds)
    if (water['original_column_sha256'] != sw.column_digest(original)
            or water['column_sha256'] != sw.column_digest(active)
            or p.sha(water['column']) != p.sha(asdict(active))
            or p.sha(water['initial_state']) != p.sha(asdict(initial))
            or rational(water['calendar_start_elapsed_seconds'], 'initial clock') != Fraction(initial.elapsed_seconds)
            or rational(water['root_boundary_depth_m'], 'root depth') !=
                sum((Fraction(layer.thickness_m) for layer in active.layers[:active.root_boundary_index]), Fraction())):
        raise ValueError('native geometry/initial head/root-face binding differs')
    # Validate original controls and numerical lineage without using their solver.
    sw.Controls(**exact(incoming['controls'], (f.name for f in fields(sw.Controls)), 'retained hydraulic controls'))
    old_numerics = bundle.parent.graph.load('work.generator_upgrade_r10.richards_numerics')
    if incoming['numerical_binding'] != old_numerics.Adapter(sw).numerical_binding():
        raise ValueError('retained hydraulic numerical source binding differs')
    hydraulic = bundle.parent.graph.load('work.generator_upgrade_r10.hydraulics')
    calendar = exact(incoming['calendar'], (f.name for f in fields(hydraulic.Calendar)), 'retained calendar')
    if type(calendar['month_durations_seconds']) is not list or len(calendar['month_durations_seconds']) != 12:
        raise ValueError('complete twelve-month calendar required')
    durations = [rational(value, 'month duration', positive=True) for value in calendar['month_durations_seconds']]
    native_calendar = hydraulic.Calendar(calendar['calendar_id'], tuple(durations),
        rational(calendar['day_seconds'], 'day duration', positive=True), calendar['evidence'])
    if hydraulic.plain(native_calendar) != calendar:
        raise ValueError('retained exact calendar representation differs')
    events, rows = incoming['events'], water['events']
    if (type(events) is not list or not 12 <= len(events) <= 8192 or type(rows) is not list
            or len(rows) != len(events) or water['completed_events'] != len(events)
            or type(water['completed_events']) is not int or type(water['months']) is not dict
            or set(water['months']) != {str(month) for month in range(1, 13)}):
        raise ValueError('complete hydraulic event/month inventory required')
    elapsed, month_sums, ids, last_month = Fraction(), [Fraction()] * 12, set(), 1
    for event, row in zip(events, rows):
        exact(event, (f.name for f in fields(hydraulic.Event)), 'retained hydraulic event')
        boundary = sw.Boundary(**exact(event['boundary'], (f.name for f in fields(sw.Boundary)), 'retained bottom boundary'))
        uptake = event['uptake']
        if uptake is not None:
            uptake = dict(exact(uptake, (f.name for f in fields(sw.Uptake)), 'retained root/Feddes law'))
            if type(uptake['weights']) is not list:
                raise ValueError('complete ordered root weights required')
            uptake['weights'] = tuple(uptake['weights'])
            uptake = sw.Uptake(**uptake)
            if (len(uptake.weights) != len(active.layers)
                    or any(weight > 0 for weight in uptake.weights[active.root_boundary_index:])):
                raise ValueError('root weights exceed the retained root face or layer inventory')
        dt = rational(event['duration_seconds'], 'event duration', positive=True)
        liquid = rational(event['liquid_input_m_s'], 'surface water input', nonnegative=True)
        demand = rational(event['potential_root_demand_m_s'], 'root potential demand', nonnegative=True)
        native_event = hydraulic.Event(**dict(event, duration_seconds=dt, liquid_input_m_s=liquid,
                                             potential_root_demand_m_s=demand, boundary=boundary, uptake=uptake))
        if hydraulic.plain(native_event) != event or demand > 0 and uptake is None:
            raise ValueError('complete original hydraulic event/uptake required')
        month = event['month_id']
        if (event['event_id'] in ids or month < last_month or row.get('status') != 'MODELLED'
                or row.get('event_id') != event['event_id'] or row.get('month_id') != month
                or rational(row.get('duration_seconds'), 'accepted event duration') != dt
                or rational(row.get('start_seconds_in_year'), 'accepted event clock') != elapsed):
            raise ValueError('retained chronological event clock differs')
        if (row.get('vegetation_hypothesis_id') != event['vegetation_hypothesis_id']
                or event['vegetation_hypothesis_id'] != unit['hydraulic_hypothesis_id']):
            raise ValueError('retained event vegetation hypothesis differs')
        ids.add(event['event_id']); month_sums[month - 1] += dt; elapsed += dt; last_month = month
    if month_sums != durations:
        raise ValueError('original events must fill each exact calendar month')
    for month, duration in enumerate(durations, 1):
        row = water['months'][str(month)]
        if row.get('status') != 'MODELLED' or row.get('month_id') != month or rational(row.get('duration_seconds'), 'saved month') != duration:
            raise ValueError('retained completed month support differs')
    # Authenticate the completed prefix structure; no old moisture/flux is fed forward.
    checkpoint = exact(water['checkpoint'], ('schema', 'source_binding_sha256', 'inputs_sha256', 'state_sha256', 'state'), 'R10 event checkpoint')
    state = exact(checkpoint['state'], ('completed_events', 'elapsed_seconds_in_year', 'continuing_state',
        'accepted_event_rows', 'completed_months', 'month_summaries', 'accumulated_ledger_m',
        'last_completed_event_id', 'next_event_id'), 'R10 completed checkpoint state')
    if (checkpoint['schema'] != 'diadem.seasonal-layered-water-checkpoint.r10'
            or checkpoint['source_binding_sha256'] != incoming['source_binding_sha256']
            or checkpoint['inputs_sha256'] != water['inputs_sha256'] or checkpoint['state_sha256'] != p.sha(state)
            or state['completed_events'] != len(events) or state['completed_months'] != 12
            or state['accepted_event_rows'] != rows or state['continuing_state'] != water['final_state']
            or rational(state['elapsed_seconds_in_year'], 'completed checkpoint clock') != elapsed
            or state['next_event_id'] is not None or state['last_completed_event_id'] != events[-1]['event_id']):
        raise ValueError('retained completed checkpoint/source/clock differs')
    return water, incoming, active, initial, durations


def exact_float(value, name):
    original = rational(value, name)
    represented = float(original)
    if Fraction(represented) != original:
        raise ValueError(name + ' is not exactly representable by the R13 numeric core')
    return represented


def finite_number(value, name):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError('explicit finite JSON number for ' + name + ' required')
    return value


def support_status(value, requested, name):
    if value not in ('CANON', 'WORKING NON-CANON', 'SYNTHETIC TEST'):
        raise ValueError('known explicit ' + name + ' source status required')
    if requested == 'WORKING NON-CANON' and value == 'SYNTHETIC TEST':
        raise ValueError('synthetic ' + name + ' cannot be promoted to a working-world recipe')


def pk_initial_water(sw, column, initial, model, temperatures):
    """Change pressure coordinates, not retained water, for apparent-pore ice.

    C is original TOTAL pore saturation; B is the full VG freezing saturation.
    In a frozen pore, C = 1 - B/A + B, so A = B/(B + 1 - C).
    A includes residual saturation: the inverse must not treat it as effective
    saturation. Saturated stock alone never determines a pressure head.
    """
    from . import soil
    constants = model['constants']
    tm, latent, gravity = (constants[key] for key in
                           ('melting_temperature_k', 'latent_heat_j_kg', 'gravity_m_s2'))
    heads, original_water = [], []
    for native, layer, head, temperature in zip(column.layers, model['layers'], initial.head_m, temperatures):
        theta = sw.hydraulic_properties(native, head)[0]
        original_water.append(theta)
        c = theta / native.theta_s
        freezing_head = -model['clapeyron_beta'] * latent / gravity * max(0., (tm-temperature)/tm)
        b = soil._vg(layer, freezing_head)[0] / native.theta_s
        if c <= b:
            converted = head
        elif c == 1.:
            if head < 0:
                raise ValueError('rounded saturated stock does not supply a nonnegative native pressure')
            converted = head
        else:
            a = b / (b + 1. - c)
            converted = sw.head_from_theta(native, a * native.theta_s)
        heads.append(converted)
    # This evaluates only the constitutive initial state, never a timestep.
    state = soil.initial_state(model, heads, temperatures, elapsed_seconds=initial.elapsed_seconds)
    residuals = [new-old for new, old in zip(state['total_water'], original_water)]
    limits = [8 * math.ulp(layer.theta_s) for layer in column.layers]
    if any(abs(error) > limit for error, limit in zip(residuals, limits)):
        raise ValueError('apparent-pore initial pressure conversion does not preserve native water to roundoff')
    return heads, {'original_native_head_sha256': p.sha(list(initial.head_m)),
                   'initial_head_semantics': 'PHYSICAL_LIQUID_PRESSURE_HEAD; frozen coordinates converted from native total-water retention',
                   'initial_pressure_conversion_law': 'Painter-Karra 2014 equations 18-19; explicit omega=1/beta approximation, inverted at fixed original total water',
                   'initial_water_preserved': True,
                   'original_native_water_fraction': original_water,
                   'converted_initial_water_fraction': state['total_water'],
                   'initial_water_conversion_residual_fraction': residuals,
                   'initial_water_roundoff_limit_fraction': limits,
                   'initial_water_support': 'ORIGINAL_NATIVE_INITIAL_WATER; liquid pressure converted without changing layer water stock'}


def from_r10_unit(bundle, unit, *, thermal_by_layer, constants, initial_temperature_k,
                  thermal_forcing_by_event, controls, context, evidence, source_status,
                  freezing_model=None, clapeyron_beta=None):
    """Return one source-explicit R13 recipe, never a simulated soil result.

    ``thermal_by_layer`` maps every exact layer ID to THERMAL_FIELDS. Initial
    temperatures map those same IDs to finite Kelvin JSON numbers. Each exact
    event ID requires THERMAL_EVENT_FIELDS, plus ``bottom_water_temperature_k``
    only for a retained fixed-head lower water boundary. Heat boundary records
    have kind/value/evidence/source_status, as defined by the R13 soil core.

    No thermal defaults, ignored extra inputs, layer deletion, old runoff, old
    moisture trajectory, or conversion of potential root demand to actual ET.
    A non-binary rational rate/duration is rejected rather than silently rounded.
    An explicit PAINTER_KARRA_2014_APPARENT_PORE model requires clapeyron_beta;
    its initial liquid-pressure coordinates are chosen to preserve native water.
    Omitting both options preserves the original zero-ice-pressure recipe.
    """
    from . import soil, year
    if source_status not in ('WORKING NON-CANON', 'SYNTHETIC TEST'):
        raise ValueError('new soil recipe must remain WORKING NON-CANON or SYNTHETIC TEST')
    if freezing_model is None and clapeyron_beta is not None:
        raise ValueError('clapeyron_beta requires an explicit freezing_model')
    text(evidence, 'adapter evidence')
    year.plain(unit)
    if len(p.encoded(unit)) > p.shared.LIMIT:
        raise ValueError('bounded decoded R10 unit required')
    water, incoming, column, initial, durations = retained_inputs(bundle, unit)
    exact(context, year.FRAME, 'caller soil frame')
    for key, value in context.items():
        text(value, key)
    if (context['scenario_id'] != incoming['scenario_id']
            or context['calendar_id'] != incoming['calendar']['calendar_id']):
        raise ValueError('caller context must match retained scenario and calendar')
    support_status(incoming['source_status'], source_status, 'hydraulic input')
    support_status(column.source_status, source_status, 'hydraulic column')
    ids = [layer.layer_id for layer in column.layers]
    exact(thermal_by_layer, ids, 'thermal layer inventory')
    exact(initial_temperature_k, ids, 'initial temperature inventory')
    exact(thermal_forcing_by_event, (row['event_id'] for row in incoming['events']), 'thermal event inventory')
    exact(constants, soil.CONSTANTS, 'soil constants')
    for key, value in constants.items():
        if finite_number(value, key) <= 0:
            raise ValueError('positive supplied soil constants required')
    for key in ('water_density_kg_m3', 'gravity_m_s2'):
        if Fraction(constants[key]) != rational(incoming[key], key, positive=True):
            raise ValueError('soil ' + key + ' must equal the retained hydraulic input')
    layers = []
    for native in column.layers:
        thermal = exact(thermal_by_layer[native.layer_id], THERMAL_FIELDS, 'supplied layer thermal law')
        text(thermal['evidence'], 'layer thermal evidence')
        support_status(native.source_status, source_status, 'hydraulic layer')
        support_status(thermal['source_status'], source_status, 'thermal law')
        for key in THERMAL_FIELDS - {'evidence', 'source_status'}:
            finite_number(thermal[key], key)
        layer = {key: getattr(native, key) for key in ('layer_id', 'thickness_m', 'theta_r', 'theta_s', 'mualem_l')}
        layer.update(vg_alpha_per_m=native.alpha_per_m, vg_n=native.n,
                     saturated_conductivity_m_s=native.ksat_m_s,
                     **{key: thermal[key] for key in THERMAL_FIELDS - {'evidence', 'source_status'}},
                     evidence='Retained hydraulic input ' + water['inputs_sha256'] + '; explicit thermal law: ' + thermal['evidence'],
                     source_status=source_status)
        layers.append(layer)
        if finite_number(initial_temperature_k[native.layer_id], 'initial soil temperature') <= 0:
            raise ValueError('positive explicit initial Kelvin temperature required')
    model = {'layers': layers, 'constants': deepcopy(constants), 'evidence': evidence, 'source_status': source_status}
    if freezing_model is not None:
        model['freezing_model'] = freezing_model
        if clapeyron_beta is not None:
            model['clapeyron_beta'] = clapeyron_beta
    soil._model(model)
    soil._controls(controls, model)
    events, elapsed, original_forcing = [], Fraction(), {}
    boundary_kinds = {'no_flow': 'noflow', 'free_drainage': 'free_drainage', 'fixed_head': 'head'}
    for old in incoming['events']:
        thermal = thermal_forcing_by_event[old['event_id']]
        needs_bottom_temperature = old['boundary']['kind'] == 'fixed_head'
        exact(thermal, THERMAL_EVENT_FIELDS | ({'bottom_water_temperature_k'} if needs_bottom_temperature else set()),
              'explicit event thermal forcing')
        text(thermal['evidence'], 'thermal forcing evidence')
        support_status(old['source_status'], source_status, 'water forcing')
        support_status(thermal['source_status'], source_status, 'thermal forcing')
        support_status(old['boundary']['source_status'], source_status, 'bottom water boundary')
        for name in ('top_heat', 'bottom_heat'):
            exact(thermal[name], ('kind', 'value', 'evidence', 'source_status'), name)
            support_status(thermal[name]['source_status'], source_status, name)
        boundary = {'kind': boundary_kinds[old['boundary']['kind']],
                    'evidence': old['boundary']['evidence'], 'source_status': old['boundary']['source_status']}
        if needs_bottom_temperature:
            boundary.update(head_m=finite_number(old['boundary']['head_m'], 'retained fixed head'),
                            temperature_k=finite_number(thermal['bottom_water_temperature_k'], 'bottom inflow temperature'))
        dt = rational(old['duration_seconds'], 'original event duration', positive=True)
        forcing = {'duration_s': exact_float(old['duration_seconds'], 'original event duration'),
                   'surface_water_flux_m_s': exact_float(old['liquid_input_m_s'], 'original surface water rate'),
                   'surface_water_temperature_k': finite_number(thermal['surface_water_temperature_k'], 'surface inflow temperature'),
                   'top_heat': deepcopy(thermal['top_heat']), 'bottom_heat': deepcopy(thermal['bottom_heat']),
                   'bottom_water': boundary, 'evidence': thermal['evidence'], 'source_status': source_status}
        if old['uptake'] is None:
            if rational(old['potential_root_demand_m_s'], 'original root demand') != 0:
                raise ValueError('positive retained potential demand requires an original uptake law')
            forcing['root_withdrawal_m_s'] = [0.0] * len(ids)
        else:
            support_status(old['uptake']['source_status'], source_status, 'root uptake law')
            forcing['uptake'] = deepcopy(old['uptake'])
            forcing['potential_root_demand_m_s'] = exact_float(old['potential_root_demand_m_s'], 'original root demand')
        soil._event(forcing, len(ids))
        events.append({'event_id': old['event_id'], 'month_id': old['month_id'],
                       'start_seconds_in_year': str(elapsed), 'duration_seconds': old['duration_seconds'],
                       'forcing': forcing, 'evidence': evidence, 'source_status': source_status})
        original_forcing[old['event_id']] = deepcopy(old)
        elapsed += dt
    initial_spec = {'head_m': list(initial.head_m),
                    'temperature_k': [initial_temperature_k[ident] for ident in ids],
                    'elapsed_seconds': initial.elapsed_seconds}
    initial_join = {}
    if freezing_model == 'PAINTER_KARRA_2014_APPARENT_PORE':
        initial_spec['head_m'], initial_join = pk_initial_water(
            bundle.parent.parent.parent.parent.parent.solver, column, initial,
            model, initial_spec['temperature_k'])
    recipe = {'schema': year.SCHEMA, 'scenario_id': incoming['scenario_id'], 'context': deepcopy(context),
        'model': model, 'initial': initial_spec,
        'calendar': {'calendar_id': incoming['calendar']['calendar_id'],
                     'month_durations_seconds': deepcopy(incoming['calendar']['month_durations_seconds'])},
        'events': events, 'controls': deepcopy(controls), 'evidence': evidence, 'source_status': source_status,
        'joins': {'schema': 'diadem.r13.retained-initial-hydraulic-input-join.v1',
                  'r11_source_sha256': bundle.source_sha256, 'r10_source_sha256': bundle.parent.source_sha256,
                  'retained_r10_unit_sha256': p.sha(unit), 'retained_hydraulic_inputs_sha256': water['inputs_sha256'],
                  'original_column_sha256': water['original_column_sha256'], 'active_column_sha256': water['column_sha256'],
                  'original_initial_state_sha256': p.sha(incoming['initial_state']),
                  'active_initial_state_sha256': p.sha(water['initial_state']),
                  'root_boundary_index': column.root_boundary_index, 'root_boundary_depth_m': water['root_boundary_depth_m'],
                  'native_layer_inventory': ids, 'geometry_preserved_exactly': True,
                  'original_calendar': deepcopy(incoming['calendar']), 'original_event_forcing': original_forcing,
                  'hydraulic_source_status': incoming['source_status'],
                  'thermal_by_layer': deepcopy(thermal_by_layer), 'thermal_forcing_by_event': deepcopy(thermal_forcing_by_event),
                  'caller_context_binding': 'EXPLICIT_CALLER_CONTEXT; only scenario/calendar verified against retained hydraulic inputs',
                  'initial_water_support': 'ORIGINAL_NATIVE_INITIAL_HEADS_ONLY',
                  'old_r10_computed_moisture_or_runoff_reused': False,
                  'air_temperature_inference': 'NONE; any heat boundary hypothesis must be explicitly caller supplied',
                  'temperature_and_thermal_laws_are_explicit_hypotheses': True}}
    recipe['joins'].update(initial_join)
    year.validate(recipe)
    return deepcopy(recipe)
