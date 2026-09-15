"""Finite stage/storage routing with conservative heat and liquid/ice coupling.

This is a supplied prism-reservoir network, NOT frozen Richards, a dynamic-wave
channel solver, or a reconstruction of sub-monthly floods. Event inputs are
uniform over their explicit interval. No physical coefficient is defaulted.
"""
from copy import deepcopy
from fractions import Fraction as F
from . import thermal as t

SCHEMA='diadem.thermal-water-network.r11'
STATE_SCHEMA='diadem.thermal-water-state.r11'
CHECKPOINT_SCHEMA='diadem.thermal-water-checkpoint.r11'
RESULT_SCHEMA='diadem.thermal-water-result.r11'
STATUS=('SYNTHETIC TEST','WORKING NON-CANON','UNKNOWN')
NODE_FIELDS=('kind','datum_m','storage_area_m2','liquid_density_kg_m3','ice_density_kg_m3',
    'capacity_m3','spill_sink_id','thermal','evidence','source_status')
LINK_FIELDS=('link_id','left','right','conductance_m2_s','liquid_fraction_exponent','evidence')
EVENT_FIELDS=('event_id','duration_seconds','inflows','withdrawals','heat_boundaries','evidence','source_status')
INFLOW_FIELDS=('allocation_id','node_id','volume_m3','temperature_k','evidence')
DRAW_FIELDS=('allocation_id','node_id','sink_id','volume_m3','kind','latent_heat_j_kg','evidence')
CONTROL_FIELDS=('max_dt_seconds','stability_fraction','max_substeps','energy_atol_j')
LEDGER=('external_in_kg','external_out_kg','internal_in_kg','internal_out_kg',
    'external_advected_in_j','external_advected_out_j','internal_advected_in_j','internal_advected_out_j',
    'boundary_heat_j','internal_heat_j','latent_export_j')


def _status(value):
    if value not in STATUS: raise ValueError('explicit working/unknown source status required')


def _hash(value):
    if type(value) is not str or len(value)!=64 or any(c not in '0123456789abcdef' for c in value):
        raise ValueError('exact lowercase SHA256 required')
    return value


def _list(value,label,maximum):
    if type(value) is not list or len(value)>maximum: raise ValueError('bounded '+label+' list required')
    return value


def validate_network(network):
    t.fields(network,('schema','network_id','nodes','links','heat_links','evidence','source_status'),'network')
    if network['schema']!=SCHEMA: raise ValueError('R11 network schema required')
    t.text(network['network_id']); t.text(network['evidence']); _status(network['source_status'])
    nodes=network['nodes']
    if type(nodes) is not dict or not 1<=len(nodes)<=64: raise ValueError('one to 64 explicit stores required')
    unknown=network['source_status']=='UNKNOWN'; fluid=None
    for key,node in nodes.items():
        t.text(key); t.fields(node,NODE_FIELDS,'water node'); t.text(node['evidence']); _status(node['source_status'])
        if node['kind'] not in ('CHANNEL','LAKE','WETLAND','GROUNDWATER'): raise ValueError('known finite store kind required')
        t.text(node['spill_sink_id'])
        if node['spill_sink_id'] in nodes: raise ValueError('spill sink is external, not another internal store')
        t.fields(node['thermal'],t.CELL_FIELDS,'thermal law')
        _status(node['thermal']['source_status']); t.text(node['thermal']['evidence'])
        if node['thermal']['cell_id']!=key: raise ValueError('thermal and water support IDs differ')
        required=('datum_m','storage_area_m2','liquid_density_kg_m3','ice_density_kg_m3','capacity_m3')
        absent=node['source_status']=='UNKNOWN' or node['thermal']['source_status']=='UNKNOWN' or any(node[k] is None for k in required) or any(node['thermal'][k] is None for k in t.CELL_FIELDS[1:6])
        unknown=unknown or absent
        if absent: continue
        t.number(node['datum_m'],'datum')
        for k in required[1:]: t.number(node[k],k,positive=True)
        coefficients=t.coefficients(node['thermal'])
        props=(t.number(node['liquid_density_kg_m3'],'liquid density'),t.number(node['ice_density_kg_m3'],'ice density'))+coefficients[1:]
        if fluid is None: fluid=props
        if props!=fluid: raise ValueError('connected stores require identical supplied fluid phase/energy reference properties')
    link_ids=set()
    for link in _list(network['links'],'hydraulic links',256):
        t.fields(link,LINK_FIELDS,'hydraulic link'); t.text(link['link_id']); t.text(link['evidence'])
        if link['link_id'] in link_ids: raise ValueError('duplicate hydraulic link ID')
        link_ids.add(link['link_id'])
        if link['left'] not in nodes or link['right'] not in nodes or link['left']==link['right']: raise ValueError('distinct internal link endpoints required')
        if link['conductance_m2_s'] is None: unknown=True
        else: t.number(link['conductance_m2_s'],'hydraulic conductance',nonnegative=True)
        if type(link['liquid_fraction_exponent']) is not int or not 1<=link['liquid_fraction_exponent']<=16: raise ValueError('explicit integer phase exponent 1..16 required')
    heat_ids=set()
    for link in _list(network['heat_links'],'heat links',256):
        t.fields(link,('link_id','left','right','conductance_w_k','evidence'),'heat link'); t.text(link['link_id']); t.text(link['evidence'])
        if link['link_id'] in heat_ids: raise ValueError('duplicate heat link')
        heat_ids.add(link['link_id'])
        if link['left'] not in nodes or link['right'] not in nodes or link['left']==link['right']: raise ValueError('distinct heat endpoints required')
        if link['conductance_w_k'] is None: unknown=True
        else: t.number(link['conductance_w_k'],'heat conductance',nonnegative=True)
    return not unknown


def controls_validate(controls):
    t.fields(controls,CONTROL_FIELDS,'water controls')
    dt=t.number(controls['max_dt_seconds'],'maximum routing step',positive=True)
    safety=t.number(controls['stability_fraction'],'explicit stability fraction',positive=True)
    if safety>F(1,2): raise ValueError('stability fraction must not exceed one half')
    if type(controls['max_substeps']) is not int or not 1<=controls['max_substeps']<=100000: raise ValueError('bounded integer work budget required')
    t.number(controls['energy_atol_j'],'energy equation allowance',positive=True)
    return dt,safety


def node_snapshot(node,state):
    phase=t.phase(node['thermal'],**state)
    liquid=F(phase['liquid_water_kg'])/F(node['liquid_density_kg_m3'])
    ice=F(phase['ice_water_kg'])/F(node['ice_density_kg_m3'])
    if node['kind']=='GROUNDWATER' and ice:
        raise ValueError('ice-bearing groundwater pressure/storage is outside the supplied unfrozen aquifer prism law')
    equivalent=F(phase['water_mass_kg'])/F(node['liquid_density_kg_m3'])
    return dict(phase,liquid_storage_m3=str(liquid),ice_volume_m3=str(ice),occupied_volume_m3=str(liquid+ice),
        water_equivalent_storage_m3=str(equivalent),
        stage_m=str(F(node['datum_m'])+equivalent/F(node['storage_area_m2'])),
        hydraulic_head_interpretation='UNFROZEN_LINEAR_AQUIFER_STORAGE' if node['kind']=='GROUNDWATER' else 'WATER_EQUIVALENT_COLUMN_LOAD_OPEN_OR_FLOATING_ICE_PRISM',
        storage_geometry='OCCUPIED_VOLUME_CAPACITY_SEPARATE_FROM_WATER_EQUIVALENT_HEAD')


def initial_state(network,states,*,elapsed_seconds=0):
    if not validate_network(network): raise ValueError('known laws required to initialise an actual physical state')
    if type(states) is not dict or set(states)!=set(network['nodes']): raise ValueError('exact initial support set required')
    for key,state in states.items():
        t.fields(state,('water_mass_kg','energy_j'),'initial node state')
        snapshot=node_snapshot(network['nodes'][key],state)
        if F(snapshot['occupied_volume_m3'])>F(network['nodes'][key]['capacity_m3']): raise ValueError('initial phase volume exceeds declared geometry')
    return {'schema':STATE_SCHEMA,'network_sha256':t.digest(network),'elapsed_seconds':str(t.number(elapsed_seconds,'initial time',nonnegative=True)),
        'nodes':t.plain(states),'consumed_event_ids':[]}


def _validate_events(network,events):
    ids=set(); allocations=set(); known=[]
    for event in _list(events,'events',512):
        t.fields(event,EVENT_FIELDS,'water event'); t.text(event['event_id']); t.text(event['evidence']); _status(event['source_status'])
        if event['event_id'] in ids: raise ValueError('event IDs must be unique')
        ids.add(event['event_id']); t.number(event['duration_seconds'],'event duration',positive=True)
        complete=event['source_status']!='UNKNOWN'
        for category,required in (('inflows',INFLOW_FIELDS),('withdrawals',DRAW_FIELDS)):
            for row in _list(event[category],category,256):
                t.fields(row,required,category); t.text(row['allocation_id']); t.text(row['evidence'])
                if row['allocation_id'] in allocations or row['allocation_id'].startswith('spill/'): raise ValueError('unique nonreserved allocation IDs required across all events')
                allocations.add(row['allocation_id'])
                if row['node_id'] not in network['nodes']: raise ValueError('unknown event support')
                if row['volume_m3'] is None: complete=False
                else: t.number(row['volume_m3'],'event water volume',nonnegative=True)
                if category=='inflows':
                    if row['temperature_k'] is None: complete=False
                    else: t.number(row['temperature_k'],'inflow temperature',positive=True)
                else:
                    t.text(row['sink_id'])
                    if row['sink_id'] in network['nodes']: raise ValueError('withdrawal sinks must be outside the routed network')
                    if row['kind'] not in ('ALLOCATION','EVAPORATION'): raise ValueError('explicit allocation or evaporation required')
                    if row['latent_heat_j_kg'] is None: complete=False
                    else:
                        latent=t.number(row['latent_heat_j_kg'],'evaporation latent heat',nonnegative=True)
                        if (row['kind']=='EVAPORATION' and latent<=0) or (row['kind']=='ALLOCATION' and latent!=0): raise ValueError('latent vaporisation energy belongs only to evaporation')
        if type(event['heat_boundaries']) is not dict or set(event['heat_boundaries'])!=set(network['nodes']): raise ValueError('explicit heat boundary for every store required, including zero conductance')
        for boundary in event['heat_boundaries'].values():
            t.fields(boundary,('temperature_k','conductance_w_k','evidence'),'heat boundary'); t.text(boundary['evidence'])
            if boundary['temperature_k'] is None or boundary['conductance_w_k'] is None: complete=False
            else:
                t.number(boundary['temperature_k'],'heat boundary temperature',positive=True); t.number(boundary['conductance_w_k'],'heat boundary conductance',nonnegative=True)
        known.append(complete)
    return known


def _state_validate(network,state):
    t.fields(state,('schema','network_sha256','elapsed_seconds','nodes','consumed_event_ids'),'water state')
    if state['schema']!=STATE_SCHEMA or state['network_sha256']!=t.digest(network): raise ValueError('physical state belongs to another network/schema')
    if type(state['consumed_event_ids']) is not list or any(type(x) is not str for x in state['consumed_event_ids']) or len(set(state['consumed_event_ids']))!=len(state['consumed_event_ids']): raise ValueError('exact once-only consumed event IDs required')
    initial_state(network,state['nodes'],elapsed_seconds=state['elapsed_seconds'])


def _step_limit(network,controls):
    dt,safety=controls_validate(controls)
    rates={key:F() for key in network['nodes']}
    for link in network['links']:
        for key in ('left','right'):
            node=link[key]; rates[node]+=F(link['conductance_m2_s'])/F(network['nodes'][node]['storage_area_m2'])
    for rate in rates.values():
        if rate: dt=min(dt,safety/rate)
    return dt


def _event(network,state,event,controls,source_binding_sha256):
    nodes=network['nodes']; start=deepcopy(state); current=deepcopy(state['nodes'])
    ledgers={key:{field:F() for field in LEDGER} for key in nodes}
    deliveries={}; transfers={link['link_id']:{'left_to_right_kg':F(),'right_to_left_kg':F(),'left_to_right_energy_j':F(),'right_to_left_energy_j':F()} for link in network['links']}
    duration=F(event['duration_seconds']); dtmax=_step_limit(network,controls); elapsed=F(); steps=[]; advective_roundoff=F()
    def remove(key,mass):
        nonlocal advective_roundoff
        if not mass: return deepcopy(current[key]),F()
        p=t.phase(nodes[key]['thermal'],**current[key])
        exact=mass*t.liquid_enthalpy(nodes[key]['thermal'],p['temperature_k_exact'])
        updated,energy=t.remove_liquid(nodes[key]['thermal'],current[key],mass,energy_atol_j=controls['energy_atol_j'])
        advective_roundoff+=abs(energy-exact)
        return updated,energy
    def delivery(row,mass,energy,latent,requested):
        key=row['allocation_id']; rho=F(nodes[row['node_id']]['liquid_density_kg_m3'])
        if key not in deliveries:
            deliveries[key]=dict(row,event_id=event['event_id'],source_binding_sha256=source_binding_sha256,
                available_after_seconds=str(F(start['elapsed_seconds'])+duration),availability_support='INTERVAL_END_DELIVERY_NOT_WITHIN_INTERVAL_RESERVOIR_STOCK',
                delivered_volume_m3=F(),delivered_mass_kg=F(),advected_energy_j=F(),latent_energy_j=F(),requested_volume_m3=F(),unmet_volume_m3=F())
        target=deliveries[key]; target['delivered_mass_kg']+=mass; target['delivered_volume_m3']+=mass/rho
        target['advected_energy_j']+=energy; target['latent_energy_j']+=latent; target['requested_volume_m3']+=requested; target['unmet_volume_m3']+=requested-mass/rho
    while elapsed<duration:
        if len(steps)>=controls['max_substeps']: raise ValueError('explicit routing work budget exhausted; no accepted event state')
        dt=min(dtmax,duration-elapsed)
        for row in event['inflows']:
            key=row['node_id']; mass=F(row['volume_m3'])*dt/duration*F(nodes[key]['liquid_density_kg_m3'])
            current[key],energy=t.add_liquid(nodes[key]['thermal'],current[key],mass,row['temperature_k'])
            ledgers[key]['external_in_kg']+=mass; ledgers[key]['external_advected_in_j']+=energy
        for key,boundary in event['heat_boundaries'].items():
            current[key],receipt=t.boundary_heat(nodes[key]['thermal'],current[key],boundary['temperature_k'],boundary['conductance_w_k'],dt,energy_atol_j=controls['energy_atol_j'])
            ledgers[key]['boundary_heat_j']+=F(receipt['energy_into_cell_j'])
        for link in network['heat_links']:
            a,b=link['left'],link['right']
            current[a],current[b],receipt=t.exchange_heat(nodes[a]['thermal'],current[a],nodes[b]['thermal'],current[b],link['conductance_w_k'],dt,energy_atol_j=controls['energy_atol_j'])
            q=F(receipt['energy_left_to_right_j']); ledgers[a]['internal_heat_j']-=q; ledgers[b]['internal_heat_j']+=q
        for link in network['links']:
            a,b=link['left'],link['right']; pa=node_snapshot(nodes[a],current[a]); pb=node_snapshot(nodes[b],current[b])
            difference=F(pa['stage_m'])-F(pb['stage_m']); donor,receiver=(a,b) if difference>=0 else (b,a)
            fractions=[]
            for p in (pa,pb):
                mass=F(p['water_mass_kg']); fractions.append(F(p['liquid_water_kg'])/mass if mass else F(1))
            factor=min(fractions)**link['liquid_fraction_exponent']
            desired=F(link['conductance_m2_s'])*factor*abs(difference)*dt*F(nodes[donor]['liquid_density_kg_m3'])
            available=F(t.phase(nodes[donor]['thermal'],**current[donor])['liquid_water_kg'])
            mass=min(desired,available)
            # Represent the flux once, then exact equal/opposite extensive updates.
            mass=min(t.represented(mass,'liquid transfer mass'),available)
            current[donor],energy=remove(donor,mass)
            current[receiver]={'water_mass_kg':str(F(current[receiver]['water_mass_kg'])+mass),'energy_j':str(F(current[receiver]['energy_j'])+energy)}
            t.phase(nodes[receiver]['thermal'],**current[receiver])
            ledgers[donor]['internal_out_kg']+=mass; ledgers[receiver]['internal_in_kg']+=mass
            ledgers[donor]['internal_advected_out_j']+=energy; ledgers[receiver]['internal_advected_in_j']+=energy
            direction='left_to_right' if donor==a else 'right_to_left'
            transfers[link['link_id']][direction+'_kg']+=mass; transfers[link['link_id']][direction+'_energy_j']+=energy
        for row in event['withdrawals']:
            key=row['node_id']; requested=F(row['volume_m3'])*dt/duration
            available=F(t.phase(nodes[key]['thermal'],**current[key])['liquid_water_kg']); mass=min(available,requested*F(nodes[key]['liquid_density_kg_m3']))
            current[key],energy=remove(key,mass); latent=mass*F(row['latent_heat_j_kg'])
            current[key]['energy_j']=str(F(current[key]['energy_j'])-latent); t.phase(nodes[key]['thermal'],**current[key])
            ledgers[key]['external_out_kg']+=mass; ledgers[key]['external_advected_out_j']+=energy; ledgers[key]['latent_export_j']+=latent
            delivery(row,mass,energy,latent,requested)
        for key,node in nodes.items():
            p=node_snapshot(node,current[key]); excess=F(p['occupied_volume_m3'])-F(node['capacity_m3'])
            if excess<=0: continue
            mass=excess*F(node['liquid_density_kg_m3'])
            if mass>F(p['liquid_water_kg']): raise ValueError('ice volume exceeds fixed storage geometry; expansion deformation not implemented')
            current[key],energy=remove(key,mass)
            ledgers[key]['external_out_kg']+=mass; ledgers[key]['external_advected_out_j']+=energy
            row={'allocation_id':'spill/'+event['event_id']+'/'+key,'node_id':key,'sink_id':node['spill_sink_id'],'kind':'SPILL','evidence':node['evidence']}
            delivery(row,mass,energy,F(),excess)
        for key,node in nodes.items():
            if F(node_snapshot(node,current[key])['occupied_volume_m3'])>F(node['capacity_m3']):
                raise ValueError('post-transfer phase volume exceeds supplied capacity; no numerical clipping')
        elapsed+=dt
        steps.append({'dt_seconds_exact':str(dt),'end_seconds_exact':str(elapsed),'states_sha256':t.digest(current),
            'end_samples':{key:node_snapshot(nodes[key],current[key]) for key in nodes}})
    rows={}
    for key,node in nodes.items():
        ledger=ledgers[key]; mi=F(start['nodes'][key]['water_mass_kg']); mf=F(current[key]['water_mass_kg']); ei=F(start['nodes'][key]['energy_j']); ef=F(current[key]['energy_j'])
        mass_residual=mi+ledger['external_in_kg']+ledger['internal_in_kg']-ledger['external_out_kg']-ledger['internal_out_kg']-mf
        energy_residual=ei+ledger['external_advected_in_j']+ledger['internal_advected_in_j']+ledger['boundary_heat_j']+ledger['internal_heat_j']-ledger['external_advected_out_j']-ledger['internal_advected_out_j']-ledger['latent_export_j']-ef
        if mass_residual or energy_residual: raise ValueError('finite water/energy accounting failure')
        rows[key]={'start':node_snapshot(node,start['nodes'][key]),'end':node_snapshot(node,current[key]),'ledger':t.plain(dict(ledger,initial_water_kg=mi,final_water_kg=mf,initial_energy_j=ei,final_energy_j=ef,water_residual_kg=mass_residual,energy_residual_j=energy_residual)),
            'liquid_export_volume_m3':str((ledger['external_out_kg']+ledger['internal_out_kg'])/F(node['liquid_density_kg_m3']))}
    state={'schema':STATE_SCHEMA,'network_sha256':start['network_sha256'],'elapsed_seconds':str(F(start['elapsed_seconds'])+duration),'nodes':current,'consumed_event_ids':start['consumed_event_ids']+[event['event_id']]}
    return state,{'event_id':event['event_id'],'status':'MODELLED','start_seconds':start['elapsed_seconds'],'duration_seconds':str(duration),'end_seconds':state['elapsed_seconds'],
        'nodes':rows,'deliveries':t.plain(list(deliveries.values())),'gross_links':t.plain(transfers),'accepted_steps':steps,
        'water_residual_kg':'0','energy_residual_j':'0','advective_representation_absolute_error_j':str(advective_roundoff),
        'forcing_support':'UNIFORM_OVER_EXPLICIT_EVENT_NOT_FLOOD_HYDROGRAPH'}


def run(network,initial,events,*,controls,source_binding_sha256,scenario_id,stop_after=None,resume=None):
    """Replay-bound event continuation; a failed/unknown event is never committed."""
    known=validate_network(network); controls_validate(controls); _hash(source_binding_sha256); t.text(scenario_id)
    event_known=_validate_events(network,events)
    if type(initial) is not dict: raise ValueError('explicit initial state required')
    if known: _state_validate(network,initial)
    total=len(events)
    if stop_after is None: stop_after=total
    if type(stop_after) is not int or not 0<=stop_after<=total: raise ValueError('absolute complete-event cursor required')
    inputs={'network':network,'initial':initial,'events':events,'controls':controls,'source_binding_sha256':source_binding_sha256,'scenario_id':scenario_id}
    input_hash=t.digest(inputs)
    if resume is not None:
        t.fields(resume,('schema','inputs_sha256','source_binding_sha256','state_sha256','state'),'water checkpoint')
        if resume['schema']!=CHECKPOINT_SCHEMA or resume['inputs_sha256']!=input_hash or resume['source_binding_sha256']!=source_binding_sha256 or resume['state_sha256']!=t.digest(resume['state']): raise ValueError('checkpoint input/source/checksum mismatch')
        saved=resume['state']; t.fields(saved,('completed_events','continuing_state','accepted_events'),'checkpoint state')
        cursor=saved['completed_events']
        if type(cursor) is not int or not 0<=cursor<=stop_after: raise ValueError('checkpoint cursor outside requested prefix')
        replay=run(network,initial,events,controls=controls,source_binding_sha256=source_binding_sha256,scenario_id=scenario_id,stop_after=cursor)
        if replay['checkpoint']['state']!=saved: raise ValueError('rehashed checkpoint is not an actual deterministic prefix')
    state=deepcopy(initial); rows=[]; completed=0; failure=None
    already=set(initial.get('consumed_event_ids',[]))
    if any(event['event_id'] in already for event in events): raise ValueError('forcing event already consumed by initial state')
    for i,event in enumerate(events[:stop_after]):
        if failure is not None:
            rows.append({'event_id':event['event_id'],'status':'NOT_ADVANCED_PRIOR_GAP'}); continue
        if not known or not event_known[i]:
            failure='UNKNOWN'; rows.append({'event_id':event['event_id'],'status':'UNKNOWN','reason':'required physical/thermal input is unknown, not zero'}); continue
        try: updated,row=_event(network,state,event,controls,source_binding_sha256)
        except (ValueError,OverflowError,ZeroDivisionError) as error:
            failure='OUTSIDE_APPLICABILITY_OR_NUMERICAL_FAILURE'; rows.append({'event_id':event['event_id'],'status':failure,'reason':str(error),'accepted_event_state':None}); continue
        state=updated; rows.append(row); completed+=1
        for delivery in row['deliveries']: delivery['source_input_sha256']=input_hash
    checkpoint_state={'completed_events':completed,'continuing_state':state,'accepted_events':rows[:completed]}
    checkpoint={'schema':CHECKPOINT_SCHEMA,'inputs_sha256':input_hash,'source_binding_sha256':source_binding_sha256,'state_sha256':t.digest(checkpoint_state),'state':checkpoint_state}
    return {'schema':RESULT_SCHEMA,'status':failure or ('MODELLED' if completed==total else 'STOPPED_AT_EVENT_BOUNDARY'),
        'scenario_id':scenario_id,'source_binding_sha256':source_binding_sha256,'inputs_sha256':input_hash,'inputs':t.plain(inputs),
        'completed_events':completed,'events':rows,'final_state':state if failure is None and completed==total else None,'checkpoint':checkpoint,
        'coupling':'FINITE_RESERVOIR_LIQUID_ICE_CONDUCTANCE_AND_ADVECTED_ENTHALPY_NOT_FROZEN_RICHARDS',
        'production_ready':False,'canon_adopted':False,'temporal_method':'ORDERED_CONSERVATIVE_FIRST_ORDER_SPLIT_REQUIRES_REFINEMENT'}


def duration_above_stage(result,node_id,threshold_stage_m):
    """Resolved endpoint-linear threshold duration, NOT observed hydroperiod.

    Only the completely accepted prefix has support. A missing suffix makes the
    full requested duration UNKNOWN, while preserving the prefix diagnostic.
    """
    if result.get('schema')!=RESULT_SCHEMA: raise ValueError('actual R11 water result required')
    if node_id not in result['inputs']['network']['nodes']: raise ValueError('threshold support not in routed input network')
    threshold=t.number(threshold_stage_m,'explicit inundation threshold datum'); duration=F(); support=F()
    for event in result['events']:
        if event['status']!='MODELLED': break
        if node_id not in event['nodes']: raise ValueError('threshold support not in routed result')
        left=F(event['nodes'][node_id]['start']['stage_m'])
        for step in event['accepted_steps']:
            dt=F(step['dt_seconds_exact']); right=F(step['end_samples'][node_id]['stage_m']); support+=dt
            if left>threshold and right>threshold: duration+=dt
            elif left<=threshold and right>threshold: duration+=dt*(right-threshold)/(right-left)
            elif left>threshold and right<=threshold: duration+=dt*(left-threshold)/(left-right)
            left=right
    return {'schema':'diadem.resolved-stage-duration.r11','status':'MODELLED_CONDITIONAL_INTERPOLATED' if result['status']=='MODELLED' else 'UNKNOWN_FULL_INTERVAL',
        'node_id':node_id,'threshold_stage_m':str(threshold),'duration_above_seconds':str(duration),'supported_seconds':str(support),
        'source_input_sha256':result['inputs_sha256'],'interpolation':'LINEAR_BETWEEN_ACCEPTED_STEP_ENDPOINTS_REQUIRES_TEMPORAL_REFINEMENT',
        'observed_hydroperiod':False,'flood_return_period':None}


def reference_spec(event_rows,initial_surface_volume_m3_by_cell):
    """Explicit fictional finite-store case, populated with actual routed inputs.

    event_rows has exact keys event_id,duration_seconds,inflows_m3 (the full cell
    set). The coefficients below define ONLY this named test, not Diadem values.
    Input water is explicitly held at 280 K; imposed bed/air reservoirs cool in
    alternate windows. All boundary heat, runoff and delivery stocks are booked.
    """
    if type(initial_surface_volume_m3_by_cell) is not dict or not initial_surface_volume_m3_by_cell: raise ValueError('explicit source cells required')
    cells=sorted(initial_surface_volume_m3_by_cell)
    if len(cells)>8 or any(k in ('lake','wetland','groundwater') for k in cells): raise ValueError('bounded nonreserved source cell IDs required')
    evidence='Explicit synthetic R11 finite-prism, free-water phase and mobility hypothesis; not owner default or calibrated geography.'
    nodes={}; initial={}
    for key,kind,datum,area,volume in [(key,'CHANNEL',3,100,initial_surface_volume_m3_by_cell[key]) for key in cells]+[
        ('lake','LAKE',1,1000,100),('wetland','WETLAND',0,1000,10),('groundwater','GROUNDWATER',0,1000,100)]:
        cell={'cell_id':key,'solid_heat_capacity_j_k':100000,'liquid_heat_capacity_j_kg_k':4180,
            'ice_heat_capacity_j_kg_k':2100,'latent_heat_j_kg':334000,'freezing_temperature_k':273.15,'evidence':evidence,'source_status':'SYNTHETIC TEST'}
        nodes[key]={'kind':kind,'datum_m':datum,'storage_area_m2':area,'liquid_density_kg_m3':1000,'ice_density_kg_m3':917,
            'capacity_m3':100000,'spill_sink_id':'external-spill/'+key,'thermal':cell,'evidence':evidence,'source_status':'SYNTHETIC TEST'}
        initial[key]=t.initial_cell(cell,t.number(volume,'explicit initial reference volume',nonnegative=True)*1000,280)
    links=[{'link_id':key+'-lake','left':key,'right':'lake','conductance_m2_s':'1/1000000','liquid_fraction_exponent':2,'evidence':evidence} for key in cells]
    links += [{'link_id':'lake-wetland','left':'lake','right':'wetland','conductance_m2_s':'1/1000000','liquid_fraction_exponent':2,'evidence':evidence},
        {'link_id':'groundwater-wetland','left':'groundwater','right':'wetland','conductance_m2_s':'1/1000000','liquid_fraction_exponent':2,'evidence':evidence}]
    network={'schema':SCHEMA,'network_id':'R11_SUPPLIED_THERMAL_PRISM_REFERENCE','nodes':nodes,'links':links,'heat_links':[],
        'evidence':evidence,'source_status':'SYNTHETIC TEST'}
    events=[]
    for i,row in enumerate(event_rows):
        t.fields(row,('event_id','duration_seconds','inflows_m3'),'reference input event')
        if type(row['inflows_m3']) is not dict or set(row['inflows_m3'])!=set(cells): raise ValueError('actual runoff support set mismatch')
        events.append({'event_id':row['event_id'],'duration_seconds':row['duration_seconds'],
            'inflows':[{'allocation_id':row['event_id']+'/runoff/'+key,'node_id':key,'volume_m3':row['inflows_m3'][key],
                'temperature_k':280,'evidence':'Actual parent runoff volume once; inflow temperature 280 K is an independent supplied synthetic hypothesis.'} for key in cells],
            'withdrawals':[{'allocation_id':row['event_id']+'/human-allocation','node_id':'lake','sink_id':'human-reservoir',
                'volume_m3':1,'kind':'ALLOCATION','latent_heat_j_kg':0,'evidence':evidence}],
            'heat_boundaries':{key:{'temperature_k':280 if key=='groundwater' else (260 if i%4<2 else 285),'conductance_w_k':1000,'evidence':evidence} for key in nodes},
            'evidence':'Actual event duration and runoff, uniformly supplied over interval; synthetic thermal boundary and network. '+evidence,'source_status':'SYNTHETIC TEST'})
    duration_min=min((t.number(x['duration_seconds'],'reference event duration',positive=True) for x in event_rows),default=F(1))
    return {'network':network,'initial':initial_state(network,initial),'events':events,
        'controls':{'max_dt_seconds':str(duration_min/4),'stability_fraction':'1/4','max_substeps':10000,'energy_atol_j':'1/100'},
        'evidence':evidence,'groundwater_recharge':'NONE_FROM_INTERNAL_PARENT_DRAINAGE','input_temperature_status':'INDEPENDENT_SYNTHETIC_NOT_SOIL_TEMPERATURE'}
