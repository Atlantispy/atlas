"""W06.4 thermal projection of exact piecewise plate/birth/first-exit histories.

Reuses the W06.3 phase-age integrator and physical policy, not its constant-motion
geometry. Neither an output request nor reassignment creates a cooling onset.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict, field
import hashlib
import math
import numpy as np

from ._validation import TectonicsError, scalar
from .materials import _json, _immutable_bytes, _account
from .regional import _cancelled
from .resources import select_budget
from .spreading import _product, _within_budget
from .spreading_history import PreparedSpreadingHistory, HistorySpreadingState, HistoryExport
from .spreading_cooling import (OceanCoolingParameters, PreparedSpreadingCooling,
    SpreadingThermalState, HEAT_RELATIVE_TOLERANCE, _remaining, _identity)


@dataclass(frozen=True, slots=True)
class HistoryThermalExport:
    """A first-exit parcel interval, retaining owner and age at exit."""
    history: HistoryExport
    destination_id: str
    enthalpy_j: float
    water_m3: float


@dataclass(frozen=True, slots=True, init=False)
class HistoryThermalState(SpreadingThermalState):
    """Same field/account units as W06.3, with piecewise semantic histories."""
    motion: HistorySpreadingState
    exports: tuple[HistoryThermalExport, ...]

    @property
    def nbytes(self):
        return sum(len(getattr(self, key)) for key in (
            '_cells', '_centres', '_fraction', '_mask', '_heat', '_water'))+self.motion.nbytes+2048+1024*len(self.exports)


def _state(plan, motion, parent, exports, cell, centre, fraction, valid, heat, water):
    result = object.__new__(HistoryThermalState)
    fields = dict(plan_id=plan.plan_id, parent_state_id=parent, motion=motion, exports=exports,
        _n=plan.spreading.grid.cells, _p=len(plan.spreading.phases),
        _cells=_immutable_bytes(cell), _centres=_immutable_bytes(centre),
        _fraction=_immutable_bytes(fraction), _mask=np.asarray(valid, dtype=np.bool_).tobytes(),
        _heat=_immutable_bytes(np.asarray(heat)), _water=_immutable_bytes(np.asarray(water)))
    for key, value in fields.items():
        object.__setattr__(result, key, value)
    object.__setattr__(result, 'state_id', _identity(result))
    return result


@dataclass(frozen=True, slots=True, init=False)
class PreparedHistoryCooling:
    """Prepared thermal adapter; owns neither its history plan nor source context.

    States are immutable candidate branches of finite named stocks. Publication
    and cross-run reservoir ownership remain the later workflow's responsibility.
    """
    spreading: PreparedSpreadingHistory
    parameters: OceanCoolingParameters
    plan_id: str
    initial: HistoryThermalState
    _depths: bytes = field(repr=False)
    _budget: object = field(repr=False, compare=False)
    _lease: object = field(repr=False, compare=False)
    _closed: bool = field(repr=False, compare=False)

    def __init__(self, spreading, parameters, *, budget=None, cancel=None):
        if type(spreading) is not PreparedSpreadingHistory or type(parameters) is not OceanCoolingParameters:
            raise TectonicsError('typed spreading history and ocean cooling parameters required')
        _cancelled(cancel); spreading._check(spreading.initial); spreading._context.verify()
        if len(parameters.phase_materials) != len(spreading.phases):
            raise TectonicsError('exactly one ordered thermal material per spreading phase required')
        if any(phase.density_kg_m3 != material.density_kg_m3
               for phase, material in zip(spreading.phases, parameters.phase_materials)):
            raise TectonicsError('phase reference mass and thermal density disagree')
        depths = np.array([0.]+[math.fsum(p.thickness_m for p in spreading.phases[:i+1])
                               for i in range(len(spreading.phases))])
        if depths[-1] != parameters.plate.thickness_m or np.any(np.diff(depths) <= 0):
            raise TectonicsError('thermal phases must exactly cover the selected plate')
        resource = spreading._budget if budget is None else select_budget(budget)
        _within_budget(resource, spreading._budget)
        n, p = spreading.grid.cells, len(spreading.phases)
        lease = resource.reserve((16*(p+5)+48)*n+16384, category='history-thermal-prepared')
        lease.__enter__()
        try:
            descriptor = dict(method='atlas.w06-history-cooling.v1', motion=spreading.plan_id,
                parameters=asdict(parameters), heat_tolerance=HEAT_RELATIVE_TOLERANCE)
            for key, value in dict(spreading=spreading, parameters=parameters,
                    plan_id=hashlib.sha256(_json(descriptor)).hexdigest(),
                    _depths=_immutable_bytes(depths), _budget=resource, _lease=lease, _closed=False).items():
                object.__setattr__(self, key, value)
            object.__setattr__(self, 'initial', self._evaluate(spreading.initial, None, resource, cancel))
            spreading._context.verify(); _cancelled(cancel)
        except BaseException:
            lease.__exit__(None, None, None)
            raise

    @property
    def depth_edges_m(self):
        return np.frombuffer(self._depths, dtype=np.float64)

    def _check(self, state):
        if self._closed:
            raise TectonicsError('history cooling preparation is closed')
        if (type(state) is not HistoryThermalState or state.plan_id != self.plan_id
                or state._n != self.spreading.grid.cells or state._p != len(self.spreading.phases)):
            raise TectonicsError('thermal state belongs to a different history plan')
        self.spreading._check(state.motion)
        if _identity(state) != state.state_id:
            raise TectonicsError('history thermal state content no longer matches its identity')

    def _values(self, young, old, resource, cancel):
        # Reuse its exact deduplication, depth/age quadrature and support gates.
        return PreparedSpreadingCooling._values(self, young, old, resource, cancel)

    def _evaluate(self, motion, parent, resource, cancel):
        source, parameters = self.spreading, self.parameters
        n, p = source.grid.cells, len(source.phases)
        plate = parameters.plate
        capacity = plate.volumetric_heat_capacity_j_m3_k
        hot_energy = _product(capacity, plate.thermal.mantle_temperature_k-plate.thermal.surface_temperature_k,
                              plate.thickness_m)
        created_area = _product(motion.created_width_m, source.width_m)
        birth = _product(created_area, hot_energy)
        birth_remaining = _remaining(parameters.birth_enthalpy_stock_j, birth, 'birth enthalpy allowance')
        _remaining(parameters.water_stock_m3, _product(created_area, parameters.axial_depth_m), 'water reservoir')
        intersections = motion.intersections
        m, e = len(intersections), len(motion.exports)
        # Sparse intersections are O(cells + strips), not an event x cell array.
        # Includes output byte copies, interval/inverse arrays, gathered values,
        # deficits, weights, accounts and export metadata. Kernel has its own lease.
        # Names may contain 256 non-ASCII characters; JSON identity serialisation
        # can expand them sixfold and briefly retain both text and encoded bytes.
        estimate = (96+32*p)*n+(256+64*p)*(m+n+e+1)+32768*e+65536
        with resource.reserve(estimate, category='history-thermal-output'):
            if created_area == 0.:
                heat = (0., parameters.birth_enthalpy_stock_j, 0., parameters.basal_heat_stock_j,
                        0., 0., 0., 0., 0., 0.)
                water = (0., parameters.water_stock_m3, 0., 0., 0., 0.)
                _cancelled(cancel)
                return _state(self, motion, parent, (), np.zeros((n, p+5)),
                    np.zeros((n, p+5)), np.zeros(n), np.zeros(n, dtype=np.bool_), heat, water)
            indices = intersections[:, 0].astype(np.intp)
            widths = intersections[:, 2]
            occupied = np.bincount(indices, weights=widths, minlength=n)
            fraction = occupied/source.grid.widths_m
            valid = motion.centre_valid
            ages = motion.centre_age_s[valid]
            young, old = intersections[:, 3], intersections[:, 4]
            exit_young = np.array([min(x.exit_age_first_s, x.exit_age_last_s) for x in motion.exports])
            exit_old = np.array([max(x.exit_age_first_s, x.exit_age_last_s) for x in motion.exports])
            # Oldest represented column EVER is either resident now or at exit.
            # Including this point prevents safe averages hiding invalid extremes.
            oldest = max(float(np.max(old, initial=0)), float(np.max(exit_old, initial=0)))
            query_young = np.r_[young, ages, exit_young, oldest]
            query_old = np.r_[old, ages, exit_old, oldest]
            values, deficit = self._values(query_young, query_old, resource, cancel)
            resident_values, resident_deficit = values[:m], deficit[:m]
            split = m+len(ages)
            exit_values, exit_deficit = values[split:split+e], deficit[split:split+e]
            cell = np.zeros((n, p+5))
            weights = widths/occupied[indices]
            # Grouped weighted sums without allocating a history x cells tensor.
            for column in range(p+5):
                cell[:, column] = np.bincount(indices, weights=weights*resident_values[:, column], minlength=n)
            centre = np.zeros_like(cell)
            centre[valid] = values[m:split]
            areas = widths*source.width_m
            exit_areas = np.array([_product(x.exported_width_m, source.width_m) for x in motion.exports])
            resident_energy = math.fsum(areas*(hot_energy-capacity*np.sum(resident_deficit, axis=1)))
            exit_energy = exit_areas*(hot_energy-capacity*np.sum(exit_deficit, axis=1))
            surface = math.fsum((math.fsum(areas*resident_values[:, -2]),
                                 math.fsum(exit_areas*exit_values[:, -2])))
            basal = -math.fsum((math.fsum(areas*resident_values[:, -1]),
                                math.fsum(exit_areas*exit_values[:, -1])))
            basal_remaining = _remaining(parameters.basal_heat_stock_j, basal, 'basal heat allowance')
            left = np.array([x.side == 'left' for x in motion.exports], dtype=np.bool_)
            exported_heat = math.fsum(exit_energy[left]), math.fsum(exit_energy[~left])
            residual = math.fsum((resident_energy, *exported_heat, surface, -basal, -birth))
            scale = max(birth, math.fsum((abs(basal), abs(surface), *(abs(q) for q in exported_heat))))
            if scale == 0. and residual != 0.:
                raise TectonicsError('nonzero heat residual without any heat input')
            relative = 0. if scale == 0. else residual/scale
            if not math.isfinite(relative) or abs(relative) > HEAT_RELATIVE_TOLERANCE:
                raise TectonicsError('piecewise moving-domain heat balance does not close')
            resident_water = math.fsum(areas*resident_values[:, p+2])
            exit_water = exit_areas*exit_values[:, p+2]
            exported_water = math.fsum(exit_water[left]), math.fsum(exit_water[~left])
            drawn = math.fsum((resident_water, *exported_water))
            water_remaining = _remaining(parameters.water_stock_m3, drawn, 'water reservoir')
            water_residual = _account(drawn, resident_water, -exported_water[0], -exported_water[1], 0.)[4]
            heat = (birth, birth_remaining, basal, basal_remaining, surface, resident_energy,
                    *exported_heat, residual, relative)
            water = (drawn, water_remaining, resident_water, *exported_water, water_residual)
            exports = tuple(HistoryThermalExport(history,
                parameters.left_export_id if history.side == 'left' else parameters.right_export_id,
                float(energy), float(water_volume))
                for history, energy, water_volume in zip(motion.exports, exit_energy, exit_water))
            _cancelled(cancel)
            return _state(self, motion, parent, exports, cell, centre, fraction, valid, heat, water)

    def advance(self, state, *, time_s, budget=None, cancel=None):
        self._check(state); _cancelled(cancel); self.spreading._context.verify()
        end = scalar(time_s, 'requested history thermal time')
        resource = self._budget if budget is None else select_budget(budget)
        _within_budget(resource, self._budget)
        if end == state.time_s:
            return state
        motion = self.spreading.advance(state.motion, time_s=end, budget=resource, cancel=cancel)
        result = self._evaluate(motion, state.state_id, resource, cancel)
        self.spreading._context.verify(); _cancelled(cancel)
        return result

    def close(self):
        if not self._closed:
            object.__setattr__(self, '_closed', True)
            self._lease.__exit__(None, None, None)

    def __enter__(self):
        self._check(self.initial)
        return self

    def __exit__(self, *args):
        self.close()
