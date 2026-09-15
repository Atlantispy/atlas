"""One source-bound seasonal state graph; independent hypotheses are not additive."""
from copy import deepcopy
from fractions import Fraction as F
import math
from . import binding, climate, hydraulics, plants, owner_inputs, payloads, richards_numerics

FIELDS=('schema','source_sha256','source_status','evidence','parent_recipe','hydraulic_hypotheses',
    'hydraulic_controls','water_density_kg_m3','gravity_m_s2','duration_atol_s','budget_atol_m','carbon','limits')


def fields(value,names,what):
    if type(value) is not dict or set(value)!=set(names): raise ValueError('exact '+what+' fields required')
    return value


def text(value):
    if type(value) is not str or not value.strip() or len(value)>4096: raise ValueError('explicit bounded evidence/identity required')


def parse(bundle,recipe):
    fields(recipe,FIELDS,'seasonal recipe')
    if recipe['schema']!=binding.RECIPE_SCHEMA or recipe['source_sha256']!=bundle.source_sha256 or recipe['source_status']!='WORKING NON-CANON': raise ValueError('exact bound R10 recipe required')
    text(recipe['evidence']); text(recipe['limits'])
    physical=recipe['parent_recipe']['parent_recipe']; hypotheses=recipe['hydraulic_hypotheses']
    if type(hypotheses) is not dict or not 1<=len(hypotheses)<=12: raise ValueError('bounded explicit hydraulic hypotheses required')
    for ident,h in hypotheses.items():
        text(ident)
        if '/' in ident: raise ValueError('hypothesis identity cannot alias a unit path')
        fields(h,('pft_id','family_id','columns','evidence','source_status'),'hydraulic hypothesis'); text(h['evidence'])
        if h['source_status'] not in ('SYNTHETIC TEST','WORKING NON-CANON'): raise ValueError('new hydraulic hypotheses are not canon')
        if h['pft_id'] not in physical['pfts'] or h['family_id'] not in physical['family_demand_multipliers']: raise ValueError('actual PFT/family join required')
        if type(h['columns']) is not dict or set(h['columns'])!=set(physical['cell_context']): raise ValueError('every actual cell needs a column hypothesis')
        for cell,s in h['columns'].items():
            if '/' in cell: raise ValueError('cell identity cannot alias a unit path')
            fields(s,('root_boundary_above_layer_id','root_weights_by_layer','uptake','boundary','initial_condition','initial_condition_evidence','soil_thermal_regime','thermal_evidence','evidence'),'column hypothesis')
            for k in ('root_boundary_above_layer_id','initial_condition_evidence','thermal_evidence','evidence'): text(s[k])
            if s['initial_condition']!='RETAINED_FORMED_PROBE_FINAL_HEADS_ALIGNED_TO_YEAR_START': raise ValueError('explicit supported initial alignment required')
            if s['soil_thermal_regime'] not in ('UNFROZEN_CONDITIONAL','UNKNOWN'): raise ValueError('no implicit soil-temperature/freeze model')
            if type(s['root_weights_by_layer']) is not dict or not s['root_weights_by_layer']: raise ValueError('explicit uptake weights required')
            for k,v in s['root_weights_by_layer'].items(): text(k); climate.rational(v)
    c=fields(recipe['carbon'],('selected_layer_suffixes','soil_temperature_k_by_month','fast_litter_carbon_kg_m2_s_by_month','slow_litter_carbon_kg_m2_s_by_month','redox','regime_by_suffix','evidence','source_status'),'diagnostic carbon scenario')
    text(c['evidence'])
    if c['source_status'] not in ('SYNTHETIC TEST','WORKING NON-CANON','UNKNOWN'): raise ValueError('new carbon scenario status required')
    if type(c['selected_layer_suffixes']) is not list or not 1<=len(c['selected_layer_suffixes'])<=8 or len(set(c['selected_layer_suffixes']))!=len(c['selected_layer_suffixes']): raise ValueError('bounded unique carbon layer selection required')
    for suffix in c['selected_layer_suffixes']: text(suffix)
    if set(c['regime_by_suffix'])!=set(c['selected_layer_suffixes']): raise ValueError('explicit per-layer carbon regime required')
    for k in ('soil_temperature_k_by_month','fast_litter_carbon_kg_m2_s_by_month','slow_litter_carbon_kg_m2_s_by_month'):
        if type(c[k]) is not list or len(c[k])!=12: raise ValueError('complete twelve-month carbon driver or explicit null required')
        for v in c[k]:
            if v is not None: climate.rational(v)
    return recipe


def actual_parents(bundle,recipe):
    parent=bundle.parent.run(recipe['parent_recipe'])
    physical=bundle.parent.parent.run(recipe['parent_recipe']['parent_recipe'])
    if parent['parent_result_sha256']!=climate.digest(physical): raise ValueError('R9/R8 separately executed physical parents differ')
    return parent,physical


def plant_projection(physical):
    calendar=physical['seasonal']['calendar']; durations=[F(v)*F(calendar['day_seconds']) for v in calendar['month_days']]
    result={}
    for snow,member in physical['state']['members'].items():
        result[snow]={}
        for cell,row in member.items():
            result[snow][cell]={}
            for family,pfts in row['pft_results'].items():
                result[snow][cell][family]={pft:plants.seasonal_activity(value,durations,source_id=snow+'/'+family+'/'+cell+'/'+pft,source_sha256=plants.digest(value)) for pft,value in pfts.items()}
    return result


def hydraulic_inputs(bundle,recipe,physical,snow,hypothesis_id,cell):
    solver=bundle.parent.parent.parent.parent.solver
    h=recipe['hydraulic_hypotheses'][hypothesis_id]; s=h['columns'][cell]
    soil=physical['soil_result']['state']['members'][snow][cell]; water=soil['formed_soil_water']
    if water['status']!='MODELLED_NEW_GEOMETRY_WATER_PROBE': raise ValueError('retained formed physical water state required')
    cs=dict(water['column']); cs['layers']=tuple(solver.HydraulicLayer(**l) for l in cs['layers'])
    column=solver.Column(**cs); state=solver.state_from_json(bundle.storage.encoded({'schema':'diadem.richards-state.r6',**water['result']['state']}),column)
    layer_ids=[l.layer_id for l in column.layers]
    if s['root_boundary_above_layer_id'] not in layer_ids: raise ValueError('explicit rooted face must match actual formed layer')
    face=layer_ids.index(s['root_boundary_above_layer_id'])
    if face<1: raise ValueError('root face needs positive rooted column depth')
    pft=recipe['parent_recipe']['parent_recipe']['pfts'][h['pft_id']]
    if math.fsum(l.thickness_m for l in column.layers[:face])>pft['rooting']['maximum_root_depth_m']+1e-12: raise ValueError('root face exceeds declared PFT root maximum')
    if not set(s['root_weights_by_layer'])<=set(layer_ids): raise ValueError('root weights name an absent formed layer')
    geometry={g['layer_id']:g for g in soil['geometry']}
    weights=tuple(s['root_weights_by_layer'].get(k,0.) for k in layer_ids)
    if any(w and (i>=face or geometry[k]['phase'] not in pft['rooting']['allowed_phases']) for i,(k,w) in enumerate(zip(layer_ids,weights))): raise ValueError('root uptake crosses the declared root face or biological allowed phase')
    uptake=solver.Uptake(weights=weights,**s['uptake']); boundary=solver.Boundary(**s['boundary'])
    cal=physical['seasonal']['calendar']
    calendar=hydraulics.Calendar(cal['calendar_id'],tuple(F(d)*F(cal['day_seconds']) for d in cal['month_days']),F(cal['day_seconds']),cal['evidence'])
    source=physical['seasonal']['members'][snow]['cells'][cell]
    if source['status']!='MODELLED_PERIODIC_SNOW': return solver,column,state,calendar,None,face
    multiplier=recipe['parent_recipe']['parent_recipe']['family_demand_multipliers'][h['family_id']]
    events=[]
    for e in source['events']:
        active=e['temperature_c']>pft['active_above_temperature_c']
        # Preserve the actual R8 event demand arithmetic exactly. No second PFT bucket sink.
        demand=e['potential_evaporation_m_s']*pft['reference_transpiration_fraction']*multiplier if active else 0.
        events.append(hydraulics.Event(e['event_id'],e['month_id'],F(e['duration_seconds']),e['liquid_input_m_s'],demand,
            uptake,boundary,hypothesis_id,s['soil_thermal_regime'],s['thermal_evidence'],e['temperature_c'],
            h['evidence']+'; exact R8 liquid-event '+climate.digest(e),h['source_status']))
    return solver,column,state,calendar,tuple(events),face


def hydraulic_product(bundle,recipe,physical,snow,hypothesis_id,cell,*,stop_after=None,resume=None):
    solver,column,state,calendar,events,face=hydraulic_inputs(bundle,recipe,physical,snow,hypothesis_id,cell)
    if events is None: return {'status':'UNKNOWN','reason':'actual representative snow-liquid chronology unresolved','annual':None,'months':None}
    solver=richards_numerics.Adapter(solver)
    return hydraulics.run_year(solver,column,state,calendar,events,solver.Controls(**recipe['hydraulic_controls']),
        root_boundary_index=face,water_density_kg_m3=recipe['water_density_kg_m3'],gravity_m_s2=recipe['gravity_m_s2'],
        duration_atol_s=recipe['duration_atol_s'],budget_atol_m=recipe['budget_atol_m'],evidence=recipe['hydraulic_hypotheses'][hypothesis_id]['evidence'],
        source_status=recipe['hydraulic_hypotheses'][hypothesis_id]['source_status'],source_binding_sha256=bundle.source_sha256,
        scenario_id=snow+'/'+hypothesis_id+'/'+cell,stop_after=stop_after,resume=resume)


def carbon_product(bundle,recipe,physical,water,snow,hypothesis_id,cell):
    # Every missing driver is carried as null, never zero.
    from . import carbon_bridge
    return carbon_bridge.project(bundle,recipe,physical,water,snow,hypothesis_id,cell)


def downstream(water,area):
    rows={}
    for month,row in (water.get('months') or {}).items():
        if row.get('status')!='MODELLED': continue
        # Only integrated local export can enter a future router; this is not channel discharge.
        ledger=row['ledger_m']; dt=F(row['duration_seconds'])
        rows[month]={'local_surface_export_m3':climate.quantity(F(ledger['surface_runoff_m'])*area),
            'local_mean_export_supply_m3_s':climate.quantity(F(ledger['surface_runoff_m'])*area/dt),
            'meaning':'unrouted cell export and its interval-mean supply; not river flow, flood depth or waterbody inflow'}
    return {'represented_area_m2':str(area),'local_water_supply':rows,
        'river_flow_m3_s':None,'lake_level_m':None,'wetland_hydroperiod_seconds':None,'soil_ice_fraction':None,
        'crop_yield_kg':None,'food_supply_kg':None,'route_passability':None,'settlement_water_security':None,
        'slope_failure_probability':None,'seasonal_population_growth':None,'political_boundary_change':None,
        'requirements':{'river_lake_wetland':'routing, finite channel/waterbody and groundwater storage, geometry and travel time',
            'soil_freezing':'soil heat/ice and hydraulic phase-change model; air frost or SWE is insufficient',
            'agriculture_food':'crop calendar, species growth/yield law, soils/nutrients, harvest/storage and daily forcing interpretation',
            'transport_settlements':'actual road/channel/flood/ice exposure and passability, demand and finite supply/storage laws',
            'hazards':'failure-plane geometry/material strength and pore pressure at the same support; no probability from an endpoint',
            'population_politics':'separate demographic/governance process, not automatic annual temperature response'},
        'states_are_not_extra_water_or_food_sources':True}


def evaluate_unit(bundle,recipe,physical,snow,hypothesis_id,cell):
    water=hydraulic_product(bundle,recipe,physical,snow,hypothesis_id,cell)
    soil=physical['soil_result']['state']['members'][snow][cell]
    area=F(physical['state']['members'][snow][cell]['area_m2'])
    return {'snow_id':snow,'hydraulic_hypothesis_id':hypothesis_id,'cell_id':cell,
        'physical_cell_sha256':climate.digest(physical['state']['members'][snow][cell]),
        'formed_soil_sha256':climate.digest(soil),'initial_water_source_sha256':climate.digest(soil['formed_soil_water']),
        'initial_condition':deepcopy(recipe['hydraulic_hypotheses'][hypothesis_id]['columns'][cell]),
        'hydrology':water,'carbon':carbon_product(bundle,recipe,physical,water,snow,hypothesis_id,cell),
        'downstream':downstream(water,area)}


def run(bundle,recipe,*,stop_after=None,resume=None):
    recipe=parse(bundle,recipe); parent,physical=actual_parents(bundle,recipe)
    parent_sha=climate.digest(parent); physical_sha=climate.digest(physical); recipe_sha=climate.digest(recipe)
    ordered=sorted((snow,h,cell) for snow,member in physical['state']['members'].items() for h in recipe['hydraulic_hypotheses'] for cell in member)
    until=len(ordered) if stop_after is None else stop_after
    if type(until) is not int or not 0<=until<=len(ordered): raise ValueError('bounded complete seasonal unit cursor required')
    def simulate(count):
        return {'completed_units':count,'parent_result_sha256':parent_sha,'physical_parent_result_sha256':physical_sha,
            'results':{'/'.join(key):payloads.pack(evaluate_unit(bundle,recipe,physical,*key)) for key in ordered[:count]}}
    if resume is not None:
        fields(resume,('schema','recipe_sha256','source_sha256','state_sha256','state'),'R10 checkpoint')
        saved=fields(resume['state'],('completed_units','parent_result_sha256','physical_parent_result_sha256','results'),'saved seasonal state')
        if resume['schema']!=binding.CHECKPOINT_SCHEMA or resume['recipe_sha256']!=recipe_sha or resume['source_sha256']!=bundle.source_sha256 or resume['state_sha256']!=climate.digest(saved): raise ValueError('seasonal checkpoint binding differs')
        cursor=saved['completed_units']
        if type(cursor) is not int or not 0<=cursor<=until or saved!=simulate(cursor): raise ValueError('seasonal checkpoint differs from actual source-bound replay')
    state=simulate(until)
    return {'schema':binding.RESULT_SCHEMA,'source_status':'WORKING NON-CANON','source_sha256':bundle.source_sha256,
        'recipe_sha256':recipe_sha,'parent_result_sha256':parent_sha,'physical_parent_result_sha256':physical_sha,
        'state':state,'status':'COMPLETE_BOUNDED_SEASONAL_EXECUTION' if until==len(ordered) else 'STOPPED_AT_UNIT_BOUNDARY',
        'climate':climate.project(physical,bundle.parent.parent.source_sha256),'plant_activity':payloads.pack(plant_projection(physical)),
        'species_phenology':plants.species_phenology(parent['biological_owner_contracts']),
        'owner_sources':owner_inputs.source_bindings(),'hypotheses_are_coequal_not_additive':True,
        'physical_soil_water_is_not_pft_bucket_water':True,'soil_is_not_periodic_or_spun_up':True,
        'r9_species_result_retained_separately':True,'production_installed':False,'canon_changed':False,'optimisation_performed':False,
        'unit_storage':'individually bounded lossless canonical scientific records; decode through payloads.unpack; no omitted scientific fields or relaxed8MiB guard',
        'limits':recipe['limits']}
