"""Drained, saturated material parcels with solid conservation and loading memory.

Prescribed area/traction, fixed grain/fluid densities, one midpoint effective
stress per solid parcel. Not a transient pore-pressure or lateral-stress solver.
W02 mixed-cell transport lacks vertical ordering: it is NOT silently reinterpreted
as a compaction column. See docs/W03_COMPACTION.md.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
import hashlib
import math

import numpy as np

from atlas_tectonics._validation import TectonicsError, scalar, input_shape, snapshot, frozen
from atlas_tectonics._validation import finite_array
from atlas_tectonics.mechanics.compaction import CompactionParameters, compaction_response
from atlas_tectonics.materials.materials import MaterialCohort
from atlas_tectonics.integration.resources import select_budget, elements
from atlas_tectonics.integration.resources import check_event as _cancel
from atlas_tectonics.integration.resources import canonical_json as _json


def _bytes(value):
    a = snapshot(value, 'compaction state')
    owner = a
    while isinstance(owner, np.ndarray):
        owner = owner.base
    return owner


def _multiply(a, b, name):
    with np.errstate(over='ignore', under='ignore', invalid='ignore'):
        result = np.multiply(a, b)
    finite_array(result, name, TectonicsError, ' exceeds finite numerical range')
    return result


def _divide(a, b, name):
    with np.errstate(over='ignore', under='ignore', invalid='ignore', divide='ignore'):
        result = np.divide(a, b)
    finite_array(result, name, TectonicsError, ' exceeds finite numerical range')
    return result


def _columns(value, count, name, *, positive=False):
    a = snapshot(value, name, nonnegative=True)
    return np.broadcast_to(a, (count,))


def _metadata_work_bytes(parcels, conditions, labels):
    # Count text without first building/serialising the repeated catalogue.
    # JSON escaping, dictionaries and publication buffers are included; input
    # records already owned by the caller are not treated as zero-cost copies.
    characters = sum(len(x) for x in labels if x is not None)
    characters += sum(len(getattr(conditions, x)) for x in ('reservoir_id', 'provenance', 'pore_fluid_material_id'))
    components = 0
    for p in parcels:
        characters += sum(len(x) for x in (p.parcel_id, p.source_id, p.parameters.profile_id, p.parameters.provenance))
        components += len(p.components)
        for c in p.components:
            characters += sum(len(x) for x in (c.density_source, c.cohort.cohort_id, c.cohort.material_id, c.cohort.origin_id))
    return 64*characters+4096*components+8192*len(parcels)+65536


@dataclass(frozen=True, slots=True)
class GrainComponent:
    cohort: MaterialCohort
    solid_volume_fraction: float
    grain_density_kg_m3: float
    density_source: str

    def __post_init__(self):
        for name in ('solid_volume_fraction', 'grain_density_kg_m3'):
            object.__setattr__(self, name, scalar(getattr(self, name), name, positive=True))


@dataclass(frozen=True, slots=True)
class CompactionParcel:
    parcel_id: str
    source_id: str
    components: tuple[GrainComponent, ...]
    parameters: CompactionParameters

    def __post_init__(self):
        scalar(self.grain_density_kg_m3, 'mixture grain density', positive=True)

    @property
    def grain_density_kg_m3(self):
        return math.fsum(c.solid_volume_fraction*c.grain_density_kg_m3 for c in self.components)


@dataclass(frozen=True, slots=True)
class DrainedCompactionConditions:
    reservoir_id: str
    provenance: str
    pore_fluid_material_id: str
    pore_fluid_density_kg_m3: float
    gravity_m_s2: float

    def __post_init__(self):
        for name in ('reservoir_id', 'provenance', 'pore_fluid_material_id'):
            getattr(self, name)
        for name in ('pore_fluid_density_kg_m3', 'gravity_m_s2'):
            object.__setattr__(self, name, scalar(getattr(self, name), name, positive=True))


def _stress(parcels, solid, area, traction, conditions):
    # d sigma_eff = (rho_grain-rho_fluid)*g*dVsolid/A. The pore-volume
    # contribution cancels exactly in the drained hydrostatic approximation.
    contrast = np.array([p.grain_density_kg_m3-conditions.pore_fluid_density_kg_m3 for p in parcels])[:, None]
    increments = _multiply(_multiply(_divide(solid, area, 'solid thickness'), contrast,
                                    'buoyant sheet'), conditions.gravity_m_s2, 'effective stress increment')
    below = finite_array(np.cumsum(increments, axis=0), 'cumulative effective stress', TectonicsError, ' exceeds finite numerical range')
    above = np.vstack((np.zeros((1, solid.shape[1])), below[:-1]))
    half = _multiply(increments, .5, 'midpoint stress')
    return finite_array(traction+above+half, 'effective stress', TectonicsError, ' exceeds finite numerical range')


@dataclass(frozen=True, slots=True, init=False)
class CompactionState:
    """Immutable parcels x columns; solid payload is shared through transitions.

    Grain/pore volumes are m3, NOT thicknesses assumed invariant under area change.
    History retains only each parcel's maximum stress and the previous state ID;
    no growing trajectory or retained parent array chain is constructed.
    """
    parcels: tuple[CompactionParcel, ...]
    conditions: DrainedCompactionConditions
    shape: tuple[int, int]
    time_s: float
    epoch_id: str
    depth_reference_id: str
    source_state_id: str
    parent_state_id: str | None
    state_id: str
    _grain: bytes = field(repr=False)
    _state: bytes = field(repr=False)
    _area: bytes = field(repr=False)
    _traction: bytes = field(repr=False)

    def __init__(self, parcels, grain_volume_m3, void_ratio, maximum_effective_stress_pa, *,
                 area_m2, top_effective_stress_pa, conditions, time_s, epoch_id,
                 depth_reference_id, source_state_id, parent_state_id=None, budget=None, cancel=None):
        _cancel(cancel)
        now = scalar(time_s, 'time_s')
        shape = input_shape(grain_volume_m3)
        normal = type(maximum_effective_stress_pa) is str and maximum_effective_stress_pa == 'normally-consolidated'
        resource = select_budget(budget)
        metadata_bytes = _metadata_work_bytes(parcels, conditions, (epoch_id, depth_reference_id, source_state_id, parent_state_id))
        with resource.reserve(256*elements(shape)+metadata_bytes, category='compaction-state'):
            grain = snapshot(grain_volume_m3, 'grain volume', nonnegative=True)
            e = snapshot(void_ratio, 'void ratio', nonnegative=True)
            area = _columns(area_m2, shape[1], 'area_m2', positive=True)
            traction = _columns(top_effective_stress_pa, shape[1], 'top effective stress')
            stress = _stress(parcels, grain, area, traction, conditions)
            if normal:
                peak = stress  # Caller explicitly asserts no previous greater load.
            else:
                peak = snapshot(maximum_effective_stress_pa, 'maximum past stress', nonnegative=True)
            groups = {}
            for i, parcel in enumerate(parcels):
                groups.setdefault(parcel.parameters, []).append(i)
            for indices in groups.values():
                compaction_response(e[indices], stress[indices], peak[indices], stress[indices],
                    parcels[indices[0]].parameters, budget=resource, cancel=cancel)
            packed = np.stack((e, peak), axis=-1)
            for k, v in dict(parcels=parcels, conditions=conditions, shape=shape, time_s=now,
                    epoch_id=epoch_id, depth_reference_id=depth_reference_id, source_state_id=source_state_id,
                    parent_state_id=parent_state_id, _grain=_bytes(grain), _state=_bytes(packed),
                    _area=_bytes(area), _traction=_bytes(traction)).items():
                object.__setattr__(self, k, v)
            h = hashlib.sha256(_json(self.descriptor()))
            for payload in (self._grain, self._state, self._area, self._traction):
                h.update(payload)
            object.__setattr__(self, 'state_id', h.hexdigest())
            _cancel(cancel)

    def descriptor(self):
        return dict(schema='atlas.drained-compaction.v1', parcels=[asdict(p) for p in self.parcels],
            conditions=asdict(self.conditions), shape=self.shape, time_s=self.time_s,
            epoch_id=self.epoch_id, depth_reference_id=self.depth_reference_id,
            source_state_id=self.source_state_id, parent_state_id=self.parent_state_id,
            layout='solid parcels top-to-bottom, independent columns; SI; midpoint effective stress')

    @property
    def grain_volume_m3(self):
        return np.frombuffer(self._grain, dtype='f8').reshape(self.shape)

    @property
    def void_ratio(self):
        return np.frombuffer(self._state, dtype='f8').reshape(self.shape+(2,))[..., 0]

    @property
    def maximum_effective_stress_pa(self):
        return np.frombuffer(self._state, dtype='f8').reshape(self.shape+(2,))[..., 1]

    @property
    def area_m2(self):
        return np.frombuffer(self._area, dtype='f8')

    @property
    def top_effective_stress_pa(self):
        return np.frombuffer(self._traction, dtype='f8')


def compaction_geometry(state, *, budget=None, cancel=None):
    """Derived geometry/mass, not extra isostatic displacement or a surface datum."""
    _cancel(cancel)
    with select_budget(budget).reserve(256*elements(state.shape)+8192, category='compaction-geometry'):
        solid = state.grain_volume_m3
        pore = _multiply(solid, state.void_ratio, 'pore volume')
        bulk = finite_array(solid+pore, 'bulk volume', TectonicsError, ' exceeds finite numerical range')
        thickness = _divide(bulk, state.area_m2, 'bulk thickness')
        grain_mass = _multiply(solid, np.array([p.grain_density_kg_m3 for p in state.parcels])[:, None], 'grain mass')
        fluid_mass = _multiply(pore, state.conditions.pore_fluid_density_kg_m3, 'fluid mass')
        density = _divide(finite_array(grain_mass+fluid_mass, 'bulk mass', TectonicsError, ' exceeds finite numerical range'), bulk, 'bulk density')
        bottom = finite_array(np.cumsum(thickness, axis=0), 'depth below sediment top', TectonicsError, ' exceeds finite numerical range')
        top = np.vstack((np.zeros((1, state.shape[1])), bottom[:-1]))
        if np.any(bottom <= top):
            raise TectonicsError('parcel depth interval is unrepresentable')
        _cancel(cancel)
        return {k: frozen(v) for k, v in dict(pore_volume_m3=pore, bulk_volume_m3=bulk,
            bulk_thickness_m=thickness, grain_mass_kg=grain_mass, pore_fluid_mass_kg=fluid_mass,
            bulk_density_kg_m3=density, porosity=state.void_ratio/(1+state.void_ratio),
            top_depth_m=top, bottom_depth_m=bottom,
            effective_stress_pa=_stress(state.parcels, solid, state.area_m2, state.top_effective_stress_pa, state.conditions)).items()}


@dataclass(frozen=True, slots=True)
class CompactionTransition:
    state: CompactionState
    reservoir_id: str
    pore_fluid_out_m3: np.ndarray
    pore_fluid_out_kg: np.ndarray
    pore_volume_change_m3: np.ndarray


def advance_compaction(state, *, area_m2, top_effective_stress_pa, time_s, epoch_id,
                       available_reservoir_fluid_m3, store=None, budget=None, context=None,
                       controller=None, cache_policy=None, cancel=None):
    """One already-drained equilibrium update; positive exchange is to reservoir.

    The supplied time labels ordering, NOT a calculated drainage time. Fluid
    availability is one finite pooled reservoir stock in m3, shared across columns;
    simultaneous expelled fluid is available for drained redistribution. No clipping
    if net rebound needs more than is supplied.
    Column area is prescribed, not calculated from a lateral constitutive law.
    """
    from atlas_tectonics.integration.reuse import cached_compaction_response
    from atlas_tectonics.codecs.storage import ArrayStore
    now = scalar(time_s, 'time_s')
    available = scalar(available_reservoir_fluid_m3, 'pooled reservoir fluid', nonnegative=True)
    if budget is None and isinstance(store, ArrayStore):
        budget = store._budget
    resource = select_budget(budget); _cancel(cancel)
    with resource.reserve(320*elements(state.shape)+8192, category='compaction-transition'):
        area = _columns(area_m2, state.shape[1], 'area_m2', positive=True)
        traction = _columns(top_effective_stress_pa, state.shape[1], 'top effective stress')
        old_stress = _stress(state.parcels, state.grain_volume_m3, state.area_m2, state.top_effective_stress_pa, state.conditions)
        stress = _stress(state.parcels, state.grain_volume_m3, area, traction, state.conditions)
        response = np.empty(state.shape+(2,)); groups = {}
        for i, parcel in enumerate(state.parcels):
            groups.setdefault(parcel.parameters, []).append(i)
        for indices in groups.values():
            _cancel(cancel)
            response[indices] = cached_compaction_response(state.void_ratio[indices], old_stress[indices],
                state.maximum_effective_stress_pa[indices], stress[indices], state.parcels[indices[0]].parameters,
                store=store, budget=resource, context=context, controller=controller,
                cache_policy=cache_policy, cancel=cancel)
        # Compute interval exchange from delta-e, not subtraction of large absolute
        # pore inventories. Internal redistribution is allowed in the drained limit.
        per_parcel_out = _multiply(state.grain_volume_m3, state.void_ratio-response[..., 0], 'pore exchange')
        out = finite_array(np.sum(per_parcel_out, axis=0), 'net pore exchange', TectonicsError, ' exceeds finite numerical range')
        total_out = math.fsum(map(float, out))
        if not math.isfinite(total_out) or -total_out > available:
            raise TectonicsError('insufficient explicit reservoir fluid for saturated rebound')
        new = CompactionState(state.parcels, state.grain_volume_m3, response[..., 0], response[..., 1],
            area_m2=area, top_effective_stress_pa=traction, conditions=state.conditions,
            time_s=now, epoch_id=epoch_id, depth_reference_id=state.depth_reference_id,
            source_state_id=state.source_state_id, parent_state_id=state.state_id, budget=resource, cancel=cancel)
        return CompactionTransition(new, state.conditions.reservoir_id, frozen(out),
            frozen(_multiply(out, state.conditions.pore_fluid_density_kg_m3, 'fluid mass exchange')),
            frozen(-per_parcel_out))


def compaction_from_geological_column(initial_state, column_id, parameters, *, subdivisions,
        area_m2, top_effective_stress_pa, maximum_effective_stress_pa, conditions, budget=None, cancel=None):
    """Explicit W01 sediment description -> ordered fixed-solid parcels.

    Only authored top sediment layers, not sampled bodies/faults or W02 mixed-cell
    inventories. Unknown porosity/grain basis/history are never silently invented.
    A mixture needs its own supplied compaction law; component laws are not averaged.
    """
    column = initial_state.case.column(column_id)
    layers = tuple(l for l in column.layers if l.role == 'sediment')
    ids = {l.layer_id for l in layers}
    if type(subdivisions) is not dict or set(subdivisions) != ids or any(type(n) is not int or n <= 0 for n in subdivisions.values()):
        raise TectonicsError('positive explicit parcel count for each sediment layer required')
    count = sum(subdivisions.values())
    if count > 8192 or type(conditions) is not DrainedCompactionConditions:
        raise TectonicsError('parcel envelope or drained conditions invalid')
    area = scalar(area_m2, 'area_m2', positive=True)
    mats = {m.material_id: m for m in initial_state.case.materials}
    cohorts = {c.cohort.cohort_id: c.cohort for c in initial_state.case.cohorts}
    resource = select_budget(budget)
    component_count = sum(len(l.components)*subdivisions[l.layer_id] for l in layers)
    with resource.reserve(16384*count+4096*component_count+65536, category='compaction-column-import'):
        parcels = []; volumes = []; voids = []
        for layer in layers:
            _cancel(cancel)
            components = []
            for part in layer.components:
                cohort = cohorts[part.cohort_id]; material = mats[cohort.material_id]
                components.append(GrainComponent(cohort, part.solid_volume_fraction,
                    material.density_kg_m3, material.source_id))
            n = subdivisions[layer.layer_id]
            v = float(_divide(_multiply(_multiply(layer.bulk_thickness_m, 1-layer.porosity, 'solid thickness'), area, 'grain volume'), n, 'parcel grain volume'))
            for j in range(n):
                parcels.append(CompactionParcel(column_id+'/'+layer.layer_id+'/'+str(j), layer.source_id,
                    tuple(components), parameters[layer.layer_id]))
                volumes.append([v]); voids.append([layer.porosity/(1-layer.porosity)])
        return CompactionState(tuple(parcels), volumes, voids, maximum_effective_stress_pa,
            area_m2=area, top_effective_stress_pa=top_effective_stress_pa, conditions=conditions,
            time_s=initial_state.case.time_s, epoch_id=initial_state.case.epoch_id,
            depth_reference_id=initial_state.case.depth_reference_id, source_state_id=initial_state.state_id,
            budget=resource, cancel=cancel)


def save_compaction_state(state, store, *, budget=None, cancel=None):
    """Self-contained history-bearing state; external reservoir remains caller-owned."""
    return store.put(state.state_id, dict(grain_volume_m3=state.grain_volume_m3,
        void_ratio=state.void_ratio, maximum_effective_stress_pa=state.maximum_effective_stress_pa,
        area_m2=state.area_m2, top_effective_stress_pa=state.top_effective_stress_pa),
        state.descriptor(), budget=budget, cancel=cancel)


def load_compaction_state(store, state_id, *, budget=None):
    """Restore exact maximum-stress memory; parent/source IDs are lineage, not decoders."""
    resource = store._budget if budget is None else select_budget(budget)
    arrays = store.get(state_id, budget=resource)
    if arrays is None:
        return None
    meta = store.metadata(state_id)
    try:
        parcels = tuple(CompactionParcel(p['parcel_id'], p['source_id'],
            tuple(GrainComponent(MaterialCohort(**c['cohort']), c['solid_volume_fraction'],
                c['grain_density_kg_m3'], c['density_source']) for c in p['components']),
            CompactionParameters(**p['parameters'])) for p in meta['parcels'])
        state = CompactionState(parcels, **arrays, conditions=DrainedCompactionConditions(**meta['conditions']),
            time_s=meta['time_s'], epoch_id=meta['epoch_id'], depth_reference_id=meta['depth_reference_id'],
            source_state_id=meta['source_state_id'], parent_state_id=meta['parent_state_id'], budget=resource)
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise TectonicsError('invalid compaction state reconstruction') from exc
    return state
