"""R4 prescribed-port coupling with event-resolved daughter-pool settling."""
from dataclasses import replace
import hashlib
import json
import math
import time

from r3_bindings import capture as r3,verify_predecessor
import event_settling
import phase_storage

CaptureState=r3.CaptureState
CONTRACT=r3.CONTRACT
number=r3.number
vector=r3.vector
total=r3.total
balance=r3.balance
check_controls=r3.check_controls


def route(state,outlets,connectivity):
    return phase_storage.route_phases(list(state.bed_m),list(state.cell_area_m2),list(state.shape),outlets,
        list(state.liquid_m3),list(state.suspended_solid_m3),connectivity=connectivity)


def from_route(state,routed):
    return replace(state,liquid_m3=tuple(routed['liquid_m3']),suspended_solid_m3=tuple(routed['suspended_solid_m3']))


def step(state,*,outlets,connectivity,liquid_input_m3,suspended_input_m3,bed_input_solid_m3,
         settling_m_year,elapsed_years,source_label):
    if not isinstance(state,CaptureState):raise ValueError('bound capture state required')
    if not isinstance(source_label,str) or not source_label.startswith('SYNTHETIC '):raise ValueError('explicit synthetic inlet source required')
    dt=number(elapsed_years,'elapsed years',0,True);velocity=number(settling_m_year,'settling',0);n=state.size
    supplied_w=vector(liquid_input_m3,n,'liquid inlet',0)
    supplied_s=vector(suspended_input_m3,n,'suspended inlet',0)
    supplied_b=vector(bed_input_solid_m3,n,'bed-only inlet',0)
    if any(w==0 and s>0 for w,s in zip(supplied_w,supplied_s)):raise ValueError('suspended inlet requires explicit carrier liquid')
    working=replace(state,bed_solid_m3=tuple(total([b,q]) for b,q in zip(state.bed_solid_m3,supplied_b)),
        liquid_m3=tuple(total([w,q]) for w,q in zip(state.liquid_m3,supplied_w)),
        suspended_solid_m3=tuple(total([s,q]) for s,q in zip(state.suspended_solid_m3,supplied_s)))
    routed=route(working,outlets,connectivity);working=from_route(working,routed)
    working,settled=event_settling.settle_components(working,settling_m_year=velocity,elapsed_years=dt,connectivity=connectivity)
    final_routing=route(working,outlets,connectivity);result=from_route(working,final_routing)
    result=replace(result,time_years=number(state.time_years+dt,'advanced time',state.time_years,True))
    exported_w=total([routed['exported_liquid_m3'],final_routing['exported_liquid_m3']])
    exported_s=total([routed['exported_suspended_solid_m3'],final_routing['exported_suspended_solid_m3']])
    water_change=total([*result.liquid_m3,*(-v for v in state.liquid_m3)])
    solid_change=total([*result.bed_solid_m3,*result.suspended_solid_m3,*(-v for v in state.bed_solid_m3),*(-v for v in state.suspended_solid_m3)])
    imported_w=total(supplied_w);imported_s=total([*supplied_s,*supplied_b])
    geometric=total([(after-before)*a for before,after,a in zip(state.bed_m,result.bed_m,state.cell_area_m2)])
    bed_delta=total([*result.bed_solid_m3,*(-v for v in state.bed_solid_m3)])
    representation_bound=total([4*math.ulp(z)*a for z,a in zip(state.bed_m,state.cell_area_m2)])
    if abs(geometric-bed_delta)>1e-9+1e-12*max(abs(geometric),abs(bed_delta))+representation_bound:
        raise ValueError('physical bed differs from conserved deposited solids')
    return result,{'status':'EVENT_RESOLVED_PRESCRIBED_PORT_REFERENCE','from_time_years':state.time_years,'to_time_years':result.time_years,
        'source_label':source_label,'imported_liquid_m3':imported_w,'imported_suspended_solid_m3':total(supplied_s),
        'imported_bed_solid_m3':total(supplied_b),'exported_liquid_m3':exported_w,'exported_suspended_solid_m3':exported_s,
        'ledgers':{'liquid_m3':balance(water_change,imported_w,exported_w),'solid_m3':balance(solid_change,imported_s,exported_s),
                   'rock_derived_kg':balance(solid_change*state.solid_density_kg_m3,imported_s*state.solid_density_kg_m3,
                       exported_s*state.solid_density_kg_m3,'rock_derived_mass_kg')},
        'geometric_bed_change_m3':geometric,'bed_ledger_change_m3':bed_delta,'bed_geometry_residual_m3':geometric-bed_delta,
        'bed_geometry_roundoff_bound_m3':representation_bound,'routing_before_settling':routed,'event_settling':settled,
        'routing_after_settling':final_routing,'shoreline_exchange_implemented':False,'physical_acceptance':False,'production_authorised':False}


def advance(state,*,steps,dt_years,outlets,connectivity,liquid_input_m3_year,suspended_input_m3_year,
            bed_input_solid_m3_year,settling_m_year,source_label,wall_seconds=120,constraints=None):
    if not isinstance(state,CaptureState):raise ValueError('bound capture state required')
    if type(steps) is not int or not 1<=steps<=CONTRACT['maximum_steps'] or steps*state.size>CONTRACT['maximum_cell_steps']:
        raise ValueError('step/cell-step envelope exceeded')
    if type(wall_seconds) is not int or not 1<=wall_seconds<=CONTRACT['maximum_wall_seconds']:raise ValueError('invalid wall envelope')
    dt=number(dt_years,'dt',0,True);deadline=time.monotonic()+wall_seconds
    forcing={key:vector(value,state.size,key,0) for key,value in {
        'liquid_input_m3':liquid_input_m3_year,'suspended_input_m3':suspended_input_m3_year,'bed_input_solid_m3':bed_input_solid_m3_year}.items()}
    volumes={key:[number(v*dt,key,0) for v in values] for key,values in forcing.items()}
    if any(v>0 and a==0 for key,values in forcing.items() for v,a in zip(values,volumes[key])):raise ValueError('positive inlet underflow')
    controls=[] if constraints is None else constraints
    check_controls(state,controls);initial=state;records=[];export_w=[];export_s=[]
    for i in range(steps):
        if time.monotonic()>deadline:raise ValueError('capture wall envelope exceeded')
        state,record=step(state,outlets=outlets,connectivity=connectivity,settling_m_year=settling_m_year,
                           elapsed_years=dt,source_label=source_label,**volumes)
        record['physical_bed_controls']=check_controls(state,controls)
        record['topology_sha256']=hashlib.sha256(json.dumps(record['routing_after_settling']['topology'],sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
        export_w.append(record['exported_liquid_m3']);export_s.append(record['exported_suspended_solid_m3'])
        record['split_events']=[{**event,'absolute_time_years':record['from_time_years']+event['time_years']} for event in record['event_settling']['events']]
        records.append(record if i==steps-1 else {k:v for k,v in record.items() if k not in {'routing_before_settling','routing_after_settling','event_settling'}})
        if time.monotonic()>deadline:raise ValueError('capture wall envelope exceeded after step')
    dw=total([*state.liquid_m3,*(-v for v in initial.liquid_m3)])
    ds=total([*state.bed_solid_m3,*state.suspended_solid_m3,*(-v for v in initial.bed_solid_m3),*(-v for v in initial.suspended_solid_m3)])
    return state,{'steps':records,'liquid_ledger':balance(dw,total(volumes['liquid_input_m3'])*steps,total(export_w)),
                  'solid_ledger':balance(ds,total([*volumes['suspended_input_m3'],*volumes['bed_input_solid_m3']])*steps,total(export_s)),
                  'physical_acceptance':False,'production_authorised':False,'shoreline_exchange_implemented':False}
