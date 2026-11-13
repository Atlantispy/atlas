"""W04 fixed-reference loads, not a flexural or isostatic displacement solver.

For each finite, fixed support, B=M+rho_fill*(V_support-V_occupied).
The imposed downward pressure is g*(B_current-B_reference)/area, plus a
separately accounted Boussinesq thermal anomaly on explicitly fixed coverage.
Future deflection-created infill belongs to the support/feedback equation,
not this prescribed load. See docs/W04_COLUMN_LOADS.md for scope and sources.
"""
from __future__ import annotations

from concurrent.futures import CancelledError
from dataclasses import asdict, dataclass
import hashlib
import json

import numpy as np

from ._validation import TectonicsError, input_shape, read_array, scalar, text
from .constitutive import BoussinesqMaterial
from .resources import select_budget
from .thermal_support import _temperature
from .stokes_execution import _factored_scale

_METHOD = 'atlas.fixed-column-loads.v1'
_MAX_COLUMNS = 2_097_152
_MAX_PHASES = 256


def _identity(record, *buffers):
    h = hashlib.sha256(json.dumps(record, sort_keys=True, separators=(',', ':'),
                                  allow_nan=False).encode('utf-8'))
    for buffer in buffers:
        h.update(buffer)
    return h.hexdigest()


def _cancel(cancel):
    if cancel is not None and cancel.is_set():
        raise CancelledError('column load construction cancelled')


def _ids(values, name, maximum):
    if type(values) is not tuple or not 0 < len(values) <= maximum:
        raise TectonicsError(name+' must be a bounded nonempty tuple')
    for value in values:
        text(value, name)
    if len(set(values)) != len(values):
        raise TectonicsError(name+' must be unique')


@dataclass(frozen=True, slots=True, init=False)
class LoadSupport:
    """Caller-attested fixed horizontal footprints and finite vertical coverage.

    geometry_source identifies the actual footprint/coverage source, not just
    the area. No spatial remapping or datum inference is performed here.
    Arrays are captured once; properties return caller-owned descriptors.
    """
    column_ids: tuple[str, ...]
    geometry_source: str
    frame_id: str
    datum_id: str
    support_id: str
    _area: bytes
    _height: bytes

    def __init__(self, column_ids, area_m2, height_m, *, geometry_source,
                 frame_id, datum_id, budget=None):
        _ids(column_ids, 'column IDs', _MAX_COLUMNS)
        for name, value in (('geometry_source', geometry_source), ('frame_id', frame_id),
                            ('datum_id', datum_id)):
            text(value, name)
        shape = (len(column_ids),)
        if input_shape(area_m2) != shape or input_shape(height_m) != shape:
            raise TectonicsError('area and finite support height must have one value per column')
        with select_budget(budget).reserve(96*len(column_ids)+8192, category='load-support'):
            a = read_array(area_m2, 'area'); h = read_array(height_m, 'height')
            if a.shape != shape or h.shape != shape or np.any(a <= 0) or np.any(h <= 0):
                raise TectonicsError('positive, unchanged support shapes required')
            with np.errstate(over='ignore', under='ignore'):
                volume = a*h
            if not np.isfinite(volume).all() or np.any(volume == 0):
                raise TectonicsError('finite support volume outside binary64 range')
            ab, hb = a.tobytes(), h.tobytes()
            for name, value in dict(column_ids=column_ids, geometry_source=geometry_source,
                    frame_id=frame_id, datum_id=datum_id, _area=ab, _height=hb,
                    support_id=_identity(dict(method=_METHOD, columns=column_ids,
                        geometry_source=geometry_source, frame=frame_id, datum=datum_id), ab, hb)).items():
                object.__setattr__(self, name, value)

    @property
    def area_m2(self):
        return np.frombuffer(self._area, dtype=np.float64)

    @property
    def height_m(self):
        return np.frombuffer(self._height, dtype=np.float64)


@dataclass(frozen=True, slots=True)
class LoadPhase:
    """A disjoint occupied inventory phase; grains and pore water are separate.

    Density is the conserved/reference inventory density, never a temperature-
    corrected density. Optional thermal material adds ONLY its unapplied anomaly.
    thermal_coverage_source attests the same fixed depth/material coverage in
    both states. Moving thermal coverage needs conservative mapping (later work).
    """
    phase_id: str
    kind: str
    density_kg_m3: float
    source: str
    thermal_material: BoussinesqMaterial | None = None
    thermal_coverage_source: str | None = None

    def __post_init__(self):
        text(self.phase_id, 'phase ID'); text(self.source, 'phase source')
        if self.kind not in ('rock', 'sediment-grain', 'pore-water', 'water', 'other'):
            raise TectonicsError('unknown inventory phase kind')
        object.__setattr__(self, 'density_kg_m3', scalar(self.density_kg_m3, 'inventory density', positive=True))
        m = self.thermal_material
        if m is None:
            if self.thermal_coverage_source is not None:
                raise TectonicsError('thermal coverage without a thermal material')
        else:
            if type(m) is not BoussinesqMaterial:
                raise TectonicsError('typed Boussinesq material required')
            text(self.thermal_coverage_source, 'fixed thermal coverage source')
            if m.density_kg_m3 != self.density_kg_m3 or m.composition_density_contrast_kg_m3 != 0:
                raise TectonicsError('thermal phase needs its uncorrected reference density and no composition anomaly')


@dataclass(frozen=True, slots=True, init=False)
class ColumnLoadState:
    """Immutable snapshot, not a W02 mass update or an already-applied deflection.

    volumes have shape (columns, phases). Missing phases must be explicit zeros
    in a common catalogue. Unoccupied volume is filled with the explicit fill
    density (zero for vacuum/neglected air). Temperature is a true volume mean
    for each thermal phase, in catalogue order; None when there are none.
    epoch_id identifies this snapshot's instant (reference/current can differ);
    this kernel does not infer a time axis or integrate a history.
    Caller-owned snapshots count against the caller's retained-state allowance.
    """
    support: LoadSupport
    phases: tuple[LoadPhase, ...]
    source_id: str
    epoch_id: str
    state_id: str
    _volumes: bytes
    _fill: bytes
    _temperature: bytes

    def __init__(self, support, phases, volume_m3, fill_density_kg_m3, *,
                 source_id, epoch_id, temperature_k=None, budget=None, cancel=None):
        _cancel(cancel)
        if type(support) is not LoadSupport:
            raise TectonicsError('explicit LoadSupport required')
        if type(phases) is not tuple or not 0 < len(phases) <= _MAX_PHASES or any(type(p) is not LoadPhase for p in phases):
            raise TectonicsError('bounded tuple of LoadPhase required')
        _ids(tuple(p.phase_id for p in phases), 'phase IDs', _MAX_PHASES)
        text(source_id, 'state source'); text(epoch_id, 'epoch identity')
        n, p = len(support.column_ids), len(phases)
        thermal = tuple(x for x in phases if x.thermal_material is not None)
        if input_shape(volume_m3) != (n, p) or input_shape(fill_density_kg_m3) != (n,):
            raise TectonicsError('expected (columns, phases) volumes and per-column replacement density')
        if (thermal and (temperature_k is None or input_shape(temperature_k) != (n, len(thermal)))) or (not thermal and temperature_k is not None):
            raise TectonicsError('temperatures must match exactly the thermal phase catalogue')
        with select_budget(budget).reserve(48*n*(p+len(thermal)+3)+8192, category='load-state'):
            v = read_array(volume_m3, 'phase volume', nonnegative=True)
            f = read_array(fill_density_kg_m3, 'replacement density', nonnegative=True)
            if v.shape != (n,p) or f.shape != (n,):
                raise TectonicsError('input shapes changed during capture')
            with np.errstate(over='ignore'):
                occupied = np.sum(v, axis=1)
            capacity = support.area_m2*support.height_m
            # No clipping, silent rescaling, or unbounded negative replacement.
            if not np.isfinite(occupied).all() or np.any(occupied > capacity):
                raise TectonicsError('occupied phase volumes exceed the finite support')
            tb = b''
            if thermal:
                t = read_array(temperature_k, 'phase temperature')
                if t.shape != (n,len(thermal)):
                    raise TectonicsError('temperature shape changed during capture')
                for j, phase in enumerate(thermal):
                    _temperature(t[:,j], phase.thermal_material)
                tb = t.tobytes()
            vb, fb = v.tobytes(), f.tobytes()
            record = dict(method=_METHOD, support=support.support_id, phases=[asdict(x) for x in phases],
                          source=source_id, epoch=epoch_id, thermal='unapplied-fixed-coverage-anomaly')
            _cancel(cancel)
            for name, value in dict(support=support, phases=phases, source_id=source_id,
                    epoch_id=epoch_id, _volumes=vb, _fill=fb, _temperature=tb,
                    state_id=_identity(record, vb, fb, tb)).items():
                object.__setattr__(self, name, value)

    @property
    def volume_m3(self):
        return np.frombuffer(self._volumes, dtype=np.float64).reshape(len(self.support.column_ids), len(self.phases))

    @property
    def fill_density_kg_m3(self):
        return np.frombuffer(self._fill, dtype=np.float64)

    @property
    def temperature_k(self):
        k = sum(p.thermal_material is not None for p in self.phases)
        return np.frombuffer(self._temperature, dtype=np.float64).reshape(len(self.support.column_ids), k)


def _compatible(reference, current, gravity_m_s2, batch_columns):
    if type(reference) is not ColumnLoadState or type(current) is not ColumnLoadState:
        raise TectonicsError('two explicit ColumnLoadState snapshots required')
    if reference.support.support_id != current.support.support_id or reference.phases != current.phases:
        raise TectonicsError('identical support and phase catalogue required; no implicit remapping')
    if type(batch_columns) is not int or not 0 < batch_columns <= _MAX_COLUMNS:
        raise TectonicsError('bounded positive batch_columns required')
    return scalar(gravity_m_s2, 'gravity magnitude', positive=True)


def _add(total, correction, term):
    """Vector Neumaier accumulation: retain small loads between opposing phases."""
    updated = total+term
    correction += np.where(np.abs(total) >= np.abs(term), (total-updated)+term, (term-updated)+total)
    total[:] = updated


def _multiply(left, right):
    result = left*right
    if np.any((result == 0) & (left != 0) & (right != 0)):
        raise TectonicsError('column load product underflows binary64')
    return result


def _divide(left, right):
    result = left/right
    if np.any((result == 0) & (left != 0)):
        raise TectonicsError('column load quotient underflows binary64')
    return result


def column_load_change(reference, current, gravity_m_s2, *, budget=None,
                       cancel=None, batch_columns=32768):
    """Return (N,4): occupied, replacement, thermal kg/m2; total downward Pa.

    A TOTAL change from the supplied reference, not an additive elevation step.
    Thermal kg/m2 is a diagnostic buoyancy sheet, NOT physical inventory mass.
    Material/fill accounts may cancel; total pressure uses density contrasts
    directly, avoiding subtraction of two huge almost equal absolute loads.
    Finite input snapshots are reused without re-copying/hashing per column.
    """
    g = _compatible(reference, current, gravity_m_s2, batch_columns)
    _cancel(cancel)
    n = len(reference.support.column_ids)
    batch = min(n, batch_columns)
    with select_budget(budget).reserve(64*n+384*batch+8192, category='column-load-change'):
        output = np.empty((n,4), dtype=np.float64)
        rv, cv = reference.volume_m3, current.volume_m3
        rf, cf = reference.fill_density_kg_m3, current.fill_density_kg_m3
        rt, ct = reference.temperature_k, current.temperature_k
        area, height = reference.support.area_m2, reference.support.height_m
        try:
            with np.errstate(over='raise', invalid='raise', divide='raise', under='ignore'):
                for start in range(0,n,batch):
                    _cancel(cancel)
                    s = slice(start,min(start+batch,n)); size = len(area[s])
                    sums = np.zeros((4,size)); corrections = np.zeros_like(sums)
                    # The unoccupied reference volume matters if replacement
                    # density changes, even when no geological phase moves.
                    gap = area[s]*height[s]-np.sum(rv[s],axis=1)
                    fill_change = _multiply(_divide(gap,area[s]), cf[s]-rf[s])
                    _add(sums[1],corrections[1],fill_change)
                    _add(sums[3],corrections[3],fill_change)
                    t = 0
                    for j, phase in enumerate(reference.phases):
                        dh = _divide(cv[s,j]-rv[s,j], area[s])
                        _add(sums[0],corrections[0],_multiply(phase.density_kg_m3,dh))
                        _add(sums[1],corrections[1],_multiply(-cf[s],dh))
                        _add(sums[3],corrections[3],_multiply(phase.density_kg_m3-cf[s],dh))
                        material = phase.thermal_material
                        if material is not None:
                            if np.any(rv[s,j] != cv[s,j]):
                                raise TectonicsError('thermal coverage moved; conservative thermal mapping required')
                            delta = ct[s,t]-rt[s,t]
                            if material.expansion_per_k != 0:
                                thermal = _factored_scale(_multiply(-delta,_divide(rv[s,j],area[s])),
                                    (phase.density_kg_m3, material.expansion_per_k), (), 'thermal sheet')
                                _add(sums[2],corrections[2],thermal)
                                _add(sums[3],corrections[3],thermal)
                            t += 1
                    values = sums+corrections
                    output[s,:3] = values[:3].T
                    output[s,3] = _factored_scale(values[3], (g,), (), 'downward load')
        except FloatingPointError as exc:
            raise TectonicsError('column load arithmetic outside finite binary64 range') from exc
        _cancel(cancel)
        if not np.isfinite(output).all():
            raise TectonicsError('nonfinite column load')
        return np.frombuffer(output.tobytes(), dtype=np.float64).reshape(n,4)
