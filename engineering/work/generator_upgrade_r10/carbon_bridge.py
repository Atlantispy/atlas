"""Actual retained R7 pools and R10 water samples, with explicit diagnostic drivers."""
from fractions import Fraction as F
from . import climate, seasonal_carbon


def inputs(bundle,recipe,physical,water,snow,hypothesis_id,cell,layer_id):
    soil=physical['soil_result']['state']['members'][snow][cell]
    organic=bundle.parent.parent.parent.graph.load('work.generator_upgrade_r7.organic')
    solver=bundle.parent.parent.parent.parent.solver
    source=soil['surface_organic'] if soil['surface_organic']['layer_id']==layer_id else soil['organic_by_layer'].get(layer_id)
    if source is None or source['status']!='MODELLED': raise ValueError('actual retained formed-layer carbon pools required')
    retained=dict(source['state'])
    for key in ('fast_carbon_kg_m2','slow_carbon_kg_m2','elapsed_seconds'): retained[key]=F(retained[key])
    initial=organic.OrganicState(**retained)
    if (initial.layer_id,initial.support_id)!=(layer_id,cell) or (source['layer_id'],source['support_id'])!=(layer_id,cell): raise ValueError('retained carbon pool layer/support differs from requested physical layer')
    law_spec=dict(source['law'])
    for key in ('fast_to_slow_fraction','carbon_fraction_dry_matter'):
        if law_spec[key] is not None: law_spec[key]=F(law_spec[key])
    for key in ('moisture_curve','redox_factors'): law_spec[key]=tuple(tuple(v) for v in law_spec[key])
    law_spec['regimes']=tuple(law_spec['regimes']); law=organic.OrganicLaw(**law_spec)
    numerics=organic.Numerics(**source['numerics'])
    cal=physical['seasonal']['calendar']; c=recipe['carbon']
    calendar=seasonal_carbon.Calendar(cal['calendar_id'],tuple(F(d)*F(cal['day_seconds']) for d in cal['month_days']),F(cal['day_seconds']),cal['evidence'])
    suffix=next((s for s in c['selected_layer_suffixes'] if cell+s==layer_id),None)
    if suffix is None: raise ValueError('explicit selected carbon layer required')
    hydraulic_column=soil['formed_soil_water']['column']; layer_ids=[l['layer_id'] for l in hydraulic_column['layers']]
    if layer_id not in layer_ids: raise ValueError('carbon/water layer identity differs')
    index=layer_ids.index(layer_id); layer=solver.HydraulicLayer(**hydraulic_column['layers'][index])
    source_events=physical['seasonal']['members'][snow]['cells'][cell].get('events')
    if source_events is None: raise ValueError('complete source seasonal chronology required')
    if (water.get('schema')!='diadem.seasonal-layered-water.r10' or water.get('source_binding_sha256')!=bundle.source_sha256
            or water.get('scenario_id')!=snow+'/'+hypothesis_id+'/'+cell): raise ValueError('carbon requires this exact source-bound water scenario')
    active=dict(water['column']);active['layers']=tuple(solver.HydraulicLayer(**l) for l in active['layers']);column=solver.Column(**active)
    original=dict(hydraulic_column);original['layers']=tuple(solver.HydraulicLayer(**l) for l in original['layers']);original=solver.Column(**original)
    if (water['column']['layers']!=hydraulic_column['layers'] or water['column_sha256']!=solver.column_digest(column)
            or water['original_column_sha256']!=solver.column_digest(original)): raise ValueError('carbon water column differs from actual fixed formed hydraulic geometry')
    if climate.digest(water['inputs'])!=water['inputs_sha256']: raise ValueError('water input identity differs')
    raw_events=water.get('events',[])
    if [e['event_id'] for e in raw_events]!=[e['event_id'] for e in source_events]: raise ValueError('water event chronology/identity differs or contains duplicates')
    water_events={r['event_id']:r for r in raw_events}
    starting=water.get('initial_state'); cursor=F(); events=[]
    def valid_state(state):
        return solver.state_from_json(bundle.storage.encoded({'schema':'diadem.richards-state.r6',**state}),column)
    if starting is not None:
        valid_state(starting)
        retained_water=soil['formed_soil_water']['result']['state']
        if (starting['head_m'],starting['elapsed_seconds'])!=(retained_water['head_m'],retained_water['elapsed_seconds']): raise ValueError('water initial heads/age are not the retained profile condition')
    for e in source_events:
        row=water_events.get(e['event_id']); mid=e['month_id']-1; dt=F(e['duration_seconds'])
        resolved=starting is not None and row is not None and row.get('status')=='MODELLED'
        if row['month_id']!=e['month_id']: raise ValueError('water/carbon month identity differs')
        if resolved:
            if F(row['duration_seconds'])!=dt or F(row['start_seconds_in_year'])!=cursor: raise ValueError('water/carbon event time support differs')
            following=valid_state(row['solver_result']['state'])
            if abs(F(following.elapsed_seconds)-F(starting['elapsed_seconds'])-dt)>F(recipe['duration_atol_s']): raise ValueError('water state does not continue through the source interval')
        wfps=None if not resolved else solver.hydraulic_properties(layer,starting['head_m'][index])[0]/layer.theta_s
        sample=cursor if resolved else None
        forcing=organic.OrganicForcing(dt,
            None if c['fast_litter_carbon_kg_m2_s_by_month'][mid] is None else F(c['fast_litter_carbon_kg_m2_s_by_month'][mid]),
            None if c['slow_litter_carbon_kg_m2_s_by_month'][mid] is None else F(c['slow_litter_carbon_kg_m2_s_by_month'][mid]),
            c['soil_temperature_k_by_month'][mid],wfps,c['redox'],c['regime_by_suffix'][suffix],
            'declared-soil-temperature/'+climate.digest(c),'actual-water-start/'+climate.digest(starting),
            c['evidence'],c['evidence'],c['evidence'],c['source_status'])
        events.append(seasonal_carbon.Event(e['event_id'],e['month_id'],initial.layer_id,initial.support_id,forcing,
            'EVENT_START_SAMPLE_HELD' if resolved else 'UNKNOWN',sample,c['evidence']))
        starting=row['solver_result']['state'] if resolved else None; cursor+=dt
    return organic,initial,law,calendar,tuple(events),numerics,source


def layer_product(bundle,recipe,physical,water,snow,hypothesis_id,cell,layer_id,*,stop_after=None,resume=None):
    organic,initial,law,calendar,events,numerics,source=inputs(bundle,recipe,physical,water,snow,hypothesis_id,cell,layer_id)
    c=recipe['carbon']; geometry=physical['soil_result']['state']['members'][snow][cell]['geometry']
    return seasonal_carbon.run_year(organic,initial,law,calendar,events,numerics=numerics,
        geometry_sha256=climate.digest(geometry),source_binding_sha256=bundle.source_sha256,
        scenario_id=snow+'/'+hypothesis_id+'/'+cell+'/'+layer_id,evidence=c['evidence'],source_status=c['source_status'],
        stop_after=stop_after,resume=resume)


def project(bundle,recipe,physical,water,snow,hypothesis_id,cell):
    if not water.get('events'):
        return {'status':'UNKNOWN','layers':None,'reason':'water chronology unavailable, no carbon interval holds invented'}
    soil=physical['soil_result']['state']['members'][snow][cell]
    products={}
    for suffix in recipe['carbon']['selected_layer_suffixes']:
        layer_id=cell+suffix
        products[layer_id]={'initial_pool_source_sha256':climate.digest(soil['surface_organic'] if soil['surface_organic']['layer_id']==layer_id else soil['organic_by_layer'].get(layer_id)),
            'diagnostic':layer_product(bundle,recipe,physical,water,snow,hypothesis_id,cell,layer_id)}
    return {'status':'CONDITIONAL_DIAGNOSTIC_ONLY','layers':products,
        'actual_field_prediction':{'status':'UNKNOWN','soil_temperature_k':None,'redox':None,'litter_carbon_kg_m2_s':None,
            'reason':'recipe drivers are explicit independent experiments, not calibrated field values or a soil-heat/litter-production model'},
        'water_product_sha256':climate.digest(water),'geometry_feedback':'NOT_APPLIED_DIAGNOSTIC_ONLY',
        'same_pool_age_initialised_once':True,'physical_geometry_and_water_not_modified':True,
        'temporal_approximation':'begin-event liquid WFPS held through that snow-liquid event; not monthly-mean WFPS or a converged coupled solution',
        'selected_layers_not_whole_soil_inventory':True}
