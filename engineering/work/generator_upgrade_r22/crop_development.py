"""Supplied thermal-stage crop development and disjoint ET demand (R22).

FAO AquaCrop 4.0 chapter 3, section 3.3.1 supplies the capped mean-temperature
GDD method. Stage thresholds, piecewise-constant coefficients, rooting depth,
post-maturity behaviour and applicability are ALL supplied, never crop defaults.
This is not AquaCrop's canopy, biomass or yield model. FAO56 chapter 7 motivates
separating transpiration from evaporation; neither a FAO56 depletion bucket nor
an automatic Kcb-to-pure-transpiration equivalence is introduced here.
"""
from copy import deepcopy
from fractions import Fraction as F
import hashlib
import json
import math

from work.generator_upgrade_r21.quantities import exact, ident, plain, q

SCHEMA = 'diadem.crop-development.r22'
THERMAL_SOURCE = 'https://www.fao.org/fileadmin/user_upload/faowater/docs/AquaCropV40Chapter3.pdf'
ET_SOURCE = 'https://www.fao.org/4/x0490e/x0490e0c.htm'
STATUS = {'CANON', 'WORKING NON-CANON', 'SYNTHETIC TEST', 'UNKNOWN'}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def _source(row):
    ident(row['evidence'], 'crop evidence')
    if row['source_status'] not in STATUS:
        raise ValueError('explicit crop source status required')
    return row['source_status'] != 'UNKNOWN'


def _signed(value, label):
    if type(value) not in (int, float, str, F):
        raise ValueError('finite explicit '+label+' required')
    try:
        result = F(value)
    except (ValueError, ZeroDivisionError, OverflowError) as error:
        raise ValueError('finite explicit '+label+' required') from error
    if max(result.numerator.bit_length(), result.denominator.bit_length()) > 8192:
        raise ValueError('bounded crop temperature required')
    return result


def _stage(stage, *, terminal=False):
    fields = {'stage_id', 'transpiration_coefficient', 'potential_soil_evaporation_coefficient',
              'maximum_total_coefficient', 'root_depth_m', 'evidence', 'source_status'}
    if not terminal:
        fields.add('end_thermal_time_cd')
    exact(stage, fields, 'supplied crop stage')
    known = _source(stage)
    ident(stage['stage_id'], 'crop stage ID')
    values = [stage[k] for k in fields-{'stage_id', 'evidence', 'source_status'}]
    if any(value is None for value in values):
        return False
    for key in fields-{'stage_id', 'evidence', 'source_status'}:
        q(stage[key], key)
    if q(stage['transpiration_coefficient'])+q(stage['potential_soil_evaporation_coefficient']) > q(stage['maximum_total_coefficient']):
        raise ValueError('disjoint ET coefficients exceed supplied total energy/demand cap')
    if q(stage['transpiration_coefficient']) and not q(stage['root_depth_m']):
        raise ValueError('nonzero transpiration requires supplied positive root depth')
    return known


def validate_profile(profile):
    exact(profile, {'profile_id', 'crop_id', 'thermal_method', 'thermal_day_seconds',
        'base_temperature_c', 'upper_temperature_c', 'forcing_interpretation',
        'coefficient_interpretation', 'root_distribution', 'stages', 'post_maturity',
        'evidence', 'source_status'}, 'crop development profile')
    known = _source(profile)
    for key in ('profile_id', 'crop_id'):
        ident(profile[key], key)
    if profile['thermal_method'] != 'FAO_AQUACROP_GDD_METHOD_1':
        raise ValueError('explicit supported thermal-time method required')
    if profile['forcing_interpretation'] != 'SUPPLIED_DAILY_EXTREMA_CONSTANT_THERMAL_RATE_WITHIN_INTERVAL':
        raise ValueError('explicit supplied within-interval thermal interpolation required')
    if profile['coefficient_interpretation'] != 'DISJOINT_PURE_TRANSPIRATION_AND_EXPOSED_SOIL_EVAPORATION':
        raise ValueError('pure transpiration applicability required; FAO basal Kcb can include soil evaporation')
    if profile['root_distribution'] != 'UNIFORM_DENSITY_OVER_ACCESSIBLE_ROOTED_LENGTH':
        raise ValueError('explicit supported root distribution required')
    if any(profile[key] is None for key in ('thermal_day_seconds', 'base_temperature_c', 'upper_temperature_c')):
        known = False
    else:
        q(profile['thermal_day_seconds'], positive=True)
        if _signed(profile['upper_temperature_c'], 'upper temperature') <= _signed(profile['base_temperature_c'], 'base temperature'):
            raise ValueError('upper temperature must exceed base temperature')
    if type(profile['stages']) is not list or not 1 <= len(profile['stages']) <= 128:
        raise ValueError('one to 128 explicit development stages required')
    before, identities = F(0), set()
    for stage in profile['stages']:
        known = _stage(stage) and known
        if stage['stage_id'] in identities:
            raise ValueError('duplicate crop stage')
        identities.add(stage['stage_id'])
        if stage['end_thermal_time_cd'] is not None:
            end = q(stage['end_thermal_time_cd'], positive=True)
            if end <= before:
                raise ValueError('strictly increasing thermal-stage boundaries required')
            before = end
    known = _stage(profile['post_maturity'], terminal=True) and known
    if profile['post_maturity']['stage_id'] in identities:
        raise ValueError('post-maturity stage must have its own identity')
    return known


def initial_state(profile, *, elapsed_seconds, thermal_time_cd):
    validate_profile(profile)
    return {'schema': SCHEMA+'.state', 'profile_sha256': digest(profile),
            'elapsed_seconds': str(q(elapsed_seconds)), 'thermal_time_cd': str(q(thermal_time_cd))}


def root_support(layers, root_depth_m):
    """Geometric overlap only; inaccessible layers retain zero root weight.

    No rooting depth beyond the supplied column is silently truncated. Root
    weights describe a supplied uniform-density hypothesis, not living biomass.
    """
    if type(layers) is not list or not 1 <= len(layers) <= 128:
        raise ValueError('bounded current ordered root geometry required')
    depth, top, rows, identities = q(root_depth_m), F(), [], set()
    for layer in layers:
        exact(layer, {'layer_id', 'thickness_m', 'root_accessibility', 'evidence', 'source_status'}, 'current root geometry')
        if not _source(layer) or layer['root_accessibility'] == 'UNKNOWN':
            return {'status': 'UNKNOWN', 'weights': None, 'reason': 'root accessibility is UNKNOWN'}
        identity = ident(layer['layer_id'], 'root layer ID')
        if identity in identities or layer['root_accessibility'] not in ('ACCESSIBLE', 'INACCESSIBLE'):
            raise ValueError('unique layer and explicit accessibility required')
        identities.add(identity)
        width = q(layer['thickness_m'], positive=True)
        overlap = max(F(), min(depth, top+width)-top)
        rows.append({'layer_id': identity, 'rooted_thickness_m': overlap if layer['root_accessibility'] == 'ACCESSIBLE' else F()})
        top += width
    if depth > top:
        raise ValueError('crop root depth extends beyond supplied column')
    total = sum((row['rooted_thickness_m'] for row in rows), F())
    if depth and not total:
        return {'status': 'UNKNOWN', 'weights': None, 'reason': 'positive root depth has no accessible supplied soil'}
    return plain({'status': 'MODELLED', 'root_depth_m': depth,
        'accessible_rooted_thickness_m': total, 'layers': rows,
        'weights': [row['rooted_thickness_m']/total if total else F() for row in rows]})


def advance(profile, state, forcing, layers):
    """Split at exact thermal-stage crossings; produce constant native demands.

    No soil water is changed here. The consumer must execute each returned segment
    once on its common soil ledger. Inputs describe the planted crop, not sowing
    decisions. A harvested/mature crop's continued ET is explicitly supplied.
    """
    profile, state, forcing, layers = deepcopy((profile, state, forcing, layers))
    known = validate_profile(profile)
    exact(state, {'schema', 'profile_sha256', 'elapsed_seconds', 'thermal_time_cd'}, 'crop state')
    if state['schema'] != SCHEMA+'.state' or state['profile_sha256'] != digest(profile):
        raise ValueError('crop state profile binding differs')
    exact(forcing, {'event_id', 'start_seconds', 'end_seconds', 'minimum_temperature_c',
        'maximum_temperature_c', 'reference_et_m', 'evidence', 'source_status'}, 'crop forcing')
    known = _source(forcing) and known
    ident(forcing['event_id'], 'crop forcing event ID')
    start, end, thermal = q(forcing['start_seconds']), q(forcing['end_seconds']), q(state['thermal_time_cd'])
    if start != q(state['elapsed_seconds']) or end <= start:
        raise ValueError('contiguous positive crop-development clock required')
    result = {'schema': SCHEMA, 'status': 'UNKNOWN', 'source_status': 'UNKNOWN',
        'profile_sha256': digest(profile), 'forcing_sha256': digest(forcing),
        'initial_state': state, 'final_state': None, 'segments': [],
        'soil_water_consumed_here_m': '0', 'primary_sources': [THERMAL_SOURCE, ET_SOURCE]}
    if not known or any(forcing[key] is None for key in ('minimum_temperature_c', 'maximum_temperature_c', 'reference_et_m')):
        return {**result, 'reason': 'required crop parameters or forcing remain UNKNOWN'}
    tmin, tmax = (_signed(forcing[key], key) for key in ('minimum_temperature_c', 'maximum_temperature_c'))
    if tmax < tmin:
        raise ValueError('daily maximum is below daily minimum')
    base, upper = (_signed(profile[key], key) for key in ('base_temperature_c', 'upper_temperature_c'))
    rate = max(F(), min((tmin+tmax)/2, upper)-base)/q(profile['thermal_day_seconds'], positive=True)
    et_rate = q(forcing['reference_et_m'])/(end-start)
    clock, segments = start, []
    while clock < end:
        stage = next((row for row in profile['stages'] if thermal < q(row['end_thermal_time_cd'])), profile['post_maturity'])
        until = end if stage is profile['post_maturity'] or not rate else min(end, clock+(q(stage['end_thermal_time_cd'])-thermal)/rate)
        roots = root_support(layers, stage['root_depth_m'])
        if roots['status'] == 'UNKNOWN':
            return {**result, 'reason': roots['reason']}
        demand_t = et_rate*q(stage['transpiration_coefficient'])
        demand_e = et_rate*q(stage['potential_soil_evaporation_coefficient'])
        segments.append(plain({'segment_id': forcing['event_id']+':'+str(len(segments)),
            'stage_id': stage['stage_id'], 'start_seconds': clock, 'end_seconds': until,
            'thermal_time_start_cd': thermal, 'thermal_time_end_cd': thermal+rate*(until-clock),
            'potential_root_demand_m_s': demand_t, 'potential_soil_evaporation_m_s': demand_e,
            'potential_transpiration_m': demand_t*(until-clock),
            'potential_soil_evaporation_m': demand_e*(until-clock), 'root_support': roots}))
        thermal += rate*(until-clock)
        clock = until
    statuses = [profile['source_status'], forcing['source_status'], *(row['source_status'] for row in layers),
                *(row['source_status'] for row in profile['stages']), profile['post_maturity']['source_status']]
    return {**result, 'status': 'MODELLED', 'source_status': 'SYNTHETIC TEST' if 'SYNTHETIC TEST' in statuses else 'WORKING NON-CANON',
        'reason': None, 'segments': segments,
        'final_state': initial_state(profile, elapsed_seconds=end, thermal_time_cd=thermal),
        'maturity_reached': thermal >= q(profile['stages'][-1]['end_thermal_time_cd']),
        'potential_transpiration_m': str(sum((q(row['potential_transpiration_m']) for row in segments), F())),
        'potential_soil_evaporation_m': str(sum((q(row['potential_soil_evaporation_m']) for row in segments), F()))}


def bind_soil_event(segment, template, model, controls):
    """Bind a stage to the ONE native soil event without withdrawing any water.

    Template supplies rain, heat, bottom boundary, Feddes thresholds, evaporation
    response and their evidence. Stage clocks must be exactly representable;
    binary64 demand error is recorded and checked with existing water tolerance.
    """
    from . import evaporation
    exact(segment, {'segment_id', 'stage_id', 'start_seconds', 'end_seconds',
        'thermal_time_start_cd', 'thermal_time_end_cd', 'potential_root_demand_m_s',
        'potential_soil_evaporation_m_s', 'potential_transpiration_m',
        'potential_soil_evaporation_m', 'root_support'}, 'crop stage segment')
    roots = segment['root_support']
    if roots.get('status') != 'MODELLED' or len(roots.get('weights', [])) != len(model['layers']):
        raise ValueError('modelled current-layer root mapping required')
    if [row['layer_id'] for row in roots['layers']] != [row['layer_id'] for row in model['layers']]:
        raise ValueError('crop roots differ from current soil layer order')
    start, end = q(segment['start_seconds']), q(segment['end_seconds'])
    if end <= start:
        raise ValueError('positive crop segment duration required')
    duration = end-start
    for clock in (start, end, duration):
        if not math.isfinite(float(clock)) or F(float(clock)) != clock:
            raise ValueError('exact crop crossing is not representable on native soil clock; supplied timestep reconciliation required')
    def represented(value, label):
        value = q(value, label)
        converted = float(value)
        if not math.isfinite(converted) or value and not converted:
            raise ValueError('unrepresentable native crop '+label)
        return converted
    kt = q(segment['potential_root_demand_m_s'])
    ke = q(segment['potential_soil_evaporation_m_s'])
    if kt*duration != q(segment['potential_transpiration_m']) or ke*duration != q(segment['potential_soil_evaporation_m']):
        raise ValueError('crop rate/integral binding differs')
    weights = [q(value) for value in roots['weights']]
    if sum(weights, F()) not in (F(0), F(1)) or kt and not sum(weights, F()):
        raise ValueError('normalised accessible roots required for transpiration')
    top, depth, total = F(), q(roots['root_depth_m']), F()
    for layer, root in zip(model['layers'], roots['layers']):
        width, rooted = q(layer['thickness_m'], positive=True), q(root['rooted_thickness_m'])
        if rooted > max(F(), min(depth, top+width)-top):
            raise ValueError('crop root support exceeds current geometric layer overlap')
        total += rooted
        top += width
    if depth > top or total != q(roots['accessible_rooted_thickness_m']):
        raise ValueError('crop root support differs from current column geometry')
    expected_weights = [q(row['rooted_thickness_m'])/total if total else F() for row in roots['layers']]
    if weights != expected_weights:
        raise ValueError('crop root weights differ from declared uniform accessible support')
    event = deepcopy(template)
    event['duration_s'] = float(duration)
    if sum(weights, F()):
        if 'uptake' not in event:
            raise ValueError('supplied Feddes response required for crop transpiration')
        event.pop('root_withdrawal_m_s', None)
        event['uptake']['weights'] = [represented(value, 'root weight') for value in weights]
        event['potential_root_demand_m_s'] = represented(kt, 'transpiration rate')
    else:
        event.pop('uptake', None); event.pop('potential_root_demand_m_s', None)
        event['root_withdrawal_m_s'] = [0.]*len(weights)
    if 'surface_evaporation' in event:
        event['surface_evaporation']['potential_m_s'] = represented(ke, 'evaporation rate')
    elif ke:
        raise ValueError('nonzero crop soil evaporation needs supplied R22 surface boundary')
    error_t = (F(event.get('potential_root_demand_m_s', 0.))-kt)*duration
    error_e = (F(event.get('surface_evaporation', {}).get('potential_m_s', 0.))-ke)*duration
    # Sum absolute component errors: cancellation cannot hide lost demand.
    if abs(error_t)+abs(error_e) > F(controls['water_atol_m']):
        raise ValueError('native crop demand representation exceeds unchanged water tolerance')
    evaporation._event(event, len(weights))
    return {'event': event, 'mapping': {'schema': SCHEMA+'.soil-event-binding',
        'segment_sha256': digest(segment), 'model_sha256': evaporation.soil.model_digest(model),
        'start_seconds': str(start), 'end_seconds': str(end),
        'transpiration_representation_residual_m': str(error_t),
        'soil_evaporation_representation_residual_m': str(error_e),
        'soil_water_consumed_here_m': '0'}}


def run(profile, crop_state, forcing_windows, layers, model, soil_state, controls,
        *, cache=True, cache_root=None):
    """Carry a planted crop and ONE physical soil state through supplied windows.

    Each window contains exactly ``forcing`` (the development forcing) and
    ``soil_event`` (the constant hydrological/thermal template). Default caching
    captures actual code/runtime, profile, model, controls, current soil/crop
    state, forcing and stage mapping; only complete audited events are admitted.
    A failed event retains the last complete shared checkpoint and exposes its
    native accepted prefix separately. No partial solve becomes a complete crop
    window or an authenticated cached success. Yield/biomass are outside scope.
    """
    from . import evaporation
    from .cache import StageCache
    if type(cache) is not bool:
        raise ValueError('explicit Boolean crop cache switch required')
    if type(forcing_windows) is not list or not 1 <= len(forcing_windows) <= 366:
        raise ValueError('one to 366 supplied crop forcing windows required')
    profile, crop_state, forcing_windows, layers, model, soil_state, controls = deepcopy(
        (profile, crop_state, forcing_windows, layers, model, soil_state, controls))
    evaporation.soil._model(model)
    evaporation.soil._controls(controls, model)
    evaporation.soil._read_state(model, soil_state)
    if q(crop_state['elapsed_seconds']) != F(soil_state['elapsed_seconds']):
        raise ValueError('crop and soil checkpoints have different clocks')
    original_crop, original_soil = deepcopy(crop_state), deepcopy(soil_state)
    stages = StageCache('crop-soil-event', {'profile': profile, 'model': model,
        'controls': controls, 'root_geometry': layers}, cache_root) if cache else None
    events, execution, used, failure = [], [], set(), None

    class IncompleteEvent(Exception):
        def __init__(self, result):
            self.result = result

    for window in forcing_windows:
        exact(window, {'forcing', 'soil_event'}, 'crop/soil forcing window')
        forcing, template = window['forcing'], window['soil_event']
        identity = forcing['event_id']
        if identity in used:
            raise ValueError('reused crop forcing event identity')
        used.add(identity)
        duration = q(forcing['end_seconds'])-q(forcing['start_seconds'])
        if F(template['duration_s']) != duration:
            raise ValueError('native template duration differs from supplied crop forcing window')
        developed = advance(profile, crop_state, forcing, layers)
        if developed['status'] != 'MODELLED':
            failure = {'kind': 'CROP_DEVELOPMENT', 'result': developed}
            break
        for segment in developed['segments']:
            bound = bind_soil_event(segment, template, model, controls)
            event = bound['event']
            if F(soil_state['elapsed_seconds']) != q(segment['start_seconds']):
                raise ValueError('crop stage is not contiguous with the actual soil state')
            invocation = {'crop_state': crop_state, 'soil_state': soil_state,
                'forcing': forcing, 'stage': segment, 'mapping': bound['mapping'], 'event': event}
            invocation_sha = digest(invocation)
            def produce():
                value = evaporation.advance(model, soil_state, event, controls)
                if value['status'] != 'MODELLED':
                    raise IncompleteEvent(value)
                return {'invocation_sha256': invocation_sha, 'soil_result': value}
            def validate(value):
                exact(value, {'invocation_sha256', 'soil_result'}, 'cached crop soil result')
                result = value['soil_result']
                if value['invocation_sha256'] != invocation_sha or result['initial_state'] != soil_state:
                    raise ValueError('cached crop soil result differs from actual incoming state/invocation')
                evaporation.audit_event(model, event, result, controls)
            try:
                if stages is None:
                    wrapped, hit = produce(), False
                    validate(wrapped)
                else:
                    wrapped, hit = stages.reuse(invocation, produce, validate)
            except IncompleteEvent as error:
                failure = {'kind': 'SOIL_EVENT', 'segment': segment, 'event': event, 'result': error.result}
                break
            result = wrapped['soil_result']
            soil_state = deepcopy(result['final_state'])
            crop_state = initial_state(profile, elapsed_seconds=segment['end_seconds'],
                                       thermal_time_cd=segment['thermal_time_end_cd'])
            events.append({'window_id': identity, 'segment': segment, 'native_event': event,
                           'mapping': bound['mapping'], 'result': result})
            execution.append({'segment_id': segment['segment_id'], 'cache_hit': hit})
        if failure is not None:
            break
        if crop_state != developed['final_state']:
            raise ValueError('committed phenology differs from the completed forcing window')
    totals = {}
    for output_key, key in (('actual_transpiration_m', 'root_withdrawal_m'),
            ('actual_soil_evaporation_m', 'surface_evaporation_m'),
            ('surface_runoff_m', 'surface_runoff_m'),
            ('soil_evaporation_liquid_enthalpy_j_m2', 'surface_evaporation_enthalpy_j_m2'),
            ('soil_evaporation_latent_heat_j_m2', 'surface_evaporation_latent_heat_j_m2')):
        totals[output_key] = str(sum((F(row['result']['ledger'].get(key, 0.)) for row in events), F()))
    return {'schema': SCHEMA+'.soil-run', 'status': 'MODELLED' if failure is None else failure['result']['status'],
        'source_status': 'SYNTHETIC TEST' if any(row['result']['source_status'] == 'SYNTHETIC TEST' for row in events)
            else ('UNKNOWN' if failure is not None else 'WORKING NON-CANON'),
        'scope': 'SUPPLIED_PLANTED_CROP_THERMAL_STAGES_AND_ACTUAL_SINGLE_COLUMN_WATER_ENTHALPY; NO_YIELD_OR_WORLD_CALIBRATION',
        'initial_crop_state': original_crop, 'initial_soil_state': original_soil,
        'final_crop_state': crop_state if failure is None else None,
        'final_soil_state': soil_state if failure is None else None,
        'last_complete_checkpoint': {'crop_state': crop_state, 'soil_state': soil_state},
        'events': events, 'completed_event_totals': totals, 'incomplete_event': failure,
        'execution': {'cache_enabled': cache, 'events': execution,
            'stats': stages.stats if stages is not None else None,
            'warnings': stages.warnings if stages is not None else []}}
