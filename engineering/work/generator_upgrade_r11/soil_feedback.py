"""Actual-layer held-water heat diagnostics and conservative unfrozen remap.

No frozen Richards or coupled thermal/history claim: the heat diagnostic holds
the *initial* water inventory, while the distinct remap conserves the actual
supplied native solver state's extensive liquid stock under new explicit laws.
"""
from copy import deepcopy
from dataclasses import asdict, fields as datafields
from fractions import Fraction as F
import json
from . import thermal as t


def _hash(value):
    if type(value) is not str or len(value)!=64 or any(c not in '0123456789abcdef' for c in value): raise ValueError('exact SHA256 required')
    return value


def native_column(sw,record):
    t.fields(record,(f.name for f in datafields(sw.Column)),'native column')
    value=dict(record)
    if type(value['layers']) is not list: raise ValueError('explicit native layer records required')
    value['layers']=tuple(sw.HydraulicLayer(**t.fields(x,(f.name for f in datafields(sw.HydraulicLayer)),'native layer')) for x in value['layers'])
    return sw.Column(**value)


def native_state(sw,column,record):
    t.fields(record,('head_m','elapsed_seconds','column_sha256'),'native water state')
    state=sw.State(tuple(record['head_m']),record['elapsed_seconds'],record['column_sha256'])
    if state.column_sha256!=sw.column_digest(column) or len(state.head_m)!=len(column.layers): raise ValueError('actual native state/column mismatch')
    return state


def water_stocks(sw,column,state):
    if type(column) is not sw.Column or type(state) is not sw.State or state.column_sha256!=sw.column_digest(column) or len(state.head_m)!=len(column.layers):
        raise ValueError('same bound native column/state required')
    return {layer.layer_id:F(sw.hydraulic_properties(layer,head)[0])*F(layer.thickness_m) for layer,head in zip(column.layers,state.head_m)}


def thermal_reference_spec(sw,actual_r10_unit):
    """Every retained layer, explicit thermal coefficients, fixed initial water.

    Contact resistance and heat capacities are explicitly synthetic hypotheses;
    they are NOT inferred from Ksat, vegetation, layer names, or waterbody T.
    """
    if type(actual_r10_unit) is not dict: raise ValueError('actual decoded R10 unit required')
    water=actual_r10_unit['hydrology']
    if water.get('schema')!='diadem.seasonal-layered-water.r10' or water.get('status')!='MODELLED_SEASONAL_HYDRAULICS' or water.get('completed_months')!=12: raise ValueError('complete actual parent hydraulic year required')
    if water['inputs_sha256']!=t.digest(water['inputs']): raise ValueError('parent hydraulic input digest differs')
    column=native_column(sw,water['column']); state=native_state(sw,column,water['initial_state'])
    if water['column_sha256']!=sw.column_digest(column): raise ValueError('parent thermal geometry digest differs')
    stock=water_stocks(sw,column,state); cells={}; initial={}; links=[]
    evidence='SYNTHETIC TEST: 1 m2 held initial-water heat column; dry solid volumetric heat capacity 2e6 J/m3/K, conductivity1.5 W/m/K, contact resistance0.1 m2 K/W, initial/deep T280 K; no mineral calibration or frozen Richards.'
    for layer in column.layers:
        cd=(1-F(layer.theta_s))*F(layer.thickness_m)*2000000
        if cd<=0: raise ValueError('positive actual dry thermal support required; pure-water cells need a separately supplied bed support')
        cell={'cell_id':layer.layer_id,'solid_heat_capacity_j_k':str(cd),'liquid_heat_capacity_j_kg_k':4180,'ice_heat_capacity_j_kg_k':2100,
            'latent_heat_j_kg':334000,'freezing_temperature_k':273.15,'evidence':evidence,'source_status':'SYNTHETIC TEST'}
        cells[layer.layer_id]=cell; initial[layer.layer_id]=t.initial_cell(cell,stock[layer.layer_id]*1000,280)
    for left,right in zip(column.layers,column.layers[1:]):
        resistance=F(1,10)+(F(left.thickness_m)+F(right.thickness_m))/3
        links.append({'link_id':left.layer_id+'->'+right.layer_id,'left':left.layer_id,'right':right.layer_id,'conductance_w_k':str(1/resistance),'evidence':evidence})
    events=[]; elapsed=F()
    for row in water['events']:
        if row['status']!='MODELLED': raise ValueError('complete actual thermal forcing chronology required')
        dt=F(row['duration_seconds'])
        if F(row['start_seconds_in_year'])!=elapsed: raise ValueError('parent event clock discontinuity')
        boundaries={key:{'temperature_k':280,'conductance_w_k':0,'evidence':evidence+'; interior no external heat source'} for key in cells}
        top,bottom=column.layers[0],column.layers[-1]
        boundaries[top.layer_id]={'temperature_k':None if row['air_temperature_c'] is None else str(F(row['air_temperature_c'])+F(27315,100)),
            'conductance_w_k':str(1/(F(1,10)+F(top.thickness_m)/3)),'evidence':evidence+'; actual event air drives a supplied surface contact law, not equality of soil and air temperature'}
        if bottom.layer_id==top.layer_id: raise ValueError('two-boundary one-layer thermal reference requires an explicit combined boundary operator')
        boundaries[bottom.layer_id]={'temperature_k':280,'conductance_w_k':str(1/(F(1,10)+F(bottom.thickness_m)/3)),'evidence':evidence+'; supplied deep bath'}
        events.append({'event_id':row['event_id'],'month_id':row['month_id'],'duration_seconds':str(dt),'start_seconds_in_year':str(elapsed),
            'boundaries':boundaries,'actual_water_event_sha256':t.digest(row),'evidence':evidence})
        elapsed+=dt
    expected=sum((F(water['months'][str(m)]['duration_seconds']) for m in range(1,13)),F())
    if elapsed!=expected: raise ValueError('actual full year chronology differs')
    return {'cells':cells,'initial_cells':initial,'links':links,'events':events,'controls':{'max_dt_seconds':str(min(F(water['months'][str(m)]['duration_seconds']) for m in range(1,13))/16),
        'max_substeps':100000,'energy_atol_j':'1/100'},'initial_elapsed_seconds':str(F(state.elapsed_seconds)),
        'joins':{'actual_r10_unit_sha256':t.digest(actual_r10_unit),'water_product_sha256':t.digest(water),'column_sha256':sw.column_digest(column),
            'initial_native_state_sha256':t.digest(water['initial_state']),'initial_layer_water_m':t.plain(stock),'represented_area_m2':'1',
            'liquid_density_kg_m3':'1000','water_support':'HOLD_INITIAL_WATER_DIAGNOSTIC_NOT_TIME_VARYING_PARENT_WATER'},'evidence':evidence}


def thermal_year(spec,*,source_binding_sha256,scenario_id,stop_after=None,resume=None):
    t.fields(spec,('cells','initial_cells','links','events','controls','initial_elapsed_seconds','joins','evidence'),'soil thermal specification')
    _hash(source_binding_sha256); t.text(scenario_id); t.text(spec['evidence']); t.fields(spec['controls'],('max_dt_seconds','max_substeps','energy_atol_j'),'thermal controls')
    identity=t.digest({'spec':spec,'source_binding_sha256':source_binding_sha256,'scenario_id':scenario_id})
    if type(spec['events']) is not list or not 1<=len(spec['events'])<=512: raise ValueError('bounded explicit thermal events required')
    total=len(spec['events']); count=total if stop_after is None else stop_after
    if type(count) is not int or not 0<=count<=total: raise ValueError('absolute complete thermal event cursor required')
    elapsed=F(); ids=set()
    for row in spec['events']:
        t.fields(row,('event_id','month_id','duration_seconds','start_seconds_in_year','boundaries','actual_water_event_sha256','evidence'),'soil thermal event')
        t.text(row['event_id']); t.text(row['evidence']); _hash(row['actual_water_event_sha256'])
        if row['event_id'] in ids or F(row['start_seconds_in_year'])!=elapsed or type(row['month_id']) is not int or not 1<=row['month_id']<=12: raise ValueError('thermal calendar/support continuity required')
        ids.add(row['event_id']); elapsed+=t.number(row['duration_seconds'],'thermal event duration',positive=True)
    if resume is not None:
        t.fields(resume,('schema','inputs_sha256','source_binding_sha256','state_sha256','state'),'soil thermal checkpoint')
        if resume['schema']!='diadem.held-soil-thermal-checkpoint.r11' or resume['inputs_sha256']!=identity or resume['source_binding_sha256']!=source_binding_sha256 or resume['state_sha256']!=t.digest(resume['state']): raise ValueError('thermal checkpoint source/input/checksum differs')
        cursor=resume['state']['completed_events']
        if type(cursor) is not int or not 0<=cursor<=count: raise ValueError('thermal checkpoint cursor invalid')
        expected=thermal_year(spec,source_binding_sha256=source_binding_sha256,scenario_id=scenario_id,stop_after=cursor)['checkpoint']
        if resume!=expected: raise ValueError('thermal checkpoint differs from actual replay')
    state=t.initial_column(spec['cells'],spec['initial_cells'],source_binding_sha256=source_binding_sha256,elapsed_seconds=spec['initial_elapsed_seconds'])
    rows=[]; completed=0; status=None
    for event in spec['events'][:count]:
        if status:
            rows.append({'event_id':event['event_id'],'status':'NOT_ADVANCED_PRIOR_GAP'}); continue
        result=t.advance_column(spec['cells'],state,spec['links'],event['boundaries'],event_id=event['event_id'],duration_seconds=event['duration_seconds'],**spec['controls'])
        if result['status']!='MODELLED': status=result['status']
        else: state=result['final_state']; completed+=1
        rows.append({'event_id':event['event_id'],'month_id':event['month_id'],'start_seconds_in_year':event['start_seconds_in_year'],'duration_seconds':event['duration_seconds'],
            'status':result['status'],'actual_water_event_sha256':event['actual_water_event_sha256'],'thermal_result':result})
    cpstate={'completed_events':completed,'continuing_state':state,'accepted_events':rows[:completed]}
    checkpoint={'schema':'diadem.held-soil-thermal-checkpoint.r11','inputs_sha256':identity,'source_binding_sha256':source_binding_sha256,'state_sha256':t.digest(cpstate),'state':cpstate}
    return {'schema':'diadem.held-soil-thermal-year.r11','status':status or ('MODELLED_HOLD_INITIAL_WATER_DIAGNOSTIC' if completed==total else 'STOPPED_AT_EVENT_BOUNDARY'),
        'inputs_sha256':identity,'inputs':{'spec':t.plain(spec),'source_binding_sha256':source_binding_sha256,'scenario_id':scenario_id},
        'source_binding_sha256':source_binding_sha256,'scenario_id':scenario_id,'events':rows,'completed_events':completed,
        'final_state':state if status is None and completed==total else None,'checkpoint':checkpoint,
        'water_support':'HOLD_INITIAL_WATER_DIAGNOSTIC','ecosystem_moisture_pairing':'NOT_VALIDATED_WITH_TIME_VARYING_R10_WATER',
        'frozen_richards_implemented':False,'geometry_feedback_applied':False}


def _organic_change(result,layer_id):
    if type(result) is not dict or result.get('schema')!='diadem.seasonal-ecosystem.r11' or result.get('status')!='MODELLED_SEASONAL_ECOSYSTEM': raise ValueError('actual complete ecosystem result required for organic material change')
    if t.digest(result['inputs'])!=result['inputs_sha256']: raise ValueError('ecosystem input digest differs')
    if any(result['inputs'][key]!=result[key] for key in ('source_binding_sha256','scenario_id','geometry_sha256')):
        raise ValueError('ecosystem inner/outer source, scenario or geometry binding differs')
    first=result['inputs']['initial_state']['organic_state']; last=result['final_state']['organic_state']
    if first['layer_id']!=layer_id or last['layer_id']!=layer_id or first['support_id']!=last['support_id']: raise ValueError('organic material support mismatch')
    cf=F(result['inputs']['organic_law']['carbon_fraction_dry_matter'])
    if not 0<cf<=1: raise ValueError('explicit valid dry carbon fraction required')
    def stock(value):
        if type(value) is not list or len(value)!=2 or any(type(x) is not int for x in value) or value[1]<=0:
            raise ValueError('actual R7 organic stock codec requires integer numerator/positive denominator')
        return t.number(F(*value),'organic carbon stock',nonnegative=True)
    old=(stock(first['fast_carbon_kg_m2'])+stock(first['slow_carbon_kg_m2']))/cf
    new=(stock(last['fast_carbon_kg_m2'])+stock(last['slow_carbon_kg_m2']))/cf
    previous=result['inputs']['initial_state']; elapsed=F(); source_events=result['inputs']['events']
    if len(result['events'])!=len(source_events) or result['completed_events']!=len(source_events): raise ValueError('full accepted ecosystem chronology required')
    for row,source in zip(result['events'],source_events):
        if (row['status']!='MODELLED' or row['event_id']!=source['event_id'] or row['layer_id']!=layer_id
                or row['support_id']!=first['support_id'] or row['initial_state']!=previous): raise ValueError('actual organic endpoint/source prefix differs')
        dt=F(source['organic_forcing']['duration_seconds'])
        if F(row['duration_seconds'])!=dt or F(row['start_seconds_in_year'])!=elapsed: raise ValueError('ecosystem accepted clock differs')
        oc0=stock(previous['organic_state']['fast_carbon_kg_m2'])+stock(previous['organic_state']['slow_carbon_kg_m2'])
        oc1=stock(row['end_state']['organic_state']['fast_carbon_kg_m2'])+stock(row['end_state']['organic_state']['slow_carbon_kg_m2'])
        live0=F(previous['live_carbon_kg_m2']); live1=F(row['end_state']['live_carbon_kg_m2'])
        growth=F(row['net_production_kg_c_m2']); potential=F(row['potential_net_production_kg_c_m2']); litter=F(row['litter_carbon_kg_m2']); harvest=F(row['harvested_carbon_kg_m2'])
        incoming=dt*(F(source['organic_forcing']['fast_litter_carbon_kg_m2_s'])+F(source['organic_forcing']['slow_litter_carbon_kg_m2_s']))
        producer=row['organic_producer']; carbon=producer['carbon']; export=F(carbon['exported_atmospheric_carbon_kg_m2'])
        if (not 0<=growth<=potential or not 0<=litter<=live0 or harvest!=(live0-litter+growth)*F(source['harvest_fraction'])
                or live1!=live0-litter+growth-harvest or F(carbon['initial_kg_m2'])!=oc0 or F(carbon['input_kg_m2'])!=incoming
                or F(carbon['final_kg_m2'])+export!=oc0+incoming or oc1!=F(carbon['final_kg_m2'])+litter
                or F(row['soil_material_change']['organic_dry_mass_change_kg_m2'])!=(oc1-oc0)/cf):
            raise ValueError('actual organic/growth/harvest stock transitions differ')
        budget={'initial':live0+oc0,'final':live1+oc1,'net_atmospheric_input':growth,'external_litter_input':incoming,
            'heterotrophic_export':export,'harvest_export':harvest,'numerical_residual':F()}
        if set(row['budgets_kg_m2']['C'])!=set(budget) or any(F(row['budgets_kg_m2']['C'][k])!=v for k,v in budget.items()) or live0+oc0+growth+incoming!=live1+oc1+export+harvest:
            raise ValueError('actual complete ecosystem carbon budget differs')
        previous=row['end_state']; elapsed+=dt
    if result['final_state']!=previous: raise ValueError('final organic state differs from accepted source-bound endpoint')
    delta=sum((F(row['soil_material_change']['organic_dry_mass_change_kg_m2']) for row in result['events']),F())
    if new-old!=delta or any(F(row['soil_material_change']['mineral_mass_change_kg_m2'])!=0 for row in result['events']): raise ValueError('actual material change ledger differs')
    return old,new


def material_spec_from_formed(sw,actual_r10_unit,formed_cell,ecosystem_result,*,organic_grain_density_kg_m3,evidence,source_binding_sha256):
    """Actual R7 mineral/OM geometry -> actual R11 selected-cohort dry change.

    Grain density of organic material is a required retained/supplied law. All
    other layers keep their existing stock; no second replay of R10 carbon.
    Porosity and retention/Ksat laws are deliberately held at the supplied old
    joint law, so the changed dry stock changes physical layer thickness only.
    """
    t.text(evidence); organic_density=t.number(organic_grain_density_kg_m3,'explicit organic grain density',positive=True)
    if (ecosystem_result['source_binding_sha256']!=_hash(source_binding_sha256)
            or ecosystem_result['scenario_id']!=actual_r10_unit['snow_id']+'/'+actual_r10_unit['hydraulic_hypothesis_id']+'/'+actual_r10_unit['cell_id']): raise ValueError('actual ecosystem source/scenario binding differs')
    if t.digest(formed_cell)!=actual_r10_unit['formed_soil_sha256']: raise ValueError('actual retained formed material cell hash differs')
    water=actual_r10_unit['hydrology']; column=native_column(sw,water['column'])
    if (ecosystem_result['geometry_sha256']!=t.digest(formed_cell['geometry'])
            or ecosystem_result['inputs_sha256']!=t.digest(ecosystem_result['inputs'])
            or actual_r10_unit['carbon']['water_product_sha256']!=t.digest(water)):
        raise ValueError('actual ecosystem/material geometry or water product join differs')
    selected=ecosystem_result['inputs']['initial_state']['organic_state']['layer_id']; old_organic,new_organic=_organic_change(ecosystem_result,selected)
    geometry=formed_cell['geometry']; old_layers=formed_cell['formation_state']['layers']
    if [row['layer_id'] for row in geometry]!=[layer.layer_id for layer in column.layers]: raise ValueError('actual formed/hydraulic layer order differs')
    minerals={row['layer_id']:row for row in old_layers}
    material={}
    for layer,row in zip(column.layers,geometry):
        if float(F(row['thickness_m']))!=layer.thickness_m or float(F(row['porosity']))!=layer.theta_s: raise ValueError('actual formed physical volume differs from native water geometry')
        mid=layer.layer_id; mineral_mass=F(row['mineral_mass_kg_m2']); organic_mass=F(row['organic_dry_mass_kg_m2'])
        if F(row['total_dry_mass_kg_m2'])!=mineral_mass+organic_mass: raise ValueError('retained dry material ledger differs')
        constituents=[]
        if mineral_mass:
            parent=minerals.get(mid)
            if parent is None or F(parent['mineral_mass_kg_m2'])!=mineral_mass: raise ValueError('retained mineral constituent missing or changed')
            density=t.number(parent['grain_density_kg_m3'],'actual mineral grain density',positive=True)
            constituents.append({'constituent_id':mid+'/mineral','kind':'MINERAL','old_mass_kg_m2':str(mineral_mass),'new_mass_kg_m2':str(mineral_mass),
                'grain_density_kg_m3':str(density),'evidence':evidence+'; actual retained formation mineral stock/density unchanged'})
        if mid==selected and organic_mass!=old_organic: raise ValueError('actual ecosystem initial organic stock differs from formed material')
        if organic_mass or mid==selected:
            constituents.append({'constituent_id':mid+'/organic','kind':'ORGANIC','old_mass_kg_m2':str(organic_mass),
                'new_mass_kg_m2':str(new_organic if mid==selected else organic_mass),'grain_density_kg_m3':str(organic_density),
                'evidence':evidence+'; actual selected organic dry-origin stock change; nonselected cohorts held, no duplicated carbon year'})
        material[mid]={'constituents':constituents,'new_porosity':str(F(layer.theta_s)),
            'hydraulic_law':{name:getattr(layer,name) for name in ('theta_r','alpha_per_m','n','mualem_l','ksat_m_s','evidence','source_status')},
            'evidence':evidence+'; explicit continuation of original joint porosity/retention law, not carbon-to-Ksat estimation','source_status':'SYNTHETIC TEST'}
    return material


def rebind_unfrozen(sw,old_column,old_state,material_layers,*,ice_water_m_by_layer,water_atol_m,geometry_atol_m,
                    source_binding_sha256,evidence,ecosystem_result=None,ecosystem_scenario_id=None):
    """Instantaneous one-to-one remap; full native next-step solve remains required.

    Each layer declares constituents with old/new dry mass and grain density,
    new porosity and a full new hydraulic law. Nonzero mass change is admitted
    only for one ORGANIC constituent joined to the actual ecosystem output.
    Old geometry must independently equal the supplied constituent solid volume.
    """
    _hash(source_binding_sha256); t.text(evidence); tolerance=t.number(water_atol_m,'water remap allowance',positive=True); geom=t.number(geometry_atol_m,'geometry allowance',positive=True)
    stocks=water_stocks(sw,old_column,old_state); ids=[x.layer_id for x in old_column.layers]
    if ecosystem_result is not None and (ecosystem_result['source_binding_sha256']!=source_binding_sha256 or ecosystem_scenario_id is None or ecosystem_result['scenario_id']!=ecosystem_scenario_id): raise ValueError('explicit ecosystem source/scenario must match remap')
    if type(material_layers) is not dict or list(material_layers)!=ids: raise ValueError('exact one-to-one ordered material supports required')
    if type(ice_water_m_by_layer) is not dict or set(ice_water_m_by_layer)!=set(ids): raise ValueError('explicit phase evidence for every layer required')
    if any(t.number(v,'ice stock',nonnegative=True)!=0 for v in ice_water_m_by_layer.values()): raise ValueError('frozen material remap/Richards is not implemented')
    new_layers=[]; rows=[]; organic_used=False
    for layer in old_column.layers:
        material=material_layers[layer.layer_id]
        t.fields(material,('constituents','new_porosity','hydraulic_law','evidence','source_status'),'material packing'); t.text(material['evidence'])
        if material['source_status'] not in ('SYNTHETIC TEST','WORKING NON-CANON'): raise ValueError('known explicitly supplied material law required')
        if type(material['constituents']) is not list or not material['constituents']: raise ValueError('finite complete dry constituents required')
        old_volume=F(); new_volume=F(); unique=set(); changes=[]
        for constituent in material['constituents']:
            t.fields(constituent,('constituent_id','kind','old_mass_kg_m2','new_mass_kg_m2','grain_density_kg_m3','evidence'),'dry constituent'); t.text(constituent['constituent_id']); t.text(constituent['evidence'])
            if constituent['constituent_id'] in unique or constituent['kind'] not in ('MINERAL','ORGANIC'): raise ValueError('unique supported dry constituents required')
            unique.add(constituent['constituent_id']); density=t.number(constituent['grain_density_kg_m3'],'grain density',positive=True)
            old=t.number(constituent['old_mass_kg_m2'],'old dry mass',nonnegative=True); new=t.number(constituent['new_mass_kg_m2'],'new dry mass',nonnegative=True)
            if new!=old:
                if constituent['kind']!='ORGANIC' or ecosystem_result is None or organic_used: raise ValueError('changed solid stock needs one actual organic producer join; mineral creation forbidden')
                expected=_organic_change(ecosystem_result,layer.layer_id)
                if (old,new)!=expected: raise ValueError('proposed organic dry mass differs from actual producer')
                organic_used=True
            old_volume+=old/density; new_volume+=new/density; changes.append({'constituent_id':constituent['constituent_id'],'dry_mass_change_kg_m2':str(new-old)})
        old_depth=old_volume/(1-F(layer.theta_s)) if layer.theta_s<1 else None
        if old_depth is None or abs(old_depth-F(layer.thickness_m))>geom: raise ValueError('actual old geometry does not close with declared dry constituent stock')
        porosity=t.number(material['new_porosity'],'new porosity',positive=True)
        if porosity>=1 or new_volume<=0: raise ValueError('finite positive solid geometry and subunit porosity required')
        exact_depth=new_volume/(1-porosity)
        law=t.fields(material['hydraulic_law'],('theta_r','alpha_per_m','n','mualem_l','ksat_m_s','evidence','source_status'),'new hydraulic law')
        converted={key:(float(t.number(value,key)) if key not in ('evidence','source_status') and value is not None else value) for key,value in law.items()}
        new_layer=sw.HydraulicLayer(layer_id=layer.layer_id,thickness_m=float(exact_depth),theta_s=float(porosity),**converted)
        if not new_layer.known or F(new_layer.theta_s)!=porosity: raise ValueError('new porosity/law cannot be represented exactly or is unknown; no clipping')
        if abs(F(new_layer.thickness_m)-exact_depth)>geom: raise ValueError('represented thickness differs from physical packing beyond allowance')
        target=stocks[layer.layer_id]/F(new_layer.thickness_m)
        old_head=old_state.head_m[len(new_layers)]; retained_saturated=False
        if target>=F(new_layer.theta_s):
            if target==F(new_layer.theta_s) and new_layer==layer and new_volume==old_volume and old_head>=0:
                retained_saturated=True
            else: raise ValueError('saturated or overflow target at '+layer.layer_id+' has no uniquely inferred pressure; redistribution/pressure solve required')
        if target<=F(new_layer.theta_r): raise ValueError('target at/below residual; no phantom wetting or artificial dry head')
        target_float=float(target)
        if not retained_saturated and not new_layer.theta_r<target_float<new_layer.theta_s: raise ValueError('target unsaturated water content is not representable')
        head=old_head if retained_saturated else sw.head_from_theta(new_layer,target_float)
        if not retained_saturated and head>=0: raise ValueError('unsaturated remap returned nonnegative head')
        represented=F(sw.hydraulic_properties(new_layer,head)[0])*F(new_layer.thickness_m); residual=represented-stocks[layer.layer_id]
        if abs(residual)>tolerance: raise ValueError('native inverse retention exceeds explicit water allowance')
        new_layers.append(new_layer); rows.append({'layer_id':layer.layer_id,'old_water_m':str(stocks[layer.layer_id]),'new_water_m':str(represented),
            'representation_residual_m':str(residual),'old_thickness_m':str(F(layer.thickness_m)),'new_thickness_m_exact':str(exact_depth),'new_thickness_m_represented':str(F(new_layer.thickness_m)),
            'new_head_m':head,'constituent_changes':changes,
            'head_status':'UNCHANGED_SATURATED_SUPPORT_PRIOR_HEAD_NUMERICAL_INITIAL_CONDITION_ONLY' if retained_saturated else 'UNIQUE_UNSATURATED_STOCK_INVERSE'})
    new_column=sw.Column(old_column.column_id,tuple(new_layers),old_column.root_boundary_index,evidence,'SYNTHETIC TEST')
    new_state=sw.initial_state(new_column,tuple(row['new_head_m'] for row in rows),elapsed_seconds=old_state.elapsed_seconds)
    total=sum((F(row['representation_residual_m']) for row in rows),F())
    if abs(total)>tolerance: raise ValueError('column inverse representation residual exceeds supplied total water allowance')
    if ecosystem_result is not None and not organic_used and any(F(row['soil_material_change']['organic_dry_mass_change_kg_m2']) for row in ecosystem_result['events']): raise ValueError('actual changed organic stock was not incorporated')
    inputs={'old_column':asdict(old_column),'old_state':asdict(old_state),'material_layers':material_layers,'ice_water_m_by_layer':ice_water_m_by_layer,
        'water_atol_m':water_atol_m,'geometry_atol_m':geometry_atol_m,'source_binding_sha256':source_binding_sha256,'evidence':evidence,
        'ecosystem_result_sha256':None if ecosystem_result is None else t.digest(ecosystem_result)}
    return {'schema':'diadem.conservative-soil-water-rebind.r11','status':'MODELLED_ONE_TO_ONE_WATER_REBIND','source_binding_sha256':source_binding_sha256,
        'inputs_sha256':t.digest(inputs),'inputs':t.plain(inputs),'old_column_sha256':sw.column_digest(old_column),'new_column_sha256':sw.column_digest(new_column),
        'new_column':t.plain(asdict(new_column)),'new_state':t.plain(asdict(new_state)),'layer_ledgers':rows,'total_water_representation_residual_m':str(total),
        'external_water_input_m':'0','external_water_output_m':'0','elapsed_seconds_before':old_state.elapsed_seconds,'elapsed_seconds_after':new_state.elapsed_seconds,
        'pressure_semantics':'CHANGED_SUPPORT_UNIQUE_UNSATURATED_INVERSE; UNCHANGED_SATURATED_PRIOR_HEAD_IS_NUMERICAL_INITIAL_GUESS_ONLY',
        'thermal_energy_and_deformation_work':'NOT_MODELLED_UNFROZEN_ISOTHERMAL_INSTANTANEOUS_GEOMETRY_HYPOTHESIS',
        'forcing_events_consumed':[],'next_actual_water_step_required':True,'frozen_richards_implemented':False,
        'current_pressure_status':'UNVERIFIED_UNTIL_NEXT_ACTUAL_WATER_STEP'}


def reference_continuation(solver,actual_r10_unit,formed_cell,ecosystem_result,*,organic_grain_density_kg_m3,
                           source_binding_sha256,evidence,duration_seconds=1,geometry_atol_m=1e-9):
    """Actual organic structure remap then a new explicit no-input water interval.

    This short isothermal/unfrozen continuation is a numerical/physical coupling
    reference, not a future climate forecast. The original whole year is never
    replayed or reset, and old saturated guesses are not the returned pressure.
    """
    t.text(evidence); dt=t.number(duration_seconds,'new explicit continuation duration',positive=True)
    if F(float(dt))!=dt: raise ValueError('reference continuation duration must be exactly representable')
    sw=solver; water=actual_r10_unit['hydrology']; scenario=actual_r10_unit['snow_id']+'/'+actual_r10_unit['hydraulic_hypothesis_id']+'/'+actual_r10_unit['cell_id']
    material=material_spec_from_formed(sw,actual_r10_unit,formed_cell,ecosystem_result,
        organic_grain_density_kg_m3=organic_grain_density_kg_m3,evidence=evidence,source_binding_sha256=source_binding_sha256)
    column=native_column(sw,water['column']); state=native_state(sw,column,water['final_state'])
    control_values=water['inputs']['controls']; controls=sw.Controls(**control_values)
    if actual_r10_unit['initial_condition']['boundary']['kind']!='no_flow': raise ValueError('this explicit closed-base continuation requires the actual no-flow parent support')
    remap=rebind_unfrozen(sw,column,state,material,ice_water_m_by_layer={layer.layer_id:0 for layer in column.layers},
        water_atol_m=controls.total_mass_atol_m,geometry_atol_m=geometry_atol_m,source_binding_sha256=source_binding_sha256,
        evidence=evidence+'; original unfrozen hydraulic hypothesis continued isothermally, no deformation-work/thermal solve',
        ecosystem_result=ecosystem_result,ecosystem_scenario_id=scenario)
    following=native_column(sw,remap['new_column']); initial=native_state(sw,following,remap['new_state'])
    forcing=sw.Forcing(float(dt),0.,0.,None,evidence+'; new declared short zero-rain/zero-demand continuation interval, not repeated annual forcing','SYNTHETIC TEST')
    boundary=sw.Boundary('no_flow',None,evidence+'; original no-flow base retained','SYNTHETIC TEST')
    result=solver.advance(following,initial,forcing,boundary,controls,
        water_density_kg_m3=water['inputs']['water_density_kg_m3'],gravity_m_s2=water['inputs']['gravity_m_s2'])
    record={key:(asdict(value) if hasattr(value,'__dataclass_fields__') else value) for key,value in result.items()}
    status='MODELLED_STRUCTURE_AND_WATER_CONTINUATION' if result['status']=='MODELLED' else 'WATER_CONTINUATION_'+result['status']
    if result['status']=='MODELLED' and (result['state'].column_sha256!=sw.column_digest(following) or F(result['state'].elapsed_seconds)!=F(state.elapsed_seconds)+dt): raise ValueError('new actual solver state/clock differs from remapped support')
    return {'schema':'diadem.actual-soil-structure-continuation.r11','status':status,'source_binding_sha256':source_binding_sha256,'scenario_id':scenario,
        'actual_r10_unit_sha256':t.digest(actual_r10_unit),'formed_cell_sha256':t.digest(formed_cell),'ecosystem_result_sha256':t.digest(ecosystem_result),
        'rebind':remap,'actual_water_step':t.plain(record),'duration_seconds':str(dt),
        'pressure_status':'ACTUAL_NEW_GEOMETRY_SOLVER_PRODUCED' if result['status']=='MODELLED' else 'UNVERIFIED',
        'thermal_regime':'EXPLICIT_UNFROZEN_ISOTHERMAL_CONTINUATION_NOT_COUPLED_TO_HELD_WATER_THERMAL_DIAGNOSTIC',
        'new_forcing_forecast':False,'full_history_recomputed':False,'frozen_richards_implemented':False}
