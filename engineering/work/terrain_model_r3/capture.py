"""Persistent two-phase, moving-bed reference with prescribed inlet ports.

No dry-channel/shoreline approximation is hidden here. Frozen R2 remains intact.
"""
from dataclasses import dataclass, replace
import hashlib
import json
import math
from pathlib import Path
import time

import phase_storage
import settling

HERE=Path(__file__).resolve().parent
CONTRACT_BYTES=(HERE/"CAPTURE_NUMERICAL_CONTRACT.json").read_bytes()
CONTRACT_SHA256="a806d8062b685123030227466e74e3b82b7a098b2de90ae196e44b89ce2da7a4"
if hashlib.sha256(CONTRACT_BYTES).hexdigest()!=CONTRACT_SHA256:raise ValueError("frozen capture numerical contract changed")
CONTRACT=json.loads(CONTRACT_BYTES)


def number(value,name,minimum=None,positive=False):
    if type(value) not in (int,float):raise ValueError(name+": numeric scalar required")
    try:value=float(value)
    except (ValueError,OverflowError) as exc:raise ValueError(name+": unrepresentable scalar") from exc
    if not math.isfinite(value) or minimum is not None and (value<=minimum if positive else value<minimum):
        raise ValueError(name+": outside finite supported range")
    return value


def vector(values,n,name,minimum=None,positive=False):
    if type(values) not in (list,tuple) or len(values)!=n:raise ValueError(name+": complete native field required")
    return tuple(number(v,name,minimum,positive) for v in values)


def total(values):
    try:return number(math.fsum(values),"sum")
    except OverflowError as exc:raise ValueError("sum exceeds finite range") from exc


def balance(change,imported,exported,contract="phase_volume_m3"):
    residual=total([change,-imported,exported]);scale=max(abs(change),imported,exported)
    limits=CONTRACT[contract];tolerance=limits["atol"]+limits["rtol"]*scale
    if abs(residual)>tolerance:raise ValueError("combined "+contract+" budget does not close")
    return {"residual":residual,"tolerance":tolerance,"scale":scale}


@dataclass(frozen=True)
class CaptureState:
    shape: tuple
    cell_area_m2: tuple
    bedrock_m: tuple
    bed_solid_m3: tuple
    liquid_m3: tuple
    suspended_solid_m3: tuple
    solid_density_kg_m3: float=2700.
    water_density_kg_m3: float=1000.
    time_years: float=0.
    frame: str="synthetic_native_cells"
    vertical_datum: str="synthetic_relative_m"
    source_status: str="WORKING NON-CANON SYNTHETIC"

    def __post_init__(self):
        if type(self.shape) not in (list,tuple) or len(self.shape)!=2 or any(type(v) is not int or v<1 for v in self.shape):
            raise ValueError("two positive native grid dimensions required")
        object.__setattr__(self,"shape",tuple(self.shape))
        if self.size>CONTRACT["maximum_cells"]:raise ValueError("capture cell envelope exceeded")
        for name,minimum,positive in (("cell_area_m2",0,True),("bedrock_m",None,False),
                ("bed_solid_m3",0,False),("liquid_m3",0,False),("suspended_solid_m3",0,False)):
            object.__setattr__(self,name,vector(getattr(self,name),self.size,name,minimum,positive))
        for name in ("solid_density_kg_m3","water_density_kg_m3"):
            object.__setattr__(self,name,number(getattr(self,name),name,0,True))
        if self.solid_density_kg_m3<=self.water_density_kg_m3:raise ValueError("this settling reference requires negatively buoyant mineral grains")
        object.__setattr__(self,"time_years",number(self.time_years,"time_years",0))
        if self.frame!="synthetic_native_cells" or self.vertical_datum!="synthetic_relative_m" or self.source_status!="WORKING NON-CANON SYNTHETIC":
            raise ValueError("this reference has no real-domain/canon input authority")
        if any(w==0 and s>0 for w,s in zip(self.liquid_m3,self.suspended_solid_m3)):
            raise ValueError("dry suspended material needs an explicit emplacement model")
        vector(self.bed_m,self.size,"physical bed")
        total(self.liquid_m3);total(self.suspended_solid_m3);total(self.bed_solid_m3)

    @property
    def size(self):return self.shape[0]*self.shape[1]

    @property
    def bed_m(self):return tuple(b+v/a for b,v,a in zip(self.bedrock_m,self.bed_solid_m3,self.cell_area_m2))

    def as_dict(self):
        return {name:list(value) if isinstance(value,tuple) else value for name,value in self.__dict__.items()}


def _route(state,outlets,connectivity):
    return phase_storage.route_phases(list(state.bed_m),list(state.cell_area_m2),list(state.shape),outlets,
        list(state.liquid_m3),list(state.suspended_solid_m3),connectivity=connectivity)


def _from_route(state,routed):
    return replace(state,liquid_m3=tuple(routed["liquid_m3"]),suspended_solid_m3=tuple(routed["suspended_solid_m3"]))


def check_controls(state,controls):
    if type(controls) is not list or len(controls)>state.size:raise ValueError("bounded explicit control list required")
    seen=set();residuals=[]
    for row in controls:
        if type(row) is not dict or set(row)!={"id","cell","minimum_m","maximum_m","source_status","source_label"}:
            raise ValueError("incomplete synthetic control provenance")
        if not isinstance(row["id"],str) or not row["id"] or row["id"] in seen:raise ValueError("unique control ID required")
        seen.add(row["id"])
        i=row["cell"]
        if type(i) is not int or not 0<=i<state.size:raise ValueError("control cell outside native grid")
        if row["source_status"]!="WORKING NON-CANON SYNTHETIC" or not isinstance(row["source_label"],str) or not row["source_label"]:
            raise ValueError("synthetic control authority required")
        lo=number(row["minimum_m"],"minimum");hi=number(row["maximum_m"],"maximum")
        if lo>hi or not lo<=state.bed_m[i]<=hi:raise ValueError("CONFLICT physical-bed control:"+row["id"])
        residuals.append({"id":row["id"],"bed_m":state.bed_m[i],"distance_from_lower_m":state.bed_m[i]-lo,"distance_from_upper_m":hi-state.bed_m[i]})
    return residuals


def require_connected_wet_cells(cells,shape,connectivity):
    """A zero-depth saddle is not a liquid connection, even at an equal sill."""
    wet=set(cells)
    if not wet:return
    rows,cols=shape;pending=[min(wet)];visited=set(pending)
    offsets=((-1,0),(1,0),(0,-1),(0,1))
    if connectivity==8:offsets+=((-1,-1),(-1,1),(1,-1),(1,1))
    while pending:
        i=pending.pop();r,c=divmod(i,cols)
        for dr,dc in offsets:
            rr,cc=r+dr,c+dc;j=rr*cols+cc
            if 0<=rr<rows and 0<=cc<cols and j in wet and j not in visited:
                visited.add(j);pending.append(j)
    if visited!=wet:
        raise ValueError("unsupported disconnected wet pool: drying saddle requires daughter-pool integration")


def step(state,*,outlets,connectivity,liquid_input_m3,suspended_input_m3,bed_input_solid_m3,
         settling_m_year,elapsed_years,source_label):
    """Import once, route mixed phases, settle, then rebuild actual geometry.

    Sources are explicit prescribed ports, not calculated channel discharge.
    Spatial phase stores persist; pool labels are derived and disposable.
    """
    if not isinstance(state,CaptureState):raise ValueError("validated capture state required")
    if not isinstance(source_label,str) or not source_label.startswith("SYNTHETIC "):
        raise ValueError("explicit synthetic input/load-partition source label required")
    dt=number(elapsed_years,"elapsed_years",0,True)
    velocity=number(settling_m_year,"effective settling velocity",0)
    n=state.size
    supplied_w=vector(liquid_input_m3,n,"liquid port volume",0)
    supplied_s=vector(suspended_input_m3,n,"suspended port solid volume",0)
    supplied_b=vector(bed_input_solid_m3,n,"external bed-only solid volume",0)
    if any(w==0 and s>0 for w,s in zip(supplied_w,supplied_s)):
        raise ValueError("suspended inlet requires its explicitly accounted carrier liquid")
    working=replace(state,bed_solid_m3=tuple(total([b,q]) for b,q in zip(state.bed_solid_m3,supplied_b)),
        liquid_m3=tuple(total([w,q]) for w,q in zip(state.liquid_m3,supplied_w)),
        suspended_solid_m3=tuple(total([s,q]) for s,q in zip(state.suspended_solid_m3,supplied_s)))
    routed=_route(working,outlets,connectivity);working=_from_route(working,routed)
    mobile=list(working.bed_solid_m3);liquid=list(working.liquid_m3);suspended=list(working.suspended_solid_m3)
    pool_records=[];seen=set()
    for pool in routed["active_pools"]:
        cells=pool["cell_indices"]
        if any(i in seen for i in cells):raise ValueError("pool footprints duplicate durable phase ownership")
        seen.update(cells)
        if velocity>0 and pool["suspended_solid_m3"]>0:
            require_connected_wet_cells(pool["wet_cell_indices"],state.shape,connectivity)
        remaining=dt;events=[];pool_water=pool["liquid_m3"];pool_solid=pool["suspended_solid_m3"]
        for event_index in range(len(cells)+1):
            actual_bed=[working.bedrock_m[i]+mobile[i]/working.cell_area_m2[i] for i in cells]
            result=settling.settle_pool(actual_bed,[working.cell_area_m2[i] for i in cells],
                pool_water,pool_solid,velocity,remaining,stop_at_first_drying_event=True)
            for j,i in enumerate(cells):
                mobile[i]=total([mobile[i],result["deposited_solid_m3"][j]])
                liquid[i]=result["liquid_by_cell_m3"][j];suspended[i]=result["suspended_by_cell_m3"][j]
            events.append(result)
            if result["stopped_at_drying_event"]:
                # Check the actual durable rock+sediment bed, not a separately
                # rounded stage-snapped display bed. Never continue through a
                # physically disconnected saddle using one concentration.
                wet=[i for i in cells if working.bedrock_m[i]+mobile[i]/working.cell_area_m2[i]<result["stage_m"]]
                intended=[i for i,h in zip(cells,result["depth_m"]) if h>0]
                if wet!=intended:raise ValueError("drying event wet connectivity is unrepresentable in durable bed state")
                require_connected_wet_cells(wet,state.shape,connectivity)
            if result["remaining_years"]==0:break
            if not 0<result["elapsed_years"]<=remaining or result["remaining_years"]>=remaining:
                raise ValueError("drying event does not make representable time progress")
            remaining=result["remaining_years"];pool_water=result["liquid_m3"];pool_solid=result["suspended_solid_m3"]
        else:raise ValueError("bounded pool drying-event integration exhausted")
        pool_records.append({"pool_id":pool["id"],"cell_indices":cells,"settling":result,"settling_intervals":events})
    working=replace(working,bed_solid_m3=tuple(mobile),liquid_m3=tuple(liquid),suspended_solid_m3=tuple(suspended))
    final_routing=_route(working,outlets,connectivity)
    result=_from_route(working,final_routing)
    result=replace(result,time_years=number(state.time_years+dt,"advanced time",state.time_years,True))
    exported_w=total([routed["exported_liquid_m3"],final_routing["exported_liquid_m3"]])
    exported_s=total([routed["exported_suspended_solid_m3"],final_routing["exported_suspended_solid_m3"]])
    water_change=total([*result.liquid_m3,*(-v for v in state.liquid_m3)])
    solid_change=total([*result.bed_solid_m3,*result.suspended_solid_m3,*(-v for v in state.bed_solid_m3),*(-v for v in state.suspended_solid_m3)])
    imported_w=total(supplied_w);imported_s=total([*supplied_s,*supplied_b])
    ledgers={"liquid_m3":balance(water_change,imported_w,exported_w),
        "solid_m3":balance(solid_change,imported_s,exported_s),
        "rock_derived_kg":balance(solid_change*state.solid_density_kg_m3,imported_s*state.solid_density_kg_m3,
                                  exported_s*state.solid_density_kg_m3,"rock_derived_mass_kg")}
    geometry_loss=total([(after-before)*a for before,after,a in zip(state.bed_m,result.bed_m,state.cell_area_m2)])
    bed_ledger_change=total([*result.bed_solid_m3,*(-v for v in state.bed_solid_m3)])
    representation_bound=total([4*math.ulp(z)*a for z,a in zip(state.bed_m,state.cell_area_m2)])
    if abs(geometry_loss-bed_ledger_change)>1e-9+1e-12*max(abs(geometry_loss),abs(bed_ledger_change))+representation_bound:
        raise ValueError("physical bed movement differs from conserved deposited solids")
    return result,{"status":"PRESCRIBED_PORT_CAPTURE_REFERENCE_ONLY","from_time_years":state.time_years,
        "to_time_years":result.time_years,"source_label":source_label,
        "imported_liquid_m3":imported_w,"imported_suspended_solid_m3":total(supplied_s),
        "imported_bed_solid_m3":total(supplied_b),"exported_liquid_m3":exported_w,"exported_suspended_solid_m3":exported_s,
        "ledgers":ledgers,"geometric_bed_change_m3":geometry_loss,"bed_ledger_change_m3":bed_ledger_change,
        "bed_geometry_residual_m3":geometry_loss-bed_ledger_change,"bed_geometry_roundoff_bound_m3":representation_bound,
        "routing_before_settling":routed,"settling_pools":pool_records,"routing_after_settling":final_routing,
        "dry_channel_shoreline_coupling_solved":False,"production_authorised":False}


def advance(state,*,steps,dt_years,outlets,connectivity,liquid_input_m3_year,suspended_input_m3_year,
            bed_input_solid_m3_year,settling_m_year,source_label,wall_seconds=120,constraints=None):
    if not isinstance(state,CaptureState):raise ValueError("validated capture state required")
    if type(steps) is not int or not 1<=steps<=CONTRACT["maximum_steps"] or steps*state.size>CONTRACT["maximum_cell_steps"]:
        raise ValueError("bounded step/cell-step envelope exceeded")
    if type(wall_seconds) is not int or not 1<=wall_seconds<=CONTRACT["maximum_wall_seconds"]:raise ValueError("invalid wall-time envelope")
    dt=number(dt_years,"dt_years",0,True);deadline=time.monotonic()+wall_seconds
    forcing={key:vector(value,state.size,key,0) for key,value in {
        "liquid_input_m3":liquid_input_m3_year,"suspended_input_m3":suspended_input_m3_year,"bed_input_solid_m3":bed_input_solid_m3_year}.items()}
    volumes={key:[number(v*dt,key,0) for v in values] for key,values in forcing.items()}
    if any(v>0 and amount==0 for key,values in forcing.items() for v,amount in zip(values,volumes[key])):
        raise ValueError("positive forcing volume underflows at this timestep")
    initial=state;records=[];exports_w=[];exports_s=[]
    constraints=[] if constraints is None else constraints
    check_controls(state,constraints)
    for i in range(steps):
        if time.monotonic()>deadline:raise ValueError("bounded capture time exceeded")
        state,record=step(state,outlets=outlets,connectivity=connectivity,settling_m_year=settling_m_year,
                          elapsed_years=dt,source_label=source_label,**volumes)
        record["physical_bed_controls"]=check_controls(state,constraints)
        exports_w.append(record["exported_liquid_m3"]);exports_s.append(record["exported_suspended_solid_m3"])
        record["topology_sha256"]=hashlib.sha256(json.dumps(record["routing_after_settling"]["topology"],sort_keys=True,separators=(",",":"),allow_nan=False).encode()).hexdigest()
        # Full current state is durable; past large graph/array snapshots are
        # not required to retain independent per-step phase/bed ledgers.
        records.append(record if i==steps-1 else {k:v for k,v in record.items() if k not in {"routing_before_settling","routing_after_settling","settling_pools"}})
        if time.monotonic()>deadline:raise ValueError("bounded capture time exceeded after step")
    delta_w=total([*state.liquid_m3,*(-v for v in initial.liquid_m3)])
    delta_s=total([*state.bed_solid_m3,*state.suspended_solid_m3,*(-v for v in initial.bed_solid_m3),*(-v for v in initial.suspended_solid_m3)])
    return state,{"steps":records,"liquid_ledger":balance(delta_w,total(volumes["liquid_input_m3"])*steps,total(exports_w)),
        "solid_ledger":balance(delta_s,total([*volumes["suspended_input_m3"],*volumes["bed_input_solid_m3"]])*steps,total(exports_s)),
        "production_authorised":False,"physical_acceptance":False,"shoreline_capture_acceptance":False}
