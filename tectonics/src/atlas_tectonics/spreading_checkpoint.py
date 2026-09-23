"""Lossless W06 ocean snapshot payloads for the existing checked ArrayStore.

Thermal fields are retained; cheap exact geometry, validity and export provenance
are reconstructed from the bound plan. Restore never evaluates an age/depth
thermal kernel. Chunk authentication/publication belong to the workflow/store.
"""
from __future__ import annotations

import math

import numpy as np

from ._validation import TectonicsError, frozen, scalar
from .materials import _account, _ROUNDOFF, _sha
from .regional import _cancelled
from .resources import select_budget
from .spreading import MAX_SPREADING_INTERVALS, _product, _within_budget
from .spreading_cooling import (PreparedSpreadingCooling, SpreadingThermalState,
    HEAT_RELATIVE_TOLERANCE, _export_history, _remaining, _state as _constant_state)
from .spreading_history_cooling import (PreparedHistoryCooling, HistoryThermalState,
    HistoryThermalExport, _state as _history_state)


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
    if value is not None:
        _sha(value, label)
    return value


def _count(value):
    if type(value) is not int or not 0 <= value <= MAX_SPREADING_INTERVALS:
        raise TectonicsError('ocean checkpoint requires zero to 256 accepted intervals')
    return value


def _export_count(plan, kind, value):
    if type(value) is not int or value < 0:
        raise TectonicsError('invalid ocean checkpoint export count')
    limit = 2 if kind == 'constant' else len(plan.spreading.events)*(len(plan.spreading.events)+1)
    if value > limit or (kind == 'constant' and value != 2):
        raise TectonicsError('ocean checkpoint export count exceeds bound history')
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
    kind = _kind(plan); _cancelled(cancel)
    expected_type = SpreadingThermalState if kind == 'constant' else HistoryThermalState
    if type(state) is not expected_type:
        raise TectonicsError('ocean checkpoint state type does not match plan')
    count = _export_count(plan, kind, len(state.exports))
    resource = plan._budget if budget is None else select_budget(budget)
    _within_budget(resource, plan._budget)
    with resource.reserve(_work_bytes(plan, count), category='ocean-checkpoint-pack'):
        plan._check(state); plan.spreading._context.verify(); _cancelled(cancel)
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
        plan.spreading._context.verify(); _cancelled(cancel)
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
    if np.any(fraction < 0) or np.any(fraction > 1+_ROUNDOFF):
        raise TectonicsError('restored ocean occupancy outside cell coverage')
    return occupied, fraction, valid


def _close(actual, expected, scale, label, *, relative=_ROUNDOFF):
    if np.any(np.abs(np.asarray(actual)-np.asarray(expected)) > relative*np.asarray(scale)):
        raise TectonicsError('ocean checkpoint '+label+' does not match physical accounts')


def _fields(plan, values, valid):
    """Cheap linear thermodynamic/support identities, with existing tolerances."""
    p = len(plan.spreading.phases); parameters = plan.parameters
    if np.any(values[~valid] != 0.):
        raise TectonicsError('ocean checkpoint has values outside its valid coverage')
    field = values[valid]
    if not len(field):
        return
    plate = parameters.plate
    ts, tb = plate.thermal.surface_temperature_k, plate.thermal.mantle_temperature_k
    width = np.diff(plan.depth_edges_m)
    temperature_tolerance = _ROUNDOFF*max(ts, tb, np.finfo(float).tiny)
    if (np.any(field[:, :p] < ts-temperature_tolerance)
            or np.any(field[:, :p] > tb+temperature_tolerance)
            or np.any(field[:, p:p+2] < 0.) or np.any(field[:, p+2] <= 0.)
            or np.any(field[:, -2] < 0.) or np.any(field[:, -1] > 0.)):
        raise TectonicsError('restored ocean fields exceed the thermal/wet envelope')
    for index, material in enumerate(parameters.phase_materials):
        anomaly = np.abs(material.expansion_per_k*(field[:, index]-tb))
        if np.any(anomaly > material.max_relative_density_anomaly*(1+_ROUNDOFF)):
            raise TectonicsError('restored ocean exceeds Boussinesq validity')
    deficits = (tb-field[:, :p])*width
    factors = np.array([m.density_kg_m3*m.expansion_per_k for m in parameters.phase_materials])
    sheet = deficits @ factors
    full_sheet = math.fsum((tb-ts)*width*factors)
    sheet_scale = max(abs(full_sheet), np.finfo(float).tiny)
    _close(field[:, p], sheet, sheet_scale, 'thermal density sheet')
    subsidence = field[:, p]/parameters.support.restoring_density_contrast_kg_m3
    _close(field[:, p+1], subsidence,
           np.maximum(np.abs(subsidence), np.finfo(float).tiny), 'single-owner subsidence')
    maximum = parameters.support.max_relative_deflection*plate.thickness_m
    if np.any(field[:, p+1] > maximum*(1+_ROUNDOFF)):
        raise TectonicsError('restored ocean exceeds small-deflection support envelope')
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
    if np.any(heat[:8] < 0) or np.any(water[:5] < 0):
        raise TectonicsError('negative ocean checkpoint inventory')
    if (heat[0] != birth
            or heat[1] != _remaining(parameters.birth_enthalpy_stock_j, birth, 'birth enthalpy allowance')
            or heat[3] != _remaining(parameters.basal_heat_stock_j, float(heat[2]), 'basal heat allowance')
            or water[1] != _remaining(parameters.water_stock_m3, float(water[0]), 'water reservoir')):
        raise TectonicsError('ocean checkpoint finite reservoir debit mismatch')
    _remaining(parameters.water_stock_m3, _product(created_area, parameters.axial_depth_m), 'axial water reservoir')
    residual = math.fsum((heat[5], heat[6], heat[7], heat[4], -heat[2], -heat[0]))
    scale = max(birth, math.fsum(abs(heat[i]) for i in (2, 4, 6, 7)))
    relative = 0. if scale == 0. else residual/scale
    if (heat[8] != residual or heat[9] != relative or abs(relative) > HEAT_RELATIVE_TOLERANCE
            or (scale == 0. and residual != 0.)):
        raise TectonicsError('ocean checkpoint heat balance/residual mismatch')
    water_residual = _account(float(water[0]), float(water[2]), -float(water[3]), -float(water[4]), 0.)[4]
    if water[5] != water_residual or water[0] != math.fsum(water[2:5]):
        raise TectonicsError('ocean checkpoint water balance/residual mismatch')
    p = len(source.phases); areas = occupied*source.width_m
    resident_energy = math.fsum(areas*capacity*np.sum(
        (state.cell_values[:, :p]-plate.thermal.surface_temperature_k)*np.diff(plan.depth_edges_m), axis=1))
    resident_water = math.fsum(areas*state.cell_values[:, p+2])
    _close(heat[5], resident_energy, scale, 'represented enthalpy', relative=HEAT_RELATIVE_TOLERANCE)
    _close(water[2], resident_water, max(float(water[0]), np.finfo(float).tiny), 'represented water')
    if kind == 'history':
        widths = [e.history.exported_width_m for e in state.exports]
        energy = np.array([e.enthalpy_j for e in state.exports])
        volume = np.array([e.water_m3 for e in state.exports])
        sides = [e.history.side for e in state.exports]
    else:
        widths = [e.width_m for e in state.exports]
        energy, volume = heat[6:8], water[3:5]
        sides = [e.side for e in state.exports]
    export_areas = np.asarray(widths)*source.width_m
    maximum_depth = parameters.axial_depth_m+parameters.support.max_relative_deflection*plate.thickness_m
    if (np.any(energy < 0.) or np.any(energy > export_areas*hot*(1+_ROUNDOFF))
            or np.any(volume < export_areas*parameters.axial_depth_m*(1-_ROUNDOFF))
            or np.any(volume > export_areas*maximum_depth*(1+_ROUNDOFF))):
        raise TectonicsError('ocean checkpoint export inventories exceed physical bounds')
    if kind == 'history':
        for index, side in enumerate(('left', 'right')):
            if (heat[6+index] != math.fsum(e for e, s in zip(energy, sides) if s == side)
                    or water[3+index] != math.fsum(v for v, s in zip(volume, sides) if s == side)):
                raise TectonicsError('ocean checkpoint first-exit totals mismatch')


def restore_ocean(plan, arrays, meta, *, time_s, intervals, motion_parent_id,
                  thermal_parent_id, budget=None, cancel=None):
    """Restore an exact typed thermal state without re-evaluating thermal fields.

    The caller supplies independently expected schedule time/count/parents.
    Payload corruption, a foreign plan/source, or inconsistent accounts raises;
    none is a cache miss. Already checked ArrayStore chunks supply authenticity.
    """
    kind = _kind(plan); _cancelled(cancel)
    end = scalar(time_s, 'expected checkpoint time'); count = _count(intervals)
    _parent(motion_parent_id, 'expected motion parent'); _parent(thermal_parent_id, 'expected thermal parent')
    origin = plan.spreading.time_s
    if (end < origin or (count == 0) != (end == origin)
            or (count == 0 and (motion_parent_id is not None or thermal_parent_id is not None))
            or (count > 0 and (motion_parent_id is None or thermal_parent_id is None))):
        raise TectonicsError('ocean checkpoint expected clock/count/parents mismatch')
    if count == 1 and (motion_parent_id != plan.spreading.initial.state_id
                       or thermal_parent_id != plan.initial.state_id):
        raise TectonicsError('first ocean checkpoint must continue declared initial states')
    if type(meta) is not dict or set(meta) != _META_KEYS:
        raise TectonicsError('invalid ocean checkpoint metadata keys')
    export_count = _export_count(plan, kind, meta['export_count'])
    for key in ('plan_id', 'motion_plan_id', 'execution_id', 'motion_state_id', 'thermal_state_id'):
        _sha(meta[key], 'checkpoint '+key)
    _parent(meta['motion_parent_id'], 'checkpoint motion parent')
    _parent(meta['thermal_parent_id'], 'checkpoint thermal parent')
    if (meta['schema'] != _SCHEMA or meta['kind'] != kind or meta['plan_id'] != plan.plan_id
            or meta['motion_plan_id'] != plan.spreading.plan_id
            or meta['execution_id'] != plan.spreading.execution_id
            or type(meta['time_s']) is not float or meta['time_s'] != end
            or _count(meta['intervals']) != count or meta['motion_parent_id'] != motion_parent_id
            or meta['thermal_parent_id'] != thermal_parent_id):
        raise TectonicsError('incompatible ocean checkpoint source/clock/parent binding')
    n, p = plan.spreading.grid.cells, len(plan.spreading.phases)
    shapes = dict(cell_values=(n, p+5), centre_values=(n, p+5), heat_accounts_j=(10,), water_accounts_m3=(6,))
    if kind == 'history':
        shapes['export_accounts'] = (export_count, 2)
    if type(arrays) is not dict or set(arrays) != set(shapes):
        raise TectonicsError('invalid ocean checkpoint array keys')
    for name, shape in shapes.items():
        if (type(arrays[name]) is not np.ndarray or arrays[name].dtype != np.dtype('float64')
                or arrays[name].shape != shape):
            raise TectonicsError('invalid ocean checkpoint field type/dtype/shape: '+name)
    resource = plan._budget if budget is None else select_budget(budget)
    _within_budget(resource, plan._budget)
    with resource.reserve(_work_bytes(plan, export_count), category='ocean-checkpoint-restore'):
        plan._check(plan.initial); plan.spreading._context.verify(); _cancelled(cancel)
        captured = {name: frozen(value) for name, value in arrays.items()}
        if any(captured[name].shape != shape for name, shape in shapes.items()):
            raise TectonicsError('ocean checkpoint array changed during capture')
        elapsed = scalar(end-origin, 'checkpoint elapsed time', nonnegative=True)
        if origin+elapsed != end:
            raise TectonicsError('ocean checkpoint clock cannot resolve endpoint')
        motion = plan.spreading._evaluate(end, elapsed, count, motion_parent_id, resource, cancel)
        if motion.state_id != meta['motion_state_id']:
            raise TectonicsError('ocean checkpoint motion identity mismatch')
        occupied, fraction, valid = _geometry(plan, motion, kind)
        if kind == 'history':
            if len(motion.exports) != export_count:
                raise TectonicsError('ocean checkpoint first-exit count mismatch')
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
        if result.state_id != meta['thermal_state_id']:
            raise TectonicsError('ocean checkpoint thermal identity mismatch')
        if count == 0 and result.state_id != plan.initial.state_id:
            raise TectonicsError('initial ocean checkpoint differs from declared empty state')
        try:
            with np.errstate(over='raise', invalid='raise', divide='raise'):
                _fields(plan, result.cell_values, fraction > 0.)
                _fields(plan, result.centre_values, valid)
                _accounts(plan, result, occupied, kind)
        except (FloatingPointError, OverflowError) as exc:
            raise TectonicsError('ocean checkpoint physical account exceeds finite range') from exc
        plan._check(result); plan.spreading._context.verify(); _cancelled(cancel)
        return result
