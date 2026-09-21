"""W02 conservative regridding and prescribed moving-control-volume evolution.

Accuracy-first: piecewise-linear limited overlap integration; MC/SSP-RK2 ALE.
No interpolation of IDs/ages, repair by renormalisation, density/force prediction,
or implicit lowering of accuracy. Pure regridding cannot change domain extent.
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
import hashlib
import math
import numpy as np
from ._validation import TectonicsError, input_shape, snapshot, frozen, scalar
from .resources import select_budget, MemoryLimitError
from .regional import RegionalGrid1D, _cancelled, _METRICS
from .mesh import ColumnGrid1D
from .materials import (MaterialState, MaterialBoundary, MaterialTransportResult,
    _json, _immutable_bytes, _hash_array, _account, _backend, _end_time, _state_work_bytes)


def _mesh_state(state):
    if type(state) is not MaterialState or type(state.grid) is not ColumnGrid1D:
        raise TectonicsError('MaterialState on ColumnGrid1D required; use to_column_state explicitly')


def _inventories(h, grid, backend='numba'):
    if backend=='numba':
        from ._mesh_native import inventories
        return inventories(h,grid.edges_m)
    widths=grid.widths_m
    return np.array([math.fsum(float(h[k,i])*float(widths[i]) for i in range(grid.cells))
                     for k in range(h.shape[0])])


def _publish(parent, grid, values, time, record, *, budget=None):
    record=dict(record,parent=parent.state_id)
    return MaterialState(grid,parent.cohorts,values,time_s=time,epoch_id=parent.epoch_id,
        parent_state_id=parent.state_id,transition_id=hashlib.sha256(_json(record)).hexdigest(),
        transition=record,budget=budget)


def to_column_state(state, *, frame_id, budget=None):
    """Explicit uniform-to-edge bridge, conserving each represented cell inventory.

    Actual binary64 edge differences need not equal length/N bit-for-bit. H is
    adjusted by dx/actual_width; this conversion is recorded, never silently done
    inside a transport call. Formation history is unchanged.
    """
    if type(state) is not MaterialState or type(state.grid) is not RegionalGrid1D:
        raise TectonicsError('legacy regional MaterialState required')
    c=len(state.cohorts);n=state.grid.cells
    with select_budget(budget).reserve(40*c*n+128*n+8192,category='uniform-mesh-bridge'):
        g=state.grid
        mesh=ColumnGrid1D(np.linspace(g.origin_m,g.origin_m+g.length_m,n+1),frame_id=frame_id,budget=budget)
        with np.errstate(over='raise',invalid='raise',divide='raise'):
            h=state.thickness_m*(g.spacing_m/mesh.widths_m)
        before=np.array([math.fsum(row)*g.spacing_m for row in state.thickness_m])
        after=_inventories(h,mesh)
        accounts=[_account(float(b),float(a),0.,0.,0.) for b,a in zip(before,after)]
        return _publish(state,mesh,h,state.time_s,{'operation':'uniform-to-columns-v1',
            'new_grid':mesh.grid_id,'cohort_accounts':accounts},budget=budget)


@dataclass(frozen=True,slots=True,init=False)
class RemapPlan:
    """Immutable sparse overlap geometry, reused for any fields on the SAME meshes.

    Geometry storage O(Ns+Nt); no dense interpolation matrix and no result cache.
    Sources/targets have the same extent and frame. Fields/time do not identify
    this operator; each resulting material state still has its own identity.
    """
    source: ColumnGrid1D
    target: ColumnGrid1D
    plan_id: str
    builder_backend: str
    _p: bytes=field(repr=False)
    _d: bytes=field(repr=False)
    _l: bytes=field(repr=False)
    _o: bytes=field(repr=False)

    def __init__(self,source,target,*,backend='numba',budget=None):
        _backend(backend)
        if type(source) is not ColumnGrid1D or type(target) is not ColumnGrid1D:
            raise TectonicsError('explicit source/target column meshes required')
        if source.frame_id!=target.frame_id or not np.array_equal(source.edges_m[[0,-1]],target.edges_m[[0,-1]]):
            raise TectonicsError('remapping must preserve the physical domain and frame; use ALE for moving boundaries')
        with select_budget(budget).reserve(112*(source.cells+target.cells)+8192,category='remap-plan'):
            if backend=='numba':
                from ._mesh_native import overlap_geometry
                p,d,l,o=overlap_geometry(source.edges_m,target.edges_m)
            else:
                x,y=source.edges_m,target.edges_m
                starts=[0];donors=[];lengths=[];offsets=[];i=0
                for j in range(target.cells):
                    while i+1<source.cells and x[i+1]<=y[j]:i+=1
                    q=i
                    while q<source.cells and x[q]<y[j+1]:
                        a=max(x[q],y[j]);b=min(x[q+1],y[j+1])
                        if b>a:
                            donors.append(q);lengths.append(b-a)
                            offsets.append((a-x[q])+.5*(b-a)-.5*(x[q+1]-x[q]))
                        if x[q+1]>=y[j+1]:break
                        q+=1
                    i=q;starts.append(len(donors))
                p=np.asarray(starts,dtype=np.int64);d=np.asarray(donors,dtype=np.int64)
                l=np.asarray(lengths);o=np.asarray(offsets)
            for key,val in (('source',source),('target',target),('_p',p.tobytes()),
                            ('_d',d.tobytes()),('_l',l.tobytes()),('_o',o.tobytes())):
                object.__setattr__(self,key,val)
            object.__setattr__(self,'builder_backend',backend)
            object.__setattr__(self,'plan_id',hashlib.sha256(_json({'method':'interval-overlap-v1',
                        'source':source.grid_id,'target':target.grid_id})).hexdigest())
    @property
    def nbytes(self):return sum(map(len,(self._p,self._d,self._l,self._o)))
    def arrays(self):
        return (np.frombuffer(self._p,np.int64),np.frombuffer(self._d,np.int64),
                np.frombuffer(self._l,np.float64),np.frombuffer(self._o,np.float64))
    def __reduce__(self):return (_restore_plan,(self.source,self.target,self.builder_backend))
    def __deepcopy__(self,memo):memo[id(self)]=self;return self


def _restore_plan(source,target,backend):
    return RemapPlan(source,target,backend=backend)


def _slopes_reference(h,x,linear):
    """Independent scalar reconstruction; endpoints preserve the mean and positivity."""
    n=len(h);out=np.zeros(n)
    if not linear or n==1:return out
    widths=np.diff(x)
    # Adjacent centres are separated by their half widths. Subtracting rounded
    # absolute centres can change that distance under a coordinate translation.
    distances=.5*widths[:-1]+.5*widths[1:]
    for i in range(n):
        if i==0:s=(h[1]-h[0])/distances[0]
        elif i==n-1:s=(h[-1]-h[-2])/distances[-1]
        else:
            dl=distances[i-1];dr=distances[i]
            a=(h[i]-h[i-1])/dl;b=(h[i+1]-h[i])/dr
            if not ((a>0 and b>0) or (a<0 and b<0)):continue
            s=math.copysign(min(abs((a*dr+b*dl)/(dl+dr)),2*abs(a),2*abs(b)),a)
            s=math.copysign(min(abs(s),2*min(abs(h[i]-h[i-1]),abs(h[i+1]-h[i]))/widths[i]),s)
        cap=2*(h[i]/widths[i])
        if abs(s)>=cap and cap>0:cap=math.nextafter(cap,0.)
        out[i]=math.copysign(min(abs(s),cap),s)
    return out


def _remap_reference(h,x,y,linear):
    # Direct interval intersections, not the compiled sparse-plan arrays.
    # This intentionally transparent reference is used for small verification cases.
    c,n=h.shape;out=np.empty((c,len(y)-1))
    for k in range(c):
        slopes=_slopes_reference(h[k],x,linear)
        for j in range(len(y)-1):
            pieces=[]
            start=max(0,int(np.searchsorted(x,y[j],side='right'))-1)
            for i in range(start,n):
                if x[i]>=y[j+1]:break
                lo=max(x[i],y[j]);hi=min(x[i+1],y[j+1])
                if hi>lo:
                    offset=(lo-x[i])+0.5*(hi-lo)-0.5*(x[i+1]-x[i])
                    pieces.append(float((hi-lo)*(h[k,i]+slopes[i]*offset)))
            out[k,j]=math.fsum(pieces)/(y[j+1]-y[j])
    return out


def remap_materials(state, target, *, plan=None, scheme='linear', backend='numba', budget=None,cancel=None):
    """Conservative mesh-only change at identical physical time; no source or sink.

    Limited linear reconstruction is normal. Constant reconstruction is explicit,
    never a memory-pressure fallback. Coarsening can lose spatial detail: total
    conservation does NOT imply arbitrary remap/inverse remap is reversible.
    """
    _cancelled(cancel);_mesh_state(state);_backend(backend)
    if type(target) is not ColumnGrid1D or scheme not in ('linear','constant'):
        raise TectonicsError('target mesh and linear/constant reconstruction required')
    if plan is not None and (type(plan) is not RemapPlan or plan.source!=state.grid or plan.target!=target):
        raise TectonicsError('stale remap plan; both mesh identities must match')
    c=len(state.cohorts);ns=state.grid.cells;nt=target.cells
    with select_budget(budget).reserve(48*c*(ns+nt)+224*(ns+nt)+8192*c+16384,category='material-remap'):
        op=RemapPlan(state.grid,target,backend=backend,budget=budget) if plan is None else plan
        if state.grid==target:return state
        try:
            if backend=='numba':
                from ._mesh_native import remap_rows
                h=remap_rows(state.thickness_m,state.grid.edges_m,target.edges_m,*op.arrays(),scheme=='linear')
            else:h=_remap_reference(state.thickness_m,state.grid.edges_m,target.edges_m,scheme=='linear')
            before=_inventories(state.thickness_m,state.grid,backend);after=_inventories(h,target,backend)
            accounts=[_account(float(b),float(a),0.,0.,0.) for b,a in zip(before,after)]
            _cancelled(cancel)
            return _publish(state,target,h,state.time_s,{'operation':'conservative-remap-v1',
                'plan':op.plan_id,'scheme':scheme,'backend':backend,'cohort_accounts':accounts},budget=budget)
        except (ValueError,OverflowError,FloatingPointError) as exc:
            if isinstance(exc,MemoryLimitError):raise
            raise TectonicsError(str(exc)) from exc


def _ale_reference(h,x,y,a,dt,el,er,linear):
    c,n=h.shape;out=np.empty_like(h);mean=np.empty((c,n+1));maximum=0.
    w0=np.diff(x);w1=np.diff(y);cap=.5 if linear else 1.
    outgoing=dt*(np.maximum(a[1:],0)+np.maximum(-a[:-1],0))
    maximum=float(max(np.max(outgoing/w0),np.max(outgoing/w1) if linear else 0.))
    if not math.isfinite(maximum) or maximum>cap:raise TectonicsError('moving-grid outgoing Courant limit exceeded')
    def flux(row,edges,left,right):
        slopes=_slopes_reference(row,edges,linear);widths=np.diff(edges)
        lo=row-.5*widths*slopes;hi=row+.5*widths*slopes
        donor_l=np.r_[left,hi];donor_r=np.r_[lo,right]
        return a*np.where(a>=0,donor_l,donor_r)
    for k in range(c):
        f0=flux(h[k],x,el[k],er[k]);q0=h[k]*w0
        q1=q0+dt*(f0[:-1]-f0[1:]);stage=q1/w1
        if np.any(stage<0):raise TectonicsError('negative ALE stage')
        if linear and dt!=0:
            f1=flux(stage,y,el[k],er[k]);q2=q1+dt*(f1[:-1]-f1[1:])
            if np.any(q2<0):raise TectonicsError('negative second ALE stage')
            out[k]=(.5*q0+.5*q2)/w1;mean[k]=.5*f0+.5*f1
        else:out[k]=stage;mean[k]=f0
    return out,mean,maximum


def _boundary_values(state, relative, boundary, left):
    if type(boundary) is not MaterialBoundary:raise TectonicsError('typed material boundaries required')
    ids=tuple(c.cohort_id for c in state.cohorts);values=dict(boundary.exterior or ())
    if not values.keys()<=set(ids):raise TectonicsError('unregistered incoming cohort')
    a=float(relative[0] if left else relative[-1]);inward=a>0 if left else a<0
    if boundary.mode=='closed' and a!=0:raise TectonicsError('closed moving boundary requires u-w=0, not u=0')
    if inward and boundary.exterior is None:raise TectonicsError('relative inflow requires explicit external composition')
    return np.array([values.get(k,0.) for k in ids])


def advect_ale(state, face_velocity_m_s, mesh_velocity_m_s, duration_s, *,left,right,
                scheme='muscl',backend='numba',event_times_s=(),budget=None,cancel=None):
    """Move a mesh linearly while transporting material relative to its faces.

    Frozen face forcing for ONE interval. Closed faces move with material; open
    boundary exchange uses u-w. The method evolves H*width (not H) and averages
    stage fluxes. Known event times may be endpoints but must not lie inside a step.
    """
    _cancelled(cancel);_mesh_state(state);_backend(backend)
    if scheme not in ('muscl','upwind'):raise TectonicsError('explicit muscl/upwind scheme required')
    dt=scalar(duration_s,'duration',nonnegative=True);end=_end_time(state,dt)
    for t in event_times_s:
        t=scalar(t,'event time')
        if state.time_s<t<end:raise TectonicsError('interval crosses a known event; split explicitly at its time')
    n=state.grid.cells;c=len(state.cohorts)
    if input_shape(face_velocity_m_s)!=(n+1,) or input_shape(mesh_velocity_m_s)!=(n+1,):
        raise TectonicsError('N+1 physical and mesh face velocities required')
    with select_budget(budget).reserve(96*c*n+256*n+16384*c+16384,category='ale-materials'):
        u=snapshot(face_velocity_m_s,'physical face velocity');w=snapshot(mesh_velocity_m_s,'mesh velocity')
        try:
            with np.errstate(over='raise',invalid='raise'):
                relative=u-w;edges=state.grid.edges_m+dt*w
        except FloatingPointError as exc:
            raise TectonicsError('physical/mesh motion exceeds numerical range') from exc
        target=ColumnGrid1D(edges,frame_id=state.grid.frame_id,budget=budget)
        if dt>0 and np.any((w!=0)&(target.edges_m==state.grid.edges_m)):
            raise TectonicsError('mesh motion is unresolvable at this coordinate magnitude')
        el=_boundary_values(state,relative,left,True);er=_boundary_values(state,relative,right,False)
        try:
            if backend=='numba':
                from ._mesh_native import advance_ale
                h,flux,maximum=advance_ale(state.thickness_m,state.grid.edges_m,target.edges_m,relative,dt,el,er,scheme=='muscl')
            else:h,flux,maximum=_ale_reference(state.thickness_m,state.grid.edges_m,target.edges_m,relative,dt,el,er,scheme=='muscl')
            before=_inventories(state.thickness_m,state.grid,backend);after=_inventories(h,target,backend)
            accounts=np.array([_account(float(before[k]),float(after[k]),dt*float(flux[k,0]),
                            -dt*float(flux[k,-1]),maximum) for k in range(c)])
            record={'operation':'ale-cohort-ssprk2-v1','physical_velocity':_hash_array(u),
                    'mesh_velocity':_hash_array(w),'duration_s':dt,'target_grid':target.grid_id,
                    'left':asdict(left),'right':asdict(right),'scheme':scheme,'backend':backend,
                    'cohort_accounts':accounts.tolist()}
            new=_publish(state,target,h,end,record,budget=budget)
            result=MaterialTransportResult(new,scheme,backend,_immutable_bytes(flux),_immutable_bytes(accounts))
            _cancelled(cancel);return result
        except (ValueError,OverflowError,FloatingPointError) as exc:
            if isinstance(exc,MemoryLimitError):raise
            raise TectonicsError(str(exc)) from exc


def ale_timestep_limit(state,face_velocity_m_s,mesh_velocity_m_s,*,left,right,scheme='muscl',budget=None):
    """Sufficient bound on both SSP stages AND mesh crossing, rounded down.

    For shrinking cells, dt*A/(V0+dt*dV) <= cap yields
    dt <= cap*V0/(A-cap*dV). Mesh crossing is checked even when relative flow is zero.
    """
    _mesh_state(state)
    if scheme not in ('muscl','upwind'):raise TectonicsError('unknown scheme')
    n=state.grid.cells
    if input_shape(face_velocity_m_s)!=(n+1,) or input_shape(mesh_velocity_m_s)!=(n+1,):raise TectonicsError('N+1 velocities required')
    with select_budget(budget).reserve(96*n+8192,category='ale-limit'):
        u=snapshot(face_velocity_m_s,'physical velocity');w=snapshot(mesh_velocity_m_s,'mesh velocity')
        try:
            with np.errstate(over='raise',invalid='raise'):
                a=u-w
        except FloatingPointError as exc:
            raise TectonicsError('relative motion exceeds numerical range') from exc
        _boundary_values(state,a,left,True);_boundary_values(state,a,right,False)
        cap=.5 if scheme=='muscl' else 1.;limit=math.inf
        for i,width in enumerate(state.grid.widths_m):
            rate=float(w[i+1])-float(w[i]);out=max(float(a[i+1]),0.)+max(-float(a[i]),0.)
            if not math.isfinite(rate) or not math.isfinite(out):
                raise TectonicsError('mesh/relative velocity range is unsupported')
            denominator=out-cap*min(rate,0.) if scheme=='muscl' else out
            if not math.isfinite(denominator):raise TectonicsError('ALE interval bound outside range')
            if denominator>0:limit=min(limit,cap*float(width)/denominator)
            if rate<0:limit=min(limit,float(width)/(-rate))
        if math.isinf(limit):return None
        limit=math.nextafter(limit,0.)
        if limit<=0 or not math.isfinite(limit):raise TectonicsError('no positive representable ALE interval')
        return limit


def restore_remap_result(parent,target,h,*,plan,scheme,backend,budget=None):
    """Validate cache/IPC values against source inventories and exact geometry IDs."""
    _mesh_state(parent);_backend(backend)
    if type(plan) is not RemapPlan or plan.source!=parent.grid or plan.target!=target:
        raise TectonicsError('remap restoration geometry mismatch')
    if scheme not in ('linear','constant') or input_shape(h)!=(len(parent.cohorts),target.cells):
        raise TectonicsError('invalid remap result shape/method')
    values=snapshot(h,'remap result',nonnegative=True)
    if parent.grid==target:
        if values.tobytes()!=parent.thickness_m.tobytes():raise TectonicsError('identity remap changed material')
        return parent
    before=_inventories(parent.thickness_m,parent.grid,backend);after=_inventories(values,target,backend)
    accounts=[_account(float(b),float(a),0.,0.,0.) for b,a in zip(before,after)]
    return _publish(parent,target,values,parent.time_s,{'operation':'conservative-remap-v1',
        'plan':plan.plan_id,'scheme':scheme,'backend':backend,'cohort_accounts':accounts},budget=budget)


def restore_ale_result(parent,u,w,dt,left,right,scheme,backend,packed,*,budget=None):
    """Rebuild a complete immutable candidate from verified typed array storage."""
    _mesh_state(parent);_backend(backend)
    if scheme not in ('muscl','upwind'):raise TectonicsError('invalid ALE scheme')
    n=parent.grid.cells;c=len(parent.cohorts);dt=scalar(dt,'duration',nonnegative=True)
    if input_shape(packed)!=(c,2*n+9):raise TectonicsError('invalid ALE result layout')
    raw=snapshot(packed,'ALE result')
    h=raw[:,:n];flux=raw[:,n:2*n+1];stored=raw[:,2*n+1:]
    if np.any(h<0):raise TectonicsError('negative restored ALE state')
    target=ColumnGrid1D(parent.grid.edges_m+dt*w,frame_id=parent.grid.frame_id,budget=budget)
    relative=u-w;_boundary_values(parent,relative,left,True);_boundary_values(parent,relative,right,False)
    before=_inventories(parent.thickness_m,parent.grid,backend);after=_inventories(h,target,backend)
    maximum=float(stored[0,5])
    if maximum<0 or maximum>(.5 if scheme=='muscl' else 1.) or np.any(stored[:,5]!=maximum):
        raise TectonicsError('invalid ALE Courant result')
    outgoing=dt*(np.maximum(relative[1:],0)+np.maximum(-relative[:-1],0))
    expected_max=float(max(np.max(outgoing/parent.grid.widths_m),np.max(outgoing/target.widths_m) if scheme=='muscl' else 0.))
    if not math.isclose(maximum,expected_max,rel_tol=8*np.finfo(float).eps,abs_tol=0):raise TectonicsError('ALE admission receipt mismatch')
    accounts=np.array([_account(float(before[k]),float(after[k]),dt*float(flux[k,0]),-dt*float(flux[k,-1]),maximum) for k in range(c)])
    if not np.array_equal(stored,accounts):raise TectonicsError('ALE restored accounts disagree with fields/parent')
    record={'operation':'ale-cohort-ssprk2-v1','physical_velocity':_hash_array(u),
            'mesh_velocity':_hash_array(w),'duration_s':dt,'target_grid':target.grid_id,
            'left':asdict(left),'right':asdict(right),'scheme':scheme,'backend':backend,'cohort_accounts':accounts.tolist()}
    state=_publish(parent,target,h,_end_time(parent,dt),record,budget=budget)
    return MaterialTransportResult(state,scheme,backend,_immutable_bytes(flux),_immutable_bytes(accounts))


def validate_ale_result(result,parent,u,w,dt,left,right,scheme,backend,*,budget=None):
    from .materials import pack_material_result
    if type(result) is not MaterialTransportResult:raise TectonicsError('invalid ALE worker result')
    restored=restore_ale_result(parent,u,w,dt,left,right,scheme,backend,pack_material_result(result),budget=budget)
    if restored.state.state_id!=result.state.state_id:raise TectonicsError('ALE worker state identity mismatch')
    return restored


def w02_native_build_info():
    """Observed compiled methods/build; neither a signature nor a physics certificate."""
    import numba, llvmlite
    from . import _mesh_native
    names=('overlap_geometry','remap_rows','inventories','advance_ale','block_inventories','mapped_points')
    records={}
    for name in names:
        fn=getattr(_mesh_native,name)
        assembly='\n'.join(fn.inspect_asm(sig) for sig in fn.signatures)
        records[name]={'signatures':[str(sig) for sig in fn.signatures],
            'fastmath':fn.targetoptions.get('fastmath',False),'nogil':fn.targetoptions.get('nogil',False),
            'parallel':fn.targetoptions.get('parallel',False),
            'generated_assembly_sha256':hashlib.sha256(assembly.encode()).hexdigest()}
    return {'numba':numba.__version__,'llvmlite':llvmlite.__version__,'disk_jit_cache':False,
            'methods':records,'scope':'compiled kernels exercised by this verification process'}
