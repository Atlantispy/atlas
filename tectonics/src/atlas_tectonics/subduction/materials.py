"""W08 finite, prescribed constant-rate retirement of crust/mantle inventories.

This is an explicit section material account, not a slab geometry, mixing law or
event-history workflow. Constant normal flux debits finite named cohorts; all
destinations receive their prescribed shares simultaneously. Signed enthalpy and
complete component masses follow the same homogeneous donor fraction.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict, field
import json
import math
import platform
from typing import cast

import numpy as np

from atlas_tectonics._validation import TectonicsError, read_array, scalar
from atlas_tectonics._validation import _PLANAR_ROUNDOFF as _ROUND
from atlas_tectonics.materials.materials import MaterialCohort, _catalogue, _name, _json, _immutable_bytes
from atlas_tectonics.integration.resources import WorkBudget, DEFAULT_BUDGET, select_budget
from atlas_tectonics.integration.resources import check_event
from atlas_tectonics.integration.resources import record_id
from atlas_tectonics.planet.timebase import interval_end


DESTINATIONS = ('accretion', 'deep-storage', 'export')
SECTION_POLICY = 'translation-invariant-along-strike'
_DEFAULT_BUDGET = WorkBudget(128*1024**2, parent=DEFAULT_BUDGET)


def _sum(values):
    try: result = math.fsum(float(x) for x in values)
    except (OverflowError, ValueError) as exc:
        raise TectonicsError('retirement account exceeds numerical range') from exc
    return result


def _balance(before, remaining, allocations):
    values = tuple(float(x) for x in allocations)
    residual = _sum((remaining, *values, -before))
    return residual


@dataclass(frozen=True, slots=True, init=False)
class SubductionInventory:
    """Finite homogeneous cohort stocks; components exhaustively partition mass.

    Formation metadata reuses W02 MaterialCohort without merging histories. Every
    row identifies crust or mantle explicitly. Enthalpy is signed joules in the
    supplied convention; a zero-mass row cannot retain components or enthalpy.
    Owner-retained payloads require the caller's separate memory allowance.
    """
    cohorts: tuple[MaterialCohort, ...]
    layer_kinds: tuple[str, ...]
    component_ids: tuple[str, ...]
    time_s: float
    epoch_id: str
    source_id: str
    enthalpy_source: str
    inventory_id: str
    _mass: bytes = field(repr=False)
    _components: bytes = field(repr=False)
    _heat: bytes = field(repr=False)
    _record: bytes = field(repr=False)

    def __init__(self, cohorts, layer_kinds, mass_kg, component_ids, component_mass_kg,
                 enthalpy_j, *, time_s, epoch_id, source_id, enthalpy_source,
                 budget=None, cancel=None):
        check_event(cancel, 'regional transport cancelled; no candidate published'); now = scalar(time_s, 'inventory time')
        _catalogue(cohorts, now); count = len(cohorts)
        for name in component_ids: _name(name, 'component ID')
        for value, label in ((epoch_id, 'epoch'), (source_id, 'inventory source'),
                             (enthalpy_source, 'enthalpy convention/source')): _name(value, label)
        resource = _DEFAULT_BUDGET if budget is None else select_budget(budget)
        with resource.reserve(96*count*(len(component_ids)+2)+4096*count+8192,
                              category='subduction-inventory'):
            mass = read_array(mass_kg, 'finite mass', nonnegative=True)
            components = read_array(component_mass_kg, 'finite component masses', nonnegative=True)
            heat = read_array(enthalpy_j, 'signed enthalpy')
            for i in range(count):
                _balance(mass[i], 0., components[i])
            record = dict(schema='atlas.w08-subduction-inventory.v1', cohorts=[asdict(c) for c in cohorts],
                layer_kinds=layer_kinds, component_ids=component_ids, time_s=now,
                epoch_id=epoch_id, source=source_id, enthalpy_source=enthalpy_source,
                composition='complete-homogeneous-cohort-component-masses', enthalpy_unit='J')
            payload = _immutable_bytes(mass), _immutable_bytes(components), _immutable_bytes(heat), _json(record)
            values = dict(cohorts=cohorts, layer_kinds=layer_kinds, component_ids=component_ids,
                time_s=now, epoch_id=epoch_id, source_id=source_id, enthalpy_source=enthalpy_source,
                inventory_id=record_id(record, *payload, encode=_json), _mass=payload[0], _components=payload[1],
                _heat=payload[2], _record=payload[3])
            for name, value in values.items(): object.__setattr__(self, name, value)
            check_event(cancel, 'regional transport cancelled; no candidate published')

    @property
    def mass_kg(self): return np.frombuffer(self._mass, np.float64)
    @property
    def component_mass_kg(self):
        return np.frombuffer(self._components, np.float64).reshape(len(self.cohorts), len(self.component_ids))
    @property
    def enthalpy_j(self): return np.frombuffer(self._heat, np.float64)
    @property
    def nbytes(self): return sum(map(len, (self._mass, self._components, self._heat, self._record)))
    def descriptor(self): return json.loads(self._record)


class RetirementExhaustionError(TectonicsError):
    """Requested constant-rate interval crosses the first finite donor event."""
    def __init__(self, duration_s, cohort_ids):
        self.exhaustion_duration_s = duration_s
        self.exhausted_cohort_ids = cohort_ids
        super().__init__('finite retirement stock exhausts at duration '+repr(duration_s)
                         +' s; split the interval and supply an explicit continuation policy')


@dataclass(frozen=True, slots=True)
class SubductionRetirementResult:
    plan_id: str
    result_id: str
    duration_s: float
    remaining: SubductionInventory
    destination_ids: tuple[str, str, str]
    _retired: bytes = field(repr=False)
    _destinations: bytes = field(repr=False)
    _residuals: bytes = field(repr=False)
    _record: bytes = field(repr=False)

    def _array(self, payload, destinations=False):
        c, k = len(self.remaining.cohorts), len(self.remaining.component_ids)+2
        return np.frombuffer(payload, np.float64).reshape((3, c, k) if destinations else (c, k))
    @property
    def retired_mass_kg(self): return self._array(self._retired)[:, 0]
    @property
    def retired_enthalpy_j(self): return self._array(self._retired)[:, 1]
    @property
    def retired_component_mass_kg(self): return self._array(self._retired)[:, 2:]
    @property
    def destination_mass_kg(self): return self._array(self._destinations, True)[:, :, 0]
    @property
    def destination_enthalpy_j(self): return self._array(self._destinations, True)[:, :, 1]
    @property
    def destination_component_mass_kg(self): return self._array(self._destinations, True)[:, :, 2:]
    @property
    def account_residuals(self): return self._array(self._residuals)
    @property
    def nbytes(self):
        return self.remaining.nbytes+sum(map(len, (self._retired, self._destinations, self._residuals, self._record)))
    def descriptor(self): return json.loads(self._record)


class PreparedSubductionRetirement:
    """Exact constant-rate branches of supplied finite stocks, not a stock ledger.

    Vectors use one named right-handed 3D Cartesian frame. The normal and strike
    directions must be orthogonal unit vectors; neither is silently normalised.
    rho*H*(v_material-v_boundary).normal is kg/(m s), multiplied by the declared
    section width for kg/s. H is the occupied boundary height normal to strike.
    The explicit translation-invariant section policy retains all tangential and
    along-strike velocities but models no flux through along-strike side faces.
    Negative normal flow is incoming supply and requires a separate declared law.
    Every evaluate() starts from the original inventory. Publication/continuation
    owners must serialise spending and perform complete source verification.
    """
    def __setattr__(self, name, value):
        object.__setattr__(self, name, value)

    def __init__(self, inventory, *, density_kg_m3, thickness_m, material_velocity_m_s,
                 boundary_velocity_m_s, outward_normal, strike_direction, section_width_m,
                 frame_id, section_policy, destination_kinds, destination_ids,
                 destination_fractions, flux_source, partition_source, source_id,
                 budget=None, cancel=None):
        check_event(cancel, 'regional transport cancelled; no candidate published')
        c, k = len(inventory.cohorts), len(inventory.component_ids)
        for value in destination_ids: _name(value, 'destination ID')
        for value, label in ((frame_id, 'frame'), (flux_source, 'flux source'),
                (partition_source, 'partition source'), (source_id, 'retirement source')): _name(value, label)
        width = scalar(section_width_m, 'section width', positive=True)
        resource = _DEFAULT_BUDGET if budget is None else select_budget(budget)
        lease = resource.reserve(inventory.nbytes+512*c*(k+16)+32768, category='subduction-retirement-prepared')
        lease.__enter__()
        try:
            density = read_array(density_kg_m3, 'reference density', nonnegative=True)
            thickness = read_array(thickness_m, 'boundary thickness', nonnegative=True)
            material = read_array(material_velocity_m_s, 'material velocity')
            boundary = read_array(boundary_velocity_m_s, 'boundary velocity')
            normal = read_array(outward_normal, 'outward normal'); strike = read_array(strike_direction, 'strike direction')
            partition = read_array(destination_fractions, 'destination fractions', nonnegative=True)
            if np.any(partition > 1): raise TectonicsError('destination fractions cannot exceed one')
            for row in partition:
                if abs(_sum(row)-1.) > _ROUND: raise TectonicsError('destination fractions must sum to one')
            order = [destination_kinds.index(kind) for kind in DESTINATIONS]
            partition = partition[:, order]; ids = tuple(destination_ids[i] for i in order)
            with np.errstate(over='ignore', invalid='ignore'):
                relative = material-boundary
            vn = np.array([_sum(row*normal) for row in relative])
            along = np.array([_sum(row*strike) for row in relative])
            with np.errstate(over='ignore', invalid='ignore', under='ignore'):
                per_strike = density*thickness*vn; rate = per_strike*width
                tangent = relative-vn[:, None]*normal
            times = tuple(None if q == 0 else scalar(float(m)/float(q), 'finite exhaustion duration', nonnegative=True)
                          for m, q in zip(inventory.mass_kg, rate))
            finite = [t for t in times if t is not None]
            exhaustion = min(finite) if finite else None
            exhausted = tuple(cohort.cohort_id for cohort, time in zip(inventory.cohorts, times)
                              if time is not None and time == exhaustion)
            record = dict(method='atlas.w08-subduction-retirement.v1', inventory=inventory.inventory_id,
                source=source_id, flux_source=flux_source, partition_source=partition_source,
                frame=frame_id, section_policy=section_policy, section_width_m=width,
                outward_normal=normal.tolist(), strike_direction=strike.tolist(),
                density_kg_m3=density.tolist(), thickness_m=thickness.tolist(),
                material_velocity_m_s=material.tolist(), boundary_velocity_m_s=boundary.tolist(),
                relative_velocity_m_s=relative.tolist(), tangential_velocity_m_s=tangent.tolist(),
                destination_kinds=DESTINATIONS, destination_ids=ids, fractions=partition.tolist(),
                cohort_exhaustion_durations_s=times, exhaustion_duration_s=exhaustion,
                exhausted_cohort_ids=exhausted, runtime=dict(python=platform.python_version(), numpy=np.__version__))
            self.inventory = inventory; self.destination_ids = ids; self.destination_kinds = DESTINATIONS
            self.exhaustion_duration_s = exhaustion; self.exhausted_cohort_ids = exhausted
            self.cohort_exhaustion_durations_s = times
            self._flows = cast(bytes, _immutable_bytes(np.stack((vn, per_strike, rate, along))))
            self._tangent = cast(bytes, _immutable_bytes(tangent)); self._partition = cast(bytes, _immutable_bytes(partition))
            self._record = _json(record); self.plan_id = record_id(record, self._flows, self._partition, self._tangent, encode=_json)
            self._budget = resource; self._lease = lease; self._closed = False
            check_event(cancel, 'regional transport cancelled; no candidate published'); self._sealed = True
        except BaseException:
            lease.__exit__(None, None, None); raise

    def _flow(self, index): return np.frombuffer(self._flows, np.float64).reshape(4, len(self.inventory.cohorts))[index]
    @property
    def normal_velocity_m_s(self): return self._flow(0)
    @property
    def mass_flux_kg_m_s(self): return self._flow(1)
    @property
    def mass_flux_kg_s(self): return self._flow(2)
    @property
    def along_strike_velocity_m_s(self): return self._flow(3)
    @property
    def tangential_velocity_m_s(self): return np.frombuffer(self._tangent, np.float64).reshape(-1, 3)
    @property
    def destination_fractions(self): return np.frombuffer(self._partition, np.float64).reshape(-1, 3)
    def descriptor(self): return json.loads(self._record)

    def evaluate(self, duration_s, *, end_time_s=None, cancel=None):
        """A declared ``end_time_s`` (duration exactly end-start) is the published end."""
        check_event(cancel, 'regional transport cancelled; no candidate published'); duration = scalar(duration_s, 'retirement duration', nonnegative=True)
        if self.exhaustion_duration_s is not None and duration > self.exhaustion_duration_s:
            raise RetirementExhaustionError(self.exhaustion_duration_s, self.exhausted_cohort_ids)
        source = self.inventory; c, k = len(source.cohorts), len(source.component_ids)
        if duration > 0 and end_time_s is not None:
            end = interval_end(source.time_s, duration, end_time_s)
        else:
            end = scalar(source.time_s+duration, 'retirement endpoint')
        with self._budget.reserve(512*c*(k+2)+16384, category='subduction-retirement-output'):
            mass = source.mass_kg; initial = np.column_stack((mass, source.enthalpy_j, source.component_mass_kg))
            with np.errstate(over='ignore', invalid='ignore', under='ignore'):
                retired_mass = self.mass_flux_kg_s*duration
            # Equality with the computed event is a named exact endpoint, not a
            # min(stock,demand) clamp or an allocation-dependent cutoff.
            for i, time in enumerate(self.cohort_exhaustion_durations_s):
                if time is not None and duration == time: retired_mass[i] = mass[i]
            if (not np.isfinite(retired_mass).all() or np.any(retired_mass > mass)
                    or np.any((self.mass_flux_kg_s > 0) & (duration > 0) & (retired_mass == 0))):
                raise TectonicsError('prescribed retirement demand is not representable within finite stock')
            fraction = np.divide(retired_mass, mass, out=np.zeros(c), where=mass != 0)
            retired = initial*fraction[:, None]; retired[:, 0] = retired_mass
            remaining_mass = mass-retired_mass
            remaining_fraction = np.divide(remaining_mass, mass, out=np.zeros(c), where=mass != 0)
            # Scale each extensive component from its original homogeneous stock.
            # Subtracting two almost equal component stocks near exhaustion would
            # destroy the composition of the small remaining inventory.
            remaining = initial*remaining_fraction[:, None]; remaining[:, 0] = remaining_mass
            allocated = self.destination_fractions.T[:, :, None]*retired[None, :, :]
            residual = np.empty_like(initial)
            for i in range(c):
                check_event(cancel, 'regional transport cancelled; no candidate published')
                for j in range(k+2): residual[i, j] = _balance(initial[i, j], remaining[i, j], allocated[:, i, j])
                _balance(retired[i, 0], 0., retired[i, 2:])
                for destination in allocated[:, i]: _balance(destination[0], 0., destination[2:])
            remainder = SubductionInventory(source.cohorts, source.layer_kinds, remaining[:, 0],
                source.component_ids, remaining[:, 2:], remaining[:, 1], time_s=end,
                epoch_id=source.epoch_id, source_id=self.plan_id, enthalpy_source=source.enthalpy_source,
                budget=self._budget, cancel=cancel)
            record = dict(operation='atlas.w08-subduction-retirement-result.v1', plan=self.plan_id,
                initial=source.inventory_id, remaining=remainder.inventory_id, duration_s=duration,
                destination_kinds=DESTINATIONS, destination_ids=self.destination_ids,
                exhaustion_duration_s=self.exhaustion_duration_s, exhausted_cohort_ids=(
                    self.exhausted_cohort_ids if duration == self.exhaustion_duration_s else ()),
                field_order=('mass_kg', 'enthalpy_j', *source.component_ids),
                meaning='single-initial-inventory-branch-not-cumulative-spending',
                enthalpy_source=source.enthalpy_source)
            payload = cast(bytes, _immutable_bytes(retired)), cast(bytes, _immutable_bytes(allocated)), cast(bytes, _immutable_bytes(residual)), _json(record)
            result = SubductionRetirementResult(self.plan_id, record_id(record, *payload, encode=_json), duration, remainder,
                                                self.destination_ids, *payload)
            check_event(cancel, 'regional transport cancelled; no candidate published'); return result

    def close(self):
        if not self._closed:
            object.__setattr__(self, '_closed', True); self._lease.__exit__(None, None, None)
    def __enter__(self):
        return self
    def __exit__(self, *args): self.close()
