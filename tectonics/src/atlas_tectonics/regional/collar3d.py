"""One full-cell FV collar around an unchanged interior mechanical grid.

This is an explicitly rigid, homogeneous exterior discretisation, not a
cut-cell or multi-plate junction law. Initial funding and global transactions
belong to the source owner. No artificial normal-flux repair is performed.
SPDX-License-Identifier: AGPL-3.0-only
"""
from contextlib import contextmanager
from dataclasses import dataclass, field
from fractions import Fraction
import math
from typing import TYPE_CHECKING, Any, cast
from atlas_tectonics._private.integration import live_collar_patch as LIVE_COLLAR
from atlas_tectonics._private.integration.geometry import live_spatial_patch as LIVE_SPATIAL

import numpy as np
from atlas_tectonics.regional.caloric import component_sum as _component_sum, component_workspace as _component_workspace

from atlas_tectonics._validation import TectonicsError, scalar, frozen
from atlas_tectonics.integration.geometry.volume import CartesianCell
from atlas_tectonics.regional.execution import RegionalMechanicalSnapshot
from atlas_tectonics.regional.execution3d import SIDES, _array, _hash, _json, _name, _cancel
from atlas_tectonics.regional.heat3d import PreparedRegionalHeat3D
from atlas_tectonics.regional.transport3d import PreparedRegionalTransport3D, ConservativeFaceFlow3D
from atlas_tectonics.integration.resources import _retain_result
from atlas_tectonics.integration.reuse import content_record
if TYPE_CHECKING:
    from collections.abc import Iterable
    from atlas_tectonics.integration.coupling.regional_inventory import ComponentRegistry



@dataclass(frozen=True)
class RigidCollarMotion:
    angular_velocity_rad_s: tuple
    source_id: str

    def __post_init__(self):
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
        object.__setattr__(self, key, value)

    def __init__(self, native, volume_map, collar_cells, *, budget, component_registry=None,
                 mechanics_scope='rigid-collar'):
        self._mechanics_scope = mechanics_scope
        definition = native.descriptor()
        if component_registry is not None:
            component_registry.validate_native(native, source_id=volume_map.record()['source']['moving_id'])
            tuple(sorted({(r['patch_id'], r['sublayer']) for r in volume_map.record()['cell_sources']}))
        self._registry = component_registry
        volume_map.native_binding(native)
        self._native, self._budget, self._map = native, budget, volume_map
        self._closed = False
        self._active = False
        self._transport = self._heat = self._guard = None
        self.cells = tuple(n+sum(p) for n, p in zip(native.cells, collar_cells))
        self._lower = tuple(p[0] for p in collar_cells)
        spacing = tuple(Fraction(v)/n for v, n in zip(native.lengths_m, native.cells))
        self.lengths_m = tuple(float(h*n) for h, n in zip(spacing, self.cells))
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
                self._definition.update(mechanics_scope=mechanics_scope,
                    source_rule='actual native donor sources on every cell, booked once',
                    flow_rule='actual native face samples and conservative streams; no rigid exterior substitution',
                    scope='complete mechanical and FV grid; physical exterior funding remains separately required')
            self.plan_id = _hash(content_record(self._definition))
        except BaseException:
            self.close()
            raise

    def _verify(self):
        self._native._verify()

    @contextmanager
    def _operation(self, cancel):
        self._verify(); _cancel(cancel)
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
        operator.descriptor()

    def _exterior_bound(self, state, operator):
        if state.exterior_heat is None:
            return
        self._exterior_operator(operator)
        _array(state.exterior_heat.array('enthalpy_j'), (len(operator._cells),), 'exterior heat', positive=True)

    def rigid_velocity(self, motion):
        self._verify()
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
        from atlas_tectonics.integration.coupling.regional_inventory import _width, _project
        self._verify()
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
            {(side, at) for side, values in streams.items()
                        for at in np.ndindex(values[0].shape)}
            seen = set()
            sides = {'x-': 'x0', 'x+': 'x1', 'y-': 'y0', 'y+': 'y1', 'z-': 'z0', 'z+': 'z1'}
            for row in record['faces']:
                signed_side = row['side']
                side = sides.get(signed_side) if type(signed_side) is str else None
                if side is None:
                    raise TectonicsError('unknown exact physical outer face')
                at = tuple(row['face_index'])
                seen.add((side, at))
                for i, name in enumerate(('inward', 'outward')):
                    volume = q(row[name+'_exact_volume_m3'])
                    streams[side][i][at] = _project(volume/Fraction(dt))
            return {s: tuple(frozen(a) for a in values) for s, values in streams.items()}

    def _slice(self, name, value):
        return value[(slice(None), *self._inner)] if name == 'component_mass_kg' else value[self._inner]

    def _fields(self, state, *, _caloric=False):
        self._verify()
        self._native._fields(state.native_state)
        arrays = {}
        for name in state.fields.array_names:
            shape = (len(self._native._composition), *self.cells) if name == 'component_mass_kg' else self.cells
            arrays[name] = _array(state.fields.array(name), shape, name)
        with _component_workspace(self.cells, len(self._native._composition), self._budget) as (scratch, _scratch_owner):
            mass = _component_sum(arrays['component_mass_kg'], out=np.empty(self.cells), scratch=scratch)
            if 'material_quadrature_m3' in arrays:
                pass
            temperature = arrays['enthalpy_j']/(mass*self._native._material.heat_capacity_j_kg_k)
            del scratch, _scratch_owner
        lo, hi = self._native._material.temperature_range_k
        return (arrays, mass, temperature) if _caloric else arrays

    def initial_state_from_funding(self, funding, owner, *, exterior_heat=None,
                                  exterior_enthalpy_j=None, exterior_state_id=None,
                                  material_quadrature_m3=None):
        """Consume one issued fresh physical funding proposal, without resampling.

        The enclosing transaction must reserve its source/remainder once. This
        initialiser neither commits that debit nor refreshes an evolved state.
        """
        self._verify()
        state = owner.initial_state.native_state
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
                if material_quadrature_m3 is None or material_quadrature_m3 is True:
                    represented = np.asarray(component_mass_kg, dtype=np.float64)
                    fields['component_mass_kg'] = represented
                    with _component_workspace(self.cells, len(self._native._composition), self._budget) as (scratch, _scratch_owner):
                        quadrature = _component_sum(represented, out=np.empty(self.cells), scratch=scratch)
                        del scratch, _scratch_owner
                    np.divide(quadrature, self._native._material.density_kg_m3, out=quadrature)
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
            native_arrays = {k: v for k, v in arrays.items() if not k.startswith('exterior_heat:')}
            exterior_arrays = {k.removeprefix('exterior_heat:'): v for k, v in arrays.items() if k.startswith('exterior_heat:')}
            fields = RegionalMechanicalSnapshot(record['fields'], native_arrays)
            native = RegionalMechanicalSnapshot(record['native'], {k: self._slice(k, fields.array(k)) for k in fields.array_names})
            exterior = None if not exterior_arrays else RegionalMechanicalSnapshot(record['exterior_heat'], exterior_arrays)
            state = RegionalCollarState(fields, native, exterior)
            self._fields(state)
            self._exterior_bound(state, exterior_heat)
            return state

    def _flow(self, stage, motion, cancel, wall_measures=None, outer=None):
        if self._mechanics_scope == 'complete-grid':
            descriptor = stage.flow.descriptor()
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
        self._fields(stage.parent)

    def _check_source_flow_stage(self, stage):
        self._verify()
        self._fields(stage.parent)

    def _source_flow_stage(self, state, dt, rigid_motion, wall_measures, cancel, driving):
        arrays = self._fields(state)
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
        _retain_result(issued, size, self._budget, 'regional-collar-stage-retained')
        self._verify(); _cancel(cancel)
        return issued

    def source_flow_stage(self, state, duration_s, *, rigid_motion=None, wall_measures=None, cancel=None, **driving):
        """Source/physical-flow branch point before any chosen advection method."""
        dt = scalar(duration_s, 'duration', positive=True)
        with self._operation(cancel), self._budget.reserve(self._work_bytes, category='regional-collar-advance'):
            return self._source_flow_stage(state, dt, rigid_motion, wall_measures, cancel, driving)

    def _transport_from_sources(self, stage, boundary_stocks, cancel):
        self._check_source_flow_stage(stage)
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
        size += sum(_result_bytes(v) for rows in (cast(Any, transport).boundary_stocks, cast(Any, transport).exports) for v in rows.values())
        _retain_result(issued, size, self._budget, 'regional-collar-stage-retained')
        self._verify(); _cancel(cancel)
        return issued

    def transport_from_sources(self, stage, *, boundary_stocks, cancel=None):
        """Apply the declared donor/MUSCL route exactly once to a source stage."""
        with self._operation(cancel), self._budget.reserve(self._work_bytes, category='regional-collar-advance'):
            return self._transport_from_sources(stage, boundary_stocks, cancel)

    def _spatial_layout(self, source, graph):
        from atlas_tectonics.integration.heat.mimetic_heat import _q
        self._check_source_flow_stage(source)
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
        for gi, row in enumerate(cast('Iterable[Any]', record['cells'])):
            if row['kind'] != 'collar':
                continue
            i = row['index']
            indices[i] = gi
        return record, tuple(indices[i] for i in range(len(boxes)))

    def transport_from_spatial(self, source, result, graph, *, method, finite_proposal=None, cancel=None):
        """Adopt one explicitly selected issued joint solve; never advect again."""
        from atlas_tectonics.integration.coupling.regional_inventory import _width
        with LIVE_COLLAR.proposal_stack() as _collar_proposal:
            data = _collar_proposal.enter_context(LIVE_SPATIAL.transport_access(result))
            with self._operation(cancel), LIVE_SPATIAL.workspace(self._budget, self._work_bytes+8*LIVE_COLLAR.width(data, _width)):
                with LIVE_COLLAR.layout(self, source, graph) as (geometry, indices):
                    LIVE_COLLAR.same_scope(data, geometry)
                    _, geometry_id = geometry, graph.geometry_id
                    if finite_proposal is not None:
                        # One decode: the record already holds the graph that graph() would decode again.
                        proposal = _collar_proposal.enter_context(LIVE_COLLAR.proposal_access(finite_proposal))
                        LIVE_COLLAR.same_scope(proposal, geometry, data)
                        extended = proposal['graph']
                        n = len(geometry['cells'])
                        if (not LIVE_COLLAR.extension_matches(extended, geometry) or proposal['physical_cell_ids'] != [r['cell_id'] for r in geometry['cells']] or
                                any(row.get('kind') != 'inventory' for row in LIVE_COLLAR.inventory_tail(extended['cells'], n)) or
                                proposal['source_stage_id'] != source.result_id or
                                proposal['transport_parent_id'] != data['state_id'] or
                                extended['finite_inventory']['registry_id'] != cast('ComponentRegistry', self._registry).registry_id or
                                not LIVE_COLLAR.equal_records(proposal['stocks'], data['exact_input_stocks'])):
                            raise TectonicsError('finite extension changed actual physical graph, parent, source or input stocks')
                        _, geometry_id = extended, LIVE_COLLAR.graph_content_identity(extended, _hash)
                    donor = {k: source.inventory.array(k) for k in source.inventory.array_names}
                    mapped = {f'component_mass_kg:{i}': a for i, a in enumerate(donor['component_mass_kg'])}
                    mapped.update({k: a for k, a in donor.items() if k != 'component_mass_kg'})
                    arrays, binary = {}, result.arrays()
                    for name, old in mapped.items():
                        _, _ = data['exact_input_stocks'][name], data['exact_stocks'][name]
                        values = binary['stock:'+name]
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
                    _retain_result(issued, 8192+transport.nbytes, self._budget, 'regional-collar-stage-retained')
                    self._verify(); _cancel(cancel)
                    return issued

    def _transport_stage(self, state, dt, rigid_motion, boundary_stocks, wall_measures, cancel, driving):
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
        _retain_result(issued, 8192+heat.nbytes+(0 if exterior is None else exterior.nbytes), self._budget, 'regional-collar-stage-retained')
        self._verify(); _cancel(cancel)
        return issued

    def heat_from_transport(self, stage, heat_boundaries, *, exterior_heat=None, cancel=None):
        """One existing heat solve from transported enthalpy; no source replay."""
        with self._operation(cancel), self._budget.reserve(self._work_bytes, category='regional-collar-advance'):
            return self._heat_from_transport(stage, heat_boundaries, exterior_heat, cancel)

    def heat_from_spatial(self, stage, result, mesh, *, cancel=None):
        """Adopt a real joint HMM solve with current transported caloric fields."""
        from atlas_tectonics.integration.heat.mimetic_heat import _q, _enc
        from atlas_tectonics.integration.coupling.regional_inventory import _width, _project
        from atlas_tectonics.integration.coupling.spatial_owner import _capacity_shape, _capacity_work_bytes, _capacity_pair_bytes
        self._check_transport_stage(stage)
        private_header = None
        if type(result).__module__ == 'atlas_tectonics._private.integration.heat.joined_consumer':
            from atlas_tectonics._private.integration.heat import joined_consumer as J
            private_header = J.validate_collar(result, self, stage, mesh, cancel=cancel)
        with LIVE_COLLAR.heat_inputs(stage, mesh) as (geometry, transport, thermal):
            with self._operation(cancel), LIVE_SPATIAL.workspace(self._budget, self._work_bytes+2*sum(
                    LIVE_COLLAR.width(v, _width) for v in (geometry, transport, thermal))) as _adoption_work:
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
                with LIVE_SPATIAL.workspace(self._budget, 65536+1024*(
                        4*len(transport['cell_ids'])+12*len(thermal['cells'])+64)) as _capacity_tables:
                    graph_rows = geometry['cells']; count = len(graph_rows)
                    exact = transport['exact_stocks']; stage.spatial_result.arrays()
                    positive = {}
                    for gi, row in enumerate(cast('Iterable[Any]', graph_rows)):
                        volume = _q(row['end_volume_m3'])
                        if volume > 0:
                            positive[row['cell_id']] = gi
                        elif volume != 0 or any(_q(v[gi]) != 0 for v in exact.values()):
                            raise TectonicsError('zero-endpoint spatial cell retains material or heat')
                    rows = thermal['cells']; logical = [r['logical_cell_id'] for r in rows]
                    order = [positive[k] for k in logical]
                    nc = len(self._native._composition)
                    cp_float = self._native._material.heat_capacity_j_kg_k
                    shapes = [_capacity_shape(exact, nc, gi, residual_cp=cp_float) for gi in order]
                    scratch_bytes = max((_capacity_work_bytes(bits) for bits, _ in shapes), default=0)
                    output_bytes = 8*len(rows)+sum(_capacity_pair_bytes(shape) for _, shape in shapes)
                    with LIVE_SPATIAL.workspace(self._budget, scratch_bytes+output_bytes) as _capacity_output:
                        capacities = np.empty(len(rows), dtype=np.float64)
                        capacity_projection = []
                        for ti, gi in enumerate(order):
                            _cancel(cancel)
                            mass = sum((_q(exact['component_mass_kg:'+str(i)][gi])
                                        for i in range(nc)), Fraction(0))
                            value = float(_project(mass)*cp_float)
                            capacities[ti] = value
                            capacity_projection.append(_enc(Fraction(cp_float)*mass-Fraction(value)))
                            del mass
                        boxes = self.cell_geometries(); indices = {}
                        for ti, (row, gi) in enumerate(zip(rows, order)):
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
                            indices[flat] = ti
                        ordered = [indices[i] for i in range(len(boxes))]
                        heat = RegionalMechanicalSnapshot(dict(schema='atlas.regional-collar-joint-heat.v1',
                            plan_id=self.plan_id, transport_stage_id=stage.result_id,
                            spatial_result_id=stage.spatial_result.result_id, joined_heat_id=result.result_id,
                            endpoint_mesh_id=mesh.geometry_id, duration_s=stage.duration_s,
                            cell_indices=ordered, thermal_logical_cell_ids=logical,
                            exact_capacity_projection_j_k=capacity_projection,
                            caloric_rule='exact component mass sum, projected once, then binary64 Cp multiplication',
                            energy_rule=('actual solved enthalpy unchanged; exact heat/face/storage accounts retained on issued HMM result'
                                if private_header is None else 'actual public enthalpy unchanged; full total-public cell/paired-face ledger retained in private result and CAS')),
                            dict(enthalpy_j=result.array('enthalpy_j')[ordered].reshape(self.cells),
                                 temperature_k=result.array('temperature_k')[ordered].reshape(self.cells)))
                        issued = object.__new__(RegionalCollarHeatStage)
                        for key, value in dict(transport_stage_id=stage.result_id, heat=heat, exterior_heat=None,
                                _owner=self, joined_result=result, joined_mesh=mesh).items():
                            object.__setattr__(issued, key, value)
                        _retain_result(issued, 8192+heat.nbytes, self._budget, 'regional-collar-stage-retained')
                        self._verify(); _cancel(cancel)
                        return issued

    def _endpoint_from_transport(self, stage, heated, cancel):
        self._check_transport_stage(stage)
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
