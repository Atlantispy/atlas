"""W08 finite, prescribed constant-rate retirement of crust/mantle inventories.

This is an explicit section material account, not a slab geometry, mixing law or
event-history workflow. Constant normal flux debits finite named cohorts; all
destinations receive their prescribed shares simultaneously. Signed enthalpy and
complete component masses follow the same homogeneous donor fraction.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict, field
import hashlib
import json
import math
import platform

import numpy as np

from ._validation import TectonicsError, input_shape, read_array, scalar
from .materials import MaterialCohort, _catalogue, _name, _json, _immutable_bytes
from .regional import _cancelled
from .resources import WorkBudget, DEFAULT_BUDGET, select_budget


DESTINATIONS = ('accretion', 'deep-storage', 'export')
SECTION_POLICY = 'translation-invariant-along-strike'
_ROUND = float(128*np.finfo(float).eps)
_DEFAULT_BUDGET = WorkBudget(128*1024**2, parent=DEFAULT_BUDGET)


def _id(record, *payload):
    digest = hashlib.sha256(_json(record))
    for value in payload: digest.update(b'\0'); digest.update(value)
    return digest.hexdigest()


def _sum(values):
    try: result = math.fsum(float(x) for x in values)
    except (OverflowError, ValueError) as exc:
        raise TectonicsError('retirement account exceeds numerical range') from exc
    if not math.isfinite(result): raise TectonicsError('retirement account exceeds numerical range')
    return result


def _balance(before, remaining, allocations):
    values = tuple(float(x) for x in allocations)
    residual = _sum((remaining, *values, -before))
    scale = _sum((abs(before), abs(remaining), *(abs(x) for x in values)))
    if abs(residual) > _ROUND*scale:
        raise TectonicsError('retirement extensive account does not reconcile')
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
        _cancelled(cancel); now = scalar(time_s, 'inventory time')
        if type(cohorts) is not tuple or not 1 <= len(cohorts) <= 64:
            raise TectonicsError('one to 64 explicit material cohorts required')
        _catalogue(cohorts, now); count = len(cohorts)
        if (type(layer_kinds) is not tuple or len(layer_kinds) != count
                or any(value not in ('crust', 'mantle') for value in layer_kinds)):
            raise TectonicsError('explicit crust/mantle classification per cohort required')
        if type(component_ids) is not tuple or not 1 <= len(component_ids) <= 64:
            raise TectonicsError('one to 64 named complete mass components required')
        for name in component_ids: _name(name, 'component ID')
        if component_ids != tuple(sorted(set(component_ids))):
            raise TectonicsError('component IDs must be unique and lexically sorted')
        for value, label in ((epoch_id, 'epoch'), (source_id, 'inventory source'),
                             (enthalpy_source, 'enthalpy convention/source')): _name(value, label)
        if (input_shape(mass_kg) != (count,) or input_shape(enthalpy_j) != (count,)
                or input_shape(component_mass_kg) != (count, len(component_ids))):
            raise TectonicsError('mass/enthalpy need cohort rows and components need (cohort, component) shape')
        resource = _DEFAULT_BUDGET if budget is None else select_budget(budget)
        with resource.reserve(96*count*(len(component_ids)+2)+4096*count+8192,
                              category='subduction-inventory'):
            mass = read_array(mass_kg, 'finite mass', nonnegative=True)
            components = read_array(component_mass_kg, 'finite component masses', nonnegative=True)
            heat = read_array(enthalpy_j, 'signed enthalpy')
            for i in range(count):
                _balance(mass[i], 0., components[i])
                if mass[i] == 0 and (heat[i] != 0 or np.any(components[i] != 0)):
                    raise TectonicsError('empty mass cannot carry components or enthalpy; no implicit pass-through law')
            record = dict(schema='atlas.w08-subduction-inventory.v1', cohorts=[asdict(c) for c in cohorts],
                layer_kinds=layer_kinds, component_ids=component_ids, time_s=now,
                epoch_id=epoch_id, source=source_id, enthalpy_source=enthalpy_source,
                composition='complete-homogeneous-cohort-component-masses', enthalpy_unit='J')
            payload = _immutable_bytes(mass), _immutable_bytes(components), _immutable_bytes(heat), _json(record)
            values = dict(cohorts=cohorts, layer_kinds=layer_kinds, component_ids=component_ids,
                time_s=now, epoch_id=epoch_id, source_id=source_id, enthalpy_source=enthalpy_source,
                inventory_id=_id(record, *payload), _mass=payload[0], _components=payload[1],
                _heat=payload[2], _record=payload[3])
            for name, value in values.items(): object.__setattr__(self, name, value)
            _cancelled(cancel)

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
        if getattr(self, '_sealed', False): raise AttributeError('prepared retirement is immutable')
        object.__setattr__(self, name, value)

    def __init__(self, inventory, *, density_kg_m3, thickness_m, material_velocity_m_s,
                 boundary_velocity_m_s, outward_normal, strike_direction, section_width_m,
                 frame_id, section_policy, destination_kinds, destination_ids,
                 destination_fractions, flux_source, partition_source, source_id,
                 budget=None, cancel=None):
        _cancelled(cancel)
        if type(inventory) is not SubductionInventory: raise TectonicsError('explicit SubductionInventory required')
        c, k = len(inventory.cohorts), len(inventory.component_ids)
        if (input_shape(density_kg_m3) != (c,) or input_shape(thickness_m) != (c,)
                or input_shape(material_velocity_m_s) != (c, 3)
                or input_shape(boundary_velocity_m_s) != (c, 3)
                or input_shape(outward_normal) != (3,) or input_shape(strike_direction) != (3,)
                or input_shape(destination_fractions) != (c, 3)):
            raise TectonicsError('cohort density/thickness, full 3D velocities, 3D section vectors and three destination fractions required')
        if section_policy != SECTION_POLICY: raise TectonicsError('explicit translation-invariant-along-strike section policy required')
        if type(destination_kinds) is not tuple or len(destination_kinds) != 3 or set(destination_kinds) != set(DESTINATIONS):
            raise TectonicsError('explicit accretion, deep-storage and export destination kinds required')
        if type(destination_ids) is not tuple or len(destination_ids) != 3 or len(set(destination_ids)) != 3:
            raise TectonicsError('three distinct named physical destinations required')
        for value in destination_ids: _name(value, 'destination ID')
        for value, label in ((frame_id, 'frame'), (flux_source, 'flux source'),
                (partition_source, 'partition source'), (source_id, 'retirement source')): _name(value, label)
        width = scalar(section_width_m, 'section width', positive=True)
        resource = _DEFAULT_BUDGET if budget is None else select_budget(budget)
        lease = resource.reserve(inventory.nbytes+512*c*(k+16)+32768, category='subduction-retirement-prepared')
        lease.__enter__()
        try:
            density = read_array(density_kg_m3, 'reference density', nonnegative=True)
            if np.any(density <= 0): raise TectonicsError('positive constant reference density required')
            thickness = read_array(thickness_m, 'boundary thickness', nonnegative=True)
            material = read_array(material_velocity_m_s, 'material velocity')
            boundary = read_array(boundary_velocity_m_s, 'boundary velocity')
            normal = read_array(outward_normal, 'outward normal'); strike = read_array(strike_direction, 'strike direction')
            for vector in (normal, strike):
                if abs(_sum(vector*vector)-1.) > _ROUND:
                    raise TectonicsError('section vectors must be unit vectors without implicit normalisation')
            if abs(_sum(normal*strike)) > _ROUND: raise TectonicsError('normal and strike must be orthogonal')
            partition = read_array(destination_fractions, 'destination fractions', nonnegative=True)
            if np.any(partition > 1): raise TectonicsError('destination fractions cannot exceed one')
            for row in partition:
                if abs(_sum(row)-1.) > _ROUND: raise TectonicsError('destination fractions must sum to one')
            order = [destination_kinds.index(kind) for kind in DESTINATIONS]
            partition = partition[:, order]; ids = tuple(destination_ids[i] for i in order)
            with np.errstate(over='ignore', invalid='ignore'):
                relative = material-boundary
            if not np.isfinite(relative).all(): raise TectonicsError('relative boundary velocity exceeds numerical range')
            vn = np.array([_sum(row*normal) for row in relative])
            along = np.array([_sum(row*strike) for row in relative])
            if np.any(vn < 0): raise TectonicsError('incoming normal flow needs an explicit supply law; retirement cannot invent stock')
            with np.errstate(over='ignore', invalid='ignore', under='ignore'):
                per_strike = density*thickness*vn; rate = per_strike*width
                tangent = relative-vn[:, None]*normal
            if (not all(np.isfinite(x).all() for x in (per_strike, rate, tangent))
                    or np.any((thickness > 0) & (vn > 0) & (rate == 0))):
                raise TectonicsError('retirement flux exceeds numerical range')
            times = tuple(None if q == 0 else scalar(float(m)/float(q), 'finite exhaustion duration', nonnegative=True)
                          for m, q in zip(inventory.mass_kg, rate))
            if any(m > 0 and time == 0 for m, time in zip(inventory.mass_kg, times)):
                raise TectonicsError('positive-stock exhaustion time is unresolvable in binary64')
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
            self._flows = _immutable_bytes(np.stack((vn, per_strike, rate, along)))
            self._tangent = _immutable_bytes(tangent); self._partition = _immutable_bytes(partition)
            self._record = _json(record); self.plan_id = _id(record, self._flows, self._partition, self._tangent)
            self._budget = resource; self._lease = lease; self._closed = False
            _cancelled(cancel); self._sealed = True
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

    def evaluate(self, duration_s, *, cancel=None):
        if self._closed: raise TectonicsError('retirement preparation is closed')
        _cancelled(cancel); duration = scalar(duration_s, 'retirement duration', nonnegative=True)
        if self.exhaustion_duration_s is not None and duration > self.exhaustion_duration_s:
            raise RetirementExhaustionError(self.exhaustion_duration_s, self.exhausted_cohort_ids)
        source = self.inventory; c, k = len(source.cohorts), len(source.component_ids)
        end = scalar(source.time_s+duration, 'retirement endpoint')
        if duration > 0 and end == source.time_s: raise TectonicsError('inventory clock cannot resolve retirement duration')
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
            if (not np.isfinite(allocated).all() or
                    np.any((initial != 0) & (fraction[:, None] > 0) & (retired == 0)) or
                    np.any((initial != 0) & (remaining_fraction[:, None] > 0) & (remaining == 0)) or
                    np.any((retired[None, :, :] != 0) & (self.destination_fractions.T[:, :, None] > 0)
                           & (allocated == 0))):
                raise TectonicsError('retirement mass/component/enthalpy allocation exceeds numerical range')
            residual = np.empty_like(initial)
            for i in range(c):
                _cancelled(cancel)
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
            payload = _immutable_bytes(retired), _immutable_bytes(allocated), _immutable_bytes(residual), _json(record)
            result = SubductionRetirementResult(self.plan_id, _id(record, *payload), duration, remainder,
                                                self.destination_ids, *payload)
            _cancelled(cancel); return result

    def close(self):
        if not self._closed:
            object.__setattr__(self, '_closed', True); self._lease.__exit__(None, None, None)
    def __enter__(self):
        if self._closed: raise TectonicsError('retirement preparation is closed')
        return self
    def __exit__(self, *args): self.close()
