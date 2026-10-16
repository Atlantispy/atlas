"""One full-cell FV collar around an unchanged interior mechanical grid.

This is an explicitly rigid, homogeneous exterior discretisation, not a
cut-cell or multi-plate junction law. Initial funding and global transactions
belong to the source owner. No artificial normal-flux repair is performed.
SPDX-License-Identifier: AGPL-3.0-only
"""
from contextlib import contextmanager
from dataclasses import dataclass, field
from fractions import Fraction
import hashlib
import math
from pathlib import Path
import weakref
import live_collar_patch as LIVE_COLLAR
import live_spatial_patch as LIVE_SPATIAL

import numpy as np
from .regional_caloric import component_sum as _component_sum

from ._validation import TectonicsError, scalar, frozen
from .integration_regional_evolution import RegionalVolumeMap
from .integration_volume import CartesianCell
from .regional_evolution3d import PreparedRegionalEvolution3D
from .regional_execution import RegionalMechanicalSnapshot
from .regional_execution3d import SIDES, _array, _hash, _json, _name, _cancel
from .regional_heat3d import PreparedRegionalHeat3D
from .regional_transport3d import PreparedRegionalTransport3D, ConservativeFaceFlow3D
from .resources import WorkBudget

_LOADED = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


@dataclass(frozen=True)
class RigidCollarMotion:
    angular_velocity_rad_s: tuple
    source_id: str

    def __post_init__(self):
        if (type(self.angular_velocity_rad_s) is not tuple or len(self.angular_velocity_rad_s) != 3 or
                any(type(v) not in (float, int) or not math.isfinite(v) for v in self.angular_velocity_rad_s)):
            raise TectonicsError('explicit finite three-component rigid angular velocity required')
        _name(self.source_id, 'rigid exterior source')

    def record(self):
        return dict(angular_velocity_rad_s=list(self.angular_velocity_rad_s), source_id=self.source_id,
                    rule='same physical omega cross actual global lever arm; one rigid exterior owner')


@dataclass(frozen=True)
class RegionalCollarState:
    fields: RegionalMechanicalSnapshot
    native_state: RegionalMechanicalSnapshot
    exterior_heat: RegionalMechanicalSnapshot | None = None

    @property
    def result_id(self):
        record = dict(fields_id=self.fields.result_id, native_state_id=self.native_state.result_id)
        if self.exterior_heat is not None:
            record['exterior_heat_id'] = self.exterior_heat.result_id
        return _hash(record)

    def record(self):
        record = dict(schema='atlas.regional-collar-state.v1', fields=self.fields.descriptor(),
                      native=self.native_state.descriptor(), result_id=self.result_id)
        if self.exterior_heat is not None:
            record['exterior_heat'] = self.exterior_heat.descriptor()
        return record

    def arrays(self):
        arrays = {k: self.fields.array(k) for k in self.fields.array_names}
        if self.exterior_heat is not None:
            arrays.update({'exterior_heat:'+k: self.exterior_heat.array(k) for k in self.exterior_heat.array_names})
        return arrays


@dataclass(frozen=True)
class RegionalCollarAdvance:
    state: RegionalCollarState
    source_stage: object
    endpoint: object
    flow: ConservativeFaceFlow3D
    transport: object
    heat: RegionalMechanicalSnapshot
    _transport_stage: object = field(default=None, repr=False, compare=False)
    _heat_stage: object = field(default=None, repr=False, compare=False)

    @property
    def transport_stage(self):
        return self._transport_stage

    @property
    def heat_stage(self):
        return self._heat_stage


def _result_bytes(result):
    if isinstance(result, RegionalMechanicalSnapshot):
        return result.nbytes
    return len(result._metadata)+sum(result.array(k).nbytes for k in result.array_names)


def _retain_stage(result, size, budget):
    lease = budget.reserve(size, category='regional-collar-stage-retained')
    lease.__enter__()
    try:
        weakref.finalize(result, lease.__exit__, None, None, None)
    except BaseException:
        lease.__exit__(None, None, None)
        raise


@dataclass(frozen=True, slots=True, weakref_slot=True, init=False)
class RegionalCollarSourceFlowStage:
    """Actual donor sources and physical flow, with NO material advection."""
    parent: RegionalCollarState
    source_stage: object
    flow: ConservativeFaceFlow3D
    inventory: RegionalMechanicalSnapshot
    heat_source_id: str
    _owner: object = field(repr=False, compare=False)

    def __init__(self, *args, **kwargs):
        raise TypeError('source/flow stages are issued by the prepared collar')

    @property
    def duration_s(self):
        return self.source_stage.inventory.descriptor()['duration_s']

    @property
    def parent_state_id(self):
        return self.parent.result_id

    @property
    def result_id(self):
        return _hash(self.record())

    def record(self):
        start = self.parent.native_state.descriptor()['time_s']
        return dict(schema='atlas.regional-collar-source-flow-stage.v1', plan_id=self._owner.plan_id,
            parent_state_id=self.parent_state_id, source_stage_id=self.source_stage.result_id,
            flow_id=self.flow.flow_id, inventory_id=self.inventory.result_id,
            start_time_s=start, end_time_s=start+self.duration_s,
            duration_s=self.duration_s, heat_source_id=self.heat_source_id,
            material_advection_applied=False, conduction_applied=False)


@dataclass(frozen=True, slots=True, weakref_slot=True, init=False)
class RegionalCollarTransportStage:
    """Issued donor/flow/advection result; not a completed thermal endpoint."""
    parent: RegionalCollarState
    source_stage: object
    flow: ConservativeFaceFlow3D
    transport: object
    heat_source_id: str
    _source_flow_stage: RegionalCollarSourceFlowStage = field(repr=False)
    _owner: object = field(repr=False, compare=False)
    spatial_result: object = field(default=None, repr=False)
    spatial_graph: object = field(default=None, repr=False)
    finite_proposal: object = field(default=None, repr=False)

    def __init__(self, *args, **kwargs):
        raise TypeError('transport stages are issued by the prepared collar')

    @property
    def source_flow_stage(self):
        return self._source_flow_stage

    @property
    def duration_s(self):
        return self.source_stage.inventory.descriptor()['duration_s']

    @property
    def parent_state_id(self):
        return self.parent.result_id

    @property
    def result_id(self):
        return _hash(self.record())

    def record(self):
        result = dict(schema='atlas.regional-collar-transport-stage.v1', plan_id=self._owner.plan_id,
            parent_state_id=self.parent_state_id, source_stage_id=self.source_stage.result_id,
            source_flow_stage_id=self._source_flow_stage.result_id,
            flow_id=self.flow.flow_id, transport_id=self.transport.result_id,
            duration_s=self.duration_s, heat_source_id=self.heat_source_id)
        if self.spatial_result is not None:
            result.update(spatial_result_id=self.spatial_result.result_id,
                          spatial_graph_id=self.spatial_graph.geometry_id)
        return result


@dataclass(frozen=True, slots=True, weakref_slot=True, init=False)
class RegionalCollarHeatStage:
    """Issued single heat solve bound to the actual transported inventories."""
    transport_stage_id: str
    heat: RegionalMechanicalSnapshot
    exterior_heat: object
    _owner: object = field(repr=False, compare=False)
    joined_result: object = field(default=None, repr=False)
    joined_mesh: object = field(default=None, repr=False)

    def __init__(self, *args, **kwargs):
        raise TypeError('heat stages are issued by a bound collar heat consumer')

    @property
    def result_id(self):
        return _hash(dict(transport_stage_id=self.transport_stage_id, heat_id=self.heat.result_id,
            exterior_heat_id=None if self.exterior_heat is None else self.exterior_heat.result_id))


class PreparedRegionalCollar3D:
    """Native Stokes inside; paired transport/conduction on the whole full grid.

    All cells are full regular boxes with exactly matching represented spacing,
    density, cp and k. One physical rigid field covers the collar. Caller funding
    must supply every cell and all six outer finite stocks; no refill or geometry
    inference occurs. Native source heating/history is applied only inside.
    """
    def __setattr__(self, key, value):
        if not key.startswith('_') and hasattr(self, key):
            raise TectonicsError('prepared collar definition is immutable')
        object.__setattr__(self, key, value)

    def __init__(self, native, volume_map, collar_cells, *, budget, component_registry=None,
                 mechanics_scope='rigid-collar'):
        if type(native) is not PreparedRegionalEvolution3D or type(volume_map) is not RegionalVolumeMap:
            raise TectonicsError('typed native evolution and actual physical volume map required')
        if type(budget) is not WorkBudget or native._resource is not budget:
            raise TectonicsError('collar and native evolution must share one WorkBudget')
        if mechanics_scope not in ('rigid-collar', 'complete-grid'):
            raise TectonicsError('explicit rigid-collar or complete-grid mechanics scope required')
        if (type(collar_cells) is not tuple or len(collar_cells) != 3 or
                any(type(p) is not tuple or len(p) != 2 or any(type(v) is not int for v in p)
                    for p in collar_cells)):
            raise TectonicsError('three explicit integer lower/upper padding pairs required')
        if mechanics_scope == 'complete-grid' and collar_cells != ((0, 0),)*3:
            raise TectonicsError('complete-grid mechanics requires exactly zero padding on every side')
        if mechanics_scope == 'rigid-collar' and any(v < 1 for p in collar_cells for v in p):
            raise TectonicsError('at least one whole collar cell on all six sides is required')
        self._mechanics_scope = mechanics_scope
        definition = native.descriptor()
        from .integration_regional_inventory import ComponentRegistry
        if component_registry is not None:
            if type(component_registry) is not ComponentRegistry:
                raise TectonicsError('explicit typed component registry required')
            component_registry.validate_native(native, source_id=volume_map.record()['source']['moving_id'])
            keys = tuple(sorted({(r['patch_id'], r['sublayer']) for r in volume_map.record()['cell_sources']}))
            if not set(keys) <= set(component_registry.source_keys):
                raise TectonicsError('registered initial prefix omits actual collar source geometry')
            if component_registry.source_keys != keys and not component_registry.initial_source_plate_ids:
                raise TectonicsError('additional original components require an explicit source plate domain')
        self._registry = component_registry
        if (mechanics_scope == 'rigid-collar' and native._material.internal_heating_w_m3 != 0 or
                native._rheology_family == 'bf23-memory'):
            raise TectonicsError('this rigid collar has no radiogenic or independent damage source law')
        volume_map.native_binding(native)
        self._native, self._budget, self._map = native, budget, volume_map
        self._closed = False
        self._active = False
        self._transport = self._heat = self._guard = None
        self.cells = tuple(n+sum(p) for n, p in zip(native.cells, collar_cells))
        if any(n > 24 for n in self.cells):
            raise TectonicsError('enlarged grid exceeds the existing transport cell-count admission')
        self._lower = tuple(p[0] for p in collar_cells)
        spacing = tuple(Fraction(v)/n for v, n in zip(native.lengths_m, native.cells))
        self.lengths_m = tuple(float(h*n) for h, n in zip(spacing, self.cells))
        if any(Fraction(v)/n != h for v, n, h in zip(self.lengths_m, self.cells, spacing)):
            raise TectonicsError('enlarged represented lengths do not preserve exact native spacing')
        self._inner = tuple(slice(a, a+n) for a, n in zip(self._lower, native.cells))
        self._nodes = tuple(slice(2*a, 2*(a+n)+1) for a, n in zip(self._lower, native.cells))
        # Include the optional independently transported material measure.
        self._work_bytes = 131072+2048*math.prod(self.cells)*(len(native._composition)+67)
        try:
            self._guard = budget.reserve(65536+2048*math.prod(self.cells), category='regional-collar-plan')
            self._guard.__enter__()
            projection = definition['projection']
            self._transport = PreparedRegionalTransport3D(self.cells, self.lengths_m,
                **projection, transport_method=definition['transport_method'], budget=budget)
            m = native._material
            self._heat = PreparedRegionalHeat3D(self.cells, self.lengths_m,
                m.density_kg_m3*m.heat_capacity_j_kg_k, m.conductivity_w_m_k, budget=budget)
            if (self._transport.volume_m3 != native._volume or self._heat._volume != native._volume or
                    not np.array_equal(self._transport._areas, native._transport._areas)):
                raise TectonicsError('enlarged arithmetic does not preserve native cell volumes/face areas')
            embedding = volume_map.record()['embedding']
            rational = lambda value: Fraction(int(value[0]), int(value[1]))
            self._basis = np.asarray([[float(rational(v)) for v in row] for row in embedding['basis']])
            self._origin = np.asarray([float(rational(v)) for v in embedding['origin_global_m']])
            self._spacing = tuple(float(h) for h in spacing)
            self._definition = dict(schema='atlas.regional-collar-plan.v1', native_plan_id=native.plan_id,
                volume_map_id=volume_map.volume_map_id, embedding=embedding,
                cells=list(self.cells), lengths_m=list(self.lengths_m), padding=[list(p) for p in collar_cells],
                transport_plan_id=self._transport.plan_id, heat_plan=self._heat.descriptor(),
                material=definition['material'], source_rule='native donor source audit inside only; rigid collar has no source',
                flow_rule='exact native inner faces; one actual rigid exterior; no collar projection',
                scope='full equal-volume homogeneous cells; funding/global motion/transactions are external owners')
            if component_registry is not None:
                self._definition['component_registry'] = component_registry.record()
            if mechanics_scope == 'complete-grid':
                if self._transport.plan_id != native._transport.plan_id:
                    raise TectonicsError('complete-grid transport must be the identical native discretisation')
                self._definition.update(mechanics_scope=mechanics_scope,
                    source_rule='actual native donor sources on every cell, booked once',
                    flow_rule='actual native face samples and conservative streams; no rigid exterior substitution',
                    scope='complete mechanical and FV grid; physical exterior funding remains separately required')
            self.plan_id = _hash(self._definition)
        except BaseException:
            self.close()
            raise

    def _verify(self):
        if self._closed or hashlib.sha256(Path(__file__).read_bytes()).hexdigest() != _LOADED:
            raise TectonicsError('closed or changed collar source')
        self._native._verify()

    @contextmanager
    def _operation(self, cancel):
        self._verify(); _cancel(cancel)
        if self._active:
            raise TectonicsError('regional collar is non-reentrant')
        self._active = True
        try:
            yield
            _cancel(cancel); self._verify()
        finally:
            self._active = False

    def descriptor(self):
        self._verify()
        import json
        return json.loads(_json(self._definition))

    @property
    def mechanics_scope(self):
        return self._mechanics_scope

    def heat_operator(self):
        """Borrow the actual enlarged operator; its lifetime remains this plan's."""
        self._verify()
        return self._heat

    def cell_geometries(self):
        """Exact boxes for a source owner's real full-cell coverage/debit proof."""
        self._verify()
        with self._budget.reserve(65536+4096*math.prod(self.cells), category='regional-collar-cell-geometry'):
            embedding = self._map.record()['embedding']
            q = lambda v: Fraction(int(v[0]), int(v[1]))
            origin = tuple(q(v) for v in embedding['origin_global_m'])
            basis = tuple(tuple(q(v) for v in row) for row in embedding['basis'])
            spacing = tuple(Fraction(v)/n for v, n in zip(self._native.lengths_m, self._native.cells))
            return tuple(CartesianCell(tuple((i-a)*h for i, a, h in zip(index, self._lower, spacing)),
                tuple((i-a+1)*h for i, a, h in zip(index, self._lower, spacing)),
                origin_m=origin, basis=basis, budget=self._budget) for index in np.ndindex(self.cells))

    def _exterior_operator(self, operator):
        from .integration_exterior_heat import PreparedFiniteExteriorHeat3D
        if (type(operator) is not PreparedFiniteExteriorHeat3D or operator.interior is not self._heat or
                operator._budget is not self._budget):
            raise TectonicsError('finite exterior heat must use this actual enlarged heat operator and budget')
        operator.descriptor()

    def _exterior_bound(self, state, operator):
        if state.exterior_heat is None:
            if operator is not None:
                raise TectonicsError('finite exterior thermal owner cannot be added to an existing collar state')
            return
        self._exterior_operator(operator)
        meta = state.exterior_heat.descriptor()
        if (meta.get('plan_id') != operator.plan_id or meta.get('time_s') != state.native_state.descriptor()['time_s'] or
                set(state.exterior_heat.array_names) != {'enthalpy_j'}):
            raise TectonicsError('finite exterior thermal plan, clock or state layout changed')
        _array(state.exterior_heat.array('enthalpy_j'), (len(operator._cells),), 'exterior heat', positive=True)

    def rigid_velocity(self, motion):
        self._verify()
        if type(motion) is not RigidCollarMotion:
            raise TectonicsError('typed physical rigid exterior motion required')
        with self._budget.reserve(1024*math.prod(self.cells)+65536, category='regional-collar-rigid-field'):
            local = np.stack(np.meshgrid(*(np.arange(2*n+1)*h/2-a*h
                for n, h, a in zip(self.cells, self._spacing, self._lower)), indexing='ij'), axis=-1)
            physical = self._origin+local@self._basis.T
            return np.cross(motion.angular_velocity_rad_s, physical).reshape(-1, 3)@self._basis

    def interior_velocity(self, motion):
        field = self.rigid_velocity(motion).reshape(*(2*n+1 for n in self.cells), 3)
        return field[self._nodes].reshape(-1, 3).copy()

    def wall_streams(self, wall_measures, motion, duration_s):
        """Exact linear-rigid outer sign split, projected once to native rates.

        Neither velocity samples nor any interior stream is changed. Native
        transport later multiplies these rates by the SAME duration; its binary
        volume difference is retained by the paired exterior projection account.
        """
        from .integration_wall_measures import WallMeasures
        from .integration_regional_inventory import _width, _project
        self._verify()
        if self._mechanics_scope == 'complete-grid':
            raise TectonicsError('complete-grid mechanics cannot replace solved outer streams with rigid wall measures')
        if (type(wall_measures) is not WallMeasures or wall_measures._resource is not self._budget or
                type(motion) is not RigidCollarMotion):
            raise TectonicsError('issued physical wall measures and typed rigid motion required')
        record = wall_measures.descriptor()
        with self._budget.reserve(65536+16*_width(record), category='regional-collar-exact-wall-streams'):
            q = lambda p: Fraction(int(p[0], 16), int(p[1], 16))
            dt = scalar(duration_s, 'wall duration', positive=True)
            if (record['collar_plan_id'] != self.plan_id or
                    q(record['end_time_s'])-q(record['start_time_s']) != Fraction(dt) or
                    tuple(map(Fraction, motion.angular_velocity_rad_s)) !=
                    tuple(q(v) for v in record['trajectory']['segments'][-1]['angular_velocity_rad_s'])):
                raise TectonicsError('exact outer wall geometry, interval or motion differs')
            streams = {s: (np.zeros(self._transport._shape('xyz'.index(s[0]), side=True)),
                           np.zeros(self._transport._shape('xyz'.index(s[0]), side=True))) for s in SIDES}
            expected = {(side, at) for side, values in streams.items()
                        for at in np.ndindex(values[0].shape)}
            seen = set()
            for row in record['faces']:
                if row['side'] not in ('x-', 'x+', 'y-', 'y+', 'z-', 'z+'):
                    raise TectonicsError('unknown exact physical outer face')
                side = row['side'][0]+('0' if row['side'][1] == '-' else '1')
                at = tuple(row['face_index'])
                if (side, at) not in expected or (side, at) in seen:
                    raise TectonicsError('each exact physical outer face must occur once')
                seen.add((side, at))
                for i, name in enumerate(('inward', 'outward')):
                    volume = q(row[name+'_exact_volume_m3'])
                    if volume < 0:
                        raise TectonicsError('physical sign-split stream must be nonnegative')
                    streams[side][i][at] = _project(volume/Fraction(dt))
            if seen != expected:
                raise TectonicsError('physical wall quadrature omitted an outer face')
            return {s: tuple(frozen(a) for a in values) for s, values in streams.items()}

    def _slice(self, name, value):
        return value[(slice(None), *self._inner)] if name == 'component_mass_kg' else value[self._inner]

    def _fields(self, state):
        self._verify()
        if type(state) is not RegionalCollarState or state.fields.descriptor().get('plan_id') != self.plan_id:
            raise TectonicsError('collar state belongs to another plan')
        self._native._fields(state.native_state)
        if state.fields.descriptor().get('time_s') != state.native_state.descriptor()['time_s']:
            raise TectonicsError('whole-grid and interior clocks disagree')
        if set(state.fields.array_names) != set(state.native_state.array_names):
            raise TectonicsError('whole-grid and interior material/history schema mismatch')
        arrays = {}
        for name in state.fields.array_names:
            shape = (len(self._native._composition), *self.cells) if name == 'component_mass_kg' else self.cells
            arrays[name] = _array(state.fields.array(name), shape, name)
            if not np.array_equal(self._slice(name, arrays[name]), state.native_state.array(name)):
                raise TectonicsError('whole-grid and actual interior state disagree')
        mass = np.sum(arrays['component_mass_kg'], axis=0)
        reference_mass = self._native._mass
        if 'material_quadrature_m3' in arrays:
            quadrature = arrays['material_quadrature_m3']
            if np.any(quadrature < 0):
                raise TectonicsError('negative collar material quadrature')
            empty = quadrature == 0
            if np.any(empty):
                if np.any(arrays['component_mass_kg'][:, empty] != 0) or any(np.any(a[empty] != 0)
                        for name, a in arrays.items() if name == 'enthalpy_j' or name.startswith('tracer:')):
                    raise TectonicsError('zero material quadrature retains collar stock')
                raise TectonicsError('zero material quadrature has no collar caloric state')
            reference_mass = self._native._material.density_kg_m3*quadrature
        if np.any(arrays['component_mass_kg'] < 0) or np.max(np.abs(mass/reference_mass-1)) > 2e-10:
            raise TectonicsError('full collar cells violate the existing Boussinesq reference inventory gate')
        temperature = arrays['enthalpy_j']/(_component_sum(arrays['component_mass_kg'])*self._native._material.heat_capacity_j_kg_k)
        lo, hi = self._native._material.temperature_range_k
        if np.any((temperature < lo) | (temperature > hi)):
            raise TectonicsError('collar temperature outside declared material law')
        for name, array in arrays.items():
            if name.startswith('tracer:') and np.any(array < 0):
                raise TectonicsError('negative carried collar history')
        if np.any(arrays['tracer:damage'] != 0):
            raise TectonicsError('rigid collar cannot silently discard damage evolution')
        return arrays

    def initial_state_from_funding(self, funding, owner, *, exterior_heat=None,
                                  exterior_enthalpy_j=None, exterior_state_id=None,
                                  material_quadrature_m3=None):
        """Consume one issued fresh physical funding proposal, without resampling.

        The enclosing transaction must reserve its source/remainder once. This
        initialiser neither commits that debit nor refreshes an evolved state.
        """
        from .integration_collar_geometry import FullCellFunding
        from .integration_regional_evolution import PreparedRegionalOwner
        self._verify()
        if (type(funding) is not FullCellFunding or type(owner) is not PreparedRegionalOwner or
                funding._resource is not self._budget or owner._native is not self._native):
            raise TectonicsError('actual shared-budget physical funding and native owner required')
        meta = funding.descriptor()
        state = owner.initial_state.native_state
        if (meta['collar_plan_id'] != self.plan_id or meta['owner_id'] != owner.owner_id or
                meta['volume_map_id'] != self._map.volume_map_id or
                meta['native_initial_state_id'] != state.result_id or
                meta['cells'] != list(self.cells) or meta['time_s'] != state.descriptor()['time_s']):
            raise TectonicsError('physical funding belongs to another grid, owner, state or clock')
        fields = funding.arrays()
        return self.initial_state(state, component_mass_kg=fields['component_mass_kg'],
            enthalpy_j=fields['enthalpy_j'],
            material_tracers={k[7:]: v for k, v in fields.items() if k.startswith('tracer:')},
            source_id=funding.funding_id, exterior_heat=exterior_heat,
            exterior_enthalpy_j=exterior_enthalpy_j, exterior_state_id=exterior_state_id,
            material_quadrature_m3=material_quadrature_m3)

    def initial_state(self, native_state, *, component_mass_kg, enthalpy_j, material_tracers, source_id,
                      exterior_heat=None, exterior_enthalpy_j=None, exterior_state_id=None,
                      material_quadrature_m3=None):
        self._verify(); _name(source_id, 'funded full-grid material source')
        with self._budget.reserve(self._work_bytes, category='regional-collar-admission'):
            fields = dict(component_mass_kg=component_mass_kg, enthalpy_j=enthalpy_j,
                          **{'tracer:'+k: v for k, v in material_tracers.items()})
            if 'material_quadrature_m3' in native_state.array_names or material_quadrature_m3 is not None:
                if 'material_quadrature_m3' not in native_state.array_names:
                    raise TectonicsError('dual collar admission requires its already funded native material quadrature')
                if native_state.descriptor()['parent_state_id'] is not None:
                    raise TectonicsError('material quadrature can only be seeded at fresh collar admission')
                if material_quadrature_m3 is None or material_quadrature_m3 is True:
                    quadrature = np.sum(component_mass_kg, axis=0)/self._native._material.density_kg_m3
                    quadrature[self._inner] = native_state.array('material_quadrature_m3')
                else:
                    quadrature = _array(material_quadrature_m3, self.cells, 'material quadrature')
                fields['material_quadrature_m3'] = quadrature
            exterior = None
            if exterior_heat is not None:
                self._exterior_operator(exterior_heat)
                _name(exterior_state_id, 'actual finite exterior thermal state')
                energy = _array(exterior_enthalpy_j, (len(exterior_heat._cells),), 'exterior heat', positive=True)
                exterior = RegionalMechanicalSnapshot(dict(schema='atlas.regional-collar-exterior-heat.v1',
                    plan_id=exterior_heat.plan_id, source_state_id=exterior_state_id, parent_id=None,
                    time_s=native_state.descriptor()['time_s']), dict(enthalpy_j=energy))
            elif exterior_enthalpy_j is not None or exterior_state_id is not None:
                raise TectonicsError('finite exterior thermal inputs require their actual coupled operator')
            result = RegionalCollarState(RegionalMechanicalSnapshot(dict(schema='atlas.regional-collar-fields.v1',
                plan_id=self.plan_id, source_id=source_id, parent_id=None,
                time_s=native_state.descriptor()['time_s']), fields), native_state, exterior)
            self._fields(result)
            self._exterior_bound(result, exterior_heat)
            return result

    def restore(self, record, arrays, *, exterior_heat=None):
        self._verify()
        with self._budget.reserve(self._work_bytes, category='regional-collar-restore'):
            if type(record) is not dict or record.get('schema') != 'atlas.regional-collar-state.v1':
                raise TectonicsError('typed collar checkpoint required')
            native_arrays = {k: v for k, v in arrays.items() if not k.startswith('exterior_heat:')}
            exterior_arrays = {k.removeprefix('exterior_heat:'): v for k, v in arrays.items() if k.startswith('exterior_heat:')}
            if bool(exterior_arrays) != ('exterior_heat' in record):
                raise TectonicsError('finite exterior thermal checkpoint is incomplete')
            fields = RegionalMechanicalSnapshot(record['fields'], native_arrays)
            native = RegionalMechanicalSnapshot(record['native'], {k: self._slice(k, fields.array(k)) for k in fields.array_names})
            exterior = None if not exterior_arrays else RegionalMechanicalSnapshot(record['exterior_heat'], exterior_arrays)
            state = RegionalCollarState(fields, native, exterior)
            self._fields(state)
            self._exterior_bound(state, exterior_heat)
            if state.result_id != record['result_id']:
                raise TectonicsError('collar checkpoint identity changed')
            return state

    def _flow(self, stage, motion, cancel, wall_measures=None, outer=None):
        if self._mechanics_scope == 'complete-grid':
            if motion is not None or wall_measures is not None or outer is not None:
                raise TectonicsError('complete-grid flow uses actual native mechanics, not a rigid outer override')
            descriptor = stage.flow.descriptor()
            if descriptor['plan_id'] != self._transport.plan_id:
                raise TectonicsError('actual complete-grid flow belongs to another native transport plan')
            descriptor.update(native_flow_id=stage.flow.flow_id, collar_plan_id=self.plan_id,
                mechanics_scope='complete-grid', interface_samples_unchanged=True,
                collar_correction_m_s=0., outer_stream_rule='unchanged actual native conservative streams')
            _cancel(cancel)
            return ConservativeFaceFlow3D(descriptor,
                {name: stage.flow.array(name) for name in stage.flow.array_names})
        rigid = self.rigid_velocity(motion).reshape(*(2*n+1 for n in self.cells), 3)
        raw = self._transport._sample_faces(rigid)
        corrected = [a.copy() for a in raw]
        for axis, label in enumerate('xyz'):
            at = list(self._inner); at[axis] = slice(self._lower[axis], self._lower[axis]+self._native.cells[axis]+1)
            native_raw = stage.flow.array('raw_normal_'+label+'_m_s')
            for end in (0, -1):
                if not np.array_equal(np.take(raw[axis][tuple(at)], end, axis=axis),
                                      np.take(native_raw, end, axis=axis)):
                    raise TectonicsError('rigid collar and native interface normal Gauss samples differ; no flux repair')
            raw[axis][tuple(at)] = native_raw
            corrected[axis][tuple(at)] = stage.flow.array('normal_'+label+'_m_s')
        areas, weights = self._transport._areas, self._transport._face_weights
        if wall_measures is not None and outer is None:
            outer = self.wall_streams(wall_measures, motion, stage.inventory.descriptor()['duration_s'])
        sum_ = lambda a: math.fsum(float(v) for v in np.asarray(a).flat)
        raw_flux = [np.sum(a*weights, axis=-1)*area for a, area in zip(raw, areas)]
        boundary_abs = math.fsum(sum_(np.take(np.abs(a), end, axis=axis)*weights)*areas[axis]
            for axis, a in enumerate(raw) for end in (0, -1))
        net = math.fsum(sign*sum_(np.take(f, end, axis=axis))
            for axis, f in enumerate(raw_flux) for end, sign in ((0, -1.), (-1, 1.)))
        eps = np.finfo(float).eps
        if abs(net) > (self._transport.divergence_rtol+256*eps)*boundary_abs:
            raise TectonicsError('collar outer flux incompatible with incompressibility')
        arrays, fluxes, scale = {}, [], 0.
        for axis, (label, old, new, area) in enumerate(zip('xyz', raw, corrected, areas)):
            pos = np.sum(np.maximum(new, 0)*weights, axis=-1)*area
            neg = np.sum(np.maximum(-new, 0)*weights, axis=-1)*area
            if outer is not None:
                for end in (0, 1):
                    at = [slice(None)]*3; at[axis] = 0 if end == 0 else -1
                    inward, outward = outer[label+str(end)]
                    pos[tuple(at)] = inward if end == 0 else outward
                    neg[tuple(at)] = outward if end == 0 else inward
            fluxes.append(pos-neg); scale = max(scale, float(np.max(pos+neg)))
            arrays.update({f'raw_normal_{label}_m_s': old, f'normal_{label}_m_s': new,
                f'positive_{label}_m3_s': pos, f'negative_{label}_m3_s': neg, f'net_{label}_m3_s': pos-neg})
        if outer is not None:
            boundary_abs = math.fsum(sum_(a) for values in outer.values() for a in values)
            net = math.fsum(sign*sum_(np.take(f, end, axis=axis))
                for axis, f in enumerate(fluxes) for end, sign in ((0, -1.), (-1, 1.)))
            if abs(net) > (self._transport.divergence_rtol+256*eps)*boundary_abs:
                raise TectonicsError('exact outer stream net violates the existing global incompressibility gate')
        residual = sum(np.diff(f, axis=i) for i, f in enumerate(fluxes))
        raw_scale = max(float(np.max(np.sum(np.abs(a)*weights, axis=-1)*area)) for a, area in zip(raw, areas))
        limit = self._transport.divergence_rtol*scale+256*eps*max(boundary_abs, raw_scale)
        if np.max(np.abs(residual)) > limit:
            raise TectonicsError('native plus rigid collar local continuity exceeds existing divergence gate')
        arrays['cell_net_volume_m3_s'] = residual
        _cancel(cancel)
        return ConservativeFaceFlow3D(dict(schema='atlas.regional3d-face-flow.v1', plan_id=self._transport.plan_id,
            source_result_id=stage.initial_mechanics.result_id, native_flow_id=stage.flow.flow_id,
            rigid_motion=motion.record(), collar_plan_id=self.plan_id,
            global_boundary_net_m3_s=net, local_residual_limit_m3_s=limit,
            corrected_max_cell_net_m3_s=float(np.max(np.abs(residual))),
            **({} if wall_measures is None else dict(wall_measure_id=wall_measures.measure_id,
                outer_stream_rule='exact physical linear-rigid face sign split; projected rates; original Gauss normals retained')),
            interface_samples_unchanged=True, collar_correction_m_s=0., scientific_acceptance=False), arrays)

    def _check_transport_stage(self, stage):
        self._verify()
        if type(stage) is not RegionalCollarTransportStage or stage._owner is not self:
            raise TectonicsError('actual transport stage from this prepared collar required')
        self._fields(stage.parent)
        if stage.source_stage.inventory.descriptor()['parent_state_id'] != stage.parent.native_state.result_id:
            raise TectonicsError('transport source stage has another native parent')

    def _check_source_flow_stage(self, stage):
        self._verify()
        if type(stage) is not RegionalCollarSourceFlowStage or stage._owner is not self:
            raise TectonicsError('actual source/flow stage from this prepared collar required')
        self._fields(stage.parent)
        if stage.source_stage.inventory.descriptor()['parent_state_id'] != stage.parent.native_state.result_id:
            raise TectonicsError('source/flow stage has another actual native parent')

    def _source_flow_stage(self, state, dt, rigid_motion, wall_measures, cancel, driving):
        arrays = self._fields(state)
        # Known-input refusals precede mechanics; reuse these projected rates.
        if self._mechanics_scope == 'complete-grid' and (rigid_motion is not None or wall_measures is not None):
            raise TectonicsError('complete-grid source flow requires actual native driving without rigid override')
        if self._mechanics_scope == 'rigid-collar' and type(rigid_motion) is not RigidCollarMotion:
            raise TectonicsError('rigid-collar source flow requires its explicit typed exterior motion')
        outer = None if wall_measures is None else self.wall_streams(wall_measures, rigid_motion, dt)
        stage = self._native.source_stage(state.native_state, dt, cancel=cancel, **driving)
        flow = self._flow(stage, rigid_motion, cancel, wall_measures, outer)
        donor = {k: a.copy() for k, a in arrays.items()}
        for name in donor:
            at = (slice(None), *self._inner) if name == 'component_mass_kg' else self._inner
            donor[name][at] = stage.inventory.array(name)
        inventory = RegionalMechanicalSnapshot(dict(schema='atlas.regional-collar-donor-inventory.v1',
            plan_id=self.plan_id, parent_state_id=state.result_id, source_stage_id=stage.result_id,
            duration_s=dt), donor)
        issued = object.__new__(RegionalCollarSourceFlowStage)
        for key, value in dict(parent=state, source_stage=stage, flow=flow, inventory=inventory,
                               heat_source_id=driving['heat_source'], _owner=self).items():
            object.__setattr__(issued, key, value)
        size = 8192+sum(_result_bytes(getattr(stage, k)) for k in
            ('inventory', 'driving', 'initial_mechanics', 'flow', 'source_audit'))
        size += _result_bytes(flow)+inventory.nbytes
        _retain_stage(issued, size, self._budget)
        self._verify(); _cancel(cancel)
        return issued

    def source_flow_stage(self, state, duration_s, *, rigid_motion=None, wall_measures=None, cancel=None, **driving):
        """Source/physical-flow branch point before any chosen advection method."""
        dt = scalar(duration_s, 'duration', positive=True)
        with self._operation(cancel), self._budget.reserve(self._work_bytes, category='regional-collar-advance'):
            return self._source_flow_stage(state, dt, rigid_motion, wall_measures, cancel, driving)

    def _transport_from_sources(self, stage, boundary_stocks, cancel):
        self._check_source_flow_stage(stage)
        if 'material_quadrature_m3' in stage.inventory.array_names:
            raise TectonicsError('material quadrature requires the joined spatial transport and mass-capacity heat route')
        donor = {k: stage.inventory.array(k) for k in stage.inventory.array_names}
        transport = self._transport.advect(donor['component_mass_kg'], donor['enthalpy_j'],
            {k[7:]: a for k, a in donor.items() if k.startswith('tracer:')}, stage.flow, stage.duration_s,
            boundary_stocks=boundary_stocks, cancel=cancel)
        issued = object.__new__(RegionalCollarTransportStage)
        for key, value in dict(parent=stage.parent, source_stage=stage.source_stage, flow=stage.flow,
                transport=transport, heat_source_id=stage.heat_source_id, _source_flow_stage=stage, _owner=self,
                spatial_result=None, spatial_graph=None, finite_proposal=None).items():
            object.__setattr__(issued, key, value)
        size = 8192+_result_bytes(transport)
        size += sum(_result_bytes(v) for rows in (transport.boundary_stocks, transport.exports) for v in rows.values())
        _retain_stage(issued, size, self._budget)
        self._verify(); _cancel(cancel)
        return issued

    def transport_from_sources(self, stage, *, boundary_stocks, cancel=None):
        """Apply the declared donor/MUSCL route exactly once to a source stage."""
        with self._operation(cancel), self._budget.reserve(self._work_bytes, category='regional-collar-advance'):
            return self._transport_from_sources(stage, boundary_stocks, cancel)

    def _spatial_layout(self, source, graph):
        from .integration_spatial_ale import SpatialALEGraph
        from .integration_mimetic_heat import _q
        self._check_source_flow_stage(source)
        if type(graph) is not SpatialALEGraph or graph._resource is not self._budget:
            raise TectonicsError('issued source-bound spatial graph on the same WorkBudget required')
        record = LIVE_COLLAR.graph_rows(graph); clock = source.record()
        # A registered collar carries one native field per registered
        # component: the source components, then any finite supplies. The
        # funding and every spatial graph name the registered source
        # components, which may exceed the components that source the
        # collar's own cells (an explicit source plate domain), and that
        # list is what the adoption compares.
        keys = (sorted({(r['patch_id'], r['sublayer']) for r in self._map.record()['cell_sources']})
                if self._registry is None else self._registry.source_keys)
        registered = None if self._registry is None else self._registry.registry_id
        if (record.get('schema') != 'atlas.source-bound-spatial-ale-graph.v1' or
                record['source_flow_stage_id'] != source.result_id or record['flow_id'] != source.flow.flow_id or
                record['collar_plan_id'] != self.plan_id or record['parent_state_id'] != source.parent_state_id or
                _q(record['start_time_s']) != Fraction(clock['start_time_s']) or
                _q(record['end_time_s']) != Fraction(clock['end_time_s']) or
                record['component_keys'] != [list(k) for k in keys] or
                (self._registry is None and len(keys) != len(self._native._composition)) or
                record.get('component_registry_id') != registered or
                record['source'] != self._map.record()['source']):
            raise TectonicsError('spatial graph source, parent, physical flow, clock or component layout differs')
        boxes = self.cell_geometries()
        indices = {}
        for gi, row in enumerate(record['cells']):
            if row['kind'] != 'collar':
                continue
            i = row['index']
            if (type(i) is not int or not 0 <= i < len(boxes) or i in indices or
                    row['physical_cell_id'] != boxes[i].cell_id or
                    _q(row['start_volume_m3']) != boxes[i].volume_m3 or
                    _q(row['end_volume_m3']) != boxes[i].volume_m3):
                raise TectonicsError('spatial graph must retain each actual full collar cell and its exact volume')
            indices[i] = gi
        if set(indices) != set(range(math.prod(self.cells))):
            raise TectonicsError('spatial graph omitted or duplicated a collar cell')
        return record, tuple(indices[i] for i in range(len(boxes)))

    def transport_from_spatial(self, source, result, graph, *, method, finite_proposal=None, cancel=None):
        """Adopt one explicitly selected issued joint solve; never advect again."""
        from .integration_spatial_transport import SpatialTransportResult
        from .integration_mimetic_heat import _q
        from .integration_regional_inventory import _width
        if method != 'implicit-upwind':
            raise TectonicsError('explicit method="implicit-upwind" selection required; no MUSCL fallback')
        if type(result) is not SpatialTransportResult or result._budget is not self._budget:
            raise TectonicsError('actual issued joint spatial transport result required')
        with LIVE_COLLAR.proposal_stack() as _collar_proposal:
            data = _collar_proposal.enter_context(LIVE_SPATIAL.transport_access(result))
            with self._operation(cancel), LIVE_SPATIAL.workspace(self._budget, self._work_bytes+8*LIVE_COLLAR.width(data, _width)):
                with LIVE_COLLAR.layout(self, source, graph) as (geometry, indices):
                    LIVE_COLLAR.same_scope(data, geometry)
                    solved_geometry, geometry_id = geometry, graph.geometry_id
                    if finite_proposal is not None:
                        from .integration_spatial_reservoir import FiniteStockProposal
                        if (type(finite_proposal) is not FiniteStockProposal or
                                finite_proposal._owner._budget is not self._budget or self._registry is None):
                            raise TectonicsError('finite adoption requires an issued registered same-budget stock proposal')
                        # One decode: the record already holds the graph that graph() would decode again.
                        proposal = _collar_proposal.enter_context(LIVE_COLLAR.proposal_access(finite_proposal))
                        LIVE_COLLAR.same_scope(proposal, geometry, data)
                        extended = proposal['graph']
                        n = len(geometry['cells'])
                        if (not LIVE_COLLAR.extension_matches(extended, geometry) or proposal['physical_cell_ids'] != [r['cell_id'] for r in geometry['cells']] or
                                any(row.get('kind') != 'inventory' for row in LIVE_COLLAR.inventory_tail(extended['cells'], n)) or
                                proposal['source_stage_id'] != source.result_id or
                                proposal['transport_parent_id'] != data['state_id'] or
                                extended['finite_inventory']['registry_id'] != self._registry.registry_id or
                                not LIVE_COLLAR.equal_records(proposal['stocks'], data['exact_input_stocks'])):
                            raise TectonicsError('finite extension changed actual physical graph, parent, source or input stocks')
                        solved_geometry, geometry_id = extended, LIVE_COLLAR.graph_identity(extended, _hash)
                    if (data['geometry_id'] != geometry_id or data['source_stage_id'] != source.result_id or
                            not LIVE_COLLAR.equal_records(data['cell_ids'], [r['cell_id'] for r in solved_geometry['cells']]) or
                            data['method'] != 'first-order backward-Euler upwind on exact-GCL integrated directed face measures'):
                        raise TectonicsError('joint result did not solve this actual source/flow graph')
                    donor = {k: source.inventory.array(k) for k in source.inventory.array_names}
                    mapped = {f'component_mass_kg:{i}': a for i, a in enumerate(donor['component_mass_kg'])}
                    mapped.update({k: a for k, a in donor.items() if k != 'component_mass_kg'})
                    if (set(data['exact_input_stocks']) != set(mapped) or set(data['exact_stocks']) != set(mapped) or
                            set(data['nonnegative_fields']) != set(mapped)-{'enthalpy_j'}):
                        raise TectonicsError('joint solve omitted, added or changed a nonnegative native material/history field')
                    arrays, binary = {}, result.arrays()
                    for name, old in mapped.items():
                        inputs, outputs = data['exact_input_stocks'][name], data['exact_stocks'][name]
                        projection = data['binary_stock_projection_accounts'][name]
                        values = binary['stock:'+name]
                        if (len(inputs) != len(solved_geometry['cells']) or len(outputs) != len(inputs) or
                                values.shape != (len(inputs),) or len(projection) != len(inputs)):
                            raise TectonicsError('joint field is not ordered on the complete actual cell graph')
                        for flat, gi in enumerate(indices):
                            if _q(inputs[gi]) != Fraction(float(old.flat[flat])):
                                raise TectonicsError('joint solve input differs from the actual pre-advection donor inventory')
                            if _q(outputs[gi]) != Fraction(float(values[gi]))+_q(projection[gi]):
                                raise TectonicsError('joint output projection differs from its retained exact stock')
                        arrays[name] = values[list(indices)].reshape(self.cells)
                    fields = {'component_mass_kg': np.stack([arrays.pop(f'component_mass_kg:{i}')
                                                            for i in range(len(self._native._composition))])}
                    fields.update(arrays)
                    metadata = dict(schema='atlas.regional-collar-spatial-transport.v1',
                        plan_id=self.plan_id, source_flow_stage_id=source.result_id, graph_id=graph.geometry_id,
                        spatial_result_id=result.result_id, spatial_parent_state_id=data['state_id'],
                        parent_state_id=source.parent_state_id, duration_s=source.duration_s,
                        method=method, accuracy='explicit first-order backward-Euler upwind; not donor/MUSCL fallback',
                        cell_indices=list(indices), exact_accounts='retained on the issued global SpatialTransportResult')
                    if finite_proposal is not None:
                        metadata.update(finite_proposal_id=finite_proposal.proposal_id, augmented_graph_id=geometry_id)
                    transport = RegionalMechanicalSnapshot(metadata, fields)
                    issued = object.__new__(RegionalCollarTransportStage)
                    for key, value in dict(parent=source.parent, source_stage=source.source_stage, flow=source.flow,
                            transport=transport, heat_source_id=source.heat_source_id, _source_flow_stage=source, _owner=self,
                            spatial_result=result, spatial_graph=graph, finite_proposal=finite_proposal).items():
                        object.__setattr__(issued, key, value)
                    _retain_stage(issued, 8192+transport.nbytes, self._budget)
                    self._verify(); _cancel(cancel)
                    return issued

    def _transport_stage(self, state, dt, rigid_motion, boundary_stocks, wall_measures, cancel, driving):
        if type(state) is RegionalCollarState and 'material_quadrature_m3' in state.fields.array_names:
            raise TectonicsError('material quadrature requires the joined spatial transport and mass-capacity heat route')
        source = self._source_flow_stage(state, dt, rigid_motion, wall_measures, cancel, driving)
        return self._transport_from_sources(source, boundary_stocks, cancel)

    def transport_stage(self, state, duration_s, *, rigid_motion=None, boundary_stocks,
                        wall_measures=None, cancel=None, **driving):
        """Donor sources and one full-grid advection; no heat solve or endpoint."""
        dt = scalar(duration_s, 'duration', positive=True)
        with self._operation(cancel), self._budget.reserve(self._work_bytes, category='regional-collar-advance'):
            return self._transport_stage(state, dt, rigid_motion, boundary_stocks, wall_measures, cancel, driving)

    def _heat_from_transport(self, stage, heat_boundaries, exterior_heat, cancel):
        self._check_transport_stage(stage)
        if stage.spatial_result is not None:
            raise TectonicsError('joint spatial transport requires one bound joint heat solve, not separate collar conduction')
        state, flow, transport, dt = stage.parent, stage.flow, stage.transport, stage.duration_s
        self._exterior_bound(state, exterior_heat)
        exterior = None
        if exterior_heat is None:
            heat = self._heat.advance(transport.array('enthalpy_j'), dt, heat_boundaries,
                0., source_id=stage.heat_source_id, cancel=cancel)
        else:
            # Fixed thermal capacities cannot silently represent a material
            # reservoir whose volume is being consumed or replenished.
            for cell in exterior_heat._cells:
                axis, end = 'xyz'.index(cell.side[0]), int(cell.side[1])
                if any(np.take(flow.array(f'{sign}_{cell.side[0]}_m3_s'), 0 if end == 0 else -1,
                        axis=axis)[cell.face_index] != 0 for sign in ('positive', 'negative')):
                    raise TectonicsError('fixed exterior thermal cell has advective crossing; evolving capacity needs its own material contract')
            heat = exterior_heat.advance(transport.array('enthalpy_j'), state.exterior_heat.array('enthalpy_j'),
                dt, heat_boundaries, 0., source_id=stage.heat_source_id,
                exterior_state_id=state.exterior_heat.result_id, cancel=cancel)
            exterior = RegionalMechanicalSnapshot(dict(schema='atlas.regional-collar-exterior-heat.v1',
                plan_id=exterior_heat.plan_id, source_state_id=heat.result_id,
                parent_id=state.exterior_heat.result_id,
                time_s=state.native_state.descriptor()['time_s']+dt),
                dict(enthalpy_j=heat.array('exterior_enthalpy_j')))
        issued = object.__new__(RegionalCollarHeatStage)
        for key, value in dict(transport_stage_id=stage.result_id, heat=heat,
                               exterior_heat=exterior, _owner=self, joined_result=None, joined_mesh=None).items():
            object.__setattr__(issued, key, value)
        _retain_stage(issued, 8192+heat.nbytes+(0 if exterior is None else exterior.nbytes), self._budget)
        self._verify(); _cancel(cancel)
        return issued

    def heat_from_transport(self, stage, heat_boundaries, *, exterior_heat=None, cancel=None):
        """One existing heat solve from transported enthalpy; no source replay."""
        with self._operation(cancel), self._budget.reserve(self._work_bytes, category='regional-collar-advance'):
            return self._heat_from_transport(stage, heat_boundaries, exterior_heat, cancel)

    def heat_from_spatial(self, stage, result, mesh, *, cancel=None):
        """Adopt a real joint HMM solve with current transported caloric fields."""
        from .integration_exterior_mesh import ExteriorMesh
        from .integration_mimetic_heat import MimeticHeatResult, _q, _enc
        from .integration_regional_inventory import _width
        self._check_transport_stage(stage)
        private_header = None
        if type(result).__module__ == 'private_heat_joined_consumer_r6':
            import private_heat_joined_consumer_r6 as J
            private_header = J.validate_collar(result, self, stage, mesh, cancel=cancel)
        if (stage.spatial_result is None or type(result) is not MimeticHeatResult and private_header is None or
                result._budget is not self._budget or type(mesh) is not ExteriorMesh or
                mesh._resource is not self._budget):
            raise TectonicsError('issued joint transport, actual HMM result and physical endpoint mesh required')
        if stage.parent.exterior_heat is not None:
            raise TectonicsError('legacy fixed exterior heat state cannot be dropped into a spatial thermal owner')
        with LIVE_COLLAR.heat_inputs(stage, mesh) as (geometry, transport, thermal):
            with self._operation(cancel), LIVE_SPATIAL.workspace(self._budget, self._work_bytes+2*sum(
                    LIVE_COLLAR.width(v, _width) for v in (geometry, transport, thermal))):
                meta = result.descriptor() if private_header is None else private_header
                expected_schema = 'atlas.mimetic-heat-advance.v1' if private_header is None else J.I.SCHEMA
                if (meta.get('schema') != expected_schema or
                        meta['state_id'] != stage.spatial_result.result_id or meta['duration_s'] != stage.duration_s or
                        meta['geometry_id'] != mesh.geometry_id or result._geometry.geometry_id != mesh.geometry_id or
                        thermal['funding_id'] != geometry['funding_id'] or
                        (thermal['source'] != geometry['source'] if private_header is None else
                         ('source' in thermal) != ('source' in geometry) or thermal.get('source') != geometry.get('source')) or
                        thermal['support_id'] != geometry['end_support_id'] or
                        thermal['trajectory_id'] != geometry['trajectory_id'] or
                        thermal['grid_id'] != geometry['grid_id'] or
                        _q(thermal['time_s']) != _q(geometry['end_time_s'])):
                    raise TectonicsError('joint thermal result has another actual transport, mesh, source, pose or interval')
                graph_rows = geometry['cells']; count = len(graph_rows)
                exact = transport['exact_stocks']; binary = stage.spatial_result.arrays()
                positive = {}
                for gi, row in enumerate(graph_rows):
                    volume = _q(row['end_volume_m3'])
                    if volume > 0:
                        positive[row['cell_id']] = gi
                    elif volume != 0 or any(_q(v[gi]) != 0 for v in exact.values()):
                        raise TectonicsError('zero-endpoint spatial cell retains material or heat')
                rows = thermal['cells']; logical = [r['logical_cell_id'] for r in rows]
                if len(set(logical)) != len(logical) or set(logical) != set(positive):
                    raise TectonicsError('thermal mesh must match every positive current spatial cell exactly once')
                order = [positive[k] for k in logical]
                nc = len(self._native._composition)
                masses = np.stack([binary['stock:component_mass_kg:'+str(i)] for i in range(nc)])
                if masses.shape != (nc, len(transport['cell_ids'])):
                    raise TectonicsError('current transported component layout changed before heat')
                # Same contiguous component reduction as the heat producer and
                # caloric field consumers. Density keeps its separate reduction.
                capacities = _component_sum(masses)*self._native._material.heat_capacity_j_kg_k
                expected_energy = binary['stock:enthalpy_j'][order]
                if (not np.array_equal(result.array('input_enthalpy_j'), expected_energy) or
                        not np.array_equal(result.array('input_capacity_j_k'), capacities[order])):
                    raise TectonicsError('HMM did not consume actual current transported heat and mass*Cp')
                if result.array('input_source_w').shape != (len(rows),):
                    raise TectonicsError('HMM source order differs from the actual thermal mesh')
                boxes = self.cell_geometries(); indices = {}
                capacity_projection = []
                cp = Fraction(self._native._material.heat_capacity_j_kg_k)
                for ti, (row, gi) in enumerate(zip(rows, order)):
                    ideal = cp*sum((_q(exact['component_mass_kg:'+str(i)][gi]) for i in range(nc)), Fraction(0))
                    capacity_projection.append(_enc(ideal-Fraction(float(capacities[gi]))))
                    if row['kind'] != 'collar':
                        continue
                    at = row['index']
                    # The exterior mesh names a collar cell by its grid coordinate;
                    # a differential thermal mesh copies the flat index of its ALE
                    # bounds. Both name one actual full-grid cell, whose identity
                    # and graph row are compared below either way.
                    if type(at) is int and 0 <= at < len(boxes):
                        flat = at
                    elif (type(at) is not list or len(at) != 3 or
                            any(type(i) is not int or not 0 <= i < n for i, n in zip(at, self.cells))):
                        raise TectonicsError('thermal collar index is not an actual full-grid coordinate')
                    else:
                        flat = int(np.ravel_multi_index(tuple(at), self.cells))
                    if (flat in indices or row['physical_cell_id'] != boxes[flat].cell_id or
                            graph_rows[gi]['kind'] != 'collar' or graph_rows[gi]['index'] != flat):
                        raise TectonicsError('thermal graph/collar physical cell mapping differs')
                    if result.array('input_source_w')[ti] != 0:
                        raise TectonicsError('native donor heat has already been booked; joined conduction cannot repeat it')
                    indices[flat] = ti
                if set(indices) != set(range(len(boxes))):
                    raise TectonicsError('joint thermal mesh omitted an actual collar cell')
                ordered = [indices[i] for i in range(len(boxes))]
                heat = RegionalMechanicalSnapshot(dict(schema='atlas.regional-collar-joint-heat.v1',
                    plan_id=self.plan_id, transport_stage_id=stage.result_id,
                    spatial_result_id=stage.spatial_result.result_id, joined_heat_id=result.result_id,
                    endpoint_mesh_id=mesh.geometry_id, duration_s=stage.duration_s,
                    cell_indices=ordered, thermal_logical_cell_ids=logical,
                    exact_capacity_projection_j_k=capacity_projection,
                    caloric_rule='sum actual binary component masses times Cp; identical to native endpoint fields',
                    energy_rule=('actual solved enthalpy unchanged; exact heat/face/storage accounts retained on issued HMM result'
                        if private_header is None else 'actual public enthalpy unchanged; full total-public cell/paired-face ledger retained in private result and CAS')), 
                    dict(enthalpy_j=result.array('enthalpy_j')[ordered].reshape(self.cells),
                         temperature_k=result.array('temperature_k')[ordered].reshape(self.cells)))
                issued = object.__new__(RegionalCollarHeatStage)
                for key, value in dict(transport_stage_id=stage.result_id, heat=heat, exterior_heat=None,
                        _owner=self, joined_result=result, joined_mesh=mesh).items():
                    object.__setattr__(issued, key, value)
                _retain_stage(issued, 8192+heat.nbytes, self._budget)
                self._verify(); _cancel(cancel)
                return issued

    def _endpoint_from_transport(self, stage, heated, cancel):
        self._check_transport_stage(stage)
        if (type(heated) is not RegionalCollarHeatStage or heated._owner is not self or
                heated.transport_stage_id != stage.result_id):
            raise TectonicsError('issued heat stage belongs to another actual transport interval')
        source, transport, heat = stage.source_stage, stage.transport, heated.heat
        fields = {k: transport.array(k) for k in stage.parent.fields.array_names}
        fields['enthalpy_j'] = heat.array('enthalpy_j')
        endpoint = self._native.endpoint_from_sources(source,
            {k: self._slice(k, a) for k, a in fields.items()}, transport_id=transport.result_id,
            heat_id=heat.result_id, cancel=cancel)
        result = RegionalCollarState(RegionalMechanicalSnapshot(dict(schema='atlas.regional-collar-fields.v1',
            plan_id=self.plan_id, source_id=source.result_id, parent_id=stage.parent_state_id,
            transport_id=transport.result_id, heat_id=heat.result_id,
            time_s=endpoint.state.descriptor()['time_s']), fields), endpoint.state, heated.exterior_heat)
        self._fields(result); _cancel(cancel); self._verify()
        return RegionalCollarAdvance(result, source, endpoint, stage.flow, transport, heat, stage, heated)

    def endpoint_from_transport(self, stage, heated, *, cancel=None):
        """Refresh mechanics using the one completed actual heat result."""
        with self._operation(cancel), self._budget.reserve(self._work_bytes, category='regional-collar-advance'):
            return self._endpoint_from_transport(stage, heated, cancel)

    def advance(self, state, duration_s, *, rigid_motion=None, boundary_stocks, heat_boundaries,
                exterior_heat=None, wall_measures=None, cancel=None, **driving):
        """One source/whole-grid transport/whole-grid conduction/interior refresh."""
        self._verify()
        dt = scalar(duration_s, 'duration', positive=True)
        with self._operation(cancel), self._budget.reserve(self._work_bytes, category='regional-collar-advance'):
            self._fields(state)
            self._exterior_bound(state, exterior_heat)
            stage = self._transport_stage(state, dt, rigid_motion, boundary_stocks, wall_measures, cancel, driving)
            heated = self._heat_from_transport(stage, heat_boundaries, exterior_heat, cancel)
            return self._endpoint_from_transport(stage, heated, cancel)

    def close(self):
        if getattr(self, '_active', False):
            raise TectonicsError('cannot close an active regional collar')
        if self._closed:
            return
        self._closed = True
        for obj in (self._heat, self._transport):
            if obj is not None:
                obj.close()
        if self._guard is not None:
            self._guard.__exit__(None, None, None); self._guard = None

    def __enter__(self):
        self._verify(); return self

    def __exit__(self, *_):
        self.close()
