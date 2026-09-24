"""Time/support-matched producer inputs to existing quasi-static W07 mechanics.

No temporal interpolation, material law, transport or extra support is inferred.
Each evaluated state owns its total physical forces and boundary values once.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import threading

import numpy as np

from ._validation import TectonicsError, scalar, input_shape, read_array
from .constitutive import _cancel, _json
from .regional_execution import (PreparedRegionalStokes2D, RegionalMechanicalSnapshot,
    RegionalMechanicsScales, RegionalReferencePressure, _name, _hash)
from .regional_stokes import boundary_coordinates
from .resources import WorkBudget, select_budget


@dataclass(frozen=True, slots=True)
class RegionalInputContext:
    """All fields describe this same instant and stationary rectangular support."""
    nx: int
    nz: int
    width_m: float
    height_m: float
    frame_id: str
    vertical_datum: str
    epoch_id: str
    time_s: float
    origin_x_m: float
    origin_z_m: float

    def __post_init__(self):
        for key in ('nx', 'nz'):
            if type(getattr(self, key)) is not int or not 2 <= getattr(self, key) <= 64:
                raise TectonicsError('mechanical support needs 2..64 cells per direction')
        for key in ('width_m', 'height_m', 'time_s', 'origin_x_m', 'origin_z_m'):
            object.__setattr__(self, key, scalar(getattr(self, key), key,
                               positive=key in ('width_m', 'height_m')))
        for key in ('frame_id', 'vertical_datum', 'epoch_id'):
            _name(getattr(self, key), key)

    def geometry(self):
        return {key: value for key, value in asdict(self).items() if key != 'time_s'}


def _effects(value):
    if type(value) is not tuple or not 1 <= len(value) <= 32:
        raise TectonicsError('one to 32 explicit physical effect IDs required')
    for item in value: _name(item, 'physical effect ID')
    if len(set(value)) != len(value): raise TectonicsError('duplicate physical effect ID')
    return value


class RegionalInputBlock(RegionalMechanicalSnapshot):
    """Immutable producer block, captured with exact source/time/support metadata.

    Kinds/fields: material (centre, vertex) in Pa s; body-force (u,w) in N/m3;
    boundary (left_u, left_w, ... top_w) in m/s or Pa by boundary_types;
    surface-pressure (downward) in Pa at top normal corners+cell centres.
    Scalars are allowed only for boundaries/pressure; material/force supports
    must be explicit. Caller owns retained input storage after construction.
    """
    __slots__ = ()

    def __init__(self, context, kind, fields, *, source_id, producer_state_id,
                 sampling, effect_ids=(), boundary_types=None,
                 includes_total_gravity=False, budget=None, cancel=None):
        _cancel(cancel)
        if type(context) is not RegionalInputContext:
            raise TectonicsError('typed mechanical input context required')
        for value, name in ((source_id, 'source'), (producer_state_id, 'producer state'),
                            (sampling, 'sampling law')): _name(value, name)
        if type(includes_total_gravity) is not bool:
            raise TectonicsError('total gravity ownership must be explicit bool')
        c = context
        kinds = None
        if kind == 'material':
            shapes = {'centre': (c.nz, c.nx), 'vertex': (c.nz+1, c.nx+1)}
            units = {name: 'Pa s' for name in shapes}
            if effect_ids != (): raise TectonicsError('material properties are not an added physical force')
        elif kind == 'body-force':
            shapes = {'u': (c.nz, c.nx+1), 'w': (c.nz+1, c.nx)}
            units = {name: 'N/m3' for name in shapes}
            _effects(effect_ids)
        elif kind == 'boundary':
            kinds = PreparedRegionalStokes2D._pattern(boundary_types)
            shapes = {}
            units = {}
            for side, parts in kinds.items():
                for component, mode in parts.items():
                    name = side+'_'+component
                    shapes[name] = boundary_coordinates(c.nx,c.nz,c.width_m,c.height_m,side,component)[0].shape
                    units[name] = 'm/s' if mode == 'velocity' else 'Pa'
            _effects(effect_ids)
        elif kind == 'surface-pressure':
            shapes = {'downward': (c.nx+2,)}
            units = {'downward': 'Pa'}
            _effects(effect_ids)
        else:
            raise TectonicsError('unsupported regional mechanical input kind')
        if (kind != 'boundary' and boundary_types is not None or
                kind != 'body-force' and includes_total_gravity):
            raise TectonicsError('boundary/gravity metadata attached to wrong input kind')
        if type(fields) is not dict or set(fields) != set(shapes):
            raise TectonicsError('exact field coverage required for mechanical input block')
        for name, shape in shapes.items():
            supplied = input_shape(fields[name], name)
            if supplied != shape and not (kind in ('boundary','surface-pressure') and supplied == ()):
                raise TectonicsError('field shape does not match its physical support: '+name)
        size = sum(int(np.prod(shape)) for shape in shapes.values())
        with select_budget(budget).reserve(64*size+65536, category='mechanical-input-capture'):
            arrays = {}
            for name, shape in shapes.items():
                a = (np.full(shape, scalar(fields[name], name)) if input_shape(fields[name]) == ()
                     else read_array(fields[name], name))
                if a.shape != shape or kind == 'material' and np.any(a <= 0):
                    raise TectonicsError('material positivity or captured support failed')
                arrays[name] = a
            metadata = dict(schema='atlas.regional-input-block.v1', context=asdict(c), kind=kind,
                source_id=source_id, producer_state_id=producer_state_id, sampling=sampling,
                effect_ids=effect_ids, boundary_types=kinds, units=units,
                includes_total_gravity=includes_total_gravity,
                force_convention='total-physical-not-pressure-split', response_owner='W07')
            super().__init__(metadata, arrays)
        _cancel(cancel)

    @property
    def context(self): return RegionalInputContext(**self.descriptor()['context'])


@dataclass(frozen=True, slots=True, init=False)
class RegionalMechanicalRequest:
    material: RegionalInputBlock
    body_forces: tuple[RegionalInputBlock, ...]
    boundary: RegionalInputBlock
    surface_pressure: RegionalInputBlock | None
    request_id: str
    _record: bytes = field(repr=False)

    def __init__(self, material, body_forces, boundary, *, surface_pressure=None,
                 additional_displacement_ids=()):
        if type(body_forces) is not tuple or not 1 <= len(body_forces) <= 16:
            raise TectonicsError('one to 16 explicit body-force blocks, including known zero, required')
        if type(additional_displacement_ids) is not tuple or additional_displacement_ids:
            raise TectonicsError('W07 owns the response; W04/other displacement cannot be added')
        expected = [(material,'material'), (boundary,'boundary')]
        expected += [(item,'body-force') for item in body_forces]
        if surface_pressure is not None: expected.append((surface_pressure,'surface-pressure'))
        context = None; effects = []; gravity_owners = 0
        for item, kind in expected:
            if type(item) is not RegionalInputBlock or item.descriptor()['kind'] != kind:
                raise TectonicsError('typed material/force/boundary/pressure block required')
            d = item.descriptor()
            if context is None: context = d['context']
            if d['context'] != context:
                raise TectonicsError('mechanical inputs must match time, epoch, frame, datum, origin and grid')
            effects.extend(d['effect_ids']); gravity_owners += int(d['includes_total_gravity'])
        if len(set(effects)) != len(effects) or gravity_owners > 1:
            raise TectonicsError('physical force/load/motion contribution would be applied twice')
        if surface_pressure is not None:
            if boundary.descriptor()['boundary_types']['top']['w'] != 'traction':
                raise TectonicsError('surface pressure requires a top normal traction boundary')
            if np.any(boundary.array('top_w') != 0.):
                raise TectonicsError('surface pressure requires an unoccupied zero top-normal load slot')
        record = dict(schema='atlas.regional-mechanical-request.v1', context=context,
            material=material.result_id, body_forces=[x.result_id for x in body_forces],
            boundary=boundary.result_id, surface_pressure=None if surface_pressure is None else surface_pressure.result_id,
            effect_ids=effects, response_owner='W07', total_gravity_owners=gravity_owners,
            interpolation='none; supplied coincident snapshots', additional_displacement_ids=[])
        for key, value in dict(material=material, body_forces=body_forces, boundary=boundary,
                              surface_pressure=surface_pressure, request_id=_hash(record), _record=_json(record)).items():
            object.__setattr__(self, key, value)

    @property
    def context(self): return self.material.context
    @property
    def nbytes(self):
        return len(self._record)+sum(x.nbytes for x in (self.material,self.boundary,*self.body_forces,
                                   *((self.surface_pressure,) if self.surface_pressure is not None else ())))
    def descriptor(self): return json.loads(self._record)


def regional_thermal_gravity(context, temperature_k, law, *, producer_state_id,
                             thermal_source_id, effect_id='gravity', budget=None, cancel=None):
    """Replace gravity with the retained Boussinesq law at this thermal snapshot.

    This is the existing named cell-mean reconstruction, not new heat evolution.
    Inventory density/mass remain with the material producer. A request refuses
    this plus an earlier gravity block; the reference gradient stays solver-owned.
    """
    from .regional_thermomechanical import RegionalThermalBodyForce, temperature_stress_sites
    if type(context) is not RegionalInputContext or type(law) is not RegionalThermalBodyForce:
        raise TectonicsError('typed context and retained thermal-gravity law required')
    _name(thermal_source_id, 'thermal source'); _name(producer_state_id, 'thermal state')
    _name(effect_id, 'gravity effect')
    if input_shape(temperature_k) != (context.nz,context.nx):
        raise TectonicsError('temperature cell means must match the mechanical input context')
    _cancel(cancel)
    with select_budget(budget).reserve(256*(context.nx+1)*(context.nz+1)+65536,
                                       category='evolving-thermal-gravity'):
        centre, vertex = temperature_stress_sites(temperature_k)
        fu, fw = law.force(centre,vertex)
        import hashlib
        provenance = _hash(dict(thermal_source=thermal_source_id, law=asdict(law),
            temperature_sha256=hashlib.sha256(centre.tobytes()).hexdigest(), context=asdict(context)))
        return RegionalInputBlock(context,'body-force',dict(u=fu,w=fw),source_id=provenance,
            producer_state_id=producer_state_id,sampling='cell-mean-linear-centre-and-vertex-v1; horizontal-face midpoint',
            effect_ids=(effect_id,),includes_total_gravity=True,budget=budget,cancel=cancel)


def _sum_forces(blocks, name):
    # Neumaier compensated array sum, independent of force magnitude ordering.
    total = np.zeros_like(blocks[0].array(name)); correction = total.copy()
    with np.errstate(over='raise', invalid='raise', under='ignore'):
        try:
            for block in blocks:
                a = block.array(name); updated = total+a
                correction += np.where(np.abs(total) >= np.abs(a), (total-updated)+a, (a-updated)+total)
                total = updated
            result = total+correction
        except FloatingPointError as exc:
            raise TectonicsError('combined physical body force exceeds binary64') from exc
    if not np.isfinite(result).all(): raise TectonicsError('nonfinite total body force')
    return result


@dataclass(frozen=True, slots=True)
class EvolvingMechanicalResult:
    mechanics: RegionalMechanicalSnapshot
    result_id: str
    _record: bytes = field(repr=False)
    def descriptor(self): return json.loads(self._record)
    @property
    def array_names(self): return self.mechanics.array_names
    def array(self, name): return self.mechanics.array(name)
    @property
    def nbytes(self): return self.mechanics.nbytes+len(self._record)


class PreparedEvolvingRegionalMechanics:
    """Compatible changing inputs, one current operator and one latest response.

    These are quasi-static snapshots, not integrated displacement histories.
    Material coefficients refill only when changed; loads reuse existing factors.
    Grid, frame, pressure convention and boundary types remain fixed per plan.
    """
    def __setattr__(self, name, value):
        if getattr(self, '_sealed', False): raise AttributeError('evolving mechanics policy is immutable')
        object.__setattr__(self, name, value)

    def __init__(self, context, boundary_types, *, scales, viscosity_scale_pa_s,
                 physical_mean_pressure_pa=None, reference_pressure=None, rigid_constraints=None,
                 budget=None, cancel=None):
        _cancel(cancel)
        if type(context) is not RegionalInputContext or type(scales) is not RegionalMechanicsScales:
            raise TectonicsError('typed mechanical context and scales required')
        if reference_pressure is not None and type(reference_pressure) is not RegionalReferencePressure:
            raise TectonicsError('typed reference pressure required')
        self._geometry = _json(context.geometry())
        self._pattern = _json(PreparedRegionalStokes2D._pattern(boundary_types))
        self._options = _json(dict(scales=asdict(scales), viscosity_pa_s=scalar(viscosity_scale_pa_s,'viscosity scale',positive=True),
            physical_mean_pressure_pa=None if physical_mean_pressure_pa is None else scalar(physical_mean_pressure_pa,'pressure datum'),
            reference_pressure=None if reference_pressure is None else asdict(reference_pressure), rigid_constraints=rigid_constraints))
        self._resource = WorkBudget(128*1024**2, parent=select_budget(budget))
        self._guard = self._resource.reserve(65536, category='evolving-mechanics-owner')
        self._guard.__enter__()
        self._plan = self._latest = self._latest_guard = None
        self._material_id = None; self._request_id = None
        self._owner = threading.get_ident(); self._closed = self._active = False
        self._stats = dict(preparations=0, changed_outputs=0, latest_hits=0)
        self._sealed = True

    def evaluate(self, request, *, cancel=None):
        if self._closed or self._active or self._owner != threading.get_ident():
            raise TectonicsError('open idle evolving-mechanics plan on its owner thread required')
        _cancel(cancel)
        if type(request) is not RegionalMechanicalRequest:
            raise TectonicsError('typed coincident mechanical request required')
        context = request.context
        if _json(context.geometry()) != self._geometry or _json(request.boundary.descriptor()['boundary_types']) != self._pattern:
            raise TectonicsError('changed geometry/epoch/frame/boundary type requires a new mechanical plan')
        object.__setattr__(self, '_active', True)
        try:
            with self._resource.reserve(3*request.nbytes+1024*context.nx*context.nz+65536,
                                        category='evolving-mechanical-inputs'):
                material = request.material
                md = material.descriptor()
                if self._plan is None:
                    opts = json.loads(self._options)
                    opts['scales'] = RegionalMechanicsScales(**opts['scales'])
                    if opts['reference_pressure'] is not None:
                        opts['reference_pressure'] = RegionalReferencePressure(**opts['reference_pressure'])
                    plan = PreparedRegionalStokes2D(context.nx,context.nz,context.width_m,context.height_m,
                        boundary_types=json.loads(self._pattern), frame_id=context.frame_id,
                        vertical_datum=context.vertical_datum, material_source=material.result_id,
                        viscosity_center_pa_s=material.array('centre'), viscosity_vertex_pa_s=material.array('vertex'),
                        material_sampling=md['sampling'], budget=self._resource, cancel=cancel, **opts)
                    object.__setattr__(self,'_plan',plan)
                    object.__setattr__(self,'_material_id',material.result_id)
                    self._stats['preparations'] += 1
                elif material.result_id != self._material_id:
                    self._plan.update_viscosity(material.array('centre'),material.array('vertex'),
                        material_source=material.result_id,material_sampling=md['sampling'],cancel=cancel)
                    object.__setattr__(self,'_material_id',material.result_id)
                fu, fw = (_sum_forces(request.body_forces, name) for name in ('u','w'))
                boundary = {side:{name:request.boundary.array(side+'_'+name) for name in ('u','w')}
                            for side in json.loads(self._pattern)}
                if request.surface_pressure is not None:
                    boundary['top']['w'] = -request.surface_pressure.array('downward')
                mechanics = self._plan.solve(fu,fw,boundary,frame_id=context.frame_id,
                    epoch_id=context.epoch_id,time_s=context.time_s,force_source=request.request_id,
                    boundary_source=request.request_id,cancel=cancel)
                if self._request_id == request.request_id and self._latest is not None:
                    self._stats['latest_hits'] += 1
                    return self._latest
                record = dict(schema='atlas.evolving-mechanical-result.v1', request=request.descriptor(),
                    input_blocks=[x.descriptor() for x in (request.material,*request.body_forces,request.boundary)],
                    surface_pressure=None if request.surface_pressure is None else request.surface_pressure.descriptor(),
                    mechanical_result_id=mechanics.result_id, steady_snapshot=True, time_advanced=False,
                    response_owner='W07', displacement_added=False,
                    origin_x_m=context.origin_x_m, origin_z_m=context.origin_z_m,
                    coordinates='local x-right,z-up; add declared origin for world coordinates')
                result = EvolvingMechanicalResult(mechanics,_hash(record),_json(record))
                _cancel(cancel)
                guard = self._resource.reserve(2*len(result._record)+65536,
                                               category='evolving-mechanical-latest')
                guard.__enter__()
                old = self._latest_guard
                object.__setattr__(self,'_latest',result)
                object.__setattr__(self,'_latest_guard',guard)
                object.__setattr__(self,'_request_id',request.request_id)
                if old is not None: old.__exit__(None,None,None)
                self._stats['changed_outputs'] += 1
                return result
        except BaseException:
            object.__setattr__(self,'_latest',None); object.__setattr__(self,'_request_id',None)
            if self._latest_guard is not None:
                self._latest_guard.__exit__(None,None,None)
                object.__setattr__(self,'_latest_guard',None)
            raise
        finally:
            object.__setattr__(self,'_active',False)

    def statistics(self):
        return dict(self._stats, mechanics=None if self._plan is None else self._plan.statistics(),
                    resources=self._resource.statistics())

    def close(self):
        if self._closed: return
        if self._active or self._owner != threading.get_ident():
            raise TectonicsError('close evolving mechanics on its idle owner thread')
        try:
            if self._plan is not None: self._plan.close()
        finally:
            object.__setattr__(self,'_latest',None); object.__setattr__(self,'_closed',True)
            if self._latest_guard is not None: self._latest_guard.__exit__(None,None,None)
            self._guard.__exit__(None,None,None)

    def __enter__(self):
        if self._closed: raise TectonicsError('closed evolving mechanics')
        return self
    def __exit__(self,*_): self.close()
