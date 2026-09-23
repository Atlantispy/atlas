"""W06.3 moving newborn ocean: phase cooling, one support owner and finite feeds.

The Step-2 prescribed motion is unchanged. Thermal histories are integrated over
each actual age interval; exports carry enthalpy/water AT EXIT, not at the output
age after continued cooling outside the represented source window.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict, field
import hashlib
import math
import numpy as np

from ._validation import TectonicsError, scalar, frozen
from .materials import _name, _json, _immutable_bytes, _account
from .parameters import PlateCoolingParameters
from .constitutive import BoussinesqMaterial
from .thermal_support import ThermalSupportParameters, _plate_material
from .spreading import PreparedRidgeSpreading, SpreadingState, _product, _within_budget
from .spreading_integrals import spreading_thermal_means
from .regional import _cancelled
from .resources import select_budget


HEAT_RELATIVE_TOLERANCE = 1.e-8


@dataclass(frozen=True, slots=True)
class OceanCoolingParameters:
    plate: PlateCoolingParameters
    phase_materials: tuple[BoussinesqMaterial, ...]
    support: ThermalSupportParameters
    axial_depth_m: float
    birth_enthalpy_stock_j: float
    basal_heat_stock_j: float
    water_stock_m3: float
    source_id: str
    birth_heat_source_id: str
    basal_heat_source_id: str
    water_source_id: str
    left_export_id: str
    right_export_id: str

    def __post_init__(self):
        if type(self.plate) is not PlateCoolingParameters:
            raise TectonicsError('typed finite cooling plate required')
        if (type(self.phase_materials) is not tuple or not 1 <= len(self.phase_materials) <= 16
                or any(type(m) is not BoussinesqMaterial for m in self.phase_materials)):
            raise TectonicsError('one to sixteen ordered phase materials required')
        for m in self.phase_materials:
            _plate_material(self.plate, m, self.support)
            if m.reference_temperature_k != self.plate.thermal.mantle_temperature_k:
                raise TectonicsError('ocean phase EOS must bind the hot birth reference')
        if self.support.fill_density_kg_m3 <= 0:
            raise TectonicsError('this ocean route requires a positive water density')
        object.__setattr__(self, 'axial_depth_m', scalar(self.axial_depth_m, 'axial depth', positive=True))
        for key in ('birth_enthalpy_stock_j', 'basal_heat_stock_j', 'water_stock_m3'):
            object.__setattr__(self, key, scalar(getattr(self, key), key, nonnegative=True))
        for key in ('source_id', 'birth_heat_source_id', 'basal_heat_source_id', 'water_source_id',
                    'left_export_id', 'right_export_id'):
            _name(getattr(self, key), key)
        if len({self.birth_heat_source_id, self.basal_heat_source_id, self.water_source_id}) != 3:
            raise TectonicsError('distinct heat-transfer, basal and water reservoir IDs required')


@dataclass(frozen=True, slots=True)
class ThermalExport:
    side: str
    destination_id: str
    width_m: float
    first_exit_offset_s: float
    last_exit_offset_s: float
    first_exit_age_s: float
    last_exit_age_s: float


@dataclass(frozen=True, slots=True, init=False)
class SpreadingThermalState:
    """A derived candidate; no reservoir is mutated until a later workflow commits.

    Values are means over the occupied ocean portion, NOT the whole possibly
    partial cell. Columns: phase temperatures K, sheet kg/m2, subsidence m,
    water depth m, cumulative outward top/base heat J/m2. Empty values are zero
    placeholders identified by ocean_fraction / centre_valid, never zero-K ocean.
    """
    plan_id: str
    state_id: str
    parent_state_id: str | None
    motion: SpreadingState
    exports: tuple[ThermalExport, ThermalExport]
    _n: int = field(repr=False)
    _p: int = field(repr=False)
    _cells: bytes = field(repr=False)
    _centres: bytes = field(repr=False)
    _fraction: bytes = field(repr=False)
    _mask: bytes = field(repr=False)
    _heat: bytes = field(repr=False)
    _water: bytes = field(repr=False)

    @property
    def time_s(self):
        return self.motion.time_s

    @property
    def cell_values(self):
        return np.frombuffer(self._cells, dtype=np.float64).reshape(self._n, self._p+5)

    @property
    def centre_values(self):
        return np.frombuffer(self._centres, dtype=np.float64).reshape(self._n, self._p+5)

    @property
    def ocean_fraction(self):
        return np.frombuffer(self._fraction, dtype=np.float64)

    @property
    def centre_valid(self):
        return np.frombuffer(self._mask, dtype=np.bool_)

    @property
    def heat_accounts_j(self):
        """Birth,remaining,basal,remaining,surface,resident,L/R export,residual,relative."""
        return np.frombuffer(self._heat, dtype=np.float64)

    @property
    def water_accounts_m3(self):
        """Draw,remaining,resident,left export,right export,balance residual."""
        return np.frombuffer(self._water, dtype=np.float64)

    @property
    def nbytes(self):
        return sum(len(getattr(self, key)) for key in (
            '_cells', '_centres', '_fraction', '_mask', '_heat', '_water'))+self.motion.nbytes+2048


def _identity(state):
    digest = hashlib.sha256(_json(dict(method='atlas.w06-ocean-thermal-state.v1',
        plan=state.plan_id, parent=state.parent_state_id, motion=state.motion.state_id,
        exports=[asdict(e) for e in state.exports], n=state._n, p=state._p)))
    for key in ('_cells', '_centres', '_fraction', '_mask', '_heat', '_water'):
        digest.update(getattr(state, key))
    return digest.hexdigest()


def _state(plan, motion, parent, exports, cell, centre, fraction, valid, heat, water):
    result = object.__new__(SpreadingThermalState)
    fields = dict(plan_id=plan.plan_id, parent_state_id=parent, motion=motion, exports=exports,
        _n=plan.spreading.grid.cells, _p=len(plan.spreading.phases),
        _cells=_immutable_bytes(cell), _centres=_immutable_bytes(centre),
        _fraction=_immutable_bytes(fraction), _mask=np.asarray(valid, dtype=np.bool_).tobytes(),
        _heat=_immutable_bytes(np.asarray(heat)), _water=_immutable_bytes(np.asarray(water)))
    for key, value in fields.items():
        object.__setattr__(result, key, value)
    object.__setattr__(result, 'state_id', _identity(result))
    return result


def _remaining(stock, demand, name):
    scalar(demand, name+' demand', nonnegative=True)
    if demand > stock:
        raise TectonicsError(name+' exhausted; complete thermal transaction refused')
    remainder = stock-demand
    _account(stock, remainder, -demand, 0., 0.)
    return remainder


def _export_history(spreading, elapsed, parameters):
    """Exact constant-velocity boundary crossings, independently of cell sums."""
    motion = spreading.motion
    r0, vr = motion.ridge_position_m, motion.ridge_velocity_m_s
    bounds = spreading.grid.edges_m[[0, -1]]
    records = []
    for side, speed, distance, relative, sign, destination in (
        ('left', -motion.left_velocity_m_s, r0-float(bounds[0]),
         vr-motion.left_velocity_m_s, 1., parameters.left_export_id),
        ('right', motion.right_velocity_m_s, float(bounds[1])-r0,
         motion.right_velocity_m_s-vr, -1., parameters.right_export_id)):
        width = max(speed*elapsed-distance, 0.)
        if width == 0:
            records.append(ThermalExport(side, destination, 0., 0., 0., 0., 0.))
            continue
        first = scalar(distance/speed, 'first boundary exit', positive=True)
        last_age = scalar(math.fsum((distance, sign*vr*elapsed))/relative,
                          'age at boundary exit', nonnegative=True)
        if not first < elapsed:
            raise TectonicsError('boundary crossing interval is not numerically resolvable')
        records.append(ThermalExport(side, destination, width, first, elapsed, first, last_age))
    return tuple(records)


@dataclass(frozen=True, slots=True, init=False)
class PreparedSpreadingCooling:
    """Layered constant-property cooling of a source-bound Step-2 birth plan.

    Owns no motion plan or shared ExecutionContext. Closing the parent invalidates
    this adapter. All initial feeds are finite; states are immutable branches.
    """
    spreading: PreparedRidgeSpreading
    parameters: OceanCoolingParameters
    plan_id: str
    initial: SpreadingThermalState
    _depths: bytes = field(repr=False)
    _budget: object = field(repr=False, compare=False)
    _lease: object = field(repr=False, compare=False)
    _closed: bool = field(repr=False, compare=False)

    def __init__(self, spreading, parameters, *, budget=None, cancel=None):
        if type(spreading) is not PreparedRidgeSpreading or type(parameters) is not OceanCoolingParameters:
            raise TectonicsError('typed spreading plan and ocean cooling parameters required')
        _cancelled(cancel); spreading._check(spreading.initial); spreading._context.verify()
        if len(parameters.phase_materials) != len(spreading.phases):
            raise TectonicsError('exactly one ordered thermal material per spreading phase required')
        for phase, material in zip(spreading.phases, parameters.phase_materials):
            if phase.density_kg_m3 != material.density_kg_m3:
                raise TectonicsError('phase reference mass and thermal density disagree')
        depths = np.array([0.]+[math.fsum(p.thickness_m for p in spreading.phases[:i+1])
                               for i in range(len(spreading.phases))])
        if depths[-1] != parameters.plate.thickness_m or np.any(np.diff(depths) <= 0):
            raise TectonicsError('nonoverlapping thermal phases must exactly cover the selected plate')
        resource = spreading._budget if budget is None else select_budget(budget)
        _within_budget(resource, spreading._budget)
        n, p = spreading.grid.cells, len(spreading.phases)
        lease = resource.reserve((16*(p+5)+48)*n+16384, category='spreading-thermal-prepared')
        lease.__enter__()
        try:
            descriptor = dict(method='atlas.w06-ocean-cooling.v1', motion=spreading.plan_id,
                              parameters=asdict(parameters), heat_tolerance=HEAT_RELATIVE_TOLERANCE)
            for key, value in dict(spreading=spreading, parameters=parameters,
                    plan_id=hashlib.sha256(_json(descriptor)).hexdigest(), _depths=_immutable_bytes(depths),
                    _budget=resource, _lease=lease, _closed=False).items():
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
            raise TectonicsError('spreading cooling preparation is closed')
        if (type(state) is not SpreadingThermalState or state.plan_id != self.plan_id
                or state._n != self.spreading.grid.cells or state._p != len(self.spreading.phases)):
            raise TectonicsError('thermal state belongs to a different plan')
        self.spreading._check(state.motion)
        if _identity(state) != state.state_id:
            raise TectonicsError('thermal state content no longer matches its identity')

    def _values(self, young, old, resource, cancel):
        """Reuse exactly equal intervals/point ages, not approximate age bins."""
        intervals = np.column_stack((young, old))
        unique, inverse = np.unique(intervals, axis=0, return_inverse=True)
        deficit, heat = spreading_thermal_means(unique[:, 0], unique[:, 1], self.depth_edges_m,
            self.parameters.plate, budget=resource, cancel=cancel)
        parameters = self.parameters
        span = parameters.plate.thermal.mantle_temperature_k-parameters.plate.thermal.surface_temperature_k
        widths = np.diff(self.depth_edges_m)
        if (np.any(deficit < 0) or np.any(deficit > span*widths*(1+64*np.finfo(float).eps))
                or np.any(heat[:, 0] < 0) or np.any(heat[:, 1] > 0)):
            raise TectonicsError('cooling integrals outside the selected physical envelope')
        sheet = deficit @ np.array([m.density_kg_m3*m.expansion_per_k for m in parameters.phase_materials])
        subsidence = sheet/parameters.support.restoring_density_contrast_kg_m3
        if np.any(subsidence > parameters.support.max_relative_deflection*parameters.plate.thickness_m):
            raise TectonicsError('ocean thermal subsidence exceeds small-deflection envelope')
        values = np.column_stack((parameters.plate.thermal.mantle_temperature_k-deficit/widths,
                                  sheet, subsidence, parameters.axial_depth_m+subsidence, heat))
        return values[inverse], deficit[inverse]

    def _evaluate(self, motion, parent, resource, cancel):
        source, parameters = self.spreading, self.parameters
        n, p = source.grid.cells, len(source.phases)
        elapsed = motion.elapsed_s
        plate = parameters.plate
        capacity = plate.volumetric_heat_capacity_j_m3_k
        hot_energy = _product(capacity, plate.thermal.mantle_temperature_k-plate.thermal.surface_temperature_k,
                              plate.thickness_m)
        created_area = _product(source.motion.right_velocity_m_s-source.motion.left_velocity_m_s,
                                elapsed, source.width_m)
        birth = _product(created_area, hot_energy)
        birth_remaining = _remaining(parameters.birth_enthalpy_stock_j, birth, 'birth enthalpy allowance')
        # Even before cooling, opening the area needs its axial water column.
        _remaining(parameters.water_stock_m3, _product(created_area, parameters.axial_depth_m), 'water reservoir')
        with resource.reserve((512+128*p)*n+32768, category='spreading-thermal-output'):
            if elapsed == 0:
                # Empty ocean has no thermal queries, no water and no heat. Do
                # not allocate the integration workspace for zero-area outputs.
                heat = (0., parameters.birth_enthalpy_stock_j, 0., parameters.basal_heat_stock_j,
                        0., 0., 0., 0., 0., 0.)
                water = (0., parameters.water_stock_m3, 0., 0., 0., 0.)
                _cancelled(cancel)
                return _state(self, motion, parent, _export_history(source, elapsed, parameters),
                              np.zeros((n, p+5)), np.zeros((n, p+5)), np.zeros(n),
                              np.zeros(n, dtype=np.bool_), heat, water)
            geometry = motion.cell_geometry
            widths = geometry[..., 0]
            occupied_width = widths.sum(axis=0)
            fraction = occupied_width/source.grid.widths_m
            valid = widths > 0
            count = int(np.sum(valid))
            young, old = geometry[..., 1][valid], geometry[..., 2][valid]
            local_edges = source.grid.edges_m-source.motion.ridge_position_m
            centres = local_edges[:-1]+.5*np.diff(local_edges)
            ridge = source.motion.ridge_velocity_m_s*elapsed
            left = source.motion.left_velocity_m_s*elapsed
            right = source.motion.right_velocity_m_s*elapsed
            centre_valid = (centres >= left) & (centres <= right) & (elapsed > 0)
            c = centres[centre_valid]
            left_rate = source.motion.ridge_velocity_m_s-source.motion.left_velocity_m_s
            right_rate = source.motion.right_velocity_m_s-source.motion.ridge_velocity_m_s
            ages = np.where(c <= ridge, (ridge-c)/left_rate, (c-ridge)/right_rate)
            exports = _export_history(source, elapsed, parameters)
            export_young = np.array([min(e.first_exit_age_s, e.last_exit_age_s) for e in exports])
            export_old = np.array([max(e.first_exit_age_s, e.last_exit_age_s) for e in exports])
            # Check the oldest actual column ever represented, not merely means.
            oldest = max(float(np.max(old, initial=0)), float(np.max(export_old, initial=0)))
            all_young = np.r_[young, ages, export_young, oldest]
            all_old = np.r_[old, ages, export_old, oldest]
            values, deficit = self._values(all_young, all_old, resource, cancel)
            side_values = np.zeros((2, n, p+5))
            side_deficit = np.zeros((2, n, p))
            side_values[valid] = values[:count]
            side_deficit[valid] = deficit[:count]
            cell = np.zeros((n, p+5))
            mask = occupied_width > 0
            # Normalised side weights avoid multiplying Kelvin by huge widths.
            weights = np.zeros_like(widths)
            np.divide(widths, occupied_width[None, :], out=weights, where=mask[None, :])
            cell[mask] = np.sum(side_values*weights[..., None], axis=0)[mask]
            centre = np.zeros_like(cell)
            centre[centre_valid] = values[count:count+len(ages)]
            exported_values = values[count+len(ages):count+len(ages)+2]
            exported_deficit = deficit[count+len(ages):count+len(ages)+2]
            areas = widths*source.width_m
            export_areas = np.array([e.width_m*source.width_m for e in exports])
            represented = math.fsum((areas*(hot_energy-capacity*np.sum(side_deficit, axis=-1))).flat)
            export_energy = export_areas*(hot_energy-capacity*np.sum(exported_deficit, axis=-1))
            # Cumulative exchanges up to output for residents and up to exit for
            # exported columns. No post-exit heat exchange is charged regionally.
            surface = math.fsum((*((areas*side_values[..., -2]).flat),
                                 *(export_areas*exported_values[:, -2])))
            basal = -math.fsum((*((areas*side_values[..., -1]).flat),
                               *(export_areas*exported_values[:, -1])))
            basal_remaining = _remaining(parameters.basal_heat_stock_j, basal, 'basal heat allowance')
            residual = math.fsum((represented, *export_energy, surface, -basal, -birth))
            scale = max(birth, math.fsum((abs(basal), abs(surface), *(abs(e) for e in export_energy))))
            if scale == 0 and residual != 0:
                raise TectonicsError('nonzero heat residual without any heat input')
            relative = 0. if scale == 0 else residual/scale
            if not math.isfinite(relative) or abs(relative) > HEAT_RELATIVE_TOLERANCE:
                raise TectonicsError('moving-domain ocean heat balance does not close')
            resident_water = math.fsum((areas*side_values[..., p+2]).flat)
            export_water = export_areas*exported_values[:, p+2]
            drawn = math.fsum((resident_water, *export_water))
            water_remaining = _remaining(parameters.water_stock_m3, drawn, 'water reservoir')
            water_residual = _account(drawn, resident_water, -export_water[0], -export_water[1], 0.)[4]
            heat_accounts = (birth, birth_remaining, basal, basal_remaining, surface, represented,
                             *export_energy, residual, relative)
            water_accounts = (drawn, water_remaining, resident_water, *export_water, water_residual)
            _cancelled(cancel)
            return _state(self, motion, parent, exports, cell, centre, fraction, centre_valid,
                          heat_accounts, water_accounts)

    def advance(self, state, *, time_s, budget=None, cancel=None):
        self._check(state); _cancelled(cancel); self.spreading._context.verify()
        end = scalar(time_s, 'requested thermal time')
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
