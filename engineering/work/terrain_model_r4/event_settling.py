"""Conservative event-driven closed settling through native pool separation."""
from dataclasses import replace
import math
import time

from r3_bindings import capture as base,settling


def wet_components(cells,shape,connectivity):
    if type(connectivity) is not int or connectivity not in (4,8):raise ValueError('explicit4/8 connectivity required')
    rows,cols=shape
    if any(type(i) is not int or not 0<=i<rows*cols for i in cells) or len(set(cells))!=len(cells):raise ValueError('invalid native component cells')
    remaining=set(cells);components=[]
    offsets=((-1,0),(1,0),(0,-1),(0,1))
    if connectivity==8:offsets+=((-1,-1),(-1,1),(1,-1),(1,1))
    while remaining:
        seed=min(remaining);remaining.remove(seed);pending=[seed];found=[seed]
        while pending:
            i=pending.pop();r,c=divmod(i,cols)
            for dr,dc in offsets:
                rr,cc=r+dr,c+dc;j=rr*cols+cc
                if 0<=rr<rows and 0<=cc<cols and j in remaining:
                    remaining.remove(j);pending.append(j);found.append(j)
        components.append(sorted(found))
    return components


def settle_components(state,*,settling_m_year,elapsed_years,connectivity=4,wall_seconds=120):
    """State must already be routed, with positive-depth connected level pools.

    No inflow/export/erosion, no input mutation. Cell stores survive topology
    changes. All descendants advance to the same final accounting time.
    """
    if not isinstance(state,base.CaptureState):raise ValueError('bound R3-compatible capture state required')
    velocity=base.number(settling_m_year,'settling velocity',0)
    duration=base.number(elapsed_years,'elapsed years',0)
    wall=base.number(wall_seconds,'wall seconds',0,True)
    if wall>120:raise ValueError('wall envelope exceeds120 seconds')
    deadline=time.monotonic()+wall;n=state.size
    wet=[i for i,(w,s) in enumerate(zip(state.liquid_m3,state.suspended_solid_m3)) if w+s>0]
    components=wet_components(wet,state.shape,connectivity)
    # Adjacent wet cells must share a level and concentration in this supplied
    # initial-state closure. Do not repair or silently mix an unrouted state.
    for cells in components:
        eta=[state.bed_m[i]+(state.liquid_m3[i]+state.suspended_solid_m3[i])/state.cell_area_m2[i] for i in cells]
        volume=base.total(state.liquid_m3[i]+state.suspended_solid_m3[i] for i in cells)
        concentration=base.total(state.suspended_solid_m3[i] for i in cells)/volume
        if max(eta)-min(eta)>base.CONTRACT['geometry_m']['atol']+base.CONTRACT['geometry_m']['rtol']*max(map(abs,eta)):
            raise ValueError('initial wet component is not a routed level pool')
        for i in cells:
            expected=concentration*(state.liquid_m3[i]+state.suspended_solid_m3[i])
            actual=state.suspended_solid_m3[i]
            if abs(actual-expected)>base.CONTRACT['phase_volume_m3']['atol']+base.CONTRACT['phase_volume_m3']['rtol']*max(actual,expected):
                raise ValueError('initial wet component is not well mixed')
    mobile=list(state.bed_solid_m3);water=list(state.liquid_m3);solid=list(state.suspended_solid_m3)
    stack=[] if duration==0 or velocity==0 or not any(solid) else [(cells,0.,duration,None) for cells in reversed(components)]
    records=[];events=[];calls=visits=0
    while stack:
        if time.monotonic()>deadline:raise ValueError('event settling wall envelope exceeded')
        cells,start,remaining,parent=stack.pop();calls+=1;visits+=len(cells)
        if calls>4*n or visits>262144:raise ValueError('event settling call/cell-visit envelope exceeded')
        bed=[state.bedrock_m[i]+mobile[i]/state.cell_area_m2[i] for i in cells]
        w=base.total(water[i] for i in cells);s=base.total(solid[i] for i in cells)
        outcome=settling.settle_pool(bed,[state.cell_area_m2[i] for i in cells],w,s,velocity,remaining,
                                    stop_at_first_drying_event=True)
        record_id=len(records)
        for j,i in enumerate(cells):
            mobile[i]=base.total([mobile[i],outcome['deposited_solid_m3'][j]])
            water[i]=outcome['liquid_by_cell_m3'][j];solid[i]=outcome['suspended_by_cell_m3'][j]
        end=base.total([start,outcome['elapsed_years']])
        records.append({'id':record_id,'parent_interval':parent,'cell_indices':cells,'start_years':start,
                        'end_years':end,'settling':outcome})
        if outcome['stopped_at_drying_event']:
            actual_wet=[i for i in cells if state.bedrock_m[i]+mobile[i]/state.cell_area_m2[i]<outcome['stage_m']]
            intended=[i for i,h in zip(cells,outcome['depth_m']) if h>0]
            if actual_wet!=intended:raise ValueError('event wet geometry is unrepresentable in durable B state')
            daughters=wet_components(actual_wet,state.shape,connectivity)
            if any((water[i]!=0 or solid[i]!=0) for i in set(cells)-set(actual_wet)):
                raise ValueError('dried cell retains unsupported suspended/liquid phase')
            transfer=[{'cell_indices':d,'liquid_m3':base.total(water[i] for i in d),
                       'suspended_solid_m3':base.total(solid[i] for i in d)} for d in daughters]
            w_after=base.total(row['liquid_m3'] for row in transfer)
            s_after=base.total(row['suspended_solid_m3'] for row in transfer)
            base.balance(w_after-w,0.,0.)
            base.balance(base.total([s_after,*outcome['deposited_solid_m3'],-s]),0.,0.)
            events.append({'time_years':end,'parent_interval':record_id,'parent_cells':cells,
                           'dried_cells':sorted(set(cells)-set(actual_wet)),'daughters':transfer,
                           'split':len(daughters)>1})
            if outcome['remaining_years']>0:
                if not 0<outcome['elapsed_years']<=remaining or outcome['remaining_years']>=remaining:
                    raise ValueError('drying event makes no representable progress')
                for daughter in reversed(daughters):stack.append((daughter,end,outcome['remaining_years'],record_id))
        elif outcome['remaining_years']!=0:raise ValueError('solver stopped without a drying event')
    result=replace(state,bed_solid_m3=tuple(mobile),liquid_m3=tuple(water),suspended_solid_m3=tuple(solid))
    delta_w=base.total([*water,*(-v for v in state.liquid_m3)])
    delta_s=base.total([*solid,*mobile,*(-v for v in state.suspended_solid_m3),*(-v for v in state.bed_solid_m3)])
    if time.monotonic()>deadline:raise ValueError('event settling wall envelope exceeded after update')
    return result,{'status':'EVENT_RESOLVED_CLOSED_POOL_SETTLING_ONLY','duration_years':duration,
                   'intervals':records,'events':sorted(events,key=lambda row:(row['time_years'],row['parent_cells'])),
                   'initial_components':components,'solver_calls':calls,'cell_visits':visits,
                   'liquid_ledger':base.balance(delta_w,0.,0.),'solid_ledger':base.balance(delta_s,0.,0.),
                   'shoreline_exchange_implemented':False,'physical_acceptance':False,'production_authorised':False}
