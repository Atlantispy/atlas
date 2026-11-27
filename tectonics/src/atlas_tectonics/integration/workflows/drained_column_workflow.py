"""Bounded W01/W02/W03 assembly: stationary, drained, fixed-area columns.

Thermal cooling/support remain fixed-reference diagnostics, not heat transport
on the changing pore geometry. Ordered solid parcels are never inferred from a
mixed W02 inventory. See docs/W03_WORKFLOW.md for the supported physical scope.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
import hashlib
import json
import math
from typing import Iterator

import numpy as np

from atlas_tectonics._validation import TectonicsError, scalar, frozen, input_shape, snapshot
from atlas_tectonics.mechanics.compaction_columns import (CompactionState, DrainedCompactionConditions,
    advance_compaction, compaction_from_geological_column, compaction_geometry,
    save_compaction_state, load_compaction_state, _json, _cancel)
from atlas_tectonics.materials.constitutive import BoussinesqMaterial
from atlas_tectonics.materials.materials import (MaterialState, MaterialCohort, MaterialBoundary,
    MaterialEvent, advect_materials, apply_material_event,
    save_material_state, load_material_state)
from atlas_tectonics.planet.parameters import PlateCoolingParameters, ThermalParameters
from atlas_tectonics.plates.cooling import finite_plate_temperature, plate_cooling_heat
from atlas_tectonics.plates.integrals import plate_cooling_deficit_change
from atlas_tectonics.mechanics.stokes_execution import _factored_scale
from atlas_tectonics.codecs.storage import ArrayStore
from atlas_tectonics.thermal.thermal_support import ThermalSupportParameters, _plate_material
from atlas_tectonics.crust.precursor_sampling import _profile_mean, PrecursorSamplingLimits
from atlas_tectonics.regional.workflow import (RegionalWorkflowState, save_regional_workflow,
                                load_regional_workflow)
from atlas_tectonics.integration.resources import select_budget
from atlas_tectonics.integration.resources import json_sha256
from atlas_tectonics.integration.reuse import (ExecutionContext, ReuseController, cached_plate_temperature, content_record,
                    cached_plate_thermal_response)


def _id(record):
    return hashlib.sha256(_json(record)).hexdigest()


class W03ExecutionContext:
    """Prepare each actual backend once; retain all existing source checks."""
    def __init__(self):
        self.reference = ExecutionContext('reference')
        try:
            self.scipy = ExecutionContext('scipy')
        except BaseException:
            self.reference.close()
            raise

    @property
    def identity(self):
        return json_sha256(dict(reference=self.reference.identity, scipy=self.scipy.identity), _json)

    def close(self):
        try:
            self.reference.close()
        finally:
            self.scipy.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


@contextmanager
def _execution(context) -> Iterator[W03ExecutionContext]:
    if context is None:
        with W03ExecutionContext() as owned:
            yield owned
    else:
        yield context


@dataclass(frozen=True, slots=True)
class W03ThermalBinding:
    source_state_id: str
    workflow_id: str
    sample_id: str
    column_id: str
    profile_id: str
    history_source_id: str
    epoch_id: str
    depth_reference_id: str
    reference_time_s: float
    reference_age_s: float
    cooling_model: PlateCoolingParameters
    buoyancy_material: BoussinesqMaterial
    support_parameters: ThermalSupportParameters
    depth_edges_m: tuple
    temperature_tolerance_k: float
    initial_max_mean_error_k: float

    def __post_init__(self):
        _plate_material(self.cooling_model, self.buoyancy_material, self.support_parameters)
        scalar(self.reference_time_s, 'reference time')
        scalar(self.reference_age_s, 'reference cooling age', nonnegative=True)
        scalar(self.temperature_tolerance_k, 'temperature tolerance', nonnegative=True)
        scalar(self.initial_max_mean_error_k, 'initial mean error', nonnegative=True)


def _reconcile(initial, workflow, column_id, model, material, support, edges, tolerance, budget, cancel):
    _plate_material(model, material, support)
    shape = input_shape(edges)
    if len(shape) != 1 or not 2 <= shape[0] <= 8193:
        raise TectonicsError('bounded one-dimensional thermal depth edges required')
    tolerance = scalar(tolerance, 'temperature tolerance', nonnegative=True)
    column = initial.case.column(column_id)
    profile = next(t for t in initial.case.thermal_profiles if t.profile_id == column.thermal_profile_id)
    history = next(h for h in initial.cooling_history if h.profile_id == profile.profile_id)
    age = scalar(initial.case.time_s-history.start_time_s, 'cooling age', nonnegative=True)
    with budget.reserve(128*shape[0]+8192, category='w03-thermal-reconciliation'):
        z = snapshot(edges, 'thermal depth edges', nonnegative=True)
        # Constructor checks the support owner, material and exact finite plate domain.
        base = dict(source_state_id=initial.state_id, workflow_id=workflow.workflow_id,
            sample_id=workflow.initial_samples.sample_id, column_id=column_id,
            profile_id=profile.profile_id, history_source_id=history.source_id,
            epoch_id=initial.case.epoch_id, depth_reference_id=initial.case.depth_reference_id,
            reference_time_s=initial.case.time_s, reference_age_s=age,
            cooling_model=model, buoyancy_material=material, support_parameters=support,
            depth_edges_m=tuple(float(x) for x in z), temperature_tolerance_k=tolerance)
        W03ThermalBinding(**base, initial_max_mean_error_k=0.)
        finite_plate_temperature(z[[0, -1]], age, model, budget=budget, cancel=cancel)
        selected = finite_plate_temperature(z[:-1], age, model, cell_bottom_m=z[1:], budget=budget, cancel=cancel)
        limits = PrecursorSamplingLimits()
        error = 0.
        for a, b, t in zip(z, z[1:], selected):
            _cancel(cancel)
            mean, quadrature_error = _profile_mean(profile, a, b, initial.case.time_s, None, limits, cancel)
            error = max(error, abs(mean-t)+quadrature_error)
        return W03ThermalBinding(**base, initial_max_mean_error_k=error)


def _inventory(compaction, cohorts, pore_cohort):
    """Project ordered parcels to W02 phase amounts; never invert that projection."""
    rows = {c.cohort_id: i for i, c in enumerate(cohorts)}
    groups = {}
    for i, parcel in enumerate(compaction.parcels):
        for part in parcel.components:
            groups.setdefault(part.cohort.cohort_id, []).append((i, part.solid_volume_fraction))
    h = np.zeros((len(cohorts), compaction.shape[1]))
    solid = compaction.grain_volume_m3
    for key, group in groups.items():
        indices, fractions = zip(*group)
        h[rows[key]] = np.sum(solid[list(indices)]*np.asarray(fractions)[:, None], axis=0)/compaction.area_m2
    h[rows[pore_cohort.cohort_id]] = np.sum(solid*compaction.void_ratio, axis=0)/compaction.area_m2
    return h


def _pore_total(compaction):
    return math.fsum((compaction.grain_volume_m3*compaction.void_ratio).flat)


@dataclass(frozen=True, slots=True, init=False)
class W03ColumnState:
    material: MaterialState
    compaction: CompactionState
    pore_fluid_cohort: MaterialCohort
    reference_width_m: float
    reservoir_fluid_m3: float
    total_fluid_m3: float
    initial_bulk_thickness_m: tuple
    binding: W03ThermalBinding
    source_workflow: RegionalWorkflowState = field(repr=False)
    execution_id: str
    parent_state_id: str | None
    state_id: str
    _transition: bytes = field(repr=False)

    @property
    def time_s(self):
        return self.compaction.time_s

    @property
    def transition_record(self):
        return json.loads(self._transition)

    def descriptor(self):
        return dict(schema='atlas.w03-columns.v1', material_state_id=self.material.state_id,
            compaction_state_id=self.compaction.state_id, pore_fluid_cohort=asdict(self.pore_fluid_cohort),
            reference_width_m=self.reference_width_m, reservoir_fluid_m3=self.reservoir_fluid_m3,
            total_fluid_m3=self.total_fluid_m3, initial_bulk_thickness_m=self.initial_bulk_thickness_m,
            binding=asdict(self.binding), execution_id=self.execution_id, parent_state_id=self.parent_state_id,
            transition=self.transition_record)

    def thermal_diagnostics(self, *, store=None, budget=None, context=None, controller=None,
                            cache_policy=None, cancel=None):
        b = self.binding
        resource = store._budget if budget is None and isinstance(store, ArrayStore) else select_budget(budget)
        with _execution(context) as active, resource.reserve(
                96*len(b.depth_edges_m)+8192, category='w03-thermal-retained'):
            age = scalar(b.reference_age_s+(self.time_s-b.reference_time_s), 'cooling age', nonnegative=True)
            z = np.asarray(b.depth_edges_m)
            kwargs = dict(store=store, budget=resource, context=active.scipy, controller=controller,
                          cache_policy=cache_policy, cancel=cancel)
            temperature = cached_plate_temperature(z[:-1], age, b.cooling_model,
                                                   cell_bottom_m=z[1:], **kwargs)
            response = cached_plate_thermal_response(age, b.reference_age_s, b.cooling_model,
                                                     b.buoyancy_material, b.support_parameters, **kwargs)
            heat = plate_cooling_heat([b.reference_age_s, age], b.cooling_model, budget=resource, cancel=cancel)
            increment = heat[1]-heat[0]
            # Net heat is integrated independently: adding large opposing steady
            # boundary fluxes can lose the much smaller stored-energy change.
            delta = plate_cooling_deficit_change(age, b.reference_age_s, b.cooling_model, budget=resource, cancel=cancel)
            net = _factored_scale(delta, (b.cooling_model.volumetric_heat_capacity_j_m3_k,
                b.cooling_model.thickness_m), (), 'W03 net heat')
            return dict(temperature_k=temperature, heat_j_m2=frozen(increment), net_heat_j_m2=frozen(net),
                        support_response=response)


def _state(material, compaction, pore, width, reservoir, total_fluid, heights, binding,
           execution_id, parent, budget, cancel, source_workflow, transition=None):
    _cancel(cancel)
    width = scalar(width, 'reference width', positive=True)
    reservoir = scalar(reservoir, 'reservoir stock', nonnegative=True)
    total_fluid = scalar(total_fluid, 'closed fluid inventory', nonnegative=True)
    if (material.time_s != compaction.time_s or material.epoch_id != compaction.epoch_id
            or material.epoch_id != binding.epoch_id or compaction.depth_reference_id != binding.depth_reference_id
            or compaction.source_state_id != binding.source_state_id
            or compaction.time_s < binding.reference_time_s
            or compaction.shape[1] != material.grid.cells
            or np.any(compaction.area_m2 != material.grid.spacing_m*width)
            or pore.material_id != compaction.conditions.pore_fluid_material_id
            or compaction.conditions.gravity_m_s2 != binding.support_parameters.gravity_m_s2):
        raise TectonicsError('W03 source/frame/time/area/fluid bindings disagree')
    with budget.reserve(96*math.prod(compaction.shape)+4*material.nbytes+8192, category='w03-phase-binding'):
        h = _inventory(compaction, material.cohorts, pore)
        for i, cohort in enumerate(material.cohorts):
            if cohort != pore and not np.array_equal(material.thickness_m[i], source_workflow.material.thickness_m[i]):
                raise TectonicsError('W03 changed source grain inventory')
        current_h = np.array([math.fsum(values) for values in h.T])
        limit = binding.cooling_model.thickness_m*binding.support_parameters.max_relative_deflection
        if np.any(np.abs(current_h-np.asarray(heights)) > limit):
            raise TectonicsError('sediment geometry change exceeds selected fixed-plate envelope')
        if parent is None:
            if transition is not None or material.state_id != source_workflow.material.state_id:
                raise TectonicsError('invalid W03 root material/transition')
        else:
            pass
    result = object.__new__(W03ColumnState)
    for k, v in dict(material=material, compaction=compaction, pore_fluid_cohort=pore,
            reference_width_m=width, reservoir_fluid_m3=reservoir, total_fluid_m3=total_fluid,
            initial_bulk_thickness_m=heights, binding=binding, execution_id=execution_id,
            parent_state_id=parent, source_workflow=source_workflow, _transition=_json(transition)).items():
        object.__setattr__(result, k, v)
    object.__setattr__(result, 'state_id', _id(content_record(result.descriptor())))
    _cancel(cancel)
    return result


def initialise_w03_columns(workflow, column_id, compaction_parameters, *, subdivisions,
        maximum_effective_stress_pa, top_effective_stress_pa, conditions, reservoir_fluid_m3,
        cooling_model, buoyancy_material, support_parameters, depth_edges_m,
        temperature_tolerance_k, budget=None, cancel=None):
    """Join an actual unmixed W01/W02 root to its authored ordered sediment stack.

    This first bridge deliberately refuses moving/mixed columns, spherical
    normalisation, excluded solids and multiple water origins. None is silently
    converted into an invented vertical history or reservoir provenance.
    """
    _cancel(cancel)
    if (type(workflow) is not RegionalWorkflowState or workflow.parent is not None
            or workflow.steps != 0 or workflow.support.kind != 'planar-strip'
            or np.any(workflow.forcing.face_velocity_m_s != 0)):
        raise TectonicsError('W03 requires a stationary, planar, unmixed workflow root')
    resource = select_budget(budget)
    initial = workflow.initial_samples.state
    column = initial.case.column(column_id)
    layers = tuple(l for l in column.layers if l.role == 'sediment')
    height = math.fsum(l.bulk_thickness_m for l in layers)
    units = tuple(initial.units[int(i)] for i in set(workflow.initial_samples.array('unit_code')))
    fluids = {f.unit_id: f.cohort for f in workflow.fluid_cohorts}
    wet = tuple(u for u in units if u.layer.porosity > 0)
    pore = fluids[wet[0].unit_id]
    # Store the already-issued catalogue representation after origin validation.
    pore = next((c for c in workflow.material.cohorts
                 if c.cohort_id == pore.cohort_id and c == pore), pore)
    width = workflow.forcing.reduction.reference_width_m
    area = workflow.material.grid.spacing_m*width
    one = compaction_from_geological_column(initial, column_id, compaction_parameters,
        subdivisions=subdivisions, area_m2=area, top_effective_stress_pa=top_effective_stress_pa,
        maximum_effective_stress_pa=maximum_effective_stress_pa, conditions=conditions,
        budget=resource, cancel=cancel)
    n = workflow.material.grid.cells
    shape = (one.shape[0], n)
    compaction = CompactionState(one.parcels, np.broadcast_to(one.grain_volume_m3, shape),
        np.broadcast_to(one.void_ratio, shape), np.broadcast_to(one.maximum_effective_stress_pa, shape),
        area_m2=area, top_effective_stress_pa=top_effective_stress_pa, conditions=conditions,
        time_s=one.time_s, epoch_id=one.epoch_id, depth_reference_id=one.depth_reference_id,
        source_state_id=one.source_state_id, budget=resource, cancel=cancel)
    binding = _reconcile(initial, workflow, column_id, cooling_model, buoyancy_material,
        support_parameters, depth_edges_m, temperature_tolerance_k, resource, cancel)
    stock = scalar(reservoir_fluid_m3, 'reservoir stock', nonnegative=True)
    with _execution(None) as active:
        return _state(workflow.material, compaction, pore, width, stock,
            scalar(math.fsum((stock, _pore_total(compaction))), 'total fluid', nonnegative=True),
            (height,)*n, binding, active.identity, None, resource, cancel, workflow)


def advance_w03_columns(state, *, time_s, top_effective_stress_pa, store=None, budget=None,
                        context=None, controller=None, cache_policy=None, cancel=None):
    """Atomic functional successor: preserve solids/history, book pore water once.

    Traction is prescribed effective stress; it is NOT a second application of
    thermal buoyancy. No temperature dependence of compaction is assumed.
    """
    resource = store._budget if budget is None and isinstance(store, ArrayStore) else select_budget(budget)
    with _execution(context) as active:
        with resource.reserve(192*math.prod(state.compaction.shape)+8*state.material.nbytes+32768,
                              category='w03-candidate-retained'):
            transition = advance_compaction(state.compaction, area_m2=state.compaction.area_m2,
                top_effective_stress_pa=top_effective_stress_pa, time_s=time_s,
                epoch_id=state.compaction.epoch_id, available_reservoir_fluid_m3=state.reservoir_fluid_m3,
                store=store, budget=resource, context=active.reference, controller=controller,
                cache_policy=cache_policy, cancel=cancel)
            new_stock = scalar(math.fsum((state.reservoir_fluid_m3, *transition.pore_fluid_out_m3)),
                               'remaining reservoir stock', nonnegative=True)
            closed = MaterialBoundary('closed')
            material = advect_materials(state.material, np.zeros(state.material.grid.cells+1),
                transition.state.time_s-state.time_s, left=closed, right=closed,
                scheme='upwind', backend='reference', budget=resource, cancel=cancel).state
            receipts = [material.transition_record]; state_ids = [material.state_id]
            # Existing W02 event receipts retain named source/destination, amount
            # hash and exact parent. No forged RegionalWorkflowState receipt.
            signed = transition.pore_fluid_out_m3/state.compaction.area_m2
            for operation, amount in (('remove', np.maximum(signed, 0.)), ('add', np.maximum(-signed, 0.))):
                if np.any(amount):
                    event = MaterialEvent('w03-'+transition.state.state_id+'-'+operation,
                        material.state_id, material.time_s, operation, state.pore_fluid_cohort,
                        transition.reservoir_id)
                    material = apply_material_event(material, event, amount, budget=resource, cancel=cancel).state
                    receipts.append(material.transition_record); state_ids.append(material.state_id)
            receipt = dict(parent=state.state_id, material_before=state.material.state_id,
                material_after=material.state_id, compaction_before=state.compaction.state_id,
                compaction_after=transition.state.state_id, reservoir_id=transition.reservoir_id,
                reservoir_before_m3=state.reservoir_fluid_m3, reservoir_after_m3=new_stock,
                pore_fluid_out_m3=transition.pore_fluid_out_m3.tolist(),
                pore_volume_before_m3=np.sum(state.compaction.grain_volume_m3*state.compaction.void_ratio, axis=0).tolist(),
                material_receipts=receipts, material_state_ids=state_ids)
            result = _state(material, transition.state, state.pore_fluid_cohort,
                state.reference_width_m, new_stock, state.total_fluid_m3, state.initial_bulk_thickness_m,
                state.binding, state.execution_id, state.state_id, resource, cancel, state.source_workflow, receipt)
            # Validate thermal numerical range and owner before returning ANY new
            # reservoir/material state. Arrays are derived, not duplicated in history.
            result.thermal_diagnostics(store=store, budget=resource, context=active,
                controller=controller, cache_policy=cache_policy, cancel=cancel)
            return result


def evolve_w03_columns(state, schedule, *, store=None, budget=None, cache_policy=None, cancel=None):
    """Preferred sequence API: prepare backends once, retain only latest state.

    Each (time_s, top_effective_stress_pa) is still evaluated: intermediate loads
    cannot be skipped without losing hysteresis. Failed runs leave the supplied
    immutable state intact; save any deliberately chosen checkpoint explicitly.
    """
    if type(state) is not W03ColumnState or type(schedule) is not tuple or not 1 <= len(schedule) <= 1024:
        raise TectonicsError('typed W03 state and bounded nonempty tuple schedule required')
    for item in schedule:
        scalar(item[0], 'scheduled time')
    controller = ReuseController()
    with _execution(None) as active:
        current = state
        for time_s, traction in schedule:
            current = advance_w03_columns(current, time_s=time_s, top_effective_stress_pa=traction,
                store=store, budget=budget, context=active, controller=controller,
                cache_policy=cache_policy, cancel=cancel)
        return current


def save_w03_columns(state, store, *, budget=None, cancel=None):
    save_regional_workflow(state.source_workflow, store, budget=budget, cancel=cancel)
    save_compaction_state(state.compaction, store, budget=budget, cancel=cancel)
    save_material_state(state.material, store, budget=budget, cancel=cancel)
    return store.put(state.state_id, {'snapshot': np.empty(0, dtype='u1')},
                     state.descriptor(), budget=budget, cancel=cancel)


def load_w03_columns(store, state_id, *, budget=None):
    budget = store._budget if budget is None else select_budget(budget)
    arrays = store.get(state_id, budget=budget)
    if arrays is None:
        return None
    meta = store.metadata(state_id)
    with _execution(None):
        try:
            b = dict(meta['binding']); p = dict(b['cooling_model'])
            p['thermal'] = ThermalParameters(**p['thermal'])
            b['cooling_model'] = PlateCoolingParameters(**p)
            m = dict(b['buoyancy_material']); m['temperature_range_k'] = tuple(m['temperature_range_k'])
            b['buoyancy_material'] = BoussinesqMaterial(**m)
            b['support_parameters'] = ThermalSupportParameters(**b['support_parameters'])
            b['depth_edges_m'] = tuple(b['depth_edges_m'])
            source = load_regional_workflow(store, b['workflow_id'], budget=budget)
            if source is None:
                raise TectonicsError('W03 source workflow dependency missing')
            checked = _reconcile(source.initial_samples.state, source, b['column_id'],
                b['cooling_model'], b['buoyancy_material'], b['support_parameters'],
                b['depth_edges_m'], b['temperature_tolerance_k'], select_budget(budget), None)
            if _json(asdict(checked)) != _json(meta['binding']):
                raise TectonicsError('W03 restored source thermal reconciliation differs')
            material = load_material_state(store, meta['material_state_id'], budget=budget)
            compaction = load_compaction_state(store, meta['compaction_state_id'], budget=budget)
            if material is None or compaction is None:
                raise TectonicsError('W03 snapshot dependency missing')
            result = _state(material, compaction, MaterialCohort(**meta['pore_fluid_cohort']),
                meta['reference_width_m'], meta['reservoir_fluid_m3'], meta['total_fluid_m3'],
                tuple(meta['initial_bulk_thickness_m']), W03ThermalBinding(**b),
                meta['execution_id'], meta['parent_state_id'], select_budget(budget), None, source, meta['transition'])
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            raise TectonicsError('invalid W03 state reconstruction') from exc
        return result
