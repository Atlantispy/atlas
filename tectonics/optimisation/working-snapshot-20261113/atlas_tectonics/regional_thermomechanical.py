"""Source-bound W07 rectangular thermal/material/mechanical intervals.

SPDX-License-Identifier: AGPL-3.0-only

One explicitly first-order split coupling interval: mechanics at the start,
conservative SSP-RK2 heat with that frozen velocity, then endpoint mechanics
from the new temperature. Heat substeps do NOT imply mechanical substeps.
Prescribed mesh translation changes world origin, never the local rectangular
mechanical metric. This is not a distorted-grid or free-surface integrator.
"""
from dataclasses import asdict, dataclass
import json
import math

import numpy as np

from ._validation import TectonicsError, scalar, input_shape, read_array, frozen
from .constitutive import DiffusiveScales, RheologyProfile, _cancel, _json
from .regional_execution import PreparedRegionalStokes2D, _name, _hash, _array_hash
from .regional_rheology import solve_regional_rheology, _validate_boundary_support
from .regional_transport import (PreparedHeatTransport, translate_material_regions,
                                 HeatBoundary, _pair)


_TEMPERATURE_SAMPLING = 'cell-mean-linear-centre-and-vertex-v1'


def _capture(value,name):
    return scalar(value,name) if input_shape(value)==() else frozen(read_array(value,name))


def _value_hash(value):
    array=np.asarray(value,dtype=np.float64)
    return _hash({'shape':array.shape,'data':_array_hash(array)})


def temperature_stress_sites(temperature_k):
    """Declared linear reconstruction: centre value and bilinear vertex value.

    Linear extrapolation at edges preserves affine temperatures. No clipping
    or silent change to a nonlinear law's admissible temperature range occurs.
    For sharp thermal discontinuities provide explicit stress-site samples to
    solve_regional_rheology instead of treating these reconstructed points as exact.
    """
    shape = input_shape(temperature_k)
    if len(shape) != 2 or not all(2 <= n <= 64 for n in shape):
        raise TectonicsError('regional cell means require 2..64 cells per axis')
    centre = read_array(temperature_k, 'temperature means')
    row = np.empty((shape[0], shape[1]+1))
    row[:, 1:-1] = .5*centre[:, :-1]+.5*centre[:, 1:]
    row[:, 0] = 1.5*centre[:, 0]-.5*centre[:, 1]
    row[:, -1] = 1.5*centre[:, -1]-.5*centre[:, -2]
    vertex = np.empty((shape[0]+1, shape[1]+1))
    vertex[1:-1] = .5*row[:-1]+.5*row[1:]
    vertex[0] = 1.5*row[0]-.5*row[1]
    vertex[-1] = 1.5*row[-1]-.5*row[-2]
    if not np.isfinite(vertex).all() or np.any(centre <= 0.) or np.any(vertex <= 0.):
        raise TectonicsError('reconstructed stress-site temperature outside positive finite kelvin')
    return frozen(centre), frozen(vertex)


@dataclass(frozen=True, slots=True)
class RegionalThermalBodyForce:
    """Linear Boussinesq TOTAL gravity force, not an inventory density model.

    Returning total force -rho0*g*(1-alpha*(T-Tref)) lets the mechanical wrapper
    subtract its reference pressure exactly once. Other supplied forces must
    exclude this gravity term. Positive z is up. No W04 support is added.
    """
    reference_density_kg_m3: float
    gravity_m_s2: float
    expansion_per_k: float
    reference_temperature_k: float
    source: str

    def __post_init__(self):
        for name in ('reference_density_kg_m3', 'reference_temperature_k'):
            object.__setattr__(self, name, scalar(getattr(self,name),name,positive=True))
        for name in ('gravity_m_s2', 'expansion_per_k'):
            object.__setattr__(self, name, scalar(getattr(self,name),name,nonnegative=True))
        _name(self.source, 'thermal body-force source')

    def force(self, centre, vertex):
        # Horizontal-face midpoints of the named bilinear temperature field.
        T = .5*vertex[:, :-1]+.5*vertex[:, 1:]
        factor = 1.-self.expansion_per_k*(T-self.reference_temperature_k)
        if not np.isfinite(factor).all() or np.any(factor <= 0.):
            raise TectonicsError('linear buoyancy density must stay finite and positive')
        force = -self.reference_density_kg_m3*self.gravity_m_s2*factor
        if not np.isfinite(force).all():
            raise TectonicsError('thermal gravity force outside finite SI range')
        return np.zeros((centre.shape[0], centre.shape[1]+1)), force


@dataclass(frozen=True, slots=True)
class RegionalThermomechanicalResult:
    initial_mechanics: object
    mechanics: object
    temperature_k: object
    material_regions: tuple | None
    material_mass_kg: object
    material_volume_fraction: object
    _metadata: bytes

    def descriptor(self):
        return json.loads(self._metadata)


def advance_regional_thermomechanics(plan, heat, profile, scales, temperature_k,
        other_force_u_n_m3, other_force_w_n_m3, boundary_values, duration_s, *,
        heat_steps, heat_boundaries, frame_id, epoch_id, time_s,
        thermal_source, material_source, force_source, boundary_source,
        heat_boundary_source, heat_source, thermal_sampling,
        source_w_m3=0., thermal_body_force=None, mesh_velocity_m_s=(0.,0.),
        material_regions=None, cancel=None):
    """Advance one bounded, source-explicit coupling interval.

    Mechanical loads/boundaries are frozen in translating local coordinates;
    heat data are explicitly sampled and held constant in local coordinates.
    Finite material rectangles require exactly uniform physical velocity. A
    nonuniform field is refused, not replaced by its mean. Frozen-damage BF23
    snapshots remain available separately: this interval does not advect damage.
    """
    if type(plan) is not PreparedRegionalStokes2D or type(heat) is not PreparedHeatTransport:
        raise TectonicsError('prepared regional mechanics and heat plans required')
    if type(profile) is not RheologyProfile or type(scales) is not DiffusiveScales:
        raise TectonicsError('typed source-explicit rheology and diffusive scales required')
    d, g = plan.descriptor(), heat.grid
    if (frame_id != d['frame_id'] or frame_id != g.frame_id or
        (d['nx'],d['nz'],d['width_m'],d['height_m']) != (g.nx,g.nz,g.width_m,g.height_m)):
        raise TectonicsError('thermal/mechanical frame or support mismatch')
    if profile.family == 'bf23-memory':
        raise TectonicsError('BF23 damage transport is not supplied by this thermal interval; use frozen snapshots')
    if thermal_sampling != _TEMPERATURE_SAMPLING:
        raise TectonicsError('explicit cell-mean-linear-centre-and-vertex-v1 reconstruction required')
    if input_shape(temperature_k)!=(g.nz,g.nx):
        raise TectonicsError('temperature means require matching rectangular support')
    _validate_boundary_support(d,boundary_values)
    if thermal_body_force is not None and type(thermal_body_force) is not RegionalThermalBodyForce:
        raise TectonicsError('typed total thermal gravity force required')
    if type(heat_steps) is not int or not 1 <= heat_steps <= 256:
        raise TectonicsError('one to 256 heat substeps required')
    duration_s = scalar(duration_s,'coupling duration',positive=True)
    time_s = scalar(time_s,'time')
    end = time_s+duration_s
    if not math.isfinite(end) or end <= time_s:
        raise TectonicsError('unresolvable coupling time')
    mesh = _pair(mesh_velocity_m_s,'mesh velocity')
    for value,name in ((epoch_id,'epoch'),(thermal_source,'thermal source'),
            (material_source,'material source'),(force_source,'other-force source'),
            (boundary_source,'mechanical boundary source'),(heat_source,'heat source'),
            (heat_boundary_source,'thermal boundary source')):
        _name(value,name)
    if not isinstance(heat_boundaries,dict) or set(heat_boundaries) != {'left','right','bottom','top'} or any(type(b) is not HeatBoundary for b in heat_boundaries.values()):
        raise TectonicsError('all four typed thermal boundaries required')
    if callable(source_w_m3) or any(callable(v) for bc in heat_boundaries.values()
            for v in (bc.inflow_temperature_k,bc.diffusion_value)):
        raise TectonicsError('coupled interval requires sampled constant-in-time heat data; use heat adapter for callbacks')
    if input_shape(source_w_m3) not in ((),(g.nz,g.nx)):
        raise TectonicsError('heat source requires cell support or scalar')
    for side,boundary in heat_boundaries.items():
        count=g.nz if side in ('left','right') else g.nx
        if any(v is not None and input_shape(v) not in ((),(count,)) for v in
               (boundary.inflow_temperature_k,boundary.diffusion_value)):
            raise TectonicsError('thermal boundary requires scalar or side face support')
    if material_regions is not None and (not isinstance(material_regions,(tuple,list)) or len(material_regions)>256):
        raise TectonicsError('bounded sequence of at most 256 material rectangles required')
    shapes=((g.nz,g.nx+1),(g.nz+1,g.nx))
    if any(input_shape(v)!=shape for v,shape in zip((other_force_u_n_m3,other_force_w_n_m3),shapes)):
        raise TectonicsError('other physical forces need complete MAC support')
    _cancel(cancel)
    # Charge coupling state plus all heat scratch to the mechanical shared cap.
    # Heat's own guard additionally honours its explicitly supplied owner budget.
    with plan._resource.reserve(heat.work_bytes+512*g.nx*g.nz+131072,
                                category='regional-thermal-coupling'):
        plan._context.verify()
        initial_temperature=frozen(read_array(temperature_k,'initial temperature means'))
        forces=tuple(frozen(read_array(v,'other body force')) for v in (other_force_u_n_m3,other_force_w_n_m3))
        boundary={s:{c:_capture(v,'mechanical boundary') for c,v in b.items()}
                  for s,b in boundary_values.items()}
        thermal_boundary={s:HeatBoundary(None if b.inflow_temperature_k is None else _capture(b.inflow_temperature_k,'inflow temperature'),
            b.diffusion_kind,_capture(b.diffusion_value,'thermal boundary value')) for s,b in heat_boundaries.items()}
        source=_capture(source_w_m3,'heat source')
        regions=None if material_regions is None else tuple(material_regions)
        binding={'frame_id':frame_id,'epoch_id':epoch_id,'start_time_s':time_s,
            'end_time_s':end,'start_origin_m':g.origin_m,'mesh_velocity_m_s':mesh,
            'thermal_source':thermal_source,'material_source':material_source,
            'force_source':force_source,'boundary_source':boundary_source,
            'heat_boundary_source':heat_boundary_source,'heat_source':heat_source,
            'thermal_sampling':thermal_sampling,'grid':asdict(g),'heat_steps':heat_steps,
            'conductivity_w_m_k':heat.conductivity,'heat_capacity_j_m3_k':heat.capacity,
            'initial_temperature_sha256':_value_hash(initial_temperature),
            'source_sha256':_value_hash(source),
            'thermal_boundary':{s:{'inflow':None if b.inflow_temperature_k is None else _value_hash(b.inflow_temperature_k),
                'kind':b.diffusion_kind,'diffusion':_value_hash(b.diffusion_value)} for s,b in thermal_boundary.items()},
            'thermal_body_force':None if thermal_body_force is None else asdict(thermal_body_force),
            'material_stock':None if regions is None else [asdict(r) for r in regions]}
        def mechanical(T,time,origin):
            centre,vertex=temperature_stress_sites(T)
            extra=(0.,0.) if thermal_body_force is None else thermal_body_force.force(centre,vertex)
            geometry_source=_hash({'origin_m':origin,'binding':binding})
            return solve_regional_rheology(plan,profile,scales,centre,vertex,
                forces[0]+extra[0],forces[1]+extra[1],boundary,frame_id=frame_id,
                epoch_id=epoch_id,time_s=time,thermal_source='w07-thermal:'+_hash({'source':thermal_source,'geometry':geometry_source}),
                material_source=material_source,force_source='w07-forcing:'+_hash({'other':force_source,'binding':binding}),
                boundary_source=boundary_source,cancel=cancel)
        initial=mechanical(initial_temperature,time_s,g.origin_m)
        u,w=initial.mechanics.array('u_m_s'),initial.mechanics.array('w_m_s')
        material=None
        if regions is not None:
            velocity=(float(u[0,0]),float(w[0,0]))
            # Only numerical roundoff around a uniform prescribed flow is allowed.
            tol=128*np.finfo(float).eps*max(float(np.max(np.abs(u))),float(np.max(np.abs(w))),np.finfo(float).tiny)
            if max(float(np.max(np.abs(u-velocity[0]))),float(np.max(np.abs(w-velocity[1]))))>tol:
                raise TectonicsError('finite rectangular material transport requires uniform physical motion')
            material=translate_material_regions(g,regions,velocity,duration_s,
                mesh_velocity_m_s=mesh,budget=plan._resource,cancel=cancel)
        evolved=heat.evolve(initial_temperature,u,w,duration_s,steps=heat_steps,boundaries=thermal_boundary,
            time_s=time_s,mesh_velocity_m_s=mesh,source_w_m3=source,cancel=cancel)
        final=mechanical(evolved['temperature_k'],end,evolved['origin_m'])
        account={k:v for k,v in evolved.items() if k!='temperature_k'}
        if math.isinf(account['timestep_limit_s']):
            account['timestep_limit_s']=None
            account['timestep_limit_status']='no advective or diffusive restriction for this field'
        metadata={'schema':'atlas.regional-thermomechanical-interval.v1','source_status':'WORKING NON-CANON',
            'binding':binding,'initial':initial.descriptor(),'final':final.descriptor(),
            'temperature_sha256':_array_hash(evolved['temperature_k']),'heat':account,
            'material':None if material is None else {k:v for k,v in material.items()
                if k not in ('cell_mass_kg','cell_volume_fraction','regions')},
            'coupling':'first-order frozen-velocity split; SSP-RK2 thermal substeps; endpoint current-law mechanics',
            'coordinates':'mechanics local x,z; world position = local position + reported origin',
            'force_ownership':'supplied other forces plus optional TOTAL thermal gravity; reference pressure removed once',
            'retained_history':'initial and final states only; no per-substep field history',
            'time_advanced':True}
        _cancel(cancel);plan._context.verify()
        return RegionalThermomechanicalResult(initial.mechanics,final.mechanics,evolved['temperature_k'],
            None if material is None else material['regions'],None if material is None else material['cell_mass_kg'],
            None if material is None else material['cell_volume_fraction'],_json(metadata))
