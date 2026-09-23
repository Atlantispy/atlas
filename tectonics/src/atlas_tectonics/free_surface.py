"""Homogeneous ALE; contract: docs/W07_SURFACE_STRENGTH.md.
SPDX-License-Identifier: AGPL-3.0-only
"""
from contextlib import contextmanager
from dataclasses import dataclass
import json
import math
import threading

import numpy as np

from ._validation import TectonicsError, scalar, input_shape, read_array
from .constitutive import _cancel, _json
from .resources import WorkBudget, select_budget
from .reuse import ExecutionContext
from .regional_execution import RegionalMechanicalSnapshot, RegionalMechanicsScales, _name, _hash
from .stokes_execution import _native_lease
from .surface_geometry import graph_mesh, cell_volume_and_flux, SurfaceProjection


@dataclass(frozen=True,slots=True)
class FreeSurfaceAdvance:
    state: RegionalMechanicalSnapshot
    mechanics: RegionalMechanicalSnapshot
    _metadata: bytes

    def descriptor(self):return json.loads(self._metadata)


class PreparedFreeSurface2D:
    """One driving thread; homogeneous inventory, gravity and current metrics."""
    def __init__(self,nx,nz,width_m,bottom_m,reference_height_m,*,viscosity_pa_s,
                 density_kg_m3,gravity_m_s2,external_pressure_pa,strike_width_m,
                 scales,frame_id,vertical_datum,material_source,load_source,
                 method='gmres',budget=None,cancel=None):
        from .regional_surface_stokes import PreparedSurfaceStokes2D
        if any(type(n) is not int or not 2<=n<=64 for n in (nx,nz)):
            raise TectonicsError('bounded 2..64 element counts required')
        if type(scales) is not RegionalMechanicsScales:raise TectonicsError('explicit mechanics scales required')
        values={}
        for name,value in dict(width_m=width_m,reference_height_m=reference_height_m,
                viscosity_pa_s=viscosity_pa_s,density_kg_m3=density_kg_m3,strike_width_m=strike_width_m).items():
            values[name]=scalar(value,name,positive=True)
        values['gravity_m_s2']=scalar(gravity_m_s2,'gravity',nonnegative=True)
        values['external_pressure_pa']=scalar(external_pressure_pa,'external pressure',nonnegative=True)
        values['bottom_m']=scalar(bottom_m,'bottom')
        if values['bottom_m']!=0.:
            raise TectonicsError('this mapped surface route requires bottom_m=0 in the explicit vertical datum')
        for value,name in ((frame_id,'frame'),(vertical_datum,'vertical datum'),
                (material_source,'material source'),(load_source,'load source')):_name(value,name)
        self._d=dict(values,nx=nx,nz=nz,frame_id=frame_id,vertical_datum=vertical_datum,
            material_source=material_source,load_source=load_source,method=method,
            scales=dict(length_m=scales.length_m,velocity_m_s=scales.velocity_m_s),
            geometry='fixed x columns; Q2 graph; bottom fixed; vertical side tangential mesh sliding',
            physical_boundaries='no-slip bottom; free-slip sides; external-pressure material top',
            material='explicit homogeneous incompressible isothermal inventory and gravity density')
        self._resource=WorkBudget(128*1024**2,parent=select_budget(budget))
        self._owner=threading.get_ident();self._active=False;self._closed=False
        self._latest_key=self._latest=None;self._stats={'mechanical_solves':0,'latest_result_hits':0,'accepted_steps':0}
        nodes=(2*nx+1)*(2*nz+1);elements=nx*nz;quadrature=25
        state_bytes=8*(2*nodes+elements)
        result_bytes=8*(6*nodes+12*elements+13*quadrature*elements)
        # Account raw quadrature fields, old/latest immutable publication and
        # the largest publication temporary concurrently. SSPRK2 retains its
        # original/current/trial/final state, both rates and geometry-flux work.
        # User-retained older outputs remain the caller's declared allowance.
        self._public_bytes=4*result_bytes+16*state_bytes+4096*elements+1024*nodes+1024**2
        self._state_bytes=state_bytes+32768
        self._guard=self._resource.reserve(self._public_bytes,category='surface-public-state')
        self._guard.__enter__();self._core=None;self._context=None
        try:
            _cancel(cancel)
            self._context=ExecutionContext('scipy');self._context_id=self._context.identity
            self._plan_id=_hash({'definition':self._d,'context':self._context_id})
            with _native_lease():
                self._projection=SurfaceProjection(np.linspace(0.,width_m,2*nx+1))
                self._core=PreparedSurfaceStokes2D(nx,nz,method=method,budget=self._resource,
                    length_scale_m=scales.length_m,velocity_scale_m_s=scales.velocity_m_s,
                    viscosity_scale_pa_s=values['viscosity_pa_s'])
            self._context.verify()
        except BaseException:
            if self._core is not None:self._core.close()
            if self._context is not None:self._context.close()
            self._closed=True;self._guard.__exit__(None,None,None);raise

    @contextmanager
    def _operation(self,cancel):
        if self._closed or self._active or self._owner!=threading.get_ident():
            raise TectonicsError('closed, active or wrong-thread surface plan')
        self._active=True
        try:
            _cancel(cancel);self._context.verify()
            with _native_lease():yield
            _cancel(cancel);self._context.verify()
        except BaseException:
            self._latest_key=self._latest=None
            raise
        finally:self._active=False

    def __enter__(self):
        if self._closed:raise TectonicsError('surface plan is closed')
        return self
    def __exit__(self,*_):self.close()
    def close(self):
        if self._closed:return
        if self._active or threading.get_ident()!=self._owner:raise TectonicsError('close surface plan on its driving thread')
        try:self._core.close();self._context.close()
        finally:
            self._latest=self._core=self._context=None;self._closed=True
            self._guard.__exit__(None,None,None)

    def descriptor(self):return json.loads(_json(self._d))
    def statistics(self):
        return dict(self._stats,public_workspace_allowance_bytes=self._public_bytes,
                    budget=self._resource.statistics())

    def _state(self,mesh,mass,epoch,time,steps,parent=None):
        return RegionalMechanicalSnapshot(dict(schema='atlas.free-surface-state.v1',source_status='WORKING NON-CANON',
            plan_id=self._plan_id,context_id=self._context_id,epoch_id=epoch,time_s=time,
            accepted_steps=steps,parent_state_id=parent,definition=self._d),
            dict(mesh_nodes_m=mesh,cell_mass_kg=mass))

    def _validate(self,state,cancel=None):
        if type(state) is not RegionalMechanicalSnapshot:raise TectonicsError('immutable source-bound surface state required')
        # Bound fields and metadata before decoding or any numerical copies.
        if state.nbytes>self._state_bytes or set(state.array_names)!={'mesh_nodes_m','cell_mass_kg'}:
            raise TectonicsError('surface state exceeds its bounded field/metadata support')
        d=state.descriptor()
        if (d.get('schema')!='atlas.free-surface-state.v1' or d.get('plan_id')!=self._plan_id or
                d.get('context_id')!=self._context_id or d.get('source_status')!='WORKING NON-CANON' or
                _json(d.get('definition'))!=_json(self._d)):
            raise TectonicsError('surface state source/geometry/material plan mismatch')
        _name(d.get('epoch_id'),'state epoch');scalar(d.get('time_s'),'state time')
        steps=d.get('accepted_steps')
        if type(steps) is not int or not 0<=steps<=256:
            raise TectonicsError('surface state accepted_steps must be an integer in 0..256')
        parent=d.get('parent_state_id')
        if ((steps==0 and parent is not None) or (steps>0 and
                (type(parent) is not str or len(parent)!=64 or any(c not in '0123456789abcdef' for c in parent)))):
            raise TectonicsError('surface state parent history is invalid')
        mesh=state.array('mesh_nodes_m');mass=state.array('cell_mass_kg')
        if (input_shape(mesh)!=(2*self._d['nz']+1,2*self._d['nx']+1,2) or
                input_shape(mass)!=(self._d['nz'],self._d['nx'])):
            raise TectonicsError('surface state mesh support mismatch')
        mesh=read_array(mesh,'state mesh');mass=read_array(mass,'state mass')
        if np.any(mass<=0.):raise TectonicsError('surface state requires positive finite cell mass')
        x=np.linspace(0.,self._d['width_m'],2*self._d['nx']+1)
        if np.max(np.abs(mesh[...,0]-x[None,:]))>1e-12*self._d['width_m']:
            raise TectonicsError('surface state fixed horizontal geometry differs from its definition')
        geometry=self._core.validate_geometry(mesh,cancel=cancel)
        expected=geometry['element_volume_m2']*self._d['density_kg_m3']*self._d['strike_width_m']
        if not np.isfinite(expected).all() or np.any(expected<=0.):
            raise TectonicsError('surface material inventory outside finite positive SI range')
        if np.max(np.abs(mass-expected)/expected)>1e-9:
            raise TectonicsError('surface state mass is incompatible with its homogeneous material definition')
        return d

    def initial_state(self,surface_elevation_m,*,epoch_id,time_s=0.,cancel=None):
        _name(epoch_id,'epoch');time=scalar(time_s,'time')
        if input_shape(surface_elevation_m)!=(2*self._d['nx']+1,):raise TectonicsError('surface support mismatch')
        with self._operation(cancel):
            mesh=graph_mesh(self._d['width_m'],self._d['bottom_m'],surface_elevation_m,self._d['nz'])
            geometry=self._core.validate_geometry(mesh,cancel=cancel)
            area=geometry['element_volume_m2']
            mass=area*self._d['density_kg_m3']*self._d['strike_width_m']
            if not np.isfinite(mass).all() or np.any(mass<=0.):
                raise TectonicsError('initial surface mass outside finite positive SI range')
            return self._state(mesh,mass,epoch_id,time,0)

    def _mechanics(self,state,cancel):
        d=self._validate(state,cancel)
        if self._latest_key==state.result_id:
            self._stats['latest_result_hits']+=1;return self._latest
        force=(0.,-self._d['density_kg_m3']*self._d['gravity_m_s2'])
        raw=self._core.solve(state.array('mesh_nodes_m'),self._d['viscosity_pa_s'],force,
            top_pressure_pa=self._d['external_pressure_pa'],cancel=cancel)
        arrays={k:v for k,v in raw.items() if isinstance(v,np.ndarray)}
        metadata=dict(schema='atlas.free-surface-mechanics.v1',source_status='WORKING NON-CANON',
            definition=self._d,plan_id=self._plan_id,state_id=state.result_id,epoch_id=d['epoch_id'],time_s=d['time_s'],
            context_id=self._context_id,diagnostics=raw['diagnostics'],
            field_support='Q2 physical velocity nodes; discontinuous physical P1 pressure; mapped Gauss stress',
            pressure='physical, fixed by actual sloping surface traction; no mean removal')
        snapshot=RegionalMechanicalSnapshot(metadata,arrays)
        self._stats['mechanical_solves']+=1;self._latest_key,self._latest=state.result_id,snapshot
        return snapshot

    def mechanics(self,state,*,cancel=None):
        with self._operation(cancel):return self._mechanics(state,cancel)

    def _rate(self,state,cancel):
        mechanical=self._mechanics(state,cancel)
        mesh=state.array('mesh_nodes_m');v=mechanical.array('velocity_nodes_m_s')
        rate,projection=self._projection.rate(mesh[-1,:,1],v[-1])
        wmz=self._core.laplacian_mesh_velocity(mesh,rate,cancel=cancel)
        wm=np.zeros_like(mesh);wm[...,1]=wmz
        area,physical=cell_volume_and_flux(mesh,v);_,moving=cell_volume_and_flux(mesh,wm)
        L=self._d['scales']['length_m'];U=self._d['scales']['velocity_m_s']
        volume_scale=max(float(area.sum()),self._d['width_m']*self._d['reference_height_m'])
        if abs(projection['projection_volume_residual_m2_s'])>1e-10*U*L:
            raise TectonicsError('weak surface projection does not preserve boundary flux')
        continuity=float(np.max(np.abs(physical.sum(axis=-1))/area))*L/U
        if continuity>1e-10:raise TectonicsError('independent physical cell flux continuity failed')
        # Uniform material: ALE advects inventory with physical MINUS mesh flux.
        change=-self._d['density_kg_m3']*self._d['strike_width_m']*(physical-moving).sum(axis=-1)
        return wm,change,dict(projection,independent_cell_divergence_scaled=continuity,
            volume_scale_m2=volume_scale,physical_boundary_flux_m2_s=float(physical.sum()))

    def advance(self,state,duration_s,*,steps,cancel=None):
        """Explicit fixed partition, at most 256 accepted intervals including parent."""
        duration=scalar(duration_s,'duration',positive=True)
        if type(steps) is not int or not 1<=steps<=256:
            raise TectonicsError('surface accepted-step history may not exceed 256')
        with self._operation(cancel):
            d=self._validate(state,cancel)
            if d['accepted_steps']+steps>256:
                raise TectonicsError('surface accepted-step history may not exceed 256')
            end=d['time_s']+duration
            if not math.isfinite(end) or end<=d['time_s']:raise TectonicsError('unresolvable surface interval')
            original=state;current=state;diagnostics=[]
            for i in range(steps):
                start=d['time_s']+duration*i/steps;stop=d['time_s']+duration*(i+1)/steps;dt=stop-start
                if dt<=0.:raise TectonicsError('unresolvable surface substep')
                m=current.array('mesh_nodes_m');mass=current.array('cell_mass_kg')
                wm0,dm0,a0=self._rate(current,cancel)
                trial=m+dt*wm0;trialmass=mass+dt*dm0
                # A declared per-step geometric bound, not an automatic substep.
                height=np.diff(m[...,1],axis=0)
                if float(np.max(np.abs(dt*wm0[...,1])))>.2*float(np.min(height)):
                    raise TectonicsError('surface step exceeds geometric displacement envelope')
                intermediate=self._state(trial,trialmass,d['epoch_id'],stop,d['accepted_steps']+i+1,current.result_id)
                wm1,dm1,a1=self._rate(intermediate,cancel)
                final=.5*m+.5*(trial+dt*wm1)
                finalmass=.5*mass+.5*(trialmass+dt*dm1)
                area,_=cell_volume_and_flux(final)
                rho_width=self._d['density_kg_m3']*self._d['strike_width_m']
                density_error=float(np.max(np.abs(finalmass-rho_width*area)/np.maximum(rho_width*area,np.finfo(float).tiny)))
                mass_error=abs(float(finalmass.sum()-mass.sum()))/max(float(mass.sum()),np.finfo(float).tiny)
                oldarea,_=cell_volume_and_flux(m)
                volume_error=abs(float(area.sum()-oldarea.sum()))/a0['volume_scale_m2']
                if min(float(trialmass.min()),float(finalmass.min()))<=0. or max(density_error,mass_error,volume_error)>1e-9:
                    raise TectonicsError('free-surface geometric/material conservation failed')
                current=self._state(final,finalmass,d['epoch_id'],stop,d['accepted_steps']+i+1,current.result_id)
                diagnostics.append(dict(start_time_s=start,end_time_s=stop,volume_residual_scaled=volume_error,
                    mass_residual_scaled=mass_error,uniform_density_residual_scaled=density_error,
                    maximum_kinematic_projection_l2_m_s=max(a0['kinematic_projection_l2_m_s'],a1['kinematic_projection_l2_m_s'])))
            mechanical=self._mechanics(current,cancel)
            self._stats['accepted_steps']+=steps
            metadata=dict(schema='atlas.free-surface-advance.v1',initial_state_id=original.result_id,
                final_state_id=current.result_id,method='explicit SSP-RK2 material-surface and Laplacian mesh; no stabilising traction',
                source_status='WORKING NON-CANON',accepted_steps=steps,intervals=diagnostics,
                transport='homogeneous inventory advanced by physical minus mesh oriented face flux',
                boundary_normal_condition='continuous Q2 weak kinematic projection; projection error reported',
                physical_pressure_datum='traction',heat_or_heterogeneous_remap=False)
            return FreeSurfaceAdvance(current,mechanical,_json(metadata))
