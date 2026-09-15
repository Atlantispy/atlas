"""R22 liquid-surface evaporation on the unchanged R13 coupled equations.

An explicit supplied piecewise-linear dry-head response limits a supplied
potential surface demand. This is an identified phenomenological boundary,
not FAO56's additional depletion bucket, atmospheric humidity/energy solver or
a sublimation law. Every accepted evaporation transfer subtracts liquid water,
its native liquid enthalpy, and separately supplied latent heat of vaporisation.
The supplied top heat flux/temperature is BEFORE this evaporative cooling.

Private function namespaces preserve the R13 source and module globals. The
native nonlinear solve, finite-volume equations and all numerical gates are
retained; the temporal gate also checks gross surface transfers independently.
"""
from copy import deepcopy
import math
from types import FunctionType

import numpy as np

from work.generator_upgrade_r13 import soil, audit as native_audit

SCHEMA = 'diadem.coupled-soil-surface-evaporation.r22'
SOURCE = 'https://www.fao.org/4/x0490e/x0490e04.htm'
FIELDS = {'kind', 'potential_m_s', 'dry_zero_head_m', 'dry_full_head_m',
          'latent_heat_vaporisation_j_kg', 'heat_boundary_basis', 'applicability', 'evidence', 'source_status'}
OUTSIDE = 'R22 evaporation donor is outside exposed unfrozen soil regime'


def _plain_receipt(value):
    """Lossless binary64/scalar conversion at the new receipt boundary.

    NumPy arithmetic in added gross-flux diagnostics may retain np.float64.
    The authenticated Store requires exact built-in JSON types. ``item`` keeps
    the represented scalar value; unsupported extended/complex types are rejected.
    No physical value, tolerance, residual or executed native source changes.
    """
    if isinstance(value, np.generic):
        converted = value.item()
        if isinstance(converted, np.generic):
            raise ValueError('unsupported extended NumPy scalar in soil receipt')
        return _plain_receipt(converted)
    if type(value) is dict:
        if any(type(key) is not str for key in value):
            raise ValueError('soil receipt requires exact string JSON keys')
        return {key: _plain_receipt(item) for key, item in value.items()}
    if type(value) in (list, tuple):
        return [_plain_receipt(item) for item in value]
    if value is None or type(value) in (str, bool, int):
        return value
    if type(value) is float and math.isfinite(value):
        return value
    raise ValueError('unsupported or nonfinite soil receipt value')


def _event(event, n):
    native = dict(event)
    boundary = native.pop('surface_evaporation', None)
    soil._event(native, n)
    if 'surface_evaporation' not in event:
        return
    if boundary is None:
        raise soil.UnknownInput('surface evaporation boundary is UNKNOWN')
    soil._keys(boundary, FIELDS, 'surface evaporation')
    soil._evidence(boundary)
    if boundary['kind'] != 'SUPPLIED_POTENTIAL_LIQUID_SURFACE':
        raise ValueError('explicit liquid surface evaporation boundary required')
    if boundary['heat_boundary_basis'] != 'BEFORE_EVAPORATIVE_LATENT_COOLING':
        raise ValueError('top heat must exclude the latent cooling applied here')
    for key in ('potential_m_s', 'dry_zero_head_m', 'dry_full_head_m', 'latent_heat_vaporisation_j_kg'):
        if boundary[key] is None:
            raise soil.UnknownInput('surface evaporation '+key+' is UNKNOWN')
        soil._number(boundary[key], key)
    if boundary['potential_m_s'] < 0 or boundary['latent_heat_vaporisation_j_kg'] <= 0:
        raise ValueError('nonnegative demand and positive vaporisation enthalpy required')
    if not boundary['dry_zero_head_m'] < boundary['dry_full_head_m'] < 0:
        raise ValueError('dry-zero < dry-full < zero for supplied evaporation response')
    app = boundary['applicability']
    soil._keys(app, {'kind', 'donor_layer_id', 'exposed_fraction', 'wetted_fraction',
        'exposed_wetted_fraction', 'demand_area_basis', 'evidence', 'source_status'}, 'surface applicability')
    soil._evidence(app)
    soil._text(app['donor_layer_id'], 'exposed donor layer')
    if app['kind'] != 'EXPOSED_UNFROZEN_NONSALINE_SOIL':
        raise ValueError('supported exposed unfrozen nonsaline soil regime required')
    if app['demand_area_basis'] != 'COLUMN_MEAN_AFTER_EXPOSED_WETTED_FRACTION':
        raise ValueError('evaporation demand must already be per column area, with exposure applied once')
    for key in ('exposed_fraction', 'wetted_fraction', 'exposed_wetted_fraction'):
        if app[key] is None:
            raise soil.UnknownInput('surface support '+key+' is UNKNOWN')
        if not 0 <= soil._number(app[key], key) <= 1:
            raise ValueError('surface support fractions must lie within zero and one')
    exposed, wetted, overlap = (app[key] for key in ('exposed_fraction', 'wetted_fraction', 'exposed_wetted_fraction'))
    if not max(0., exposed+wetted-1.)-8*math.ulp(1.) <= overlap <= min(exposed, wetted):
        raise ValueError('exposed/wetted intersection differs from declared support fractions')
    if boundary['potential_m_s'] and not overlap:
        raise ValueError('nonzero evaporation requires exposed and wetted donor support')


def _rates(model, props, temperature, event, *, temperature_offset=None):
    boundary = event['surface_evaporation']
    if boundary['applicability']['donor_layer_id'] != model['layers'][0]['layer_id']:
        raise ValueError('surface evaporation donor differs from current exposed top material')
    if props['ice'][0] > 0:
        raise soil.ConstitutiveDomainError(OUTSIDE)
    rates = soil._rates(model, props, temperature, event, temperature_offset=temperature_offset)
    a, b = boundary['dry_zero_head_m'], boundary['dry_full_head_m']
    psi = props['liquid_head'][0]
    stress, slope = (0., 0.) if psi <= a else ((1., 0.) if psi >= b else ((psi-a)/(b-a), 1/(b-a)))
    n = len(temperature)
    demand = boundary['potential_m_s']
    evaporation = demand*stress
    derivative = np.zeros(2*n)
    derivative[0], derivative[n] = demand*slope*props['psi_h'][0], demand*slope*props['psi_t'][0]
    constants = model['constants']
    rho, cw, lf, tm = (constants[key] for key in ('water_density_kg_m3',
        'water_heat_capacity_j_kg_k', 'latent_heat_j_kg', 'melting_temperature_k'))
    offset = temperature[0]-tm if temperature_offset is None else temperature_offset[0]
    specific = rho*(lf+cw*offset)
    enthalpy = evaporation*specific
    latent = rho*boundary['latent_heat_vaporisation_j_kg']*evaporation
    liquid_flux = rates['water'][0]
    # Gross liquid runoff is separate from vapour and from rain bypass. R13's
    # surface face supplies its own correctly upwinded liquid enthalpy.
    rates['surface_gross'] = {
        'surface_evaporation_m': evaporation,
        'surface_evaporation_enthalpy_j_m2': enthalpy,
        'surface_evaporation_latent_heat_j_m2': latent,
        'infiltration_m': max(liquid_flux, 0.),
        'rain_excess_runoff_m': event['surface_water_flux_m_s']-max(liquid_flux, 0.),
        'surface_exfiltration_m': max(-liquid_flux, 0.),
        'surface_exfiltration_enthalpy_j_m2': -rates['advection'][0] if liquid_flux < 0 else 0.,
        'surface_heat_before_evaporation_j_m2': rates['heat'][0],
    }
    rates['water'][0] -= evaporation
    rates['water_jac'][0] -= derivative
    operand = demand if slope == 0 else demand*(abs(psi)+abs(a)+stress*(abs(a)+abs(b)))/(b-a)
    rates['water_roundoff_operands'][0] += operand
    rates['advection'][0] -= enthalpy
    rates['advection_jac'][0] -= specific*derivative
    rates['advection_jac'][0, n] -= rho*cw*evaporation
    rates['heat'][0] -= latent
    rates['heat_jac'][0] -= rho*boundary['latent_heat_vaporisation_j_kg']*derivative
    if not all(math.isfinite(float(value)) for value in rates['surface_gross'].values()):
        raise soil.ConstitutiveDomainError('unrepresentable surface evaporation transfer')
    if not all(np.all(np.isfinite(rates[key])) for key in ('water', 'water_jac', 'advection', 'advection_jac', 'heat', 'heat_jac')):
        raise soil.ConstitutiveDomainError('unrepresentable surface evaporation flux/Jacobian')
    return rates


def _namespace():
    namespace = dict(soil.__dict__)
    # All native helpers must resolve the modified boundary consistently,
    # including the saturated endpoint-pressure projection.
    for name, value in soil.__dict__.items():
        if isinstance(value, FunctionType) and value.__globals__ is soil.__dict__:
            cloned = FunctionType(value.__code__, namespace, value.__name__, value.__defaults__, value.__closure__)
            cloned.__kwdefaults__ = value.__kwdefaults__
            namespace[name] = cloned
    namespace['_event'], namespace['_rates'] = _event, _rates
    return namespace


def advance(model, state, event, controls):
    """Advance the actual finite soil stock; no separate evaporation store."""
    if 'surface_evaporation' not in event:
        return soil.advance(model, state, event, controls)
    try:
        n = soil._model(model)
        _event(event, n)
    except soil.UnknownInput:
        pass  # The native complete UNKNOWN path supplies the ordinary result.
    else:
        soil._controls(controls, model)
        soil._read_state(model, state)
        if event['surface_evaporation']['applicability']['donor_layer_id'] != model['layers'][0]['layer_id']:
            raise ValueError('surface evaporation donor differs from current exposed top material')
        if state['ice_water'][0] > 0:
            return {'schema': SCHEMA, 'status': 'OUTSIDE_REGIME', 'source_status': event['surface_evaporation']['source_status'],
                'initial_state': deepcopy(state), 'final_state': None, 'last_accepted_state': deepcopy(state),
                'ledger': None, 'accepted_steps': [], 'reason': OUTSIDE, 'physical_acceptance': False,
                'surface_evaporation_boundary': deepcopy(event['surface_evaporation']),
                'assumptions': ['The first R22 evaporation boundary admits an unfrozen exposed soil donor only.']}
    namespace = _namespace()
    native_step, native_errors = namespace['_step'], namespace['_errors']
    candidates = []

    def step(model, head, temperature, dt, event, controls, *, temperature_offset=None):
        result, reason = native_step(model, head, temperature, dt, event, controls,
                                     temperature_offset=temperature_offset)
        if result is None:
            return result, reason
        # Recover the accepted BE stage, which may precede a zero-storage PK
        # pressure projection. Re-evaluation is read-only and is not a new solve.
        integration_head = result['head'].copy()
        projection = result['endpoint_pressure_projection']
        integration_head[projection['layer_indices']] = projection['integration_head_m']
        props = soil._properties(model, integration_head, result['temperature'],
                                 temperature_offset=result['temperature_offset'])
        rates = _rates(model, props, result['temperature'], event,
                       temperature_offset=result['temperature_offset'])
        for key in ('water', 'heat', 'advection', 'root', 'root_energy'):
            if not np.array_equal(result[key], dt*rates[key]):
                raise ValueError('surface diagnostic differs from the accepted integration-stage flux')
        result['surface_gross'] = {key: dt*value for key, value in rates['surface_gross'].items()}
        return result, reason

    def errors(full, first, second, controls, tm):
        _, components, _ = native_errors(full, first, second, controls, tm)
        for key, value in full['surface_gross'].items():
            fine = first['surface_gross'][key]+second['surface_gross'][key]
            atol = controls['water_atol_m'] if key.endswith('_m') else controls['energy_atol_j_m2']
            ratio = abs(value-fine)/(atol+controls['relative_tolerance']*max(abs(value), abs(fine)))
            components[key+'_gross_integral'] = {'ratio': ratio, 'index': 0, 'absolute_difference': abs(value-fine)}
        worst = max(components, key=lambda key: components[key]['ratio'])
        ratio = components[worst]['ratio']
        if ratio <= 1:
            candidates.append({key: first['surface_gross'][key]+second['surface_gross'][key] for key in full['surface_gross']})
        return ratio, components, worst

    namespace['_step'], namespace['_errors'] = step, errors
    result = namespace['advance'](model, state, event, controls)
    result['schema'] = SCHEMA
    if result['status'] == 'NUMERICAL_FAILURE':
        failures = (result.get('numerics', {}).get('last_trial') or {}).get('solve_failures', {})
        if any(OUTSIDE in str(reason) for reason in failures.values()):
            result['status'], result['reason'] = 'OUTSIDE_REGIME', OUTSIDE
    result['surface_evaporation_boundary'] = deepcopy(event['surface_evaporation'])
    result['surface_evaporation_method'] = 'SUPPLIED_POTENTIAL_WITH_SUPPLIED_PIECEWISE_LINEAR_LIQUID_HEAD_REDUCTION'
    result['evaporation_primary_source'] = SOURCE
    result['assumptions'].extend([
        'Supplied evaporation demand and dry-head response are explicit uncalibrated inputs unless owner evidence establishes applicability.',
        'Liquid evaporates at the top-cell temperature; no vapour transport, atmospheric humidity feedback or direct ice sublimation.',
        'Latent vaporisation cooling is subtracted once from the declared pre-evaporation top heat boundary.',
        'Root withdrawal remains a separate liquid/enthalpy export; its atmospheric vaporisation is outside the soil energy control volume.',
    ])
    if result['ledger'] is None:
        return result
    rows = candidates[:len(result['accepted_steps'])]
    for accepted, transfers in zip(result['accepted_steps'], rows):
        accepted['surface_gross'] = transfers
    if rows:
        total = {key: math.fsum(row[key] for row in rows) for key in rows[0]}
    else:
        total = dict.fromkeys(('surface_evaporation_m', 'surface_evaporation_enthalpy_j_m2',
            'surface_evaporation_latent_heat_j_m2', 'infiltration_m', 'rain_excess_runoff_m', 'surface_exfiltration_m',
            'surface_exfiltration_enthalpy_j_m2', 'surface_heat_before_evaporation_j_m2'), 0.)
    ledger = result['ledger']
    ledger.update(total)
    ledger['surface_runoff_m'] = ledger['rain_excess_runoff_m']+ledger['surface_exfiltration_m']
    ledger['surface_input_representation_residual_m'] = ledger['surface_input_m']-ledger['infiltration_m']-ledger['rain_excess_runoff_m']
    constants = model['constants']
    rain_h = constants['water_density_kg_m3']*(constants['latent_heat_j_kg']+
        constants['water_heat_capacity_j_kg_k']*(event['surface_water_temperature_k']-constants['melting_temperature_k']))
    ledger['rain_excess_enthalpy_j_m2'] = ledger['rain_excess_runoff_m']*rain_h
    ledger['surface_runoff_enthalpy_j_m2'] = ledger['rain_excess_enthalpy_j_m2']+ledger['surface_exfiltration_enthalpy_j_m2']
    ledger['potential_surface_evaporation_m'] = event['surface_evaporation']['potential_m_s']*ledger['elapsed_s']
    ledger['unmet_surface_evaporation_m'] = ledger['potential_surface_evaporation_m']-ledger['surface_evaporation_m']
    ledger['surface_face_semantics'] = 'NET_LIQUID_INPUT_MINUS_LIQUID_EXFILTRATION_MINUS_EVAPORATION; gross runoff and vapour are separate'
    records = [model, *model['layers'], event, event['top_heat'], event['bottom_heat'],
               event['bottom_water'], event['surface_evaporation'], event['surface_evaporation']['applicability']]
    if 'uptake' in event and 'source_status' in event['uptake']:
        records.append(event['uptake'])
    if any(record['source_status'] == 'SYNTHETIC TEST' for record in records):
        result['source_status'] = 'SYNTHETIC TEST'
    return _plain_receipt(result)


def audit_event(model, event, result, controls):
    """Independent finite-volume and gross-surface readback without re-solving."""
    if 'surface_evaporation' not in event:
        return native_audit.event(model, event, result, controls)
    if result.get('status') != 'MODELLED':
        raise ValueError('complete R22 evaporation event required')
    _event(event, len(model['layers']))
    if (event['surface_evaporation']['applicability']['donor_layer_id'] != model['layers'][0]['layer_id']
            or result['initial_state']['ice_water'][0] > 0 or result['final_state']['ice_water'][0] > 0):
        raise ValueError('audited surface donor identity or unfrozen regime differs')
    ledger = result['ledger']
    wt, et = controls['water_atol_m'], controls['energy_atol_j_m2']
    close = native_audit._close
    evaporation = ledger['surface_evaporation_m']
    potential = event['surface_evaporation']['potential_m_s']*event['duration_s']
    if (not 0 <= evaporation <= potential+wt or ledger['rain_excess_runoff_m'] < -wt
            or ledger['surface_runoff_m'] < -wt or ledger['infiltration_m'] < 0
            or ledger['surface_exfiltration_m'] < 0):
        raise ValueError('invalid finite surface evaporation/runoff account')
    close(ledger['potential_surface_evaporation_m'], potential, wt, 'potential surface evaporation')
    close(ledger['unmet_surface_evaporation_m'], potential-evaporation, wt, 'unmet surface evaporation')
    close(ledger['surface_input_m']-ledger['surface_runoff_m']-evaporation,
          ledger['face_water_m'][0], wt, 'disjoint infiltration/runoff/evaporation')
    close(ledger['infiltration_m']-ledger['surface_exfiltration_m']-evaporation,
          ledger['face_water_m'][0], wt, 'gross liquid versus net water face')
    constants = model['constants']
    rain_h = constants['water_density_kg_m3']*(constants['latent_heat_j_kg']+
        constants['water_heat_capacity_j_kg_k']*(event['surface_water_temperature_k']-constants['melting_temperature_k']))
    close(ledger['surface_runoff_enthalpy_j_m2'], ledger['rain_excess_runoff_m']*rain_h+
        ledger['surface_exfiltration_enthalpy_j_m2'], et, 'runoff liquid enthalpy')
    close(ledger['surface_input_m']*rain_h-ledger['surface_runoff_enthalpy_j_m2']-
        ledger['surface_evaporation_enthalpy_j_m2'], ledger['face_advective_energy_j_m2'][0], et, 'surface liquid energy')
    close(ledger['surface_evaporation_latent_heat_j_m2'], evaporation*constants['water_density_kg_m3']*
        event['surface_evaporation']['latent_heat_vaporisation_j_kg'], et, 'vaporisation latent energy')
    close(ledger['surface_heat_before_evaporation_j_m2']-ledger['surface_evaporation_latent_heat_j_m2'],
          ledger['face_conductive_energy_j_m2'][0], et, 'evaporative top cooling')
    for key in ('surface_evaporation_m', 'surface_evaporation_enthalpy_j_m2', 'surface_evaporation_latent_heat_j_m2',
                'infiltration_m', 'rain_excess_runoff_m', 'surface_exfiltration_m', 'surface_exfiltration_enthalpy_j_m2',
                'surface_heat_before_evaporation_j_m2'):
        close(ledger[key], math.fsum(row['surface_gross'][key] for row in result['accepted_steps']),
              wt if key.endswith('_m') else et, 'accepted surface substeps '+key)
    # Native audit independently reconstructs all layer phase energies and
    # extensive balances. Present its legacy diagnostic-only surface fields in
    # native net-face semantics; all REAL gross surface accounts were audited
    # above. Conserved face transfers, layer states and residuals are unchanged.
    native = deepcopy(result)
    old = native['ledger']
    old['infiltration_m'], old['surface_exfiltration_m'] = old['face_downward_m'][0], old['face_upward_m'][0]
    old['rain_excess_runoff_m'] = old['surface_input_m']-old['infiltration_m']
    old['surface_runoff_m'] = old['surface_input_m']-old['face_water_m'][0]
    old['rain_excess_enthalpy_j_m2'] = old['rain_excess_runoff_m']*rain_h
    old['surface_input_representation_residual_m'] = old['surface_input_m']-old['infiltration_m']-old['rain_excess_runoff_m']
    checked = native_audit.event(model, event, native, controls)
    return {**checked, 'surface_scope': 'DISJOINT_GROSS_LIQUID_AND_VAPOUR_WATER_ENTHALPY_LATENT_ACCOUNTS',
            'surface_evaporation_m': evaporation}


audit = audit_event
