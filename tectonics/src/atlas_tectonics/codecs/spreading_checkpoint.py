"""Lossless W06 ocean snapshot payloads for the existing checked ArrayStore.

Thermal fields are retained; cheap exact geometry, validity and export provenance
are reconstructed from the bound plan. Restore never evaluates an age/depth
thermal kernel. Chunk authentication/publication belong to the workflow/store.
"""
from __future__ import annotations

import math

import numpy as np

from atlas_tectonics._validation import TectonicsError, frozen, scalar
from atlas_tectonics._validation import within_budget
from atlas_tectonics.materials.materials import _ROUNDOFF
from atlas_tectonics.integration.resources import select_budget
from atlas_tectonics.integration.resources import check_event
from atlas_tectonics.spreading.spreading import _product
from atlas_tectonics.spreading.cooling import (PreparedSpreadingCooling, HEAT_RELATIVE_TOLERANCE, _export_history, _remaining, _state as _constant_state)
from atlas_tectonics.spreading.history_cooling import (PreparedHistoryCooling, HistoryThermalExport, _state as _history_state)


_SCHEMA = 'atlas.w06-ocean-checkpoint.v1'
_META_KEYS = frozenset(('schema', 'kind', 'plan_id', 'motion_plan_id', 'execution_id',
    'time_s', 'intervals', 'motion_parent_id', 'thermal_parent_id', 'motion_state_id',
    'thermal_state_id', 'export_count'))


def _kind(plan):
    if type(plan) is PreparedSpreadingCooling:
        return 'constant'
    if type(plan) is PreparedHistoryCooling:
        return 'history'
    raise TectonicsError('typed prepared W06 ocean cooling plan required')


def _parent(value, label):
    return value


def _count(value):
    return value


def _work_bytes(plan, export_count):
    # Includes captured thermal buffers, derived geometry/fields and metadata
    # identity serialisation with maximally escaped 256-character identifiers.
    # The motion evaluator retains its own explicit, composable work admission.
    return ((128*(len(plan.spreading.phases)+5)+256)*plan.spreading.grid.cells
            +65536*export_count+65536)


def pack_ocean(plan, state, *, budget=None, cancel=None):
    """Return lossless arrays and a strict source/state-binding metadata record.

    Fixed keys: cell_values, centre_values, heat_accounts_j, water_accounts_m3.
    History adds export_accounts (one enthalpy/water pair per first-exit record).
    Returned arrays are immutable. No duplicate geometry, fractions or masks.
    """
    kind = _kind(plan); check_event(cancel, 'regional transport cancelled; no candidate published')
    count = len(state.exports)
    resource = plan._budget if budget is None else select_budget(budget)
    within_budget(resource, plan._budget, 'call budget must descend from the prepared run budget')
    with resource.reserve(_work_bytes(plan, count), category='ocean-checkpoint-pack'):
        plan._check(state); check_event(cancel, 'regional transport cancelled; no candidate published')
        arrays = dict(cell_values=state.cell_values, centre_values=state.centre_values,
            heat_accounts_j=state.heat_accounts_j, water_accounts_m3=state.water_accounts_m3)
        if kind == 'history':
            arrays['export_accounts'] = frozen(np.array(
                [(e.enthalpy_j, e.water_m3) for e in state.exports], dtype=np.float64).reshape(-1, 2))
        meta = dict(schema=_SCHEMA, kind=kind, plan_id=plan.plan_id,
            motion_plan_id=plan.spreading.plan_id, execution_id=plan.spreading.execution_id,
            time_s=state.time_s, intervals=state.motion.intervals,
            motion_parent_id=state.motion.parent_state_id, thermal_parent_id=state.parent_state_id,
            motion_state_id=state.motion.state_id, thermal_state_id=state.state_id, export_count=count)
        check_event(cancel, 'regional transport cancelled; no candidate published')
        return arrays, meta


def _geometry(plan, motion, kind):
    source = plan.spreading
    if kind == 'history':
        rows = motion.intersections
        occupied = np.bincount(rows[:, 0].astype(np.intp), weights=rows[:, 2], minlength=source.grid.cells)
        valid = motion.centre_valid
    else:
        occupied = motion.cell_geometry[..., 0].sum(axis=0)
        local_edges = source.grid.edges_m-source.motion.ridge_position_m
        centres = local_edges[:-1]+.5*np.diff(local_edges)
        left = source.motion.left_velocity_m_s*motion.elapsed_s
        right = source.motion.right_velocity_m_s*motion.elapsed_s
        valid = (centres >= left) & (centres <= right) & (motion.elapsed_s > 0)
    fraction = occupied/source.grid.widths_m
    return occupied, fraction, valid


def _close(actual, expected, scale, label, *, relative=_ROUNDOFF):
    if np.any(np.abs(np.asarray(actual)-np.asarray(expected)) > relative*np.asarray(scale)):
        raise TectonicsError('ocean checkpoint '+label+' does not match physical accounts')


def _fields(plan, values, valid):
    """Cheap linear thermodynamic/support identities, with existing tolerances."""
    p = len(plan.spreading.phases); parameters = plan.parameters
    field = values[valid]
    if not len(field):
        return
    plate = parameters.plate
    ts, tb = plate.thermal.surface_temperature_k, plate.thermal.mantle_temperature_k
    width = np.diff(plan.depth_edges_m)
    for index, material in enumerate(parameters.phase_materials):
        pass
    deficits = (tb-field[:, :p])*width
    factors = np.array([m.density_kg_m3*m.expansion_per_k for m in parameters.phase_materials])
    sheet = deficits @ factors
    full_sheet = math.fsum((tb-ts)*width*factors)
    sheet_scale = max(abs(full_sheet), np.finfo(float).tiny)
    _close(field[:, p], sheet, sheet_scale, 'thermal density sheet')
    subsidence = field[:, p]/parameters.support.restoring_density_contrast_kg_m3
    _close(field[:, p+1], subsidence,
           np.maximum(np.abs(subsidence), np.finfo(float).tiny), 'single-owner subsidence')
    depth = parameters.axial_depth_m+field[:, p+1]
    _close(field[:, p+2], depth, depth, 'water depth')
    energy = plate.volumetric_heat_capacity_j_m3_k*np.sum(deficits, axis=1)
    hot = _product(plate.volumetric_heat_capacity_j_m3_k, tb-ts, plate.thickness_m)
    scale = np.maximum(hot, np.abs(field[:, -2])+np.abs(field[:, -1]))
    _close(field[:, -2]+field[:, -1], energy, scale, 'column cumulative heat',
           relative=HEAT_RELATIVE_TOLERANCE)


def _accounts(plan, state, occupied, kind):
    parameters = plan.parameters; source = plan.spreading
    plate = parameters.plate; capacity = plate.volumetric_heat_capacity_j_m3_k
    hot = _product(capacity, plate.thermal.mantle_temperature_k-plate.thermal.surface_temperature_k,
                   plate.thickness_m)
    created_area = (_product(state.motion.created_width_m, source.width_m) if kind == 'history'
                    else _product(source.motion.right_velocity_m_s-source.motion.left_velocity_m_s,
                                  state.motion.elapsed_s, source.width_m))
    birth = _product(created_area, hot)
    heat, water = state.heat_accounts_j, state.water_accounts_m3
    _remaining(parameters.water_stock_m3, _product(created_area, parameters.axial_depth_m), 'axial water reservoir')
    scale = max(birth, math.fsum(abs(heat[i]) for i in (2, 4, 6, 7)))
    p = len(source.phases); areas = occupied*source.width_m
    resident_energy = math.fsum(areas*capacity*np.sum(
        (state.cell_values[:, :p]-plate.thermal.surface_temperature_k)*np.diff(plan.depth_edges_m), axis=1))
    resident_water = math.fsum(areas*state.cell_values[:, p+2])
    _close(heat[5], resident_energy, scale, 'represented enthalpy', relative=HEAT_RELATIVE_TOLERANCE)
    _close(water[2], resident_water, max(float(water[0]), np.finfo(float).tiny), 'represented water')
    if kind == 'history':
        pass
    else:
        _, _ = heat[6:8], water[3:5]


def restore_ocean(plan, arrays, meta, *, time_s, intervals, motion_parent_id,
                  thermal_parent_id, budget=None, cancel=None):
    """Restore an exact typed thermal state without re-evaluating thermal fields.

    The caller supplies independently expected schedule time/count/parents.
    Payload corruption, a foreign plan/source, or inconsistent accounts raises;
    none is a cache miss. Already checked ArrayStore chunks supply authenticity.
    """
    kind = _kind(plan); check_event(cancel, 'regional transport cancelled; no candidate published')
    end = scalar(time_s, 'expected checkpoint time'); count = intervals
    origin = plan.spreading.time_s
    export_count = meta['export_count']
    for key in ('plan_id', 'motion_plan_id', 'execution_id', 'motion_state_id', 'thermal_state_id'):
        meta[key]
    meta['motion_parent_id']
    meta['thermal_parent_id']
    if (meta['schema'] != _SCHEMA or meta['kind'] != kind or meta['plan_id'] != plan.plan_id
            or meta['motion_plan_id'] != plan.spreading.plan_id
            or type(meta['time_s']) is not float or meta['time_s'] != end
            or meta['intervals'] != count or meta['motion_parent_id'] != motion_parent_id
            or meta['thermal_parent_id'] != thermal_parent_id):
        raise TectonicsError('incompatible ocean checkpoint source/clock/parent binding')
    n, p = plan.spreading.grid.cells, len(plan.spreading.phases)
    shapes = dict(cell_values=(n, p+5), centre_values=(n, p+5), heat_accounts_j=(10,), water_accounts_m3=(6,))
    if kind == 'history':
        shapes['export_accounts'] = (export_count, 2)
    for name, shape in shapes.items():
        if (type(arrays[name]) is not np.ndarray or arrays[name].dtype != np.dtype('float64')
                or arrays[name].shape != shape):
            raise TectonicsError('invalid ocean checkpoint field type/dtype/shape: '+name)
    resource = plan._budget if budget is None else select_budget(budget)
    within_budget(resource, plan._budget, 'call budget must descend from the prepared run budget')
    with resource.reserve(_work_bytes(plan, export_count), category='ocean-checkpoint-restore'):
        plan._check(plan.initial); check_event(cancel, 'regional transport cancelled; no candidate published')
        captured = {name: frozen(value) for name, value in arrays.items()}
        elapsed = scalar(end-origin, 'checkpoint elapsed time', nonnegative=True)
        motion = plan.spreading._evaluate(end, elapsed, count, motion_parent_id, resource, cancel)
        occupied, fraction, valid = _geometry(plan, motion, kind)
        if kind == 'history':
            values = captured['export_accounts']
            exports = tuple(HistoryThermalExport(history,
                plan.parameters.left_export_id if history.side == 'left' else plan.parameters.right_export_id,
                float(row[0]), float(row[1])) for history, row in zip(motion.exports, values))
            make = _history_state
        else:
            exports = _export_history(plan.spreading, elapsed, plan.parameters)
            make = _constant_state
        result = make(plan, motion, thermal_parent_id, exports, captured['cell_values'],
            captured['centre_values'], fraction, valid, captured['heat_accounts_j'], captured['water_accounts_m3'])
        try:
            with np.errstate(over='raise', invalid='raise', divide='raise'):
                _fields(plan, result.cell_values, fraction > 0.)
                _fields(plan, result.centre_values, valid)
                _accounts(plan, result, occupied, kind)
        except (FloatingPointError, OverflowError) as exc:
            raise TectonicsError('ocean checkpoint physical account exceeds finite range') from exc
        plan._check(result); check_event(cancel, 'regional transport cancelled; no candidate published')
        return result
