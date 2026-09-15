"""Timed SURFACE irrigation, unchanged R13 soil, and compatible seasonal Ky.

This is a fixed-column, supplied-crop reference, not a second soil bucket. The
only actual water/heat evolution is R13. Ky is the source-bound R1 seasonal
relation, evaluated on explicitly compatible transpiration totals. All yield,
root, salinity, oxygen and evaporation applicability is caller supplied.
"""
from copy import deepcopy
from fractions import Fraction as F
import json
import math
from types import FunctionType

from work.generator_upgrade_r13 import soil
from . import _native_human as human, _native_crop as crop_source
from .quantities import exact, ident, q, plain

SCHEMA = 'diadem.coupled-soil-agriculture.r21'
YIELD_SCHEMA = 'diadem.coupled-soil-crop-yield.r21'
PRODUCER_KIND = 'ACTUAL_R13_COUPLED_SOIL_CROP_YIELD'
CONTEXT = {'world_id', 'snapshot_id', 'calendar_id', 'spatial_frame_id',
           'vertical_reference', 'scenario_id'}
PLAN = {'plan_id', 'support_id', 'irrigation_sink_id', 'settlement_id', 'area_m2',
        'context', 'terrain_generation', 'model', 'initial_state', 'controls',
        'events', 'crops', 'bare_soil_evaporation', 'evidence', 'source_status'}
STATUS = {'WORKING NON-CANON', 'SYNTHETIC TEST', 'UNKNOWN'}


def _source(row):
    ident(row.get('evidence'), 'physical evidence')
    if row.get('source_status') not in STATUS:
        raise ValueError('working/synthetic/unknown applicability status required')
    return row['source_status'] != 'UNKNOWN'


def _bounded(value):
    if max(value.numerator.bit_length(), value.denominator.bit_length()) > 8192:
        raise ValueError('physical exact account exceeds 8192 bits')
    return value


def _float(value, label):
    result = float(value)
    if not math.isfinite(result) or value != 0 and result == 0:
        raise ValueError(label+' cannot be represented by native binary64')
    return result


def _clock(value, label):
    value = q(value, label)
    result = _float(value, label)
    if F(result) != value:
        raise ValueError(label+' must be exactly representable on the native clock')
    return value


def _observed_advance(model, state, event, controls):
    """Observe a conservative superset of accepted endpoints; mutate no native globals.

R13 publishes flux histories, not half-step states. The private clone executes
the identical advance code and original step function. Including successful
rejected trials can reject a crop unnecessarily, but cannot conceal accepted
ice/saturation. This certifies discrete endpoint applicability, not a continuous
hydroperiod between finite-volume timesteps.
"""
    count = len(model['layers'])
    envelope = {'min_temperature_k': list(state['temperature_k']),
                'max_ice_water': list(state['ice_water']),
                'max_liquid_head_m': list(state['liquid_head_m']),
                'successful_trial_endpoints': 0,
                'scope': 'INITIAL_AND_ALL_SUCCESSFUL_TRIAL_ENDPOINTS; conservative superset of accepted half steps, not continuous hydroperiod'}
    def step(*args, **kwargs):
        result, reason = soil._step(*args, **kwargs)
        if result is not None:
            envelope['successful_trial_endpoints'] += 1
            for i in range(count):
                envelope['min_temperature_k'][i] = min(envelope['min_temperature_k'][i], float(result['temperature'][i]))
                envelope['max_ice_water'][i] = max(envelope['max_ice_water'][i], float(result['props']['ice'][i]))
                envelope['max_liquid_head_m'][i] = max(envelope['max_liquid_head_m'][i], float(result['props']['liquid_head'][i]))
        return result, reason
    namespace = dict(soil.advance.__globals__)
    namespace['_step'] = step
    advance = FunctionType(soil.advance.__code__, namespace, soil.advance.__name__,
                           soil.advance.__defaults__, soil.advance.__closure__)
    result = advance(model, state, event, controls)
    result['r21_trajectory'] = envelope
    return result


def _root_support(crop, model, state):
    root = crop['root_support']
    exact(root, {'rooted_thickness_by_layer_m', 'field_capacity_by_layer',
                 'wilting_point_by_layer', 'layer_accessibility',
                 'endpoint_convention', 'evidence', 'source_status'}, 'crop root support')
    known = _source(root)
    ident(root['endpoint_convention'], 'FC/WP endpoint convention')
    ids = [layer['layer_id'] for layer in model['layers']]
    for key in ('rooted_thickness_by_layer_m', 'field_capacity_by_layer',
                'wilting_point_by_layer', 'layer_accessibility'):
        if type(root[key]) is not dict or set(root[key]) != set(ids):
            raise ValueError('complete exact hydraulic layer inventory required for '+key)
    rows, closed = [], False
    for i, layer in enumerate(model['layers']):
        identity = layer['layer_id']; dz = q(layer['thickness_m'])
        rooted = q(root['rooted_thickness_by_layer_m'][identity])
        fc = q(root['field_capacity_by_layer'][identity]); wp = q(root['wilting_point_by_layer'][identity])
        access = root['layer_accessibility'][identity]
        if access not in ('ACCESSIBLE', 'EXCLUDED'):
            raise ValueError('explicit accessible/excluded root layer required')
        if (rooted > dz or (closed and rooted) or (rooted and access != 'ACCESSIBLE')
                or not q(layer['theta_r']) <= wp < fc <= q(layer['theta_s'])):
            raise ValueError('root depth/access or distinct FC/WP endpoints incompatible with actual column')
        closed = closed or rooted < dz or access == 'EXCLUDED'
        liquid = q(state['liquid_water'][i])
        rows.append({'layer_id': identity, 'rooted_thickness_m': rooted,
            'field_capacity': fc, 'wilting_point': wp,
            'initial_liquid_fraction': liquid,
            'total_available_water_mm': 1000*rooted*(fc-wp),
            'initial_depletion_mm_unclipped': 1000*rooted*(fc-liquid),
            'initial_above_fc_excess_mm': 1000*rooted*max(F(0), liquid-fc),
            'initial_below_wp_deficit_mm': 1000*rooted*max(F(0), wp-liquid),
            'initial_water_at_or_below_wp_mm': 1000*rooted*min(wp, liquid)})
    if not any(row['rooted_thickness_m'] for row in rows):
        raise ValueError('positive explicitly accessible crop root support required')
    return known, rows


def _validate(plan, deliveries):
    raw = json.dumps({'plan': plan, 'deliveries': deliveries}, sort_keys=True,
                     separators=(',', ':'), allow_nan=False)
    if len(raw.encode()) > 8*1024*1024:
        raise ValueError('bounded 8 MiB coupled agriculture input required')
    plan, deliveries = deepcopy(plan), deepcopy(deliveries)
    exact(plan, PLAN, 'coupled crop plan')
    _source(plan)
    if plan['source_status'] == 'UNKNOWN':
        raise ValueError('physical scenario must be supplied; crop applicability may be UNKNOWN')
    for key in ('plan_id', 'support_id', 'irrigation_sink_id', 'settlement_id', 'terrain_generation'):
        ident(plan[key], key)
    exact(plan['context'], CONTEXT, 'common physical context')
    for value in plan['context'].values():
        ident(value, 'common context identity')
    area = q(plan['area_m2'], positive=True)
    soil._model(plan['model']); soil._controls(plan['controls'], plan['model'])
    soil._read_state(plan['model'], plan['initial_state'])
    if plan['source_status'] == 'WORKING NON-CANON' and any(
            row['source_status'] == 'SYNTHETIC TEST' for row in [plan['model'], *plan['model']['layers']]):
        raise ValueError('synthetic physical model cannot be promoted into a working plan')
    bare = plan['bare_soil_evaporation']
    exact(bare, {'kind', 'evidence', 'source_status'}, 'explicit evaporation reference')
    _source(bare)
    if bare['kind'] != 'ZERO_EXPLICIT_REFERENCE':
        raise ValueError('bare-soil evaporation is not implemented by R13; explicit zero reference required')
    if type(plan['events']) is not list or not 1 <= len(plan['events']) <= 366:
        raise ValueError('one to 366 explicit constant-forcing soil events required')
    if type(plan['crops']) is not list or not 1 <= len(plan['crops']) <= 32:
        raise ValueError('one to 32 explicit sequential crop seasons required')
    crops, events, before = {}, {}, _clock(plan['initial_state']['elapsed_seconds'], 'initial soil time')
    for crop in plan['crops']:
        exact(crop, {'crop_id', 'commodity_id', 'start_seconds', 'end_seconds',
                     'potential_yield_kg_m2', 'yield_response_factor', 'minimum_valid_et_ratio',
                     'yield_mass_basis', 'conversion', 'et_compatibility', 'root_support',
                     'regime', 'evidence', 'source_status'}, 'physical crop season')
        _source(crop); identity = ident(crop['crop_id'], 'crop ID')
        ident(crop['commodity_id'], 'commodity ID')
        if identity in crops or crop['yield_mass_basis'] != 'DRY_HARVEST_KG':
            raise ValueError('unique crop identity and explicit dry-harvest yield basis required')
        start = _clock(crop['start_seconds'], 'crop start'); end = _clock(crop['end_seconds'], 'crop end')
        if end <= start:
            raise ValueError('positive crop season required')
        for key in ('potential_yield_kg_m2', 'yield_response_factor', 'minimum_valid_et_ratio'):
            if crop[key] is not None:
                q(crop[key], key)
        if crop['minimum_valid_et_ratio'] is not None and q(crop['minimum_valid_et_ratio']) > 1:
            raise ValueError('minimum valid ET ratio exceeds one')
        _root_support(crop, plan['model'], plan['initial_state'])
        crops[identity] = crop
    sorted_crops = sorted(crops.values(), key=lambda c: q(c['start_seconds']))
    if any(q(a['end_seconds']) > q(b['start_seconds']) for a, b in zip(sorted_crops, sorted_crops[1:])):
        raise ValueError('whole-plot crop seasons overlap; shared soil/land cannot be double counted')
    for row in plan['events']:
        exact(row, {'event_id', 'start_seconds', 'end_seconds', 'soil_event', 'crop_id'}, 'timed soil event')
        identity = ident(row['event_id'], 'event ID')
        start = _clock(row['start_seconds'], 'event start'); end = _clock(row['end_seconds'], 'event end')
        if identity in events or start != before or end <= start:
            raise ValueError('unique contiguous constant-forcing events required')
        before = end
        soil._event(row['soil_event'], len(plan['model']['layers']))
        if F(row['soil_event']['duration_s']) != end-start:
            raise ValueError('event duration differs from the exact shared clock')
        if row['crop_id'] is not None and row['crop_id'] not in crops:
            raise ValueError('unknown crop event attribution')
        active = [c for c in sorted_crops if q(c['start_seconds']) < end and q(c['end_seconds']) > start]
        if len(active) != (row['crop_id'] is not None) or active and (
                active[0]['crop_id'] != row['crop_id'] or q(active[0]['start_seconds']) > start or q(active[0]['end_seconds']) < end):
            raise ValueError('split soil events at every crop boundary; exact crop/time attribution required')
        if active and 'uptake' not in row['soil_event']:
            raise ValueError('actual crop uptake requires potential demand and supplied Feddes response, not prescribed withdrawal')
        if not active and (row['soil_event'].get('potential_root_demand_m_s', 0) or any(row['soil_event'].get('root_withdrawal_m_s', []))):
            raise ValueError('fallow has no undeclared crop root demand')
        events[identity] = row
    for crop in sorted_crops:
        own = [row for row in plan['events'] if row['crop_id'] == crop['crop_id']]
        if not own or q(own[0]['start_seconds']) != q(crop['start_seconds']) or q(own[-1]['end_seconds']) != q(crop['end_seconds']):
            raise ValueError('crop season is not completely covered by actual soil events')
    if type(deliveries) is not list or len(deliveries) > 4096:
        raise ValueError('bounded actual surface-delivery list required')
    by_event = {key: [] for key in events}; used, uses = set(), set()
    required = {'event_id', 'delivery_id', 'source_use_id', 'support_id', 'receiving_sink_id',
        'start_seconds', 'end_seconds', 'soil_boundary_m3', 'temperature_k',
        'delivery_boundary', 'evidence', 'source_status'}
    for delivery in deliveries:
        if type(delivery) is not dict or not required <= set(delivery):
            raise ValueError('complete actual soil-boundary delivery record required')
        if not _source(delivery):
            raise ValueError('unknown water cannot become actual surface input')
        identity = ident(delivery['delivery_id'], 'delivery ID'); use = ident(delivery['source_use_id'], 'water source-use ID')
        event = events.get(delivery['event_id'])
        if identity in used or use in uses or event is None:
            raise ValueError('unknown event or reused physical irrigation delivery/source debit')
        used.add(identity); uses.add(use)
        if (delivery['delivery_boundary'] != 'SURFACE_APPLICATION' or delivery['support_id'] != plan['support_id']
                or delivery['receiving_sink_id'] != plan['irrigation_sink_id']
                or q(delivery['start_seconds']) != q(event['start_seconds'])
                or q(delivery['end_seconds']) != q(event['end_seconds'])):
            raise ValueError('irrigation support/sink/boundary/time mismatch; split before entry')
        q(delivery['soil_boundary_m3']); q(delivery['temperature_k'], positive=True)
        by_event[delivery['event_id']].append(delivery)
    return plan, by_event, crops, area


def _surface(model, event, deliveries, area, controls):
    result = deepcopy(event); dt = F(event['duration_s'])
    constants = {k: F(v) for k, v in model['constants'].items()}
    rho, latent, cw, tm = (constants[k] for k in ('water_density_kg_m3', 'latent_heat_j_kg',
                            'water_heat_capacity_j_kg_k', 'melting_temperature_k'))
    def enthalpy(t):
        return rho*(latent+cw*(t-tm))
    rain = F(event['surface_water_flux_m_s'])*dt*area
    irrigation = sum((q(row['soil_boundary_m3']) for row in deliveries), F(0))
    volume = _bounded(rain+irrigation)
    energy = _bounded(rain*enthalpy(F(event['surface_water_temperature_k'])) + sum(
        (q(row['soil_boundary_m3'])*enthalpy(q(row['temperature_k'])) for row in deliveries), F(0)))
    temperature = F(event['surface_water_temperature_k']) if not volume else tm+(energy/(rho*volume)-latent)/cw
    result['surface_water_flux_m_s'] = _float(volume/(area*dt), 'combined surface water rate')
    result['surface_water_temperature_k'] = _float(temperature, 'mixed incoming water temperature')
    represented_volume = F(result['surface_water_flux_m_s'])*dt*area
    represented_energy = represented_volume*enthalpy(F(result['surface_water_temperature_k']))
    volume_residual, energy_residual = represented_volume-volume, represented_energy-energy
    if abs(volume_residual)/area > F(controls['water_atol_m']) or abs(energy_residual)/area > F(controls['energy_atol_j_m2']):
        raise ValueError('surface input representation exceeds unchanged native physical tolerance')
    receipt = plain({'rain_volume_m3': rain, 'soil_boundary_irrigation_m3': irrigation,
        'requested_surface_volume_m3': volume, 'represented_surface_volume_m3': represented_volume,
        'incoming_liquid_enthalpy_j': energy, 'represented_incoming_liquid_enthalpy_j': represented_energy,
        'volume_representation_residual_m3': volume_residual,
        'energy_representation_residual_j': energy_residual,
        'mixed_temperature_k_exact': temperature, 'deliveries': deliveries,
        'application_efficiency_applied_here': False, 'root_zone_injection': False})
    return result, receipt


def _yield(crop, model, initial, event_rows, input_sha):
    known, root = _root_support(crop, model, initial)
    compatibility = crop['et_compatibility']; regime = crop['regime']
    exact(compatibility, {'kind', 'potential_basis', 'actual_basis', 'yield_response_basis',
                         'evidence', 'source_status'}, 'ET/Ky compatibility')
    known = _source(compatibility) and known and _source(crop)
    exact(regime, {'kind', 'soil_nonsaline', 'delivered_water_nonsaline',
                  'oxygen_applicability', 'evidence', 'source_status'}, 'crop applicability')
    known = _source(regime) and known
    for key in ('soil_nonsaline', 'delivered_water_nonsaline'):
        exact(regime[key], {'status', 'evidence', 'source_status'}, key)
        known = _source(regime[key]) and regime[key]['status'] == 'SUPPORTED' and known
        if regime[key]['status'] not in ('SUPPORTED', 'UNKNOWN', 'OUTSIDE_REGIME'):
            raise ValueError('explicit salinity applicability decision required')
    oxygen = regime['oxygen_applicability']
    exact(oxygen, {'maximum_liquid_head_m', 'maximum_saturated_duration_s',
                   'trajectory_basis', 'evidence', 'source_status'}, 'oxygen applicability')
    known = _source(oxygen) and known
    head = float(oxygen['maximum_liquid_head_m'])
    if not math.isfinite(head) or head >= 0 or isinstance(oxygen['maximum_liquid_head_m'], bool):
        raise ValueError('explicit finite unsaturated liquid-head ceiling required')
    if q(oxygen['maximum_saturated_duration_s']) != 0 or oxygen['trajectory_basis'] != 'R13_DISCRETE_ENDPOINTS_CONSERVATIVE_TRIAL_ENVELOPE':
        known = False
    reasons = []
    if regime['kind'] != 'FIXED_ROOT_UNFROZEN_NONSALINE_WELL_DRAINED':
        known = False
    if (compatibility['kind'] not in ('NEGLIGIBLE_SOIL_EVAPORATION_TRANSPIRATION_DOMINATED', 'MATCHED_TRANSPIRATION_KY_CALIBRATION')
            or compatibility['potential_basis'] != 'POTENTIAL_ROOT_TRANSPIRATION'
            or compatibility['actual_basis'] != 'R13_ROOT_WITHDRAWAL'
            or compatibility['yield_response_basis'] != 'COMPATIBLE_TRANSPIRATION_RATIO'):
        known = False
    actual = sum((F(row['result']['ledger']['root_withdrawal_m']) for row in event_rows), F(0))
    potential = sum((F(row['native_event']['potential_root_demand_m_s'])*F(row['native_event']['duration_s']) for row in event_rows), F(0))
    result = {'schema': YIELD_SCHEMA, 'status': 'UNKNOWN', 'crop_id': crop['crop_id'],
        'yield_kg_m2': None, 'actual_to_potential_et_ratio': None,
        'actual_root_transpiration_m': str(actual), 'potential_root_transpiration_m': str(potential),
        'et_compatibility': deepcopy(compatibility), 'root_support': plain(root),
        'soil_input_sha256': input_sha, 'source_status': crop['source_status'],
        'evidence': crop['evidence'], 'reasons': reasons,
        'yield_law': 'R1 seasonal Ky: Y=Ym*(1-Ky*(1-Ta/Tp)); no second soil bucket or drought multiplier',
        'crop_source_file_sha256': getattr(crop_source, '_R12_EXECUTED_SHA256', None),
        'continuous_hydroperiod_certified': False, 'physical_acceptance': False}
    for row in event_rows:
        weights = row['native_event']['uptake']['weights']
        trajectory = row['result']['r21_trajectory']
        for i, support in enumerate(root):
            if weights[i] > 0 and not support['rooted_thickness_m']:
                raise ValueError('Feddes weights withdraw outside explicitly accessible crop roots')
            if trajectory['max_ice_water'][i] > 0 or trajectory['min_temperature_k'][i] < model['constants']['melting_temperature_k']:
                reasons.append('growing-season column ice/freezing is outside this crop extension')
            if support['rooted_thickness_m'] and trajectory['max_liquid_head_m'][i] > head:
                reasons.append('supplied zero-saturation/oxygen liquid-head criterion exceeded')
    if any(regime[k]['status'] == 'OUTSIDE_REGIME' for k in ('soil_nonsaline', 'delivered_water_nonsaline')):
        reasons.append('supplied soil or delivered-water salinity is outside regime')
    if reasons:
        return {**result, 'status': 'OUTSIDE_REGIME', 'reasons': sorted(set(reasons))}
    coefficients = [crop[key] for key in ('potential_yield_kg_m2', 'yield_response_factor', 'minimum_valid_et_ratio')]
    if not known or any(value is None for value in coefficients):
        return {**result, 'reasons': ['missing compatible ET/Ky, root or applicability evidence']}
    if potential == 0:
        return {**result, 'status': 'OUTSIDE_REGIME', 'reasons': ['zero potential seasonal transpiration']}
    ratio = _bounded(actual/potential)
    factor = 1-q(crop['yield_response_factor'])*(1-ratio)
    if actual > potential or ratio < q(crop['minimum_valid_et_ratio']) or factor < 0:
        return {**result, 'status': 'OUTSIDE_REGIME', 'actual_to_potential_et_ratio': str(ratio),
                'reasons': ['actual/potential transpiration or deficit outside supplied Ky regime; no clipping']}
    return {**result, 'status': 'MODELLED', 'yield_kg_m2': str(_bounded(q(crop['potential_yield_kg_m2'])*factor)),
            'actual_to_potential_et_ratio': str(ratio)}


def run(plan, water_deliveries, *, cache_step=None):
    """Run all soil events once, carrying actual state; return timed native harvests.

cache_step(name, invocation, producer) must return the authenticated producer
result; the parent binds owner/context/source/cache identity. Source-side debit,
permissions and delivery queue validation are upstream, never recreated here.
"""
    plan, deliveries, crops, area = _validate(plan, water_deliveries)
    state = deepcopy(plan['initial_state']); rows, crop_initial = [], {}
    inputs = {'plan': plan, 'actual_deliveries': water_deliveries}
    input_sha = human.digest(inputs)
    water_bound, energy_bound = F(0), F(0)
    for row in plan['events']:
        if row['crop_id'] not in crop_initial and row['crop_id'] is not None:
            crop_initial[row['crop_id']] = deepcopy(state)
        event, surface = _surface(plan['model'], row['soil_event'], deliveries[row['event_id']], area, plan['controls'])
        water_bound += abs(F(surface['volume_representation_residual_m3']))
        energy_bound += abs(F(surface['energy_representation_residual_j']))
        if water_bound/area > F(plan['controls']['water_atol_m']) or energy_bound/area > F(plan['controls']['energy_atol_j_m2']):
            raise ValueError('cumulative input representation exceeds unchanged per-column tolerance')
        invocation = {'model': plan['model'], 'state': state, 'event': event, 'controls': plan['controls'],
                      'context': plan['context'], 'terrain_generation': plan['terrain_generation'],
                      'support_id': plan['support_id'], 'area_m2': plan['area_m2'], 'surface_input': surface}
        def produce(invocation=deepcopy(invocation)):
            return _observed_advance(invocation['model'], invocation['state'], invocation['event'], invocation['controls'])
        result = produce() if cache_step is None else cache_step('soil:'+plan['plan_id']+':'+row['event_id'], invocation, produce)
        if type(result) is not dict or result.get('initial_state') != state or 'r21_trajectory' not in result:
            raise ValueError('cached actual soil result does not match invocation/trajectory')
        record = {'event_id': row['event_id'], 'crop_id': row['crop_id'],
            'start_seconds': str(q(row['start_seconds'])), 'end_seconds': str(q(row['end_seconds'])),
            'native_event': event, 'surface_input': surface, 'result': result}
        rows.append(record)
        if result['status'] != 'MODELLED':
            return {'schema': SCHEMA, 'status': result['status'], 'reason': result.get('reason'),
                'source_status': plan['source_status'], 'events': rows, 'final_state': None,
                'last_accepted_state': result.get('last_accepted_state'), 'harvests': [],
                'total_edible_dry_kg': None, 'total_edible_energy_kcal': None,
                'source_input_sha256': input_sha, 'physical_acceptance': False}
        state = deepcopy(result['final_state']); soil._read_state(plan['model'], state)
        if F(state['elapsed_seconds']) != q(row['end_seconds']):
            raise ValueError('actual soil clock differs from agreed event endpoint')
        ledger = result['ledger']; c = plan['model']['constants']
        incoming_h = c['water_density_kg_m3']*(c['latent_heat_j_kg']+c['water_heat_capacity_j_kg_k']*(event['surface_water_temperature_k']-c['melting_temperature_k']))
        surface_export = ledger['rain_excess_enthalpy_j_m2']+ledger['infiltration_m']*incoming_h-ledger['face_advective_energy_j_m2'][0]
        record['actual_exports'] = {'surface_runoff_m3': str(F(ledger['surface_runoff_m'])*area),
            'rain_excess_m3': str(F(ledger['rain_excess_runoff_m'])*area),
            'surface_exfiltration_m3': str(F(ledger['surface_exfiltration_m'])*area),
            'bottom_downward_m3': str(F(ledger['bottom_downward_m'])*area),
            'bottom_upward_m3': str(F(ledger['bottom_upward_m'])*area),
            'root_withdrawal_m3': str(F(ledger['root_withdrawal_m'])*area),
            'surface_export_enthalpy_j': str(F(surface_export)*area),
            'bottom_net_advective_enthalpy_j': str(F(ledger['face_advective_energy_j_m2'][-1])*area),
            'root_enthalpy_j': str(F(ledger['root_enthalpy_j_m2'])*area),
            'water_residual_m3': str(F(ledger['water_residual_m'])*area),
            'energy_residual_j': str(F(ledger['energy_residual_j_m2'])*area),
            'return_flow_credited': False}
    harvests, yields = [], []
    for identity, crop in crops.items():
        own = [row for row in rows if row['crop_id'] == identity]
        prediction = _yield(crop, plan['model'], crop_initial[identity], own, input_sha)
        if plan['bare_soil_evaporation']['source_status'] == 'UNKNOWN':
            prediction.update(status='UNKNOWN', yield_kg_m2=None,
                              reasons=['zero-evaporation reference applicability is UNKNOWN'])
        yields.append(prediction)
        if prediction['status'] != 'MODELLED':
            continue
        conversion = deepcopy(crop['conversion'])
        density = q(conversion.pop('edible_energy_kcal_kg'), positive=True)
        cf = q(conversion['carbon_fraction_dry_matter'], positive=True)
        producer = {'status': 'MODELLED', 'event_id': identity, 'support_id': plan['support_id'],
            'harvested_carbon_kg_m2': str(q(prediction['yield_kg_m2'])*cf),
            'source_input_sha256': human.digest({'inputs': inputs, 'crop': prediction, 'events': own}),
            'source_use_id': 'r21-physical-harvest:'+plan['plan_id']+':'+identity,
            'evidence_id': crop['evidence'], 'available_after_seconds': str(q(crop['end_seconds'])),
            'source_status': plan['source_status'], 'crop_receipt': prediction}
        harvest = human.harvest_from_ecosystem(producer, harvest_id=plan['plan_id']+':'+identity,
            settlement_id=plan['settlement_id'], commodity_id=crop['commodity_id'],
            support_id=plan['support_id'], area_m2=area, conversion=conversion,
            available_at_seconds=crop['end_seconds'])
        harvest['conversion']['producer_kind'] = PRODUCER_KIND
        harvest['conversion']['irrigation_delivery_ids'] = sorted(d['delivery_id'] for row in own for d in deliveries[row['event_id']])
        harvest['edible_energy_kcal'] = str(q(harvest['quantity_kg'])*density)
        harvests.append(harvest)
    status = 'MODELLED' if all(row['status'] == 'MODELLED' for row in yields) else (
        'OUTSIDE_REGIME' if any(row['status'] == 'OUTSIDE_REGIME' for row in yields) else 'UNKNOWN')
    return {'schema': SCHEMA, 'status': status, 'soil_status': 'MODELLED',
        'source_status': plan['source_status'], 'source_input_sha256': input_sha,
        'initial_state': plan['initial_state'], 'final_state': state, 'last_accepted_state': state,
        'events': rows, 'crops': yields, 'harvests': harvests,
        'total_edible_dry_kg': str(sum((q(h['quantity_kg']) for h in harvests), F(0))) if status == 'MODELLED' else None,
        'total_edible_energy_kcal': str(sum((q(h['edible_energy_kcal']) for h in harvests), F(0))) if status == 'MODELLED' else None,
        'input_representation_absolute_bound_m3': str(water_bound),
        'input_representation_absolute_bound_j': str(energy_bound),
        'physical_acceptance': False, 'freight_feasibility': 'UNKNOWN',
        'scope': 'Supplied finite fixed geometry, crop schedules and compatibility; R13 sole soil ledger. No second bucket, root-zone injection, source refill, automatic return, frost/salt biology or continuous-hydroperiod proof.'}


def reference_plan():
    """Tiny fully explicit SYNTHETIC TEST fixture; no Diadem coefficients."""
    evidence = 'Synthetic 200-second irrigation/crop connection oracle; not agronomic or Diadem calibration'
    source = {'evidence': evidence, 'source_status': 'SYNTHETIC TEST'}
    layer = dict(layer_id='test-soil', thickness_m=.1, theta_r=.05, theta_s=.45,
        vg_alpha_per_m=2., vg_n=1.6, mualem_l=.5, saturated_conductivity_m_s=1e-6,
        ice_impedance=7., dry_heat_capacity_j_m3_k=1.4e6, conductivity_dry_w_m_k=.25,
        conductivity_saturated_unfrozen_w_m_k=1.6, conductivity_saturated_frozen_w_m_k=2.2, **source)
    model = {'layers': [layer], 'constants': {'water_density_kg_m3': 1000.,
        'water_heat_capacity_j_kg_k': 4180., 'ice_heat_capacity_j_kg_k': 2100.,
        'latent_heat_j_kg': 334000., 'melting_temperature_k': 273.15, 'gravity_m_s2': 9.80665}, **source}
    controls = {'initial_step_s': 100., 'min_step_s': 1e-4, 'max_step_s': 1000.,
        'water_atol_m': 1e-8, 'water_fraction_atol': 1e-5, 'energy_atol_j_m2': .1,
        'head_atol_m': 1e-3, 'temperature_atol_k': 1e-3, 'relative_tolerance': 1e-4,
        'nonlinear_water_atol_m': 1e-11, 'nonlinear_energy_atol_j_m2': 1e-4,
        'min_head_m': -1000., 'max_head_m': 100., 'min_temperature_k': 230.,
        'max_temperature_k': 330., 'max_steps': 2000, 'max_nonlinear_evaluations': 80}
    event = {'duration_s': 100., 'surface_water_flux_m_s': 0., 'surface_water_temperature_k': 280.,
        'top_heat': {'kind': 'flux', 'value': 0., **source},
        'bottom_heat': {'kind': 'flux', 'value': 0., **source},
        'bottom_water': {'kind': 'free_drainage', **source},
        'uptake': {'weights': [1.], 'dry_zero_head_m': -100., 'dry_full_head_m': -2.,
                   'wet_full_head_m': -.2, 'wet_zero_head_m': -.01, **source},
        'potential_root_demand_m_s': 1e-7, **source}
    crop = {'crop_id': 'test-crop', 'commodity_id': 'test-grain', 'start_seconds': '0', 'end_seconds': '200',
        'potential_yield_kg_m2': '1', 'yield_response_factor': '1', 'minimum_valid_et_ratio': '0',
        'yield_mass_basis': 'DRY_HARVEST_KG',
        'conversion': {'mass_basis': 'EDIBLE_DRY_FOOD_KG', 'carbon_fraction_dry_matter': '1/2',
            'edible_fraction': '1', 'processing_loss_fraction': '0', 'food_quality_evidence': evidence,
            'evidence_id': evidence, 'source_status': 'SYNTHETIC TEST', 'edible_energy_kcal_kg': '3000'},
        'et_compatibility': {'kind': 'NEGLIGIBLE_SOIL_EVAPORATION_TRANSPIRATION_DOMINATED',
            'potential_basis': 'POTENTIAL_ROOT_TRANSPIRATION', 'actual_basis': 'R13_ROOT_WITHDRAWAL',
            'yield_response_basis': 'COMPATIBLE_TRANSPIRATION_RATIO', **source},
        'root_support': {'rooted_thickness_by_layer_m': {'test-soil': str(F(.1))},
            'field_capacity_by_layer': {'test-soil': '.35'}, 'wilting_point_by_layer': {'test-soil': '.1'},
            'layer_accessibility': {'test-soil': 'ACCESSIBLE'}, 'endpoint_convention': 'Explicit synthetic measured-equivalent FC/WP, not theta_r/theta_s', **source},
        'regime': {'kind': 'FIXED_ROOT_UNFROZEN_NONSALINE_WELL_DRAINED',
            'soil_nonsaline': {'status': 'SUPPORTED', **source},
            'delivered_water_nonsaline': {'status': 'SUPPORTED', **source},
            'oxygen_applicability': {'maximum_liquid_head_m': -.1, 'maximum_saturated_duration_s': '0',
                'trajectory_basis': 'R13_DISCRETE_ENDPOINTS_CONSERVATIVE_TRIAL_ENVELOPE', **source}, **source}, **source}
    plan = {'plan_id': 'coupled-test-plot', 'support_id': 'coupled-test-support',
        'irrigation_sink_id': 'coupled-test-surface', 'settlement_id': 'test-settlement', 'area_m2': '1',
        'context': {key: 'synthetic-'+key for key in sorted(CONTEXT)},
        'terrain_generation': 'SYNTHETIC_FIXED_COLUMN_R21', 'model': model,
        'initial_state': soil.initial_state(model, [-3.], [280.]), 'controls': controls,
        'events': [{'event_id': 'soil-'+str(i), 'start_seconds': str(100*i), 'end_seconds': str(100*(i+1)),
            'soil_event': deepcopy(event), 'crop_id': 'test-crop'} for i in range(2)],
        'crops': [crop], 'bare_soil_evaporation': {'kind': 'ZERO_EXPLICIT_REFERENCE', **source}, **source}
    deliveries = [{'event_id': 'soil-0', 'delivery_id': 'test-delivery-0', 'source_use_id': 'test-water-debit-0',
        'support_id': plan['support_id'], 'receiving_sink_id': plan['irrigation_sink_id'],
        'start_seconds': '0', 'end_seconds': '100', 'soil_boundary_m3': '1/100000',
        'temperature_k': '281', 'delivery_boundary': 'SURFACE_APPLICATION', **source}]
    return plan, deliveries
