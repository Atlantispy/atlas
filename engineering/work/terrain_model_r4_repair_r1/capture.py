"""R4 prescribed-port coupling with event-resolved daughter-pool settling."""
from dataclasses import dataclass, replace
from fractions import Fraction
import hashlib
import json
import math
import time

from r3_bindings import capture as r3,verify_predecessor
import event_settling
import phase_storage

@dataclass(frozen=True)
class CaptureState(r3.CaptureState):
    """R3-compatible state with optional exact pure-liquid float residuals.

    W is the represented store; logical W is W plus its canonical rational.
    No new material/terrain authority is inferred. Nonzero residual-bearing
    suspension is unsupported until every phase operator can transport it.
    """
    liquid_remainder_m3: tuple = None

    def __post_init__(self):
        super().__post_init__()
        residuals = phase_storage.liquid_remainders(self.liquid_m3, self.liquid_remainder_m3)
        if any(residuals) and any(self.suspended_solid_m3):
            raise ValueError('nonzero liquid remainder with suspension requires exact phase transport')
        object.__setattr__(self, 'liquid_remainder_m3', tuple(tuple(phase_storage.ratio(v)) for v in residuals))

    def as_dict(self):
        result = super().as_dict()
        # Historical zero-residual checkpoint shape stays byte-compatible.
        if any(n for n,d in self.liquid_remainder_m3):
            result['liquid_remainder_m3'] = [list(v) for v in self.liquid_remainder_m3]
        else:
            result.pop('liquid_remainder_m3')
        return result
CONTRACT=r3.CONTRACT
number=r3.number
vector=r3.vector
total=r3.total
balance=r3.balance
check_controls=r3.check_controls


def exact_liquid(state):
    residuals=phase_storage.liquid_remainders(state.liquid_m3,getattr(state,'liquid_remainder_m3',None))
    return sum((Fraction(w)+r for w,r in zip(state.liquid_m3,residuals)),Fraction())


def route(state,outlets,connectivity,*,exact_liquid_routing=False):
    return phase_storage.route_phases(list(state.bed_m),list(state.cell_area_m2),list(state.shape),outlets,
        list(state.liquid_m3),list(state.suspended_solid_m3),connectivity=connectivity,
        liquid_remainder_m3=getattr(state,'liquid_remainder_m3',None),exact_liquid=exact_liquid_routing)


def from_route(state,routed):
    return replace(state,liquid_m3=tuple(routed['liquid_m3']),suspended_solid_m3=tuple(routed['suspended_solid_m3']),
                   liquid_remainder_m3=routed['liquid_remainder_m3'])


def step(state,*,outlets,connectivity,liquid_input_m3,suspended_input_m3,bed_input_solid_m3,
         settling_m_year,elapsed_years,source_label):
    if not isinstance(state,CaptureState):raise ValueError('bound capture state required')
    if not isinstance(source_label,str) or not source_label.startswith('SYNTHETIC '):raise ValueError('explicit synthetic inlet source required')
    dt=number(elapsed_years,'elapsed years',0,True);velocity=number(settling_m_year,'settling',0);n=state.size
    supplied_w=vector(liquid_input_m3,n,'liquid inlet',0)
    supplied_s=vector(suspended_input_m3,n,'suspended inlet',0)
    supplied_b=vector(bed_input_solid_m3,n,'bed-only inlet',0)
    if any(w==0 and s>0 for w,s in zip(supplied_w,supplied_s)):raise ValueError('suspended inlet requires explicit carrier liquid')
    pure_liquid=not any((*state.suspended_solid_m3,*supplied_s))
    residuals=phase_storage.liquid_remainders(state.liquid_m3,state.liquid_remainder_m3)
    if any(residuals) and not pure_liquid:
        raise ValueError('nonzero liquid remainder with suspension requires exact phase transport')
    exact_added=[Fraction(w)+r+Fraction(q) for w,r,q in zip(state.liquid_m3,residuals,supplied_w)]
    water=tuple(number(float(v),'combined liquid',0) for v in exact_added) if pure_liquid else tuple(total([w,q]) for w,q in zip(state.liquid_m3,supplied_w))
    remainders=[phase_storage.ratio(v-Fraction(w)) for v,w in zip(exact_added,water)] if pure_liquid else [[0,1]]*n
    working=replace(state,bed_solid_m3=tuple(total([b,q]) for b,q in zip(state.bed_solid_m3,supplied_b)),
        liquid_m3=water,liquid_remainder_m3=remainders,
        suspended_solid_m3=tuple(total([s,q]) for s,q in zip(state.suspended_solid_m3,supplied_s)))
    routed=route(working,outlets,connectivity,exact_liquid_routing=pure_liquid);working=from_route(working,routed)
    working,settled=event_settling.settle_components(working,settling_m_year=velocity,elapsed_years=dt,connectivity=connectivity)
    final_routing=route(working,outlets,connectivity,exact_liquid_routing=pure_liquid);result=from_route(working,final_routing)
    result=replace(result,time_years=number(state.time_years+dt,'advanced time',state.time_years,True))
    exported_w=total([routed['exported_liquid_m3'],final_routing['exported_liquid_m3']])
    exported_s=total([routed['exported_suspended_solid_m3'],final_routing['exported_suspended_solid_m3']])
    exact_export=sum((Fraction(r['exported_liquid_m3'])+Fraction(*r['exported_liquid_remainder_m3']) for r in (routed,final_routing)),Fraction())
    export_remainder=exact_export-Fraction(exported_w)
    exact_residual=exact_liquid(result)-exact_liquid(state)-sum(map(Fraction,supplied_w),Fraction())+exact_export
    if pure_liquid and exact_residual:
        raise ValueError('exact durable liquid step ledger failed')
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
        'exported_liquid_remainder_m3':phase_storage.ratio(export_remainder),
        'exact_liquid_ledger':{'checked':pure_liquid,'residual_m3':phase_storage.ratio(exact_residual)},
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
    exact_export=sum((Fraction(r['exported_liquid_m3'])+Fraction(*r['exported_liquid_remainder_m3']) for r in records),Fraction())
    exact_import=sum(map(Fraction,volumes['liquid_input_m3']),Fraction())*steps
    exact_residual=exact_liquid(state)-exact_liquid(initial)-exact_import+exact_export
    exact_checked=all(r['exact_liquid_ledger']['checked'] for r in records)
    if exact_checked and exact_residual:raise ValueError('exact durable liquid advance ledger failed')
    return state,{'steps':records,'liquid_ledger':balance(dw,total(volumes['liquid_input_m3'])*steps,total(export_w)),
                  'exported_liquid_remainder_m3':phase_storage.ratio(exact_export-Fraction(total(export_w))),
                  'exact_liquid_ledger':{'checked':exact_checked,'residual_m3':phase_storage.ratio(exact_residual)},
                  'solid_ledger':balance(ds,total([*volumes['suspended_input_m3'],*volumes['bed_input_solid_m3']])*steps,total(export_s)),
                  'physical_acceptance':False,'production_authorised':False,'shoreline_exchange_implemented':False}
