"""Source-bound W07 workflows and atomic recovery. SPDX-License-Identifier: AGPL-3.0-only"""
from contextlib import contextmanager
from dataclasses import dataclass
import json
import math
import threading
from time import perf_counter

import numpy as np

from ._validation import TectonicsError, scalar, input_shape, read_array, frozen
from .constitutive import _json, _cancel
from .geological_records import GeologySource
from .regional_execution import (RegionalMechanicalSnapshot, RegionalMechanicsScales,
    RegionalReferencePressure, PreparedRegionalStokes2D, _hash, _array_hash)
from .regional_strength import DryStrengthProfile, solve_regional_strength
from .regional_thermomechanical import RegionalThermalBodyForce, temperature_stress_sites
from .regional_transport import RectangularTransportGrid, PreparedHeatTransport, HeatBoundary
from .free_surface import PreparedFreeSurface2D
from .surface_geometry import SurfaceProjection
from .resources import WorkBudget, select_budget
from .reuse import ExecutionContext
from .storage import ArrayStore
from .spreading import _within_budget
from .stokes_execution import _native_lease


def _source(value, name):
    if type(value) is not GeologySource:raise TectonicsError(name+' requires an explicit GeologySource')
    from dataclasses import asdict
    return json.loads(_json(asdict(value)))


@dataclass(frozen=True, slots=True)
class W07BoundaryMotion:
    """closed, source-translation, or independently sourced simple-shear."""
    kind: str
    source: GeologySource
    shear_rate_s_1: float = 0.

    def __post_init__(self):
        if self.kind not in ('closed','source-translation','simple-shear'):
            raise TectonicsError('unsupported W07 boundary motion')
        _source(self.source,'boundary source')
        object.__setattr__(self,'shear_rate_s_1',scalar(self.shear_rate_s_1,'shear rate'))
        if self.kind!='simple-shear' and self.shear_rate_s_1!=0.:
            raise TectonicsError('shear rate supplied to a nonshear boundary')

    def descriptor(self):
        return dict(kind=self.kind,source=_source(self.source,'boundary source'),shear_rate_s_1=self.shear_rate_s_1)


@dataclass(frozen=True, slots=True)
class W07WorkflowOutput:
    checkpoint_id: str
    output_index: int
    state: RegionalMechanicalSnapshot
    mechanics: RegionalMechanicalSnapshot
    _receipt: bytes

    def descriptor(self):return json.loads(self._receipt)

    @property
    def output_id(self):
        return _hash(dict(state=self.state.result_id,mechanics=self.mechanics.result_id,receipt=self.descriptor()))


class PreparedW07Workflow:
    """Borrow geology/store; retain prepared mechanics and latest physical state."""
    def __setattr__(self,name,value):
        if name in ('geology','store','route','times','steps','execution_id','plan_id') and hasattr(self,name):
            raise AttributeError('W07 source and policy are immutable; prepare a new workflow')
        object.__setattr__(self,name,value)

    def __init__(self, geology, output_times_s, *, route, scales, boundary_motion=None,
                 physical_mean_pressure_pa=None, reference_pressure=None, strength_profile=None,
                 interval_steps=None, heat_boundaries=None, heat_boundary_source=None,
                 surface_perturbation_m=None, perturbation_source=None,
                 store=None, budget=None, cancel=None):
        from .regional_geology import RegionalGeologicalInputs
        if type(geology) is not RegionalGeologicalInputs:raise TectonicsError('typed geological input binding required')
        if route not in ('steady','thermal','surface'):raise TectonicsError('unsupported W07 workflow route')
        if type(scales) is not RegionalMechanicsScales:raise TectonicsError('explicit regional SI scales required')
        if type(output_times_s) not in (tuple,list) or not 1<=len(output_times_s)<=256:
            raise TectonicsError('one to 256 explicit requested outputs required')
        times=tuple(scalar(t,'output time') for t in output_times_s)
        if times[0]<geology.time_s or any(b<=a for a,b in zip(times,times[1:])):
            raise TectonicsError('output times must increase from the geological epoch')
        if route=='steady' and times!=(geology.time_s,):
            raise TectonicsError('a steady snapshot does not advance geological time')
        if interval_steps is None:interval_steps=tuple(0 if t==geology.time_s else 1 for t in times)
        if type(interval_steps) not in (tuple,list) or len(interval_steps)!=len(times):
            raise TectonicsError('each output needs its explicit interval partition')
        steps=tuple(interval_steps)
        if any(type(n) is not int or not 0<=n<=256 or (n==0)!=(t==geology.time_s) for n,t in zip(steps,times)) or sum(steps)>256:
            raise TectonicsError('cumulative accepted partition exceeds 256 or contains invalid zero interval')
        if store is not None and not isinstance(store,ArrayStore):raise TectonicsError('ArrayStore required')
        if reference_pressure is not None and type(reference_pressure) is not RegionalReferencePressure:
            raise TectonicsError('typed reference pressure required')
        if strength_profile is not None and (route!='steady' or type(strength_profile) is not DryStrengthProfile):
            raise TectonicsError('dry strength applies to the steady regional route')
        if route!='thermal' and (heat_boundaries is not None or heat_boundary_source is not None):
            raise TectonicsError('heat controls require the thermal route')
        if route!='surface' and (surface_perturbation_m is not None or perturbation_source is not None):
            raise TectonicsError('surface disturbance requires the surface route')
        if route=='surface' and any(x is not None for x in (boundary_motion,reference_pressure,physical_mean_pressure_pa,strength_profile)):
            raise TectonicsError('surface traction fixes its own boundary/pressure conditions')
        if route!='surface' and type(boundary_motion) is not W07BoundaryMotion:
            raise TectonicsError('explicit regional boundary motion required')
        self._owner=threading.get_ident();self._active=False;self._closed=False
        self._resource=WorkBudget(128*1024**2,parent=select_budget(budget))
        if store is not None:_within_budget(self._resource,store._budget)
        self.geology,self.store,self.route=geology,store,route
        self.times,self.steps=times,steps
        self._current=self._current_guard=None
        self._mechanical=self._heat=self._context=None
        self._stats=dict(computed_outputs=0,restored_outputs=0,latest_hits=0,physics_seconds=0.,storage_seconds=0.)
        self._work_bytes=2*1024**2+4096*geology.nx*geology.nz+3*geology.nbytes
        self._guard=self._resource.reserve(2*1024**2+1024*geology.nx*geology.nz+4096*len(times)+3*geology.nbytes,
            category='w07-workflow-prepared')
        self._guard.__enter__()
        try:
            _cancel(cancel);geology.verify(cancel=cancel)
            self._context=ExecutionContext('scipy');self.execution_id=self._context.identity
            d=geology.descriptor();self._geology_descriptor=d
            self._source_snapshot=RegionalMechanicalSnapshot(d,{k:geology.array(k) for k in geology.array_names})
            self._homogeneous=geology.homogeneous_material
            self._strength=strength_profile
            self._boundary_motion=boundary_motion
            self._heat_boundaries=None
            self._initial_surface=None
            thermal_record=perturbation_record=None
            if route=='surface':
                arguments=geology.surface_parameters()
                self._mechanical=PreparedFreeSurface2D(**arguments,scales=scales,budget=self._resource,cancel=cancel)
                surface=geology.array('surface_height_m')
                if surface_perturbation_m is not None:
                    perturbation_record=_source(perturbation_source,'surface perturbation')
                    if input_shape(surface_perturbation_m)!=(2*geology.nx+1,):
                        raise TectonicsError('surface perturbation requires Q2 graph support')
                    delta=read_array(surface_perturbation_m,'surface perturbation')
                    projection=SurfaceProjection(np.linspace(0.,geology.width_m,2*geology.nx+1))
                    if abs(projection.integral(delta))>1e-12*geology.width_m*geology.height_m:
                        raise TectonicsError('declared surface disturbance changes supplied material volume')
                    surface=surface+delta
                    perturbation_record=dict(source=perturbation_record,sha256=_hash(delta.tolist()),
                        meaning='declared fresh homogeneous initial scenario, not observed source topography')
                elif perturbation_source is not None:raise TectonicsError('perturbation source without disturbance')
                self._initial_surface=self._mechanical.initial_state(surface,epoch_id=geology.epoch_id,time_s=geology.time_s,cancel=cancel)
            else:
                self._validate_motion(d,boundary_motion)
                pattern={s:{'u':'velocity','w':'velocity'} for s in ('left','right','bottom','top')}
                self._mechanical=PreparedRegionalStokes2D(geology.nx,geology.nz,geology.width_m,geology.height_m,
                    float(geology.array('eta_center_pa_s')[0,0]),pattern,scales=scales,frame_id=geology.frame_id,
                    vertical_datum=geology.vertical_datum,material_source=geology.binding_id,
                    physical_mean_pressure_pa=physical_mean_pressure_pa,reference_pressure=reference_pressure,
                    viscosity_center_pa_s=geology.array('eta_center_pa_s'),viscosity_vertex_pa_s=geology.array('eta_vertex_pa_s'),
                    material_sampling='source-bound pure ordered layers; exact series shear-dual compliance',
                    budget=self._resource,cancel=cancel)
                self._boundary=self._boundary_values()
                self._boundary_samples={s:{c:frozen(np.full(self._mechanical.coordinates((s,c))[0].shape,v))
                    if input_shape(v)==() else v for c,v in parts.items()} for s,parts in self._boundary.items()}
                self._boundary_hashes={s:{c:_array_hash(v) for c,v in parts.items()} for s,parts in self._boundary_samples.items()}
                if strength_profile is not None:
                    if self._homogeneous is None or strength_profile.creep_viscosity_pa_s!=self._homogeneous['viscosity_pa_s']:
                        raise TectonicsError('one C01 creep law must match the homogeneous geological viscosity')
                if route=='thermal':
                    if self._homogeneous is None or len(geology.array('cohort_partial_thickness_m'))!=1 or boundary_motion.kind!='closed':
                        raise TectonicsError('thermal workflow requires single-cohort homogeneous closed material support')
                    _source(heat_boundary_source,'heat boundary source')
                    if type(heat_boundaries) is not dict or set(heat_boundaries)!=set(pattern) or any(type(b) is not HeatBoundary for b in heat_boundaries.values()):
                        raise TectonicsError('all four typed thermal boundaries required')
                    self._heat_boundaries={}
                    for side,b in heat_boundaries.items():
                        count=geology.nz if side in ('left','right') else geology.nx
                        values=[]
                        for value in (b.inflow_temperature_k,b.diffusion_value):
                            if value is None:values.append(None);continue
                            if callable(value) or input_shape(value) not in ((),(count,)):
                                raise TectonicsError('sampled scalar/side-supported constant-in-time thermal boundary required')
                            values.append(float(value) if input_shape(value)==() else frozen(read_array(value,'thermal boundary')))
                        self._heat_boundaries[side]=HeatBoundary(values[0],b.diffusion_kind,values[1])
                    h=self._homogeneous
                    if h['conductivity_w_m_k'] is None or h['specific_heat_j_kg_k'] is None or h['heat_production_w_m3'] is None:
                        raise TectonicsError('complete source thermal properties required; unknown is not zero')
                    grid=RectangularTransportGrid(geology.nx,geology.nz,geology.width_m,geology.height_m,geology.frame_id,
                        strike_width_m=geology.strike_width_m)
                    self._heat=PreparedHeatTransport(grid,h['conductivity_w_m_k'],h['density_kg_m3']*h['specific_heat_j_kg_k'],
                        budget=self._resource)
                    thermal_record=dict(source=_source(heat_boundary_source,'heat boundary source'),
                        boundaries={s:dict(inflow=None if b.inflow_temperature_k is None else np.asarray(b.inflow_temperature_k).tolist(),
                            kind=b.diffusion_kind,value=np.asarray(b.diffusion_value).tolist()) for s,b in self._heat_boundaries.items()},
                        material=h,method='first-order frozen-velocity coupling; SSPRK2 heat; constant source-selected viscosity')
            from dataclasses import asdict
            self._definition=dict(schema='atlas.w07-workflow.v1',geology=geology.binding_id,execution=self.execution_id,
                route=route,times_s=times,interval_steps=steps,scales=asdict(scales),
                boundary=None if boundary_motion is None else boundary_motion.descriptor(),
                physical_mean_pressure_pa=physical_mean_pressure_pa,
                reference_pressure=None if reference_pressure is None else asdict(reference_pressure),
                strength=None if strength_profile is None else strength_profile.descriptor(),
                thermal=thermal_record,surface_perturbation=perturbation_record)
            self.plan_id=_hash(self._definition);self._check(cancel)
        except BaseException:
            self.close();raise

    def _validate_motion(self,d,motion):
        values=self.geology.array('source_face_velocity_m_s')
        owner=d['ownership']['boundary_motion_owner']
        expected_source=d['ownership']['motion_source' if owner=='W01-S6' else 'boundary_source']
        if _source(motion.source,'boundary source')!=expected_source:
            raise TectonicsError('boundary motion source differs from declared physical owner')
        if motion.kind=='source-translation':
            if owner!='W01-S6' or np.any(values!=values[0]):
                raise TectonicsError('source translation requires unchanged uniform S6 motion ownership')
        elif owner!='W07-boundary' or np.any(values!=0.):
            raise TectonicsError('regional boundary must not discard active S6 motion')

    def _boundary_values(self):
        motion=self._boundary_motion;g=self.geology
        shift=float(g.array('source_face_velocity_m_s')[0]) if motion.kind=='source-translation' else 0.
        return {side:{'u':frozen(shift+motion.shear_rate_s_1*self._mechanical.coordinates((side,'u'))[1]),'w':0.}
                for side in ('left','right','bottom','top')}

    def _check(self,cancel=None):
        if self._closed or threading.get_ident()!=self._owner:raise TectonicsError('closed or wrong-thread W07 workflow')
        _cancel(cancel);self._context.verify();self.geology.verify(cancel=cancel)
        if _hash(self._definition)!=self.plan_id:raise TectonicsError('W07 source/policy changed; prepare a new workflow')

    @contextmanager
    def _operation(self,cancel):
        if self._active:raise TectonicsError('W07 workflow already active')
        self._check(cancel);self._active=True
        try:
            with _native_lease():yield
            self._check(cancel)
        finally:self._active=False

    def _index(self,index):
        if type(index) is not int or not 0<=index<len(self.times):raise TectonicsError('output index outside W07 schedule')
        return index

    def _invocation(self,index):
        self._index(index)
        return dict(schema='atlas.w07-requested-output.v1',plan_id=self.plan_id,index=index,time_s=self.times[index],
                    accepted_steps=sum(self.steps[:index+1]))

    def checkpoint_id(self,index):return _hash(self._invocation(index))
    def descriptor(self):return json.loads(_json(self._definition))
    def statistics(self):return dict(self._stats,budget=self._resource.statistics())

    def _state(self,T,time,steps,parent):
        return RegionalMechanicalSnapshot(dict(schema='atlas.w07-thermal-state.v1',geology=self.geology.binding_id,
            time_s=time,epoch_id=self.geology.epoch_id,accepted_steps=steps,parent_output_id=parent,
            material='fixed reference inventories; buoyancy density does not replace mass'),
            dict(temperature_k=T,reference_mass_kg=self.geology.array('reference_mass_kg')))

    def _temperature(self,T):
        a=read_array(T,'current geological temperature')
        if a.shape!=(self.geology.nz,self.geology.nx):raise TectonicsError('current temperature support mismatch')
        lo,hi=self._homogeneous['valid_temperature_k']
        if np.any((a<=0.)|(a<lo)|(a>hi)):raise TectonicsError('temperature outside the declared geological material law')
        return a

    def _force(self,T):
        g=self.geology;fx=g.array('force_u_n_m3');fz=g.array('force_w_n_m3')
        if self.route=='thermal':
            T=self._temperature(T);h=self._homogeneous
            if h['density_law']=='boussinesq-linear-reference':
                centre,vertex=temperature_stress_sites(T)
                body=RegionalThermalBodyForce(h['density_kg_m3'],self._geology_descriptor['gravity_m_s2'],
                    h['thermal_expansion_per_k'],h['reference_temperature_k'],g.binding_id)
                fx,fz=body.force(centre,vertex)  # Replace, never add, total gravity.
        return fx,fz

    def _force_source(self,T):
        return _hash(dict(geology=self.geology.binding_id,temperature=None if T is None else _hash(np.asarray(T).tolist())))

    def _solve(self,time,T,cancel):
        g=self.geology;fx,fz=self._force(T)
        arguments=dict(frame_id=g.frame_id,epoch_id=g.epoch_id,time_s=time,
            force_source=self._force_source(T),
            boundary_source=_hash(self._boundary_motion.descriptor()),cancel=cancel)
        if self._strength is None:return self._mechanical.solve(fx,fz,self._boundary,**arguments)
        return solve_regional_strength(self._mechanical,self._strength,fx,fz,self._boundary,
            material_source=g.binding_id,**arguments).mechanics

    def _compute(self,index,previous,cancel):
        g=self.geology;time=self.times[index];start=g.time_s if previous is None else self.times[index-1]
        parent=None if previous is None else previous.output_id
        receipt=dict(schema='atlas.w07-workflow-output.v1',invocation=self._invocation(index),
            geology_id=g.binding_id,parent_output_id=parent,route=self.route,source_status='WORKING NON-CANON',
            ownership=self._geology_descriptor['ownership'],start_time_s=start,end_time_s=time)
        if self.route=='surface':
            initial=self._initial_surface if previous is None else previous.state
            if time==start:
                state=initial;mechanics=self._mechanical.mechanics(state,cancel=cancel);account=None
            else:
                advanced=self._mechanical.advance(initial,time-start,steps=self.steps[index],cancel=cancel)
                state,mechanics,account=advanced.state,advanced.mechanics,advanced.descriptor()
            receipt['surface']=account
        elif self.route=='thermal':
            T=g.array('temperature_k') if previous is None else previous.state.array('temperature_k')
            self._temperature(T)
            if time==start:
                mechanics=self._solve(time,T,cancel);account=None
            else:
                initial=self._solve(start,T,cancel)
                evolved=self._heat.evolve(T,initial.array('u_m_s'),initial.array('w_m_s'),time-start,
                    steps=self.steps[index],boundaries=self._heat_boundaries,time_s=start,
                    source_w_m3=self._homogeneous['heat_production_w_m3'],cancel=cancel)
                T=self._temperature(evolved['temperature_k'])
                account={k:v for k,v in evolved.items() if k!='temperature_k'}
                if 'timestep_limit_s' in account and math.isinf(account['timestep_limit_s']):account['timestep_limit_s']=None
                mechanics=self._solve(time,T,cancel)
            state=self._state(T,time,sum(self.steps[:index+1]),parent);receipt['heat']=account
        else:
            mechanics=self._solve(time,None,cancel);state=self._source_snapshot
        return W07WorkflowOutput(self.checkpoint_id(index),index,state,mechanics,_json(receipt))

    def _pack(self,result,cancel):
        from .regional_checkpoint import pack_regional_snapshots
        arrays,payload=pack_regional_snapshots(dict(state=result.state,mechanics=result.mechanics),budget=self._resource,cancel=cancel)
        header=dict(invocation=self._invocation(result.output_index),execution=self.execution_id,
            parent_checkpoint_id=None if result.output_index==0 else self.checkpoint_id(result.output_index-1),
            parent_output_id=result.descriptor()['parent_output_id'],output_id=result.output_id,
            receipt=result.descriptor(),payload=payload)
        return arrays,dict(header,content_id=_hash(header))

    def _header(self,index,meta,parent):
        expected={'invocation','execution','parent_checkpoint_id','parent_output_id','output_id','receipt','payload','content_id'}
        if type(meta) is not dict or set(meta)!=expected:raise TectonicsError('invalid W07 checkpoint envelope')
        header={k:v for k,v in meta.items() if k!='content_id'}
        if (meta['invocation']!=self._invocation(index) or meta['execution']!=self.execution_id or
            meta['parent_checkpoint_id']!=(None if index==0 else self.checkpoint_id(index-1)) or
            meta['parent_output_id']!=parent or meta['content_id']!=_hash(header)):
            raise TectonicsError('W07 checkpoint source/schedule/parent mismatch')
        r=meta['receipt']
        keys={'schema','invocation','geology_id','parent_output_id','route','source_status','ownership','start_time_s','end_time_s'}
        if self.route!='steady':keys.add('heat' if self.route=='thermal' else 'surface')
        if (type(r) is not dict or set(r)!=keys or r.get('schema')!='atlas.w07-workflow-output.v1' or
            r.get('source_status')!='WORKING NON-CANON' or
            r.get('start_time_s')!=(self.geology.time_s if index==0 else self.times[index-1]) or
            type(meta['output_id']) is not str or len(meta['output_id'])!=64 or
            any(c not in '0123456789abcdef' for c in meta['output_id']) or
            r.get('invocation')!=self._invocation(index) or r.get('geology_id')!=self.geology.binding_id or
            r.get('parent_output_id')!=parent or r.get('route')!=self.route or
            r.get('ownership')!=self._geology_descriptor['ownership'] or r.get('end_time_s')!=self.times[index]):
            raise TectonicsError('W07 physical receipt/ownership mismatch')
        return meta['payload']

    def _scan(self,end,cancel):
        latest,meta,parent,gap=-1,None,None,False
        for i in range(end+1):
            _cancel(cancel);candidate=self.store.metadata(self.checkpoint_id(i))
            if candidate is None:gap=True;continue
            if gap:raise TectonicsError('W07 requested-output checkpoint history has a gap')
            self._header(i,candidate,parent)
            if self.route=='thermal':
                prior=self._heat_energy(self.geology.array('temperature_k')) if meta is None else (
                    meta['receipt']['heat']['heat_after_j'] if meta['receipt']['heat'] is not None else
                    self._heat_energy(self.geology.array('temperature_k')))
                self._heat_receipt(i,candidate['receipt'],before=prior)
            latest,meta,parent=i,candidate,candidate['output_id']
        return latest,meta

    def _restore(self,index,meta,cancel):
        from .regional_checkpoint import restore_regional_snapshots
        arrays=self.store.get(self.checkpoint_id(index),budget=self._resource)
        if arrays is None:raise TectonicsError('W07 checkpoint disappeared')
        with self._resource.reserve(4*sum(a.nbytes for a in arrays.values())+65536,category='w07-restore'):
            snapshots=restore_regional_snapshots(arrays,meta['payload'],budget=self._resource,cancel=cancel)
            if set(snapshots)!={'state','mechanics'}:raise TectonicsError('W07 checkpoint field-set mismatch')
            result=W07WorkflowOutput(self.checkpoint_id(index),index,snapshots['state'],snapshots['mechanics'],_json(meta['receipt']))
            if result.output_id!=meta['output_id']:raise TectonicsError('W07 checkpoint scientific output mismatch')
            self._validate_output(result,cancel)
        self._stats['restored_outputs']+=1
        return result

    def _heat_energy(self,T):
        g=self.geology
        return math.fsum(np.asarray(T).ravel())*self._heat.capacity*g.width_m*g.height_m*g.strike_width_m/(g.nx*g.nz)

    def _heat_receipt(self,index,receipt,*,before=None,after=None):
        account=receipt['heat'];n=self.steps[index]
        if not n:
            if account is not None:raise TectonicsError('initial temperature has an unexpected evolved heat account')
            return
        if type(account) is not dict:raise TectonicsError('missing physical heat account')
        g=self.geology;duration=self.times[index]-(g.time_s if index==0 else self.times[index-1])
        volume=g.width_m*g.height_m*g.strike_width_m
        expected_source=self._homogeneous['heat_production_w_m3']*volume*duration
        close=lambda a,b:abs(a-b)<=1e-9*max(abs(a),abs(b),np.finfo(float).tiny)
        if (account.get('accepted_steps')!=n or account.get('time_s')!=self.times[index] or
            account.get('origin_m') not in ((0.,0.),[0.,0.])):
            raise TectonicsError('restored heat time/geometry/partition mismatch')
        values={k:scalar(account.get(k),'heat '+k) for k in
            ('source_energy_j','heat_before_j','heat_after_j','balance_residual_j','balance_relative','maximum_step_balance_relative')}
        if (not close(values['source_energy_j'],expected_source) or
            before is not None and not close(values['heat_before_j'],before) or
            after is not None and not close(values['heat_after_j'],after)):
            raise TectonicsError('restored heat source or stored energy mismatch')
        adv,diff=account.get('advective_energy_j'),account.get('diffusive_energy_j')
        if any(type(v) is not dict or set(v)!=set(self._heat_boundaries) for v in (adv,diff)):
            raise TectonicsError('restored heat boundary support mismatch')
        adv={s:scalar(v,'advective energy') for s,v in adv.items()};diff={s:scalar(v,'diffusive energy') for s,v in diff.items()}
        if any(v!=0. for v in adv.values()):raise TectonicsError('closed material boundary cannot advect heat externally')
        for side,b in self._heat_boundaries.items():
            if b.diffusion_kind=='outward_flux':
                length=g.height_m if side in ('left','right') else g.width_m
                expected_flux=float(np.asarray(b.diffusion_value).mean())*length*g.strike_width_m*duration
                if not close(diff[side],expected_flux):raise TectonicsError('restored prescribed heat flux mismatch')
        residual=math.fsum((values['heat_after_j'],-values['heat_before_j'],*adv.values(),*diff.values(),-expected_source))
        scale=max(abs(values['heat_before_j']),abs(values['heat_after_j']),np.finfo(float).tiny)
        if (abs(residual)/scale>1e-9 or abs(residual-values['balance_residual_j'])/scale>1e-12 or
            not 0.<=values['balance_relative']<=1e-9 or not 0.<=values['maximum_step_balance_relative']<=1e-9):
            raise TectonicsError('restored heat storage/flux closure failed')

    def _validate_output(self,result,cancel):
        d=result.mechanics.descriptor()
        diagnostics=d.get('diagnostics',{})
        gates={'momentum_residual':1e-9,'normalised_work_residual':1e-9,'linear_residual':1e-12}
        gates.update({'weak_continuity_scaled_max':1e-10,'global_volume_flux_relative':1e-10,
            'flux_divergence_identity_relative':1e-10} if self.route=='surface' else
            {'divergence_residual':1e-10,'pressure_gauge_residual':1e-12})
        if diagnostics.get('gates_passed') is not True or any(
                type(diagnostics.get(k)) not in (float,int) or not math.isfinite(diagnostics[k]) or
                not 0.<=diagnostics[k]<=limit for k,limit in gates.items()):
            raise TectonicsError('restored mechanics were not accepted by the frozen numerical gates')
        if d.get('context_id')!=self.execution_id or d.get('source_status')!='WORKING NON-CANON':
            raise TectonicsError('restored mechanical source/status mismatch')
        if self.route=='surface':
            with self._mechanical._operation(cancel):s=self._mechanical._validate(result.state,cancel)
            if (s['time_s']!=self.times[result.output_index] or s['epoch_id']!=self.geology.epoch_id or
                s['accepted_steps']!=sum(self.steps[:result.output_index+1])):
                raise TectonicsError('restored surface time/partition mismatch')
            if (d.get('state_id')!=result.state.result_id or d.get('plan_id')!=s['plan_id'] or
                d.get('epoch_id')!=s['epoch_id'] or d.get('time_s')!=s['time_s'] or d.get('definition')!=s['definition'] or
                not np.array_equal(result.mechanics.array('mesh_nodes_m'),result.state.array('mesh_nodes_m'))):
                raise TectonicsError('restored mechanics belongs to another mesh state')
            initial_mass=float(self._initial_surface.array('cell_mass_kg').sum())
            if abs(float(result.state.array('cell_mass_kg').sum())-initial_mass)>1e-9*initial_mass:
                raise TectonicsError('restored surface lost its original total material inventory')
        else:
            request=d.get('request',{});definition=d.get('definition',{});T=None
            if request.get('time_s')!=self.times[result.output_index] or request.get('epoch_id')!=self.geology.epoch_id:
                raise TectonicsError('restored regional epoch mismatch')
            if self.route=='thermal':
                s=result.state.descriptor();T=self._temperature(result.state.array('temperature_k'))
                if (set(result.state.array_names)!={'temperature_k','reference_mass_kg'} or
                    s.get('schema')!='atlas.w07-thermal-state.v1' or s.get('geology')!=self.geology.binding_id or
                    s.get('epoch_id')!=self.geology.epoch_id or s.get('parent_output_id')!=result.descriptor()['parent_output_id'] or
                    s.get('time_s')!=self.times[result.output_index] or
                    s.get('accepted_steps')!=sum(self.steps[:result.output_index+1]) or
                    not np.array_equal(result.state.array('reference_mass_kg'),self.geology.array('reference_mass_kg'))):
                    raise TectonicsError('restored thermal/material state mismatch')
                self._heat_receipt(result.output_index,result.descriptor(),after=self._heat_energy(T))
            elif result.state.result_id!=self.geology.binding_id:raise TectonicsError('restored geological state mismatch')
            fx,fz=self._force(T)
            if (request.get('force_source')!=self._force_source(T) or
                request.get('boundary_source')!=_hash(self._boundary_motion.descriptor()) or
                request.get('forces')!={'u':_array_hash(fx),'w':_array_hash(fz)} or
                d.get('request_id')!=_hash(request) or
                request.get('plan_id')!=_hash(dict(definition=definition,context=self.execution_id))):
                raise TectonicsError('restored mechanical force/plan binding mismatch')
            expected=self._mechanical.descriptor()
            for key in expected:
                if self._strength is not None and key in ('material_source','stress_site_viscosity'):
                    continue
                if definition.get(key)!=expected[key]:raise TectonicsError('restored mechanical material/geometry policy mismatch: '+key)
            if self._strength is not None:
                binding=d.get('strength_binding',{})
                if (binding.get('profile')!=self._strength.descriptor() or binding.get('material_source')!=self.geology.binding_id or
                    definition.get('material_source')!='regional-C01='+_hash(binding)):
                    raise TectonicsError('restored strength law/source mismatch')
            support=definition.get('stress_site_viscosity',{})
            if (support.get('centre_sha256')!=_array_hash(result.mechanics.array('viscosity_center_pa_s')) or
                support.get('vertex_sha256')!=_array_hash(result.mechanics.array('viscosity_vertex_pa_s'))):
                raise TectonicsError('restored stress-site viscosity mismatch')
            for side,parts in self._boundary_samples.items():
                for component,value in parts.items():
                    if (request.get('boundary',{}).get(side,{}).get(component)!=self._boundary_hashes[side][component] or
                        not np.array_equal(result.mechanics.array('boundary_input_'+side+'_'+component),value)):
                        raise TectonicsError('restored physical boundary mismatch')

    def _adopt(self,result):
        guard=self._resource.reserve(result.state.nbytes+result.mechanics.nbytes+len(result._receipt)+65536,category='w07-latest-output')
        guard.__enter__();old=self._current_guard
        self._current,self._current_guard=result,guard
        if old is not None:old.__exit__(None,None,None)

    def load(self,index,*,cancel=None):
        self._index(index)
        with self._operation(cancel):
            if self.store is None:return self._current if self._current and self._current.output_index==index else None
            latest,meta=self._scan(index,cancel)
            return None if latest!=index else self._restore(index,meta,cancel)

    def run(self,*,through=None,cancel=None):
        end=len(self.times)-1 if through is None else self._index(through)
        with self._operation(cancel):
            current=self._current
            if current is not None and current.output_index==end:
                if self.store is None:self._stats['latest_hits']+=1;return current
            if self.store is not None:
                latest,meta=self._scan(end,cancel)
                current=None if latest<0 else self._restore(latest,meta,cancel)
                if current is not None:self._adopt(current)
            elif current is not None and current.output_index>end:
                raise TectonicsError('earlier output not retained; use a store')
            begin=0 if current is None else current.output_index+1
            for index in range(begin,end+1):
                self._check(cancel);started=perf_counter()
                with self._resource.reserve(self._work_bytes,category='w07-output-and-storage-scratch'):
                    candidate=self._compute(index,current,cancel)
                    self._validate_output(candidate,cancel)
                    self._stats['physics_seconds']+=perf_counter()-started
                    if self.store is not None:
                        started=perf_counter();arrays,metadata=self._pack(candidate,cancel)
                        self.store.put(candidate.checkpoint_id,arrays,metadata,budget=self._resource,cancel=cancel,
                            publication_check=lambda:self._check(cancel))
                        self._stats['storage_seconds']+=perf_counter()-started
                    self._check(cancel);self._adopt(candidate);self._stats['computed_outputs']+=1;current=candidate
            return current

    def close(self):
        if self._closed:return
        if self._active or threading.get_ident()!=self._owner:raise TectonicsError('close W07 on its idle driving thread')
        self._closed=True
        if self._mechanical is not None:self._mechanical.close()
        if self._context is not None:self._context.close()
        if self._current_guard is not None:self._current_guard.__exit__(None,None,None)
        self._current=None;self._guard.__exit__(None,None,None)

    def __enter__(self):self._check();return self
    def __exit__(self,*_):self.close()
