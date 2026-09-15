"""Actual climate -> persistent snow -> demand -> sealed R3 physical coupling.

This is a bounded transect reference, not a solved global atmosphere or an A/G
production replacement. Three coequal snow members have independent feedback.
"""
from __future__ import annotations
from dataclasses import dataclass
from fractions import Fraction as F
import math

from . import climate, hydromet as hm, storage as st
from work.generator_upgrade_r3 import pipeline as r3

SCHEMA = 'diadem.climate-terrain-water-soil-recipe.r4'
STATUS = 'WORKING NON-CANON'


def fields(value, names):
    if type(value) is not dict or set(value) != set(names):
        raise ValueError('exact R4 fields required')


def number(v, *, positive=False, signed=False):
    if type(v) not in (int, float) or not math.isfinite(v) or (not signed and v < 0) or (positive and v <= 0):
        raise ValueError('explicit finite physical quantity required')
    return v


def evidence(v):
    if type(v) is not str or not v.strip() or len(v) > 4096:
        raise ValueError('bounded explicit evidence required')
    return v


def digest(v):
    return st.sha(st.encoded(r3.plain(v)))


@dataclass(frozen=True)
class Model:
    recipe: dict
    physical: object
    scenarios: tuple
    binding: str
    phase: object
    constants: object


def parse(recipe, source_sha256):
    st.encoded(recipe); st.digest(source_sha256)
    fields(recipe, ('schema', 'source_status', 'evidence', 'physical_recipe', 'transect',
                   'phase', 'phase_controls', 'demand_constants', 'initial_swe_m', 'day_seconds', 'model_day_seconds',
                   'calendar', 'coupling_controls', 'events'))
    if recipe['schema'] != SCHEMA or recipe['source_status'] not in (STATUS, 'SYNTHETIC TEST'):
        raise ValueError('reference recipe only; no canon/production authority')
    evidence(recipe['evidence']); number(recipe['day_seconds'], positive=True)
    if recipe['calendar'] != 'JAN_DEC_365_FEB28_REPORTING_NOT_EVENT_HISTORY':
        raise ValueError('explicit retained reporting calendar required')
    model = r3.parse(recipe['physical_recipe']); ids = set(model.profiles)
    number(recipe['model_day_seconds'], positive=True)
    if F(recipe['model_day_seconds'])*365 != F(recipe['physical_recipe']['seconds_per_year']):
        raise ValueError('365 model calendar days and physical year unit differ; DDF coefficient-day remains separate')
    # R3 parser's events are support-validation templates, never a second forcing.
    if len(recipe['physical_recipe']['events']) != 1:
        raise ValueError('one R3 support-validation template required')
    template = recipe['physical_recipe']['events'][0]
    if any(row['liquid_input_m_s'] != 0 or row['potential_et_m_s'] != 0 for row in template['cells'].values()):
        raise ValueError('R3 template cannot contain hidden duplicate climate forcing')
    if type(recipe['transect']) is not list or len(recipe['transect']) != len(ids):
        raise ValueError('one ordered atmospheric support per physical column required')
    seen = set()
    for row in recipe['transect']:
        fields(row, ('cell_id', 'length_m', 'width_m', 'evidence'))
        key = row['cell_id']
        if key not in ids or key in seen: raise ValueError('duplicate/unknown transect cell')
        seen.add(key); evidence(row['evidence'])
        number(row['length_m'], positive=True); number(row['width_m'], positive=True)
        if F(row['length_m']) * F(row['width_m']) != model.profiles[key].column.area_m2:
            raise ValueError('atmospheric footprint and actual hydraulic area differ')
    if type(recipe['initial_swe_m']) is not dict or set(recipe['initial_swe_m']) != ids:
        raise ValueError('explicit initial SWE for every physical column required')
    for v in recipe['initial_swe_m'].values(): number(v)
    phase = hm.PhaseLaw(**recipe['phase']); constants = hm.DemandConstants(**recipe['demand_constants'])
    pc = recipe['phase_controls']
    if phase.temperature_basis == 'AIR_TEMPERATURE':
        if pc is not None: raise ValueError('unused wet-bulb controls under air-temperature phase are ambiguous')
    else:
        fields(pc, ('lower_bound_c','temperature_atol_c','vapour_atol_pa','max_iterations','evidence'))
        number(pc['lower_bound_c'],signed=True); climate.saturation_liquid(pc['lower_bound_c'])
        number(pc['temperature_atol_c'],positive=True); number(pc['vapour_atol_pa'],positive=True); evidence(pc['evidence'])
        if type(pc['max_iterations']) is not int or not 1 <= pc['max_iterations'] <= 1000:
            raise ValueError('bounded wet-bulb iteration budget required')
    if constants.water_density_kg_m3 != recipe['physical_recipe']['water_density_kg_m3']:
        raise ValueError('atmospheric/surface water density must agree')
    controls = recipe['coupling_controls']
    fields(controls, ('snow_atol_m', 'precipitation_atol_m', 'potential_demand_atol_m',
                      'temperature_atol_c', 'humidity_atol_kg_kg', 'joint_budget_atol_m3'))
    for value in controls.values(): number(value, positive=True)
    events = recipe['events']
    if type(events) is not list or not 1 <= len(events) <= 366:
        raise ValueError('bounded explicit event schedule required; monthly totals alone are not events')
    interval_ids = set()
    for event in events:
        fields(event, ('interval_id', 'month', 'duration_seconds', 'atmosphere', 'climate_controls',
                       'surfaces', 'vegetation', 'boundaries', 'evidence', 'temperature_distribution_evidence'))
        ident = evidence(event['interval_id'])
        if ident in interval_ids: raise ValueError('duplicate forcing interval identity')
        interval_ids.add(ident)
        if type(event['month']) is not int or not 1 <= event['month'] <= 12: raise ValueError('Jan-Dec month required')
        number(event['duration_seconds'], positive=True)
        evidence(event['evidence']); evidence(event['temperature_distribution_evidence'])
        air = climate.AirMass(**event['atmosphere']); climate.Controls(**event['climate_controls'])
        if (air.water_density_kg_m3 != constants.water_density_kg_m3 or air.epsilon != constants.molecular_mass_ratio
                or air.gravity_m_s2 != recipe['physical_recipe']['gravity_m_s2']):
            raise ValueError('climate, demand and physical fluid constants differ')
        for name in ('surfaces', 'vegetation', 'boundaries'):
            if type(event[name]) is not dict or set(event[name]) != ids:
                raise ValueError('explicit per-cell surface/vegetation/boundary required')
        for key in ids:
            hm.DemandSurface(**event['surfaces'][key])
            veg = event['vegetation'][key]
            fields(veg, ('reference_demand_fraction', 'uptake', 'evidence'))
            fraction = number(veg['reference_demand_fraction']); evidence(veg['evidence'])
            if fraction > 1: raise ValueError('explicit 0..1 reference canopy demand allocation required')
            if fraction and recipe['physical_recipe']['cells'][key]['stability_roots']['mode'] == 'ABSENT':
                raise ValueError('positive transpiration allocation contradicts absent roots')
            column, _ = r3.water_column(model, key, model.profiles[key])
            r3.water_forcing(column, {'liquid_input_m_s': 0, 'potential_et_m_s': fraction * 1e-8,
                 'uptake': veg['uptake']}, event['duration_seconds'], event['evidence'])
            b = r3.sw.Boundary(**event['boundaries'][key])
            if b.source_status == 'UNKNOWN' or (b.kind == 'fixed_head' and b.head_m is None):
                raise ValueError('known lower boundary hypothesis required')
    return Model(recipe, model, hm.snow_scenarios(), digest({'recipe': recipe, 'source_sha256': source_sha256}), phase, constants)


def atmosphere(model, physical, event):
    cells = tuple(climate.Cell(**row, elevation_m=float(physical['profiles'][row['cell_id']].column.surface_m))
                  for row in model.recipe['transect'])
    return climate.generate(cells, climate.AirMass(**event['atmosphere']), climate.Controls(**event['climate_controls']))


def initial(model, scenario):
    return {'physical': r3.initial(model.physical), 'snow': {
        k: hm.initial_snow(k, scenario, v, binding_sha256=model.binding, elapsed_seconds=0, evidence=model.recipe['evidence'])
        for k, v in model.recipe['initial_swe_m'].items()}, 'joint_history': []}


def stock(state):
    return r3.stock(state['physical']) + sum((s.swe_m * state['physical']['profiles'][k].column.area_m2
                                            for k, s in state['snow'].items()), F())


class StepFailure(ValueError): pass


def trial(model, state, event, scenario, dt, _splits=0):
    """Antecedent-terrain atmosphere, phase/SWE, morphology then water; isolated.

    Snow depletion is an internal event boundary, so a short melt pulse is never
    silently smeared over the entire surface-water solve.
    """
    if _splits > 16: raise StepFailure('snow/terrain event split budget exhausted')
    dt = F(dt); start = state['physical']['elapsed']
    generated = atmosphere(model, state['physical'], event)
    input_sha = digest({'climate': generated, 'event': event, 'start': str(start), 'duration': str(dt)})
    forcing = {}; snow = {}; products = {}; depletion = []
    for key, profile in state['physical']['profiles'].items():
        air = generated['cells'][key]
        demand = hm.penman_monteith(air, hm.DemandSurface(**event['surfaces'][key]), model.constants,
                                    evidence=event['evidence'], source_status=STATUS)
        bulb = None
        if model.phase.temperature_basis == 'SUPPLIED_WET_BULB':
            solved = hm.psychrometric_wet_bulb(air['temperature_c'],air['vapour_pressure_pa'],demand['psychrometric_constant_pa_k'],
                saturation_liquid=climate.saturation_liquid,**model.recipe['phase_controls'])
            if solved['status'] != 'MODELLED': raise ValueError('wet-bulb phase unavailable: '+solved['reason'])
            bulb = solved['wet_bulb_c']
        phase = hm.partition_precipitation(air['precipitation_m_s'], air['temperature_c'], model.phase,
                                          wet_bulb_c=bulb,evidence=event['evidence'], source_status=STATUS)
        step = hm.snow_step(state['snow'][key], scenario, temperature_c=air['temperature_c'],
            precipitation_m_s=phase['precipitation_m_s'], snowfall_m_s=phase['snowfall_m_s'],
            start_seconds=start, duration_seconds=dt, day_seconds=model.recipe['day_seconds'],
            interval_id=event['interval_id'], input_sha256=input_sha, binding_sha256=model.binding,
            evidence=event['evidence'], source_status=STATUS,
            temperature_distribution_evidence=event['temperature_distribution_evidence'])
        if step['depletion_after_seconds'] is not None: depletion.append(step['depletion_after_seconds'])
        veg = event['vegetation'][key]
        rate = demand['potential_evaporation_m_s'] * veg['reference_demand_fraction']
        forcing[key] = {'liquid_input_m_s': float(step['liquid_input_m_s']), 'potential_et_m_s': rate,
                        'uptake': veg['uptake'], 'boundary': event['boundaries'][key]}
        snow[key] = step['state']
        products[key] = {'snow_ledger': step['ledger'], 'potential_reference_evaporation_m': F(demand['potential_evaporation_m_s']) * dt,
            'potential_root_demand_m': F(rate) * dt, 'potential_condensation_m': F(demand['potential_condensation_m_s']) * dt,
            'temperature_c': air['temperature_c'], 'specific_humidity_kg_kg': air['specific_humidity_kg_kg'],
            'phase_temperature_c':phase['phase_temperature_c'],'phase_temperature_basis':model.phase.temperature_basis,
            'liquid_transfer_roundoff_m': (F(forcing[key]['liquid_input_m_s']) - step['liquid_input_m_s']) * dt}
    if depletion:
        cut = min(depletion)
        if not 0 < cut < dt: raise StepFailure('invalid snow event boundary')
        first = trial(model, state, event, scenario, cut, _splits+1)
        return trial(model, first, event, scenario, dt-cut, _splits+1)
    physical = r3.trial(model.physical, state['physical'],
                        {'duration_seconds': float(dt), 'cells': forcing, 'evidence': event['evidence']}, dt)
    out = {'physical': physical, 'snow': snow, 'joint_history': list(state['joint_history'])}
    p = sum((v['snow_ledger']['precipitation_m'] * physical['profiles'][k].column.area_m2 for k, v in products.items()), F())
    atmospheric_p = F(generated['receipt']['precipitation_kg_s'])*dt/F(model.constants.water_density_kg_m3)
    transfer_roundoff = p-atmospheric_p
    row = physical['history'][-1]
    residual = stock(state) + p + F(row['bottom_in_m3']) - F(row['actual_et_m3']) - F(row['bottom_out_m3']) \
               - F(row['runoff_export_m3']) - F(row['sediment_porewater_export_m3']) - stock(out)
    residual -= transfer_roundoff
    if abs(float(residual)) > model.recipe['coupling_controls']['joint_budget_atol_m3']:
        raise StepFailure('joint snow/surface/soil budget failed')
    out['joint_history'].append(r3.plain({'interval_id': event['interval_id'], 'month': event['month'],
        'start_seconds': start, 'duration_seconds': dt, 'antecedent_terrain_sha256': digest({k:p.as_dict() for k,p in state['physical']['profiles'].items()}),
        'generated_forcing_sha256': input_sha, 'atmospheric_moisture_ledger': generated['receipt'],
        'initial_total_water_m3': stock(state), 'precipitation_m3': p, 'atmospheric_precipitation_m3':atmospheric_p,
        'atmosphere_surface_transfer_roundoff_m3':transfer_roundoff,'final_total_water_m3': stock(out),
        'joint_residual_m3': residual, 'cells': products}))
    return out


def compare(model, full, fine, baseline):
    error, parts = r3.compare(model.physical, full['physical'], fine['physical'], baseline['physical'])
    ctl = model.recipe['coupling_controls']; rel = model.recipe['physical_recipe']['coupling_controls']['relative_tolerance']
    def add(name, a, b, atol):
        a,b = float(a),float(b)
        parts[name] = abs(a-b)/(atol+rel*max(abs(a),abs(b)))
    first = len(baseline['joint_history'])
    for key in full['snow']:
        add(key+'/snow_change', full['snow'][key].swe_m-baseline['snow'][key].swe_m,
            fine['snow'][key].swe_m-baseline['snow'][key].swe_m, ctl['snow_atol_m'])
        for name, atol in (('precipitation_m',ctl['precipitation_atol_m']), ('melt_m',ctl['snow_atol_m'])):
            values = [sum((F(r['cells'][key]['snow_ledger'][name]) for r in s['joint_history'][first:]),F()) for s in (full,fine)]
            add(key+'/'+name,*values,atol)
        for name in ('potential_reference_evaporation_m','potential_root_demand_m','potential_condensation_m'):
            values = [sum((F(r['cells'][key][name]) for r in s['joint_history'][first:]),F()) for s in (full,fine)]
            add(key+'/'+name,*values,ctl['potential_demand_atol_m'])
        # Celsius has an arbitrary zero: a relative tolerance on its absolute
        # value would accept different errors after an additive unit offset.
        parts[key+'/temperature_c']=abs(full['joint_history'][-1]['cells'][key]['temperature_c']-
            fine['joint_history'][-1]['cells'][key]['temperature_c'])/ctl['temperature_atol_c']
        for name, atol in (('specific_humidity_kg_kg',ctl['humidity_atol_kg_kg']),):
            add(key+'/'+name, full['joint_history'][-1]['cells'][key][name], fine['joint_history'][-1]['cells'][key][name],atol)
    return max(parts.values(),default=error),parts


def advance_event(model, state, event, scenario):
    ctl = model.recipe['physical_recipe']['coupling_controls']
    left = F(event['duration_seconds']); dt = F(ctl['initial_dt_seconds']); checks=[]; attempts=0
    while left:
        attempts += 1
        if attempts > ctl['max_attempts']: raise StepFailure('coupled climate work budget exhausted')
        dt = min(dt,left)
        try:
            full = trial(model,state,event,scenario,dt)
            half = trial(model,state,event,scenario,dt/2)
            fine = trial(model,half,event,scenario,dt/2)
            err, parts = compare(model,full,fine,state)
        except (r3.tt.TerrainStepTooLarge, r3.CoupledStepFailure, StepFailure):
            err = math.inf
        if err > 1:
            if dt/2 < F(ctl['min_dt_seconds']): raise StepFailure('whole-chain error gate failed at minimum timestep')
            dt /= 2
            continue
        state = fine; left -= dt
        checks.append({'duration_seconds':str(dt),'error_ratio':err,'components':parts})
        if err < .125: dt=min(2*dt,F(ctl['max_dt_seconds']))
    state['physical']['completed_events'] += 1
    state['joint_history'][-1]['coupled_acceptance'] = {'attempts':attempts,'accepted_intervals':checks}
    return state


def serialise(members, completed):
    return {'completed_events':completed,'members':{name:{'physical':r3.serialise(s['physical']),
        'snow':{k:hm.state_json(v) for k,v in s['snow'].items()},'joint_history':s['joint_history']} for name,s in members.items()}}


def run(recipe, *, stop_after=None, resume=None, source_sha256=None):
    if source_sha256 is None:
        from .provenance import source_identity
        _, source_sha256 = source_identity()
    model = parse(recipe,source_sha256); rh=digest(recipe)
    if stop_after is None: stop_after=len(recipe['events'])
    if type(stop_after) is not int or not 0 <= stop_after <= len(recipe['events']): raise ValueError('valid event-boundary stop required')
    members={s.scenario_id:initial(model,s) for s in model.scenarios}; completed=0
    def advance(index):
        for scenario in model.scenarios:
            name=scenario.scenario_id
            members[name]=advance_event(model,members[name],recipe['events'][index],scenario)
    if resume is not None:
        raw=st.restore(resume,recipe_sha256=rh,source_sha256=source_sha256)
        fields(raw,('completed_events','members')); completed=raw['completed_events']
        if type(completed) is not int or not 0 <= completed <= stop_after: raise ValueError('joint checkpoint cursor invalid')
        for index in range(completed): advance(index)
        if serialise(members,completed)!=raw: raise ValueError('joint checkpoint is not the deterministic physical/snow/forcing state')
    for index in range(completed,stop_after): advance(index)
    final_event=recipe['events'][max(0,stop_after-1)]
    results={name:{'initial_total_water_m3':str(stock(initial(model,s))), 'final_total_water_m3':str(stock(members[name])),
        'joint_residual_m3':str(sum((F(r['joint_residual_m3']) for r in members[name]['joint_history']),F())),
        'final_terrain_climate_diagnostic':r3.plain(atmosphere(model,members[name]['physical'],final_event)),
        'final_terrain_sha256':digest({k:p.as_dict() for k,p in members[name]['physical']['profiles'].items()}),
        'soil_products':r3.soil_products(model.physical,members[name]['physical']) if stop_after else {}}
        for s in model.scenarios for name in (s.scenario_id,)}
    return {'schema':'diadem.connected-climate-terrain-water-soil.r4','status':'BOUNDED_CONNECTED_REFERENCE',
        'source_status':STATUS,'source_sha256':source_sha256,'production_installed':False,'canon_changed':False,
        'state':serialise(members,stop_after),'members':results,'snow_family':'THREE_COEQUAL_SENSITIVITIES_NO_PREFERRED_MEMBER',
        'snow_scenarios':r3.plain(model.scenarios),'degree_day_coefficient_day_seconds':recipe['day_seconds'],
        'model_calendar_day_seconds':recipe['model_day_seconds'],
        'degree_day_units_status':'RETAINED_86400_SECOND_COEFFICIENT_DAY' if recipe['day_seconds']==86400 else 'EXPLICIT_COEFFICIENT_UNIT_SENSITIVITY_NOT_RETAINED_REPLAY',
        'coupling':'antecedent-terrain prescribed-circulation moist-air transect -> phase/persistent SWE/depletion events -> potential canopy demand -> R3 morphology/wet remap/Richards; whole-chain full/two-half gate',
        'limits':['not a global circulation model or calibrated A/G successor','supplied radiation/circulation/vegetation and representative event thermal hypotheses',
                  'potential condensation not added as realised dew; no snow energy balance/refreezing/sublimation',
                  'no automatic soil formation/fertility/ecological model; no production installation']}
